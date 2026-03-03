"""Tests for transfer dialog event binder helpers."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests._wx_stub import load_module_with_fake_wx


@pytest.fixture
def transfer_module(monkeypatch):
    module, fake_wx = load_module_with_fake_wx("portkeydrop.dialogs.transfer", monkeypatch)
    return module, fake_wx


def test_notify_posts_event(transfer_module):
    module, fake_wx = transfer_module
    fake_wx.PostEvent.reset_mock()
    module._TRANSFER_EVENT_BINDER = None
    module._TRANSFER_EVENT_TYPE = None
    window = MagicMock()
    manager = module.TransferManager(notify_window=window)

    manager._notify()

    fake_wx.PostEvent.assert_called_once()


def test_wx_event_binder_is_cached(transfer_module):
    module, fake_wx = transfer_module
    module._TRANSFER_EVENT_BINDER = None
    module._TRANSFER_EVENT_TYPE = None
    binder1, event_type1 = module._get_wx_event_binder()
    binder2, event_type2 = module._get_wx_event_binder()

    assert binder1 == binder2
    assert event_type1 == event_type2
    assert fake_wx.NewEventType.call_count == 1


def test_get_transfer_event_binder_returns_shared_value(transfer_module):
    module, _ = transfer_module
    module._TRANSFER_EVENT_BINDER = None
    module._TRANSFER_EVENT_TYPE = None

    binder = module.get_transfer_event_binder()

    assert binder is module._TRANSFER_EVENT_BINDER


def test_cancel_announces_filename_before_refresh(transfer_module):
    module, fake_wx = transfer_module
    fake_wx.DEFAULT_DIALOG_STYLE = 0
    fake_wx.RESIZE_BORDER = 0
    fake_wx.CLOSE_BOX = 0
    fake_wx.ID_CLOSE = 999
    fake_wx.RIGHT = 0
    fake_wx.ALIGN_RIGHT = 0
    fake_wx.WXK_ESCAPE = 27
    fake_wx.VERTICAL = 0
    fake_wx.HORIZONTAL = 0

    class _Dialog:
        def __init__(self, parent, *args, **kwargs):
            self._parent = parent

        def Bind(self, *args, **kwargs):
            return None

        def SetSizer(self, *args, **kwargs):
            return None

        def SetName(self, *args, **kwargs):
            return None

        def Close(self):
            return None

        def GetParent(self):
            return self._parent

        def Destroy(self):
            return None

    fake_wx.Dialog = _Dialog

    parent = MagicMock()
    manager = MagicMock()
    manager.transfers = [
        SimpleNamespace(
            id=5,
            remote_path="/remote/folder/report.csv",
            local_path="/tmp/report.csv",
            direction=SimpleNamespace(value="download"),
            progress_pct=0,
            display_status="queued",
        )
    ]

    dialog = module.create_transfer_dialog(parent, manager)
    dialog.GetParent = MagicMock(return_value=parent)
    dialog.transfer_list.GetFirstSelected.return_value = 0
    dialog._refresh = MagicMock()

    dialog._on_cancel(None)

    manager.cancel.assert_called_once_with(5)
    parent._announce.assert_called_once_with("Cancelled transfer: report.csv")
    dialog._refresh.assert_called_once()
