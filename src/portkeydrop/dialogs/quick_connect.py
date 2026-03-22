"""Quick Connect dialog for Portkey Drop."""

from __future__ import annotations

import wx

from portkeydrop.protocols import ConnectionInfo, Protocol


class QuickConnectDialog(wx.Dialog):
    """Dialog for quickly connecting to a server."""

    def __init__(self, parent: wx.Window | None = None) -> None:
        super().__init__(parent, title="Quick Connect", style=wx.DEFAULT_DIALOG_STYLE)
        self._connection_info: ConnectionInfo | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        sizer = wx.BoxSizer(wx.VERTICAL)
        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
        grid.AddGrowableCol(1, 1)

        def _link(label_widget, ctrl):  # pragma: no cover
            """Associate label with control for NVDA/VoiceOver name resolution."""
            if hasattr(label_widget, "SetLabelFor"):
                label_widget.SetLabelFor(ctrl)

        # Protocol
        lbl = wx.StaticText(self, label="&Protocol:")
        self.protocol_choice = wx.Choice(self, choices=["sftp", "ftp", "ftps"])
        self.protocol_choice.SetSelection(0)
        _link(lbl, self.protocol_choice)
        grid.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.protocol_choice, 1, wx.EXPAND)

        # Host
        lbl = wx.StaticText(self, label="&Host:")
        self.host_text = wx.TextCtrl(self)
        _link(lbl, self.host_text)
        grid.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.host_text, 1, wx.EXPAND)

        # Port
        lbl = wx.StaticText(self, label="P&ort:")
        self.port_text = wx.TextCtrl(self, value="22")
        _link(lbl, self.port_text)
        grid.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.port_text, 1, wx.EXPAND)

        # Username
        lbl = wx.StaticText(self, label="&Username:")
        self.username_text = wx.TextCtrl(self)
        _link(lbl, self.username_text)
        grid.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.username_text, 1, wx.EXPAND)

        # Password
        lbl = wx.StaticText(self, label="Pass&word:")
        self.password_text = wx.TextCtrl(self, style=wx.TE_PASSWORD)
        _link(lbl, self.password_text)
        grid.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.password_text, 1, wx.EXPAND)

        sizer.Add(grid, 1, wx.ALL | wx.EXPAND, 10)

        # Buttons
        btn_sizer = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(btn_sizer, 0, wx.ALL | wx.EXPAND, 10)

        self.SetSizer(sizer)
        self.Fit()

        # Set OK as default so Enter submits the form.
        ok_btn = self.FindWindowById(wx.ID_OK)
        if ok_btn:  # pragma: no cover
            ok_btn.SetDefault()

        # Focus the first field so screen readers announce the dialog purpose.
        self.protocol_choice.SetFocus()  # pragma: no cover

        # Update port when protocol changes
        self.protocol_choice.Bind(wx.EVT_CHOICE, self._on_protocol_change)

    def _on_protocol_change(self, event: wx.CommandEvent) -> None:
        proto = self.protocol_choice.GetStringSelection()
        defaults = {"sftp": "22", "ftp": "21", "ftps": "990"}
        self.port_text.SetValue(defaults.get(proto, "22"))

    def get_connection_info(self) -> ConnectionInfo:
        """Return ConnectionInfo from dialog fields."""
        proto_map = {"sftp": Protocol.SFTP, "ftp": Protocol.FTP, "ftps": Protocol.FTPS}
        proto_str = self.protocol_choice.GetStringSelection()
        port_str = self.port_text.GetValue().strip()
        return ConnectionInfo(
            protocol=proto_map.get(proto_str, Protocol.SFTP),
            host=self.host_text.GetValue().strip(),
            port=int(port_str) if port_str else 0,
            username=self.username_text.GetValue().strip(),
            password=self.password_text.GetValue(),
        )
