"""Helpers for injecting a fake wx module into tests."""

from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import MagicMock


class _FakeFrame:
    def __init__(self, *args, **kwargs):
        self._bindings: list[tuple] = []
        self.title = ""
        self.status_bar = MagicMock(SetStatusText=MagicMock())

    def Bind(self, *args, **kwargs) -> None:
        self._bindings.append((args, kwargs))

    def SetName(self, *args, **kwargs) -> None:
        pass

    def SetSizer(self, *_args, **_kwargs) -> None:
        pass

    def SetAcceleratorTable(self, table) -> None:
        self._accelerator_table = table

    def CreateStatusBar(self, *args, **kwargs):
        status = MagicMock(SetStatusText=MagicMock())
        self.status_bar = status
        return status

    def SetTitle(self, title: str) -> None:
        self.title = title

    def Show(self) -> None:
        pass

    def Raise(self) -> None:
        pass

    def FindFocus(self):
        return None

    def Focus(self) -> None:
        pass

    def Select(self, *args, **kwargs) -> None:
        pass


class _FakeApp(_FakeFrame):
    def MainLoop(self) -> None:
        pass


class _SimpleWidget(MagicMock):
    def __init__(self, *args, **kwargs):
        super().__init__(bind=MagicMock())
        self.Bind = MagicMock()
        self.SetSizer = MagicMock()
        self.InsertItem = MagicMock(return_value=0)
        self.SetItem = MagicMock()
        self.GetItemCount = MagicMock(return_value=0)
        self.Select = MagicMock()
        self.Focus = MagicMock()
        self.SetValue = MagicMock()
        self.GetValue = MagicMock()


def _create_fake_wx() -> tuple[types.ModuleType, types.ModuleType]:
    fake_wx = types.ModuleType("wx")
    counter = 0

    def _new_id_ref(*_args, **_kwargs):
        nonlocal counter
        counter += 1
        return counter

    fake_wx.NewIdRef = _new_id_ref
    fake_wx.Frame = _FakeFrame
    fake_wx.App = _FakeApp
    fake_wx.MenuBar = lambda *args, **kwargs: _SimpleWidget()
    fake_wx.Menu = lambda *args, **kwargs: _SimpleWidget()
    fake_wx.ToolBar = lambda *args, **kwargs: _SimpleWidget()
    fake_wx.Panel = lambda *args, **kwargs: _SimpleWidget()
    fake_wx.BoxSizer = lambda *args, **kwargs: _SimpleWidget()
    fake_wx.StaticText = lambda *args, **kwargs: _SimpleWidget()
    fake_wx.Choice = lambda *args, **kwargs: _SimpleWidget()
    fake_wx.TextCtrl = lambda *args, **kwargs: _SimpleWidget()
    fake_wx.Button = lambda *args, **kwargs: _SimpleWidget()
    fake_wx.ListCtrl = lambda *args, **kwargs: _SimpleWidget()
    fake_wx.Timer = lambda *args, **kwargs: _SimpleWidget()
    fake_wx.FileDataObject = MagicMock()

    class _Clipboard:
        @staticmethod
        def Open() -> bool:
            return False

        @staticmethod
        def GetData(_data) -> bool:
            return False

        @staticmethod
        def Close() -> None:
            pass

    fake_wx.TheClipboard = _Clipboard

    # Basic constants
    fake_wx.ALIGN_CENTER_VERTICAL = 1
    fake_wx.LEFT = 2
    fake_wx.EXPAND = 4
    fake_wx.ALL = 8
    fake_wx.VERTICAL = 16
    fake_wx.HORIZONTAL = 32
    fake_wx.LC_REPORT = 64
    fake_wx.LC_SINGLE_SEL = 128
    fake_wx.TE_PASSWORD = 256
    fake_wx.TE_PROCESS_ENTER = 512
    fake_wx.TE_MULTILINE = 1024
    fake_wx.TE_READONLY = 2048
    fake_wx.TE_RICH2 = 4096
    fake_wx.HSCROLL = 8192
    fake_wx.TOP = 16384
    fake_wx.WXK_BACK = 513
    fake_wx.WXK_DELETE = 514
    fake_wx.WXK_F2 = 515
    fake_wx.WXK_F6 = 516
    fake_wx.ACCEL_NORMAL = 1
    fake_wx.ACCEL_CTRL = 2
    fake_wx.ID_OK = 100
    fake_wx.OK = 100
    fake_wx.YES = 101
    fake_wx.YES_NO = 102
    fake_wx.ICON_WARNING = 103
    fake_wx.ICON_ERROR = 104
    fake_wx.ICON_INFORMATION = 105
    fake_wx.ID_EXIT = 200
    fake_wx.ID_ABOUT = 201

    fake_wx.StaticBox = lambda *args, **kwargs: _SimpleWidget()
    fake_wx.StaticBoxSizer = lambda *args, **kwargs: _SimpleWidget()

    fake_wx.EVT_MENU = object()
    fake_wx.EVT_BUTTON = object()
    fake_wx.EVT_CHOICE = object()
    fake_wx.EVT_LIST_ITEM_ACTIVATED = object()
    fake_wx.EVT_KEY_DOWN = object()
    fake_wx.EVT_CONTEXT_MENU = object()
    fake_wx.EVT_TEXT_ENTER = object()
    fake_wx.EVT_TIMER = object()
    fake_wx.EVT_CHAR_HOOK = object()
    fake_wx.EVT_CLOSE = object()
    fake_wx.FILECTRL_ACTIVATED = object()

    fake_wx.CallAfter = lambda callback, *args, **kwargs: callback(*args, **kwargs)
    fake_wx.Yield = lambda *args, **kwargs: None
    fake_wx.NotFound = -1
    fake_wx.NOT_FOUND = -1

    def _new_event_type() -> str:
        return f"event-{_new_id_ref()}"

    fake_wx.NewEventType = MagicMock(side_effect=_new_event_type)
    fake_wx.PyEventBinder = MagicMock(side_effect=lambda event_type, flag: f"binder-{event_type}")
    fake_wx.PyCommandEvent = MagicMock(
        side_effect=lambda event_type, id: MagicMock(event_type=event_type, id=id)
    )
    fake_wx.PostEvent = MagicMock()
    fake_wx.MessageBox = MagicMock(return_value=fake_wx.OK)

    fake_wx.Dialog = _SimpleWidget
    fake_wx.TextEntryDialog = lambda *args, **kwargs: _SimpleWidget()
    fake_wx.AcceleratorEntry = lambda flags, key_code, command: (flags, key_code, command)
    fake_wx.AcceleratorTable = lambda entries: tuple(entries)

    fake_adv = types.ModuleType("wx.adv")

    class _AboutDialogInfo:
        def __init__(self) -> None:
            self.name = ""
            self.version = ""
            self.description = ""

        def SetName(self, value: str) -> None:
            self.name = value

        def SetVersion(self, value: str) -> None:
            self.version = value

        def SetDescription(self, value: str) -> None:
            self.description = value

    fake_adv.AboutDialogInfo = _AboutDialogInfo
    fake_adv.AboutBox = lambda info: None
    fake_wx.adv = fake_adv

    return fake_wx, fake_adv


def load_module_with_fake_wx(
    module_name: str, monkeypatch
) -> tuple[types.ModuleType, types.ModuleType]:
    fake_wx, fake_adv = _create_fake_wx()
    monkeypatch.setitem(sys.modules, "wx", fake_wx)
    monkeypatch.setitem(sys.modules, "wx.adv", fake_adv)
    sys.modules.pop(module_name, None)
    module = importlib.import_module(module_name)
    return module, fake_wx
