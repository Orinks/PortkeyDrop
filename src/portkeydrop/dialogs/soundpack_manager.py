"""wxPython sound pack manager dialog."""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import wx

from portkeydrop.sound_events import FRIENDLY_SOUND_EVENT_CHOICES
from portkeydrop.soundpack_paths import ensure_default_soundpack, get_soundpacks_dir
from portkeydrop.soundpacks import (
    AUDIO_WILDCARD,
    SoundPackInstaller,
    get_available_sound_packs,
    parse_sound_entry,
    play_sound_file,
    safe_extractall,
    slugify_pack_name,
)

logger = logging.getLogger(__name__)


@dataclass
class SoundPackInfo:
    """Information about a sound pack."""

    pack_id: str
    name: str
    author: str
    description: str
    path: Path
    sounds: dict


class SoundPackManagerDialog(wx.Dialog):
    """Dialog for managing local sound packs."""

    def __init__(self, parent: wx.Window | None, soundpacks_dir: Path | None = None) -> None:
        super().__init__(
            parent,
            title="Sound Pack Manager",
            size=(820, 560),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        self.soundpacks_dir = ensure_default_soundpack(soundpacks_dir or get_soundpacks_dir())
        self.installer = SoundPackInstaller(self.soundpacks_dir)
        self.sound_packs: dict[str, SoundPackInfo] = {}
        self.selected_pack: str | None = None
        self._load_sound_packs()
        self._build_ui()
        self._refresh_pack_list()
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.Centre()

    def _build_ui(self) -> None:
        panel = wx.Panel(self)
        root = wx.BoxSizer(wx.VERTICAL)
        content = wx.BoxSizer(wx.HORIZONTAL)
        content.Add(self._create_pack_list_panel(panel), 1, wx.EXPAND | wx.RIGHT, 10)
        content.Add(self._create_details_panel(panel), 2, wx.EXPAND)
        root.Add(content, 1, wx.EXPAND | wx.ALL, 10)
        root.Add(self._create_button_panel(panel), 0, wx.EXPAND | wx.ALL, 10)
        panel.SetSizer(root)

    def _create_pack_list_panel(self, parent: wx.Window) -> wx.BoxSizer:
        sizer = wx.BoxSizer(wx.VERTICAL)
        label = wx.StaticText(parent, label="Available sound packs:")
        sizer.Add(label, 0, wx.BOTTOM, 5)
        self.pack_listbox = wx.ListBox(parent, style=wx.LB_SINGLE)
        self.pack_listbox.SetName("Available sound packs")
        self.pack_listbox.Bind(wx.EVT_LISTBOX, self._on_pack_selected)
        sizer.Add(self.pack_listbox, 1, wx.EXPAND | wx.BOTTOM, 10)
        import_btn = wx.Button(parent, label="Import Sound Pack...")
        import_btn.Bind(wx.EVT_BUTTON, self._on_import_pack)
        sizer.Add(import_btn, 0, wx.EXPAND)
        return sizer

    def _create_details_panel(self, parent: wx.Window) -> wx.BoxSizer:
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.name_label = wx.StaticText(parent, label="No pack selected")
        sizer.Add(self.name_label, 0, wx.BOTTOM, 5)
        self.author_label = wx.StaticText(parent, label="")
        sizer.Add(self.author_label, 0, wx.BOTTOM, 5)
        self.description_label = wx.StaticText(parent, label="")
        self.description_label.Wrap(400)
        sizer.Add(self.description_label, 0, wx.BOTTOM, 10)

        sizer.Add(wx.StaticText(parent, label="Sounds in this pack:"), 0, wx.BOTTOM, 5)
        self.sounds_listbox = wx.ListBox(parent)
        self.sounds_listbox.SetName("Sounds in selected pack")
        self.sounds_listbox.Bind(wx.EVT_LISTBOX, self._on_sound_selected)
        sizer.Add(self.sounds_listbox, 1, wx.EXPAND | wx.BOTTOM, 5)

        preview_row = wx.BoxSizer(wx.HORIZONTAL)
        self.preview_btn = wx.Button(parent, label="Preview Selected Sound")
        self.preview_btn.Bind(wx.EVT_BUTTON, self._on_preview_sound)
        self.preview_btn.Enable(False)
        preview_row.Add(self.preview_btn, 0, wx.RIGHT, 5)
        preview_row.Add(
            wx.StaticText(parent, label="Volume:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5
        )
        self.volume_spin = wx.SpinCtrl(parent, min=0, max=100, initial=100, size=(70, -1))
        self.volume_spin.SetName("Selected sound volume")
        preview_row.Add(self.volume_spin, 0, wx.RIGHT, 5)
        self.set_volume_btn = wx.Button(parent, label="Set Volume")
        self.set_volume_btn.Bind(wx.EVT_BUTTON, self._on_set_volume)
        self.set_volume_btn.Enable(False)
        preview_row.Add(self.set_volume_btn, 0)
        sizer.Add(preview_row, 0, wx.BOTTOM, 10)

        mapping_box = wx.StaticBox(parent, label="Sound mappings")
        mapping_sizer = wx.StaticBoxSizer(mapping_box, wx.VERTICAL)
        category_row = wx.BoxSizer(wx.HORIZONTAL)
        category_row.Add(
            wx.StaticText(parent, label="Event:"), 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5
        )
        self.event_choice = wx.Choice(
            parent, choices=[name for name, _key in FRIENDLY_SOUND_EVENT_CHOICES]
        )
        self.event_choice.SetName("Sound event")
        self.event_choice.Bind(wx.EVT_CHOICE, self._on_event_changed)
        category_row.Add(self.event_choice, 1, wx.RIGHT, 5)
        self.mapping_file_text = wx.TextCtrl(parent, style=wx.TE_READONLY)
        self.mapping_file_text.SetName("Mapped sound file")
        category_row.Add(self.mapping_file_text, 1, wx.RIGHT, 5)
        browse_btn = wx.Button(parent, label="Choose Sound...")
        browse_btn.Bind(wx.EVT_BUTTON, self._on_browse_mapping)
        category_row.Add(browse_btn, 0)
        mapping_sizer.Add(category_row, 0, wx.EXPAND | wx.ALL, 5)
        sizer.Add(mapping_sizer, 0, wx.EXPAND)
        return sizer

    def _create_button_panel(self, parent: wx.Window) -> wx.BoxSizer:
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.create_btn = wx.Button(parent, label="Create Sound Pack...")
        self.create_btn.Bind(wx.EVT_BUTTON, self._on_create_pack)
        sizer.Add(self.create_btn, 0, wx.RIGHT, 5)
        self.duplicate_btn = wx.Button(parent, label="Duplicate")
        self.duplicate_btn.Bind(wx.EVT_BUTTON, self._on_duplicate_pack)
        self.duplicate_btn.Enable(False)
        sizer.Add(self.duplicate_btn, 0, wx.RIGHT, 5)
        self.edit_btn = wx.Button(parent, label="Edit...")
        self.edit_btn.Bind(wx.EVT_BUTTON, self._on_edit_pack)
        self.edit_btn.Enable(False)
        sizer.Add(self.edit_btn, 0, wx.RIGHT, 5)
        self.delete_btn = wx.Button(parent, label="Delete")
        self.delete_btn.Bind(wx.EVT_BUTTON, self._on_delete_pack)
        self.delete_btn.Enable(False)
        sizer.Add(self.delete_btn, 0, wx.RIGHT, 5)
        self.export_btn = wx.Button(parent, label="Export...")
        self.export_btn.Bind(wx.EVT_BUTTON, self._on_export_pack)
        self.export_btn.Enable(False)
        sizer.Add(self.export_btn, 0)
        sizer.AddStretchSpacer()
        close_btn = wx.Button(parent, wx.ID_CLOSE, label="Close")
        close_btn.Bind(wx.EVT_BUTTON, self._on_close)
        sizer.Add(close_btn, 0)
        return sizer

    def _load_sound_packs(self) -> None:
        self.sound_packs.clear()
        for pack_id, data in get_available_sound_packs(self.soundpacks_dir).items():
            self.sound_packs[pack_id] = SoundPackInfo(
                pack_id=pack_id,
                name=data.get("name", pack_id),
                author=data.get("author", "Unknown"),
                description=data.get("description", ""),
                path=Path(data["path"]),
                sounds=data.get("sounds", {}),
            )

    def _refresh_pack_list(self) -> None:
        self.pack_listbox.Clear()
        for pack_id, info in sorted(self.sound_packs.items(), key=lambda item: item[1].name):
            self.pack_listbox.Append(f"{info.name} (by {info.author})", pack_id)
        if self.pack_listbox.GetCount() > 0:
            self.pack_listbox.SetSelection(0)
            self._on_pack_selected(None)

    def _on_pack_selected(self, event) -> None:
        selection = self.pack_listbox.GetSelection()
        self.selected_pack = (
            None if selection == wx.NOT_FOUND else self.pack_listbox.GetClientData(selection)
        )
        self._update_pack_details()

    def _update_pack_details(self) -> None:
        if not self.selected_pack or self.selected_pack not in self.sound_packs:
            self.name_label.SetLabel("No pack selected")
            self.author_label.SetLabel("")
            self.description_label.SetLabel("")
            self.sounds_listbox.Clear()
            for button in (
                self.preview_btn,
                self.duplicate_btn,
                self.edit_btn,
                self.delete_btn,
                self.export_btn,
                self.set_volume_btn,
            ):
                button.Enable(False)
            return

        info = self.sound_packs[self.selected_pack]
        self.name_label.SetLabel(info.name)
        self.author_label.SetLabel(f"Author: {info.author}")
        self.description_label.SetLabel(info.description or "No description available")
        self.description_label.Wrap(400)
        self.sounds_listbox.Clear()
        sounds, volumes = self._read_pack_sounds(info)
        for event_key, sound_entry in sounds.items():
            filename, volume = parse_sound_entry(sound_entry, event_key, volumes)
            status = "OK" if (info.path / filename).exists() else "Missing"
            label = self._friendly_name(event_key)
            self.sounds_listbox.Append(
                f"{label} ({filename}) at {int(volume * 100)} percent - {status}",
                (event_key, filename, volume),
            )
        self.duplicate_btn.Enable(True)
        self.edit_btn.Enable(True)
        self.delete_btn.Enable(self.selected_pack != "default")
        self.export_btn.Enable(True)
        self._on_event_changed(None)

    def _on_sound_selected(self, event) -> None:
        selection = self.sounds_listbox.GetSelection()
        if selection == wx.NOT_FOUND or not self.selected_pack:
            self.preview_btn.Enable(False)
            self.set_volume_btn.Enable(False)
            return
        data = self.sounds_listbox.GetClientData(selection)
        if not data:
            return
        _event_key, filename, volume = data
        exists = (self.sound_packs[self.selected_pack].path / filename).exists()
        self.volume_spin.SetValue(int(volume * 100))
        self.preview_btn.Enable(exists)
        self.set_volume_btn.Enable(exists)

    def _on_preview_sound(self, event) -> None:
        if not self.selected_pack:
            return
        selection = self.sounds_listbox.GetSelection()
        if selection == wx.NOT_FOUND:
            return
        data = self.sounds_listbox.GetClientData(selection)
        if not data:
            return
        _event_key, filename, _volume = data
        play_sound_file(
            self.sound_packs[self.selected_pack].path / filename,
            volume=self.volume_spin.GetValue() / 100.0,
        )

    def _on_event_changed(self, event) -> None:
        if not self.selected_pack or self.event_choice.GetSelection() == wx.NOT_FOUND:
            self.mapping_file_text.SetValue("")
            return
        event_key = FRIENDLY_SOUND_EVENT_CHOICES[self.event_choice.GetSelection()][1]
        sounds, volumes = self._read_pack_sounds(self.sound_packs[self.selected_pack])
        entry = sounds.get(event_key, "")
        if entry:
            filename, volume = parse_sound_entry(entry, event_key, volumes)
            self.mapping_file_text.SetValue(filename)
            self.volume_spin.SetValue(int(volume * 100))
        else:
            self.mapping_file_text.SetValue("")
            self.volume_spin.SetValue(100)

    def _on_browse_mapping(self, event) -> None:
        if not self.selected_pack:
            return
        selection = self.event_choice.GetSelection()
        if selection == wx.NOT_FOUND:
            wx.MessageBox("Please select an event first.", "No Event", wx.OK | wx.ICON_INFORMATION)
            return
        event_key = FRIENDLY_SOUND_EVENT_CHOICES[selection][1]
        with wx.FileDialog(
            self,
            "Select Audio File",
            wildcard=AUDIO_WILDCARD,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            src_path = Path(dialog.GetPath())
        info = self.sound_packs[self.selected_pack]
        dest_path = info.path / src_path.name
        if src_path.resolve() != dest_path.resolve():
            shutil.copy2(src_path, dest_path)
        self._write_sound_mapping(
            info, event_key, src_path.name, self.volume_spin.GetValue() / 100.0
        )
        self._load_sound_packs()
        self._update_pack_details()

    def _on_set_volume(self, event) -> None:
        if not self.selected_pack:
            return
        selection = self.sounds_listbox.GetSelection()
        if selection == wx.NOT_FOUND:
            return
        event_key, filename, _volume = self.sounds_listbox.GetClientData(selection)
        info = self.sound_packs[self.selected_pack]
        self._write_sound_mapping(info, event_key, filename, self.volume_spin.GetValue() / 100.0)
        self._load_sound_packs()
        self._update_pack_details()

    def _on_import_pack(self, event) -> None:
        with wx.FileDialog(
            self,
            "Select Sound Pack ZIP File",
            wildcard="ZIP files (*.zip)|*.zip",
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            zip_path = Path(dialog.GetPath())
        try:
            with zipfile.ZipFile(zip_path, "r") as zip_file:
                with tempfile.TemporaryDirectory() as temp_dir:
                    temp_path = Path(temp_dir)
                    safe_extractall(zip_file, temp_path)
                    pack_json = next(iter(temp_path.rglob("pack.json")), None)
                    if pack_json is None:
                        wx.MessageBox(
                            "Invalid sound pack: missing pack.json.",
                            "Import Error",
                            wx.OK | wx.ICON_ERROR,
                        )
                        return
                    data = json.loads(pack_json.read_text(encoding="utf-8"))
                    pack_name = data.get("name", zip_path.stem)
                    pack_id = slugify_pack_name(pack_name)
                    pack_dir = self.soundpacks_dir / pack_id
                    if pack_dir.exists():
                        result = wx.MessageBox(
                            f"A sound pack named '{pack_name}' already exists. Overwrite?",
                            "Pack Exists",
                            wx.YES_NO | wx.ICON_QUESTION,
                        )
                        if result != wx.YES:
                            return
                        shutil.rmtree(pack_dir)
                    shutil.copytree(pack_json.parent, pack_dir)
            self._load_sound_packs()
            self._refresh_pack_list()
        except Exception as exc:
            logger.error("Failed to import sound pack: %s", exc)
            wx.MessageBox(
                f"Failed to import sound pack: {exc}", "Import Error", wx.OK | wx.ICON_ERROR
            )

    def _on_create_pack(self, event) -> None:
        from portkeydrop.dialogs.soundpack_wizard import SoundPackWizardDialog

        wizard = SoundPackWizardDialog(self, self.soundpacks_dir)
        result = wizard.ShowModal()
        created_pack_id = wizard.created_pack_id
        wizard.Destroy()
        if result == wx.ID_OK and created_pack_id:
            self._load_sound_packs()
            self._refresh_pack_list()
            self._select_pack(created_pack_id)

    def _on_duplicate_pack(self, event) -> None:
        if not self.selected_pack:
            return
        info = self.sound_packs[self.selected_pack]
        candidate = f"{self.selected_pack}_copy"
        suffix = 2
        while (self.soundpacks_dir / candidate).exists():
            candidate = f"{self.selected_pack}_copy{suffix}"
            suffix += 1
        shutil.copytree(info.path, self.soundpacks_dir / candidate)
        pack_json = self.soundpacks_dir / candidate / "pack.json"
        data = json.loads(pack_json.read_text(encoding="utf-8"))
        data["name"] = f"{info.name} (Copy)"
        pack_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
        self._load_sound_packs()
        self._refresh_pack_list()
        self._select_pack(candidate)

    def _on_edit_pack(self, event) -> None:
        if not self.selected_pack:
            return
        info = self.sound_packs[self.selected_pack]
        dialog = wx.TextEntryDialog(self, "Enter a new display name:", "Edit Sound Pack", info.name)
        if dialog.ShowModal() == wx.ID_OK:
            data_path = info.path / "pack.json"
            data = json.loads(data_path.read_text(encoding="utf-8"))
            data["name"] = dialog.GetValue().strip() or info.name
            data_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            self._load_sound_packs()
            self._refresh_pack_list()
            self._select_pack(self.selected_pack)
        dialog.Destroy()

    def _on_delete_pack(self, event) -> None:
        if not self.selected_pack or self.selected_pack == "default":
            return
        info = self.sound_packs[self.selected_pack]
        result = wx.MessageBox(
            f"Delete '{info.name}'? This cannot be undone.",
            "Delete Sound Pack",
            wx.YES_NO | wx.ICON_WARNING,
        )
        if result != wx.YES:
            return
        shutil.rmtree(info.path)
        self.selected_pack = None
        self._load_sound_packs()
        self._refresh_pack_list()

    def _on_export_pack(self, event) -> None:
        if not self.selected_pack:
            return
        with wx.FileDialog(
            self,
            "Export Sound Pack",
            defaultFile=f"{self.selected_pack}.zip",
            wildcard="ZIP files (*.zip)|*.zip",
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            ok, message = self.installer.export_pack(self.selected_pack, Path(dialog.GetPath()))
        wx.MessageBox(
            message, "Export Sound Pack", wx.OK | (wx.ICON_INFORMATION if ok else wx.ICON_ERROR)
        )

    def _select_pack(self, pack_id: str) -> None:
        for index in range(self.pack_listbox.GetCount()):
            if self.pack_listbox.GetClientData(index) == pack_id:
                self.pack_listbox.SetSelection(index)
                self._on_pack_selected(None)
                break

    @staticmethod
    def _friendly_name(event_key: str) -> str:
        for display_name, key in FRIENDLY_SOUND_EVENT_CHOICES:
            if key == event_key:
                return display_name
        return event_key.replace("_", " ").title()

    @staticmethod
    def _read_pack_sounds(info: SoundPackInfo) -> tuple[dict, dict]:
        try:
            data = json.loads((info.path / "pack.json").read_text(encoding="utf-8"))
        except Exception:
            return {}, {}
        sounds = data.get("sounds", {})
        volumes = data.get("volumes", {})
        return sounds if isinstance(sounds, dict) else {}, volumes if isinstance(
            volumes, dict
        ) else {}

    @staticmethod
    def _write_sound_mapping(
        info: SoundPackInfo, event_key: str, filename: str, volume: float
    ) -> None:
        data_path = info.path / "pack.json"
        data = json.loads(data_path.read_text(encoding="utf-8"))
        sounds = data.get("sounds", {})
        if volume < 1.0:
            sounds[event_key] = {"file": filename, "volume": max(0.0, min(1.0, volume))}
        else:
            sounds[event_key] = filename
        data["sounds"] = sounds
        data_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self._on_close(event)
            return
        event.Skip()

    def _on_close(self, event) -> None:
        self.EndModal(wx.ID_CLOSE)
