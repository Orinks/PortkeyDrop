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
