"""Wizard dialog for importing saved connection profiles."""

from __future__ import annotations

from pathlib import Path

import wx

from portkeydrop.importers import (
    SOURCES,
    WINSCP_REGISTRY_SENTINEL,
    available_sources,
    detect_default_path,
    load_from_source,
)
from portkeydrop.importers.models import ImportedSite


class ImportConnectionsDialog(wx.Dialog):
    """Wizard-style dialog for importing connection profiles."""

    def __init__(self, parent: wx.Window | None) -> None:
        super().__init__(
            parent,
            title="Import Sites",
            size=(680, 480),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )

        self._step = 0
        self._source = SOURCES[0].key
        self._loaded_sites: list[ImportedSite] = []
        self._selected_sites: list[ImportedSite] = []

        self._build_ui()
        self._update_step_ui()

    def _build_ui(self) -> None:
        root = wx.BoxSizer(wx.VERTICAL)

        self.step_title = wx.StaticText(self, label="")
        root.Add(self.step_title, 0, wx.ALL, 8)

        self._available_sources = available_sources()
        self._auto_advance = False
        self.pages = [
            self._build_source_page(),
            self._build_path_page(),
            self._build_preview_page(),
        ]
        for page in self.pages:
            root.Add(page, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 8)

        nav = wx.BoxSizer(wx.HORIZONTAL)
        self.back_btn = wx.Button(self, label="< &Back")
        self.next_btn = wx.Button(self, label="&Next >")
        self.import_btn = wx.Button(self, label="&Import")
        cancel_btn = wx.Button(self, wx.ID_CANCEL)

        nav.Add(self.back_btn, 0, wx.RIGHT, 6)
        nav.Add(self.next_btn, 0, wx.RIGHT, 6)
        nav.Add(self.import_btn, 0, wx.RIGHT, 6)
        nav.AddStretchSpacer(1)
        nav.Add(cancel_btn, 0)
        root.Add(nav, 0, wx.EXPAND | wx.ALL, 8)

        self.back_btn.Bind(wx.EVT_BUTTON, self._on_back)
        self.next_btn.Bind(wx.EVT_BUTTON, self._on_next)
        self.import_btn.Bind(wx.EVT_BUTTON, self._on_import)
        self.source_radio.Bind(wx.EVT_RADIOBOX, self._on_source_change)
        self.autodetect_btn.Bind(wx.EVT_BUTTON, self._on_autodetect)
        self.browse_file_btn.Bind(wx.EVT_BUTTON, self._on_browse_file)
        self.browse_folder_btn.Bind(wx.EVT_BUTTON, self._on_browse_folder)
        self.select_all_btn.Bind(wx.EVT_BUTTON, self._on_select_all)
        self.select_none_btn.Bind(wx.EVT_BUTTON, self._on_select_none)

        self.SetSizer(root)

    def _build_source_page(self) -> wx.Panel:
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        self._available_sources = available_sources()
        choices = [source.label for source in self._available_sources]

        if not choices:
            choices = ["From file..."]

        if (
            len(choices) == 1
            and self._available_sources
            and self._available_sources[0].key != "from_file"
        ):
            # Only one client detected — note it for auto-skip
            self._auto_advance = True
        else:
            self._auto_advance = False

        self.source_radio = wx.RadioBox(
            panel,
            label="Choose source client",
            choices=choices,
            majorDimension=1,
            style=wx.RA_SPECIFY_ROWS,
        )
        sizer.Add(self.source_radio, 0, wx.EXPAND | wx.ALL, 4)

        if not self._available_sources or all(
            s.key == "from_file" for s in self._available_sources
        ):
            note = wx.StaticText(
                panel,
                label="No supported FTP clients detected. You can still import from a file.",
            )
            sizer.Add(note, 0, wx.ALL, 4)

        panel.SetSizer(sizer)
        return panel

    def _build_path_page(self) -> wx.Panel:
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        description = wx.StaticText(
            panel,
            label=(
                "Auto-detect the configuration path, or browse manually. "
                "For Cyberduck you can select either a .duck file or Bookmarks folder."
            ),
        )
        sizer.Add(description, 0, wx.EXPAND | wx.ALL, 4)

        path_lbl = wx.StaticText(panel, label="Configuration &path:")
        sizer.Add(path_lbl, 0, wx.LEFT | wx.RIGHT, 4)
        if hasattr(path_lbl, "SetLabelFor"):
            # Defer binding until after path_text is created (below).
            pass

        row = wx.BoxSizer(wx.HORIZONTAL)
        self.path_text = wx.TextCtrl(panel)
        if hasattr(path_lbl, "SetLabelFor"):
            path_lbl.SetLabelFor(self.path_text)
        row.Add(self.path_text, 1, wx.RIGHT | wx.EXPAND, 6)

        self.autodetect_btn = wx.Button(panel, label="&Auto-Detect")
        self.browse_file_btn = wx.Button(panel, label="Browse &File...")
        self.browse_folder_btn = wx.Button(panel, label="Browse &Folder...")
        row.Add(self.autodetect_btn, 0, wx.RIGHT, 4)
        row.Add(self.browse_file_btn, 0, wx.RIGHT, 4)
        row.Add(self.browse_folder_btn, 0)
        sizer.Add(row, 0, wx.EXPAND | wx.ALL, 4)

        panel.SetSizer(sizer)
        return panel

    def _build_preview_page(self) -> wx.Panel:
        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        preview_note = wx.StaticText(panel, label="Select connections to import")
        sizer.Add(preview_note, 0, wx.ALL, 4)

        self.preview_list = wx.CheckListBox(panel)
        sizer.Add(self.preview_list, 1, wx.EXPAND | wx.ALL, 4)

        actions = wx.BoxSizer(wx.HORIZONTAL)
        self.select_all_btn = wx.Button(panel, label="Select &All")
        self.select_none_btn = wx.Button(panel, label="Select &None")
        actions.Add(self.select_all_btn, 0, wx.RIGHT, 4)
        actions.Add(self.select_none_btn, 0)
        sizer.Add(actions, 0, wx.ALL, 4)

        panel.SetSizer(sizer)
        return panel

    def _selected_source_key(self) -> str:
        """Return currently selected source key from available choices."""
        index = self.source_radio.GetSelection()
        if 0 <= index < len(self._available_sources):
            return self._available_sources[index].key
        return "from_file"

    def _on_source_change(self, event: wx.CommandEvent) -> None:
        self._source = self._selected_source_key()
        self._run_autodetect()

    def _on_autodetect(self, event: wx.CommandEvent) -> None:
        self._run_autodetect()

    def _run_autodetect(self) -> None:
        source = self._selected_source_key()
        default_path = detect_default_path(source)
        if default_path is not None:
            self.path_text.SetValue(str(default_path))

    def _on_browse_file(self, event: wx.CommandEvent) -> None:
        source = self._selected_source_key()
        wildcard = self._file_wildcard_for_source(source)
        with wx.FileDialog(
            self,
            "Select Configuration File",
            wildcard=wildcard,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.path_text.SetValue(dlg.GetPath())

    def _on_browse_folder(self, event: wx.CommandEvent) -> None:
        with wx.DirDialog(self, "Select Configuration Folder", style=wx.DD_DIR_MUST_EXIST) as dlg:
            if dlg.ShowModal() == wx.ID_OK:
                self.path_text.SetValue(dlg.GetPath())

    def _on_select_all(self, event: wx.CommandEvent) -> None:
        for i in range(self.preview_list.GetCount()):
            self.preview_list.Check(i, True)

    def _on_select_none(self, event: wx.CommandEvent) -> None:
        for i in range(self.preview_list.GetCount()):
            self.preview_list.Check(i, False)

    def _on_back(self, event: wx.CommandEvent) -> None:
        if self._step > 0:
            self._step -= 1
            self._update_step_ui()

    def _on_next(self, event: wx.CommandEvent) -> None:
        if self._step == 0:
            self._source = self._available_sources[self.source_radio.GetSelection()].key
            self._step = 1
            self._update_step_ui()
            return

        if self._step == 1:
            if not self._load_preview():
                return
            self._step = 2
            self._update_step_ui()

    def _on_import(self, event: wx.CommandEvent) -> None:
        selected: list[ImportedSite] = []
        for i, site in enumerate(self._loaded_sites):
            if self.preview_list.IsChecked(i):
                selected.append(site)

        if not selected:
            wx.MessageBox(
                "Select at least one connection to import.",
                "Import Sites",
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            return

        self._selected_sites = selected
        self.EndModal(wx.ID_OK)

    def _load_preview(self) -> bool:
        input_path = self.path_text.GetValue().strip()
        use_registry = input_path == WINSCP_REGISTRY_SENTINEL
        path = None if use_registry else (Path(input_path).expanduser() if input_path else None)

        source = self._selected_source_key()
        if source == "from_file" and not path:
            wx.MessageBox(
                "Choose a file or folder for 'From file...' import.",
                "Import Sites",
                wx.OK | wx.ICON_WARNING,
                self,
            )
            return False

        if source in {"filezilla", "cyberduck"} and path is None:
            default_path = detect_default_path(source)
            if default_path is not None:
                path = default_path

        if path and not path.exists():
            wx.MessageBox(
                f"Path does not exist:\n{path}",
                "Import Sites",
                wx.OK | wx.ICON_WARNING,
                self,
            )
            return False

        try:
            self._loaded_sites = load_from_source(source, path)
        except Exception as exc:
            message = f"Failed to parse configuration: {exc}"
            if source == "winscp":
                message += (
                    "\n\nTip: WinSCP imports support INI exports and Windows Registry sessions. "
                    "Passwords protected by WinSCP master password cannot be decrypted."
                )
            wx.MessageBox(
                message,
                "Import Sites",
                wx.OK | wx.ICON_ERROR,
                self,
            )
            return False

        if not self._loaded_sites:
            message = "No connections were found in the selected source."
            if source == "winscp":
                message += (
                    "\n\nTip: Make sure the file contains [Sessions\\...] entries, "
                    "or use Auto-Detect to load sessions from the Windows Registry."
                )
            wx.MessageBox(
                message,
                "Import Sites",
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            return False

        self._populate_preview(self._loaded_sites)
        return True

    def _populate_preview(self, sites: list[ImportedSite]) -> None:
        self.preview_list.Clear()
        for site in sites:
            port = f":{site.port}" if site.port else ""
            username = f" ({site.username})" if site.username else ""
            label = f"{site.name} - {site.protocol}://{site.host}{port}{username}"
            self.preview_list.Append(label)
            self.preview_list.Check(self.preview_list.GetCount() - 1, True)

    def _update_step_ui(self) -> None:
        titles = [
            "Step 1 of 3: Choose source client",
            "Step 2 of 3: Detect or choose configuration path",
            "Step 3 of 3: Select connections to import",
        ]
        self.step_title.SetLabel(titles[self._step])

        for i, page in enumerate(self.pages):
            page.Show(i == self._step)

        self.back_btn.Enable(self._step > 0)
        self.next_btn.Show(self._step < 2)
        self.import_btn.Show(self._step == 2)
        # Set the default button so Enter advances the wizard on the current step.
        if self._step < 2:
            self.next_btn.SetDefault()
        else:
            self.import_btn.SetDefault()
        self.Layout()

        # Move focus to the first meaningful control on each page so screen
        # readers announce the new step without the user having to navigate.
        if self._step == 0:
            self.source_radio.SetFocus()
        elif self._step == 1:
            self.path_text.SetFocus()
        elif self._step == 2:
            self.preview_list.SetFocus()

    def _file_wildcard_for_source(self, source: str) -> str:
        if source == "filezilla":
            return "FileZilla XML (*.xml)|*.xml|All files (*.*)|*.*"
        if source == "winscp":
            return "WinSCP INI (*.ini)|*.ini|All files (*.*)|*.*"
        if source == "cyberduck":
            return "Cyberduck bookmarks (*.duck)|*.duck|All files (*.*)|*.*"
        return "Supported files (*.xml;*.ini;*.duck)|*.xml;*.ini;*.duck|All files (*.*)|*.*"

    @property
    def selected_sites(self) -> list[ImportedSite]:
        return list(self._selected_sites)
