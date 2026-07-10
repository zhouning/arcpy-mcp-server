import json
import subprocess
from pathlib import Path


ARCPY_PYTHON = Path(
    r"D:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"
)
WORKER = Path("src/arcpy_mcp_server/worker/main.py")


def test_worker_calculates_slope_from_real_raster(tmp_path):
    input_raster = tmp_path / "elevation.tif"
    output_raster = tmp_path / "slope.tif"
    work = tmp_path / "work"
    work.mkdir()
    setup = """
import arcpy
import numpy
import sys

values = numpy.array(
    [[1, 2, 3], [2, 3, 4], [3, 4, 5]],
    dtype="float32",
)
raster = arcpy.NumPyArrayToRaster(
    values,
    arcpy.Point(0, 0),
    10,
    10,
)
raster.save(sys.argv[1])
"""
    subprocess.run(
        [str(ARCPY_PYTHON), "-c", setup, str(input_raster)],
        check=True,
        capture_output=True,
        text=True,
    )
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
            "job_id": "job-raster",
            "tool_id": "raster.slope",
            "parameters": {
                "input_path": str(input_raster),
                "output_path": str(output_raster),
                "output_measurement": "DEGREE",
                "work_dir": str(work),
            },
        }
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.flush()
        json.loads(process.stdout.readline())
        result = json.loads(process.stdout.readline())
    finally:
        process.terminate()
        process.wait(timeout=10)

    assert result["type"] == "result"
    assert output_raster.exists()
