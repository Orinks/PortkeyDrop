"""Settings dialog for Portkey Drop."""

from __future__ import annotations

import wx

from portkeydrop.settings import Settings


class SettingsDialog(wx.Dialog):
    """Dialog for editing application settings."""

    def __init__(self, parent: wx.Window | None, settings: Settings) -> None:
        super().__init__(
            parent,
            title="Settings",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            size=(560, 460),
        )
        self._settings = settings
        self._spin_controls: list[wx.SpinCtrl] = []

        self._build_ui()
        self._populate()
        self.SetName("Settings Dialog")

        self.Bind(wx.EVT_SHOW, self._on_show)
        self.Bind(wx.EVT_WINDOW_CREATE, self._on_window_create)

    def _build_ui(self) -> None:
        root = wx.BoxSizer(wx.VERTICAL)

        self.notebook = wx.Notebook(self)
        self.notebook.SetName("Settings categories")

        self._build_transfer_tab()
        self._build_display_tab()
        self._build_connection_tab()
        self._build_speech_tab()

        root.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 8)

        buttons = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        root.Add(buttons, 0, wx.ALL | wx.EXPAND, 8)

        self.SetSizer(root)

    def _new_tab_panel(self) -> tuple[wx.Panel, wx.BoxSizer]:
        panel = wx.Panel(self.notebook)
        panel_sizer = wx.BoxSizer(wx.VERTICAL)
        panel.SetSizer(panel_sizer)
        return panel, panel_sizer

    def _add_labeled_row(
        self,
        panel: wx.Panel,
        parent_sizer: wx.BoxSizer,
        *,
        label: str,
        control: wx.Control,
        control_name: str,
    ) -> wx.Control:
        row = wx.BoxSizer(wx.HORIZONTAL)

        row_label = wx.StaticText(panel, label=label)
        row_label.SetName(control_name)
        row_label.SetMinSize((240, -1))
        row_label.Wrap(-1)

        if hasattr(row_label, "SetLabelFor"):
            row_label.SetLabelFor(control)

        control.SetName(control_name)
        row.Add(row_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        row.Add(control, 1, wx.ALIGN_CENTER_VERTICAL | wx.EXPAND)

        parent_sizer.Add(row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
        return control

    def _add_checkbox_row(
        self,
        parent_sizer: wx.BoxSizer,
        checkbox: wx.CheckBox,
        *,
        name: str,
    ) -> wx.CheckBox:
        checkbox.SetName(name)
        parent_sizer.Add(checkbox, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        return checkbox

    def _register_spin(self, spin: wx.SpinCtrl, name: str) -> wx.SpinCtrl:
        self._spin_controls.append(spin)
        self._set_spin_context(spin, name)
        return spin

    def _set_spin_context(self, spin: wx.SpinCtrl, name: str) -> None:
        spin.SetName(name)
        spin.SetToolTip(name)

        text_child = self._find_text_child(spin)
        if text_child is not None and hasattr(text_child, "SetName"):
            text_child.SetName(f"{name} value")

    def _find_text_child(self, control: wx.Window) -> wx.Window | None:
        for child in control.GetChildren():
            class_name = getattr(child, "GetClassName", lambda: "")()
            if class_name == "wxTextCtrl":
                return child

            nested = self._find_text_child(child)
            if nested is not None:
                return nested

        return None

    def _refresh_spin_contexts(self) -> None:
        for spin in self._spin_controls:
            self._set_spin_context(spin, spin.GetName())

    def _on_window_create(self, event: wx.WindowCreateEvent) -> None:
        self._refresh_spin_contexts()
        event.Skip()

    def _on_show(self, event: wx.ShowEvent) -> None:
        if event.IsShown():
            self._refresh_spin_contexts()
            wx.CallAfter(self.notebook.SetFocus)
        event.Skip()

    def _build_transfer_tab(self) -> None:
        panel, sizer = self._new_tab_panel()

        self.concurrent_spin = self._register_spin(wx.SpinCtrl(panel, min=1, max=10), "Concurrent transfers")
        self._add_labeled_row(
            panel,
            sizer,
            label="&Concurrent transfers:",
            control=self.concurrent_spin,
            control_name="Concurrent transfers",
        )

        self.overwrite_choice = wx.Choice(panel, choices=["ask", "overwrite", "skip", "rename"])
        self._add_labeled_row(
            panel,
            sizer,
            label="&Overwrite mode:",
            control=self.overwrite_choice,
            control_name="Overwrite mode",
        )

        self.resume_check = self._add_checkbox_row(
            sizer,
            wx.CheckBox(panel, label="&Resume partial transfers"),
            name="Resume partial transfers",
        )

        self.preserve_ts_check = self._add_checkbox_row(
            sizer,
            wx.CheckBox(panel, label="&Preserve timestamps"),
            name="Preserve timestamps",
        )

        self.follow_symlinks_check = self._add_checkbox_row(
            sizer,
            wx.CheckBox(panel, label="&Follow symlinks"),
            name="Follow symlinks",
        )

        self.download_dir_text = wx.TextCtrl(panel)
        self._add_labeled_row(
            panel,
            sizer,
            label="&Download directory:",
            control=self.download_dir_text,
            control_name="Download directory",
        )

        sizer.AddStretchSpacer(1)
        self.notebook.AddPage(panel, "Transfer")

    def _build_display_tab(self) -> None:
        panel, sizer = self._new_tab_panel()

        self.announce_count_check = self._add_checkbox_row(
            sizer,
            wx.CheckBox(panel, label="&Announce file count"),
            name="Announce file count",
        )

        self.progress_interval_spin = self._register_spin(
            wx.SpinCtrl(panel, min=5, max=50), "Progress interval"
        )
        self._add_labeled_row(
            panel,
            sizer,
            label="&Progress interval (%):",
            control=self.progress_interval_spin,
            control_name="Progress interval",
        )

        self.show_hidden_check = self._add_checkbox_row(
            sizer,
            wx.CheckBox(panel, label="Show &hidden files"),
            name="Show hidden files",
        )

        self.sort_by_choice = wx.Choice(panel, choices=["name", "size", "modified", "type"])
        self._add_labeled_row(
            panel,
            sizer,
            label="&Sort by:",
            control=self.sort_by_choice,
            control_name="Sort by",
        )

        self.sort_asc_check = self._add_checkbox_row(
            sizer,
            wx.CheckBox(panel, label="Sort &ascending"),
            name="Sort ascending",
        )

        self.date_format_choice = wx.Choice(panel, choices=["relative", "absolute"])
        self._add_labeled_row(
            panel,
            sizer,
            label="&Date format:",
            control=self.date_format_choice,
            control_name="Date format",
        )

        sizer.AddStretchSpacer(1)
        self.notebook.AddPage(panel, "Display")

    def _build_connection_tab(self) -> None:
        panel, sizer = self._new_tab_panel()

        self.default_proto_choice = wx.Choice(panel, choices=["sftp", "ftp", "ftps"])
        self._add_labeled_row(
            panel,
            sizer,
            label="&Default protocol:",
            control=self.default_proto_choice,
            control_name="Default protocol",
        )

        self.timeout_spin = self._register_spin(wx.SpinCtrl(panel, min=5, max=300), "Connection timeout")
        self._add_labeled_row(
            panel,
            sizer,
            label="&Timeout (seconds):",
            control=self.timeout_spin,
            control_name="Connection timeout",
        )

        self.keepalive_spin = self._register_spin(wx.SpinCtrl(panel, min=0, max=600), "Keepalive interval")
        self._add_labeled_row(
            panel,
            sizer,
            label="&Keepalive (seconds):",
            control=self.keepalive_spin,
            control_name="Keepalive interval",
        )

        self.retries_spin = self._register_spin(wx.SpinCtrl(panel, min=0, max=10), "Maximum retries")
        self._add_labeled_row(
            panel,
            sizer,
            label="Max &retries:",
            control=self.retries_spin,
            control_name="Maximum retries",
        )

        self.passive_check = self._add_checkbox_row(
            sizer,
            wx.CheckBox(panel, label="&Passive mode (FTP)"),
            name="Passive mode",
        )

        self.verify_keys_choice = wx.Choice(panel, choices=["ask", "always", "never"])
        self._add_labeled_row(
            panel,
            sizer,
            label="&Verify host keys:",
            control=self.verify_keys_choice,
            control_name="Verify host keys",
        )

        self.remember_local_folder_check = self._add_checkbox_row(
            sizer,
            wx.CheckBox(panel, label="&Remember last local folder on startup"),
            name="Remember last local folder on startup",
        )

        sizer.AddStretchSpacer(1)
        self.notebook.AddPage(panel, "Connection")

    def _build_speech_tab(self) -> None:
        panel, sizer = self._new_tab_panel()

        self.speech_rate_spin = self._register_spin(wx.SpinCtrl(panel, min=0, max=100), "Speech rate")
        self._add_labeled_row(
            panel,
            sizer,
            label="&Rate:",
            control=self.speech_rate_spin,
            control_name="Speech rate",
        )

        self.speech_volume_spin = self._register_spin(wx.SpinCtrl(panel, min=0, max=100), "Speech volume")
        self._add_labeled_row(
            panel,
            sizer,
            label="&Volume:",
            control=self.speech_volume_spin,
            control_name="Speech volume",
        )

        self.verbosity_choice = wx.Choice(panel, choices=["minimal", "normal", "verbose"])
        self._add_labeled_row(
            panel,
            sizer,
            label="V&erbosity:",
            control=self.verbosity_choice,
            control_name="Speech verbosity",
        )

        sizer.AddStretchSpacer(1)
        self.notebook.AddPage(panel, "Speech")

    def _populate(self) -> None:
        s = self._settings

        self.concurrent_spin.SetValue(s.transfer.concurrent_transfers)
        self.overwrite_choice.SetSelection(["ask", "overwrite", "skip", "rename"].index(s.transfer.overwrite_mode))
        self.resume_check.SetValue(s.transfer.resume_partial)
        self.preserve_ts_check.SetValue(s.transfer.preserve_timestamps)
        self.follow_symlinks_check.SetValue(s.transfer.follow_symlinks)
        self.download_dir_text.SetValue(s.transfer.default_download_dir)

        self.announce_count_check.SetValue(s.display.announce_file_count)
        self.progress_interval_spin.SetValue(s.display.progress_interval)
        self.show_hidden_check.SetValue(s.display.show_hidden_files)
        self.sort_by_choice.SetSelection(["name", "size", "modified", "type"].index(s.display.sort_by))
        self.sort_asc_check.SetValue(s.display.sort_ascending)
        self.date_format_choice.SetSelection(["relative", "absolute"].index(s.display.date_format))

        self.default_proto_choice.SetSelection(["sftp", "ftp", "ftps"].index(s.connection.protocol))
        self.timeout_spin.SetValue(s.connection.timeout)
        self.keepalive_spin.SetValue(s.connection.keepalive)
        self.retries_spin.SetValue(s.connection.max_retries)
        self.passive_check.SetValue(s.connection.passive_mode)
        self.verify_keys_choice.SetSelection(["ask", "always", "never"].index(s.connection.verify_host_keys))
        self.remember_local_folder_check.SetValue(s.app.remember_last_local_folder_on_startup)

        self.speech_rate_spin.SetValue(s.speech.rate)
        self.speech_volume_spin.SetValue(s.speech.volume)
        self.verbosity_choice.SetSelection(["minimal", "normal", "verbose"].index(s.speech.verbosity))

    def get_settings(self) -> Settings:
        """Return updated Settings from the dialog fields."""
        s = self._settings
        s.transfer.concurrent_transfers = self.concurrent_spin.GetValue()
        s.transfer.overwrite_mode = self.overwrite_choice.GetStringSelection()
        s.transfer.resume_partial = self.resume_check.GetValue()
        s.transfer.preserve_timestamps = self.preserve_ts_check.GetValue()
        s.transfer.follow_symlinks = self.follow_symlinks_check.GetValue()
        s.transfer.default_download_dir = self.download_dir_text.GetValue()

        s.display.announce_file_count = self.announce_count_check.GetValue()
        s.display.progress_interval = self.progress_interval_spin.GetValue()
        s.display.show_hidden_files = self.show_hidden_check.GetValue()
        s.display.sort_by = self.sort_by_choice.GetStringSelection()
        s.display.sort_ascending = self.sort_asc_check.GetValue()
        s.display.date_format = self.date_format_choice.GetStringSelection()

        s.connection.protocol = self.default_proto_choice.GetStringSelection()
        s.connection.timeout = self.timeout_spin.GetValue()
        s.connection.keepalive = self.keepalive_spin.GetValue()
        s.connection.max_retries = self.retries_spin.GetValue()
        s.connection.passive_mode = self.passive_check.GetValue()
        s.connection.verify_host_keys = self.verify_keys_choice.GetStringSelection()
        s.app.remember_last_local_folder_on_startup = self.remember_local_folder_check.GetValue()

        s.speech.rate = self.speech_rate_spin.GetValue()
        s.speech.volume = self.speech_volume_spin.GetValue()
        s.speech.verbosity = self.verbosity_choice.GetStringSelection()
        return s
