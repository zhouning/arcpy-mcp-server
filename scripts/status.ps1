[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"
$taskName = "ArcPyMCPServer"
$installRoot = Join-Path $env:LOCALAPPDATA "ArcPyMCP"
$pidFile = Join-Path $installRoot "server.pid"
$caCertificate = Join-Path $installRoot "certs\ca.crt"
$environmentFile = Join-Path $installRoot "config\server.env"

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
    # Health-check the address recorded at bootstrap, then compare it with the
    # address this host has now: a mismatch is the DHCP-drift failure, where the
    # service is up but its certificate no longer matches what clients dial.
    $configuredUrl = $null
    if (Test-Path -LiteralPath $environmentFile) {
        $configuredLine = Select-String `
            -LiteralPath $environmentFile `
            -Pattern "^ARCPY_MCP_PUBLIC_BASE_URL=(.+)$" `
            -ErrorAction SilentlyContinue
        if ($configuredLine) {
            $configuredUrl = $configuredLine.Matches[0].Groups[1].Value.Trim()
        }
    }
    if (-not $configuredUrl) {
        Write-Host "HTTPS health: no publishing address recorded; run bootstrap.ps1"
    }
    else {
        Write-Host "Configured address: $configuredUrl"
        $health = & curl.exe `
            --noproxy "*" `
            --silent `
            --show-error `
            --max-time 5 `
            --ssl-no-revoke `
            --cacert $caCertificate `
            "$configuredUrl/healthz" 2>&1
        Write-Host "HTTPS health: $health"

        $currentIp = & (Join-Path $PSScriptRoot "resolve_ip.ps1")
        if ($currentIp) {
            $configuredHost = ([Uri]$configuredUrl).Host
            if ($configuredHost -ne $currentIp) {
                Write-Warning (
                    "Address drift: certificate and configuration name " +
                    "$configuredHost but this host is now at $currentIp. " +
                    "Run scripts\bootstrap.ps1 to reissue, then " +
                    "scripts\install_scheduled_task.ps1 to re-scope the " +
                    "firewall, then re-import ca.crt on the client."
                )
            }
        }
    }
}
else {
    Write-Host "HTTPS health: CA certificate is missing"
}
