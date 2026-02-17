"""Site Manager - saved connection profiles."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from portkeydrop.protocols import ConnectionInfo, Protocol

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_DIR = Path.home() / ".portkeydrop"
KEYRING_SERVICE = "portkeydrop"

try:
    import keyring

    _has_keyring = True
except ImportError:
    _has_keyring = False


def _store_password(site_id: str, password: str) -> None:
    """Store a password in the system keyring."""
    if not _has_keyring or not password:
        return
    try:
        keyring.set_password(KEYRING_SERVICE, site_id, password)
    except Exception as e:
        logger.warning(f"Failed to store password in keyring: {e}")


def _retrieve_password(site_id: str) -> str:
    """Retrieve a password from the system keyring."""
    if not _has_keyring:
        return ""
    try:
        pw = keyring.get_password(KEYRING_SERVICE, site_id)
        return pw or ""
    except Exception as e:
        logger.warning(f"Failed to retrieve password from keyring: {e}")
        return ""


def _delete_password(site_id: str) -> None:
    """Delete a password from the system keyring."""
    if not _has_keyring:
        return
    try:
        keyring.delete_password(KEYRING_SERVICE, site_id)
    except Exception as e:
        logger.debug(f"Failed to delete password from keyring: {e}")


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
            # Retrieve passwords from keyring; migrate any leftover plaintext passwords
            for site in self._sites:
                stored_pw = _retrieve_password(site.id)
                if stored_pw:
                    site.password = stored_pw
                elif site.password:
                    # Migrate plaintext password to keyring
                    _store_password(site.id, site.password)
        except Exception as e:
            logger.warning(f"Failed to load sites: {e}")
            self._sites = []

    def save(self) -> None:
        self._config_dir.mkdir(parents=True, exist_ok=True)
        # Store passwords in keyring, strip from JSON
        for site in self._sites:
            if site.password:
                _store_password(site.id, site.password)
        data = []
        for site in self._sites:
            d = asdict(site)
            if _has_keyring:
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
        _delete_password(site_id)
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
