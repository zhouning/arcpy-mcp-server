import json
import subprocess
from pathlib import Path


ARCPY_PYTHON = Path(
    r"D:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"
)
WORKER = Path("src/arcpy_mcp_server/worker/main.py")


def test_worker_reports_arcgis_371_capabilities():
    process = subprocess.Popen(
        [str(ARCPY_PYTHON), "-u", str(WORKER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        ready = json.loads(process.stdout.readline())
    finally:
        process.terminate()
        process.wait(timeout=10)

    assert ready["type"] == "ready"
    assert ready["payload"]["install"]["Version"] == "3.7.1"
    assert ready["payload"]["product"] == "ArcInfo"
    assert ready["payload"]["extensions"]["Spatial"] in {
        "Available",
        "CheckedOut",
    }
    assert ready["payload"]["extensions"]["ImageAnalyst"] in {
        "Available",
        "CheckedOut",
    }
    assert ready["payload"]["processor_type"] == "CPU"
