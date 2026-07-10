import hashlib
import shutil
import tempfile
import time
import uuid
from datetime import timedelta
from pathlib import Path

from starlette.requests import Request
from starlette.responses import (
    PlainTextResponse,
    Response,
    StreamingResponse,
)
from starlette.routing import Route

from .auth import ArtifactSigner
from .db import Database
from .models import ArtifactRecord, ArtifactState, utc_now
from .workspace import Workspace


class ArtifactService:
    def __init__(
        self,
        db: Database,
        root: Path,
        workspace: Workspace,
        signer: ArtifactSigner,
        max_upload_bytes: int,
    ):
        self.db = db
        self.root = root
        self.workspace = workspace
        self.signer = signer
        self.max_upload_bytes = max_upload_bytes
        self.root.mkdir(parents=True, exist_ok=True)

    async def create_upload(
        self,
        logical_name: str,
        expected_size: int,
        expected_sha256: str,
        media_type: str,
    ) -> ArtifactRecord:
        if expected_size < 0 or expected_size > self.max_upload_bytes:
            raise ValueError("upload size exceeds configured limit")
        if len(expected_sha256) != 64:
            raise ValueError(
                "expected_sha256 must be a SHA-256 hex digest"
            )
        artifact_id = str(uuid.uuid4())
        record = ArtifactRecord(
            id=artifact_id,
            logical_name=logical_name,
            state=ArtifactState.INCOMPLETE,
            expected_size=expected_size,
            expected_sha256=expected_sha256.lower(),
            media_type=media_type,
            storage_path=str(self.root / f"{artifact_id}.part"),
        )
        await self.db.insert_artifact(record)
        return record

    async def get_upload_status(self, artifact_id: str) -> ArtifactRecord:
        record = await self.db.get_artifact(artifact_id)
        if record is None:
            raise KeyError(artifact_id)
        return record

    async def append_upload(
        self, artifact_id: str, offset: int, chunk: bytes
    ) -> ArtifactRecord:
        record = await self.get_upload_status(artifact_id)
        if record.state is not ArtifactState.INCOMPLETE:
            raise ValueError("artifact is not uploadable")
        if offset != record.committed_size:
            raise ValueError(
                f"offset mismatch; expected {record.committed_size}"
            )
        if record.committed_size + len(chunk) > record.expected_size:
            raise ValueError("chunk exceeds declared upload size")
        path = Path(record.storage_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("ab") as output:
            output.write(chunk)
        record.committed_size += len(chunk)
        await self.db.update_artifact(record)
        return record

    async def complete_upload(self, artifact_id: str) -> ArtifactRecord:
        record = await self.get_upload_status(artifact_id)
        if record.committed_size != record.expected_size:
            raise ValueError("upload is incomplete")
        digest = hashlib.sha256()
        with Path(record.storage_path).open("rb") as input_stream:
            for block in iter(
                lambda: input_stream.read(1024 * 1024), b""
            ):
                digest.update(block)
        actual = digest.hexdigest()
        if actual != record.expected_sha256:
            raise ValueError("artifact hash mismatch")
        final_path = self.root / artifact_id / record.logical_name
        final_path.parent.mkdir(parents=True, exist_ok=True)
        Path(record.storage_path).replace(final_path)
        record.storage_path = str(final_path)
        if final_path.suffix.casefold() == ".zip":
            content_root = self.root / artifact_id / "content"
            self.workspace.extract_zip(final_path, content_root)
            record.content_root = str(content_root)
        else:
            record.content_root = str(final_path.parent)
        record.actual_sha256 = actual
        record.state = ArtifactState.READY
        record.completed_at = utc_now()
        await self.db.update_artifact(record)
        return record

    async def resolve_ready_path(
        self, artifact_id: str, relative_path: str
    ) -> Path:
        record = await self.get_upload_status(artifact_id)
        if (
            record.state is not ArtifactState.READY
            or record.content_root is None
        ):
            raise ValueError("artifact is not ready")
        base = Path(record.content_root)
        resolved = self.workspace.resolve_relative(base, relative_path)
        if not resolved.exists():
            raise ValueError("artifact-relative path does not exist")
        return resolved

    async def list_artifacts(self) -> list[ArtifactRecord]:
        return [
            record
            for record in await self.db.list_artifacts()
            if record.state is not ArtifactState.DELETED
        ]

    async def delete_artifact(
        self, artifact_id: str
    ) -> ArtifactRecord:
        record = await self.get_upload_status(artifact_id)
        artifact_root = self.root / artifact_id
        if artifact_root.exists():
            shutil.rmtree(artifact_root)
        if record.storage_path:
            stored = Path(record.storage_path)
            if stored.exists() and stored.is_file():
                stored.unlink()
        record.state = ArtifactState.DELETED
        await self.db.update_artifact(record)
        return record

    async def register_output(
        self,
        output_path: Path,
        logical_name: str,
        media_type: str,
    ) -> ArtifactRecord:
        if output_path.suffix.casefold() == ".shp":
            with tempfile.TemporaryDirectory(dir=self.root) as staging_name:
                staging = Path(staging_name)
                for component in output_path.parent.glob(
                    f"{output_path.stem}.*"
                ):
                    shutil.copy2(component, staging / component.name)
                archive_base = (
                    self.root / str(uuid.uuid4()) / output_path.stem
                )
                archive_base.parent.mkdir(parents=True, exist_ok=True)
                output_path = Path(
                    shutil.make_archive(
                        str(archive_base), "zip", staging
                    )
                )
                logical_name = f"{output_path.stem}.zip"
                media_type = "application/zip"
        if output_path.is_dir():
            archive_base = self.root / str(uuid.uuid4()) / logical_name
            archive_base.parent.mkdir(parents=True, exist_ok=True)
            output_path = Path(
                shutil.make_archive(
                    str(archive_base), "zip", output_path
                )
            )
            logical_name = f"{logical_name}.zip"
            media_type = "application/zip"
        digest = hashlib.sha256()
        size = 0
        with output_path.open("rb") as input_stream:
            for block in iter(
                lambda: input_stream.read(1024 * 1024), b""
            ):
                size += len(block)
                digest.update(block)
        artifact_id = str(uuid.uuid4())
        destination = self.root / artifact_id / logical_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        output_path.replace(destination)
        record = ArtifactRecord(
            id=artifact_id,
            logical_name=logical_name,
            state=ArtifactState.READY,
            expected_size=size,
            expected_sha256=digest.hexdigest(),
            committed_size=size,
            actual_sha256=digest.hexdigest(),
            media_type=media_type,
            storage_path=str(destination),
            content_root=str(destination.parent),
            completed_at=utc_now(),
        )
        await self.db.insert_artifact(record)
        return record

    async def cleanup_expired(
        self, retention_days: int, incomplete_upload_hours: int
    ) -> list[str]:
        cutoff = utc_now() - timedelta(days=retention_days)
        incomplete_cutoff = utc_now() - timedelta(
            hours=incomplete_upload_hours
        )
        deleted = []
        for record in await self.list_artifacts():
            if record.state is ArtifactState.INCOMPLETE:
                if record.created_at < incomplete_cutoff:
                    await self.delete_artifact(record.id)
                    deleted.append(record.id)
                continue
            reference_time = record.completed_at or record.created_at
            if reference_time >= cutoff:
                continue
            if await self.db.artifact_has_active_job(record.id):
                continue
            await self.delete_artifact(record.id)
            deleted.append(record.id)
        return deleted

    def signed_url(
        self,
        base_url: str,
        artifact_id: str,
        operation: str,
        ttl: int,
    ) -> str:
        expires = int(time.time()) + ttl
        signature = self.signer.sign(
            operation, artifact_id, expires
        )
        base_url = base_url.rstrip("/")
        return (
            f"{base_url}/artifacts/{artifact_id}/content"
            f"?op={operation}&expires={expires}&signature={signature}"
        )


def artifact_routes() -> list[Route]:
    return [
        Route(
            "/artifacts/{artifact_id}/content",
            upload_content,
            methods=["PUT"],
        ),
        Route(
            "/artifacts/{artifact_id}/content",
            download_content,
            methods=["GET", "HEAD"],
        ),
    ]


def _verified_operation(
    request: Request, expected_operation: str
) -> tuple[ArtifactService, str] | Response:
    service: ArtifactService = request.app.state.artifact_service
    artifact_id = request.path_params["artifact_id"]
    operation = request.query_params.get("op", "")
    signature = request.query_params.get("signature", "")
    try:
        expires_at = int(request.query_params.get("expires", "0"))
    except ValueError:
        return PlainTextResponse("invalid expiry", status_code=403)
    if operation != expected_operation or not service.signer.verify(
        operation, artifact_id, expires_at, signature
    ):
        return PlainTextResponse("invalid signature", status_code=403)
    return service, artifact_id


async def upload_content(request: Request) -> Response:
    verified = _verified_operation(request, "upload")
    if isinstance(verified, Response):
        return verified
    service, artifact_id = verified
    try:
        offset = int(request.headers["Upload-Offset"])
        async for chunk in request.stream():
            if not chunk:
                continue
            record = await service.append_upload(
                artifact_id, offset, chunk
            )
            offset = record.committed_size
    except KeyError:
        return PlainTextResponse(
            "missing artifact or Upload-Offset", status_code=404
        )
    except ValueError as error:
        return PlainTextResponse(str(error), status_code=409)
    return Response(
        status_code=204, headers={"Upload-Offset": str(offset)}
    )


async def download_content(request: Request) -> Response:
    verified = _verified_operation(request, "download")
    if isinstance(verified, Response):
        return verified
    service, artifact_id = verified
    try:
        record = await service.get_upload_status(artifact_id)
    except KeyError:
        return PlainTextResponse("artifact not found", status_code=404)
    if (
        record.state is not ArtifactState.READY
        or record.storage_path is None
    ):
        return PlainTextResponse("artifact is not ready", status_code=409)
    path = Path(record.storage_path)
    size = path.stat().st_size
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Type": record.media_type,
        "Content-Disposition": (
            f'attachment; filename="{record.logical_name}"'
        ),
    }
    byte_range = request.headers.get("Range")
    if byte_range:
        try:
            start, end = _parse_range(byte_range, size)
        except ValueError:
            return Response(
                status_code=416,
                headers={"Content-Range": f"bytes */{size}"},
            )
        headers.update(
            {
                "Content-Length": str(end - start + 1),
                "Content-Range": f"bytes {start}-{end}/{size}",
            }
        )
        if request.method == "HEAD":
            return Response(status_code=206, headers=headers)
        return StreamingResponse(
            _read_file_range(path, start, end),
            status_code=206,
            headers=headers,
        )
    headers["Content-Length"] = str(size)
    if request.method == "HEAD":
        return Response(status_code=200, headers=headers)
    return StreamingResponse(
        _read_file_range(path, 0, size - 1),
        status_code=200,
        headers=headers,
    )


def _parse_range(value: str, size: int) -> tuple[int, int]:
    if not value.startswith("bytes=") or "," in value:
        raise ValueError("only one byte range is supported")
    bounds = value[6:].split("-", maxsplit=1)
    if len(bounds) != 2 or not bounds[0]:
        raise ValueError("range start is required")
    start = int(bounds[0])
    end = int(bounds[1]) if bounds[1] else size - 1
    if start < 0 or end < start or start >= size:
        raise ValueError("range is outside the artifact")
    return start, min(end, size - 1)


def _read_file_range(path: Path, start: int, end: int):
    remaining = end - start + 1
    with path.open("rb") as input_stream:
        input_stream.seek(start)
        while remaining:
            chunk = input_stream.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
