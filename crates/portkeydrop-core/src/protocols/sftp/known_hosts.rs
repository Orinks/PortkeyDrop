//! Reading, matching, and appending OpenSSH `known_hosts` entries.
//!
//! Only the plain (unhashed) host-name form is written, because the file is
//! also meant to be human-readable when a user checks what they have trusted.
//! Hashed entries written by OpenSSH itself are recognised but skipped rather
//! than mis-parsed, so a hashed file degrades to "unknown host" and prompts
//! instead of silently trusting the wrong key.

use std::path::Path;

/// A UTF-8 byte order mark, which some Windows editors write at the start
/// of a file whether or not anyone wanted one.
const BYTE_ORDER_MARK: char = '\u{feff}';

/// One parsed `known_hosts` line.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct KnownHostEntry {
    /// Comma-separated host patterns exactly as written.
    pub patterns: String,
    /// Key algorithm, e.g. `ssh-ed25519`.
    pub key_type: String,
    /// Base64 key blob.
    pub key_data: String,
}

impl KnownHostEntry {
    /// Whether this entry covers `host` on `port`.
    pub fn matches(&self, host: &str, port: u16) -> bool {
        // A hashed entry (`|1|salt|hash`) cannot be compared by name.
        if self.patterns.starts_with('|') {
            return false;
        }
        let target = host_pattern(host, port);
        let bare = host.to_ascii_lowercase();
        self.patterns.split(',').any(|pattern| {
            let pattern = pattern.trim().to_ascii_lowercase();
            // A non-default port is written as `[host]:port`; the default port
            // is written bare, so both spellings are accepted for port 22.
            pattern == target || (port == 22 && pattern == bare)
        })
    }

    /// The `known_hosts` line for this entry.
    pub fn to_line(&self) -> String {
        format!("{} {} {}", self.patterns, self.key_type, self.key_data)
    }
}

/// The host pattern OpenSSH uses for a host and port.
pub fn host_pattern(host: &str, port: u16) -> String {
    if port == 22 {
        host.to_ascii_lowercase()
    } else {
        format!("[{}]:{}", host.to_ascii_lowercase(), port)
    }
}

/// Parse one line, returning `None` for blanks, comments, and malformed lines.
pub fn parse_line(line: &str) -> Option<KnownHostEntry> {
    let line = line.trim();
    if line.is_empty() || line.starts_with('#') {
        return None;
    }
    // `@revoked` and `@cert-authority` markers change the meaning of a line;
    // treating them as ordinary entries would trust a revoked key.
    if line.starts_with('@') {
        return None;
    }

    let mut fields = line.split_whitespace();
    let patterns = fields.next()?;
    let key_type = fields.next()?;
    let key_data = fields.next()?;
    Some(KnownHostEntry {
        patterns: patterns.to_string(),
        key_type: key_type.to_string(),
        key_data: key_data.to_string(),
    })
}

/// Parse a whole `known_hosts` document.
pub fn parse(contents: &str) -> Vec<KnownHostEntry> {
    // A byte order mark would otherwise become part of the first entry's
    // host pattern, so exactly one host -- whichever is first -- stops
    // matching. Windows editors add one without being asked.
    let contents = contents.strip_prefix(BYTE_ORDER_MARK).unwrap_or(contents);
    contents.lines().filter_map(parse_line).collect()
}

/// Load entries from disk; a missing file yields no entries.
pub fn load(path: &Path) -> Vec<KnownHostEntry> {
    match std::fs::read_to_string(path) {
        Ok(contents) => parse(&contents),
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => Vec::new(),
        Err(err) => {
            log::warn!("could not read {}: {err}", path.display());
            Vec::new()
        }
    }
}

/// What the known-hosts file says about a key offered by a server.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HostKeyStatus {
    /// This exact key is already trusted for this host.
    Known,
    /// Nothing is recorded for this host.
    Unknown,
    /// A *different* key is recorded for this host.
    ///
    /// This is the man-in-the-middle case and is never resolved by prompting.
    Changed,
}

/// Compare an offered key against the entries for a host.
pub fn status(
    entries: &[KnownHostEntry],
    host: &str,
    port: u16,
    key_type: &str,
    key_data: &str,
) -> HostKeyStatus {
    let mut host_seen = false;
    for entry in entries {
        if !entry.matches(host, port) {
            continue;
        }
        if entry.key_type == key_type {
            if entry.key_data == key_data {
                return HostKeyStatus::Known;
            }
            host_seen = true;
        }
    }
    if host_seen {
        HostKeyStatus::Changed
    } else {
        HostKeyStatus::Unknown
    }
}

/// Append a trusted key to the known-hosts file, creating it if needed.
pub fn append(
    path: &Path,
    host: &str,
    port: u16,
    key_type: &str,
    key_data: &str,
) -> std::io::Result<()> {
    use std::io::Write;

    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let entry = KnownHostEntry {
        patterns: host_pattern(host, port),
        key_type: key_type.to_string(),
        key_data: key_data.to_string(),
    };
    let mut file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)?;

    // Start a line of our own. A file whose last line has no newline -- one
    // an editor saved, or an earlier release wrote -- would otherwise have
    // this entry glued onto it, breaking the host recorded there. That host
    // then reads as a *changed* key, which is refused outright, so accepting
    // one server silently stops another from connecting.
    if ends_mid_line(path) {
        writeln!(file)?;
    }
    writeln!(file, "{}", entry.to_line())
}

/// Whether the file ends part way through a line, owing a newline.
fn ends_mid_line(path: &Path) -> bool {
    use std::io::{Read, Seek, SeekFrom};

    let Ok(mut file) = std::fs::File::open(path) else {
        return false;
    };
    // Only the last byte matters, so the file is not read into memory.
    if file.seek(SeekFrom::End(-1)).is_err() {
        return false; // Empty or not seekable; nothing is owed either way.
    }
    let mut last = [0u8; 1];
    matches!(file.read_exact(&mut last), Ok(())) && last[0] != b'\n'
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    const ED25519: &str = "AAAAC3NzaC1lZDI1NTE5AAAAIExample1";
    const OTHER: &str = "AAAAC3NzaC1lZDI1NTE5AAAAIExample2";

    #[test]
    fn default_port_hosts_are_written_bare() {
        assert_eq!(host_pattern("Example.COM", 22), "example.com");
    }

    #[test]
    fn non_default_ports_use_the_bracket_form() {
        assert_eq!(host_pattern("example.com", 2222), "[example.com]:2222");
    }

    #[test]
    fn blank_lines_and_comments_are_skipped() {
        assert!(parse_line("").is_none());
        assert!(parse_line("   ").is_none());
        assert!(parse_line("# a comment").is_none());
    }

    #[test]
    fn marker_lines_are_skipped_rather_than_trusted() {
        // Treating @revoked as an ordinary entry would trust a revoked key.
        assert!(parse_line(&format!("@revoked example.com ssh-ed25519 {ED25519}")).is_none());
        assert!(parse_line(&format!(
            "@cert-authority example.com ssh-ed25519 {ED25519}"
        ))
        .is_none());
    }

    #[test]
    fn a_well_formed_line_parses_into_its_three_fields() {
        let entry = parse_line(&format!("example.com ssh-ed25519 {ED25519} comment")).unwrap();
        assert_eq!(entry.patterns, "example.com");
        assert_eq!(entry.key_type, "ssh-ed25519");
        assert_eq!(entry.key_data, ED25519);
    }

    #[test]
    fn truncated_lines_are_rejected() {
        assert!(parse_line("example.com ssh-ed25519").is_none());
        assert!(parse_line("example.com").is_none());
    }

    #[test]
    fn entries_match_the_bare_host_on_the_default_port() {
        let entry = parse_line(&format!("example.com ssh-ed25519 {ED25519}")).unwrap();
        assert!(entry.matches("example.com", 22));
        assert!(entry.matches("EXAMPLE.com", 22));
        assert!(!entry.matches("example.com", 2222));
        assert!(!entry.matches("other.com", 22));
    }

    #[test]
    fn entries_match_the_bracket_form_on_other_ports() {
        let entry = parse_line(&format!("[example.com]:2222 ssh-ed25519 {ED25519}")).unwrap();
        assert!(entry.matches("example.com", 2222));
        assert!(!entry.matches("example.com", 22));
    }

    #[test]
    fn comma_separated_patterns_all_match() {
        let entry =
            parse_line(&format!("alpha.example,beta.example ssh-ed25519 {ED25519}")).unwrap();
        assert!(entry.matches("alpha.example", 22));
        assert!(entry.matches("beta.example", 22));
        assert!(!entry.matches("gamma.example", 22));
    }

    #[test]
    fn hashed_entries_never_match_by_name() {
        // Without the salt these cannot be compared, so they must read as
        // "unknown" and prompt rather than appear to match.
        let entry = parse_line(&format!("|1|abcdefg=|hijklmn= ssh-ed25519 {ED25519}")).unwrap();
        assert!(!entry.matches("example.com", 22));
    }

    #[test]
    fn a_matching_key_is_reported_as_known() {
        let entries = parse(&format!("example.com ssh-ed25519 {ED25519}\n"));
        assert_eq!(
            status(&entries, "example.com", 22, "ssh-ed25519", ED25519),
            HostKeyStatus::Known
        );
    }

    #[test]
    fn an_absent_host_is_reported_as_unknown() {
        let entries = parse(&format!("other.com ssh-ed25519 {ED25519}\n"));
        assert_eq!(
            status(&entries, "example.com", 22, "ssh-ed25519", ED25519),
            HostKeyStatus::Unknown
        );
    }

    #[test]
    fn a_different_key_for_a_known_host_is_reported_as_changed() {
        // This is the man-in-the-middle signal and must not read as "unknown".
        let entries = parse(&format!("example.com ssh-ed25519 {ED25519}\n"));
        assert_eq!(
            status(&entries, "example.com", 22, "ssh-ed25519", OTHER),
            HostKeyStatus::Changed
        );
    }

    #[test]
    fn a_new_key_algorithm_for_a_known_host_is_unknown_not_changed() {
        // Servers legitimately offer several key types; a type we have not
        // seen before is not evidence of tampering.
        let entries = parse(&format!("example.com ssh-ed25519 {ED25519}\n"));
        assert_eq!(
            status(&entries, "example.com", 22, "ssh-rsa", OTHER),
            HostKeyStatus::Unknown
        );
    }

    #[test]
    fn appending_creates_the_file_and_its_directory() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("nested").join("known_hosts");
        append(&path, "example.com", 22, "ssh-ed25519", ED25519).unwrap();

        let entries = load(&path);
        assert_eq!(
            status(&entries, "example.com", 22, "ssh-ed25519", ED25519),
            HostKeyStatus::Known
        );
    }

    #[test]
    fn appending_preserves_existing_entries() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("known_hosts");
        append(&path, "first.example", 22, "ssh-ed25519", ED25519).unwrap();
        append(&path, "second.example", 2222, "ssh-ed25519", OTHER).unwrap();

        let entries = load(&path);
        assert_eq!(entries.len(), 2);
        assert_eq!(
            status(&entries, "first.example", 22, "ssh-ed25519", ED25519),
            HostKeyStatus::Known
        );
        assert_eq!(
            status(&entries, "second.example", 2222, "ssh-ed25519", OTHER),
            HostKeyStatus::Known
        );
    }

    #[test]
    fn loading_a_missing_file_yields_no_entries() {
        let dir = TempDir::new().unwrap();
        assert!(load(&dir.path().join("nope")).is_empty());
    }
}
