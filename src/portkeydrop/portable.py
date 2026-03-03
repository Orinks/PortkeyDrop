"""Portable mode detection and config directory resolution."""

from __future__ import annotations

import sys
from pathlib import Path


def is_portable_mode() -> bool:
    """Return True if the app is running in portable mode.

    Portable mode is active when a ``data/`` directory or a ``portable.txt``
    file exists alongside ``sys.executable``.
    """
    exe_dir = Path(sys.executable).parent
    return (exe_dir / "data").is_dir() or (exe_dir / "portable.txt").is_file()


def get_config_dir() -> Path:
    """Return the configuration directory for the current mode.

    In portable mode the config lives next to the executable
    (``<exe_dir>/data``); otherwise it falls back to ``~/.portkeydrop``.
    """
    if is_portable_mode():
        return Path(sys.executable).parent / "data"
    return Path.home() / ".portkeydrop"
