"""Tests for sound pack helpers."""

from __future__ import annotations

import json
import sys
import types
import zipfile

import pytest

import portkeydrop.soundpacks as soundpacks_module
from portkeydrop.soundpack_paths import ensure_default_soundpack
from portkeydrop.soundpacks import (
    SoundPackInstaller,
    get_available_sound_packs,
    get_sound_entry,
    parse_sound_entry,
    play_sound_file,
    safe_extractall,
    slugify_pack_name,
    validate_sound_pack,
)


def test_ensure_default_soundpack_installs_packaged_default(tmp_path):
    soundpacks_dir = ensure_default_soundpack(tmp_path / "soundpacks")

    pack_json = soundpacks_dir / "default" / "pack.json"
    pack_data = json.loads(pack_json.read_text(encoding="utf-8"))

    assert pack_json.exists()
    assert pack_data["sounds"]["transfer_complete"] == "transfers/transfer_complete.ogg"
    assert (soundpacks_dir / "default" / "transfers" / "transfer_complete.ogg").exists()


def test_ensure_default_soundpack_upgrades_placeholder_default(tmp_path):
    soundpacks_dir = tmp_path / "soundpacks"
    default_dir = soundpacks_dir / "default"
    default_dir.mkdir(parents=True)
    (default_dir / "pack.json").write_text(
        json.dumps({"name": "Default", "sounds": {}}),
        encoding="utf-8",
    )

    ensure_default_soundpack(soundpacks_dir)

    pack_data = json.loads((default_dir / "pack.json").read_text(encoding="utf-8"))
    assert pack_data["sounds"]["connect_success"] == "connections/connect_success.ogg"
    assert (default_dir / "connections" / "connect_success.ogg").exists()


def test_ensure_default_soundpack_preserves_custom_default_manifest(tmp_path):
    soundpacks_dir = tmp_path / "soundpacks"
    default_dir = soundpacks_dir / "default"
    default_dir.mkdir(parents=True)
    (default_dir / "custom.wav").write_bytes(b"RIFF")
    (default_dir / "pack.json").write_text(
        json.dumps({"name": "My Default", "sounds": {"success": "custom.wav"}}),
        encoding="utf-8",
    )

    ensure_default_soundpack(soundpacks_dir)

    pack_data = json.loads((default_dir / "pack.json").read_text(encoding="utf-8"))
    assert pack_data == {"name": "My Default", "sounds": {"success": "custom.wav"}}
    assert (default_dir / "transfers" / "transfer_complete.ogg").exists()


def test_validate_sound_pack_accepts_inline_volume_format(tmp_path):
    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    (pack_dir / "complete.wav").write_bytes(b"RIFF")
    (pack_dir / "pack.json").write_text(
        json.dumps(
            {
                "name": "Transfers",
                "sounds": {"transfer_complete": {"file": "complete.wav", "volume": 0.5}},
            }
        ),
        encoding="utf-8",
    )

    valid, message = validate_sound_pack(pack_dir)

    assert valid is True
    assert message == "Sound pack is valid"


def test_validate_sound_pack_rejects_missing_mapped_file(tmp_path):
    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    (pack_dir / "pack.json").write_text(
        json.dumps({"name": "Broken", "sounds": {"transfer_failed": "missing.wav"}}),
        encoding="utf-8",
    )

    valid, message = validate_sound_pack(pack_dir)

    assert valid is False
    assert "Missing sound files" in message


def test_validate_sound_pack_rejects_missing_directory(tmp_path):
    valid, message = validate_sound_pack(tmp_path / "missing")

    assert valid is False
    assert message == "Sound pack directory does not exist"


def test_validate_sound_pack_rejects_non_directory(tmp_path):
    pack_path = tmp_path / "pack.zip"
    pack_path.write_text("not a directory", encoding="utf-8")

    valid, message = validate_sound_pack(pack_path)

    assert valid is False
    assert message == "Sound pack path is not a directory"


def test_validate_sound_pack_rejects_missing_pack_json(tmp_path):
    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()

    valid, message = validate_sound_pack(pack_dir)

    assert valid is False
    assert message == "Missing pack.json file"


def test_validate_sound_pack_rejects_invalid_manifest_shapes(tmp_path):
    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    pack_json = pack_dir / "pack.json"

    pack_json.write_text(json.dumps({"sounds": {}}), encoding="utf-8")
    valid, message = validate_sound_pack(pack_dir)
    assert valid is False
    assert message == "Missing 'name' field in pack.json"

    pack_json.write_text(json.dumps({"name": "Broken"}), encoding="utf-8")
    valid, message = validate_sound_pack(pack_dir)
    assert valid is False
    assert message == "Missing 'sounds' field in pack.json"

    pack_json.write_text(json.dumps({"name": "Broken", "sounds": []}), encoding="utf-8")
    valid, message = validate_sound_pack(pack_dir)
    assert valid is False
    assert message == "'sounds' field must be a dictionary"


def test_validate_sound_pack_rejects_invalid_volume_data(tmp_path):
    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    (pack_dir / "cue.wav").write_bytes(b"RIFF")
    pack_json = pack_dir / "pack.json"

    pack_json.write_text(
        json.dumps({"name": "Broken", "sounds": {"success": "cue.wav"}, "volumes": []}),
        encoding="utf-8",
    )
    valid, message = validate_sound_pack(pack_dir)
    assert valid is False
    assert message == "'volumes' field must be a dictionary"

    pack_json.write_text(
        json.dumps(
            {"name": "Broken", "sounds": {"success": "cue.wav"}, "volumes": {"success": "loud"}}
        ),
        encoding="utf-8",
    )
    valid, message = validate_sound_pack(pack_dir)
    assert valid is False
    assert "Invalid volume value" in message

    pack_json.write_text(
        json.dumps(
            {"name": "Broken", "sounds": {"success": "cue.wav"}, "volumes": {"success": 1.5}}
        ),
        encoding="utf-8",
    )
    valid, message = validate_sound_pack(pack_dir)
    assert valid is False
    assert "must be between 0.0 and 1.0" in message


def test_get_sound_entry_falls_back_to_default_pack(tmp_path):
    soundpacks_dir = ensure_default_soundpack(tmp_path / "soundpacks")
    default_dir = soundpacks_dir / "default"
    (default_dir / "error.wav").write_bytes(b"RIFF")
    (default_dir / "pack.json").write_text(
        json.dumps({"name": "Default", "sounds": {"transfer_failed": "error.wav"}}),
        encoding="utf-8",
    )
    custom_dir = soundpacks_dir / "custom"
    custom_dir.mkdir()
    (custom_dir / "pack.json").write_text(
        json.dumps({"name": "Custom", "sounds": {}}),
        encoding="utf-8",
    )

    sound_file, volume = get_sound_entry(
        "transfer_failed",
        "custom",
        soundpacks_dir=soundpacks_dir,
    )

    assert sound_file == default_dir / "error.wav"
    assert volume == 1.0


def test_get_sound_entry_ignores_unreadable_pack_manifest(tmp_path):
    soundpacks_dir = ensure_default_soundpack(tmp_path / "soundpacks")
    broken_dir = soundpacks_dir / "broken"
    broken_dir.mkdir()
    (broken_dir / "pack.json").write_text("{", encoding="utf-8")

    sound_file, volume = get_sound_entry(
        "transfer_failed",
        "broken",
        soundpacks_dir=soundpacks_dir,
    )

    assert sound_file is not None
    assert sound_file.name == "transfer_failed.ogg"
    assert volume == 1.0


def test_installer_exports_pack_zip(tmp_path):
    soundpacks_dir = ensure_default_soundpack(tmp_path / "soundpacks")
    pack_dir = soundpacks_dir / "custom"
    pack_dir.mkdir()
    (pack_dir / "done.wav").write_bytes(b"RIFF")
    (pack_dir / "pack.json").write_text(
        json.dumps({"name": "Custom", "sounds": {"transfer_complete": "done.wav"}}),
        encoding="utf-8",
    )
    output = tmp_path / "custom.zip"

    ok, message = SoundPackInstaller(soundpacks_dir).export_pack("custom", output)

    assert ok is True
    assert "Successfully exported" in message
    with zipfile.ZipFile(output) as zf:
        assert sorted(zf.namelist()) == ["done.wav", "pack.json"]


def test_installer_installs_pack_zip_from_nested_directory(tmp_path):
    soundpacks_dir = ensure_default_soundpack(tmp_path / "soundpacks")
    archive = tmp_path / "new-pack.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "nested/pack.json",
            json.dumps({"name": "Fancy Pack", "sounds": {"success": "done.wav"}}),
        )
        zf.writestr("nested/done.wav", b"RIFF")

    ok, message = SoundPackInstaller(soundpacks_dir).install_from_zip(archive)

    assert ok is True
    assert "Successfully installed" in message
    assert (soundpacks_dir / "fancy_pack" / "pack.json").exists()


def test_installer_rejects_invalid_zip_inputs(tmp_path):
    soundpacks_dir = ensure_default_soundpack(tmp_path / "soundpacks")
    installer = SoundPackInstaller(soundpacks_dir)

    ok, message = installer.install_from_zip(tmp_path / "missing.zip")
    assert ok is False
    assert "ZIP file not found" in message

    archive = tmp_path / "not-a-pack.zip"
    archive.write_text("not a zip", encoding="utf-8")
    ok, message = installer.install_from_zip(archive)
    assert ok is False
    assert message == "Invalid ZIP file"

    empty_archive = tmp_path / "empty.zip"
    with zipfile.ZipFile(empty_archive, "w") as zf:
        zf.writestr("readme.txt", "hello")
    ok, message = installer.install_from_zip(empty_archive)
    assert ok is False
    assert message == "No pack.json file found in ZIP archive"


def test_installer_rejects_invalid_or_duplicate_pack_zip(tmp_path):
    soundpacks_dir = ensure_default_soundpack(tmp_path / "soundpacks")
    archive = tmp_path / "broken-pack.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "pack.json", json.dumps({"name": "Broken", "sounds": {"success": "missing.wav"}})
        )

    ok, message = SoundPackInstaller(soundpacks_dir).install_from_zip(archive)

    assert ok is False
    assert "Invalid sound pack" in message

    duplicate_archive = tmp_path / "duplicate-pack.zip"
    with zipfile.ZipFile(duplicate_archive, "w") as zf:
        zf.writestr("pack.json", json.dumps({"name": "Default", "sounds": {"success": "done.wav"}}))
        zf.writestr("done.wav", b"RIFF")
    ok, message = SoundPackInstaller(soundpacks_dir).install_from_zip(duplicate_archive)
    assert ok is False
    assert "already exists" in message


def test_installer_uninstalls_custom_pack_only(tmp_path):
    soundpacks_dir = ensure_default_soundpack(tmp_path / "soundpacks")
    pack_dir = soundpacks_dir / "custom"
    pack_dir.mkdir()
    (pack_dir / "pack.json").write_text(
        json.dumps({"name": "Custom", "sounds": {}}),
        encoding="utf-8",
    )
    installer = SoundPackInstaller(soundpacks_dir)

    ok, message = installer.uninstall_pack("default")
    assert ok is False
    assert message == "Cannot uninstall the default sound pack"

    ok, message = installer.uninstall_pack("missing")
    assert ok is False
    assert "not found" in message

    ok, message = installer.uninstall_pack("custom")
    assert ok is True
    assert "Successfully uninstalled" in message
    assert not pack_dir.exists()


def test_safe_extractall_rejects_zip_slip(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../evil.txt", "bad")

    with zipfile.ZipFile(archive) as zf:
        with pytest.raises(ValueError, match="Zip Slip"):
            safe_extractall(zf, tmp_path / "out")


def test_slugify_pack_name_has_safe_fallback():
    assert slugify_pack_name("My Pack!") == "my_pack"
    assert slugify_pack_name("!!!") == "sound_pack"


def test_get_available_sound_packs_includes_default(tmp_path):
    soundpacks_dir = ensure_default_soundpack(tmp_path / "soundpacks")

    packs = get_available_sound_packs(soundpacks_dir)

    assert "default" in packs


def test_parse_sound_entry_clamps_volume():
    assert parse_sound_entry({"file": "x.wav", "volume": 2}, "event") == ("x.wav", 1.0)


def test_parse_sound_entry_uses_volume_mapping_and_fallbacks():
    assert parse_sound_entry("", "notify", {"notify": 0.5}) == ("notify.wav", 0.5)
    assert parse_sound_entry({"volume": "quiet"}, "notify") == ("notify.wav", 1.0)


def test_sound_player_respects_disabled_and_muted_events(tmp_path, monkeypatch):
    soundpacks_dir = ensure_default_soundpack(tmp_path / "soundpacks")
    player = soundpacks_module.SoundPlayer(soundpacks_dir)
    calls: list[tuple[object, float]] = []
    monkeypatch.setattr(
        soundpacks_module,
        "play_sound_file",
        lambda path, volume=1.0: calls.append((path, volume)) or True,
    )

    assert player.play_event("success", enabled=False) is False
    assert player.play_event("success", muted={"success"}) is False
    assert player.play_event("success") is True
    assert calls


def test_play_sound_file_handles_missing_backend_and_errors(tmp_path, monkeypatch):
    sound_file = tmp_path / "cue.ogg"
    sound_file.write_bytes(b"OggS")

    monkeypatch.setattr(soundpacks_module, "SOUND_LIB_AVAILABLE", False)
    assert play_sound_file(sound_file) is False
    assert play_sound_file(tmp_path / "missing.ogg") is False
    assert play_sound_file(sound_file, volume=0) is True

    class BrokenFileStream:
        is_playing = False

        def __init__(self, *, file: str) -> None:
            raise RuntimeError(file)

    stream_module = types.ModuleType("sound_lib.stream")
    stream_module.FileStream = BrokenFileStream
    monkeypatch.setitem(sys.modules, "sound_lib", types.ModuleType("sound_lib"))
    monkeypatch.setitem(sys.modules, "sound_lib.stream", stream_module)
    monkeypatch.setattr(soundpacks_module, "SOUND_LIB_AVAILABLE", True)
    assert play_sound_file(sound_file) is False


def test_play_sound_file_uses_sound_lib_only(tmp_path, monkeypatch):
    sound_file = tmp_path / "cue.ogg"
    sound_file.write_bytes(b"OggS")
    calls: dict[str, object] = {}

    stream_module = types.ModuleType("sound_lib.stream")

    class FakeFileStream:
        is_playing = True

        def __init__(self, *, file: str) -> None:
            calls["file"] = file
            self.volume = 0

        def play(self) -> None:
            calls["volume"] = self.volume
            calls["played"] = True

    stream_module.FileStream = FakeFileStream
    monkeypatch.setitem(sys.modules, "sound_lib", types.ModuleType("sound_lib"))
    monkeypatch.setitem(sys.modules, "sound_lib.stream", stream_module)
    monkeypatch.setattr(soundpacks_module, "SOUND_LIB_AVAILABLE", True)
    monkeypatch.setattr(soundpacks_module, "_active_streams", [])

    assert play_sound_file(sound_file, volume=0.25) is True
    assert calls == {
        "file": str(sound_file),
        "volume": 0.25,
        "played": True,
    }
    assert len(soundpacks_module._active_streams) == 1
