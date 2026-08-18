//! Portable-mode detection and configuration directory resolution.
//!
//! A portable install keeps everything beside the executable so the app can
//! live on a USB stick. It is signalled by a `.portable` marker file, a `data/`
//! directory, or the legacy `portable.txt` file next to the executable.

use std::path::{Path, PathBuf};

/// Marker files and directories that put the app into portable mode.
const PORTABLE_MARKER_FILES: [&str; 2] = [".portable", "portable.txt"];
const PORTABLE_DATA_DIR: &str = "data";

/// Directory name used for the per-user configuration when not portable.
const USER_CONFIG_DIR_NAME: &str = ".portkeydrop";

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

/// Resolve the configuration directory for a given executable and home
/// directory.
pub fn config_dir_for(exe_dir: &Path, home_dir: &Path) -> PathBuf {
    if is_portable_dir(exe_dir) {
        exe_dir.join(PORTABLE_DATA_DIR)
    } else {
        home_dir.join(USER_CONFIG_DIR_NAME)
    }
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
/// Portable installs use `<exe_dir>/data`; everything else uses
/// `~/.portkeydrop`.
pub fn config_dir() -> PathBuf {
    config_dir_for(&executable_dir(), &home_dir())
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
        let exe_dir = TempDir::new().unwrap();
        let home = TempDir::new().unwrap();
        std::fs::write(exe_dir.path().join(".portable"), b"").unwrap();
        assert_eq!(
            config_dir_for(exe_dir.path(), home.path()),
            exe_dir.path().join("data")
        );
    }

    #[test]
    fn standard_config_lives_under_the_home_directory() {
        let exe_dir = TempDir::new().unwrap();
        let home = TempDir::new().unwrap();
        assert_eq!(
            config_dir_for(exe_dir.path(), home.path()),
            home.path().join(".portkeydrop")
        );
    }

    #[test]
    fn known_hosts_sits_inside_the_config_directory() {
        let dir = TempDir::new().unwrap();
        assert_eq!(known_hosts_path(dir.path()), dir.path().join("known_hosts"));
    }
}
