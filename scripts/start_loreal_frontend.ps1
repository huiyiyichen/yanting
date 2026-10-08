[CmdletBinding()]
param([switch]$Background)

$ErrorActionPreference = 'Stop'

$webRoot = (Join-Path $PSScriptRoot '..\apps\web' | Resolve-Path).Path
Set-Location -LiteralPath $webRoot

$existing = Get-NetTCPConnection -State Listen -LocalPort 5173 -ErrorAction SilentlyContinue
if ($existing) {
    $ownerPids = @($existing | Select-Object -ExpandProperty OwningProcess -Unique)
    if ($ownerPids.Count -ne 1) {
        throw 'Port 5173 has multiple listeners; refusing to start automatically.'
    }
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$([int]$ownerPids[0])"
    if ($owner.CommandLine -match '(?i)vite' `
        -and $owner.CommandLine -match [regex]::Escape($webRoot) `
        -and $owner.CommandLine -match '(?i)--port\s+5173') {
        $page = Invoke-WebRequest -Uri 'http://127.0.0.1:5173/' -UseBasicParsing -TimeoutSec 5
        if ($page.StatusCode -ne 200 -or $page.Content -notmatch 'id="root"') {
            throw 'Project Vite process is listening, but the application page is not ready.'
        }
        Write-Host 'Frontend already running: http://127.0.0.1:5173'
        return
    }
    throw 'Port 5173 is occupied by a process that is not the verified project Vite process.'
}

$node = (Get-Command node.exe -ErrorAction Stop).Source
$vite = Join-Path $webRoot 'node_modules\vite\bin\vite.js'
if (-not (Test-Path -LiteralPath $vite -PathType Leaf)) {
    Write-Host 'Installing frontend dependencies...'
    & npm.cmd ci
    if ($LASTEXITCODE -ne 0) {
        throw 'Frontend dependency installation failed.'
    }
}
if (-not (Test-Path -LiteralPath $vite -PathType Leaf)) {
    throw 'Vite is missing after dependency installation.'
}
if ($Background) {
    $logRoot = [System.IO.Path]::GetFullPath((Join-Path $webRoot '..\..\data\runtime\logs'))
    New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
    $process = Start-Process -FilePath $node `
        -ArgumentList @("`"$vite`"", '--host', '127.0.0.1', '--port', '5173', '--strictPort') `
        -WorkingDirectory $webRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logRoot 'frontend.stdout.log') `
        -RedirectStandardError (Join-Path $logRoot 'frontend.stderr.log')
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
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
                    Write-Host "URL: http://127.0.0.1:5173"
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

& $node $vite --host 127.0.0.1 --port 5173 --strictPort
if ($LASTEXITCODE -ne 0) {
    throw 'Frontend exited with an error. Check the preceding startup log.'
}
