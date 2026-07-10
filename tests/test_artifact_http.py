import hashlib
from urllib.parse import urlsplit

import httpx
from starlette.applications import Starlette

from arcpy_mcp_server.artifacts import (
    ArtifactService,
    artifact_routes,
)
from arcpy_mcp_server.auth import ArtifactSigner
from arcpy_mcp_server.db import Database
from arcpy_mcp_server.workspace import Workspace


async def make_client(tmp_path):
    db = Database(tmp_path / "state.db")
    await db.start()
    signer = ArtifactSigner(b"k" * 32)
    service = ArtifactService(
        db,
        tmp_path / "artifacts",
        Workspace(tmp_path / "workspace", 1024, 10, 4),
        signer,
        1024,
    )
    app = Starlette(routes=artifact_routes())
    app.state.artifact_service = service
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(
        transport=transport, base_url="https://testserver"
    )
    return db, service, client


async def test_signed_upload_and_range_download(tmp_path):
    payload = b"abcdef"
    db, service, client = await make_client(tmp_path)
    created = await service.create_upload(
        "data.bin",
        len(payload),
        hashlib.sha256(payload).hexdigest(),
        "application/octet-stream",
    )
    upload_url = service.signed_url(
        "https://testserver", created.id, "upload", 60
    )
    upload_target = urlsplit(upload_url)

    first = await client.put(
        f"{upload_target.path}?{upload_target.query}",
        headers={"Upload-Offset": "0"},
        content=payload[:3],
    )
    second = await client.put(
        f"{upload_target.path}?{upload_target.query}",
        headers={"Upload-Offset": "3"},
        content=payload[3:],
    )
    await service.complete_upload(created.id)
    download_url = service.signed_url(
        "https://testserver", created.id, "download", 60
    )
    download_target = urlsplit(download_url)
    target = f"{download_target.path}?{download_target.query}"
    metadata = await client.head(target)
    ranged = await client.get(target, headers={"Range": "bytes=2-4"})

    assert first.status_code == 204
    assert first.headers["Upload-Offset"] == "3"
    assert second.status_code == 204
    assert second.headers["Upload-Offset"] == "6"
    assert metadata.status_code == 200
    assert metadata.headers["Content-Length"] == "6"
    assert ranged.status_code == 206
    assert ranged.headers["Content-Range"] == "bytes 2-4/6"
    assert ranged.content == b"cde"
    await client.aclose()
    await db.stop()


async def test_tampered_artifact_signature_is_rejected(tmp_path):
    db, service, client = await make_client(tmp_path)
    created = await service.create_upload(
        "data.bin",
        1,
        hashlib.sha256(b"x").hexdigest(),
        "application/octet-stream",
    )
    upload_url = service.signed_url(
        "https://testserver", created.id, "upload", 60
    )
    target = urlsplit(upload_url)
    query = target.query.replace("signature=", "signature=bad")

    response = await client.put(
        f"{target.path}?{query}",
        headers={"Upload-Offset": "0"},
        content=b"x",
    )

    assert response.status_code == 403
    await client.aclose()
    await db.stop()
