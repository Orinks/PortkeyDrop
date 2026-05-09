"""Tests for notification area / system tray support."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests._wx_stub import load_module_with_fake_wx


@pytest.fixture
def app_module(monkeypatch):
    return load_module_with_fake_wx("portkeydrop.app", monkeypatch)


def test_system_tray_icon_creates_portkeydrop_menu(monkeypatch):
    module, fake_wx = load_module_with_fake_wx("portkeydrop.system_tray", monkeypatch)

    appended: list[str] = []

    class FakeMenu:
        def Append(self, item_id, label, *_args):
            appended.append(label)
            return SimpleNamespace(id=item_id, label=label)

        def AppendSeparator(self):
            appended.append("separator")

        def Destroy(self):
            pass

    fake_wx.Menu = FakeMenu
    tray = module.SystemTrayIcon.__new__(module.SystemTrayIcon)
    tray.Bind = MagicMock()
    tray.frame = MagicMock()

    tray._create_popup_menu()

    assert "&Show Portkey Drop" in appended
    assert "Transfer &Queue..." in appended
    assert "Check for &Updates..." in appended
    assert "E&xit" in appended


def test_system_tray_icon_initializes_icon_and_taskbar_bindings(monkeypatch):
    module, fake_wx = load_module_with_fake_wx("portkeydrop.system_tray", monkeypatch)
    frame = MagicMock()
    icon = MagicMock()
    icon.IsOk.return_value = True
    monkeypatch.setattr(module.SystemTrayIcon, "_load_icon", MagicMock(return_value=icon))

    tray = module.SystemTrayIcon(frame)

    assert tray.frame is frame
    assert tray._cached_icon is icon
    assert tray._icon_set is True
    assert (fake_wx.adv.EVT_TASKBAR_LEFT_DOWN, tray._on_left_click) in [
        args for args, _kwargs in tray._bindings
    ]
    assert (fake_wx.adv.EVT_TASKBAR_LEFT_DCLICK, tray._on_left_click) in [
        args for args, _kwargs in tray._bindings
    ]
    assert (fake_wx.adv.EVT_TASKBAR_RIGHT_DOWN, tray._on_right_click) in [
        args for args, _kwargs in tray._bindings
    ]


def test_system_tray_setup_icon_warns_when_icon_cannot_load(monkeypatch):
    module, _ = load_module_with_fake_wx("portkeydrop.system_tray", monkeypatch)
    tray = module.SystemTrayIcon.__new__(module.SystemTrayIcon)
    tray._icon_set = False
    tray._cached_icon = None
    tray.SetIcon = MagicMock()
    tray._load_icon = MagicMock(return_value=None)

    tray._setup_icon()

    tray.SetIcon.assert_not_called()
    assert tray._cached_icon is None
    assert tray._icon_set is False


def test_system_tray_load_icon_uses_first_valid_icon_file(monkeypatch, tmp_path):
    module, fake_wx = load_module_with_fake_wx("portkeydrop.system_tray", monkeypatch)
    ico_path = tmp_path / "app.ico"
    ico_path.write_bytes(b"icon")
    png_path = tmp_path / "app_32.png"
    icon = MagicMock()
    icon.IsOk.return_value = True
    fake_wx.Icon = MagicMock(return_value=icon)
    tray = module.SystemTrayIcon.__new__(module.SystemTrayIcon)
    tray._get_icon_paths = MagicMock(return_value=[ico_path, png_path])
    tray._create_default_icon = MagicMock()

    loaded = tray._load_icon()

    assert loaded is icon
    fake_wx.Icon.assert_called_once_with(str(ico_path), fake_wx.BITMAP_TYPE_ICO)
    tray._create_default_icon.assert_not_called()


def test_system_tray_load_icon_falls_back_after_bad_or_missing_files(monkeypatch, tmp_path):
    module, fake_wx = load_module_with_fake_wx("portkeydrop.system_tray", monkeypatch)
    bad_path = tmp_path / "app.png"
    bad_path.write_bytes(b"bad icon")
    missing_path = tmp_path / "missing.ico"
    fallback = MagicMock()
    invalid_icon = MagicMock()
    invalid_icon.IsOk.return_value = False
    fake_wx.Icon = MagicMock(return_value=invalid_icon)
    tray = module.SystemTrayIcon.__new__(module.SystemTrayIcon)
    tray._get_icon_paths = MagicMock(return_value=[missing_path, bad_path])
    tray._create_default_icon = MagicMock(return_value=fallback)

    loaded = tray._load_icon()

    assert loaded is fallback
    fake_wx.Icon.assert_called_once_with(str(bad_path), fake_wx.BITMAP_TYPE_PNG)
    tray._create_default_icon.assert_called_once()


def test_system_tray_load_icon_ignores_icon_constructor_errors(monkeypatch, tmp_path):
    module, fake_wx = load_module_with_fake_wx("portkeydrop.system_tray", monkeypatch)
    icon_path = tmp_path / "app.ico"
    icon_path.write_bytes(b"bad icon")
    fallback = MagicMock()
    fake_wx.Icon = MagicMock(side_effect=RuntimeError("bad icon"))
    tray = module.SystemTrayIcon.__new__(module.SystemTrayIcon)
    tray._get_icon_paths = MagicMock(return_value=[icon_path])
    tray._create_default_icon = MagicMock(return_value=fallback)

    assert tray._load_icon() is fallback


def test_system_tray_get_icon_paths_handles_source_and_frozen_layouts(monkeypatch, tmp_path):
    module, _ = load_module_with_fake_wx("portkeydrop.system_tray", monkeypatch)
    tray = module.SystemTrayIcon.__new__(module.SystemTrayIcon)

    source_paths = tray._get_icon_paths()

    assert source_paths == [
        module.Path(module.__file__).parent / "resources" / "app.ico",
        module.Path(module.__file__).parent / "resources" / "app_32.png",
        module.Path(module.__file__).parent / "resources" / "app_16.png",
    ]

    executable = tmp_path / "PortkeyDrop.exe"
    monkeypatch.setattr(module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(module.sys, "executable", str(executable))

    assert tray._get_icon_paths() == [
        tmp_path / "app.ico",
        tmp_path / "resources" / "app.ico",
        tmp_path / "resources" / "app_32.png",
        tmp_path / "resources" / "app_16.png",
    ]


def test_system_tray_creates_default_icon(monkeypatch):
    module, fake_wx = load_module_with_fake_wx("portkeydrop.system_tray", monkeypatch)
    bitmap = object()
    dc = MagicMock()
    icon = MagicMock()
    fake_wx.Bitmap = MagicMock(return_value=bitmap)
    fake_wx.MemoryDC = MagicMock(return_value=dc)
    fake_wx.Brush = MagicMock(return_value=object())
    fake_wx.Colour = MagicMock(return_value=object())
    fake_wx.Pen = MagicMock(return_value=object())
    fake_wx.WHITE = object()
    fake_wx.Icon = MagicMock(return_value=icon)
    tray = module.SystemTrayIcon.__new__(module.SystemTrayIcon)

    assert tray._create_default_icon() is icon

    fake_wx.Bitmap.assert_called_once_with(16, 16)
    icon.CopyFromBitmap.assert_called_once()


def test_system_tray_pointer_and_menu_events_open_expected_actions(monkeypatch):
    module, _ = load_module_with_fake_wx("portkeydrop.system_tray", monkeypatch)
    frame = MagicMock()
    event = object()
    tray = module.SystemTrayIcon.__new__(module.SystemTrayIcon)
    tray.frame = frame
    tray.show_main_window = MagicMock()
    tray.PopupMenu = MagicMock()
    menu = MagicMock()
    tray._create_popup_menu = MagicMock(return_value=menu)

    tray._on_left_click(event)
    tray._on_right_click(event)
    tray._on_show_menu(event)
    tray._on_transfer_queue_menu(event)
    tray._on_check_updates_menu(event)

    assert tray.show_main_window.call_count == 4
    tray.PopupMenu.assert_called_once_with(menu)
    menu.Destroy.assert_called_once()
    frame._on_transfer_queue.assert_called_once_with(event)
    frame._on_check_updates.assert_called_once_with(event)


def test_system_tray_show_main_window_restores_frame(monkeypatch):
    module, _ = load_module_with_fake_wx("portkeydrop.system_tray", monkeypatch)
    frame = MagicMock()
    tray = module.SystemTrayIcon.__new__(module.SystemTrayIcon)
    tray.frame = frame

    tray.show_main_window()

    frame.Show.assert_called_once_with(True)
    frame.Iconize.assert_called_once_with(False)
    frame.Raise.assert_called_once()
    frame.SetFocus.assert_called_once()


def test_system_tray_show_main_window_requests_attention_on_macos(monkeypatch):
    module, _ = load_module_with_fake_wx("portkeydrop.system_tray", monkeypatch)
    frame = MagicMock()
    tray = module.SystemTrayIcon.__new__(module.SystemTrayIcon)
    tray.frame = frame
    monkeypatch.setattr(module.sys, "platform", "darwin")

    tray.show_main_window()

    frame.Show.assert_called_once_with(True)
    frame.Iconize.assert_called_once_with(False)
    frame.RequestUserAttention.assert_called_once()
    frame.Raise.assert_not_called()
    frame.SetFocus.assert_not_called()


def test_system_tray_update_tooltip_reuses_cached_icon(monkeypatch):
    module, _ = load_module_with_fake_wx("portkeydrop.system_tray", monkeypatch)
    icon = MagicMock()
    icon.IsOk.return_value = True
    tray = module.SystemTrayIcon.__new__(module.SystemTrayIcon)
    tray._icon_set = True
    tray._cached_icon = icon
    tray.SetIcon = MagicMock()

    tray.update_tooltip("Transfers active")

    tray.SetIcon.assert_called_once_with(icon, "Transfers active")


def test_system_tray_update_tooltip_ignores_missing_or_invalid_icon(monkeypatch):
    module, _ = load_module_with_fake_wx("portkeydrop.system_tray", monkeypatch)
    invalid_icon = MagicMock()
    invalid_icon.IsOk.return_value = False
    tray = module.SystemTrayIcon.__new__(module.SystemTrayIcon)
    tray.SetIcon = MagicMock()

    tray._icon_set = False
    tray._cached_icon = invalid_icon
    tray.update_tooltip("Transfers active")
    tray.SetIcon.assert_not_called()

    tray._icon_set = True
    tray._cached_icon = None
    tray.update_tooltip("Transfers active")
    tray.SetIcon.assert_not_called()

    tray._cached_icon = invalid_icon
    tray.update_tooltip("Transfers active")
    tray.SetIcon.assert_not_called()


def test_system_tray_quit_delegates_to_frame(monkeypatch):
    module, _ = load_module_with_fake_wx("portkeydrop.system_tray", monkeypatch)
    frame = MagicMock()
    tray = module.SystemTrayIcon.__new__(module.SystemTrayIcon)
    tray.frame = frame

    tray._on_exit_menu(None)

    frame.request_exit.assert_called_once()


def test_main_frame_creates_tray_icon_when_setting_enabled(app_module, monkeypatch):
    app, _ = app_module
    frame = object.__new__(app.MainFrame)
    frame._settings = SimpleNamespace(app=SimpleNamespace(show_notification_area_icon=True))
    fake_tray = MagicMock()
    monkeypatch.setattr(app, "SystemTrayIcon", MagicMock(return_value=fake_tray))

    frame._tray_icon = None
    frame._sync_tray_icon()

    app.SystemTrayIcon.assert_called_once_with(frame)
    assert frame._tray_icon is fake_tray


def test_main_frame_removes_tray_icon_when_setting_disabled(app_module):
    app, _ = app_module
    frame = object.__new__(app.MainFrame)
    tray = MagicMock()
    frame._tray_icon = tray
    frame._settings = SimpleNamespace(app=SimpleNamespace(show_notification_area_icon=False))

    frame._sync_tray_icon()

    tray.RemoveIcon.assert_called_once()
    tray.Destroy.assert_called_once()
    assert frame._tray_icon is None


def test_close_minimizes_to_tray_when_enabled(app_module):
    app, _ = app_module
    frame = object.__new__(app.MainFrame)
    frame._settings = SimpleNamespace(
        app=SimpleNamespace(
            show_notification_area_icon=True,
            minimize_to_notification_area_on_close=True,
        )
    )
    frame._tray_icon = MagicMock()
    frame._transfer_service = MagicMock()
    frame._auto_update_check_timer = MagicMock()
    frame.Hide = MagicMock()
    frame._announce = MagicMock()
    event = MagicMock()

    frame._on_close(event)

    frame.Hide.assert_called_once()
    event.Veto.assert_called_once()
    frame._auto_update_check_timer.Stop.assert_not_called()
    frame._announce.assert_called_once_with(
        "Portkey Drop is still running in the notification area."
    )


def test_request_exit_closes_without_minimizing(app_module):
    app, _ = app_module
    frame = object.__new__(app.MainFrame)
    frame._force_exit = False
    frame.Close = MagicMock()

    frame.request_exit()

    assert frame._force_exit is True
    frame.Close.assert_called_once_with(True)
