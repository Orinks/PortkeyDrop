//! Persisting the transfer queue between sessions.
//!
//! Only unfinished work is written, and only paths and counters — never a
//! credential or a live connection. On restart the jobs come back as
//! [`Status::Restored`], waiting for the user to reconnect and retry.

use std::path::{Path, PathBuf};

use super::job::{Status, StoredJob, TransferJob};

/// File name of the queue document inside the config directory.
pub const QUEUE_FILE_NAME: &str = "queue.json";

/// Path of the queue document.
pub fn queue_path(config_dir: &Path) -> PathBuf {
    config_dir.join(QUEUE_FILE_NAME)
}

/// The jobs worth writing out.
///
/// An in-progress job is recorded as failed: the process is going away, so it
/// did not finish, and presenting it as still running on next launch would be
/// wrong.
pub fn persistable_jobs(jobs: &[TransferJob]) -> Vec<StoredJob> {
    jobs.iter()
        .filter_map(|job| match job.status {
            status if status.is_persistable() => Some(job.to_stored()),
            Status::InProgress => {
                let mut stored = job.to_stored();
                stored.status = Status::Failed;
                if stored.error.is_empty() {
                    stored.error = "interrupted when the app closed".to_string();
                }
                Some(stored)
            }
            _ => None,
        })
        .collect()
}

/// Write the queue.
///
/// Failures are logged rather than raised: losing the queue file is a nuisance,
/// but it must not stop the app from closing.
pub fn save_queue(jobs: &[TransferJob], config_dir: &Path) {
    let path = queue_path(config_dir);
    let stored = persistable_jobs(jobs);

    let result = (|| -> std::io::Result<()> {
        std::fs::create_dir_all(config_dir)?;
        let text = serde_json::to_string_pretty(&stored)
            .map_err(|err| std::io::Error::new(std::io::ErrorKind::InvalidData, err))?;
        std::fs::write(&path, text)
    })();

    if let Err(err) = result {
        log::error!(
            "could not save the transfer queue to {}: {err}",
            path.display()
        );
    }
}

/// Read the queue, returning nothing when it is absent or unreadable.
pub fn load_queue(config_dir: &Path) -> Vec<TransferJob> {
    let path = queue_path(config_dir);
    let Ok(text) = std::fs::read_to_string(&path) else {
        return Vec::new();
    };
    match serde_json::from_str::<Vec<StoredJob>>(&text) {
        Ok(stored) => stored.into_iter().map(TransferJob::from_stored).collect(),
        Err(err) => {
            log::error!(
                "could not read the transfer queue from {}: {err}",
                path.display()
            );
            Vec::new()
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::transfer::job::Direction;
    use tempfile::TempDir;

    fn job(status: Status) -> TransferJob {
        let mut job = TransferJob::new(Direction::Download, "/remote/a.txt", "/local/a.txt");
        job.status = status;
        job
    }

    #[test]
    fn unfinished_work_is_written_out() {
        let jobs = vec![
            job(Status::Pending),
            job(Status::Failed),
            job(Status::Restored),
        ];
        assert_eq!(persistable_jobs(&jobs).len(), 3);
    }

    #[test]
    fn finished_work_is_not_written_out() {
        let jobs = vec![job(Status::Complete), job(Status::Cancelled)];
        assert!(persistable_jobs(&jobs).is_empty());
    }

    #[test]
    fn an_interrupted_transfer_is_recorded_as_failed_with_a_reason() {
        // Coming back as "in progress" would show a running transfer that is
        // not running, and the user would have nothing to act on.
        let jobs = vec![job(Status::InProgress)];
        let stored = persistable_jobs(&jobs);
        assert_eq!(stored.len(), 1);
        assert_eq!(stored[0].status, Status::Failed);
        assert!(stored[0].error.contains("interrupted"));
    }

    #[test]
    fn an_interrupted_transfer_keeps_an_error_it_already_had() {
        let mut interrupted = job(Status::InProgress);
        interrupted.error = Some("connection reset".into());
        let stored = persistable_jobs(&[interrupted]);
        assert_eq!(stored[0].error, "connection reset");
    }

    #[test]
    fn the_queue_survives_a_round_trip() {
        let dir = TempDir::new().unwrap();
        let mut pending = job(Status::Pending);
        pending.total_bytes = 1000;
        pending.transferred_bytes = 250;
        pending.protocol = "sftp".into();

        save_queue(&[pending.clone(), job(Status::Complete)], dir.path());
        let restored = load_queue(dir.path());

        assert_eq!(restored.len(), 1);
        assert_eq!(restored[0].id, pending.id);
        assert_eq!(restored[0].source, "/remote/a.txt");
        assert_eq!(restored[0].total_bytes, 1000);
        assert_eq!(restored[0].transferred_bytes, 250);
        assert_eq!(restored[0].protocol, "sftp");
        assert_eq!(restored[0].status, Status::Restored);
    }

    #[test]
    fn the_queue_file_creates_its_directory() {
        let dir = TempDir::new().unwrap();
        let config = dir.path().join("nested").join("config");
        save_queue(&[job(Status::Pending)], &config);
        assert!(queue_path(&config).exists());
    }

    #[test]
    fn a_missing_queue_file_loads_as_empty() {
        let dir = TempDir::new().unwrap();
        assert!(load_queue(dir.path()).is_empty());
    }

    #[test]
    fn a_malformed_queue_file_loads_as_empty_rather_than_failing_startup() {
        let dir = TempDir::new().unwrap();
        std::fs::write(queue_path(dir.path()), "{not json").unwrap();
        assert!(load_queue(dir.path()).is_empty());
    }

    #[test]
    fn a_queue_file_holding_something_other_than_a_list_loads_as_empty() {
        let dir = TempDir::new().unwrap();
        std::fs::write(queue_path(dir.path()), r#"{"jobs": []}"#).unwrap();
        assert!(load_queue(dir.path()).is_empty());
    }

    #[test]
    fn the_queue_file_never_contains_credentials() {
        // The stored shape has no password field at all; this guards against
        // one being added by accident.
        let dir = TempDir::new().unwrap();
        save_queue(&[job(Status::Pending)], dir.path());
        let text = std::fs::read_to_string(queue_path(dir.path())).unwrap();
        assert!(!text.contains("password"));
        assert!(!text.contains("passphrase"));
    }

    #[test]
    fn saving_an_empty_queue_writes_an_empty_list() {
        let dir = TempDir::new().unwrap();
        save_queue(&[], dir.path());
        assert!(load_queue(dir.path()).is_empty());
        assert_eq!(
            std::fs::read_to_string(queue_path(dir.path()))
                .unwrap()
                .trim(),
            "[]"
        );
    }
}
