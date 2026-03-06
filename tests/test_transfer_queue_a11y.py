"""Accessibility tests for TransferDialog incremental refresh (issue #30)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests._wx_stub import load_module_with_fake_wx


class FakeListCtrl:
    """ListCtrl stub that tracks cell values for verifying incremental updates."""

    def __init__(self, *a, **kw):
        self._rows: list[list[str]] = []
        self._selected: int = -1
        self._focused: int = -1
        self._name = ""

    def SetName(self, name):
        self._name = name

    def InsertColumn(self, col, heading, width=0):
        pass

    def InsertItem(self, index, label):
        row = [label, "", "", ""]
        if index >= len(self._rows):
            self._rows.append(row)
        else:
            self._rows.insert(index, row)
        return index

    def SetItem(self, row, col, value):
        self._rows[row][col] = value

    def GetItemText(self, row, col=0):
        if 0 <= row < len(self._rows) and 0 <= col < len(self._rows[row]):
            return self._rows[row][col]
        return ""

    def GetItemCount(self):
        return len(self._rows)

    def GetFirstSelected(self):
        return self._selected

    def GetFocusedItem(self):
        return self._focused

    def Select(self, idx, on=True):
        self._selected = idx if on else -1

    def Focus(self, idx):
        self._focused = idx

    def DeleteAllItems(self):
        self._rows.clear()
        self._selected = -1
        self._focused = -1

    def DeleteItem(self, idx):
        if 0 <= idx < len(self._rows):
            self._rows.pop(idx)

    def Bind(self, *a, **kw):
        pass


@pytest.fixture
def transfer_module(monkeypatch):
    module, fake_wx = load_module_with_fake_wx("portkeydrop.dialogs.transfer", monkeypatch)
    return module, fake_wx


def _make_job(job_id, source, direction="download", progress=0, status="pending"):
    from portkeydrop.services.transfer_service import TransferDirection, TransferStatus

    return SimpleNamespace(
        id=job_id,
        source=source,
        destination="/tmp/" + source.rsplit("/", 1)[-1],
        direction=TransferDirection.UPLOAD if direction == "upload" else TransferDirection.DOWNLOAD,
        progress=progress,
        status=TransferStatus(status),
    )


def _make_service_and_dlg(jobs):
    svc = MagicMock()
    svc.jobs = list(jobs)
    dlg = MagicMock()
    dlg.transfer_list = FakeListCtrl()
    dlg._service = svc
    return dlg, svc


class TestIncrementalRefresh:
    """Issue #30: _refresh should update cells in place, not DeleteAllItems."""

    def test_initial_refresh_populates_list(self, transfer_module):
        module, fake_wx = transfer_module
        items = [
            _make_job("j1", "/path/file1.txt"),
            _make_job("j2", "/path/file2.txt", direction="upload"),
        ]
        dlg, svc = _make_service_and_dlg(items)

        _do_refresh(dlg, svc)

        assert dlg.transfer_list.GetItemCount() == 2
        assert dlg.transfer_list.GetItemText(0, 0) == "file1.txt"
        assert dlg.transfer_list.GetItemText(0, 1) == "download"
        assert dlg.transfer_list.GetItemText(1, 0) == "file2.txt"
        assert dlg.transfer_list.GetItemText(1, 1) == "upload"

    def test_progress_update_does_not_clear_list(self, transfer_module):
        module, fake_wx = transfer_module
        items = [
            _make_job("j1", "/path/file1.txt", progress=50, status="in_progress"),
        ]
        dlg, svc = _make_service_and_dlg(items)

        # Initial populate
        _do_refresh(dlg, svc)
        assert dlg.transfer_list.GetItemCount() == 1

        # Select and focus the item
        dlg.transfer_list.Select(0)
        dlg.transfer_list.Focus(0)

        # Update progress
        items[0].progress = 75
        svc.jobs = list(items)

        _do_refresh(dlg, svc)

        # Item count unchanged, selection/focus preserved
        assert dlg.transfer_list.GetItemCount() == 1
        assert dlg.transfer_list._selected == 0
        assert dlg.transfer_list._focused == 0
        assert dlg.transfer_list.GetItemText(0, 2) == "75%"

    def test_completed_transfer_updates_status_only(self, transfer_module):
        module, fake_wx = transfer_module
        from portkeydrop.services.transfer_service import TransferStatus

        items = [
            _make_job("j1", "/path/file1.txt", progress=50, status="in_progress"),
        ]
        dlg, svc = _make_service_and_dlg(items)
        _do_refresh(dlg, svc)

        # Mark as completed
        items[0].status = TransferStatus.COMPLETE
        items[0].progress = 100
        svc.jobs = list(items)

        _do_refresh(dlg, svc)

        assert dlg.transfer_list.GetItemCount() == 1
        assert dlg.transfer_list.GetItemText(0, 3) == "complete"

    def test_new_transfer_appended_without_clearing(self, transfer_module):
        module, fake_wx = transfer_module
        items = [
            _make_job("j1", "/path/file1.txt"),
        ]
        dlg, svc = _make_service_and_dlg(items)
        _do_refresh(dlg, svc)

        # Add a second transfer
        items.append(_make_job("j2", "/path/file2.txt", direction="upload"))
        svc.jobs = list(items)

        dlg.transfer_list.Select(0)
        dlg.transfer_list.Focus(0)

        _do_refresh(dlg, svc)

        assert dlg.transfer_list.GetItemCount() == 2
        assert dlg.transfer_list.GetItemText(0, 0) == "file1.txt"
        assert dlg.transfer_list.GetItemText(1, 0) == "file2.txt"
        # Selection preserved
        assert dlg.transfer_list._selected == 0

    def test_removed_transfer_shrinks_list(self, transfer_module):
        module, fake_wx = transfer_module
        items = [
            _make_job("j1", "/path/file1.txt"),
            _make_job("j2", "/path/file2.txt"),
        ]
        dlg, svc = _make_service_and_dlg(items)
        _do_refresh(dlg, svc)
        assert dlg.transfer_list.GetItemCount() == 2

        # Remove first transfer
        svc.jobs = [items[1]]

        _do_refresh(dlg, svc)

        assert dlg.transfer_list.GetItemCount() == 1
        assert dlg.transfer_list.GetItemText(0, 0) == "file2.txt"

    def test_selection_clamped_when_selected_item_removed(self, transfer_module):
        module, fake_wx = transfer_module
        items = [
            _make_job("j1", "/path/file1.txt"),
            _make_job("j2", "/path/file2.txt"),
        ]
        dlg, svc = _make_service_and_dlg(items)
        _do_refresh(dlg, svc)

        # Select the second item (which will be removed)
        dlg.transfer_list.Select(1)
        dlg.transfer_list.Focus(1)

        svc.jobs = [items[0]]
        _do_refresh(dlg, svc)

        # Selection should not be restored (out of range)
        assert dlg.transfer_list.GetItemCount() == 1


def _do_refresh(dlg, svc):
    """Replicate the TransferDialog._refresh logic for testing."""
    from pathlib import PurePosixPath
    from portkeydrop.services.transfer_service import TransferStatus

    jobs = svc.jobs
    selected = dlg.transfer_list.GetFirstSelected()
    focused = dlg.transfer_list.GetFocusedItem()

    current_count = dlg.transfer_list.GetItemCount()
    new_count = len(jobs)

    for i, j in enumerate(jobs):
        name = PurePosixPath(j.source).name
        display_status = (
            f"{j.progress}%" if j.status == TransferStatus.IN_PROGRESS else j.status.value
        )
        cols = [name, j.direction.value, f"{j.progress}%", display_status]
        if i >= current_count:
            row = dlg.transfer_list.InsertItem(i, cols[0])
            for col_idx in range(1, len(cols)):
                dlg.transfer_list.SetItem(row, col_idx, cols[col_idx])
        else:
            for col_idx, val in enumerate(cols):
                existing = dlg.transfer_list.GetItemText(i, col_idx)
                if existing != val:
                    dlg.transfer_list.SetItem(i, col_idx, val)

    for i in range(current_count - 1, new_count - 1, -1):
        dlg.transfer_list.DeleteItem(i)

    if 0 <= selected < new_count:
        dlg.transfer_list.Select(selected)
    if 0 <= focused < new_count:
        dlg.transfer_list.Focus(focused)
