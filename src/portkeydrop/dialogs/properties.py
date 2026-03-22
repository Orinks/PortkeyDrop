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

        self._first_value_ctrl = None
        for label_text, value in fields:
            lbl = wx.StaticText(self, label=label_text)
            val = wx.TextCtrl(self, value=value, style=wx.TE_READONLY)
            # Associate the label with its control so NVDA/VoiceOver can resolve
            # the accessible name even when multiple rows share the same parent.
            if hasattr(lbl, "SetLabelFor"):
                lbl.SetLabelFor(val)
            grid.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(val, 1, wx.EXPAND)
            if self._first_value_ctrl is None:
                self._first_value_ctrl = val

        sizer.Add(grid, 1, wx.ALL | wx.EXPAND, 12)
        btn = self.CreateStdDialogButtonSizer(wx.OK)
        sizer.Add(btn, 0, wx.ALL | wx.EXPAND, 8)
        self.SetSizer(sizer)
        self.Fit()
        if self._first_value_ctrl:
            self._first_value_ctrl.SetFocus()
