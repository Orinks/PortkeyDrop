"""Directory comparison helpers for local/remote file panes."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from portkeydrop.protocols import RemoteFile


class CompareAction(Enum):
    """Preview action for a local/remote directory comparison row."""

    SAME = "same"
    UPLOAD = "upload"
    DOWNLOAD = "download"
    LOCAL_NEWER = "local_newer"
    REMOTE_NEWER = "remote_newer"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class CompareRow:
    """One named item in a directory comparison."""

    name: str
    action: CompareAction
    local: RemoteFile | None = None
    remote: RemoteFile | None = None
    detail: str = ""

    @property
    def action_label(self) -> str:
        labels = {
            CompareAction.SAME: "No action",
            CompareAction.UPLOAD: "Upload",
            CompareAction.DOWNLOAD: "Download",
            CompareAction.LOCAL_NEWER: "Upload newer local",
            CompareAction.REMOTE_NEWER: "Download newer remote",
            CompareAction.CONFLICT: "Review conflict",
        }
        return labels[self.action]

    @property
    def speech(self) -> str:
        detail = f", {self.detail}" if self.detail else ""
        return f"{self.name}: {self.action_label}{detail}"


@dataclass(frozen=True)
class CompareResult:
    """Complete directory comparison result."""

    rows: tuple[CompareRow, ...]

    @property
    def summary_counts(self) -> Counter[CompareAction]:
        return Counter(row.action for row in self.rows)

    @property
    def summary(self) -> str:
        counts = self.summary_counts
        parts = [
            f"{len(self.rows)} item{'s' if len(self.rows) != 1 else ''}",
            f"{counts[CompareAction.UPLOAD] + counts[CompareAction.LOCAL_NEWER]} upload",
            f"{counts[CompareAction.DOWNLOAD] + counts[CompareAction.REMOTE_NEWER]} download",
            f"{counts[CompareAction.CONFLICT]} conflict",
            f"{counts[CompareAction.SAME]} unchanged",
        ]
        return ", ".join(parts)


def compare_directories(
    local_files: list[RemoteFile], remote_files: list[RemoteFile]
) -> CompareResult:
    """Compare two current-directory file lists by name.

    Parent-directory entries are ignored. The result is read-only: actions describe
    what a future sync preview would do, but no transfer jobs are created here.
    """

    local_by_name = _index_by_name(local_files)
    remote_by_name = _index_by_name(remote_files)
    names = sorted(set(local_by_name) | set(remote_by_name), key=str.casefold)
    rows = tuple(
        _compare_name(name, local_by_name.get(name), remote_by_name.get(name)) for name in names
    )
    return CompareResult(rows=rows)


def _index_by_name(files: list[RemoteFile]) -> dict[str, RemoteFile]:
    return {file.name: file for file in files if file.name != ".."}


def _compare_name(name: str, local: RemoteFile | None, remote: RemoteFile | None) -> CompareRow:
    if local is None and remote is not None:
        return CompareRow(
            name=name, action=CompareAction.DOWNLOAD, remote=remote, detail="remote only"
        )
    if remote is None and local is not None:
        return CompareRow(name=name, action=CompareAction.UPLOAD, local=local, detail="local only")
    if local is None or remote is None:  # pragma: no cover - guarded above
        raise AssertionError("comparison row needs at least one side")

    if local.is_dir != remote.is_dir:
        return CompareRow(
            name=name,
            action=CompareAction.CONFLICT,
            local=local,
            remote=remote,
            detail="file type differs",
        )
    if local.is_dir and remote.is_dir:
        return CompareRow(
            name=name, action=CompareAction.SAME, local=local, remote=remote, detail="directory"
        )
    if local.size != remote.size:
        return _newer_row(
            name,
            local,
            remote,
            f"size differs: {local.display_size} local, {remote.display_size} remote",
        )
    if _same_modified(local.modified, remote.modified):
        return CompareRow(
            name=name,
            action=CompareAction.SAME,
            local=local,
            remote=remote,
            detail="same size and date",
        )
    return _newer_row(name, local, remote, "same size, modified date differs")


def _newer_row(name: str, local: RemoteFile, remote: RemoteFile, detail: str) -> CompareRow:
    if local.modified and remote.modified:
        if local.modified > remote.modified:
            return CompareRow(
                name=name,
                action=CompareAction.LOCAL_NEWER,
                local=local,
                remote=remote,
                detail=detail,
            )
        if remote.modified > local.modified:
            return CompareRow(
                name=name,
                action=CompareAction.REMOTE_NEWER,
                local=local,
                remote=remote,
                detail=detail,
            )
    return CompareRow(
        name=name, action=CompareAction.CONFLICT, local=local, remote=remote, detail=detail
    )


def _same_modified(left: datetime | None, right: datetime | None) -> bool:
    if left is None or right is None:
        return left is right
    return int(left.timestamp()) == int(right.timestamp())
