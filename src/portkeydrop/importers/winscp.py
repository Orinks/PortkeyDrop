"""WinSCP profile importer (INI + optional Windows Registry)."""

from __future__ import annotations

import configparser
import os
import sys
from pathlib import Path
from urllib.parse import unquote

from .models import ImportedSite


_NUMERIC_PROTOCOL_MAP = {
    "0": "sftp",
    "1": "scp",
    "5": "ftp",
    "6": "ftps",
}


def detect_ini_path() -> Path:
    """Return likely WinSCP INI path."""
    appdata = os.environ.get("APPDATA", "")
    if appdata:
        return Path(appdata) / "WinSCP.ini"
    return Path.home() / "WinSCP.ini"


def parse_ini_file(path: Path) -> list[ImportedSite]:
    """Parse WinSCP exported INI file."""
    parser = configparser.RawConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read(path, encoding="utf-8")

    sites: list[ImportedSite] = []
    for section in parser.sections():
        if not section.startswith("Sessions\\"):
            continue

        cfg = parser[section]
        host = cfg.get("HostName", "").strip()
        if not host:
            continue

        raw_port = cfg.get("PortNumber", "").strip()
        port = int(raw_port) if raw_port.isdigit() else 0

        protocol = _detect_protocol(cfg)
        if protocol == "scp":
            protocol = "sftp"

        username = cfg.get("UserName", "").strip()
        initial_dir = cfg.get("RemoteDirectory", "").strip() or "/"
        key_path = cfg.get("PublicKeyFile", "").strip()
        name = _decode_name(section.removeprefix("Sessions\\"))

        sites.append(
            ImportedSite(
                name=name,
                protocol=protocol,
                host=host,
                port=port,
                username=username,
                key_path=key_path,
                initial_dir=initial_dir,
            )
        )
    return sites


def parse_registry_sessions() -> list[ImportedSite]:
    """Parse WinSCP session data from Windows Registry if available."""
    if sys.platform != "win32":
        return []

    try:
        import winreg
    except Exception:
        return []

    key_path = r"Software\Martin Prikryl\WinSCP 2\Sessions"
    sites: list[ImportedSite] = []

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as sessions_key:
            index = 0
            while True:
                try:
                    session_name = winreg.EnumKey(sessions_key, index)
                except OSError:
                    break
                index += 1

                with winreg.OpenKey(sessions_key, session_name) as session_key:
                    values = _read_reg_values(winreg, session_key)
                    host = values.get("HostName", "").strip()
                    if not host:
                        continue

                    raw_port = values.get("PortNumber", "").strip()
                    port = int(raw_port) if raw_port.isdigit() else 0

                    protocol = _detect_protocol(values)
                    if protocol == "scp":
                        protocol = "sftp"

                    username = values.get("UserName", "").strip()
                    initial_dir = values.get("RemoteDirectory", "").strip() or "/"
                    key_path_value = values.get("PublicKeyFile", "").strip()

                    sites.append(
                        ImportedSite(
                            name=_decode_name(session_name),
                            protocol=protocol,
                            host=host,
                            port=port,
                            username=username,
                            key_path=key_path_value,
                            initial_dir=initial_dir,
                        )
                    )
    except OSError:
        return []

    return sites


def _read_reg_values(winreg, key) -> dict[str, str]:
    values: dict[str, str] = {}
    idx = 0
    while True:
        try:
            value_name, value, _ = winreg.EnumValue(key, idx)
        except OSError:
            break
        idx += 1
        values[value_name] = str(value)
    return values


def _detect_protocol(cfg: configparser.SectionProxy | dict[str, str]) -> str:
    protocol_value = str(cfg.get("FSProtocol", "")).strip()
    if protocol_value in _NUMERIC_PROTOCOL_MAP:
        return _NUMERIC_PROTOCOL_MAP[protocol_value]

    file_protocol = str(cfg.get("FileProtocol", "")).strip().lower()
    if file_protocol in {"ftp", "ftps", "sftp", "scp"}:
        return file_protocol

    if str(cfg.get("Ftps", "")).strip() in {"1", "true", "True"}:
        return "ftps"

    return "sftp"


def _decode_name(raw_name: str) -> str:
    return unquote(raw_name).replace("%5C", "\\")
