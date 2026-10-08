[CmdletBinding()]
param([switch]$Background, [switch]$Restart)

$ErrorActionPreference = 'Stop'

$apiRoot = (Join-Path $PSScriptRoot '..\services\api' | Resolve-Path).Path
Set-Location -LiteralPath $apiRoot
# Avoid user-site .pth files from leaking into this Chinese-path virtualenv.
$env:PYTHONNOUSERSITE = '1'

function Test-ProjectBackend($Process) {
    if (-not $Process -or $Process.CommandLine -notmatch '(?i)uvicorn\s+app\.main:app' `
        -or $Process.CommandLine -notmatch '(?i)--port\s+8000') {
        return $false
    }
    # Windows virtualenv Python can spawn its base interpreter as a child process.
    $pythonPath = Join-Path $apiRoot '.venv\Scripts\python.exe'
    $current = $Process
    for ($depth = 0; $depth -lt 4 -and $current; $depth++) {
        if ([string]$current.ExecutablePath -eq $pythonPath `
            -or [string]$current.CommandLine -match [regex]::Escape($pythonPath)) {
            return $true
        }
        $current = Get-CimInstance Win32_Process -Filter "ProcessId=$($current.ParentProcessId)"
    }
    return $false
}

$existing = Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue
if ($existing) {
    $ownerPids = @($existing | Select-Object -ExpandProperty OwningProcess -Unique)
    if ($ownerPids.Count -ne 1) {
        throw 'Port 8000 has multiple listeners; refusing to restart automatically.'
    }
    $ownerPid = [int]$ownerPids[0]
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$ownerPid"
    if (-not (Test-ProjectBackend $owner)) {
        throw 'Port 8000 belongs to an unverified process. No process was stopped.'
    }
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 3
        if ($health.runMode -eq 'live' -and $health.database.state -eq 'ready') {
            if (-not $Restart) {
                Write-Host 'Backend already running: http://127.0.0.1:8000'
                Write-Host 'Use -Restart to reload the current Python source.'
                return
            }
            $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$ownerPid"
            if (-not (Test-ProjectBackend $owner)) {
                throw 'Port 8000 is live, but the owner is not the verified project Uvicorn process; refusing to restart.'
            }
            Write-Host "Restarting verified project backend PID $ownerPid..."
            Stop-Process -Id $ownerPid
            for ($attempt = 0; $attempt -lt 30; $attempt++) {
                if (-not (Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue)) {
                    break
                }
                Start-Sleep -Milliseconds 250
            }
            if (Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue) {
                throw 'The previous project backend did not release port 8000.'
            }
        }
    } catch {
        if ($_.Exception.Message -like '*refusing to restart*' -or $_.Exception.Message -like '*did not release*') {
            throw
        }
        throw 'Port 8000 is occupied by a process that is not the live project backend.'
    }
    if (Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue) {
        throw 'Port 8000 is occupied, but the project backend is not healthy and live.'
    }
}

# Always use a non-editable install in this Chinese-path workspace.
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw 'uv is not installed or not on PATH. Install uv before starting the backend.'
}
uv sync --extra dev --no-editable
if ($LASTEXITCODE -ne 0) {
    throw 'Dependency synchronization failed. Backend was not started.'
}
$editablePth = Get-ChildItem -LiteralPath (Join-Path $apiRoot '.venv\Lib\site-packages') `
    -Filter '*.pth' -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '(?i)editable' }
if ($editablePth) {
    $names = ($editablePth | Select-Object -ExpandProperty Name) -join ', '
    throw "Editable .pth remains in the virtualenv ($names). Backend was not started; rerun uv sync --extra dev --no-editable."
}
if ($Background) {
    $logRoot = [System.IO.Path]::GetFullPath((Join-Path $apiRoot '..\..\data\runtime\logs'))
    New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
    $process = Start-Process -FilePath (Join-Path $apiRoot '.venv\Scripts\python.exe') `
        -ArgumentList @('-u', '-X', 'utf8', '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000') `
        -WorkingDirectory $apiRoot -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logRoot 'backend.stdout.log') `
        -RedirectStandardError (Join-Path $logRoot 'backend.stderr.log')
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        if ($process.HasExited) {
            throw "Backend exited. Check $logRoot\backend.stderr.log"
        }
        try {
            $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 2
            if ($health.runMode -eq 'live' -and $health.database.state -eq 'ready') {
                Write-Host "Backend running in background: PID $($process.Id)"
                Write-Host "Logs: $logRoot"
                return
            }
        } catch {
            # Startup has not finished; keep observing this process.
        }
        Start-Sleep -Milliseconds 500
        $process.Refresh()
    }
    throw "Backend did not become ready within the startup window. PID $($process.Id); logs: $logRoot"
}
& .\.venv\Scripts\python.exe -X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
if ($LASTEXITCODE -ne 0) {
    throw 'Backend exited with an error. Check the preceding startup log.'
}
