"""Connection profile importers for external FTP/SFTP clients."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from . import cyberduck, filezilla, winscp
from .models import ImportedSite

WINSCP_REGISTRY_SENTINEL = r"Registry (HKCU\Software\Martin Prikryl\WinSCP 2\Sessions)"


@dataclass(frozen=True)
class ImportSource:
    key: str
    label: str


SOURCES = [
    ImportSource("filezilla", "FileZilla"),
    ImportSource("winscp", "WinSCP"),
    ImportSource("cyberduck", "Cyberduck"),
    ImportSource("from_file", "From file..."),
]


def _winscp_registry_available() -> bool:
    """Check whether WinSCP sessions exist in the Windows Registry."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        key_path = r"Software\Martin Prikryl\WinSCP 2\Sessions"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path):
            return True
    except Exception:
        return False


def is_source_available(source: str) -> bool:
    """Return True if the given import source has detectable config on this machine."""
    if source == "filezilla":
        return filezilla.detect_path().exists()
    if source == "winscp":
        return _winscp_registry_available() or winscp.detect_ini_path().exists()
    if source == "cyberduck":
        return cyberduck.detect_bookmarks_dir().exists()
    if source == "from_file":
        return True
    return False


def available_sources() -> list[ImportSource]:
    """Return only the sources that have detectable config on this machine."""
    return [s for s in SOURCES if is_source_available(s.key)]


def detect_default_path(source: str) -> Path | str | None:
    """Return the default path (or sentinel) for the requested source client."""
    if source == "filezilla":
        return filezilla.detect_path()
    if source == "winscp":
        if _winscp_registry_available():
            return WINSCP_REGISTRY_SENTINEL
        ini_path = winscp.detect_ini_path()
        return ini_path
    if source == "cyberduck":
        return cyberduck.detect_bookmarks_dir()
    return None


def load_from_source(source: str, path: Path | None = None) -> list[ImportedSite]:
    """Load imported profiles for a specific source and path."""
    if source == "filezilla":
        if not path:
            path = filezilla.detect_path()
        return filezilla.parse_file(path)

    if source == "winscp":
        if path:
            return winscp.parse_ini_file(path)

        ini_path = winscp.detect_ini_path()
        if ini_path.exists():
            return winscp.parse_ini_file(ini_path)
        return winscp.parse_registry_sessions()

    if source == "cyberduck":
        if not path:
            path = cyberduck.detect_bookmarks_dir()
        if path.is_dir():
            return cyberduck.parse_bookmarks_dir(path)
        return [cyberduck.parse_bookmark_file(path)]

    if source == "from_file":
        if not path:
            raise ValueError("Path is required for 'from_file' import")
        return _load_from_unknown_path(path)

    raise ValueError(f"Unknown import source: {source}")


def _load_from_unknown_path(path: Path) -> list[ImportedSite]:
    if path.is_dir():
        sites = cyberduck.parse_bookmarks_dir(path)
        if sites:
            return sites

    suffix = path.suffix.lower()
    if suffix == ".ini":
        return winscp.parse_ini_file(path)
    if suffix == ".duck":
        return [cyberduck.parse_bookmark_file(path)]

    parse_attempts = (
        lambda: filezilla.parse_file(path),
        lambda: winscp.parse_ini_file(path),
        lambda: [cyberduck.parse_bookmark_file(path)],
    )
    for parse_fn in parse_attempts:
        try:
            sites = parse_fn()
        except Exception:
            continue
        if sites:
            return sites

    return []
