# Technology Stack

**Analysis Date:** 2026-03-14

## Languages

**Primary:**
- Python 3.11+ (3.11 - 3.12) - All application code and entry point

**Secondary:**
- Batch/Shell scripts - Update installation on Windows/macOS

## Runtime

**Environment:**
- Python 3.11 or 3.12 (minimum >= 3.11, < 3.13)
- Requires `uv` package manager for development

**Package Manager:**
- `uv` (modern Python project manager) - Development and production
- Lockfile: `uv.lock` present

## Frameworks

**Core:**
- `wxPython >= 4.2` - Desktop GUI framework (cross-platform: Windows, macOS, Linux)

**Async/Concurrency:**
- `asyncio` (Python standard library) - Async operations for SFTP/SSH
- `threading` (Python standard library) - Background worker threads for transfers

**Protocol Support:**
- `asyncssh >= 2.14` - SSH, SFTP, SCP protocol implementation
- `ftplib` (Python standard library) - FTP/FTPS protocol
- `ssl` (Python standard library) - FTPS encryption
- `webdavclient3 >= 3.14` - WebDAV protocol (optional dependency)

**Testing:**
- `pytest >= 9.0` - Test runner
- `pytest-cov >= 7.0` - Code coverage reports
- `pytest-xdist >= 3.0` - Parallel test execution
- `diff-cover >= 9.0.0` - Coverage comparison and reporting

**Build/Dev:**
- `ruff >= 0.15.0` - Linting and code formatting (unified tool)
- `hatchling` - Build backend (in pyproject.toml)

## Key Dependencies

**Critical:**
- `asyncssh 2.22.0` - SSH/SFTP client library, handles all remote protocol operations
- `wxPython >= 4.2` - GUI framework, all user interface components
- `keyring >= 25.0` - System keyring access for password storage (Tier 1)
- `cryptography 46.0.5` - Fernet encryption for local vault passwords (Tier 2), SSH key handling, FTPS support

**Security/Storage:**
- `puttykeys` - PuTTY private key format (.ppk) support for SSH authentication
- Cryptography ecosystem: cffi, typing-extensions (asyncssh dependencies)

**Infrastructure:**
- `certifi 2026.2.25` - CA certificate bundle for HTTPS verification
- `chardet 7.0.1` - Character encoding detection (for importers)
- `charset-normalizer 3.4.5` - Character encoding normalization

**Testing/Dev:**
- `coverage 7.13.4` - Code coverage measurement
- `pytest` ecosystem tools
- `pluggy`, `jinja2`, `pygments` - Testing and reporting

## Configuration

**Environment:**
- Development and production share same Python environment
- Single-instance lock file: `{temp_dir}/portkeydrop.lock`

**Build:**
- `pyproject.toml` - Project metadata and tool configuration
- `uv.lock` - Locked dependency versions for reproducible builds
- Tool configs: `[tool.ruff]`, `[tool.pytest.ini_options]`, `[tool.coverage.run]`

**Runtime Configuration:**
- `~/.portkeydrop/` directory (standard mode) or `<exe_dir>/data/` (portable mode)
- `settings.json` - User settings (display, transfer, connection, speech)
- `sites.json` - Saved connection profiles
- `vault.enc` - Encrypted password vault (portable mode or when keyring unavailable)
- `transfer_queue.json` - Persisted transfer jobs

## Platform Requirements

**Development:**
- Python 3.11 or 3.12 installed
- `uv` package manager
- Platform-specific build tools for wxPython (system libraries vary by OS)

**Production:**
- **Windows:** Standalone executable (PyInstaller), or Python 3.11+
- **macOS:** .app bundle or Python 3.11+
- **Linux:** Python 3.11+ with system wxPython dependencies

**Deployment Targets:**
- Windows (7+), macOS (10.9+), Linux (various distributions)
- Portable ZIP mode for Windows (all dependencies bundled)

## Key Technical Characteristics

- **Async-first for I/O:** asyncssh operations on dedicated event loop in background thread
- **Three-tier password storage:** System keyring (Tier 1) > Encrypted Fernet vault (Tier 2) > Memory only (Tier 3)
- **Cross-platform:** Single codebase via wxPython and native Python libraries
- **Self-updating:** Built-in GitHub release-based auto-update mechanism
- **Minimal external HTTP:** Only GitHub API for update checks (urllib.request, no requests library)

---

*Stack analysis: 2026-03-14*
