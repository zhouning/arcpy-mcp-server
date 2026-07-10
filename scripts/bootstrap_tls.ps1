[CmdletBinding()]
param(
    [string]$ServerIp = "192.168.25.228",
    [string]$CertificateDirectory = (Join-Path $env:LOCALAPPDATA "ArcPyMCP\certs"),
    [switch]$Rotate
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$projectPython = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $projectPython)) {
    throw "Missing gateway environment. Run scripts\bootstrap.ps1 first."
}
$arguments = @(
    "-m", "arcpy_mcp_server.tls_bootstrap",
    "--output-dir", $CertificateDirectory,
    "--ip", $ServerIp,
    "--repository-root", $repositoryRoot
)
if ($Rotate) {
    $arguments += "--rotate"
}

Push-Location $repositoryRoot
try {
    & $projectPython @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "TLS certificate generation failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

& icacls.exe $CertificateDirectory /inheritance:r /grant:r "${env:USERNAME}:(OI)(CI)F" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Failed to restrict certificate directory permissions"
}

Write-Output (Join-Path $CertificateDirectory "ca.crt")
