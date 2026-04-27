"""Tests for TransferDialog._refresh coverage branches."""

from __future__ import annotations

from types import SimpleNamespace
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

        def Hide(self):
            pass

        def Destroy(self):
            pass

        def GetParent(self):
            return self._parent

    fake_wx.Dialog = _Dialog

    return module, fake_wx


def _make_job(
    transfer_id,
    path,
    direction="download",
    progress=0,
    status="pending",
    transferred_bytes=0,
    total_bytes=0,
):
    from portkeydrop.services.transfer_service import TransferDirection, TransferStatus

    return SimpleNamespace(
        id=transfer_id,
        source=path,
        destination="/tmp/" + path.rsplit("/", 1)[-1],
        direction=TransferDirection.UPLOAD if direction == "upload" else TransferDirection.DOWNLOAD,
        progress=progress,
        transferred_bytes=transferred_bytes,
        total_bytes=total_bytes,
        status=TransferStatus(status),
    )


def _build_dialog(module, fake_wx):
    transfer_list = MagicMock(name="transfer_list")
    transfer_list.GetFirstSelected.return_value = -1
    transfer_list.GetFocusedItem.return_value = -1
    transfer_list.GetItemCount.return_value = 0
    transfer_list.InsertItem.side_effect = lambda i, _label: i

    fake_wx.ListCtrl = MagicMock(return_value=transfer_list)
    parent = MagicMock(name="parent_dialog")
    service = MagicMock(name="transfer_service")
    service.jobs = []

    dialog = module.create_transfer_dialog(parent, service)
    transfer_list.reset_mock()
    return dialog, transfer_list, service


def test_refresh_empty_transfers_removes_existing_rows(transfer_module):
    module, fake_wx = transfer_module
    dialog, transfer_list, service = _build_dialog(module, fake_wx)
    service.jobs = []
    transfer_list.GetItemCount.return_value = 3

    dialog._refresh()

    transfer_list.DeleteItem.assert_has_calls([call(2), call(1), call(0)])
    transfer_list.DeleteAllItems.assert_not_called()


def test_refresh_adds_new_transfers_when_row_missing(transfer_module):
    module, fake_wx = transfer_module
    dialog, transfer_list, service = _build_dialog(module, fake_wx)
    service.jobs = [
        _make_job("j1", "/tmp/a.txt", "download", progress=25, status="in_progress"),
        _make_job("j2", "/tmp/b.txt", "upload", progress=0, status="pending"),
    ]
    transfer_list.GetItemCount.return_value = 0

    dialog._refresh()

    transfer_list.InsertItem.assert_has_calls([call(0, "a.txt"), call(1, "b.txt")])
    assert transfer_list.SetItem.call_count == 8
    transfer_list.DeleteAllItems.assert_not_called()


def test_refresh_shows_transferred_bytes_as_progress_detail(transfer_module):
    module, fake_wx = transfer_module
    dialog, transfer_list, service = _build_dialog(module, fake_wx)
    service.jobs = [
        _make_job(
            "j3",
            "/tmp/archive.zip",
            "download",
            progress=50,
            status="in_progress",
            transferred_bytes=1024,
            total_bytes=2048,
        ),
    ]
    transfer_list.GetItemCount.return_value = 0

    dialog._refresh()

    transfer_list.SetItem.assert_any_call(0, 3, "1.0 KB of 2.0 KB")
    transfer_list.SetItem.assert_any_call(0, 4, "50%")


def test_refresh_updates_only_changed_existing_cells(transfer_module):
    module, fake_wx = transfer_module
    dialog, transfer_list, service = _build_dialog(module, fake_wx)
    service.jobs = [_make_job("j10", "/tmp/file.txt", "upload", progress=40, status="in_progress")]
    transfer_list.GetItemCount.return_value = 1
    transfer_list.GetItemText.side_effect = lambda _row, _col: "stale"

    dialog._refresh()

    transfer_list.InsertItem.assert_not_called()
    assert transfer_list.SetItem.call_count == 5
    transfer_list.DeleteAllItems.assert_not_called()


def test_refresh_does_not_set_item_when_values_unchanged(transfer_module):
    module, fake_wx = transfer_module
    dialog, transfer_list, service = _build_dialog(module, fake_wx)
    service.jobs = [
        _make_job("j11", "/tmp/same.txt", "download", progress=50, status="in_progress")
    ]
    transfer_list.GetItemCount.return_value = 1
    current_values = ["same.txt", "download", "50%", "0 B transferred", "50%"]
    transfer_list.GetItemText.side_effect = lambda _row, col: current_values[col]

    dialog._refresh()

    transfer_list.InsertItem.assert_not_called()
    transfer_list.SetItem.assert_not_called()
    transfer_list.DeleteAllItems.assert_not_called()


def test_refresh_restores_selection_and_focus(transfer_module):
    module, fake_wx = transfer_module
    dialog, transfer_list, service = _build_dialog(module, fake_wx)
    service.jobs = [
        _make_job("j21", "/tmp/one.txt"),
        _make_job("j22", "/tmp/two.txt"),
    ]
    transfer_list.GetItemCount.return_value = 2
    transfer_list.GetFirstSelected.return_value = 1
    transfer_list.GetFocusedItem.return_value = 0
    transfer_list.GetItemText.side_effect = lambda _row, _col: "stale"

    dialog._refresh()

    transfer_list.Select.assert_called_once_with(1)
    transfer_list.Focus.assert_called_once_with(0)
    transfer_list.DeleteAllItems.assert_not_called()
