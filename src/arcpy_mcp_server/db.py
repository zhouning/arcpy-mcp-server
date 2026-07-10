import json
from pathlib import Path

import aiosqlite

from .models import ArtifactRecord, JobRecord, JobStatus, utc_now


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS job_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS job_artifacts (
    job_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    role TEXT NOT NULL,
    PRIMARY KEY (job_id, artifact_id, role)
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.connection: aiosqlite.Connection | None = None

    async def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = await aiosqlite.connect(self.path)
        await self.connection.executescript(SCHEMA)
        await self.connection.commit()

    async def stop(self) -> None:
        if self.connection is not None:
            await self.connection.close()
            self.connection = None

    def _conn(self) -> aiosqlite.Connection:
        if self.connection is None:
            raise RuntimeError("database is not started")
        return self.connection

    async def insert_artifact(self, record: ArtifactRecord) -> None:
        await self._conn().execute(
            "INSERT INTO artifacts(id, payload) VALUES (?, ?)",
            (record.id, record.model_dump_json()),
        )
        await self._conn().commit()

    async def update_artifact(self, record: ArtifactRecord) -> None:
        await self._conn().execute(
            "UPDATE artifacts SET payload = ? WHERE id = ?",
            (record.model_dump_json(), record.id),
        )
        await self._conn().commit()

    async def get_artifact(self, artifact_id: str) -> ArtifactRecord | None:
        cursor = await self._conn().execute(
            "SELECT payload FROM artifacts WHERE id = ?",
            (artifact_id,),
        )
        row = await cursor.fetchone()
        return ArtifactRecord.model_validate_json(row[0]) if row else None

    async def list_artifacts(self) -> list[ArtifactRecord]:
        cursor = await self._conn().execute(
            "SELECT payload FROM artifacts ORDER BY rowid DESC"
        )
        return [ArtifactRecord.model_validate_json(row[0]) async for row in cursor]

    async def insert_job(self, record: JobRecord) -> None:
        await self._conn().execute(
            "INSERT INTO jobs(id, status, payload) VALUES (?, ?, ?)",
            (record.id, record.status.value, record.model_dump_json()),
        )
        await self._conn().commit()

    async def update_job(self, record: JobRecord) -> None:
        record.updated_at = utc_now()
        await self._conn().execute(
            "UPDATE jobs SET status = ?, payload = ? WHERE id = ?",
            (record.status.value, record.model_dump_json(), record.id),
        )
        await self._conn().commit()

    async def get_job(self, job_id: str) -> JobRecord | None:
        cursor = await self._conn().execute(
            "SELECT payload FROM jobs WHERE id = ?",
            (job_id,),
        )
        row = await cursor.fetchone()
        return JobRecord.model_validate_json(row[0]) if row else None

    async def list_jobs(self, limit: int = 100) -> list[JobRecord]:
        cursor = await self._conn().execute(
            "SELECT payload FROM jobs ORDER BY rowid DESC LIMIT ?",
            (limit,),
        )
        return [JobRecord.model_validate_json(row[0]) async for row in cursor]

    async def list_jobs_by_status(
        self, statuses: set[JobStatus]
    ) -> list[JobRecord]:
        placeholders = ",".join("?" for _ in statuses)
        cursor = await self._conn().execute(
            f"SELECT payload FROM jobs WHERE status IN ({placeholders})",
            tuple(status.value for status in statuses),
        )
        return [JobRecord.model_validate_json(row[0]) async for row in cursor]

    async def append_event(
        self, job_id: str, event_type: str, payload: dict
    ) -> None:
        await self._conn().execute(
            "INSERT INTO job_events(job_id, event_type, payload, created_at) "
            "VALUES (?, ?, ?, ?)",
            (job_id, event_type, json.dumps(payload), utc_now().isoformat()),
        )
        await self._conn().commit()

    async def list_events(self, job_id: str) -> list[dict]:
        cursor = await self._conn().execute(
            "SELECT event_type, payload, created_at FROM job_events "
            "WHERE job_id = ? ORDER BY sequence",
            (job_id,),
        )
        return [
            {
                "event_type": row[0],
                "payload": json.loads(row[1]),
                "created_at": row[2],
            }
            async for row in cursor
        ]

    async def link_artifact(
        self, job_id: str, artifact_id: str, role: str
    ) -> None:
        await self._conn().execute(
            "INSERT OR IGNORE INTO job_artifacts(job_id, artifact_id, role) "
            "VALUES (?, ?, ?)",
            (job_id, artifact_id, role),
        )
        await self._conn().commit()

    async def artifact_has_active_job(self, artifact_id: str) -> bool:
        active = (
            JobStatus.QUEUED.value,
            JobStatus.STARTING.value,
            JobStatus.RUNNING.value,
            JobStatus.CANCELLING.value,
        )
        cursor = await self._conn().execute(
            "SELECT 1 FROM job_artifacts ja JOIN jobs j ON j.id = ja.job_id "
            "WHERE ja.artifact_id = ? AND j.status IN (?, ?, ?, ?) LIMIT 1",
            (artifact_id, *active),
        )
        return await cursor.fetchone() is not None
