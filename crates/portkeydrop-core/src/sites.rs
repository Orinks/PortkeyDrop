//! Saved connection profiles.
//!
//! `sites.json` holds everything except passwords; those live in the password
//! store (see [`crate::credentials`]) and are re-attached on load. That split is
//! the reason the file can be copied around, backed up, or checked by hand
//! without leaking credentials.

use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::credentials::{self, PasswordStore, StorageTier};
use crate::protocols::{ConnectionInfo, HostKeyPolicy, Protocol};

/// File name of the sites document inside the config directory.
pub const SITES_FILE_NAME: &str = "sites.json";

fn default_protocol() -> String {
    "sftp".to_string()
}

fn default_initial_dir() -> String {
    "/".to_string()
}

/// A saved connection profile.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct Site {
    /// Stable identifier, also the key under which the password is stored.
    pub id: String,
    pub name: String,
    /// Protocol name; see `SUPPORTED_PROTOCOL_VALUES`.
    pub protocol: String,
    pub host: String,
    /// 0 means "use the protocol default".
    pub port: u16,
    pub username: String,
    /// Held in memory only. Never serialised — see [`Site::to_stored`].
    #[serde(skip_serializing)]
    pub password: String,
    pub key_path: String,
    pub ftp_explicit_ssl: bool,
    pub initial_dir: String,
    pub notes: String,
}

impl Default for Site {
    fn default() -> Self {
        Self {
            id: uuid::Uuid::new_v4().to_string(),
            name: String::new(),
            protocol: default_protocol(),
            host: String::new(),
            port: 0,
            username: String::new(),
            password: String::new(),
            key_path: String::new(),
            ftp_explicit_ssl: false,
            initial_dir: default_initial_dir(),
            notes: String::new(),
        }
    }
}

impl Site {
    /// A new site with a freshly generated id.
    pub fn new(name: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            ..Default::default()
        }
    }

    /// The parsed protocol, defaulting to SFTP for an unrecognised value.
    pub fn protocol(&self) -> Protocol {
        self.protocol.parse().unwrap_or(Protocol::Sftp)
    }

    /// Connection parameters for this site.
    ///
    /// `ftp_explicit_ssl` only applies to plain FTP; carrying it onto other
    /// protocols would change which port and TLS mode are chosen.
    pub fn to_connection_info(&self) -> ConnectionInfo {
        let protocol = self.protocol();
        ConnectionInfo {
            protocol,
            host: self.host.clone(),
            port: self.port,
            username: self.username.clone(),
            password: self.password.clone(),
            key_path: self.key_path.clone(),
            ftp_explicit_ssl: self.ftp_explicit_ssl && protocol == Protocol::Ftp,
            host_key_policy: HostKeyPolicy::default(),
            ..Default::default()
        }
    }

    /// A copy with the password cleared, for writing to disk.
    pub fn to_stored(&self) -> Site {
        Site {
            password: String::new(),
            ..self.clone()
        }
    }

    /// A label for the sites list.
    pub fn display_label(&self) -> String {
        let target = if self.username.is_empty() {
            self.host.clone()
        } else {
            format!("{}@{}", self.username, self.host)
        };
        if self.name.is_empty() {
            target
        } else {
            format!("{} ({} {})", self.name, self.protocol, target)
        }
    }
}

/// Manages the saved site list and its passwords.
pub struct SiteManager {
    config_dir: PathBuf,
    sites: Vec<Site>,
    passwords: Box<dyn PasswordStore>,
}

impl SiteManager {
    /// Open the site list in `config_dir`, choosing a password tier.
    pub fn open(config_dir: &Path, portable: bool) -> Self {
        let passwords = credentials::open_store(config_dir, portable);
        Self::with_store(config_dir, passwords)
    }

    /// Open with an explicit password store, for tests.
    pub fn with_store(config_dir: &Path, passwords: Box<dyn PasswordStore>) -> Self {
        let mut manager = Self {
            config_dir: config_dir.to_path_buf(),
            sites: Vec::new(),
            passwords,
        };
        manager.load();
        manager
    }

    /// Path of the sites document.
    pub fn sites_path(&self) -> PathBuf {
        self.config_dir.join(SITES_FILE_NAME)
    }

    /// Which password tier is in use.
    pub fn storage_tier(&self) -> StorageTier {
        self.passwords.tier()
    }

    /// Read the site list, re-attaching stored passwords.
    ///
    /// A site file carrying a plaintext password — written by a much older
    /// build, or edited by hand — is migrated into the password store on load.
    pub fn load(&mut self) {
        let path = self.sites_path();
        let Ok(text) = std::fs::read_to_string(&path) else {
            self.sites.clear();
            return;
        };
        let mut sites: Vec<Site> = match serde_json::from_str(&text) {
            Ok(sites) => sites,
            Err(err) => {
                log::warn!("could not read {}: {err}", path.display());
                Vec::new()
            }
        };

        let mut needs_rewrite = false;
        for site in &mut sites {
            match self.passwords.get(&site.id) {
                Some(stored) => site.password = stored,
                None if !site.password.is_empty() => {
                    self.passwords.set(&site.id, &site.password);
                    needs_rewrite = true;
                }
                None => {}
            }
        }
        self.sites = sites;

        if needs_rewrite {
            log::info!("moved a plaintext password out of {}", path.display());
            let _ = self.save();
        }
    }

    /// Write the site list and sync every password to the store.
    pub fn save(&mut self) -> std::io::Result<()> {
        crate::private_files::ensure_private_dir(&self.config_dir)?;

        for site in &self.sites {
            if site.password.is_empty() {
                // A cleared password must be removed, or the next load would
                // restore it from the store and appear to undo the change.
                self.passwords.remove(&site.id);
            } else {
                self.passwords.set(&site.id, &site.password);
            }
        }

        let stored: Vec<Site> = self.sites.iter().map(Site::to_stored).collect();
        let text = serde_json::to_string_pretty(&stored)
            .map_err(|err| std::io::Error::new(std::io::ErrorKind::InvalidData, err))?;
        std::fs::write(self.sites_path(), text)
    }

    /// Sites whose password is in the system keyring but not in this store.
    ///
    /// Only meaningful for a vault-backed install: someone who moves to a
    /// portable copy has their passwords sitting in the keyring of the machine
    /// they left behind, and nothing here would ever look there. Sites that
    /// already have a password are left alone, so this narrows to exactly what
    /// an import would add.
    pub fn keyring_passwords_to_import(&self) -> Vec<String> {
        if self.passwords.tier() != StorageTier::Vault || !credentials::KeyringStore::available() {
            return Vec::new();
        }
        let keyring = credentials::KeyringStore;
        self.sites
            .iter()
            .filter(|site| site.password.is_empty())
            .filter(|site| {
                keyring
                    .get(&site.id)
                    .is_some_and(|stored| !stored.is_empty())
            })
            .map(|site| site.id.clone())
            .collect()
    }

    /// Copy those passwords out of the keyring into this store.
    ///
    /// The keyring entries are left in place, so the installed copy of the app
    /// keeps working.
    pub fn import_keyring_passwords(&mut self) -> std::io::Result<usize> {
        let ids = self.keyring_passwords_to_import();
        if ids.is_empty() {
            return Ok(0);
        }
        let keyring = credentials::KeyringStore;
        let mut imported = 0;
        for id in ids {
            let Some(password) = keyring.get(&id).filter(|stored| !stored.is_empty()) else {
                continue;
            };
            if let Some(site) = self.sites.iter_mut().find(|site| site.id == id) {
                site.password = password;
                imported += 1;
            }
        }
        if imported > 0 {
            self.save()?;
        }
        Ok(imported)
    }

    /// Every saved site, in list order.
    pub fn sites(&self) -> &[Site] {
        &self.sites
    }

    /// Add a site and persist.
    pub fn add(&mut self, site: Site) -> std::io::Result<()> {
        self.sites.push(site);
        self.save()
    }

    /// Replace a site by id and persist.
    pub fn update(&mut self, site: Site) -> std::io::Result<()> {
        let Some(slot) = self
            .sites
            .iter_mut()
            .find(|existing| existing.id == site.id)
        else {
            return Err(std::io::Error::new(
                std::io::ErrorKind::NotFound,
                format!("site {} not found", site.id),
            ));
        };
        *slot = site;
        self.save()
    }

    /// Remove a site by id, along with its stored password.
    pub fn remove(&mut self, site_id: &str) -> std::io::Result<()> {
        self.passwords.remove(site_id);
        self.sites.retain(|site| site.id != site_id);
        self.save()
    }

    /// Look up a site by id.
    pub fn get(&self, site_id: &str) -> Option<&Site> {
        self.sites.iter().find(|site| site.id == site_id)
    }

    /// Look up a site by name, ignoring case.
    pub fn find_by_name(&self, name: &str) -> Option<&Site> {
        self.sites
            .iter()
            .find(|site| site.name.eq_ignore_ascii_case(name))
    }

    /// Whether a name is already taken by a different site.
    pub fn name_taken(&self, name: &str, except_id: Option<&str>) -> bool {
        self.sites
            .iter()
            .any(|site| site.name.eq_ignore_ascii_case(name) && Some(site.id.as_str()) != except_id)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeMap;
    use std::sync::{Arc, Mutex};
    use tempfile::TempDir;

    /// An in-memory password store that records what it was asked to keep.
    #[derive(Clone, Default)]
    struct FakeStore {
        entries: Arc<Mutex<BTreeMap<String, String>>>,
    }

    impl PasswordStore for FakeStore {
        fn tier(&self) -> StorageTier {
            StorageTier::Vault
        }
        fn get(&self, site_id: &str) -> Option<String> {
            self.entries.lock().unwrap().get(site_id).cloned()
        }
        fn set(&mut self, site_id: &str, password: &str) {
            self.entries
                .lock()
                .unwrap()
                .insert(site_id.to_string(), password.to_string());
        }
        fn remove(&mut self, site_id: &str) {
            self.entries.lock().unwrap().remove(site_id);
        }
    }

    /// A store that reports the keyring tier, for the paths that branch on it.
    #[derive(Clone, Default)]
    struct KeyringTierStore;

    impl PasswordStore for KeyringTierStore {
        fn tier(&self) -> StorageTier {
            StorageTier::Keyring
        }
        fn get(&self, _site_id: &str) -> Option<String> {
            None
        }
        fn set(&mut self, _site_id: &str, _password: &str) {}
        fn remove(&mut self, _site_id: &str) {}
    }

    fn manager(dir: &TempDir) -> (SiteManager, FakeStore) {
        let store = FakeStore::default();
        (
            SiteManager::with_store(dir.path(), Box::new(store.clone())),
            store,
        )
    }

    fn sample_site() -> Site {
        Site {
            name: "Work".into(),
            protocol: "sftp".into(),
            host: "sftp.example.com".into(),
            port: 2222,
            username: "alice".into(),
            password: "hunter2".into(),
            ..Default::default()
        }
    }

    #[test]
    fn new_sites_get_distinct_identifiers() {
        assert_ne!(Site::new("a").id, Site::new("b").id);
        assert!(!Site::new("a").id.is_empty());
    }

    #[test]
    fn a_new_site_defaults_to_sftp_at_the_root() {
        let site = Site::new("Work");
        assert_eq!(site.protocol, "sftp");
        assert_eq!(site.initial_dir, "/");
        assert_eq!(site.port, 0);
    }

    #[test]
    fn an_unknown_protocol_falls_back_to_sftp() {
        // A site file from a newer build must not make the app unusable.
        let site = Site {
            protocol: "gopher".into(),
            ..Default::default()
        };
        assert_eq!(site.protocol(), Protocol::Sftp);
    }

    #[test]
    fn connection_info_carries_the_site_settings() {
        let info = sample_site().to_connection_info();
        assert_eq!(info.protocol, Protocol::Sftp);
        assert_eq!(info.host, "sftp.example.com");
        assert_eq!(info.effective_port(), 2222);
        assert_eq!(info.username, "alice");
        assert_eq!(info.password, "hunter2");
    }

    #[test]
    fn explicit_ssl_only_applies_to_plain_ftp() {
        // Carrying the flag onto SFTP would change the chosen port and TLS
        // mode for a protocol it means nothing to.
        let site = Site {
            protocol: "sftp".into(),
            ftp_explicit_ssl: true,
            ..Default::default()
        };
        assert!(!site.to_connection_info().ftp_explicit_ssl);

        let site = Site {
            protocol: "ftp".into(),
            ftp_explicit_ssl: true,
            ..Default::default()
        };
        assert!(site.to_connection_info().ftp_explicit_ssl);
    }

    #[test]
    fn the_display_label_names_the_user_and_host() {
        assert_eq!(
            sample_site().display_label(),
            "Work (sftp alice@sftp.example.com)"
        );

        let anonymous = Site {
            username: String::new(),
            ..sample_site()
        };
        assert_eq!(anonymous.display_label(), "Work (sftp sftp.example.com)");

        let unnamed = Site {
            name: String::new(),
            ..sample_site()
        };
        assert_eq!(unnamed.display_label(), "alice@sftp.example.com");
    }

    #[test]
    fn an_empty_config_directory_yields_no_sites() {
        let dir = TempDir::new().unwrap();
        let (manager, _) = manager(&dir);
        assert!(manager.sites().is_empty());
    }

    #[test]
    fn a_malformed_sites_file_yields_no_sites_rather_than_failing() {
        let dir = TempDir::new().unwrap();
        std::fs::write(dir.path().join(SITES_FILE_NAME), "{not json").unwrap();
        let (manager, _) = manager(&dir);
        assert!(manager.sites().is_empty());
    }

    #[test]
    fn sites_survive_a_reopen() {
        let dir = TempDir::new().unwrap();
        let store = FakeStore::default();

        let mut manager = SiteManager::with_store(dir.path(), Box::new(store.clone()));
        manager.add(sample_site()).unwrap();

        let reopened = SiteManager::with_store(dir.path(), Box::new(store));
        assert_eq!(reopened.sites().len(), 1);
        assert_eq!(reopened.sites()[0].name, "Work");
        assert_eq!(reopened.sites()[0].host, "sftp.example.com");
    }

    #[test]
    fn passwords_are_never_written_to_the_sites_file() {
        let dir = TempDir::new().unwrap();
        let (mut manager, _) = manager(&dir);
        manager.add(sample_site()).unwrap();

        let contents = std::fs::read_to_string(dir.path().join(SITES_FILE_NAME)).unwrap();
        assert!(!contents.contains("hunter2"));
        assert!(contents.contains("sftp.example.com"));
    }

    #[test]
    fn passwords_are_reattached_from_the_store_on_load() {
        let dir = TempDir::new().unwrap();
        let store = FakeStore::default();

        let mut manager = SiteManager::with_store(dir.path(), Box::new(store.clone()));
        manager.add(sample_site()).unwrap();

        let reopened = SiteManager::with_store(dir.path(), Box::new(store));
        assert_eq!(reopened.sites()[0].password, "hunter2");
    }

    #[test]
    fn clearing_a_password_removes_it_from_the_store() {
        // Otherwise the next load would restore it and appear to undo the
        // user's change.
        let dir = TempDir::new().unwrap();
        let store = FakeStore::default();
        let mut manager = SiteManager::with_store(dir.path(), Box::new(store.clone()));
        manager.add(sample_site()).unwrap();

        let cleared = Site {
            password: String::new(),
            ..manager.sites()[0].clone()
        };
        manager.update(cleared).unwrap();

        let reopened = SiteManager::with_store(dir.path(), Box::new(store));
        assert_eq!(reopened.sites()[0].password, "");
    }

    #[test]
    fn a_plaintext_password_in_the_file_is_migrated_into_the_store() {
        let dir = TempDir::new().unwrap();
        let legacy = r#"[{"id":"site-1","name":"Old","protocol":"sftp","host":"h",
                          "port":0,"username":"u","password":"leaked","key_path":"",
                          "ftp_explicit_ssl":false,"initial_dir":"/","notes":""}]"#;
        std::fs::write(dir.path().join(SITES_FILE_NAME), legacy).unwrap();

        let store = FakeStore::default();
        let manager = SiteManager::with_store(dir.path(), Box::new(store.clone()));

        assert_eq!(manager.sites()[0].password, "leaked");
        assert_eq!(store.get("site-1").as_deref(), Some("leaked"));
        // The file is rewritten without the plaintext.
        let contents = std::fs::read_to_string(dir.path().join(SITES_FILE_NAME)).unwrap();
        assert!(!contents.contains("leaked"));
    }

    #[test]
    fn removing_a_site_also_removes_its_password() {
        let dir = TempDir::new().unwrap();
        let store = FakeStore::default();
        let mut manager = SiteManager::with_store(dir.path(), Box::new(store.clone()));
        manager.add(sample_site()).unwrap();
        let id = manager.sites()[0].id.clone();

        manager.remove(&id).unwrap();

        assert!(manager.sites().is_empty());
        assert_eq!(store.get(&id), None);
    }

    #[test]
    fn updating_an_unknown_site_is_an_error() {
        let dir = TempDir::new().unwrap();
        let (mut manager, _) = manager(&dir);
        assert!(manager.update(sample_site()).is_err());
    }

    #[test]
    fn a_keyring_backed_install_has_no_passwords_to_import() {
        // The import exists to reach a store this install does not use. One
        // already reading the keyring has nothing to fetch from it.
        let dir = TempDir::new().unwrap();
        let mut manager = SiteManager::with_store(dir.path(), Box::new(KeyringTierStore));
        manager.add(sample_site()).unwrap();
        assert!(manager.keyring_passwords_to_import().is_empty());
        assert_eq!(manager.import_keyring_passwords().unwrap(), 0);
    }

    #[test]
    fn sites_that_already_have_a_password_are_not_import_candidates() {
        // Their password is in the vault; overwriting it from the keyring
        // would undo a change made in this copy.
        let dir = TempDir::new().unwrap();
        let (mut manager, _store) = manager(&dir);
        manager.add(sample_site()).unwrap();
        assert!(manager.sites().iter().all(|site| !site.password.is_empty()));
        assert!(manager.keyring_passwords_to_import().is_empty());
    }

    #[test]
    fn sites_can_be_found_by_id_and_by_name() {
        let dir = TempDir::new().unwrap();
        let (mut manager, _) = manager(&dir);
        manager.add(sample_site()).unwrap();
        let id = manager.sites()[0].id.clone();

        assert_eq!(manager.get(&id).unwrap().name, "Work");
        assert_eq!(manager.find_by_name("work").unwrap().id, id);
        assert!(manager.find_by_name("nope").is_none());
        assert!(manager.get("nope").is_none());
    }

    #[test]
    fn a_name_clash_is_detected_but_a_site_does_not_clash_with_itself() {
        let dir = TempDir::new().unwrap();
        let (mut manager, _) = manager(&dir);
        manager.add(sample_site()).unwrap();
        let id = manager.sites()[0].id.clone();

        assert!(manager.name_taken("Work", None));
        assert!(manager.name_taken("WORK", None));
        // Renaming a site to its own current name is not a clash.
        assert!(!manager.name_taken("Work", Some(&id)));
        assert!(!manager.name_taken("Other", None));
    }

    #[test]
    fn unknown_fields_in_the_sites_file_are_ignored() {
        let dir = TempDir::new().unwrap();
        let future = r#"[{"id":"s1","name":"N","host":"h","colour":"blue"}]"#;
        std::fs::write(dir.path().join(SITES_FILE_NAME), future).unwrap();
        let (manager, _) = manager(&dir);
        assert_eq!(manager.sites().len(), 1);
        assert_eq!(manager.sites()[0].name, "N");
        // Absent fields keep their defaults.
        assert_eq!(manager.sites()[0].protocol, "sftp");
    }
}
