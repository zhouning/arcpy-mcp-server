import json
from typing import Any, Literal

from pydantic import BaseModel, Field


class WorkerRequest(BaseModel):
    type: Literal["execute"] = "execute"
    job_id: str
    tool_id: str
    parameters: dict[str, Any]

    def to_line(self) -> bytes:
        return (self.model_dump_json() + "\n").encode()


class WorkerMessage(BaseModel):
    type: Literal["ready", "event", "result", "error"]
    job_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_line(cls, line: bytes) -> "WorkerMessage":
        return cls.model_validate(json.loads(line.decode()))
