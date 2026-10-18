[CmdletBinding()]
param(
    [switch]$Background,
    # 生产包预览：先构建再用 vite preview 提供静态产物。
    # dev 模式每个模块单独一个请求（约 610 个），首屏 3.8s、切换有 100-300ms 长任务；
    # preview 模式只有一个打包文件，首屏 0.54s、切换无长任务。路演/验收用这个。
    [switch]$Preview,
    # 配合 -Preview：强制重新构建（改了源码后需要）。
    [switch]$Rebuild,
    # 只停掉本项目的 Vite 进程（dev / preview 任一形态），不启动。
    [switch]$Stop
)

$ErrorActionPreference = 'Stop'

$webRoot = (Join-Path $PSScriptRoot '..\apps\web' | Resolve-Path).Path
Set-Location -LiteralPath $webRoot

$node = (Get-Command node.exe -ErrorAction Stop).Source
$vite = Join-Path $webRoot 'node_modules\vite\bin\vite.js'

function Test-ProjectViteOwner($Process, [switch]$WantPreview) {
    if (-not $Process) { return $false }
    if ($Process.CommandLine -notmatch '(?i)vite') { return $false }
    if ($Process.CommandLine -notmatch [regex]::Escape($webRoot)) { return $false }
    if ($Process.CommandLine -notmatch '(?i)--port\s+5173') { return $false }
    $isPreview = $Process.CommandLine -match '(?i)\bpreview\b'
    return ($isPreview -eq [bool]$WantPreview)
}

# -Stop：只停本项目的 Vite 进程，便于在 dev / preview 之间切换。
if ($Stop) {
    $listeners = Get-NetTCPConnection -State Listen -LocalPort 5173 -ErrorAction SilentlyContinue
    if (-not $listeners) { Write-Host 'No listener on 5173.'; return }
    foreach ($pid2 in @($listeners | Select-Object -ExpandProperty OwningProcess -Unique)) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$pid2)"
        if ($proc.CommandLine -match '(?i)vite' -and $proc.CommandLine -match [regex]::Escape($webRoot)) {
            Stop-Process -Id ([int]$pid2) -Force -ErrorAction SilentlyContinue
            Write-Host "Stopped project Vite process $pid2"
        } else {
            throw "Port 5173 is held by a process that is not this project's Vite (PID $pid2); refusing to kill it."
        }
    }
    for ($wait = 0; $wait -lt 20; $wait++) {
        if (-not (Get-NetTCPConnection -State Listen -LocalPort 5173 -ErrorAction SilentlyContinue)) {
            Write-Host 'Port 5173 released.'
            return
        }
        Start-Sleep -Milliseconds 250
    }
    throw 'Port 5173 is still held after stopping the project Vite process.'
}

# 端口占用检查：只接受本项目自己启动的进程，并区分「dev」「preview」两种形态。
$existing = Get-NetTCPConnection -State Listen -LocalPort 5173 -ErrorAction SilentlyContinue
if ($existing) {
    $ownerPids = @($existing | Select-Object -ExpandProperty OwningProcess -Unique)
    if ($ownerPids.Count -ne 1) {
        throw 'Port 5173 has multiple listeners; refusing to start automatically.'
    }
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$ownerPids[0])"
    if (Test-ProjectViteOwner $owner -WantPreview:$Preview) {
        $page = Invoke-WebRequest -Uri 'http://127.0.0.1:5173/' -UseBasicParsing -TimeoutSec 5
        if ($page.StatusCode -ne 200 -or $page.Content -notmatch 'id="root"') {
            throw 'Project Vite process is listening, but the application page is not ready.'
        }
        Write-Host "Frontend already running: http://127.0.0.1:5173 ($(if ($Preview) { 'preview' } else { 'dev' }))"
        return
    }
    throw "Port 5173 is occupied by $(if ($Preview) { 'a dev-mode' } else { 'another' }) process. Stop it first: scripts\start_loreal_frontend.ps1 -Stop"
}

if (-not (Test-Path -LiteralPath $vite -PathType Leaf)) {
    Write-Host 'Installing frontend dependencies...'
    & npm.cmd ci
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
}
if (-not (Test-Path -LiteralPath $vite -PathType Leaf)) {
    throw 'Vite is missing after dependency installation.'
}

if ($Preview) {
    $indexHtml = Join-Path $webRoot 'dist\index.html'
    if ($Rebuild -or -not (Test-Path -LiteralPath $indexHtml -PathType Leaf)) {
        Write-Host 'Building production bundle...'
        & $node $vite build --logLevel warn
        if ($LASTEXITCODE -ne 0) { throw 'Production build failed.' }
        if (-not (Test-Path -LiteralPath $indexHtml -PathType Leaf)) {
            throw 'Production build finished but dist\index.html is missing.'
        }
    } else {
        Write-Host "Using existing production bundle from $((Get-Item $indexHtml).LastWriteTime)"
    }
}

$viteArgs = if ($Preview) {
    @("`"$vite`"", 'preview', '--host', '127.0.0.1', '--port', '5173', '--strictPort')
} else {
    @("`"$vite`"", '--host', '127.0.0.1', '--port', '5173', '--strictPort')
}

if ($Background) {
    $logRoot = [System.IO.Path]::GetFullPath((Join-Path $webRoot '..\..\data\runtime\logs'))
    New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
    $process = Start-Process -FilePath $node -ArgumentList $viteArgs `
        -WorkingDirectory $webRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logRoot 'frontend.stdout.log') `
        -RedirectStandardError (Join-Path $logRoot 'frontend.stderr.log')
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        if ($process.HasExited) {
            throw "Frontend exited. Check $logRoot\frontend.stderr.log"
        }
        $listener = Get-NetTCPConnection -State Listen -LocalPort 5173 -ErrorAction SilentlyContinue
        if ($listener) {
            if (@($listener | Where-Object { $_.OwningProcess -ne $process.Id }).Count) {
                throw 'Port 5173 was claimed by another process during startup.'
            }
            try {
                $page = Invoke-WebRequest -Uri 'http://127.0.0.1:5173/' -UseBasicParsing -TimeoutSec 2
                if ($page.StatusCode -eq 200 -and $page.Content -match 'id="root"') {
                    Write-Host "Frontend running in background: PID $($process.Id)"
                    Write-Host "URL: http://127.0.0.1:5173 ($(if ($Preview) { 'preview / production bundle' } else { 'dev' }))"
                    Write-Host "Logs: $logRoot"
                    return
                }
            } catch {
                # Continue observing this process while Vite initializes.
            }
        }
        Start-Sleep -Milliseconds 500
        $process.Refresh()
    }
    throw "Frontend did not become ready within the startup window. PID $($process.Id); logs: $logRoot"
}

& $node $viteArgs
if ($LASTEXITCODE -ne 0) { throw 'Frontend exited with an error. Check the preceding startup log.' }
