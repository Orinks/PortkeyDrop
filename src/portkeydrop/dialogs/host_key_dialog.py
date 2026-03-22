"""Dialog for unknown SSH host keys."""

from __future__ import annotations

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

        wx.StaticText(pane, label="The server identity could not be verified.")
        security_text = f"Host: {hostname}\nKey type: {key_type}\nFingerprint: {fingerprint}"
        self.security_details = wx.TextCtrl(
            pane,
            value=security_text,
            style=wx.TE_MULTILINE | wx.TE_READONLY,
            size=(450, 90),
        )
        wx.StaticText(pane, label="Do you want to connect?")

        btn_pane = sc.SizedPanel(pane)
        btn_pane.SetSizerType("horizontal")

        accept_perm_btn = wx.Button(btn_pane, label="&Accept Permanently")
        accept_once_btn = wx.Button(btn_pane, label="Accept &Once")
        reject_btn = wx.Button(btn_pane, id=wx.ID_NO, label="&Reject")
        # Reject is the safest default: Enter key triggers rejection without
        # requiring the user to navigate to the button.
        reject_btn.SetDefault()

        accept_perm_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(self.ACCEPT_PERMANENT))
        accept_once_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(self.ACCEPT_ONCE))
        reject_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(self.REJECT))
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)

        self.Fit()
        self.SetMinSize((400, 200))
        # Focus the reject button so screen readers immediately announce the
        # security decision required, rather than landing on read-only detail text.
        reject_btn.SetFocus()

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.EndModal(self.REJECT)
            return
        event.Skip()
