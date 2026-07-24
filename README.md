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

To run from source instead, Portkey Drop currently supports Python 3.11 and 3.12.

**Windows:**
```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
git clone https://github.com/Orinks/PortkeyDrop.git
cd PortkeyDrop
uv sync
uv run portkeydrop
```

**Mac/Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/Orinks/PortkeyDrop.git
cd PortkeyDrop
uv sync
uv run portkeydrop
```

## Development

```bash
uv sync --all-extras --group dev
uv run pytest
uv run ruff check
```

## Build

Release-style local builds use Nuitka, matching the GitHub Actions build path:

```bash
uv sync --extra build --group dev
uv run python installer/build_nuitka.py
```

On Windows, install Inno Setup 6 before building the installer.

## License

MIT
