"""Sound pack path helpers."""

from __future__ import annotations

import json
import sys
from importlib import resources
from pathlib import Path

from portkeydrop.portable import get_config_dir


def get_soundpacks_dir(config_dir: Path | None = None) -> Path:
    """Return the writable soundpacks directory."""
    return (config_dir or get_config_dir()) / "soundpacks"


def _should_replace_pack_json(pack_json: Path) -> bool:
    """Return whether an existing default pack manifest is still the old placeholder."""
    if not pack_json.exists():
        return True
    try:
        data = json.loads(pack_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return data.get("sounds") == {}


def _copy_pack_resource(resource, target_dir: Path, *, replace_pack_json: bool) -> None:
    """Copy packaged default sound pack files without overwriting user-edited assets."""
    for child in resource.iterdir():
        target = target_dir / child.name
        if child.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            _copy_pack_resource(child, target, replace_pack_json=replace_pack_json)
            continue
        if target.exists() and not (child.name == "pack.json" and replace_pack_json):
            continue
        target.write_bytes(child.read_bytes())


def _packaged_default_soundpack():
    """Return the packaged default sound pack resource, including macOS app bundles."""
    packaged_default = resources.files("portkeydrop").joinpath("default_soundpacks", "default")
    if packaged_default.is_dir():
        return packaged_default

    executable = Path(sys.executable).resolve()
    for parent in executable.parents:
        candidate = (
            parent
            / "Resources"
            / "portkeydrop"
            / "default_soundpacks"
            / "default"
        )
        if candidate.is_dir():
            return candidate
    return packaged_default


def ensure_default_soundpack(soundpacks_dir: Path | None = None) -> Path:
    """Ensure the built-in default pack is available in the writable packs directory."""
    base_dir = soundpacks_dir or get_soundpacks_dir()
    default_dir = base_dir / "default"
    default_dir.mkdir(parents=True, exist_ok=True)
    pack_json = default_dir / "pack.json"
    replace_pack_json = _should_replace_pack_json(pack_json)
    packaged_default = _packaged_default_soundpack()
    if packaged_default.is_dir():
        _copy_pack_resource(packaged_default, default_dir, replace_pack_json=replace_pack_json)
    elif replace_pack_json:
        pack_json.write_text(
            json.dumps(
                {
                    "name": "Default",
                    "author": "Portkey Drop",
                    "description": "Default sound pack.",
                    "version": "1.0.0",
                    "sounds": {},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return base_dir
