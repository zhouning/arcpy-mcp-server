import pytest

from arcpy_mcp_server.workspace import Workspace


@pytest.mark.parametrize(
    "relative_path",
    [
        "../outside.txt",
        "..\\outside.txt",
        "%2e%2e/outside.txt",
        "%252e%252e/outside.txt",
        "C:\\Windows\\system.ini",
        "\\\\server\\share\\data.gdb",
        "roads.shp:secret",
    ],
)
def test_workspace_rejects_windows_and_encoded_path_attacks(
    tmp_path, relative_path
):
    workspace = Workspace(tmp_path / "workspace", 1024, 10, 4)

    with pytest.raises(ValueError):
        workspace.resolve_relative(workspace.root, relative_path)

