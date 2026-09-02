# PortkeyDrop — AI Agent Guidelines

Cross-platform file transfer client (SFTP, FTP, FTPS, WebDAV) with screen
reader accessibility. Written in Rust; the UI uses wxDragon. Config lives in
the platform's config folder (`%APPDATA%\PortkeyDrop`, `~/Library/Application
Support`, `~/.config/portkeydrop`), or `<exe dir>/data` in portable mode.

## Quick Reference

```bash
cargo test                     # Run the test suite
cargo test -p portkeydrop-core # One crate
cargo build                    # Debug build
cargo clippy --all-targets     # Lints
cargo fmt                      # Format
```

## Layout

| Crate | Contents |
|---|---|
| `portkeydrop` | wxWidgets front end (wxDragon): window, panes, dialogs |
| `portkeydrop-core` | Protocols, transfers, settings, sites, sound packs, updates |
| `prism` | Safe wrapper over the Prism speech library |
| `prism-sys` | Raw FFI to Prism's C API; platform binaries vendored under `vendor/` |

`portkeydrop-core` never depends on the UI, so protocol parsing, transfer rules,
and credential handling are tested without a display.

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

## Nightly Builds

A nightly is published only when there is something new to tell the user:
`scripts/changelog_tools.py should-build-nightly` looks for `## Unreleased`
entries that neither the previous nightly nor the latest stable release has
already announced. A build whose changes are all internal therefore does not
ship a release whose notes read "No user-facing changes".

When a build matters for a reason that has no user-facing bullet — a
dependency bump, a fix inside a vendored library — say so in the commit and
it is built anyway:

```
fix(deps): bump russh to 0.62.1

nightly: build
```

`[nightly build]` works the same way. Both have to be a line of their own:
a commit that merely writes about the marker, such as a change to this
tooling, would otherwise set it off.

A change that touches user-facing files but has nothing to tell a user --
a rename, a refactor -- opts out of the CHANGELOG gate the same way, with
`Changelog: none` or `[skip changelog]` on its own line in **every** commit
of the range, or a `skip-changelog` label on the PR.

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

- Three-tier password storage: keyring > encrypted vault > none. Portable
  installs prefer the vault so credentials travel with the data folder.
- Accessibility: every interactive control needs an explicit accessible name
  via `set_name`, and list controls need a `StaticText` immediately before them
  (NVDA reads the preceding sibling as the list's name).
- SFTP uses `russh`; FTP/FTPS is implemented directly so the legacy `AUTH SSL`
  upgrade stays available; WebDAV uses `reqwest` plus a hand-written PROPFIND
  parser.
- Network work never runs on the UI thread. Workers post an `AppEvent` down a
  channel and a timer on the frame drains it.
- On Windows the binary embeds an application manifest requesting Common
  Controls 6. Without it wxWidgets' `GetWindowSubclass` import cannot resolve
  and the process will not start.
