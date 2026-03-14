# Codebase Concerns

**Analysis Date:** 2026-03-14

## Tech Debt

**Broad Exception Handling in Protocols:**
- Issue: Multiple methods catch bare `Exception` without distinguishing error types, making debugging difficult
- Files: `src/portkeydrop/protocols.py` (lines 215, 218, 233, 241, 365, 789, 1151, 1156, 1283, 1373)
- Impact: Silent failures in SFTP operations, difficult to trace root causes of connection failures, error messages lose context
- Fix approach: Replace `except Exception` with specific exception types (e.g., `asyncssh.SFTPError`, `ConnectionError`, `OSError`), propagate context with `from e`

**Vault Decryption Failures Silently Reset State:**
- Issue: `_VaultStore._load()` catches `InvalidToken` and bare `Exception`, silently returns empty dict if decryption fails
- Files: `src/portkeydrop/sites.py` (line 83-85)
- Impact: User passwords lost if vault becomes corrupted or machine changes; no recovery mechanism or user warning
- Fix approach: Add explicit logging with urgency, consider backup/recovery mechanism, prompt user to restore from backup if vault corrupts

**Machine Key Derivation Uses Weak Seed Material:**
- Issue: Fernet encryption key derived from `platform.node() + username` — predictable cross-machine
- Files: `src/portkeydrop/sites.py` (lines 44-52)
- Impact: Passwords are not portable between machines or if username changes; vault.enc file becomes unreadable on environment change
- Current mitigation: Documented as "not meant to be unbreakable; just prevents casual reading"
- Fix approach: Acceptable for intended use, but document clearly in UI when moving to portable mode

**Subprocess Invocation in Update Service:**
- Issue: `subprocess.Popen()` calls in `apply_update()` don't wait for process completion or handle errors
- Files: `src/portkeydrop/services/updater.py` (lines 355, 359)
- Impact: Process may fail silently; `os._exit(0)` called unconditionally, terminating app without cleanup
- Fix approach: Capture exit status, log results, consider graceful restart mechanism instead of `os._exit(0)`

**Bare `pass` Statements in Exception Handlers:**
- Issue: Multiple symlink/stat operations catch exceptions and silently continue
- Files: `src/portkeydrop/protocols.py` (lines 219, 266, 366, 1152, 1157, 1214, 1284)
- Impact: Silent failures in directory detection, symlink resolution may fall back to incorrect state
- Fix approach: Replace with explicit error logging or re-raise, ensure fallback logic is intentional

## Known Bugs

**PPK Key Conversion Fragile to Malformed Data:**
- Symptoms: Complex parsing logic for PuTTY key files with multiple format variants (v2 RSA, v3 Ed25519); unencrypted only
- Files: `src/portkeydrop/protocols.py` (lines 520-847)
- Trigger: Loading PPK files with unexpected format or corruption
- Workaround: Convert to OpenSSH format using PuTTY first; native converter is fallback only
- Risk: If native converter fails, user must use external tool

**Transfer Job State Machine Has Race Conditions:**
- Symptoms: Job status transitions (PENDING → IN_PROGRESS → COMPLETE) protected by lock, but client field is internal and may be modified concurrently
- Files: `src/portkeydrop/services/transfer_service.py` (lines 278-305)
- Trigger: Rapid retry/cancel sequences during transfer
- Current mitigation: RLock used for critical sections; worker thread checks `cancel_event` in callback
- Potential issue: Progress callback raises `InterruptedError` if cancel event set, but exception handling may mask intent

**Update Check Can Hang on Network Timeout:**
- Symptoms: `UpdateService._json_get()` and `_download_file()` use `urlopen()` with timeout, but no connection pooling or retry
- Files: `src/portkeydrop/services/updater.py` (lines 388, 438, 475)
- Trigger: Slow/unreliable network, large update artifacts
- Workaround: Auto-update checks use 30s timeout; manual checks may block UI
- Fix approach: Implement connection pooling, exponential backoff for retries, non-blocking download

**Settings Exceptions Fallback Silently:**
- Symptoms: `_get_update_channel()` and `_start_auto_update_checks()` catch generic `Exception` and return defaults
- Files: `src/portkeydrop/app.py` (lines 1601-1604, 1634-1635)
- Trigger: Malformed settings file or missing attributes
- Impact: Settings changes may be silently ignored without user awareness
- Risk: User disables auto-updates but setting doesn't persist; user assumes it's off when it's still on

## Security Considerations

**FTPS Certificate Verification Uses Default Context:**
- Risk: `ssl.create_default_context()` in FTPSClient should verify certificates, but no explicit certificate pinning or custom validation
- Files: `src/portkeydrop/protocols.py` (lines 376-377)
- Current mitigation: Uses Python's standard certificate chain; modern systems have CA bundle
- Recommendations: Add option for custom CA certificates, certificate pinning for high-security deployments, log certificate verification failures

**SSH Host Key Policy Options May Be Too Permissive:**
- Risk: `AUTO_ADD` policy auto-accepts unknown host keys without user confirmation (default may be dangerous)
- Files: `src/portkeydrop/protocols.py` (lines 43-48), `src/portkeydrop/app.py` (host key dialog integration)
- Current mitigation: User can select PROMPT or STRICT at connection time
- Recommendations: Change default to STRICT, require explicit user action for first connection, log host key changes

**Passwords Logged in Plain Text During Error Messages:**
- Risk: Exception strings may contain passwords from `ConnectionInfo` if string representation includes it
- Files: `src/portkeydrop/app.py` (line 1334, 1379, 1394), `src/portkeydrop/protocols.py` (error strings)
- Current mitigation: Most exceptions don't include password field explicitly
- Recommendations: Ensure `ConnectionInfo.__repr__()` masks password, audit error messages for sensitive data, use structured logging

**Vault File Permissions Not Explicitly Set:**
- Risk: `vault.enc` created with default umask, may be readable by other processes on shared systems
- Files: `src/portkeydrop/sites.py` (line 88)
- Current mitigation: Fernet encryption provides confidentiality
- Recommendations: Set `chmod 0600` on vault.enc, add permission validation on load

**Update Artifacts Downloaded to World-Readable Temp Dir:**
- Risk: `tempfile.mkdtemp()` creates directory with default permissions, downloaded update visible to other users
- Files: `src/portkeydrop/services/updater.py` (line 460)
- Current mitigation: Checksum verification prevents tampering
- Recommendations: Create temp dir with restricted permissions (0o700), clean up on failure

## Performance Bottlenecks

**Recursive Directory Transfers Not Optimized for Large Trees:**
- Problem: Recursive download/upload traverses directory tree with nested SFTP calls, one level at a time
- Files: `src/portkeydrop/services/transfer_service.py` (lines 349-530)
- Cause: Each directory requires separate `list_dir` call; no batching or parallel walks
- Impact: Large folder hierarchies (100+ files) may take minutes
- Improvement path: Implement breadth-first traversal with connection pooling, consider parallel SFTP sessions

**SFTP List Directory Reads Entries in Small Chunks:**
- Problem: `_readdir_safe()` reads SFTP directory with configurable block reads, but default chunk size unknown
- Files: `src/portkeydrop/protocols.py` (lines 1181-1217)
- Cause: asyncssh SFTP handler may batch reads in 1KB blocks; no optimization for large directories
- Impact: 10,000+ file directories slow to populate
- Improvement path: Profile chunk sizes, consider `glob` patterns for filtering before read

**Transfer Progress Callbacks Run Synchronously in Worker Thread:**
- Problem: Progress callbacks (`_cb` in `_run_download`, `_run_upload`) lock and post events on every chunk
- Files: `src/portkeydrop/services/transfer_service.py` (lines 321-329, 337-345)
- Cause: High-frequency UI updates (one per 64KB chunk = 1000+ updates per GB)
- Impact: CPU spent on locking and event posting; UI may stutter on large files
- Improvement path: Batch progress updates (e.g., every 512KB or 100ms), use debouncing

**Activity Log Append Operations May Scale Poorly:**
- Problem: `ActivityLogPane` appends log entries one at a time; no batching
- Files: Related to transfer events in `src/portkeydrop/app.py`
- Cause: Each log event is a UI update; no buffer
- Impact: High-volume transfers generate hundreds of log lines; UI responsiveness degrades
- Improvement path: Buffer log entries, flush every 100ms or 50 lines

## Fragile Areas

**SFTP Directory Detection Complex and Fragile:**
- Files: `src/portkeydrop/protocols.py` (lines 1265-1290)
- Why fragile: Directory type detected via multiple fallbacks: permission bits, SFTP v4+ type field, symlink resolution, longname string parsing. Each can fail or conflict.
- Safe modification: Add comprehensive unit tests for edge cases (Bitvise, OpenSSH, Windows SSH), use feature-detection for server capabilities
- Test coverage: Limited test coverage for symlink and directory detection edge cases

**Host Key Verification Logic Splits Between Dialog and Connection:**
- Files: `src/portkeydrop/app.py` (site_manager dialog), `src/portkeydrop/protocols.py` (SFTPClient.connect)
- Why fragile: User selects policy in dialog, but actual verification happens in asyncssh layers; dialog doesn't reflect actual policy used
- Safe modification: Consolidate policy selection and application in one module, add logging for policy violations
- Risk: User's selected policy may not match what's actually enforced

**PPK to OpenSSH Conversion Serves as Critical Path:**
- Files: `src/portkeydrop/protocols.py` (lines 520-847)
- Why fragile: Inline native conversion for RSA/Ed25519 PPK files; if conversion fails, user must use external tool. No fallback to puttykeys library.
- Safe modification: Add optional fallback to puttykeys library if native conversion fails; improve error messages with recovery steps
- Test coverage: PPK conversion is tested but only for simple cases; needs more malformed input tests

**Transfer Queue Persistence Naive to Concurrent Writes:**
- Files: `src/portkeydrop/dialogs/transfer.py` (queue save/load), `src/portkeydrop/app.py`
- Why fragile: Queue saved/loaded as simple JSON without locking; if app crashes during save, file may be corrupted
- Safe modification: Use atomic writes (write to temp file, rename), add JSON validation on load, versioning for format changes
- Test coverage: No test for concurrent write scenarios or corruption recovery

## Scaling Limits

**Transfer Worker Pool Fixed Size:**
- Current capacity: User-configured up to N workers (default ~2-4); one transfer per worker
- Limit: System with many small files (1MB each) bottlenecked at worker thread count
- Scaling path: Implement async I/O within worker threads, use asyncio directly instead of threading

**Event Posting May Saturate UI Thread:**
- Current capacity: Progress callbacks post event on every chunk (potentially 1000+/GB)
- Limit: UI thread may not keep up; events queue and memory grows
- Scaling path: Implement debounced/throttled event posting, batch updates

**Vault Encryption Loads Entire File Into Memory:**
- Current capacity: `vault.enc` loaded entirely into memory as JSON
- Limit: If vault contains 1000+ connections, memory footprint grows
- Scaling path: Implement streaming decryption, lazy-load sections

## Dependencies at Risk

**asyncssh SSL/TLS Defaults:**
- Risk: asyncssh defaults to standard certificate validation; if Python CA bundle is outdated, some servers rejected
- Impact: Users on older systems may see spurious "certificate verify failed" errors
- Migration plan: Document minimum Python/certifi versions; allow custom CA bundles; provide diagnostic tool

**puttykeys Optional Dependency:**
- Risk: puttykeys library not installed by default; PPK import falls back to native converter which may fail
- Impact: Users with encrypted PPK files cannot import without external tool
- Migration plan: Add puttykeys to optional dependencies with clear error messages

**wxPython Version Compatibility:**
- Risk: wxPython 4.2+ API changes between versions; future versions may drop deprecated methods
- Impact: Accessibility features (aria labels, screen reader hooks) may break in newer wx
- Migration plan: Monitor wx releases, test on new versions before they become LTS

## Missing Critical Features

**No Connection Timeout Configuration:**
- Problem: SFTP connections hang indefinitely if server doesn't respond to protocol negotiation
- Blocks: Users on flaky networks cannot set connection timeout beyond read timeout
- Recommendation: Add configurable SSH handshake timeout in settings (20s-300s range)

**No Partial Transfer Resume for Uploads:**
- Problem: Download can resume from offset; upload always restarts from byte 0
- Blocks: Resuming large upload after interruption re-transfers entire file
- Recommendation: Implement upload resume via SFTP FSTAT and seek on remote file

**No Transfer Bandwidth Throttling:**
- Problem: Transfers use all available bandwidth; no QoS
- Blocks: Background transfers can saturate user's internet connection
- Recommendation: Add configurable rate limit setting (KB/s) in settings

**No Selective Sync Filters:**
- Problem: Recursive transfer includes all files; no way to exclude patterns
- Blocks: Syncing large folders with many temp/cache files wastes bandwidth
- Recommendation: Add .gitignore-style filter patterns for recursive operations

## Test Coverage Gaps

**SFTP Error Handling Not Fully Tested:**
- What's not tested: PermissionError, SFTPError codes (3=FX_PERMISSION_DENIED, 4=FX_FAILURE), timeout scenarios
- Files: `src/portkeydrop/protocols.py` (list_dir, stat, download, upload), `tests/test_host_key_verification.py`
- Risk: Connection errors may manifest differently across SSH servers (Bitvise vs OpenSSH); undetected edge cases
- Priority: High — affects reliability of file operations

**Host Key Verification Dialogs Not Tested:**
- What's not tested: PROMPT policy triggering dialog, user accepting/rejecting unknown keys, adding to known_hosts
- Files: `src/portkeydrop/app.py` (host key dialog), `src/portkeydrop/dialogs/host_key_dialog.py`
- Risk: User workflow may be broken (e.g., PROMPT policy not working); no safe re-test without mocking asyncssh
- Priority: High — critical user-facing feature

**Accessibility (Aria Labels) Not Systematically Tested:**
- What's not tested: Screen reader announcements for all dialogs, ListCtrl labels, focus management in tabs
- Files: `src/portkeydrop/dialogs/`, `src/portkeydrop/app.py`
- Risk: Regression in accessibility features (recent fixes in 0.2.0); new dialogs may lack labels
- Priority: Medium — important for accessibility promise but limited user base impact

**Password Vault Migration Not Tested:**
- What's not tested: Keyring to vault migration, vault corruption recovery, multi-user scenarios
- Files: `src/portkeydrop/sites.py` (migrate_keyring_passwords_to_vault), `tests/test_password_backend.py`
- Risk: User loses passwords if migration fails silently; no recovery path
- Priority: High — data loss scenario

**Recursive Transfer Edge Cases Not Covered:**
- What's not tested: Empty directories, symlink loops, permission denied mid-traverse, directories with 10000+ files
- Files: `src/portkeydrop/services/transfer_service.py` (recursive functions), `tests/test_queue_during_transfer.py`
- Risk: Transfers fail unexpectedly or hang on edge-case directory structures
- Priority: Medium — affects users with complex folder hierarchies

**Update Service Checksum Verification Not Tested:**
- What's not tested: Malformed checksum file, hash algorithm mismatch, missing checksum asset
- Files: `src/portkeydrop/services/updater.py` (verify_file_checksum, find_checksum_asset)
- Risk: Corrupted update files accepted if checksum file missing or malformed
- Priority: Medium — security-relevant feature

---

*Concerns audit: 2026-03-14*
