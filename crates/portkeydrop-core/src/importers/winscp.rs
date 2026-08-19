//! WinSCP profile importer, from `WinSCP.ini` or the Windows registry.
//!
//! WinSCP's stored passwords are obfuscated, not encrypted: the algorithm is
//! published in its own `Security.cpp`. Recovering them is what makes an import
//! useful, but it is worth being clear that it offers no security — a WinSCP
//! password on disk is readable by anything that can read the file.
//!
//! Passwords protected by a WinSCP master password are *not* recoverable and
//! are skipped, leaving the field empty for the user to fill in.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use super::{ImportError, ImportedSite};

/// XOR constant from WinSCP's `Security.cpp`.
const MAGIC: u8 = 0xA3;
const PWALG_SIMPLE_FLAG: u8 = 0xFF;
const PWALG_SIMPLE_INTERNAL: u8 = 0x00;
const PWALG_SIMPLE_EXTERNAL: u8 = 0x01;
const PWALG_SIMPLE_INTERNAL2: u8 = 0x02;

/// Registry key holding WinSCP sessions.
pub const REGISTRY_SESSIONS_KEY: &str = r"Software\Martin Prikryl\WinSCP 2\Sessions";

/// WinSCP's numeric protocol values.
fn map_numeric_protocol(value: &str) -> Option<&'static str> {
    match value.trim() {
        "0" => Some("sftp"),
        "1" => Some("scp"),
        "5" => Some("ftp"),
        "6" => Some("ftps"),
        _ => None,
    }
}

/// The default `WinSCP.ini` location.
pub fn detect_ini_path() -> PathBuf {
    if let Ok(appdata) = std::env::var("APPDATA") {
        if !appdata.is_empty() {
            return PathBuf::from(appdata).join("WinSCP.ini");
        }
    }
    crate::portable::home_dir().join("WinSCP.ini")
}

/// Whether WinSCP sessions exist in this user's registry.
pub fn registry_sessions_available() -> bool {
    #[cfg(windows)]
    {
        registry::sessions_key_exists()
    }
    #[cfg(not(windows))]
    {
        false
    }
}

/// Parse an exported `WinSCP.ini`.
pub fn parse_ini_file(path: &Path) -> Result<Vec<ImportedSite>, ImportError> {
    let bytes = std::fs::read(path).map_err(|source| ImportError::Io {
        path: path.to_path_buf(),
        source,
    })?;
    Ok(parse_ini_str(&decode_ini_bytes(&bytes)))
}

/// Decode INI bytes, honouring the BOM WinSCP writes.
///
/// WinSCP writes UTF-16 on some systems and the ANSI code page on others, so
/// the encoding is detected rather than assumed; guessing wrong turns every
/// host name into mojibake.
pub fn decode_ini_bytes(bytes: &[u8]) -> String {
    if bytes.starts_with(&[0xFF, 0xFE]) {
        let (text, _, _) = encoding_rs::UTF_16LE.decode(&bytes[2..]);
        return text.into_owned();
    }
    if bytes.starts_with(&[0xFE, 0xFF]) {
        let (text, _, _) = encoding_rs::UTF_16BE.decode(&bytes[2..]);
        return text.into_owned();
    }
    if bytes.starts_with(&[0xEF, 0xBB, 0xBF]) {
        return String::from_utf8_lossy(&bytes[3..]).into_owned();
    }
    match std::str::from_utf8(bytes) {
        Ok(text) => text.to_string(),
        Err(_) => {
            let (text, _, _) = encoding_rs::WINDOWS_1252.decode(bytes);
            text.into_owned()
        }
    }
}

/// Parse INI text.
pub fn parse_ini_str(text: &str) -> Vec<ImportedSite> {
    let mut sites = Vec::new();
    let mut section: Option<String> = None;
    let mut values: BTreeMap<String, String> = BTreeMap::new();

    let mut flush = |section: &Option<String>, values: &mut BTreeMap<String, String>| {
        if let Some(name) = section.as_ref().and_then(|s| s.strip_prefix("Sessions\\")) {
            if let Some(site) = site_from_values(values, name) {
                sites.push(site);
            }
        }
        values.clear();
    };

    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with(';') || line.starts_with('#') {
            continue;
        }
        if let Some(name) = line
            .strip_prefix('[')
            .and_then(|rest| rest.strip_suffix(']'))
        {
            flush(&section, &mut values);
            section = Some(name.trim().to_string());
            continue;
        }
        if let Some((key, value)) = line.split_once('=') {
            values.insert(key.trim().to_string(), value.trim().to_string());
        }
    }
    flush(&section, &mut values);
    sites
}

/// Read WinSCP sessions from the Windows registry.
pub fn parse_registry_sessions() -> Vec<ImportedSite> {
    #[cfg(windows)]
    {
        registry::read_sessions()
    }
    #[cfg(not(windows))]
    {
        Vec::new()
    }
}

/// Build a profile from one session's key/value pairs.
pub fn site_from_values(values: &BTreeMap<String, String>, raw_name: &str) -> Option<ImportedSite> {
    let get = |key: &str| values.get(key).map(String::as_str).unwrap_or("").trim();

    let host = decode_value(get("HostName"));
    if host.is_empty() {
        return None;
    }

    let port = get("PortNumber").parse::<u16>().unwrap_or(0);
    let mut protocol = detect_protocol(values);
    // SCP is not implemented; those sessions are still worth importing, and
    // SFTP is the same server over the same transport.
    if protocol == "scp" {
        protocol = "sftp";
    }
    // WinSCP records explicit TLS as FTPS on a non-implicit port.
    let ftp_explicit_ssl = protocol == "ftps" && port != 990;
    if ftp_explicit_ssl {
        protocol = "ftp";
    }

    let username = get("UserName").to_string();
    let initial_dir = {
        let dir = decode_value(get("RemoteDirectory"));
        if dir.is_empty() {
            "/".to_string()
        } else {
            dir
        }
    };

    Some(ImportedSite {
        name: decode_name(raw_name),
        protocol: protocol.to_string(),
        host: host.clone(),
        port,
        username: username.clone(),
        password: decrypt_password(get("Password"), &username, &host).unwrap_or_default(),
        key_path: decode_value(get("PublicKeyFile")),
        ftp_explicit_ssl,
        initial_dir,
        notes: String::new(),
    })
}

/// Work out the protocol from whichever fields the session carries.
fn detect_protocol(values: &BTreeMap<String, String>) -> &'static str {
    let get = |key: &str| values.get(key).map(String::as_str).unwrap_or("").trim();

    if let Some(protocol) = map_numeric_protocol(get("FSProtocol")) {
        return protocol;
    }
    match get("FileProtocol").to_ascii_lowercase().as_str() {
        "ftp" => return "ftp",
        "ftps" => return "ftps",
        "sftp" => return "sftp",
        "scp" => return "scp",
        _ => {}
    }
    if matches!(get("Ftps"), "1" | "true" | "True") {
        return "ftps";
    }
    "sftp"
}

/// Percent-decode a stored value.
pub fn decode_value(value: &str) -> String {
    if value.is_empty() {
        return String::new();
    }
    percent_encoding::percent_decode_str(value)
        .decode_utf8_lossy()
        .into_owned()
}

/// Decode a session name, which additionally escapes backslashes.
pub fn decode_name(raw_name: &str) -> String {
    decode_value(raw_name).replace("%5C", "\\")
}

/// Why a stored password could not be recovered.
#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum PasswordError {
    #[error("the stored value is not an even-length hex string")]
    NotHex,
    #[error("the stored value ended unexpectedly")]
    Truncated,
    #[error("this password is protected by a WinSCP master password")]
    MasterPassword,
    #[error("unsupported WinSCP password format (version {0})")]
    UnsupportedVersion(u8),
    #[error("the decoded value does not belong to this account")]
    KeyMismatch,
    #[error("the decoded value is not valid text")]
    NotText,
}

/// Recover a stored WinSCP password.
///
/// The obfuscation mixes in the user name and host, so both must match the
/// session the value came from; a mismatch is reported rather than returning
/// nonsense.
pub fn decrypt_password(
    encrypted: &str,
    username: &str,
    hostname: &str,
) -> Result<String, PasswordError> {
    if encrypted.is_empty() {
        return Ok(String::new());
    }
    if encrypted.len() % 2 != 0 || !encrypted.chars().all(|c| c.is_ascii_hexdigit()) {
        return Err(PasswordError::NotHex);
    }

    let mut bytes: std::collections::VecDeque<u8> = (0..encrypted.len())
        .step_by(2)
        .map(|index| u8::from_str_radix(&encrypted[index..index + 2], 16).unwrap_or(0))
        .collect();

    let next = move |queue: &mut std::collections::VecDeque<u8>| -> Result<u8, PasswordError> {
        let byte = queue.pop_front().ok_or(PasswordError::Truncated)?;
        Ok(!(byte ^ MAGIC))
    };

    let flag = next(&mut bytes)?;
    let length = if flag == PWALG_SIMPLE_FLAG {
        let version = next(&mut bytes)?;
        match version {
            PWALG_SIMPLE_INTERNAL => usize::from(next(&mut bytes)?),
            PWALG_SIMPLE_INTERNAL2 => {
                let high = usize::from(next(&mut bytes)?);
                let low = usize::from(next(&mut bytes)?);
                (high << 8) + low
            }
            PWALG_SIMPLE_EXTERNAL => return Err(PasswordError::MasterPassword),
            other => return Err(PasswordError::UnsupportedVersion(other)),
        }
    } else {
        usize::from(flag)
    };

    // A random-length run of padding precedes the payload.
    let shift = next(&mut bytes)?;
    for _ in 0..shift {
        next(&mut bytes)?;
    }

    let mut payload = Vec::with_capacity(length);
    for _ in 0..length {
        payload.push(next(&mut bytes)?);
    }

    if flag == PWALG_SIMPLE_FLAG {
        // Newer values prefix the payload with username+hostname; that prefix
        // is what ties the value to its session.
        let key = format!("{username}{hostname}");
        let key = key.as_bytes();
        if !payload.starts_with(key) {
            return Err(PasswordError::KeyMismatch);
        }
        payload.drain(..key.len());
    }

    String::from_utf8(payload).map_err(|_| PasswordError::NotText)
}

#[cfg(windows)]
mod registry {
    //! Reading WinSCP sessions from `HKEY_CURRENT_USER`.

    use std::collections::BTreeMap;

    use windows_sys::Win32::Foundation::{ERROR_SUCCESS, HANDLE};
    use windows_sys::Win32::System::Registry::{
        RegCloseKey, RegEnumKeyExW, RegEnumValueW, RegOpenKeyExW, HKEY, HKEY_CURRENT_USER,
        KEY_READ, REG_DWORD, REG_SZ,
    };

    use super::{site_from_values, ImportedSite, REGISTRY_SESSIONS_KEY};

    /// Encode a Rust string as a NUL-terminated UTF-16 buffer.
    fn wide(value: &str) -> Vec<u16> {
        value.encode_utf16().chain(std::iter::once(0)).collect()
    }

    /// Decode a UTF-16 buffer up to its first NUL.
    fn from_wide(buffer: &[u16]) -> String {
        let end = buffer
            .iter()
            .position(|unit| *unit == 0)
            .unwrap_or(buffer.len());
        String::from_utf16_lossy(&buffer[..end])
    }

    /// Open a subkey for reading.
    fn open(parent: HKEY, path: &str) -> Option<HKEY> {
        let mut handle: HKEY = std::ptr::null_mut::<std::ffi::c_void>() as HKEY;
        // SAFETY: `path` is NUL-terminated and `handle` is a valid out-pointer.
        let status =
            unsafe { RegOpenKeyExW(parent, wide(path).as_ptr(), 0, KEY_READ, &mut handle) };
        if status == ERROR_SUCCESS {
            Some(handle)
        } else {
            None
        }
    }

    /// Whether the sessions key exists.
    pub fn sessions_key_exists() -> bool {
        match open(HKEY_CURRENT_USER, REGISTRY_SESSIONS_KEY) {
            Some(handle) => {
                // SAFETY: `handle` came from a successful open.
                unsafe { RegCloseKey(handle) };
                true
            }
            None => false,
        }
    }

    /// Every value in a key, as strings.
    fn read_values(key: HKEY) -> BTreeMap<String, String> {
        let mut values = BTreeMap::new();
        let mut index = 0u32;
        loop {
            let mut name = [0u16; 512];
            let mut name_len = name.len() as u32;
            let mut data = [0u8; 4096];
            let mut data_len = data.len() as u32;
            let mut value_type = 0u32;

            // SAFETY: every buffer is sized by the length passed alongside it.
            let status = unsafe {
                RegEnumValueW(
                    key,
                    index,
                    name.as_mut_ptr(),
                    &mut name_len,
                    std::ptr::null_mut(),
                    &mut value_type,
                    data.as_mut_ptr(),
                    &mut data_len,
                )
            };
            if status != ERROR_SUCCESS {
                break;
            }
            index += 1;

            let name = from_wide(&name[..name_len as usize]);
            let value = match value_type {
                REG_SZ => {
                    let units: Vec<u16> = data[..data_len as usize]
                        .chunks_exact(2)
                        .map(|pair| u16::from_le_bytes([pair[0], pair[1]]))
                        .collect();
                    from_wide(&units)
                }
                REG_DWORD if data_len >= 4 => {
                    u32::from_le_bytes([data[0], data[1], data[2], data[3]]).to_string()
                }
                _ => continue,
            };
            values.insert(name, value);
        }
        values
    }

    /// Read every stored session.
    pub fn read_sessions() -> Vec<ImportedSite> {
        let Some(sessions) = open(HKEY_CURRENT_USER, REGISTRY_SESSIONS_KEY) else {
            return Vec::new();
        };

        let mut sites = Vec::new();
        let mut index = 0u32;
        loop {
            let mut name = [0u16; 512];
            let mut name_len = name.len() as u32;
            // SAFETY: `name` is sized by `name_len`.
            let status = unsafe {
                RegEnumKeyExW(
                    sessions,
                    index,
                    name.as_mut_ptr(),
                    &mut name_len,
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                )
            };
            if status != ERROR_SUCCESS {
                break;
            }
            index += 1;

            let session_name = from_wide(&name[..name_len as usize]);
            if let Some(session) = open(
                sessions,
                &format!("{REGISTRY_SESSIONS_KEY}\\{session_name}"),
            ) {
                let values = read_values(session);
                // SAFETY: `session` came from a successful open.
                unsafe { RegCloseKey(session) };
                if let Some(site) = site_from_values(&values, &session_name) {
                    sites.push(site);
                }
            }
        }
        // SAFETY: `sessions` came from a successful open.
        unsafe { RegCloseKey(sessions) };
        sites
    }

    // `HANDLE` is imported for documentation of the HKEY alias; silence the
    // unused warning without dropping the reference.
    #[allow(dead_code)]
    type _Handle = HANDLE;
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    /// Encode a password the way WinSCP does, so the decoder can be tested
    /// against a known-good value without shipping a real profile.
    fn encode_password(password: &str, username: &str, hostname: &str, shift: u8) -> String {
        let payload: Vec<u8> = format!("{username}{hostname}{password}")
            .as_bytes()
            .to_vec();
        let mut plain: Vec<u8> = vec![
            PWALG_SIMPLE_FLAG,
            PWALG_SIMPLE_INTERNAL,
            payload.len() as u8,
            shift,
        ];
        plain.extend(std::iter::repeat_n(0x5A, shift as usize));
        plain.extend_from_slice(&payload);

        plain
            .iter()
            .map(|byte| format!("{:02X}", (!byte) ^ MAGIC))
            .collect()
    }

    const INI: &str = r#"
[Configuration\Interface]
Theme=Default

[Sessions\Work%20box]
HostName=sftp.example.com
PortNumber=2222
UserName=alice
FSProtocol=0
RemoteDirectory=%2Fhome%2Falice

[Sessions\Legacy FTP]
HostName=ftp.example.com
PortNumber=21
UserName=bob
FSProtocol=5
"#;

    #[test]
    fn only_session_sections_become_profiles() {
        let sites = parse_ini_str(INI);
        assert_eq!(sites.len(), 2);
    }

    #[test]
    fn session_fields_are_carried_across() {
        let sites = parse_ini_str(INI);
        let work = &sites[0];
        assert_eq!(work.name, "Work box");
        assert_eq!(work.protocol, "sftp");
        assert_eq!(work.host, "sftp.example.com");
        assert_eq!(work.port, 2222);
        assert_eq!(work.username, "alice");
        assert_eq!(work.initial_dir, "/home/alice");
    }

    #[test]
    fn sessions_without_a_host_are_skipped() {
        let sites = parse_ini_str("[Sessions\\Broken]\nUserName=alice\n");
        assert!(sites.is_empty());
    }

    #[test]
    fn scp_sessions_are_imported_as_sftp() {
        // SCP is not implemented, but it is the same server over the same
        // transport, so the profile is still worth keeping.
        let sites = parse_ini_str("[Sessions\\S]\nHostName=h\nFSProtocol=1\n");
        assert_eq!(sites[0].protocol, "sftp");
    }

    #[test]
    fn ftps_on_a_non_implicit_port_becomes_ftp_with_explicit_ssl() {
        let sites = parse_ini_str("[Sessions\\S]\nHostName=h\nFSProtocol=6\nPortNumber=21\n");
        assert_eq!(sites[0].protocol, "ftp");
        assert!(sites[0].ftp_explicit_ssl);
    }

    #[test]
    fn ftps_on_port_990_stays_implicit() {
        let sites = parse_ini_str("[Sessions\\S]\nHostName=h\nFSProtocol=6\nPortNumber=990\n");
        assert_eq!(sites[0].protocol, "ftps");
        assert!(!sites[0].ftp_explicit_ssl);
    }

    #[test]
    fn the_protocol_falls_back_through_the_named_and_flag_fields() {
        let sites = parse_ini_str("[Sessions\\S]\nHostName=h\nFileProtocol=ftp\n");
        assert_eq!(sites[0].protocol, "ftp");

        let sites = parse_ini_str("[Sessions\\S]\nHostName=h\nFtps=1\nPortNumber=990\n");
        assert_eq!(sites[0].protocol, "ftps");

        // Nothing recorded at all: SFTP is the safe default.
        let sites = parse_ini_str("[Sessions\\S]\nHostName=h\n");
        assert_eq!(sites[0].protocol, "sftp");
    }

    #[test]
    fn percent_escapes_in_names_and_paths_are_decoded() {
        assert_eq!(decode_name("Work%20box"), "Work box");
        assert_eq!(decode_name("Group%5CChild"), "Group\\Child");
        assert_eq!(decode_value("%2Fvar%2Fwww"), "/var/www");
    }

    #[test]
    fn a_session_without_a_remote_directory_starts_at_the_root() {
        let sites = parse_ini_str("[Sessions\\S]\nHostName=h\n");
        assert_eq!(sites[0].initial_dir, "/");
    }

    #[test]
    fn an_obfuscated_password_round_trips() {
        let encoded = encode_password("hunter2", "alice", "sftp.example.com", 3);
        assert_eq!(
            decrypt_password(&encoded, "alice", "sftp.example.com").unwrap(),
            "hunter2"
        );
    }

    #[test]
    fn an_empty_password_field_yields_an_empty_password() {
        assert_eq!(decrypt_password("", "alice", "host").unwrap(), "");
    }

    #[test]
    fn a_password_from_a_different_account_is_rejected() {
        // The account is mixed into the value; decoding it against the wrong
        // one must report a mismatch rather than return nonsense.
        let encoded = encode_password("hunter2", "alice", "sftp.example.com", 3);
        assert_eq!(
            decrypt_password(&encoded, "bob", "sftp.example.com"),
            Err(PasswordError::KeyMismatch)
        );
    }

    #[test]
    fn a_master_password_protected_value_is_reported_as_such() {
        // The user needs to be told these cannot be imported, not shown a
        // blank field with no explanation.
        let plain = [PWALG_SIMPLE_FLAG, PWALG_SIMPLE_EXTERNAL, 0x04];
        let encoded: String = plain
            .iter()
            .map(|byte| format!("{:02X}", (!byte) ^ MAGIC))
            .collect();
        assert_eq!(
            decrypt_password(&encoded, "alice", "host"),
            Err(PasswordError::MasterPassword)
        );
    }

    #[test]
    fn a_non_hex_password_value_is_rejected() {
        assert_eq!(
            decrypt_password("zzzz", "a", "h"),
            Err(PasswordError::NotHex)
        );
        assert_eq!(
            decrypt_password("abc", "a", "h"),
            Err(PasswordError::NotHex)
        );
    }

    #[test]
    fn a_truncated_password_value_is_rejected() {
        let plain = [PWALG_SIMPLE_FLAG, PWALG_SIMPLE_INTERNAL, 0x40];
        let encoded: String = plain
            .iter()
            .map(|byte| format!("{:02X}", (!byte) ^ MAGIC))
            .collect();
        assert_eq!(
            decrypt_password(&encoded, "a", "h"),
            Err(PasswordError::Truncated)
        );
    }

    #[test]
    fn an_unrecoverable_password_leaves_the_field_empty_rather_than_failing_the_import() {
        let mut values = BTreeMap::new();
        values.insert("HostName".to_string(), "h".to_string());
        values.insert("Password".to_string(), "zzzz".to_string());
        let site = site_from_values(&values, "S").unwrap();
        assert_eq!(site.password, "");
        assert_eq!(site.host, "h");
    }

    #[test]
    fn utf16_ini_files_are_decoded() {
        let mut bytes = vec![0xFF, 0xFE];
        for unit in "[Sessions\\S]\nHostName=h\n".encode_utf16() {
            bytes.extend_from_slice(&unit.to_le_bytes());
        }
        let text = decode_ini_bytes(&bytes);
        assert!(text.contains("HostName=h"));
        assert_eq!(parse_ini_str(&text).len(), 1);
    }

    #[test]
    fn utf8_bom_files_are_decoded() {
        let mut bytes = vec![0xEF, 0xBB, 0xBF];
        bytes.extend_from_slice(b"[Sessions\\S]\nHostName=h\n");
        assert!(decode_ini_bytes(&bytes).starts_with("[Sessions"));
    }

    #[test]
    fn ansi_files_are_decoded_without_mojibake() {
        // 0xE9 is 'é' in Windows-1252 and invalid UTF-8.
        let bytes = b"[Sessions\\S]\nHostName=caf\xE9.example\n";
        let text = decode_ini_bytes(bytes);
        assert!(text.contains("café.example"));
    }

    #[test]
    fn comments_and_blank_lines_are_ignored() {
        let text = "; a comment\n\n[Sessions\\S]\n# another\nHostName=h\n";
        assert_eq!(parse_ini_str(text).len(), 1);
    }

    #[test]
    fn a_missing_ini_file_is_reported_as_an_io_error() {
        let dir = TempDir::new().unwrap();
        assert!(matches!(
            parse_ini_file(&dir.path().join("nope.ini")),
            Err(ImportError::Io { .. })
        ));
    }

    #[test]
    fn registry_import_is_a_no_op_off_windows() {
        if !cfg!(windows) {
            assert!(!registry_sessions_available());
            assert!(parse_registry_sessions().is_empty());
        }
    }
}
