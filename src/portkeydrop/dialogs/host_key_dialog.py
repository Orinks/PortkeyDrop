"""Dialog for unknown SSH host keys."""

import wx
import wx.lib.sized_controls as sc


class HostKeyDialog(sc.SizedDialog):
    """Ask user whether to accept an unknown SSH host key."""

    REJECT = 0
    ACCEPT_ONCE = 1
    ACCEPT_PERMANENT = 2

    def __init__(self, parent, hostname: str, key_type: str, fingerprint: str):
        super().__init__(
            parent,
            title="Unknown Host Key",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        pane = self.GetContentsPane()
        pane.SetSizerType("vertical")

        wx.StaticText(
            pane, label=f"The host key for {hostname!r} is not in your known hosts."
        )
        wx.StaticText(pane, label=f"Key type: {key_type}")
        wx.StaticText(pane, label=f"Fingerprint: {fingerprint}")
        wx.StaticText(pane, label="Do you want to connect?")

        btn_pane = sc.SizedPanel(pane)
        btn_pane.SetSizerType("horizontal")

        accept_perm_btn = wx.Button(btn_pane, label="&Accept Permanently")
        accept_once_btn = wx.Button(btn_pane, label="Accept &Once")
        reject_btn = wx.Button(btn_pane, label="&Reject")

        accept_perm_btn.Bind(
            wx.EVT_BUTTON, lambda e: self.EndModal(self.ACCEPT_PERMANENT)
        )
        accept_once_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(self.ACCEPT_ONCE))
        reject_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(self.REJECT))

        self.Fit()
        self.SetMinSize((400, 200))
        reject_btn.SetFocus()
