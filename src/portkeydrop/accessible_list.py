"""Cross-platform report-list helpers with a macOS VoiceOver fallback."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import importlib
from typing import Any


RowFormatter = Callable[[Sequence[str], Sequence[str]], str]


def _wx() -> Any:
    return importlib.import_module("wx")


def _is_macos() -> bool:
    wx = _wx()
    return getattr(wx, "Platform", "") == "__WXMAC__"


def file_row_text(columns: Sequence[str], _headers: Sequence[str]) -> str:
    name = columns[0] if len(columns) > 0 else ""
    size = columns[1] if len(columns) > 1 else ""
    kind = columns[2] if len(columns) > 2 else ""
    modified = columns[3] if len(columns) > 3 else ""
    permissions = columns[4] if len(columns) > 4 else ""

    parts = [name or "Item"]
    if kind:
        parts.append(kind)
    if size:
        parts.append(f"size {size}")
    if modified:
        parts.append(f"modified {modified}")
    if permissions:
        parts.append(f"permissions {permissions}")
    return ", ".join(parts)


def report_row_text(columns: Sequence[str], headers: Sequence[str]) -> str:
    parts = []
    for header, value in zip(headers, columns, strict=False):
        if value:
            parts.append(f"{header} {value}")
    return ", ".join(parts)


class AccessibleReportList:
    """A ListCtrl-compatible wrapper that uses ListBox on macOS.

    wx.ListCtrl works well enough for NVDA/JAWS in report mode, but VoiceOver
    often fails to expose useful row/column details. On macOS, a single-column
    ListBox with complete row text gives VoiceOver a simpler accessibility tree.
    """

    def __init__(
        self,
        parent: Any,
        *,
        style: int = 0,
        row_formatter: RowFormatter | None = None,
    ) -> None:
        self._headers: list[str] = []
        self._rows: list[list[str]] = []
        self._row_formatter = row_formatter or report_row_text
        self._wx = _wx()
        self._focused = self._wx.NOT_FOUND
        self._is_listbox = _is_macos()

        if self._is_listbox:
            listbox_style = getattr(self._wx, "LB_SINGLE", 0)
            self._ctrl = self._wx.ListBox(parent, style=listbox_style)
        else:
            self._ctrl = self._wx.ListCtrl(parent, style=style)
            for name in (
                "Bind",
                "DeleteAllItems",
                "DeleteItem",
                "Focus",
                "GetFirstSelected",
                "GetFocusedItem",
                "GetItemCount",
                "GetItemText",
                "InsertColumn",
                "InsertItem",
                "Select",
                "SetFocus",
                "SetItem",
            ):
                setattr(self, name, getattr(self._ctrl, name))

    @property
    def window(self) -> Any:
        return self._ctrl

    def __getattr__(self, name: str) -> Any:
        return getattr(self._ctrl, name)

    def InsertColumn(self, col: int, heading: str, width: int = -1) -> None:
        if col >= len(self._headers):
            self._headers.extend([""] * (col - len(self._headers) + 1))
        self._headers[col] = heading
        if not self._is_listbox:
            self._ctrl.InsertColumn(col, heading, width=width)

    def InsertItem(self, index: int, label: str) -> int:
        if not self._is_listbox:
            return self._ctrl.InsertItem(index, label)

        row = ["" for _ in self._headers]
        if not row:
            row = [""]
        row[0] = label
        index = max(0, min(index, len(self._rows)))
        self._rows.insert(index, row)
        self._ctrl.InsertItems([self._format_row(index)], index)
        return index

    def SetItem(self, row: int, col: int, value: str) -> None:
        if not self._is_listbox:
            self._ctrl.SetItem(row, col, value)
            return

        previous_count = len(self._rows)
        self._ensure_cell(row, col)
        self._rows[row][col] = value
        if row >= previous_count:
            new_items = [self._format_row(i) for i in range(previous_count, len(self._rows))]
            self._ctrl.InsertItems(new_items, previous_count)
        else:
            self._ctrl.SetString(row, self._format_row(row))

    def GetItemText(self, row: int, col: int = 0) -> str:
        if not self._is_listbox:
            return self._ctrl.GetItemText(row, col)
        if 0 <= row < len(self._rows) and 0 <= col < len(self._rows[row]):
            return self._rows[row][col]
        return ""

    def GetItemCount(self) -> int:
        if not self._is_listbox:
            return self._ctrl.GetItemCount()
        return len(self._rows)

    def DeleteAllItems(self) -> None:
        self._rows.clear()
        self._focused = self._wx.NOT_FOUND
        if self._is_listbox:
            self._ctrl.Clear()
        else:
            self._ctrl.DeleteAllItems()

    def DeleteItem(self, row: int) -> None:
        if not self._is_listbox:
            self._ctrl.DeleteItem(row)
            return
        if 0 <= row < len(self._rows):
            del self._rows[row]
            self._ctrl.Delete(row)
            if self._focused >= len(self._rows):
                self._focused = self._wx.NOT_FOUND

    def GetFirstSelected(self) -> int:
        if not self._is_listbox:
            return self._ctrl.GetFirstSelected()
        selection = self._ctrl.GetSelection()
        if 0 <= selection < len(self._rows):
            return selection
        return self._wx.NOT_FOUND

    def GetFocusedItem(self) -> int:
        if not self._is_listbox:
            return self._ctrl.GetFocusedItem()
        selected = self.GetFirstSelected()
        if selected != self._wx.NOT_FOUND:
            return selected
        if 0 <= self._focused < len(self._rows):
            return self._focused
        return self._wx.NOT_FOUND

    def Select(self, row: int, on: bool = True) -> None:
        if not self._is_listbox:
            self._ctrl.Select(row, on)
            return
        if on and 0 <= row < len(self._rows):
            self._ctrl.SetSelection(row)
            self._focused = row
        elif not on and self.GetFirstSelected() == row:
            self._ctrl.SetSelection(self._wx.NOT_FOUND)

    def Focus(self, row: int) -> None:
        if not self._is_listbox:
            self._ctrl.Focus(row)
            return
        if 0 <= row < len(self._rows):
            self._focused = row
            self._ctrl.SetSelection(row)

    def Bind(self, event: Any, handler: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        if self._is_listbox and event is self._wx.EVT_LIST_ITEM_ACTIVATED:
            self._bind_listbox_activation(handler)
            return
        if self._is_listbox and event is self._wx.EVT_KEY_DOWN:
            self._ctrl.Bind(self._wx.EVT_CHAR_HOOK, handler, *args, **kwargs)
            return
        self._ctrl.Bind(event, handler, *args, **kwargs)

    def _bind_listbox_activation(self, handler: Callable[..., Any]) -> None:
        if hasattr(self._wx, "EVT_LISTBOX_DCLICK"):
            self._ctrl.Bind(self._wx.EVT_LISTBOX_DCLICK, handler)

        def on_char_hook(event: Any) -> None:
            key = event.GetKeyCode()
            enter_keys = {
                getattr(self._wx, "WXK_RETURN", 13),
                getattr(self._wx, "WXK_NUMPAD_ENTER", 13),
            }
            if key in enter_keys:
                handler(event)
                return
            event.Skip()

        self._ctrl.Bind(self._wx.EVT_CHAR_HOOK, on_char_hook)

    def _format_row(self, row: int) -> str:
        return self._row_formatter(self._rows[row], self._headers)

    def _ensure_cell(self, row: int, col: int) -> None:
        while row >= len(self._rows):
            self._rows.append(["" for _ in self._headers])
        if col >= len(self._rows[row]):
            self._rows[row].extend([""] * (col - len(self._rows[row]) + 1))


def create_report_list(
    parent: Any,
    *,
    style: int = 0,
    row_formatter: RowFormatter | None = None,
) -> AccessibleReportList:
    return AccessibleReportList(parent, style=style, row_formatter=row_formatter)
