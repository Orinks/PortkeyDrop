# Codebase Structure

**Analysis Date:** 2026-03-14

## Directory Layout

```
/home/openclaw/projects/PortkeyDrop/
├── src/portkeydrop/
│   ├── __init__.py                 # Version and package exports
│   ├── main.py                     # Entry point: single-instance lock, logging setup
│   ├── app.py                      # MainFrame: dual-pane UI, menu/toolbar, event routing
│   │
│   ├── protocols.py                # TransferClient abstraction (FTP, SFTP, etc.)
│   ├── host_key_policy.py          # SSH host key verification policies
│   ├── ssh_utils.py                # SSH agent detection utilities
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── transfer_service.py     # TransferService: queue, worker pool, job lifecycle
│   │   └── updater.py              # UpdateService: auto-update checks, checksum verification
│   │
│   ├── dialogs/
│   │   ├── __init__.py
│   │   ├── transfer.py             # TransferDialog: stateless queue observer, job list UI
│   │   ├── site_manager.py         # Site management UI
│   │   ├── settings.py             # Settings UI with transfer/display/connection/speech tabs
│   │   ├── quick_connect.py        # One-off connection dialog
│   │   ├── properties.py           # File properties viewer
│   │   ├── import_connections.py   # Bulk import from other FTP clients
│   │   └── host_key_dialog.py      # Host key verification prompt
│   │
│   ├── ui/
│   │   ├── __init__.py
│   │   └── dialogs/
│   │       ├── migration_dialog.py # Data migration UI for v0.1→v0.2 upgrade
│   │       └── update_dialog.py    # Update available notification
│   │
│   ├── sites.py                    # SiteManager: site profiles with 3-tier vault
│   ├── settings.py                 # Settings: dataclasses + load/save
│   ├── screen_reader.py            # ScreenReaderAnnouncer: accessibility layer
│   ├── local_files.py              # Local filesystem operations (mirror remote API)
│   ├── portable.py                 # Portable mode detection, config dir resolution
│   ├── migration.py                # Data migration utilities
│   │
│   └── importers/
│       ├── __init__.py
│       ├── models.py               # ImportedSite dataclass
│       ├── cyberduck.py            # Import from Cyberduck profiles
│       ├── filezilla.py            # Import from FileZilla sites.xml
│       └── winscp.py               # Import from WinSCP registry
│
├── tests/
│   ├── __init__.py
│   ├── test_app.py                 # Main app frame tests
│   ├── test_transfer_service.py    # Transfer queue and worker tests
│   ├── test_sites.py               # Site manager and vault tests
│   ├── test_settings_dialog_a11y.py # Settings dialog accessibility
│   ├── test_properties_dialog_a11y.py
│   ├── test_host_key_dialog.py     # Host key verification
│   ├── test_host_key_policy.py     # SSH key policy logic
│   ├── test_password_backend.py    # Keyring/vault integration
│   ├── test_ssh_agent_auth.py      # SSH agent detection
│   ├── test_updater.py             # Auto-update logic
│   ├── test_transfer_dialog.py     # Queue UI
│   ├── test_import_connections_dialog.py
│   ├── test_importers_winscp.py
│   ├── test_queue_during_transfer.py # Concurrent transfer scenarios
│   ├── test_migration_dialog.py
│   ├── test_portable.py            # Portable mode behavior
│   ├── test_screen_reader.py       # Accessibility announcements
│   ├── test_ui_logic.py            # File browser navigation, filtering
│   ├── test_wordpress_release_page.py # Update checker parsing
│   └── conftest.py                 # Pytest fixtures (if exists)
│
├── pyproject.toml                  # Build config, dependencies, test/lint settings
├── CLAUDE.md                       # Developer guidelines
└── .planning/codebase/             # (Generated) Architecture documentation
```

## Directory Purposes

**`src/portkeydrop/`:**
- Purpose: Main application package
- Contains: All Python source code organized by concern
- Key files: `main.py` (entry), `app.py` (UI), `protocols.py` (transfer abstraction)

**`src/portkeydrop/services/`:**
- Purpose: Service layer for core business logic
- Contains: Transfer queue management, update checks
- Key files: `transfer_service.py` (owns worker threads), `updater.py` (auto-update)

**`src/portkeydrop/dialogs/`:**
- Purpose: Modal and modeless dialogs for user interactions
- Contains: File operations, connection, settings, site management, transfer queue
- Key files: `transfer.py` (queue observer), `site_manager.py` (profile CRUD), `settings.py` (preferences)

**`src/portkeydrop/ui/dialogs/`:**
- Purpose: Additional modal dialogs (separate from main dialogs dir for organizational clarity)
- Contains: Update notifications, data migration prompts
- Key files: `update_dialog.py` (new version available), `migration_dialog.py` (legacy data import)

**`src/portkeydrop/importers/`:**
- Purpose: Bulk import from other FTP/SFTP clients
- Contains: Client-specific parsers (Cyberduck, FileZilla, WinSCP)
- Key files: `models.py` (normalized import format), one parser per client

**`tests/`:**
- Purpose: Pytest test suite (132 tests)
- Contains: Unit, integration, UI (wxPython), accessibility, and end-to-end tests
- Key files: Test files match source modules (`test_*.py`)
- Run: `uv run pytest` or `uv run pytest -n auto` (parallel)

## Key File Locations

**Entry Points:**
- `src/portkeydrop/main.py`: Single-instance lock, logging, wx module check, app launch
- `src/portkeydrop/app.py:PortkeyDropApp`: wxPython app object (inherits from `wx.App`)
- `src/portkeydrop/app.py:MainFrame`: Main window (inherits from `wx.Frame`)

**Configuration:**
- `~/.portkeydrop/settings.json`: User settings (transfer, display, connection, speech, app)
- `~/.portkeydrop/sites.json`: Site profile metadata
- `~/.portkeydrop/vault.json`: Encrypted credentials (Fernet-encrypted with machine key)
- `~/.portkeydrop/queue.json`: Persisted transfer jobs (pending, failed, restored only)

**Core Logic:**
- `src/portkeydrop/protocols.py`: `TransferClient` abstraction and protocol implementations
- `src/portkeydrop/services/transfer_service.py`: Transfer queue, worker pool, job lifecycle
- `src/portkeydrop/sites.py`: Connection profiles, three-tier password management
- `src/portkeydrop/settings.py`: Application settings with defaults

**Testing:**
- `tests/conftest.py`: Pytest fixtures (if exists; check for mocking, fixtures)
- `tests/test_transfer_service.py`: Queue and concurrent worker tests
- `tests/test_sites.py`: Vault encryption/decryption tests
- `tests/test_app.py`: Main frame integration tests

## Naming Conventions

**Files:**
- Source: `lowercase_with_underscores.py` (PEP 8)
- Dialogs: `*_dialog.py` or `*_dialog.py` in `dialogs/` subdirectory
- Tests: `test_*.py` (pytest discovery)
- Modules containing protocols: `protocol_name.py` (e.g., `sftp_client.py` in protocols)

**Directories:**
- Feature packages: `lowercase/` (e.g., `services/`, `dialogs/`, `importers/`)
- Nested UI layers: `ui/dialogs/` for secondary dialogs

**Classes:**
- Abstract base: `TransferClient` (no `ABC` suffix)
- Concrete protocol clients: `{FTPClient, SFTPClient}` (protocol + Client)
- Dialogs: `{QuickConnectDialog, SiteManagerDialog}` (name + Dialog)
- Services: `{TransferService, UpdateService}` (name + Service)
- Managers: `SiteManager` (name + Manager)

**Functions:**
- Private: `_leading_underscore()` (e.g., `_acquire_lock()`)
- Public: `lowercase_with_underscores()` (e.g., `list_local_dir()`)
- Event handlers: `_on_*()` (e.g., `_on_toolbar_protocol_change()`)

**Variables:**
- Private class fields: `self._field_name`
- Module-level constants: `UPPERCASE_CONSTANT` (e.g., `KEYRING_SERVICE`, `DEFAULT_CONFIG_DIR`)

**Types:**
- Protocol enums: `class Protocol(Enum)` with lowercase values (`Protocol.SFTP`)
- Status enums: `class TransferStatus(Enum)`
- Dataclasses: `@dataclass` for immutable value objects

## Where to Add New Code

**New Feature (File Transfer Operation):**
- Primary code: `src/portkeydrop/services/transfer_service.py` (worker logic)
- Protocol implementation: `src/portkeydrop/protocols.py` (add method to `TransferClient` abstract class, implement in `FTPClient`/`SFTPClient`)
- UI: `src/portkeydrop/app.py` (add menu item, event handler) + dialog if needed
- Tests: `tests/test_transfer_service.py` (worker tests), `tests/test_app.py` (UI tests)

**New Dialog/UI:**
- Implementation: `src/portkeydrop/dialogs/{feature_name}.py` or `src/portkeydrop/ui/dialogs/` if secondary
- Event binding in main app: `src/portkeydrop/app.py` (add wx ID, menu item, event handler)
- Tests: `tests/test_{feature_name}_dialog.py` or `tests/test_{feature_name}_a11y.py` for accessibility
- Accessibility: Set `SetName()` on all controls, add screen reader announcements via `ScreenReaderAnnouncer`

**New Importer:**
- Implementation: `src/portkeydrop/importers/{client_name}.py`
- Normalized model: Use `ImportedSite` from `src/portkeydrop/importers/models.py`
- Entry point: Register parser in `src/portkeydrop/dialogs/import_connections.py`
- Tests: `tests/test_importers_{client_name}.py`

**Utilities:**
- Shared helpers: `src/portkeydrop/{feature_name}.py` (e.g., `local_files.py`, `ssh_utils.py`, `portable.py`)
- Tests: `tests/test_{feature_name}.py`

**Configuration:**
- Settings: Add dataclass field to `Settings` hierarchy in `src/portkeydrop/settings.py`, add UI to `src/portkeydrop/dialogs/settings.py`
- Protocol defaults: `src/portkeydrop/settings.py:ConnectionDefaults`

## Special Directories

**`.planning/codebase/`:**
- Purpose: Generated architecture documentation (ARCHITECTURE.md, STRUCTURE.md, etc.)
- Generated: Yes (created by `/gsd:map-codebase` command)
- Committed: Yes (stored in `.planning/` git subdirectory)

**`~/.portkeydrop/`:**
- Purpose: Runtime user configuration directory
- Generated: Yes (created on first run)
- Committed: No (local machine-specific)
- Contents: `settings.json`, `sites.json`, `vault.json`, `queue.json`

**`.venv/`:**
- Purpose: Python virtual environment (uv-managed)
- Generated: Yes (created by `uv sync`)
- Committed: No (in .gitignore)

**`.pytest_cache/` and `.ruff_cache/`:**
- Purpose: Tool caches
- Generated: Yes
- Committed: No
