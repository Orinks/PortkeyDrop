"""Tests for ImportConnectionsDialog (headless, wx-stubbed)."""

from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Minimal wx stubs for the ImportConnectionsDialog
# ---------------------------------------------------------------------------


class _Window:
    def __init__(self, parent=None, **_kw):
        self.parent = parent
        self.children: list[_Window] = []
        self._bound: list[tuple] = []
        if parent is not None and hasattr(parent, "children"):
            parent.children.append(self)

    def Bind(self, event, handler):
        self._bound.append((event, handler))

    def Show(self, show=True) -> None:
        self._shown = show

    def SetFocus(self) -> None:
        pass

    def Enable(self, enable=True) -> None:
        self._enabled = enable


class _Dialog(_Window):
    def __init__(self, parent=None, title: str = "", size=None, style: int = 0, **_kw):
        super().__init__(parent)
        self.title = title

    def SetSizer(self, sizer) -> None:
        pass

    def Layout(self) -> None:
        pass

    def EndModal(self, result: int) -> None:
        self._modal_result = result


class _Panel(_Window):
    def SetSizer(self, sizer) -> None:
        pass


class _StaticText(_Window):
    def __init__(self, parent=None, label: str = "", **_kw):
        super().__init__(parent)
        self._label = label

    def SetLabel(self, label: str) -> None:
        self._label = label


class _TextCtrl(_Window):
    def __init__(self, parent=None, **_kw):
        super().__init__(parent)
        self._value = ""

    def GetValue(self) -> str:
        return self._value

    def SetValue(self, value: str) -> None:
        self._value = value


class _RadioBox(_Window):
    def __init__(self, parent=None, label: str = "", choices=None, **_kw):
        super().__init__(parent)
        self._choices = choices or []
        self._selection = 0

    def GetSelection(self) -> int:
        return self._selection

    def SetSelection(self, index: int) -> None:
        self._selection = index


class _CheckListBox(_Window):
    def __init__(self, parent=None, **_kw):
        super().__init__(parent)
        self._items: list[str] = []
        self._checked: dict[int, bool] = {}

    def Clear(self) -> None:
        self._items.clear()
        self._checked.clear()

    def Append(self, label: str) -> None:
        self._items.append(label)

    def GetCount(self) -> int:
        return len(self._items)

    def Check(self, index: int, check: bool = True) -> None:
        self._checked[index] = check

    def IsChecked(self, index: int) -> bool:
        return self._checked.get(index, False)


class _Button(_Window):
    def __init__(self, parent=None, id: int = -1, label: str = "", **_kw):
        super().__init__(parent)
        self.label = label


class _BoxSizer:
    def __init__(self, orient=0):
        pass

    def Add(self, *args, **kwargs):
        pass

    def AddStretchSpacer(self, *args, **kwargs):
        pass


class _CommandEvent:
    pass


def _make_wx_module():
    fake_wx = types.ModuleType("wx")
    fake_wx.Dialog = _Dialog
    fake_wx.Panel = _Panel
    fake_wx.StaticText = _StaticText
    fake_wx.TextCtrl = _TextCtrl
    fake_wx.RadioBox = _RadioBox
    fake_wx.CheckListBox = _CheckListBox
    fake_wx.Button = _Button
    fake_wx.BoxSizer = _BoxSizer
    fake_wx.CommandEvent = _CommandEvent
    fake_wx.VERTICAL = 0
    fake_wx.HORIZONTAL = 1
    fake_wx.DEFAULT_DIALOG_STYLE = 1
    fake_wx.RESIZE_BORDER = 2
    fake_wx.ALL = 0x10
    fake_wx.LEFT = 0x20
    fake_wx.RIGHT = 0x40
    fake_wx.EXPAND = 0x80
    fake_wx.RA_SPECIFY_ROWS = 0
    fake_wx.ID_CANCEL = 5101
    fake_wx.ID_OK = 5100
    fake_wx.OK = 0x04
    fake_wx.ICON_WARNING = 0x100
    fake_wx.ICON_ERROR = 0x200
    fake_wx.ICON_INFORMATION = 0x800
    fake_wx.FD_OPEN = 0x01
    fake_wx.FD_FILE_MUST_EXIST = 0x02
    fake_wx.DD_DIR_MUST_EXIST = 0x04
    fake_wx.EVT_RADIOBOX = object()
    fake_wx.EVT_BUTTON = object()
    fake_wx.MessageBox = lambda *a, **kw: None
    return fake_wx


def _load_dialog(monkeypatch):
    """Import ImportConnectionsDialog with fake wx and return the class."""
    fake_wx = _make_wx_module()
    monkeypatch.setitem(sys.modules, "wx", fake_wx)

    sys.modules.pop("portkeydrop.dialogs.import_connections", None)
    mod = importlib.import_module("portkeydrop.dialogs.import_connections")
    return mod.ImportConnectionsDialog


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAutoDetectOnSourceChange:
    """Auto-detect should fire automatically when the client selection changes."""

    def test_source_change_triggers_autodetect(self, monkeypatch):
        """Selecting a client from the dropdown should auto-detect and pre-fill the path."""
        DialogCls = _load_dialog(monkeypatch)
        dlg = DialogCls(None)

        # Select WinSCP (index 1)
        dlg.source_radio.SetSelection(1)

        with patch(
            "portkeydrop.dialogs.import_connections.detect_default_path",
            return_value="/fake/WinSCP.ini",
        ):
            dlg._on_source_change(_CommandEvent())

        assert dlg.path_text.GetValue() == "/fake/WinSCP.ini"

    def test_source_change_clears_path_when_no_default(self, monkeypatch):
        """When no default is detected, the path should stay empty."""
        DialogCls = _load_dialog(monkeypatch)
        dlg = DialogCls(None)

        dlg.source_radio.SetSelection(3)  # "From file..." — no auto-detect

        with patch(
            "portkeydrop.dialogs.import_connections.detect_default_path",
            return_value=None,
        ):
            dlg._on_source_change(_CommandEvent())

        assert dlg.path_text.GetValue() == ""

    def test_autodetect_button_still_works_as_manual_retry(self, monkeypatch):
        """The Auto-Detect button should work as a manual retry."""
        DialogCls = _load_dialog(monkeypatch)
        dlg = DialogCls(None)

        dlg.source_radio.SetSelection(0)  # FileZilla

        with patch(
            "portkeydrop.dialogs.import_connections.detect_default_path",
            return_value="/fake/filezilla.xml",
        ):
            dlg._on_autodetect(_CommandEvent())

        assert dlg.path_text.GetValue() == "/fake/filezilla.xml"


class TestWinSCPRegistrySentinel:
    """The dialog should handle the WinSCP registry sentinel correctly."""

    def test_source_change_to_winscp_shows_registry_sentinel(self, monkeypatch):
        """When WinSCP is selected and registry is available, show registry sentinel."""
        DialogCls = _load_dialog(monkeypatch)
        from portkeydrop.importers import WINSCP_REGISTRY_SENTINEL

        dlg = DialogCls(None)
        dlg.source_radio.SetSelection(1)  # WinSCP

        with patch(
            "portkeydrop.dialogs.import_connections.detect_default_path",
            return_value=WINSCP_REGISTRY_SENTINEL,
        ):
            dlg._on_source_change(_CommandEvent())

        assert dlg.path_text.GetValue() == WINSCP_REGISTRY_SENTINEL

    def test_load_preview_with_registry_sentinel_passes_none_path(self, monkeypatch):
        """When the path text contains the registry sentinel, load_from_source gets path=None."""
        DialogCls = _load_dialog(monkeypatch)
        from portkeydrop.importers import WINSCP_REGISTRY_SENTINEL
        from portkeydrop.importers.models import ImportedSite

        from portkeydrop.importers import ImportSource

        with patch(
            "portkeydrop.dialogs.import_connections.available_sources",
            return_value=[
                ImportSource("winscp", "WinSCP"),
                ImportSource("from_file", "From file..."),
            ],
        ):
            dlg = DialogCls(None)
        dlg.source_radio.SetSelection(0)  # WinSCP in filtered list
        dlg.path_text.SetValue(WINSCP_REGISTRY_SENTINEL)

        fake_site = ImportedSite(name="test", protocol="sftp", host="example.com", port=22)
        with patch(
            "portkeydrop.dialogs.import_connections.load_from_source",
            return_value=[fake_site],
        ) as mock_load:
            result = dlg._load_preview()

        assert result is True
        mock_load.assert_called_once_with("winscp", None)


class TestAvailableSourceIndexMapping:
    """Selection index should map against available (filtered) source list."""

    def test_autodetect_uses_filtered_source_list(self, monkeypatch):
        """If only WinSCP + From file are available, index 0 must map to WinSCP."""
        DialogCls = _load_dialog(monkeypatch)
        from portkeydrop.importers import ImportSource

        with patch(
            "portkeydrop.dialogs.import_connections.available_sources",
            return_value=[
                ImportSource("winscp", "WinSCP"),
                ImportSource("from_file", "From file..."),
            ],
        ):
            dlg = DialogCls(None)

        # First choice in filtered list is WinSCP, not FileZilla.
        dlg.source_radio.SetSelection(0)

        with patch(
            "portkeydrop.dialogs.import_connections.detect_default_path",
            return_value="/fake/WinSCP.ini",
        ) as mock_detect:
            dlg._on_autodetect(_CommandEvent())

        mock_detect.assert_called_once_with("winscp")
        assert dlg.path_text.GetValue() == "/fake/WinSCP.ini"


class TestWinSCPMessaging:
    """WinSCP errors should include actionable troubleshooting guidance."""

    def test_winscp_no_sites_message_includes_tip(self, monkeypatch):
        DialogCls = _load_dialog(monkeypatch)
        from portkeydrop.importers import ImportSource

        with patch(
            "portkeydrop.dialogs.import_connections.available_sources",
            return_value=[
                ImportSource("filezilla", "FileZilla"),
                ImportSource("winscp", "WinSCP"),
                ImportSource("from_file", "From file..."),
            ],
        ):
            dlg = DialogCls(None)

        dlg.source_radio.SetSelection(1)  # WinSCP
        dlg.path_text.SetValue("")

        with (
            patch(
                "portkeydrop.dialogs.import_connections.load_from_source",
                return_value=[],
            ),
            patch("portkeydrop.dialogs.import_connections.wx.MessageBox") as mock_message,
        ):
            result = dlg._load_preview()

        assert result is False
        message = mock_message.call_args.args[0]
        assert "No connections were found" in message
        assert "[Sessions\\...]" in message

    def test_winscp_parse_error_message_mentions_master_password(self, monkeypatch):
        DialogCls = _load_dialog(monkeypatch)
        from portkeydrop.importers import ImportSource

        with patch(
            "portkeydrop.dialogs.import_connections.available_sources",
            return_value=[
                ImportSource("filezilla", "FileZilla"),
                ImportSource("winscp", "WinSCP"),
                ImportSource("from_file", "From file..."),
            ],
        ):
            dlg = DialogCls(None)

        dlg.source_radio.SetSelection(1)  # WinSCP
        dlg.path_text.SetValue("")

        with (
            patch(
                "portkeydrop.dialogs.import_connections.load_from_source",
                side_effect=ValueError("bad format"),
            ),
            patch("portkeydrop.dialogs.import_connections.wx.MessageBox") as mock_message,
        ):
            result = dlg._load_preview()

        assert result is False
        message = mock_message.call_args.args[0]
        assert "Failed to parse configuration" in message
        assert "master password" in message.lower()
