//! The whole journey: accept a host key, then connect again.
//!
//! Checking a key against a file is one thing; what a user experiences is
//! accept-then-reconnect. If what `append` writes is not what `status` later
//! looks for, the app asks about the same host forever, which is what "my
//! known hosts get rejected" looks like from the outside.
//!
//! Needs a server; skipped unless `PORTKEYDROP_TEST_SSHD` is set.

use base64::Engine;
use portkeydrop_core::protocols::sftp::known_hosts::{self, HostKeyStatus};

fn server() -> Option<(String, u16)> {
    let address = std::env::var("PORTKEYDROP_TEST_SSHD").ok()?;
    let (host, port) = address.rsplit_once(':')?;
    Some((host.to_string(), port.parse().ok()?))
}

/// The key the server offers, as the client handler sees it.
fn offered(host: &str, port: u16) -> Option<(String, String)> {
    struct Collector(std::sync::Arc<std::sync::Mutex<Option<(String, String)>>>);

    impl russh::client::Handler for Collector {
        type Error = russh::Error;

        async fn check_server_key(
            &mut self,
            key: &russh::keys::PublicKey,
        ) -> Result<bool, Self::Error> {
            *self.0.lock().unwrap() = Some((
                key.algorithm().as_str().to_string(),
                base64::engine::general_purpose::STANDARD
                    .encode(key.to_bytes().unwrap_or_default()),
            ));
            Ok(false)
        }
    }

    let seen = std::sync::Arc::new(std::sync::Mutex::new(None));
    let runtime = tokio::runtime::Runtime::new().ok()?;
    runtime.block_on(async {
        let config = std::sync::Arc::new(russh::client::Config::default());
        let _ = russh::client::connect(config, (host, port), Collector(seen.clone())).await;
    });
    let result = seen.lock().unwrap().clone();
    result
}

#[test]
fn accepting_a_key_means_the_next_connection_does_not_ask_again() {
    let Some((host, port)) = server() else {
        eprintln!("PORTKEYDROP_TEST_SSHD is unset; skipping");
        return;
    };
    let Some((algorithm, blob)) = offered(&host, port) else {
        panic!("the server offered no host key");
    };

    let dir = tempfile::TempDir::new().expect("a temp dir");
    let path = dir.path().join("known_hosts");

    // First connection: nothing recorded, so the user is asked.
    let before = known_hosts::status(&known_hosts::load(&path), &host, port, &algorithm, &blob);
    assert_eq!(
        before,
        HostKeyStatus::Unknown,
        "an empty file must read as unknown, not as a changed key"
    );

    // The user chooses "accept permanently".
    known_hosts::append(&path, &host, port, &algorithm, &blob).expect("the key is recorded");

    // Second connection: the same server, the same code path.
    let after = known_hosts::status(&known_hosts::load(&path), &host, port, &algorithm, &blob);
    assert_eq!(
        after,
        HostKeyStatus::Known,
        "after accepting, the same host must be known; what was written was:\n{}",
        std::fs::read_to_string(&path).unwrap_or_default()
    );
}

#[test]
fn a_key_accepted_on_a_default_port_is_still_known() {
    // The pattern written for port 22 is the bare host name, and the pattern
    // looked for must be the same. A mismatch here would only ever show up on
    // a default-port site, which is most of them.
    let dir = tempfile::TempDir::new().expect("a temp dir");
    let path = dir.path().join("known_hosts");
    let blob = "AAAAC3NzaC1lZDI1NTE5AAAAIAABAgMEBQYHCAkKCwwNDg8QERITFBUWFxgZGhscHR4f";

    known_hosts::append(&path, "example.com", 22, "ssh-ed25519", blob).unwrap();
    let status = known_hosts::status(
        &known_hosts::load(&path),
        "example.com",
        22,
        "ssh-ed25519",
        blob,
    );
    assert_eq!(
        status,
        HostKeyStatus::Known,
        "written: {:?}",
        std::fs::read_to_string(&path)
    );
}

#[test]
fn a_host_recorded_by_openssh_on_a_default_port_is_known() {
    // OpenSSH writes the bare host name for port 22. A file brought over from
    // ~/.ssh/known_hosts, or written by the Python build, looks like this.
    let dir = tempfile::TempDir::new().expect("a temp dir");
    let path = dir.path().join("known_hosts");
    let blob = "AAAAC3NzaC1lZDI1NTE5AAAAIAABAgMEBQYHCAkKCwwNDg8QERITFBUWFxgZGhscHR4f";
    std::fs::write(&path, format!("example.com ssh-ed25519 {blob}\n")).unwrap();

    let status = known_hosts::status(
        &known_hosts::load(&path),
        "example.com",
        22,
        "ssh-ed25519",
        blob,
    );
    assert_eq!(status, HostKeyStatus::Known);
}

const BLOB: &str = "AAAAC3NzaC1lZDI1NTE5AAAAIAABAgMEBQYHCAkKCwwNDg8QERITFBUWFxgZGhscHR4f";
const OTHER: &str = "AAAAC3NzaC1lZDI1NTE5AAAAIB8eHRwbGhkYFxYVFBMSERAPDg0MCwoJCAcGBQQDAgEA";

#[test]
fn appending_to_a_file_with_no_trailing_newline_does_not_corrupt_it() {
    // Anything that wrote the file without a final newline -- an editor, an
    // earlier release, a hand edit -- would otherwise have its last entry
    // glued to the new one, breaking a host that used to work at the very
    // moment the user accepts an unrelated one.
    let dir = tempfile::TempDir::new().unwrap();
    let path = dir.path().join("known_hosts");
    std::fs::write(&path, format!("first.example.com ssh-ed25519 {BLOB}")).unwrap();

    known_hosts::append(&path, "second.example.com", 22, "ssh-ed25519", OTHER).unwrap();

    let contents = std::fs::read_to_string(&path).unwrap();
    let status = known_hosts::status(
        &known_hosts::load(&path),
        "first.example.com",
        22,
        "ssh-ed25519",
        BLOB,
    );
    assert_eq!(
        status,
        HostKeyStatus::Known,
        "accepting one host must not break another; the file became:\n{contents}"
    );
}

#[test]
fn a_file_written_with_a_byte_order_mark_still_matches_its_first_entry() {
    // A file written by a Windows tool can start with a byte order mark,
    // which would otherwise become part of the first entry's host pattern
    // -- so exactly one host, the first, silently stops being recognised.
    let dir = tempfile::TempDir::new().unwrap();
    let path = dir.path().join("known_hosts");
    let bom = "\u{feff}";
    std::fs::write(
        &path,
        format!("{bom}first.example.com ssh-ed25519 {BLOB}\n"),
    )
    .unwrap();

    let status = known_hosts::status(
        &known_hosts::load(&path),
        "first.example.com",
        22,
        "ssh-ed25519",
        BLOB,
    );
    assert_eq!(
        status,
        HostKeyStatus::Known,
        "a leading byte order mark hid the first host"
    );
}

#[test]
fn windows_line_endings_are_read() {
    let dir = tempfile::TempDir::new().unwrap();
    let path = dir.path().join("known_hosts");
    std::fs::write(&path, format!("first.example.com ssh-ed25519 {BLOB}\r\n")).unwrap();

    let status = known_hosts::status(
        &known_hosts::load(&path),
        "first.example.com",
        22,
        "ssh-ed25519",
        BLOB,
    );
    assert_eq!(status, HostKeyStatus::Known);
}
