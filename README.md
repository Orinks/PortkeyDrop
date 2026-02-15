# AccessiTransfer

Accessible file transfer client for screen reader users. Supports FTP, SFTP, FTPS, SCP, and WebDAV with a keyboard-driven, dual-pane interface designed for NVDA and JAWS compatibility.

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

## Install

```bash
uv sync
uv run accessitransfer
```

On Linux, install wxPython from the prebuilt wheel:
```bash
pip install -f https://extras.wxpython.org/wxPython4/extras/linux/gtk3/ubuntu-24.04 wxPython
```

## Development

```bash
uv sync --group dev
uv run pytest
uv run ruff check
```

## License

MIT
