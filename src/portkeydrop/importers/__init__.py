"""Connection profile importers for external FTP/SFTP clients."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import cyberduck, filezilla, winscp
from .models import ImportedSite


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


def detect_default_path(source: str) -> Path | None:
    """Return the default path for the requested source client."""
    if source == "filezilla":
        return filezilla.detect_path()
    if source == "winscp":
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
