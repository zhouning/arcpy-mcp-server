import asyncio
import hashlib
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from arcpy_mcp_server.app import build_services, create_application
from arcpy_mcp_server.config import Settings
from arcpy_mcp_server.models import JobStatus


async def wait_for_terminal(services, job_id, timeout=5):
    async with asyncio.timeout(timeout):
        while True:
            job = await services.jobs.get(job_id)
            if job.status in {JobStatus.SUCCEEDED, JobStatus.FAILED}:
                return job
            await asyncio.sleep(0.02)


async def test_gateway_upload_job_and_log_flow_with_fake_worker(tmp_path):
    settings = Settings(
        public_base_url="https://192.168.25.228:8765",
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
    app = create_application(settings, services)
    payload = b"gateway artifact"
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        artifact = await services.artifacts.create_upload(
            "input.bin",
            len(payload),
            hashlib.sha256(payload).hexdigest(),
            "application/octet-stream",
        )
        signed = services.artifacts.signed_url(
            "https://testserver", artifact.id, "upload", 60
        )
        target = urlsplit(signed)
        async with httpx.AsyncClient(
            transport=transport, base_url="https://testserver"
        ) as client:
            uploaded = await client.put(
                f"{target.path}?{target.query}",
                headers={"Upload-Offset": "0"},
                content=payload,
            )
        completed = await services.artifacts.complete_upload(artifact.id)
        job = await services.runner.submit(
            "inspect.dataset",
            {
                "input_artifact_id": completed.id,
                "input_path": "input.bin",
            },
        )
        terminal = await wait_for_terminal(services, job.id)
        events = await services.jobs.events(job.id)

    assert uploaded.status_code == 204
    assert terminal.status is JobStatus.SUCCEEDED
    assert terminal.result["input_path"].endswith("input.bin")
    assert str(tmp_path) not in str(events)

