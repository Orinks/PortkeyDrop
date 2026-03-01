"""Tests for SiteManagerDialog, including show/hide password toggle."""

from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import MagicMock
import pytest


# ---------------------------------------------------------------------------
# Minimal wx stub for SiteManagerDialog
# ---------------------------------------------------------------------------


class _Window:
    def __init__(self, parent=None, **_kw):
        pass

    def Bind(self, *a, **kw):
        pass

    def SetName(self, *a):
        pass

    def SetSizer(self, *a):
        pass

    def Layout(self):
        pass

    def SetFocus(self):
        pass

    def Destroy(self):
        pass

    def GetContainingSizer(self):
        return _Sizer()

    def GetWindowStyle(self):
        return 0

    def GetValue(self):
        return ""

    def SetValue(self, v):
        self._value = v

    def SetLabel(self, v):
        pass


class _Dialog(_Window):
    def __init__(self, parent=None, title="", size=None, style=0, **_kw):
        pass

    def EndModal(self, r):
        pass


class _Sizer:
    def GetItem(self, ctrl):
        return self

    def Replace(self, old, new):
        pass

    def Add(self, *a, **kw):
        pass


class _TextCtrl(_Window):
    def __init__(self, parent=None, style=0, **_kw):
        self._style = style
        self._value = ""

    def GetWindowStyle(self):
        return self._style

    def GetValue(self):
        return self._value

    def SetValue(self, v):
        self._value = v

    def GetContainingSizer(self):
        return _Sizer()

    def Destroy(self):
        pass


class _Button(_Window):
    def __init__(self, parent=None, label="", **_kw):
        self._label = label
        self._name = ""

    def SetLabel(self, v):
        self._label = v

    def SetName(self, v):
        self._name = v


class _Choice(_Window):
    def __init__(self, *a, choices=None, **kw):
        self._choices = choices or []

    def SetSelection(self, i):
        pass

    def GetStringSelection(self):
        return self._choices[0] if self._choices else ""


class _StaticText(_Window):
    pass


class _FlexGridSizer(_Sizer):
    def AddGrowableCol(self, *a):
        pass

    def Add(self, *a, **kw):
        pass


class _BoxSizer(_Sizer):
    def Add(self, *a, **kw):
        pass


class _ListBox(_Window):
    def __init__(self, *a, **kw):
        self._items = []

    def Clear(self):
        self._items = []

    def Append(self, label, data=None):
        self._items.append((label, data))

    def GetSelection(self):
        return -1

    def GetClientData(self, i):
        return None

    def Bind(self, *a, **kw):
        pass


def _make_fake_wx():
    wx = types.ModuleType("wx")
    wx.Dialog = _Dialog
    wx.Frame = _Window
    wx.Panel = _Window
    wx.TextCtrl = _TextCtrl
    wx.Button = _Button
    wx.Choice = _Choice
    wx.StaticText = _StaticText
    wx.FlexGridSizer = _FlexGridSizer
    wx.BoxSizer = _BoxSizer
    wx.ListBox = _ListBox
    wx.StaticBox = _Window
    wx.StaticBoxSizer = _BoxSizer
    wx.FileDialog = _Dialog
    wx.OK = 5100
    wx.ID_OK = 5100
    wx.CANCEL = 5101
    wx.ALIGN_CENTER_VERTICAL = 1
    wx.LEFT = 2
    wx.EXPAND = 4
    wx.ALL = 8
    wx.VERTICAL = 16
    wx.HORIZONTAL = 32
    wx.TE_PASSWORD = 64
    wx.DEFAULT_DIALOG_STYLE = 128
    wx.RESIZE_BORDER = 256
    wx.FD_OPEN = 512
    wx.FD_FILE_MUST_EXIST = 1024
    wx.NOT_FOUND = -1
    wx.EVT_BUTTON = object()
    wx.EVT_LISTBOX = object()
    wx.MessageBox = MagicMock(return_value=wx.OK)
    return wx


@pytest.fixture
def dialog_module(monkeypatch):
    fake_wx = _make_fake_wx()
    monkeypatch.setitem(sys.modules, "wx", fake_wx)
    sys.modules.pop("portkeydrop.dialogs.site_manager", None)
    mod = importlib.import_module("portkeydrop.dialogs.site_manager")
    return mod, fake_wx


def _make_dialog(mod, fake_wx, masked=True):
    site_manager = MagicMock()
    site_manager.sites = []
    dlg = object.__new__(mod.SiteManagerDialog)
    dlg._site_manager = site_manager
    dlg._selected_site = None
    dlg._connect_requested = False

    # Password ctrl
    pw = _TextCtrl(style=fake_wx.TE_PASSWORD if masked else 0)
    pw.SetValue("secret123")
    dlg.password_text = pw

    dlg.show_password_btn = _Button()
    dlg.Layout = MagicMock()
    return dlg


class TestTogglePassword:
    def test_show_reveals_password(self, dialog_module):
        mod, fake_wx = dialog_module
        dlg = _make_dialog(mod, fake_wx, masked=True)

        mod.SiteManagerDialog._on_toggle_password(dlg, MagicMock())

        # New ctrl is plain text (no TE_PASSWORD)
        assert dlg.password_text.GetWindowStyle() == 0
        # Value preserved
        assert dlg.password_text.GetValue() == "secret123"
        # Button updated
        assert dlg.show_password_btn._label == "H&ide"
        assert dlg.show_password_btn._name == "Hide password"
        dlg.Layout.assert_called_once()

    def test_hide_masks_password(self, dialog_module):
        mod, fake_wx = dialog_module
        dlg = _make_dialog(mod, fake_wx, masked=False)
        dlg.password_text.SetValue("secret123")

        mod.SiteManagerDialog._on_toggle_password(dlg, MagicMock())

        assert dlg.password_text.GetWindowStyle() == fake_wx.TE_PASSWORD
        assert dlg.show_password_btn._label == "S&how"
        assert dlg.show_password_btn._name == "Show password"

    def test_value_preserved_on_toggle(self, dialog_module):
        mod, fake_wx = dialog_module
        dlg = _make_dialog(mod, fake_wx, masked=True)
        dlg.password_text.SetValue("mypassword")

        mod.SiteManagerDialog._on_toggle_password(dlg, MagicMock())

        assert dlg.password_text.GetValue() == "mypassword"
