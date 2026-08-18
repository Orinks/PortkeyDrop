//! Cyberduck and Mountain Duck bookmark importer.
//!
//! Bookmarks are `.duck` files: Apple property lists, one per connection.
//! Cyberduck keeps passwords in the OS keychain rather than in the bookmark, so
//! imported profiles never carry one.

use std::path::{Path, PathBuf};

use super::{ImportError, ImportedSite};

/// Map a Cyberduck protocol identifier onto this app's protocols.
fn map_protocol(protocol: &str) -> &'static str {
    match protocol.trim().to_ascii_lowercase().as_str() {
        "ftp" => "ftp",
        "ftps" | "ftp-ssl" => "ftps",
        "sftp" | "ssh" => "sftp",
        "dav" | "davs" | "webdav" => "webdav",
        _ => "sftp",
    }
}

/// The default bookmarks directory for this platform.
pub fn detect_bookmarks_dir() -> PathBuf {
    if let Ok(appdata) = std::env::var("APPDATA") {
        if !appdata.is_empty() {
            return PathBuf::from(appdata).join("Cyberduck").join("Bookmarks");
        }
    }

    let home = crate::portable::home_dir();
    let mac = home
        .join("Library")
        .join("Application Support")
        .join("Cyberduck")
        .join("Bookmarks");
    if mac.is_dir() {
        return mac;
    }
    home.join(".config").join("Cyberduck").join("Bookmarks")
}

/// Parse one `.duck` bookmark.
pub fn parse_bookmark_file(path: &Path) -> Result<ImportedSite, ImportError> {
    let value = plist::Value::from_file(path)
        .map_err(|err| ImportError::Format(format!("{}: {err}", path.display())))?;
    site_from_plist(&value)
        .ok_or_else(|| ImportError::Format(format!("{}: no host name in bookmark", path.display())))
}

/// Build a profile from a parsed plist.
pub fn site_from_plist(value: &plist::Value) -> Option<ImportedSite> {
    let dictionary = value.as_dictionary()?;
    let text = |key: &str| -> String {
        dictionary
            .get(key)
            .and_then(|value| match value {
                plist::Value::String(text) => Some(text.clone()),
                plist::Value::Integer(number) => Some(number.to_string()),
                _ => None,
            })
            .unwrap_or_default()
            .trim()
            .to_string()
    };

    // Cyberduck has used both spellings over the years.
    let host = {
        let hostname = text("Hostname");
        if hostname.is_empty() {
            text("Host")
        } else {
            hostname
        }
    };
    if host.is_empty() {
        return None;
    }

    let protocol = map_protocol(&{
        let protocol = text("Protocol");
        if protocol.is_empty() {
            "sftp".to_string()
        } else {
            protocol
        }
    });

    let port = dictionary
        .get("Port")
        .and_then(|value| match value {
            plist::Value::Integer(number) => number.as_unsigned().map(|n| n as u16),
            plist::Value::String(text) => text.trim().parse().ok(),
            _ => None,
        })
        .unwrap_or(0);

    let username = text("Username");
    let initial_dir = {
        let path = text("Path");
        if path.is_empty() {
            "/".to_string()
        } else {
            path
        }
    };

    let nickname = text("Nickname");
    let name = if !nickname.is_empty() {
        nickname
    } else if username.is_empty() {
        host.clone()
    } else {
        format!("{username}@{host}")
    };

    Some(ImportedSite {
        name,
        protocol: protocol.to_string(),
        host,
        port,
        username,
        // Cyberduck stores credentials in the OS keychain, not the bookmark.
        password: String::new(),
        key_path: text("Private Key File"),
        ftp_explicit_ssl: false,
        initial_dir,
        notes: text("Comment"),
    })
}

/// Parse every `.duck` bookmark in a directory.
///
/// Unreadable bookmarks are skipped so one bad file does not lose the rest.
pub fn parse_bookmarks_dir(path: &Path) -> Vec<ImportedSite> {
    let Ok(entries) = std::fs::read_dir(path) else {
        return Vec::new();
    };

    let mut paths: Vec<PathBuf> = entries
        .flatten()
        .map(|entry| entry.path())
        .filter(|path| {
            path.extension()
                .is_some_and(|extension| extension.eq_ignore_ascii_case("duck"))
        })
        .collect();
    paths.sort();

    paths
        .iter()
        .filter_map(|path| match parse_bookmark_file(path) {
            Ok(site) => Some(site),
            Err(err) => {
                log::debug!("skipping bookmark {}: {err}", path.display());
                None
            }
        })
        .filter(|site| !site.host.is_empty())
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn bookmark_xml(nickname: &str, host: &str, protocol: &str, port: i64) -> String {
        format!(
            r#"<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Protocol</key><string>{protocol}</string>
    <key>Nickname</key><string>{nickname}</string>
    <key>Hostname</key><string>{host}</string>
    <key>Port</key><integer>{port}</integer>
    <key>Username</key><string>alice</string>
    <key>Path</key><string>/home/alice</string>
</dict>
</plist>"#
        )
    }

    fn write_bookmark(dir: &Path, file_name: &str, contents: &str) -> PathBuf {
        let path = dir.join(file_name);
        std::fs::write(&path, contents).unwrap();
        path
    }

    #[test]
    fn a_bookmark_becomes_a_profile() {
        let dir = TempDir::new().unwrap();
        let path = write_bookmark(
            dir.path(),
            "work.duck",
            &bookmark_xml("Work", "sftp.example.com", "sftp", 2222),
        );

        let site = parse_bookmark_file(&path).unwrap();
        assert_eq!(site.name, "Work");
        assert_eq!(site.protocol, "sftp");
        assert_eq!(site.host, "sftp.example.com");
        assert_eq!(site.port, 2222);
        assert_eq!(site.username, "alice");
        assert_eq!(site.initial_dir, "/home/alice");
    }

    #[test]
    fn imported_bookmarks_never_carry_a_password() {
        // Cyberduck keeps them in the OS keychain, so there is nothing to read.
        let dir = TempDir::new().unwrap();
        let path = write_bookmark(
            dir.path(),
            "w.duck",
            &bookmark_xml("W", "h.example", "sftp", 22),
        );
        assert_eq!(parse_bookmark_file(&path).unwrap().password, "");
    }

    #[test]
    fn protocol_identifiers_map_onto_this_apps_protocols() {
        assert_eq!(map_protocol("ftp"), "ftp");
        assert_eq!(map_protocol("FTPS"), "ftps");
        assert_eq!(map_protocol("sftp"), "sftp");
        assert_eq!(map_protocol("ssh"), "sftp");
        assert_eq!(map_protocol("davs"), "webdav");
        // An unknown protocol must not make the profile unusable.
        assert_eq!(map_protocol("s3"), "sftp");
    }

    #[test]
    fn a_bookmark_without_a_nickname_is_labelled_from_its_user_and_host() {
        let xml = r#"<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict>
    <key>Hostname</key><string>h.example</string>
    <key>Username</key><string>bob</string>
</dict></plist>"#;
        let dir = TempDir::new().unwrap();
        let path = write_bookmark(dir.path(), "b.duck", xml);
        assert_eq!(parse_bookmark_file(&path).unwrap().name, "bob@h.example");
    }

    #[test]
    fn the_legacy_host_key_spelling_is_accepted() {
        let xml = r#"<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict><key>Host</key><string>old.example</string></dict></plist>"#;
        let dir = TempDir::new().unwrap();
        let path = write_bookmark(dir.path(), "b.duck", xml);
        assert_eq!(parse_bookmark_file(&path).unwrap().host, "old.example");
    }

    #[test]
    fn a_bookmark_without_a_host_is_rejected() {
        let xml = r#"<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict><key>Nickname</key><string>Broken</string></dict></plist>"#;
        let dir = TempDir::new().unwrap();
        let path = write_bookmark(dir.path(), "b.duck", xml);
        assert!(matches!(
            parse_bookmark_file(&path),
            Err(ImportError::Format(_))
        ));
    }

    #[test]
    fn a_bookmark_without_a_path_starts_at_the_root() {
        let xml = r#"<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict><key>Hostname</key><string>h</string></dict></plist>"#;
        let dir = TempDir::new().unwrap();
        let path = write_bookmark(dir.path(), "b.duck", xml);
        assert_eq!(parse_bookmark_file(&path).unwrap().initial_dir, "/");
    }

    #[test]
    fn every_duck_file_in_a_directory_is_read_in_a_stable_order() {
        let dir = TempDir::new().unwrap();
        write_bookmark(
            dir.path(),
            "b.duck",
            &bookmark_xml("Beta", "b.example", "sftp", 22),
        );
        write_bookmark(
            dir.path(),
            "a.duck",
            &bookmark_xml("Alpha", "a.example", "ftp", 21),
        );
        // A non-bookmark file in the same folder must be ignored.
        write_bookmark(dir.path(), "notes.txt", "not a bookmark");

        let sites = parse_bookmarks_dir(dir.path());
        assert_eq!(sites.len(), 2);
        assert_eq!(sites[0].name, "Alpha");
        assert_eq!(sites[1].name, "Beta");
    }

    #[test]
    fn one_unreadable_bookmark_does_not_lose_the_others() {
        let dir = TempDir::new().unwrap();
        write_bookmark(
            dir.path(),
            "good.duck",
            &bookmark_xml("Good", "g.example", "sftp", 22),
        );
        write_bookmark(dir.path(), "bad.duck", "this is not a plist");

        let sites = parse_bookmarks_dir(dir.path());
        assert_eq!(sites.len(), 1);
        assert_eq!(sites[0].name, "Good");
    }

    #[test]
    fn a_missing_directory_yields_no_profiles() {
        let dir = TempDir::new().unwrap();
        assert!(parse_bookmarks_dir(&dir.path().join("nope")).is_empty());
    }

    #[test]
    fn a_binary_plist_bookmark_is_read() {
        // Cyberduck writes binary plists on some platforms.
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("bin.duck");
        let mut dictionary = plist::Dictionary::new();
        dictionary.insert(
            "Hostname".into(),
            plist::Value::String("bin.example".into()),
        );
        dictionary.insert("Nickname".into(), plist::Value::String("Binary".into()));
        dictionary.insert("Protocol".into(), plist::Value::String("ftp".into()));
        plist::Value::Dictionary(dictionary)
            .to_file_binary(&path)
            .unwrap();

        let site = parse_bookmark_file(&path).unwrap();
        assert_eq!(site.name, "Binary");
        assert_eq!(site.host, "bin.example");
        assert_eq!(site.protocol, "ftp");
    }
}
