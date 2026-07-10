import asyncio
import hashlib
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from starlette.applications import Starlette

from arcpy_mcp_server.artifacts import ArtifactService, artifact_routes
from arcpy_mcp_server.auth import ArtifactSigner
from arcpy_mcp_server.catalog import ToolCatalog
from arcpy_mcp_server.db import Database
from arcpy_mcp_server.jobs import JobRunner, JobService
from arcpy_mcp_server.models import JobStatus
from arcpy_mcp_server.worker_supervisor import WorkerSupervisor
from arcpy_mcp_server.workspace import Workspace


ARCPY_PYTHON = Path(
    r"D:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"
)
WORKER = Path("src/arcpy_mcp_server/worker/main.py")
CATALOG = Path("config/tool_catalog.yaml")


async def wait_for_terminal(jobs, job_id, timeout=60):
    async with asyncio.timeout(timeout):
        while True:
            job = await jobs.get(job_id)
            if job.status in {JobStatus.SUCCEEDED, JobStatus.FAILED}:
                return job
            await asyncio.sleep(0.05)


def create_input_geodatabase(tmp_path):
    setup = """
import arcpy
import sys

root, geodatabase = sys.argv[1:3]
arcpy.management.CreateFileGDB(root, geodatabase)
feature_class = str(arcpy.os.path.join(root, geodatabase, "points"))
arcpy.management.CreateFeatureclass(
    str(arcpy.os.path.join(root, geodatabase)),
    "points",
    "POINT",
    spatial_reference=4326,
)
with arcpy.da.InsertCursor(feature_class, ["SHAPE@XY"]) as cursor:
    cursor.insertRow([(121.0, 31.0)])
    cursor.insertRow([(121.001, 31.001)])
"""
    subprocess.run(
        [str(ARCPY_PYTHON), "-c", setup, str(tmp_path), "input.gdb"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(
        shutil.make_archive(
            str(tmp_path / "input"),
            "zip",
            root_dir=tmp_path,
            base_dir="input.gdb",
        )
    )


async def test_real_arcpy_artifact_buffer_and_download_flow(tmp_path):
    archive = create_input_geodatabase(tmp_path)
    payload = archive.read_bytes()
    db = Database(tmp_path / "state.db")
    await db.start()
    workspace = Workspace(tmp_path / "workspace", 100 * 1024**2, 1000, 16)
    artifacts = ArtifactService(
        db,
        tmp_path / "artifacts",
        workspace,
        ArtifactSigner(b"k" * 32),
        100 * 1024**2,
    )
    supervisor = WorkerSupervisor(ARCPY_PYTHON, WORKER)
    jobs = JobService(db)
    runner = JobRunner(
        jobs,
        db,
        ToolCatalog.load(CATALOG),
        artifacts,
        workspace,
        supervisor,
    )
    app = Starlette(routes=artifact_routes())
    app.state.artifact_service = artifacts
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://testserver",
    )

    await runner.start()
    try:
        created = await artifacts.create_upload(
            archive.name,
            len(payload),
            hashlib.sha256(payload).hexdigest(),
            "application/zip",
        )
        await artifacts.append_upload(created.id, 0, payload)
        ready = await artifacts.complete_upload(created.id)
        job = await runner.submit(
            "vector.buffer",
            {
                "input_artifact_id": ready.id,
                "input_path": "input.gdb/points",
                "output_name": "buffer.shp",
                "distance": "10 Meters",
                "dissolve_option": "NONE",
            },
        )
        terminal = await wait_for_terminal(jobs, job.id)
        assert terminal.status is JobStatus.SUCCEEDED, terminal.error_message
        output_id = terminal.result["output_artifact_ids"][0]
        output = await artifacts.get_upload_status(output_id)
        assert Path(output.storage_path).is_file()
        assert hashlib.sha256(Path(output.storage_path).read_bytes()).hexdigest() == (
            output.actual_sha256
        )

        signed = artifacts.signed_url(
            "https://testserver", output.id, "download", 60
        )
        target = urlsplit(signed)
        downloaded = await client.get(
            f"{target.path}?{target.query}",
            headers={"Range": "bytes=0-127"},
        )
        assert downloaded.status_code == 206
        assert downloaded.content
    finally:
        await client.aclose()
        await runner.stop()
        await db.stop()

