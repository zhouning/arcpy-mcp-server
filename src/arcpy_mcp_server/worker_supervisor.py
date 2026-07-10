import asyncio
import inspect
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from pydantic import ValidationError

from .worker_protocol import WorkerMessage, WorkerRequest


class WorkerCrashed(RuntimeError):
    pass


class WorkerExecutionError(RuntimeError):
    def __init__(self, error_code: str, message: str, payload: dict):
        super().__init__(message)
        self.error_code = error_code
        self.payload = payload


class WorkerSupervisor:
    def __init__(
        self,
        executable: Path,
        script: Path,
        event_callback: Callable[[WorkerMessage], object] | None = None,
    ):
        self.executable = executable
        self.script = script
        self.event_callback = event_callback
        self.process: asyncio.subprocess.Process | None = None
        self.capabilities: dict = {}
        self._execute_lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()
        self._stderr_task: asyncio.Task | None = None

    @property
    def pid(self) -> int | None:
        return self.process.pid if self.process else None

    async def start(self) -> None:
        async with self._lifecycle_lock:
            await self._start_unlocked()

    async def _start_unlocked(self) -> None:
        if self.process and self.process.returncode is None:
            return
        self.process = await asyncio.create_subprocess_exec(
            str(self.executable),
            "-u",
            str(self.script),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        try:
            message = await asyncio.wait_for(
                self._read_message(), timeout=120
            )
            if message.type != "ready":
                raise WorkerCrashed(
                    "worker did not send a ready message"
                )
            self.capabilities = message.payload
        except Exception:
            await self.stop()
            raise

    async def stop(self) -> None:
        async with self._lifecycle_lock:
            await self._stop_unlocked()

    async def _stop_unlocked(self) -> None:
        process = self.process
        stderr_task = self._stderr_task
        self.process = None
        self._stderr_task = None
        self.capabilities = {}
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except TimeoutError:
                process.kill()
                await process.wait()
        if stderr_task is not None:
            stderr_task.cancel()
            with suppress(asyncio.CancelledError):
                await stderr_task

    async def restart(self) -> None:
        async with self._lifecycle_lock:
            await self._stop_unlocked()
            await self._start_unlocked()

    async def _read_message(self) -> WorkerMessage:
        if self.process is None or self.process.stdout is None:
            raise WorkerCrashed("worker is not running")
        line = await self.process.stdout.readline()
        if not line:
            raise WorkerCrashed("worker closed stdout")
        try:
            return WorkerMessage.from_line(line)
        except (ValueError, ValidationError) as error:
            raise WorkerCrashed("worker emitted invalid JSONL") from error

    async def _drain_stderr(self) -> None:
        if self.process is None or self.process.stderr is None:
            return
        while await self.process.stderr.readline():
            pass

    async def _emit_event(self, message: WorkerMessage) -> None:
        if self.event_callback is None:
            return
        result = self.event_callback(message)
        if inspect.isawaitable(result):
            await result

    async def execute(
        self,
        job_id: str,
        tool_id: str,
        parameters: dict,
        timeout: float,
    ) -> dict:
        async with self._execute_lock:
            await self.start()
            assert self.process is not None
            assert self.process.stdin is not None
            request = WorkerRequest(
                job_id=job_id,
                tool_id=tool_id,
                parameters=parameters,
            )
            self.process.stdin.write(request.to_line())
            await self.process.stdin.drain()
            try:
                async with asyncio.timeout(timeout):
                    while True:
                        message = await self._read_message()
                        if message.job_id not in (None, job_id):
                            raise WorkerCrashed(
                                "worker returned a mismatched job ID"
                            )
                        if message.type == "event":
                            await self._emit_event(message)
                        elif message.type == "result":
                            return message.payload
                        elif message.type == "error":
                            raise WorkerExecutionError(
                                message.payload.get(
                                    "error_code",
                                    "ARCPY_EXECUTION_FAILED",
                                ),
                                message.payload.get(
                                    "message", "worker error"
                                ),
                                message.payload,
                            )
            except WorkerExecutionError:
                raise
            except TimeoutError:
                await self.restart()
                raise
            except Exception:
                await self.restart()
                raise
