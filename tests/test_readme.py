import re
from pathlib import Path


README = Path(__file__).parents[1] / "README.md"


def test_readme_covers_secure_operations_and_limitations():
    content = README.read_text(encoding="utf-8")

    for expected in (
        "ArcGIS Pro 3.7.1",
        "ARCPY_MCP_SERVER_IP",
        "8765",
        "bootstrap.ps1",
        "install_scheduled_task.ps1",
        "ARCPY_MCP_BEARER_TOKEN",
        "ca.crt",
        "server.stdout.log",
        "state.db",
        "7 days",
        "CPU",
        "TrainDeepLearningModel",
        "SuperResolution",
        "pytest tests -v",
        "-RemoveData",
    ):
        assert expected in content


def test_readme_documents_address_changes_without_hardcoding_one():
    content = README.read_text(encoding="utf-8")

    for expected in (
        "resolve_ip.ps1",
        "auto-detect",
        "address changes",
    ):
        assert expected.lower() in content.lower()

    # Documenting a specific address invites copy-paste of a value that is wrong
    # on every other host; the docs should describe resolution instead.
    literal = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
    allowed = {"0.0.0.0", "127.0.0.1", "3.7.1", "8.4.2"}
    found = set(literal.findall(content)) - allowed
    assert not found, f"README hardcodes {sorted(found)}"
