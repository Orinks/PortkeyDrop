//! Local filesystem browsing, returning the same row type as the remote pane.
//!
//! Both panes render [`RemoteFile`] so one formatter and one selection model
//! serve local and remote listings alike.

use std::path::{Path, PathBuf};

use chrono::{DateTime, Local};

use crate::protocols::RemoteFile;

/// List a local directory.
///
/// Entries that cannot be stat'd are still returned, marked with `?`
/// permissions, so a single unreadable file does not blank the pane. An
/// unreadable *directory* yields an error, because there is nothing to show.
pub fn list_local_dir(directory: &Path) -> std::io::Result<Vec<RemoteFile>> {
    let mut files = Vec::new();
    for entry in std::fs::read_dir(directory)? {
        let Ok(entry) = entry else {
            continue;
        };
        let name = entry.file_name().to_string_lossy().into_owned();
        let path = entry.path().to_string_lossy().into_owned();

        match entry.metadata() {
            Ok(metadata) => {
                let is_dir = metadata.is_dir();
                files.push(RemoteFile {
                    name,
                    path,
                    size: if is_dir { 0 } else { metadata.len() },
                    is_dir,
                    modified: modified_time(&metadata),
                    permissions: permission_string(&metadata),
                    owner: String::new(),
                    group: String::new(),
                });
            }
            Err(err) => {
                log::debug!("cannot stat {}: {err}", entry.path().display());
                files.push(RemoteFile {
                    name,
                    path,
                    permissions: "?".to_string(),
                    ..Default::default()
                });
            }
        }
    }
    Ok(files)
}

/// Modification time as naive local time, matching how remote times display.
fn modified_time(metadata: &std::fs::Metadata) -> Option<chrono::NaiveDateTime> {
    let modified = metadata.modified().ok()?;
    let datetime: DateTime<Local> = modified.into();
    Some(datetime.naive_local())
}

/// A `ls -l` style permission string.
///
/// On Windows there is no mode word, so this reports the type character plus
/// read/write state, which is what the platform actually distinguishes.
fn permission_string(metadata: &std::fs::Metadata) -> String {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        format_mode(metadata.permissions().mode())
    }
    #[cfg(not(unix))]
    {
        let type_char = if metadata.is_dir() { 'd' } else { '-' };
        let write = if metadata.permissions().readonly() {
            '-'
        } else {
            'w'
        };
        format!("{type_char}r{write}-")
    }
}

/// Render a Unix mode word the way `ls -l` does.
pub fn format_mode(mode: u32) -> String {
    const S_IFMT: u32 = 0o170000;
    let type_char = match mode & S_IFMT {
        0o040000 => 'd',
        0o120000 => 'l',
        0o140000 => 's',
        0o010000 => 'p',
        0o060000 => 'b',
        0o020000 => 'c',
        _ => '-',
    };

    let mut out = String::with_capacity(10);
    out.push(type_char);
    for shift in [6, 3, 0] {
        let bits = (mode >> shift) & 0o7;
        out.push(if bits & 0o4 != 0 { 'r' } else { '-' });
        out.push(if bits & 0o2 != 0 { 'w' } else { '-' });
        out.push(if bits & 0o1 != 0 { 'x' } else { '-' });
    }
    // Overlay the setuid/setgid/sticky bits onto the execute positions.
    let mut chars: Vec<char> = out.chars().collect();
    if mode & 0o4000 != 0 {
        chars[3] = if chars[3] == 'x' { 's' } else { 'S' };
    }
    if mode & 0o2000 != 0 {
        chars[6] = if chars[6] == 'x' { 's' } else { 'S' };
    }
    if mode & 0o1000 != 0 {
        chars[9] = if chars[9] == 'x' { 't' } else { 'T' };
    }
    chars.into_iter().collect()
}

/// Move into `target` relative to `current`, returning the resolved path.
pub fn navigate_local(current: &Path, target: &str) -> std::io::Result<PathBuf> {
    let candidate = current.join(target);
    let resolved = candidate.canonicalize()?;
    if !resolved.is_dir() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::NotADirectory,
            format!("{} is not a directory", resolved.display()),
        ));
    }
    Ok(resolved)
}

/// The parent of `current`, or `current` itself when already at a root.
pub fn parent_local(current: &Path) -> PathBuf {
    let resolved = current
        .canonicalize()
        .unwrap_or_else(|_| current.to_path_buf());
    resolved.parent().map(Path::to_path_buf).unwrap_or(resolved)
}

/// Delete a local file or directory tree.
pub fn delete_local(path: &Path) -> std::io::Result<()> {
    if path.is_dir() {
        std::fs::remove_dir_all(path)
    } else {
        std::fs::remove_file(path)
    }
}

/// Rename an entry in place, returning the new path.
pub fn rename_local(old_path: &Path, new_name: &str) -> std::io::Result<PathBuf> {
    let parent = old_path.parent().unwrap_or_else(|| Path::new("."));
    let new_path = parent.join(new_name);
    std::fs::rename(old_path, &new_path)?;
    Ok(new_path)
}

/// Create a directory, failing if it already exists.
pub fn mkdir_local(parent: &Path, name: &str) -> std::io::Result<PathBuf> {
    let new_dir = parent.join(name);
    std::fs::create_dir(&new_dir)?;
    Ok(new_dir)
}

/// A destination path that does not collide with an existing file.
///
/// Appends ` (1)`, ` (2)`, ... before the extension, matching what browsers and
/// file managers do.
pub fn unique_local_path(path: &Path) -> PathBuf {
    if !path.exists() {
        return path.to_path_buf();
    }
    let parent = path.parent().unwrap_or_else(|| Path::new("."));
    let stem = path
        .file_stem()
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_default();
    let extension = path
        .extension()
        .map(|s| format!(".{}", s.to_string_lossy()))
        .unwrap_or_default();

    for counter in 1..10_000 {
        let candidate = parent.join(format!("{stem} ({counter}){extension}"));
        if !candidate.exists() {
            return candidate;
        }
    }
    path.to_path_buf()
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn listing_reports_files_and_directories() {
        let dir = TempDir::new().unwrap();
        std::fs::write(dir.path().join("notes.txt"), b"hello").unwrap();
        std::fs::create_dir(dir.path().join("docs")).unwrap();

        let mut files = list_local_dir(dir.path()).unwrap();
        files.sort_by(|a, b| a.name.cmp(&b.name));

        assert_eq!(files.len(), 2);
        assert_eq!(files[0].name, "docs");
        assert!(files[0].is_dir);
        assert_eq!(files[0].size, 0);
        assert_eq!(files[1].name, "notes.txt");
        assert!(!files[1].is_dir);
        assert_eq!(files[1].size, 5);
        assert!(files[1].modified.is_some());
    }

    #[test]
    fn listing_an_empty_directory_yields_no_rows() {
        let dir = TempDir::new().unwrap();
        assert!(list_local_dir(dir.path()).unwrap().is_empty());
    }

    #[test]
    fn listing_a_missing_directory_is_an_error() {
        assert!(list_local_dir(Path::new("/definitely/not/here")).is_err());
    }

    #[test]
    fn mode_words_render_like_ls() {
        assert_eq!(format_mode(0o100644), "-rw-r--r--");
        assert_eq!(format_mode(0o040755), "drwxr-xr-x");
        assert_eq!(format_mode(0o120777), "lrwxrwxrwx");
        assert_eq!(format_mode(0o100000), "----------");
    }

    #[test]
    fn special_mode_bits_overlay_the_execute_positions() {
        assert_eq!(format_mode(0o104755), "-rwsr-xr-x");
        assert_eq!(format_mode(0o102755), "-rwxr-sr-x");
        assert_eq!(format_mode(0o041777), "drwxrwxrwt");
        // Without the execute bit the marker is uppercase.
        assert_eq!(format_mode(0o104644), "-rwSr--r--");
    }

    #[test]
    fn navigating_into_a_subdirectory_resolves_it() {
        let dir = TempDir::new().unwrap();
        std::fs::create_dir(dir.path().join("docs")).unwrap();
        let moved = navigate_local(dir.path(), "docs").unwrap();
        assert_eq!(moved, dir.path().join("docs").canonicalize().unwrap());
    }

    #[test]
    fn navigating_into_a_file_is_rejected() {
        let dir = TempDir::new().unwrap();
        std::fs::write(dir.path().join("notes.txt"), b"x").unwrap();
        assert!(navigate_local(dir.path(), "notes.txt").is_err());
    }

    #[test]
    fn the_parent_of_a_subdirectory_is_its_container() {
        let dir = TempDir::new().unwrap();
        let child = dir.path().join("docs");
        std::fs::create_dir(&child).unwrap();
        assert_eq!(parent_local(&child), dir.path().canonicalize().unwrap());
    }

    #[test]
    fn deleting_removes_files_and_whole_trees() {
        let dir = TempDir::new().unwrap();
        let file = dir.path().join("notes.txt");
        std::fs::write(&file, b"x").unwrap();
        delete_local(&file).unwrap();
        assert!(!file.exists());

        let tree = dir.path().join("tree");
        std::fs::create_dir(&tree).unwrap();
        std::fs::write(tree.join("inner.txt"), b"x").unwrap();
        delete_local(&tree).unwrap();
        assert!(!tree.exists());
    }

    #[test]
    fn renaming_keeps_the_entry_in_its_directory() {
        let dir = TempDir::new().unwrap();
        let old = dir.path().join("before.txt");
        std::fs::write(&old, b"x").unwrap();
        let new = rename_local(&old, "after.txt").unwrap();
        assert_eq!(new, dir.path().join("after.txt"));
        assert!(new.exists());
        assert!(!old.exists());
    }

    #[test]
    fn creating_an_existing_directory_is_an_error() {
        let dir = TempDir::new().unwrap();
        mkdir_local(dir.path(), "docs").unwrap();
        assert!(mkdir_local(dir.path(), "docs").is_err());
    }

    #[test]
    fn a_free_path_is_returned_unchanged() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("notes.txt");
        assert_eq!(unique_local_path(&path), path);
    }

    #[test]
    fn a_taken_path_gains_a_counter_before_the_extension() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("notes.txt");
        std::fs::write(&path, b"x").unwrap();
        assert_eq!(unique_local_path(&path), dir.path().join("notes (1).txt"));

        std::fs::write(dir.path().join("notes (1).txt"), b"x").unwrap();
        assert_eq!(unique_local_path(&path), dir.path().join("notes (2).txt"));
    }

    #[test]
    fn extensionless_names_still_get_a_counter() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("README");
        std::fs::write(&path, b"x").unwrap();
        assert_eq!(unique_local_path(&path), dir.path().join("README (1)"));
    }
}
