//! File properties.
//!
//! Read-only, and presented as text rather than a grid of fields: a screen
//! reader user can then review the whole thing line by line instead of tabbing
//! between a dozen static labels.

use wxdragon::prelude::*;

use portkeydrop_core::protocols::RemoteFile;

use crate::ui::main_frame::Side;

/// Window title.
pub const TITLE: &str = "Properties";

/// Show properties for a file.
pub fn show(parent: &dyn WxWidget, file: &RemoteFile, side: Side) {
    super::show_text_window(parent, TITLE, &properties_text(file, side));
}

/// The properties text for a file.
pub fn properties_text(file: &RemoteFile, side: Side) -> String {
    let location = match side {
        Side::Local => "Local",
        Side::Remote => "Remote",
    };

    let mut lines = vec![
        format!("Name: {}", file.name),
        format!("Location: {location}"),
        format!("Path: {}", file.path),
        format!("Type: {}", file.display_type()),
    ];

    if file.is_dir {
        // A directory's byte count is meaningless without walking it, and
        // showing "0 bytes" would be actively misleading.
        lines.push("Size: not calculated for folders".to_string());
    } else {
        lines.push(format!(
            "Size: {} ({} bytes)",
            file.display_size(),
            file.size
        ));
    }

    let modified = file.display_modified();
    lines.push(format!(
        "Modified: {}",
        if modified.is_empty() {
            "not reported by the server"
        } else {
            &modified
        }
    ));

    if !file.permissions.is_empty() {
        lines.push(format!("Permissions: {}", file.permissions));
    }
    if !file.owner.is_empty() {
        lines.push(format!("Owner: {}", file.owner));
    }
    if !file.group.is_empty() {
        lines.push(format!("Group: {}", file.group));
    }
    if file.is_hidden() {
        lines.push("Hidden: yes".to_string());
    }

    lines.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::NaiveDate;

    fn file() -> RemoteFile {
        let mut file = RemoteFile::file("notes.txt", "/home/a/notes.txt", 2048);
        file.permissions = "-rw-r--r--".into();
        file.owner = "1000".into();
        file.group = "1000".into();
        file.modified = Some(
            NaiveDate::from_ymd_opt(2026, 3, 4)
                .unwrap()
                .and_hms_opt(9, 5, 0)
                .unwrap(),
        );
        file
    }

    #[test]
    fn properties_list_the_file_details() {
        let text = properties_text(&file(), Side::Remote);
        assert!(text.contains("Name: notes.txt"));
        assert!(text.contains("Location: Remote"));
        assert!(text.contains("Path: /home/a/notes.txt"));
        assert!(text.contains("Type: TXT file"));
        assert!(text.contains("Permissions: -rw-r--r--"));
        assert!(text.contains("Owner: 1000"));
    }

    #[test]
    fn the_size_is_given_both_scaled_and_exact() {
        // The scaled value is readable; the exact one is what you need when
        // comparing against a server or another copy.
        let text = properties_text(&file(), Side::Local);
        assert!(text.contains("Size: 2.0 KB (2048 bytes)"));
    }

    #[test]
    fn a_folder_does_not_claim_to_be_zero_bytes() {
        let text = properties_text(&RemoteFile::dir("docs", "/docs"), Side::Remote);
        assert!(text.contains("Size: not calculated for folders"));
        assert!(!text.contains("0 bytes"));
    }

    #[test]
    fn a_missing_timestamp_says_so_rather_than_showing_nothing() {
        let bare = RemoteFile::file("a.bin", "/a.bin", 1);
        let text = properties_text(&bare, Side::Remote);
        assert!(text.contains("Modified: not reported by the server"));
    }

    #[test]
    fn empty_fields_are_left_out_entirely() {
        let bare = RemoteFile::file("a.bin", "/a.bin", 1);
        let text = properties_text(&bare, Side::Local);
        assert!(!text.contains("Permissions:"));
        assert!(!text.contains("Owner:"));
        assert!(!text.contains("Group:"));
    }

    #[test]
    fn hidden_files_are_marked_as_such() {
        let hidden = RemoteFile::file(".bashrc", "/home/a/.bashrc", 100);
        assert!(properties_text(&hidden, Side::Local).contains("Hidden: yes"));
        assert!(!properties_text(&file(), Side::Local).contains("Hidden:"));
    }

    #[test]
    fn the_local_and_remote_sides_are_distinguished() {
        assert!(properties_text(&file(), Side::Local).contains("Location: Local"));
        assert!(properties_text(&file(), Side::Remote).contains("Location: Remote"));
    }
}
