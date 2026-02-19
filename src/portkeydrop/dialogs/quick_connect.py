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
        self.SetName("Quick Connect Dialog")

    def _add_field(self, grid: wx.FlexGridSizer, label_text: str, control: wx.Control, name: str) -> None:
        label = wx.StaticText(self, label=label_text)
        if hasattr(label, "SetLabelFor"):
            label.SetLabelFor(control)
        control.SetName(name)
        grid.Add(label, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(control, 1, wx.EXPAND)

    def _build_ui(self) -> None:
        sizer = wx.BoxSizer(wx.VERTICAL)
        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
        grid.AddGrowableCol(1, 1)

        self.protocol_choice = wx.Choice(self, choices=["sftp", "ftp", "ftps"])
        self.protocol_choice.SetSelection(0)
        self._add_field(grid, "&Protocol:", self.protocol_choice, "Protocol")

        self.host_text = wx.TextCtrl(self)
        self._add_field(grid, "&Host:", self.host_text, "Host")

        self.port_text = wx.TextCtrl(self, value="22")
        self._add_field(grid, "P&ort:", self.port_text, "Port")

        self.username_text = wx.TextCtrl(self)
        self._add_field(grid, "&Username:", self.username_text, "Username")

        self.password_text = wx.TextCtrl(self, style=wx.TE_PASSWORD)
        self._add_field(grid, "Pass&word:", self.password_text, "Password")

        sizer.Add(grid, 1, wx.ALL | wx.EXPAND, 10)

        btn_sizer = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(btn_sizer, 0, wx.ALL | wx.EXPAND, 10)

        self.SetSizer(sizer)
        self.Fit()
        self.host_text.SetFocus()

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
