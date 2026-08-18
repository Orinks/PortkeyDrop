//! POSIX path helpers for remote paths.
//!
//! Remote paths are always `/`-separated regardless of the client's platform,
//! so `std::path` (which uses `\` on Windows) cannot be used for them.

/// Join a base directory and a child name into a remote path.
///
/// A trailing slash on `base` is not duplicated, and an absolute `child`
/// replaces `base` entirely.
pub fn join(base: &str, child: &str) -> String {
    if child.starts_with('/') {
        return normalize(child);
    }
    let base = base.trim_end_matches('/');
    if base.is_empty() {
        format!("/{}", child.trim_start_matches('/'))
    } else {
        format!("{base}/{child}")
    }
}

/// The parent directory of a remote path.
///
/// The parent of `/` is `/`, matching how the file panes stop at the root
/// instead of walking off the top.
pub fn parent(path: &str) -> String {
    let trimmed = path.trim_end_matches('/');
    if trimmed.is_empty() {
        return "/".to_string();
    }
    match trimmed.rsplit_once('/') {
        Some(("", _)) => "/".to_string(),
        Some((head, _)) => head.to_string(),
        None => "/".to_string(),
    }
}

/// The final component of a remote path.
pub fn file_name(path: &str) -> &str {
    let trimmed = path.trim_end_matches('/');
    match trimmed.rsplit_once('/') {
        Some((_, name)) => name,
        None => trimmed,
    }
}

/// Collapse duplicate separators and strip a trailing slash.
///
/// The root path stays `/`. `.` and `..` are left alone: the server resolves
/// those, and rewriting them locally would break symlinked paths.
pub fn normalize(path: &str) -> String {
    if path.is_empty() {
        return "/".to_string();
    }
    let leading_slash = path.starts_with('/');
    let mut result = String::with_capacity(path.len());
    if leading_slash {
        result.push('/');
    }
    let mut first = true;
    for segment in path.split('/').filter(|segment| !segment.is_empty()) {
        if !first {
            result.push('/');
        }
        result.push_str(segment);
        first = false;
    }
    if result.is_empty() {
        ".".to_string()
    } else {
        result
    }
}

/// Resolve `path` against `cwd`, leaving absolute paths alone.
pub fn resolve(cwd: &str, path: &str) -> String {
    if path.is_empty() || path == "." {
        return normalize(cwd);
    }
    if path.starts_with('/') {
        return normalize(path);
    }
    join(cwd, path)
}

/// Convert a local filesystem path into a remote-style path.
///
/// Used when mirroring a local directory tree onto a server from Windows,
/// where `std::path` produced `\` separators.
pub fn from_local(path: &std::path::Path) -> String {
    path.to_string_lossy().replace('\\', "/")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn joining_appends_a_single_separator() {
        assert_eq!(join("/home/user", "notes.txt"), "/home/user/notes.txt");
        assert_eq!(join("/home/user/", "notes.txt"), "/home/user/notes.txt");
        assert_eq!(join("/", "notes.txt"), "/notes.txt");
    }

    #[test]
    fn joining_an_absolute_child_discards_the_base() {
        assert_eq!(join("/home/user", "/etc/hosts"), "/etc/hosts");
    }

    #[test]
    fn joining_onto_an_empty_base_produces_an_absolute_path() {
        assert_eq!(join("", "notes.txt"), "/notes.txt");
    }

    #[test]
    fn the_parent_of_root_is_root() {
        assert_eq!(parent("/"), "/");
        assert_eq!(parent(""), "/");
    }

    #[test]
    fn parents_walk_up_one_level() {
        assert_eq!(parent("/home/user/notes.txt"), "/home/user");
        assert_eq!(parent("/home/user"), "/home");
        assert_eq!(parent("/home"), "/");
        // A trailing slash does not add a level.
        assert_eq!(parent("/home/user/"), "/home");
    }

    #[test]
    fn file_names_come_from_the_last_segment() {
        assert_eq!(file_name("/home/user/notes.txt"), "notes.txt");
        assert_eq!(file_name("/home/user/"), "user");
        assert_eq!(file_name("notes.txt"), "notes.txt");
    }

    #[test]
    fn normalizing_collapses_repeats_and_trailing_slashes() {
        assert_eq!(normalize("/home//user///"), "/home/user");
        assert_eq!(normalize("/"), "/");
        assert_eq!(normalize(""), "/");
        assert_eq!(normalize("home/user"), "home/user");
    }

    #[test]
    fn normalizing_leaves_dot_segments_for_the_server_to_resolve() {
        // Rewriting these locally would break paths that traverse symlinks.
        assert_eq!(normalize("/home/../etc"), "/home/../etc");
    }

    #[test]
    fn resolving_handles_relative_absolute_and_current() {
        assert_eq!(resolve("/home/user", "."), "/home/user");
        assert_eq!(resolve("/home/user", ""), "/home/user");
        assert_eq!(resolve("/home/user", "docs"), "/home/user/docs");
        assert_eq!(resolve("/home/user", "/etc"), "/etc");
    }

    #[test]
    fn local_paths_convert_to_forward_slashes() {
        assert_eq!(
            from_local(std::path::Path::new(r"C:\Users\me\docs")),
            "C:/Users/me/docs"
        );
    }
}
