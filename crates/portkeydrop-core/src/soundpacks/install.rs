//! Installing and exporting sound packs as ZIP archives.
//!
//! A downloaded pack is untrusted input. Every archive member is checked to
//! land inside the destination before anything is written, so an archive
//! containing `../../autorun` cannot escape the packs directory.

use std::io::{Read, Seek};
use std::path::{Component, Path, PathBuf};

use super::{slugify_pack_name, validate_pack, PackError, DEFAULT_PACK, MANIFEST_FILE_NAME};

/// Why an install or export failed.
#[derive(Debug, thiserror::Error)]
pub enum InstallError {
    #[error("the file was not found: {0}")]
    NotFound(PathBuf),
    #[error("that file is not a valid ZIP archive")]
    NotAZip,
    #[error("the archive has no {MANIFEST_FILE_NAME} file")]
    NoManifest,
    #[error("this is not a usable sound pack: {0}")]
    InvalidPack(#[from] PackError),
    #[error("a sound pack named '{0}' is already installed")]
    AlreadyInstalled(String),
    #[error("the built-in default sound pack cannot be removed")]
    CannotRemoveDefault,
    #[error("no sound pack named '{0}' is installed")]
    NotInstalled(String),
    #[error(
        "the archive entry '{0}' would be written outside the sound packs folder, so the \
         archive was rejected"
    )]
    UnsafeEntry(String),
    #[error("the archive could not be read: {0}")]
    Zip(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
}

impl From<zip::result::ZipError> for InstallError {
    fn from(err: zip::result::ZipError) -> Self {
        match err {
            zip::result::ZipError::Io(err) => InstallError::Io(err),
            zip::result::ZipError::InvalidArchive(_)
            | zip::result::ZipError::UnsupportedArchive(_) => InstallError::NotAZip,
            other => InstallError::Zip(other.to_string()),
        }
    }
}

/// Whether an archive member name is safe to extract under `root`.
///
/// Rejects absolute paths, drive letters, and any `..` component. Checking the
/// name rather than the resolved path means the decision does not depend on
/// what already exists on disk.
pub fn is_safe_archive_name(name: &str) -> bool {
    if name.is_empty() {
        return false;
    }
    let path = Path::new(name);
    if path.is_absolute() {
        return false;
    }
    // A Windows archive may carry a backslash-separated name.
    if name.starts_with('/') || name.starts_with('\\') || name.contains(':') {
        return false;
    }
    path.components()
        .all(|component| matches!(component, Component::Normal(_)))
        && !name.split(['/', '\\']).any(|segment| segment == "..")
}

/// Extract an archive under `destination`, rejecting unsafe members.
pub fn extract_safely<R: Read + Seek>(
    archive: &mut zip::ZipArchive<R>,
    destination: &Path,
) -> Result<(), InstallError> {
    // Validate every name before writing anything, so a rejected archive
    // leaves nothing behind.
    for index in 0..archive.len() {
        let entry = archive.by_index(index)?;
        let name = entry.name().to_string();
        if !is_safe_archive_name(&name) {
            return Err(InstallError::UnsafeEntry(name));
        }
    }

    for index in 0..archive.len() {
        let mut entry = archive.by_index(index)?;
        let name = entry.name().replace('\\', "/");
        let target = destination.join(&name);

        if entry.is_dir() {
            std::fs::create_dir_all(&target)?;
            continue;
        }
        if let Some(parent) = target.parent() {
            std::fs::create_dir_all(parent)?;
        }
        let mut file = std::fs::File::create(&target)?;
        std::io::copy(&mut entry, &mut file)?;
    }
    Ok(())
}

/// Installs, exports, and removes packs in one directory.
pub struct PackInstaller {
    soundpacks_dir: PathBuf,
}

impl PackInstaller {
    /// Manage packs in `soundpacks_dir`, creating it if needed.
    pub fn new(soundpacks_dir: PathBuf) -> std::io::Result<Self> {
        std::fs::create_dir_all(&soundpacks_dir)?;
        Ok(Self { soundpacks_dir })
    }

    /// The directory this installer manages.
    pub fn soundpacks_dir(&self) -> &Path {
        &self.soundpacks_dir
    }

    /// Install a pack from a ZIP archive, returning its directory name.
    ///
    /// The archive is unpacked to a temporary directory and validated before
    /// anything reaches the packs folder, so a bad archive cannot leave a
    /// half-installed pack behind.
    pub fn install_from_zip(
        &self,
        zip_path: &Path,
        preferred_name: Option<&str>,
    ) -> Result<String, InstallError> {
        if !zip_path.is_file() {
            return Err(InstallError::NotFound(zip_path.to_path_buf()));
        }

        let file = std::fs::File::open(zip_path)?;
        let mut archive = zip::ZipArchive::new(file).map_err(|_| InstallError::NotAZip)?;

        let staging = tempfile::tempdir()?;
        extract_safely(&mut archive, staging.path())?;

        let pack_root = find_pack_root(staging.path()).ok_or(InstallError::NoManifest)?;
        let manifest = validate_pack(&pack_root)?;

        let fallback = zip_path
            .file_stem()
            .map(|stem| stem.to_string_lossy().into_owned())
            .unwrap_or_else(|| "sound_pack".to_string());
        let source_name = preferred_name
            .map(str::to_string)
            .filter(|name| !name.trim().is_empty())
            .or_else(|| Some(manifest.name.clone()).filter(|name| !name.trim().is_empty()))
            .unwrap_or_else(|| fallback.clone());
        let directory =
            slugify_pack_name(&source_name, &slugify_pack_name(&fallback, "sound_pack"));

        let target = self.soundpacks_dir.join(&directory);
        if target.exists() {
            return Err(InstallError::AlreadyInstalled(directory));
        }
        copy_tree(&pack_root, &target)?;
        Ok(directory)
    }

    /// Write a pack to a ZIP archive.
    pub fn export_pack(&self, directory: &str, output_path: &Path) -> Result<(), InstallError> {
        let pack = self.soundpacks_dir.join(directory);
        if !pack.is_dir() {
            return Err(InstallError::NotInstalled(directory.to_string()));
        }

        let file = std::fs::File::create(output_path)?;
        let mut writer = zip::ZipWriter::new(file);
        let options: zip::write::FileOptions<()> =
            zip::write::FileOptions::default().compression_method(zip::CompressionMethod::Deflated);

        for entry in walk_files(&pack) {
            let relative = entry
                .strip_prefix(&pack)
                .expect("walk_files only yields paths under the pack")
                .to_string_lossy()
                .replace('\\', "/");
            writer.start_file(relative, options)?;
            let mut source = std::fs::File::open(&entry)?;
            std::io::copy(&mut source, &mut writer)?;
        }
        writer.finish()?;
        Ok(())
    }

    /// Remove an installed pack.
    ///
    /// The built-in default cannot be removed: it is the fallback every other
    /// pack relies on for events it does not define.
    pub fn uninstall(&self, directory: &str) -> Result<(), InstallError> {
        if directory == DEFAULT_PACK {
            return Err(InstallError::CannotRemoveDefault);
        }
        let pack = self.soundpacks_dir.join(directory);
        if !pack.is_dir() {
            return Err(InstallError::NotInstalled(directory.to_string()));
        }
        std::fs::remove_dir_all(pack)?;
        Ok(())
    }
}

/// Find the directory holding `pack.json`, at any depth.
///
/// Archives are commonly wrapped in a top-level folder, so the manifest is
/// rarely at the root.
fn find_pack_root(root: &Path) -> Option<PathBuf> {
    if root.join(MANIFEST_FILE_NAME).is_file() {
        return Some(root.to_path_buf());
    }
    let entries = std::fs::read_dir(root).ok()?;
    let mut directories: Vec<PathBuf> = entries
        .flatten()
        .map(|entry| entry.path())
        .filter(|path| path.is_dir())
        .collect();
    directories.sort();
    directories
        .iter()
        .find_map(|directory| find_pack_root(directory))
}

/// Every file under `root`, in a stable order.
fn walk_files(root: &Path) -> Vec<PathBuf> {
    let mut files = Vec::new();
    let mut stack = vec![root.to_path_buf()];
    while let Some(directory) = stack.pop() {
        let Ok(entries) = std::fs::read_dir(&directory) else {
            continue;
        };
        let mut paths: Vec<PathBuf> = entries.flatten().map(|entry| entry.path()).collect();
        paths.sort();
        for path in paths {
            if path.is_dir() {
                stack.push(path);
            } else {
                files.push(path);
            }
        }
    }
    files.sort();
    files
}

/// Recursively copy a directory.
fn copy_tree(source: &Path, destination: &Path) -> std::io::Result<()> {
    std::fs::create_dir_all(destination)?;
    for entry in std::fs::read_dir(source)? {
        let entry = entry?;
        let target = destination.join(entry.file_name());
        if entry.file_type()?.is_dir() {
            copy_tree(&entry.path(), &target)?;
        } else {
            std::fs::copy(entry.path(), target)?;
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    const MANIFEST: &str = r#"{"name":"Retro Beeps","sounds":{"error":"e.ogg"}}"#;

    /// Build a ZIP from `(name, contents)` pairs.
    fn build_zip(path: &Path, entries: &[(&str, &[u8])]) {
        use std::io::Write;
        let file = std::fs::File::create(path).unwrap();
        let mut writer = zip::ZipWriter::new(file);
        let options: zip::write::FileOptions<()> = zip::write::FileOptions::default();
        for (name, contents) in entries {
            writer.start_file(*name, options).unwrap();
            writer.write_all(contents).unwrap();
        }
        writer.finish().unwrap();
    }

    fn installer(dir: &TempDir) -> PackInstaller {
        PackInstaller::new(dir.path().join("soundpacks")).unwrap()
    }

    #[test]
    fn ordinary_relative_names_are_safe() {
        assert!(is_safe_archive_name("pack.json"));
        assert!(is_safe_archive_name("transfers/done.ogg"));
        assert!(is_safe_archive_name("a/b/c/d.wav"));
    }

    #[test]
    fn traversal_and_absolute_names_are_rejected() {
        // These are the shapes a malicious pack would use to write outside the
        // packs folder.
        assert!(!is_safe_archive_name("../escape.txt"));
        assert!(!is_safe_archive_name("pack/../../escape.txt"));
        assert!(!is_safe_archive_name("/etc/passwd"));
        assert!(!is_safe_archive_name(r"C:\Windows\system32\evil.dll"));
        assert!(!is_safe_archive_name(r"..\escape.txt"));
        assert!(!is_safe_archive_name(""));
    }

    #[test]
    fn a_valid_archive_installs() {
        let dir = TempDir::new().unwrap();
        let zip_path = dir.path().join("pack.zip");
        build_zip(
            &zip_path,
            &[("pack.json", MANIFEST.as_bytes()), ("e.ogg", b"audio")],
        );

        let installer = installer(&dir);
        let directory = installer.install_from_zip(&zip_path, None).unwrap();

        assert_eq!(directory, "retro_beeps");
        assert!(installer
            .soundpacks_dir()
            .join("retro_beeps")
            .join("pack.json")
            .exists());
        assert!(installer
            .soundpacks_dir()
            .join("retro_beeps")
            .join("e.ogg")
            .exists());
    }

    #[test]
    fn an_archive_wrapped_in_a_folder_installs() {
        let dir = TempDir::new().unwrap();
        let zip_path = dir.path().join("pack.zip");
        build_zip(
            &zip_path,
            &[
                ("retro/pack.json", MANIFEST.as_bytes()),
                ("retro/e.ogg", b"audio"),
            ],
        );

        let installer = installer(&dir);
        assert_eq!(
            installer.install_from_zip(&zip_path, None).unwrap(),
            "retro_beeps"
        );
    }

    #[test]
    fn a_traversal_archive_is_rejected_and_writes_nothing() {
        let dir = TempDir::new().unwrap();
        let zip_path = dir.path().join("evil.zip");
        build_zip(
            &zip_path,
            &[
                ("pack.json", MANIFEST.as_bytes()),
                ("../escaped.txt", b"owned"),
            ],
        );

        let installer = installer(&dir);
        let error = installer.install_from_zip(&zip_path, None).unwrap_err();

        assert!(matches!(error, InstallError::UnsafeEntry(_)));
        assert!(!dir.path().join("escaped.txt").exists());
        assert!(!installer.soundpacks_dir().join("retro_beeps").exists());
    }

    #[test]
    fn an_archive_without_a_manifest_is_rejected() {
        let dir = TempDir::new().unwrap();
        let zip_path = dir.path().join("pack.zip");
        build_zip(&zip_path, &[("e.ogg", b"audio")]);
        assert!(matches!(
            installer(&dir).install_from_zip(&zip_path, None),
            Err(InstallError::NoManifest)
        ));
    }

    #[test]
    fn an_archive_whose_manifest_names_missing_files_is_rejected() {
        let dir = TempDir::new().unwrap();
        let zip_path = dir.path().join("pack.zip");
        build_zip(&zip_path, &[("pack.json", MANIFEST.as_bytes())]);
        assert!(matches!(
            installer(&dir).install_from_zip(&zip_path, None),
            Err(InstallError::InvalidPack(PackError::MissingFiles(_)))
        ));
    }

    #[test]
    fn a_file_that_is_not_a_zip_is_rejected() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("notazip.zip");
        std::fs::write(&path, b"just text").unwrap();
        assert!(matches!(
            installer(&dir).install_from_zip(&path, None),
            Err(InstallError::NotAZip)
        ));
    }

    #[test]
    fn a_missing_archive_is_reported() {
        let dir = TempDir::new().unwrap();
        assert!(matches!(
            installer(&dir).install_from_zip(&dir.path().join("nope.zip"), None),
            Err(InstallError::NotFound(_))
        ));
    }

    #[test]
    fn installing_over_an_existing_pack_is_refused() {
        let dir = TempDir::new().unwrap();
        let zip_path = dir.path().join("pack.zip");
        build_zip(
            &zip_path,
            &[("pack.json", MANIFEST.as_bytes()), ("e.ogg", b"audio")],
        );

        let installer = installer(&dir);
        installer.install_from_zip(&zip_path, None).unwrap();
        assert!(matches!(
            installer.install_from_zip(&zip_path, None),
            Err(InstallError::AlreadyInstalled(name)) if name == "retro_beeps"
        ));
    }

    #[test]
    fn a_preferred_name_overrides_the_manifest_name() {
        let dir = TempDir::new().unwrap();
        let zip_path = dir.path().join("pack.zip");
        build_zip(
            &zip_path,
            &[("pack.json", MANIFEST.as_bytes()), ("e.ogg", b"audio")],
        );
        assert_eq!(
            installer(&dir)
                .install_from_zip(&zip_path, Some("My Pack"))
                .unwrap(),
            "my_pack"
        );
    }

    #[test]
    fn a_pack_round_trips_through_export_and_install() {
        let dir = TempDir::new().unwrap();
        let zip_path = dir.path().join("pack.zip");
        build_zip(
            &zip_path,
            &[
                ("pack.json", MANIFEST.as_bytes()),
                ("e.ogg", b"audio"),
                ("sub/x.ogg", b"more"),
            ],
        );

        let installer = installer(&dir);
        installer.install_from_zip(&zip_path, None).unwrap();

        let exported = dir.path().join("exported.zip");
        installer.export_pack("retro_beeps", &exported).unwrap();
        installer.uninstall("retro_beeps").unwrap();
        installer.install_from_zip(&exported, None).unwrap();

        let root = installer.soundpacks_dir().join("retro_beeps");
        assert!(root.join("pack.json").exists());
        assert!(root.join("e.ogg").exists());
        assert!(root.join("sub").join("x.ogg").exists());
    }

    #[test]
    fn exporting_a_pack_that_is_not_installed_is_reported() {
        let dir = TempDir::new().unwrap();
        assert!(matches!(
            installer(&dir).export_pack("nope", &dir.path().join("out.zip")),
            Err(InstallError::NotInstalled(_))
        ));
    }

    #[test]
    fn the_default_pack_cannot_be_removed() {
        // Every other pack falls back to it for events it does not define.
        let dir = TempDir::new().unwrap();
        let installer = installer(&dir);
        std::fs::create_dir_all(installer.soundpacks_dir().join(DEFAULT_PACK)).unwrap();
        assert!(matches!(
            installer.uninstall(DEFAULT_PACK),
            Err(InstallError::CannotRemoveDefault)
        ));
        assert!(installer.soundpacks_dir().join(DEFAULT_PACK).exists());
    }

    #[test]
    fn uninstalling_a_pack_that_is_not_installed_is_reported() {
        let dir = TempDir::new().unwrap();
        assert!(matches!(
            installer(&dir).uninstall("nope"),
            Err(InstallError::NotInstalled(_))
        ));
    }
}
