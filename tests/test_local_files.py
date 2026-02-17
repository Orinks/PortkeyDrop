"""Tests for local file operations."""

from __future__ import annotations

import os

import pytest

from portkeydrop.local_files import (
    delete_local,
    list_local_dir,
    mkdir_local,
    navigate_local,
    parent_local,
    rename_local,
)


class TestListLocalDir:
    def test_list_empty_dir(self, tmp_path):
        files = list_local_dir(tmp_path)
        assert files == []

    def test_list_files_and_dirs(self, tmp_path):
        (tmp_path / "file.txt").write_text("hello")
        (tmp_path / "subdir").mkdir()
        files = list_local_dir(tmp_path)
        names = {f.name for f in files}
        assert names == {"file.txt", "subdir"}

    def test_file_attributes(self, tmp_path):
        (tmp_path / "test.txt").write_text("data")
        files = list_local_dir(tmp_path)
        f = files[0]
        assert f.name == "test.txt"
        assert f.size == 4
        assert not f.is_dir
        assert f.modified is not None
        assert f.permissions  # non-empty

    def test_dir_attributes(self, tmp_path):
        (tmp_path / "mydir").mkdir()
        files = list_local_dir(tmp_path)
        d = files[0]
        assert d.name == "mydir"
        assert d.is_dir
        assert d.size == 0

    def test_hidden_files_included(self, tmp_path):
        (tmp_path / ".hidden").write_text("secret")
        files = list_local_dir(tmp_path)
        assert len(files) == 1
        assert files[0].name == ".hidden"

    def test_path_is_absolute(self, tmp_path):
        (tmp_path / "a.txt").write_text("x")
        files = list_local_dir(tmp_path)
        assert os.path.isabs(files[0].path)

    def test_permission_error_dir(self, tmp_path):
        # Should not raise, returns empty
        bad_dir = tmp_path / "noaccess"
        bad_dir.mkdir()
        bad_dir.chmod(0o000)
        try:
            files = list_local_dir(bad_dir)
            assert files == []
        finally:
            bad_dir.chmod(0o755)


class TestNavigateLocal:
    def test_navigate_into_subdir(self, tmp_path):
        sub = tmp_path / "child"
        sub.mkdir()
        result = navigate_local(tmp_path, "child")
        assert result == sub.resolve()

    def test_navigate_nonexistent_raises(self, tmp_path):
        with pytest.raises(NotADirectoryError):
            navigate_local(tmp_path, "nonexistent")

    def test_navigate_to_file_raises(self, tmp_path):
        (tmp_path / "file.txt").write_text("x")
        with pytest.raises(NotADirectoryError):
            navigate_local(tmp_path, "file.txt")


class TestParentLocal:
    def test_parent_of_subdir(self, tmp_path):
        sub = tmp_path / "child"
        sub.mkdir()
        result = parent_local(sub)
        assert result == tmp_path.resolve()

    def test_parent_of_root(self):
        result = parent_local("/")
        assert str(result) == "/"


class TestDeleteLocal:
    def test_delete_file(self, tmp_path):
        f = tmp_path / "del.txt"
        f.write_text("bye")
        delete_local(f)
        assert not f.exists()

    def test_delete_dir(self, tmp_path):
        d = tmp_path / "deldir"
        d.mkdir()
        (d / "inner.txt").write_text("x")
        delete_local(d)
        assert not d.exists()

    def test_delete_nonexistent_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            delete_local(tmp_path / "nope.txt")


class TestRenameLocal:
    def test_rename_file(self, tmp_path):
        f = tmp_path / "old.txt"
        f.write_text("data")
        new = rename_local(f, "new.txt")
        assert new == tmp_path / "new.txt"
        assert new.exists()
        assert not f.exists()

    def test_rename_dir(self, tmp_path):
        d = tmp_path / "olddir"
        d.mkdir()
        new = rename_local(d, "newdir")
        assert new.exists()
        assert new.is_dir()


class TestMkdirLocal:
    def test_create_dir(self, tmp_path):
        result = mkdir_local(tmp_path, "newdir")
        assert result.exists()
        assert result.is_dir()
        assert result.name == "newdir"

    def test_create_existing_raises(self, tmp_path):
        (tmp_path / "existing").mkdir()
        with pytest.raises(FileExistsError):
            mkdir_local(tmp_path, "existing")
