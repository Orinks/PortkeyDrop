from __future__ import annotations

from datetime import datetime

from portkeydrop.directory_compare import CompareAction, compare_directories
from portkeydrop.protocols import RemoteFile


def _file(name: str, size: int = 10, modified: datetime | None = None) -> RemoteFile:
    return RemoteFile(name=name, path=f"/{name}", size=size, modified=modified)


def _dir(name: str) -> RemoteFile:
    return RemoteFile(name=name, path=f"/{name}", is_dir=True)


def test_compare_directories_reports_uploads_downloads_and_same_items():
    modified = datetime(2026, 5, 8, 12, 0)

    result = compare_directories(
        [_file("local.txt"), _file("same.txt", modified=modified), RemoteFile("..", "/")],
        [_file("remote.txt"), _file("same.txt", modified=modified), RemoteFile("..", "/")],
    )

    actions = {row.name: row.action for row in result.rows}
    assert actions == {
        "local.txt": CompareAction.UPLOAD,
        "remote.txt": CompareAction.DOWNLOAD,
        "same.txt": CompareAction.SAME,
    }
    assert "3 items" in result.summary
    assert "1 upload" in result.summary
    assert "1 download" in result.summary


def test_compare_directories_prefers_newer_side_when_sizes_differ():
    older = datetime(2026, 5, 8, 12, 0)
    newer = datetime(2026, 5, 8, 13, 0)

    result = compare_directories(
        [_file("report.txt", size=20, modified=newer)],
        [_file("report.txt", size=10, modified=older)],
    )

    row = result.rows[0]
    assert row.action is CompareAction.LOCAL_NEWER
    assert row.action_label == "Upload newer local"
    assert "size differs" in row.detail
    assert row.speech.startswith("report.txt: Upload newer local")


def test_compare_directories_flags_type_conflicts():
    result = compare_directories([_dir("assets")], [_file("assets")])

    assert result.rows[0].action is CompareAction.CONFLICT
    assert result.rows[0].detail == "file type differs"
