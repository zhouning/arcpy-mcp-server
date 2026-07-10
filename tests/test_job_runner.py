import asyncio
import sys
from pathlib import Path

from arcpy_mcp_server.artifacts import ArtifactService
from arcpy_mcp_server.auth import ArtifactSigner
from arcpy_mcp_server.catalog import ToolCatalog, ToolDefinition
from arcpy_mcp_server.db import Database
from arcpy_mcp_server.jobs import JobRunner, JobService
from arcpy_mcp_server.models import JobStatus
from arcpy_mcp_server.worker_supervisor import WorkerSupervisor
from arcpy_mcp_server.workspace import Workspace


def make_catalog():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"value": {"type": "integer"}},
    }
    tools = {
        "delay": ToolDefinition(
            id="delay",
            title="Delay",
            category="test",
            description="Delayed success",
            timeout_seconds=2,
            parameters=schema,
        ),
        "hang": ToolDefinition(
            id="hang",
            title="Hang",
            category="test",
            description="Timeout",
            timeout_seconds=1,
            parameters={
                "type": "object",
                "additionalProperties": False,
                "properties": {},
            },
        ),
    }
    return ToolCatalog(tools)


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
        make_catalog(),
        artifacts,
        workspace,
        supervisor,
    )
    await runner.start()
    return db, jobs, runner, supervisor


async def wait_for_status(jobs, job_id, statuses, timeout=5):
    async with asyncio.timeout(timeout):
        while True:
            job = await jobs.get(job_id)
            if job.status in statuses:
                return job
            await asyncio.sleep(0.02)


async def test_runner_serializes_jobs(tmp_path):
    db, jobs, runner, _ = await make_runner(tmp_path)
    first = await runner.submit("delay", {"value": 1})
    second = await runner.submit("delay", {"value": 2})

    await wait_for_status(jobs, first.id, {JobStatus.RUNNING})
    assert (await jobs.get(second.id)).status is JobStatus.QUEUED
    first_done = await wait_for_status(
        jobs, first.id, {JobStatus.SUCCEEDED}
    )
    second_done = await wait_for_status(
        jobs, second.id, {JobStatus.SUCCEEDED}
    )

    assert first_done.result["value"] == 1
    assert second_done.result["value"] == 2
    await runner.stop()
    await db.stop()


async def test_timeout_restarts_worker_and_next_job_succeeds(tmp_path):
    db, jobs, runner, supervisor = await make_runner(tmp_path)
    timed = await runner.submit("hang", {})
    first_pid = supervisor.pid

    timed_done = await wait_for_status(
        jobs, timed.id, {JobStatus.TIMED_OUT}, timeout=4
    )
    following = await runner.submit("delay", {"value": 3})
    following_done = await wait_for_status(
        jobs, following.id, {JobStatus.SUCCEEDED}
    )

    assert timed_done.error_code == "JOB_TIMEOUT"
    assert supervisor.pid != first_pid
    assert following_done.result["value"] == 3
    await runner.stop()
    await db.stop()


async def test_running_job_can_be_cancelled_and_worker_recovers(tmp_path):
    db, jobs, runner, supervisor = await make_runner(tmp_path)
    job = await runner.submit("hang", {})
    await wait_for_status(jobs, job.id, {JobStatus.RUNNING})
    first_pid = supervisor.pid

    await runner.cancel(job.id)
    cancelled = await wait_for_status(
        jobs, job.id, {JobStatus.CANCELLED}
    )
    following = await runner.submit("delay", {"value": 4})
    following_done = await wait_for_status(
        jobs, following.id, {JobStatus.SUCCEEDED}
    )

    assert cancelled.status is JobStatus.CANCELLED
    assert supervisor.pid != first_pid
    assert following_done.result["value"] == 4
    await runner.stop()
    await db.stop()


async def test_worker_events_are_persisted_without_absolute_paths(tmp_path):
    db, jobs, runner, _ = await make_runner(tmp_path)
    try:
        job = await runner.submit("delay", {"value": 5})
        await wait_for_status(jobs, job.id, {JobStatus.SUCCEEDED})
        events = await jobs.events(job.id)

        worker_events = [
            event for event in events if event["event_type"] == "worker_event"
        ]
        assert worker_events
        assert worker_events[0]["payload"] == {
            "stage": "started",
            "path": "work",
        }
        assert str(tmp_path) not in str(events)
    finally:
        await runner.stop()
        await db.stop()
