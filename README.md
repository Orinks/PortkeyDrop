# PortkeyDrop

A keyboard-first file transfer client that works the way you do.

PortkeyDrop is a desktop client for SFTP, FTP, FTPS, and WebDAV. Connect to your servers, move files, and track every transfer without ever reaching for a mouse. Its dual-pane interface keeps local and remote files clear, labeled, and ready for screen readers including NVDA, JAWS, and VoiceOver.

## Layout

Two side-by-side file browsers:
- **Left pane**: Local files (starts at your home directory)
- **Right pane**: Remote files (connected server)

Each pane is a labeled standard list control, so screen readers announce "Local Files" or "Remote Files" when you Tab between them.
Use Shift+Arrow or Ctrl+Arrow/Space in a file pane to select multiple items for batch transfers.

## Sound Packs

Portkey Drop includes a built-in default sound pack with short cues for transfers, connections, file operations, and general app events. Sound packs live under a pack folder with section subfolders, such as `default/transfers/transfer_complete.ogg`, and a `pack.json` manifest maps each event to its sound file.

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| Ctrl+T | Transfer selected items: uploads from local pane, downloads from remote pane |
| Ctrl+U | Upload selected local items to remote |
| Ctrl+D | Download selected remote items to local |
| Ctrl+N | Quick Connect |
| Ctrl+S | Site Manager |
| Ctrl+R | Refresh active pane |
| Ctrl+F | Filter active pane |
| Ctrl+I | File properties |
| Ctrl+Shift+N | New directory |
| Ctrl+Shift+T | Transfer queue |
| Ctrl+Enter | Connect using the quick connect bar |
| Enter | Open directory / download file |
| Backspace | Parent directory |
| Delete | Delete selected |
| F2 | Rename selected |

## Protocols

Implemented:

- **SFTP** (default) — SSH-based, most secure
- **FTP** — Legacy support
- **FTP with SSL (AUTH SSL)** — Explicit SSL upgrade for FTP servers which require it
- **FTPS** — FTP over SSL/TLS
- **WebDAV** — Experimental HTTP-based support for compatible servers and cloud services

Planned:

- **SCP** — Fast SSH transfers (planned)

## Security

Saved connection passwords are stored in your system's secure keyring (Windows Credential Locker, macOS Keychain, Linux Secret Service) and never written to disk in plaintext.

## Install

Packaged builds for Windows (installer and portable ZIP), macOS, and Linux (tarball and AppImage) are published on the [releases page](https://github.com/Orinks/PortkeyDrop/releases). On Linux, download the AppImage, mark it executable (`chmod +x PortkeyDrop-*.AppImage`), and run it.

To run from source you need a Rust toolchain (1.85 or newer) and a C++ compiler, since wxWidgets is built from source on first compile.

```bash
git clone https://github.com/Orinks/PortkeyDrop.git
cd PortkeyDrop
cargo run --release
```

## Development

```bash
cargo test            # Run the test suite
cargo build           # Debug build
cargo clippy          # Lints
cargo fmt             # Format
```

The workspace is four crates:

| Crate | Contents |
|---|---|
| `portkeydrop` | The wxWidgets front end: window, panes, dialogs |
| `portkeydrop-core` | Protocols, transfers, settings, sites, sound packs, updates |
| `prism` | Safe wrapper over the Prism speech library |
| `prism-sys` | Raw FFI to Prism's C API, with the platform binaries vendored |

`portkeydrop-core` has no UI dependency, so protocol parsing, transfer rules, and
credential handling are all tested without a display.

## Build

```bash
cargo build --release
```

On Windows the executable embeds an application manifest requesting Common
Controls 6. That is not optional: wxWidgets imports `GetWindowSubclass`, which
only version 6 exports, so a build without the manifest will not start.

## License

MIT
