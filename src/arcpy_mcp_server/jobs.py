import asyncio
import shutil
import uuid
from copy import deepcopy
from pathlib import Path

from .artifacts import ArtifactService
from .catalog import ToolCatalog
from .db import Database
from .models import JobRecord, JobStatus
from .worker_supervisor import (
    WorkerExecutionError,
    WorkerSupervisor,
)
from .workspace import Workspace


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


async def resolve_worker_parameters(
    definition,
    request: dict,
    artifact_service: ArtifactService,
    workspace: Workspace,
    job_id: str,
) -> dict:
    resolved = deepcopy(request)
    for input_definition in definition.inputs:
        if input_definition.multiple:
            container = input_definition.container_field
            if container is None:
                raise ValueError(
                    "multiple artifact input requires container_field"
                )
            values = []
            for item in resolved[container]:
                path = await artifact_service.resolve_ready_path(
                    item[input_definition.artifact_id_field],
                    item[input_definition.path_field],
                )
                values.append(str(path))
            resolved[container] = values
            continue
        artifact_id = resolved.pop(
            input_definition.artifact_id_field
        )
        relative_path = resolved[input_definition.path_field]
        resolved[input_definition.path_field] = str(
            await artifact_service.resolve_ready_path(
                artifact_id, relative_path
            )
        )
    job_root = workspace.job_root(job_id)
    resolved["work_dir"] = str(job_root / "work")
    if definition.output is not None:
        output_name = resolved.pop(definition.output.name_field)
        output_path = workspace.resolve_relative(
            job_root / "output", output_name
        )
        resolved["output_path"] = str(output_path)
        resolved["output_kind"] = definition.output.kind
    return resolved


async def link_job_artifacts(
    db,
    job_id,
    definition,
    request,
    output_ids=(),
):
    for input_definition in definition.inputs:
        if input_definition.multiple:
            for item in request[input_definition.container_field]:
                await db.link_artifact(
                    job_id,
                    item[input_definition.artifact_id_field],
                    "input",
                )
        else:
            await db.link_artifact(
                job_id,
                request[input_definition.artifact_id_field],
                "input",
            )
    for artifact_id in output_ids:
        await db.link_artifact(job_id, artifact_id, "output")


class JobRunner:
    def __init__(
        self,
        jobs: JobService,
        db: Database,
        catalog: ToolCatalog,
        artifacts: ArtifactService,
        workspace: Workspace,
        supervisor: WorkerSupervisor,
    ):
        self.jobs = jobs
        self.db = db
        self.catalog = catalog
        self.artifacts = artifacts
        self.workspace = workspace
        self.supervisor = supervisor
        self.queue: asyncio.Queue[str | None] = asyncio.Queue()
        self.task: asyncio.Task | None = None
        self.current_job_id: str | None = None
        self._cancel_lock = asyncio.Lock()

    async def start(self) -> None:
        await self.supervisor.start()
        if self.task is None:
            self.task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self.task is not None:
            await self.queue.put(None)
            await self.task
            self.task = None
        await self.supervisor.stop()

    async def submit(self, tool_id: str, request: dict) -> JobRecord:
        validated = self.catalog.validate_request(tool_id, request)
        definition = self.catalog.describe(tool_id)
        job = await self.jobs.submit(tool_id, validated)
        await link_job_artifacts(
            self.db, job.id, definition, validated
        )
        await self.queue.put(job.id)
        return job

    async def cancel(self, job_id: str) -> JobRecord:
        async with self._cancel_lock:
            job = await self.jobs.get(job_id)
            if job.status is JobStatus.QUEUED:
                return await self.jobs.transition(
                    job_id, JobStatus.CANCELLED
                )
            if (
                job.status is not JobStatus.RUNNING
                or self.current_job_id != job_id
            ):
                raise InvalidTransition(
                    f"cannot cancel {job.status.value}"
                )
            await self.jobs.transition(
                job_id, JobStatus.CANCELLING
            )
            await self.supervisor.stop()
            output = self.workspace.job_root(job_id) / "output"
            if output.exists():
                shutil.rmtree(output)
            output.mkdir(parents=True, exist_ok=True)
            return await self.jobs.transition(
                job_id, JobStatus.CANCELLED
            )

    async def _run(self) -> None:
        while True:
            job_id = await self.queue.get()
            if job_id is None:
                self.queue.task_done()
                return
            try:
                job = await self.jobs.get(job_id)
                if job.status is JobStatus.CANCELLED:
                    continue
                try:
                    await self._execute(job)
                except Exception as error:
                    current = await self.jobs.get(job.id)
                    if current.status not in {
                        JobStatus.CANCELLED,
                        JobStatus.CANCELLING,
                    }:
                        await self.jobs.transition(
                            job.id,
                            JobStatus.FAILED,
                            error_code="WORKER_CRASHED",
                            error_message=str(error),
                        )
            finally:
                self.current_job_id = None
                self.queue.task_done()

    async def _execute(self, job: JobRecord) -> None:
        definition = self.catalog.describe(job.tool_id)
        await self.jobs.transition(job.id, JobStatus.STARTING)
        parameters = await resolve_worker_parameters(
            definition,
            job.request,
            self.artifacts,
            self.workspace,
            job.id,
        )
        await self.jobs.transition(job.id, JobStatus.RUNNING)
        self.current_job_id = job.id
        try:
            response = await self.supervisor.execute(
                job.id,
                job.tool_id,
                parameters,
                definition.timeout_seconds,
            )
            worker_result = response.get("result", response)
            declared_paths = [
                Path(value)
                for value in worker_result.pop("outputs", [])
            ]
            output_ids = []
            for path in declared_paths:
                artifact = await self.artifacts.register_output(
                    path, path.name, "application/octet-stream"
                )
                output_ids.append(artifact.id)
            await link_job_artifacts(
                self.db,
                job.id,
                definition,
                job.request,
                output_ids,
            )
            safe_result = {
                **worker_result,
                "output_artifact_ids": output_ids,
            }
            await self.jobs.transition(
                job.id,
                JobStatus.SUCCEEDED,
                result=safe_result,
            )
        except TimeoutError:
            if (await self.jobs.get(job.id)).status in {
                JobStatus.CANCELLING,
                JobStatus.CANCELLED,
            }:
                return
            await self.jobs.transition(
                job.id,
                JobStatus.TIMED_OUT,
                error_code="JOB_TIMEOUT",
                error_message="ArcPy job exceeded its deadline",
            )
        except WorkerExecutionError as error:
            if (await self.jobs.get(job.id)).status in {
                JobStatus.CANCELLING,
                JobStatus.CANCELLED,
            }:
                return
            await self.jobs.transition(
                job.id,
                JobStatus.FAILED,
                error_code=error.error_code,
                error_message=str(error),
            )
        except Exception as error:
            if (await self.jobs.get(job.id)).status in {
                JobStatus.CANCELLING,
                JobStatus.CANCELLED,
            }:
                return
            await self.jobs.transition(
                job.id,
                JobStatus.FAILED,
                error_code="WORKER_CRASHED",
                error_message=str(error),
            )
