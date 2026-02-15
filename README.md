# AccessiTransfer

Accessible file transfer client for screen reader users. Supports FTP, SFTP, FTPS, SCP, and WebDAV with a keyboard-driven, single-pane interface designed for NVDA and JAWS compatibility.

## Why?

Existing transfer clients (FileZilla, WinSCP) use dual-pane layouts that are painful with screen readers. AccessiTransfer takes a single-pane approach where every action is keyboard-accessible and every state change is spoken.

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
