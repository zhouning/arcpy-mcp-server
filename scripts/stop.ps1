[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$pidFile = Join-Path $env:LOCALAPPDATA "ArcPyMCP\server.pid"
if (-not (Test-Path -LiteralPath $pidFile)) {
    Write-Host "ArcPy MCP is not running (no PID file)."
    return
}

$recordedPid = [int](Get-Content -Raw -LiteralPath $pidFile)
$process = Get-Process -Id $recordedPid -ErrorAction SilentlyContinue
if ($process) {
    Stop-Process -Id $recordedPid -Force
    $process.WaitForExit(10000) | Out-Null
}
Remove-Item -LiteralPath $pidFile -Force
Write-Host "ArcPy MCP stopped."
