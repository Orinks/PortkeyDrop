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
# TransferService.retry() tests
# ---------------------------------------------------------------------------


class TestTransferManagerRetry:
    """Tests for TransferService.retry() method."""

    def test_retry_failed_download_resets_in_place(self, transfer_module):
        """retry() resets the failed job in-place — same id, same list position."""
        module, _ = transfer_module
        svc = module.TransferService()
        item = module.TransferJob(
            direction=module.TransferDirection.DOWNLOAD,
            source="/remote/file.txt",
            destination="/local/file.txt",
            total_bytes=1024,
            status=module.TransferStatus.FAILED,
            error="Connection lost",
        )
        with svc._lock:
            svc._jobs.append(item)

        client = MagicMock()
        retried = svc.retry(item.id, client)

        assert retried is not None
        assert retried is item  # same object, not a clone
        assert retried.id == item.id
        assert retried.status == module.TransferStatus.PENDING
        assert retried.error is None
        assert retried.direction == module.TransferDirection.DOWNLOAD
        assert retried.source == "/remote/file.txt"
        assert len(svc.jobs) == 1  # no duplicate added

    def test_retry_failed_upload_resets_in_place(self, transfer_module):
        module, _ = transfer_module
        svc = module.TransferService()
        item = module.TransferJob(
            direction=module.TransferDirection.UPLOAD,
            source="/local/file.txt",
            destination="/remote/file.txt",
            total_bytes=2048,
            status=module.TransferStatus.FAILED,
            error="Permission denied",
        )
        with svc._lock:
            svc._jobs.append(item)

        client = MagicMock()
        retried = svc.retry(item.id, client)

        assert retried is item
        assert retried.status == module.TransferStatus.PENDING
        assert retried.error is None
        assert retried.direction == module.TransferDirection.UPLOAD
        assert retried.source == "/local/file.txt"
        assert len(svc.jobs) == 1

    def test_retry_non_failed_transfer_returns_none(self, transfer_module):
        module, _ = transfer_module
        svc = module.TransferService()
        item = module.TransferJob(
            direction=module.TransferDirection.DOWNLOAD,
            source="/remote/file.txt",
            destination="/local/file.txt",
            status=module.TransferStatus.COMPLETE,
        )
        with svc._lock:
            svc._jobs.append(item)

        client = MagicMock()
        result = svc.retry(item.id, client)

        assert result is None

    def test_retry_nonexistent_transfer_returns_none(self, transfer_module):
        module, _ = transfer_module
        svc = module.TransferService()

        client = MagicMock()
        result = svc.retry("nonexistent-id", client)

        assert result is None

    def test_retry_queued_transfer_returns_none(self, transfer_module):
        module, _ = transfer_module
        svc = module.TransferService()
        item = module.TransferJob(
            direction=module.TransferDirection.DOWNLOAD,
            source="/remote/file.txt",
            destination="/local/file.txt",
            status=module.TransferStatus.PENDING,
        )
        with svc._lock:
            svc._jobs.append(item)

        client = MagicMock()
        result = svc.retry(item.id, client)

        assert result is None

    def test_retry_cancelled_transfer_returns_none(self, transfer_module):
        module, _ = transfer_module
        svc = module.TransferService()
        item = module.TransferJob(
            direction=module.TransferDirection.DOWNLOAD,
            source="/remote/file.txt",
            destination="/local/file.txt",
            status=module.TransferStatus.CANCELLED,
        )
        with svc._lock:
            svc._jobs.append(item)

        client = MagicMock()
        result = svc.retry(item.id, client)

        assert result is None

    def test_retry_resets_job_in_place(self, transfer_module):
        """Retry resets the existing job — no duplicate added to the list."""
        module, _ = transfer_module
        svc = module.TransferService()
        item = module.TransferJob(
            direction=module.TransferDirection.DOWNLOAD,
            source="/remote/file.txt",
            destination="/local/file.txt",
            total_bytes=512,
            status=module.TransferStatus.FAILED,
            error="Timeout",
        )
        with svc._lock:
            svc._jobs.append(item)

        client = MagicMock()
        svc.retry(item.id, client)

        jobs = svc.jobs
        assert len(jobs) == 1
        assert jobs[0].id == item.id
        assert jobs[0].status == module.TransferStatus.PENDING

    def test_retry_preserves_job_id(self, transfer_module):
        """In-place retry keeps the same job ID (no clone)."""
        module, _ = transfer_module
        svc = module.TransferService()
        item = module.TransferJob(
            direction=module.TransferDirection.DOWNLOAD,
            source="/remote/file.txt",
            destination="/local/file.txt",
            status=module.TransferStatus.FAILED,
        )
        original_id = item.id
        with svc._lock:
            svc._jobs.append(item)

        client = MagicMock()
        retried = svc.retry(item.id, client)

        assert retried is not None
        assert retried.id == original_id

    def test_retry_resets_progress_fields(self, transfer_module):
        """Retried job has progress/error reset; source/dest/total preserved."""
        module, _ = transfer_module
        svc = module.TransferService()
        item = module.TransferJob(
            direction=module.TransferDirection.DOWNLOAD,
            source="/remote/file.txt",
            destination="/local/file.txt",
            total_bytes=1024,
            transferred_bytes=500,
            status=module.TransferStatus.FAILED,
            error="Network error",
        )
        with svc._lock:
            svc._jobs.append(item)

        client = MagicMock()
        retried = svc.retry(item.id, client)

        assert retried is not None
        assert retried.source == "/remote/file.txt"
        assert retried.destination == "/local/file.txt"
        assert retried.total_bytes == 1024
        # transferred_bytes is preserved so _run_download can attempt resume
        assert retried.transferred_bytes == 500
        assert retried.error is None
        assert retried.status == module.TransferStatus.PENDING


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
        service = MagicMock()
        service.jobs = []

        dialog = module.create_transfer_dialog(parent, service)
        assert hasattr(dialog, "retry_btn")

    def test_retry_button_initially_disabled(self, transfer_module):
        module, fake_wx = transfer_module
        _make_wx_constants(fake_wx)
        fake_wx.Dialog = _Dialog

        parent = MagicMock()
        service = MagicMock()
        service.jobs = []

        dialog = module.create_transfer_dialog(parent, service)
        dialog.retry_btn.Enable.assert_called_with(False)

    def test_retry_button_calls_retry_on_failed_transfer(self, transfer_module):
        module, fake_wx = transfer_module
        _make_wx_constants(fake_wx)
        fake_wx.Dialog = _Dialog

        parent = MagicMock()
        parent._client = MagicMock()
        parent._client.connected = True
        parent._client.cwd = "/remote"

        failed_job = SimpleNamespace(
            id="abc123",
            source="/remote/report.csv",
            destination="/tmp/report.csv",
            direction=module.TransferDirection.DOWNLOAD,
            status=module.TransferStatus.FAILED,
            progress=0,
        )
        service = MagicMock()
        service.jobs = [failed_job]
        service.retry.return_value = SimpleNamespace(id="def456")

        dialog = module.create_transfer_dialog(parent, service)
        dialog.GetParent = MagicMock(return_value=parent)
        dialog.transfer_list.GetFirstSelected.return_value = 0
        dialog._refresh = MagicMock()

        dialog._on_retry(None)

        service.retry.assert_called_once_with("abc123", parent._client)
        parent._announce.assert_called_once_with("Retrying download of report.csv")
        parent._update_status.assert_called_once_with("Retrying download of report.csv", "/remote")

    def test_retry_button_does_nothing_for_non_failed(self, transfer_module):
        module, fake_wx = transfer_module
        _make_wx_constants(fake_wx)
        fake_wx.Dialog = _Dialog

        parent = MagicMock()
        completed_job = SimpleNamespace(
            id="abc123",
            source="/remote/report.csv",
            destination="/tmp/report.csv",
            direction=module.TransferDirection.DOWNLOAD,
            status=module.TransferStatus.COMPLETE,
            progress=100,
        )
        service = MagicMock()
        service.jobs = [completed_job]

        dialog = module.create_transfer_dialog(parent, service)
        dialog.GetParent = MagicMock(return_value=parent)
        dialog.transfer_list.GetFirstSelected.return_value = 0
        dialog._refresh = MagicMock()

        dialog._on_retry(None)

        service.retry.assert_not_called()

    def test_retry_announces_upload_direction(self, transfer_module):
        module, fake_wx = transfer_module
        _make_wx_constants(fake_wx)
        fake_wx.Dialog = _Dialog

        parent = MagicMock()
        parent._client = MagicMock()
        parent._client.connected = True
        parent._client.cwd = "/uploads"

        failed_upload = SimpleNamespace(
            id="xyz789",
            source="/home/user/data.bin",
            destination="/uploads/data.bin",
            direction=module.TransferDirection.UPLOAD,
            status=module.TransferStatus.FAILED,
            progress=0,
        )
        service = MagicMock()
        service.jobs = [failed_upload]
        service.retry.return_value = SimpleNamespace(id="new999")

        dialog = module.create_transfer_dialog(parent, service)
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

    def SetLabel(self, name):
        self._name = name

    def InsertColumn(self, col, heading, width=0):
        pass

    def InsertItem(self, index, label):
        row = [label, "", "", "", ""]
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
        failed_job = SimpleNamespace(
            id="j1",
            source="/remote/file.txt",
            destination="/local/file.txt",
            direction=SimpleNamespace(value="download"),
            status=module.TransferStatus.FAILED,
            progress=0,
        )
        service = MagicMock()
        service.jobs = [failed_job]

        dialog = module.create_transfer_dialog(parent, service)
        dialog.transfer_list = FakeListCtrl()

        dialog._refresh()

        dialog.transfer_list.Select(0)
        dialog._update_retry_btn_state()

        dialog.retry_btn.Enable.assert_called_with(True)

    def test_retry_disabled_when_completed_selected(self, transfer_module):
        module, fake_wx = transfer_module
        _make_wx_constants(fake_wx)
        fake_wx.Dialog = _Dialog

        parent = MagicMock()
        completed_job = SimpleNamespace(
            id="j1",
            source="/remote/file.txt",
            destination="/local/file.txt",
            direction=SimpleNamespace(value="download"),
            status=module.TransferStatus.COMPLETE,
            progress=100,
        )
        service = MagicMock()
        service.jobs = [completed_job]

        dialog = module.create_transfer_dialog(parent, service)
        dialog.transfer_list = FakeListCtrl()

        dialog._refresh()

        dialog.transfer_list.Select(0)
        dialog._update_retry_btn_state()

        dialog.retry_btn.Enable.assert_called_with(False)

    def test_retry_disabled_when_no_selection(self, transfer_module):
        module, fake_wx = transfer_module
        _make_wx_constants(fake_wx)
        fake_wx.Dialog = _Dialog

        parent = MagicMock()
        service = MagicMock()
        service.jobs = []

        dialog = module.create_transfer_dialog(parent, service)
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
    frame._transfer_service = MagicMock()
    frame._transfer_state_by_id = {}
    frame._last_failed_transfer = None
    frame._retry_last_failed_item = MagicMock()
    frame._client = None
    frame.status_bar = MagicMock(SetStatusText=MagicMock())
    frame.activity_log = MagicMock()
    frame._activity_log_visible = True
    return frame


class TestRetryLastFailedMenuItem:
    """Tests for the Transfer > Retry Last Failed Transfer menu item."""

    def test_last_failed_tracked_on_failure(self, transfer_module, monkeypatch):
        """_on_transfer_update should track the last failed transfer ID."""
        app_module, _ = load_module_with_fake_wx("portkeydrop.app", monkeypatch)
        frame = _hydrate_frame(app_module)

        failed_job = SimpleNamespace(
            id="job42",
            direction=app_module.TransferDirection.UPLOAD,
            status=app_module.TransferStatus.FAILED,
            source="/local/file.txt",
            destination="/remote/file.txt",
            error="Connection lost",
        )
        frame._transfer_service.jobs = [failed_job]

        frame._on_transfer_update(None)

        assert frame._last_failed_transfer == "job42"
        frame._retry_last_failed_item.Enable.assert_called_with(True)

    def test_retry_last_failed_calls_retry(self, transfer_module, monkeypatch):
        """_on_retry_last_failed should call retry and announce."""
        app_module, _ = load_module_with_fake_wx("portkeydrop.app", monkeypatch)
        frame = _hydrate_frame(app_module)

        failed_job = MagicMock()
        failed_job.id = "job10"
        failed_job.status = app_module.TransferStatus.FAILED
        failed_job.direction = app_module.TransferDirection.DOWNLOAD
        failed_job.source = "/remote/data.csv"
        failed_job.destination = "/local/data.csv"

        frame._last_failed_transfer = "job10"
        frame._client = MagicMock()
        frame._client.connected = True
        frame._client.cwd = "/remote"

        frame._transfer_service.jobs = [failed_job]
        frame._transfer_service.retry.return_value = MagicMock(id="job11")

        frame._on_retry_last_failed(None)

        frame._transfer_service.retry.assert_called_once_with("job10", frame._client)

    def test_retry_last_failed_announces_message(self, transfer_module, monkeypatch):
        app_module, _ = load_module_with_fake_wx("portkeydrop.app", monkeypatch)
        frame = _hydrate_frame(app_module)

        failed_job = MagicMock()
        failed_job.id = "job10"
        failed_job.status = app_module.TransferStatus.FAILED
        failed_job.direction = app_module.TransferDirection.DOWNLOAD
        failed_job.source = "/remote/data.csv"
        failed_job.destination = "/local/data.csv"

        frame._last_failed_transfer = "job10"
        frame._client = MagicMock()
        frame._client.connected = True
        frame._client.cwd = "/remote"

        frame._transfer_service.jobs = [failed_job]
        frame._transfer_service.retry.return_value = MagicMock(id="job11")

        frame._on_retry_last_failed(None)

        frame._announce.assert_called_once_with("Retrying download of data.csv")

    def test_retry_last_failed_clears_tracking(self, transfer_module, monkeypatch):
        """After a successful retry, last_failed should be cleared."""
        app_module, _ = load_module_with_fake_wx("portkeydrop.app", monkeypatch)
        frame = _hydrate_frame(app_module)

        failed_job = MagicMock()
        failed_job.id = "job10"
        failed_job.status = app_module.TransferStatus.FAILED
        failed_job.direction = app_module.TransferDirection.DOWNLOAD
        failed_job.source = "/remote/data.csv"
        failed_job.destination = "/local/data.csv"

        frame._last_failed_transfer = "job10"
        frame._client = MagicMock()
        frame._client.connected = True
        frame._client.cwd = "/remote"

        frame._transfer_service.jobs = [failed_job]
        frame._transfer_service.retry.return_value = MagicMock(id="job11")

        frame._on_retry_last_failed(None)

        assert frame._last_failed_transfer is None
        frame._retry_last_failed_item.Enable.assert_called_with(False)

    def test_completed_transfer_does_not_enable_retry(self, transfer_module, monkeypatch):
        """Completed transfers should not set _last_failed_transfer."""
        app_module, _ = load_module_with_fake_wx("portkeydrop.app", monkeypatch)
        frame = _hydrate_frame(app_module)

        completed_job = SimpleNamespace(
            id="job5",
            direction=app_module.TransferDirection.DOWNLOAD,
            status=app_module.TransferStatus.COMPLETE,
            source="/remote/file.txt",
            destination="/local/file.txt",
            error=None,
        )
        frame._transfer_service.jobs = [completed_job]

        frame._on_transfer_update(None)

        assert frame._last_failed_transfer is None

    def test_retry_last_failed_shows_transfer_queue(self, transfer_module, monkeypatch):
        """Retry should open the transfer queue dialog."""
        app_module, _ = load_module_with_fake_wx("portkeydrop.app", monkeypatch)
        frame = _hydrate_frame(app_module)

        failed_job = MagicMock()
        failed_job.id = "job10"
        failed_job.status = app_module.TransferStatus.FAILED
        failed_job.direction = app_module.TransferDirection.UPLOAD
        failed_job.source = "/local/file.bin"
        failed_job.destination = "/remote/file.bin"

        frame._last_failed_transfer = "job10"
        frame._client = MagicMock()
        frame._client.connected = True
        frame._client.cwd = "/remote"

        frame._transfer_service.jobs = [failed_job]
        frame._transfer_service.retry.return_value = MagicMock(id="job11")

        frame._on_retry_last_failed(None)

        frame._show_transfer_queue.assert_called_once()

    def test_retry_last_failed_does_nothing_when_no_failure(self, transfer_module, monkeypatch):
        app_module, _ = load_module_with_fake_wx("portkeydrop.app", monkeypatch)
        frame = _hydrate_frame(app_module)
        frame._last_failed_transfer = None

        frame._on_retry_last_failed(None)

        frame._transfer_service.retry.assert_not_called()

    def test_retry_last_failed_does_nothing_when_disconnected(self, transfer_module, monkeypatch):
        app_module, _ = load_module_with_fake_wx("portkeydrop.app", monkeypatch)
        frame = _hydrate_frame(app_module)
        frame._last_failed_transfer = "job10"
        frame._client = None

        frame._on_retry_last_failed(None)

        frame._announce.assert_called_once_with("Not connected")
