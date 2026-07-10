import json
import sys

from executor import execute
from health import collect_health


def emit(message):
    sys.stdout.write(
        json.dumps(message, ensure_ascii=True, default=str) + "\n"
    )
    sys.stdout.flush()


emit({"type": "ready", "payload": collect_health()})
for line in sys.stdin:
    request = json.loads(line)
    job_id = request["job_id"]
    emit(
        {
            "type": "event",
            "job_id": job_id,
            "payload": {"stage": "started"},
        }
    )
    response = execute(request["tool_id"], request["parameters"])
    if response["ok"]:
        emit(
            {
                "type": "result",
                "job_id": job_id,
                "payload": response,
            }
        )
    else:
        emit(
            {
                "type": "error",
                "job_id": job_id,
                "payload": response,
            }
        )
