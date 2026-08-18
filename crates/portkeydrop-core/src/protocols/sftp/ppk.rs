//! PuTTY private key (`.ppk`) reading.
//!
//! PuTTY's format is not OpenSSH's, and users who generated their key with
//! PuTTYgen should not have to re-export it before connecting. This module
//! parses PPK v2 and v3 — encrypted or not — and hands back an
//! [`ssh_key::PrivateKey`] the SSH layer can use directly.
//!
//! The MAC is always verified before the key material is used, so a corrupted
//! or tampered file is reported rather than fed to the crypto layer.

use hmac::{Hmac, Mac};
use russh::keys::ssh_key;
use sha1::Sha1;
use sha2::{Digest, Sha256};
use ssh_key::private::{Ed25519Keypair, Ed25519PrivateKey, KeypairData, RsaKeypair, RsaPrivateKey};
use ssh_key::public::RsaPublicKey;
use ssh_key::{Mpint, PrivateKey};

use base64::Engine;

type HmacSha1 = Hmac<Sha1>;
type HmacSha256 = Hmac<Sha256>;
type Aes256CbcDec = cbc::Decryptor<aes::Aes256>;

/// Things that can go wrong reading a PPK file.
#[derive(Debug, thiserror::Error)]
pub enum PpkError {
    #[error("not a PuTTY private key file")]
    NotPpk,
    #[error("unsupported PPK version {0}")]
    UnsupportedVersion(u32),
    #[error("malformed PPK: {0}")]
    Malformed(String),
    #[error("unsupported PPK key type '{0}'")]
    UnsupportedKeyType(String),
    #[error("unsupported PPK encryption '{0}'")]
    UnsupportedEncryption(String),
    #[error("this key is encrypted; enter its passphrase")]
    PassphraseRequired,
    #[error("the passphrase for this key is incorrect")]
    WrongPassphrase,
    #[error("the key file is corrupted (MAC mismatch)")]
    MacMismatch,
    #[error("could not build a usable key: {0}")]
    KeyConstruction(String),
}

/// A parsed PPK file, before decryption.
#[derive(Debug, Clone)]
pub struct PpkFile {
    /// Format version: 2 or 3.
    pub version: u32,
    /// SSH algorithm name, e.g. `ssh-ed25519`.
    pub key_type: String,
    /// `none` or `aes256-cbc`.
    pub encryption: String,
    pub comment: String,
    /// Public key blob (SSH wire format).
    pub public_blob: Vec<u8>,
    /// Private key blob, still encrypted when `encryption` is not `none`.
    pub private_blob: Vec<u8>,
    /// Hex MAC over the key material.
    pub mac: String,
    /// v3 Argon2 parameters, present only for encrypted v3 files.
    pub argon2: Option<Argon2Params>,
}

/// Argon2 key-derivation parameters from a v3 header.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Argon2Params {
    pub flavour: String,
    pub memory_kib: u32,
    pub passes: u32,
    pub parallelism: u32,
    pub salt: Vec<u8>,
}

impl PpkFile {
    /// Whether the file needs a passphrase.
    #[allow(dead_code)] // Used by diagnostics and tests.
    pub fn is_encrypted(&self) -> bool {
        !self.encryption.eq_ignore_ascii_case("none")
    }
}

/// Whether a byte slice looks like a PPK file.
pub fn is_ppk(data: &[u8]) -> bool {
    data.starts_with(b"PuTTY-User-Key-File-")
}

/// A short human-readable description of the file, for error messages.
///
/// Produced without decrypting anything, so it is safe to include in a
/// failure the user will see.
pub fn describe(data: &[u8]) -> String {
    match parse(data) {
        Ok(file) => format!(
            "PPK v{} ({}, encryption={})",
            file.version, file.key_type, file.encryption
        ),
        Err(_) if is_ppk(data) => "PPK".to_string(),
        Err(_) => "PPK (.ppk)".to_string(),
    }
}

/// Parse the textual structure of a PPK file.
pub fn parse(data: &[u8]) -> Result<PpkFile, PpkError> {
    let text = std::str::from_utf8(data)
        .map_err(|_| PpkError::Malformed("file is not valid UTF-8 text".into()))?;
    let lines: Vec<&str> = text.lines().map(str::trim).collect();
    let first = lines.first().copied().unwrap_or_default();

    let rest = first
        .strip_prefix("PuTTY-User-Key-File-")
        .ok_or(PpkError::NotPpk)?;
    let (version_text, key_type) = rest
        .split_once(':')
        .ok_or_else(|| PpkError::Malformed("missing key type".into()))?;
    let version: u32 = version_text
        .trim()
        .parse()
        .map_err(|_| PpkError::Malformed("invalid version header".into()))?;
    if !(2..=3).contains(&version) {
        return Err(PpkError::UnsupportedVersion(version));
    }
    let key_type = key_type.trim().to_string();
    if key_type.is_empty() {
        return Err(PpkError::Malformed("missing key type".into()));
    }

    // Body fields are `Name: value`, except Public-Lines / Private-Lines which
    // are followed by that many base64 lines.
    let mut fields: std::collections::HashMap<String, String> = std::collections::HashMap::new();
    let mut index = 1;
    while index < lines.len() {
        let line = lines[index];
        let Some((name, value)) = line.split_once(':') else {
            index += 1;
            continue;
        };
        let name = name.trim().to_string();
        let value = value.trim().to_string();

        if name == "Public-Lines" || name == "Private-Lines" {
            let count: usize = value
                .parse()
                .map_err(|_| PpkError::Malformed(format!("invalid {name} count")))?;
            let start = index + 1;
            let end = start
                .checked_add(count)
                .filter(|end| *end <= lines.len())
                .ok_or_else(|| PpkError::Malformed(format!("truncated {name} data")))?;
            fields.insert(name, lines[start..end].concat());
            index = end;
            continue;
        }

        fields.insert(name, value);
        index += 1;
    }

    let encryption = fields
        .get("Encryption")
        .cloned()
        .ok_or_else(|| PpkError::Malformed("missing Encryption field".into()))?;
    let comment = fields.get("Comment").cloned().unwrap_or_default();
    let public_blob = decode_base64(
        fields
            .get("Public-Lines")
            .ok_or_else(|| PpkError::Malformed("missing Public-Lines".into()))?,
    )?;
    let private_blob = decode_base64(
        fields
            .get("Private-Lines")
            .ok_or_else(|| PpkError::Malformed("missing Private-Lines".into()))?,
    )?;
    let mac = fields
        .get("Private-MAC")
        .cloned()
        .ok_or_else(|| PpkError::Malformed("missing Private-MAC field".into()))?;

    let argon2 = parse_argon2(&fields)?;

    Ok(PpkFile {
        version,
        key_type,
        encryption,
        comment,
        public_blob,
        private_blob,
        mac,
        argon2,
    })
}

/// Read the v3 Argon2 header fields, if present.
fn parse_argon2(
    fields: &std::collections::HashMap<String, String>,
) -> Result<Option<Argon2Params>, PpkError> {
    let Some(flavour) = fields.get("Key-Derivation") else {
        return Ok(None);
    };
    let number = |name: &str| -> Result<u32, PpkError> {
        fields
            .get(name)
            .and_then(|value| value.parse().ok())
            .ok_or_else(|| PpkError::Malformed(format!("missing or invalid {name}")))
    };
    let salt = fields
        .get("Argon2-Salt")
        .ok_or_else(|| PpkError::Malformed("missing Argon2-Salt".into()))?;
    Ok(Some(Argon2Params {
        flavour: flavour.clone(),
        memory_kib: number("Argon2-Memory")?,
        passes: number("Argon2-Passes")?,
        parallelism: number("Argon2-Parallelism")?,
        salt: decode_hex(salt)?,
    }))
}

fn decode_base64(text: &str) -> Result<Vec<u8>, PpkError> {
    base64::engine::general_purpose::STANDARD
        .decode(text.trim())
        .map_err(|err| PpkError::Malformed(format!("invalid base64 data: {err}")))
}

fn decode_hex(text: &str) -> Result<Vec<u8>, PpkError> {
    let text = text.trim();
    if text.len() % 2 != 0 {
        return Err(PpkError::Malformed("hex value has an odd length".into()));
    }
    (0..text.len())
        .step_by(2)
        .map(|index| {
            u8::from_str_radix(&text[index..index + 2], 16)
                .map_err(|_| PpkError::Malformed("invalid hex value".into()))
        })
        .collect()
}

/// Reader for the SSH wire format: length-prefixed strings.
pub struct BlobReader<'a> {
    data: &'a [u8],
    offset: usize,
}

impl<'a> BlobReader<'a> {
    pub fn new(data: &'a [u8]) -> Self {
        Self { data, offset: 0 }
    }

    /// Read one length-prefixed byte string.
    pub fn read_string(&mut self) -> Result<&'a [u8], PpkError> {
        if self.offset + 4 > self.data.len() {
            return Err(PpkError::Malformed("truncated blob".into()));
        }
        let length = u32::from_be_bytes([
            self.data[self.offset],
            self.data[self.offset + 1],
            self.data[self.offset + 2],
            self.data[self.offset + 3],
        ]) as usize;
        self.offset += 4;
        if self.offset + length > self.data.len() {
            return Err(PpkError::Malformed("truncated blob".into()));
        }
        let value = &self.data[self.offset..self.offset + length];
        self.offset += length;
        Ok(value)
    }

    /// Bytes not yet consumed.
    #[allow(dead_code)] // Used to detect trailing data in tests.
    pub fn remaining(&self) -> &'a [u8] {
        &self.data[self.offset..]
    }
}

/// Write a length-prefixed byte string in SSH wire format.
pub fn write_string(out: &mut Vec<u8>, value: &[u8]) {
    out.extend_from_slice(&(value.len() as u32).to_be_bytes());
    out.extend_from_slice(value);
}

/// Key material derived from a passphrase.
struct DerivedKeys {
    cipher_key: Vec<u8>,
    iv: Vec<u8>,
    mac_key: Vec<u8>,
}

/// Derive the v2 cipher and MAC keys (SHA-1 based).
fn derive_v2(passphrase: &str) -> DerivedKeys {
    // PuTTY v2: key = SHA1(0x00000000 || pass) || SHA1(0x00000001 || pass),
    // truncated to 32 bytes; IV is zero; MAC key = SHA1("putty-private-key-file-mac-key" || pass).
    let mut cipher_key = Vec::with_capacity(40);
    for sequence in 0u32..2 {
        let mut hasher = Sha1::new();
        hasher.update(sequence.to_be_bytes());
        hasher.update(passphrase.as_bytes());
        cipher_key.extend_from_slice(&hasher.finalize());
    }
    cipher_key.truncate(32);

    let mut mac_hasher = Sha1::new();
    mac_hasher.update(b"putty-private-key-file-mac-key");
    mac_hasher.update(passphrase.as_bytes());
    let mac_key = mac_hasher.finalize().to_vec();

    DerivedKeys {
        cipher_key,
        iv: vec![0u8; 16],
        mac_key,
    }
}

/// Derive the v3 cipher and MAC keys with Argon2.
fn derive_v3(passphrase: &str, params: &Argon2Params) -> Result<DerivedKeys, PpkError> {
    use argon2::{Algorithm, Argon2, Params, Version};

    let algorithm = match params.flavour.as_str() {
        "Argon2i" => Algorithm::Argon2i,
        "Argon2d" => Algorithm::Argon2d,
        "Argon2id" => Algorithm::Argon2id,
        other => {
            return Err(PpkError::UnsupportedEncryption(format!(
                "Argon2 flavour {other}"
            )))
        }
    };
    // 32-byte cipher key + 16-byte IV + 32-byte MAC key, in one derivation.
    const OUTPUT_LEN: usize = 32 + 16 + 32;
    let argon2_params = Params::new(
        params.memory_kib,
        params.passes,
        params.parallelism,
        Some(OUTPUT_LEN),
    )
    .map_err(|err| PpkError::Malformed(format!("invalid Argon2 parameters: {err}")))?;

    let mut output = vec![0u8; OUTPUT_LEN];
    Argon2::new(algorithm, Version::V0x13, argon2_params)
        .hash_password_into(passphrase.as_bytes(), &params.salt, &mut output)
        .map_err(|err| PpkError::Malformed(format!("Argon2 derivation failed: {err}")))?;

    Ok(DerivedKeys {
        cipher_key: output[..32].to_vec(),
        iv: output[32..48].to_vec(),
        mac_key: output[48..].to_vec(),
    })
}

/// The byte sequence the MAC is computed over.
fn mac_payload(file: &PpkFile, private_blob: &[u8]) -> Vec<u8> {
    let mut payload = Vec::new();
    write_string(&mut payload, file.key_type.as_bytes());
    write_string(&mut payload, file.encryption.as_bytes());
    write_string(&mut payload, file.comment.as_bytes());
    write_string(&mut payload, &file.public_blob);
    write_string(&mut payload, private_blob);
    payload
}

/// Verify the file MAC against the decrypted private blob.
///
/// A mismatch on an encrypted file almost always means a wrong passphrase; on
/// an unencrypted one it means corruption. The two are reported differently so
/// the user is told something actionable.
fn verify_mac(file: &PpkFile, private_blob: &[u8], mac_key: &[u8]) -> Result<(), PpkError> {
    let payload = mac_payload(file, private_blob);
    let computed = match file.version {
        2 => {
            let mut mac = HmacSha1::new_from_slice(mac_key)
                .map_err(|err| PpkError::KeyConstruction(err.to_string()))?;
            mac.update(&payload);
            hex(&mac.finalize().into_bytes())
        }
        _ => {
            let mut mac = HmacSha256::new_from_slice(mac_key)
                .map_err(|err| PpkError::KeyConstruction(err.to_string()))?;
            mac.update(&payload);
            hex(&mac.finalize().into_bytes())
        }
    };

    if computed.eq_ignore_ascii_case(file.mac.trim()) {
        return Ok(());
    }
    if file.is_encrypted() {
        Err(PpkError::WrongPassphrase)
    } else {
        Err(PpkError::MacMismatch)
    }
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

/// Decrypt the private blob, returning it in the clear.
fn decrypt_private_blob(file: &PpkFile, passphrase: Option<&str>) -> Result<Vec<u8>, PpkError> {
    if !file.is_encrypted() {
        // An unencrypted v2 file uses an empty MAC key; v3 uses an empty key
        // too, so both verify against b"".
        let keys = DerivedKeys {
            cipher_key: Vec::new(),
            iv: Vec::new(),
            mac_key: Vec::new(),
        };
        verify_mac(file, &file.private_blob, &keys.mac_key)?;
        return Ok(file.private_blob.clone());
    }

    if !file.encryption.eq_ignore_ascii_case("aes256-cbc") {
        return Err(PpkError::UnsupportedEncryption(file.encryption.clone()));
    }
    let passphrase = passphrase
        .filter(|value| !value.is_empty())
        .ok_or(PpkError::PassphraseRequired)?;

    let keys = match file.version {
        2 => derive_v2(passphrase),
        _ => {
            let params = file.argon2.as_ref().ok_or_else(|| {
                PpkError::Malformed("encrypted v3 key without Argon2 header".into())
            })?;
            derive_v3(passphrase, params)?
        }
    };

    if file.private_blob.len() % 16 != 0 {
        return Err(PpkError::Malformed(
            "encrypted blob is not a whole number of blocks".into(),
        ));
    }
    let mut blob = file.private_blob.clone();
    let decryptor = Aes256CbcDec::new_from_slices(&keys.cipher_key, &keys.iv)
        .map_err(|err| PpkError::KeyConstruction(err.to_string()))?;
    // PuTTY pads to the block size without a padding scheme, so decrypt raw
    // blocks and let the blob reader stop at the real end of the key data.
    use aes::cipher::{BlockDecryptMut, KeyIvInit};
    let mut previous = keys.iv.clone();
    for chunk in blob.chunks_mut(16) {
        let ciphertext = chunk.to_vec();
        let mut block = aes::cipher::generic_array::GenericArray::clone_from_slice(chunk);
        let mut decryptor = decryptor.clone();
        decryptor.decrypt_block_mut(&mut block);
        for (index, byte) in block.iter().enumerate() {
            chunk[index] = byte ^ previous[index];
        }
        previous = ciphertext;
    }

    verify_mac(file, &blob, &keys.mac_key)?;
    Ok(blob)
}

/// Read a PPK file and build an SSH private key from it.
pub fn load(data: &[u8], passphrase: Option<&str>) -> Result<PrivateKey, PpkError> {
    let file = parse(data)?;
    let private_blob = decrypt_private_blob(&file, passphrase)?;
    let keypair = build_keypair(&file, &private_blob)?;
    let mut key = PrivateKey::new(keypair, file.comment.clone())
        .map_err(|err| PpkError::KeyConstruction(err.to_string()))?;
    key.set_comment(file.comment);
    Ok(key)
}

/// Turn the public and private blobs into a keypair.
fn build_keypair(file: &PpkFile, private_blob: &[u8]) -> Result<KeypairData, PpkError> {
    match file.key_type.as_str() {
        "ssh-rsa" => build_rsa(file, private_blob),
        "ssh-ed25519" => build_ed25519(file, private_blob),
        other => Err(PpkError::UnsupportedKeyType(other.to_string())),
    }
}

fn build_rsa(file: &PpkFile, private_blob: &[u8]) -> Result<KeypairData, PpkError> {
    let mut public = BlobReader::new(&file.public_blob);
    let algorithm = public.read_string()?;
    if algorithm != b"ssh-rsa" {
        return Err(PpkError::Malformed("public blob is not an RSA key".into()));
    }
    let e = public.read_string()?.to_vec();
    let n = public.read_string()?.to_vec();

    let mut private = BlobReader::new(private_blob);
    let d = private.read_string()?.to_vec();
    let p = private.read_string()?.to_vec();
    let q = private.read_string()?.to_vec();
    let iqmp = private.read_string()?.to_vec();

    // PuTTY writes the CRT coefficient as q^-1 mod p with p and q in the same
    // order OpenSSH expects, so the components carry across unchanged.
    let public_key = RsaPublicKey::new(
        Mpint::from_bytes(&e).map_err(construction)?,
        Mpint::from_bytes(&n).map_err(construction)?,
    )
    .map_err(construction)?;
    let private_key = RsaPrivateKey::new(
        Mpint::from_bytes(&d).map_err(construction)?,
        Mpint::from_bytes(&iqmp).map_err(construction)?,
        Mpint::from_bytes(&p).map_err(construction)?,
        Mpint::from_bytes(&q).map_err(construction)?,
    )
    .map_err(construction)?;
    let keypair = RsaKeypair::new(public_key, private_key).map_err(construction)?;
    Ok(KeypairData::Rsa(keypair))
}

fn build_ed25519(file: &PpkFile, private_blob: &[u8]) -> Result<KeypairData, PpkError> {
    let mut public = BlobReader::new(&file.public_blob);
    let algorithm = public.read_string()?;
    if algorithm != b"ssh-ed25519" {
        return Err(PpkError::Malformed(
            "public blob is not an Ed25519 key".into(),
        ));
    }
    let public_bytes: [u8; 32] = public
        .read_string()?
        .try_into()
        .map_err(|_| PpkError::Malformed("Ed25519 public key is not 32 bytes".into()))?;

    let mut private = BlobReader::new(private_blob);
    let private_bytes: [u8; 32] = private
        .read_string()?
        .try_into()
        .map_err(|_| PpkError::Malformed("Ed25519 private key is not 32 bytes".into()))?;

    Ok(KeypairData::Ed25519(Ed25519Keypair {
        public: ssh_key::public::Ed25519PublicKey(public_bytes),
        private: Ed25519PrivateKey::from_bytes(&private_bytes),
    }))
}

fn construction(err: impl std::fmt::Display) -> PpkError {
    PpkError::KeyConstruction(err.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A minimal well-formed unencrypted v3 Ed25519 PPK, built here so the
    /// tests do not depend on a fixture file.
    fn ed25519_ppk_v3() -> Vec<u8> {
        let public_key = [7u8; 32];
        let private_key = [9u8; 32];

        let mut public_blob = Vec::new();
        write_string(&mut public_blob, b"ssh-ed25519");
        write_string(&mut public_blob, &public_key);

        let mut private_blob = Vec::new();
        write_string(&mut private_blob, &private_key);

        let comment = "test-key";
        let file = PpkFile {
            version: 3,
            key_type: "ssh-ed25519".into(),
            encryption: "none".into(),
            comment: comment.into(),
            public_blob: public_blob.clone(),
            private_blob: private_blob.clone(),
            mac: String::new(),
            argon2: None,
        };
        let mut mac = HmacSha256::new_from_slice(b"").unwrap();
        mac.update(&mac_payload(&file, &private_blob));
        let mac = hex(&mac.finalize().into_bytes());

        let encode = |blob: &[u8]| -> Vec<String> {
            let text = base64::engine::general_purpose::STANDARD.encode(blob);
            text.as_bytes()
                .chunks(64)
                .map(|chunk| String::from_utf8_lossy(chunk).into_owned())
                .collect()
        };
        let public_lines = encode(&public_blob);
        let private_lines = encode(&private_blob);

        let mut out = String::new();
        out.push_str("PuTTY-User-Key-File-3: ssh-ed25519\n");
        out.push_str("Encryption: none\n");
        out.push_str(&format!("Comment: {comment}\n"));
        out.push_str(&format!("Public-Lines: {}\n", public_lines.len()));
        for line in &public_lines {
            out.push_str(line);
            out.push('\n');
        }
        out.push_str(&format!("Private-Lines: {}\n", private_lines.len()));
        for line in &private_lines {
            out.push_str(line);
            out.push('\n');
        }
        out.push_str(&format!("Private-MAC: {mac}\n"));
        out.into_bytes()
    }

    #[test]
    fn ppk_files_are_recognised_by_their_header() {
        assert!(is_ppk(b"PuTTY-User-Key-File-3: ssh-ed25519\n"));
        assert!(!is_ppk(b"-----BEGIN OPENSSH PRIVATE KEY-----\n"));
        assert!(!is_ppk(b""));
    }

    #[test]
    fn a_non_ppk_file_is_rejected() {
        assert!(matches!(
            parse(b"-----BEGIN RSA PRIVATE KEY-----"),
            Err(PpkError::NotPpk)
        ));
    }

    #[test]
    fn an_unsupported_version_is_named_in_the_error() {
        let data = b"PuTTY-User-Key-File-9: ssh-rsa\nEncryption: none\n";
        assert!(matches!(parse(data), Err(PpkError::UnsupportedVersion(9))));
    }

    #[test]
    fn a_v3_header_parses_into_its_fields() {
        let file = parse(&ed25519_ppk_v3()).unwrap();
        assert_eq!(file.version, 3);
        assert_eq!(file.key_type, "ssh-ed25519");
        assert_eq!(file.encryption, "none");
        assert_eq!(file.comment, "test-key");
        assert!(!file.is_encrypted());
        assert!(file.argon2.is_none());
    }

    #[test]
    fn an_unencrypted_v3_ed25519_key_loads() {
        let key = load(&ed25519_ppk_v3(), None).unwrap();
        assert_eq!(key.algorithm().as_str(), "ssh-ed25519");
        assert_eq!(key.comment().to_string(), "test-key");
    }

    #[test]
    fn a_tampered_mac_is_reported_as_corruption_not_a_bad_passphrase() {
        // The file is unencrypted, so a MAC failure cannot be a passphrase
        // problem and must not tell the user to check their passphrase.
        let mut data = String::from_utf8(ed25519_ppk_v3()).unwrap();
        let mac_line_start = data.find("Private-MAC: ").unwrap();
        data.replace_range(
            mac_line_start.."Private-MAC: ".len() + mac_line_start + 4,
            "Private-MAC: dead",
        );
        assert!(matches!(
            load(data.as_bytes(), None),
            Err(PpkError::MacMismatch)
        ));
    }

    #[test]
    fn a_truncated_field_count_is_reported_as_malformed() {
        let data =
            b"PuTTY-User-Key-File-3: ssh-ed25519\nEncryption: none\nComment: x\nPublic-Lines: 99\n";
        assert!(matches!(parse(data), Err(PpkError::Malformed(_))));
    }

    #[test]
    fn a_missing_mac_field_is_reported_as_malformed() {
        let mut data = String::from_utf8(ed25519_ppk_v3()).unwrap();
        let mac_line_start = data.find("Private-MAC: ").unwrap();
        data.truncate(mac_line_start);
        assert!(matches!(
            parse(data.as_bytes()),
            Err(PpkError::Malformed(_))
        ));
    }

    #[test]
    fn editing_the_header_invalidates_the_mac() {
        // The MAC covers the key type, so a header edit is caught as
        // corruption before the key material is looked at. That ordering is
        // deliberate: never parse key bytes that failed authentication.
        let data = String::from_utf8(ed25519_ppk_v3())
            .unwrap()
            .replace("ssh-ed25519", "ssh-dss");
        assert!(matches!(
            load(data.as_bytes(), None),
            Err(PpkError::MacMismatch)
        ));
    }

    #[test]
    fn an_unsupported_key_type_is_named() {
        let mut file = parse(&ed25519_ppk_v3()).unwrap();
        file.key_type = "ssh-dss".into();
        let blob = file.private_blob.clone();
        assert!(matches!(
            build_keypair(&file, &blob),
            Err(PpkError::UnsupportedKeyType(kind)) if kind == "ssh-dss"
        ));
    }

    #[test]
    fn describing_a_file_never_needs_the_passphrase() {
        assert_eq!(
            describe(&ed25519_ppk_v3()),
            "PPK v3 (ssh-ed25519, encryption=none)"
        );
        assert_eq!(describe(b"not a key at all"), "PPK (.ppk)");
    }

    #[test]
    fn blob_strings_round_trip() {
        let mut blob = Vec::new();
        write_string(&mut blob, b"ssh-ed25519");
        write_string(&mut blob, &[1, 2, 3]);

        let mut reader = BlobReader::new(&blob);
        assert_eq!(reader.read_string().unwrap(), b"ssh-ed25519");
        assert_eq!(reader.read_string().unwrap(), &[1, 2, 3]);
        assert!(reader.remaining().is_empty());
    }

    #[test]
    fn a_truncated_blob_is_rejected_rather_than_read_past_the_end() {
        let mut blob = Vec::new();
        blob.extend_from_slice(&100u32.to_be_bytes());
        blob.extend_from_slice(b"short");
        let mut reader = BlobReader::new(&blob);
        assert!(matches!(reader.read_string(), Err(PpkError::Malformed(_))));
    }

    #[test]
    fn hex_values_decode_and_reject_odd_lengths() {
        assert_eq!(decode_hex("0a1b").unwrap(), vec![0x0a, 0x1b]);
        assert!(decode_hex("0a1").is_err());
        assert!(decode_hex("zz").is_err());
    }

    #[test]
    fn v2_key_derivation_produces_the_documented_sizes() {
        let keys = derive_v2("hunter2");
        assert_eq!(keys.cipher_key.len(), 32);
        assert_eq!(keys.iv.len(), 16);
        assert_eq!(keys.mac_key.len(), 20);
    }

    #[test]
    fn an_encrypted_key_without_a_passphrase_says_so() {
        let mut file = parse(&ed25519_ppk_v3()).unwrap();
        file.encryption = "aes256-cbc".into();
        assert!(matches!(
            decrypt_private_blob(&file, None),
            Err(PpkError::PassphraseRequired)
        ));
    }

    #[test]
    fn an_unknown_cipher_is_reported_rather_than_attempted() {
        let mut file = parse(&ed25519_ppk_v3()).unwrap();
        file.encryption = "blowfish-cbc".into();
        assert!(matches!(
            decrypt_private_blob(&file, Some("x")),
            Err(PpkError::UnsupportedEncryption(_))
        ));
    }
}
