"""PuTTY PPK key file support for PortkeyDrop.

Converts PuTTY PPK (v2) private key files to paramiko PKey objects
in-memory, without writing anything to disk.

Supports RSA and Ed25519 key types. PPK v3 is not yet supported by the
underlying parser; users with v3 keys can convert them to OpenSSH format
using PuTTYgen.
"""

from __future__ import annotations

import logging
from io import StringIO
from pathlib import Path

import paramiko

logger = logging.getLogger(__name__)


def is_ppk_file(path: str) -> bool:
    """Return True if the given path looks like a PuTTY PPK key file."""
    return Path(path).suffix.lower() == ".ppk"


def load_ppk_key(path: str, passphrase: str | None = None) -> paramiko.PKey:
    """Load a PuTTY PPK key file and return a paramiko PKey object.

    Args:
        path: Path to the .ppk file.
        passphrase: Passphrase to decrypt the key, or None for unencrypted keys.

    Returns:
        A paramiko PKey instance (RSAKey, Ed25519Key, etc.).

    Raises:
        ValueError: If the PPK format is unsupported or the passphrase is wrong.
        FileNotFoundError: If the key file does not exist.
        ImportError: If the puttykeys dependency is not installed.
    """
    try:
        import puttykeys
    except ImportError as exc:
        raise ImportError(
            "puttykeys is required for PPK key support. "
            "Install it with: pip install puttykeys"
        ) from exc

    key_path = Path(path)
    if not key_path.exists():
        raise FileNotFoundError(f"PPK key file not found: {path}")

    raw = key_path.read_text(encoding="utf-8", errors="replace")

    try:
        openssh_pem = puttykeys.ppkraw_to_openssh(raw, passphrase or "")
    except ValueError as exc:
        # Bad passphrase or corrupt key
        raise ValueError(f"Failed to decrypt PPK key '{path}': {exc}") from exc
    except SyntaxError as exc:
        raise ValueError(f"Invalid or unsupported PPK format in '{path}': {exc}") from exc
    except Exception as exc:
        raise ValueError(f"Could not parse PPK key '{path}': {exc}") from exc

    try:
        pkey = paramiko.PKey.from_private_key(StringIO(openssh_pem))
    except paramiko.PasswordRequiredException:
        # Should not happen (puttykeys already decrypted), but handle gracefully
        raise ValueError(
            f"PPK key '{path}' requires a passphrase. Please provide one."
        )
    except paramiko.SSHException as exc:
        raise ValueError(f"Could not load converted PPK key '{path}': {exc}") from exc

    logger.debug("Loaded PPK key from '%s' (type: %s)", path, type(pkey).__name__)
    return pkey
