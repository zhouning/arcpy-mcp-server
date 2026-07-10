from pathlib import Path

import pytest
from pydantic import ValidationError

from arcpy_mcp_server.config import Settings


def test_settings_expand_environment_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    settings = Settings(
        bearer_token="a" * 32,
        artifact_signing_key="b" * 32,
        arcpy_python=Path(
            "D:/Program Files/ArcGIS/Pro/bin/Python/envs/arcgispro-py3/python.exe"
        ),
    )

    assert settings.data_root == tmp_path / "ArcPyMCP" / "data"
    assert settings.database_path == settings.data_root / "state.db"


def test_short_bearer_token_is_rejected(tmp_path):
    with pytest.raises(ValidationError):
        Settings(
            bearer_token="short",
            artifact_signing_key="b" * 32,
            data_root=tmp_path,
            arcpy_python=tmp_path / "python.exe",
        )
