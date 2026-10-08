[CmdletBinding()]
param([switch]$OpenBrowser)

$ErrorActionPreference = 'Stop'

$originalLocation = Get-Location
$logRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\data\runtime\logs'))
try {
    Write-Host "Starting L'Oreal service demo..."
    & (Join-Path $PSScriptRoot 'start_loreal_backend.ps1') -Background
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
