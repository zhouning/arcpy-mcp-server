from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ArtifactState(StrEnum):
    INCOMPLETE = "incomplete"
    READY = "ready"
    DELETED = "deleted"


class JobStatus(StrEnum):
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class ArtifactRecord(BaseModel):
    id: str
    logical_name: str
    state: ArtifactState
    expected_size: int
    expected_sha256: str
    committed_size: int = 0
    actual_sha256: str | None = None
    media_type: str
    storage_path: str | None = None
    content_root: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class JobRecord(BaseModel):
    id: str
    tool_id: str
    status: JobStatus
    request: dict[str, Any]
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
