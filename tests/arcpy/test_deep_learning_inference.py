import os
from pathlib import Path

import pytest


def test_deep_learning_model_fixture_is_explicitly_required():
    model = os.environ.get("ARCPY_MCP_DL_TEST_MODEL")
    if not model:
        pytest.skip(
            "No compatible ArcGIS Pro 3.7.1 test model supplied"
        )
    assert Path(model).is_file()
