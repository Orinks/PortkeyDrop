# Architecture

**Analysis Date:** 2026-03-14

## Pattern Overview

**Overall:** MVC + Service Layer with Protocol Abstraction

**Key Characteristics:**
- Dual-pane file browser UI (wxPython) with local and remote sides
- Protocol-agnostic transfer via abstract `TransferClient` interface
- Service-owned transfer queue with worker thread pool (async operations)
- Stateless UI dialogs observing service state
- Configuration and credentials management with three-tier password storage

## Layers

**Presentation (UI):**
- Purpose: User interaction, dialogs, menu/toolbar bindings, file list display
- Location: `src/portkeydrop/app.py`, `src/portkeydrop/dialogs/`
- Contains: wxPython frames, dialogs, event handlers, screen reader announcements
- Depends on: Services (transfer, updater), protocols, sites, settings
- Used by: Application entry point

**Services:**
- Purpose: Core business logic, async operations, state management
- Location: `src/portkeydrop/services/`
- Contains: `TransferService` (queue + worker pool), `UpdateService` (auto-updates, checksum verification)
- Depends on: Protocols, settings
- Used by: Main application frame

**Protocol Abstraction:**
- Purpose: Unified interface for file transfer operations across FTP/FTPS/SFTP/SCP/WebDAV
- Location: `src/portkeydrop/protocols.py`
- Contains: `TransferClient` abstract base, `FTPClient`, `SFTPClient` (async), `ConnectionInfo` dataclass
- Depends on: None (self-contained)
- Used by: Services, main app

**Configuration & Credentials:**
- Purpose: Settings persistence, site profiles, password management
- Location: `src/portkeydrop/settings.py`, `src/portkeydrop/sites.py`
- Contains: Settings dataclasses, `SiteManager`, three-tier vault (`_VaultStore`, keyring, Fernet encryption)
- Depends on: Portable config directory detection
- Used by: UI, services

**Utilities:**
- Purpose: Cross-cutting operations
- Location: `src/portkeydrop/local_files.py`, `src/portkeydrop/ssh_utils.py`, `src/portkeydrop/migration.py`
- Contains: Local filesystem operations (mirrored to `RemoteFile` API), SSH agent detection, data migration
- Depends on: Protocols (for `RemoteFile` compatibility)
- Used by: Services, app

## Data Flow

**Connection Flow:**

1. User enters connection info in toolbar or dialog → `ConnectionInfo` dataclass
2. Main app calls `create_client(info)` → returns appropriate `TransferClient` subclass
3. Client connects, returns list of `RemoteFile` objects
4. Main app displays remote file list

**Transfer Flow:**

1. User selects file(s) and triggers upload/download
2. Main app calls `transfer_service.submit_download()` or `submit_upload()` → creates `TransferJob`
3. Job enqueued in `TransferService._queue` (thread-safe with `threading.RLock()`)
4. Worker threads pop jobs, execute via `_execute_download()` or `_execute_upload()`
5. Worker calls protocol client methods with progress callback
6. Transfer dialog observes job list, updates UI via custom wx events (`TransferEventBinder`)
7. On completion, job status updated; dialog observes but **does NOT control** job
8. Job persisted to `queue.json` on app exit

**Settings & Credentials:**

1. App loads `Settings` from `~/.portkeydrop/settings.json` at startup
2. Site profiles stored in `~/.portkeydrop/sites.json` (credentials in separate vault)
3. Password lookup: Keyring → Fernet vault → prompt user
4. After login, credentials optionally saved to keyring (Tier 1) or vault (Tier 2)

**State Management:**
- `MainFrame` holds reference to active `_client`, current working directories (`_remote_cwd`, `_local_cwd`)
- Transfer state owned by `TransferService`, NOT the UI
- Settings changes persist immediately to disk
- Sites are loaded once on startup and reloaded when manager dialog closes

## Key Abstractions

**TransferClient (Abstract):**
- Purpose: Protocol-agnostic interface for file operations
- Examples: `FTPClient`, `SFTPClient` (async), `WebDAVClient` (when installed)
- Pattern: Abstract base class with concrete subclasses for each protocol
- Key methods: `connect()`, `disconnect()`, `list_dir()`, `chdir()`, `download()`, `upload()`, `delete()`, `mkdir()`, `rename()`

**RemoteFile (Dataclass):**
- Purpose: Unified representation of remote OR local files
- Pattern: Used by both `TransferClient.list_dir()` and `list_local_dir()` for symmetric API
- Includes: `name`, `path`, `size`, `is_dir`, `modified`, `permissions`, display formatters

**TransferJob (Dataclass):**
- Purpose: Represents a queued transfer with lifecycle state
- Pattern: Immutable public fields, internal `_client` and `_recursive` fields for workers
- States: PENDING → IN_PROGRESS → COMPLETE/FAILED/CANCELLED
- Persistence: Serialized to `queue.json` (Tier 1: PENDING, FAILED, RESTORED jobs only)

**TransferService:**
- Purpose: Central queue and worker thread pool ownership
- Pattern: Singleton-like (one instance per app), thread-safe with `threading.RLock()`
- Features: Configurable worker count, progress callbacks, job persistence/restoration

**SiteManager:**
- Purpose: Persistent connection profiles
- Pattern: Lazy-loads JSON from disk, reloads on demand
- Storage: `sites.json` (metadata) + vault (passwords), machine-keyed encryption

**ScreenReaderAnnouncer:**
- Purpose: Accessibility layer for screen readers
- Pattern: Lazy-loads prismatoid/prism backend with graceful fallback
- Usage: App announces file counts, transfer progress, errors to screen reader

## Entry Points

**`main()` in `main.py`:**
- Location: `src/portkeydrop/main.py`
- Triggers: User runs `portkeydrop` command
- Responsibilities: Single-instance lock handling, logging setup, wx module verification, application launch

**`PortkeyDropApp` in `app.py`:**
- Location: `src/portkeydrop/app.py`
- Triggers: Instantiated in `main()` to create `MainFrame` and start `MainLoop()`
- Responsibilities: Application object initialization (handled by wxPython base class)

**`MainFrame.__init__()` in `app.py`:**
- Location: `src/portkeydrop/app.py:99-143`
- Triggers: Called when `PortkeyDropApp.MainLoop()` starts
- Responsibilities: Build UI (menu, toolbar, dual pane, status bar), load settings, restore transfer queue, start auto-update checks

## Error Handling

**Strategy:** Try-except at boundaries, log and notify user via dialogs

**Patterns:**
- Connection errors → Display message box, stay disconnected
- Transfer errors → Mark job as FAILED, persist to queue, allow retry
- Settings load failure → Log warning, fall back to defaults
- Password lookup failure → Fall back to next tier (vault → prompt)
- Update verification failure → Catch `ChecksumVerificationError`, warn user, skip update

## Cross-Cutting Concerns

**Logging:**
- Uses Python standard `logging` module
- Configurable level via `--debug` flag in `main()`
- Optional file output via `--log=` argument

**Validation:**
- Connection info validated on connect attempt (protocol-specific)
- File paths validated before transfer (local checks via `Path.resolve()`)
- Host key validation via policy (AUTO_ADD, STRICT, PROMPT)

**Authentication:**
- Three-tier: System keyring (preferred) → Fernet-encrypted local vault → interactive prompt
- SSH key support: `asyncssh` handles agent + key file paths
- Host key policy stored per connection, applied on connect

**Accessibility:**
- All interactive elements have `SetName()` for screen readers
- Announcements via `ScreenReaderAnnouncer` for file counts, progress, status
- Keyboard navigation: Menu shortcuts, focus switching (F6 cycles panes), Escape closes dialogs
