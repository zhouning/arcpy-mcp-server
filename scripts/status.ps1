[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"
$taskName = "ArcPyMCPServer"
$installRoot = Join-Path $env:LOCALAPPDATA "ArcPyMCP"
$pidFile = Join-Path $installRoot "server.pid"
$caCertificate = Join-Path $installRoot "certs\ca.crt"

$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
    Write-Host "Scheduled task: $($task.State)"
}
else {
    Write-Host "Scheduled task: not installed"
}

if (Test-Path -LiteralPath $pidFile) {
    $recordedPid = [int](Get-Content -Raw -LiteralPath $pidFile)
    $process = Get-Process -Id $recordedPid -ErrorAction SilentlyContinue
    $processState = if ($process) { "running" } else { "not running" }
    Write-Host "PID: $recordedPid ($processState)"
}
else {
    Write-Host "PID: not recorded"
}

$listener = Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue
Write-Host "TCP 8765: $(if ($listener) { 'listening' } else { 'not listening' })"

if (Test-Path -LiteralPath $caCertificate) {
    $health = & curl.exe `
        --noproxy "*" `
        --silent `
        --show-error `
        --max-time 5 `
        --ssl-no-revoke `
        --cacert $caCertificate `
        "https://192.168.25.228:8765/healthz" 2>&1
    Write-Host "HTTPS health: $health"
}
else {
    Write-Host "HTTPS health: CA certificate is missing"
}
