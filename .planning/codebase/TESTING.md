# Testing Patterns

**Analysis Date:** 2026-03-14

## Test Framework

**Runner:**
- pytest `>=9.0`
- Config: `pyproject.toml` with `[tool.pytest.ini_options]`
- Test paths: `testpaths = ["tests"]`

**Assertion Library:**
- pytest's built-in assertions with `assert` statements
- No custom assertion helpers; uses direct equality checks

**Run Commands:**
```bash
uv run pytest                          # Run all tests
uv run pytest -n auto                  # Parallel tests (pytest-xdist)
uv run pytest tests/test_file.py::test_func  # Single test
```

**Coverage:**
- Tool: pytest-cov
- Configuration in `pyproject.toml`:
  - Source: `source = ["src/portkeydrop"]`
  - Excluded lines: pragma comments, TYPE_CHECKING blocks, `if __name__ == "__main__":`
- Run: `uv run pytest --cov=src/portkeydrop --cov-report=html`

## Test File Organization

**Location:**
- Tests co-located in separate `tests/` directory (not embedded in source)
- One test module per source module: `tests/test_sites.py` for `src/portkeydrop/sites.py`
- 40+ test files total covering core and UI functionality

**Naming:**
- Test classes: `TestClassName` (PascalCase with `Test` prefix)
- Test methods: `test_specific_behavior()` (snake_case with `test_` prefix)
- Helper functions: `_helper_name()` (private prefix for non-test code)
- Fixture functions: Named with function notation, decorated with `@pytest.fixture()`

**Structure:**
```
tests/
├── test_sites.py
├── test_settings.py
├── test_local_files.py
├── test_transfer_service.py
├── test_protocols.py
├── _wx_stub.py                 # Shared test utility for mocking wxPython
└── [40+ other test modules]
```

## Test Structure

**Suite Organization:**

Class-based test grouping is standard. From `test_sites.py`:

```python
class TestSite:
    def test_defaults(self):
        site = Site()
        assert site.protocol == "sftp"

class TestSiteManager:
    """Core site manager tests (keyring backend)."""

    @pytest.fixture(autouse=True)
    def _use_keyring(self, mock_keyring):
        pass

    def test_empty_initially(self, tmp_path):
        mgr = SiteManager(tmp_path)
        assert mgr.sites == []

class TestKeyringBackend:
    """Tests specific to keyring password storage."""

    @pytest.fixture(autouse=True)
    def _use_keyring(self, mock_keyring):
        pass
```

**Patterns:**

1. **Setup via Fixtures:**
   - `tmp_path`: pytest built-in for temporary directories
   - `monkeypatch`: pytest built-in for patching module attributes
   - Custom fixtures with `@pytest.fixture()` decorator
   - Fixture dependencies injected as parameters
   - Autouse fixtures: `@pytest.fixture(autouse=True)` applied to all tests in class

2. **Teardown:**
   - Automatic cleanup via `tmp_path` fixture (deleted after test)
   - Manual cleanup in fixtures: `_fake_store.clear()` before each test using mock_keyring
   - Context managers for temporary patches: `with patch(...):` blocks

3. **Assertion Patterns:**
   - Direct equality: `assert mgr.sites == []`
   - Member checking: `assert len(mgr.sites) == 1`
   - Attribute checks: `assert site.protocol == "sftp"`
   - Absence checks: `assert "password" not in data[0]`
   - Existence checks: `assert (tmp_path / "vault.enc").exists()`
   - Exception checks: `with pytest.raises(ValueError, match="not found"):`

## Mocking

**Framework:** unittest.mock (Python stdlib)

**Patterns:**

```python
from unittest.mock import patch, MagicMock, AsyncMock

# Function-level patch
with patch("portkeydrop.sites._keyring_mod.set_password", _fake_set):
    # test code

# Fixture-based patching
@pytest.fixture()
def mock_keyring(monkeypatch):
    _fake_store.clear()
    import portkeydrop.sites as sites_mod
    monkeypatch.setattr(sites_mod, "_has_keyring", True)
    monkeypatch.setattr(sites_mod, "_has_fernet", True)
    with (
        patch("portkeydrop.sites._keyring_mod.set_password", _fake_set),
        patch("portkeydrop.sites._keyring_mod.get_password", _fake_get),
        patch("portkeydrop.sites._keyring_mod.delete_password", _fake_delete),
    ):
        yield
```

**What to Mock:**
- External services (keyring, cryptography)
- Filesystem operations (via tmp_path instead of mocking)
- wxPython GUI components (via custom `_wx_stub.py` module)
- Third-party network clients
- Threading (replaced with synchronous helpers in app tests)

**What NOT to Mock:**
- Internal dataclass constructors
- JSON serialization/deserialization (actual behavior tested)
- Local filesystem operations (use tmp_path)
- Core business logic

## Fixtures and Factories

**Test Data:**

From `test_sites.py`:

```python
@pytest.fixture()
def mock_keyring(monkeypatch):
    """Provide an in-memory keyring backend."""
    _fake_store.clear()
    # ...setup code...
    yield

@pytest.fixture()
def vault_only(monkeypatch):
    """Disable keyring, use encrypted vault only."""
    import portkeydrop.sites as sites_mod
    monkeypatch.setattr(sites_mod, "_has_keyring", False)
    monkeypatch.setattr(sites_mod, "_has_fernet", True)

@pytest.fixture()
def no_storage(monkeypatch):
    """Disable both keyring and vault."""
    import portkeydrop.sites as sites_mod
    monkeypatch.setattr(sites_mod, "_has_keyring", False)
    monkeypatch.setattr(sites_mod, "_has_fernet", False)
```

Factory pattern for building test objects:

```python
# In test_app.py
def _build_frame(module, tmp_path):
    app, _ = module
    display = SimpleNamespace(
        show_hidden_files=True,
        announce_file_count=False,
        sort_by="name",
        sort_ascending=True,
    )
    # ...construct and return test object...

def _hydrate_frame(module):
    app, _ = module
    frame = object.__new__(app.MainFrame)
    frame._announce = MagicMock()
    # ...inject mocks...
    return frame
```

**Location:**
- Fixtures defined in individual test modules (no conftest.py observed)
- Helper functions at module level: `_wait_for_status()`, `_build_frame()`, `_hydrate_frame()`
- Shared utilities: `tests/_wx_stub.py` for wxPython mocking

## Coverage

**Requirements:** No enforced coverage target visible

**View Coverage:**
```bash
uv run pytest --cov=src/portkeydrop --cov-report=html
uv run pytest --cov=src/portkeydrop --cov-report=term-missing
```

**Exclusions (from pyproject.toml):**
- Lines with `pragma: no cover` comment
- `if TYPE_CHECKING:` blocks
- `if __name__ == "__main__":` blocks

## Test Types

**Unit Tests:**
- Scope: Individual classes/functions
- Approach: Test behavior in isolation
- Examples: `TestSite` (dataclass defaults), `TestSettings` (load/save)
- Mocking: Optional; actual filesystem used via tmp_path

**Integration Tests:**
- Scope: Multiple components working together
- Approach: Real-world workflows
- Examples: `TestSiteManager` (adding/loading/removing sites with secure storage backends), `test_save_and_load` (settings round-trip)
- Mocking: Selective; external services mocked, internal components real

**E2E Tests:**
- Framework: Not observed in codebase
- wxPython UI testing handled via custom stubs in `_wx_stub.py` rather than true E2E

## Common Patterns

**Async Testing:**
- Not used; codebase uses threading instead of async/await
- Blocking waits in test helpers:
  ```python
  def _wait_for_terminal(job, timeout=5):
      """Block until job reaches a terminal status."""
      terminal = {TransferStatus.COMPLETE, TransferStatus.FAILED, TransferStatus.CANCELLED}
      deadline = time.monotonic() + timeout
      while job.status not in terminal and time.monotonic() < deadline:
          time.sleep(0.02)
  ```

**Error Testing:**

Exception handling is tested explicitly:

```python
def test_navigate_nonexistent_raises(self, tmp_path):
    with pytest.raises(NotADirectoryError):
        navigate_local(tmp_path, "nonexistent")

def test_update_missing_raises(self, tmp_path):
    mgr = SiteManager(tmp_path)
    site = Site(name="Ghost")
    with pytest.raises(ValueError, match="not found"):
        mgr.update(site)
```

**Parameterized Tests:**
- Not heavily used; individual test methods preferred
- Some tests use SimpleNamespace for variant configuration

**Fixture Scoping:**
- Fixture scope not explicitly specified; defaults to `function` scope
- Autouse fixtures applied per test function/method
- Manual setup/teardown via context managers where needed

**Isolation:**
- Tests modify tmp_path fixtures (fresh per test)
- Mock storage (`_fake_store`) manually cleared in fixtures
- monkeypatch isolation automatic (restored after test)

## Test Quality Notes

- **Coverage:** 906 test functions/methods across 40+ test modules
- **Maintainability:** Tests use clear naming and descriptive assertions
- **Readability:** Class-based organization groups related tests
- **Fixtures:** Heavy use of parametric fixtures to test multiple configurations (keyring, vault, no storage)
- **Real-world scenarios:** Tests include legacy data migration, corruption handling, cross-platform considerations

---

*Testing analysis: 2026-03-14*
