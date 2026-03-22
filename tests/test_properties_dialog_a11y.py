"""Accessibility tests for PropertiesDialog."""

from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import MagicMock


# -- Minimal wx stubs for PropertiesDialog --


class _Window:
    def __init__(self, parent=None, **_kw):
        self._name = ""
        self._focused = False

    def SetName(self, name):
        self._name = name

    def GetName(self):
        return self._name

    def SetFocus(self):
        self._focused = True

    def Bind(self, *a, **kw):
        pass

    def SetSizer(self, *a):
        pass

    def Fit(self):
        pass


class _Dialog(_Window):
    def __init__(self, parent=None, title="", style=0, **_kw):
        super().__init__(parent)

    def CreateStdDialogButtonSizer(self, _flags):
        return _BoxSizer()


class _BoxSizer:
    def __init__(self, *a, **kw):
        pass

    def Add(self, *a, **kw):
        pass


class _FlexGridSizer(_BoxSizer):
    def AddGrowableCol(self, *a):
        pass


class _StaticText(_Window):
    def __init__(self, parent=None, label="", **_kw):
        super().__init__(parent)
        self.label = label
        self._label_for = None

    def SetLabelFor(self, ctrl):
        self._label_for = ctrl


class _TextCtrl(_Window):
    def __init__(self, parent=None, value="", style=0, **_kw):
        super().__init__(parent)
        self._value = value

    def GetValue(self):
        return self._value

    def SetValue(self, v):
        self._value = v


def _make_fake_wx():
    wx = types.ModuleType("wx")
    wx.Dialog = _Dialog
    wx.StaticText = _StaticText
    wx.TextCtrl = _TextCtrl
    wx.BoxSizer = _BoxSizer
    wx.FlexGridSizer = _FlexGridSizer
    wx.OK = 5100
    wx.VERTICAL = 256
    wx.HORIZONTAL = 512
    wx.EXPAND = 64
    wx.ALL = 128
    wx.ALIGN_CENTER_VERTICAL = 1
    wx.DEFAULT_DIALOG_STYLE = 128
    wx.TE_READONLY = 2048
    return wx


def _make_remote_file():
    rf = MagicMock()
    rf.name = "test.txt"
    rf.path = "/home/user/test.txt"
    rf.display_size = "1.2 KB"
    rf.is_dir = False
    rf.display_modified = "2025-01-15"
    rf.permissions = "rwxr-xr-x"
    rf.owner = "user"
    return rf


def test_initial_focus_set_on_first_value_control(monkeypatch):
    """Issue #37: PropertiesDialog should set focus on the first field."""
    fake_wx = _make_fake_wx()
    monkeypatch.setitem(sys.modules, "wx", fake_wx)
    sys.modules.pop("portkeydrop.dialogs.properties", None)
    # Also stub the protocols import
    fake_protocols = types.ModuleType("portkeydrop.protocols")
    fake_protocols.RemoteFile = MagicMock
    monkeypatch.setitem(sys.modules, "portkeydrop.protocols", fake_protocols)

    mod = importlib.import_module("portkeydrop.dialogs.properties")

    rf = _make_remote_file()
    dlg = mod.PropertiesDialog(None, rf)

    assert dlg._first_value_ctrl is not None
    assert dlg._first_value_ctrl._focused is True


def test_first_value_ctrl_contains_file_name(monkeypatch):
    """The focused control should contain the file's name."""
    fake_wx = _make_fake_wx()
    monkeypatch.setitem(sys.modules, "wx", fake_wx)
    sys.modules.pop("portkeydrop.dialogs.properties", None)
    fake_protocols = types.ModuleType("portkeydrop.protocols")
    fake_protocols.RemoteFile = MagicMock
    monkeypatch.setitem(sys.modules, "portkeydrop.protocols", fake_protocols)

    mod = importlib.import_module("portkeydrop.dialogs.properties")

    rf = _make_remote_file()
    dlg = mod.PropertiesDialog(None, rf)

    assert dlg._first_value_ctrl.GetValue() == "test.txt"
