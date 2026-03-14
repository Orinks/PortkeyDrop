# External Integrations

**Analysis Date:** 2026-03-14

## APIs & External Services

**GitHub:**
- GitHub Releases API - Automatic update checking and download
  - SDK/Client: `urllib.request` (Python standard library)
  - Endpoint: `https://api.github.com/repos/Orinks/PortkeyDrop/releases?per_page=20`
  - Auth: None (public repository, GitHub anonymous rate limit ~60 req/hr)
  - Implementation: `src/portkeydrop/services/updater.py`

## Data Storage

**Databases:**
- None - Application uses file-based JSON storage only

**File Storage:**
- Local filesystem only (no cloud storage integration)
- User's local file system for SFTP/FTP/SCP downloads
- Default download directory: `~/Downloads`

**Local Configuration Files:**
- `settings.json` - JSON dataclass serialization
- `sites.json` - Connection profiles (plaintext, credentials stored separately)
- `vault.enc` - Encrypted password vault (Fernet encryption)
- `transfer_queue.json` - Persisted transfer jobs

**Caching:**
- None - No cache layer; all settings/profiles loaded on startup

## Authentication & Identity

**Auth Provider:**
- Custom implementation (no OAuth/SAML)
- Three-tier password storage system:
  1. **Tier 1 - System Keyring:** `keyring>=25.0` library
     - Uses OS-level credential managers (Windows Credential Manager, macOS Keychain, Linux secret-service)
     - Accessed via: `src/portkeydrop/sites.py` `_PasswordBackend` class
  2. **Tier 2 - Encrypted Local Vault:** `cryptography.fernet.Fernet`
     - File location: `{config_dir}/vault.enc`
     - Key derived from: machine hostname + current username (SHA256)
     - Used in portable mode or when keyring unavailable
  3. **Tier 3 - Memory Only:** Passwords not persisted between sessions

**SSH Key Authentication:**
- PuTTY key format (.ppk) support via `puttykeys` package
- Standard OpenSSH key formats via `cryptography`
- Implementation: `src/portkeydrop/protocols.py` `SFTPClient._read_ppk_*` methods

**Remote Server Auth (Protocols):**
- SFTP: Password, SSH keys (OpenSSH + PPK), host key verification policies
- SFTP Host Keys: Prompt, Auto-add, or Strict verification
- FTP: Username/password only
- FTPS: Username/password with TLS certificate verification
- SCP: Password, SSH keys
- WebDAV: Username/password with HTTP Basic auth

## Monitoring & Observability

**Error Tracking:**
- None - No external error tracking service integrated

**Logs:**
- File-based logging via Python `logging` module
- Log file: specified via `--log=<path>` CLI argument (optional)
- Stderr output for console errors
- Logging levels: DEBUG (with `--debug` flag) or WARNING (default)

## CI/CD & Deployment

**Hosting:**
- GitHub-hosted repository: https://github.com/Orinks/PortkeyDrop

**CI Pipeline:**
- GitHub Actions workflows (`.github/workflows/`)
  - `ci.yml` - Test and lint on PR
  - `build.yml` - Build artifacts (Windows EXE, macOS DMG/APP, Linux packages)
  - `push-releases.yml` - Publish releases to GitHub Releases
  - `update-pages.yml` - Deploy documentation to GitHub Pages
  - `update-wordpress.yml` - Sync release notes to WordPress (external blog)

**Distribution:**
- GitHub Releases API - Download source code and prebuilt binaries
- PyPI - Not packaged on PyPI (desktop app, not a library)
- Windows: `.exe` installer (NSIS) or portable `.zip`
- macOS: `.dmg` or `.app` bundle
- Linux: Manual install via Python

## Environment Configuration

**Required env vars:**
- None required for normal operation
- Optional: `--log=<path>` - Log file path (CLI argument, not env var)
- Optional: `--debug` - Enable debug logging (CLI argument)
- Optional: `--updated` - Post-update restart flag (internal use)

**Secrets location:**
- System keyring (OS-managed, Tier 1)
- Encrypted vault file: `~/.portkeydrop/vault.enc` or `<portable_dir>/data/vault.enc`
- Plaintext: Connection hostnames/usernames stored in `sites.json` (passwords separate)

**No .env files used** - Configuration via GUI and JSON files only

## Remote File Transfer Protocols

**Supported Protocols:**
- SFTP (SSH File Transfer Protocol) - `asyncssh >= 2.14`
- SCP (Secure Copy) - `asyncssh >= 2.14`
- FTP (File Transfer Protocol) - Python `ftplib`
- FTPS (FTP over TLS/SSL) - Python `ftplib` + `ssl`
- WebDAV (HTTP-based file transfer) - `webdavclient3 >= 3.14` (optional)

**Connection Management:**
- Pooled concurrent transfers (configurable, default 2 concurrent)
- Timeout: 30 seconds (configurable)
- Keep-alive: 60 seconds (configurable)
- Max retries: 3 (configurable)
- Host key policy: Auto-add, Prompt, or Strict (configurable)

## Webhooks & Callbacks

**Incoming:**
- None

**Outgoing:**
- None (no external callbacks)

## Import Integrations

**Third-party App Migration:**
- WinSCP - Connection import from `WinSCP.ini`
  - Location: `src/portkeydrop/importers/winscp.py`
- FileZilla - Connection import from `sitemanager.xml`
  - Location: `src/portkeydrop/importers/filezilla.py`
- CyberDuck - Connection import from `.duck` files
  - Location: `src/portkeydrop/importers/cyberduck.py`

## Update System

**GitHub Release Auto-Update:**
- Monitors: https://api.github.com/repos/Orinks/PortkeyDrop/releases
- Channels: `stable` (release) or `nightly` (pre-release builds)
- Checksums: SHA256 verification when available (from release assets)
- Download: Automatic to temp directory, applied on next restart
- Implementation: `src/portkeydrop/services/updater.py` `UpdateService` class

---

*Integration audit: 2026-03-14*
