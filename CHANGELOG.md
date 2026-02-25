# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Initial AccessiTransfer project

- Add full wxPython UI with accessible dialogs and keyboard shortcuts

- Refactor to dual-pane layout with local and remote file browsers

- Add Ctrl+T as context-aware transfer key

- Add '..' parent dir entry and improve remote navigation feedback

- Add 'Save Current Connection' to Sites menu

- Add logging for remote directory navigation

- Add recursive folder download and upload

- Add Home Directory shortcut (Ctrl+H)

- Add context menus for both file list panes

- Auto-show transfer queue on download/upload

- Store site passwords in system keyring instead of plaintext JSON

- Add security section to README

- Three-tier password storage (keyring > encrypted vault > no storage)

- Paste files from clipboard (Ctrl+V) to upload or copy locally

- Add clone step and fix install to include all extras

- Add uv install link to readme

- Add uv install commands for Windows and Mac/Linux

- SSH agent authentication support

- Port AccessiWeather-style a11y pattern to settings dialog


### Changed

- Rename AccessiTransfer to Portkey Drop


### Fixed

- Validate empty credentials and close dialogs before connecting

- Hide toolbar after connect, show on disconnect

- Improve directory detection in SFTP listing

- Follow symlinks to detect directory targets

- Repair class name broken by rename (Portkey DropApp -> PortkeyDropApp)

- Select first item after directory change for screen reader feedback

- Make default install include GUI dependencies

- Remove gui extra install hint and guard unsupported python

- Reorder menu bar to conventional sequence

- Use pip install -e '.[dev]' instead of requirements-dev.txt

- Remove unused dlg variable, apply ruff formatting


