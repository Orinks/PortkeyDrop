# Coding Conventions

**Analysis Date:** 2026-03-14

## Naming Patterns

**Files:**
- Snake case: `transfer_service.py`, `local_files.py`, `site_manager.py`
- Module-specific test files: `test_<module_name>.py` in `tests/` directory
- UI dialogs: `transfer.py`, `settings.py`, `properties.py` in `dialogs/` subdirectory

**Functions:**
- Snake case: `list_local_dir()`, `navigate_local()`, `check_ssh_agent_available()`
- Private functions prefixed with single underscore: `_get_lock_path()`, `_acquire_lock()`, `_release_lock()`, `_derive_machine_key()`
- Helper functions at module level prefixed with underscore: `_fake_set()`, `_fake_get()` in test files

**Variables:**
- Snake case throughout: `concurrent_transfers`, `default_download_dir`, `is_portable_mode`
- Constants in UPPER_SNAKE_CASE: `DEFAULT_CONFIG_DIR`, `KEYRING_SERVICE`, `TransferStatus.PENDING`
- Module-level logger instances: `logger = logging.getLogger(__name__)`
- Fake/mock storage for testing: `_fake_store` (module-level dict)

**Types:**
- Dataclass names: PascalCase: `Site`, `Settings`, `TransferJob`, `TransferSettings`, `DisplaySettings`, `ConnectionDefaults`, `SpeechSettings`, `AppSettings`
- Enum classes: PascalCase: `TransferDirection`, `TransferStatus`, `Protocol`
- Type hints with forward annotations: `from __future__ import annotations` at top of every module
- Union syntax: `str | None` (Python 3.10+ union syntax)

## Code Style

**Formatting:**
- Line length: 100 characters (configured in `pyproject.toml`)
- Tool: Ruff (both linter and formatter)
- Target Python: 3.11+ (`requires-python = ">=3.11,<3.13"`)
- Indentation: 4 spaces (standard Python)

**Linting:**
- Tool: Ruff `>=0.15.0`
- Command: `uv run ruff check --fix .` then `uv run ruff format .`
- Configuration: `[tool.ruff]` in `pyproject.toml`
- No special rules visible in checked files; uses Ruff defaults

## Import Organization

**Order:**
1. `from __future__ import annotations` (always first, on every module)
2. Standard library imports (`import logging`, `import json`, `from pathlib import Path`)
3. Third-party imports (`import pytest`, `import wx`, `from cryptography.fernet import Fernet`)
4. Local imports (`from portkeydrop.portable import get_config_dir`)

**Path Aliases:**
- No import aliases observed; uses full absolute imports from package root
- Example: `from portkeydrop.protocols import ConnectionInfo, Protocol`
- Tests import directly: `from portkeydrop.sites import Site, SiteManager, _VaultStore`

**Lazy Imports:**
- Conditional imports for optional dependencies: `try/except ImportError` pattern used in `sites.py` for keyring and cryptography modules
- wx (wxPython) imported in functions rather than at module level when optional: `import wx` inside function blocks

## Error Handling

**Patterns:**
- Explicit exception catching with type specification: `except (PermissionError, OSError) as e:`
- Context manager support: `with (patch(...), patch(...)):` for multiple context managers
- Exception chaining: `raise ConnectionError(...) from e`
- Broad exception catch followed by fallback: `except Exception:` with `pass` for non-critical paths (e.g., wx import failure in main.py)
- Warning logging on exceptions in recovery paths: `logger.warning(f"Keyring store failed: {e}")`

**Custom Exceptions:**
- Built-in exceptions used: `NotADirectoryError`, `FileNotFoundError`, `FileExistsError`, `ValueError`, `ConnectionError`, `RuntimeError`
- No custom exception classes defined in analyzed modules

**Null Safety:**
- Defensive null checks: `if not password:` before operations
- Optional returns: `return None` for missing items
- Empty string as "no value": `password = ""` (default) in dataclass fields
- Type hints: `str | None` for nullable fields

## Logging

**Framework:** Python's standard `logging` module

**Patterns:**
- Module-level logger initialization: `logger = logging.getLogger(__name__)` immediately after imports
- Log levels used:
  - `logger.debug()`: Fine-grained informational events (SSH key policy decisions, initialization details)
  - `logger.info()`: Significant events (transfer starts, update checks scheduled)
  - `logger.warning()`: Warning conditions (failed keyring operations, missing resources, unreadable directories)
  - `logger.exception()`: Error conditions with traceback (remote operations that fail)
  - `logger.error()`: Error events without traceback (checksum verification failures)
- String formatting: f-strings: `f"Keyring store failed: {e}"`
- Parameterized logging: `logger.warning("Cannot list directory %s: %s", directory, e)`
- Exception info: `logger.debug("Failed to set initial focus", exc_info=True)`

## Comments

**When to Comment:**
- Multi-step operations: `# Portable builds should keep credentials in local data/ (vault.enc)...`
- Non-obvious control flow: Comments before conditional blocks explaining why
- Domain-specific context: Password storage tier descriptions in `sites.py`

**JSDoc/TSDoc:**
- Python docstrings (module and function level) in triple-quote format
- Functions have detailed docstrings describing behavior, parameters, and return values
- Example from `ssh_utils.py`:
  ```python
  """Check whether an SSH agent is available on the current platform.

  Checks for the following agent sources in order:

  - **Linux/macOS**: ``SSH_AUTH_SOCK`` environment variable pointing to
    an existing Unix socket.
  - **Windows (OpenSSH)**: The named pipe
    ``\\\\.\\pipe\\openssh-ssh-agent``.

  Returns:
      ``True`` if at least one SSH agent source is detected, ``False``
      otherwise.
  """
  ```
- Uses reStructuredText-style formatting for docs (bullet points, inline code with backticks)

## Function Design

**Size:**
- Functions stay concise; 20-50 lines typical
- Complex logic broken into smaller helpers (e.g., `_derive_machine_key()`, `_load()`, `_save()` as private methods)

**Parameters:**
- Positional parameters for required inputs
- Keyword arguments for optional behavior (e.g., `skip_prompt: bool = False` in `_acquire_lock()`)
- Type hints on all parameters: `def list_local_dir(directory: str | Path) -> list[RemoteFile]:`
- Default values for optional parameters

**Return Values:**
- Explicit return types in all function signatures
- Return early on failure: `if not ...: return`
- Return copies of internal state: `return list(self._sites)` (not the actual list reference)
- None for missing items: `return None` (not empty/default values)

## Module Design

**Exports:**
- All public APIs exported directly; no `__all__` observed
- Private module-level classes/functions prefixed with `_`: `_VaultStore`, `_PasswordBackend`, `_fake_set()`
- Dataclass instances exported for use: `Site()`, `Settings()`

**Barrel Files:**
- No barrel/index files with wildcard imports observed
- Explicit imports of specific classes/functions: `from portkeydrop.sites import Site, SiteManager`

## Dataclass Usage

**Pattern:**
- Dataclasses used for data containers with default factories:
  ```python
  @dataclass
  class Site:
      id: str = field(default_factory=lambda: str(uuid.uuid4()))
      name: str = ""
      protocol: str = "sftp"
  ```
- Nested dataclasses for hierarchical settings: `Settings` contains `TransferSettings`, `DisplaySettings`, `ConnectionDefaults`, etc.
- Conversion methods on dataclasses: `def to_connection_info(self) -> ConnectionInfo:`, `def to_dict(self) -> dict:`
- Deserialization from dict with field filtering: `Site(**{k: v for k, v in s.items() if k in Site.__dataclass_fields__})`

## Concurrency

**Pattern:**
- Thread-based concurrency using `threading.Thread` and `threading.Event`
- Worker thread pattern in `TransferService`: multiple daemon threads processing from a queue
- Thread-safe job cancellation via `cancel_event` fields on dataclasses
- No async/await usage in main codebase; synchronous threading model

---

*Convention analysis: 2026-03-14*
