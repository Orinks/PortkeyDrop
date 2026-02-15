# AccessiTransfer

Accessible file transfer client for screen reader users. Supports FTP, SFTP, FTPS, SCP, and WebDAV with a keyboard-driven, dual-pane interface designed for NVDA and JAWS compatibility.

## Layout

Two side-by-side file browsers:
- **Left pane**: Local files (starts at your home directory)
- **Right pane**: Remote files (connected server)

Each pane is a labeled standard list control, so screen readers announce "Local Files" or "Remote Files" when you Tab between them. Upload with Ctrl+U (local → remote), download with Ctrl+D (remote → local) — no file picker dialogs needed.

## Protocols

- **SFTP** (default) — SSH-based, most secure
- **FTP** — Legacy support
- **FTPS** — FTP over SSL/TLS
- **SCP** — Fast SSH transfers
- **WebDAV** — HTTP-based, cloud service compatible

## Install

```bash
uv sync
uv run accessitransfer
```

## Development

```bash
uv sync --group dev
uv run pytest
uv run ruff check
```

## License

MIT
