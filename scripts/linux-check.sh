#!/usr/bin/env bash
# Run the Linux half of CI locally, through WSL.
#
# Windows compiles out every `cfg(unix)` block, so a clean `cargo clippy` there
# says nothing about the code inside those blocks. That is not theoretical: a
# `needless_return` in local_files.rs passed every local run and failed the
# Core (Ubuntu) job, and the missing ALSA and D-Bus development packages were
# found the same way. This runs what that job runs.
#
# Usage, from a Windows shell:
#   wsl -d Ubuntu -- bash scripts/linux-check.sh
# or from inside WSL:
#   bash scripts/linux-check.sh [repo-path]
#
# First-time setup inside WSL:
#   sudo apt-get install -y build-essential pkg-config \
#     libasound2-dev libdbus-1-dev libssl-dev
#   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
#
# rodio reaches ALSA for sound packs and the keyring crate reaches D-Bus for
# the Secret Service, so portkeydrop-core needs both even though it has no
# user interface.
set -uo pipefail

if [ -f "$HOME/.cargo/env" ]; then
	# shellcheck disable=SC1091
	source "$HOME/.cargo/env"
fi

cd "${1:-$(dirname "$0")/..}" || exit 1

# A target directory of its own, on the Linux filesystem. Sharing one with the
# Windows build makes each invalidate the other's artifacts, and writing it
# across the 9p mount is slow enough to notice.
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-$HOME/.cache/portkeydrop-linux-target}"

echo "repo:   $(pwd)"
echo "commit: $(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
echo "target: $CARGO_TARGET_DIR"
echo

echo "=== clippy (the Core job's command) ==="
RUSTFLAGS="-D warnings" cargo clippy \
	-p portkeydrop-core -p prism -p prism-sys --all-targets
clippy_status=$?

echo
echo "=== tests ==="
# Fewer tests run here than on Windows: the credential tests covering the
# Windows Credential Manager naming are cfg(windows).
cargo test -p portkeydrop-core -p prism -p prism-sys
test_status=$?

echo
if [ "$clippy_status" -eq 0 ] && [ "$test_status" -eq 0 ]; then
	echo "Linux checks passed."
else
	echo "Linux checks FAILED (clippy: $clippy_status, tests: $test_status)."
fi
exit $(( clippy_status | test_status ))
