"""Notification area icon for Portkey Drop."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import wx
import wx.adv

if TYPE_CHECKING:
    from portkeydrop.app import MainFrame

logger = logging.getLogger(__name__)


class SystemTrayIcon(wx.adv.TaskBarIcon):
    """Cross-platform system tray / notification area icon."""

    def __init__(self, frame: MainFrame) -> None:
        super().__init__()
        self.frame = frame
        self._icon_set = False
        self._cached_icon: wx.Icon | None = None

        self._setup_icon()
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DOWN, self._on_left_click)
        self.Bind(wx.adv.EVT_TASKBAR_LEFT_DCLICK, self._on_left_click)
        self.Bind(wx.adv.EVT_TASKBAR_RIGHT_DOWN, self._on_right_click)

    def _setup_icon(self) -> None:
        icon = self._load_icon()
        if icon is not None and icon.IsOk():
            self._cached_icon = icon
            self.SetIcon(icon, "Portkey Drop")
            self._icon_set = True
            logger.debug("Notification area icon set")
        else:
            logger.warning("Notification area icon could not be loaded")

    def _load_icon(self) -> wx.Icon | None:
        for icon_path in self._get_icon_paths():
            if not icon_path.exists():
                continue
            try:
                bitmap_type = (
                    wx.BITMAP_TYPE_ICO if icon_path.suffix.lower() == ".ico" else wx.BITMAP_TYPE_PNG
                )
                icon = wx.Icon(str(icon_path), bitmap_type)
                if icon.IsOk():
                    return icon
            except Exception:
                logger.debug("Failed to load tray icon from %s", icon_path, exc_info=True)
        return self._create_default_icon()

    def _get_icon_paths(self) -> list[Path]:
        if getattr(sys, "frozen", False):
            base_path = Path(sys.executable).parent
            return [
                base_path / "app.ico",
                base_path / "resources" / "app.ico",
                base_path / "resources" / "app_32.png",
                base_path / "resources" / "app_16.png",
            ]

        package_path = Path(__file__).parent
        return [
            package_path / "resources" / "app.ico",
            package_path / "resources" / "app_32.png",
            package_path / "resources" / "app_16.png",
        ]

    def _create_default_icon(self) -> wx.Icon:
        bitmap = wx.Bitmap(16, 16)
        dc = wx.MemoryDC(bitmap)
        dc.SetBackground(wx.Brush(wx.Colour(42, 92, 170)))
        dc.Clear()
        dc.SetPen(wx.Pen(wx.WHITE, 1))
        dc.SetTextForeground(wx.WHITE)
        dc.DrawText("P", 4, 1)
        dc.SelectObject(wx.NullBitmap)

        icon = wx.Icon()
        icon.CopyFromBitmap(bitmap)
        return icon

    def _on_left_click(self, event) -> None:
        self.show_main_window()

    def _on_right_click(self, event) -> None:
        menu = self._create_popup_menu()
        try:
            self.PopupMenu(menu)
        finally:
            menu.Destroy()

    def _create_popup_menu(self) -> wx.Menu:
        menu = wx.Menu()
        show_item = menu.Append(wx.ID_ANY, "&Show Portkey Drop")
        queue_item = menu.Append(wx.ID_ANY, "Transfer &Queue...")
        updates_item = menu.Append(wx.ID_ANY, "Check for &Updates...")
        menu.AppendSeparator()
        exit_item = menu.Append(wx.ID_EXIT, "E&xit")

        self.Bind(wx.EVT_MENU, self._on_show_menu, show_item)
        self.Bind(wx.EVT_MENU, self._on_transfer_queue_menu, queue_item)
        self.Bind(wx.EVT_MENU, self._on_check_updates_menu, updates_item)
        self.Bind(wx.EVT_MENU, self._on_exit_menu, exit_item)
        return menu

    def _on_show_menu(self, event) -> None:
        self.show_main_window()

    def _on_transfer_queue_menu(self, event) -> None:
        self.show_main_window()
        self.frame._on_transfer_queue(event)

    def _on_check_updates_menu(self, event) -> None:
        self.show_main_window()
        self.frame._on_check_updates(event)

    def _on_exit_menu(self, event) -> None:
        self.frame.request_exit()

    def show_main_window(self) -> None:
        self.frame.Show(True)
        self.frame.Iconize(False)
        if sys.platform == "darwin":
            self.frame.RequestUserAttention()
        else:
            self.frame.Raise()
            self.frame.SetFocus()

    def update_tooltip(self, text: str) -> None:
        if self._icon_set and self._cached_icon is not None and self._cached_icon.IsOk():
            self.SetIcon(self._cached_icon, text)
