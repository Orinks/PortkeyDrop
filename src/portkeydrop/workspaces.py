"""Saved local/remote workspace bookmarks."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from portkeydrop.portable import get_config_dir

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_DIR = get_config_dir()


@dataclass
class WorkspaceBookmark:
    """A non-secret bookmark pairing a local folder with a remote folder."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    local_path: str = ""
    remote_path: str = "/"


class WorkspaceManager:
    """Manages saved workspace bookmarks."""

    def __init__(self, config_dir: Path = DEFAULT_CONFIG_DIR) -> None:
        self._config_dir = config_dir
        self._workspaces_path = config_dir / "workspaces.json"
        self._workspaces: list[WorkspaceBookmark] = []
        self.load()

    def load(self) -> None:
        if not self._workspaces_path.exists():
            self._workspaces = []
            return
        try:
            data = json.loads(self._workspaces_path.read_text(encoding="utf-8"))
            self._workspaces = [
                WorkspaceBookmark(
                    **{
                        key: value
                        for key, value in item.items()
                        if key in WorkspaceBookmark.__dataclass_fields__
                    }
                )
                for item in data
                if isinstance(item, dict)
            ]
        except Exception as exc:
            logger.warning(f"Failed to load workspaces: {exc}")
            self._workspaces = []

    def save(self) -> None:
        self._config_dir.mkdir(parents=True, exist_ok=True)
        data = [asdict(workspace) for workspace in self._workspaces]
        self._workspaces_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @property
    def workspaces(self) -> list[WorkspaceBookmark]:
        return list(self._workspaces)

    def add(self, workspace: WorkspaceBookmark) -> None:
        self._workspaces.append(workspace)
        self.save()

    def remove(self, workspace_id: str) -> None:
        self._workspaces = [
            workspace for workspace in self._workspaces if workspace.id != workspace_id
        ]
        self.save()

    def get(self, workspace_id: str) -> WorkspaceBookmark | None:
        for workspace in self._workspaces:
            if workspace.id == workspace_id:
                return workspace
        return None

    def find_by_name(self, name: str) -> WorkspaceBookmark | None:
        for workspace in self._workspaces:
            if workspace.name.lower() == name.lower():
                return workspace
        return None
