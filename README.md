# Portkey Drop

A keyboard-driven file transfer client supporting FTP, SFTP, FTPS, SCP, and WebDAV. Dual-pane interface with full keyboard navigation and screen reader compatibility (NVDA, JAWS).

## Layout

Two side-by-side file browsers:
- **Left pane**: Local files (starts at your home directory)
- **Right pane**: Remote files (connected server)

Each pane is a labeled standard list control, so screen readers announce "Local Files" or "Remote Files" when you Tab between them.

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| Ctrl+T | Transfer: uploads from local pane, downloads from remote pane |
| Ctrl+U | Upload selected local file to remote |
| Ctrl+D | Download selected remote file to local |
| Ctrl+N | Quick Connect |
| Ctrl+S | Site Manager |
| Ctrl+R | Refresh active pane |
| Ctrl+F | Filter active pane |
| Ctrl+I | File properties |
| Ctrl+Shift+N | New directory |
| Ctrl+Shift+T | Transfer queue |
| Ctrl+Q | Disconnect |
| Enter | Open directory / download file |
| Backspace | Parent directory |
| Delete | Delete selected |
| F2 | Rename selected |

## Protocols

- **SFTP** (default) — SSH-based, most secure
- **FTP** — Legacy support
- **FTPS** — FTP over SSL/TLS
- **SCP** — Fast SSH transfers (planned)
- **WebDAV** — HTTP-based, cloud service compatible (planned)

## Security

Saved connection passwords are stored in your system's secure keyring (Windows Credential Locker, macOS Keychain, Linux Secret Service) and never written to disk in plaintext.

## Install

Portkey Drop currently supports Python 3.11 and 3.12.

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

## Experimental PySide6 settings dialog

Phase 1 of the PySide6 migration includes an experimental settings prototype alongside the existing wxPython app.

```bash
uv sync --extra qt
uv run portkeydrop --qt-settings-prototype
```

- This path is optional and non-default.
- The primary application still launches via wxPython (`uv run portkeydrop`).

## Development

```bash
uv sync --all-extras --group dev
uv run pytest
uv run ruff check
```

## License

MIT
