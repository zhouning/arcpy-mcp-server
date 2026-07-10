from arcpy_mcp_server.db import Database
from arcpy_mcp_server.models import (
    ArtifactRecord,
    ArtifactState,
    JobRecord,
    JobStatus,
)


async def test_database_round_trips_artifacts_jobs_events_and_links(tmp_path):
    db = Database(tmp_path / "state.db")
    await db.start()
    artifact = ArtifactRecord(
        id="artifact-1",
        logical_name="roads.zip",
        state=ArtifactState.INCOMPLETE,
        expected_size=100,
        expected_sha256="a" * 64,
        committed_size=0,
        media_type="application/zip",
    )
    job = JobRecord(
        id="job-1",
        tool_id="vector.buffer",
        status=JobStatus.QUEUED,
        request={},
    )

    await db.insert_artifact(artifact)
    await db.insert_job(job)
    await db.append_event(job.id, "submitted", {"tool_id": job.tool_id})
    await db.link_artifact(job.id, artifact.id, "input")

    assert (await db.get_artifact("artifact-1")).logical_name == "roads.zip"
    assert (await db.get_job("job-1")).status is JobStatus.QUEUED
    assert (await db.list_artifacts())[0].id == artifact.id
    assert (await db.list_jobs())[0].id == job.id
    assert (await db.list_events(job.id))[0]["event_type"] == "submitted"
    assert await db.artifact_has_active_job(artifact.id)
    await db.stop()
