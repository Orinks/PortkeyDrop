# PortkeyDrop Changelog

All notable changes to this project will be documented in this file.

## Unreleased

### Changed
- Choosing Connect with an empty host, username, or required password now moves focus to the field that needs input and announces it, instead of showing a dead-end error dialog.
- Quick Connect (Ctrl+N) now focuses the quick connect bar (revealing it while connected) instead of opening a separate dialog with the same fields.
- Pressing Enter in any quick connect field now starts the connection, matching the old dialog behavior.
- An invalid port in the quick connect bar now focuses the port field with an announcement instead of crashing the connect action.
- Development builds now report the next 0.5.2 development version after the 0.5.1 hotfix release.

## [0.5.1] - 2026-05-31

### Fixed
- Windows portable ZIPs now keep Portkey Drop data alongside the extracted app folder so settings, sites, sounds, and portable credentials stay with the portable copy.

## [0.5.0] - 2026-05-31

### Fixed
- Release notes now use curated user-facing changelog entries instead of raw commit or PR text.
- Packaged builds now correctly recognize installed copies when checking for updates.
- Starting Portkey Drop again on Windows now restores the running window instead of showing a stale lock-file prompt.
- Windows packaged builds can connect to SFTP servers again instead of failing with a missing `win32timezone` module.
- Windows packaged builds now include the native audio libraries needed for built-in sound events.
- Windows installers now close running Portkey Drop copies before replacing app files.
- WebDAV shares that use a username with no password now connect and open folders correctly.

### Added
- Batch transfers: select multiple local or remote files and folders, then use Ctrl+U,
  Ctrl+D, or Ctrl+T to queue them together.
- Default sound pack: Portkey Drop now includes built-in transfer, connection, file
  operation, and app event sounds with a structured folder layout for custom packs.
- FTP connections can now enable explicit SSL with the AUTH SSL command.
- Release builds now use Nuitka for Windows and macOS packaged artifacts.
- Experimental WebDAV connections for basic browse, upload, download, delete, folder creation, and rename workflows.

## [0.4.0] - 2026-05-05

### Added
- Added a macOS listbox fallback so VoiceOver can read local and remote file lists more reliably.

### Fixed
- Announce transfer progress details more clearly for screen reader users.
- Apply configured connection defaults consistently when creating and importing saved connections.
- Enforce overwrite policy before transfers are queued.

## [0.3.0] - 2026-03-23

### Fixed
- Set initial keyboard focus on Reject button in HostKeyDialog for immediate screen reader announcement
- Set Reject as default button in HostKeyDialog so Enter key safely rejects unknown host keys
- Set initial focus on first field in QuickConnectDialog and SiteManagerDialog for screen reader discoverability
- Associate StaticText labels with controls via SetLabelFor in QuickConnectDialog and ImportConnectionsDialog
- Set OK as default button in QuickConnectDialog so Enter submits the form
- Set default button per wizard step in ImportConnectionsDialog
- Set initial focus in MigrationDialog checkboxes for screen reader announcement
- Focus remote path bar when toolbar is hidden in main app window
- Ctrl+L focuses local path bar when local pane is active (previously always focused remote)
- Restore site list selection after saving a site in Site Manager
- Validate port field on save in Site Manager; show error for non-numeric input
- Populate form with next site after removing a site in Site Manager
- Guard against `..` entry in delete and rename operations to prevent parent-directory changes

## [0.2.0] - 2026-03-10

### Added
- Activity log console panel with Prism screen reader announcements, F6 pane cycling, Ctrl+1/2/3 shortcuts, and Tab navigation (#94)
- Decoupled transfer logic from dialog — transfers now run in the background (#95)
- One-click retry for failed transfers (#101)
- Persist transfer queue across app sessions — restored jobs survive crashes and restarts (#100)
- Queue additional files during an active transfer (#103)
- Resume interrupted downloads from byte offset instead of restarting (#109)
- Concurrent transfers setting wired into worker pool — honors max parallel transfers from settings (#110)
- Dedicated Updates tab in settings (#90)

### Fixed
- Reset progress display to 0% immediately on retry
- Announce transfer cancellation immediately with clear messaging (#86, #92)
- Add cancel/close button to Site Manager dialog (#80)
- Add colons to file list and toolbar field labels for screen reader clarity (#108)
- Associate StaticText labels with file lists via SetLabelFor
- Use SetLabel() for ListCtrl and name= for ListBox accessible names
- Resolve Tab focus trap in activity log panel
- Switch activity log to TextCtrl with HSCROLL for reliable NVDA reading (#104)
- Read version and build info from _build_meta when available (#105)



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
