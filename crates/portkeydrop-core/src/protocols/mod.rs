//! Protocol abstraction for file transfer clients.
//!
//! Every protocol implements [`TransferClient`], so the UI and the transfer
//! engine never branch on which protocol is in use. Concrete clients live in
//! the sibling modules and are built through [`create_client`].

use std::io::{Read, Write};

pub mod model;
pub mod path;

mod ftp;
pub mod sftp;
mod webdav;

pub use ftp::FtpClient;
pub use model::{
    ConnectionInfo, HostKeyDecision, HostKeyPolicy, Protocol, RemoteFile, UnknownProtocol,
    SUPPORTED_PROTOCOL_VALUES,
};
pub use sftp::{AgentAuthNotice, HostKeyPrompt, SftpClient};
pub use webdav::WebdavClient;

/// Errors any protocol client can raise.
///
/// Deliberately protocol-independent: callers show these to the user and
/// branch on the variant, never on a protocol-specific code.
#[derive(Debug, thiserror::Error)]
pub enum ProtocolError {
    /// An operation was attempted before a successful connect.
    #[error("not connected")]
    NotConnected,
    /// The connection or authentication attempt failed.
    ///
    /// The message is user-facing and already explains what to try next.
    #[error("{0}")]
    Connection(String),
    /// The server refused access to the path.
    #[error("Permission denied: {0}")]
    PermissionDenied(String),
    /// The path does not exist.
    #[error("Not found: {0}")]
    NotFound(String),
    /// A directory operation targeted something that is not a directory.
    #[error("Not a directory: {0}")]
    NotADirectory(String),
    /// The destination already exists and overwriting was not requested.
    #[error("Destination already exists: {0}")]
    AlreadyExists(String),
    /// The user cancelled an in-flight transfer.
    #[error("Transfer cancelled")]
    Cancelled,
    /// A post-operation check did not see the expected result on the server.
    #[error("{0}")]
    Verification(String),
    /// The protocol cannot do what was asked (for example, WebDAV resume).
    #[error("{0}")]
    Unsupported(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error("{0}")]
    Other(String),
}

impl ProtocolError {
    /// Wrap any error as a connection failure with a user-facing prefix.
    pub fn connection(protocol: Protocol, detail: impl std::fmt::Display) -> Self {
        let label = match protocol {
            Protocol::Sftp => "SFTP",
            Protocol::Ftp => "FTP",
            Protocol::Ftps => "FTPS",
            Protocol::Scp => "SCP",
            Protocol::Webdav => "WebDAV",
        };
        ProtocolError::Connection(format!("{label} connection failed: {detail}"))
    }

    /// Whether this error means the transfer was deliberately stopped.
    pub fn is_cancelled(&self) -> bool {
        matches!(self, ProtocolError::Cancelled)
    }
}

/// Convenience alias for protocol results.
pub type Result<T> = std::result::Result<T, ProtocolError>;

/// Progress reporter for a transfer.
///
/// Called with `(bytes transferred so far, total bytes)`. Returning
/// [`ProtocolError::Cancelled`] stops the transfer; the client propagates the
/// error without treating it as a failure.
///
/// For a resumed download the counts are relative to the resumed portion: they
/// start at 0, not at the resume offset.
pub type ProgressFn<'a> = &'a mut dyn FnMut(u64, u64) -> Result<()>;

/// A file transfer protocol client.
///
/// Implementations are synchronous and single-threaded; the transfer engine
/// runs them on worker threads.
pub trait TransferClient: Send {
    /// Which protocol this client speaks.
    fn protocol(&self) -> Protocol;

    /// Whether a session is currently established.
    fn is_connected(&self) -> bool;

    /// The current remote working directory.
    fn cwd(&self) -> &str;

    /// Open the session. Fails with [`ProtocolError::Connection`].
    fn connect(&mut self) -> Result<()>;

    /// Close the session. Always succeeds; errors are logged, not returned.
    fn disconnect(&mut self);

    /// List a directory. `"."` means the current working directory.
    fn list_dir(&mut self, path: &str) -> Result<Vec<RemoteFile>>;

    /// Change directory, returning the new absolute path.
    fn chdir(&mut self, path: &str) -> Result<String>;

    /// Download `remote_path` into `sink`.
    ///
    /// When `offset` is greater than zero the first `offset` bytes are skipped
    /// and writing begins from that point; the caller is responsible for having
    /// positioned `sink` accordingly.
    fn download(
        &mut self,
        remote_path: &str,
        sink: &mut dyn Write,
        progress: Option<ProgressFn<'_>>,
        offset: u64,
    ) -> Result<()>;

    /// Upload `total_bytes` from `source` to `remote_path`.
    ///
    /// Implementations verify the resulting remote size and raise
    /// [`ProtocolError::Verification`] on a mismatch, so a silently truncated
    /// upload is reported rather than shown as success.
    fn upload(
        &mut self,
        source: &mut dyn Read,
        total_bytes: u64,
        remote_path: &str,
        progress: Option<ProgressFn<'_>>,
    ) -> Result<()>;

    /// Delete a remote file.
    fn delete(&mut self, path: &str) -> Result<()>;

    /// Remove a remote directory.
    fn rmdir(&mut self, path: &str) -> Result<()>;

    /// Create a remote directory.
    fn mkdir(&mut self, path: &str) -> Result<()>;

    /// Rename or move a remote entry.
    fn rename(&mut self, old_path: &str, new_path: &str) -> Result<()>;

    /// Fetch metadata for a single remote path.
    fn stat(&mut self, path: &str) -> Result<RemoteFile>;

    /// Move to the parent of the current directory.
    fn parent_dir(&mut self) -> Result<String> {
        let parent = path::parent(self.cwd());
        self.chdir(&parent)
    }

    /// The real path of `path`, following directory symlinks.
    ///
    /// Recursive walks use this as an identity so a symlink or listing that
    /// points back at a directory already seen is not listed again. Protocols
    /// without a realpath operation return the normalised path.
    fn canonicalize(&mut self, path: &str) -> Result<String> {
        let _ = self;
        Ok(path::normalize(path))
    }
}

/// Build the client for a connection.
///
/// FTP with explicit SSL is an FTP client that upgrades via `AUTH SSL`, so it
/// is selected here rather than by a separate protocol value.
pub fn create_client(
    info: ConnectionInfo,
    host_key_prompt: Option<HostKeyPrompt>,
    agent_notice: Option<AgentAuthNotice>,
) -> Result<Box<dyn TransferClient>> {
    match info.protocol {
        Protocol::Sftp => Ok(Box::new(SftpClient::with_hooks(
            info,
            host_key_prompt,
            agent_notice,
        ))),
        Protocol::Ftp | Protocol::Ftps => Ok(Box::new(FtpClient::new(info))),
        Protocol::Webdav => Ok(Box::new(WebdavClient::new(info))),
        Protocol::Scp => Err(ProtocolError::Unsupported(
            "Protocol scp is not yet supported".to_string(),
        )),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn scp_is_reported_as_not_yet_supported() {
        let info = ConnectionInfo {
            protocol: Protocol::Scp,
            ..Default::default()
        };
        let Err(error) = create_client(info, None, None) else {
            panic!("scp should not build a client");
        };
        assert!(matches!(error, ProtocolError::Unsupported(_)));
        assert!(error.to_string().contains("scp"));
    }

    #[test]
    fn each_supported_protocol_builds_a_client() {
        for name in SUPPORTED_PROTOCOL_VALUES {
            let info = ConnectionInfo {
                protocol: name.parse().unwrap(),
                host: "example.com".into(),
                ..Default::default()
            };
            let client = create_client(info, None, None).expect("client for {name}");
            // A freshly built client has not connected yet.
            assert!(!client.is_connected());
        }
    }

    #[test]
    fn ftp_and_ftps_share_one_client_implementation() {
        for protocol in [Protocol::Ftp, Protocol::Ftps] {
            let info = ConnectionInfo {
                protocol,
                ..Default::default()
            };
            let client = create_client(info, None, None).unwrap();
            assert_eq!(client.protocol(), protocol);
        }
    }

    #[test]
    fn connection_errors_name_the_protocol() {
        let error = ProtocolError::connection(Protocol::Sftp, "host unreachable");
        assert_eq!(
            error.to_string(),
            "SFTP connection failed: host unreachable"
        );
    }

    #[test]
    fn cancellation_is_distinguishable_from_other_failures() {
        assert!(ProtocolError::Cancelled.is_cancelled());
        assert!(!ProtocolError::NotConnected.is_cancelled());
    }
}
