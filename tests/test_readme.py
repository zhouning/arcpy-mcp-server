from pathlib import Path


README = Path(__file__).parents[1] / "README.md"


def test_readme_covers_secure_operations_and_limitations():
    content = README.read_text(encoding="utf-8")

    for expected in (
        "ArcGIS Pro 3.7.1",
        "192.168.25.228",
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
