"""Experimental PySide6 settings dialog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from portkeydrop.settings import Settings


class QtSettingsDialog(QDialog):
    """Dialog for editing application settings using PySide6."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings = settings

        self.setWindowTitle("Settings (Experimental)")
        self.resize(620, 420)

        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.setAccessibleName("Settings categories")
        root.addWidget(self.tabs)

        self._build_transfer_tab()
        self._build_display_tab()
        self._build_connection_tab()
        self._build_speech_tab()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setAccessibleName("Save settings")
        buttons.button(QDialogButtonBox.Cancel).setAccessibleName("Cancel settings changes")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._populate()
        self.tabs.setFocus()

    def _add_labeled_control(
        self, layout: QFormLayout, label_text: str, control: QWidget, control_name: str
    ) -> None:
        label = QLabel(label_text)
        label.setBuddy(control)
        label.setAccessibleName(f"{control_name} label")
        control.setAccessibleName(control_name)
        layout.addRow(label, control)

    def _build_transfer_tab(self) -> None:
        tab = QWidget()
        form = QFormLayout(tab)

        self.concurrent_spin = QSpinBox()
        self.concurrent_spin.setRange(1, 10)
        self._add_labeled_control(
            form,
            "Concurrent transfers:",
            self.concurrent_spin,
            "Concurrent transfers",
        )

        self.overwrite_combo = QComboBox()
        self.overwrite_combo.addItems(["ask", "overwrite", "skip", "rename"])
        self._add_labeled_control(form, "Overwrite mode:", self.overwrite_combo, "Overwrite mode")

        self.resume_check = QCheckBox("Resume partial transfers")
        self.resume_check.setAccessibleName("Resume partial transfers")
        form.addRow("", self.resume_check)

        self.preserve_check = QCheckBox("Preserve timestamps")
        self.preserve_check.setAccessibleName("Preserve timestamps")
        form.addRow("", self.preserve_check)

        self.follow_symlinks_check = QCheckBox("Follow symlinks")
        self.follow_symlinks_check.setAccessibleName("Follow symlinks")
        form.addRow("", self.follow_symlinks_check)

        self.download_dir_edit = QLineEdit()
        self._add_labeled_control(
            form,
            "Download directory:",
            self.download_dir_edit,
            "Download directory",
        )

        self.tabs.addTab(tab, "Transfer")

    def _build_display_tab(self) -> None:
        tab = QWidget()
        form = QFormLayout(tab)

        self.announce_count_check = QCheckBox("Announce file count")
        self.announce_count_check.setAccessibleName("Announce file count")
        form.addRow("", self.announce_count_check)

        self.progress_spin = QSpinBox()
        self.progress_spin.setRange(5, 50)
        self._add_labeled_control(
            form,
            "Progress interval (%):",
            self.progress_spin,
            "Progress interval",
        )

        self.show_hidden_check = QCheckBox("Show hidden files")
        self.show_hidden_check.setAccessibleName("Show hidden files")
        form.addRow("", self.show_hidden_check)

        self.sort_by_combo = QComboBox()
        self.sort_by_combo.addItems(["name", "size", "modified", "type"])
        self._add_labeled_control(form, "Sort by:", self.sort_by_combo, "Sort by")

        self.sort_ascending_check = QCheckBox("Sort ascending")
        self.sort_ascending_check.setAccessibleName("Sort ascending")
        form.addRow("", self.sort_ascending_check)

        self.date_format_combo = QComboBox()
        self.date_format_combo.addItems(["relative", "absolute"])
        self._add_labeled_control(form, "Date format:", self.date_format_combo, "Date format")

        self.tabs.addTab(tab, "Display")

    def _build_connection_tab(self) -> None:
        tab = QWidget()
        form = QFormLayout(tab)

        self.protocol_combo = QComboBox()
        self.protocol_combo.addItems(["sftp", "ftp", "ftps"])
        self._add_labeled_control(form, "Default protocol:", self.protocol_combo, "Default protocol")

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(5, 300)
        self._add_labeled_control(form, "Timeout (seconds):", self.timeout_spin, "Timeout")

        self.keepalive_spin = QSpinBox()
        self.keepalive_spin.setRange(0, 600)
        self._add_labeled_control(form, "Keepalive (seconds):", self.keepalive_spin, "Keepalive")

        self.retries_spin = QSpinBox()
        self.retries_spin.setRange(0, 10)
        self._add_labeled_control(form, "Max retries:", self.retries_spin, "Max retries")

        self.passive_check = QCheckBox("Passive mode (FTP)")
        self.passive_check.setAccessibleName("Passive mode")
        form.addRow("", self.passive_check)

        self.verify_keys_combo = QComboBox()
        self.verify_keys_combo.addItems(["ask", "always", "never"])
        self._add_labeled_control(
            form,
            "Verify host keys:",
            self.verify_keys_combo,
            "Verify host keys",
        )

        self.remember_local_folder_check = QCheckBox("Remember last local folder on startup")
        self.remember_local_folder_check.setAccessibleName("Remember last local folder on startup")
        form.addRow("", self.remember_local_folder_check)

        self.tabs.addTab(tab, "Connection")

    def _build_speech_tab(self) -> None:
        tab = QWidget()
        form = QFormLayout(tab)

        self.speech_rate_spin = QSpinBox()
        self.speech_rate_spin.setRange(0, 100)
        self._add_labeled_control(form, "Rate:", self.speech_rate_spin, "Speech rate")

        self.speech_volume_spin = QSpinBox()
        self.speech_volume_spin.setRange(0, 100)
        self._add_labeled_control(form, "Volume:", self.speech_volume_spin, "Speech volume")

        self.verbosity_combo = QComboBox()
        self.verbosity_combo.addItems(["minimal", "normal", "verbose"])
        self._add_labeled_control(form, "Verbosity:", self.verbosity_combo, "Verbosity")

        self.tabs.addTab(tab, "Speech")

    def _populate(self) -> None:
        s = self._settings
        self.concurrent_spin.setValue(s.transfer.concurrent_transfers)
        self.overwrite_combo.setCurrentText(s.transfer.overwrite_mode)
        self.resume_check.setChecked(s.transfer.resume_partial)
        self.preserve_check.setChecked(s.transfer.preserve_timestamps)
        self.follow_symlinks_check.setChecked(s.transfer.follow_symlinks)
        self.download_dir_edit.setText(s.transfer.default_download_dir)

        self.announce_count_check.setChecked(s.display.announce_file_count)
        self.progress_spin.setValue(s.display.progress_interval)
        self.show_hidden_check.setChecked(s.display.show_hidden_files)
        self.sort_by_combo.setCurrentText(s.display.sort_by)
        self.sort_ascending_check.setChecked(s.display.sort_ascending)
        self.date_format_combo.setCurrentText(s.display.date_format)

        self.protocol_combo.setCurrentText(s.connection.protocol)
        self.timeout_spin.setValue(s.connection.timeout)
        self.keepalive_spin.setValue(s.connection.keepalive)
        self.retries_spin.setValue(s.connection.max_retries)
        self.passive_check.setChecked(s.connection.passive_mode)
        self.verify_keys_combo.setCurrentText(s.connection.verify_host_keys)
        self.remember_local_folder_check.setChecked(s.app.remember_last_local_folder_on_startup)

        self.speech_rate_spin.setValue(s.speech.rate)
        self.speech_volume_spin.setValue(s.speech.volume)
        self.verbosity_combo.setCurrentText(s.speech.verbosity)

    def get_settings(self) -> Settings:
        """Return updated Settings from the dialog fields."""
        s = self._settings
        s.transfer.concurrent_transfers = self.concurrent_spin.value()
        s.transfer.overwrite_mode = self.overwrite_combo.currentText()
        s.transfer.resume_partial = self.resume_check.isChecked()
        s.transfer.preserve_timestamps = self.preserve_check.isChecked()
        s.transfer.follow_symlinks = self.follow_symlinks_check.isChecked()
        s.transfer.default_download_dir = self.download_dir_edit.text()

        s.display.announce_file_count = self.announce_count_check.isChecked()
        s.display.progress_interval = self.progress_spin.value()
        s.display.show_hidden_files = self.show_hidden_check.isChecked()
        s.display.sort_by = self.sort_by_combo.currentText()
        s.display.sort_ascending = self.sort_ascending_check.isChecked()
        s.display.date_format = self.date_format_combo.currentText()

        s.connection.protocol = self.protocol_combo.currentText()
        s.connection.timeout = self.timeout_spin.value()
        s.connection.keepalive = self.keepalive_spin.value()
        s.connection.max_retries = self.retries_spin.value()
        s.connection.passive_mode = self.passive_check.isChecked()
        s.connection.verify_host_keys = self.verify_keys_combo.currentText()
        s.app.remember_last_local_folder_on_startup = (
            self.remember_local_folder_check.isChecked()
        )

        s.speech.rate = self.speech_rate_spin.value()
        s.speech.volume = self.speech_volume_spin.value()
        s.speech.verbosity = self.verbosity_combo.currentText()
        return s
