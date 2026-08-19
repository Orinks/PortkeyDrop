//! Creating the configuration directory and its files so only the owner can
//! read them.
//!
//! The directory holds saved sites, accepted host keys, and -- where no system
//! keyring is available -- an encrypted vault of passwords. The vault's key is
//! derived from the machine and the user name, not from a secret the user
//! knows, so anyone who can read the file can also work out its key. Left to
//! the default umask a POSIX system writes it world-readable, which on a
//! shared machine hands every local account the saved passwords.
//!
//! Windows inherits an access control list from the user profile that already
//! restricts these to the owner, so there is nothing to add there.

use std::io;
use std::path::Path;

/// Permissions for the configuration directory: owner only, `rwx------`.
#[cfg(unix)]
const DIR_MODE: u32 = 0o700;

/// Permissions for a file inside it: owner only, `rw-------`.
#[cfg(unix)]
const FILE_MODE: u32 = 0o600;

/// Create `path` and every parent, restricting it to its owner.
///
/// Tightens an existing directory too: an install that predates this would
/// otherwise keep whatever the umask gave it the first time.
pub fn ensure_private_dir(path: &Path) -> io::Result<()> {
    std::fs::create_dir_all(path)?;
    restrict_dir(path)
}

/// Write `contents` to `path` so only its owner can read it.
///
/// The permissions are set before the bytes are written where the platform
/// allows it, so there is no window in which the file exists and is readable.
pub fn write_private(path: &Path, contents: impl AsRef<[u8]>) -> io::Result<()> {
    #[cfg(unix)]
    {
        use std::io::Write;
        use std::os::unix::fs::OpenOptionsExt;

        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .mode(FILE_MODE)
            .open(path)?;
        file.write_all(contents.as_ref())?;
        // `mode` only applies when the file is created, so an existing one
        // keeps whatever it had until this.
        restrict_file(path)?;
        file.sync_all()
    }
    #[cfg(not(unix))]
    {
        std::fs::write(path, contents)
    }
}

#[cfg(unix)]
fn restrict_dir(path: &Path) -> io::Result<()> {
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(DIR_MODE))
}

#[cfg(not(unix))]
fn restrict_dir(_path: &Path) -> io::Result<()> {
    Ok(())
}

#[cfg(unix)]
fn restrict_file(path: &Path) -> io::Result<()> {
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(FILE_MODE))
}

#[cfg(not(unix))]
#[allow(dead_code)]
fn restrict_file(_path: &Path) -> io::Result<()> {
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_new_directory_is_private() {
        let dir = tempfile::TempDir::new().unwrap();
        let target = dir.path().join("config");
        ensure_private_dir(&target).unwrap();
        assert!(target.is_dir());
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = std::fs::metadata(&target).unwrap().permissions().mode();
            assert_eq!(
                mode & 0o777,
                DIR_MODE,
                "config directory must be owner-only"
            );
        }
    }

    #[test]
    fn an_existing_open_directory_is_tightened() {
        // An install from before this change keeps the mode it was created
        // with; opening the app has to fix it rather than leave it.
        let dir = tempfile::TempDir::new().unwrap();
        let target = dir.path().join("config");
        std::fs::create_dir_all(&target).unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&target, std::fs::Permissions::from_mode(0o755)).unwrap();
            ensure_private_dir(&target).unwrap();
            let mode = std::fs::metadata(&target).unwrap().permissions().mode();
            assert_eq!(mode & 0o777, DIR_MODE);
        }
        #[cfg(not(unix))]
        ensure_private_dir(&target).unwrap();
    }

    #[test]
    fn a_written_file_is_private_and_keeps_its_contents() {
        let dir = tempfile::TempDir::new().unwrap();
        let path = dir.path().join("vault.enc");
        write_private(&path, b"ciphertext").unwrap();
        assert_eq!(std::fs::read(&path).unwrap(), b"ciphertext");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = std::fs::metadata(&path).unwrap().permissions().mode();
            assert_eq!(mode & 0o777, FILE_MODE, "the vault must be owner-only");
        }
    }

    #[test]
    fn rewriting_an_existing_readable_file_tightens_it() {
        let dir = tempfile::TempDir::new().unwrap();
        let path = dir.path().join("vault.enc");
        std::fs::write(&path, b"old").unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o644)).unwrap();
        }
        write_private(&path, b"new").unwrap();
        assert_eq!(std::fs::read(&path).unwrap(), b"new");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            let mode = std::fs::metadata(&path).unwrap().permissions().mode();
            assert_eq!(mode & 0o777, FILE_MODE);
        }
    }
}
