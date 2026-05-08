"""Accessible directory comparison preview dialog."""

from __future__ import annotations

from portkeydrop.directory_compare import CompareResult


def create_directory_compare_dialog(parent, result: CompareResult):
    """Create a modal read-only directory comparison dialog. Requires wx."""
    import wx

    class DirectoryCompareDialog(wx.Dialog):
        def __init__(self, parent_window, compare_result: CompareResult):
            super().__init__(
                parent_window,
                title="Directory Comparison",
                style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
                size=(720, 420),
            )
            self._result = compare_result
            self._build_ui()
            self._populate()
            self.compare_list.SetFocus()

        def _build_ui(self):
            root = wx.BoxSizer(wx.VERTICAL)

            summary = wx.StaticText(self, label=f"Summary: {self._result.summary}")
            root.Add(summary, 0, wx.EXPAND | wx.ALL, 8)

            wx.StaticText(self, label="Comparison results:")
            self.compare_list = wx.ListCtrl(self, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
            self.compare_list.SetName("Directory comparison results")
            self.compare_list.InsertColumn(0, "Name", width=220)
            self.compare_list.InsertColumn(1, "Action", width=150)
            self.compare_list.InsertColumn(2, "Local", width=110)
            self.compare_list.InsertColumn(3, "Remote", width=110)
            self.compare_list.InsertColumn(4, "Detail", width=260)
            root.Add(self.compare_list, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

            buttons = self.CreateStdDialogButtonSizer(wx.OK)
            root.Add(buttons, 0, wx.EXPAND | wx.ALL, 8)
            self.SetSizer(root)

        def _populate(self):
            for row in self._result.rows:
                idx = self.compare_list.InsertItem(self.compare_list.GetItemCount(), row.name)
                self.compare_list.SetItem(idx, 1, row.action_label)
                self.compare_list.SetItem(idx, 2, row.local.display_size if row.local else "")
                self.compare_list.SetItem(idx, 3, row.remote.display_size if row.remote else "")
                self.compare_list.SetItem(idx, 4, row.detail)
                self.compare_list.SetItemData(idx, idx)
            if self.compare_list.GetItemCount() > 0:
                self.compare_list.Select(0)
                self.compare_list.Focus(0)

    return DirectoryCompareDialog(parent, result)
