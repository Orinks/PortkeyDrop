"""Tests for the Quick Connect dialog protocol choices."""

from __future__ import annotations

import importlib
import sys
import types


class _Window:
    def Bind(self, *_args, **_kwargs):
        return None

    def SetFocus(self):
        return None


class _Dialog(_Window):
    def __init__(self, *_args, **_kwargs):
        return None

    def SetSizer(self, *_args, **_kwargs):
        return None

    def Fit(self):
        return None

    def FindWindowById(self, _id):
        return _Button()

    def CreateStdDialogButtonSizer(self, *_args, **_kwargs):
        return _Sizer()


class _Sizer:
    def __init__(self, *_args, **_kwargs):
        return None

    def Add(self, *_args, **_kwargs):
        return None

    def AddGrowableCol(self, *_args, **_kwargs):
        return None


class _StaticText(_Window):
    def __init__(self, *_args, **_kwargs):
        self.label_for = None

    def SetLabelFor(self, ctrl):
        self.label_for = ctrl


class _Choice(_Window):
    def __init__(self, *_args, choices=None, **_kwargs):
        self.choices = choices or []
        self.selection = 0

    def SetSelection(self, selection):
        self.selection = selection

    def GetStringSelection(self):
        return self.choices[self.selection]


class _TextCtrl(_Window):
    def __init__(self, *_args, value="", **_kwargs):
        self.value = value

    def SetValue(self, value):
        self.value = value

    def GetValue(self):
        return self.value


class _Button(_Window):
    def SetDefault(self):
        return None


def _load_quick_connect(monkeypatch):
    wx = types.ModuleType("wx")
    wx.Dialog = _Dialog
    wx.Window = _Window
    wx.BoxSizer = _Sizer
    wx.FlexGridSizer = _Sizer
    wx.StaticText = _StaticText
    wx.Choice = _Choice
    wx.TextCtrl = _TextCtrl
    wx.DEFAULT_DIALOG_STYLE = 1
    wx.VERTICAL = 2
    wx.EXPAND = 4
    wx.ALL = 8
    wx.ALIGN_CENTER_VERTICAL = 16
    wx.TE_PASSWORD = 32
    wx.OK = 64
    wx.CANCEL = 128
    wx.ID_OK = 1
    wx.EVT_CHOICE = object()
    monkeypatch.setitem(sys.modules, "wx", wx)
    sys.modules.pop("portkeydrop.dialogs.quick_connect", None)
    return importlib.import_module("portkeydrop.dialogs.quick_connect")


def test_quick_connect_exposes_webdav_and_default_port(monkeypatch):
    module = _load_quick_connect(monkeypatch)
    dialog = module.QuickConnectDialog()

    assert dialog.protocol_choice.choices == ["sftp", "ftp", "ftps", "webdav"]

    dialog.protocol_choice.SetSelection(3)
    dialog._on_protocol_change(None)

    assert dialog.port_text.GetValue() == "443"
    assert dialog.get_connection_info().protocol is module.Protocol.WEBDAV
