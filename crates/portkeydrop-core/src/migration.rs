//! Copying an existing installation's config into a portable data directory.
//!
//! Offered once, when a portable build starts next to an existing standard
//! install. Files are copied rather than moved so the original install keeps
//! working.

use std::path::{Path, PathBuf};

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

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn write(dir: &Path, name: &str, contents: &str) {
        std::fs::write(dir.join(name), contents).unwrap();
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
