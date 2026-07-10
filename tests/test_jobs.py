import pytest

from arcpy_mcp_server.db import Database
from arcpy_mcp_server.jobs import InvalidTransition, JobService
from arcpy_mcp_server.models import JobStatus


async def test_job_transitions_and_restart_reconciliation(tmp_path):
    db = Database(tmp_path / "state.db")
    await db.start()
    service = JobService(db)
    job = await service.submit(
        "vector.buffer", {"distance": "10 Meters"}
    )

    await service.transition(job.id, JobStatus.STARTING)
    await service.transition(job.id, JobStatus.RUNNING)
    await service.reconcile_after_restart()

    assert (await service.get(job.id)).status is JobStatus.INTERRUPTED
    with pytest.raises(InvalidTransition):
        await service.transition(job.id, JobStatus.SUCCEEDED)
    await db.stop()


async def test_queued_job_can_be_cancelled(tmp_path):
    db = Database(tmp_path / "state.db")
    await db.start()
    service = JobService(db)
    job = await service.submit("inspect.dataset", {})

    cancelled = await service.transition(job.id, JobStatus.CANCELLED)

    assert cancelled.status is JobStatus.CANCELLED
    assert (await db.list_events(job.id))[-1]["payload"] == {
        "status": "cancelled"
    }
    await db.stop()
