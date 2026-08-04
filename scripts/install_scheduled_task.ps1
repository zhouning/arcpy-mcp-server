[CmdletBinding()]
param([switch]$FirewallOnly)

$ErrorActionPreference = "Stop"
$firewallName = "ArcPy MCP 8765"
$taskName = "ArcPyMCPServer"

function Get-LocalSubnet {
    # Scope the rule to the subnet this host is actually on. A rule pinned to a
    # stale subnet still exists and still looks installed, but silently drops
    # every client on the current network.
    $resolved = & (Join-Path $PSScriptRoot "resolve_ip.ps1")
    if (-not $resolved) {
        throw "Could not determine this host's LAN address"
    }
    $repositoryRoot = Split-Path -Parent $PSScriptRoot
    $projectPython = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
    # Pass the address as argv rather than interpolating it into the source: a
    # here-string loses the quoting, so Python receives a bare dotted number and
    # fails with a SyntaxError instead of a string.
    $program = "import sys;from arcpy_mcp_server.host_address import " +
        "resolve_ipv4_network;print(resolve_ipv4_network(sys.argv[1]))"
    Push-Location $repositoryRoot
    try {
        $subnet = & $projectPython "-c" $program $resolved
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to derive the firewall scope"
        }
    }
    finally {
        Pop-Location
    }
    return $subnet.Trim()
}

function Test-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Install-FirewallRule {
    $subnet = Get-LocalSubnet
    $existing = Get-NetFirewallRule -DisplayName $firewallName -ErrorAction SilentlyContinue
    if ($existing) {
        # Re-point an existing rule instead of leaving it on the old subnet.
        $currentScope = ($existing | Get-NetFirewallAddressFilter).RemoteAddress
        if ($currentScope -ne $subnet) {
            Write-Host "Updating firewall scope from '$currentScope' to '$subnet'."
            $existing | Set-NetFirewallRule -RemoteAddress $subnet | Out-Null
        }
        return
    }
    New-NetFirewallRule `
        -DisplayName $firewallName `
        -Direction Inbound `
        -Action Allow `
        -Protocol TCP `
        -LocalPort 8765 `
        -Profile Private `
        -RemoteAddress $subnet | Out-Null
    Write-Host "Firewall rule allows TCP 8765 from $subnet (Private profile)."
}

if ($FirewallOnly) {
    if (-not (Test-Administrator)) {
        throw "The firewall-only operation requires elevation"
    }
    Install-FirewallRule
    return
}

$firewallRule = Get-NetFirewallRule -DisplayName $firewallName -ErrorAction SilentlyContinue
$firewallScopeIsStale = $false
if ($firewallRule) {
    $currentScope = ($firewallRule | Get-NetFirewallAddressFilter).RemoteAddress
    $firewallScopeIsStale = $currentScope -ne (Get-LocalSubnet)
}
if (-not $firewallRule -or $firewallScopeIsStale) {
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
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
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
