//! SSH agent detection.
//!
//! Used to decide whether agent authentication is worth attempting and to
//! explain, when authentication fails, whether an agent was even reachable.

use std::path::Path;

/// Where an SSH agent was found.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum AgentSource {
    /// A Unix domain socket named by `SSH_AUTH_SOCK`.
    AuthSock(String),
    /// The Windows OpenSSH agent's named pipe.
    WindowsOpenSsh,
    /// PuTTY's Pageant.
    Pageant,
}

/// The Windows OpenSSH agent pipe.
pub const WINDOWS_OPENSSH_PIPE: &str = r"\\.\pipe\openssh-ssh-agent";

/// Find an SSH agent, if one is running.
///
/// `SSH_AUTH_SOCK` is checked first because it works on every platform,
/// including Windows under WSL and with Git Bash.
pub fn detect_agent() -> Option<AgentSource> {
    if let Some(source) = detect_auth_sock(std::env::var("SSH_AUTH_SOCK").ok().as_deref()) {
        return Some(source);
    }
    #[cfg(windows)]
    {
        if Path::new(WINDOWS_OPENSSH_PIPE).exists() {
            return Some(AgentSource::WindowsOpenSsh);
        }
    }
    None
}

/// Resolve an `SSH_AUTH_SOCK` value into an agent source.
///
/// Split out from [`detect_agent`] so the "set but stale" case is testable
/// without touching the process environment.
pub fn detect_auth_sock(value: Option<&str>) -> Option<AgentSource> {
    let value = value?.trim();
    if value.is_empty() {
        return None;
    }
    // A leftover variable pointing at a socket from a dead session is worse
    // than none at all: it makes agent auth fail with a confusing error.
    if !Path::new(value).exists() {
        log::debug!("SSH_AUTH_SOCK is set to {value} but that path does not exist");
        return None;
    }
    Some(AgentSource::AuthSock(value.to_string()))
}

/// Whether any SSH agent is available.
pub fn is_agent_available() -> bool {
    detect_agent().is_some()
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn an_unset_auth_sock_yields_no_agent() {
        assert_eq!(detect_auth_sock(None), None);
    }

    #[test]
    fn an_empty_auth_sock_yields_no_agent() {
        assert_eq!(detect_auth_sock(Some("")), None);
        assert_eq!(detect_auth_sock(Some("   ")), None);
    }

    #[test]
    fn an_auth_sock_pointing_at_nothing_yields_no_agent() {
        // A stale variable from a dead login session must not be reported as a
        // working agent.
        assert_eq!(
            detect_auth_sock(Some("/tmp/definitely-not-a-socket-12345")),
            None
        );
    }

    #[test]
    fn an_existing_auth_sock_path_is_reported() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("agent.sock");
        std::fs::write(&path, b"").unwrap();
        let value = path.to_string_lossy().into_owned();
        assert_eq!(
            detect_auth_sock(Some(&value)),
            Some(AgentSource::AuthSock(value))
        );
    }

    #[test]
    fn detection_never_panics() {
        // Whatever the machine's state, this must return rather than fail.
        let _ = is_agent_available();
    }
}
