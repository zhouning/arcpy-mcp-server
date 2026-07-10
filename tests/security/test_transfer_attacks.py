import hashlib
import time

import httpx
from starlette.applications import Starlette

from arcpy_mcp_server.artifacts import ArtifactService, artifact_routes
from arcpy_mcp_server.auth import ArtifactSigner
from arcpy_mcp_server.db import Database
from arcpy_mcp_server.workspace import Workspace


async def make_transfer_client(tmp_path, max_upload_bytes=8):
    db = Database(tmp_path / "state.db")
    await db.start()
    service = ArtifactService(
        db,
        tmp_path / "artifacts",
        Workspace(tmp_path / "workspace", 1024, 10, 4),
        ArtifactSigner(b"k" * 32),
        max_upload_bytes,
    )
    app = Starlette(routes=artifact_routes())
    app.state.artifact_service = service
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://testserver",
    )
    return db, service, client


async def test_expired_upload_signature_is_rejected(tmp_path):
    db, service, client = await make_transfer_client(tmp_path)
    try:
        artifact = await service.create_upload(
            "data.bin", 1, hashlib.sha256(b"x").hexdigest(), "application/octet-stream"
        )
        expires = int(time.time()) - 1
        signature = service.signer.sign("upload", artifact.id, expires)
        response = await client.put(
            f"/artifacts/{artifact.id}/content"
            f"?op=upload&expires={expires}&signature={signature}",
            headers={"Upload-Offset": "0"},
            content=b"x",
        )

        assert response.status_code == 403
    finally:
        await client.aclose()
        await db.stop()


async def test_wrong_offset_and_oversized_chunk_are_rejected(tmp_path):
    db, service, client = await make_transfer_client(tmp_path)
    try:
        artifact = await service.create_upload(
            "data.bin", 2, hashlib.sha256(b"xy").hexdigest(), "application/octet-stream"
        )
        signed = service.signed_url("https://testserver", artifact.id, "upload", 60)
        target = signed.removeprefix("https://testserver")

        wrong_offset = await client.put(
            target, headers={"Upload-Offset": "1"}, content=b"x"
        )
        oversized = await client.put(
            target, headers={"Upload-Offset": "0"}, content=b"xyz"
        )

        assert wrong_offset.status_code == 409
        assert oversized.status_code == 409
    finally:
        await client.aclose()
        await db.stop()


async def test_oversized_upload_declaration_is_rejected(tmp_path):
    db, service, client = await make_transfer_client(tmp_path, max_upload_bytes=2)
    try:
        try:
            await service.create_upload(
                "large.bin",
                3,
                hashlib.sha256(b"xyz").hexdigest(),
                "application/octet-stream",
            )
        except ValueError as error:
            assert "configured limit" in str(error)
        else:
            raise AssertionError("oversized upload declaration was accepted")
    finally:
        await client.aclose()
        await db.stop()

