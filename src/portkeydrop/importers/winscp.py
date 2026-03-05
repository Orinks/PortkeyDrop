"""WinSCP profile importer (INI + optional Windows Registry)."""

from __future__ import annotations

import configparser
import locale
import logging
import os
import sys
from pathlib import Path
from urllib.parse import unquote

from .models import ImportedSite

logger = logging.getLogger(__name__)

_MAGIC = 0xA3
_PWALG_SIMPLE_FLAG = 0xFF
_PWALG_SIMPLE_INTERNAL = 0x00
_PWALG_SIMPLE_EXTERNAL = 0x01
_PWALG_SIMPLE_INTERNAL2 = 0x02

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
    parser = configparser.RawConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    parser.read_string(_read_ini_text(path), source=str(path))

    sites: list[ImportedSite] = []
    for section in parser.sections():
        if not section.startswith("Sessions\\"):
            continue

        parsed = _parse_site(parser[section], section.removeprefix("Sessions\\"))
        if parsed is not None:
            sites.append(parsed)
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
                    parsed = _parse_site(values, session_name)
                    if parsed is not None:
                        sites.append(parsed)
    except OSError:
        return []

    return sites


def _read_ini_text(path: Path) -> str:
    data = path.read_bytes()
    tried: set[str] = set()
    encodings = [
        "utf-8-sig",
        "utf-16",
        "utf-16-le",
        "utf-16-be",
        locale.getpreferredencoding(False),
        "cp1252",
        "latin-1",
    ]
    for encoding in encodings:
        if not encoding or encoding in tried:
            continue
        tried.add(encoding)
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _parse_site(
    cfg: configparser.SectionProxy | dict[str, str], raw_name: str
) -> ImportedSite | None:
    host = _decode_value(str(cfg.get("HostName", "")).strip())
    if not host:
        return None

    raw_port = str(cfg.get("PortNumber", "")).strip()
    port = int(raw_port) if raw_port.isdigit() else 0

    protocol = _detect_protocol(cfg)
    if protocol == "scp":
        protocol = "sftp"

    username = str(cfg.get("UserName", "")).strip()
    initial_dir = _decode_value(str(cfg.get("RemoteDirectory", "")).strip()) or "/"
    key_path = _decode_value(str(cfg.get("PublicKeyFile", "")).strip())
    name = _decode_name(raw_name)
    password = _safe_decrypt(str(cfg.get("Password", "")).strip(), username, host)

    return ImportedSite(
        name=name,
        protocol=protocol,
        host=host,
        port=port,
        username=username,
        password=password,
        key_path=key_path,
        initial_dir=initial_dir,
    )


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
    return _decode_value(raw_name).replace("%5C", "\\")


def _decode_value(value: str) -> str:
    if not value:
        return ""
    return unquote(value)


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

    Algorithm reference: WinSCP source `source/core/Security.cpp`
    """
    if len(encrypted) % 2 != 0:
        raise ValueError("Encrypted WinSCP password must be even-length hex")
    encrypted_hex = [encrypted[i : i + 2] for i in range(0, len(encrypted), 2)]

    flag = _decrypt_next(encrypted_hex)
    if flag == _PWALG_SIMPLE_FLAG:
        version = _decrypt_next(encrypted_hex)
        if version == _PWALG_SIMPLE_INTERNAL:
            length = _decrypt_next(encrypted_hex)
        elif version == _PWALG_SIMPLE_INTERNAL2:
            length = (_decrypt_next(encrypted_hex) << 8) + _decrypt_next(encrypted_hex)
        elif version == _PWALG_SIMPLE_EXTERNAL:
            raise ValueError("WinSCP external/master-password encrypted value is unsupported")
        else:
            raise ValueError(f"Unsupported WinSCP password version: {version}")
    else:
        length = flag

    shift = _decrypt_next(encrypted_hex)
    for _ in range(shift):
        _decrypt_next(encrypted_hex)

    result: list[int] = []
    for _ in range(length):
        result.append(_decrypt_next(encrypted_hex))

    password_bytes = bytes(result)
    if flag == _PWALG_SIMPLE_FLAG:
        key = (username + hostname).encode("utf-8")
        if not password_bytes.startswith(key):
            raise ValueError("Decrypted WinSCP payload key-prefix mismatch")
        password_bytes = password_bytes[len(key) :]

    return password_bytes.decode("utf-8")


def _decrypt_next(encrypted_hex: list[str]) -> int:
    """Consume one hex-encoded byte and return one decrypted byte."""
    if not encrypted_hex:
        raise ValueError("Unexpected end of encrypted WinSCP payload")
    b = int(encrypted_hex.pop(0), 16)
    return (~(b ^ _MAGIC)) & 0xFF
