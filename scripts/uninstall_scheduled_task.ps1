[CmdletBinding()]
param(
    [switch]$RemoveFirewall,
    [switch]$RemoveData
)

$ErrorActionPreference = "Stop"
$taskName = "ArcPyMCPServer"
$firewallName = "ArcPy MCP 8765"
$installRoot = Join-Path $env:LOCALAPPDATA "ArcPyMCP"

& (Join-Path $PSScriptRoot "stop.ps1")
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

if ($RemoveFirewall) {
    if (-not ([Security.Principal.WindowsPrincipal]::new(
        [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))) {
        throw "Removing the firewall rule requires an elevated PowerShell"
    }
    Remove-NetFirewallRule -DisplayName $firewallName -ErrorAction SilentlyContinue
}

if ($RemoveData -and (Test-Path -LiteralPath $installRoot)) {
    Remove-Item -LiteralPath $installRoot -Recurse -Force
}

Write-Host "Scheduled task removed. Data was$(if ($RemoveData) { '' } else { ' not' }) removed."
