//! Deciding whether an interrupted download can be resumed.
//!
//! Resuming appends to a partial file. If the remote file changed since the
//! first attempt, that splices two different files together and produces a
//! corrupt result that looks complete. So the checks here are deliberately
//! conservative: anything unverifiable restarts from zero, because a slower
//! transfer is always better than a silently broken one.

/// What the local side of a stalled download looks like.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct LocalPartial {
    /// Bytes the job believes it already transferred.
    pub recorded_bytes: u64,
    /// Size of the partial file on disk, if it is still there.
    pub file_size: Option<u64>,
}

/// What the server says about the file now.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RemoteSnapshot {
    pub size: u64,
    /// Modification time as a Unix timestamp, when the server reports one.
    pub mtime: Option<i64>,
}

/// What the job recorded when the transfer first started.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct RecordedSnapshot {
    /// Total size at the time, or 0 if it was never established.
    pub total_bytes: u64,
    pub mtime: Option<i64>,
}

/// The outcome of a resume check.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ResumeDecision {
    /// Continue from this byte offset.
    Resume { offset: u64 },
    /// Start over, for the stated reason.
    Restart { reason: RestartReason },
}

/// Why a resume was refused.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RestartReason {
    /// Nothing had been transferred yet.
    NothingTransferred,
    /// The partial file is gone.
    PartialMissing,
    /// The partial file's size disagrees with the recorded count.
    SizeMismatch,
    /// The server's copy is a different size than when we started.
    RemoteSizeChanged,
    /// The server's copy has been modified since we started.
    RemoteModified,
    /// The server would not report the file's current state.
    RemoteUnavailable,
    /// The user turned resuming off.
    Disabled,
}

impl RestartReason {
    /// A line for the activity log.
    pub fn describe(self) -> &'static str {
        match self {
            RestartReason::NothingTransferred => "starting from the beginning",
            RestartReason::PartialMissing => {
                "the partial file is missing, so the transfer restarts"
            }
            RestartReason::SizeMismatch => {
                "the partial file does not match what was transferred, so the transfer restarts"
            }
            RestartReason::RemoteSizeChanged => {
                "the file changed size on the server, so the transfer restarts"
            }
            RestartReason::RemoteModified => {
                "the file was modified on the server, so the transfer restarts"
            }
            RestartReason::RemoteUnavailable => {
                "the server did not report the file's state, so the transfer restarts"
            }
            RestartReason::Disabled => "resuming is turned off, so the transfer restarts",
        }
    }
}

/// Decide whether to resume a download.
///
/// `remote` is `None` when the server could not be asked; that is treated as
/// unverifiable and restarts.
pub fn decide(
    resume_enabled: bool,
    local: LocalPartial,
    recorded: RecordedSnapshot,
    remote: Option<RemoteSnapshot>,
) -> ResumeDecision {
    let restart = |reason| ResumeDecision::Restart { reason };

    if !resume_enabled {
        return restart(RestartReason::Disabled);
    }
    if local.recorded_bytes == 0 {
        return restart(RestartReason::NothingTransferred);
    }

    let Some(file_size) = local.file_size else {
        return restart(RestartReason::PartialMissing);
    };
    if file_size != local.recorded_bytes {
        return restart(RestartReason::SizeMismatch);
    }

    let Some(remote) = remote else {
        return restart(RestartReason::RemoteUnavailable);
    };
    // A total of 0 means the size was never established, so there is nothing
    // to compare against and the size check is skipped rather than failed.
    if recorded.total_bytes > 0 && remote.size != recorded.total_bytes {
        return restart(RestartReason::RemoteSizeChanged);
    }
    // Only compare timestamps when both are known; a server that reports no
    // mtime cannot be used to prove the file is unchanged, but neither is it
    // evidence that it changed.
    if let (Some(recorded_mtime), Some(remote_mtime)) = (recorded.mtime, remote.mtime) {
        if recorded_mtime != remote_mtime {
            return restart(RestartReason::RemoteModified);
        }
    }
    // The partial cannot be longer than the file it came from.
    if local.recorded_bytes > remote.size {
        return restart(RestartReason::SizeMismatch);
    }

    ResumeDecision::Resume {
        offset: local.recorded_bytes,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn local(recorded: u64, on_disk: Option<u64>) -> LocalPartial {
        LocalPartial {
            recorded_bytes: recorded,
            file_size: on_disk,
        }
    }

    fn recorded(total: u64, mtime: Option<i64>) -> RecordedSnapshot {
        RecordedSnapshot {
            total_bytes: total,
            mtime,
        }
    }

    fn remote(size: u64, mtime: Option<i64>) -> Option<RemoteSnapshot> {
        Some(RemoteSnapshot { size, mtime })
    }

    fn restart_reason(decision: ResumeDecision) -> RestartReason {
        match decision {
            ResumeDecision::Restart { reason } => reason,
            ResumeDecision::Resume { offset } => {
                panic!("expected a restart, got a resume from {offset}")
            }
        }
    }

    #[test]
    fn a_matching_partial_resumes_from_where_it_stopped() {
        let decision = decide(
            true,
            local(400, Some(400)),
            recorded(1000, Some(100)),
            remote(1000, Some(100)),
        );
        assert_eq!(decision, ResumeDecision::Resume { offset: 400 });
    }

    #[test]
    fn resuming_turned_off_always_restarts() {
        let decision = decide(
            false,
            local(400, Some(400)),
            recorded(1000, Some(100)),
            remote(1000, Some(100)),
        );
        assert_eq!(restart_reason(decision), RestartReason::Disabled);
    }

    #[test]
    fn a_first_attempt_starts_from_the_beginning() {
        let decision = decide(
            true,
            local(0, None),
            RecordedSnapshot::default(),
            remote(1000, None),
        );
        assert_eq!(restart_reason(decision), RestartReason::NothingTransferred);
    }

    #[test]
    fn a_deleted_partial_file_restarts() {
        let decision = decide(
            true,
            local(400, None),
            recorded(1000, None),
            remote(1000, None),
        );
        assert_eq!(restart_reason(decision), RestartReason::PartialMissing);
    }

    #[test]
    fn a_partial_file_of_the_wrong_size_restarts() {
        // Appending from the recorded offset would leave a gap or a duplicate.
        let decision = decide(
            true,
            local(400, Some(250)),
            recorded(1000, None),
            remote(1000, None),
        );
        assert_eq!(restart_reason(decision), RestartReason::SizeMismatch);
    }

    #[test]
    fn a_remote_file_that_changed_size_restarts() {
        let decision = decide(
            true,
            local(400, Some(400)),
            recorded(1000, None),
            remote(2000, None),
        );
        assert_eq!(restart_reason(decision), RestartReason::RemoteSizeChanged);
    }

    #[test]
    fn a_remote_file_that_was_modified_restarts() {
        // Same size, different content: the case a size check alone misses.
        let decision = decide(
            true,
            local(400, Some(400)),
            recorded(1000, Some(100)),
            remote(1000, Some(200)),
        );
        assert_eq!(restart_reason(decision), RestartReason::RemoteModified);
    }

    #[test]
    fn an_unreachable_server_restarts_rather_than_guessing() {
        let decision = decide(true, local(400, Some(400)), recorded(1000, Some(100)), None);
        assert_eq!(restart_reason(decision), RestartReason::RemoteUnavailable);
    }

    #[test]
    fn a_partial_longer_than_the_remote_file_restarts() {
        let decision = decide(
            true,
            local(1500, Some(1500)),
            recorded(0, None),
            remote(1000, None),
        );
        assert_eq!(restart_reason(decision), RestartReason::SizeMismatch);
    }

    #[test]
    fn an_unknown_original_size_skips_the_size_comparison() {
        // Nothing to compare against is not the same as a mismatch.
        let decision = decide(
            true,
            local(400, Some(400)),
            recorded(0, Some(100)),
            remote(1000, Some(100)),
        );
        assert_eq!(decision, ResumeDecision::Resume { offset: 400 });
    }

    #[test]
    fn a_server_that_reports_no_timestamp_can_still_resume() {
        // Many FTP servers omit MDTM; refusing every resume there would make
        // the feature useless.
        let decision = decide(
            true,
            local(400, Some(400)),
            recorded(1000, Some(100)),
            remote(1000, None),
        );
        assert_eq!(decision, ResumeDecision::Resume { offset: 400 });
    }

    #[test]
    fn a_first_attempt_with_no_recorded_timestamp_can_still_resume() {
        let decision = decide(
            true,
            local(400, Some(400)),
            recorded(1000, None),
            remote(1000, Some(200)),
        );
        assert_eq!(decision, ResumeDecision::Resume { offset: 400 });
    }

    #[test]
    fn a_complete_partial_resumes_at_the_end_rather_than_restarting() {
        let decision = decide(
            true,
            local(1000, Some(1000)),
            recorded(1000, None),
            remote(1000, None),
        );
        assert_eq!(decision, ResumeDecision::Resume { offset: 1000 });
    }

    #[test]
    fn every_restart_reason_has_an_explanation() {
        for reason in [
            RestartReason::NothingTransferred,
            RestartReason::PartialMissing,
            RestartReason::SizeMismatch,
            RestartReason::RemoteSizeChanged,
            RestartReason::RemoteModified,
            RestartReason::RemoteUnavailable,
            RestartReason::Disabled,
        ] {
            assert!(!reason.describe().is_empty());
        }
    }
}
