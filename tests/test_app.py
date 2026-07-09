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
    transfer = SimpleNamespace(concurrent_transfers=2)
    settings = SimpleNamespace(display=display, transfer=transfer)
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
    frame._connecting = False
    frame._focus_before_quick_connect = None
    frame._announce = MagicMock()
    frame._status = MagicMock()
    frame._update_status = MagicMock()
    frame._show_transfer_queue = MagicMock()
    frame._refresh_local_files = MagicMock()
    frame._refresh_remote_files = MagicMock()
    frame._play_sound_event = MagicMock(return_value=True)
    frame._get_selected_local_file = MagicMock()
    frame._get_selected_remote_file = MagicMock()
    frame._transfer_service = MagicMock()
    frame._transfer_state_by_id = {}
    frame._transfer_progress_by_id = {}
    frame.status_bar = MagicMock(SetStatusText=MagicMock())
    frame.activity_log = MagicMock()
    frame._activity_log_visible = True
    frame._last_failed_transfer = None
    frame._retry_last_failed_item = MagicMock()
    frame._toolbar_panel = MagicMock()
    frame._settings = SimpleNamespace(
        connection=SimpleNamespace(
            timeout=45,
            passive_mode=False,
            ftp_explicit_ssl=False,
            verify_host_keys="never",
        ),
        display=SimpleNamespace(progress_interval=25, show_hidden_files=True),
        transfer=SimpleNamespace(overwrite_mode="ask"),
    )
    return frame


def _remote_file(app, name, path, *, is_dir=False, size=0):
    return app.RemoteFile(name=name, path=path, is_dir=is_dir, size=size)


def _selected_list(*indices):
    selected = list(indices)
    first = selected[0] if selected else -1
    next_by_previous = {
        selected[index]: selected[index + 1] if index + 1 < len(selected) else -1
        for index in range(len(selected))
    }
    list_ctrl = MagicMock()
    list_ctrl.GetFirstSelected.return_value = first
    list_ctrl.GetNextSelected.side_effect = lambda previous: next_by_previous.get(previous, -1)
    return list_ctrl


def test_on_transfer_update_announces_progress_at_configured_interval(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = None
    job = SimpleNamespace(
        id="job-progress",
        direction=app.TransferDirection.DOWNLOAD,
        source="/remote/report.zip",
        destination="C:/Users/joshu/Downloads/report.zip",
        status=app.TransferStatus.IN_PROGRESS,
        progress=24,
        transferred_bytes=24,
        total_bytes=100,
    )
    frame._transfer_service.jobs = [job]

    frame._on_transfer_update(None)
    frame._announce.assert_not_called()

    job.progress = 25
    job.transferred_bytes = 25
    frame._on_transfer_update(None)

    frame._announce.assert_called_once_with("Download report.zip 25%, 25 B of 100 B")
    frame._update_status.assert_called_with("Download report.zip 25%, 25 B of 100 B", "")


def test_main_frame_init_sets_transfer_state(tmp_path, app_module):
    frame, _, transfer_service_cls = _build_frame(app_module, tmp_path)
    assert frame._transfer_state_by_id == {}
    transfer_service_cls.assert_called_once_with(notify_window=frame, max_workers=2)


def test_log_event_preserves_review_cursor_when_activity_log_has_focus(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame.FindFocus = MagicMock(return_value=frame.activity_log)
    frame.activity_log.GetInsertionPoint.return_value = 7

    frame.log_event("Speech output is unavailable")

    frame.activity_log.AppendText.assert_called_once()
    frame.activity_log.SetInsertionPoint.assert_called_once_with(7)
    frame._announce.assert_called_once_with("Speech output is unavailable")


def test_bind_events_hooks_transfer_update(app_module):
    app, _ = app_module
    frame = object.__new__(app.MainFrame)
    frame.Bind = MagicMock()
    frame.tb_connect_btn = MagicMock(Bind=MagicMock())
    frame.tb_protocol = MagicMock(Bind=MagicMock())
    frame._toolbar_panel = MagicMock(Bind=MagicMock())
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
    frame._toolbar_panel = MagicMock(Bind=MagicMock())
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
    assert (fake_wx.ACCEL_CTRL, fake_wx.WXK_RETURN, app.ID_CONNECT) in table_entries


def test_macos_menu_uses_command_q_for_exit_not_disconnect(app_module):
    app, fake_wx = app_module
    fake_wx.Platform = "__WXMAC__"

    appended_labels: list[str] = []

    class FakeMenu:
        def Append(self, *_args):
            if len(_args) >= 2:
                appended_labels.append(_args[1])
            return MagicMock(Enable=MagicMock())

        def AppendSeparator(self):
            pass

        def AppendCheckItem(self, *_args):
            if len(_args) >= 2:
                appended_labels.append(_args[1])
            return MagicMock()

        def AppendRadioItem(self, *_args):
            if len(_args) >= 2:
                appended_labels.append(_args[1])
            return MagicMock()

        def AppendSubMenu(self, *_args):
            pass

        def Check(self, *_args):
            pass

    class FakeMenuBar:
        def Append(self, *_args):
            pass

    fake_wx.Menu = FakeMenu
    fake_wx.MenuBar = FakeMenuBar
    frame = object.__new__(app.MainFrame)
    frame._settings = SimpleNamespace(display=SimpleNamespace(show_hidden_files=False))
    frame._get_update_channel = MagicMock(return_value="stable")
    frame.SetMenuBar = MagicMock()

    frame._build_menu()

    assert "&Disconnect" in appended_labels
    assert "&Disconnect\tCtrl+Q" not in appended_labels
    # wx maps Ctrl accelerators to Command on macOS, so this is Command+Q to users.
    assert "E&xit\tCtrl+Q" in appended_labels


def test_windows_menu_does_not_override_alt_f4_close(app_module):
    app, fake_wx = app_module
    fake_wx.Platform = "__WXMSW__"

    appended_labels: list[str] = []

    class FakeMenu:
        def Append(self, *_args):
            if len(_args) >= 2:
                appended_labels.append(_args[1])
            return MagicMock(Enable=MagicMock())

        def AppendSeparator(self):
            pass

        def AppendCheckItem(self, *_args):
            if len(_args) >= 2:
                appended_labels.append(_args[1])
            return MagicMock()

        def AppendRadioItem(self, *_args):
            if len(_args) >= 2:
                appended_labels.append(_args[1])
            return MagicMock()

        def AppendSubMenu(self, *_args):
            pass

        def Check(self, *_args):
            pass

    class FakeMenuBar:
        def Append(self, *_args):
            pass

    fake_wx.Menu = FakeMenu
    fake_wx.MenuBar = FakeMenuBar
    frame = object.__new__(app.MainFrame)
    frame._settings = SimpleNamespace(display=SimpleNamespace(show_hidden_files=False))
    frame._get_update_channel = MagicMock(return_value="stable")
    frame.SetMenuBar = MagicMock()

    frame._build_menu()

    assert "E&xit" in appended_labels
    assert "E&xit\tAlt+F4" not in appended_labels


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
    frame._announce.assert_called_once_with("Quick connect bar")


def test_on_upload_directory_updates_status(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    frame._client.stat.side_effect = FileNotFoundError
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
    frame._client.stat.side_effect = FileNotFoundError
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


def test_get_selected_files_from_list_returns_all_selected_visible_items(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    files = [
        _remote_file(app, "..", "/tmp"),
        _remote_file(app, "a.txt", "/tmp/a.txt", size=1),
        _remote_file(app, "docs", "/tmp/docs", is_dir=True),
        _remote_file(app, "b.txt", "/tmp/b.txt", size=2),
    ]

    result = frame._get_selected_files_from_list(_selected_list(1, 3), files, "")

    assert [item.name for item in result] == ["a.txt", "b.txt"]


def test_get_selected_files_from_list_empty_selection(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)

    result = frame._get_selected_files_from_list(
        _selected_list(), [_remote_file(app, "a.txt", "/tmp/a.txt")], ""
    )

    assert result == []


def test_on_upload_batch_mixed_files_and_folders_skips_parent(tmp_path, app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    frame._client.stat.side_effect = FileNotFoundError
    file_path = tmp_path / "report.txt"
    file_path.write_text("report")
    folder_path = tmp_path / "docs"
    folder_path.mkdir()
    frame._get_selected_local_files = MagicMock(
        return_value=[
            _remote_file(app, "..", str(tmp_path.parent), is_dir=True),
            _remote_file(app, "report.txt", str(file_path), size=6),
            _remote_file(app, "docs", str(folder_path), is_dir=True),
        ]
    )
    frame._transfer_service.submit_upload = MagicMock()

    frame._on_upload(None)

    assert frame._transfer_service.submit_upload.call_count == 2
    frame._transfer_service.submit_upload.assert_any_call(
        frame._client,
        str(file_path),
        "/remote/report.txt",
        6,
        overwrite_existing=False,
    )
    frame._transfer_service.submit_upload.assert_any_call(
        frame._client,
        str(folder_path),
        "/remote/docs",
        recursive=True,
        overwrite_existing=False,
    )
    frame._announce.assert_called_with("Queued 2 uploads")
    # The queue dialog must not steal focus by auto-opening.
    frame._show_transfer_queue.assert_not_called()


def test_on_download_batch_mixed_files_and_folders_skips_parent(tmp_path, app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    frame._local_cwd = str(tmp_path)
    frame._get_selected_remote_files = MagicMock(
        return_value=[
            _remote_file(app, "..", "/"),
            _remote_file(app, "report.txt", "/remote/report.txt", size=123),
            _remote_file(app, "docs", "/remote/docs", is_dir=True),
        ]
    )
    frame._transfer_service.submit_download = MagicMock()

    frame._on_download(None)

    assert frame._transfer_service.submit_download.call_count == 2
    frame._transfer_service.submit_download.assert_any_call(
        frame._client,
        "/remote/report.txt",
        str(tmp_path / "report.txt"),
        123,
        overwrite_existing=False,
    )
    frame._transfer_service.submit_download.assert_any_call(
        frame._client,
        "/remote/docs",
        str(tmp_path / "docs"),
        recursive=True,
        overwrite_existing=False,
    )
    frame._announce.assert_called_with("Queued 2 downloads")
    # The queue dialog must not steal focus by auto-opening.
    frame._show_transfer_queue.assert_not_called()


def test_on_upload_empty_selection_does_not_enqueue(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    frame._get_selected_local_files = MagicMock(return_value=[])
    frame._get_selected_local_file = MagicMock(return_value=None)
    frame._transfer_service.submit_upload = MagicMock()

    frame._on_upload(None)

    frame._transfer_service.submit_upload.assert_not_called()
    frame._announce.assert_called_once_with("Nothing selected to upload")
    frame._show_transfer_queue.assert_not_called()


def test_on_download_empty_selection_does_not_enqueue(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    frame._get_selected_remote_files = MagicMock(return_value=[])
    frame._get_selected_remote_file = MagicMock(return_value=None)
    frame._transfer_service.submit_download = MagicMock()

    frame._on_download(None)

    frame._transfer_service.submit_download.assert_not_called()
    frame._announce.assert_called_once_with("Nothing selected to download")
    frame._show_transfer_queue.assert_not_called()


def test_on_upload_batch_conflict_skip_continues_with_remaining_item(tmp_path, app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    frame._settings.transfer.overwrite_mode = "skip"
    first = tmp_path / "existing.txt"
    first.write_text("existing")
    second = tmp_path / "new.txt"
    second.write_text("new")

    def stat(path):
        if path == "/remote/existing.txt":
            return SimpleNamespace()
        raise FileNotFoundError(path)

    frame._client.stat.side_effect = stat
    frame._get_selected_local_files = MagicMock(
        return_value=[
            _remote_file(app, "existing.txt", str(first), size=8),
            _remote_file(app, "new.txt", str(second), size=3),
        ]
    )
    frame._transfer_service.submit_upload = MagicMock()

    frame._on_upload(None)

    frame._transfer_service.submit_upload.assert_called_once_with(
        frame._client,
        str(second),
        "/remote/new.txt",
        3,
        overwrite_existing=False,
    )
    frame._announce.assert_any_call("Skipped upload; existing.txt already exists")
    frame._announce.assert_called_with("Queued 1 upload")
    # The queue dialog must not steal focus by auto-opening.
    frame._show_transfer_queue.assert_not_called()


def test_on_download_batch_conflict_skip_continues_with_remaining_item(tmp_path, app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    frame._local_cwd = str(tmp_path)
    frame._settings.transfer.overwrite_mode = "skip"
    (tmp_path / "existing.txt").write_text("existing")
    frame._get_selected_remote_files = MagicMock(
        return_value=[
            _remote_file(app, "existing.txt", "/remote/existing.txt", size=8),
            _remote_file(app, "new.txt", "/remote/new.txt", size=3),
        ]
    )
    frame._transfer_service.submit_download = MagicMock()

    frame._on_download(None)

    frame._transfer_service.submit_download.assert_called_once_with(
        frame._client,
        "/remote/new.txt",
        str(tmp_path / "new.txt"),
        3,
        overwrite_existing=False,
    )
    frame._announce.assert_any_call("Skipped download; existing.txt already exists")
    frame._announce.assert_called_with("Queued 1 download")
    # The queue dialog must not steal focus by auto-opening.
    frame._show_transfer_queue.assert_not_called()


def test_on_download_skip_existing_file_does_not_enqueue(tmp_path, app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    frame._local_cwd = str(tmp_path)
    frame._settings.transfer.overwrite_mode = "skip"
    existing = tmp_path / "report.txt"
    existing.write_text("existing")
    selected = MagicMock()
    selected.name = "report.txt"
    selected.path = "/remote/report.txt"
    selected.is_dir = False
    selected.size = 123
    frame._get_selected_remote_file.return_value = selected
    frame._transfer_service.submit_download = MagicMock()

    frame._on_download(None)

    frame._transfer_service.submit_download.assert_not_called()
    frame._announce.assert_called_with("Skipped download; report.txt already exists")
    frame._show_transfer_queue.assert_not_called()


def test_on_download_rename_existing_file_before_enqueue(tmp_path, app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    frame._local_cwd = str(tmp_path)
    frame._settings.transfer.overwrite_mode = "rename"
    (tmp_path / "report.txt").write_text("existing")
    selected = MagicMock()
    selected.name = "report.txt"
    selected.path = "/remote/report.txt"
    selected.is_dir = False
    selected.size = 123
    frame._get_selected_remote_file.return_value = selected
    frame._transfer_service.submit_download = MagicMock()

    frame._on_download(None)

    expected = str(tmp_path / "report (1).txt")
    frame._transfer_service.submit_download.assert_called_once_with(
        frame._client,
        "/remote/report.txt",
        expected,
        123,
        overwrite_existing=False,
    )


def test_on_download_existing_folder_overwrite_enqueues_recursive(tmp_path, app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    frame._local_cwd = str(tmp_path)
    frame._settings.transfer.overwrite_mode = "overwrite"
    (tmp_path / "docs").mkdir()
    selected = MagicMock()
    selected.name = "docs"
    selected.path = "/remote/docs"
    selected.is_dir = True
    frame._get_selected_remote_file.return_value = selected
    frame._transfer_service.submit_download = MagicMock()

    frame._on_download(None)

    frame._transfer_service.submit_download.assert_called_once_with(
        frame._client,
        "/remote/docs",
        str(tmp_path / "docs"),
        recursive=True,
        overwrite_existing=True,
    )
    frame._announce.assert_called_with(f"Downloading folder docs to {tmp_path}")


def test_on_upload_skip_existing_remote_file_does_not_enqueue(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    frame._client.stat.return_value = SimpleNamespace()
    frame._settings.transfer.overwrite_mode = "skip"
    selected = MagicMock()
    selected.name = "report.txt"
    selected.path = "/tmp/report.txt"
    selected.is_dir = False
    frame._get_selected_local_file.return_value = selected
    frame._transfer_service.submit_upload = MagicMock()

    with patch.object(app.os.path, "getsize", return_value=123):
        frame._on_upload(None)

    frame._client.stat.assert_called_once_with("/remote/report.txt")
    frame._transfer_service.submit_upload.assert_not_called()
    frame._announce.assert_called_with("Skipped upload; report.txt already exists")


def test_on_upload_overwrite_existing_remote_file(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    frame._client.stat.return_value = SimpleNamespace()
    frame._settings.transfer.overwrite_mode = "overwrite"
    selected = MagicMock()
    selected.name = "report.txt"
    selected.path = "/tmp/report.txt"
    selected.is_dir = False
    frame._get_selected_local_file.return_value = selected
    frame._transfer_service.submit_upload = MagicMock()

    with patch.object(app.os.path, "getsize", return_value=123):
        frame._on_upload(None)

    frame._transfer_service.submit_upload.assert_called_once_with(
        frame._client,
        "/tmp/report.txt",
        "/remote/report.txt",
        123,
        overwrite_existing=True,
    )


def test_on_upload_rename_existing_remote_file_before_enqueue(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    frame._settings.transfer.overwrite_mode = "rename"

    def stat(path):
        if path == "/remote/report.txt":
            return SimpleNamespace()
        raise FileNotFoundError(path)

    frame._client.stat.side_effect = stat
    selected = MagicMock()
    selected.name = "report.txt"
    selected.path = "/tmp/report.txt"
    selected.is_dir = False
    frame._get_selected_local_file.return_value = selected
    frame._transfer_service.submit_upload = MagicMock()

    with patch.object(app.os.path, "getsize", return_value=123):
        frame._on_upload(None)

    frame._transfer_service.submit_upload.assert_called_once_with(
        frame._client,
        "/tmp/report.txt",
        "/remote/report (1).txt",
        123,
        overwrite_existing=False,
    )


def test_resolve_local_conflict_ask_accepts_existing_path(tmp_path, app_module):
    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)
    local_path = tmp_path / "report.txt"
    local_path.write_text("existing")
    fake_wx.MessageBox.return_value = fake_wx.YES

    result = frame._resolve_local_transfer_conflict(str(local_path), "report.txt", "download")

    assert result == str(local_path)
    fake_wx.MessageBox.assert_called_once()


def test_resolve_local_conflict_ask_rejects_existing_path(tmp_path, app_module):
    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)
    local_path = tmp_path / "report.txt"
    local_path.write_text("existing")
    fake_wx.MessageBox.return_value = fake_wx.OK

    result = frame._resolve_local_transfer_conflict(str(local_path), "report.txt", "download")

    assert result is None
    frame._announce.assert_called_with("Skipped download; report.txt already exists")


def test_unique_local_path_skips_existing_numbered_candidate(tmp_path, app_module):
    app, _ = app_module
    original = tmp_path / "report.txt"
    first = tmp_path / "report (1).txt"
    original.write_text("existing")
    first.write_text("existing")

    assert app.MainFrame._unique_local_path(str(original)) == str(tmp_path / "report (2).txt")


def test_remote_conflict_helpers_cover_empty_and_ask_paths(app_module):
    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)
    frame._client = None
    assert frame._remote_path_exists("/remote/missing.txt") is False

    frame._client = MagicMock()
    frame._client.stat.side_effect = [FileNotFoundError, SimpleNamespace(), FileNotFoundError]
    assert frame._unique_remote_path("/remote/report.txt") == "/remote/report.txt"

    def stat_existing_numbered(path):
        if path in {"/remote/report.txt", "/remote/report (1).txt"}:
            return SimpleNamespace()
        raise FileNotFoundError(path)

    frame._client.stat.side_effect = stat_existing_numbered
    assert frame._unique_remote_path("/remote/report.txt") == "/remote/report (2).txt"

    frame._client.stat.return_value = SimpleNamespace()
    frame._client.stat.side_effect = None
    fake_wx.MessageBox.return_value = fake_wx.YES
    assert (
        frame._resolve_remote_transfer_conflict("/remote/report.txt", "report.txt", "upload")
        == "/remote/report.txt"
    )

    fake_wx.MessageBox.return_value = fake_wx.OK
    assert (
        frame._resolve_remote_transfer_conflict("/remote/report.txt", "report.txt", "upload")
        is None
    )
    frame._announce.assert_called_with("Skipped upload; report.txt already exists")


def test_paste_upload_queues_without_opening_dialog(tmp_path, app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    frame._client.stat.side_effect = FileNotFoundError
    frame._transfer_service.submit_upload = MagicMock()
    file_path = tmp_path / "clip.txt"
    file_path.write_text("clip")
    frame._get_clipboard_files = MagicMock(return_value=[str(file_path)])

    frame._paste_upload()

    frame._transfer_service.submit_upload.assert_called_once()
    # The queue dialog must not steal focus by auto-opening.
    frame._show_transfer_queue.assert_not_called()


def test_paste_upload_skip_existing_remote_file(tmp_path, app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    frame._client.stat.return_value = SimpleNamespace()
    frame._settings.transfer.overwrite_mode = "skip"
    frame._transfer_service.submit_upload = MagicMock()
    file_path = tmp_path / "clip.txt"
    file_path.write_text("clip")
    frame._get_clipboard_files = MagicMock(return_value=[str(file_path)])

    frame._paste_upload()

    frame._transfer_service.submit_upload.assert_not_called()
    frame._show_transfer_queue.assert_not_called()
    frame._announce.assert_called_with("Skipped upload; clip.txt already exists")


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
    frame._play_sound_event.assert_called_with("delete_complete")


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
    frame._play_sound_event.assert_called_with("delete_failed")
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
    frame._play_sound_event.assert_called_with("rename_complete")


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
    frame._play_sound_event.assert_called_with("rename_failed")
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
    frame._play_sound_event.assert_called_with("folder_created")


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
    frame._play_sound_event.assert_called_with("folder_create_failed")
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


def test_apply_connection_defaults_sets_timeout_passive_and_host_key_policy(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    info = app.ConnectionInfo(protocol=app.Protocol.SFTP, host="example.com")

    frame._apply_connection_defaults(info)

    assert info.timeout == 45
    assert info.passive_mode is False
    assert info.host_key_policy == app.HostKeyPolicy.STRICT


def test_toolbar_protocol_change_uses_webdav_default_port(app_module):
    _app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame.tb_protocol = MagicMock(GetStringSelection=MagicMock(return_value="webdav"))
    frame.tb_port = MagicMock(GetValue=MagicMock(return_value="22"))
    frame.tb_ftp_ssl = MagicMock(GetValue=MagicMock(return_value=True))

    frame._on_toolbar_protocol_change(None)

    frame.tb_port.SetValue.assert_called_once_with("443")
    frame.tb_ftp_ssl.Enable.assert_called_once_with(False)
    frame.tb_ftp_ssl.SetValue.assert_called_once_with(False)
    frame._announce.assert_any_call("Port set to 443")
    frame._announce.assert_any_call("Use SSL turned off")


def test_toolbar_protocol_change_keeps_custom_port(app_module):
    _app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame.tb_protocol = MagicMock(GetStringSelection=MagicMock(return_value="ftp"))
    frame.tb_port = MagicMock(GetValue=MagicMock(return_value="2222"))
    frame.tb_ftp_ssl = MagicMock(GetValue=MagicMock(return_value=False))

    frame._on_toolbar_protocol_change(None)

    frame.tb_port.SetValue.assert_not_called()
    frame.tb_ftp_ssl.SetValue.assert_not_called()


def test_effective_site_port_uses_webdav_default(app_module):
    _app, _ = app_module
    frame = _hydrate_frame(app_module)

    assert frame._effective_site_port("webdav", 0) == 443


def test_do_connect_allows_webdav_without_password(app_module):
    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)
    frame._on_disconnect = MagicMock()
    info = app.ConnectionInfo(
        protocol=app.Protocol.WEBDAV,
        host="dav.example.com",
        username="guest",
        password="",
    )
    client = MagicMock(cwd="/")
    frame._on_connect_success = MagicMock()

    with (
        patch.object(app, "create_client", return_value=client) as create_client,
        patch.object(app.threading, "Thread", _ImmediateThread),
    ):
        frame._do_connect(info)

    fake_wx.MessageBox.assert_not_called()
    create_client.assert_called_once_with(info)
    client.connect.assert_called_once_with()
    frame._on_connect_success.assert_called_once_with(client)


def test_do_connect_still_requires_ftp_password(app_module):
    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)
    frame._on_disconnect = MagicMock()
    info = app.ConnectionInfo(
        protocol=app.Protocol.FTP,
        host="ftp.example.com",
        username="guest",
        password="",
    )

    with patch.object(app, "create_client") as create_client:
        frame._do_connect(info)

    fake_wx.MessageBox.assert_called_once()
    assert fake_wx.MessageBox.call_args.args[0] == "Please enter a password."
    create_client.assert_not_called()


def _hydrate_toolbar_fields(frame, *, proto="sftp", host="", port="22", username="", password=""):
    frame.tb_protocol = MagicMock(GetStringSelection=MagicMock(return_value=proto))
    frame.tb_host = MagicMock(GetValue=MagicMock(return_value=host))
    frame.tb_port = MagicMock(GetValue=MagicMock(return_value=port))
    frame.tb_username = MagicMock(GetValue=MagicMock(return_value=username))
    frame.tb_password = MagicMock(GetValue=MagicMock(return_value=password))
    frame.tb_ftp_ssl = MagicMock(GetValue=MagicMock(return_value=False))


def test_connect_toolbar_empty_host_focuses_host_field(app_module):
    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)
    frame._do_connect = MagicMock()
    _hydrate_toolbar_fields(frame, host="   ")

    frame._on_connect_toolbar(None)

    frame.tb_host.SetFocus.assert_called_once()
    frame._announce.assert_called_once_with("Enter a host to connect.")
    frame._do_connect.assert_not_called()
    fake_wx.MessageBox.assert_not_called()


def test_connect_toolbar_empty_host_reveals_hidden_quick_connect_bar(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._do_connect = MagicMock()
    frame._toolbar_panel.IsShown.return_value = False
    frame.GetSizer = MagicMock()
    _hydrate_toolbar_fields(frame)

    frame._on_connect_toolbar(None)

    frame._toolbar_panel.Show.assert_called_once()
    frame.GetSizer.return_value.Layout.assert_called_once()
    frame.tb_host.SetFocus.assert_called_once()


def test_connect_toolbar_empty_username_focuses_username_field(app_module):
    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)
    frame._do_connect = MagicMock()
    _hydrate_toolbar_fields(frame, host="example.com")

    frame._on_connect_toolbar(None)

    frame.tb_username.SetFocus.assert_called_once()
    frame._announce.assert_called_once_with("Enter a username to connect.")
    frame._do_connect.assert_not_called()
    fake_wx.MessageBox.assert_not_called()


def test_connect_toolbar_ftp_without_password_focuses_password_field(app_module):
    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)
    frame._do_connect = MagicMock()
    _hydrate_toolbar_fields(frame, proto="ftp", host="example.com", port="21", username="alice")

    frame._on_connect_toolbar(None)

    frame.tb_password.SetFocus.assert_called_once()
    frame._announce.assert_called_once_with("Enter a password to connect.")
    frame._do_connect.assert_not_called()
    fake_wx.MessageBox.assert_not_called()


def test_connect_toolbar_non_numeric_port_focuses_port_field(app_module):
    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)
    frame._do_connect = MagicMock()
    _hydrate_toolbar_fields(frame, host="example.com", username="alice", port="abc")

    frame._on_connect_toolbar(None)

    frame.tb_port.SetFocus.assert_called_once()
    frame._announce.assert_called_once_with("Enter a port number between 1 and 65535.")
    frame._do_connect.assert_not_called()
    fake_wx.MessageBox.assert_not_called()


def test_connect_toolbar_out_of_range_port_focuses_port_field(app_module):
    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)
    frame._do_connect = MagicMock()
    _hydrate_toolbar_fields(frame, host="example.com", username="alice", port="70000")

    frame._on_connect_toolbar(None)

    frame.tb_port.SetFocus.assert_called_once()
    frame._announce.assert_called_once_with("Enter a port number between 1 and 65535.")
    frame._do_connect.assert_not_called()


def test_connect_toolbar_empty_port_uses_protocol_default(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._do_connect = MagicMock()
    _hydrate_toolbar_fields(frame, host="example.com", username="alice", port="")

    frame._on_connect_toolbar(None)

    frame._do_connect.assert_called_once()
    assert frame._do_connect.call_args.args[0].port == 0


def test_connect_toolbar_sftp_without_password_still_connects(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._do_connect = MagicMock()
    _hydrate_toolbar_fields(frame, host="example.com", username="alice")

    frame._on_connect_toolbar(None)

    frame._do_connect.assert_called_once()
    info = frame._do_connect.call_args.args[0]
    assert info.host == "example.com"
    assert info.username == "alice"
    frame._announce.assert_not_called()


def test_quick_connect_reveal_remembers_previous_focus(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame.tb_host = MagicMock(SetFocus=MagicMock())
    frame._toolbar_panel.IsShown.return_value = False
    frame.GetSizer = MagicMock()
    previous = MagicMock()
    frame.FindFocus = MagicMock(return_value=previous)

    frame._on_quick_connect(None)

    assert frame._focus_before_quick_connect is previous


def test_escape_dismisses_quick_connect_bar_while_connected(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True)
    frame.GetSizer = MagicMock()
    frame.local_file_list = MagicMock()
    previous = MagicMock(IsShown=MagicMock(return_value=True))
    frame._focus_before_quick_connect = previous
    event = MagicMock(GetKeyCode=MagicMock(return_value=app.wx.WXK_ESCAPE))

    frame._on_quick_connect_bar_key(event)

    frame._toolbar_panel.Hide.assert_called_once()
    frame.GetSizer.return_value.Layout.assert_called_once()
    previous.SetFocus.assert_called_once()
    frame._announce.assert_called_once_with("Quick connect cancelled")
    event.Skip.assert_not_called()
    assert frame._focus_before_quick_connect is None


def test_escape_keeps_quick_connect_bar_while_disconnected(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = None
    event = MagicMock(GetKeyCode=MagicMock(return_value=app.wx.WXK_ESCAPE))

    frame._on_quick_connect_bar_key(event)

    frame._toolbar_panel.Hide.assert_not_called()
    event.Skip.assert_called_once()


def test_dismiss_quick_connect_falls_back_to_local_file_list(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame.GetSizer = MagicMock()
    frame.local_file_list = MagicMock()
    frame._focus_before_quick_connect = None

    frame._dismiss_quick_connect_bar()

    frame.local_file_list.SetFocus.assert_called_once()
    frame._announce.assert_called_once_with("Quick connect cancelled")


def test_do_connect_ignores_repeat_submit_while_connecting(app_module):
    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)
    frame._on_disconnect = MagicMock()
    frame._connecting = True
    info = app.ConnectionInfo(
        protocol=app.Protocol.SFTP, host="example.com", username="alice", password="pw"
    )

    with patch.object(app, "create_client") as create_client:
        frame._do_connect(info)

    create_client.assert_not_called()
    frame._on_disconnect.assert_not_called()
    frame._announce.assert_called_once_with("Still connecting, please wait.")
    fake_wx.MessageBox.assert_not_called()


def test_do_connect_announces_connection_start(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._on_disconnect = MagicMock()
    frame._on_connect_success = MagicMock()
    info = app.ConnectionInfo(
        protocol=app.Protocol.SFTP, host="example.com", username="alice", password="pw"
    )

    with (
        patch.object(app, "create_client", return_value=MagicMock(cwd="/")),
        patch.object(app.threading, "Thread", _ImmediateThread),
    ):
        frame._do_connect(info)

    frame._announce.assert_called_once_with("Connecting to example.com")


def test_connect_failure_resets_connecting_flag(app_module):
    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)
    frame._connecting = True
    frame._update_title = MagicMock()

    frame._on_connect_failure(RuntimeError("boom"))

    assert frame._connecting is False
    fake_wx.MessageBox.assert_called_once()


def test_connect_success_resets_connecting_flag(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._connecting = True
    frame._update_title = MagicMock()
    frame.GetSizer = MagicMock()
    frame.local_file_list = MagicMock()
    client = MagicMock(
        cwd="/home",
        _info=SimpleNamespace(protocol=SimpleNamespace(value="sftp"), host="example.com"),
    )

    frame._on_connect_success(client)

    assert frame._connecting is False


def test_quick_connect_focuses_host_field(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame.tb_host = MagicMock(SetFocus=MagicMock())

    frame._on_quick_connect(None)

    frame.tb_host.SetFocus.assert_called_once()
    frame._announce.assert_called_once_with("Quick connect bar")


def test_quick_connect_reveals_hidden_bar_while_connected(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame.tb_host = MagicMock(SetFocus=MagicMock())
    frame._toolbar_panel.IsShown.return_value = False
    frame.GetSizer = MagicMock()

    frame._on_quick_connect(None)

    frame._toolbar_panel.Show.assert_called_once()
    frame.GetSizer.return_value.Layout.assert_called_once()
    frame.tb_host.SetFocus.assert_called_once()


def test_site_manager_connect_applies_connection_defaults(app_module):
    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)
    frame._do_connect = MagicMock()
    site = MagicMock()
    info = app.ConnectionInfo(protocol=app.Protocol.FTPS, host="example.com", username="alice")
    site.to_connection_info.return_value = info
    dialog = MagicMock(
        ShowModal=MagicMock(return_value=fake_wx.ID_OK),
        connect_requested=True,
        selected_site=site,
        Destroy=MagicMock(),
    )
    frame._site_manager = MagicMock()

    with patch.object(app, "SiteManagerDialog", return_value=dialog):
        frame._on_site_manager(None)

    frame._do_connect.assert_called_once_with(info)
    assert info.timeout == 45
    assert info.passive_mode is False
    assert info.host_key_policy == app.HostKeyPolicy.STRICT


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


def test_on_transfer_update_pending_job_shows_queued_status(app_module):
    app, _ = app_module
    frame = _hydrate_frame(app_module)
    frame._client = MagicMock(connected=True, cwd="/remote")
    frame.activity_log = MagicMock()
    pending_job = SimpleNamespace(
        id="ccc",
        direction=app.TransferDirection.DOWNLOAD,
        status=app.TransferStatus.PENDING,
        source="/remote/queued.txt",
        destination="/local/queued.txt",
        error=None,
        progress=0,
    )
    frame._transfer_service.jobs = [pending_job]
    frame._transfer_state_by_id = {}

    frame._on_transfer_update(None)

    frame._update_status.assert_called_once_with("Download queued.", "/remote")


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
    frame.FromDIP = lambda size: size
    with patch.object(fake_wx, "StaticText", side_effect=_Label):
        app.MainFrame._build_toolbar(frame)

    assert [label.label for label in created_labels[:5]] == [
        "&Protocol:",
        "&Host:",
        "P&ort:",
        "&Username:",
        "Pass&word:",
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
    frame.remote_file_list = MagicMock(GetItemCount=MagicMock(return_value=1))
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
    # Entering a new directory speaks the item count when the setting is on.
    frame._announce.assert_called_once_with("1 item")


def test_on_remote_files_loaded_announces_empty_folder(app_module):
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
    frame._get_visible_files = MagicMock(return_value=[])
    frame._remote_files = []

    app.MainFrame._on_remote_files_loaded(frame, [RemoteFile(name="..", path="/")], "/home/user")

    frame._announce.assert_called_once_with("Empty folder")


def test_on_remote_files_loaded_same_dir_preserves_focused_row(app_module):
    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)

    from portkeydrop.protocols import RemoteFile

    frame._client = MagicMock(cwd="/home/user")
    frame._remote_filter_text = ""
    frame._settings = MagicMock()
    frame._settings.display.announce_file_count = True
    frame._remote_populated_cwd = "/home/user"
    rows = ["..", "alpha", "beta"]
    frame.remote_file_list = MagicMock(
        GetItemCount=MagicMock(return_value=3),
        GetFocusedItem=MagicMock(return_value=2),
        GetItemText=MagicMock(side_effect=lambda i: rows[i]),
    )
    frame.remote_path_bar = MagicMock()
    frame._update_title = MagicMock()
    frame._apply_sort = MagicMock()
    frame._populate_file_list = MagicMock()
    frame._get_visible_files = MagicMock(return_value=[MagicMock()] * 3)
    frame._remote_files = []

    app.MainFrame._on_remote_files_loaded(
        frame, [RemoteFile(name="beta", path="/home/user/beta")], "/home/user"
    )

    # Background refresh of the same directory keeps the user's row (beta, index 2).
    frame.remote_file_list.Select.assert_called_once_with(2)
    frame.remote_file_list.Focus.assert_called_once_with(2)
    # Same-directory refreshes do not re-announce the item count.
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
        transfer=SimpleNamespace(concurrent_transfers=2),
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
        transfer=SimpleNamespace(concurrent_transfers=4),
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
        transfer=SimpleNamespace(concurrent_transfers=2),
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


def test_on_check_updates_allows_nuitka_compiled_builds(app_module, monkeypatch):
    app, fake_wx = app_module
    frame = object.__new__(app.MainFrame)
    frame._settings = SimpleNamespace(app=SimpleNamespace(update_channel="stable"))
    frame.version = "1.0.0"
    frame.build_tag = "nightly-20260305"
    monkeypatch.setattr(app.sys, "frozen", False, raising=False)
    monkeypatch.setattr(app, "__compiled__", object(), raising=False)
    monkeypatch.setattr(app.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(fake_wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw))

    called: dict[str, object] = {}

    class _FakeService:
        def __init__(self, _name):
            pass

        def check_for_updates(self, **kwargs):
            called["current_nightly_date"] = kwargs["current_nightly_date"]
            called["channel"] = kwargs["channel"]
            return None

    monkeypatch.setattr(app, "UpdateService", _FakeService)

    frame._on_check_updates(None)

    assert called == {"current_nightly_date": "20260305", "channel": "stable"}
    assert fake_wx.MessageBox.call_args.args[1] == "No Updates Available"


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


def test_on_close_stops_auto_update_timer_and_skips_event(app_module, monkeypatch):
    app, _ = app_module
    frame = object.__new__(app.MainFrame)
    frame._auto_update_check_timer = MagicMock(Stop=MagicMock())
    frame._transfer_service = MagicMock()
    frame._play_exit_sound_once = MagicMock()
    event = MagicMock(Skip=MagicMock())
    monkeypatch.setattr(app, "save_queue", lambda *a, **kw: None)

    frame._on_close(event)

    frame._play_exit_sound_once.assert_called_once()
    frame._auto_update_check_timer.Stop.assert_called_once()
    event.Skip.assert_called_once()


def test_play_exit_sound_once_deduplicates_menu_and_close_paths(app_module):
    app, _ = app_module
    frame = object.__new__(app.MainFrame)
    frame._exit_sound_played = False
    frame._play_sound_event = MagicMock(return_value=True)

    assert frame._play_exit_sound_once() is True
    assert frame._play_exit_sound_once() is False

    frame._play_sound_event.assert_called_once_with("exit")


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
    monkeypatch.setattr(fake_wx, "GetTopLevelWindows", lambda: [], raising=False)
    monkeypatch.setattr(fake_wx, "SafeYield", lambda: None, raising=False)
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


def test_restore_transfer_queue_announces_when_jobs_restored(app_module, monkeypatch):
    """_restore_transfer_queue should announce when jobs are loaded from queue.json."""
    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)

    fake_job = MagicMock()
    monkeypatch.setattr(app, "load_queue", lambda _: [fake_job])
    monkeypatch.setattr(app, "get_config_dir", lambda: MagicMock())
    monkeypatch.setattr(fake_wx, "CallAfter", lambda fn, *a, **kw: fn(*a, **kw))

    frame._restore_transfer_queue()

    frame._transfer_service.restore_jobs.assert_called_once_with([fake_job])
    frame._announce.assert_called_once()
    msg = frame._announce.call_args.args[0]
    assert "restored" in msg.lower()


def test_restore_transfer_queue_silent_when_empty(app_module, monkeypatch):
    """_restore_transfer_queue should not announce if queue.json is empty."""
    app, fake_wx = app_module
    frame = _hydrate_frame(app_module)

    monkeypatch.setattr(app, "load_queue", lambda _: [])
    monkeypatch.setattr(app, "get_config_dir", lambda: MagicMock())

    frame._restore_transfer_queue()

    frame._transfer_service.restore_jobs.assert_not_called()
    frame._announce.assert_not_called()
