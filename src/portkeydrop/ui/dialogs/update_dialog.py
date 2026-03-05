"""Update available dialog for Portkey Drop."""

from __future__ import annotations

import wx


class UpdateAvailableDialog(wx.Dialog):
    """Dialog showing update details with release notes."""

    def __init__(
        self,
        parent: wx.Window | None,
        *,
        current_version: str,
        new_version: str,
        channel_label: str,
        release_notes: str,
    ) -> None:
        super().__init__(
            parent,
            title=f"{channel_label} Update Available",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self._build_ui(current_version, new_version, channel_label, release_notes)
        self.SetSize((500, 420))
        self.CenterOnParent()

    def _build_ui(
        self,
        current_version: str,
        new_version: str,
        channel_label: str,
        release_notes: str,
    ) -> None:
        root = wx.BoxSizer(wx.VERTICAL)

        header = wx.StaticText(
            self,
            label=(
                f"A new {channel_label} update is available!\n"
                f"Current: {current_version}  ->  Latest: {new_version}"
            ),
        )
        root.Add(header, 0, wx.ALL | wx.EXPAND, 10)

        notes_label = wx.StaticText(self, label="What's new:")
        root.Add(notes_label, 0, wx.LEFT | wx.RIGHT, 10)

        notes = release_notes.strip() if release_notes else "No release notes available."
        self.release_notes_text = wx.TextCtrl(
            self,
            value=notes,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2 | wx.HSCROLL,
        )
        self.release_notes_text.SetName("Update release notes")
        root.Add(self.release_notes_text, 1, wx.ALL | wx.EXPAND, 10)

        buttons = wx.StdDialogButtonSizer()
        download_btn = wx.Button(self, wx.ID_OK, "&Download Update")
        download_btn.SetDefault()
        cancel_btn = wx.Button(self, wx.ID_CANCEL, "&Cancel")
        buttons.AddButton(download_btn)
        buttons.AddButton(cancel_btn)
        buttons.Realize()
        root.Add(buttons, 0, wx.ALL | wx.EXPAND, 10)

        self.SetSizer(root)
        self.release_notes_text.SetFocus()
        self.release_notes_text.SetInsertionPoint(0)
