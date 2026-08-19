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
pub mod private_files;
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

/// The date of the nightly this build came from, as `YYYYMMDD`.
///
/// Empty for a release build. Prefer [`nightly_date`], which turns that into
/// an `Option` rather than leaving an empty string to be compared.
pub const NIGHTLY_DATE: &str = env!("PORTKEYDROP_NIGHTLY_DATE");

/// Which nightly this build is, if it is one.
///
/// Every nightly carries the version of the release it was cut after, so the
/// version alone cannot tell one from another. Without this the updater has
/// nothing to compare a nightly against and offers the build already
/// installed, over and over.
pub fn nightly_date() -> Option<&'static str> {
    (!NIGHTLY_DATE.is_empty()).then_some(NIGHTLY_DATE)
}

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
