//! The transfer job model and its on-disk form.
//!
//! Jobs outlive the queue window — closing that window must never cancel a
//! transfer — and pending or failed jobs outlive the process, so the model is
//! deliberately separate from any UI type.

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use serde::{Deserialize, Serialize};

/// Which way a transfer goes.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Direction {
    Upload,
    Download,
}

impl Direction {
    /// The verb used in announcements and queue rows.
    pub fn label(self) -> &'static str {
        match self {
            Direction::Upload => "Upload",
            Direction::Download => "Download",
        }
    }
}

/// Where a job is in its life.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Status {
    /// Queued, not yet started.
    Pending,
    InProgress,
    Complete,
    Failed,
    Cancelled,
    /// Restored from a previous session. Distinct from `Pending` because a
    /// restored job has no client attached and cannot start on its own.
    Restored,
}

impl Status {
    /// The text shown in the queue's Status column.
    pub fn label(self) -> &'static str {
        match self {
            Status::Pending => "pending",
            Status::InProgress => "in progress",
            Status::Complete => "complete",
            Status::Failed => "failed",
            Status::Cancelled => "cancelled",
            Status::Restored => "pending (restored)",
        }
    }

    /// Whether the job has stopped for good.
    pub fn is_finished(self) -> bool {
        matches!(self, Status::Complete | Status::Failed | Status::Cancelled)
    }

    /// Whether the job should be written to the queue file.
    ///
    /// Finished work is not worth restoring; a job still waiting is.
    pub fn is_persistable(self) -> bool {
        matches!(self, Status::Pending | Status::Failed | Status::Restored)
    }
}

/// A queued transfer.
#[derive(Debug, Clone)]
pub struct TransferJob {
    pub id: String,
    pub direction: Direction,
    /// Remote path for a download, local path for an upload.
    pub source: String,
    /// Local path for a download, remote path for an upload.
    pub destination: String,
    /// Protocol name, kept for the queue display after a disconnect.
    pub protocol: String,
    pub status: Status,
    pub error: Option<String>,
    /// 0–100.
    pub progress: u8,
    pub total_bytes: u64,
    pub transferred_bytes: u64,
    /// Whether an existing destination may be replaced.
    pub overwrite_existing: bool,
    /// Whether this job transfers a directory tree.
    pub recursive: bool,
    /// Remote modification time when the transfer began, as a Unix timestamp.
    ///
    /// A resume compares against this: if the remote file changed between
    /// attempts, continuing from an offset would splice two different files
    /// together.
    pub remote_mtime: Option<i64>,
    cancel: Arc<AtomicBool>,
}

impl TransferJob {
    /// A new job with a fresh id.
    pub fn new(
        direction: Direction,
        source: impl Into<String>,
        destination: impl Into<String>,
    ) -> Self {
        Self {
            id: uuid::Uuid::new_v4().simple().to_string(),
            direction,
            source: source.into(),
            destination: destination.into(),
            protocol: String::new(),
            status: Status::Pending,
            error: None,
            progress: 0,
            total_bytes: 0,
            transferred_bytes: 0,
            overwrite_existing: false,
            recursive: false,
            remote_mtime: None,
            cancel: Arc::new(AtomicBool::new(false)),
        }
    }

    /// Ask this job to stop at the next progress checkpoint.
    pub fn request_cancel(&self) {
        self.cancel.store(true, Ordering::SeqCst);
    }

    /// Whether cancellation has been requested.
    pub fn is_cancelled(&self) -> bool {
        self.cancel.load(Ordering::SeqCst)
    }

    /// Clear the cancel flag, for a retry.
    pub fn clear_cancel(&self) {
        self.cancel.store(false, Ordering::SeqCst);
    }

    /// A handle to this job's cancel flag, for the worker thread.
    pub fn cancel_flag(&self) -> Arc<AtomicBool> {
        Arc::clone(&self.cancel)
    }

    /// Recompute `progress` from the byte counts.
    pub fn update_progress(&mut self) {
        // A server that reports a smaller size than it sends must not produce
        // a progress figure above 100.
        self.progress = (self.transferred_bytes.min(self.total_bytes) * 100)
            .checked_div(self.total_bytes)
            .unwrap_or(0) as u8;
    }

    /// The file name shown in the queue.
    pub fn display_name(&self) -> String {
        let path = match self.direction {
            Direction::Download => &self.source,
            Direction::Upload => &self.destination,
        };
        let name = path.rsplit(['/', '\\']).next().unwrap_or(path);
        if name.is_empty() {
            path.clone()
        } else {
            name.to_string()
        }
    }

    /// The serialisable form of this job.
    pub fn to_stored(&self) -> StoredJob {
        StoredJob {
            id: self.id.clone(),
            direction: self.direction,
            source: self.source.clone(),
            destination: self.destination.clone(),
            protocol: self.protocol.clone(),
            total_bytes: self.total_bytes,
            transferred_bytes: self.transferred_bytes,
            overwrite_existing: self.overwrite_existing,
            recursive: self.recursive,
            status: self.status,
            error: self.error.clone().unwrap_or_default(),
        }
    }

    /// Rebuild a job from its stored form.
    ///
    /// Restored jobs always come back as [`Status::Restored`], never as
    /// in-progress: no transfer survives a restart, and showing one as running
    /// would be a lie.
    pub fn from_stored(stored: StoredJob) -> Self {
        let mut job = Self {
            id: if stored.id.is_empty() {
                uuid::Uuid::new_v4().simple().to_string()
            } else {
                stored.id
            },
            direction: stored.direction,
            source: stored.source,
            destination: stored.destination,
            protocol: stored.protocol,
            status: Status::Restored,
            error: Some(stored.error).filter(|error| !error.is_empty()),
            progress: 0,
            total_bytes: stored.total_bytes,
            transferred_bytes: stored.transferred_bytes,
            overwrite_existing: stored.overwrite_existing,
            recursive: stored.recursive,
            remote_mtime: None,
            cancel: Arc::new(AtomicBool::new(false)),
        };
        job.update_progress();
        job
    }
}

/// The on-disk form of a job.
///
/// Deliberately free of credentials and client handles: the queue file holds
/// paths and counters only.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct StoredJob {
    pub id: String,
    pub direction: Direction,
    pub source: String,
    pub destination: String,
    pub protocol: String,
    pub total_bytes: u64,
    pub transferred_bytes: u64,
    pub overwrite_existing: bool,
    pub recursive: bool,
    pub status: Status,
    pub error: String,
}

impl Default for StoredJob {
    fn default() -> Self {
        Self {
            id: String::new(),
            direction: Direction::Download,
            source: String::new(),
            destination: String::new(),
            protocol: String::new(),
            total_bytes: 0,
            transferred_bytes: 0,
            overwrite_existing: false,
            recursive: false,
            status: Status::Pending,
            error: String::new(),
        }
    }
}

/// A human-readable byte count.
pub fn format_bytes(bytes: u64) -> String {
    const UNITS: [&str; 5] = ["B", "KB", "MB", "GB", "TB"];
    if bytes < 1024 {
        return format!("{bytes} B");
    }
    let mut value = bytes as f64;
    for unit in UNITS.iter().skip(1) {
        value /= 1024.0;
        if value < 1024.0 {
            return format!("{value:.1} {unit}");
        }
    }
    format!("{value:.1} PB")
}

/// Byte-level progress text for queue rows and announcements.
pub fn format_transfer_detail(job: &TransferJob) -> String {
    let transferred = format_bytes(job.transferred_bytes);
    if job.total_bytes > 0 {
        format!("{transferred} of {}", format_bytes(job.total_bytes))
    } else {
        format!("{transferred} transferred")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn job() -> TransferJob {
        TransferJob::new(Direction::Download, "/remote/notes.txt", "/local/notes.txt")
    }

    #[test]
    fn new_jobs_get_distinct_identifiers() {
        assert_ne!(job().id, job().id);
        assert!(!job().id.is_empty());
    }

    #[test]
    fn a_new_job_is_pending_and_uncancelled() {
        let job = job();
        assert_eq!(job.status, Status::Pending);
        assert!(!job.is_cancelled());
        assert_eq!(job.progress, 0);
    }

    #[test]
    fn cancellation_is_visible_through_a_shared_flag() {
        // The worker thread watches the flag, not the job struct.
        let job = job();
        let flag = job.cancel_flag();
        assert!(!flag.load(Ordering::SeqCst));
        job.request_cancel();
        assert!(flag.load(Ordering::SeqCst));
        job.clear_cancel();
        assert!(!flag.load(Ordering::SeqCst));
    }

    #[test]
    fn progress_is_a_percentage_of_the_total() {
        let mut job = job();
        job.total_bytes = 200;
        job.transferred_bytes = 50;
        job.update_progress();
        assert_eq!(job.progress, 25);
    }

    #[test]
    fn progress_stays_at_zero_when_the_total_is_unknown() {
        let mut job = job();
        job.transferred_bytes = 500;
        job.update_progress();
        assert_eq!(job.progress, 0);
    }

    #[test]
    fn progress_never_exceeds_one_hundred() {
        // A server that reports a smaller size than it sends must not produce
        // a 250% progress bar.
        let mut job = job();
        job.total_bytes = 100;
        job.transferred_bytes = 250;
        job.update_progress();
        assert_eq!(job.progress, 100);
    }

    #[test]
    fn the_display_name_is_the_remote_file_for_a_download() {
        assert_eq!(job().display_name(), "notes.txt");
    }

    #[test]
    fn the_display_name_is_the_remote_destination_for_an_upload() {
        let job = TransferJob::new(
            Direction::Upload,
            r"C:\local\report.pdf",
            "/remote/report.pdf",
        );
        assert_eq!(job.display_name(), "report.pdf");
    }

    #[test]
    fn the_display_name_handles_windows_separators() {
        let job = TransferJob::new(Direction::Download, r"C:\a\b.txt", r"C:\a\b.txt");
        assert_eq!(job.display_name(), "b.txt");
    }

    #[test]
    fn finished_statuses_are_recognised() {
        assert!(Status::Complete.is_finished());
        assert!(Status::Failed.is_finished());
        assert!(Status::Cancelled.is_finished());
        assert!(!Status::Pending.is_finished());
        assert!(!Status::InProgress.is_finished());
        assert!(!Status::Restored.is_finished());
    }

    #[test]
    fn only_unfinished_work_is_worth_persisting() {
        assert!(Status::Pending.is_persistable());
        assert!(Status::Failed.is_persistable());
        assert!(Status::Restored.is_persistable());
        assert!(!Status::Complete.is_persistable());
        assert!(!Status::Cancelled.is_persistable());
        // An in-progress job cannot survive a restart, so it is not stored as
        // one; the queue writer converts it first.
        assert!(!Status::InProgress.is_persistable());
    }

    #[test]
    fn every_status_has_a_label() {
        for status in [
            Status::Pending,
            Status::InProgress,
            Status::Complete,
            Status::Failed,
            Status::Cancelled,
            Status::Restored,
        ] {
            assert!(!status.label().is_empty());
        }
        assert_eq!(Status::Restored.label(), "pending (restored)");
    }

    #[test]
    fn a_job_round_trips_through_its_stored_form() {
        let mut original = job();
        original.total_bytes = 1000;
        original.transferred_bytes = 400;
        original.overwrite_existing = true;
        original.recursive = true;
        original.protocol = "sftp".into();

        let restored = TransferJob::from_stored(original.to_stored());

        assert_eq!(restored.id, original.id);
        assert_eq!(restored.source, original.source);
        assert_eq!(restored.destination, original.destination);
        assert_eq!(restored.total_bytes, 1000);
        assert_eq!(restored.transferred_bytes, 400);
        assert!(restored.overwrite_existing);
        assert!(restored.recursive);
        assert_eq!(restored.protocol, "sftp");
    }

    #[test]
    fn a_restored_job_is_never_shown_as_running() {
        // No transfer survives a restart; showing one as in progress would be
        // a lie the user cannot act on.
        let mut original = job();
        original.status = Status::InProgress;
        let restored = TransferJob::from_stored(original.to_stored());
        assert_eq!(restored.status, Status::Restored);
    }

    #[test]
    fn a_restored_job_keeps_its_partial_progress() {
        let mut original = job();
        original.total_bytes = 1000;
        original.transferred_bytes = 250;
        let restored = TransferJob::from_stored(original.to_stored());
        assert_eq!(restored.progress, 25);
    }

    #[test]
    fn a_stored_job_without_an_id_gets_a_fresh_one() {
        let stored = StoredJob {
            source: "/a".into(),
            ..Default::default()
        };
        assert!(!TransferJob::from_stored(stored).id.is_empty());
    }

    #[test]
    fn a_stored_error_is_carried_back_and_an_empty_one_is_not() {
        let stored = StoredJob {
            error: "timed out".into(),
            ..Default::default()
        };
        assert_eq!(
            TransferJob::from_stored(stored).error.as_deref(),
            Some("timed out")
        );

        let stored = StoredJob::default();
        assert_eq!(TransferJob::from_stored(stored).error, None);
    }

    #[test]
    fn byte_counts_scale_through_the_units() {
        assert_eq!(format_bytes(0), "0 B");
        assert_eq!(format_bytes(512), "512 B");
        assert_eq!(format_bytes(1024), "1.0 KB");
        assert_eq!(format_bytes(1536), "1.5 KB");
        assert_eq!(format_bytes(1024 * 1024), "1.0 MB");
        assert_eq!(format_bytes(1024 * 1024 * 1024), "1.0 GB");
        assert_eq!(format_bytes(1024_u64.pow(4)), "1.0 TB");
    }

    #[test]
    fn transfer_detail_shows_a_total_when_one_is_known() {
        let mut job = job();
        job.transferred_bytes = 512;
        job.total_bytes = 2048;
        assert_eq!(format_transfer_detail(&job), "512 B of 2.0 KB");
    }

    #[test]
    fn transfer_detail_omits_an_unknown_total() {
        let mut job = job();
        job.transferred_bytes = 512;
        assert_eq!(format_transfer_detail(&job), "512 B transferred");
    }
}
