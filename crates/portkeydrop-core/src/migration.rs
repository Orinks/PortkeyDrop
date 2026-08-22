//! Copying an existing installation's config into a portable data directory.
//!
//! Offered once, when a portable build starts next to an existing standard
//! install. Files are copied rather than moved so the original install keeps
//! working.

use std::path::{Path, PathBuf};

/// Marker recording that the one-time keyring password import has been offered.
///
/// The name matches what earlier Python releases wrote, so someone who already
/// declined there is not asked again by this build.
pub const KEYRING_IMPORT_MARKER: &str = ".keyring_migrated";

/// `(label shown to the user, file name)` for each migratable item.
pub const MIGRATION_ITEMS: &[(&str, &str)] = &[
    ("Sites and connections", "sites.json"),
    ("Saved passwords (encrypted vault)", "vault.enc"),
    ("Known SSH hosts", "known_hosts"),
    ("App settings", "settings.json"),
];

/// Whether at least one file could be copied into the portable directory.
///
/// Files already present in the portable directory are skipped, so a second
/// launch does not re-offer a migration that has been done.
pub fn has_migration_candidates(portable_dir: &Path, standard_dir: &Path) -> bool {
    MIGRATION_ITEMS.iter().any(|(_, file_name)| {
        standard_dir.join(file_name).exists() && !portable_dir.join(file_name).exists()
    })
}

/// Every `(label, file name)` that exists in the standard config directory.
pub fn migration_candidates(standard_dir: &Path) -> Vec<(&'static str, &'static str)> {
    MIGRATION_ITEMS
        .iter()
        .copied()
        .filter(|(_, file_name)| standard_dir.join(file_name).exists())
        .collect()
}

/// Copy the named files from the standard directory into the portable one.
///
/// Names that do not exist in the source are skipped silently — the caller
/// passes a user selection, which may include an item that vanished since the
/// dialog was populated.
pub fn migrate_files<I, S>(
    file_names: I,
    standard_dir: &Path,
    portable_dir: &Path,
) -> std::io::Result<Vec<PathBuf>>
where
    I: IntoIterator<Item = S>,
    S: AsRef<str>,
{
    std::fs::create_dir_all(portable_dir)?;
    let mut copied = Vec::new();
    for file_name in file_names {
        let file_name = file_name.as_ref();
        let source = standard_dir.join(file_name);
        if !source.exists() {
            continue;
        }
        let destination = portable_dir.join(file_name);
        std::fs::copy(&source, &destination)?;
        copied.push(destination);
    }
    Ok(copied)
}

/// The first of `candidates` holding something worth copying.
///
/// Kept separate from [`standard_source_dir`] so it can be tested with
/// temporary directories rather than wherever this machine happens to keep its
/// configuration. A candidate that *is* the portable directory is skipped:
/// copying a folder onto itself is never what was meant.
pub fn source_with_candidates<I>(portable_dir: &Path, candidates: I) -> Option<PathBuf>
where
    I: IntoIterator<Item = PathBuf>,
{
    candidates
        .into_iter()
        .filter(|dir| dir != portable_dir)
        .find(|dir| has_migration_candidates(portable_dir, dir))
}

/// The standard install a portable build should offer to copy from.
///
/// Both the platform configuration folder and the old home-folder location are
/// considered, because an install predating the move still keeps everything in
/// `~/.portkeydrop`. Returns `None` when neither has anything worth copying.
pub fn standard_source_dir(portable_dir: &Path) -> Option<PathBuf> {
    source_with_candidates(
        portable_dir,
        [
            crate::portable::standard_config_dir(),
            crate::portable::legacy_config_dir(&crate::portable::home_dir()),
        ],
    )
}

/// Whether the one-time keyring import has already been offered.
pub fn keyring_import_offered(config_dir: &Path) -> bool {
    config_dir.join(KEYRING_IMPORT_MARKER).exists()
}

/// Record that the keyring import has been offered, answered either way.
///
/// Written whether or not the user accepted: the question is asked once, and
/// re-asking on every launch would be worse than never asking.
pub fn mark_keyring_import_offered(config_dir: &Path) -> std::io::Result<()> {
    std::fs::create_dir_all(config_dir)?;
    std::fs::write(config_dir.join(KEYRING_IMPORT_MARKER), b"")
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn write(dir: &Path, name: &str, contents: &str) {
        std::fs::write(dir.join(name), contents).unwrap();
    }

    #[test]
    fn the_keyring_import_is_offered_once_and_then_remembered() {
        let dir = TempDir::new().unwrap();
        assert!(!keyring_import_offered(dir.path()));
        mark_keyring_import_offered(dir.path()).unwrap();
        assert!(keyring_import_offered(dir.path()));
    }

    #[test]
    fn the_keyring_marker_matches_what_earlier_releases_wrote() {
        // Someone who already declined in the Python build must not be asked
        // again by this one.
        assert_eq!(KEYRING_IMPORT_MARKER, ".keyring_migrated");
    }

    #[test]
    fn the_first_candidate_with_something_to_copy_wins() {
        let portable = TempDir::new().unwrap();
        let empty = TempDir::new().unwrap();
        let installed = TempDir::new().unwrap();
        write(installed.path(), "sites.json", "[]");
        assert_eq!(
            source_with_candidates(
                portable.path(),
                [empty.path().to_path_buf(), installed.path().to_path_buf()]
            ),
            Some(installed.path().to_path_buf())
        );
    }

    #[test]
    fn a_portable_directory_is_never_offered_as_its_own_source() {
        // Copying a folder onto itself is a no-op at best and a truncation at
        // worst, and it would make the offer appear on every launch.
        let portable = TempDir::new().unwrap();
        write(portable.path(), "sites.json", "[]");
        assert_eq!(
            source_with_candidates(portable.path(), [portable.path().to_path_buf()]),
            None
        );
    }

    #[test]
    fn no_candidate_with_anything_new_means_no_offer() {
        let portable = TempDir::new().unwrap();
        let installed = TempDir::new().unwrap();
        write(portable.path(), "sites.json", "[]");
        write(installed.path(), "sites.json", "[]");
        // The portable folder already has it, so there is nothing to bring.
        assert_eq!(
            source_with_candidates(portable.path(), [installed.path().to_path_buf()]),
            None
        );
    }

    #[test]
    fn nothing_to_migrate_from_an_empty_standard_directory() {
        let portable = TempDir::new().unwrap();
        let standard = TempDir::new().unwrap();
        assert!(!has_migration_candidates(portable.path(), standard.path()));
        assert!(migration_candidates(standard.path()).is_empty());
    }

    #[test]
    fn a_file_present_only_in_the_standard_directory_is_a_candidate() {
        let portable = TempDir::new().unwrap();
        let standard = TempDir::new().unwrap();
        write(standard.path(), "sites.json", "[]");
        assert!(has_migration_candidates(portable.path(), standard.path()));
        assert_eq!(
            migration_candidates(standard.path()),
            vec![("Sites and connections", "sites.json")]
        );
    }

    #[test]
    fn a_file_already_in_the_portable_directory_is_not_re_offered() {
        let portable = TempDir::new().unwrap();
        let standard = TempDir::new().unwrap();
        write(standard.path(), "sites.json", "[]");
        write(portable.path(), "sites.json", "[]");
        assert!(!has_migration_candidates(portable.path(), standard.path()));
    }

    #[test]
    fn candidates_keep_the_catalogue_order() {
        let standard = TempDir::new().unwrap();
        write(standard.path(), "settings.json", "{}");
        write(standard.path(), "sites.json", "[]");
        let labels: Vec<&str> = migration_candidates(standard.path())
            .into_iter()
            .map(|(_, name)| name)
            .collect();
        assert_eq!(labels, vec!["sites.json", "settings.json"]);
    }

    #[test]
    fn migrating_copies_the_selected_files_and_leaves_the_source_intact() {
        let portable = TempDir::new().unwrap();
        let standard = TempDir::new().unwrap();
        write(standard.path(), "sites.json", "[1]");
        write(standard.path(), "settings.json", "{}");

        let copied = migrate_files(["sites.json"], standard.path(), portable.path()).unwrap();

        assert_eq!(copied, vec![portable.path().join("sites.json")]);
        assert_eq!(
            std::fs::read_to_string(portable.path().join("sites.json")).unwrap(),
            "[1]"
        );
        assert!(standard.path().join("sites.json").exists());
        // Only the selected file is copied.
        assert!(!portable.path().join("settings.json").exists());
    }

    #[test]
    fn migrating_creates_the_portable_directory_when_missing() {
        let standard = TempDir::new().unwrap();
        let parent = TempDir::new().unwrap();
        let portable = parent.path().join("data");
        write(standard.path(), "known_hosts", "host key");

        migrate_files(["known_hosts"], standard.path(), &portable).unwrap();

        assert!(portable.join("known_hosts").exists());
    }

    #[test]
    fn migrating_skips_names_that_do_not_exist() {
        let portable = TempDir::new().unwrap();
        let standard = TempDir::new().unwrap();
        let copied = migrate_files(
            ["sites.json", "vault.enc"],
            standard.path(),
            portable.path(),
        )
        .unwrap();
        assert!(copied.is_empty());
    }
}
