"""File properties dialog for Portkey Drop."""

from __future__ import annotations

import wx

from portkeydrop.protocols import RemoteFile


class PropertiesDialog(wx.Dialog):
    """Dialog showing properties of a remote file or directory."""

    def __init__(self, parent: wx.Window | None, remote_file: RemoteFile) -> None:
        super().__init__(parent, title="File Properties", style=wx.DEFAULT_DIALOG_STYLE)
        self._file = remote_file
        self._build_ui()
        self.SetName("File Properties Dialog")

    def _build_ui(self) -> None:
        sizer = wx.BoxSizer(wx.VERTICAL)
        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=12)
        grid.AddGrowableCol(1, 1)

        fields = [
            ("Name:", self._file.name),
            ("Path:", self._file.path),
            ("Size:", self._file.display_size),
            ("Type:", "Directory" if self._file.is_dir else "File"),
            ("Modified:", self._file.display_modified or "Unknown"),
            ("Permissions:", self._file.permissions or "Unknown"),
            ("Owner:", self._file.owner or "Unknown"),
        ]

        for label_text, value in fields:
            lbl = wx.StaticText(self, label=label_text)
            val = wx.TextCtrl(self, value=value, style=wx.TE_READONLY)
            val.SetName(label_text.rstrip(":"))
            if hasattr(lbl, "SetLabelFor"):
                lbl.SetLabelFor(val)
            grid.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(val, 1, wx.EXPAND)

        sizer.Add(grid, 1, wx.ALL | wx.EXPAND, 12)
        btn = self.CreateStdDialogButtonSizer(wx.OK)
        ok_btn = self.FindWindowById(wx.ID_OK)
        if ok_btn:
            ok_btn.SetName("Close File Properties")
            ok_btn.SetFocus()
        sizer.Add(btn, 0, wx.ALL | wx.EXPAND, 8)
        self.SetSizer(sizer)
        self.Fit()
