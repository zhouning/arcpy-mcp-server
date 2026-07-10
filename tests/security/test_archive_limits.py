import stat
import zipfile

import pytest

from arcpy_mcp_server.workspace import UnsafeArchiveError, Workspace


def create_zip(path, entries):
    with zipfile.ZipFile(path, "w") as archive:
        for name, payload in entries:
            archive.writestr(name, payload)


def test_archive_entry_count_is_limited(tmp_path):
    archive = tmp_path / "many.zip"
    create_zip(archive, [(f"{index}.txt", b"x") for index in range(3)])
    workspace = Workspace(tmp_path / "workspace", 1024, 2, 4)

    with pytest.raises(UnsafeArchiveError, match="too many entries"):
        workspace.extract_zip(archive, tmp_path / "out")


def test_archive_expanded_size_is_limited(tmp_path):
    archive = tmp_path / "large.zip"
    create_zip(archive, [("large.bin", b"x" * 11)])
    workspace = Workspace(tmp_path / "workspace", 10, 10, 4)

    with pytest.raises(UnsafeArchiveError, match="size limit"):
        workspace.extract_zip(archive, tmp_path / "out")


def test_archive_depth_and_symlinks_are_rejected(tmp_path):
    deep = tmp_path / "deep.zip"
    create_zip(deep, [("one/two/three.txt", b"x")])
    workspace = Workspace(tmp_path / "workspace", 1024, 10, 2)
    with pytest.raises(UnsafeArchiveError, match="nesting limit"):
        workspace.extract_zip(deep, tmp_path / "deep-out")

    link_archive = tmp_path / "link.zip"
    link = zipfile.ZipInfo("link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(link_archive, "w") as archive:
        archive.writestr(link, "target")
    with pytest.raises(UnsafeArchiveError, match="symlinks"):
        workspace.extract_zip(link_archive, tmp_path / "link-out")

