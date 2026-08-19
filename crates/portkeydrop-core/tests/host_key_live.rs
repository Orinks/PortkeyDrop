//! Measure the host key check against a real SSH server.
//!
//! The checker compares the algorithm name russh reports against the key type
//! field OpenSSH wrote into `known_hosts`. Those are two different pieces of
//! software naming the same key, and nothing guarantees they agree -- so this
//! asks a real server rather than reasoning about it.
//!
//! Needs a server. Skipped unless `PORTKEYDROP_TEST_SSHD` is set to
//! `host:port`; see `scripts/host-key-harness.sh`.

use base64::Engine;
use portkeydrop_core::protocols::sftp::known_hosts::{self, HostKeyStatus};

/// Connect and report the key exactly as the client handler sees it.
///
/// Mirrors `ClientHandler::check_server_key`: the same accessor for the
/// algorithm and the same encoding for the blob. A measurement of anything
/// else would not be a measurement of the bug.
fn offered_key_with(
    address: &str,
    prefer: Option<russh::keys::Algorithm>,
) -> Vec<(String, String)> {
    struct Collector(std::sync::Arc<std::sync::Mutex<Vec<(String, String)>>>);

    impl russh::client::Handler for Collector {
        type Error = russh::Error;

        async fn check_server_key(
            &mut self,
            key: &russh::keys::PublicKey,
        ) -> Result<bool, Self::Error> {
            let algorithm = key.algorithm().as_str().to_string();
            let blob = base64::engine::general_purpose::STANDARD
                .encode(key.to_bytes().unwrap_or_default());
            self.0.lock().unwrap().push((algorithm, blob));
            // Stop here: the host key is all this is after, and going further
            // would need credentials.
            Ok(false)
        }
    }

    let seen = std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
    let runtime = tokio::runtime::Runtime::new().expect("a tokio runtime");
    runtime.block_on(async {
        let mut config = russh::client::Config::default();
        // Ask for one host key algorithm so each can be measured, rather than
        // whichever the two ends happen to agree on first.
        if let Some(algorithm) = prefer {
            config.preferred.key = std::borrow::Cow::Owned(vec![algorithm]);
        }
        let _ = russh::client::connect(
            std::sync::Arc::new(config),
            address,
            Collector(seen.clone()),
        )
        .await;
    });
    let result = seen.lock().unwrap().clone();
    result
}

fn entry(pattern: &str, key_type: &str, blob: &str) -> Vec<known_hosts::KnownHostEntry> {
    known_hosts::parse(&format!("{pattern} {key_type} {blob}\n"))
}

/// What OpenSSH writes in the key type field for a given signature algorithm.
///
/// It records the key's own type. RSA keys are always `ssh-rsa` there, even
/// when the session negotiated an `rsa-sha2-*` signature.
fn openssh_key_type(algorithm: &str) -> &str {
    if algorithm.starts_with("rsa-sha2") {
        "ssh-rsa"
    } else {
        algorithm
    }
}

#[test]
fn every_host_key_algorithm_matches_what_openssh_recorded() {
    let Ok(address) = std::env::var("PORTKEYDROP_TEST_SSHD") else {
        eprintln!("PORTKEYDROP_TEST_SSHD is unset; skipping");
        return;
    };
    let (host, port) = address.rsplit_once(':').expect("host:port");
    let port: u16 = port.parse().expect("a port number");
    let pattern = if port == 22 {
        host.to_string()
    } else {
        format!("[{host}]:{port}")
    };

    let mut failures = Vec::new();
    for algorithm in [
        russh::keys::Algorithm::Ed25519,
        russh::keys::Algorithm::Rsa {
            hash: Some(russh::keys::HashAlg::Sha512),
        },
        russh::keys::Algorithm::Rsa {
            hash: Some(russh::keys::HashAlg::Sha256),
        },
        russh::keys::Algorithm::Ecdsa {
            curve: russh::keys::EcdsaCurve::NistP256,
        },
    ] {
        let offered = offered_key_with(&address, Some(algorithm.clone()));
        let Some((reported, blob)) = offered.first() else {
            println!("  {algorithm:?}: the server did not offer one");
            continue;
        };
        let recorded = openssh_key_type(reported);
        let entries = entry(&pattern, recorded, blob);
        let status = known_hosts::status(&entries, host, port, reported, blob);
        println!("  requested {algorithm:?}");
        println!("    russh reports : {reported}");
        println!("    openssh writes: {recorded}");
        println!("    status        : {status:?}");
        if status != HostKeyStatus::Known {
            failures.push(format!("{reported} vs {recorded} -> {status:?}"));
        }
    }

    assert!(
        failures.is_empty(),
        "a host OpenSSH already trusts read as something other than Known: {failures:?}"
    );
}

#[test]
fn what_the_client_sees_matches_what_openssh_records() {
    let Ok(address) = std::env::var("PORTKEYDROP_TEST_SSHD") else {
        eprintln!("PORTKEYDROP_TEST_SSHD is unset; skipping the live host key check");
        return;
    };
    let (host, port) = address.rsplit_once(':').expect("host:port");
    let port: u16 = port.parse().expect("a port number");

    let offered = offered_key_with(&address, None);
    assert!(!offered.is_empty(), "the server offered no host key");
    let (algorithm, blob) = &offered[0];
    println!("russh reports algorithm: {algorithm}");

    // The key type OpenSSH writes for an RSA host key is `ssh-rsa`, whatever
    // signature algorithm the session negotiated.
    let openssh_key_type = match algorithm.as_str() {
        alg if alg.starts_with("rsa-sha2") => "ssh-rsa",
        alg => alg,
    };
    println!("openssh would record key type: {openssh_key_type}");

    let pattern = if port == 22 {
        host.to_string()
    } else {
        format!("[{host}]:{port}")
    };

    let as_openssh_wrote_it = entry(&pattern, openssh_key_type, blob);
    let status = known_hosts::status(&as_openssh_wrote_it, host, port, algorithm, blob);

    println!("status against an OpenSSH-written entry: {status:?}");
    assert_eq!(
        status,
        HostKeyStatus::Known,
        "a host OpenSSH already trusts must read as Known; got {status:?} for \
         algorithm {algorithm} against key type {openssh_key_type}"
    );
}

#[test]
fn a_hashed_entry_is_reported_unknown_rather_than_changed() {
    // Debian and Ubuntu ship HashKnownHosts on by default, so a file brought
    // from another machine is often entirely hashed. Unknown means the user
    // is asked; Changed would refuse outright.
    let hashed = entry(
        "|1|F1E2D3C4B5A60718293A4B5C6D7E8F9012345678=|9876543210FEDCBA9876543210FEDCBA98765432=",
        "ssh-ed25519",
        "AAAAC3NzaC1lZDI1NTE5AAAAIAABAgMEBQYHCAkKCwwNDg8QERITFBUWFxgZGhscHR4f",
    );
    let status = known_hosts::status(
        &hashed,
        "example.com",
        22,
        "ssh-ed25519",
        "AAAAC3NzaC1lZDI1NTE5AAAAIAABAgMEBQYHCAkKCwwNDg8QERITFBUWFxgZGhscHR4f",
    );
    assert_eq!(status, HostKeyStatus::Unknown);
}
