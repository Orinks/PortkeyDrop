"""Settings dialog for Portkey Drop."""

from __future__ import annotations

from typing import Callable

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
        self._spin_controls: list[tuple[wx.SpinCtrl, str]] = []

        self._build_ui()
        self._populate()
        self.SetName("Settings Dialog")

        # Re-apply accessible names on spin inner editors after _populate()
        # may have reset them via SetValue().
        self._apply_spin_accessible_names()
        wx.CallAfter(self.notebook.SetFocus)

    # -- UI construction -----------------------------------------------

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
        sizer = wx.BoxSizer(wx.VERTICAL)
        panel.SetSizer(sizer)
        return panel, sizer

    # -- Layout helpers ------------------------------------------------
    #
    # CRITICAL: The StaticText label HWND must be created *before* the
    # control HWND.  NVDA resolves labels by walking backward through
    # sibling HWNDs; if the control is created first its HWND precedes
    # the label and NVDA associates the wrong label (or none at all).
    #
    # To guarantee correct order the helpers below accept a *factory*
    # callable that creates the control — the helper creates the label
    # first, then calls the factory.

    def _add_labeled_row(
        self,
        panel: wx.Panel,
        parent_sizer: wx.BoxSizer,
        *,
        label: str,
        make_control: Callable[[wx.Panel], wx.Control],
        control_name: str,
    ) -> wx.Control:
        """Create a label then a control, in that HWND order, and lay them out."""
        row = wx.BoxSizer(wx.HORIZONTAL)

        # Label HWND created FIRST
        row_label = wx.StaticText(panel, label=label)
        row_label.SetMinSize((220, -1))

        # Control HWND created SECOND — correct Z-order for NVDA
        control = make_control(panel)

        if hasattr(row_label, "SetLabelFor"):
            row_label.SetLabelFor(control)

        control.SetName(control_name)
        row.Add(row_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        row.Add(control, 1, wx.EXPAND)

        parent_sizer.Add(row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
        return control

    def _add_spin_row(
        self,
        panel: wx.Panel,
        parent_sizer: wx.BoxSizer,
        *,
        label: str,
        control_name: str,
        min_val: int,
        max_val: int,
    ) -> wx.SpinCtrl:
        """Create a label then a spin control with full accessible naming."""
        row = wx.BoxSizer(wx.HORIZONTAL)

        # Label HWND created FIRST
        row_label = wx.StaticText(panel, label=label)
        row_label.SetMinSize((220, -1))

        # SpinCtrl HWND created SECOND — correct Z-order for NVDA
        spin = wx.SpinCtrl(panel, min=min_val, max=max_val)

        if hasattr(row_label, "SetLabelFor"):
            row_label.SetLabelFor(spin)

        self._register_spin(spin, control_name)

        row.Add(row_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 10)
        row.Add(spin, 1, wx.EXPAND)

        parent_sizer.Add(row, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.TOP, 10)
        return spin

    def _add_checkbox_row(
        self,
        parent_sizer: wx.BoxSizer,
        checkbox: wx.CheckBox,
        *,
        name: str,
    ) -> wx.CheckBox:
        """Add a standalone checkbox with an accessible name."""
        checkbox.SetName(name)
        parent_sizer.Add(checkbox, 0, wx.LEFT | wx.RIGHT | wx.TOP, 10)
        return checkbox

    # -- Spin control accessibility ------------------------------------

    def _register_spin(self, spin: wx.SpinCtrl, name: str) -> wx.SpinCtrl:
        """Register a spin control for accessible name management."""
        self._spin_controls.append((spin, name))
        self._set_spin_accessible_name(spin, name)
        return spin

    def _set_spin_accessible_name(self, spin: wx.SpinCtrl, name: str) -> None:
        """Set accessible name on spin and its inner text editor."""
        spin.SetName(name)
        spin.SetToolTip(name)

        text_child = self._find_text_child(spin)
        if text_child is not None:
            if hasattr(text_child, "SetName"):
                text_child.SetName(f"{name} value")
            if hasattr(text_child, "SetToolTip"):
                text_child.SetToolTip(name)

    @staticmethod
    def _find_text_child(control: wx.Window) -> wx.Window | None:
        """Find the inner wxTextCtrl child of a composite control."""
        for child in control.GetChildren():
            class_name = getattr(child, "GetClassName", lambda: "")()
            if class_name == "wxTextCtrl":
                return child
            nested = SettingsDialog._find_text_child(child)
            if nested is not None:
                return nested
        return None

    def _apply_spin_accessible_names(self) -> None:
        """Re-apply accessible names to all registered spin controls."""
        for spin, name in self._spin_controls:
            self._set_spin_accessible_name(spin, name)

    # -- Tab builders --------------------------------------------------

    def _build_transfer_tab(self) -> None:
        panel, sizer = self._new_tab_panel()

        self.concurrent_spin = self._add_spin_row(
            panel,
            sizer,
            label="&Concurrent transfers:",
            control_name="Concurrent transfers count",
            min_val=1,
            max_val=10,
        )

        self.overwrite_choice = self._add_labeled_row(
            panel,
            sizer,
            label="&Overwrite mode:",
            make_control=lambda p: wx.Choice(
                p,
                choices=["ask", "overwrite", "skip", "rename"],
            ),
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

        self.download_dir_text = self._add_labeled_row(
            panel,
            sizer,
            label="&Download directory:",
            make_control=lambda p: wx.TextCtrl(p),
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

        self.progress_interval_spin = self._add_spin_row(
            panel,
            sizer,
            label="&Progress interval (%):",
            control_name="Progress interval",
            min_val=5,
            max_val=50,
        )

        self.show_hidden_check = self._add_checkbox_row(
            sizer,
            wx.CheckBox(panel, label="Show &hidden files"),
            name="Show hidden files",
        )

        self.sort_by_choice = self._add_labeled_row(
            panel,
            sizer,
            label="&Sort by:",
            make_control=lambda p: wx.Choice(
                p,
                choices=["name", "size", "modified", "type"],
            ),
            control_name="Sort by",
        )

        self.sort_asc_check = self._add_checkbox_row(
            sizer,
            wx.CheckBox(panel, label="Sort &ascending"),
            name="Sort ascending",
        )

        self.date_format_choice = self._add_labeled_row(
            panel,
            sizer,
            label="&Date format:",
            make_control=lambda p: wx.Choice(p, choices=["relative", "absolute"]),
            control_name="Date format",
        )

        sizer.AddStretchSpacer(1)
        self.notebook.AddPage(panel, "Display")

    def _build_connection_tab(self) -> None:
        panel, sizer = self._new_tab_panel()

        self.default_proto_choice = self._add_labeled_row(
            panel,
            sizer,
            label="&Default protocol:",
            make_control=lambda p: wx.Choice(p, choices=["sftp", "ftp", "ftps"]),
            control_name="Default protocol",
        )

        self.timeout_spin = self._add_spin_row(
            panel,
            sizer,
            label="&Timeout (seconds):",
            control_name="Connection timeout",
            min_val=5,
            max_val=300,
        )

        self.keepalive_spin = self._add_spin_row(
            panel,
            sizer,
            label="&Keepalive (seconds):",
            control_name="Keepalive interval",
            min_val=0,
            max_val=600,
        )

        self.retries_spin = self._add_spin_row(
            panel,
            sizer,
            label="Max &retries:",
            control_name="Maximum retries",
            min_val=0,
            max_val=10,
        )

        self.passive_check = self._add_checkbox_row(
            sizer,
            wx.CheckBox(panel, label="&Passive mode (FTP)"),
            name="Passive mode",
        )

        self.verify_keys_choice = self._add_labeled_row(
            panel,
            sizer,
            label="&Verify host keys:",
            make_control=lambda p: wx.Choice(p, choices=["ask", "always", "never"]),
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

        self.speech_rate_spin = self._add_spin_row(
            panel,
            sizer,
            label="&Rate:",
            control_name="Speech rate",
            min_val=0,
            max_val=100,
        )

        self.speech_volume_spin = self._add_spin_row(
            panel,
            sizer,
            label="&Volume:",
            control_name="Speech volume",
            min_val=0,
            max_val=100,
        )

        self.verbosity_choice = self._add_labeled_row(
            panel,
            sizer,
            label="V&erbosity:",
            make_control=lambda p: wx.Choice(
                p,
                choices=["minimal", "normal", "verbose"],
            ),
            control_name="Speech verbosity",
        )

        sizer.AddStretchSpacer(1)
        self.notebook.AddPage(panel, "Speech")

    # -- Data binding --------------------------------------------------

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
        self.remember_local_folder_check.SetValue(s.app.remember_last_local_folder_on_startup)
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
        s.app.remember_last_local_folder_on_startup = self.remember_local_folder_check.GetValue()

        s.speech.rate = self.speech_rate_spin.GetValue()
        s.speech.volume = self.speech_volume_spin.GetValue()
        s.speech.verbosity = self.verbosity_choice.GetStringSelection()
        return s
