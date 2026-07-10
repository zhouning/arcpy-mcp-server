import hashlib
import zipfile
from datetime import timedelta

from arcpy_mcp_server.artifacts import ArtifactService
from arcpy_mcp_server.auth import ArtifactSigner
from arcpy_mcp_server.db import Database
from arcpy_mcp_server.models import ArtifactState, utc_now
from arcpy_mcp_server.workspace import Workspace


async def make_service(tmp_path):
    db = Database(tmp_path / "state.db")
    await db.start()
    workspace = Workspace(tmp_path / "workspace", 1024 * 1024, 100, 8)
    service = ArtifactService(
        db,
        tmp_path / "artifacts",
        workspace,
        ArtifactSigner(b"k" * 32),
        1024 * 1024,
    )
    return db, service


async def test_upload_resumes_and_completes(tmp_path):
    payload = b"abcdef"
    db, service = await make_service(tmp_path)

    created = await service.create_upload(
        "data.bin",
        len(payload),
        hashlib.sha256(payload).hexdigest(),
        "application/octet-stream",
    )
    await service.append_upload(created.id, 0, payload[:3])
    status = await service.get_upload_status(created.id)
    await service.append_upload(created.id, status.committed_size, payload[3:])
    completed = await service.complete_upload(created.id)

    assert completed.state is ArtifactState.READY
    assert completed.actual_sha256 == hashlib.sha256(payload).hexdigest()
    assert (
        await service.resolve_ready_path(completed.id, completed.logical_name)
    ).read_bytes() == payload
    await db.stop()


async def test_zip_upload_extracts_to_content_root(tmp_path):
    archive = tmp_path / "roads.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("roads/roads.shp", b"shape")
    payload = archive.read_bytes()
    db, service = await make_service(tmp_path)

    created = await service.create_upload(
        archive.name,
        len(payload),
        hashlib.sha256(payload).hexdigest(),
        "application/zip",
    )
    await service.append_upload(created.id, 0, payload)
    completed = await service.complete_upload(created.id)

    resolved = await service.resolve_ready_path(
        completed.id, "roads/roads.shp"
    )
    assert resolved.read_bytes() == b"shape"
    await db.stop()


async def test_cleanup_deletes_expired_unreferenced_artifact(tmp_path):
    payload = b"old"
    db, service = await make_service(tmp_path)
    created = await service.create_upload(
        "old.bin",
        len(payload),
        hashlib.sha256(payload).hexdigest(),
        "application/octet-stream",
    )
    await service.append_upload(created.id, 0, payload)
    completed = await service.complete_upload(created.id)
    completed.completed_at = utc_now() - timedelta(days=8)
    await db.update_artifact(completed)

    deleted = await service.cleanup_expired(7, 24)

    assert deleted == [completed.id]
    assert (await db.get_artifact(completed.id)).state is ArtifactState.DELETED
    await db.stop()
