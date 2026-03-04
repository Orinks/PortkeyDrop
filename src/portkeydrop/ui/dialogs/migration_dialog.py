"""Dialog prompting users to migrate configuration files into portable mode."""

from __future__ import annotations

import wx


class MigrationDialog(wx.Dialog):
    """Prompt user to choose which standard-install files to migrate."""

    def __init__(
        self,
        parent: wx.Window | None,
        candidates: list[tuple[str, str]],
    ) -> None:
        super().__init__(
            parent,
            title="Migrate Existing Data",
            size=(420, 260),
            style=wx.DEFAULT_DIALOG_STYLE,
        )
        self._checkboxes: list[tuple[str, wx.CheckBox]] = []

        root = wx.BoxSizer(wx.VERTICAL)
        description = wx.StaticText(
            self,
            label=(
                "Existing Portkey Drop data was found in your standard install. "
                "Select what to copy into this portable copy."
            ),
        )
        root.Add(description, 0, wx.ALL | wx.EXPAND, 10)

        for label, filename in candidates:
            checkbox = wx.CheckBox(self, label=label)
            checkbox.SetValue(True)
            self._checkboxes.append((filename, checkbox))
            root.Add(checkbox, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)

        buttons = wx.StdDialogButtonSizer()
        migrate_button = wx.Button(self, wx.ID_OK, "Migrate selected")
        skip_button = wx.Button(self, wx.ID_CANCEL, "Skip")
        buttons.AddButton(migrate_button)
        buttons.AddButton(skip_button)
        buttons.Realize()
        root.Add(buttons, 0, wx.ALL | wx.ALIGN_RIGHT, 10)

        self.SetSizerAndFit(root)

    def get_selected_filenames(self) -> list[str]:
        """Return selected candidate filenames."""
        return [filename for filename, checkbox in self._checkboxes if checkbox.GetValue()]
