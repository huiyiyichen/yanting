# 端到端测试运行脚本（完全隔离的库与后端）
#
# 为什么需要：e2e 会真实落库且不清理数据。反复运行后会话累积到数百条，
# 列表渲染变慢会让「定位目标会话」这类断言超时，测试结果因此依赖历史数据
# （详见 开发进度.md 第 6.2 节）。本脚本用独立的 SQLite、独立的运行目录和
# 独立的后端端口跑 e2e，开发库 data/runtime 完全不受影响。
#
# 做法：vite 的 /api 代理目标由 ANKER_AGENT_API_TARGET 控制，因此这里临时
# 用指向隔离后端（默认 8001）的 vite 实例替换 5173 上的开发前端；因为浏览器
# 页面与 page.request 都走同源 /api，隔离后端即可覆盖全部请求。结束后恢复。
#
# 进程模型：两个服务用 PowerShell 后台作业（Start-Job）承载，脚本退出时
# 一并停止；不使用 Start-Process，避免遗留脱离父进程的孤儿服务。
#
# 用法（任意目录）：
#   pwsh -File scripts/run_e2e.ps1
#   pwsh -File scripts/run_e2e.ps1 -Project desktop-1440x900
#   pwsh -File scripts/run_e2e.ps1 -Grep "托管"
#   pwsh -File scripts/run_e2e.ps1 -KeepFrontend   # 结束后不恢复开发前端

param(
  [int]$ApiPort = 8001,
  [int]$WebPort = 5173,
  [int]$DevApiPort = 8000,
  [string]$Project = "",
  [string]$Grep = "",
  [switch]$KeepFrontend
)

$ErrorActionPreference = "Stop"

$codeRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$apiDir = Join-Path $codeRoot "services\api"
$webDir = Join-Path $codeRoot "apps\web"
$python = Join-Path $apiDir ".venv\Scripts\python.exe"
$backendLog = Join-Path $env:TEMP "anker-e2e-backend.log"
$frontendLog = Join-Path $env:TEMP "anker-e2e-frontend.log"

foreach ($path in @($python, $webDir)) {
  if (-not (Test-Path $path)) { throw "缺少必需路径：$path" }
}

function Stop-PortListener([int]$Port) {
  $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  if ($conn) {
    Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 700
  }
}

function Wait-Http([string]$Url, [int]$Attempts) {
  for ($i = 0; $i -lt $Attempts; $i++) {
    Start-Sleep -Milliseconds 500
    try {
      $r = Invoke-WebRequest -Uri $Url -TimeoutSec 3 -UseBasicParsing
      if ($r.StatusCode -eq 200) { return $true }
    } catch { }
  }
  return $false
}

# ── 隔离数据 ────────────────────────────────────────────────────────────────
$e2eDbRelative = "data/runtime-e2e/e2e.sqlite3"
$e2eRuntimeDir = Join-Path $codeRoot "data\runtime-e2e"
New-Item -ItemType Directory -Force -Path $e2eRuntimeDir | Out-Null

# 每次运行都用干净库：e2e 数据没有保留价值，隔离才能保证可复现
$dbFile = Join-Path $e2eRuntimeDir "e2e.sqlite3"
foreach ($suffix in @("", "-wal", "-shm")) {
  $f = "$dbFile$suffix"
  if (Test-Path $f) { Remove-Item $f -Force -ErrorAction SilentlyContinue }
}

# 索引必须**复制**而非共用：Qdrant 本地模式对存储目录加进程级文件锁，
# 两个后端同时打开同一路径会失败。复制已发布快照，e2e 只读使用。
$srcQdrant = Join-Path $codeRoot "data\runtime\qdrant"
$dstQdrant = Join-Path $e2eRuntimeDir "qdrant"
if (-not (Test-Path $srcQdrant)) { throw "缺少知识索引：$srcQdrant（请先运行 scripts/ingest_knowledge.py）" }
if (Test-Path $dstQdrant) { Remove-Item $dstQdrant -Recurse -Force -ErrorAction SilentlyContinue }
Copy-Item $srcQdrant $dstQdrant -Recurse -Force

# 知识索引还有一半在**库里**：knowledge_snapshot / knowledge_document /
# knowledge_chunk 等元数据表。只复制 Qdrant 目录时，隔离库没有 active 快照，
# `get_active_snapshot()` 返回 None，检索直接判 not_found（索引根本没被打开）。
# 因此这里必须同时把这几张表播种到隔离库。
$seedScript = Join-Path $codeRoot "scripts\seed_isolated_knowledge.py"
$e2eDbPath = Join-Path $e2eRuntimeDir "e2e.sqlite3"
Write-Host "[e2e] 播种知识元数据 -> $e2eDbRelative"
& $python $seedScript --target-db $e2eDbPath --create-schema
if ($LASTEXITCODE -ne 0) { throw "知识元数据播种失败（退出码 $LASTEXITCODE）" }

Stop-PortListener $ApiPort
Stop-PortListener $WebPort

$backendJob = $null
$frontendJob = $null
$env:ANKER_AGENT_WEB_BASE = "http://127.0.0.1:$WebPort"

try {
  Write-Host "[e2e] 启动隔离后端 127.0.0.1:$ApiPort（库：$e2eDbRelative）"
  $backendJob = Start-Job -ScriptBlock {
    param($Dir, $Python, $Port, $DbUrl, $RuntimeDir, $QdrantPath)
    Set-Location $Dir
    $env:PYTHONIOENCODING = "utf-8"
    $env:ANKER_AGENT_DATABASE_URL = $DbUrl
    $env:ANKER_AGENT_RUNTIME_DIR = $RuntimeDir
    $env:ANKER_AGENT_QDRANT_PATH = $QdrantPath
    & $Python -m uvicorn app.main:app --host 127.0.0.1 --port $Port 2>&1
  } -ArgumentList $apiDir, $python, $ApiPort, "sqlite+pysqlite:///$e2eDbRelative", "data/runtime-e2e", "data/runtime-e2e/qdrant"

  if (-not (Wait-Http "http://127.0.0.1:$ApiPort/api/health" 40)) {
    Write-Host "[e2e] 后端启动失败，作业输出尾部："
    Receive-Job $backendJob -Keep | Select-Object -Last 30
    throw "隔离后端未在 20 秒内就绪"
  }
  Write-Host "[e2e] 隔离后端就绪"

  Write-Host "[e2e] 启动指向隔离后端的 vite（:$WebPort -> :$ApiPort）"
  $frontendJob = Start-Job -ScriptBlock {
    param($Dir, $Port, $Target)
    Set-Location $Dir
    $env:ANKER_AGENT_API_TARGET = $Target
    & npx vite --host 127.0.0.1 --port $Port 2>&1
  } -ArgumentList $webDir, $WebPort, "http://127.0.0.1:$ApiPort"

  if (-not (Wait-Http "http://127.0.0.1:$WebPort" 60)) {
    Write-Host "[e2e] 前端启动失败，作业输出尾部："
    Receive-Job $frontendJob -Keep | Select-Object -Last 30
    throw "隔离前端未在 30 秒内就绪"
  }
  Write-Host "[e2e] 隔离前端就绪"

  $playwrightArgs = @("playwright", "test", "--reporter=list")
  if ($Project) { $playwrightArgs += "--project=$Project" }
  if ($Grep) { $playwrightArgs += "-g", $Grep }

  Write-Host "[e2e] 运行：npx $($playwrightArgs -join ' ')"
  Push-Location $webDir
  try {
    & npx @playwrightArgs
    $code = $LASTEXITCODE
  } finally {
    Pop-Location
  }
  Write-Host "[e2e] playwright 退出码：$code"
} finally {
  foreach ($job in @($frontendJob, $backendJob)) {
    if ($job) {
      Stop-Job $job -ErrorAction SilentlyContinue
      Remove-Job $job -Force -ErrorAction SilentlyContinue
    }
  }
  Stop-PortListener $WebPort
  Stop-PortListener $ApiPort
  Write-Host "[e2e] 已停止隔离后端与隔离前端"

  if (-not $KeepFrontend) {
    $devApi = Get-NetTCPConnection -LocalPort $DevApiPort -State Listen -ErrorAction SilentlyContinue
    if ($devApi) {
      Write-Host "[e2e] 测试结束，开发前端已停止。请重新运行 npm run dev 恢复 http://127.0.0.1:$WebPort"
    } else {
      Write-Host "[e2e] 开发后端 :$DevApiPort 未运行，跳过前端恢复"
    }
  }
}
