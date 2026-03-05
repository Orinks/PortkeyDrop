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


def test_refresh_preserves_selected_transfer_when_list_updates(transfer_module):
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
    fake_wx.LIST_STATE_SELECTED = 1
    fake_wx.LIST_STATE_FOCUSED = 2

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
            id=10,
            remote_path="/remote/a.txt",
            local_path="/tmp/a.txt",
            direction=SimpleNamespace(value="download"),
            progress_pct=10,
            display_status="in_progress",
        ),
        SimpleNamespace(
            id=20,
            remote_path="/remote/b.txt",
            local_path="/tmp/b.txt",
            direction=SimpleNamespace(value="download"),
            progress_pct=50,
            display_status="in_progress",
        ),
    ]

    dialog = module.create_transfer_dialog(parent, manager)

    # Replace list control with controllable mock for selection assertions.
    list_mock = MagicMock()
    list_mock.GetFirstSelected.return_value = 1  # currently selected second transfer (id=20)
    list_mock.GetItemCount.side_effect = [0, 1]
    list_mock.InsertItem.side_effect = [0, 1]
    dialog.transfer_list = list_mock

    dialog._refresh()

    # Selection should be restored to row of transfer id=20.
    if list_mock.SetItemState.call_count:
        selected_rows = [c.args[0] for c in list_mock.SetItemState.call_args_list]
        assert 1 in selected_rows
    else:
        list_mock.Select.assert_called_once_with(1)


def test_get_selected_transfer_id_handles_non_int_selection(transfer_module):
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
    manager.transfers = []
    dialog = module.create_transfer_dialog(parent, manager)

    dialog.transfer_list.GetFirstSelected.return_value = object()
    assert dialog._get_selected_transfer_id() is None


def test_refresh_uses_select_fallback_without_set_item_state(transfer_module):
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
    # Intentionally do not define LIST_STATE_SELECTED/LIST_STATE_FOCUSED.

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
            id=1,
            remote_path="/remote/a.txt",
            local_path="/tmp/a.txt",
            direction=SimpleNamespace(value="download"),
            progress_pct=10,
            display_status="in_progress",
        )
    ]

    dialog = module.create_transfer_dialog(parent, manager)
    list_mock = MagicMock()
    list_mock.GetFirstSelected.return_value = 0
    list_mock.GetItemCount.return_value = 0
    list_mock.InsertItem.return_value = 0
    dialog.transfer_list = list_mock

    dialog._refresh()

    list_mock.Select.assert_called_once_with(0)


def test_get_selected_transfer_id_returns_none_for_not_found(transfer_module):
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
    fake_wx.NOT_FOUND = -1

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
    manager.transfers = []
    dialog = module.create_transfer_dialog(parent, manager)
    dialog.transfer_list.GetFirstSelected.return_value = -1

    assert dialog._get_selected_transfer_id() is None
