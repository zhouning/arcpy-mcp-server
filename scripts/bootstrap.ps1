[CmdletBinding()]
param(
    [switch]$RotateSecrets,
    [switch]$RotateCertificates
)

$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$installRoot = Join-Path $env:LOCALAPPDATA "ArcPyMCP"
$configDirectory = Join-Path $installRoot "config"
$certificateDirectory = Join-Path $installRoot "certs"
$dataDirectory = Join-Path $installRoot "data"
$logDirectory = Join-Path $installRoot "logs"
$environmentFile = Join-Path $configDirectory "server.env"
$bootstrapPython = Join-Path $installRoot "bootstrap\Scripts\python.exe"
$projectPython = Join-Path $repositoryRoot ".venv\Scripts\python.exe"

function Invoke-UvSync {
    $uvCommand = Get-Command uv.exe -ErrorAction SilentlyContinue
    if ($uvCommand) {
        & $uvCommand.Source sync --dev
    }
    else {
        if (-not (Test-Path -LiteralPath $bootstrapPython)) {
            $systemPython = Get-Command python.exe -ErrorAction SilentlyContinue
            if (-not $systemPython) {
                throw "Python is required to bootstrap uv"
            }
            & $systemPython.Source -m venv (Split-Path -Parent (Split-Path -Parent $bootstrapPython))
            if ($LASTEXITCODE -ne 0) {
                throw "Failed to create the isolated uv bootstrap environment"
            }
        }
        & $bootstrapPython -m pip install --disable-pip-version-check "uv>=0.8,<1"
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to install uv into the bootstrap environment"
        }
        & $bootstrapPython "-m" "uv" sync --dev
    }
    if ($LASTEXITCODE -ne 0) {
        throw "uv sync failed with exit code $LASTEXITCODE"
    }
}

Push-Location $repositoryRoot
try {
    Invoke-UvSync
}
finally {
    Pop-Location
}
if (-not (Test-Path -LiteralPath $projectPython)) {
    throw "Gateway environment was not created at $projectPython"
}

@($configDirectory, $certificateDirectory, $dataDirectory, $logDirectory) |
    ForEach-Object { New-Item -ItemType Directory -Force -Path $_ | Out-Null }

if (-not (Test-Path -LiteralPath $environmentFile) -or $RotateSecrets) {
    $tokenBytes = [byte[]]::new(48)
    $signingBytes = [byte[]]::new(48)
    $random = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $random.GetBytes($tokenBytes)
        $random.GetBytes($signingBytes)
    }
    finally {
        $random.Dispose()
    }
    $bearerToken = [Convert]::ToBase64String($tokenBytes)
    $signingKey = [Convert]::ToBase64String($signingBytes)
    $lines = @(
        "ARCPY_MCP_PUBLIC_BASE_URL=https://192.168.25.228:8765",
        "ARCPY_MCP_BIND_HOST=0.0.0.0",
        "ARCPY_MCP_BIND_PORT=8765",
        "ARCPY_MCP_ARCPY_PYTHON=D:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe",
        "ARCPY_MCP_DATA_ROOT=$dataDirectory",
        "ARCPY_MCP_TLS_CERT=$(Join-Path $certificateDirectory 'server.crt')",
        "ARCPY_MCP_TLS_KEY=$(Join-Path $certificateDirectory 'server.key')",
        "ARCPY_MCP_BEARER_TOKEN=$bearerToken",
        "ARCPY_MCP_ARTIFACT_SIGNING_KEY=$signingKey",
        "ARCPY_MCP_RETENTION_DAYS=7"
    )
    [IO.File]::WriteAllLines(
        $environmentFile,
        $lines,
        [Text.UTF8Encoding]::new($false)
    )
}

& icacls.exe $configDirectory /inheritance:r /grant:r "${env:USERNAME}:(OI)(CI)F" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Failed to restrict configuration directory permissions"
}

$tlsArguments = @{
    ServerIp = "192.168.25.228"
    CertificateDirectory = $certificateDirectory
}
if ($RotateCertificates) {
    $tlsArguments.Rotate = $true
}
& (Join-Path $PSScriptRoot "bootstrap_tls.ps1") @tlsArguments | Out-Null

Write-Host "Bootstrap complete. Import this CA certificate on the macOS client:"
Write-Host (Join-Path $certificateDirectory "ca.crt")
