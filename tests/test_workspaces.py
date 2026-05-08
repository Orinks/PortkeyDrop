"""Tests for saved workspace bookmarks."""

from __future__ import annotations

import json

from portkeydrop.workspaces import WorkspaceBookmark, WorkspaceManager


def test_empty_initially(tmp_path):
    manager = WorkspaceManager(tmp_path)

    assert manager.workspaces == []


def test_add_persists_workspace(tmp_path):
    manager = WorkspaceManager(tmp_path)
    workspace = WorkspaceBookmark(
        name="Reports",
        local_path=str(tmp_path / "reports"),
        remote_path="/srv/reports",
    )

    manager.add(workspace)

    reloaded = WorkspaceManager(tmp_path)
    assert len(reloaded.workspaces) == 1
    assert reloaded.workspaces[0].name == "Reports"
    assert reloaded.workspaces[0].local_path == str(tmp_path / "reports")
    assert reloaded.workspaces[0].remote_path == "/srv/reports"


def test_remove_workspace(tmp_path):
    manager = WorkspaceManager(tmp_path)
    workspace = WorkspaceBookmark(name="Reports")
    manager.add(workspace)

    manager.remove(workspace.id)

    assert manager.workspaces == []


def test_get_by_id(tmp_path):
    manager = WorkspaceManager(tmp_path)
    workspace = WorkspaceBookmark(name="Reports")
    manager.add(workspace)

    found = manager.get(workspace.id)

    assert found is not None
    assert found.name == "Reports"


def test_find_by_name_is_case_insensitive(tmp_path):
    manager = WorkspaceManager(tmp_path)
    manager.add(WorkspaceBookmark(name="Reports"))

    found = manager.find_by_name("reports")

    assert found is not None
    assert found.name == "Reports"


def test_load_corrupt_file(tmp_path):
    (tmp_path / "workspaces.json").write_text("not json", encoding="utf-8")

    manager = WorkspaceManager(tmp_path)

    assert manager.workspaces == []


def test_workspaces_returns_copy(tmp_path):
    manager = WorkspaceManager(tmp_path)
    manager.add(WorkspaceBookmark(name="Reports"))
    workspaces = manager.workspaces

    workspaces.clear()

    assert len(manager.workspaces) == 1


def test_workspace_file_contains_no_secret_connection_fields(tmp_path):
    manager = WorkspaceManager(tmp_path)
    manager.add(
        WorkspaceBookmark(
            name="Reports",
            local_path=str(tmp_path / "reports"),
            remote_path="/srv/reports",
        )
    )

    data = json.loads((tmp_path / "workspaces.json").read_text(encoding="utf-8"))

    assert set(data[0]) == {"id", "name", "local_path", "remote_path"}
