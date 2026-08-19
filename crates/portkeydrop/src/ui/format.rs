//! Turning model values into the text the user sees and hears.
//!
//! Screen reader users get these strings read aloud, so they are written to be
//! listened to: the item's name first, then its details, with the units spelled
//! out rather than left as bare numbers.

use portkeydrop_core::protocols::RemoteFile;
use portkeydrop_core::transfer::{format_bytes, Status, TransferJob};

/// The columns both file panes show.
pub const FILE_COLUMNS: [(&str, i32); 5] = [
    ("Name", 200),
    ("Size", 80),
    ("Type", 70),
    ("Modified", 130),
    ("Permissions", 100),
];

/// The cell values for one file row.
pub fn file_row(file: &RemoteFile) -> [String; 5] {
    [
        file.name.clone(),
        file.display_size(),
        file.display_type(),
        file.display_modified(),
        file.permissions.clone(),
    ]
}

/// A whole file row as one spoken sentence.
///
/// Used where a single-column list is the more accessible control, and as the
/// text announced when focus lands on a row.
pub fn file_row_text(file: &RemoteFile) -> String {
    let mut parts = vec![if file.name.is_empty() {
        "Item".to_string()
    } else {
        file.name.clone()
    }];
    parts.push(file.display_type());
    if !file.is_dir {
        parts.push(format!("size {}", file.display_size()));
    }
    let modified = file.display_modified();
    if !modified.is_empty() {
        parts.push(format!("modified {modified}"));
    }
    if !file.permissions.is_empty() {
        parts.push(format!("permissions {}", file.permissions));
    }
    parts.join(", ")
}

/// The columns the transfer queue shows.
pub const QUEUE_COLUMNS: [(&str, i32); 5] = [
    ("File", 200),
    ("Direction", 90),
    ("Status", 120),
    ("Progress", 90),
    ("Detail", 160),
];

/// The cell values for one queue row.
pub fn queue_row(job: &TransferJob) -> [String; 5] {
    [
        job.display_name(),
        job.direction.label().to_string(),
        queue_status_text(job),
        format!("{}%", job.progress),
        portkeydrop_core::transfer::format_transfer_detail(job),
    ]
}

/// The Status column text, including the failure reason when there is one.
pub fn queue_status_text(job: &TransferJob) -> String {
    match (&job.status, job.error.as_deref()) {
        (Status::Failed, Some(error)) => format!("failed: {error}"),
        (status, _) => status.label().to_string(),
    }
}

/// What to announce when a directory listing finishes loading.
pub fn listing_announcement(pane: &str, path: &str, shown: usize, total: usize) -> String {
    let count = if shown == 1 {
        "1 item".to_string()
    } else {
        format!("{shown} items")
    };
    if shown == total {
        format!("{pane}, {path}, {count}")
    } else {
        // The user filtered or hid something; saying only the visible count
        // would make files look as if they had vanished.
        format!("{pane}, {path}, {count} of {total}")
    }
}

/// What to announce when a filter is applied or cleared.
pub fn filter_announcement(filter: &str, shown: usize, total: usize) -> String {
    if filter.is_empty() {
        return format!("Filter cleared, {total} items");
    }
    if shown == 0 {
        return format!("No items match {filter}");
    }
    format!("{shown} of {total} items match {filter}")
}

/// What to announce as a transfer progresses.
pub fn transfer_progress_announcement(job: &TransferJob) -> String {
    format!(
        "{} {}, {} percent, {}",
        job.direction.label(),
        job.display_name(),
        job.progress,
        portkeydrop_core::transfer::format_transfer_detail(job)
    )
}

/// What to announce when a transfer finishes, whatever the outcome.
pub fn transfer_finished_announcement(job: &TransferJob) -> String {
    let name = job.display_name();
    match job.status {
        Status::Complete => format!(
            "{} of {name} complete, {}",
            job.direction.label(),
            format_bytes(job.transferred_bytes)
        ),
        Status::Failed => format!(
            "{} of {name} failed: {}",
            job.direction.label(),
            job.error.as_deref().unwrap_or("unknown error")
        ),
        Status::Cancelled => format!("{} of {name} cancelled", job.direction.label()),
        status => format!("{} of {name} {}", job.direction.label(), status.label()),
    }
}

/// Whether progress should be announced at this percentage.
///
/// Announcing every byte would drown out everything else, so it is limited to
/// each `interval` percent, plus the very end.
pub fn should_announce_progress(previous: Option<u8>, current: u8, interval: u32) -> bool {
    if interval == 0 {
        return false;
    }
    let interval = interval.clamp(1, 100) as u8;
    match previous {
        None => current > 0,
        Some(previous) if current <= previous => false,
        Some(previous) => current == 100 || (current / interval) > (previous / interval),
    }
}

/// The running version, naming the nightly when this is one.
///
/// A nightly carries the version of the release before it, so "0.6.0" alone
/// leaves someone on a nightly unable to say which build they have -- or to
/// tell whether an update actually landed.
pub fn build_version() -> String {
    match portkeydrop_core::nightly_date() {
        Some(date) => format!("{} nightly {date}", portkeydrop_core::VERSION),
        None => portkeydrop_core::VERSION.to_string(),
    }
}

/// The status bar's connection field.
pub fn connection_status(connected: bool, host: &str) -> String {
    if connected && !host.is_empty() {
        format!("Connected to {host}")
    } else if connected {
        "Connected".to_string()
    } else {
        "Disconnected".to_string()
    }
}

/// The window title.
pub fn window_title(remote_path: Option<&str>) -> String {
    match remote_path.filter(|path| !path.is_empty()) {
        Some(path) => format!("{} - {path}", portkeydrop_core::APP_NAME),
        None => portkeydrop_core::APP_NAME.to_string(),
    }
}

/// One activity log line, timestamped.
pub fn log_line(timestamp: chrono::NaiveDateTime, message: &str) -> String {
    format!("[{}] {message}", timestamp.format("%H:%M:%S"))
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::NaiveDate;
    use portkeydrop_core::transfer::Direction;

    fn file() -> RemoteFile {
        let mut file = RemoteFile::file("notes.txt", "/home/a/notes.txt", 2048);
        file.permissions = "-rw-r--r--".into();
        file.modified = Some(
            NaiveDate::from_ymd_opt(2026, 3, 4)
                .unwrap()
                .and_hms_opt(9, 5, 0)
                .unwrap(),
        );
        file
    }

    fn job(status: Status) -> TransferJob {
        let mut job =
            TransferJob::new(Direction::Download, "/remote/notes.txt", "/local/notes.txt");
        job.status = status;
        job.total_bytes = 2048;
        job.transferred_bytes = 1024;
        job.update_progress();
        job
    }

    #[test]
    fn a_file_row_fills_every_column() {
        let row = file_row(&file());
        assert_eq!(row[0], "notes.txt");
        assert_eq!(row[1], "2.0 KB");
        assert_eq!(row[2], "TXT file");
        assert_eq!(row[3], "2026-03-04 09:05");
        assert_eq!(row[4], "-rw-r--r--");
    }

    #[test]
    fn the_spoken_row_leads_with_the_file_name() {
        // The name is what the user is looking for; details come after.
        let text = file_row_text(&file());
        assert!(text.starts_with("notes.txt,"));
        assert!(text.contains("size 2.0 KB"));
        assert!(text.contains("modified 2026-03-04 09:05"));
        assert!(text.contains("permissions -rw-r--r--"));
    }

    #[test]
    fn a_directory_is_not_announced_with_a_size() {
        // "<DIR>" read aloud after every folder is noise.
        let text = file_row_text(&RemoteFile::dir("docs", "/docs"));
        assert!(text.starts_with("docs, Folder"));
        assert!(!text.contains("size"));
    }

    #[test]
    fn an_unnamed_row_still_says_something() {
        let text = file_row_text(&RemoteFile::default());
        assert!(text.starts_with("Item"));
    }

    #[test]
    fn empty_details_are_left_out_of_the_spoken_row() {
        let bare = RemoteFile::file("a.bin", "/a.bin", 10);
        let text = file_row_text(&bare);
        assert!(!text.contains("modified"));
        assert!(!text.contains("permissions"));
    }

    #[test]
    fn a_queue_row_fills_every_column() {
        let row = queue_row(&job(Status::InProgress));
        assert_eq!(row[0], "notes.txt");
        assert_eq!(row[1], "Download");
        assert_eq!(row[2], "in progress");
        assert_eq!(row[3], "50%");
        assert_eq!(row[4], "1.0 KB of 2.0 KB");
    }

    #[test]
    fn a_failed_queue_row_carries_the_reason() {
        // "failed" alone gives the user nothing to act on.
        let mut failed = job(Status::Failed);
        failed.error = Some("permission denied".into());
        assert_eq!(queue_status_text(&failed), "failed: permission denied");
    }

    #[test]
    fn a_failure_without_a_reason_still_reads_as_failed() {
        assert_eq!(queue_status_text(&job(Status::Failed)), "failed");
    }

    #[test]
    fn a_full_listing_announces_just_the_count() {
        assert_eq!(
            listing_announcement("Remote files", "/home", 12, 12),
            "Remote files, /home, 12 items"
        );
    }

    #[test]
    fn a_single_item_is_announced_in_the_singular() {
        assert_eq!(
            listing_announcement("Local files", "/tmp", 1, 1),
            "Local files, /tmp, 1 item"
        );
    }

    #[test]
    fn a_partial_listing_says_how_many_are_hidden() {
        // Without the total, filtered-out files look as though they vanished.
        assert_eq!(
            listing_announcement("Remote files", "/home", 3, 12),
            "Remote files, /home, 3 items of 12"
        );
    }

    #[test]
    fn filter_announcements_cover_matching_empty_and_cleared() {
        assert_eq!(filter_announcement("log", 3, 12), "3 of 12 items match log");
        assert_eq!(filter_announcement("zzz", 0, 12), "No items match zzz");
        assert_eq!(filter_announcement("", 0, 12), "Filter cleared, 12 items");
    }

    #[test]
    fn progress_announcements_name_the_file_and_the_amount() {
        let text = transfer_progress_announcement(&job(Status::InProgress));
        assert!(text.contains("Download notes.txt"));
        assert!(text.contains("50 percent"));
        assert!(text.contains("1.0 KB of 2.0 KB"));
    }

    #[test]
    fn a_completed_transfer_announces_how_much_moved() {
        let mut complete = job(Status::Complete);
        complete.transferred_bytes = 2048;
        let text = transfer_finished_announcement(&complete);
        assert!(text.contains("complete"));
        assert!(text.contains("2.0 KB"));
    }

    #[test]
    fn a_failed_transfer_announces_why() {
        let mut failed = job(Status::Failed);
        failed.error = Some("connection lost".into());
        assert!(transfer_finished_announcement(&failed).contains("connection lost"));
    }

    #[test]
    fn a_failure_with_no_message_still_announces_something() {
        assert!(transfer_finished_announcement(&job(Status::Failed)).contains("unknown error"));
    }

    #[test]
    fn a_cancelled_transfer_is_announced_as_cancelled() {
        assert!(transfer_finished_announcement(&job(Status::Cancelled)).contains("cancelled"));
    }

    #[test]
    fn progress_is_announced_once_per_interval() {
        assert!(should_announce_progress(None, 5, 25));
        assert!(should_announce_progress(Some(20), 25, 25));
        assert!(should_announce_progress(Some(49), 50, 25));
        // Within the same band there is nothing new to say.
        assert!(!should_announce_progress(Some(26), 30, 25));
    }

    #[test]
    fn completion_is_always_announced() {
        // 100% matters even when it lands inside the previous band.
        assert!(should_announce_progress(Some(99), 100, 25));
    }

    #[test]
    fn progress_going_backwards_is_not_announced() {
        // A restarted transfer resets the counter; re-announcing would be
        // confusing.
        assert!(!should_announce_progress(Some(50), 20, 25));
        assert!(!should_announce_progress(Some(50), 50, 25));
    }

    #[test]
    fn a_zero_interval_turns_progress_announcements_off() {
        assert!(!should_announce_progress(Some(0), 50, 0));
        assert!(!should_announce_progress(None, 100, 0));
    }

    #[test]
    fn the_status_bar_names_the_connected_host() {
        assert_eq!(
            connection_status(true, "sftp.example.com"),
            "Connected to sftp.example.com"
        );
        assert_eq!(connection_status(true, ""), "Connected");
        assert_eq!(connection_status(false, "sftp.example.com"), "Disconnected");
    }

    #[test]
    fn the_window_title_shows_the_remote_path_when_connected() {
        assert_eq!(window_title(Some("/home/a")), "Portkey Drop - /home/a");
        assert_eq!(window_title(None), "Portkey Drop");
        assert_eq!(window_title(Some("")), "Portkey Drop");
    }

    #[test]
    fn log_lines_are_timestamped_to_the_second() {
        let when = NaiveDate::from_ymd_opt(2026, 3, 4)
            .unwrap()
            .and_hms_opt(9, 5, 30)
            .unwrap();
        assert_eq!(log_line(when, "Connected"), "[09:05:30] Connected");
    }
}

#[cfg(test)]
mod build_version_tests {
    #[test]
    fn the_version_string_is_never_empty() {
        assert!(!super::build_version().is_empty());
    }

    #[test]
    fn a_nightly_build_says_so() {
        // Compiled without the stamp this is just the version; the point is
        // that whichever it is, it names the build well enough to compare
        // against what the update dialog offers.
        let version = super::build_version();
        assert!(version.starts_with(portkeydrop_core::VERSION), "{version}");
        if portkeydrop_core::nightly_date().is_some() {
            assert!(version.contains("nightly"), "{version}");
        }
    }
}
