"""Tests for TransferDialog._refresh coverage branches."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from tests._wx_stub import load_module_with_fake_wx


@pytest.fixture
def transfer_module(monkeypatch):
    module, fake_wx = load_module_with_fake_wx("portkeydrop.dialogs.transfer", monkeypatch)

    # Constants used by create_transfer_dialog but not present in the generic stub.
    fake_wx.DEFAULT_DIALOG_STYLE = 0
    fake_wx.RESIZE_BORDER = 0
    fake_wx.CLOSE_BOX = 0
    fake_wx.ID_CLOSE = 5100
    fake_wx.RIGHT = 0
    fake_wx.ALIGN_RIGHT = 0
    fake_wx.WXK_ESCAPE = 27

    class _Dialog:
        def __init__(self, parent, **_kwargs):
            self._parent = parent
            self._bindings = []

        def Bind(self, *args, **kwargs):
            self._bindings.append((args, kwargs))

        def SetName(self, *_args, **_kwargs):
            pass

        def SetSizer(self, *_args, **_kwargs):
            pass

        def Close(self):
            pass

        def Destroy(self):
            pass

        def GetParent(self):
            return self._parent

    fake_wx.Dialog = _Dialog

    return module, fake_wx


def _make_transfer(
    module, transfer_id: int, path: str, direction="download", progress=0, status="queued"
):
    item = module.TransferItem()
    item.id = transfer_id
    item.remote_path = path
    item.direction = (
        module.TransferDirection.UPLOAD
        if direction == "upload"
        else module.TransferDirection.DOWNLOAD
    )
    item.transferred_bytes = progress
    item.total_bytes = 100 if progress else 0
    item.status = module.TransferStatus(status)
    return item


def _build_dialog(module, fake_wx):
    transfer_list = MagicMock(name="transfer_list")
    transfer_list.GetFirstSelected.return_value = -1
    transfer_list.GetFocusedItem.return_value = -1
    transfer_list.GetItemCount.return_value = 0
    transfer_list.InsertItem.side_effect = lambda i, _label: i

    fake_wx.ListCtrl = MagicMock(return_value=transfer_list)
    parent = MagicMock(name="parent_dialog")
    transfer_manager = MagicMock(name="transfer_manager")
    transfer_manager.transfers = []

    dialog = module.create_transfer_dialog(parent, transfer_manager)
    transfer_list.reset_mock()
    return dialog, transfer_list, transfer_manager


def test_refresh_empty_transfers_removes_existing_rows(transfer_module):
    module, fake_wx = transfer_module
    dialog, transfer_list, transfer_manager = _build_dialog(module, fake_wx)
    transfer_manager.transfers = []
    transfer_list.GetItemCount.return_value = 3

    dialog._refresh()

    transfer_list.DeleteItem.assert_has_calls([call(2), call(1), call(0)])


def test_refresh_adds_new_transfers_when_row_missing(transfer_module):
    module, fake_wx = transfer_module
    dialog, transfer_list, transfer_manager = _build_dialog(module, fake_wx)
    transfer_manager.transfers = [
        _make_transfer(module, 1, "/tmp/a.txt", "download", progress=25, status="in_progress"),
        _make_transfer(module, 2, "/tmp/b.txt", "upload", progress=0, status="queued"),
    ]
    transfer_list.GetItemCount.return_value = 0

    dialog._refresh()

    transfer_list.InsertItem.assert_has_calls([call(0, "a.txt"), call(1, "b.txt")])
    assert transfer_list.SetItem.call_count == 6


def test_refresh_updates_only_changed_existing_cells(transfer_module):
    module, fake_wx = transfer_module
    dialog, transfer_list, transfer_manager = _build_dialog(module, fake_wx)
    transfer_manager.transfers = [
        _make_transfer(module, 10, "/tmp/file.txt", "upload", progress=40, status="in_progress")
    ]
    transfer_list.GetItemCount.return_value = 1
    transfer_list.GetItemText.side_effect = lambda _row, _col: "stale"

    dialog._refresh()

    transfer_list.InsertItem.assert_not_called()
    assert transfer_list.SetItem.call_count == 4


def test_refresh_does_not_set_item_when_values_unchanged(transfer_module):
    module, fake_wx = transfer_module
    dialog, transfer_list, transfer_manager = _build_dialog(module, fake_wx)
    item = _make_transfer(
        module, 11, "/tmp/same.txt", "download", progress=50, status="in_progress"
    )
    transfer_manager.transfers = [item]
    transfer_list.GetItemCount.return_value = 1
    current_values = ["same.txt", "download", "50%", "50%"]
    transfer_list.GetItemText.side_effect = lambda _row, col: current_values[col]

    dialog._refresh()

    transfer_list.InsertItem.assert_not_called()
    transfer_list.SetItem.assert_not_called()


def test_refresh_restores_selection_and_focus(transfer_module):
    module, fake_wx = transfer_module
    dialog, transfer_list, transfer_manager = _build_dialog(module, fake_wx)
    transfer_manager.transfers = [
        _make_transfer(module, 21, "/tmp/one.txt"),
        _make_transfer(module, 22, "/tmp/two.txt"),
    ]
    transfer_list.GetItemCount.return_value = 2
    transfer_list.GetFirstSelected.return_value = 1
    transfer_list.GetFocusedItem.return_value = 0
    transfer_list.GetItemText.side_effect = lambda _row, _col: "stale"

    dialog._refresh()

    transfer_list.Select.assert_called_once_with(1)
    transfer_list.Focus.assert_called_once_with(0)
