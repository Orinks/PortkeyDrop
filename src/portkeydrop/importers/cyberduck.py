"""Cyberduck / Mountain Duck bookmark importer."""

from __future__ import annotations

import os
import plistlib
from pathlib import Path

from .models import ImportedSite


_PROTOCOL_MAP = {
    "ftp": "ftp",
    "ftps": "ftps",
    "sftp": "sftp",
    "ssh": "sftp",
}


def detect_bookmarks_dir() -> Path:
    """Return default Cyberduck bookmarks directory for current platform."""
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        return Path(appdata) / "Cyberduck" / "Bookmarks"

    mac_dir = Path.home() / "Library" / "Application Support" / "Cyberduck" / "Bookmarks"
    if mac_dir.exists():
        return mac_dir

    return Path.home() / ".config" / "Cyberduck" / "Bookmarks"


def parse_bookmark_file(path: Path) -> ImportedSite:
    """Parse a single `.duck` bookmark file."""
    with path.open("rb") as handle:
        data = plistlib.load(handle)

    host = str(data.get("Hostname", data.get("Host", ""))).strip()
    protocol = _map_protocol(str(data.get("Protocol", "sftp")).strip())

    raw_port = data.get("Port", 0)
    try:
        port = int(raw_port)
    except (TypeError, ValueError):
        port = 0

    username = str(data.get("Username", "")).strip()
    initial_dir = str(data.get("Path", "/")).strip() or "/"
    nickname = str(data.get("Nickname", "")).strip()

    name = nickname or (f"{username}@{host}" if username else host)
    return ImportedSite(
        name=name,
        protocol=protocol,
        host=host,
        port=port,
        username=username,
        initial_dir=initial_dir,
    )


def parse_bookmarks_dir(path: Path) -> list[ImportedSite]:
    """Parse all Cyberduck bookmarks in a directory."""
    sites: list[ImportedSite] = []
    if not path.exists():
        return sites

    for bookmark_path in sorted(path.glob("*.duck")):
        try:
            site = parse_bookmark_file(bookmark_path)
        except Exception:
            continue
        if site.host:
            sites.append(site)

    return sites


def _map_protocol(protocol: str) -> str:
    return _PROTOCOL_MAP.get(protocol.lower(), "sftp")
