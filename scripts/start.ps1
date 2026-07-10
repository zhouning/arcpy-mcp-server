[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$installRoot = Join-Path $env:LOCALAPPDATA "ArcPyMCP"
$environmentFile = Join-Path $installRoot "config\server.env"
$pidFile = Join-Path $installRoot "server.pid"
$logDirectory = Join-Path $installRoot "logs"
$projectPython = Join-Path $repositoryRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $environmentFile)) {
    throw "Missing $environmentFile. Run scripts\bootstrap.ps1 first."
}
if (-not (Test-Path -LiteralPath $projectPython)) {
    throw "Missing gateway environment. Run scripts\bootstrap.ps1 first."
}

if (Test-Path -LiteralPath $pidFile) {
    $recordedPid = [int](Get-Content -Raw -LiteralPath $pidFile)
    if (Get-Process -Id $recordedPid -ErrorAction SilentlyContinue) {
        Write-Host "ArcPy MCP is already running as PID $recordedPid."
        return
    }
    Remove-Item -LiteralPath $pidFile -Force
}

foreach ($line in Get-Content -LiteralPath $environmentFile) {
    if ([string]::IsNullOrWhiteSpace($line) -or $line.StartsWith("#")) {
        continue
    }
    $parts = $line.Split("=", 2)
    if ($parts.Count -ne 2) {
        throw "Invalid environment entry in $environmentFile"
    }
    [Environment]::SetEnvironmentVariable($parts[0], $parts[1], "Process")
}

New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$stdoutLog = Join-Path $logDirectory "server.stdout.log"
$stderrLog = Join-Path $logDirectory "server.stderr.log"
$process = Start-Process `
    -FilePath $projectPython `
    -ArgumentList @("-m", "arcpy_mcp_server") `
    -WorkingDirectory $repositoryRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru
[IO.File]::WriteAllText($pidFile, [string]$process.Id)
Write-Host "ArcPy MCP started as PID $($process.Id)."
