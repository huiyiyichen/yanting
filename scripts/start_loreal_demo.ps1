[CmdletBinding()]
param(
    [switch]$OpenBrowser,
    # demo：路演用 data/runtime/demo.sqlite3（由 build_demo_database.py + reset_demo.ps1 准备）
    # dev：日常开发用默认运行库
    [ValidateSet('demo', 'dev')][string]$Profile = 'dev',
    [switch]$Restart
)

$ErrorActionPreference = 'Stop'

$originalLocation = Get-Location
$logRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\data\runtime\logs'))
try {
    Write-Host "Starting Yanting ($Profile profile)..."
    if ($Profile -eq 'demo') {
        $demoDb = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\data\runtime\demo.sqlite3'))
        if (-not (Test-Path -LiteralPath $demoDb -PathType Leaf)) {
            throw 'demo.sqlite3 is missing. Run scripts\build_demo_database.py, then scripts\reset_demo.ps1.'
        }
        $env:ANKER_AGENT_DATABASE_URL = 'sqlite+pysqlite:///data/runtime/demo.sqlite3'
        $env:ANKER_AGENT_QDRANT_PATH = 'data/runtime/demo-qdrant'
        $storylines = Get-Content -Raw -Encoding UTF8 (Join-Path $PSScriptRoot '..\data\demo\storylines.json') | ConvertFrom-Json
        $env:VITE_DEMO_CUSTOMER_ID = $storylines.customerViewId
    }
    if ($Restart) {
        & (Join-Path $PSScriptRoot 'start_loreal_backend.ps1') -Background -Restart
    } else {
        & (Join-Path $PSScriptRoot 'start_loreal_backend.ps1') -Background
    }
    & (Join-Path $PSScriptRoot 'start_loreal_frontend.ps1') -Background

    $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 5
    if ($health.runMode -ne 'live' -or $health.database.state -ne 'ready') {
        throw 'Backend is not ready in live mode.'
    }
    $page = Invoke-WebRequest -Uri 'http://127.0.0.1:5173/support' -UseBasicParsing -TimeoutSec 5
    if ($page.StatusCode -ne 200 -or $page.Content -notmatch 'id="root"') {
        throw 'Frontend did not return the application page.'
    }
    $proxiedHealth = Invoke-RestMethod -Uri 'http://127.0.0.1:5173/api/health' -TimeoutSec 5
    if ($proxiedHealth.runMode -ne 'live' -or $proxiedHealth.database.state -ne 'ready') {
        throw 'Frontend cannot reach the backend through its API proxy.'
    }
    Write-Host 'Demo ready:'
    Write-Host '  Support: http://127.0.0.1:5173/support'
    Write-Host '  Customer: http://127.0.0.1:5173/customer'
    Write-Host '  Risk:    http://127.0.0.1:5173/risk'
    Write-Host "  Logs:    $logRoot"
    if ($health.status -ne 'ok') {
        Write-Warning 'The application is running, but some AI capabilities are unavailable. Check model configuration.'
    }
    if ($OpenBrowser) {
        Start-Process -FilePath 'http://127.0.0.1:5173/support'
    }
} catch {
    Write-Host "Startup failed: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Logs: $logRoot"
    exit 1
} finally {
    Set-Location -LiteralPath $originalLocation.Path
}
