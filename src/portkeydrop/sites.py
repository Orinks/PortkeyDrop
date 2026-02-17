"""Site Manager - saved connection profiles."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import platform
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from portkeydrop.protocols import ConnectionInfo, Protocol

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_DIR = Path.home() / ".portkeydrop"
KEYRING_SERVICE = "portkeydrop"

# --- Tier 1: System keyring ---

try:
    import keyring as _keyring_mod

    _has_keyring = True
except ImportError:
    _keyring_mod = None  # type: ignore[assignment]
    _has_keyring = False

# --- Tier 2: Encrypted local vault (Fernet) ---

try:
    from cryptography.fernet import Fernet, InvalidToken

    _has_fernet = True
except ImportError:
    Fernet = None  # type: ignore[assignment, misc]
    InvalidToken = Exception  # type: ignore[assignment, misc]
    _has_fernet = False


def _derive_machine_key() -> bytes:
    """Derive a Fernet key from machine-specific values.

    Uses platform node (hostname) + login username as seed material.
    Not meant to be unbreakable; just prevents casual reading of the vault file.
    """
    seed = f"portkeydrop:{platform.node()}:{_get_username()}"
    digest = hashlib.sha256(seed.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _get_username() -> str:
    """Get current username, cross-platform."""
    try:
        import getpass

        return getpass.getuser()
    except Exception:
        return "unknown"


class _VaultStore:
    """Encrypted local password vault using Fernet."""

    def __init__(self, vault_path: Path) -> None:
        self._path = vault_path
        self._key = _derive_machine_key()
        self._data: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            self._data = {}
            return
        try:
            f = Fernet(self._key)
            encrypted = self._path.read_bytes()
            decrypted = f.decrypt(encrypted)
            self._data = json.loads(decrypted)
        except (InvalidToken, Exception) as e:
            logger.warning(f"Failed to decrypt vault (machine changed?): {e}")
            self._data = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        f = Fernet(self._key)
        plaintext = json.dumps(self._data).encode()
        self._path.write_bytes(f.encrypt(plaintext))

    def get(self, key: str) -> str:
        return self._data.get(key, "")

    def set(self, key: str, value: str) -> None:
        self._data[key] = value
        self._save()

    def delete(self, key: str) -> None:
        if key in self._data:
            del self._data[key]
            self._save()


# --- Unified password backend ---


class _PasswordBackend:
    """Three-tier password storage: keyring > encrypted vault > no storage."""

    def __init__(self, config_dir: Path) -> None:
        self._vault: _VaultStore | None = None
        if _has_keyring:
            self._tier = "keyring"
        elif _has_fernet:
            self._tier = "vault"
            self._vault = _VaultStore(config_dir / "vault.enc")
        else:
            self._tier = "none"
            logger.warning(
                "Neither keyring nor cryptography available. "
                "Passwords will not be saved between sessions."
            )

    @property
    def can_store(self) -> bool:
        return self._tier != "none"

    def store(self, site_id: str, password: str) -> None:
        if not password:
            return
        if self._tier == "keyring":
            try:
                _keyring_mod.set_password(KEYRING_SERVICE, site_id, password)
            except Exception as e:
                logger.warning(f"Keyring store failed: {e}")
        elif self._tier == "vault" and self._vault:
            self._vault.set(site_id, password)

    def retrieve(self, site_id: str) -> str:
        if self._tier == "keyring":
            try:
                pw = _keyring_mod.get_password(KEYRING_SERVICE, site_id)
                return pw or ""
            except Exception as e:
                logger.warning(f"Keyring retrieve failed: {e}")
                return ""
        elif self._tier == "vault" and self._vault:
            return self._vault.get(site_id)
        return ""

    def delete(self, site_id: str) -> None:
        if self._tier == "keyring":
            try:
                _keyring_mod.delete_password(KEYRING_SERVICE, site_id)
            except Exception as e:
                logger.debug(f"Keyring delete failed: {e}")
        elif self._tier == "vault" and self._vault:
            self._vault.delete(site_id)


@dataclass
class Site:
    """A saved connection profile."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    protocol: str = "sftp"
    host: str = ""
    port: int = 0
    username: str = ""
    password: str = ""
    key_path: str = ""
    initial_dir: str = "/"
    notes: str = ""

    def to_connection_info(self) -> ConnectionInfo:
        return ConnectionInfo(
            protocol=Protocol(self.protocol),
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            key_path=self.key_path,
        )


class SiteManager:
    """Manages saved connection profiles."""

    def __init__(self, config_dir: Path = DEFAULT_CONFIG_DIR) -> None:
        self._config_dir = config_dir
        self._sites_path = config_dir / "sites.json"
        self._sites: list[Site] = []
        self._passwords = _PasswordBackend(config_dir)
        self.load()

    def load(self) -> None:
        if not self._sites_path.exists():
            self._sites = []
            return
        try:
            data = json.loads(self._sites_path.read_text(encoding="utf-8"))
            self._sites = [
                Site(**{k: v for k, v in s.items() if k in Site.__dataclass_fields__}) for s in data
            ]
            for site in self._sites:
                stored_pw = self._passwords.retrieve(site.id)
                if stored_pw:
                    site.password = stored_pw
                elif site.password:
                    # Migrate plaintext password to secure storage
                    self._passwords.store(site.id, site.password)
        except Exception as e:
            logger.warning(f"Failed to load sites: {e}")
            self._sites = []

    def save(self) -> None:
        self._config_dir.mkdir(parents=True, exist_ok=True)
        for site in self._sites:
            if site.password:
                self._passwords.store(site.id, site.password)
        data = []
        for site in self._sites:
            d = asdict(site)
            # Never write passwords to disk in plaintext
            d.pop("password", None)
            data.append(d)
        self._sites_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @property
    def sites(self) -> list[Site]:
        return list(self._sites)

    def add(self, site: Site) -> None:
        self._sites.append(site)
        self.save()

    def update(self, site: Site) -> None:
        for i, s in enumerate(self._sites):
            if s.id == site.id:
                self._sites[i] = site
                self.save()
                return
        raise ValueError(f"Site {site.id} not found")

    def remove(self, site_id: str) -> None:
        self._passwords.delete(site_id)
        self._sites = [s for s in self._sites if s.id != site_id]
        self.save()

    def get(self, site_id: str) -> Site | None:
        for s in self._sites:
            if s.id == site_id:
                return s
        return None

    def find_by_name(self, name: str) -> Site | None:
        for s in self._sites:
            if s.name.lower() == name.lower():
                return s
        return None
