"""Site Manager - saved connection profiles."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from accessitransfer.protocols import ConnectionInfo, Protocol

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_DIR = Path.home() / ".accessitransfer"


@dataclass
class Site:
    """A saved connection profile."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    protocol: str = "sftp"
    host: str = ""
    port: int = 0
    username: str = ""
    password: str = ""  # TODO: use keyring for secure storage
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
                Site(**{k: v for k, v in s.items() if k in Site.__dataclass_fields__})
                for s in data
            ]
        except Exception as e:
            logger.warning(f"Failed to load sites: {e}")
            self._sites = []

    def save(self) -> None:
        self._config_dir.mkdir(parents=True, exist_ok=True)
        data = [asdict(s) for s in self._sites]
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
