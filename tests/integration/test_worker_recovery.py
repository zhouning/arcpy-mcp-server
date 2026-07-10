import asyncio
import sys
from pathlib import Path

from arcpy_mcp_server.artifacts import ArtifactService
from arcpy_mcp_server.auth import ArtifactSigner
from arcpy_mcp_server.catalog import (
    OutputDefinition,
    ToolCatalog,
    ToolDefinition,
)
from arcpy_mcp_server.db import Database
from arcpy_mcp_server.jobs import JobRunner, JobService
from arcpy_mcp_server.models import JobStatus
from arcpy_mcp_server.worker_supervisor import WorkerSupervisor
from arcpy_mcp_server.workspace import Workspace


def recovery_catalog():
    empty_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {},
    }
    output_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["output_name"],
        "properties": {"output_name": {"type": "string"}},
    }
    return ToolCatalog(
        {
            "malformed": ToolDefinition(
                id="malformed",
                title="Malformed",
                category="test",
                description="Emit malformed JSON",
                timeout_seconds=2,
                parameters=empty_schema,
            ),
            "partial_crash": ToolDefinition(
                id="partial_crash",
                title="Partial crash",
                category="test",
                description="Write output then crash",
                timeout_seconds=2,
                parameters=output_schema,
                output=OutputDefinition(name_field="output_name", kind="file"),
            ),
            "delay": ToolDefinition(
                id="delay",
                title="Delay",
                category="test",
                description="Successful follow-up",
                timeout_seconds=2,
                parameters={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"value": {"type": "integer"}},
                },
            ),
        }
    )


async def wait_for_terminal(jobs, job_id, timeout=5):
    async with asyncio.timeout(timeout):
        while True:
            job = await jobs.get(job_id)
            if job.status in {
                JobStatus.SUCCEEDED,
                JobStatus.FAILED,
                JobStatus.TIMED_OUT,
                JobStatus.CANCELLED,
            }:
                return job
            await asyncio.sleep(0.02)


async def make_runner(tmp_path):
    db = Database(tmp_path / "state.db")
    await db.start()
    workspace = Workspace(tmp_path / "workspace", 1024, 10, 4)
    artifacts = ArtifactService(
        db,
        tmp_path / "artifacts",
        workspace,
        ArtifactSigner(b"k" * 32),
        1024,
    )
    supervisor = WorkerSupervisor(
        Path(sys.executable), Path("tests/fixtures/fake_worker.py")
    )
    jobs = JobService(db)
    runner = JobRunner(
        jobs,
        db,
        recovery_catalog(),
        artifacts,
        workspace,
        supervisor,
    )
    await runner.start()
    return db, jobs, runner, supervisor, workspace


async def test_malformed_worker_output_restarts_and_following_job_succeeds(tmp_path):
    db, jobs, runner, supervisor, _ = await make_runner(tmp_path)
    try:
        first_pid = supervisor.pid
        malformed = await runner.submit("malformed", {})
        failed = await wait_for_terminal(jobs, malformed.id)
        following = await runner.submit("delay", {"value": 7})
        succeeded = await wait_for_terminal(jobs, following.id)

        assert failed.error_code == "WORKER_CRASHED"
        assert supervisor.pid != first_pid
        assert succeeded.result["value"] == 7
    finally:
        await runner.stop()
        await db.stop()


async def test_worker_crash_removes_incomplete_job_output(tmp_path):
    db, jobs, runner, _, workspace = await make_runner(tmp_path)
    try:
        crashed = await runner.submit(
            "partial_crash", {"output_name": "partial.bin"}
        )
        failed = await wait_for_terminal(jobs, crashed.id)

        assert failed.error_code == "WORKER_CRASHED"
        assert list((workspace.job_root(crashed.id) / "output").iterdir()) == []
    finally:
        await runner.stop()
        await db.stop()
