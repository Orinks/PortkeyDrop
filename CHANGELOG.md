# PortkeyDrop Changelog

All notable changes to this project will be documented in this file.

## Unreleased

### Changed
- Portkey Drop is now a native application written in Rust rather than Python. The Windows download is about a fifth of the size it was (7 MB portable, down from 36 MB) and starts without unpacking a bundled interpreter first. Everything it did before it still does: SFTP, FTP, FTPS, and WebDAV, the same keyboard shortcuts, the same sound packs, and the same saved sites and passwords, which are read from where the previous version left them.
- macOS builds now ship as a disk image containing a universal app bundle, so one download works on both Intel and Apple silicon Macs, and updating no longer leaves you to finish the job in Finder.

- Linux downloads are paused for this release. The build links a system library from an older distribution and will not start on current ones, and the AppImage does not carry its own copy of the desktop toolkit. Windows and macOS are unaffected.

- Settings, sites, and known hosts now live where each system keeps application configuration -- `%APPDATA%\PortkeyDrop` on Windows, `Application Support` on macOS, `~/.config/portkeydrop` on Linux -- rather than a folder in your home directory. Everything is copied across the first time you start, and the old folder is left where it is, so an older version still works. Portable installs are unchanged and keep their data beside the program.

### Security
- On Linux and macOS the configuration folder and the encrypted password vault were created with whatever permissions the system defaulted to, commonly leaving them readable by every account on the machine. Since the vault's key is derived from the machine and user name rather than a secret, another local user could read the file and work out its key. The folder and the vault are now owner-only, and opening the app tightens an existing install. Windows already restricted them through the user profile.

### Added
- A portable copy started on a computer that also has Portkey Drop installed now offers to bring the installed copy's configuration across on first launch: a list of what to copy -- your sites, known hosts, and settings -- and, separately, your saved passwords. The installed copy is read and left exactly as it is. Passwords need the separate question because an installed copy keeps them in the computer's keyring, which a portable copy on a different machine cannot read, so without copying them into the portable copy's own encrypted vault the sites would arrive with every password blank. Both questions are asked once.
- The Modified column can show how long ago a file changed -- "3 days ago" rather than a date and time -- which is much shorter to listen to when skimming a folder. The exact stamp is still there for comparing two files; choose between them in Settings.
- The Site Manager has its Browse button back for choosing a private key file, and it opens where the current path points rather than at your home folder.
- A "Waiting to connect" cue now loops while an SFTP connection is held up waiting for your SSH agent to approve the key. Agents such as Bitwarden show that approval in a box that can open behind the Portkey Drop window with nothing to say it is there; the sound fills that gap and stops the moment the connection succeeds or fails. Give it a sound by adding a `connect_waiting` entry to a sound pack, and mute it in Settings like any other cue.

### Fixed
- A fresh install made no sound at all. The default sound pack was written with an empty list and none of its audio, so only people upgrading from the Python version, whose old pack was carried across, heard any cues. The twenty default sounds now ship inside the program and are written out on first start, including the new "Waiting to connect" cue, which is also added to an existing default pack without touching any sound you have replaced.
- Sound cues played in mono, most audibly the connect sound. The opening fraction of a second of every cue was folded to a single channel and slightly stretched before playback settled into stereo, and the short cues carry their stereo image right at the start. Cues now play in full stereo from the first sample.
- Backspace, Alt+Left, and Alt+Up in a file pane now go to the parent directory. Those keys were bound to a list event that never reported which key was pressed, so they did nothing in either pane. Ctrl+Up and Ctrl+[ do the same (Command+Up and Command+[ on a Mac, matching Finder).
- The exit sound was cut off as the program closed. Closing now waits for it to finish.
- Uploading a file always asked whether to replace it, even when nothing of that name was on the server. The prompt now appears only when the remote folder already has that name, matching downloads.
- Installing an update no longer asks you to close Portkey Drop first, and no longer leaves the app sitting there with nothing happening. Setup checks whether the app is running, and it was being started while the app was still on screen. Portkey Drop now closes itself and Setup opens on its own first page, the way the portable and macOS updates already worked. Quitting for an update is also final now: the download's progress window could keep the program alive after its window had closed, which left the update waiting for a program that never went away.
- Leaving Portkey Drop while a transfer was running froze the window instead of closing it. Quitting closed the connection, and that waited for the transfer to let go of it -- on the window's own thread, so nothing repainted until the transfer finished. The connection is now closed out of the way of the window.
- Downloading a folder no longer freezes the window for the length of the transfer. The connection check behind the status bar and tray tooltip waited for the connection to be free, and a transfer holds it for as long as its work takes -- the whole listing of a folder, then each file in turn -- so the window stopped repainting and Windows offered to close it. The check no longer waits: a connection busy with a transfer is reported as connected.
- Downloading a folder no longer hangs until the app runs out of memory when the server lists that folder (or its parent) as one of its own children, or when a directory symlink points back at a folder already being copied. Large folders are listed once and then copied; a loop in the listing is skipped rather than followed forever.
- Connecting to an unknown SSH host with "Ask before trusting a new server" (the default) now shows a dialog to reject the key, accept it once, or accept it permanently, instead of refusing every new host. Reject is the default, so Enter and Escape both refuse.
- Starting Portkey Drop opened an empty terminal window behind it. The program was built as a console application, so Windows gave it a console whether it wanted one or not; it is now built as a windowed application and starts with nothing but its own window. `--version` and `--help` still print to the terminal you run them from.
- The update offer said "Current: 0.6.0" on a nightly build, which is the version of the release before it and the same for every nightly. It now names the running build the way About does, so you can see which nightly you are on and which one is being offered.
- Alt+U reached both Duplicate and Username in the Site Manager, and Alt+P reached both Play and Preview in the sound pack window, so neither letter activated anything. Each access key now reaches one control.
- Accepting a host key could stop a different server from connecting. The new entry was written onto the end of the last line when the known hosts file did not end in a newline, which corrupted both; the server recorded there then looked like it had changed its key, and a changed key is refused outright. Existing files are repaired the next time a key is accepted.
- The first server in the known hosts file was not recognised if the file began with a byte order mark, as one written by some Windows editors does.
- Checking for updates on a nightly build kept offering the nightly already installed. Nightlies carry the version number of the release before them, so the app had no way to tell one from another; it now knows which nightly it is, and About names it too.
- Speech could corrupt memory on every platform. Portkey Drop's description of the speech library's configuration was forty-seven bytes shorter than the real one, so starting speech wrote past the space set aside for it. Windows and macOS survived it; Linux crashed on the first announcement, which is how it came to light.
- Settings, Site Manager, and the import window announced the wrong labels: each field was read out with the previous field's label, spin controls were read as unlabelled, and the first control on every page had no label at all.
- The update check said a new version was available and then offered only a Close button. It now offers to download and install it, with progress you can hear and a Cancel that stops the download.
- Release notes shown in the update window are no longer read out with their formatting characters.
- SFTP connections left idle were dropped without warning by firewalls and by servers that close quiet sessions, and you only found out when the next thing you did failed. Portkey Drop now sends a keepalive every 60 seconds so the connection keeps answering. The interval is in Settings, and 0 turns it off.
- The spoken detail setting only ever affected transfer progress announcements. It now governs how often progress is spoken as well: minimal stops progress being announced and verbose announces it twice as often. Setting the interval itself to 0 still silences progress whatever the detail level.
- The default protocol and the "use AUTH SSL" preference were saved but ignored: the quick connect bar always opened on the same protocol with the SSL box clear. It now starts from your defaults, and saving settings moves it onto whichever of the two you changed rather than resetting a protocol or port you had already typed in.

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
