"""Tests for UI logic that doesn't require wx."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


from accessitransfer.protocols import RemoteFile


class TestRemoteFileDisplay:
    """Test RemoteFile display properties used by the UI."""

    def test_display_size_bytes(self):
        f = RemoteFile(name="a.txt", path="/a.txt", size=500)
        assert f.display_size == "500 B"

    def test_display_size_kb(self):
        f = RemoteFile(name="a.txt", path="/a.txt", size=2048)
        assert "KB" in f.display_size

    def test_display_size_mb(self):
        f = RemoteFile(name="a.txt", path="/a.txt", size=5 * 1024 * 1024)
        assert "MB" in f.display_size

    def test_display_size_gb(self):
        f = RemoteFile(name="a.txt", path="/a.txt", size=2 * 1024 * 1024 * 1024)
        assert "GB" in f.display_size

    def test_display_size_dir(self):
        f = RemoteFile(name="docs", path="/docs", is_dir=True)
        assert f.display_size == "<DIR>"

    def test_display_modified(self):
        f = RemoteFile(name="a.txt", path="/a.txt", modified=datetime(2025, 1, 15, 10, 30))
        assert f.display_modified == "2025-01-15 10:30"

    def test_display_modified_none(self):
        f = RemoteFile(name="a.txt", path="/a.txt")
        assert f.display_modified == ""


class TestFileSorting:
    """Test file sorting logic used by the main window."""

    def _make_files(self):
        return [
            RemoteFile(name="beta.txt", path="/beta.txt", size=200, modified=datetime(2025, 2, 1)),
            RemoteFile(name="alpha", path="/alpha", is_dir=True, modified=datetime(2025, 1, 1)),
            RemoteFile(name="gamma.py", path="/gamma.py", size=100, modified=datetime(2025, 3, 1)),
        ]

    def test_sort_by_name_dirs_first(self):
        files = self._make_files()
        files.sort(key=lambda f: (not f.is_dir, f.name.lower()))
        assert files[0].name == "alpha"
        assert files[1].name == "beta.txt"

    def test_sort_by_size(self):
        files = self._make_files()
        files.sort(key=lambda f: (not f.is_dir, f.size))
        assert files[0].name == "alpha"  # dir first
        assert files[1].name == "gamma.py"  # 100
        assert files[2].name == "beta.txt"  # 200

    def test_sort_by_type(self):
        files = self._make_files()
        files.sort(key=lambda f: (not f.is_dir, Path(f.name).suffix.lower()))
        assert files[0].name == "alpha"  # dir first

    def test_filter_hidden(self):
        files = [
            RemoteFile(name=".hidden", path="/.hidden"),
            RemoteFile(name="visible.txt", path="/visible.txt"),
        ]
        visible = [f for f in files if not f.name.startswith(".")]
        assert len(visible) == 1
        assert visible[0].name == "visible.txt"

    def test_filter_by_pattern(self):
        files = [
            RemoteFile(name="readme.md", path="/readme.md"),
            RemoteFile(name="setup.py", path="/setup.py"),
            RemoteFile(name="test.py", path="/test.py"),
        ]
        pattern = ".py"
        filtered = [f for f in files if pattern in f.name.lower()]
        assert len(filtered) == 2


class TestTransferItem:
    """Test TransferItem data class."""

    def test_progress_pct(self):
        from accessitransfer.dialogs.transfer import TransferItem

        item = TransferItem(total_bytes=1000, transferred_bytes=500)
        assert item.progress_pct == 50

    def test_progress_pct_zero_total(self):
        from accessitransfer.dialogs.transfer import TransferItem

        item = TransferItem(total_bytes=0)
        assert item.progress_pct == 0

    def test_display_status_in_progress(self):
        from accessitransfer.dialogs.transfer import TransferItem, TransferStatus

        item = TransferItem(
            total_bytes=100, transferred_bytes=75, status=TransferStatus.IN_PROGRESS
        )
        assert item.display_status == "75%"

    def test_display_status_completed(self):
        from accessitransfer.dialogs.transfer import TransferItem, TransferStatus

        item = TransferItem(status=TransferStatus.COMPLETED)
        assert item.display_status == "completed"

    def test_cancel_event(self):
        from accessitransfer.dialogs.transfer import TransferItem

        item = TransferItem()
        assert not item.cancel_event.is_set()
        item.cancel_event.set()
        assert item.cancel_event.is_set()
