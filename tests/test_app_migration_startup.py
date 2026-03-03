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
    site_manager = MagicMock()
    site_manager.should_offer_keyring_to_vault_migration.return_value = False

    with (
        patch.object(app, "is_portable_mode", return_value=True),
        patch.object(app, "get_config_dir", return_value=portable_dir),
        patch.object(app.Path, "home", return_value=tmp_path),
        patch.object(app, "has_migration_candidates", return_value=True),
        patch.object(app, "get_migration_candidates", return_value=candidates),
        patch.object(app, "MigrationDialog", return_value=dialog) as migration_dialog_cls,
        patch.object(app, "migrate_files") as migrate_files,
        patch.object(app, "SiteManager", return_value=site_manager),
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
    site_manager = MagicMock()
    site_manager.should_offer_keyring_to_vault_migration.return_value = False

    with (
        patch.object(app, "is_portable_mode", return_value=True),
        patch.object(app, "get_config_dir", return_value=portable_dir),
        patch.object(app.Path, "home", return_value=tmp_path),
        patch.object(app, "has_migration_candidates", return_value=True),
        patch.object(app, "get_migration_candidates", return_value=[("Sites", "sites.json")]),
        patch.object(app, "MigrationDialog", return_value=dialog),
        patch.object(app, "migrate_files") as migrate_files,
        patch.object(app, "SiteManager", return_value=site_manager),
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


def test_on_init_prompts_for_keyring_to_vault_migration_and_marks_complete(tmp_path, app_module):
    app, fake_wx = app_module
    portable_dir = tmp_path / "portable"
    portable_dir.mkdir()
    frame = SimpleNamespace(Show=MagicMock())
    site_manager = MagicMock()
    site_manager.should_offer_keyring_to_vault_migration.return_value = True

    with (
        patch.object(app, "is_portable_mode", return_value=True),
        patch.object(app, "get_config_dir", return_value=portable_dir),
        patch.object(app.Path, "home", return_value=tmp_path),
        patch.object(app, "has_migration_candidates", return_value=False),
        patch.object(app, "SiteManager", return_value=site_manager),
        patch.object(app.wx, "MessageBox", return_value=fake_wx.YES) as message_box,
        patch.object(app, "MainFrame", return_value=frame),
    ):
        result = app.PortkeyDropApp.OnInit(_app_instance(app))

    assert result is True
    message_box.assert_called_once()
    site_manager.migrate_keyring_passwords_to_vault.assert_called_once()
    assert (portable_dir / ".keyring_migrated").exists()


def test_on_init_decline_keyring_to_vault_migration_still_writes_marker(tmp_path, app_module):
    app, fake_wx = app_module
    portable_dir = tmp_path / "portable"
    portable_dir.mkdir()
    frame = SimpleNamespace(Show=MagicMock())
    site_manager = MagicMock()
    site_manager.should_offer_keyring_to_vault_migration.return_value = True

    with (
        patch.object(app, "is_portable_mode", return_value=True),
        patch.object(app, "get_config_dir", return_value=portable_dir),
        patch.object(app.Path, "home", return_value=tmp_path),
        patch.object(app, "has_migration_candidates", return_value=False),
        patch.object(app, "SiteManager", return_value=site_manager),
        patch.object(app.wx, "MessageBox", return_value=fake_wx.ID_OK),
        patch.object(app, "MainFrame", return_value=frame),
    ):
        result = app.PortkeyDropApp.OnInit(_app_instance(app))

    assert result is True
    site_manager.migrate_keyring_passwords_to_vault.assert_not_called()
    assert (portable_dir / ".keyring_migrated").exists()


def test_on_init_skips_keyring_prompt_when_marker_exists(tmp_path, app_module):
    app, _ = app_module
    portable_dir = tmp_path / "portable"
    portable_dir.mkdir()
    (portable_dir / ".keyring_migrated").touch()
    frame = SimpleNamespace(Show=MagicMock())

    with (
        patch.object(app, "is_portable_mode", return_value=True),
        patch.object(app, "get_config_dir", return_value=portable_dir),
        patch.object(app.Path, "home", return_value=tmp_path),
        patch.object(app, "has_migration_candidates", return_value=False),
        patch.object(app, "SiteManager") as site_manager_cls,
        patch.object(app.wx, "MessageBox") as message_box,
        patch.object(app, "MainFrame", return_value=frame),
    ):
        result = app.PortkeyDropApp.OnInit(_app_instance(app))

    assert result is True
    site_manager_cls.assert_not_called()
    message_box.assert_not_called()
