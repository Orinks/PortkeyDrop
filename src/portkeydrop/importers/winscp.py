"""WinSCP profile importer (INI + optional Windows Registry)."""

from __future__ import annotations

import configparser
import logging
import os
import sys
from pathlib import Path
from urllib.parse import unquote

from .models import ImportedSite

logger = logging.getLogger(__name__)

_MAGIC = 0xA3

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
        password = _safe_decrypt(cfg.get("Password", "").strip(), username, host)

        sites.append(
            ImportedSite(
                name=name,
                protocol=protocol,
                host=host,
                port=port,
                username=username,
                password=password,
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
                    password = _safe_decrypt(values.get("Password", "").strip(), username, host)

                    sites.append(
                        ImportedSite(
                            name=_decode_name(session_name),
                            protocol=protocol,
                            host=host,
                            port=port,
                            username=username,
                            password=password,
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


def _safe_decrypt(encrypted: str, username: str, hostname: str) -> str:
    """Decrypt a WinSCP password, returning empty string on any failure."""
    if not encrypted:
        return ""
    try:
        return _decrypt_winscp_password(username, hostname, encrypted)
    except Exception:
        logger.debug("Failed to decrypt WinSCP password for %s@%s", username, hostname)
        return ""


def _decrypt_winscp_password(username: str, hostname: str, encrypted: str) -> str:
    """Decrypt a WinSCP XOR-obfuscated password.

    Algorithm reference: https://github.com/NetSPI/WinSCPPasswordDecryptor
    """
    key = username + hostname
    encrypted_bytes = [int(encrypted[i : i + 2], 16) for i in range(0, len(encrypted), 2)]

    flag = _decrypt_next(encrypted_bytes)
    if flag == _MAGIC:
        _decrypt_next(encrypted_bytes)  # skip byte
        length = _decrypt_next(encrypted_bytes)
    else:
        length = flag

    result: list[str] = []
    for _ in range(length):
        result.append(chr(_decrypt_next(encrypted_bytes) ^ _MAGIC))

    password = "".join(result)
    if flag == _MAGIC:
        password = password[len(key) :]
    return password


def _decrypt_next(encrypted_bytes: list[int]) -> int:
    """Consume two values from the byte list and return one decrypted byte."""
    a = encrypted_bytes.pop(0)
    b = encrypted_bytes.pop(0)
    return (((a << 4) + b) ^ _MAGIC) & 0xFF
