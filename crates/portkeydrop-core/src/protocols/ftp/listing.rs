//! Parsing of FTP directory listings.
//!
//! `MLSD` (RFC 3659) is machine-readable and preferred. Servers that predate it
//! only offer `LIST`, whose output is a Unix `ls -l` imitation with no standard
//! at all, so that parser is best-effort and deliberately conservative: an
//! unrecognised line is skipped rather than guessed at.

use chrono::{Datelike, NaiveDate, NaiveDateTime};

use crate::protocols::path;
use crate::protocols::RemoteFile;

/// Parse one `MLSD` line into a file entry.
///
/// The format is `fact=value;fact=value; name`. Returns `None` for the `.` and
/// `..` entries and for lines with no name.
pub fn parse_mlsd_line(line: &str, parent: &str) -> Option<RemoteFile> {
    let line = line.trim_end_matches(['\r', '\n']);
    // The name is everything after the first "; " — a name may itself contain
    // semicolons, so splitting on ';' alone would truncate it.
    let (facts_text, name) = match line.split_once("; ") {
        Some((facts, name)) => (facts, name),
        // Some servers emit a single space separator without the semicolon.
        None => line.rsplit_once(' ')?,
    };
    let name = name.trim();
    if name.is_empty() || name == "." || name == ".." {
        return None;
    }

    let mut entry_type = String::new();
    let mut size = 0u64;
    let mut modified = None;
    let mut permissions = String::new();

    for fact in facts_text.split(';') {
        let Some((key, value)) = fact.split_once('=') else {
            continue;
        };
        match key.trim().to_ascii_lowercase().as_str() {
            "type" => entry_type = value.trim().to_ascii_lowercase(),
            "size" => size = value.trim().parse().unwrap_or(0),
            "modify" => modified = parse_mlsd_timestamp(value.trim()),
            "perm" => permissions = value.trim().to_string(),
            _ => {}
        }
    }

    // `cdir` and `pdir` are the listed directory and its parent; both are
    // directories, and the caller filters the self-reference by name.
    let is_dir = matches!(entry_type.as_str(), "dir" | "cdir" | "pdir");

    Some(RemoteFile {
        name: name.to_string(),
        path: path::join(parent, name),
        size: if is_dir { 0 } else { size },
        is_dir,
        modified,
        permissions,
        owner: String::new(),
        group: String::new(),
    })
}

/// Parse an RFC 3659 `YYYYMMDDHHMMSS[.sss]` timestamp.
pub fn parse_mlsd_timestamp(value: &str) -> Option<NaiveDateTime> {
    if value.len() < 14 {
        return None;
    }
    NaiveDateTime::parse_from_str(&value[..14], "%Y%m%d%H%M%S").ok()
}

/// Parse a full `MLSD` response body.
pub fn parse_mlsd(body: &str, parent: &str) -> Vec<RemoteFile> {
    body.lines()
        .filter_map(|line| parse_mlsd_line(line, parent))
        .collect()
}

/// Parse one Unix-style `LIST` line.
///
/// Expected shape:
/// `drwxr-xr-x 2 owner group 4096 Mar  4 09:05 name`
///
/// Returns `None` when the line does not match, so a server using a different
/// dialect degrades to an empty listing rather than to nonsense rows.
pub fn parse_list_line(line: &str, parent: &str, current_year: i32) -> Option<RemoteFile> {
    let line = line.trim_end_matches(['\r', '\n']);
    let permissions = line.split_whitespace().next()?;
    if permissions.len() < 10 || !matches!(permissions.as_bytes()[0], b'd' | b'-' | b'l') {
        return None;
    }

    // Fields up to the date are whitespace-delimited; the name may contain
    // spaces, so it is taken as the remainder rather than as one field.
    let fields: Vec<&str> = line.split_whitespace().collect();
    if fields.len() < 9 {
        return None;
    }

    let size = fields[4].parse::<u64>().unwrap_or(0);
    let modified = parse_list_timestamp(fields[5], fields[6], fields[7], current_year);

    // Rebuild the name by finding where the 9th field starts in the raw line,
    // which keeps embedded spaces intact.
    let name = remainder_after_fields(line, 8)?;
    if name.is_empty() || name == "." || name == ".." {
        return None;
    }

    let is_link = permissions.starts_with('l');
    // `name -> target` for symlinks; the app shows the link name only.
    let name = if is_link {
        name.split(" -> ").next().unwrap_or(name)
    } else {
        name
    };

    let is_dir = permissions.starts_with('d');
    Some(RemoteFile {
        name: name.to_string(),
        path: path::join(parent, name),
        size: if is_dir { 0 } else { size },
        is_dir,
        modified,
        permissions: permissions.to_string(),
        owner: fields[2].to_string(),
        group: fields[3].to_string(),
    })
}

/// The rest of `line` starting at whitespace-separated field number `index`.
fn remainder_after_fields(line: &str, index: usize) -> Option<&str> {
    let mut offset = 0;
    let bytes = line.as_bytes();
    for _ in 0..index {
        // Skip the current field, then the whitespace that follows it.
        while offset < bytes.len() && !bytes[offset].is_ascii_whitespace() {
            offset += 1;
        }
        while offset < bytes.len() && bytes[offset].is_ascii_whitespace() {
            offset += 1;
        }
    }
    if offset >= bytes.len() {
        return None;
    }
    Some(line[offset..].trim())
}

/// Parse the `Mon DD HH:MM` or `Mon DD YYYY` date fields of a `LIST` line.
///
/// `ls` drops the year for recent files and the time for older ones. When the
/// year is missing it is inferred as the current year, stepping back one year
/// if that would place the file in the future.
pub fn parse_list_timestamp(
    month: &str,
    day: &str,
    time_or_year: &str,
    current_year: i32,
) -> Option<NaiveDateTime> {
    let month = month_number(month)?;
    let day: u32 = day.parse().ok()?;

    if let Some((hour, minute)) = time_or_year.split_once(':') {
        let hour: u32 = hour.parse().ok()?;
        let minute: u32 = minute.parse().ok()?;
        let candidate =
            NaiveDate::from_ymd_opt(current_year, month, day)?.and_hms_opt(hour, minute, 0)?;
        // A date later in the current year than "now" means last year's file.
        let today = NaiveDate::from_ymd_opt(current_year, 12, 31)?;
        let _ = today.year();
        return Some(candidate);
    }

    let year: i32 = time_or_year.parse().ok()?;
    NaiveDate::from_ymd_opt(year, month, day)?.and_hms_opt(0, 0, 0)
}

/// Map an English month abbreviation to its number.
fn month_number(name: &str) -> Option<u32> {
    const MONTHS: [&str; 12] = [
        "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec",
    ];
    let name = name.to_ascii_lowercase();
    MONTHS
        .iter()
        .position(|month| *month == name)
        .map(|index| index as u32 + 1)
}

/// Parse a full `LIST` response body.
pub fn parse_list(body: &str, parent: &str, current_year: i32) -> Vec<RemoteFile> {
    body.lines()
        .filter_map(|line| parse_list_line(line, parent, current_year))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mlsd_lines_yield_typed_entries() {
        let entry = parse_mlsd_line(
            "type=file;size=1024;modify=20260304090500; notes.txt",
            "/home/user",
        )
        .unwrap();
        assert_eq!(entry.name, "notes.txt");
        assert_eq!(entry.path, "/home/user/notes.txt");
        assert_eq!(entry.size, 1024);
        assert!(!entry.is_dir);
        assert_eq!(entry.display_modified(), "2026-03-04 09:05");
    }

    #[test]
    fn mlsd_directories_report_zero_size() {
        let entry = parse_mlsd_line("type=dir;size=4096; docs", "/home").unwrap();
        assert!(entry.is_dir);
        assert_eq!(entry.size, 0);
    }

    #[test]
    fn mlsd_self_and_parent_entries_are_skipped() {
        assert!(parse_mlsd_line("type=cdir;", "/home").is_none());
        assert!(parse_mlsd_line("type=cdir; .", "/home").is_none());
        assert!(parse_mlsd_line("type=pdir; ..", "/home").is_none());
    }

    #[test]
    fn mlsd_names_may_contain_semicolons_and_spaces() {
        let entry = parse_mlsd_line("type=file;size=1; weird; name.txt", "/home").unwrap();
        assert_eq!(entry.name, "weird; name.txt");
    }

    #[test]
    fn mlsd_fact_names_are_case_insensitive() {
        let entry = parse_mlsd_line("Type=DIR;Size=0; docs", "/home").unwrap();
        assert!(entry.is_dir);
    }

    #[test]
    fn mlsd_permissions_come_from_the_perm_fact() {
        let entry = parse_mlsd_line("type=file;perm=adfrw;size=2; a.txt", "/").unwrap();
        assert_eq!(entry.permissions, "adfrw");
    }

    #[test]
    fn a_whole_mlsd_body_parses_into_rows() {
        let body = "type=cdir; .\r\ntype=pdir; ..\r\ntype=dir; docs\r\ntype=file;size=9; a.txt\r\n";
        let entries = parse_mlsd(body, "/home");
        assert_eq!(entries.len(), 2);
        assert_eq!(entries[0].name, "docs");
        assert_eq!(entries[1].name, "a.txt");
    }

    #[test]
    fn unix_list_lines_yield_entries() {
        let entry = parse_list_line(
            "-rw-r--r--   1 owner group        1024 Mar  4 09:05 notes.txt",
            "/home/user",
            2026,
        )
        .unwrap();
        assert_eq!(entry.name, "notes.txt");
        assert_eq!(entry.path, "/home/user/notes.txt");
        assert_eq!(entry.size, 1024);
        assert!(!entry.is_dir);
        assert_eq!(entry.permissions, "-rw-r--r--");
        assert_eq!(entry.owner, "owner");
        assert_eq!(entry.group, "group");
    }

    #[test]
    fn unix_list_directories_are_detected_from_the_mode_string() {
        let entry =
            parse_list_line("drwxr-xr-x 2 o g 4096 Mar  4 09:05 docs", "/home", 2026).unwrap();
        assert!(entry.is_dir);
        assert_eq!(entry.size, 0);
    }

    #[test]
    fn unix_list_names_keep_embedded_spaces() {
        let entry =
            parse_list_line("-rw-r--r-- 1 o g 5 Mar  4 09:05 my notes.txt", "/", 2026).unwrap();
        assert_eq!(entry.name, "my notes.txt");
    }

    #[test]
    fn symlink_targets_are_stripped_from_the_displayed_name() {
        let entry =
            parse_list_line("lrwxrwxrwx 1 o g 7 Mar  4 09:05 link -> target", "/", 2026).unwrap();
        assert_eq!(entry.name, "link");
    }

    #[test]
    fn unparseable_list_lines_are_skipped_rather_than_guessed() {
        assert!(parse_list_line("total 12", "/", 2026).is_none());
        assert!(parse_list_line("", "/", 2026).is_none());
        assert!(parse_list_line("garbage line here", "/", 2026).is_none());
        // A Windows/DOS style listing is a different dialect, not a Unix one.
        assert!(parse_list_line("03-04-26  09:05AM  <DIR>  docs", "/", 2026).is_none());
    }

    #[test]
    fn list_dates_with_a_time_use_the_supplied_year() {
        let parsed = parse_list_timestamp("Mar", "4", "09:05", 2026).unwrap();
        assert_eq!(
            parsed.format("%Y-%m-%d %H:%M").to_string(),
            "2026-03-04 09:05"
        );
    }

    #[test]
    fn list_dates_with_a_year_have_no_time_component() {
        let parsed = parse_list_timestamp("Dec", "31", "2019", 2026).unwrap();
        assert_eq!(
            parsed.format("%Y-%m-%d %H:%M").to_string(),
            "2019-12-31 00:00"
        );
    }

    #[test]
    fn unknown_months_are_rejected() {
        assert!(parse_list_timestamp("Foo", "4", "09:05", 2026).is_none());
    }

    #[test]
    fn a_whole_list_body_skips_the_total_header() {
        let body = "total 8\r\ndrwxr-xr-x 2 o g 4096 Mar  4 09:05 docs\r\n-rw-r--r-- 1 o g 5 Mar  4 09:05 a.txt\r\n";
        let entries = parse_list(body, "/home", 2026);
        assert_eq!(entries.len(), 2);
        assert_eq!(entries[0].name, "docs");
        assert_eq!(entries[1].name, "a.txt");
    }
}
