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
    frame._update_status = MagicMock()
    frame._show_transfer_queue = MagicMock()
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
    dialog = MagicMock(ShowModal=MagicMock(return_value=fake_wx.ID_OK), GetValue=MagicMock(return_value="new.txt"), Destroy=MagicMock())
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
    dialog = MagicMock(ShowModal=MagicMock(return_value=fake_wx.ID_OK), GetValue=MagicMock(return_value="new.txt"), Destroy=MagicMock())
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
    dialog = MagicMock(ShowModal=MagicMock(return_value=fake_wx.ID_OK), GetValue=MagicMock(return_value="new-dir"), Destroy=MagicMock())

    with patch.object(fake_wx, "TextEntryDialog", return_value=dialog):
        frame._mkdir_remote()

    frame._update_status.assert_any_call("Creating directory new-dir...", "/remote")
    frame._update_status.assert_any_call("Directory created.", "/remote")


def test_mkdir_remote_reports_error(app_module):
    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    frame._client.mkdir.side_effect = RuntimeError("boom")
    dialog = MagicMock(ShowModal=MagicMock(return_value=fake_wx.ID_OK), GetValue=MagicMock(return_value="new-dir"), Destroy=MagicMock())

    with patch.object(fake_wx, "TextEntryDialog", return_value=dialog):
        frame._mkdir_remote()

    frame._update_status.assert_any_call("Create directory failed.", "/remote")
    fake_wx.MessageBox.assert_called()


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
