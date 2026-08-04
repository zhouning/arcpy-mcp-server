import hashlib
import sys
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import AsyncMock

import httpx

from arcpy_mcp_server.app import (
    build_services,
    create_application,
)
from arcpy_mcp_server.config import Settings


def make_app(tmp_path):
    settings = Settings(
        public_base_url="https://198.51.100.10:8765",
        data_root=tmp_path / "data",
        tls_cert=tmp_path / "server.crt",
        tls_key=tmp_path / "server.key",
        bearer_token="x" * 32,
        artifact_signing_key="k" * 32,
        arcpy_python=Path(sys.executable),
    )
    services = build_services(
        settings,
        worker_script=Path("tests/fixtures/fake_worker.py"),
    )
    return create_application(settings, services)


def initialize_request():
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1.0"},
        },
    }


async def test_mcp_requires_bearer_and_accepts_correct_token(tmp_path):
    app = make_app(tmp_path)
    transport = httpx.ASGITransport(app=app)
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport, base_url="https://testserver"
        ) as client:
            rejected = await client.post(
                "/mcp", headers=headers, json=initialize_request()
            )
            accepted = await client.post(
                "/mcp",
                headers={
                    **headers,
                    "Authorization": f"Bearer {'x' * 32}",
                },
                json=initialize_request(),
            )

    assert rejected.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json()["result"]["serverInfo"]["name"] == "ArcPy MCP"


async def test_public_healthz_exposes_no_secrets(tmp_path):
    app = make_app(tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport, base_url="https://testserver"
        ) as client:
            response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "version": "0.1.0",
    }
    assert "x" * 32 not in response.text


async def test_signed_artifact_upload_does_not_require_bearer(tmp_path):
    app = make_app(tmp_path)
    payload = b"remote artifact"
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        artifact = await app.state.services.artifacts.create_upload(
            "roads.zip",
            len(payload),
            hashlib.sha256(payload).hexdigest(),
            "application/zip",
        )
        upload_url = app.state.services.artifacts.signed_url(
            "https://testserver", artifact.id, "upload", 60
        )
        target = urlsplit(upload_url)
        async with httpx.AsyncClient(
            transport=transport, base_url="https://testserver"
        ) as client:
            response = await client.put(
                f"{target.path}?{target.query}",
                headers={"Upload-Offset": "0"},
                content=payload,
            )

    assert response.status_code == 204
    assert response.headers["Upload-Offset"] == str(len(payload))


async def test_application_lifespan_runs_artifact_retention_cleanup(tmp_path):
    app = make_app(tmp_path)
    app.state.services.artifacts.cleanup_expired = AsyncMock(return_value=[])

    async with app.router.lifespan_context(app):
        pass

    app.state.services.artifacts.cleanup_expired.assert_awaited_once_with(7, 24)
