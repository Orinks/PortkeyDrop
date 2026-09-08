//! The transfer queue and its worker pool.
//!
//! The service owns every job. The queue window is a disposable observer over
//! that list, so closing it never cancels a transfer — which is the whole
//! reason the queue does not live in the dialog.
//!
//! Workers are plain OS threads. Each pulls a job, runs it against the client
//! the job carries, and reports progress through a callback the UI turns into
//! a repaint.

pub mod job;
pub mod queue_file;
pub mod resume;

use std::collections::HashSet;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{Receiver, RecvTimeoutError, Sender};
use std::sync::{Arc, Mutex};
use std::time::Duration;

pub use job::{format_bytes, format_transfer_detail, Direction, Status, StoredJob, TransferJob};
pub use queue_file::{load_queue, save_queue};
pub use resume::{RestartReason, ResumeDecision};

use crate::protocols::{path as remote_path, ProtocolError, TransferClient};

/// A client shared between the UI thread and a transfer worker.
pub type SharedClient = Arc<Mutex<Box<dyn TransferClient>>>;

/// Called whenever the job list changes, so the UI can refresh.
///
/// Runs on a worker thread; implementations must marshal to the UI thread
/// themselves.
pub type ChangeCallback = Arc<dyn Fn() + Send + Sync>;

/// How long a worker waits for a job before checking whether it should exit.
const WORKER_POLL: Duration = Duration::from_millis(100);

/// Work handed to a worker thread.
struct QueuedWork {
    job_id: String,
    client: SharedClient,
}

/// A running worker and its stop flag.
struct Worker {
    handle: std::thread::JoinHandle<()>,
    stop: Arc<AtomicBool>,
}

/// Owns the transfer queue and its workers.
pub struct TransferService {
    jobs: Arc<Mutex<Vec<TransferJob>>>,
    sender: Sender<QueuedWork>,
    receiver: Arc<Mutex<Receiver<QueuedWork>>>,
    workers: Mutex<Vec<Worker>>,
    on_change: Arc<Mutex<Option<ChangeCallback>>>,
    resume_enabled: Arc<AtomicBool>,
}

impl TransferService {
    /// Start a service with `worker_count` workers.
    pub fn new(worker_count: usize) -> Arc<Self> {
        let (sender, receiver) = std::sync::mpsc::channel();
        let service = Arc::new(Self {
            jobs: Arc::new(Mutex::new(Vec::new())),
            sender,
            receiver: Arc::new(Mutex::new(receiver)),
            workers: Mutex::new(Vec::new()),
            on_change: Arc::new(Mutex::new(None)),
            resume_enabled: Arc::new(AtomicBool::new(true)),
        });
        service.set_worker_count(worker_count);
        service
    }

    /// Register the callback fired when the job list changes.
    pub fn set_change_callback(&self, callback: Option<ChangeCallback>) {
        if let Ok(mut slot) = self.on_change.lock() {
            *slot = callback;
        }
    }

    /// Turn download resuming on or off.
    pub fn set_resume_enabled(&self, enabled: bool) {
        self.resume_enabled.store(enabled, Ordering::SeqCst);
    }

    /// A snapshot of every job, in queue order.
    pub fn jobs(&self) -> Vec<TransferJob> {
        self.jobs
            .lock()
            .map(|jobs| jobs.clone())
            .unwrap_or_default()
    }

    /// One job by id.
    pub fn job(&self, job_id: &str) -> Option<TransferJob> {
        self.jobs
            .lock()
            .ok()?
            .iter()
            .find(|job| job.id == job_id)
            .cloned()
    }

    /// How many jobs are queued or running.
    pub fn active_count(&self) -> usize {
        self.jobs
            .lock()
            .map(|jobs| jobs.iter().filter(|job| !job.status.is_finished()).count())
            .unwrap_or(0)
    }

    /// Resize the worker pool.
    ///
    /// Existing workers finish their current job before exiting, so a resize
    /// never interrupts a transfer in flight.
    pub fn set_worker_count(self: &Arc<Self>, count: usize) {
        let count = count.max(1);
        let mut workers = match self.workers.lock() {
            Ok(workers) => workers,
            Err(poisoned) => poisoned.into_inner(),
        };

        for worker in workers.drain(..) {
            worker.stop.store(true, Ordering::SeqCst);
            // Not joined: a worker mid-transfer would block the UI. It exits
            // on its own once the current job finishes.
            drop(worker.handle);
        }

        for _ in 0..count {
            let stop = Arc::new(AtomicBool::new(false));
            let service = Arc::clone(self);
            let worker_stop = Arc::clone(&stop);
            let handle = std::thread::Builder::new()
                .name("portkeydrop-transfer".to_string())
                .spawn(move || service.worker_loop(worker_stop))
                .expect("spawning a transfer worker");
            workers.push(Worker { handle, stop });
        }
    }

    /// Queue a download.
    pub fn submit_download(
        &self,
        client: SharedClient,
        remote_path: &str,
        local_path: &str,
        total_bytes: u64,
        recursive: bool,
        overwrite_existing: bool,
    ) -> String {
        let mut job = TransferJob::new(Direction::Download, remote_path, local_path);
        job.total_bytes = total_bytes;
        job.recursive = recursive;
        job.overwrite_existing = overwrite_existing;
        // Submission runs on the UI thread. An active transfer may hold the
        // client for a whole scan or file; let the worker fill this in later
        // rather than blocking the next item in a multi-selection.
        job.protocol = client
            .try_lock()
            .map(|client| client.protocol().as_str().to_string())
            .unwrap_or_default();
        self.enqueue(job, client)
    }

    /// Queue an upload.
    pub fn submit_upload(
        &self,
        client: SharedClient,
        local_path: &str,
        remote_path: &str,
        total_bytes: u64,
        recursive: bool,
        overwrite_existing: bool,
    ) -> String {
        let mut job = TransferJob::new(Direction::Upload, local_path, remote_path);
        job.total_bytes = total_bytes;
        job.recursive = recursive;
        job.overwrite_existing = overwrite_existing;
        // As with downloads, protocol metadata must not stall UI submission.
        job.protocol = client
            .try_lock()
            .map(|client| client.protocol().as_str().to_string())
            .unwrap_or_default();
        self.enqueue(job, client)
    }

    /// Add jobs restored from a previous session.
    ///
    /// They are listed but not started: a restored job has no connection, and
    /// starting one silently would reconnect without the user asking.
    pub fn restore_jobs(&self, jobs: Vec<TransferJob>) {
        if let Ok(mut list) = self.jobs.lock() {
            list.extend(jobs);
        }
        self.notify_change();
    }

    /// Cancel a job, whether queued or running.
    pub fn cancel(&self, job_id: &str) {
        if let Ok(mut jobs) = self.jobs.lock() {
            if let Some(job) = jobs.iter_mut().find(|job| job.id == job_id) {
                job.request_cancel();
                // A job that has not started yet will never reach a worker's
                // cancel check, so it is marked here.
                if matches!(job.status, Status::Pending | Status::Restored) {
                    job.status = Status::Cancelled;
                }
            }
        }
        self.notify_change();
    }

    /// Remove a finished job from the list.
    ///
    /// Returns whether anything was removed; a running job is left alone.
    pub fn remove_job(&self, job_id: &str) -> bool {
        let removed = match self.jobs.lock() {
            Ok(mut jobs) => {
                let before = jobs.len();
                jobs.retain(|job| !(job.id == job_id && job.status.is_finished()));
                jobs.len() != before
            }
            Err(_) => false,
        };
        if removed {
            self.notify_change();
        }
        removed
    }

    /// Re-queue a failed job against a fresh connection.
    ///
    /// The same job is reused — same id, same position — so the queue shows an
    /// update rather than a duplicate. Byte counts are kept so the retry can
    /// resume rather than start over.
    pub fn retry(&self, job_id: &str, client: SharedClient) -> bool {
        let ready = match self.jobs.lock() {
            Ok(mut jobs) => match jobs.iter_mut().find(|job| job.id == job_id) {
                Some(job) if job.status == Status::Failed || job.status == Status::Restored => {
                    job.status = Status::Pending;
                    job.error = None;
                    job.progress = 0;
                    job.clear_cancel();
                    true
                }
                _ => false,
            },
            Err(_) => false,
        };
        if !ready {
            return false;
        }
        let _ = self.sender.send(QueuedWork {
            job_id: job_id.to_string(),
            client,
        });
        self.notify_change();
        true
    }

    /// Retry every failed job against one connection.
    pub fn retry_all_failed(&self, client: SharedClient) -> usize {
        let failed: Vec<String> = self
            .jobs()
            .into_iter()
            .filter(|job| job.status == Status::Failed)
            .map(|job| job.id)
            .collect();
        failed
            .iter()
            .filter(|id| self.retry(id, Arc::clone(&client)))
            .count()
    }

    /// Persist the queue.
    pub fn save(&self, config_dir: &std::path::Path) {
        save_queue(&self.jobs(), config_dir);
    }

    // ---------------------------------------------------------------
    // Internals
    // ---------------------------------------------------------------

    fn enqueue(&self, job: TransferJob, client: SharedClient) -> String {
        let job_id = job.id.clone();
        if let Ok(mut jobs) = self.jobs.lock() {
            jobs.push(job);
        }
        let _ = self.sender.send(QueuedWork {
            job_id: job_id.clone(),
            client,
        });
        self.notify_change();
        job_id
    }

    fn notify_change(&self) {
        let callback = self.on_change.lock().ok().and_then(|slot| slot.clone());
        if let Some(callback) = callback {
            callback();
        }
    }

    /// Apply a mutation to one job and notify observers.
    fn with_job<R>(&self, job_id: &str, apply: impl FnOnce(&mut TransferJob) -> R) -> Option<R> {
        let result = {
            let mut jobs = self.jobs.lock().ok()?;
            let job = jobs.iter_mut().find(|job| job.id == job_id)?;
            apply(job)
        };
        self.notify_change();
        Some(result)
    }

    /// Read one field from a job without holding the lock afterwards.
    fn read_job<R>(&self, job_id: &str, read: impl FnOnce(&TransferJob) -> R) -> Option<R> {
        let jobs = self.jobs.lock().ok()?;
        jobs.iter().find(|job| job.id == job_id).map(read)
    }

    fn worker_loop(&self, stop: Arc<AtomicBool>) {
        loop {
            if stop.load(Ordering::SeqCst) {
                return;
            }
            let work = {
                let Ok(receiver) = self.receiver.lock() else {
                    return;
                };
                match receiver.recv_timeout(WORKER_POLL) {
                    Ok(work) => work,
                    Err(RecvTimeoutError::Timeout) => continue,
                    Err(RecvTimeoutError::Disconnected) => return,
                }
            };

            // A worker asked to stop puts the job back rather than dropping it.
            if stop.load(Ordering::SeqCst) {
                let _ = self.sender.send(work);
                return;
            }
            self.run_job(work);
        }
    }

    fn run_job(&self, work: QueuedWork) {
        let job_id = work.job_id;

        if self
            .read_job(&job_id, TransferJob::is_cancelled)
            .unwrap_or(true)
        {
            self.with_job(&job_id, |job| job.status = Status::Cancelled);
            return;
        }
        self.with_job(&job_id, |job| job.status = Status::InProgress);

        let outcome = self.execute(&job_id, &work.client);

        self.with_job(&job_id, |job| {
            match outcome {
                Ok(()) => {
                    // A cancel that landed while the last chunk was in flight
                    // still counts as a cancellation.
                    if job.is_cancelled() {
                        job.status = Status::Cancelled;
                    } else {
                        job.status = Status::Complete;
                        if job.total_bytes == 0 {
                            job.total_bytes = job.transferred_bytes;
                        }
                    }
                }
                Err(err) if err.is_cancelled() => job.status = Status::Cancelled,
                Err(err) => {
                    job.status = Status::Failed;
                    job.error = Some(err.to_string());
                }
            }
            job.update_progress();
        });
    }

    /// Run one job to completion.
    fn execute(&self, job_id: &str, client: &SharedClient) -> Result<(), ProtocolError> {
        // Only workers may wait for the connection. Release its guard before
        // updating the queue or notifying observers.
        let protocol = lock_client(client)?.protocol().as_str().to_string();
        self.with_job(job_id, |job| job.protocol = protocol);
        // Cancellation may have arrived while this worker waited for another
        // transfer to release the connection.
        if self
            .read_job(job_id, TransferJob::is_cancelled)
            .unwrap_or(true)
        {
            return Err(ProtocolError::Cancelled);
        }
        let Some((direction, recursive)) =
            self.read_job(job_id, |job| (job.direction, job.recursive))
        else {
            return Ok(());
        };

        match (direction, recursive) {
            (Direction::Download, false) => self.run_download(job_id, client),
            (Direction::Download, true) => self.run_recursive_download(job_id, client),
            (Direction::Upload, false) => self.run_upload(job_id, client),
            (Direction::Upload, true) => self.run_recursive_upload(job_id, client),
        }
    }

    /// A progress callback that records bytes and honours cancellation.
    fn progress_reporter<'a>(
        &'a self,
        job_id: &'a str,
        base_bytes: u64,
    ) -> impl FnMut(u64, u64) -> Result<(), ProtocolError> + 'a {
        move |transferred, total| {
            let cancelled = self
                .with_job(job_id, |job| {
                    job.transferred_bytes = base_bytes + transferred;
                    if total > 0 {
                        job.total_bytes = base_bytes + total;
                    }
                    job.update_progress();
                    job.is_cancelled()
                })
                .unwrap_or(true);
            if cancelled {
                return Err(ProtocolError::Cancelled);
            }
            Ok(())
        }
    }

    fn run_download(&self, job_id: &str, client: &SharedClient) -> Result<(), ProtocolError> {
        let Some((source, destination, recorded_bytes, total_bytes, recorded_mtime, overwrite)) =
            self.read_job(job_id, |job| {
                (
                    job.source.clone(),
                    job.destination.clone(),
                    job.transferred_bytes,
                    job.total_bytes,
                    job.remote_mtime,
                    job.overwrite_existing,
                )
            })
        else {
            return Ok(());
        };

        let remote = {
            let mut client = lock_client(client)?;
            client
                .stat(&source)
                .ok()
                .map(|file| resume::RemoteSnapshot {
                    size: file.size,
                    mtime: file.modified.map(|time| time.and_utc().timestamp()),
                })
        };

        let decision = resume::decide(
            self.resume_enabled.load(Ordering::SeqCst),
            resume::LocalPartial {
                recorded_bytes,
                file_size: std::fs::metadata(&destination).ok().map(|meta| meta.len()),
            },
            resume::RecordedSnapshot {
                total_bytes,
                mtime: recorded_mtime,
            },
            remote,
        );

        let offset = match decision {
            ResumeDecision::Resume { offset } => {
                log::info!("resuming {job_id} from byte {offset}");
                offset
            }
            ResumeDecision::Restart { reason } => {
                if recorded_bytes > 0 {
                    log::info!("{job_id}: {}", reason.describe());
                }
                self.with_job(job_id, |job| {
                    job.transferred_bytes = 0;
                    job.progress = 0;
                    // Record the server's state so the *next* attempt has
                    // something to compare against.
                    if let Some(remote) = remote {
                        job.remote_mtime = remote.mtime;
                        if job.total_bytes == 0 {
                            job.total_bytes = remote.size;
                        }
                    }
                });
                0
            }
        };

        let mut file = open_download_target(&destination, offset, overwrite, recorded_bytes > 0)?;
        let mut report = self.progress_reporter(job_id, offset);
        let mut client = lock_client(client)?;
        client.download(&source, &mut file, Some(&mut report), offset)
    }

    fn run_upload(&self, job_id: &str, client: &SharedClient) -> Result<(), ProtocolError> {
        let Some((source, destination)) =
            self.read_job(job_id, |job| (job.source.clone(), job.destination.clone()))
        else {
            return Ok(());
        };

        let mut file = std::fs::File::open(&source)?;
        let total = file.metadata().map(|meta| meta.len()).unwrap_or(0);
        self.with_job(job_id, |job| {
            job.total_bytes = total;
            job.transferred_bytes = 0;
        });

        let mut report = self.progress_reporter(job_id, 0);
        let mut client = lock_client(client)?;
        client.upload(&mut file, total, &destination, Some(&mut report))
    }

    fn run_recursive_download(
        &self,
        job_id: &str,
        client: &SharedClient,
    ) -> Result<(), ProtocolError> {
        let Some((source, destination, overwrite)) = self.read_job(job_id, |job| {
            (
                job.source.clone(),
                job.destination.clone(),
                job.overwrite_existing,
            )
        }) else {
            return Ok(());
        };

        let files = {
            let mut client = lock_client(client)?;
            collect_remote_files(&mut **client, &source, std::path::Path::new(&destination))?
        };
        let total: u64 = files.iter().map(|entry| entry.size).sum();
        self.with_job(job_id, |job| {
            job.total_bytes = total;
            job.transferred_bytes = 0;
            job.update_progress();
        });

        let mut base = 0u64;
        for entry in files {
            if self
                .read_job(job_id, TransferJob::is_cancelled)
                .unwrap_or(true)
            {
                return Err(ProtocolError::Cancelled);
            }
            if let Some(parent) = entry.local_path.parent() {
                std::fs::create_dir_all(parent)?;
            }
            let mut file =
                open_download_target(&entry.local_path.to_string_lossy(), 0, overwrite, false)?;
            let mut report = self.progress_reporter(job_id, base);
            {
                let mut client = lock_client(client)?;
                client.download(&entry.remote_path, &mut file, Some(&mut report), 0)?;
            }
            base = self
                .read_job(job_id, |job| job.transferred_bytes)
                .unwrap_or(base);
        }
        Ok(())
    }

    fn run_recursive_upload(
        &self,
        job_id: &str,
        client: &SharedClient,
    ) -> Result<(), ProtocolError> {
        let Some((source, destination)) =
            self.read_job(job_id, |job| (job.source.clone(), job.destination.clone()))
        else {
            return Ok(());
        };

        let files = collect_local_files(std::path::Path::new(&source), &destination)?;
        let total: u64 = files.iter().map(|entry| entry.size).sum();
        self.with_job(job_id, |job| {
            job.total_bytes = total;
            job.transferred_bytes = 0;
            job.update_progress();
        });

        // Create the destination tree first, deepest last, so every parent
        // exists before its children.
        {
            let mut client = lock_client(client)?;
            for directory in remote_directories(&destination, &files) {
                // An existing directory is the expected case for every level
                // above the one actually missing.
                let _ = client.mkdir(&directory);
            }
        }

        let mut base = 0u64;
        for entry in files {
            if self
                .read_job(job_id, TransferJob::is_cancelled)
                .unwrap_or(true)
            {
                return Err(ProtocolError::Cancelled);
            }
            let mut file = std::fs::File::open(&entry.local_path)?;
            let mut report = self.progress_reporter(job_id, base);
            {
                let mut client = lock_client(client)?;
                client.upload(&mut file, entry.size, &entry.remote_path, Some(&mut report))?;
            }
            base = self
                .read_job(job_id, |job| job.transferred_bytes)
                .unwrap_or(base);
        }
        Ok(())
    }
}

/// Lock a shared client, reporting a poisoned lock as a lost connection.
fn lock_client(
    client: &SharedClient,
) -> Result<std::sync::MutexGuard<'_, Box<dyn TransferClient>>, ProtocolError> {
    client.lock().map_err(|_| {
        ProtocolError::Connection(
            "the connection was left in an unusable state by an earlier error".to_string(),
        )
    })
}

/// Open the local file a download writes into.
///
/// Refuses to clobber an existing file unless overwriting was requested; a
/// resumed or restarted transfer is allowed to reuse its own partial file.
fn open_download_target(
    destination: &str,
    offset: u64,
    overwrite: bool,
    had_partial: bool,
) -> Result<std::fs::File, ProtocolError> {
    use std::io::{Seek, SeekFrom};

    let path = std::path::Path::new(destination);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }

    if offset > 0 {
        let mut file = std::fs::OpenOptions::new().write(true).open(path)?;
        file.seek(SeekFrom::Start(offset))?;
        return Ok(file);
    }

    if overwrite || had_partial {
        return Ok(std::fs::File::create(path)?);
    }

    std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|err| {
            if err.kind() == std::io::ErrorKind::AlreadyExists {
                ProtocolError::AlreadyExists(destination.to_string())
            } else {
                ProtocolError::Io(err)
            }
        })
}

/// One file in a recursive transfer.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TransferEntry {
    pub remote_path: String,
    pub local_path: std::path::PathBuf,
    pub size: u64,
}

/// Walk a remote directory tree, listing every file to transfer.
///
/// Directory identity is the canonical path, so a listing that names itself as
/// a child — FTP `cdir` with a real path, a WebDAV self-href, an SFTP symlink
/// back to a parent — is skipped instead of being listed until the process
/// runs out of memory. The walk is iterative; a deep tree does not grow the
/// call stack.
pub fn collect_remote_files(
    client: &mut dyn TransferClient,
    remote_dir: &str,
    local_dir: &std::path::Path,
) -> Result<Vec<TransferEntry>, ProtocolError> {
    let mut entries = Vec::new();
    let mut stack = vec![(remote_dir.to_string(), local_dir.to_path_buf())];
    let mut visited = HashSet::new();

    while let Some((remote, local)) = stack.pop() {
        let key = directory_identity(client, &remote);
        if !visited.insert(key.clone()) {
            continue;
        }
        for file in client.list_dir(&remote)? {
            if file.name.is_empty() || file.name == "." || file.name == ".." {
                continue;
            }
            if file.is_dir {
                let child_key = directory_identity(client, &file.path);
                if child_key == key || visited.contains(&child_key) {
                    continue;
                }
                stack.push((file.path.clone(), local.join(&file.name)));
            } else {
                entries.push(TransferEntry {
                    remote_path: file.path.clone(),
                    local_path: local.join(&file.name),
                    size: file.size,
                });
            }
        }
    }
    entries.sort_by(|a, b| a.remote_path.cmp(&b.remote_path));
    Ok(entries)
}

/// Identity used to recognise a remote directory already seen in this walk.
fn directory_identity(client: &mut dyn TransferClient, remote: &str) -> String {
    match client.canonicalize(remote) {
        Ok(canonical) => remote_path::normalize(&canonical),
        Err(_) => remote_path::normalize(remote),
    }
}

/// Walk a local directory tree, listing every file to transfer.
pub fn collect_local_files(
    local_dir: &std::path::Path,
    remote_dir: &str,
) -> Result<Vec<TransferEntry>, ProtocolError> {
    let mut entries = Vec::new();
    let mut stack = vec![(local_dir.to_path_buf(), remote_path::normalize(remote_dir))];

    while let Some((local, remote)) = stack.pop() {
        for entry in std::fs::read_dir(&local)? {
            let entry = entry?;
            let name = entry.file_name().to_string_lossy().into_owned();
            let remote_child = remote_path::join(&remote, &name);
            let file_type = entry.file_type()?;

            if file_type.is_dir() {
                stack.push((entry.path(), remote_child));
            } else if file_type.is_file() {
                entries.push(TransferEntry {
                    remote_path: remote_child,
                    local_path: entry.path(),
                    size: entry.metadata().map(|meta| meta.len()).unwrap_or(0),
                });
            }
            // Symlinks are skipped: following one could walk out of the tree
            // the user selected, or loop forever.
        }
    }
    entries.sort_by(|a, b| a.local_path.cmp(&b.local_path));
    Ok(entries)
}

/// Every remote directory needed for a set of uploads, parents first.
pub fn remote_directories(root: &str, entries: &[TransferEntry]) -> Vec<String> {
    let root = remote_path::normalize(root);
    let mut directories: Vec<String> = vec![root.clone()];

    for entry in entries {
        let mut parent = remote_path::parent(&entry.remote_path);
        while parent.len() > root.len() && parent.starts_with(&root) {
            if !directories.contains(&parent) {
                directories.push(parent.clone());
            }
            parent = remote_path::parent(&parent);
        }
    }
    // Shortest first, so a parent is always created before its children.
    directories.sort_by_key(|directory| (directory.matches('/').count(), directory.clone()));
    directories
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn a_new_service_has_no_jobs() {
        let service = TransferService::new(2);
        assert!(service.jobs().is_empty());
        assert_eq!(service.active_count(), 0);
    }

    #[test]
    fn restored_jobs_appear_without_starting() {
        let service = TransferService::new(1);
        let mut job = TransferJob::new(Direction::Download, "/a", "/b");
        job.status = Status::Restored;
        service.restore_jobs(vec![job.clone()]);

        let jobs = service.jobs();
        assert_eq!(jobs.len(), 1);
        assert_eq!(jobs[0].status, Status::Restored);
        assert_eq!(service.job(&job.id).unwrap().id, job.id);
    }

    #[test]
    fn cancelling_a_queued_job_marks_it_cancelled_immediately() {
        // It will never reach a worker's cancel check, so the state has to be
        // set here or the job would sit as "pending" forever.
        let service = TransferService::new(1);
        let mut job = TransferJob::new(Direction::Download, "/a", "/b");
        job.status = Status::Restored;
        let id = job.id.clone();
        service.restore_jobs(vec![job]);

        service.cancel(&id);
        assert_eq!(service.job(&id).unwrap().status, Status::Cancelled);
    }

    #[test]
    fn finished_jobs_can_be_removed_and_running_ones_cannot() {
        let service = TransferService::new(1);
        let mut finished = TransferJob::new(Direction::Download, "/a", "/b");
        finished.status = Status::Complete;
        let mut running = TransferJob::new(Direction::Download, "/c", "/d");
        running.status = Status::InProgress;
        let (finished_id, running_id) = (finished.id.clone(), running.id.clone());
        service.restore_jobs(vec![finished, running]);

        assert!(service.remove_job(&finished_id));
        assert!(!service.remove_job(&running_id));
        assert!(!service.remove_job("no-such-job"));
        assert_eq!(service.jobs().len(), 1);
    }

    #[test]
    fn the_active_count_ignores_finished_work() {
        let service = TransferService::new(1);
        let mut complete = TransferJob::new(Direction::Download, "/a", "/b");
        complete.status = Status::Complete;
        let mut pending = TransferJob::new(Direction::Download, "/c", "/d");
        pending.status = Status::Pending;
        service.restore_jobs(vec![complete, pending]);

        assert_eq!(service.active_count(), 1);
    }

    #[test]
    fn the_change_callback_fires_when_the_list_changes() {
        let service = TransferService::new(1);
        let calls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
        let counter = Arc::clone(&calls);
        service.set_change_callback(Some(Arc::new(move || {
            counter.fetch_add(1, Ordering::SeqCst);
        })));

        service.restore_jobs(vec![TransferJob::new(Direction::Download, "/a", "/b")]);
        assert!(calls.load(Ordering::SeqCst) >= 1);
    }

    #[test]
    fn a_download_target_refuses_to_clobber_an_existing_file() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("notes.txt");
        std::fs::write(&path, b"existing").unwrap();

        let error = open_download_target(&path.to_string_lossy(), 0, false, false).unwrap_err();
        assert!(matches!(error, ProtocolError::AlreadyExists(_)));
        // The existing file is untouched.
        assert_eq!(std::fs::read_to_string(&path).unwrap(), "existing");
    }

    #[test]
    fn a_download_target_may_be_overwritten_when_asked() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("notes.txt");
        std::fs::write(&path, b"existing").unwrap();

        open_download_target(&path.to_string_lossy(), 0, true, false).unwrap();
        assert_eq!(std::fs::read_to_string(&path).unwrap(), "");
    }

    #[test]
    fn a_restarted_transfer_may_reuse_its_own_partial_file() {
        // Without this a restart after a failure would report "already exists"
        // against the partial file it wrote itself.
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("notes.txt");
        std::fs::write(&path, b"partial").unwrap();

        assert!(open_download_target(&path.to_string_lossy(), 0, false, true).is_ok());
    }

    #[test]
    fn a_resumed_transfer_opens_at_its_offset_without_truncating() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("notes.txt");
        std::fs::write(&path, b"0123456789").unwrap();

        {
            use std::io::Write;
            let mut file = open_download_target(&path.to_string_lossy(), 5, false, true).unwrap();
            file.write_all(b"ABCDE").unwrap();
        }
        assert_eq!(std::fs::read_to_string(&path).unwrap(), "01234ABCDE");
    }

    #[test]
    fn a_download_target_creates_missing_parent_directories() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("a").join("b").join("notes.txt");
        assert!(open_download_target(&path.to_string_lossy(), 0, false, false).is_ok());
        assert!(path.exists());
    }

    #[test]
    fn a_local_tree_is_walked_into_matching_remote_paths() {
        let dir = TempDir::new().unwrap();
        std::fs::write(dir.path().join("a.txt"), b"12345").unwrap();
        std::fs::create_dir(dir.path().join("sub")).unwrap();
        std::fs::write(dir.path().join("sub").join("b.txt"), b"678").unwrap();

        let entries = collect_local_files(dir.path(), "/remote/dest").unwrap();

        assert_eq!(entries.len(), 2);
        let remote: Vec<&str> = entries
            .iter()
            .map(|entry| entry.remote_path.as_str())
            .collect();
        assert!(remote.contains(&"/remote/dest/a.txt"));
        assert!(remote.contains(&"/remote/dest/sub/b.txt"));
        assert_eq!(entries.iter().map(|entry| entry.size).sum::<u64>(), 8);
    }

    #[test]
    fn walking_an_empty_local_tree_yields_nothing() {
        let dir = TempDir::new().unwrap();
        assert!(collect_local_files(dir.path(), "/remote")
            .unwrap()
            .is_empty());
    }

    #[test]
    fn walking_a_missing_local_directory_is_an_error() {
        let dir = TempDir::new().unwrap();
        assert!(collect_local_files(&dir.path().join("nope"), "/remote").is_err());
    }

    #[test]
    fn upload_directories_are_listed_parents_first() {
        // Creating a child before its parent fails on every protocol.
        let entries = vec![
            TransferEntry {
                remote_path: "/dest/a/b/deep.txt".into(),
                local_path: "x".into(),
                size: 1,
            },
            TransferEntry {
                remote_path: "/dest/top.txt".into(),
                local_path: "y".into(),
                size: 1,
            },
        ];
        let directories = remote_directories("/dest", &entries);
        assert_eq!(directories, vec!["/dest", "/dest/a", "/dest/a/b"]);
    }

    #[test]
    fn upload_directories_include_the_destination_itself() {
        assert_eq!(remote_directories("/dest", &[]), vec!["/dest"]);
    }

    #[test]
    fn upload_directories_are_not_duplicated() {
        let entries = vec![
            TransferEntry {
                remote_path: "/d/a/1.txt".into(),
                local_path: "x".into(),
                size: 1,
            },
            TransferEntry {
                remote_path: "/d/a/2.txt".into(),
                local_path: "y".into(),
                size: 1,
            },
        ];
        assert_eq!(remote_directories("/d", &entries), vec!["/d", "/d/a"]);
    }

    // No background workers: tests explicitly run queued work after releasing
    // the connection, so contention and cleanup do not depend on scheduling.
    fn manual_service() -> Arc<TransferService> {
        let (sender, receiver) = std::sync::mpsc::channel();
        Arc::new(TransferService {
            jobs: Arc::new(Mutex::new(Vec::new())),
            sender,
            receiver: Arc::new(Mutex::new(receiver)),
            workers: Mutex::new(Vec::new()),
            on_change: Arc::new(Mutex::new(None)),
            resume_enabled: Arc::new(AtomicBool::new(true)),
        })
    }

    fn assert_busy_batch_queues(direction: Direction, recursive: [bool; 2]) {
        let service = manual_service();
        let mut remote = FakeRemote::with_budget(2);
        remote.add_dir("/first", Vec::new());
        remote.add_dir("/second", Vec::new());
        let client: SharedClient = Arc::new(Mutex::new(Box::new(remote)));
        let directory = tempfile::tempdir().unwrap();
        let paths = [
            directory.path().join("first"),
            directory.path().join("second"),
        ];
        if direction == Direction::Upload {
            for (path, is_dir) in paths.iter().zip(recursive) {
                if is_dir {
                    std::fs::create_dir(path).unwrap();
                } else {
                    std::fs::write(path, b"upload").unwrap();
                }
            }
        }
        let busy = client.lock().unwrap();
        let queued_service = Arc::clone(&service);
        let queued_client = Arc::clone(&client);
        let (sent, received) = std::sync::mpsc::channel();
        let submitter = std::thread::spawn(move || {
            let mut ids = Vec::new();
            for (index, remote_path) in ["/first", "/second"].iter().enumerate() {
                let local_path = paths[index].to_string_lossy();
                ids.push(match direction {
                    Direction::Download => queued_service.submit_download(
                        Arc::clone(&queued_client),
                        remote_path,
                        &local_path,
                        0,
                        recursive[index],
                        false,
                    ),
                    Direction::Upload => queued_service.submit_upload(
                        Arc::clone(&queued_client),
                        &local_path,
                        remote_path,
                        0,
                        recursive[index],
                        false,
                    ),
                });
            }
            sent.send(ids).unwrap();
        });
        let queued = received.recv_timeout(Duration::from_secs(2));
        // Release before asserting or joining, so the broken implementation
        // fails with a bounded timeout instead of leaving a hung test process.
        drop(busy);
        submitter.join().unwrap();
        let ids = queued.expect("batch submission waited for the busy connection");
        assert_eq!(service.active_count(), 2);
        for id in ids {
            let work = service.receiver.lock().unwrap().try_recv().unwrap();
            assert_eq!(work.job_id, id);
            service.run_job(work);
            let job = service.job(&id).unwrap();
            assert_eq!(job.status, Status::Complete, "{:?}", job.error);
            assert_eq!(job.protocol, "sftp");
        }
    }

    #[test]
    fn busy_connection_does_not_block_multiple_file_downloads() {
        assert_busy_batch_queues(Direction::Download, [false, false]);
    }

    #[test]
    fn busy_connection_does_not_block_multiple_folder_downloads() {
        assert_busy_batch_queues(Direction::Download, [true, true]);
    }

    #[test]
    fn busy_connection_does_not_block_mixed_downloads() {
        assert_busy_batch_queues(Direction::Download, [false, true]);
    }

    #[test]
    fn busy_connection_does_not_block_mixed_uploads() {
        assert_busy_batch_queues(Direction::Upload, [false, true]);
    }

    /// A connected client that serves scripted directory listings.
    ///
    /// `list_budget` is the crash detector: without a visited set, a cyclic
    /// listing would keep calling `list_dir` until the process ran out of
    /// memory. Hitting the budget fails the test instead of hanging.
    struct FakeRemote {
        listings: std::collections::HashMap<String, Vec<crate::protocols::RemoteFile>>,
        aliases: Vec<(String, String)>,
        lists: usize,
        list_budget: usize,
    }

    impl FakeRemote {
        fn with_budget(list_budget: usize) -> Self {
            Self {
                listings: std::collections::HashMap::new(),
                aliases: Vec::new(),
                lists: 0,
                list_budget,
            }
        }

        fn add_dir(&mut self, path: &str, children: Vec<crate::protocols::RemoteFile>) {
            self.listings.insert(remote_path::normalize(path), children);
        }
    }

    impl TransferClient for FakeRemote {
        fn protocol(&self) -> crate::protocols::Protocol {
            crate::protocols::Protocol::Sftp
        }

        fn is_connected(&self) -> bool {
            true
        }

        fn cwd(&self) -> &str {
            "/"
        }

        fn connect(&mut self) -> Result<(), ProtocolError> {
            Ok(())
        }

        fn disconnect(&mut self) {}

        fn list_dir(
            &mut self,
            path: &str,
        ) -> Result<Vec<crate::protocols::RemoteFile>, ProtocolError> {
            self.lists += 1;
            assert!(
                self.lists <= self.list_budget,
                "collect_remote_files listed {path} unbounded ({} listings)",
                self.lists
            );
            let key = directory_identity(self, path);
            self.listings
                .get(&key)
                .cloned()
                .ok_or_else(|| ProtocolError::NotFound(path.to_string()))
        }

        fn chdir(&mut self, path: &str) -> Result<String, ProtocolError> {
            Ok(path.to_string())
        }

        fn download(
            &mut self,
            _remote_path: &str,
            _sink: &mut dyn std::io::Write,
            _progress: Option<crate::protocols::ProgressFn<'_>>,
            _offset: u64,
        ) -> Result<(), ProtocolError> {
            Ok(())
        }

        fn upload(
            &mut self,
            _source: &mut dyn std::io::Read,
            _total_bytes: u64,
            _remote_path: &str,
            _progress: Option<crate::protocols::ProgressFn<'_>>,
        ) -> Result<(), ProtocolError> {
            Ok(())
        }

        fn delete(&mut self, _path: &str) -> Result<(), ProtocolError> {
            Ok(())
        }

        fn rmdir(&mut self, _path: &str) -> Result<(), ProtocolError> {
            Ok(())
        }

        fn mkdir(&mut self, _path: &str) -> Result<(), ProtocolError> {
            Ok(())
        }

        fn rename(&mut self, _old_path: &str, _new_path: &str) -> Result<(), ProtocolError> {
            Ok(())
        }

        fn stat(&mut self, path: &str) -> Result<crate::protocols::RemoteFile, ProtocolError> {
            Err(ProtocolError::NotFound(path.to_string()))
        }

        fn canonicalize(&mut self, path: &str) -> Result<String, ProtocolError> {
            let mut current = remote_path::normalize(path);
            for _ in 0..64 {
                let mut changed = false;
                for (from, to) in &self.aliases {
                    if current == *from {
                        current = to.clone();
                        changed = true;
                        break;
                    }
                    let prefix = format!("{from}/");
                    if let Some(rest) = current.strip_prefix(&prefix) {
                        current = format!("{to}/{rest}");
                        changed = true;
                        break;
                    }
                }
                if !changed {
                    return Ok(current);
                }
            }
            Ok(current)
        }
    }

    #[test]
    fn a_remote_tree_is_walked_into_matching_local_paths() {
        let mut client = FakeRemote::with_budget(8);
        client.add_dir(
            "/photos",
            vec![
                crate::protocols::RemoteFile::file("a.jpg", "/photos/a.jpg", 10),
                crate::protocols::RemoteFile::dir("album", "/photos/album"),
            ],
        );
        client.add_dir(
            "/photos/album",
            vec![crate::protocols::RemoteFile::file(
                "b.jpg",
                "/photos/album/b.jpg",
                20,
            )],
        );

        let dir = TempDir::new().unwrap();
        let entries = collect_remote_files(&mut client, "/photos", dir.path()).unwrap();
        let remote: Vec<&str> = entries
            .iter()
            .map(|entry| entry.remote_path.as_str())
            .collect();
        assert_eq!(entries.len(), 2);
        assert!(remote.contains(&"/photos/a.jpg"));
        assert!(remote.contains(&"/photos/album/b.jpg"));
        assert_eq!(entries.iter().map(|entry| entry.size).sum::<u64>(), 30);
    }

    #[test]
    fn a_listing_that_names_itself_as_a_child_does_not_loop() {
        // FTP MLSD `type=cdir` with the real path, or a WebDAV self-href,
        // would otherwise list the same directory forever until OOM.
        let mut client = FakeRemote::with_budget(8);
        client.add_dir(
            "/photos",
            vec![
                crate::protocols::RemoteFile::dir("photos", "/photos"),
                crate::protocols::RemoteFile::file("a.jpg", "/photos/a.jpg", 4),
            ],
        );

        let dir = TempDir::new().unwrap();
        let entries = collect_remote_files(&mut client, "/photos", dir.path()).unwrap();
        assert_eq!(entries.len(), 1);
        assert_eq!(entries[0].remote_path, "/photos/a.jpg");
        assert_eq!(client.lists, 1);
    }

    #[test]
    fn a_listing_that_points_at_a_parent_does_not_walk_the_server() {
        // FTP `type=pdir` with an absolute parent path would otherwise climb
        // to `/` and then cycle through the whole tree.
        let mut client = FakeRemote::with_budget(8);
        client.add_dir(
            "/photos",
            vec![
                crate::protocols::RemoteFile::dir("up", "/"),
                crate::protocols::RemoteFile::file("a.jpg", "/photos/a.jpg", 4),
            ],
        );
        client.add_dir(
            "/",
            vec![crate::protocols::RemoteFile::dir("photos", "/photos")],
        );

        let dir = TempDir::new().unwrap();
        let entries = collect_remote_files(&mut client, "/photos", dir.path()).unwrap();
        assert_eq!(entries.len(), 1);
        assert_eq!(entries[0].remote_path, "/photos/a.jpg");
        assert!(client.lists <= 2);
    }

    #[test]
    fn a_directory_symlink_back_to_an_ancestor_does_not_loop() {
        // SFTP treats a symlink-to-dir as a directory. REALPATH collapses the
        // growing `/tree/link/link/...` path onto `/tree`, which is already
        // visited.
        let mut client = FakeRemote::with_budget(8);
        client.aliases.push(("/tree/link".into(), "/tree".into()));
        client.add_dir(
            "/tree",
            vec![
                crate::protocols::RemoteFile::dir("link", "/tree/link"),
                crate::protocols::RemoteFile::file("notes.txt", "/tree/notes.txt", 3),
            ],
        );

        let dir = TempDir::new().unwrap();
        let entries = collect_remote_files(&mut client, "/tree", dir.path()).unwrap();
        assert_eq!(entries.len(), 1);
        assert_eq!(entries[0].remote_path, "/tree/notes.txt");
        assert_eq!(client.lists, 1);
    }

    #[test]
    fn a_large_remote_folder_is_listed_without_unbounded_growth() {
        // A wide listing must be collected as a finite Vec, not walked as if
        // each file were another directory, and must not panic on the size.
        const FILES: usize = 8_000;
        let mut client = FakeRemote::with_budget(4);
        let children: Vec<_> = (0..FILES)
            .map(|i| {
                crate::protocols::RemoteFile::file(
                    format!("f{i}.dat"),
                    format!("/wide/f{i}.dat"),
                    1,
                )
            })
            .collect();
        client.add_dir("/wide", children);

        let dir = TempDir::new().unwrap();
        let entries = collect_remote_files(&mut client, "/wide", dir.path()).unwrap();
        assert_eq!(entries.len(), FILES);
        assert_eq!(client.lists, 1);
        assert_eq!(
            entries.iter().map(|entry| entry.size).sum::<u64>(),
            FILES as u64
        );
    }

    #[test]
    fn a_deep_remote_tree_does_not_overflow_the_stack() {
        const DEPTH: usize = 400;
        let mut client = FakeRemote::with_budget(DEPTH + 4);
        for level in 0..DEPTH {
            let path = format!("/d{level}");
            let mut children = vec![crate::protocols::RemoteFile::file(
                "leaf.txt",
                format!("{path}/leaf.txt"),
                1,
            )];
            if level + 1 < DEPTH {
                children.push(crate::protocols::RemoteFile::dir(
                    "next",
                    format!("/d{}", level + 1),
                ));
            }
            client.add_dir(&path, children);
        }

        let dir = TempDir::new().unwrap();
        let entries = collect_remote_files(&mut client, "/d0", dir.path()).unwrap();
        assert_eq!(entries.len(), DEPTH);
        assert_eq!(client.lists, DEPTH);
    }
}
