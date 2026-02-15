"""Settings dialog for AccessiTransfer."""

from __future__ import annotations

import wx

from accessitransfer.settings import Settings


class SettingsDialog(wx.Dialog):
    """Dialog for editing application settings."""

    def __init__(self, parent: wx.Window | None, settings: Settings) -> None:
        super().__init__(
            parent,
            title="Settings",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            size=(450, 400),
        )
        self._settings = settings
        self._build_ui()
        self._populate()
        self.SetName("Settings Dialog")

    def _build_ui(self) -> None:
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.notebook = wx.Notebook(self)
        self.notebook.SetName("Settings Categories")

        self._build_transfer_tab()
        self._build_display_tab()
        self._build_connection_tab()
        self._build_speech_tab()

        sizer.Add(self.notebook, 1, wx.EXPAND | wx.ALL, 8)
        btn_sizer = self.CreateStdDialogButtonSizer(wx.OK | wx.CANCEL)
        sizer.Add(btn_sizer, 0, wx.ALL | wx.EXPAND, 8)
        self.SetSizer(sizer)

    def _add_field(self, parent, grid, label_text, ctrl, name=None):
        lbl = wx.StaticText(parent, label=label_text)
        grid.Add(lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        if name:
            ctrl.SetName(name)
        grid.Add(ctrl, 1, wx.EXPAND)
        return ctrl

    def _build_transfer_tab(self) -> None:
        panel = wx.Panel(self.notebook)
        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
        grid.AddGrowableCol(1, 1)

        self.concurrent_spin = wx.SpinCtrl(panel, min=1, max=10)
        self._add_field(
            panel, grid, "&Concurrent transfers:", self.concurrent_spin, "Concurrent transfers"
        )

        self.overwrite_choice = wx.Choice(panel, choices=["ask", "overwrite", "skip", "rename"])
        self._add_field(panel, grid, "&Overwrite mode:", self.overwrite_choice, "Overwrite mode")

        self.resume_check = wx.CheckBox(panel, label="&Resume partial transfers")
        self.resume_check.SetName("Resume partial transfers")
        grid.Add((0, 0))
        grid.Add(self.resume_check)

        self.preserve_ts_check = wx.CheckBox(panel, label="&Preserve timestamps")
        self.preserve_ts_check.SetName("Preserve timestamps")
        grid.Add((0, 0))
        grid.Add(self.preserve_ts_check)

        self.follow_symlinks_check = wx.CheckBox(panel, label="&Follow symlinks")
        self.follow_symlinks_check.SetName("Follow symlinks")
        grid.Add((0, 0))
        grid.Add(self.follow_symlinks_check)

        self.download_dir_text = wx.TextCtrl(panel)
        self._add_field(
            panel, grid, "&Download directory:", self.download_dir_text, "Download directory"
        )

        panel.SetSizer(grid)
        self.notebook.AddPage(panel, "Transfer")

    def _build_display_tab(self) -> None:
        panel = wx.Panel(self.notebook)
        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
        grid.AddGrowableCol(1, 1)

        self.announce_count_check = wx.CheckBox(panel, label="&Announce file count")
        self.announce_count_check.SetName("Announce file count")
        grid.Add((0, 0))
        grid.Add(self.announce_count_check)

        self.progress_interval_spin = wx.SpinCtrl(panel, min=5, max=50)
        self._add_field(
            panel, grid, "&Progress interval (%):", self.progress_interval_spin, "Progress interval"
        )

        self.show_hidden_check = wx.CheckBox(panel, label="Show &hidden files")
        self.show_hidden_check.SetName("Show hidden files")
        grid.Add((0, 0))
        grid.Add(self.show_hidden_check)

        self.sort_by_choice = wx.Choice(panel, choices=["name", "size", "modified", "type"])
        self._add_field(panel, grid, "&Sort by:", self.sort_by_choice, "Sort by")

        self.sort_asc_check = wx.CheckBox(panel, label="Sort &ascending")
        self.sort_asc_check.SetName("Sort ascending")
        grid.Add((0, 0))
        grid.Add(self.sort_asc_check)

        self.date_format_choice = wx.Choice(panel, choices=["relative", "absolute"])
        self._add_field(panel, grid, "&Date format:", self.date_format_choice, "Date format")

        panel.SetSizer(grid)
        self.notebook.AddPage(panel, "Display")

    def _build_connection_tab(self) -> None:
        panel = wx.Panel(self.notebook)
        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
        grid.AddGrowableCol(1, 1)

        self.default_proto_choice = wx.Choice(panel, choices=["sftp", "ftp", "ftps"])
        self._add_field(
            panel, grid, "&Default protocol:", self.default_proto_choice, "Default protocol"
        )

        self.timeout_spin = wx.SpinCtrl(panel, min=5, max=300)
        self._add_field(panel, grid, "&Timeout (seconds):", self.timeout_spin, "Timeout")

        self.keepalive_spin = wx.SpinCtrl(panel, min=0, max=600)
        self._add_field(panel, grid, "&Keepalive (seconds):", self.keepalive_spin, "Keepalive")

        self.retries_spin = wx.SpinCtrl(panel, min=0, max=10)
        self._add_field(panel, grid, "Max &retries:", self.retries_spin, "Max retries")

        self.passive_check = wx.CheckBox(panel, label="&Passive mode (FTP)")
        self.passive_check.SetName("Passive mode")
        grid.Add((0, 0))
        grid.Add(self.passive_check)

        self.verify_keys_choice = wx.Choice(panel, choices=["ask", "always", "never"])
        self._add_field(
            panel, grid, "&Verify host keys:", self.verify_keys_choice, "Verify host keys"
        )

        panel.SetSizer(grid)
        self.notebook.AddPage(panel, "Connection")

    def _build_speech_tab(self) -> None:
        panel = wx.Panel(self.notebook)
        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=8)
        grid.AddGrowableCol(1, 1)

        self.speech_rate_spin = wx.SpinCtrl(panel, min=0, max=100)
        self._add_field(panel, grid, "&Rate:", self.speech_rate_spin, "Speech rate")

        self.speech_volume_spin = wx.SpinCtrl(panel, min=0, max=100)
        self._add_field(panel, grid, "&Volume:", self.speech_volume_spin, "Speech volume")

        self.verbosity_choice = wx.Choice(panel, choices=["minimal", "normal", "verbose"])
        self._add_field(panel, grid, "V&erbosity:", self.verbosity_choice, "Verbosity")

        panel.SetSizer(grid)
        self.notebook.AddPage(panel, "Speech")

    def _populate(self) -> None:
        s = self._settings
        # Transfer
        self.concurrent_spin.SetValue(s.transfer.concurrent_transfers)
        idx = ["ask", "overwrite", "skip", "rename"].index(s.transfer.overwrite_mode)
        self.overwrite_choice.SetSelection(idx)
        self.resume_check.SetValue(s.transfer.resume_partial)
        self.preserve_ts_check.SetValue(s.transfer.preserve_timestamps)
        self.follow_symlinks_check.SetValue(s.transfer.follow_symlinks)
        self.download_dir_text.SetValue(s.transfer.default_download_dir)
        # Display
        self.announce_count_check.SetValue(s.display.announce_file_count)
        self.progress_interval_spin.SetValue(s.display.progress_interval)
        self.show_hidden_check.SetValue(s.display.show_hidden_files)
        idx = ["name", "size", "modified", "type"].index(s.display.sort_by)
        self.sort_by_choice.SetSelection(idx)
        self.sort_asc_check.SetValue(s.display.sort_ascending)
        idx = ["relative", "absolute"].index(s.display.date_format)
        self.date_format_choice.SetSelection(idx)
        # Connection
        idx = ["sftp", "ftp", "ftps"].index(s.connection.protocol)
        self.default_proto_choice.SetSelection(idx)
        self.timeout_spin.SetValue(s.connection.timeout)
        self.keepalive_spin.SetValue(s.connection.keepalive)
        self.retries_spin.SetValue(s.connection.max_retries)
        self.passive_check.SetValue(s.connection.passive_mode)
        idx = ["ask", "always", "never"].index(s.connection.verify_host_keys)
        self.verify_keys_choice.SetSelection(idx)
        # Speech
        self.speech_rate_spin.SetValue(s.speech.rate)
        self.speech_volume_spin.SetValue(s.speech.volume)
        idx = ["minimal", "normal", "verbose"].index(s.speech.verbosity)
        self.verbosity_choice.SetSelection(idx)

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
        s.speech.rate = self.speech_rate_spin.GetValue()
        s.speech.volume = self.speech_volume_spin.GetValue()
        s.speech.verbosity = self.verbosity_choice.GetStringSelection()
        return s
