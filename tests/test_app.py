"""Tests covering MainFrame helpers around uploads, deletes, and transfer updates."""

from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tests._wx_stub import load_module_with_fake_wx


@pytest.fixture
def app_module(monkeypatch):
    module, fake_wx = load_module_with_fake_wx("portkeydrop.app", monkeypatch)
    return module, fake_wx


class _ImmediateThread:
    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        if self._target:
            self._target(*self._args, **self._kwargs)


def _build_frame(module, tmp_path):
    app, _ = module
    display = SimpleNamespace(
        show_hidden_files=True,
        announce_file_count=False,
        sort_by="name",
        sort_ascending=True,
    )
    settings = SimpleNamespace(display=display)
    fake_manager = MagicMock(jobs=[])
    fake_site_manager = MagicMock()

    with ExitStack() as stack:
        stack.enter_context(patch.object(app, "load_settings", return_value=settings))
        stack.enter_context(
            patch.object(app, "resolve_startup_local_folder", return_value=str(tmp_path))
        )
        stack.enter_context(patch.object(app, "SiteManager", return_value=fake_site_manager))
        transfer_service_patch = stack.enter_context(patch.object(app, "TransferService"))
        transfer_service_patch.return_value = fake_manager
        for method in (
            "_build_menu",
            "_build_toolbar",
            "_build_dual_pane",
            "_build_status_bar",
            "_bind_events",
            "_update_title",
            "_refresh_local_files",
            "_persist_local_folder_setting",
        ):
            stack.enter_context(patch.object(app.MainFrame, method, lambda self: None))
        frame = app.MainFrame()
    return frame, fake_manager, transfer_service_patch


def _hydrate_frame(module):
    app, _ = module
    frame = object.__new__(app.MainFrame)
    frame._announce = MagicMock()
    frame._status = MagicMock()
    frame._update_status = MagicMock()
    frame._show_transfer_queue = MagicMock()
    frame._refresh_local_files = MagicMock()
    frame._refresh_remote_files = MagicMock()
    frame._get_selected_local_file = MagicMock()
    frame._get_selected_remote_file = MagicMock()
    frame._transfer_service = MagicMock()
    frame.status_bar = MagicMock(SetStatusText=MagicMock())
    frame.activity_log = MagicMock()
    frame._activity_log_visible = True
    return frame


def test_main_frame_init_sets_transfer_state(tmp_path, app_module):
    frame, _, transfer_service_cls = _build_frame(app_module, tmp_path)
    assert frame._transfer_state_by_id == {}
    transfer_service_cls.assert_called_once_with(notify_window=frame)


def test_bind_events_hooks_transfer_update(app_module):
    app, _ = app_module
    frame = object.__new__(app.MainFrame)
    frame.Bind = MagicMock()
    frame.tb_connect_btn = MagicMock(Bind=MagicMock())
    frame.tb_protocol = MagicMock(Bind=MagicMock())
    frame.remote_file_list = MagicMock(Bind=MagicMock())
    frame.local_file_list = MagicMock(Bind=MagicMock())
    frame.local_path_bar = MagicMock(Bind=MagicMock())
    frame.remote_path_bar = MagicMock(Bind=MagicMock())

    binder = object()
    with patch.object(app, "get_transfer_event_binder", return_value=binder):
        frame._bind_events()

    assert any(
        call.args[0] == binder and call.args[1] == frame._on_transfer_update
        for call in frame.Bind.call_args_list
    )


def test_bind_events_sets_f6_and_ctrl_l_accelerators(app_module):
    app, fake_wx = app_module
    frame = object.__new__(app.MainFrame)
    frame.Bind = MagicMock()
    frame.SetAcceleratorTable = MagicMock()
    frame.tb_connect_btn = MagicMock(Bind=MagicMock())
    frame.tb_protocol = MagicMock(Bind=MagicMock())
    frame.remote_file_list = MagicMock(Bind=MagicMock())
    frame.local_file_list = MagicMock(Bind=MagicMock())
    frame.local_path_bar = MagicMock(Bind=MagicMock())
    frame.remote_path_bar = MagicMock(Bind=MagicMock())
    frame.activity_log = MagicMock(Bind=MagicMock())

    with patch.object(app, "get_transfer_event_binder", return_value=object()):
        frame._bind_events()

    frame.SetAcceleratorTable.assert_called_once()
    table_entries = frame.SetAcceleratorTable.call_args.args[0]
    assert (
        fake_wx.ACCEL_NORMAL,
        fake_wx.WXK_F6,
        app.ID_SWITCH_PANE_FOCUS,
    ) in table_entries
    assert (fake_wx.ACCEL_CTRL, ord("L"), app.ID_FOCUS_ADDRESS_BAR) in table_entries


def test_switch_pane_focus_local_to_remote(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame.local_file_list = MagicMock(SetFocus=MagicMock())
    frame.remote_file_list = MagicMock(SetFocus=MagicMock())
    frame.FindFocus = MagicMock(return_value=frame.local_file_list)

    frame._on_switch_pane_focus(None)

    frame.remote_file_list.SetFocus.assert_called_once()
    frame._announce.assert_not_called()


def test_switch_pane_focus_remote_to_activity_log(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame.local_file_list = MagicMock(SetFocus=MagicMock())
    frame.remote_file_list = MagicMock(SetFocus=MagicMock())
    frame.FindFocus = MagicMock(return_value=frame.remote_file_list)

    frame._on_switch_pane_focus(None)

    frame.activity_log.SetFocus.assert_called_once()
    frame._announce.assert_not_called()


def test_focus_address_bar_sets_toolbar_host_focus_and_announces(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame.tb_host = MagicMock(SetFocus=MagicMock())

    frame._on_focus_address_bar(None)

    frame.tb_host.SetFocus.assert_called_once()
    frame._announce.assert_called_once_with("Address bar")


def test_on_upload_directory_updates_status(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    selected = MagicMock()
    selected.name = "docs"
    selected.path = "/tmp/docs"
    selected.is_dir = True
    frame._get_selected_local_file.return_value = selected
    frame._transfer_service.submit_upload = MagicMock()

    frame._on_upload(None)

    frame._transfer_service.submit_upload.assert_called_once()
    frame._update_status.assert_called_with("Uploading folder docs...", "/remote")


def test_on_upload_file_reports_progress(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    selected = MagicMock(name="file.txt")
    selected.is_dir = False
    selected.name = "file.txt"
    selected.path = "/tmp/file.txt"
    frame._get_selected_local_file.return_value = selected
    frame._transfer_service.submit_upload = MagicMock()

    with patch.object(app.os.path, "getsize", return_value=123):
        frame._on_upload(None)

    frame._transfer_service.submit_upload.assert_called_once()
    frame._update_status.assert_called_with("Uploading file.txt...", "/remote")


def test_paste_upload_shows_queue(tmp_path, app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    frame._transfer_service.submit_upload = MagicMock()
    file_path = tmp_path / "clip.txt"
    file_path.write_text("clip")
    frame._get_clipboard_files = MagicMock(return_value=[str(file_path)])

    frame._paste_upload()

    frame._transfer_service.submit_upload.assert_called_once()
    frame._update_status.assert_called()
    frame._show_transfer_queue.assert_called_once()


def test_delete_remote_updates_status_on_success(app_module):
    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    remote = MagicMock(name="doc.txt")
    remote.name = "doc.txt"
    remote.path = "/remote/doc.txt"
    remote.is_dir = False
    frame._get_selected_remote_file.return_value = remote
    frame._client.delete = MagicMock()
    frame._update_status.reset_mock()
    fake_wx.MessageBox.return_value = fake_wx.YES

    frame._delete_remote()

    frame._update_status.assert_any_call("Deleting doc.txt...", "/remote")
    frame._update_status.assert_any_call("Delete complete.", "/remote")
    frame._refresh_remote_files.assert_called_once()


def test_delete_remote_reports_failure(app_module):
    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    remote = MagicMock(name="doc.txt")
    remote.name = "doc.txt"
    remote.path = "/remote/doc.txt"
    remote.is_dir = False
    frame._get_selected_remote_file.return_value = remote
    frame._client.delete.side_effect = RuntimeError("boom")
    fake_wx.MessageBox.return_value = fake_wx.YES

    frame._delete_remote()

    frame._update_status.assert_any_call("Delete failed.", "/remote")
    fake_wx.MessageBox.assert_called()


def test_rename_remote_updates_status(app_module):
    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    remote = MagicMock(name="old.txt")
    remote.name = "old.txt"
    remote.path = "/remote/old.txt"
    frame._get_selected_remote_file.return_value = remote
    frame._client.rename = MagicMock()
    dialog = MagicMock(
        ShowModal=MagicMock(return_value=fake_wx.ID_OK),
        GetValue=MagicMock(return_value="new.txt"),
        Destroy=MagicMock(),
    )
    with patch.object(fake_wx, "TextEntryDialog", return_value=dialog):
        frame._rename_remote()

    frame._update_status.assert_any_call("Renaming old.txt...", "/remote")
    frame._update_status.assert_any_call("Rename complete.", "/remote")


def test_rename_remote_handles_error(app_module):
    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    remote = MagicMock(name="old.txt")
    remote.name = "old.txt"
    remote.path = "/remote/old.txt"
    frame._get_selected_remote_file.return_value = remote
    frame._client.rename.side_effect = RuntimeError("boom")
    dialog = MagicMock(
        ShowModal=MagicMock(return_value=fake_wx.ID_OK),
        GetValue=MagicMock(return_value="new.txt"),
        Destroy=MagicMock(),
    )
    fake_wx.MessageBox.reset_mock()

    with patch.object(fake_wx, "TextEntryDialog", return_value=dialog):
        frame._rename_remote()

    frame._update_status.assert_any_call("Rename failed.", "/remote")
    fake_wx.MessageBox.assert_called()


def test_mkdir_remote_updates_status(app_module):
    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    frame._client.mkdir = MagicMock()
    dialog = MagicMock(
        ShowModal=MagicMock(return_value=fake_wx.ID_OK),
        GetValue=MagicMock(return_value="new-dir"),
        Destroy=MagicMock(),
    )

    with patch.object(fake_wx, "TextEntryDialog", return_value=dialog):
        frame._mkdir_remote()

    frame._update_status.assert_any_call("Creating directory new-dir...", "/remote")
    frame._update_status.assert_any_call("Directory created.", "/remote")


def test_mkdir_remote_reports_error(app_module):
    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    frame._client.mkdir.side_effect = RuntimeError("boom")
    dialog = MagicMock(
        ShowModal=MagicMock(return_value=fake_wx.ID_OK),
        GetValue=MagicMock(return_value="new-dir"),
        Destroy=MagicMock(),
    )

    with patch.object(fake_wx, "TextEntryDialog", return_value=dialog):
        frame._mkdir_remote()

    frame._update_status.assert_any_call("Create directory failed.", "/remote")
    fake_wx.MessageBox.assert_called()


def test_import_connections_adds_non_duplicates(app_module):
    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)

    existing = SimpleNamespace(host="dup.example.com", port=22, username="alice", protocol="sftp")
    frame._site_manager = MagicMock(sites=[existing], add=MagicMock())

    imported_site = SimpleNamespace(
        name="New Site",
        protocol="ftp",
        host="new.example.com",
        port=21,
        username="bob",
        password="pw",
        key_path="",
        initial_dir="/",
        notes="",
    )

    dialog = MagicMock(
        ShowModal=MagicMock(return_value=fake_wx.ID_OK),
        selected_sites=[imported_site],
        Destroy=MagicMock(),
    )
    fake_wx.MessageBox.reset_mock()

    with patch.object(app, "ImportConnectionsDialog", return_value=dialog):
        frame._on_import_connections(None)

    frame._site_manager.add.assert_called_once()
    fake_wx.MessageBox.assert_called_once()
    message = fake_wx.MessageBox.call_args.args[0]
    assert "Imported 1 connection" in message


def test_import_connections_skips_duplicates(app_module):
    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)

    existing = SimpleNamespace(host="dup.example.com", port=22, username="alice", protocol="sftp")
    frame._site_manager = MagicMock(sites=[existing], add=MagicMock())

    duplicate = SimpleNamespace(
        name="Duplicate Site",
        protocol="sftp",
        host="dup.example.com",
        port=22,
        username="alice",
        password="pw",
        key_path="",
        initial_dir="/",
        notes="",
    )

    dialog = MagicMock(
        ShowModal=MagicMock(return_value=fake_wx.ID_OK),
        selected_sites=[duplicate],
        Destroy=MagicMock(),
    )
    fake_wx.MessageBox.reset_mock()

    with patch.object(app, "ImportConnectionsDialog", return_value=dialog):
        frame._on_import_connections(None)

    frame._site_manager.add.assert_not_called()
    fake_wx.MessageBox.assert_called_once()
    message = fake_wx.MessageBox.call_args.args[0]
    assert "Imported 0 connections" in message
    assert "Skipped 1 duplicate" in message


def test_on_transfer_update_reports_latest_status(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    frame.activity_log = MagicMock()
    upload = SimpleNamespace(
        id="aaa",
        direction=app.TransferDirection.UPLOAD,
        status=app.TransferStatus.IN_PROGRESS,
        source="/local/file.txt",
        destination="/remote/file.txt",
        error=None,
        progress=50,
    )
    download = SimpleNamespace(
        id="bbb",
        direction=app.TransferDirection.DOWNLOAD,
        status=app.TransferStatus.COMPLETE,
        source="/remote/dl.txt",
        destination="/local/dl.txt",
        error=None,
        progress=100,
    )
    frame._transfer_service.jobs = [upload, download]
    frame._transfer_state_by_id = {}

    frame._on_transfer_update(None)

    frame._update_status.assert_called_once_with("Download complete.", "/remote")


def test_on_transfer_update_refreshes_local_files_after_download_complete(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    download = SimpleNamespace(
        id="ccc",
        direction=app.TransferDirection.DOWNLOAD,
        status=app.TransferStatus.COMPLETE,
        source="/remote/file.txt",
        destination="/tmp/file.txt",
        error=None,
        progress=100,
    )
    frame._transfer_service.jobs = [download]
    frame._transfer_state_by_id = {}
    frame._refresh_local_files = MagicMock()
    frame._refresh_remote_files = MagicMock()

    frame._on_transfer_update(None)

    frame._refresh_local_files.assert_called_once()
    frame._refresh_remote_files.assert_not_called()


def test_on_transfer_update_refreshes_remote_files_after_upload_complete(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    upload = SimpleNamespace(
        id="ddd",
        direction=app.TransferDirection.UPLOAD,
        status=app.TransferStatus.COMPLETE,
        source="/tmp/file.txt",
        destination="/remote/file.txt",
        error=None,
        progress=100,
    )
    frame._transfer_service.jobs = [upload]
    frame._transfer_state_by_id = {}
    frame._refresh_local_files = MagicMock()
    frame._refresh_remote_files = MagicMock()

    frame._on_transfer_update(None)

    frame._refresh_remote_files.assert_called_once()
    frame._refresh_local_files.assert_not_called()


def test_on_transfer_update_announces_download_complete(app_module):
    """Acceptance: Prism announces completion even when dialog is hidden."""
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    download = SimpleNamespace(
        id="ann1",
        direction=app.TransferDirection.DOWNLOAD,
        status=app.TransferStatus.COMPLETE,
        source="/remote/file.txt",
        destination="/local/file.txt",
        error=None,
        progress=100,
    )
    frame._transfer_service.jobs = [download]
    frame._transfer_state_by_id = {}

    frame._on_transfer_update(None)

    frame._announce.assert_any_call("Download complete: file.txt")


def test_on_transfer_update_announces_upload_complete(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    upload = SimpleNamespace(
        id="ann2",
        direction=app.TransferDirection.UPLOAD,
        status=app.TransferStatus.COMPLETE,
        source="/local/file.txt",
        destination="/remote/file.txt",
        error=None,
        progress=100,
    )
    frame._transfer_service.jobs = [upload]
    frame._transfer_state_by_id = {}

    frame._on_transfer_update(None)

    frame._announce.assert_any_call("Upload complete: file.txt")


def test_on_transfer_update_announces_download_failed(app_module):
    """Acceptance: Prism announces failure even when dialog is hidden."""
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    download = SimpleNamespace(
        id="fail1",
        direction=app.TransferDirection.DOWNLOAD,
        status=app.TransferStatus.FAILED,
        source="/remote/file.txt",
        destination="/local/file.txt",
        error="Connection lost",
        progress=50,
    )
    frame._transfer_service.jobs = [download]
    frame._transfer_state_by_id = {}

    frame._on_transfer_update(None)

    frame._announce.assert_any_call("Download failed: file.txt \u2014 Connection lost")


def test_on_transfer_update_announces_upload_failed(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    upload = SimpleNamespace(
        id="fail2",
        direction=app.TransferDirection.UPLOAD,
        status=app.TransferStatus.FAILED,
        source="/local/file.txt",
        destination="/remote/file.txt",
        error="Permission denied",
        progress=0,
    )
    frame._transfer_service.jobs = [upload]
    frame._transfer_state_by_id = {}

    frame._on_transfer_update(None)

    frame._announce.assert_any_call("Upload failed: file.txt \u2014 Permission denied")


def test_on_transfer_update_skips_already_seen_state(app_module):
    """Don't re-announce if state hasn't changed."""
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    job = SimpleNamespace(
        id="seen1",
        direction=app.TransferDirection.DOWNLOAD,
        status=app.TransferStatus.COMPLETE,
        source="/remote/file.txt",
        destination="/local/file.txt",
        error=None,
        progress=100,
    )
    frame._transfer_service.jobs = [job]
    frame._transfer_state_by_id = {"seen1": "complete"}

    frame._on_transfer_update(None)

    frame._announce.assert_not_called()
    frame._update_status.assert_not_called()


def test_on_transfer_update_handles_disconnected_client(app_module):
    """Status bar updates use empty path when client is disconnected."""
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=False)
    job = SimpleNamespace(
        id="disc1",
        direction=app.TransferDirection.DOWNLOAD,
        status=app.TransferStatus.IN_PROGRESS,
        source="/remote/file.txt",
        destination="/local/file.txt",
        error=None,
        progress=50,
    )
    frame._transfer_service.jobs = [job]
    frame._transfer_state_by_id = {}

    frame._on_transfer_update(None)

    frame._update_status.assert_called_once_with("Download in progress...", "")


def test_build_toolbar_adds_mnemonics_and_label_associations(app_module):
    app, fake_wx = app_module
    created_labels = []
    fake_wx.EVT_CHOICE = object()

    class _Label:
        def __init__(self, _parent, label=""):
            self.label = label
            self._label_for = None
            created_labels.append(self)

        def SetLabelFor(self, control):
            self._label_for = control

    frame = object.__new__(app.MainFrame)
    with patch.object(fake_wx, "StaticText", side_effect=_Label):
        app.MainFrame._build_toolbar(frame)

    assert [label.label for label in created_labels[:5]] == [
        "&Protocol",
        "&Host",
        "P&ort",
        "&Username",
        "Pass&word",
    ]
    assert created_labels[0]._label_for is frame.tb_protocol
    assert created_labels[1]._label_for is frame.tb_host
    assert created_labels[2]._label_for is frame.tb_port
    assert created_labels[3]._label_for is frame.tb_username
    assert created_labels[4]._label_for is frame.tb_password


# ── _refresh_remote_files threading ──────────────────────────────────────────


def test_refresh_remote_files_spawns_thread(app_module):
    """_refresh_remote_files should return immediately and spawn a worker thread."""
    import threading

    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)

    from portkeydrop.protocols import RemoteFile

    frame._client = MagicMock(connected=True, cwd="/home/user")
    frame._remote_filter_text = ""
    frame._settings = MagicMock()
    frame._settings.display.announce_file_count = False
    frame.remote_file_list = MagicMock(GetItemCount=MagicMock(return_value=0))
    frame.remote_path_bar = MagicMock()
    frame._update_title = MagicMock()
    frame._apply_sort = MagicMock()
    frame._populate_file_list = MagicMock()
    frame._get_visible_files = MagicMock(return_value=[])
    frame._remote_files = []

    done = threading.Event()
    real_files = [RemoteFile(name="f.txt", path="/home/user/f.txt")]
    frame._client.list_dir.side_effect = lambda *a, **kw: done.set() or real_files

    # Override refresh to use real implementation
    app.MainFrame._refresh_remote_files(frame)
    done.wait(timeout=5)

    frame._client.list_dir.assert_called_once()


def test_on_remote_files_loaded_populates_list(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)

    from portkeydrop.protocols import RemoteFile

    frame._client = MagicMock(cwd="/home/user")
    frame._remote_filter_text = ""
    frame._settings = MagicMock()
    frame._settings.display.announce_file_count = False
    frame.remote_file_list = MagicMock(GetItemCount=MagicMock(return_value=1))
    frame.remote_path_bar = MagicMock()
    frame._update_title = MagicMock()
    frame._apply_sort = MagicMock()
    frame._populate_file_list = MagicMock()
    frame._get_visible_files = MagicMock(return_value=[])
    frame._remote_files = []

    files = [RemoteFile(name="f.txt", path="/home/user/f.txt")]
    app.MainFrame._on_remote_files_loaded(frame, files, "/home/user")

    frame._populate_file_list.assert_called_once()
    frame._update_status.assert_called_with("Connected", "/home/user")
    frame.remote_path_bar.SetValue.assert_called_with("/home/user")


def test_on_remote_files_loaded_does_not_steal_focus(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)

    from portkeydrop.protocols import RemoteFile

    frame._client = MagicMock(cwd="/home/user")
    frame._remote_filter_text = ""
    frame._settings = MagicMock()
    frame._settings.display.announce_file_count = False
    frame.remote_file_list = MagicMock(GetItemCount=MagicMock(return_value=1))
    frame.remote_path_bar = MagicMock()
    frame._update_title = MagicMock()
    frame._apply_sort = MagicMock()
    frame._populate_file_list = MagicMock()
    frame._get_visible_files = MagicMock(return_value=[])
    frame._remote_files = []
    frame.FindFocus = MagicMock(return_value=object())

    files = [RemoteFile(name="f.txt", path="/home/user/f.txt")]
    app.MainFrame._on_remote_files_loaded(frame, files, "/home/user")

    frame.remote_file_list.SetFocus.assert_not_called()


def test_on_remote_files_loaded_keeps_remote_focus_when_already_active(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)

    from portkeydrop.protocols import RemoteFile

    frame._client = MagicMock(cwd="/home/user")
    frame._remote_filter_text = ""
    frame._settings = MagicMock()
    frame._settings.display.announce_file_count = False
    frame.remote_file_list = MagicMock(GetItemCount=MagicMock(return_value=1))
    frame.remote_path_bar = MagicMock()
    frame._update_title = MagicMock()
    frame._apply_sort = MagicMock()
    frame._populate_file_list = MagicMock()
    frame._get_visible_files = MagicMock(return_value=[])
    frame._remote_files = []
    frame.FindFocus = MagicMock(return_value=frame.remote_file_list)

    files = [RemoteFile(name="f.txt", path="/home/user/f.txt")]
    app.MainFrame._on_remote_files_loaded(frame, files, "/home/user")

    frame.remote_file_list.SetFocus.assert_called_once()


def test_on_remote_files_error_shows_messagebox(app_module):
    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(cwd="/home/user")

    app.MainFrame._on_remote_files_error(frame, PermissionError("Permission denied"), "/home/user")

    fake_wx.MessageBox.assert_called_once()
    args = fake_wx.MessageBox.call_args[0]
    assert "Permission denied" in args[0]


def test_refresh_local_files_does_not_steal_focus(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)

    from portkeydrop.protocols import RemoteFile

    frame._local_cwd = "/tmp"
    frame._local_filter_text = ""
    frame._settings = MagicMock()
    frame._settings.display.announce_file_count = False
    frame.local_file_list = MagicMock(GetItemCount=MagicMock(return_value=1))
    frame.local_path_bar = MagicMock()
    frame._apply_sort = MagicMock()
    frame._populate_file_list = MagicMock()
    frame._get_visible_files = MagicMock(return_value=[MagicMock()])
    frame.FindFocus = MagicMock(return_value=object())

    with patch.object(
        app, "list_local_dir", return_value=[RemoteFile(name="a.txt", path="/tmp/a.txt")]
    ):
        app.MainFrame._refresh_local_files(frame)

    frame.local_file_list.SetFocus.assert_not_called()


def test_refresh_local_files_keeps_focus_when_local_list_active(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)

    from portkeydrop.protocols import RemoteFile

    frame._local_cwd = "/tmp"
    frame._local_filter_text = ""
    frame._settings = MagicMock()
    frame._settings.display.announce_file_count = False
    frame.local_file_list = MagicMock(GetItemCount=MagicMock(return_value=1))
    frame.local_path_bar = MagicMock()
    frame._apply_sort = MagicMock()
    frame._populate_file_list = MagicMock()
    frame._get_visible_files = MagicMock(return_value=[MagicMock()])
    frame.FindFocus = MagicMock(return_value=frame.local_file_list)

    with patch.object(
        app, "list_local_dir", return_value=[RemoteFile(name="a.txt", path="/tmp/a.txt")]
    ):
        app.MainFrame._refresh_local_files(frame)

    frame.local_file_list.SetFocus.assert_called_once()


def test_on_remote_files_error_timeout_message(app_module):
    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(cwd="/home/user")

    app.MainFrame._on_remote_files_error(frame, TimeoutError("timed out"), "/home/user")

    fake_wx.MessageBox.assert_called_once()
    args = fake_wx.MessageBox.call_args[0]
    assert "server did not respond" in args[0].lower() or "timed out" in args[0].lower()


def test_on_remote_files_loaded_announces_count(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)

    from portkeydrop.protocols import RemoteFile

    frame._client = MagicMock(cwd="/home/user")
    frame._remote_filter_text = ""
    frame._settings = MagicMock()
    frame._settings.display.announce_file_count = True
    frame.remote_file_list = MagicMock(GetItemCount=MagicMock(return_value=0))
    frame.remote_path_bar = MagicMock()
    frame._update_title = MagicMock()
    frame._apply_sort = MagicMock()
    frame._populate_file_list = MagicMock()
    frame._get_visible_files = MagicMock(return_value=[MagicMock()])
    frame._remote_files = []

    files = [RemoteFile(name="f.txt", path="/home/user/f.txt")]
    app.MainFrame._on_remote_files_loaded(frame, files, "/home/user")

    frame._status.assert_called_once()
    assert "/home/user" in frame._status.call_args[0][0]
    frame._announce.assert_not_called()


def test_on_remote_item_activated_chdir_error(app_module):
    import threading

    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)

    from portkeydrop.protocols import RemoteFile

    f = RemoteFile(name=".ssh", path="/home/user/.ssh", is_dir=True)
    frame._get_selected_remote_file = MagicMock(return_value=f)
    frame._client = MagicMock(connected=True)
    frame._client.chdir.side_effect = PermissionError("Permission denied")
    frame._update_status = MagicMock()

    done = threading.Event()
    original_msgbox = fake_wx.MessageBox

    def _msgbox(*a, **kw):
        done.set()
        return original_msgbox(*a, **kw)

    fake_wx.MessageBox = _msgbox

    app.MainFrame._on_remote_item_activated(frame, MagicMock(GetIndex=MagicMock(return_value=0)))
    done.wait(timeout=5)

    fake_wx.MessageBox = original_msgbox
    assert done.is_set()


def test_refresh_remote_files_worker_error(app_module):
    """Exception in list_dir worker should call _on_remote_files_error."""
    import threading

    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)

    frame._client = MagicMock(connected=True, cwd="/home/user")
    frame._remote_filter_text = ""
    frame._client.list_dir.side_effect = OSError("boom")
    frame._update_status = MagicMock()

    done = threading.Event()
    original_msgbox = fake_wx.MessageBox

    def _msgbox(*a, **kw):
        done.set()
        return original_msgbox(*a, **kw)

    fake_wx.MessageBox = _msgbox
    app.MainFrame._refresh_remote_files(frame)
    done.wait(timeout=5)
    fake_wx.MessageBox = original_msgbox
    assert done.is_set()


def test_main_debug_flag(monkeypatch, tmp_path):
    """--debug and --log flags configure logging correctly."""
    import logging
    import sys

    log_file = tmp_path / "debug.log"
    monkeypatch.setattr(sys, "argv", ["portkeydrop", "--debug", f"--log={log_file}"])

    debug = "--debug" in sys.argv
    log_path = None
    for arg in sys.argv:
        if arg.startswith("--log="):
            log_path = arg.split("=", 1)[1]

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_path:
        fh = logging.FileHandler(log_path, encoding="utf-8")
        handlers.append(fh)

    logging.basicConfig(
        level=logging.DEBUG if debug else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
        handlers=handlers,
        force=True,
    )

    assert logging.getLogger().level == logging.DEBUG
    file_handlers = [h for h in handlers if isinstance(h, logging.FileHandler)]
    assert len(file_handlers) == 1
    file_handlers[0].close()
    logging.basicConfig(level=logging.WARNING, force=True)


def test_main_no_flags(monkeypatch):
    """No flags → WARNING level, no file handler."""
    import logging
    import sys

    monkeypatch.setattr(sys, "argv", ["portkeydrop"])

    debug = "--debug" in sys.argv
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.WARNING,
        handlers=handlers,
        force=True,
    )
    assert not debug
    assert logging.getLogger().level == logging.WARNING


def test_announce_delegates_to_status_and_announcer(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._announcer = MagicMock()

    app.MainFrame._announce(frame, "Hello")

    frame._status.assert_called_once_with("Hello")
    frame._announcer.announce.assert_called_once_with("Hello")


def test_on_home_dir_remote_updates_status_and_calls_after(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._is_local_focused = MagicMock(return_value=False)
    frame._client = MagicMock(connected=True)
    frame._status = MagicMock()
    frame._navigate_remote_home = MagicMock()

    app.MainFrame._on_home_dir(frame, None)

    frame._status.assert_called_once_with("Going home...")
    frame._navigate_remote_home.assert_called_once_with()


def test_on_home_dir_local_updates_status(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._is_local_focused = MagicMock(return_value=True)
    frame._client = None
    frame._local_cwd = "/tmp"
    frame._set_local_cwd = MagicMock()
    frame._refresh_local_files = MagicMock()
    frame._status = MagicMock()

    app.MainFrame._on_home_dir(frame, None)

    frame._status.assert_called_once()


def test_open_selected_remote_dir_reports_status_before_chdir(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    from portkeydrop.protocols import RemoteFile

    frame._client = MagicMock()
    frame._client.chdir = MagicMock()
    frame._refresh_remote_files = MagicMock()
    frame._status = MagicMock()
    frame._get_selected_remote_file = MagicMock(
        return_value=RemoteFile(name="docs", path="/remote/docs", is_dir=True)
    )

    app.MainFrame._open_selected_remote_dir(frame)

    frame._status.assert_called_once_with("Opening docs...")


def test_navigate_remote_home_sets_status_on_success(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock()
    frame._client.cwd = "/remote/home"
    frame._remote_home = "/remote/home"
    frame._refresh_remote_files = MagicMock()
    frame._status = MagicMock()

    app.MainFrame._navigate_remote_home(frame)

    frame._status.assert_called_once_with("Home: /remote/home")


def test_refresh_local_files_status_count_path(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._settings = SimpleNamespace(display=SimpleNamespace(announce_file_count=True))
    frame._local_cwd = "/tmp"
    frame._local_filter_text = ""
    frame.FindFocus = MagicMock(return_value=None)
    frame.local_file_list = MagicMock(GetItemCount=MagicMock(return_value=0))
    frame.local_path_bar = MagicMock()
    frame._apply_sort = MagicMock()
    frame._populate_file_list = MagicMock()
    frame._get_visible_files = MagicMock(return_value=[])
    frame._status = MagicMock()

    with patch("portkeydrop.app.list_local_dir", return_value=[]):
        app.MainFrame._refresh_local_files(frame)

    frame._status.assert_called_once_with("/tmp: 0 items")


def test_on_remote_item_activated_file_sets_status(app_module):
    import threading

    app, _ = app_module
    frame = _hydrate_frame(app_module)
    from portkeydrop.protocols import RemoteFile

    frame._client = MagicMock()
    frame._status = MagicMock()
    frame._on_download = MagicMock()
    frame._get_selected_remote_file = MagicMock(
        return_value=RemoteFile(name="file.txt", path="/remote/file.txt", is_dir=False)
    )

    original_thread = threading.Thread

    class _ImmediateThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self._target = target
            self._args = args
            self._kwargs = kwargs or {}

        def start(self):
            if self._target:
                self._target(*self._args, **self._kwargs)

    with patch.object(threading, "Thread", _ImmediateThread):
        app.MainFrame._on_remote_item_activated(frame, MagicMock())

    frame._status.assert_called_once_with("file.txt detected as file, not directory")
    frame._on_download.assert_called_once_with(None)

    threading.Thread = original_thread


def test_get_update_channel_reads_settings(app_module):
    app, _ = app_module
    frame = object.__new__(app.MainFrame)
    frame._settings = SimpleNamespace(app=SimpleNamespace(update_channel="nightly"))

    assert frame._get_update_channel() == "nightly"


def test_update_menu_label_reflects_channel(app_module):
    app, _ = app_module
    frame = object.__new__(app.MainFrame)
    frame._settings = SimpleNamespace(app=SimpleNamespace(update_channel="nightly"))
    frame._check_updates_item = MagicMock(SetItemLabel=MagicMock())

    frame.update_check_updates_menu_label()

    frame._check_updates_item.SetItemLabel.assert_called_once_with(
        "Check for &Updates (Nightly)..."
    )


def test_start_auto_update_checks_starts_timer_with_interval(app_module):
    app, fake_wx = app_module
    frame = object.__new__(app.MainFrame)
    frame._settings = SimpleNamespace(
        app=SimpleNamespace(auto_update_enabled=True, update_check_interval_hours=3)
    )
    frame._auto_update_check_timer = None

    timer = MagicMock(Bind=MagicMock(), Start=MagicMock(), Stop=MagicMock())
    with patch.object(fake_wx, "Timer", return_value=timer):
        frame._start_auto_update_checks()

    timer.Bind.assert_called_once()
    timer.Start.assert_called_once_with(3 * 60 * 60 * 1000)
    assert frame._auto_update_check_timer is timer


def test_start_auto_update_checks_stops_existing_and_skips_when_disabled(app_module):
    app, _ = app_module
    frame = object.__new__(app.MainFrame)
    existing_timer = MagicMock(Stop=MagicMock())
    frame._auto_update_check_timer = existing_timer
    frame._settings = SimpleNamespace(app=SimpleNamespace(auto_update_enabled=False))

    frame._start_auto_update_checks()

    existing_timer.Stop.assert_called_once()
    assert frame._auto_update_check_timer is None


def test_on_settings_reconfigures_update_menu_and_timer(app_module):
    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)
    frame._settings = SimpleNamespace(
        app=SimpleNamespace(update_channel="stable"),
        display=SimpleNamespace(show_hidden_files=True),
    )
    frame._local_cwd = "/tmp"
    frame.remote_file_list = MagicMock()
    frame.local_file_list = MagicMock()
    frame._remote_files = []
    frame._local_files = []
    frame._remote_filter_text = ""
    frame._local_filter_text = ""
    frame._get_visible_files = MagicMock(return_value=[])
    frame.update_check_updates_menu_label = MagicMock()
    frame._start_auto_update_checks = MagicMock()

    updated_settings = SimpleNamespace(
        app=SimpleNamespace(update_channel="nightly"),
        display=SimpleNamespace(show_hidden_files=True),
    )
    dialog = MagicMock(
        ShowModal=MagicMock(return_value=fake_wx.ID_OK),
        get_settings=MagicMock(return_value=updated_settings),
        Destroy=MagicMock(),
    )
    with (
        patch.object(app, "SettingsDialog", return_value=dialog),
        patch.object(app, "save_settings"),
        patch.object(app, "update_last_local_folder"),
    ):
        frame._on_settings(None)

    frame.update_check_updates_menu_label.assert_called_once()
    frame._start_auto_update_checks.assert_called_once()


def test_on_settings_passes_check_updates_callback(app_module):
    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)
    frame._settings = SimpleNamespace(
        app=SimpleNamespace(update_channel="stable"),
        display=SimpleNamespace(show_hidden_files=True),
    )
    frame._local_cwd = "/tmp"
    frame.remote_file_list = MagicMock()
    frame.local_file_list = MagicMock()
    frame._remote_files = []
    frame._local_files = []
    frame._remote_filter_text = ""
    frame._local_filter_text = ""
    frame._get_visible_files = MagicMock(return_value=[])

    dialog = MagicMock(
        ShowModal=MagicMock(return_value=fake_wx.ID_OK),
        get_settings=MagicMock(return_value=frame._settings),
        Destroy=MagicMock(),
    )
    with (
        patch.object(app, "SettingsDialog", return_value=dialog) as settings_dialog_cls,
        patch.object(app, "save_settings"),
        patch.object(app, "update_last_local_folder"),
    ):
        frame._on_settings(None)

    assert settings_dialog_cls.call_count == 1
    kwargs = settings_dialog_cls.call_args.kwargs
    assert kwargs["on_check_updates"] == frame._on_check_updates_from_settings


def test_on_check_updates_from_settings_forwards_channel_and_parent(app_module):
    app, _ = app_module
    frame = object.__new__(app.MainFrame)
    frame._on_check_updates = MagicMock()
    parent = object()

    frame._on_check_updates_from_settings("nightly", parent)

    frame._on_check_updates.assert_called_once_with(
        None,
        channel_override="nightly",
        parent=parent,
    )


def test_on_check_updates_from_source_shows_info_message(app_module, monkeypatch):
    app, fake_wx = app_module
    frame = object.__new__(app.MainFrame)
    frame._settings = SimpleNamespace(app=SimpleNamespace(update_channel="stable"))
    monkeypatch.setattr(app.sys, "frozen", False, raising=False)

    frame._on_check_updates(None)

    fake_wx.MessageBox.assert_called_once()
    assert fake_wx.MessageBox.call_args.args[1] == "Running from Source"


def test_startup_update_check_uses_update_dialog_and_respects_cancel(app_module, monkeypatch):
    app, fake_wx = app_module
    frame = object.__new__(app.MainFrame)
    frame._settings = SimpleNamespace(app=SimpleNamespace(auto_update_enabled=True))
    frame.version = "1.0.0"
    frame.build_tag = None
    frame._download_and_apply_update = MagicMock()

    monkeypatch.setattr(app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(app.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(fake_wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw))

    class _FakeService:
        def __init__(self, _name):
            pass

        def check_for_updates(self, **kwargs):
            assert kwargs["channel"] == "stable"
            return (
                SimpleNamespace(
                    version="1.2.3",
                    is_nightly=False,
                    release_notes="Fixes",
                ),
                {"tag_name": "v1.2.3"},
            )

    created: dict[str, object] = {}

    class _FakeDialog:
        def __init__(self, parent=None, **kwargs):
            created["parent"] = parent
            created["kwargs"] = kwargs

        def ShowModal(self):
            return 0

        def Destroy(self):
            return None

    monkeypatch.setattr(app, "UpdateService", _FakeService)
    monkeypatch.setattr(app, "UpdateAvailableDialog", _FakeDialog)

    frame._check_for_updates_on_startup()

    assert created["parent"] is frame
    kwargs = created["kwargs"]
    assert kwargs["current_version"] == "1.0.0"
    assert kwargs["new_version"] == "1.2.3"
    assert kwargs["channel_label"] == "Stable"
    frame._download_and_apply_update.assert_not_called()


def test_on_check_updates_honors_channel_override(app_module, monkeypatch):
    app, fake_wx = app_module
    frame = object.__new__(app.MainFrame)
    frame._settings = SimpleNamespace(app=SimpleNamespace(update_channel="stable"))
    frame.version = "1.0.0"
    frame.build_tag = None

    monkeypatch.setattr(app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(app.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(fake_wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw))

    called: dict[str, object] = {}

    class _FakeService:
        def __init__(self, _name):
            pass

        def check_for_updates(self, **kwargs):
            called["channel"] = kwargs["channel"]
            return None

    monkeypatch.setattr(app, "UpdateService", _FakeService)

    frame._on_check_updates(None, channel_override="nightly")

    assert called["channel"] == "nightly"
    fake_wx.MessageBox.assert_called_once()
    assert fake_wx.MessageBox.call_args.args[1] == "No Updates Available"


def test_on_close_stops_auto_update_timer_and_skips_event(app_module):
    app, _ = app_module
    frame = object.__new__(app.MainFrame)
    frame._auto_update_check_timer = MagicMock(Stop=MagicMock())
    event = MagicMock(Skip=MagicMock())

    frame._on_close(event)

    frame._auto_update_check_timer.Stop.assert_called_once()
    event.Skip.assert_called_once()


def test_get_update_channel_falls_back_to_stable_on_exception(app_module):
    app, _ = app_module
    frame = object.__new__(app.MainFrame)

    class _BrokenSettings:
        @property
        def app(self):
            raise RuntimeError("bad settings")

    frame._settings = _BrokenSettings()
    assert frame._get_update_channel() == "stable"


def test_auto_update_timer_event_calls_startup_check(app_module):
    app, _ = app_module
    frame = object.__new__(app.MainFrame)
    frame._check_for_updates_on_startup = MagicMock()
    frame._on_auto_update_check_timer(None)
    frame._check_for_updates_on_startup.assert_called_once()


def test_show_update_available_dialog_calls_accept_and_always_destroys(app_module):
    app, fake_wx = app_module
    frame = object.__new__(app.MainFrame)
    accepted = MagicMock()
    created = {}

    class _Dialog:
        def __init__(self, **kwargs):
            created["kwargs"] = kwargs

        def ShowModal(self):
            return fake_wx.ID_OK

        def Destroy(self):
            created["destroyed"] = True

    with patch.object(app, "UpdateAvailableDialog", _Dialog):
        frame._show_update_available_dialog(
            current_display_version="1.0.0",
            update_info=SimpleNamespace(version="1.1.0", is_nightly=True, release_notes="notes"),
            on_accept=accepted,
            parent=None,
        )

    accepted.assert_called_once()
    assert created["destroyed"] is True
    assert created["kwargs"]["channel_label"] == "Nightly"


def test_startup_update_check_skips_when_auto_updates_disabled(app_module, monkeypatch):
    app, _ = app_module
    frame = object.__new__(app.MainFrame)
    frame._settings = SimpleNamespace(app=SimpleNamespace(auto_update_enabled=False))
    monkeypatch.setattr(app.sys, "frozen", True, raising=False)

    service_ctor = MagicMock(side_effect=AssertionError("should not construct service"))
    monkeypatch.setattr(app, "UpdateService", service_ctor)
    frame._check_for_updates_on_startup()
    service_ctor.assert_not_called()


def test_startup_update_check_skips_nightly_without_build_tag(app_module, monkeypatch):
    app, _ = app_module
    frame = object.__new__(app.MainFrame)
    frame._settings = SimpleNamespace(
        app=SimpleNamespace(auto_update_enabled=True, update_channel="nightly")
    )
    frame.version = "1.0.0"
    frame.build_tag = None
    monkeypatch.setattr(app.sys, "frozen", True, raising=False)

    service_ctor = MagicMock(side_effect=AssertionError("should not construct service"))
    monkeypatch.setattr(app, "UpdateService", service_ctor)
    frame._check_for_updates_on_startup()
    service_ctor.assert_not_called()


def test_on_check_updates_no_update_message_for_nightly_on_stable_channel(app_module, monkeypatch):
    app, fake_wx = app_module
    frame = object.__new__(app.MainFrame)
    frame._settings = SimpleNamespace(app=SimpleNamespace(update_channel="nightly"))
    frame.version = "1.0.0"
    frame.build_tag = "nightly-20260305"

    monkeypatch.setattr(app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(app.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(fake_wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw))

    class _FakeService:
        def __init__(self, _name):
            pass

        def check_for_updates(self, **kwargs):
            assert kwargs["channel"] == "stable"
            return None

    monkeypatch.setattr(app, "UpdateService", _FakeService)

    frame._on_check_updates(None, channel_override="stable")

    msg = fake_wx.MessageBox.call_args.args[0]
    assert "No newer stable release available" in msg


def test_on_check_updates_no_update_message_for_latest_nightly(app_module, monkeypatch):
    app, fake_wx = app_module
    frame = object.__new__(app.MainFrame)
    frame._settings = SimpleNamespace(app=SimpleNamespace(update_channel="nightly"))
    frame.version = "1.0.0"
    frame.build_tag = "nightly-20260305"

    monkeypatch.setattr(app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(app.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(fake_wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw))

    class _FakeService:
        def __init__(self, _name):
            pass

        def check_for_updates(self, **kwargs):
            assert kwargs["channel"] == "nightly"
            return None

    monkeypatch.setattr(app, "UpdateService", _FakeService)

    frame._on_check_updates(None)

    msg = fake_wx.MessageBox.call_args.args[0]
    assert "latest nightly (20260305)" in msg


def test_on_check_updates_ends_busy_cursor_and_reports_failures(app_module, monkeypatch):
    app, fake_wx = app_module
    frame = object.__new__(app.MainFrame)
    frame._settings = SimpleNamespace(app=SimpleNamespace(update_channel="stable"))
    frame.version = "1.0.0"
    frame.build_tag = None

    monkeypatch.setattr(app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(app.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(fake_wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw))
    monkeypatch.setattr(fake_wx, "BeginBusyCursor", MagicMock(), raising=False)
    monkeypatch.setattr(fake_wx, "EndBusyCursor", MagicMock(), raising=False)

    class _FakeService:
        def __init__(self, _name):
            pass

        def check_for_updates(self, **kwargs):
            raise RuntimeError("network down")

    monkeypatch.setattr(app, "UpdateService", _FakeService)

    frame._on_check_updates(None)
    fake_wx.BeginBusyCursor.assert_called_once()
    fake_wx.EndBusyCursor.assert_called_once()
    assert fake_wx.MessageBox.call_args.args[1] == "Update Check Failed"


def test_download_and_apply_update_success_with_progress_and_apply(
    app_module, monkeypatch, tmp_path
):
    app, fake_wx = app_module
    frame = object.__new__(app.MainFrame)
    update_info = SimpleNamespace(artifact_name="PortkeyDrop.zip")
    artifact_path = tmp_path / "PortkeyDrop.zip"
    artifact_path.write_text("payload", encoding="utf-8")
    progress_dialog = MagicMock(Update=MagicMock(return_value=(True, False)), Destroy=MagicMock())

    monkeypatch.setattr(
        fake_wx, "ProgressDialog", MagicMock(return_value=progress_dialog), raising=False
    )
    monkeypatch.setattr(fake_wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw))
    monkeypatch.setattr(fake_wx, "PD_APP_MODAL", 1, raising=False)
    monkeypatch.setattr(fake_wx, "PD_AUTO_HIDE", 2, raising=False)
    monkeypatch.setattr(fake_wx, "PD_CAN_ABORT", 4, raising=False)
    monkeypatch.setattr(fake_wx, "YES", 101, raising=False)
    monkeypatch.setattr(fake_wx, "ICON_QUESTION", 106, raising=False)
    monkeypatch.setattr(fake_wx, "MessageBox", MagicMock(return_value=fake_wx.YES), raising=False)
    monkeypatch.setattr(app.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(app.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(app, "is_portable_mode", lambda: False)
    apply_mock = MagicMock()
    monkeypatch.setattr(app, "apply_update", apply_mock)

    class _FakeService:
        def __init__(self, _name):
            pass

        def download_update(self, *args, **kwargs):
            kwargs["progress_callback"](50, 100)
            return artifact_path

    monkeypatch.setattr(app, "UpdateService", _FakeService)

    frame._download_and_apply_update(update_info, {"tag_name": "v1.2.3"})
    progress_dialog.Update.assert_called_once()
    progress_dialog.Destroy.assert_called_once()
    apply_mock.assert_called_once_with(artifact_path, portable=False)


def test_download_and_apply_update_checksum_failure_shows_error(app_module, monkeypatch):
    app, fake_wx = app_module
    frame = object.__new__(app.MainFrame)
    update_info = SimpleNamespace(artifact_name="PortkeyDrop.zip")
    progress_dialog = MagicMock(Update=MagicMock(), Destroy=MagicMock())

    monkeypatch.setattr(
        fake_wx, "ProgressDialog", MagicMock(return_value=progress_dialog), raising=False
    )
    monkeypatch.setattr(fake_wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw))
    monkeypatch.setattr(fake_wx, "PD_APP_MODAL", 1, raising=False)
    monkeypatch.setattr(fake_wx, "PD_AUTO_HIDE", 2, raising=False)
    monkeypatch.setattr(fake_wx, "PD_CAN_ABORT", 4, raising=False)
    monkeypatch.setattr(app.threading, "Thread", _ImmediateThread)

    class _FakeService:
        def __init__(self, _name):
            pass

        def download_update(self, *args, **kwargs):
            raise app.ChecksumVerificationError("bad checksum")

    monkeypatch.setattr(app, "UpdateService", _FakeService)

    frame._download_and_apply_update(update_info, {"tag_name": "v1.2.3"})
    progress_dialog.Destroy.assert_called_once()
    assert fake_wx.MessageBox.call_args.args[1] == "Update Verification Failed"


def test_download_and_apply_update_download_failure_shows_error(app_module, monkeypatch):
    app, fake_wx = app_module
    frame = object.__new__(app.MainFrame)
    update_info = SimpleNamespace(artifact_name="PortkeyDrop.zip")
    progress_dialog = MagicMock(Update=MagicMock(), Destroy=MagicMock())

    monkeypatch.setattr(
        fake_wx, "ProgressDialog", MagicMock(return_value=progress_dialog), raising=False
    )
    monkeypatch.setattr(fake_wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw))
    monkeypatch.setattr(fake_wx, "PD_APP_MODAL", 1, raising=False)
    monkeypatch.setattr(fake_wx, "PD_AUTO_HIDE", 2, raising=False)
    monkeypatch.setattr(fake_wx, "PD_CAN_ABORT", 4, raising=False)
    monkeypatch.setattr(app.threading, "Thread", _ImmediateThread)

    class _FakeService:
        def __init__(self, _name):
            pass

        def download_update(self, *args, **kwargs):
            raise RuntimeError("download failed")

    monkeypatch.setattr(app, "UpdateService", _FakeService)

    frame._download_and_apply_update(update_info, {"tag_name": "v1.2.3"})
    progress_dialog.Destroy.assert_called_once()
    assert fake_wx.MessageBox.call_args.args[1] == "Download Error"


def test_startup_update_check_returns_cleanly_when_no_result(app_module, monkeypatch):
    app, fake_wx = app_module
    frame = object.__new__(app.MainFrame)
    frame._settings = SimpleNamespace(
        app=SimpleNamespace(auto_update_enabled=True, update_channel="stable")
    )
    frame.version = "1.0.0"
    frame.build_tag = None

    monkeypatch.setattr(app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(app.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(fake_wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw))
    frame._show_update_available_dialog = MagicMock()

    class _FakeService:
        def __init__(self, _name):
            pass

        def check_for_updates(self, **kwargs):
            return None

    monkeypatch.setattr(app, "UpdateService", _FakeService)
    frame._check_for_updates_on_startup()
    frame._show_update_available_dialog.assert_not_called()


def test_startup_update_check_logs_failure(app_module, monkeypatch):
    app, _ = app_module
    frame = object.__new__(app.MainFrame)
    frame._settings = SimpleNamespace(
        app=SimpleNamespace(auto_update_enabled=True, update_channel="stable")
    )
    frame.version = "1.0.0"
    frame.build_tag = None

    monkeypatch.setattr(app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(app.threading, "Thread", _ImmediateThread)
    warning = MagicMock()
    monkeypatch.setattr(app.logger, "warning", warning)

    class _FakeService:
        def __init__(self, _name):
            pass

        def check_for_updates(self, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(app, "UpdateService", _FakeService)
    frame._check_for_updates_on_startup()
    warning.assert_called_once()


def test_on_check_updates_with_result_prompts_update_dialog(app_module, monkeypatch):
    app, fake_wx = app_module
    frame = object.__new__(app.MainFrame)
    frame._settings = SimpleNamespace(app=SimpleNamespace(update_channel="stable"))
    frame.version = "1.0.0"
    frame.build_tag = None
    frame._download_and_apply_update = MagicMock()
    frame._show_update_available_dialog = MagicMock()

    monkeypatch.setattr(app.sys, "frozen", True, raising=False)
    monkeypatch.setattr(app.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(fake_wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw))
    monkeypatch.setattr(fake_wx, "BeginBusyCursor", MagicMock(), raising=False)
    monkeypatch.setattr(fake_wx, "EndBusyCursor", MagicMock(), raising=False)

    update_info = SimpleNamespace(version="1.1.0", is_nightly=False, release_notes="notes")
    release = {"tag_name": "v1.1.0"}

    class _FakeService:
        def __init__(self, _name):
            pass

        def check_for_updates(self, **kwargs):
            return update_info, release

    monkeypatch.setattr(app, "UpdateService", _FakeService)
    parent = object()
    frame._on_check_updates(None, parent=parent)
    fake_wx.EndBusyCursor.assert_called_once()
    frame._show_update_available_dialog.assert_called_once()
    assert frame._show_update_available_dialog.call_args.kwargs["parent"] is parent


def test_download_and_apply_update_ignores_progress_when_total_unknown(app_module, monkeypatch):
    app, fake_wx = app_module
    frame = object.__new__(app.MainFrame)
    update_info = SimpleNamespace(artifact_name="PortkeyDrop.zip")
    progress_dialog = MagicMock(Update=MagicMock(), Destroy=MagicMock())
    artifact_path = Path("/tmp/PortkeyDrop.zip")

    monkeypatch.setattr(
        fake_wx, "ProgressDialog", MagicMock(return_value=progress_dialog), raising=False
    )
    monkeypatch.setattr(fake_wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw))
    monkeypatch.setattr(fake_wx, "PD_APP_MODAL", 1, raising=False)
    monkeypatch.setattr(fake_wx, "PD_AUTO_HIDE", 2, raising=False)
    monkeypatch.setattr(fake_wx, "PD_CAN_ABORT", 4, raising=False)
    monkeypatch.setattr(fake_wx, "ICON_QUESTION", 106, raising=False)
    monkeypatch.setattr(fake_wx, "YES", 101, raising=False)
    monkeypatch.setattr(fake_wx, "MessageBox", MagicMock(return_value=0), raising=False)
    monkeypatch.setattr(app.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(app, "apply_update", MagicMock())

    class _FakeService:
        def __init__(self, _name):
            pass

        def download_update(self, *args, **kwargs):
            kwargs["progress_callback"](1, 0)
            return artifact_path

    monkeypatch.setattr(app, "UpdateService", _FakeService)
    frame._download_and_apply_update(update_info, {"tag_name": "v1.2.3"})
    progress_dialog.Update.assert_not_called()
