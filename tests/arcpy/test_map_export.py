import os
from pathlib import Path

import pytest


def test_map_export_fixture_is_explicitly_required():
    fixture = os.environ.get("ARCPY_MCP_APRX_TEST_FIXTURE")
    if not fixture:
        pytest.skip(
            "ArcPy cannot create a new APRX without a template fixture"
        )
    assert Path(fixture).is_file()
