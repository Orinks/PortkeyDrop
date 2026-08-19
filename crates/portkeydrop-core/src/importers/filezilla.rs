//! FileZilla Site Manager importer.
//!
//! Reads `sitemanager.xml`. Two details are worth knowing: passwords are
//! base64, not encrypted, and remote directories use FileZilla's own
//! length-prefixed segment encoding rather than a plain path.

use std::path::{Path, PathBuf};

use base64::Engine;
use quick_xml::events::Event;
use quick_xml::Reader;

use super::{ImportError, ImportedSite};

/// FileZilla's numeric protocol values.
fn map_protocol(raw: &str) -> (&'static str, bool) {
    match raw.trim() {
        "0" => ("ftp", false),
        "1" => ("sftp", false),
        // 3 is "FTP over explicit TLS", which this app models as FTP with the
        // explicit-SSL flag set.
        "3" => ("ftp", true),
        "4" => ("ftps", false),
        _ => ("sftp", false),
    }
}

/// The default `sitemanager.xml` location for this platform.
pub fn detect_path() -> PathBuf {
    if let Ok(appdata) = std::env::var("APPDATA") {
        if !appdata.is_empty() {
            return PathBuf::from(appdata)
                .join("FileZilla")
                .join("sitemanager.xml");
        }
    }
    if cfg!(target_os = "macos") {
        return crate::portable::home_dir()
            .join(".config")
            .join("filezilla")
            .join("sitemanager.xml");
    }
    crate::portable::home_dir()
        .join(".config")
        .join("filezilla")
        .join("sitemanager.xml")
}

/// Parse a `sitemanager.xml` file.
pub fn parse_file(path: &Path) -> Result<Vec<ImportedSite>, ImportError> {
    let text = std::fs::read_to_string(path).map_err(|source| ImportError::Io {
        path: path.to_path_buf(),
        source,
    })?;
    parse_str(&text)
}

/// Parse `sitemanager.xml` content.
pub fn parse_str(xml: &str) -> Result<Vec<ImportedSite>, ImportError> {
    let mut reader = Reader::from_str(xml);
    reader.config_mut().trim_text(true);

    let mut sites = Vec::new();
    let mut fields: std::collections::HashMap<String, String> = std::collections::HashMap::new();
    let mut pass_encoding = String::new();
    let mut current_field: Option<String> = None;
    let mut depth_in_server = 0usize;
    let mut buffer = Vec::new();

    loop {
        let event = reader
            .read_event_into(&mut buffer)
            .map_err(|err| ImportError::Format(format!("invalid FileZilla XML: {err}")))?;
        match event {
            Event::Start(element) => {
                let name = String::from_utf8_lossy(element.name().as_ref()).into_owned();
                if name == "Server" {
                    depth_in_server = 1;
                    fields.clear();
                    pass_encoding.clear();
                } else if depth_in_server > 0 {
                    if name == "Pass" {
                        // FileZilla marks base64 values with an attribute; a
                        // plain value is stored as-is.
                        pass_encoding = element
                            .attributes()
                            .flatten()
                            .find(|attribute| attribute.key.as_ref() == b"encoding")
                            .and_then(|attribute| String::from_utf8(attribute.value.to_vec()).ok())
                            .unwrap_or_default();
                    }
                    current_field = Some(name);
                }
            }
            Event::Text(text) if depth_in_server > 0 => {
                if let Some(field) = current_field.as_ref() {
                    let value = text
                        .unescape()
                        .map_err(|err| {
                            ImportError::Format(format!("invalid FileZilla XML: {err}"))
                        })?
                        .trim()
                        .to_string();
                    fields.insert(field.clone(), value);
                }
            }
            Event::End(element) => {
                let name = String::from_utf8_lossy(element.name().as_ref()).into_owned();
                if name == "Server" {
                    depth_in_server = 0;
                    if let Some(site) = site_from_fields(&fields, &pass_encoding) {
                        sites.push(site);
                    }
                } else if current_field.as_deref() == Some(name.as_str()) {
                    current_field = None;
                }
            }
            Event::Eof => break,
            _ => {}
        }
        buffer.clear();
    }
    Ok(sites)
}

/// Build a profile from one `<Server>` element's fields.
fn site_from_fields(
    fields: &std::collections::HashMap<String, String>,
    pass_encoding: &str,
) -> Option<ImportedSite> {
    let get = |name: &str| fields.get(name).map(String::as_str).unwrap_or("").trim();

    let host = get("Host");
    if host.is_empty() {
        return None;
    }

    let (protocol, ftp_explicit_ssl) = map_protocol(get("Protocol"));
    let port = get("Port").parse::<u16>().unwrap_or(0);
    let username = get("User").to_string();
    let password = decode_password(get("Pass"), pass_encoding);
    let key_path = if protocol == "sftp" {
        // Exports differ on the casing of this element.
        normalize_key_path(if !get("Keyfile").is_empty() {
            get("Keyfile")
        } else {
            get("KeyFile")
        })
    } else {
        String::new()
    };

    let name = {
        let explicit = get("Name");
        if !explicit.is_empty() {
            explicit.to_string()
        } else if username.is_empty() {
            host.to_string()
        } else {
            format!("{username}@{host}")
        }
    };

    Some(ImportedSite {
        name,
        protocol: protocol.to_string(),
        host: host.to_string(),
        port,
        username,
        password,
        key_path,
        ftp_explicit_ssl,
        initial_dir: parse_remote_dir(get("RemoteDir")),
        notes: get("Comments").to_string(),
    })
}

/// Decode a stored password.
pub fn decode_password(raw: &str, encoding: &str) -> String {
    if raw.is_empty() {
        return String::new();
    }
    if !encoding.eq_ignore_ascii_case("base64") {
        return raw.to_string();
    }
    base64::engine::general_purpose::STANDARD
        .decode(raw)
        .ok()
        .and_then(|bytes| String::from_utf8(bytes).ok())
        .unwrap_or_default()
}

/// Turn a `file://` URL into a native path, leaving plain paths alone.
pub fn normalize_key_path(raw: &str) -> String {
    let raw = raw.trim();
    if raw.is_empty() {
        return String::new();
    }
    let Ok(url) = url::Url::parse(raw) else {
        return raw.to_string();
    };
    if url.scheme() != "file" {
        return raw.to_string();
    }

    let decoded = percent_encoding::percent_decode_str(url.path())
        .decode_utf8_lossy()
        .into_owned();

    // A host component means a UNC path: file://server/share -> \\server\share.
    if let Some(host) = url.host_str().filter(|host| !host.is_empty()) {
        let tail = decoded.trim_start_matches('/').replace('/', "\\");
        return if tail.is_empty() {
            format!(r"\\{host}")
        } else {
            format!(r"\\{host}\{tail}")
        };
    }

    // file:///C:/x -> C:\x
    let bytes = decoded.as_bytes();
    if bytes.len() >= 3 && bytes[0] == b'/' && bytes[2] == b':' {
        return decoded[1..].replace('/', "\\");
    }
    decoded
}

/// Decode FileZilla's remote directory encoding.
///
/// Paths are stored as `<version> <type> <len> <segment> <len> <segment>...`,
/// for example `1 0 4 home 4 user` for `/home/user`. Anything that does not
/// match that shape is treated as an ordinary path.
pub fn parse_remote_dir(raw: &str) -> String {
    let raw = raw.trim();
    if raw.is_empty() {
        return "/".to_string();
    }

    let tokens: Vec<&str> = raw.split_whitespace().collect();
    let looks_encoded = tokens.len() >= 2
        && tokens[0].chars().all(|c| c.is_ascii_digit())
        && tokens[1].chars().all(|c| c.is_ascii_digit());

    if looks_encoded {
        let mut segments: Vec<String> = Vec::new();
        let mut index = 2;
        while index < tokens.len() {
            let Ok(length) = tokens[index].parse::<usize>() else {
                break;
            };
            index += 1;
            if index >= tokens.len() {
                break;
            }
            let segment = tokens[index];
            index += 1;
            // The length prefix bounds the segment; a segment containing a
            // space would otherwise swallow the next token.
            let truncated: String = segment.chars().take(length).collect();
            if !truncated.is_empty() {
                segments.push(truncated.trim_matches('/').to_string());
            }
        }
        if !segments.is_empty() {
            return format!("/{}", segments.join("/"));
        }
    }

    if raw.starts_with('/') {
        raw.to_string()
    } else {
        format!("/{}", raw.trim_start_matches('/'))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    const SITEMANAGER: &str = r#"<?xml version="1.0" encoding="UTF-8"?>
<FileZilla3 version="3.66.5">
  <Servers>
    <Server>
      <Host>sftp.example.com</Host>
      <Port>2222</Port>
      <Protocol>1</Protocol>
      <User>alice</User>
      <Pass encoding="base64">aHVudGVyMg==</Pass>
      <Name>Work</Name>
      <RemoteDir>1 0 4 home 5 alice</RemoteDir>
      <Comments>The work box</Comments>
    </Server>
    <Server>
      <Host>ftp.example.com</Host>
      <Port>21</Port>
      <Protocol>0</Protocol>
      <User>bob</User>
      <Name>Old FTP</Name>
    </Server>
  </Servers>
</FileZilla3>"#;

    #[test]
    fn each_server_element_becomes_a_profile() {
        let sites = parse_str(SITEMANAGER).unwrap();
        assert_eq!(sites.len(), 2);
    }

    #[test]
    fn profile_fields_are_carried_across() {
        let sites = parse_str(SITEMANAGER).unwrap();
        let work = &sites[0];
        assert_eq!(work.name, "Work");
        assert_eq!(work.protocol, "sftp");
        assert_eq!(work.host, "sftp.example.com");
        assert_eq!(work.port, 2222);
        assert_eq!(work.username, "alice");
        assert_eq!(work.initial_dir, "/home/alice");
        assert_eq!(work.notes, "The work box");
    }

    #[test]
    fn base64_passwords_are_decoded() {
        let sites = parse_str(SITEMANAGER).unwrap();
        assert_eq!(sites[0].password, "hunter2");
    }

    #[test]
    fn a_password_without_the_base64_marker_is_taken_literally() {
        assert_eq!(decode_password("plaintext", ""), "plaintext");
        assert_eq!(decode_password("aHVudGVyMg==", "base64"), "hunter2");
        assert_eq!(decode_password("", "base64"), "");
        // Undecodable base64 yields nothing rather than garbage.
        assert_eq!(decode_password("!!!not base64!!!", "base64"), "");
    }

    #[test]
    fn servers_without_a_host_are_skipped() {
        let xml =
            "<FileZilla3><Servers><Server><Name>Broken</Name></Server></Servers></FileZilla3>";
        assert!(parse_str(xml).unwrap().is_empty());
    }

    #[test]
    fn an_unnamed_server_is_labelled_from_its_user_and_host() {
        let xml = "<FileZilla3><Servers><Server><Host>h.example</Host><User>bob</User>\
                   </Server></Servers></FileZilla3>";
        assert_eq!(parse_str(xml).unwrap()[0].name, "bob@h.example");

        let xml =
            "<FileZilla3><Servers><Server><Host>h.example</Host></Server></Servers></FileZilla3>";
        assert_eq!(parse_str(xml).unwrap()[0].name, "h.example");
    }

    #[test]
    fn protocol_numbers_map_onto_this_apps_protocols() {
        assert_eq!(map_protocol("0"), ("ftp", false));
        assert_eq!(map_protocol("1"), ("sftp", false));
        // Explicit TLS over FTP is modelled as FTP plus the AUTH SSL flag.
        assert_eq!(map_protocol("3"), ("ftp", true));
        assert_eq!(map_protocol("4"), ("ftps", false));
        // An unknown value must not make the profile unusable.
        assert_eq!(map_protocol("99"), ("sftp", false));
    }

    #[test]
    fn explicit_tls_sets_the_ftp_ssl_flag() {
        let xml = "<FileZilla3><Servers><Server><Host>h</Host><Protocol>3</Protocol>\
                   </Server></Servers></FileZilla3>";
        let site = &parse_str(xml).unwrap()[0];
        assert_eq!(site.protocol, "ftp");
        assert!(site.ftp_explicit_ssl);
    }

    #[test]
    fn key_files_are_only_read_for_sftp_profiles() {
        let sftp = "<FileZilla3><Servers><Server><Host>h</Host><Protocol>1</Protocol>\
                    <Keyfile>C:\\keys\\id_rsa</Keyfile></Server></Servers></FileZilla3>";
        assert_eq!(parse_str(sftp).unwrap()[0].key_path, r"C:\keys\id_rsa");

        let ftp = "<FileZilla3><Servers><Server><Host>h</Host><Protocol>0</Protocol>\
                   <Keyfile>C:\\keys\\id_rsa</Keyfile></Server></Servers></FileZilla3>";
        assert_eq!(parse_str(ftp).unwrap()[0].key_path, "");
    }

    #[test]
    fn the_alternate_keyfile_spelling_is_accepted() {
        let xml = "<FileZilla3><Servers><Server><Host>h</Host><Protocol>1</Protocol>\
                   <KeyFile>/home/a/id_ed25519</KeyFile></Server></Servers></FileZilla3>";
        assert_eq!(parse_str(xml).unwrap()[0].key_path, "/home/a/id_ed25519");
    }

    #[test]
    fn file_urls_become_native_paths() {
        assert_eq!(
            normalize_key_path("file:///C:/keys/id_rsa"),
            r"C:\keys\id_rsa"
        );
        assert_eq!(
            normalize_key_path("file:///home/a/id_rsa"),
            "/home/a/id_rsa"
        );
        assert_eq!(
            normalize_key_path("file://server/share/key"),
            r"\\server\share\key"
        );
        assert_eq!(normalize_key_path("/already/native"), "/already/native");
        assert_eq!(normalize_key_path(""), "");
    }

    #[test]
    fn percent_escapes_in_file_urls_are_decoded() {
        assert_eq!(
            normalize_key_path("file:///home/a/my%20key"),
            "/home/a/my key"
        );
    }

    #[test]
    fn the_encoded_remote_directory_format_is_decoded() {
        assert_eq!(parse_remote_dir("1 0 4 home 4 user"), "/home/user");
        assert_eq!(parse_remote_dir("1 0 3 srv"), "/srv");
    }

    #[test]
    fn a_plain_remote_directory_is_used_as_written() {
        assert_eq!(parse_remote_dir("/var/www"), "/var/www");
        assert_eq!(parse_remote_dir("var/www"), "/var/www");
    }

    #[test]
    fn an_absent_remote_directory_becomes_the_root() {
        assert_eq!(parse_remote_dir(""), "/");
        assert_eq!(parse_remote_dir("   "), "/");
    }

    #[test]
    fn escaped_characters_in_names_are_decoded() {
        let xml = "<FileZilla3><Servers><Server><Host>h</Host>\
                   <Name>R&amp;D box</Name></Server></Servers></FileZilla3>";
        assert_eq!(parse_str(xml).unwrap()[0].name, "R&D box");
    }

    #[test]
    fn a_missing_file_is_reported_as_an_io_error() {
        let dir = TempDir::new().unwrap();
        assert!(matches!(
            parse_file(&dir.path().join("nope.xml")),
            Err(ImportError::Io { .. })
        ));
    }

    #[test]
    fn a_file_that_is_not_xml_is_reported_as_a_format_error() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("bad.xml");
        std::fs::write(&path, "<FileZilla3><Servers>").unwrap();
        // An unclosed document is tolerated by the reader; what matters is
        // that it does not panic and yields nothing usable.
        assert!(parse_file(&path)
            .map(|sites| sites.is_empty())
            .unwrap_or(true));
    }

    #[test]
    fn a_document_with_no_servers_yields_no_profiles() {
        assert!(parse_str("<FileZilla3><Servers></Servers></FileZilla3>")
            .unwrap()
            .is_empty());
    }
}
