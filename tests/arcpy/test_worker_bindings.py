import subprocess
from pathlib import Path


ARCPY_PYTHON = Path(
    r"D:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"
)
WORKER_DIRECTORY = Path("src/arcpy_mcp_server/worker").resolve()


def test_worker_exposes_confirmed_raster_map_and_dl_bindings():
    expected = {
        "raster.clip",
        "raster.project",
        "raster.resample",
        "raster.extract_by_mask",
        "raster.slope",
        "raster.zonal_statistics",
        "raster.mosaic",
        "map.inspect_aprx",
        "map.export_layout",
        "dl.detect_objects",
        "dl.classify_pixels",
        "dl.classify_objects",
        "dl.detect_change",
        "dl.translate_pixels",
        "dl.export_training_data",
    }
    script = (
        "import json, sys; "
        f"sys.path.insert(0, {str(WORKER_DIRECTORY)!r}); "
        "from tool_bindings import BINDINGS; "
        "print(json.dumps(sorted(BINDINGS)))"
    )

    result = subprocess.run(
        [str(ARCPY_PYTHON), "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )

    assert expected <= set(__import__("json").loads(result.stdout))


def test_arcgis_deep_learning_tools_exist_without_training_binding():
    script = """
import arcpy
import json
import sys

sys.path.insert(0, sys.argv[1])
from tool_bindings import BINDINGS

names = [
    "DetectObjectsUsingDeepLearning",
    "ClassifyPixelsUsingDeepLearning",
    "ClassifyObjectsUsingDeepLearning",
    "DetectChangeUsingDeepLearning",
    "TranslatePixelsUsingDeepLearning",
    "ExportTrainingDataForDeepLearning",
]
print(json.dumps({
    "available": {name: hasattr(arcpy.ia, name) for name in names},
    "has_training": "dl.train_model" in BINDINGS,
    "has_superresolution": "dl.superresolution" in BINDINGS,
}))
"""
    result = subprocess.run(
        [str(ARCPY_PYTHON), "-c", script, str(WORKER_DIRECTORY)],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = __import__("json").loads(result.stdout)

    assert all(payload["available"].values())
    assert not payload["has_training"]
    assert not payload["has_superresolution"]
