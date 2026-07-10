import sys
from pathlib import Path

import pytest

from arcpy_mcp_server.worker_supervisor import (
    WorkerExecutionError,
    WorkerSupervisor,
)


FAKE_WORKER = Path("tests/fixtures/fake_worker.py")


async def test_supervisor_executes_and_restarts_after_timeout():
    supervisor = WorkerSupervisor(
        executable=Path(sys.executable),
        script=FAKE_WORKER,
    )
    await supervisor.start()
    result = await supervisor.execute(
        "job-1", "echo", {"value": 7}, timeout=2
    )
    assert result["value"] == 7

    first_pid = supervisor.pid
    with pytest.raises(TimeoutError):
        await supervisor.execute("job-2", "hang", {}, timeout=0.1)
    assert supervisor.pid != first_pid
    await supervisor.stop()


async def test_tool_error_does_not_restart_healthy_worker():
    supervisor = WorkerSupervisor(
        executable=Path(sys.executable),
        script=FAKE_WORKER,
    )
    await supervisor.start()
    first_pid = supervisor.pid

    with pytest.raises(WorkerExecutionError) as error:
        await supervisor.execute("job-1", "fail", {}, timeout=2)

    assert error.value.error_code == "ARCPY_EXECUTION_FAILED"
    assert supervisor.pid == first_pid
    await supervisor.stop()


async def test_process_crash_restarts_worker():
    supervisor = WorkerSupervisor(
        executable=Path(sys.executable),
        script=FAKE_WORKER,
    )
    await supervisor.start()
    first_pid = supervisor.pid

    with pytest.raises(Exception):
        await supervisor.execute("job-1", "crash", {}, timeout=2)

    assert supervisor.pid != first_pid
    await supervisor.stop()
