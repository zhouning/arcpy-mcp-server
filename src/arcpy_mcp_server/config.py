import os
from pathlib import Path

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from arcpy_mcp_server.host_address import resolve_server_ip


def _default_local_app_data() -> Path:
    value = os.environ.get("LOCALAPPDATA")
    if not value:
        raise RuntimeError("LOCALAPPDATA is required on Windows")
    return Path(value)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ARCPY_MCP_",
        env_file=None,
        case_sensitive=False,
    )

    # Derived from the host's current LAN address rather than hardcoded, so a
    # DHCP change does not leave signed artifact URLs pointing at an address
    # clients can no longer reach. bootstrap.ps1 writes the resolved value into
    # server.env; this default keeps a direct `python -m` run working too.
    public_base_url: AnyHttpUrl = Field(
        default_factory=lambda: AnyHttpUrl(f"https://{resolve_server_ip()}:8765")
    )
    bind_host: str = "0.0.0.0"
    bind_port: int = Field(default=8765, ge=1, le=65535)
    arcpy_python: Path = Path(
        r"D:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"
    )
    data_root: Path = Field(
        default_factory=lambda: _default_local_app_data() / "ArcPyMCP" / "data"
    )
    tls_cert: Path = Field(
        default_factory=lambda: _default_local_app_data()
        / "ArcPyMCP"
        / "certs"
        / "server.crt"
    )
    tls_key: Path = Field(
        default_factory=lambda: _default_local_app_data()
        / "ArcPyMCP"
        / "certs"
        / "server.key"
    )
    bearer_token: SecretStr = Field(min_length=32)
    artifact_signing_key: SecretStr = Field(min_length=32)
    retention_days: int = Field(default=7, ge=1, le=365)
    max_upload_bytes: int = Field(default=20 * 1024**3, ge=1)
    max_expanded_bytes: int = Field(default=50 * 1024**3, ge=1)
    max_zip_entries: int = Field(default=100_000, ge=1)
    max_zip_depth: int = Field(default=16, ge=1, le=64)
    incomplete_upload_hours: int = Field(default=24, ge=1, le=168)

    @field_validator("data_root", "tls_cert", "tls_key", mode="before")
    @classmethod
    def expand_percent_variables(cls, value):
        if isinstance(value, str):
            return Path(os.path.expandvars(value))
        return value

    @property
    def database_path(self) -> Path:
        return self.data_root / "state.db"

    @property
    def worker_script(self) -> Path:
        return Path(__file__).parent / "worker" / "main.py"
