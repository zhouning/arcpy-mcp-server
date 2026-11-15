import json
import subprocess
from pathlib import Path

from tests.arcpy.process_helpers import stop_process


ARCPY_PYTHON = Path(
    r"D:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"
)
WORKER = Path("src/arcpy_mcp_server/worker/main.py")

# 20 x 20 cells of 100 m in Hong Kong 1980 Grid (EPSG:2326, datum HK1980)
SETUP = """
import arcpy, numpy, sys
values = numpy.arange(400, dtype="float32").reshape(20, 20)
raster = arcpy.NumPyArrayToRaster(values, arcpy.Point(830000, 815000), 100, 100)
raster.save(sys.argv[1])
arcpy.management.DefineProjection(sys.argv[1], arcpy.SpatialReference(2326))
"""


def _make_raster(path: Path) -> None:
    subprocess.run([str(ARCPY_PYTHON), "-c", SETUP, str(path)], check=True,
                   capture_output=True, text=True)


def _run(requests: list[dict]) -> list[dict]:
    process = subprocess.Popen([str(ARCPY_PYTHON), "-u", str(WORKER)], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out = []
    try:
        json.loads(process.stdout.readline())               # ready
        for request in requests:
            process.stdin.write(json.dumps(request) + "\n")
            process.stdin.flush()
            json.loads(process.stdout.readline())           # started
            out.append(json.loads(process.stdout.readline()))
    finally:
        stop_process(process)
    return out


def test_project_raster_across_datums_with_transform_and_registration_point(tmp_path):
    src = tmp_path / "hk.tif"
    _make_raster(src)
    work = tmp_path / "work"
    work.mkdir()
    out = tmp_path / "wgs84.tif"
    [result] = _run([{
        "type": "execute", "job_id": "job-project", "tool_id": "raster.project",
        "parameters": {"input_path": str(src), "output_path": str(out),
                       "output_spatial_reference": 4326, "resampling_type": "BILINEAR",
                       "cell_size": 0.001, "geographic_transform": "Hong_Kong_1980_To_WGS_1984_1",
                       "registration_point": "114.0 22.0", "work_dir": str(work)},
    }])
    assert result["type"] == "result", result
    assert out.exists()


def test_extract_by_mask_accepts_a_geojson_mask(tmp_path):
    src = tmp_path / "hk.tif"
    _make_raster(src)
    work = tmp_path / "work"
    work.mkdir()
    mask = tmp_path / "mask.geojson"
    ring = [[830500, 815500], [831500, 815500], [831500, 816500], [830500, 816500], [830500, 815500]]
    mask.write_text(json.dumps({
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::2326"}},
        "features": [{"type": "Feature", "properties": {},
                      "geometry": {"type": "Polygon", "coordinates": [ring]}}],
    }))
    out = tmp_path / "masked.tif"
    [result] = _run([{
        "type": "execute", "job_id": "job-mask", "tool_id": "raster.extract_by_mask",
        "parameters": {"input_path": str(src), "mask_path": str(mask), "output_path": str(out),
                       "work_dir": str(work)},
    }])
    assert result["type"] == "result", result
    assert out.exists()
