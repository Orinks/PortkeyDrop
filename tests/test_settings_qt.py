"""Tests for the experimental PySide6 settings dialog."""

from __future__ import annotations

from dataclasses import asdict

import pytest

from portkeydrop.settings import Settings

qtwidgets = pytest.importorskip("PySide6.QtWidgets")

from portkeydrop.dialogs.settings_qt import QtSettingsDialog  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = qtwidgets.QApplication.instance() or qtwidgets.QApplication([])
    yield app


def test_qt_settings_dialog_accessibility_contracts(qapp):
    dlg = QtSettingsDialog(Settings())

    assert dlg.tabs.accessibleName() == "Settings categories"
    assert dlg.focusWidget() is dlg.tabs

    assert dlg.concurrent_spin.accessibleName() == "Concurrent transfers"
    assert dlg.overwrite_combo.accessibleName() == "Overwrite mode"
    assert dlg.download_dir_edit.accessibleName() == "Download directory"
    assert dlg.remember_local_folder_check.accessibleName() == "Remember last local folder on startup"


def test_qt_settings_dialog_round_trip_updates_settings(qapp):
    settings = Settings()
    dlg = QtSettingsDialog(settings)

    dlg.concurrent_spin.setValue(4)
    dlg.overwrite_combo.setCurrentText("rename")
    dlg.resume_check.setChecked(False)
    dlg.download_dir_edit.setText("/tmp/downloads")

    dlg.progress_spin.setValue(10)
    dlg.sort_by_combo.setCurrentText("modified")

    dlg.protocol_combo.setCurrentText("ftp")
    dlg.timeout_spin.setValue(90)
    dlg.remember_local_folder_check.setChecked(False)

    dlg.speech_rate_spin.setValue(65)
    dlg.verbosity_combo.setCurrentText("verbose")

    updated = dlg.get_settings()

    assert updated.transfer.concurrent_transfers == 4
    assert updated.transfer.overwrite_mode == "rename"
    assert updated.transfer.resume_partial is False
    assert updated.transfer.default_download_dir == "/tmp/downloads"
    assert updated.display.progress_interval == 10
    assert updated.display.sort_by == "modified"
    assert updated.connection.protocol == "ftp"
    assert updated.connection.timeout == 90
    assert updated.app.remember_last_local_folder_on_startup is False
    assert updated.speech.rate == 65
    assert updated.speech.verbosity == "verbose"


def test_settings_model_full_round_trip(tmp_path):
    settings = Settings()
    settings.transfer.concurrent_transfers = 7
    settings.transfer.overwrite_mode = "overwrite"
    settings.display.sort_by = "type"
    settings.connection.verify_host_keys = "always"
    settings.speech.verbosity = "minimal"
    settings.app.remember_last_local_folder_on_startup = False

    from portkeydrop.settings import load_settings, save_settings

    save_settings(settings, tmp_path)
    loaded = load_settings(tmp_path)

    assert asdict(loaded) == asdict(settings)
