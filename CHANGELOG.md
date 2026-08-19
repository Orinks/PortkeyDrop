# PortkeyDrop Changelog

All notable changes to this project will be documented in this file.

## Unreleased

### Changed
- Portkey Drop is now a native application written in Rust rather than Python. The Windows download is about a fifth of the size it was (7 MB portable, down from 36 MB) and starts without unpacking a bundled interpreter first. Everything it did before it still does: SFTP, FTP, FTPS, and WebDAV, the same keyboard shortcuts, the same sound packs, and the same saved sites and passwords, which are read from where the previous version left them.
- macOS builds now ship as a disk image containing a universal app bundle, so one download works on both Intel and Apple silicon Macs, and updating no longer leaves you to finish the job in Finder.

- Linux downloads are paused for this release. The build links a system library from an older distribution and will not start on current ones, and the AppImage does not carry its own copy of the desktop toolkit. Windows and macOS are unaffected.

### Fixed
- Checking for updates on a nightly build kept offering the nightly already installed. Nightlies carry the version number of the release before them, so the app had no way to tell one from another; it now knows which nightly it is, and About names it too.
- Speech could corrupt memory on every platform. Portkey Drop's description of the speech library's configuration was forty-seven bytes shorter than the real one, so starting speech wrote past the space set aside for it. Windows and macOS survived it; Linux crashed on the first announcement, which is how it came to light.
- Settings, Site Manager, and the import window announced the wrong labels: each field was read out with the previous field's label, spin controls were read as unlabelled, and the first control on every page had no label at all.
- The update check said a new version was available and then offered only a Close button. It now offers to download and install it, with progress you can hear and a Cancel that stops the download.
- Release notes shown in the update window are no longer read out with their formatting characters.

## [0.6.0] - 2026-07-24

### Added
- Linux builds: releases and nightlies now include a Linux tarball and an AppImage. The AppImage bundles the libraries missing on non-Ubuntu systems, so it runs on Fedora, Arch, and openSUSE too, while screen reader support, themes, and TLS keep using your distro's own libraries.
- Linux AppImage installs can update themselves: the updater downloads the new AppImage, verifies its checksum, swaps it in place, and relaunches. Tarball runs get told where the verified download was saved instead of hitting a dead end.

### Fixed
- Pressing Delete or F2 while editing a text field no longer triggers file delete or rename — those keys now act only inside the file panes, and file operations tell you to focus a pane first instead of guessing (and sometimes targeting a remote file you never touched).
- Background transfer completions no longer jump your position in the file lists back to the top; deletes and renames keep you on the nearest neighbouring file, and sorting or toggling hidden files keeps your selection.
- The "Announce file count" setting now actually speaks the count when entering a directory; empty folders and empty filter results are announced instead of silent.
- The Speech settings tab (rate, volume, verbosity) now controls the built-in speech output instead of doing nothing; verbosity also controls transfer progress announcements.
- The "Verify host keys: ask" setting now really asks: connecting to an unknown SSH host shows an accessible dialog to reject or accept the key once or permanently, instead of silently trusting it.
- The Cancel button on the update download progress dialog now actually cancels the download.
- Upload, download, and transfer with nothing selected or no connection announce why nothing happened instead of doing nothing silently.
- Restoring the window from the notification area and closing the transfer queue now place keyboard focus in the file list rather than on the window frame.
- Removing a site in the Site Manager now asks for confirmation, announces the removal, and clears the form after the last site is deleted.
- Repeated connect presses while a connection attempt is in progress no longer start duplicate attempts (and duplicate error dialogs). Starting a connection is now announced for screen readers.

### Changed
- The transfer queue window no longer opens (and steals focus) automatically every time a transfer is queued; announcements cover the feedback and Ctrl+Shift+T opens it on demand. Queue buttons disable without a selection, and the selection follows the same transfer when rows are removed.
- Added Help > Keyboard Shortcuts listing every binding, including the previously undocumented F6, Ctrl+L, and Ctrl+1/2/3 pane shortcuts.
- Duplicate menu and dialog access keys (Alt+letter) were reassigned so each letter activates its control directly across the menus, Site Manager, Settings, transfer queue, sound pack, and import dialogs.
- The Settings Audio tab now scrolls so all mute checkboxes stay visible when focused; the file lists have proper accessible names for VoiceOver; keyboard-opened context menus appear at the focused file instead of the mouse pointer; switching protocol keeps a hand-typed port; the activity log no longer moves your reading position when new entries arrive; and a startup notice appears when no speech backend is available.
- Pressing Escape in the quick connect bar while connected now hides the bar and returns focus to where you were.
- Choosing Connect with an empty host, username, or required password now moves focus to the field that needs input and announces it, instead of showing a dead-end error dialog.
- Quick Connect (Ctrl+N) now focuses the quick connect bar (revealing it while connected) instead of opening a separate dialog with the same fields.
- Pressing Enter in any quick connect field now starts the connection, matching the old dialog behavior.
- Removed the redundant File > Connect menu item; connecting lives in the quick connect bar and the Sites menu. Ctrl+Enter still connects.
- Moved Disconnect from the File menu to the Sites menu, so connecting, disconnecting, and site management share one menu.
- An invalid port in the quick connect bar now focuses the port field with an announcement instead of crashing the connect action.

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
