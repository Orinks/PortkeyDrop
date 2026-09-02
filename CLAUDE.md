# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# PortkeyDrop — AI Agent Guidelines

Cross-platform file transfer client (SFTP, FTP, FTPS, WebDAV) with screen
reader accessibility. Written in Rust; the UI uses wxDragon (wxWidgets).
Config lives in the platform's config folder (`%APPDATA%\PortkeyDrop`,
`~/Library/Application Support`, `~/.config/portkeydrop`), or `<exe dir>/data`
in portable mode. An older `~/.portkeydrop` is copied across on first start.

## Quick Reference

```bash
cargo test                                  # Whole workspace (builds wxWidgets first time: slow)
cargo test -p portkeydrop-core              # One crate, no UI dependency, fast
cargo test -p portkeydrop-core known_hosts  # Tests whose name contains a string
cargo test -p portkeydrop-core --test host_key_journey   # One integration test file
cargo build                                 # Debug build
cargo clippy --workspace --all-targets -- -D warnings    # What the push hook and CI run
cargo fmt --all --check                     # What the commit hook and CI run

wsl -d Ubuntu -- bash scripts/linux-check.sh   # The Core (Ubuntu) CI job, locally
python -m pytest tests/test_changelog_tools.py -q   # The only Python tests left
```

`pre-commit install` sets up both hook types: `cargo fmt --check` on commit,
clippy and the full test suite on push. CI builds with `RUSTFLAGS="-D warnings"`,
so a warning that passes locally still fails there.

On Windows every `cfg(unix)` block is compiled out, so a clean local clippy
says nothing about the code inside one. `scripts/linux-check.sh` runs the
Core (Ubuntu) job's commands through WSL; use it before pushing anything
that touches platform-gated code.

The live SSH host-key tests (`host_key_live`, `host_key_journey`) skip
themselves unless `PORTKEYDROP_TEST_SSHD=host:port` is set.
`scripts/host-key-harness.sh` stands up a throwaway sshd for them.

## CI shape

- **Core (Ubuntu)** runs clippy and tests for `portkeydrop-core`, `prism`,
  `prism-sys` only. It needs ALSA and D-Bus dev packages even without a UI:
  rodio and the keyring crate link them.
- **App (Windows)** runs clippy and tests for the whole workspace, including
  the wxWidgets front end. macOS and Linux front ends are only compiled by the
  release workflow (`build.yml`), which is where platform breaks surface.
- **Release tooling** runs the pytest file for `scripts/changelog_tools.py`.
- **CHANGELOG Check** runs on `dev` and PRs to it (see below).

## CHANGELOG gate

A change touching `crates/`, `installer/`, `Cargo.toml`, or
`rust-toolchain.toml` (excluding `/tests/` and `/benches/` paths) must add an
entry under `## Unreleased` in `CHANGELOG.md`. Entries are user-facing prose
grouped under Added, Changed, Fixed, Improved, Removed, Deprecated, Security;
release notes are generated from them, not from PR titles.

To opt out when there is genuinely nothing to tell a user (rename, refactor),
put `Changelog: none` or `[skip changelog]` on its own line in **every**
commit of the range, or add the `skip-changelog` label to the PR.

Nightlies only ship when `## Unreleased` has entries no previous nightly or
stable release announced. To force one for a change with no user-facing
bullet (a dependency bump), put `nightly: build` or `[nightly build]` on its
own line in the commit.

## Layout

| Crate | Contents |
|---|---|
| `portkeydrop` | wxWidgets front end (wxDragon): window, panes, dialogs, CLI flags, single-instance |
| `portkeydrop-core` | Protocols, transfers, settings, sites, credentials, sound packs, updater, importers |
| `prism` | Safe wrapper over the Prism speech library |
| `prism-sys` | Raw FFI to Prism's C API; platform binaries vendored under `vendor/` and loaded at run time |

`portkeydrop-core` never depends on the UI and is synchronously callable, so
protocol parsing, transfer rules, and credential handling are tested without
a display.

`src/` and `tests/` are leftovers from the Python application. The only live
Python is `scripts/changelog_tools.py` and its test.

## Architecture

**Protocols.** Every client implements `TransferClient`
(`crates/portkeydrop-core/src/protocols/mod.rs`) and is built through
`create_client`, so neither the UI nor the transfer engine branches on
protocol. `ProtocolError` variants are protocol-independent and user-facing.
Remote paths are always `/`-separated and go through `protocols::path`, never
`std::path`. SFTP uses `russh`; FTP/FTPS is hand-written so the legacy
`AUTH SSL` upgrade stays available; WebDAV is `reqwest` plus a PROPFIND parser,
with all path/URL translation in `webdav/url_map.rs`. Listings return
`RemoteFile` values carrying full paths.

**Transfers.** `TransferService` owns every job and a pool of plain OS thread
workers. The queue dialog is a disposable observer over it, so closing the
window never cancels a transfer. A `ChangeCallback` fires on worker threads;
the UI marshals it back itself.

**Threading in the UI.** wxWidgets objects are UI-thread only. Background work
(connect, list, transfer, update check) posts an `AppEvent`
(`crates/portkeydrop/src/ui/events.rs`) down an mpsc channel and a timer on
`MainFrame` drains it. `HostKeyPrompt` carries a reply sender and blocks the
worker until the UI answers; dropping it is a rejection. Tray menu commands are
routed through the channel too, because acting inside the icon's handler can
free the icon under wxWidgets.

**State.** `AppState` (`ui/state.rs`) holds everything that is not a widget:
settings, sites, transfer service, sounds, speech, the live connection. Widget
code borrows it once rather than juggling `Rc`s. Under test `audible` is off so
the suite does not talk over NVDA. Each file pane's model (`ui/view.rs`) is
widget-free so sorting, filtering, and cursor restoration are unit-tested.

**Menus and keys.** `ui/ids.rs` is one table of command ids, labels, and
accelerators; menus and the Keyboard Shortcuts window are both generated from
it. `ui/keys.rs` declares wx key codes by name; a bare `WXK_*` in a `match`
arm binds a fresh variable and matches everything. All standard dialogs go
through `ui/prompts.rs` so destructive prompts default to No.

**Configuration.** `sites.json` never holds passwords; `credentials.rs`
re-attaches them from a three-tier store: keyring > encrypted vault > none.
Portable installs prefer the vault so credentials travel with the data folder.
The vault key derives from machine and user name, so `private_files.rs` makes
the config dir and vault owner-only on POSIX. `settings.rs` returns defaults on
a malformed file rather than failing to start.

**Nightlies and updates.** `portkeydrop-core/build.rs` stamps
`PORTKEYDROP_NIGHTLY_DATE` into the binary because every nightly shares the
version of the release it followed; the updater compares dates. Update
downloads are checksum-verified and deleted on mismatch.

**Cross-file invariants pinned by tests.** Several things are linked only by a
test, so keep them in sync when renaming: the single-instance mutex name and
`AppMutex` in `installer/portkeydrop.iss` (`installer_mutex.rs`); release asset
names in `build.yml` and `select_asset` in the updater (`release_assets.rs`);
the vendored Prism library per platform (`vendored_libraries.rs`); and unique
Alt+letter mnemonics per dialog (`dialog_mnemonics.rs`).

## Branch Strategy

| Branch | Purpose |
|--------|---------|
| `main` | Stable releases |
| `dev` | Active development — PRs go here |
| `feature/*` | Feature work → PR to dev |
| `fix/*` | Bug fixes → PR to dev |

## Commit Format

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

- Accessibility: every interactive control needs an explicit accessible name
  via `set_name`, and list controls need a `StaticText` immediately before them
  (NVDA reads the preceding sibling as the list's name). Every menu action must
  also be reachable from a key, and Alt+letter mnemonics must be unique within
  a dialog.
- Release builds link as a Windows GUI subsystem; debug builds keep the
  console so panics are visible. `--debug` and `--log=<file>` exist for getting
  a log out of a user.
- On Windows the binary embeds an application manifest requesting Common
  Controls 6. Without it wxWidgets' `GetWindowSubclass` import cannot resolve
  and the process will not start.
- `.claude/worktrees/` is gitignored; a worktree was once committed as a bare
  gitlink and broke every CI job's cleanup step.
