# Transfer hang audit

PR #151 retains its batch-submission fix and four contention regressions, and
adds the following changes from the earlier threading investigation.

| Cause | Fix |
| --- | --- |
| Worker waits for a session mutex after cancellation | Poll with cancellation checks, including after acquiring the guard; acquire before creating a download target. |
| Folder discovery and remote mkdir ignore cancellation | Check between directory operations and entries; preserve existing cycle and symlink handling. |
| Idle workers strongly own their service | Hold weak references while waiting and signal stopping when the service is dropped; never join network workers on the UI. |
| Progress notifications flood the UI | Coalesce transfer notifications and process at most 256 events per tick. Clear the pending flag before reading the UI snapshot to avoid lost wakeups. |
| Idle disconnect performs network shutdown on the UI | Defer both mutex acquisition and disconnect to a background thread. |
| FTPS data TLS starts before the transfer command | Connect passive TCP first, send MLSD/LIST, RETR/REST, or STOR, then negotiate TLS. Preserve certificate validation. |
| Failed data TLS leaves a pending transfer reply | Close and invalidate the session without waiting for QUIT, preventing subsequent jobs from reusing a desynchronised connection. |

All new regressions were run against the previous behavior and failed before
the corresponding fixes. The FTPS cleanup regression was also observed failing
with handshake ordering fixed but cleanup absent. Tests use controlled locks,
cancellation flags, and loopback servers, not live account credentials.

The `concurrent_ftp_transfers` integration tests run the real protocol factory,
FTP client, worker pool, recursive scanning, and local file writes against a
loopback FTP server. They stall the first folder's listing, verify that the
second can be queued or cancelled while the first owns the session, and compare
successful downloads byte-for-byte. They run headlessly on Linux and Windows.

Validation commands:

- `cargo fmt --all --check`
- `cargo test -p portkeydrop-core -p prism -p prism-sys --locked`
- `cargo clippy -p portkeydrop-core -p prism -p prism-sys --all-targets --locked`
- Windows CI: `cargo test --workspace` and workspace Clippy.

UI state and event modules were additionally compiled and tested in a temporary
headless harness against the real core and Prism crates. This does not replace
Windows application CI or manual screen-reader testing.

Limits: operations on one session still serialize. Cancellation takes effect
between synchronous network/filesystem operations or at a protocol progress
callback/timeout; it cannot forcibly terminate a blocked OS operation. FTP
socket and WebDAV request timeouts remain configured, and the locked SFTP
library has its own request timeout. Interactive host-key/agent approval is
unchanged. Running jobs keep the service alive until they return; idle jobs do
not. This audit is not proof of every possible thread interleaving.

Separate pre-existing follow-up areas include stale events from overlapping
reconnections, fairness between clients sharing a worker pool, and recursive
progress totals reaching 100% before the final file. These are not changed by
this PR.
