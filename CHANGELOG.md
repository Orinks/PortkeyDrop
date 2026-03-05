# PortkeyDrop Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Fixed
- Replaced local/remote file panes with `wx.dataview.DataViewListCtrl` to improve accessibility semantics while preserving dual-pane keyboard workflows and file operations.

---

## [0.1.0] - 2026-02-25

Initial release of PortkeyDrop (formerly AccessiTransfer).

### Added
- Dual-pane layout with local and remote file browsers
- Full wxPython UI with accessible dialogs and keyboard shortcuts
- SFTP file transfer with progress tracking and transfer queue
- SSH agent authentication support
- Three-tier password storage (keyring > encrypted vault > no storage)
- Site management — save and reload connections from the Sites menu
- Recursive folder upload and download
- Clipboard paste upload (Ctrl+V)
- Context menus for both file panes
- Home directory shortcut (Ctrl+H)
- Auto-show transfer queue on upload/download start
- Parent directory navigation via ".." entry

### Fixed
- Empty credential validation before connecting
- Directory detection in SFTP directory listings
- Symlink handling for directory targets
- Screen reader feedback after directory navigation
- Conventional menu bar ordering
