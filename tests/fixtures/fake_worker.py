import json
import os
import sys
import time


def emit(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


emit({"type": "ready", "payload": {"worker": "fake", "pid": os.getpid()}})
for line in sys.stdin:
    request = json.loads(line)
    job_id = request["job_id"]
    tool_id = request["tool_id"]
    if tool_id == "hang":
        time.sleep(60)
    elif tool_id == "malformed":
        sys.stdout.write("not-json\n")
        sys.stdout.flush()
    elif tool_id == "partial_crash":
        with open(request["parameters"]["output_path"], "wb") as output:
            output.write(b"partial")
        os._exit(8)
    elif tool_id == "delay":
        emit(
            {
                "type": "event",
                "job_id": job_id,
                "payload": {
                    "stage": "started",
                    "path": request["parameters"].get("work_dir", ""),
                },
            }
        )
        time.sleep(0.25)
        emit(
            {
                "type": "result",
                "job_id": job_id,
                "payload": {
                    "ok": True,
                    "result": {
                        "outputs": [],
                        "value": request["parameters"].get("value"),
                    },
                    "messages": {},
                },
            }
        )
    elif tool_id == "fail":
        emit(
            {
                "type": "error",
                "job_id": job_id,
                "payload": {
                    "error_code": "ARCPY_EXECUTION_FAILED",
                    "message": "requested fake failure",
                },
            }
        )
    elif tool_id == "crash":
        os._exit(7)
    else:
        emit(
            {
                "type": "result",
                "job_id": job_id,
                "payload": request["parameters"],
            }
        )
