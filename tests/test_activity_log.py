"""Tests for the activity log console panel."""

from __future__ import annotations

import re
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests._wx_stub import load_module_with_fake_wx


@pytest.fixture
def app_module(monkeypatch):
    module, fake_wx = load_module_with_fake_wx("portkeydrop.app", monkeypatch)
    return module, fake_wx


@pytest.fixture
def transfer_module(monkeypatch):
    module, fake_wx = load_module_with_fake_wx("portkeydrop.dialogs.transfer", monkeypatch)
    return module, fake_wx


def _hydrate_frame(app_module):
    """Create a minimal MainFrame without __init__."""
    app, _ = app_module
    frame = object.__new__(app.MainFrame)
    frame._announce = MagicMock()
    frame._status = MagicMock()
    frame._update_status = MagicMock()
    frame._show_transfer_queue = MagicMock()
    frame._refresh_local_files = MagicMock()
    frame._refresh_remote_files = MagicMock()
    frame._transfer_manager = MagicMock()
    frame.status_bar = MagicMock(SetStatusText=MagicMock())
    frame.activity_log = MagicMock()
    return frame


class TestLogEvent:
    def test_appends_timestamped_entry(self, app_module):
        frame = _hydrate_frame(app_module)

        frame.log_event("Connected to example.com via sftp")

        frame.activity_log.AppendText.assert_called_once()
        entry = frame.activity_log.AppendText.call_args[0][0]
        assert re.match(r"\[\d{2}:\d{2}:\d{2}\] Connected to example.com via sftp\n", entry)

    def test_calls_announce(self, app_module):
        frame = _hydrate_frame(app_module)

        frame.log_event("Disconnected from server")

        frame._announce.assert_called_once_with("Disconnected from server")


class TestTransferLogEvents:
    def test_log_event_on_transfer_complete(self, app_module):
        app, _ = app_module
        frame = _hydrate_frame(app_module)
        frame._client = MagicMock(connected=True, cwd="/remote")
        transfer = SimpleNamespace(
            id=1,
            direction=app.TransferDirection.DOWNLOAD,
            status=app.TransferStatus.COMPLETED,
            local_path="/tmp/report.csv",
            remote_path="/remote/report.csv",
            error="",
        )
        frame._transfer_manager.transfers = [transfer]
        frame._transfer_state_by_id = {}

        frame._on_transfer_update(None)

        frame.activity_log.AppendText.assert_called_once()
        entry = frame.activity_log.AppendText.call_args[0][0]
        assert "Download complete: report.csv" in entry

    def test_log_event_on_transfer_error(self, app_module):
        app, _ = app_module
        frame = _hydrate_frame(app_module)
        frame._client = MagicMock(connected=True, cwd="/remote")
        transfer = SimpleNamespace(
            id=1,
            direction=app.TransferDirection.UPLOAD,
            status=app.TransferStatus.FAILED,
            local_path="/tmp/data.zip",
            remote_path="/remote/data.zip",
            error="Permission denied",
        )
        frame._transfer_manager.transfers = [transfer]
        frame._transfer_state_by_id = {}

        frame._on_transfer_update(None)

        frame.activity_log.AppendText.assert_called_once()
        entry = frame.activity_log.AppendText.call_args[0][0]
        assert "Upload failed: data.zip" in entry
        assert "Permission denied" in entry

    def test_log_event_on_transfer_cancel(self, app_module):
        app, _ = app_module
        frame = _hydrate_frame(app_module)
        frame._client = MagicMock(connected=True, cwd="/remote")
        transfer = SimpleNamespace(
            id=1,
            direction=app.TransferDirection.DOWNLOAD,
            status=app.TransferStatus.CANCELLED,
            local_path="/tmp/file.txt",
            remote_path="/remote/file.txt",
            error="",
        )
        frame._transfer_manager.transfers = [transfer]
        frame._transfer_state_by_id = {}

        frame._on_transfer_update(None)

        frame.activity_log.AppendText.assert_called_once()
        entry = frame.activity_log.AppendText.call_args[0][0]
        assert "Download cancelled: file.txt" in entry

    def test_no_log_event_on_in_progress(self, app_module):
        app, _ = app_module
        frame = _hydrate_frame(app_module)
        frame._client = MagicMock(connected=True, cwd="/remote")
        transfer = SimpleNamespace(
            id=1,
            direction=app.TransferDirection.UPLOAD,
            status=app.TransferStatus.IN_PROGRESS,
            local_path="/tmp/file.txt",
            remote_path="/remote/file.txt",
            error="",
        )
        frame._transfer_manager.transfers = [transfer]
        frame._transfer_state_by_id = {}

        frame._on_transfer_update(None)

        frame.activity_log.AppendText.assert_not_called()


class TestConnectDisconnectLogEvents:
    def test_connect_success_logs_event(self, app_module):
        app, _ = app_module
        frame = _hydrate_frame(app_module)
        frame._toolbar_panel = MagicMock()
        frame._update_title = MagicMock()
        frame.local_file_list = MagicMock()
        frame.GetSizer = MagicMock()

        client = MagicMock()
        client.cwd = "/home/user"
        client._info = SimpleNamespace(
            host="example.com",
            protocol=SimpleNamespace(value="sftp"),
        )

        frame._on_connect_success(client)

        frame.activity_log.AppendText.assert_called_once()
        entry = frame.activity_log.AppendText.call_args[0][0]
        assert "Connected to example.com via sftp" in entry

    def test_connect_failure_logs_event(self, app_module):
        app, fake_wx = app_module
        frame = _hydrate_frame(app_module)

        frame._on_connect_failure(Exception("timeout"))

        frame.activity_log.AppendText.assert_called_once()
        entry = frame.activity_log.AppendText.call_args[0][0]
        assert "Connection failed" in entry
        assert "timeout" in entry

    def test_disconnect_logs_event(self, app_module):
        app, _ = app_module
        frame = _hydrate_frame(app_module)
        frame._update_title = MagicMock()
        frame._toolbar_panel = MagicMock()
        frame._toolbar_panel.IsShown.return_value = True
        frame.remote_file_list = MagicMock()
        frame.remote_path_bar = MagicMock()
        frame._remote_files = []
        frame._client = MagicMock()

        frame._on_disconnect(None)

        frame.activity_log.AppendText.assert_called_once()
        entry = frame.activity_log.AppendText.call_args[0][0]
        assert "Disconnected from server" in entry

    def test_disconnect_no_log_when_not_connected(self, app_module):
        app, _ = app_module
        frame = _hydrate_frame(app_module)
        frame._update_title = MagicMock()
        frame._toolbar_panel = MagicMock()
        frame._toolbar_panel.IsShown.return_value = True
        frame.remote_file_list = MagicMock()
        frame.remote_path_bar = MagicMock()
        frame._remote_files = []
        frame._client = None

        frame._on_disconnect(None)

        frame.activity_log.AppendText.assert_not_called()


def _make_transfer_dialog_wx(fake_wx):
    """Set required wx constants for TransferDialog creation."""
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

    fake_wx.Dialog = _Dialog


class TestTransferDialogLogCallback:
    def test_on_cancel_calls_log_callback(self, transfer_module):
        module, fake_wx = transfer_module
        _make_transfer_dialog_wx(fake_wx)

        callback = MagicMock()
        parent = MagicMock()
        manager = MagicMock()
        manager.transfers = [
            SimpleNamespace(
                id=1,
                remote_path="/remote/report.csv",
                local_path="/tmp/report.csv",
                direction=SimpleNamespace(value="download"),
                progress_pct=0,
                display_status="queued",
            )
        ]

        dialog = module.create_transfer_dialog(parent, manager, log_callback=callback)
        dialog.GetParent = MagicMock(return_value=parent)
        dialog.transfer_list.GetFirstSelected.return_value = 0
        dialog._refresh = MagicMock()

        dialog._on_cancel(None)

        callback.assert_called_once()
        msg = callback.call_args.args[0]
        assert "cancelled" in msg.lower()
        assert "report.csv" in msg

    def test_on_cancel_safe_when_log_callback_none(self, transfer_module):
        module, fake_wx = transfer_module
        _make_transfer_dialog_wx(fake_wx)

        parent = MagicMock()
        manager = MagicMock()
        manager.transfers = [
            SimpleNamespace(
                id=1,
                remote_path="/remote/report.csv",
                local_path="/tmp/report.csv",
                direction=SimpleNamespace(value="download"),
                progress_pct=0,
                display_status="queued",
            )
        ]

        dialog = module.create_transfer_dialog(parent, manager)
        dialog.GetParent = MagicMock(return_value=parent)
        dialog.transfer_list.GetFirstSelected.return_value = 0
        dialog._refresh = MagicMock()

        # Should not raise
        dialog._on_cancel(None)

        manager.cancel.assert_called_once_with(1)

    def test_log_callback_none_by_default(self, transfer_module):
        module, fake_wx = transfer_module
        _make_transfer_dialog_wx(fake_wx)

        parent = MagicMock()
        manager = MagicMock()
        manager.transfers = []

        dialog = module.create_transfer_dialog(parent, manager)
        assert dialog.log_callback is None
