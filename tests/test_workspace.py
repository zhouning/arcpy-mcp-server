import stat
import zipfile

import pytest

from arcpy_mcp_server.workspace import UnsafeArchiveError, Workspace


def test_resolve_rejects_absolute_and_parent_paths(tmp_path):
    workspace = Workspace(tmp_path, 1024, 10, 4)

    with pytest.raises(ValueError):
        workspace.resolve_relative(tmp_path, "../outside.txt")
    with pytest.raises(ValueError):
        workspace.resolve_relative(tmp_path, "C:/Windows/system.ini")


def test_extract_zip_rejects_zip_slip(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../escape.txt", "blocked")

    workspace = Workspace(tmp_path, 1024, 10, 4)
    with pytest.raises(UnsafeArchiveError):
        workspace.extract_zip(archive, tmp_path / "out")


def test_extract_zip_rejects_symlink(tmp_path):
    archive = tmp_path / "symlink.zip"
    link = zipfile.ZipInfo("link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr(link, "target")

    workspace = Workspace(tmp_path, 1024, 10, 4)
    with pytest.raises(UnsafeArchiveError):
        workspace.extract_zip(archive, tmp_path / "out")
