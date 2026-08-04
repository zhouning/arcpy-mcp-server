[CmdletBinding()]
param()

# Single source of truth for "which address does this host publish".
# Every script that needs the address calls here, so the certificate SAN, the
# public base URL and the firewall scope cannot drift apart.

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$projectPython = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $projectPython)) {
    throw "Missing gateway environment. Run scripts\bootstrap.ps1 first."
}

$program = "from arcpy_mcp_server.host_address import resolve_server_ip;" +
    "print(resolve_server_ip())"

Push-Location $repositoryRoot
try {
    $resolved = & $projectPython "-c" $program
    if ($LASTEXITCODE -ne 0) {
        throw "Address resolution failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}

Write-Output $resolved.Trim()
