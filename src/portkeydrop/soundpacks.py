"""Sound pack lookup, management, and playback helpers."""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from portkeydrop.soundpack_paths import ensure_default_soundpack

logger = logging.getLogger(__name__)

AUDIO_WILDCARD = "Audio files (*.wav;*.mp3;*.ogg;*.flac)|*.wav;*.mp3;*.ogg;*.flac"
DEFAULT_PACK = "default"
SOUND_LIB_AVAILABLE = False
_sound_lib_output = None
_active_streams: list = []

try:
    from sound_lib import output

    _sound_lib_output = output.Output()
    SOUND_LIB_AVAILABLE = True
except ImportError:
    pass
except Exception as exc:
    logger.debug("sound_lib initialization failed: %s", exc)


def slugify_pack_name(value: str, fallback: str = "sound_pack") -> str:
    """Return a filesystem-friendly pack identifier."""
    slug = value.strip().lower().replace("-", "_").replace(" ", "_")
    slug = "".join(char for char in slug if char.isalnum() or char == "_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or fallback


def safe_extractall(zip_file: zipfile.ZipFile, target_dir: Path) -> None:
    """Extract a zip archive after rejecting path traversal members."""
    target_dir = target_dir.resolve()
    for member in zip_file.namelist():
        member_path = (target_dir / member).resolve()
        try:
            member_path.relative_to(target_dir)
        except ValueError as exc:
            raise ValueError(
                f"Zip Slip detected: member '{member}' would extract outside target directory"
            ) from exc
    zip_file.extractall(target_dir)


def parse_sound_entry(
    entry: str | dict[str, Any], event: str, volumes: dict[str, float] | None = None
) -> tuple[str, float]:
    """Parse a pack sound entry and return a clamped filename/volume pair."""
    if isinstance(entry, dict):
        filename = entry.get("file", f"{event}.wav")
        volume = entry.get("volume", 1.0)
    else:
        filename = str(entry) if entry else f"{event}.wav"
        volume = volumes[event] if volumes and event in volumes else 1.0

    try:
        volume = max(0.0, min(1.0, float(volume)))
    except (TypeError, ValueError):
        volume = 1.0
    return filename, volume


def load_pack_sounds(pack_json: Path) -> tuple[dict[str, Any], dict[str, float]]:
    """Load sound and volume mappings from a pack.json file."""
    with open(pack_json, encoding="utf-8") as f:
        meta: dict[str, Any] = json.load(f)
    sounds = meta.get("sounds", {})
    volumes = meta.get("volumes", {})
    return sounds if isinstance(sounds, dict) else {}, volumes if isinstance(volumes, dict) else {}


def validate_sound_pack(pack_path: Path) -> tuple[bool, str]:
    """Validate a sound pack directory and its pack.json contents."""
    if not pack_path.exists():
        return False, "Sound pack directory does not exist"
    if not pack_path.is_dir():
        return False, "Sound pack path is not a directory"

    pack_json = pack_path / "pack.json"
    if not pack_json.exists():
        return False, "Missing pack.json file"

    try:
        with open(pack_json, encoding="utf-8") as f:
            pack_data = json.load(f)
        if "name" not in pack_data:
            return False, "Missing 'name' field in pack.json"
        if "sounds" not in pack_data:
            return False, "Missing 'sounds' field in pack.json"
        if not isinstance(pack_data["sounds"], dict):
            return False, "'sounds' field must be a dictionary"

        missing_files = []
        for sound_name, sound_entry in pack_data["sounds"].items():
            filename = (
                sound_entry.get("file", f"{sound_name}.wav")
                if isinstance(sound_entry, dict)
                else str(sound_entry)
            )
            if not filename or not (pack_path / filename).exists():
                missing_files.append(filename or sound_name)
        if missing_files:
            return False, f"Missing sound files: {', '.join(missing_files)}"

        volumes = pack_data.get("volumes", {})
        if not isinstance(volumes, dict):
            return False, "'volumes' field must be a dictionary"
        for event, volume in volumes.items():
            try:
                value = float(volume)
            except (TypeError, ValueError):
                return False, f"Invalid volume value for '{event}': {volume}"
            if value < 0.0 or value > 1.0:
                return False, f"Volume for '{event}' must be between 0.0 and 1.0"
        return True, "Sound pack is valid"
    except json.JSONDecodeError as exc:
        return False, f"Invalid JSON in pack.json: {exc}"
    except Exception as exc:
        return False, f"Error validating sound pack: {exc}"


def get_available_sound_packs(soundpacks_dir: Path) -> dict[str, dict[str, Any]]:
    """Return all available sound packs with metadata."""
    ensure_default_soundpack(soundpacks_dir)
    packs: dict[str, dict[str, Any]] = {}
    for pack_dir in soundpacks_dir.iterdir():
        if not pack_dir.is_dir():
            continue
        pack_json = pack_dir / "pack.json"
        if not pack_json.exists():
            continue
        try:
            with open(pack_json, encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)
            data["directory"] = pack_dir.name
            data["path"] = str(pack_dir)
            packs[pack_dir.name] = data
        except Exception as exc:
            logger.error("Failed to load sound pack %s: %s", pack_dir.name, exc)
    return packs


def get_sound_entry(
    event: str,
    pack_dir: str,
    *,
    soundpacks_dir: Path,
    default_pack: str = DEFAULT_PACK,
) -> tuple[Path | None, float]:
    """Resolve a sound file and volume for an event in a pack."""
    ensure_default_soundpack(soundpacks_dir)
    for candidate_pack in (pack_dir, default_pack):
        pack_path = soundpacks_dir / candidate_pack
        pack_json = pack_path / "pack.json"
        if not pack_json.exists():
            continue
        try:
            sounds, volumes = load_pack_sounds(pack_json)
            entry = sounds.get(event)
            if entry is None:
                continue
            filename, volume = parse_sound_entry(entry, event, volumes)
            sound_file = pack_path / filename
            if sound_file.exists():
                return sound_file, volume
        except Exception as exc:
            logger.error("Error reading sound pack %s: %s", candidate_pack, exc)
    return None, 1.0


class SoundPackInstaller:
    """Handles local installation and management of sound packs."""

    def __init__(self, soundpacks_dir: Path):
        self.soundpacks_dir = ensure_default_soundpack(soundpacks_dir)

    def install_from_zip(self, zip_path: Path, pack_name: str | None = None) -> tuple[bool, str]:
        """Install a sound pack from a ZIP file."""
        if not zip_path.exists():
            return False, f"ZIP file not found: {zip_path}"

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            try:
                with zipfile.ZipFile(zip_path, "r") as zip_file:
                    safe_extractall(zip_file, temp_path)
                pack_json_files = list(temp_path.rglob("pack.json"))
                if not pack_json_files:
                    return False, "No pack.json file found in ZIP archive"
                pack_dir = pack_json_files[0].parent
                is_valid, message = validate_sound_pack(pack_dir)
                if not is_valid:
                    return False, f"Invalid sound pack: {message}"

                with open(pack_dir / "pack.json", encoding="utf-8") as f:
                    pack_data = json.load(f)
                target_name = slugify_pack_name(pack_name or pack_data.get("name", zip_path.stem))
                target_dir = self.soundpacks_dir / target_name
                if target_dir.exists():
                    return False, f"Sound pack '{target_name}' already exists"
                shutil.copytree(pack_dir, target_dir)
                return (
                    True,
                    f"Successfully installed sound pack '{pack_data.get('name', target_name)}'",
                )
            except zipfile.BadZipFile:
                return False, "Invalid ZIP file"
            except Exception as exc:
                logger.error("Error installing sound pack: %s", exc)
                return False, f"Installation failed: {exc}"

    def export_pack(self, pack_name: str, output_path: Path) -> tuple[bool, str]:
        """Export a sound pack to a ZIP file."""
        pack_dir = self.soundpacks_dir / pack_name
        if not pack_dir.exists():
            return False, f"Sound pack '{pack_name}' not found"
        try:
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
                for file_path in pack_dir.rglob("*"):
                    if file_path.is_file():
                        zip_file.write(file_path, file_path.relative_to(pack_dir))
            return True, f"Successfully exported sound pack to {output_path}"
        except Exception as exc:
            logger.error("Error exporting sound pack: %s", exc)
            return False, f"Export failed: {exc}"

    def uninstall_pack(self, pack_name: str) -> tuple[bool, str]:
        """Remove an installed sound pack."""
        if pack_name == DEFAULT_PACK:
            return False, "Cannot uninstall the default sound pack"
        pack_dir = self.soundpacks_dir / pack_name
        if not pack_dir.exists():
            return False, f"Sound pack '{pack_name}' not found"
        shutil.rmtree(pack_dir)
        return True, f"Successfully uninstalled sound pack '{pack_name}'"


class SoundPlayer:
    """Small optional-backend player for soundpack event sounds."""

    def __init__(self, soundpacks_dir: Path, pack_name: str = DEFAULT_PACK) -> None:
        self.soundpacks_dir = ensure_default_soundpack(soundpacks_dir)
        self.pack_name = pack_name or DEFAULT_PACK

    def play_event(
        self, event: str, *, enabled: bool = True, muted: set[str] | None = None
    ) -> bool:
        """Play a configured event sound when available."""
        if not enabled or event in (muted or set()):
            return False
        sound_file, volume = get_sound_entry(
            event,
            self.pack_name,
            soundpacks_dir=self.soundpacks_dir,
        )
        if sound_file is None:
            return False
        return play_sound_file(sound_file, volume=volume)


def play_sound_file(sound_file: Path, volume: float = 1.0) -> bool:
    """Play a sound file with sound_lib, returning whether playback started."""
    if not sound_file.exists():
        return False
    volume = max(0.0, min(1.0, volume))
    if volume <= 0.0:
        return True
    if not SOUND_LIB_AVAILABLE:
        logger.warning("sound_lib audio backend unavailable")
        return False

    try:
        from sound_lib import stream

        _active_streams[:] = [active for active in _active_streams if active.is_playing]
        sound_stream = stream.FileStream(file=str(sound_file))
        sound_stream.volume = volume
        sound_stream.play()
        _active_streams.append(sound_stream)
        logger.debug("Played sound using sound_lib at volume %s: %s", volume, sound_file)
        return True
    except Exception as exc:
        logger.warning("sound_lib playback failed: %s", exc)
        return False
