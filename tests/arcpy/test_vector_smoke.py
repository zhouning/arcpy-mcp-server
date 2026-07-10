import json
import subprocess
from pathlib import Path

import pytest


ARCPY_PYTHON = Path(
    r"D:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"
)
WORKER = Path("src/arcpy_mcp_server/worker/main.py")


@pytest.fixture
def point_feature_class(tmp_path):
    geodatabase = tmp_path / "input.gdb"
    feature_class = geodatabase / "points"
    setup = """
import arcpy
import sys

root, geodatabase, feature_class = sys.argv[1:4]
arcpy.management.CreateFileGDB(root, geodatabase)
arcpy.management.CreateFeatureclass(
    feature_class.rsplit("\\\\", 1)[0],
    feature_class.rsplit("\\\\", 1)[1],
    "POINT",
    spatial_reference=4326,
)
with arcpy.da.InsertCursor(feature_class, ["SHAPE@XY"]) as cursor:
    cursor.insertRow([(121.0, 31.0)])
    cursor.insertRow([(121.001, 31.001)])
"""
    subprocess.run(
        [
            str(ARCPY_PYTHON),
            "-c",
            setup,
            str(tmp_path),
            geodatabase.name,
            str(feature_class),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    yield feature_class
    cleanup = (
        "import arcpy, sys; "
        "arcpy.management.Delete(sys.argv[1]) "
        "if arcpy.Exists(sys.argv[1]) else None"
    )
    subprocess.run(
        [str(ARCPY_PYTHON), "-c", cleanup, str(geodatabase)],
        check=True,
        capture_output=True,
        text=True,
    )


def test_worker_buffers_two_features(point_feature_class, tmp_path):
    output = tmp_path / "buffer.shp"
    work = tmp_path / "work"
    work.mkdir()
    process = subprocess.Popen(
        [str(ARCPY_PYTHON), "-u", str(WORKER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        json.loads(process.stdout.readline())
        request = {
            "type": "execute",
            "job_id": "job-vector",
            "tool_id": "vector.buffer",
            "parameters": {
                "input_path": str(point_feature_class),
                "output_path": str(output),
                "distance": "10 Meters",
                "work_dir": str(work),
            },
        }
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.flush()
        event = json.loads(process.stdout.readline())
        result = json.loads(process.stdout.readline())
    finally:
        process.terminate()
        process.wait(timeout=10)

    assert event["type"] == "event"
    assert result["type"] == "result"
    assert result["payload"]["result"]["count"] == 2
    assert output.exists()
