//! Protocol-independent data model: protocols, host key policy, remote files,
//! and connection parameters.

use std::fmt;
use std::str::FromStr;

use chrono::NaiveDateTime;
use serde::{Deserialize, Serialize};

/// A supported (or planned) file transfer protocol.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
#[derive(Default)]
pub enum Protocol {
    Ftp,
    Ftps,
    #[default]
    Sftp,
    /// Planned; [`crate::protocols::create_client`] rejects it for now.
    Scp,
    Webdav,
}

/// Protocol values the app offers in the UI, in display order.
pub const SUPPORTED_PROTOCOL_VALUES: [&str; 4] = ["sftp", "ftp", "ftps", "webdav"];

impl Protocol {
    /// The wire name used in settings and site files.
    pub fn as_str(self) -> &'static str {
        match self {
            Protocol::Ftp => "ftp",
            Protocol::Ftps => "ftps",
            Protocol::Sftp => "sftp",
            Protocol::Scp => "scp",
            Protocol::Webdav => "webdav",
        }
    }

    /// The port used when a site does not pin one.
    ///
    /// FTP with explicit SSL stays on the plain FTP port because the upgrade
    /// happens after the control connection is established.
    pub fn default_port(self, ftp_explicit_ssl: bool) -> u16 {
        match self {
            Protocol::Ftp => 21,
            Protocol::Ftps if ftp_explicit_ssl => 21,
            Protocol::Ftps => 990,
            Protocol::Sftp | Protocol::Scp => 22,
            Protocol::Webdav => 443,
        }
    }
}

impl fmt::Display for Protocol {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

/// Returned when a protocol name is not recognised.
#[derive(Debug, thiserror::Error)]
#[error("unknown protocol: {0}")]
pub struct UnknownProtocol(pub String);

impl FromStr for Protocol {
    type Err = UnknownProtocol;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value.trim().to_ascii_lowercase().as_str() {
            "ftp" => Ok(Protocol::Ftp),
            "ftps" => Ok(Protocol::Ftps),
            "sftp" => Ok(Protocol::Sftp),
            "scp" => Ok(Protocol::Scp),
            "webdav" => Ok(Protocol::Webdav),
            other => Err(UnknownProtocol(other.to_string())),
        }
    }
}

/// How to treat an SSH host key that is not already trusted.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum HostKeyPolicy {
    /// Trust any key without asking. The historical default.
    #[default]
    AutoAdd,
    /// Refuse anything not already in the known-hosts file.
    Strict,
    /// Ask the user, then optionally remember the answer.
    Prompt,
}

impl HostKeyPolicy {
    /// Map a `verify_host_keys` setting value onto a policy.
    pub fn from_setting(value: &str) -> Self {
        match value.trim().to_ascii_lowercase().as_str() {
            "always" => HostKeyPolicy::Strict,
            "ask" => HostKeyPolicy::Prompt,
            _ => HostKeyPolicy::AutoAdd,
        }
    }
}

/// The user's answer to a host key prompt.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HostKeyDecision {
    /// Abandon the connection.
    Reject,
    /// Trust for this session only.
    AcceptOnce,
    /// Trust and write to the known-hosts file.
    AcceptPermanent,
}

impl HostKeyDecision {
    /// Parse the string form used across the UI boundary.
    pub fn from_str_lossy(value: &str) -> Self {
        match value.trim() {
            "accept_once" => HostKeyDecision::AcceptOnce,
            "accept_permanent" => HostKeyDecision::AcceptPermanent,
            _ => HostKeyDecision::Reject,
        }
    }
}

/// A file or directory on a remote server, or in a local pane.
///
/// The local file browser produces these too, so both panes share one row
/// renderer and one selection model.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct RemoteFile {
    /// Base name as displayed.
    pub name: String,
    /// Full path on its side of the connection.
    pub path: String,
    /// Size in bytes; always 0 for directories.
    pub size: u64,
    pub is_dir: bool,
    /// Modification time in the server's reported local time, if known.
    pub modified: Option<NaiveDateTime>,
    /// Unix-style permission string, e.g. `drwxr-xr-x`.
    pub permissions: String,
    pub owner: String,
    pub group: String,
}

impl RemoteFile {
    /// A file entry with just a name and path.
    pub fn file(name: impl Into<String>, path: impl Into<String>, size: u64) -> Self {
        Self {
            name: name.into(),
            path: path.into(),
            size,
            ..Default::default()
        }
    }

    /// A directory entry with just a name and path.
    pub fn dir(name: impl Into<String>, path: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            path: path.into(),
            is_dir: true,
            ..Default::default()
        }
    }

    /// Size for the Size column: `<DIR>` for directories, else a scaled unit.
    pub fn display_size(&self) -> String {
        if self.is_dir {
            return "<DIR>".to_string();
        }
        const KIB: u64 = 1024;
        const MIB: u64 = KIB * 1024;
        const GIB: u64 = MIB * 1024;
        match self.size {
            size if size < KIB => format!("{size} B"),
            size if size < MIB => format!("{:.1} KB", size as f64 / KIB as f64),
            size if size < GIB => format!("{:.1} MB", size as f64 / MIB as f64),
            size => format!("{:.1} GB", size as f64 / GIB as f64),
        }
    }

    /// Modification time for the Modified column, or an empty string.
    pub fn display_modified(&self) -> String {
        self.modified
            .map(|dt| dt.format("%Y-%m-%d %H:%M").to_string())
            .unwrap_or_default()
    }

    /// Type for the Type column.
    pub fn display_type(&self) -> String {
        if self.is_dir {
            return "Folder".to_string();
        }
        match self.name.rsplit_once('.') {
            Some((stem, ext)) if !stem.is_empty() && !ext.is_empty() => {
                format!("{} file", ext.to_ascii_uppercase())
            }
            _ => "File".to_string(),
        }
    }

    /// Whether this entry is hidden by Unix convention.
    pub fn is_hidden(&self) -> bool {
        self.name.starts_with('.')
    }
}

/// Everything needed to open a connection.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ConnectionInfo {
    pub protocol: Protocol,
    pub host: String,
    /// 0 means "use the protocol default".
    pub port: u16,
    pub username: String,
    /// Password, or the passphrase for `key_path` when that is set.
    pub password: String,
    /// Path to a private key file; empty to use agent/default keys.
    pub key_path: String,
    /// Connect timeout in seconds.
    pub timeout: u64,
    /// SSH only: seconds between keepalive probes. 0 turns them off.
    ///
    /// Idle SFTP sessions are dropped by firewalls and by servers with a
    /// `ClientAliveInterval`; a probe keeps the connection answering.
    pub keepalive: u64,
    /// FTP only.
    pub passive_mode: bool,
    /// FTP only: upgrade the control connection with `AUTH SSL`.
    pub ftp_explicit_ssl: bool,
    pub host_key_policy: HostKeyPolicy,
}

impl Default for ConnectionInfo {
    fn default() -> Self {
        Self {
            protocol: Protocol::Sftp,
            host: String::new(),
            port: 0,
            username: String::new(),
            password: String::new(),
            key_path: String::new(),
            timeout: 30,
            keepalive: 60,
            passive_mode: true,
            ftp_explicit_ssl: false,
            host_key_policy: HostKeyPolicy::AutoAdd,
        }
    }
}

impl ConnectionInfo {
    /// The port to dial: the explicit one, else the protocol default.
    pub fn effective_port(&self) -> u16 {
        if self.port > 0 {
            return self.port;
        }
        if self.protocol == Protocol::Ftp && self.ftp_explicit_ssl {
            return 21;
        }
        self.protocol.default_port(self.ftp_explicit_ssl)
    }

    /// `host:port` as used in log lines and error messages.
    pub fn endpoint(&self) -> String {
        format!("{}:{}", self.host, self.effective_port())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::NaiveDate;

    #[test]
    fn protocol_names_round_trip() {
        for name in ["ftp", "ftps", "sftp", "scp", "webdav"] {
            let protocol: Protocol = name.parse().unwrap();
            assert_eq!(protocol.as_str(), name);
        }
    }

    #[test]
    fn protocol_parsing_is_case_and_space_insensitive() {
        assert_eq!("  SFTP ".parse::<Protocol>().unwrap(), Protocol::Sftp);
        assert!("gopher".parse::<Protocol>().is_err());
    }

    #[test]
    fn default_ports_match_each_protocol() {
        assert_eq!(Protocol::Ftp.default_port(false), 21);
        assert_eq!(Protocol::Ftps.default_port(false), 990);
        assert_eq!(Protocol::Sftp.default_port(false), 22);
        assert_eq!(Protocol::Webdav.default_port(false), 443);
    }

    #[test]
    fn an_explicit_port_wins_over_the_protocol_default() {
        let info = ConnectionInfo {
            protocol: Protocol::Sftp,
            port: 2222,
            ..Default::default()
        };
        assert_eq!(info.effective_port(), 2222);
    }

    #[test]
    fn ftp_with_explicit_ssl_stays_on_the_plain_ftp_port() {
        // AUTH SSL upgrades an ordinary control connection, so it does not
        // move to the implicit-FTPS port.
        let info = ConnectionInfo {
            protocol: Protocol::Ftp,
            ftp_explicit_ssl: true,
            ..Default::default()
        };
        assert_eq!(info.effective_port(), 21);
    }

    #[test]
    fn the_endpoint_string_includes_the_resolved_port() {
        let info = ConnectionInfo {
            host: "example.com".into(),
            protocol: Protocol::Sftp,
            ..Default::default()
        };
        assert_eq!(info.endpoint(), "example.com:22");
    }

    #[test]
    fn host_key_settings_map_onto_policies() {
        assert_eq!(HostKeyPolicy::from_setting("always"), HostKeyPolicy::Strict);
        assert_eq!(HostKeyPolicy::from_setting("ask"), HostKeyPolicy::Prompt);
        assert_eq!(HostKeyPolicy::from_setting("never"), HostKeyPolicy::AutoAdd);
        assert_eq!(
            HostKeyPolicy::from_setting("nonsense"),
            HostKeyPolicy::AutoAdd
        );
    }

    #[test]
    fn an_unrecognised_host_key_answer_is_treated_as_a_rejection() {
        assert_eq!(HostKeyDecision::from_str_lossy(""), HostKeyDecision::Reject);
        assert_eq!(
            HostKeyDecision::from_str_lossy("maybe"),
            HostKeyDecision::Reject
        );
        assert_eq!(
            HostKeyDecision::from_str_lossy("accept_permanent"),
            HostKeyDecision::AcceptPermanent
        );
    }

    #[test]
    fn directories_display_dir_instead_of_a_byte_count() {
        assert_eq!(RemoteFile::dir("docs", "/docs").display_size(), "<DIR>");
    }

    #[test]
    fn sizes_scale_through_the_binary_units() {
        assert_eq!(RemoteFile::file("a", "/a", 0).display_size(), "0 B");
        assert_eq!(RemoteFile::file("a", "/a", 1023).display_size(), "1023 B");
        assert_eq!(RemoteFile::file("a", "/a", 1024).display_size(), "1.0 KB");
        assert_eq!(RemoteFile::file("a", "/a", 1536).display_size(), "1.5 KB");
        assert_eq!(
            RemoteFile::file("a", "/a", 1024 * 1024).display_size(),
            "1.0 MB"
        );
        assert_eq!(
            RemoteFile::file("a", "/a", 1024 * 1024 * 1024).display_size(),
            "1.0 GB"
        );
    }

    #[test]
    fn a_missing_timestamp_renders_as_an_empty_string() {
        assert_eq!(RemoteFile::file("a", "/a", 1).display_modified(), "");
    }

    #[test]
    fn timestamps_render_in_sortable_form() {
        let mut file = RemoteFile::file("a", "/a", 1);
        file.modified = Some(
            NaiveDate::from_ymd_opt(2026, 3, 4)
                .unwrap()
                .and_hms_opt(9, 5, 0)
                .unwrap(),
        );
        assert_eq!(file.display_modified(), "2026-03-04 09:05");
    }

    #[test]
    fn the_type_column_uses_the_extension() {
        assert_eq!(RemoteFile::dir("docs", "/docs").display_type(), "Folder");
        assert_eq!(
            RemoteFile::file("notes.txt", "/notes.txt", 1).display_type(),
            "TXT file"
        );
        assert_eq!(
            RemoteFile::file("README", "/README", 1).display_type(),
            "File"
        );
        // A leading dot is a hidden file, not an extension.
        assert_eq!(
            RemoteFile::file(".bashrc", "/.bashrc", 1).display_type(),
            "File"
        );
    }

    #[test]
    fn dotfiles_are_hidden() {
        assert!(RemoteFile::file(".ssh", "/.ssh", 0).is_hidden());
        assert!(!RemoteFile::file("ssh", "/ssh", 0).is_hidden());
    }
}
