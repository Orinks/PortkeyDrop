"""Local filesystem operations returning RemoteFile-compatible objects."""

from __future__ import annotations

import logging
import shutil
import stat
from datetime import datetime
from pathlib import Path

from accessitransfer.protocols import RemoteFile

logger = logging.getLogger(__name__)


def list_local_dir(directory: str | Path) -> list[RemoteFile]:
    """List contents of a local directory, returning RemoteFile objects."""
    directory = Path(directory)
    files: list[RemoteFile] = []
    try:
        for entry in directory.iterdir():
            try:
                st = entry.stat()
                is_dir = entry.is_dir()
                modified = datetime.fromtimestamp(st.st_mtime)
                perms = stat.filemode(st.st_mode)
                files.append(
                    RemoteFile(
                        name=entry.name,
                        path=str(entry),
                        size=0 if is_dir else st.st_size,
                        is_dir=is_dir,
                        modified=modified,
                        permissions=perms,
                    )
                )
            except (PermissionError, OSError) as e:
                logger.debug("Cannot stat %s: %s", entry, e)
                files.append(
                    RemoteFile(
                        name=entry.name,
                        path=str(entry),
                        permissions="?",
                    )
                )
    except PermissionError as e:
        logger.warning("Cannot list directory %s: %s", directory, e)
    return files


def navigate_local(current: str | Path, target: str) -> Path:
    """Navigate to a target directory. Returns the resolved absolute path."""
    target_path = Path(current) / target
    resolved = target_path.resolve()
    if not resolved.is_dir():
        raise NotADirectoryError(f"{resolved} is not a directory")
    return resolved


def parent_local(current: str | Path) -> Path:
    """Navigate to parent directory."""
    return Path(current).resolve().parent


def delete_local(path: str | Path) -> None:
    """Delete a local file or directory."""
    p = Path(path)
    if p.is_dir():
        shutil.rmtree(p)
    else:
        p.unlink()


def rename_local(old_path: str | Path, new_name: str) -> Path:
    """Rename a local file or directory. Returns the new path."""
    old = Path(old_path)
    new = old.parent / new_name
    old.rename(new)
    return new


def mkdir_local(parent: str | Path, name: str) -> Path:
    """Create a new directory. Returns the path."""
    new_dir = Path(parent) / name
    new_dir.mkdir(parents=False, exist_ok=False)
    return new_dir
