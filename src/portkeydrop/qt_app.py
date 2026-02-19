"""Experimental PySide6 entry points."""

from __future__ import annotations

import sys

from portkeydrop.settings import load_settings, save_settings


def run_qt_settings_prototype() -> int:
    """Run the experimental Qt settings dialog against the current settings model."""
    try:
        from PySide6.QtWidgets import QApplication
    except ModuleNotFoundError:
        print("PySide6 is not installed.")
        print("Install with:")
        print("  uv sync --extra qt")
        return 1

    from portkeydrop.dialogs.settings_qt import QtSettingsDialog

    _app = QApplication.instance() or QApplication(sys.argv)
    settings = load_settings()
    dialog = QtSettingsDialog(settings)
    if dialog.exec():
        save_settings(dialog.get_settings())
    return 0
