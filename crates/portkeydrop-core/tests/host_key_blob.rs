//! The blob we compare against `known_hosts` must be the one OpenSSH wrote.
//!
//! `status()` reports a host whose key type matches but whose key data does
//! not as `Changed`, and a changed key is never accepted automatically. So an
//! encoding that differs from OpenSSH by even its framing does not degrade to
//! "ask again" -- it rejects every host already in the file.

use base64::Engine;

/// A real `known_hosts` third field, as OpenSSH writes it.
const ED25519_BLOB: &str = "AAAAC3NzaC1lZDI1NTE5AAAAIAABAgMEBQYHCAkKCwwNDg8QERITFBUWFxgZGhscHR4f";

#[test]
fn a_known_hosts_blob_survives_a_round_trip_through_our_encoder() {
    let decoded = base64::engine::general_purpose::STANDARD
        .decode(ED25519_BLOB)
        .expect("the fixture is valid base64");

    // The path a server key takes at connect time: bytes off the wire, into
    // russh's key type, back out through the encoder the checker uses.
    let key =
        russh::keys::PublicKey::from_bytes(&decoded).expect("a valid ed25519 public key blob");
    let reencoded = base64::engine::general_purpose::STANDARD
        .encode(key.to_bytes().expect("the key re-encodes"));

    assert_eq!(
        reencoded, ED25519_BLOB,
        "our encoding must match what OpenSSH wrote into known_hosts, or every          stored host reads as a changed key and is rejected"
    );
}

#[test]
fn the_algorithm_name_matches_the_known_hosts_key_type_field() {
    let decoded = base64::engine::general_purpose::STANDARD
        .decode(ED25519_BLOB)
        .unwrap();
    let key = russh::keys::PublicKey::from_bytes(&decoded).unwrap();
    assert_eq!(key.algorithm().as_str(), "ssh-ed25519");
}
