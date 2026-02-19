"""Tests for settings management."""

from __future__ import annotations

import json

from portkeydrop.settings import (
    AppSettings,
    ConnectionDefaults,
    DisplaySettings,
    Settings,
    SpeechSettings,
    TransferSettings,
    load_settings,
    resolve_startup_local_folder,
    save_settings,
    update_last_local_folder,
)


class TestTransferSettings:
    def test_defaults(self):
        s = TransferSettings()
        assert s.concurrent_transfers == 2
        assert s.overwrite_mode == "ask"
        assert s.resume_partial is True
        assert s.preserve_timestamps is True
        assert s.follow_symlinks is False

    def test_default_download_dir(self):
        s = TransferSettings()
        assert "Downloads" in s.default_download_dir


class TestDisplaySettings:
    def test_defaults(self):
        s = DisplaySettings()
        assert s.announce_file_count is True
        assert s.progress_interval == 25
        assert s.show_hidden_files is False
        assert s.sort_by == "name"
        assert s.sort_ascending is True
        assert s.date_format == "relative"


class TestConnectionDefaults:
    def test_defaults(self):
        s = ConnectionDefaults()
        assert s.protocol == "sftp"
        assert s.timeout == 30
        assert s.keepalive == 60
        assert s.max_retries == 3
        assert s.passive_mode is True
        assert s.verify_host_keys == "ask"


class TestSpeechSettings:
    def test_defaults(self):
        s = SpeechSettings()
        assert s.rate == 50
        assert s.volume == 100
        assert s.verbosity == "normal"


class TestAppSettings:
    def test_defaults(self):
        s = AppSettings()
        assert s.remember_last_local_folder_on_startup is True
        assert s.last_local_folder is None


class TestSettings:
    def test_defaults(self):
        s = Settings()
        assert isinstance(s.transfer, TransferSettings)
        assert isinstance(s.display, DisplaySettings)
        assert isinstance(s.connection, ConnectionDefaults)
        assert isinstance(s.speech, SpeechSettings)
        assert isinstance(s.app, AppSettings)


class TestLoadSaveSettings:
    def test_load_missing_file(self, tmp_path):
        settings = load_settings(tmp_path)
        assert settings.transfer.concurrent_transfers == 2
        assert settings.connection.protocol == "sftp"

    def test_save_and_load(self, tmp_path):
        settings = Settings()
        settings.transfer.concurrent_transfers = 5
        settings.display.show_hidden_files = True
        settings.connection.timeout = 60
        settings.speech.rate = 75

        save_settings(settings, tmp_path)
        loaded = load_settings(tmp_path)

        assert loaded.transfer.concurrent_transfers == 5
        assert loaded.display.show_hidden_files is True
        assert loaded.connection.timeout == 60
        assert loaded.speech.rate == 75

    def test_load_corrupt_file(self, tmp_path):
        (tmp_path / "settings.json").write_text("not json", encoding="utf-8")
        settings = load_settings(tmp_path)
        # Should return defaults
        assert settings.transfer.concurrent_transfers == 2

    def test_load_partial_settings(self, tmp_path):
        data = {"transfer": {"concurrent_transfers": 10}}
        (tmp_path / "settings.json").write_text(json.dumps(data), encoding="utf-8")
        settings = load_settings(tmp_path)
        assert settings.transfer.concurrent_transfers == 10
        assert settings.display.sort_by == "name"  # default preserved

    def test_load_ignores_unknown_keys(self, tmp_path):
        data = {"transfer": {"concurrent_transfers": 3, "unknown_key": True}}
        (tmp_path / "settings.json").write_text(json.dumps(data), encoding="utf-8")
        settings = load_settings(tmp_path)
        assert settings.transfer.concurrent_transfers == 3

    def test_save_creates_directory(self, tmp_path):
        nested = tmp_path / "deep" / "nested"
        settings = Settings()
        save_settings(settings, nested)
        assert (nested / "settings.json").exists()


class TestRememberLastLocalFolder:
    def test_update_last_local_folder_enabled(self, tmp_path):
        settings = Settings()
        local_dir = tmp_path / "local"
        local_dir.mkdir()

        changed = update_last_local_folder(settings, str(local_dir))

        assert changed is True
        assert settings.app.last_local_folder == str(local_dir.resolve())

    def test_update_last_local_folder_disabled_clears_value(self):
        settings = Settings(
            app=AppSettings(
                remember_last_local_folder_on_startup=False,
                last_local_folder="/tmp/old",
            )
        )

        changed = update_last_local_folder(settings, "/tmp/new")

        assert changed is True
        assert settings.app.last_local_folder is None

    def test_resolve_startup_local_folder_restores_when_available(self, tmp_path):
        local_dir = tmp_path / "mounted"
        local_dir.mkdir()
        settings = Settings(
            app=AppSettings(
                remember_last_local_folder_on_startup=True,
                last_local_folder=str(local_dir),
            )
        )

        resolved = resolve_startup_local_folder(settings, fallback=str(tmp_path / "fallback"))

        assert resolved == str(local_dir.resolve())

    def test_resolve_startup_local_folder_missing_path_falls_back_and_clears(self, tmp_path):
        missing = tmp_path / "missing"
        fallback = tmp_path / "fallback"
        fallback.mkdir()
        settings = Settings(
            app=AppSettings(
                remember_last_local_folder_on_startup=True,
                last_local_folder=str(missing),
            )
        )

        resolved = resolve_startup_local_folder(settings, fallback=str(fallback))

        assert resolved == str(fallback)
        assert settings.app.last_local_folder is None

    def test_save_settings_does_not_persist_last_local_folder_when_disabled(self, tmp_path):
        settings = Settings(
            app=AppSettings(
                remember_last_local_folder_on_startup=False,
                last_local_folder="/tmp/should-not-persist",
            )
        )

        save_settings(settings, tmp_path)

        data = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
        assert data["app"]["remember_last_local_folder_on_startup"] is False
        assert data["app"]["last_local_folder"] is None
