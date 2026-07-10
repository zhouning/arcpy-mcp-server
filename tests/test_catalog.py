from pathlib import Path

import pytest

from arcpy_mcp_server.catalog import ToolCatalog


CATALOG = Path("config/tool_catalog.yaml")


def test_catalog_search_and_parameter_validation():
    catalog = ToolCatalog.load(CATALOG)

    matches = catalog.search("buffer")
    validated = catalog.validate_request(
        "vector.buffer",
        {
            "input_artifact_id": "artifact-1",
            "input_path": "roads.shp",
            "output_name": "roads_buffer.shp",
            "distance": "50 Meters",
        },
    )

    assert matches[0].id == "vector.buffer"
    assert validated["distance"] == "50 Meters"
    assert catalog.describe("vector.buffer").inputs[0].path_field == (
        "input_path"
    )


def test_catalog_rejects_unknown_parameters_and_tool_ids():
    catalog = ToolCatalog.load(CATALOG)

    with pytest.raises(ValueError):
        catalog.validate_request(
            "vector.buffer", {"python_code": "import os"}
        )
    with pytest.raises(ValueError):
        catalog.validate_request("python.eval", {})


def test_catalog_contains_confirmed_first_release_tools():
    catalog = ToolCatalog.load(CATALOG)

    expected = {
        "inspect.dataset",
        "vector.buffer",
        "vector.clip",
        "vector.dissolve",
        "vector.intersect",
        "vector.union",
        "vector.spatial_join",
        "vector.project",
        "vector.merge",
        "vector.check_geometry",
        "vector.repair_geometry",
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

    assert set(catalog.tools) == expected
