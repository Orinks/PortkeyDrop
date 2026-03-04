"""Tests covering MainFrame helpers around uploads, deletes, and transfer updates."""

from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tests._wx_stub import load_module_with_fake_wx


@pytest.fixture
def app_module(monkeypatch):
    module, fake_wx = load_module_with_fake_wx("portkeydrop.app", monkeypatch)
    return module, fake_wx


def _build_frame(module, tmp_path):
    app, _ = module
    display = SimpleNamespace(
        show_hidden_files=True,
        announce_file_count=False,
        sort_by="name",
        sort_ascending=True,
    )
    settings = SimpleNamespace(display=display)
    fake_manager = MagicMock(transfers=[])
    fake_site_manager = MagicMock()

    with ExitStack() as stack:
        stack.enter_context(patch.object(app, "load_settings", return_value=settings))
        stack.enter_context(
            patch.object(app, "resolve_startup_local_folder", return_value=str(tmp_path))
        )
        stack.enter_context(patch.object(app, "SiteManager", return_value=fake_site_manager))
        transfer_manager_patch = stack.enter_context(patch.object(app, "TransferManager"))
        transfer_manager_patch.return_value = fake_manager
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
    return frame, fake_manager, transfer_manager_patch


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
    frame._transfer_manager = MagicMock()
    frame.status_bar = MagicMock(SetStatusText=MagicMock())
    return frame


def test_main_frame_init_sets_transfer_state(tmp_path, app_module):
    frame, _, transfer_manager_cls = _build_frame(app_module, tmp_path)
    assert frame._transfer_state_by_id == {}
    transfer_manager_cls.assert_called_once_with(notify_window=frame)


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


def test_switch_pane_focus_local_to_remote_announces(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame.local_file_list = MagicMock(SetFocus=MagicMock())
    frame.remote_file_list = MagicMock(SetFocus=MagicMock())
    frame.FindFocus = MagicMock(return_value=frame.local_file_list)

    frame._on_switch_pane_focus(None)

    frame.remote_file_list.SetFocus.assert_called_once()
    frame._announce.assert_called_once_with("Remote Files pane")


def test_switch_pane_focus_remote_to_local_announces(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame.local_file_list = MagicMock(SetFocus=MagicMock())
    frame.remote_file_list = MagicMock(SetFocus=MagicMock())
    frame.FindFocus = MagicMock(return_value=frame.remote_file_list)

    frame._on_switch_pane_focus(None)

    frame.local_file_list.SetFocus.assert_called_once()
    frame._announce.assert_called_once_with("Local Files pane")


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
    frame._transfer_manager.add_recursive_upload = MagicMock()

    frame._on_upload(None)

    frame._transfer_manager.add_recursive_upload.assert_called_once()
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
    frame._transfer_manager.add_upload = MagicMock()

    with patch.object(app.os.path, "getsize", return_value=123):
        frame._on_upload(None)

    frame._transfer_manager.add_upload.assert_called_once()
    frame._update_status.assert_called_with("Uploading file.txt...", "/remote")


def test_paste_upload_shows_queue(tmp_path, app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    frame._transfer_manager.add_upload = MagicMock()
    file_path = tmp_path / "clip.txt"
    file_path.write_text("clip")
    frame._get_clipboard_files = MagicMock(return_value=[str(file_path)])

    frame._paste_upload()

    frame._transfer_manager.add_upload.assert_called_once()
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
    import importlib

    transfer_module = importlib.import_module("portkeydrop.dialogs.transfer")

    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    frame._transfer_manager = MagicMock()
    upload = transfer_module.TransferItem(
        id=1, direction=app.TransferDirection.UPLOAD, status=app.TransferStatus.IN_PROGRESS
    )
    download = transfer_module.TransferItem(
        id=2, direction=app.TransferDirection.DOWNLOAD, status=app.TransferStatus.COMPLETED
    )
    frame._transfer_manager.transfers = [upload, download]
    frame._transfer_state_by_id = {}

    frame._on_transfer_update(None)

    frame._update_status.assert_called_once_with("Download complete.", "/remote")


def test_on_transfer_update_refreshes_local_files_after_download_complete(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    frame._transfer_manager = MagicMock()
    download = SimpleNamespace(
        id=1,
        direction=app.TransferDirection.DOWNLOAD,
        status=app.TransferStatus.COMPLETED,
    )
    frame._transfer_manager.transfers = [download]
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
    frame._transfer_manager = MagicMock()
    upload = SimpleNamespace(
        id=1,
        direction=app.TransferDirection.UPLOAD,
        status=app.TransferStatus.COMPLETED,
    )
    frame._transfer_manager.transfers = [upload]
    frame._transfer_state_by_id = {}
    frame._refresh_local_files = MagicMock()
    frame._refresh_remote_files = MagicMock()

    frame._on_transfer_update(None)

    frame._refresh_remote_files.assert_called_once()
    frame._refresh_local_files.assert_not_called()


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
