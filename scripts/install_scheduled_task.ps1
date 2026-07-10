[CmdletBinding()]
param([switch]$FirewallOnly)

$ErrorActionPreference = "Stop"
$firewallName = "ArcPy MCP 8765"
$taskName = "ArcPyMCPServer"

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Install-FirewallRule {
    if (-not (Get-NetFirewallRule -DisplayName $firewallName -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule `
            -DisplayName $firewallName `
            -Direction Inbound `
            -Action Allow `
            -Protocol TCP `
            -LocalPort 8765 `
            -Profile Private `
            -RemoteAddress "192.168.25.0/24" | Out-Null
    }
}

if ($FirewallOnly) {
    if (-not (Test-Administrator)) {
        throw "The firewall-only operation requires elevation"
    }
    Install-FirewallRule
    return
}

if (-not (Get-NetFirewallRule -DisplayName $firewallName -ErrorAction SilentlyContinue)) {
    if (Test-Administrator) {
        Install-FirewallRule
    }
    else {
        $argumentList = @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", "`"$PSCommandPath`"",
            "-FirewallOnly"
        )
        $process = Start-Process `
            -FilePath "powershell.exe" `
            -Verb RunAs `
            -WindowStyle Hidden `
            -ArgumentList $argumentList `
            -Wait `
            -PassThru
        if ($process.ExitCode -ne 0) {
            throw "Elevated firewall installation failed"
        }
    }
}

$currentUser = "${env:USERDOMAIN}\${env:USERNAME}"
$startScript = Join-Path $PSScriptRoot "start.ps1"
$actionArguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$startScript`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $actionArguments
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
$principal = New-ScheduledTaskPrincipal `
    -UserId $currentUser `
    -LogonType Interactive `
    -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Force | Out-Null

Write-Host "Scheduled task '$taskName' is installed for $currentUser."
