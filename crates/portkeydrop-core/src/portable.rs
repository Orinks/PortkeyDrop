//! Portable-mode detection and configuration directory resolution.
//!
//! A portable install keeps everything beside the executable so the app can
//! live on a USB stick. It is signalled by a `.portable` marker file, a `data/`
//! directory, or the legacy `portable.txt` file next to the executable.
//!
//! Everything else uses the platform's own configuration folder. Earlier
//! releases used `~/.portkeydrop` on every system; that install is copied
//! across on the first start and left in place, so an older build keeps
//! working. The move buys convention and tidiness, not security -- both
//! locations sit inside the user's profile with the same permissions, and it
//! is `private_files` that restricts them.

use std::path::{Path, PathBuf};
use std::sync::OnceLock;

/// Marker files and directories that put the app into portable mode.
const PORTABLE_MARKER_FILES: [&str; 2] = [".portable", "portable.txt"];
const PORTABLE_DATA_DIR: &str = "data";

/// The old per-user configuration directory, directly in the home folder.
///
/// Still read: an install that predates the move keeps working, and its
/// contents are copied across the first time the app starts.
const LEGACY_CONFIG_DIR_NAME: &str = ".portkeydrop";

/// Directory name under the platform's configuration folder.
///
/// Capitalised on Windows and macOS, where application folders are, and lower
/// case under `~/.config`, where they are not.
#[cfg(any(windows, target_os = "macos"))]
const APP_CONFIG_DIR_NAME: &str = "PortkeyDrop";
#[cfg(not(any(windows, target_os = "macos")))]
const APP_CONFIG_DIR_NAME: &str = "portkeydrop";

/// Whether an executable directory carries portable-mode markers.
///
/// Kept separate from [`is_portable_mode`] so tests can drive it with a
/// temporary directory instead of the real executable location.
pub fn is_portable_dir(exe_dir: &Path) -> bool {
    if exe_dir.join(PORTABLE_DATA_DIR).is_dir() {
        return true;
    }
    PORTABLE_MARKER_FILES
        .iter()
        .any(|marker| exe_dir.join(marker).is_file())
}

/// Resolve the configuration directory.
///
/// `platform_config` is the system's own place for application configuration
/// -- `%APPDATA%`, `~/Library/Application Support`, `~/.config`. When the
/// platform will not say, the old home folder location is used, because
/// somewhere predictable beats somewhere arbitrary.
pub fn resolve_config_dir(
    exe_dir: &Path,
    platform_config: Option<&Path>,
    home_dir: &Path,
) -> PathBuf {
    if is_portable_dir(exe_dir) {
        return exe_dir.join(PORTABLE_DATA_DIR);
    }
    match platform_config {
        Some(base) => base.join(APP_CONFIG_DIR_NAME),
        None => home_dir.join(LEGACY_CONFIG_DIR_NAME),
    }
}

/// The old location, for reading an install that predates the move.
pub fn legacy_config_dir(home_dir: &Path) -> PathBuf {
    home_dir.join(LEGACY_CONFIG_DIR_NAME)
}

/// Where a standard, non-portable install keeps its configuration.
///
/// A portable build needs this to find an existing install to copy from; it is
/// never where a portable build writes.
pub fn standard_config_dir() -> PathBuf {
    match platform_config_dir() {
        Some(base) => base.join(APP_CONFIG_DIR_NAME),
        None => legacy_config_dir(&home_dir()),
    }
}

/// The platform's configuration folder, if it has one.
pub fn platform_config_dir() -> Option<PathBuf> {
    dirs::config_dir()
}

/// Copy an installation from the old home folder location into `target`.
///
/// Copied rather than moved: a downgrade, or a second copy of the app, still
/// finds what it expects. Does nothing when `target` already holds a
/// configuration, so this runs once and then stops.
///
/// A failure is reported but is not fatal to the caller -- starting with fresh
/// settings is a better outcome than refusing to start.
pub fn migrate_legacy_config(legacy: &Path, target: &Path) -> std::io::Result<Vec<PathBuf>> {
    if !legacy.is_dir() || target.join("settings.json").exists() {
        return Ok(Vec::new());
    }
    crate::private_files::ensure_private_dir(target)?;
    let mut copied = Vec::new();
    copy_tree(legacy, target, &mut copied)?;
    Ok(copied)
}

/// Copy a directory's contents, recursing into subdirectories.
///
/// Used for the whole configuration folder rather than a list of names, so a
/// file added later is not silently left behind on the old install.
fn copy_tree(from: &Path, to: &Path, copied: &mut Vec<PathBuf>) -> std::io::Result<()> {
    for entry in std::fs::read_dir(from)? {
        let entry = entry?;
        let source = entry.path();
        let destination = to.join(entry.file_name());
        if entry.file_type()?.is_dir() {
            std::fs::create_dir_all(&destination)?;
            copy_tree(&source, &destination, copied)?;
        } else if !destination.exists() {
            std::fs::copy(&source, &destination)?;
            copied.push(destination);
        }
    }
    Ok(())
}

/// The directory holding the running executable.
///
/// Falls back to the current working directory when the executable path cannot
/// be determined, which keeps startup working in unusual environments rather
/// than aborting.
pub fn executable_dir() -> PathBuf {
    std::env::current_exe()
        .ok()
        .and_then(|exe| exe.parent().map(Path::to_path_buf))
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_else(|_| PathBuf::from(".")))
}

/// The user's home directory, falling back to the current directory.
pub fn home_dir() -> PathBuf {
    dirs::home_dir().unwrap_or_else(|| PathBuf::from("."))
}

/// Whether the app is running in portable mode.
pub fn is_portable_mode() -> bool {
    is_portable_dir(&executable_dir())
}

/// The configuration directory for the current mode.
///
/// Portable installs use `<exe dir>/data`; everything else uses the
/// platform's configuration folder. Resolved once and remembered, because an
/// install that moves part way through a session would be worse than either
/// location on its own.
///
/// The first call also copies across an installation from the old home folder
/// location, so this has to happen before anything reads a setting.
pub fn config_dir() -> PathBuf {
    static RESOLVED: OnceLock<PathBuf> = OnceLock::new();
    RESOLVED
        .get_or_init(|| {
            let home = home_dir();
            let target =
                resolve_config_dir(&executable_dir(), platform_config_dir().as_deref(), &home);
            let legacy = legacy_config_dir(&home);
            if legacy != target {
                match migrate_legacy_config(&legacy, &target) {
                    Ok(copied) if !copied.is_empty() => log::info!(
                        "copied {} configuration files from {} to {}",
                        copied.len(),
                        legacy.display(),
                        target.display()
                    ),
                    Ok(_) => {}
                    Err(err) => log::warn!(
                        "could not copy the configuration from {}: {err}",
                        legacy.display()
                    ),
                }
            }
            target
        })
        .clone()
}

/// Path to the known-hosts file used for SSH host key verification.
pub fn known_hosts_path(config_dir: &Path) -> PathBuf {
    config_dir.join("known_hosts")
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn a_bare_directory_is_not_portable() {
        let dir = TempDir::new().unwrap();
        assert!(!is_portable_dir(dir.path()));
    }

    #[test]
    fn a_dot_portable_marker_enables_portable_mode() {
        let dir = TempDir::new().unwrap();
        std::fs::write(dir.path().join(".portable"), b"").unwrap();
        assert!(is_portable_dir(dir.path()));
    }

    #[test]
    fn a_legacy_portable_txt_marker_enables_portable_mode() {
        let dir = TempDir::new().unwrap();
        std::fs::write(dir.path().join("portable.txt"), b"").unwrap();
        assert!(is_portable_dir(dir.path()));
    }

    #[test]
    fn a_data_directory_enables_portable_mode() {
        let dir = TempDir::new().unwrap();
        std::fs::create_dir(dir.path().join("data")).unwrap();
        assert!(is_portable_dir(dir.path()));
    }

    #[test]
    fn a_data_file_does_not_enable_portable_mode() {
        // Only a directory counts; a stray file named `data` must not flip the
        // app into portable mode.
        let dir = TempDir::new().unwrap();
        std::fs::write(dir.path().join("data"), b"").unwrap();
        assert!(!is_portable_dir(dir.path()));
    }

    #[test]
    fn portable_config_lives_next_to_the_executable() {
        // Portable wins over the platform folder: the whole point is that the
        // configuration travels on the stick with the app.
        let exe_dir = TempDir::new().unwrap();
        let home = TempDir::new().unwrap();
        let platform = TempDir::new().unwrap();
        std::fs::write(exe_dir.path().join(".portable"), b"").unwrap();
        assert_eq!(
            resolve_config_dir(exe_dir.path(), Some(platform.path()), home.path()),
            exe_dir.path().join("data")
        );
    }

    #[test]
    fn an_installed_copy_uses_the_platform_config_folder() {
        let exe_dir = TempDir::new().unwrap();
        let home = TempDir::new().unwrap();
        let platform = TempDir::new().unwrap();
        assert_eq!(
            resolve_config_dir(exe_dir.path(), Some(platform.path()), home.path()),
            platform.path().join(APP_CONFIG_DIR_NAME)
        );
    }

    #[test]
    fn without_a_platform_folder_the_old_home_location_is_used() {
        // Somewhere predictable beats somewhere arbitrary when the platform
        // will not say where configuration belongs.
        let exe_dir = TempDir::new().unwrap();
        let home = TempDir::new().unwrap();
        assert_eq!(
            resolve_config_dir(exe_dir.path(), None, home.path()),
            home.path().join(".portkeydrop")
        );
    }

    #[test]
    fn an_existing_installation_is_copied_to_the_new_location() {
        let home = TempDir::new().unwrap();
        let target = TempDir::new().unwrap();
        let legacy = legacy_config_dir(home.path());
        std::fs::create_dir_all(legacy.join("soundpacks").join("default")).unwrap();
        std::fs::write(legacy.join("settings.json"), b"{}").unwrap();
        std::fs::write(legacy.join("sites.json"), b"[]").unwrap();
        std::fs::write(legacy.join("vault.enc"), b"secret").unwrap();
        std::fs::write(legacy.join("soundpacks/default/pack.json"), b"{}").unwrap();

        let copied = migrate_legacy_config(&legacy, target.path()).unwrap();

        assert_eq!(copied.len(), 4, "copied: {copied:?}");
        assert_eq!(
            std::fs::read(target.path().join("vault.enc")).unwrap(),
            b"secret"
        );
        // Sound packs live in a subdirectory; copying only the top level would
        // silently lose them.
        assert!(target.path().join("soundpacks/default/pack.json").is_file());
        // The original is left alone, so an older build still works.
        assert!(legacy.join("settings.json").is_file());
    }

    #[test]
    fn a_second_start_does_not_copy_again() {
        // Otherwise a file deleted on purpose in the new location would come
        // back from the old one at every launch.
        let home = TempDir::new().unwrap();
        let target = TempDir::new().unwrap();
        let legacy = legacy_config_dir(home.path());
        std::fs::create_dir_all(&legacy).unwrap();
        std::fs::write(legacy.join("settings.json"), b"{\"old\": true}").unwrap();

        migrate_legacy_config(&legacy, target.path()).unwrap();
        std::fs::write(target.path().join("settings.json"), b"{\"new\": true}").unwrap();
        let second = migrate_legacy_config(&legacy, target.path()).unwrap();

        assert!(second.is_empty());
        assert_eq!(
            std::fs::read(target.path().join("settings.json")).unwrap(),
            b"{\"new\": true}",
            "the settings in use must not be overwritten by the old copy"
        );
    }

    #[test]
    fn nothing_to_migrate_is_not_an_error() {
        let home = TempDir::new().unwrap();
        let target = TempDir::new().unwrap();
        let copied = migrate_legacy_config(&legacy_config_dir(home.path()), target.path()).unwrap();
        assert!(copied.is_empty());
    }

    #[test]
    fn known_hosts_sits_inside_the_config_directory() {
        let dir = TempDir::new().unwrap();
        assert_eq!(known_hosts_path(dir.path()), dir.path().join("known_hosts"));
    }
}
