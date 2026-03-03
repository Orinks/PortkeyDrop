"""Tests for migration startup flow in PortkeyDropApp.OnInit."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tests._wx_stub import load_module_with_fake_wx


@pytest.fixture
def app_module(monkeypatch):
    module, fake_wx = load_module_with_fake_wx("portkeydrop.app", monkeypatch)
    return module, fake_wx


def _app_instance(app):
    instance = object.__new__(app.PortkeyDropApp)
    instance.SetTopWindow = MagicMock()
    return instance


def test_on_init_portable_mode_runs_migration_when_user_confirms(tmp_path, app_module):
    app, fake_wx = app_module
    portable_dir = tmp_path / "portable"
    portable_dir.mkdir()
    candidates = [("Sites & connections", "sites.json"), ("Known SSH hosts", "known_hosts")]

    dialog = MagicMock()
    dialog.ShowModal.return_value = fake_wx.ID_OK
    dialog.get_selected_filenames.return_value = ["sites.json"]
    frame = SimpleNamespace(Show=MagicMock())

    with (
        patch.object(app, "is_portable_mode", return_value=True),
        patch.object(app, "get_config_dir", return_value=portable_dir),
        patch.object(app.Path, "home", return_value=tmp_path),
        patch.object(app, "has_migration_candidates", return_value=True),
        patch.object(app, "get_migration_candidates", return_value=candidates),
        patch.object(app, "MigrationDialog", return_value=dialog) as migration_dialog_cls,
        patch.object(app, "migrate_files") as migrate_files,
        patch.object(app, "MainFrame", return_value=frame),
    ):
        result = app.PortkeyDropApp.OnInit(_app_instance(app))
        migration_dialog_cls.assert_called_once_with(None, candidates)

    assert result is True
    migrate_files.assert_called_once_with(["sites.json"], tmp_path / ".portkeydrop", portable_dir)
    dialog.Destroy.assert_called_once()


def test_on_init_portable_mode_skips_migration_when_user_cancels(tmp_path, app_module):
    app, fake_wx = app_module
    fake_wx.ID_CANCEL = 999
    portable_dir = tmp_path / "portable"
    portable_dir.mkdir()

    dialog = MagicMock()
    dialog.ShowModal.return_value = fake_wx.ID_CANCEL
    frame = SimpleNamespace(Show=MagicMock())

    with (
        patch.object(app, "is_portable_mode", return_value=True),
        patch.object(app, "get_config_dir", return_value=portable_dir),
        patch.object(app.Path, "home", return_value=tmp_path),
        patch.object(app, "has_migration_candidates", return_value=True),
        patch.object(app, "get_migration_candidates", return_value=[("Sites", "sites.json")]),
        patch.object(app, "MigrationDialog", return_value=dialog),
        patch.object(app, "migrate_files") as migrate_files,
        patch.object(app, "MainFrame", return_value=frame),
    ):
        result = app.PortkeyDropApp.OnInit(_app_instance(app))

    assert result is True
    migrate_files.assert_not_called()
    dialog.Destroy.assert_called_once()


def test_on_init_non_portable_mode_does_not_show_migration_dialog(app_module):
    app, _ = app_module
    frame = SimpleNamespace(Show=MagicMock())

    with (
        patch.object(app, "is_portable_mode", return_value=False),
        patch.object(app, "MigrationDialog") as migration_dialog,
        patch.object(app, "has_migration_candidates") as has_candidates,
        patch.object(app, "migrate_files") as migrate_files,
        patch.object(app, "MainFrame", return_value=frame),
    ):
        result = app.PortkeyDropApp.OnInit(_app_instance(app))

    assert result is True
    migration_dialog.assert_not_called()
    has_candidates.assert_not_called()
    migrate_files.assert_not_called()
