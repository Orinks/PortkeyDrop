# PortkeyDrop — AI Agent Guidelines

Cross-platform SFTP file transfer tool with screen reader accessibility. Package: `portkeydrop`. Config dir: `~/.portkeydrop`.

## Quick Reference

```bash
uv run ruff check --fix . && uv run ruff format .   # Lint + format
uv run pytest                                        # Run tests (132 tests)
uv run pytest tests/test_file.py::test_func          # Single test
uv run pytest -n auto                               # Parallel tests
```

## Branch Strategy

| Branch | Purpose |
|--------|---------|
| `main` | Stable releases |
| `dev` | Active development — PRs go here |
| `feature/*` | Feature work → PR to dev |
| `fix/*` | Bug fixes → PR to dev |

## Commit Format

Use conventional commits only. Do not use Lore commit trailers in this repo.
When committing from an OMX-enabled Codex surface, opt out of the Lore commit guard:

```bash
OMX_LORE_COMMIT_GUARD=0 git commit -m "type(scope): description"
```

PowerShell equivalent:

```powershell
$env:OMX_LORE_COMMIT_GUARD="0"; git commit -m "type(scope): description"
```

```
type(scope): description
Types: feat, fix, docs, style, refactor, test, chore
```

## PR Rules

- Always PR to `dev`, never `main`
- Title in Conventional Commit format
- Body via `--body-file` (never inline `--body`)
- Do not auto-merge

## Key Notes

- Three-tier password storage: keyring > encrypted vault > none
- Accessibility: all interactive UI elements need aria labels
- SFTP operations use `asyncssh`
