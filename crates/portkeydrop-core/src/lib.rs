//! Core engine for Portkey Drop: configuration, credentials, protocol clients,
//! transfers, sound packs, and updates.
//!
//! Everything here is UI-independent and synchronously callable, so the
//! wxWidgets front end can drive it from worker threads without pulling GUI
//! types into the engine.

pub mod credentials;
pub mod importers;
pub mod local_files;
pub mod migration;
pub mod portable;
pub mod protocols;
pub mod settings;
pub mod sites;
pub mod sound_events;
pub mod soundpacks;
pub mod ssh_agent;
pub mod transfer;
pub mod updater;

/// The application version, taken from the crate manifest.
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

/// The product name as shown in window titles and the notification area.
pub const APP_NAME: &str = "Portkey Drop";

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_version_is_a_three_part_semver() {
        let parts: Vec<&str> = VERSION.split('.').collect();
        assert_eq!(
            parts.len(),
            3,
            "version {VERSION} should be major.minor.patch"
        );
        assert!(parts
            .iter()
            .all(|part| part.chars().all(|c| c.is_ascii_digit())));
    }
}
