[CmdletBinding()]
param()

# 演练前把演示库恢复到快照状态。只操作 demo.sqlite3 与 demo-qdrant，不碰主运行库。
$ErrorActionPreference = 'Stop'

$runtime = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\data\runtime'))
$snapshot = Join-Path $runtime 'demo-snapshot.sqlite3'
$snapshotQdrant = Join-Path $runtime 'demo-snapshot-qdrant'
$target = Join-Path $runtime 'demo.sqlite3'
$targetQdrant = Join-Path $runtime 'demo-qdrant'

if (-not (Test-Path -LiteralPath $snapshot -PathType Leaf)) {
    throw 'demo-snapshot.sqlite3 is missing. Run scripts\build_demo_database.py first.'
}
if (Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue) {
    throw 'Port 8000 is in use. Stop the backend before resetting the demo database.'
}
foreach ($suffix in @('', '-wal', '-shm')) {
    $path = "$target$suffix"
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Force
    }
}
Copy-Item -LiteralPath $snapshot -Destination $target
if (Test-Path -LiteralPath $targetQdrant) {
    Remove-Item -LiteralPath $targetQdrant -Recurse -Force
}
if (Test-Path -LiteralPath $snapshotQdrant) {
    Copy-Item -LiteralPath $snapshotQdrant -Destination $targetQdrant -Recurse
} else {
    Write-Warning 'Snapshot has no knowledge index (built with --skip-knowledge); retrieval will be unavailable.'
}
Write-Host "Demo database restored: $target"
