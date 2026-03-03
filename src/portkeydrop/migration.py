"""Helpers for migrating config files into portable mode."""

from __future__ import annotations

import shutil
from collections.abc import Iterable
from pathlib import Path

MIGRATION_ITEMS: list[tuple[str, str]] = [
    ("Sites and connections", "sites.json"),
    ("Saved passwords (encrypted vault)", "vault.enc"),
    ("Known SSH hosts", "known_hosts"),
    ("App settings", "settings.json"),
]


def has_migration_candidates(portable_dir: Path, standard_dir: Path) -> bool:
    """Return True when at least one file can be copied to portable config."""
    for _, filename in MIGRATION_ITEMS:
        if (standard_dir / filename).exists() and not (portable_dir / filename).exists():
            return True
    return False


def get_migration_candidates(standard_dir: Path) -> list[tuple[str, str]]:
    """Return (label, filename) entries that exist in the standard install dir."""
    return [
        (label, filename)
        for label, filename in MIGRATION_ITEMS
        if (standard_dir / filename).exists()
    ]


def migrate_files(candidates: Iterable[str], standard_dir: Path, portable_dir: Path) -> None:
    """Copy selected files from standard config dir into portable config dir."""
    portable_dir.mkdir(parents=True, exist_ok=True)
    for filename in candidates:
        src = standard_dir / filename
        if not src.exists():
            continue
        shutil.copy2(src, portable_dir / filename)
