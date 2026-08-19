//! Three-tier password storage: system keyring, encrypted vault, or nothing.
//!
//! Passwords are never written to `sites.json`. Where they *are* written
//! depends on the install:
//!
//! * a normal install prefers the OS keyring (Credential Locker, Keychain,
//!   Secret Service), which is the only tier backed by real OS protection;
//! * a portable install prefers the encrypted vault, so credentials travel on
//!   the USB stick with everything else;
//! * if neither is usable, nothing is stored and the user re-enters passwords
//!   each session.
//!
//! The vault's key is derived from the machine, not from a user secret. That
//! stops casual reading of the file; it is not protection against someone who
//! has the machine. The tier is reported to callers so the UI can say which
//! applies.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use base64::Engine;
use sha2::{Digest, Sha256};

/// Service name used for keyring entries.
pub const KEYRING_SERVICE: &str = "portkeydrop";

/// File name of the encrypted vault inside the config directory.
pub const VAULT_FILE_NAME: &str = "vault.enc";

/// Which storage tier is in use.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StorageTier {
    /// The operating system's credential store.
    Keyring,
    /// A machine-encrypted file beside the other config.
    Vault,
    /// Nothing is stored between sessions.
    None,
}

impl StorageTier {
    /// A short phrase for the settings screen.
    pub fn describe(self) -> &'static str {
        match self {
            StorageTier::Keyring => "your system keyring",
            StorageTier::Vault => "an encrypted file in the app's data folder",
            StorageTier::None => "nowhere — passwords are not saved between sessions",
        }
    }
}

/// Machine-specific seed for the vault key.
///
/// Split out so the derivation is testable without depending on the host.
pub fn vault_seed(node: &str, username: &str) -> String {
    format!("portkeydrop:{node}:{username}")
}

/// This machine's node name.
///
/// On Windows the environment's `COMPUTERNAME` is preferred so the value
/// matches what earlier releases derived their key from; a mismatch would make
/// an existing vault undecryptable.
pub fn machine_node() -> String {
    #[cfg(windows)]
    {
        if let Ok(name) = std::env::var("COMPUTERNAME") {
            if !name.is_empty() {
                return name;
            }
        }
    }
    whoami::fallible::hostname().unwrap_or_else(|_| "unknown".to_string())
}

/// The current user's login name.
pub fn machine_username() -> String {
    whoami::fallible::username().unwrap_or_else(|_| "unknown".to_string())
}

/// Derive the Fernet key for the vault from a seed.
pub fn derive_vault_key(seed: &str) -> String {
    let digest = Sha256::digest(seed.as_bytes());
    base64::engine::general_purpose::URL_SAFE.encode(digest)
}

/// An encrypted local password store.
pub struct VaultStore {
    path: PathBuf,
    key: fernet::Fernet,
    entries: BTreeMap<String, String>,
    /// Whether the file existed and decrypted on load.
    loaded: bool,
}

impl VaultStore {
    /// Open (or start) the vault at `path`.
    ///
    /// A vault that cannot be decrypted — usually because the machine changed —
    /// is treated as empty rather than as an error, so the app still starts.
    pub fn open(path: PathBuf) -> Self {
        let key = fernet::Fernet::new(&derive_vault_key(&vault_seed(
            &machine_node(),
            &machine_username(),
        )))
        .expect("a base64 SHA-256 digest is always a valid Fernet key");
        let mut store = Self {
            path,
            key,
            entries: BTreeMap::new(),
            loaded: false,
        };
        store.load();
        store
    }

    /// Open a vault with an explicit key, for tests.
    pub fn open_with_key(path: PathBuf, key: &str) -> Option<Self> {
        let key = fernet::Fernet::new(key)?;
        let mut store = Self {
            path,
            key,
            entries: BTreeMap::new(),
            loaded: false,
        };
        store.load();
        Some(store)
    }

    fn load(&mut self) {
        let Ok(encrypted) = std::fs::read_to_string(&self.path) else {
            self.entries.clear();
            return;
        };
        let Some(decrypted) = self.key.decrypt(encrypted.trim()).ok() else {
            log::warn!(
                "could not decrypt {} (has this machine changed?); starting with an empty vault",
                self.path.display()
            );
            self.entries.clear();
            return;
        };
        match serde_json::from_slice(&decrypted) {
            Ok(entries) => {
                self.entries = entries;
                self.loaded = true;
            }
            Err(err) => {
                log::warn!("vault contents are not valid JSON: {err}");
                self.entries.clear();
            }
        }
    }

    fn save(&self) -> std::io::Result<()> {
        if let Some(parent) = self.path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let plaintext = serde_json::to_vec(&self.entries)
            .map_err(|err| std::io::Error::new(std::io::ErrorKind::InvalidData, err))?;
        std::fs::write(&self.path, self.key.encrypt(&plaintext))
    }

    /// Whether the vault holds nothing, either because it is new or unreadable.
    pub fn is_missing_or_empty(&self) -> bool {
        !self.path.exists() || self.entries.is_empty()
    }

    /// Whether the file was present and decrypted successfully.
    pub fn was_loaded(&self) -> bool {
        self.loaded
    }

    pub fn get(&self, key: &str) -> Option<&str> {
        self.entries.get(key).map(String::as_str)
    }

    pub fn set(&mut self, key: &str, value: &str) -> std::io::Result<()> {
        self.entries.insert(key.to_string(), value.to_string());
        self.save()
    }

    pub fn remove(&mut self, key: &str) -> std::io::Result<()> {
        if self.entries.remove(key).is_some() {
            return self.save();
        }
        Ok(())
    }
}

/// Somewhere passwords can be kept. Implemented by the keyring and the vault,
/// and by a test double.
pub trait PasswordStore: Send {
    fn tier(&self) -> StorageTier;
    fn get(&self, site_id: &str) -> Option<String>;
    fn set(&mut self, site_id: &str, password: &str);
    fn remove(&mut self, site_id: &str);
}

/// The Windows Credential Manager target name earlier releases wrote under.
///
/// Those releases went through Python's `keyring`, which names the credential
/// `{user}@{service}`. The Rust `keyring` crate defaults to `{user}.{service}`,
/// so reading with the default would silently miss every password a user had
/// already saved, and the app would look as though it had forgotten them.
#[cfg(windows)]
fn windows_target(site_id: &str) -> String {
    format!("{site_id}@{KEYRING_SERVICE}")
}

/// The credential entry for a site.
///
/// On Windows this pins the target name to the form described above. Other
/// platforms already agree on how the entry is keyed, and overriding the target
/// there would break *their* compatibility instead.
fn keyring_entry(site_id: &str) -> keyring::Result<keyring::Entry> {
    #[cfg(windows)]
    {
        keyring::Entry::new_with_target(&windows_target(site_id), KEYRING_SERVICE, site_id)
    }
    #[cfg(not(windows))]
    {
        keyring::Entry::new(KEYRING_SERVICE, site_id)
    }
}

/// The entry under the Rust crate's own default naming.
///
/// Only used as a read fallback, so a password saved before the naming was
/// corrected is still found rather than lost.
fn fallback_entry(site_id: &str) -> keyring::Result<keyring::Entry> {
    keyring::Entry::new(KEYRING_SERVICE, site_id)
}

/// The OS credential store.
pub struct KeyringStore;

impl KeyringStore {
    /// Build a keyring store if the platform actually has a usable one.
    ///
    /// A probe is required: the `keyring` crate builds everywhere, but on a
    /// headless Linux box with no Secret Service every call fails at run time.
    pub fn available() -> bool {
        match keyring_entry("__portkeydrop_probe__") {
            Ok(entry) => !matches!(
                entry.get_password(),
                Err(keyring::Error::PlatformFailure(_)) | Err(keyring::Error::NoStorageAccess(_))
            ),
            Err(_) => false,
        }
    }
}

impl PasswordStore for KeyringStore {
    fn tier(&self) -> StorageTier {
        StorageTier::Keyring
    }

    fn get(&self, site_id: &str) -> Option<String> {
        // Both namings are tried, so a password saved by any release is found.
        for entry in [keyring_entry(site_id), fallback_entry(site_id)] {
            let Ok(entry) = entry else {
                continue;
            };
            match entry.get_password() {
                Ok(password) => return Some(password),
                Err(keyring::Error::NoEntry) => continue,
                Err(err) => {
                    log::warn!("keyring lookup failed for {site_id}: {err}");
                    continue;
                }
            }
        }
        None
    }

    fn set(&mut self, site_id: &str, password: &str) {
        let Ok(entry) = keyring_entry(site_id) else {
            return;
        };
        if let Err(err) = entry.set_password(password) {
            log::warn!("could not save the password for {site_id} to the keyring: {err}");
        }
    }

    fn remove(&mut self, site_id: &str) {
        // Remove under both namings, or a cleared password could come back
        // from the entry the other naming left behind.
        if let Ok(entry) = fallback_entry(site_id) {
            let _ = entry.delete_credential();
        }
        let Ok(entry) = keyring_entry(site_id) else {
            return;
        };
        match entry.delete_credential() {
            Ok(()) | Err(keyring::Error::NoEntry) => {}
            Err(err) => log::debug!("could not remove the keyring entry for {site_id}: {err}"),
        }
    }
}

impl PasswordStore for VaultStore {
    fn tier(&self) -> StorageTier {
        StorageTier::Vault
    }

    fn get(&self, site_id: &str) -> Option<String> {
        VaultStore::get(self, site_id).map(str::to_string)
    }

    fn set(&mut self, site_id: &str, password: &str) {
        if let Err(err) = VaultStore::set(self, site_id, password) {
            log::warn!("could not write the password vault: {err}");
        }
    }

    fn remove(&mut self, site_id: &str) {
        if let Err(err) = VaultStore::remove(self, site_id) {
            log::warn!("could not write the password vault: {err}");
        }
    }
}

/// A store that keeps nothing.
pub struct NullStore;

impl PasswordStore for NullStore {
    fn tier(&self) -> StorageTier {
        StorageTier::None
    }
    fn get(&self, _site_id: &str) -> Option<String> {
        None
    }
    fn set(&mut self, _site_id: &str, _password: &str) {}
    fn remove(&mut self, _site_id: &str) {}
}

/// Choose the storage tier for an install.
///
/// Portable installs prefer the vault so the data folder is self-contained;
/// everything else prefers the keyring.
pub fn open_store(config_dir: &Path, portable: bool) -> Box<dyn PasswordStore> {
    if portable {
        return Box::new(VaultStore::open(config_dir.join(VAULT_FILE_NAME)));
    }
    if KeyringStore::available() {
        return Box::new(KeyringStore);
    }
    log::warn!("no system keyring is available; falling back to the encrypted vault");
    Box::new(VaultStore::open(config_dir.join(VAULT_FILE_NAME)))
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    /// A valid Fernet key, fixed so tests do not depend on the host machine.
    const TEST_KEY: &str = "dGVzdC1rZXktdGVzdC1rZXktdGVzdC1rZXktdGVzdC0=";

    #[test]
    fn the_vault_seed_has_a_stable_shape() {
        // Changing this makes every existing vault undecryptable.
        assert_eq!(vault_seed("HOST", "alice"), "portkeydrop:HOST:alice");
    }

    #[test]
    fn the_derived_key_is_url_safe_base64_of_a_sha256_digest() {
        let key = derive_vault_key("portkeydrop:HOST:alice");
        // 32 bytes base64-encodes to 44 characters including padding.
        assert_eq!(key.len(), 44);
        assert!(!key.contains('+') && !key.contains('/'));
        // Fernet must accept it.
        assert!(fernet::Fernet::new(&key).is_some());
    }

    #[test]
    fn the_derived_key_is_deterministic_and_seed_dependent() {
        assert_eq!(derive_vault_key("a"), derive_vault_key("a"));
        assert_ne!(derive_vault_key("a"), derive_vault_key("b"));
    }

    #[test]
    fn a_new_vault_starts_empty() {
        let dir = TempDir::new().unwrap();
        let vault = VaultStore::open_with_key(dir.path().join("vault.enc"), TEST_KEY).unwrap();
        assert!(vault.is_missing_or_empty());
        assert!(!vault.was_loaded());
        assert_eq!(VaultStore::get(&vault, "site-1"), None);
    }

    #[test]
    fn vault_entries_survive_a_reopen() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("vault.enc");

        let mut vault = VaultStore::open_with_key(path.clone(), TEST_KEY).unwrap();
        vault.set("site-1", "hunter2").unwrap();
        drop(vault);

        let vault = VaultStore::open_with_key(path, TEST_KEY).unwrap();
        assert_eq!(VaultStore::get(&vault, "site-1"), Some("hunter2"));
        assert!(vault.was_loaded());
        assert!(!vault.is_missing_or_empty());
    }

    #[test]
    fn the_vault_file_never_contains_the_plaintext_password() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("vault.enc");
        let mut vault = VaultStore::open_with_key(path.clone(), TEST_KEY).unwrap();
        vault.set("site-1", "hunter2").unwrap();

        let contents = std::fs::read_to_string(&path).unwrap();
        assert!(!contents.contains("hunter2"));
        assert!(!contents.contains("site-1"));
    }

    #[test]
    fn removing_an_entry_takes_it_out_of_the_file() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("vault.enc");
        let mut vault = VaultStore::open_with_key(path.clone(), TEST_KEY).unwrap();
        vault.set("site-1", "hunter2").unwrap();
        vault.remove("site-1").unwrap();

        let vault = VaultStore::open_with_key(path, TEST_KEY).unwrap();
        assert_eq!(VaultStore::get(&vault, "site-1"), None);
    }

    #[test]
    fn removing_an_absent_entry_is_harmless() {
        let dir = TempDir::new().unwrap();
        let mut vault = VaultStore::open_with_key(dir.path().join("vault.enc"), TEST_KEY).unwrap();
        assert!(vault.remove("never-existed").is_ok());
    }

    #[test]
    fn a_vault_written_on_another_machine_reads_as_empty_rather_than_failing() {
        // The key is machine-derived, so moving the file to a new machine must
        // degrade to "no saved passwords", not to a startup failure.
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("vault.enc");

        let mut vault = VaultStore::open_with_key(path.clone(), TEST_KEY).unwrap();
        vault.set("site-1", "hunter2").unwrap();
        drop(vault);

        let other_key = derive_vault_key("portkeydrop:OTHERHOST:bob");
        let vault = VaultStore::open_with_key(path, &other_key).unwrap();
        assert_eq!(VaultStore::get(&vault, "site-1"), None);
        assert!(!vault.was_loaded());
    }

    #[test]
    fn a_corrupted_vault_reads_as_empty() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("vault.enc");
        std::fs::write(&path, b"this is not fernet ciphertext").unwrap();
        let vault = VaultStore::open_with_key(path, TEST_KEY).unwrap();
        assert!(vault.is_missing_or_empty());
    }

    #[test]
    fn the_null_store_keeps_nothing() {
        let mut store = NullStore;
        store.set("site-1", "hunter2");
        assert_eq!(store.get("site-1"), None);
        assert_eq!(store.tier(), StorageTier::None);
    }

    #[test]
    fn a_portable_install_always_gets_the_vault() {
        // Portable means self-contained: credentials must not be left behind
        // in the host machine's keyring.
        let dir = TempDir::new().unwrap();
        let store = open_store(dir.path(), true);
        assert_eq!(store.tier(), StorageTier::Vault);
    }

    #[cfg(windows)]
    #[test]
    fn the_windows_target_matches_what_earlier_releases_wrote() {
        // Earlier releases went through Python's keyring, which names the
        // credential `{user}@{service}`. Changing this orphans every password
        // a user has already saved.
        assert_eq!(
            windows_target("8c970d23-c4db-4f1c-882e-fad73f61e067"),
            "8c970d23-c4db-4f1c-882e-fad73f61e067@portkeydrop"
        );
    }

    #[cfg(windows)]
    #[test]
    fn the_windows_target_is_not_the_crate_default() {
        // The crate defaults to `{user}.{service}`; if the two ever coincide
        // this test has stopped guarding anything.
        let site = "site-1";
        assert_ne!(windows_target(site), format!("{site}.{KEYRING_SERVICE}"));
    }

    #[test]
    fn entries_can_be_built_for_a_site() {
        // Both namings must be constructible, since reads try each in turn.
        assert!(keyring_entry("site-1").is_ok());
        assert!(fallback_entry("site-1").is_ok());
    }

    #[test]
    fn every_tier_has_a_description_for_the_settings_screen() {
        for tier in [StorageTier::Keyring, StorageTier::Vault, StorageTier::None] {
            assert!(!tier.describe().is_empty());
        }
    }
}
