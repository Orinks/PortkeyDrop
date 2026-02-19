"""Settings management for Portkey Drop."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_DIR = Path.home() / ".portkeydrop"


@dataclass
class TransferSettings:
    concurrent_transfers: int = 2
    overwrite_mode: str = "ask"  # ask, overwrite, skip, rename
    resume_partial: bool = True
    preserve_timestamps: bool = True
    follow_symlinks: bool = False
    default_download_dir: str = str(Path.home() / "Downloads")


@dataclass
class DisplaySettings:
    announce_file_count: bool = True
    progress_interval: int = 25  # announce every N%
    show_hidden_files: bool = False
    sort_by: str = "name"  # name, size, modified, type
    sort_ascending: bool = True
    date_format: str = "relative"  # relative, absolute


@dataclass
class ConnectionDefaults:
    protocol: str = "sftp"
    timeout: int = 30
    keepalive: int = 60
    max_retries: int = 3
    passive_mode: bool = True  # FTP only
    verify_host_keys: str = "ask"  # ask, always, never


@dataclass
class SpeechSettings:
    rate: int = 50
    volume: int = 100
    verbosity: str = "normal"  # minimal, normal, verbose


@dataclass
class AppSettings:
    remember_last_local_folder_on_startup: bool = True
    last_local_folder: str | None = None


@dataclass
class Settings:
    transfer: TransferSettings = field(default_factory=TransferSettings)
    display: DisplaySettings = field(default_factory=DisplaySettings)
    connection: ConnectionDefaults = field(default_factory=ConnectionDefaults)
    speech: SpeechSettings = field(default_factory=SpeechSettings)
    app: AppSettings = field(default_factory=AppSettings)


def load_settings(config_dir: Path = DEFAULT_CONFIG_DIR) -> Settings:
    """Load settings from disk, returning defaults if file doesn't exist."""
    settings_path = config_dir / "settings.json"
    if not settings_path.exists():
        return Settings()
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        return _dict_to_settings(data)
    except Exception as e:
        logger.warning(f"Failed to load settings: {e}")
        return Settings()


def save_settings(settings: Settings, config_dir: Path = DEFAULT_CONFIG_DIR) -> None:
    """Save settings to disk."""
    config_dir.mkdir(parents=True, exist_ok=True)
    settings_path = config_dir / "settings.json"
    data = asdict(settings)
    if not settings.app.remember_last_local_folder_on_startup:
        data["app"]["last_local_folder"] = None
    settings_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def resolve_startup_local_folder(settings: Settings, fallback: str | None = None) -> str:
    """Return the local folder to use on startup, falling back safely when needed."""
    fallback_path = str(Path.home() if fallback is None else Path(fallback))
    if not settings.app.remember_last_local_folder_on_startup:
        return fallback_path

    saved = settings.app.last_local_folder
    if not saved:
        return fallback_path

    path = Path(saved).expanduser()
    if path.is_dir():
        return str(path.resolve())

    logger.warning("Saved local folder is unavailable: %s", saved)
    settings.app.last_local_folder = None
    return fallback_path


def update_last_local_folder(settings: Settings, path: str) -> bool:
    """Update remembered local folder according to current app settings.

    Returns True if settings were mutated.
    """
    if not settings.app.remember_last_local_folder_on_startup:
        if settings.app.last_local_folder is not None:
            settings.app.last_local_folder = None
            return True
        return False

    resolved = str(Path(path).expanduser().resolve())
    if settings.app.last_local_folder == resolved:
        return False
    settings.app.last_local_folder = resolved
    return True


def _dict_to_settings(data: dict) -> Settings:
    """Convert a dictionary to Settings, filling in defaults for missing keys."""
    return Settings(
        transfer=TransferSettings(
            **{
                k: v
                for k, v in data.get("transfer", {}).items()
                if k in TransferSettings.__dataclass_fields__
            }
        ),
        display=DisplaySettings(
            **{
                k: v
                for k, v in data.get("display", {}).items()
                if k in DisplaySettings.__dataclass_fields__
            }
        ),
        connection=ConnectionDefaults(
            **{
                k: v
                for k, v in data.get("connection", {}).items()
                if k in ConnectionDefaults.__dataclass_fields__
            }
        ),
        speech=SpeechSettings(
            **{
                k: v
                for k, v in data.get("speech", {}).items()
                if k in SpeechSettings.__dataclass_fields__
            }
        ),
        app=AppSettings(
            **{
                k: v
                for k, v in data.get("app", {}).items()
                if k in AppSettings.__dataclass_fields__
            }
        ),
    )
