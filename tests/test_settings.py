"""Tests for settings management."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from accessitransfer.settings import (
    ConnectionDefaults,
    DisplaySettings,
    Settings,
    SpeechSettings,
    TransferSettings,
    load_settings,
    save_settings,
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


class TestSettings:
    def test_defaults(self):
        s = Settings()
        assert isinstance(s.transfer, TransferSettings)
        assert isinstance(s.display, DisplaySettings)
        assert isinstance(s.connection, ConnectionDefaults)
        assert isinstance(s.speech, SpeechSettings)


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
