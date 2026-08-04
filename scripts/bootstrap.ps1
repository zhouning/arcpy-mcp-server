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

# Resolve once and reuse for the env file, the certificate SAN and the
# firewall scope, so the three cannot disagree.
$serverIp = & (Join-Path $PSScriptRoot "resolve_ip.ps1")
if (-not $serverIp) {
    throw "Could not determine this host's LAN address"
}
$publicBaseUrl = "https://${serverIp}:8765"
Write-Host "Publishing address: $publicBaseUrl"

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
        "ARCPY_MCP_PUBLIC_BASE_URL=$publicBaseUrl",
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
else {
    # The env file already exists, so it still carries the address from the last
    # bootstrap. Rewrite just that line -- rewriting the file wholesale would
    # discard the Bearer token and signing key, invalidating every client and
    # every already-issued artifact URL.
    $existing = [IO.File]::ReadAllLines($environmentFile)
    $updated = $false
    $rewritten = foreach ($line in $existing) {
        if ($line -like "ARCPY_MCP_PUBLIC_BASE_URL=*") {
            if ($line -ne "ARCPY_MCP_PUBLIC_BASE_URL=$publicBaseUrl") {
                $updated = $true
                Write-Host "Address changed; was '$($line.Split('=', 2)[1])'."
            }
            "ARCPY_MCP_PUBLIC_BASE_URL=$publicBaseUrl"
        }
        else {
            $line
        }
    }
    if ($updated) {
        [IO.File]::WriteAllLines(
            $environmentFile,
            $rewritten,
            [Text.UTF8Encoding]::new($false)
        )
        # The old certificate's SAN names the previous address, so clients would
        # reject it. Reissue and tell the operator to re-import the CA.
        $RotateCertificates = $true
        Write-Host "Certificates will be reissued for the new address."
    }
}

& icacls.exe $configDirectory /inheritance:r /grant:r "${env:USERNAME}:(OI)(CI)F" | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Failed to restrict configuration directory permissions"
}

$tlsArguments = @{
    ServerIp = $serverIp
    CertificateDirectory = $certificateDirectory
}
if ($RotateCertificates) {
    $tlsArguments.Rotate = $true
}
& (Join-Path $PSScriptRoot "bootstrap_tls.ps1") @tlsArguments | Out-Null

Write-Host "Bootstrap complete. Gateway address: $publicBaseUrl"
Write-Host "Import this CA certificate on the client:"
Write-Host (Join-Path $certificateDirectory "ca.crt")
