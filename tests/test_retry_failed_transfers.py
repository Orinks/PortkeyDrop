"""Tests for retry failed transfers feature (issue #97)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests._wx_stub import load_module_with_fake_wx


@pytest.fixture
def transfer_module(monkeypatch):
    module, fake_wx = load_module_with_fake_wx("portkeydrop.dialogs.transfer", monkeypatch)
    return module, fake_wx


# ---------------------------------------------------------------------------
# TransferManager.retry() tests
# ---------------------------------------------------------------------------


class TestTransferManagerRetry:
    """Tests for TransferManager.retry() method."""

    def test_retry_failed_download_creates_new_item(self, transfer_module):
        module, _ = transfer_module
        tm = module.TransferManager()
        # Manually add a failed download
        item = module.TransferItem(
            id=1,
            direction=module.TransferDirection.DOWNLOAD,
            remote_path="/remote/file.txt",
            local_path="/local/file.txt",
            total_bytes=1024,
            status=module.TransferStatus.FAILED,
            error="Connection lost",
        )
        tm._transfers.append(item)
        tm._next_id = 2

        client = MagicMock()
        client.download = MagicMock()

        new_item = tm.retry(1, client)

        assert new_item is not None
        assert new_item.id == 2
        assert new_item.direction == module.TransferDirection.DOWNLOAD
        assert new_item.remote_path == "/remote/file.txt"
        assert new_item.local_path == "/local/file.txt"
        assert new_item.total_bytes == 1024

    def test_retry_failed_upload_creates_new_item(self, transfer_module):
        module, _ = transfer_module
        tm = module.TransferManager()
        item = module.TransferItem(
            id=1,
            direction=module.TransferDirection.UPLOAD,
            remote_path="/remote/file.txt",
            local_path="/local/file.txt",
            total_bytes=2048,
            status=module.TransferStatus.FAILED,
            error="Permission denied",
        )
        tm._transfers.append(item)
        tm._next_id = 2

        client = MagicMock()
        client.upload = MagicMock()

        new_item = tm.retry(1, client)

        assert new_item is not None
        assert new_item.id == 2
        assert new_item.direction == module.TransferDirection.UPLOAD
        assert new_item.remote_path == "/remote/file.txt"
        assert new_item.local_path == "/local/file.txt"

    def test_retry_non_failed_transfer_returns_none(self, transfer_module):
        module, _ = transfer_module
        tm = module.TransferManager()
        item = module.TransferItem(
            id=1,
            direction=module.TransferDirection.DOWNLOAD,
            remote_path="/remote/file.txt",
            local_path="/local/file.txt",
            status=module.TransferStatus.COMPLETED,
        )
        tm._transfers.append(item)
        tm._next_id = 2

        client = MagicMock()
        result = tm.retry(1, client)

        assert result is None

    def test_retry_nonexistent_transfer_returns_none(self, transfer_module):
        module, _ = transfer_module
        tm = module.TransferManager()
        tm._next_id = 1

        client = MagicMock()
        result = tm.retry(999, client)

        assert result is None

    def test_retry_queued_transfer_returns_none(self, transfer_module):
        module, _ = transfer_module
        tm = module.TransferManager()
        item = module.TransferItem(
            id=1,
            direction=module.TransferDirection.DOWNLOAD,
            remote_path="/remote/file.txt",
            local_path="/local/file.txt",
            status=module.TransferStatus.QUEUED,
        )
        tm._transfers.append(item)
        tm._next_id = 2

        client = MagicMock()
        result = tm.retry(1, client)

        assert result is None

    def test_retry_cancelled_transfer_returns_none(self, transfer_module):
        module, _ = transfer_module
        tm = module.TransferManager()
        item = module.TransferItem(
            id=1,
            direction=module.TransferDirection.DOWNLOAD,
            remote_path="/remote/file.txt",
            local_path="/local/file.txt",
            status=module.TransferStatus.CANCELLED,
        )
        tm._transfers.append(item)
        tm._next_id = 2

        client = MagicMock()
        result = tm.retry(1, client)

        assert result is None

    def test_retry_preserves_original_transfer(self, transfer_module):
        """Original failed transfer should remain in the list after retry."""
        module, _ = transfer_module
        tm = module.TransferManager()
        item = module.TransferItem(
            id=1,
            direction=module.TransferDirection.DOWNLOAD,
            remote_path="/remote/file.txt",
            local_path="/local/file.txt",
            total_bytes=512,
            status=module.TransferStatus.FAILED,
            error="Timeout",
        )
        tm._transfers.append(item)
        tm._next_id = 2

        client = MagicMock()
        client.download = MagicMock()

        tm.retry(1, client)

        # Both original and new transfer should be in the list
        assert len(tm.transfers) == 2
        assert tm.transfers[0].status == module.TransferStatus.FAILED
        assert tm.transfers[0].id == 1

    def test_retry_increments_id(self, transfer_module):
        """Each retry should get a unique, incrementing ID."""
        module, _ = transfer_module
        tm = module.TransferManager()
        item = module.TransferItem(
            id=1,
            direction=module.TransferDirection.DOWNLOAD,
            remote_path="/remote/file.txt",
            local_path="/local/file.txt",
            status=module.TransferStatus.FAILED,
        )
        tm._transfers.append(item)
        tm._next_id = 2

        client = MagicMock()
        client.download = MagicMock()

        new1 = tm.retry(1, client)
        # Mark the new one as failed too so we can retry the original again
        assert new1 is not None
        assert new1.id == 2

    def test_retry_creates_fresh_transfer_item(self, transfer_module):
        """Retried transfer should be a fresh TransferItem with reset fields."""
        module, _ = transfer_module
        tm = module.TransferManager()
        item = module.TransferItem(
            id=1,
            direction=module.TransferDirection.DOWNLOAD,
            remote_path="/remote/file.txt",
            local_path="/local/file.txt",
            total_bytes=1024,
            transferred_bytes=500,
            status=module.TransferStatus.FAILED,
            error="Network error",
        )
        tm._transfers.append(item)
        tm._next_id = 2

        client = MagicMock()
        client.download = MagicMock()

        # The retry calls add_download which spawns a thread;
        # verify the new item was created with correct params
        new_item = tm.retry(1, client)

        assert new_item is not None
        assert new_item.id == 2
        assert new_item.remote_path == "/remote/file.txt"
        assert new_item.local_path == "/local/file.txt"
        assert new_item.total_bytes == 1024
        # Original item remains failed
        assert item.status == module.TransferStatus.FAILED
        assert item.error == "Network error"


# ---------------------------------------------------------------------------
# TransferDialog retry button tests
# ---------------------------------------------------------------------------


def _make_wx_constants(fake_wx):
    """Set wx constants needed for create_transfer_dialog."""
    fake_wx.DEFAULT_DIALOG_STYLE = 0
    fake_wx.RESIZE_BORDER = 0
    fake_wx.CLOSE_BOX = 0
    fake_wx.ID_CLOSE = 999
    fake_wx.RIGHT = 0
    fake_wx.ALIGN_RIGHT = 0
    fake_wx.WXK_ESCAPE = 27
    fake_wx.VERTICAL = 0
    fake_wx.HORIZONTAL = 0


class _Dialog:
    """Minimal wx.Dialog stub for testing."""

    def __init__(self, parent, *args, **kwargs):
        self._parent = parent

    def Bind(self, *args, **kwargs):
        return None

    def SetSizer(self, *args, **kwargs):
        return None

    def SetName(self, *args, **kwargs):
        return None

    def Close(self):
        return None

    def GetParent(self):
        return self._parent

    def Destroy(self):
        return None


class TestTransferDialogRetryButton:
    """Tests for the Retry Selected button in TransferDialog."""

    def test_retry_button_exists(self, transfer_module):
        module, fake_wx = transfer_module
        _make_wx_constants(fake_wx)
        fake_wx.Dialog = _Dialog

        parent = MagicMock()
        manager = MagicMock()
        manager.transfers = []

        dialog = module.create_transfer_dialog(parent, manager)
        assert hasattr(dialog, "retry_btn")

    def test_retry_button_initially_disabled(self, transfer_module):
        module, fake_wx = transfer_module
        _make_wx_constants(fake_wx)
        fake_wx.Dialog = _Dialog

        parent = MagicMock()
        manager = MagicMock()
        manager.transfers = []

        dialog = module.create_transfer_dialog(parent, manager)
        dialog.retry_btn.Enable.assert_called_with(False)

    def test_retry_button_calls_retry_on_failed_transfer(self, transfer_module):
        module, fake_wx = transfer_module
        _make_wx_constants(fake_wx)
        fake_wx.Dialog = _Dialog

        parent = MagicMock()
        parent._client = MagicMock()
        parent._client.connected = True
        parent._client.cwd = "/remote"

        failed_transfer = SimpleNamespace(
            id=5,
            remote_path="/remote/report.csv",
            local_path="/tmp/report.csv",
            direction=module.TransferDirection.DOWNLOAD,
            progress_pct=0,
            display_status="failed",
            status=module.TransferStatus.FAILED,
        )
        manager = MagicMock()
        manager.transfers = [failed_transfer]
        manager.retry.return_value = SimpleNamespace(id=6)

        dialog = module.create_transfer_dialog(parent, manager)
        dialog.GetParent = MagicMock(return_value=parent)
        dialog.transfer_list.GetFirstSelected.return_value = 0
        dialog._refresh = MagicMock()

        dialog._on_retry(None)

        manager.retry.assert_called_once_with(5, parent._client)
        parent._announce.assert_called_once_with("Retrying download of report.csv")
        parent._update_status.assert_called_once_with("Retrying download of report.csv", "/remote")

    def test_retry_button_does_nothing_for_non_failed(self, transfer_module):
        module, fake_wx = transfer_module
        _make_wx_constants(fake_wx)
        fake_wx.Dialog = _Dialog

        parent = MagicMock()
        completed_transfer = SimpleNamespace(
            id=5,
            remote_path="/remote/report.csv",
            local_path="/tmp/report.csv",
            direction=module.TransferDirection.DOWNLOAD,
            status=module.TransferStatus.COMPLETED,
            progress_pct=100,
            display_status="completed",
        )
        manager = MagicMock()
        manager.transfers = [completed_transfer]

        dialog = module.create_transfer_dialog(parent, manager)
        dialog.GetParent = MagicMock(return_value=parent)
        dialog.transfer_list.GetFirstSelected.return_value = 0
        dialog._refresh = MagicMock()

        dialog._on_retry(None)

        manager.retry.assert_not_called()

    def test_retry_button_does_nothing_when_disconnected(self, transfer_module):
        module, fake_wx = transfer_module
        _make_wx_constants(fake_wx)
        fake_wx.Dialog = _Dialog

        parent = MagicMock()
        parent._client = MagicMock()
        parent._client.connected = False

        failed_transfer = SimpleNamespace(
            id=5,
            remote_path="/remote/report.csv",
            local_path="/tmp/report.csv",
            direction=module.TransferDirection.DOWNLOAD,
            status=module.TransferStatus.FAILED,
            progress_pct=0,
            display_status="failed",
        )
        manager = MagicMock()
        manager.transfers = [failed_transfer]

        dialog = module.create_transfer_dialog(parent, manager)
        dialog.GetParent = MagicMock(return_value=parent)
        dialog.transfer_list.GetFirstSelected.return_value = 0
        dialog._refresh = MagicMock()

        dialog._on_retry(None)

        manager.retry.assert_not_called()

    def test_retry_button_does_nothing_when_no_selection(self, transfer_module):
        module, fake_wx = transfer_module
        _make_wx_constants(fake_wx)
        fake_wx.Dialog = _Dialog
        fake_wx.NOT_FOUND = -1

        parent = MagicMock()
        manager = MagicMock()
        manager.transfers = []

        dialog = module.create_transfer_dialog(parent, manager)
        dialog.GetParent = MagicMock(return_value=parent)
        dialog.transfer_list.GetFirstSelected.return_value = -1
        dialog._refresh = MagicMock()

        dialog._on_retry(None)

        manager.retry.assert_not_called()

    def test_retry_announces_upload_direction(self, transfer_module):
        module, fake_wx = transfer_module
        _make_wx_constants(fake_wx)
        fake_wx.Dialog = _Dialog

        parent = MagicMock()
        parent._client = MagicMock()
        parent._client.connected = True
        parent._client.cwd = "/uploads"

        failed_upload = SimpleNamespace(
            id=3,
            remote_path="/uploads/data.bin",
            local_path="/home/user/data.bin",
            direction=module.TransferDirection.UPLOAD,
            status=module.TransferStatus.FAILED,
            progress_pct=0,
            display_status="failed",
        )
        manager = MagicMock()
        manager.transfers = [failed_upload]
        manager.retry.return_value = SimpleNamespace(id=4)

        dialog = module.create_transfer_dialog(parent, manager)
        dialog.GetParent = MagicMock(return_value=parent)
        dialog.transfer_list.GetFirstSelected.return_value = 0
        dialog._refresh = MagicMock()

        dialog._on_retry(None)

        parent._announce.assert_called_once_with("Retrying upload of data.bin")


# ---------------------------------------------------------------------------
# TransferDialog retry button enable/disable state tests
# ---------------------------------------------------------------------------


class FakeListCtrl:
    """ListCtrl stub that tracks cell values for testing."""

    def __init__(self, *a, **kw):
        self._rows: list[list[str]] = []
        self._selected: int = -1
        self._focused: int = -1
        self._name = ""

    def SetName(self, name):
        self._name = name

    def InsertColumn(self, col, heading, width=0):
        pass

    def InsertItem(self, index, label):
        row = [label, "", "", ""]
        if index >= len(self._rows):
            self._rows.append(row)
        else:
            self._rows.insert(index, row)
        return index

    def SetItem(self, row, col, value):
        self._rows[row][col] = value

    def GetItemText(self, row, col=0):
        if 0 <= row < len(self._rows) and 0 <= col < len(self._rows[row]):
            return self._rows[row][col]
        return ""

    def GetItemCount(self):
        return len(self._rows)

    def GetFirstSelected(self):
        return self._selected

    def GetFocusedItem(self):
        return self._focused

    def Select(self, idx, on=True):
        self._selected = idx if on else -1

    def Focus(self, idx):
        self._focused = idx

    def DeleteAllItems(self):
        self._rows.clear()
        self._selected = -1
        self._focused = -1

    def DeleteItem(self, idx):
        if 0 <= idx < len(self._rows):
            self._rows.pop(idx)

    def Bind(self, *a, **kw):
        pass


class TestRetryButtonState:
    """Tests for retry button enable/disable state in _refresh."""

    def test_retry_enabled_when_failed_selected(self, transfer_module):
        module, fake_wx = transfer_module
        _make_wx_constants(fake_wx)
        fake_wx.Dialog = _Dialog

        parent = MagicMock()
        failed_item = SimpleNamespace(
            id=1,
            remote_path="/remote/file.txt",
            local_path="/local/file.txt",
            direction=SimpleNamespace(value="download"),
            status=module.TransferStatus.FAILED,
            progress_pct=0,
            display_status="failed",
        )
        manager = MagicMock()
        manager.transfers = [failed_item]

        dialog = module.create_transfer_dialog(parent, manager)
        # Replace with FakeListCtrl for better control
        dialog.transfer_list = FakeListCtrl()

        # Populate via refresh
        dialog._refresh()

        # Select the failed item
        dialog.transfer_list.Select(0)
        dialog._update_retry_btn_state()

        # Should be enabled
        dialog.retry_btn.Enable.assert_called_with(True)

    def test_retry_disabled_when_completed_selected(self, transfer_module):
        module, fake_wx = transfer_module
        _make_wx_constants(fake_wx)
        fake_wx.Dialog = _Dialog

        parent = MagicMock()
        completed_item = SimpleNamespace(
            id=1,
            remote_path="/remote/file.txt",
            local_path="/local/file.txt",
            direction=SimpleNamespace(value="download"),
            status=module.TransferStatus.COMPLETED,
            progress_pct=100,
            display_status="completed",
        )
        manager = MagicMock()
        manager.transfers = [completed_item]

        dialog = module.create_transfer_dialog(parent, manager)
        dialog.transfer_list = FakeListCtrl()

        dialog._refresh()

        dialog.transfer_list.Select(0)
        dialog._update_retry_btn_state()

        # Last call should be Enable(False) since it's not failed
        dialog.retry_btn.Enable.assert_called_with(False)

    def test_retry_disabled_when_no_selection(self, transfer_module):
        module, fake_wx = transfer_module
        _make_wx_constants(fake_wx)
        fake_wx.Dialog = _Dialog

        parent = MagicMock()
        manager = MagicMock()
        manager.transfers = []

        dialog = module.create_transfer_dialog(parent, manager)
        dialog.transfer_list = FakeListCtrl()
        dialog._refresh()

        dialog._update_retry_btn_state()

        dialog.retry_btn.Enable.assert_called_with(False)


# ---------------------------------------------------------------------------
# MainFrame menu item tests
# ---------------------------------------------------------------------------


def _hydrate_frame(app_module):
    """Create a MainFrame without __init__ for unit-testing individual methods."""
    frame = object.__new__(app_module.MainFrame)
    frame._announce = MagicMock()
    frame._status = MagicMock()
    frame._update_status = MagicMock()
    frame._show_transfer_queue = MagicMock()
    frame._refresh_local_files = MagicMock()
    frame._refresh_remote_files = MagicMock()
    frame._transfer_manager = MagicMock()
    frame._transfer_state_by_id = {}
    frame._last_failed_transfer = None
    frame._retry_last_failed_item = MagicMock()
    frame._announcer = MagicMock()
    frame._client = None
    frame.status_bar = MagicMock(SetStatusText=MagicMock())
    return frame


class TestRetryLastFailedMenuItem:
    """Tests for the Transfer > Retry Last Failed Transfer menu item."""

    def test_last_failed_tracked_on_failure(self, transfer_module, monkeypatch):
        """_on_transfer_update should track the last failed transfer ID."""
        app_module, _ = load_module_with_fake_wx("portkeydrop.app", monkeypatch)
        frame = _hydrate_frame(app_module)

        failed_transfer = SimpleNamespace(
            id=42,
            direction=app_module.TransferDirection.UPLOAD,
            status=app_module.TransferStatus.FAILED,
        )
        frame._transfer_manager.transfers = [failed_transfer]

        frame._on_transfer_update(None)

        assert frame._last_failed_transfer == 42
        frame._retry_last_failed_item.Enable.assert_called_with(True)

    def test_retry_last_failed_calls_retry(self, transfer_module, monkeypatch):
        """_on_retry_last_failed should call retry and announce."""
        app_module, _ = load_module_with_fake_wx("portkeydrop.app", monkeypatch)
        frame = _hydrate_frame(app_module)

        failed_transfer = MagicMock()
        failed_transfer.id = 10
        failed_transfer.status = app_module.TransferStatus.FAILED
        failed_transfer.direction = app_module.TransferDirection.DOWNLOAD
        failed_transfer.remote_path = "/remote/data.csv"
        failed_transfer.local_path = "/local/data.csv"

        frame._last_failed_transfer = 10
        frame._client = MagicMock()
        frame._client.connected = True
        frame._client.cwd = "/remote"

        frame._transfer_manager.transfers = [failed_transfer]
        frame._transfer_manager.retry.return_value = MagicMock(id=11)

        frame._on_retry_last_failed(None)

        frame._transfer_manager.retry.assert_called_once_with(10, frame._client)

    def test_retry_last_failed_announces_message(self, transfer_module, monkeypatch):
        app_module, _ = load_module_with_fake_wx("portkeydrop.app", monkeypatch)
        frame = _hydrate_frame(app_module)

        failed_transfer = MagicMock()
        failed_transfer.id = 10
        failed_transfer.status = app_module.TransferStatus.FAILED
        failed_transfer.direction = app_module.TransferDirection.DOWNLOAD
        failed_transfer.remote_path = "/remote/data.csv"
        failed_transfer.local_path = "/local/data.csv"

        frame._last_failed_transfer = 10
        frame._client = MagicMock()
        frame._client.connected = True
        frame._client.cwd = "/remote"

        frame._transfer_manager.transfers = [failed_transfer]
        frame._transfer_manager.retry.return_value = MagicMock(id=11)

        frame._on_retry_last_failed(None)

        frame._announce.assert_called_once_with("Retrying download of data.csv")

    def test_retry_last_failed_does_nothing_when_disconnected(self, transfer_module, monkeypatch):
        app_module, _ = load_module_with_fake_wx("portkeydrop.app", monkeypatch)
        frame = _hydrate_frame(app_module)
        frame._last_failed_transfer = 10
        frame._client = None

        frame._on_retry_last_failed(None)

        frame._announce.assert_called_once_with("Not connected")

    def test_retry_last_failed_does_nothing_when_no_failure(self, transfer_module, monkeypatch):
        app_module, _ = load_module_with_fake_wx("portkeydrop.app", monkeypatch)
        frame = _hydrate_frame(app_module)
        frame._last_failed_transfer = None

        frame._on_retry_last_failed(None)

        # Should not call retry
        frame._transfer_manager.retry.assert_not_called()

    def test_retry_last_failed_clears_tracking(self, transfer_module, monkeypatch):
        """After a successful retry, last_failed should be cleared."""
        app_module, _ = load_module_with_fake_wx("portkeydrop.app", monkeypatch)
        frame = _hydrate_frame(app_module)

        failed_transfer = MagicMock()
        failed_transfer.id = 10
        failed_transfer.status = app_module.TransferStatus.FAILED
        failed_transfer.direction = app_module.TransferDirection.DOWNLOAD
        failed_transfer.remote_path = "/remote/data.csv"
        failed_transfer.local_path = "/local/data.csv"

        frame._last_failed_transfer = 10
        frame._client = MagicMock()
        frame._client.connected = True
        frame._client.cwd = "/remote"

        frame._transfer_manager.transfers = [failed_transfer]
        frame._transfer_manager.retry.return_value = MagicMock(id=11)

        frame._on_retry_last_failed(None)

        assert frame._last_failed_transfer is None
        frame._retry_last_failed_item.Enable.assert_called_with(False)

    def test_completed_transfer_does_not_enable_retry(self, transfer_module, monkeypatch):
        """Completed transfers should not set _last_failed_transfer."""
        app_module, _ = load_module_with_fake_wx("portkeydrop.app", monkeypatch)
        frame = _hydrate_frame(app_module)

        completed_transfer = SimpleNamespace(
            id=5,
            direction=app_module.TransferDirection.DOWNLOAD,
            status=app_module.TransferStatus.COMPLETED,
        )
        frame._transfer_manager.transfers = [completed_transfer]

        frame._on_transfer_update(None)

        assert frame._last_failed_transfer is None

    def test_retry_last_failed_shows_transfer_queue(self, transfer_module, monkeypatch):
        """Retry should open the transfer queue dialog."""
        app_module, _ = load_module_with_fake_wx("portkeydrop.app", monkeypatch)
        frame = _hydrate_frame(app_module)

        failed_transfer = MagicMock()
        failed_transfer.id = 10
        failed_transfer.status = app_module.TransferStatus.FAILED
        failed_transfer.direction = app_module.TransferDirection.UPLOAD
        failed_transfer.remote_path = "/remote/file.bin"
        failed_transfer.local_path = "/local/file.bin"

        frame._last_failed_transfer = 10
        frame._client = MagicMock()
        frame._client.connected = True
        frame._client.cwd = "/remote"

        frame._transfer_manager.transfers = [failed_transfer]
        frame._transfer_manager.retry.return_value = MagicMock(id=11)

        frame._on_retry_last_failed(None)

        frame._show_transfer_queue.assert_called_once()
