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
    frame._transfer_service = MagicMock()
    frame.status_bar = MagicMock(SetStatusText=MagicMock())
    frame.activity_log = MagicMock()
    frame._activity_log_visible = True
    return frame


class TestLogEvent:
    def test_appends_timestamped_entry(self, app_module):
        frame = _hydrate_frame(app_module)

        frame.log_event("Connected to example.com via sftp")

        frame.activity_log.Append.assert_called_once()
        entry = frame.activity_log.Append.call_args[0][0]
        assert re.match(r"\[\d{2}:\d{2}:\d{2}\] Connected to example.com via sftp$", entry)

    def test_calls_announce(self, app_module):
        frame = _hydrate_frame(app_module)

        frame.log_event("Disconnected from server")

        frame._announce.assert_called_once_with("Disconnected from server")


class TestTransferLogEvents:
    def test_log_event_on_transfer_complete(self, app_module):
        app, _ = app_module
        frame = _hydrate_frame(app_module)
        frame._client = MagicMock(connected=True, cwd="/remote")
        job = SimpleNamespace(
            id="j1",
            direction=app.TransferDirection.DOWNLOAD,
            status=app.TransferStatus.COMPLETE,
            source="/remote/report.csv",
            destination="/tmp/report.csv",
            error=None,
            progress=100,
        )
        frame._transfer_service.jobs = [job]
        frame._transfer_state_by_id = {}

        frame._on_transfer_update(None)

        frame.activity_log.Append.assert_called_once()
        entry = frame.activity_log.Append.call_args[0][0]
        assert "Download complete: report.csv" in entry

    def test_log_event_on_transfer_error(self, app_module):
        app, _ = app_module
        frame = _hydrate_frame(app_module)
        frame._client = MagicMock(connected=True, cwd="/remote")
        job = SimpleNamespace(
            id="j2",
            direction=app.TransferDirection.UPLOAD,
            status=app.TransferStatus.FAILED,
            source="/tmp/data.zip",
            destination="/remote/data.zip",
            error="Permission denied",
            progress=0,
        )
        frame._transfer_service.jobs = [job]
        frame._transfer_state_by_id = {}

        frame._on_transfer_update(None)

        frame.activity_log.Append.assert_called_once()
        entry = frame.activity_log.Append.call_args[0][0]
        assert "Upload failed: data.zip" in entry
        assert "Permission denied" in entry

    def test_log_event_on_transfer_cancel(self, app_module):
        app, _ = app_module
        frame = _hydrate_frame(app_module)
        frame._client = MagicMock(connected=True, cwd="/remote")
        job = SimpleNamespace(
            id="j3",
            direction=app.TransferDirection.DOWNLOAD,
            status=app.TransferStatus.CANCELLED,
            source="/remote/file.txt",
            destination="/tmp/file.txt",
            error=None,
            progress=0,
        )
        frame._transfer_service.jobs = [job]
        frame._transfer_state_by_id = {}

        frame._on_transfer_update(None)

        frame.activity_log.Append.assert_called_once()
        entry = frame.activity_log.Append.call_args[0][0]
        assert "Download cancelled: file.txt" in entry

    def test_no_log_event_on_in_progress(self, app_module):
        app, _ = app_module
        frame = _hydrate_frame(app_module)
        frame._client = MagicMock(connected=True, cwd="/remote")
        job = SimpleNamespace(
            id="j4",
            direction=app.TransferDirection.UPLOAD,
            status=app.TransferStatus.IN_PROGRESS,
            source="/tmp/file.txt",
            destination="/remote/file.txt",
            error=None,
            progress=50,
        )
        frame._transfer_service.jobs = [job]
        frame._transfer_state_by_id = {}

        frame._on_transfer_update(None)

        frame.activity_log.Append.assert_not_called()


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

        frame.activity_log.Append.assert_called_once()
        entry = frame.activity_log.Append.call_args[0][0]
        assert "Connected to example.com via sftp" in entry

    def test_connect_failure_logs_event(self, app_module):
        app, fake_wx = app_module
        frame = _hydrate_frame(app_module)

        frame._on_connect_failure(Exception("timeout"))

        frame.activity_log.Append.assert_called_once()
        entry = frame.activity_log.Append.call_args[0][0]
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

        frame.activity_log.Append.assert_called_once()
        entry = frame.activity_log.Append.call_args[0][0]
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

        frame.activity_log.Append.assert_not_called()


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
        svc = MagicMock()
        svc.jobs = [
            SimpleNamespace(
                id="job1",
                source="/remote/report.csv",
                destination="/tmp/report.csv",
                direction=SimpleNamespace(value="download"),
                status=SimpleNamespace(value="pending"),
                progress=0,
                error=None,
            )
        ]

        dialog = module.create_transfer_dialog(parent, svc, log_callback=callback)
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
        svc = MagicMock()
        svc.jobs = [
            SimpleNamespace(
                id="job1",
                source="/remote/report.csv",
                destination="/tmp/report.csv",
                direction=SimpleNamespace(value="download"),
                status=SimpleNamespace(value="pending"),
                progress=0,
                error=None,
            )
        ]

        dialog = module.create_transfer_dialog(parent, svc)
        dialog.GetParent = MagicMock(return_value=parent)
        dialog.transfer_list.GetFirstSelected.return_value = 0
        dialog._refresh = MagicMock()

        # Should not raise
        dialog._on_cancel(None)

        svc.cancel.assert_called_once_with("job1")

    def test_log_callback_none_by_default(self, transfer_module):
        module, fake_wx = transfer_module
        _make_transfer_dialog_wx(fake_wx)

        parent = MagicMock()
        svc = MagicMock()
        svc.jobs = []

        dialog = module.create_transfer_dialog(parent, svc)
        assert dialog.log_callback is None


class TestBuildDualPaneActivityLog:
    """Cover the activity log panel creation in _build_dual_pane."""

    def test_activity_log_widget_created(self, app_module):
        app, fake_wx = app_module
        frame = object.__new__(app.MainFrame)
        # Minimal attributes needed by _build_dual_pane
        frame._local_cwd = "/tmp"
        frame._toolbar_panel = MagicMock()

        frame._build_dual_pane()

        # The activity log TextCtrl should be assigned
        assert hasattr(frame, "activity_log")
        # A StaticText label should exist above the TextCtrl
        assert hasattr(frame, "_activity_log_label")
        # A dedicated panel wraps both — third column in the h_sizer
        assert hasattr(frame, "_activity_panel")
        frame.activity_log.SetMinSize.assert_called_once()

    def test_activity_log_label_created(self, app_module):
        app, fake_wx = app_module
        frame = object.__new__(app.MainFrame)
        frame._local_cwd = "/tmp"
        frame._toolbar_panel = MagicMock()

        frame._build_dual_pane()

        assert hasattr(frame, "_activity_log_label")

    def test_activity_log_visible_by_default(self, app_module):
        app, fake_wx = app_module
        frame = object.__new__(app.MainFrame)
        frame._local_cwd = "/tmp"
        frame._toolbar_panel = MagicMock()

        frame._build_dual_pane()

        assert frame._activity_log_visible is True

    def test_main_sizer_includes_log_panel(self, app_module):
        app, fake_wx = app_module
        frame = object.__new__(app.MainFrame)
        frame._local_cwd = "/tmp"
        frame._toolbar_panel = MagicMock()

        frame._build_dual_pane()

        # SetSizer is called on the frame itself (from _FakeFrame)
        # Verify pane_container and file_list were created
        assert hasattr(frame, "_pane_container")
        assert hasattr(frame, "file_list")


class TestShowTransferQueue:
    """Cover _show_transfer_queue creating a new dialog (line 1257)."""

    @staticmethod
    def _make_frame(app_module):
        app, _ = app_module
        frame = object.__new__(app.MainFrame)
        frame._announce = MagicMock()
        frame._transfer_service = MagicMock()
        frame.activity_log = MagicMock()
        frame.log_event = MagicMock()
        return frame, app

    def test_creates_new_dialog_when_none_exists(self, app_module, monkeypatch):
        frame, app = self._make_frame(app_module)
        frame._transfer_dlg = None

        mock_dialog = MagicMock()
        monkeypatch.setattr(app, "create_transfer_dialog", lambda *a, **kw: mock_dialog)

        frame._show_transfer_queue()

        assert frame._transfer_dlg is mock_dialog
        mock_dialog.Show.assert_called_once()

    def test_raises_existing_dialog(self, app_module, monkeypatch):
        frame, app = self._make_frame(app_module)
        existing = MagicMock()
        frame._transfer_dlg = existing

        frame._show_transfer_queue()

        existing.Raise.assert_called_once()

    def test_creates_new_dialog_when_existing_raises(self, app_module, monkeypatch):
        frame, app = self._make_frame(app_module)
        old_dlg = MagicMock()
        old_dlg.Raise.side_effect = RuntimeError("destroyed")
        frame._transfer_dlg = old_dlg

        mock_dialog = MagicMock()
        monkeypatch.setattr(app, "create_transfer_dialog", lambda *a, **kw: mock_dialog)

        frame._show_transfer_queue()

        assert frame._transfer_dlg is mock_dialog
        mock_dialog.Show.assert_called_once()


def _make_frame_with_log(app_module):
    """Create a MainFrame with activity log toggle support."""
    app, _ = app_module
    frame = object.__new__(app.MainFrame)
    frame._announce = MagicMock()
    frame.local_file_list = MagicMock()
    frame.remote_file_list = MagicMock()
    frame.activity_log = MagicMock()
    frame._activity_log_label = MagicMock()
    frame._activity_panel = MagicMock()
    frame._activity_log_visible = True
    frame._toggle_log_item = MagicMock()
    frame._pane_container = MagicMock()
    frame._pane_container.GetSizer = MagicMock(return_value=MagicMock())
    frame.GetSizer = MagicMock(return_value=MagicMock())
    return frame


class TestF6PaneCycling:
    """F6 cycles focus: local -> remote -> activity log -> local (when visible)."""

    def test_local_to_remote(self, app_module):
        frame = _make_frame_with_log(app_module)
        frame.FindFocus = MagicMock(return_value=frame.local_file_list)

        frame._on_switch_pane_focus(None)

        frame.remote_file_list.SetFocus.assert_called_once()
        frame._announce.assert_not_called()

    def test_remote_to_activity_log(self, app_module):
        frame = _make_frame_with_log(app_module)
        frame.FindFocus = MagicMock(return_value=frame.remote_file_list)

        frame._on_switch_pane_focus(None)

        frame.activity_log.SetFocus.assert_called_once()
        frame._announce.assert_not_called()

    def test_activity_log_to_local(self, app_module):
        frame = _make_frame_with_log(app_module)
        frame.FindFocus = MagicMock(return_value=frame.activity_log)

        frame._on_switch_pane_focus(None)

        frame.local_file_list.SetFocus.assert_called_once()
        frame._announce.assert_not_called()

    def test_local_to_remote_when_log_hidden(self, app_module):
        frame = _make_frame_with_log(app_module)
        frame._activity_log_visible = False
        frame.FindFocus = MagicMock(return_value=frame.local_file_list)

        frame._on_switch_pane_focus(None)

        frame.remote_file_list.SetFocus.assert_called_once()
        frame._announce.assert_not_called()

    def test_remote_to_local_when_log_hidden(self, app_module):
        frame = _make_frame_with_log(app_module)
        frame._activity_log_visible = False
        frame.FindFocus = MagicMock(return_value=frame.remote_file_list)

        frame._on_switch_pane_focus(None)

        frame.local_file_list.SetFocus.assert_called_once()
        frame._announce.assert_not_called()

    def test_unknown_focus_to_local_when_log_hidden(self, app_module):
        frame = _make_frame_with_log(app_module)
        frame._activity_log_visible = False
        frame.FindFocus = MagicMock(return_value=MagicMock())

        frame._on_switch_pane_focus(None)

        frame.local_file_list.SetFocus.assert_called_once()
        frame._announce.assert_not_called()


class TestToggleActivityLog:
    """View > Hide/Show Activity Log toggles panel visibility."""

    def test_hide_activity_log(self, app_module):
        frame = _make_frame_with_log(app_module)

        frame._on_toggle_activity_log(None)

        assert frame._activity_log_visible is False
        frame._activity_panel.Hide.assert_called_once()
        frame._toggle_log_item.SetItemLabel.assert_called_with("Show &Activity Log")
        frame._announce.assert_called_with("Activity log hidden")

    def test_show_activity_log(self, app_module):
        frame = _make_frame_with_log(app_module)
        frame._activity_log_visible = False

        frame._on_toggle_activity_log(None)

        assert frame._activity_log_visible is True
        frame._activity_panel.Show.assert_called_once()
        frame._toggle_log_item.SetItemLabel.assert_called_with("Hide &Activity Log")
        frame._announce.assert_called_with("Activity log shown")

    def test_toggle_round_trip(self, app_module):
        frame = _make_frame_with_log(app_module)
        assert frame._activity_log_visible is True

        frame._on_toggle_activity_log(None)
        assert frame._activity_log_visible is False

        frame._on_toggle_activity_log(None)
        assert frame._activity_log_visible is True


class TestDirectPaneFocus:
    """Ctrl+1/2/3 directly focus local, remote, and activity log panes."""

    def test_ctrl1_focuses_local(self, app_module):
        frame = _make_frame_with_log(app_module)

        frame._on_focus_local_pane(None)

        frame.local_file_list.SetFocus.assert_called_once()
        frame._announce.assert_not_called()

    def test_ctrl2_focuses_remote(self, app_module):
        frame = _make_frame_with_log(app_module)

        frame._on_focus_remote_pane(None)

        frame.remote_file_list.SetFocus.assert_called_once()
        frame._announce.assert_not_called()

    def test_ctrl3_focuses_activity_log_when_visible(self, app_module):
        frame = _make_frame_with_log(app_module)

        frame._on_focus_activity_log_pane(None)

        frame.activity_log.SetFocus.assert_called_once()
        frame._announce.assert_not_called()

    def test_ctrl3_announces_hidden_when_log_not_visible(self, app_module):
        frame = _make_frame_with_log(app_module)
        frame._activity_log_visible = False

        frame._on_focus_activity_log_pane(None)

        frame.activity_log.SetFocus.assert_not_called()
        frame._announce.assert_called_with("Activity log is hidden")
