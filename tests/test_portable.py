"""Tests for portable mode detection and config directory resolution."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from portkeydrop.portable import get_config_dir, is_portable_mode


class TestIsPortableMode:
    def test_true_when_data_dir_exists(self, tmp_path: Path):
        (tmp_path / "data").mkdir()
        fake_exe = tmp_path / "portkeydrop.exe"
        fake_exe.touch()
        with patch("portkeydrop.portable.sys") as mock_sys:
            mock_sys.executable = str(fake_exe)
            assert is_portable_mode() is True

    def test_true_when_portable_txt_exists(self, tmp_path: Path):
        (tmp_path / "portable.txt").write_text("")
        fake_exe = tmp_path / "portkeydrop.exe"
        fake_exe.touch()
        with patch("portkeydrop.portable.sys") as mock_sys:
            mock_sys.executable = str(fake_exe)
            assert is_portable_mode() is True

    def test_false_when_neither_marker_exists(self, tmp_path: Path):
        fake_exe = tmp_path / "portkeydrop.exe"
        fake_exe.touch()
        with patch("portkeydrop.portable.sys") as mock_sys:
            mock_sys.executable = str(fake_exe)
            assert is_portable_mode() is False


class TestGetConfigDir:
    def test_returns_data_dir_in_portable_mode(self, tmp_path: Path):
        (tmp_path / "data").mkdir()
        fake_exe = tmp_path / "portkeydrop.exe"
        fake_exe.touch()
        with patch("portkeydrop.portable.sys") as mock_sys:
            mock_sys.executable = str(fake_exe)
            assert get_config_dir() == tmp_path / "data"

    def test_returns_home_dir_in_normal_mode(self, tmp_path: Path):
        fake_exe = tmp_path / "portkeydrop.exe"
        fake_exe.touch()
        with patch("portkeydrop.portable.sys") as mock_sys:
            mock_sys.executable = str(fake_exe)
            result = get_config_dir()
            assert result == Path.home() / ".portkeydrop"
