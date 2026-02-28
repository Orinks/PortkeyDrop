"""FileZilla Site Manager importer."""

from __future__ import annotations

import base64
import os
import xml.etree.ElementTree as ET
from pathlib import Path

from .models import ImportedSite

_PROTOCOL_MAP = {
    "0": "ftp",
    "1": "sftp",
    "3": "ftps",
    "4": "ftps",
}


def detect_path() -> Path:
    """Return default FileZilla Site Manager path for current platform."""
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        return Path(appdata) / "FileZilla" / "sitemanager.xml"
    return Path.home() / ".config" / "filezilla" / "sitemanager.xml"


def parse_file(path: Path) -> list[ImportedSite]:
    """Parse a FileZilla `sitemanager.xml` file."""
    root = ET.parse(path).getroot()
    return _parse_root(root)


def _parse_root(root: ET.Element) -> list[ImportedSite]:
    sites: list[ImportedSite] = []
    for server in root.findall(".//Server"):
        host = (server.findtext("Host") or "").strip()
        if not host:
            continue

        raw_protocol = (server.findtext("Protocol") or "1").strip()
        protocol = _PROTOCOL_MAP.get(raw_protocol, "sftp")

        raw_port = (server.findtext("Port") or "").strip()
        port = int(raw_port) if raw_port.isdigit() else 0

        username = (server.findtext("User") or "").strip()
        password = _decode_password(server)

        raw_remote_dir = (server.findtext("RemoteDir") or "").strip()
        initial_dir = _parse_remote_dir(raw_remote_dir)

        name = (server.findtext("Name") or f"{username}@{host}" or host).strip() or host
        notes = (server.findtext("Comments") or "").strip()

        sites.append(
            ImportedSite(
                name=name,
                protocol=protocol,
                host=host,
                port=port,
                username=username,
                password=password,
                initial_dir=initial_dir,
                notes=notes,
            )
        )
    return sites


def _decode_password(server: ET.Element) -> str:
    raw_password = (server.findtext("Pass") or "").strip()
    if not raw_password:
        return ""

    pass_element = server.find("Pass")
    encoding = pass_element.get("encoding", "") if pass_element is not None else ""
    if encoding.lower() == "base64":
        try:
            return base64.b64decode(raw_password).decode("utf-8")
        except Exception:
            return ""
    return raw_password


def _parse_remote_dir(raw_remote_dir: str) -> str:
    if not raw_remote_dir:
        return "/"

    # FileZilla stores path segments in an integer-prefixed format:
    # e.g. "1 0 4 home 4 user" => "/home/user".
    tokens = raw_remote_dir.split()
    if len(tokens) >= 2 and tokens[0].isdigit() and tokens[1].isdigit():
        segments: list[str] = []
        i = 2
        while i < len(tokens):
            if not tokens[i].isdigit():
                break
            length = int(tokens[i])
            i += 1
            if i >= len(tokens):
                break
            segment = tokens[i]
            i += 1
            segments.append(segment[:length])
        if segments:
            return "/" + "/".join(segment.strip("/") for segment in segments if segment)

    if raw_remote_dir.startswith("/"):
        return raw_remote_dir
    return "/" + raw_remote_dir.lstrip("/")
