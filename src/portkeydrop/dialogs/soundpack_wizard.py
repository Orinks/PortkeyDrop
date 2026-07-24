"""wxPython sound pack creation wizard."""

from __future__ import annotations

import contextlib
import json
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import wx

from portkeydrop.sound_events import FRIENDLY_SOUND_EVENT_CHOICES
from portkeydrop.soundpacks import AUDIO_WILDCARD, play_sound_file, slugify_pack_name


@dataclass
class WizardState:
    """State container for the wizard."""

    pack_name: str = ""
    author: str = ""
    description: str = ""
    selected_event_keys: list[str] = field(default_factory=list)
    sound_mappings: dict[str, str] = field(default_factory=dict)


class SoundPackWizardDialog(wx.Dialog):
    """Wizard dialog for creating a new sound pack."""

    def __init__(self, parent: wx.Window, soundpacks_dir: Path) -> None:
        super().__init__(
            parent,
            title="Create Sound Pack",
            size=(650, 550),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.soundpacks_dir = soundpacks_dir
        self.current_step = 1
        self.total_steps = 4
        self.state = WizardState()
        self.created_pack_id: str | None = None
        self.staging_dir = Path(tempfile.mkdtemp(prefix="pkd_soundpack_wizard_"))

        self._build_shell()
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self._render_step()
        self.Centre()

    def _build_shell(self) -> None:
        self.panel = wx.Panel(self)
        main_sizer = wx.BoxSizer(wx.VERTICAL)

        self.header_label = wx.StaticText(self.panel, label="")
        main_sizer.Add(self.header_label, 0, wx.ALL, 10)

        self.content_panel = wx.Panel(self.panel)
        self.content_sizer = wx.BoxSizer(wx.VERTICAL)
        self.content_panel.SetSizer(self.content_sizer)
        main_sizer.Add(self.content_panel, 1, wx.EXPAND | wx.LEFT | wx.RIGHT, 10)

        nav_sizer = wx.BoxSizer(wx.HORIZONTAL)
        nav_sizer.AddStretchSpacer()
        self.prev_btn = wx.Button(self.panel, label="< &Previous")
        self.prev_btn.Bind(wx.EVT_BUTTON, self._go_previous)
        nav_sizer.Add(self.prev_btn, 0, wx.RIGHT, 5)
        self.next_btn = wx.Button(self.panel, label="&Next >")
        self.next_btn.Bind(wx.EVT_BUTTON, self._go_next)
        nav_sizer.Add(self.next_btn, 0, wx.RIGHT, 5)
        self.cancel_btn = wx.Button(self.panel, wx.ID_CANCEL, label="Cancel")
        self.cancel_btn.Bind(wx.EVT_BUTTON, self._on_cancel)
        nav_sizer.Add(self.cancel_btn, 0)

        main_sizer.Add(nav_sizer, 0, wx.EXPAND | wx.ALL, 10)
        self.panel.SetSizer(main_sizer)

    def _render_step(self) -> None:
        titles = {
            1: "Pack Details",
            2: "Select Events",
            3: "Assign Sounds",
            4: "Preview and Finalize",
        }
        header = f"Step {self.current_step} of {self.total_steps}: {titles[self.current_step]}"
        self.header_label.SetLabel(header)
        self.prev_btn.Enable(self.current_step > 1)
        self.next_btn.SetLabel(
            "&Create Pack" if self.current_step == self.total_steps else "&Next >"
        )
        self.content_sizer.Clear(True)
        self._step_focus_target: wx.Window | None = None
        builders = {
            1: self._build_step1,
            2: self._build_step2,
            3: self._build_step3,
            4: self._build_step4,
        }
        builders[self.current_step]()
        self.content_panel.Layout()
        self.panel.Layout()
        # Move focus into the new step's content and speak the step header;
        # otherwise the change is silent and focus stays on the Next button.
        target = self._step_focus_target or self.next_btn
        wx.CallAfter(target.SetFocus)
        wx.CallAfter(self._announce, header)

    def _announce(self, message: str) -> None:
        """Announce via the main frame's announcer, if reachable."""
        parent = self.GetParent()
        while parent is not None:
            announce = getattr(parent, "_announce", None)
            if callable(announce):
                announce(message)
                return
            parent = parent.GetParent() if hasattr(parent, "GetParent") else None

    def _bind_scroll_into_view(self, scroll: wx.ScrolledWindow) -> None:
        """Keep the focused child visible; wx does not auto-scroll on focus."""

        def on_child_focus(event: wx.ChildFocusEvent) -> None:
            window = event.GetWindow() if hasattr(event, "GetWindow") else None
            if window is not None:
                scroll.ScrollChildIntoView(window)
            event.Skip()

        scroll.Bind(wx.EVT_CHILD_FOCUS, on_child_focus)

    def _build_step1(self) -> None:
        self.content_sizer.Add(
            wx.StaticText(self.content_panel, label="Pack name:"), 0, wx.BOTTOM, 3
        )
        self.name_input = wx.TextCtrl(self.content_panel, value=self.state.pack_name)
        self.name_input.SetName("Sound pack name")
        self.content_sizer.Add(self.name_input, 0, wx.EXPAND | wx.BOTTOM, 10)

        self.content_sizer.Add(wx.StaticText(self.content_panel, label="Author:"), 0, wx.BOTTOM, 3)
        self.author_input = wx.TextCtrl(self.content_panel, value=self.state.author)
        self.author_input.SetName("Sound pack author")
        self.content_sizer.Add(self.author_input, 0, wx.EXPAND | wx.BOTTOM, 10)

        self.content_sizer.Add(
            wx.StaticText(self.content_panel, label="Description:"), 0, wx.BOTTOM, 3
        )
        self.desc_input = wx.TextCtrl(
            self.content_panel,
            value=self.state.description,
            style=wx.TE_MULTILINE,
            size=(-1, 100),
        )
        self.desc_input.SetName("Sound pack description")
        self.content_sizer.Add(self.desc_input, 1, wx.EXPAND | wx.BOTTOM, 10)
        self._step_focus_target = self.name_input

    def _build_step2(self) -> None:
        self.content_sizer.Add(
            wx.StaticText(self.content_panel, label="Choose the events you want sounds for:"),
            0,
            wx.BOTTOM,
            10,
        )
        scroll = wx.ScrolledWindow(self.content_panel, size=(-1, 300))
        scroll_sizer = wx.BoxSizer(wx.VERTICAL)
        self.event_checks: list[tuple[str, wx.CheckBox]] = []
        for display_name, event_key in FRIENDLY_SOUND_EVENT_CHOICES:
            checkbox = wx.CheckBox(scroll, label=display_name)
            checkbox.SetName(f"{display_name} sound event")
            checkbox.SetValue(event_key in self.state.selected_event_keys)
            scroll_sizer.Add(checkbox, 0, wx.BOTTOM, 5)
            self.event_checks.append((event_key, checkbox))
        scroll.SetSizer(scroll_sizer)
        scroll.SetScrollRate(5, 5)
        self._bind_scroll_into_view(scroll)
        self.content_sizer.Add(scroll, 1, wx.EXPAND | wx.BOTTOM, 10)
        if self.event_checks:
            self._step_focus_target = self.event_checks[0][1]

        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        common_btn = wx.Button(self.content_panel, label="Select Co&mmon")
        common_btn.Bind(wx.EVT_BUTTON, self._select_common_events)
        button_sizer.Add(common_btn, 0, wx.RIGHT, 5)
        clear_btn = wx.Button(self.content_panel, label="Clear &All")
        clear_btn.Bind(wx.EVT_BUTTON, self._clear_all_events)
        button_sizer.Add(clear_btn, 0)
        self.content_sizer.Add(button_sizer, 0)

    def _select_common_events(self, event) -> None:
        common = {
            "transfer_queued",
            "transfer_started",
            "transfer_complete",
            "transfer_failed",
            "connect_success",
            "connect_failed",
            "success",
            "error",
        }
        for key, checkbox in self.event_checks:
            checkbox.SetValue(key in common)

    def _clear_all_events(self, event) -> None:
        for _key, checkbox in self.event_checks:
            checkbox.SetValue(False)

    def _build_step3(self) -> None:
        self.content_sizer.Add(
            wx.StaticText(self.content_panel, label="Assign a sound file to each selected event."),
            0,
            wx.BOTTOM,
            10,
        )
        scroll = wx.ScrolledWindow(self.content_panel, size=(-1, 350))
        grid = wx.FlexGridSizer(cols=3, hgap=5, vgap=5)
        grid.AddGrowableCol(1, 1)
        self.mapping_controls: list[tuple[str, wx.TextCtrl]] = []
        for key in self.state.selected_event_keys:
            friendly = self._friendly_name(key)
            grid.Add(wx.StaticText(scroll, label=f"{friendly}:"), 0, wx.ALIGN_CENTER_VERTICAL)
            file_ctrl = wx.TextCtrl(scroll, style=wx.TE_READONLY)
            file_ctrl.SetName(f"{friendly} sound file")
            existing = self.state.sound_mappings.get(key)
            if existing:
                file_ctrl.SetValue(Path(existing).name)
            grid.Add(file_ctrl, 1, wx.EXPAND)
            choose_btn = wx.Button(scroll, label="Ch&oose...")
            choose_btn.Bind(
                wx.EVT_BUTTON,
                lambda evt, event_key=key, ctrl=file_ctrl: self._choose_sound_file(event_key, ctrl),
            )
            grid.Add(choose_btn, 0)
            if self._step_focus_target is None:
                self._step_focus_target = choose_btn
            self.mapping_controls.append((key, file_ctrl))
        scroll.SetSizer(grid)
        scroll.SetScrollRate(5, 5)
        self._bind_scroll_into_view(scroll)
        self.content_sizer.Add(scroll, 1, wx.EXPAND)

    def _choose_sound_file(self, key: str, file_ctrl: wx.TextCtrl) -> None:
        with wx.FileDialog(
            self,
            f"Choose sound for {self._friendly_name(key)}",
            wildcard=AUDIO_WILDCARD,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            src = Path(dialog.GetPath())
            dest = self.staging_dir / src.name
            if src.resolve() != dest.resolve():
                shutil.copy2(src, dest)
            self.state.sound_mappings[key] = str(dest)
            file_ctrl.SetValue(dest.name)

    def _build_step4(self) -> None:
        assigned = len(
            [key for key in self.state.selected_event_keys if key in self.state.sound_mappings]
        )
        self.content_sizer.Add(
            wx.StaticText(
                self.content_panel,
                label=f"Sounds assigned: {assigned} of {len(self.state.selected_event_keys)}",
            ),
            0,
            wx.BOTTOM,
            10,
        )
        scroll = wx.ScrolledWindow(self.content_panel, size=(-1, 300))
        grid = wx.FlexGridSizer(cols=3, hgap=5, vgap=5)
        grid.AddGrowableCol(1, 1)
        for key in self.state.selected_event_keys:
            grid.Add(
                wx.StaticText(scroll, label=f"{self._friendly_name(key)}:"),
                0,
                wx.ALIGN_CENTER_VERTICAL,
            )
            file_name = (
                Path(self.state.sound_mappings[key]).name
                if key in self.state.sound_mappings
                else "(none)"
            )
            grid.Add(wx.StaticText(scroll, label=file_name), 1, wx.EXPAND)
            preview_btn = wx.Button(scroll, label="Pre&view")
            preview_btn.Enable(key in self.state.sound_mappings)
            preview_btn.Bind(
                wx.EVT_BUTTON, lambda evt, event_key=key: self._preview_sound(event_key)
            )
            grid.Add(preview_btn, 0)
            if self._step_focus_target is None:
                self._step_focus_target = preview_btn
        scroll.SetSizer(grid)
        scroll.SetScrollRate(5, 5)
        self._bind_scroll_into_view(scroll)
        self.content_sizer.Add(scroll, 1, wx.EXPAND)

    def _preview_sound(self, key: str) -> None:
        src = self.state.sound_mappings.get(key)
        if src:
            play_sound_file(Path(src))

    def _validate_current_step(self) -> bool:
        if self.current_step == 1:
            self.state.pack_name = self.name_input.GetValue().strip()
            self.state.author = self.author_input.GetValue().strip()
            self.state.description = self.desc_input.GetValue().strip()
            if not self.state.pack_name:
                wx.MessageBox(
                    "Please enter a pack name.", "Missing Name", wx.OK | wx.ICON_WARNING, self
                )
                return False
        elif self.current_step == 2:
            self.state.selected_event_keys = [
                key for key, checkbox in self.event_checks if checkbox.GetValue()
            ]
            if not self.state.selected_event_keys:
                wx.MessageBox(
                    "Please select at least one event.",
                    "No Selection",
                    wx.OK | wx.ICON_WARNING,
                    self,
                )
                return False
        return True

    def _go_previous(self, event) -> None:
        if self.current_step > 1:
            self.current_step -= 1
            self._render_step()

    def _go_next(self, event) -> None:
        if not self._validate_current_step():
            return
        if self.current_step < self.total_steps:
            self.current_step += 1
            self._render_step()
            return
        self._create_pack()

    def _create_pack(self) -> None:
        pack_id = slugify_pack_name(self.state.pack_name)
        candidate = pack_id
        suffix = 2
        while (self.soundpacks_dir / candidate).exists():
            candidate = f"{pack_id}_{suffix}"
            suffix += 1
        pack_dir = self.soundpacks_dir / candidate
        pack_dir.mkdir(parents=True)

        sounds_mapping: dict[str, str] = {}
        for key, src_path_str in self.state.sound_mappings.items():
            src_path = Path(src_path_str)
            if src_path.exists():
                dest = pack_dir / src_path.name
                shutil.copy2(src_path, dest)
                sounds_mapping[key] = src_path.name

        pack_data = {
            "name": self.state.pack_name,
            "author": self.state.author or "Unknown",
            "description": self.state.description,
            "version": "1.0.0",
            "sounds": sounds_mapping,
        }
        (pack_dir / "pack.json").write_text(json.dumps(pack_data, indent=2), encoding="utf-8")
        self.created_pack_id = candidate
        with contextlib.suppress(Exception):
            shutil.rmtree(self.staging_dir)
        wx.MessageBox(
            f"Sound pack '{self.state.pack_name}' created successfully.",
            "Pack Created",
            wx.OK | wx.ICON_INFORMATION,
            self,
        )
        self.EndModal(wx.ID_OK)

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self._on_cancel(event)
            return
        event.Skip()

    def _on_cancel(self, event) -> None:
        has_changes = bool(
            self.state.pack_name
            or self.state.author
            or self.state.description
            or self.state.selected_event_keys
            or self.state.sound_mappings
        )
        if has_changes:
            result = wx.MessageBox(
                "Discard changes and close the wizard?",
                "Cancel Wizard",
                wx.YES_NO | wx.ICON_QUESTION,
                self,
            )
            if result != wx.YES:
                return
        with contextlib.suppress(Exception):
            shutil.rmtree(self.staging_dir)
        self.EndModal(wx.ID_CANCEL)

    @staticmethod
    def _friendly_name(event_key: str) -> str:
        for display_name, key in FRIENDLY_SOUND_EVENT_CHOICES:
            if key == event_key:
                return display_name
        return event_key.replace("_", " ").title()
