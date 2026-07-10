import uuid

from .db import Database
from .models import JobRecord, JobStatus


class InvalidTransition(ValueError):
    pass


ALLOWED_TRANSITIONS = {
    JobStatus.QUEUED: {JobStatus.STARTING, JobStatus.CANCELLED},
    JobStatus.STARTING: {
        JobStatus.RUNNING,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    },
    JobStatus.RUNNING: {
        JobStatus.SUCCEEDED,
        JobStatus.FAILED,
        JobStatus.TIMED_OUT,
        JobStatus.CANCELLING,
        JobStatus.INTERRUPTED,
    },
    JobStatus.CANCELLING: {
        JobStatus.CANCELLED,
        JobStatus.FAILED,
    },
}


class JobService:
    def __init__(self, db: Database):
        self.db = db

    async def submit(self, tool_id: str, request: dict) -> JobRecord:
        record = JobRecord(
            id=str(uuid.uuid4()),
            tool_id=tool_id,
            status=JobStatus.QUEUED,
            request=request,
        )
        await self.db.insert_job(record)
        await self.db.append_event(
            record.id, "submitted", {"tool_id": tool_id}
        )
        return record

    async def get(self, job_id: str) -> JobRecord:
        record = await self.db.get_job(job_id)
        if record is None:
            raise KeyError(job_id)
        return record

    async def list_jobs(self, limit: int = 100) -> list[JobRecord]:
        return await self.db.list_jobs(limit)

    async def events(self, job_id: str) -> list[dict]:
        await self.get(job_id)
        return await self.db.list_events(job_id)

    async def transition(
        self,
        job_id: str,
        status: JobStatus,
        *,
        result: dict | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> JobRecord:
        record = await self.get(job_id)
        if status not in ALLOWED_TRANSITIONS.get(record.status, set()):
            raise InvalidTransition(
                f"{record.status.value} -> {status.value}"
            )
        record.status = status
        record.result = result
        record.error_code = error_code
        record.error_message = error_message
        await self.db.update_job(record)
        await self.db.append_event(
            job_id, "status", {"status": status.value}
        )
        return record

    async def reconcile_after_restart(self) -> None:
        stale = await self.db.list_jobs_by_status(
            {
                JobStatus.STARTING,
                JobStatus.RUNNING,
                JobStatus.CANCELLING,
            }
        )
        for record in stale:
            record.status = JobStatus.INTERRUPTED
            record.error_code = "WORKER_UNAVAILABLE"
            record.error_message = (
                "service restarted while the job was active"
            )
            await self.db.update_job(record)
            await self.db.append_event(record.id, "interrupted", {})
