//! Importing connection profiles from other FTP/SFTP clients.
//!
//! Each source module knows one client's storage format and produces
//! [`ImportedSite`] values. Nothing here writes to the site list; the caller
//! decides which of the discovered profiles to keep.

pub mod cyberduck;
pub mod filezilla;
pub mod winscp;

use std::path::{Path, PathBuf};

/// A profile discovered in another client's configuration.
///
/// Deliberately separate from [`crate::sites::Site`]: an imported profile has
/// no identity in this app until the user accepts it.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ImportedSite {
    pub name: String,
    /// Protocol name; see `SUPPORTED_PROTOCOL_VALUES`.
    pub protocol: String,
    pub host: String,
    /// 0 means "use the protocol default".
    pub port: u16,
    pub username: String,
    /// Empty when the source client did not store a recoverable password.
    pub password: String,
    pub key_path: String,
    pub ftp_explicit_ssl: bool,
    pub initial_dir: String,
    pub notes: String,
}

impl ImportedSite {
    /// A profile with the required fields and sensible defaults.
    pub fn new(
        name: impl Into<String>,
        protocol: impl Into<String>,
        host: impl Into<String>,
    ) -> Self {
        Self {
            name: name.into(),
            protocol: protocol.into(),
            host: host.into(),
            initial_dir: "/".to_string(),
            ..Default::default()
        }
    }

    /// Turn this into a saved site, giving it a fresh identity.
    pub fn to_site(&self) -> crate::sites::Site {
        crate::sites::Site {
            name: self.name.clone(),
            protocol: self.protocol.clone(),
            host: self.host.clone(),
            port: self.port,
            username: self.username.clone(),
            password: self.password.clone(),
            key_path: self.key_path.clone(),
            ftp_explicit_ssl: self.ftp_explicit_ssl,
            initial_dir: if self.initial_dir.is_empty() {
                "/".to_string()
            } else {
                self.initial_dir.clone()
            },
            notes: self.notes.clone(),
            ..Default::default()
        }
    }
}

/// A client Portkey Drop can import from.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ImportSource {
    FileZilla,
    WinScp,
    Cyberduck,
    /// A file the user picks; the format is detected from its contents.
    FromFile,
}

/// Every source, in the order the picker shows them.
pub const SOURCES: [ImportSource; 4] = [
    ImportSource::FileZilla,
    ImportSource::WinScp,
    ImportSource::Cyberduck,
    ImportSource::FromFile,
];

/// Sentinel shown when WinSCP profiles live in the registry rather than a file.
pub const WINSCP_REGISTRY_SENTINEL: &str =
    r"Registry (HKCU\Software\Martin Prikryl\WinSCP 2\Sessions)";

impl ImportSource {
    /// Stable identifier used in settings and tests.
    pub fn key(self) -> &'static str {
        match self {
            ImportSource::FileZilla => "filezilla",
            ImportSource::WinScp => "winscp",
            ImportSource::Cyberduck => "cyberduck",
            ImportSource::FromFile => "from_file",
        }
    }

    /// Name shown in the picker.
    pub fn label(self) -> &'static str {
        match self {
            ImportSource::FileZilla => "FileZilla",
            ImportSource::WinScp => "WinSCP",
            ImportSource::Cyberduck => "Cyberduck",
            ImportSource::FromFile => "From file...",
        }
    }

    /// Parse an identifier back into a source.
    pub fn from_key(key: &str) -> Option<Self> {
        SOURCES.into_iter().find(|source| source.key() == key)
    }

    /// Whether this machine has configuration for this source.
    pub fn is_available(self) -> bool {
        match self {
            ImportSource::FileZilla => filezilla::detect_path().is_file(),
            ImportSource::WinScp => {
                winscp::registry_sessions_available() || winscp::detect_ini_path().is_file()
            }
            ImportSource::Cyberduck => cyberduck::detect_bookmarks_dir().is_dir(),
            // Picking a file is always possible.
            ImportSource::FromFile => true,
        }
    }

    /// The default location for this source, or the registry sentinel.
    pub fn default_location(self) -> Option<String> {
        match self {
            ImportSource::FileZilla => {
                Some(filezilla::detect_path().to_string_lossy().into_owned())
            }
            ImportSource::WinScp if winscp::registry_sessions_available() => {
                Some(WINSCP_REGISTRY_SENTINEL.to_string())
            }
            ImportSource::WinScp => Some(winscp::detect_ini_path().to_string_lossy().into_owned()),
            ImportSource::Cyberduck => Some(
                cyberduck::detect_bookmarks_dir()
                    .to_string_lossy()
                    .into_owned(),
            ),
            ImportSource::FromFile => None,
        }
    }
}

/// Sources with detectable configuration on this machine.
pub fn available_sources() -> Vec<ImportSource> {
    SOURCES
        .into_iter()
        .filter(|source| source.is_available())
        .collect()
}

/// Errors raised while importing.
#[derive(Debug, thiserror::Error)]
pub enum ImportError {
    #[error("no file was selected")]
    PathRequired,
    #[error("could not read {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
    #[error("{0}")]
    Format(String),
}

/// Load profiles from a source.
///
/// `path` overrides the source's default location; WinSCP falls back to the
/// registry when no INI file exists.
pub fn load_from_source(
    source: ImportSource,
    path: Option<&Path>,
) -> Result<Vec<ImportedSite>, ImportError> {
    match source {
        ImportSource::FileZilla => {
            let path = path
                .map(Path::to_path_buf)
                .unwrap_or_else(filezilla::detect_path);
            filezilla::parse_file(&path)
        }
        ImportSource::WinScp => match path {
            Some(path) => winscp::parse_ini_file(path),
            None => {
                let ini = winscp::detect_ini_path();
                if ini.is_file() {
                    winscp::parse_ini_file(&ini)
                } else {
                    Ok(winscp::parse_registry_sessions())
                }
            }
        },
        ImportSource::Cyberduck => {
            let path = path
                .map(Path::to_path_buf)
                .unwrap_or_else(cyberduck::detect_bookmarks_dir);
            if path.is_dir() {
                Ok(cyberduck::parse_bookmarks_dir(&path))
            } else {
                cyberduck::parse_bookmark_file(&path).map(|site| vec![site])
            }
        }
        ImportSource::FromFile => {
            let path = path.ok_or(ImportError::PathRequired)?;
            Ok(load_from_unknown_path(path))
        }
    }
}

/// Work out a file's format by trying each parser.
///
/// The extension is used as a hint first; failing that every parser is tried
/// and the first one that finds profiles wins. Returning an empty list rather
/// than an error keeps "this file has nothing in it" distinct from "this file
/// is broken", which is what the user needs to know.
pub fn load_from_unknown_path(path: &Path) -> Vec<ImportedSite> {
    if path.is_dir() {
        let sites = cyberduck::parse_bookmarks_dir(path);
        if !sites.is_empty() {
            return sites;
        }
    }

    let extension = path
        .extension()
        .map(|ext| ext.to_string_lossy().to_ascii_lowercase())
        .unwrap_or_default();
    match extension.as_str() {
        "ini" => return winscp::parse_ini_file(path).unwrap_or_default(),
        "duck" | "plist" => {
            return cyberduck::parse_bookmark_file(path)
                .map(|site| vec![site])
                .unwrap_or_default()
        }
        "xml" => {
            if let Ok(sites) = filezilla::parse_file(path) {
                if !sites.is_empty() {
                    return sites;
                }
            }
        }
        _ => {}
    }

    for sites in [
        filezilla::parse_file(path).unwrap_or_default(),
        winscp::parse_ini_file(path).unwrap_or_default(),
        cyberduck::parse_bookmark_file(path)
            .map(|site| vec![site])
            .unwrap_or_default(),
    ] {
        if !sites.is_empty() {
            return sites;
        }
    }
    Vec::new()
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn source_keys_and_labels_round_trip() {
        for source in SOURCES {
            assert_eq!(ImportSource::from_key(source.key()), Some(source));
            assert!(!source.label().is_empty());
        }
        assert_eq!(ImportSource::from_key("nope"), None);
    }

    #[test]
    fn picking_a_file_is_always_available() {
        assert!(ImportSource::FromFile.is_available());
        assert!(available_sources().contains(&ImportSource::FromFile));
    }

    #[test]
    fn picking_a_file_has_no_default_location() {
        assert_eq!(ImportSource::FromFile.default_location(), None);
    }

    #[test]
    fn importing_from_a_file_without_a_path_is_rejected() {
        assert!(matches!(
            load_from_source(ImportSource::FromFile, None),
            Err(ImportError::PathRequired)
        ));
    }

    #[test]
    fn an_imported_profile_becomes_a_site_with_a_fresh_identity() {
        let mut imported = ImportedSite::new("Work", "sftp", "example.com");
        imported.username = "alice".into();
        imported.password = "hunter2".into();
        imported.port = 2222;

        let site = imported.to_site();
        assert_eq!(site.name, "Work");
        assert_eq!(site.host, "example.com");
        assert_eq!(site.port, 2222);
        assert_eq!(site.username, "alice");
        assert_eq!(site.password, "hunter2");
        assert!(!site.id.is_empty());
        // Two imports of the same profile are distinct sites.
        assert_ne!(site.id, imported.to_site().id);
    }

    #[test]
    fn an_imported_profile_without_a_directory_starts_at_the_root() {
        let imported = ImportedSite {
            initial_dir: String::new(),
            ..ImportedSite::new("a", "sftp", "h")
        };
        assert_eq!(imported.to_site().initial_dir, "/");
    }

    #[test]
    fn an_unreadable_file_yields_no_profiles_rather_than_an_error() {
        let dir = TempDir::new().unwrap();
        assert!(load_from_unknown_path(&dir.path().join("nope.xml")).is_empty());
    }

    #[test]
    fn a_file_in_no_recognised_format_yields_no_profiles() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("random.dat");
        std::fs::write(&path, b"just some bytes").unwrap();
        assert!(load_from_unknown_path(&path).is_empty());
    }

    #[test]
    fn a_filezilla_export_is_detected_from_an_unlabelled_file() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("export.bak");
        std::fs::write(
            &path,
            r#"<FileZilla3><Servers><Server><Host>ftp.example.com</Host><Protocol>0</Protocol>
               <Port>21</Port><User>bob</User><Name>Mine</Name></Server></Servers></FileZilla3>"#,
        )
        .unwrap();

        let sites = load_from_unknown_path(&path);
        assert_eq!(sites.len(), 1);
        assert_eq!(sites[0].host, "ftp.example.com");
    }
}
