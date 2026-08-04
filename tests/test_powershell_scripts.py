import os
import re
import subprocess
from pathlib import Path


SCRIPTS = Path(__file__).parents[1] / "scripts"


def script(name: str) -> str:
    return (SCRIPTS / name).read_text(encoding="utf-8")


def test_expected_operational_scripts_exist():
    assert {path.name for path in SCRIPTS.glob("*.ps1")} >= {
        "bootstrap.ps1",
        "bootstrap_tls.ps1",
        "install_scheduled_task.ps1",
        "uninstall_scheduled_task.ps1",
        "start.ps1",
        "stop.ps1",
        "status.ps1",
    }


def test_scripts_parse_in_windows_powershell():
    parser = (
        "$tokens = $null; $errors = $null; "
        "[Management.Automation.Language.Parser]::ParseFile("
        "$env:ARCPY_MCP_PARSE_TARGET, [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count) { $errors | ForEach-Object { "
        "[Console]::Error.WriteLine($_.Message) }; exit 1 }"
    )
    for path in SCRIPTS.glob("*.ps1"):
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                parser,
            ],
            env={**os.environ, "ARCPY_MCP_PARSE_TARGET": str(path)},
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"{path.name}: {result.stderr}"


def test_bootstrap_generates_restricted_secrets_without_printing_them():
    content = script("bootstrap.ps1")
    tls = script("bootstrap_tls.ps1")

    assert "RandomNumberGenerator" in content
    assert ".GetBytes(" in content
    assert "::Fill(" not in content
    assert "ARCPY_MCP_BEARER_TOKEN" in content
    assert "ARCPY_MCP_ARTIFACT_SIGNING_KEY" in content
    assert "server.env" in content
    assert "icacls.exe" in content
    assert "bootstrap_tls.ps1" in content
    assert "$tlsArguments = @{" in content
    assert "bootstrap\\Scripts\\python.exe" in content
    assert '& $bootstrapPython "-m" "uv" sync --dev' in content
    assert ".venv\\Scripts\\python.exe" in tls
    assert "Write-Host $bearerToken" not in content
    assert "Write-Output $bearerToken" not in content
    assert "Write-Host $signingKey" not in content
    assert "Write-Output $signingKey" not in content


def test_install_script_limits_firewall_and_registers_current_user_task():
    content = script("install_scheduled_task.ps1")

    assert "ArcPy MCP 8765" in content
    # The scope must be derived, never a literal subnet: a rule pinned to a
    # stale subnet still looks installed while dropping every current client.
    assert "resolve_ipv4_network" in content
    assert "Get-LocalSubnet" in content
    assert "-RemoteAddress $subnet" in content
    assert "Set-NetFirewallRule" in content  # re-scopes instead of leaving stale
    assert "New-NetFirewallRule" in content
    assert "-Profile Private" in content
    assert "ArcPyMCPServer" in content
    assert "New-ScheduledTaskTrigger -AtLogOn" in content
    assert "RestartCount 3" in content
    assert "RestartInterval" in content
    assert "-AllowStartIfOnBatteries" in content
    assert "-DontStopIfGoingOnBatteries" in content
    assert "-LogonType Interactive" in content
    assert "InteractiveToken" not in content
    assert "-WindowStyle Hidden" in content


def test_lifecycle_scripts_use_external_config_and_recorded_pid():
    start = script("start.ps1")
    stop = script("stop.ps1")
    status = script("status.ps1")

    assert "server.env" in start
    assert "SetEnvironmentVariable" in start
    assert "server.pid" in start
    assert "launcher.log" in start
    assert "starting gateway process" in start
    assert "gateway process started" in start
    assert ".venv\\Scripts\\python.exe" in start
    assert "uv.exe" not in start
    assert "-m" in start and "arcpy_mcp_server" in start
    assert "server.pid" in stop
    assert "Stop-Process -Id" in stop
    assert "server.pid" in status
    assert "Get-ScheduledTask" in status
    assert "Get-NetTCPConnection" in status
    assert "/healthz" in status
    assert "--noproxy" in status
    assert "--ssl-no-revoke" in status
    assert "--cacert" in status
    assert "--insecure" not in status


def test_no_script_hardcodes_a_lan_address():
    """A baked-in address is the DHCP-drift bug: TLS breaks when the IP moves."""
    literal = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
    allowed = {"0.0.0.0", "127.0.0.1"}  # bind-any and loopback are not host IPs
    for path in sorted(SCRIPTS.glob("*.ps1")):
        found = set(literal.findall(path.read_text(encoding="utf-8"))) - allowed
        assert not found, f"{path.name} hardcodes {sorted(found)}"
