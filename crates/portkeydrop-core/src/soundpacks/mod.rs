//! Sound pack discovery, validation, installation, and playback.
//!
//! A pack is a directory holding a `pack.json` manifest and its audio files.
//! The manifest maps event keys (see [`crate::sound_events`]) to file names and
//! optional per-event volumes.
//!
//! Packs are user-supplied content, so installation is treated as untrusted
//! input: archives are checked for path traversal before anything is written.

mod builtin;
mod install;
mod manifest;
mod player;

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

pub use builtin::{BuiltinSound, BUILTIN_SOUNDS};
pub use install::{is_safe_archive_name, InstallError, PackInstaller};
pub use manifest::{PackManifest, SoundEntry};
pub use player::{
    can_decode, play_looping_sound_file, play_sound_file, wait_for_playback, LoopHandle,
    SoundPlayer, EXIT_SOUND_TIMEOUT,
};

/// Directory name of the built-in pack.
pub const DEFAULT_PACK: &str = "default";

/// Manifest file name inside a pack directory.
pub const MANIFEST_FILE_NAME: &str = "pack.json";

/// File dialog filter for pack audio.
pub const AUDIO_WILDCARD: &str = "Audio files (*.wav;*.mp3;*.ogg;*.flac)|*.wav;*.mp3;*.ogg;*.flac";

/// Extensions the audio backend can decode.
pub const AUDIO_EXTENSIONS: [&str; 4] = ["wav", "mp3", "ogg", "flac"];

/// The writable sound packs directory inside a config directory.
pub fn soundpacks_dir(config_dir: &Path) -> PathBuf {
    config_dir.join("soundpacks")
}

/// Turn a display name into a directory name.
pub fn slugify_pack_name(value: &str, fallback: &str) -> String {
    let mut slug = String::with_capacity(value.len());
    for character in value.trim().to_lowercase().chars() {
        if character.is_alphanumeric() {
            slug.push(character);
        } else if character == '_' || character == '-' || character == ' ' {
            slug.push('_');
        }
    }
    // Collapse runs of underscores left by punctuation and spaces.
    while slug.contains("__") {
        slug = slug.replace("__", "_");
    }
    let slug = slug.trim_matches('_').to_string();
    if slug.is_empty() {
        fallback.to_string()
    } else {
        slug
    }
}

/// A pack found on disk.
#[derive(Debug, Clone, PartialEq)]
pub struct InstalledPack {
    /// Directory name, used as the stable identifier.
    pub directory: String,
    pub path: PathBuf,
    pub manifest: PackManifest,
}

impl InstalledPack {
    /// The name shown in the picker, falling back to the directory name.
    pub fn display_name(&self) -> &str {
        if self.manifest.name.is_empty() {
            &self.directory
        } else {
            &self.manifest.name
        }
    }
}

/// Why a pack was rejected.
#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum PackError {
    #[error("the sound pack folder does not exist")]
    Missing,
    #[error("the sound pack path is not a folder")]
    NotADirectory,
    #[error("the folder has no {MANIFEST_FILE_NAME} file")]
    NoManifest,
    #[error("{MANIFEST_FILE_NAME} is not valid JSON: {0}")]
    InvalidJson(String),
    #[error("{MANIFEST_FILE_NAME} is missing the '{0}' field")]
    MissingField(&'static str),
    #[error("these sound files are named in the manifest but missing: {0}")]
    MissingFiles(String),
    #[error("the volume for '{event}' must be between 0.0 and 1.0, not {value}")]
    VolumeOutOfRange { event: String, value: String },
}

/// Check that a directory is a usable pack.
pub fn validate_pack(pack_path: &Path) -> Result<PackManifest, PackError> {
    if !pack_path.exists() {
        return Err(PackError::Missing);
    }
    if !pack_path.is_dir() {
        return Err(PackError::NotADirectory);
    }

    let manifest_path = pack_path.join(MANIFEST_FILE_NAME);
    if !manifest_path.exists() {
        return Err(PackError::NoManifest);
    }

    let text = std::fs::read_to_string(&manifest_path)
        .map_err(|err| PackError::InvalidJson(err.to_string()))?;
    let manifest = PackManifest::from_json(&text)?;

    let missing: Vec<String> = manifest
        .sounds
        .iter()
        .map(|(event, entry)| entry.file_name(event))
        .filter(|file_name| file_name.is_empty() || !pack_path.join(file_name).exists())
        .collect();
    if !missing.is_empty() {
        return Err(PackError::MissingFiles(missing.join(", ")));
    }

    Ok(manifest)
}

/// Every valid pack in a directory, keyed by directory name.
///
/// Invalid packs are skipped with a log line rather than failing the scan, so
/// one broken pack does not hide the rest.
pub fn available_packs(soundpacks_dir: &Path) -> BTreeMap<String, InstalledPack> {
    let mut packs = BTreeMap::new();
    let Ok(entries) = std::fs::read_dir(soundpacks_dir) else {
        return packs;
    };

    for entry in entries.flatten() {
        let path = entry.path();
        if !path.is_dir() {
            continue;
        }
        let directory = entry.file_name().to_string_lossy().into_owned();
        match validate_pack(&path) {
            Ok(manifest) => {
                packs.insert(
                    directory.clone(),
                    InstalledPack {
                        directory,
                        path,
                        manifest,
                    },
                );
            }
            Err(PackError::NoManifest) => {}
            Err(err) => log::warn!("ignoring sound pack {directory}: {err}"),
        }
    }
    packs
}

/// Resolve the file and volume for an event.
///
/// The active pack is tried first, then the default pack, so a partial pack
/// still gets sound for the events it does not define.
pub fn resolve_sound(
    event: &str,
    pack_directory: &str,
    soundpacks_dir: &Path,
) -> Option<(PathBuf, f32)> {
    for candidate in [pack_directory, DEFAULT_PACK] {
        if candidate.is_empty() {
            continue;
        }
        let pack_path = soundpacks_dir.join(candidate);
        let manifest_path = pack_path.join(MANIFEST_FILE_NAME);
        let Ok(text) = std::fs::read_to_string(&manifest_path) else {
            continue;
        };
        let Ok(manifest) = PackManifest::from_json(&text) else {
            log::warn!("sound pack {candidate} has an unreadable manifest");
            continue;
        };
        let Some(entry) = manifest.sounds.get(event) else {
            continue;
        };
        let file = pack_path.join(entry.file_name(event));
        if file.exists() {
            return Some((file, manifest.volume_for(event, entry)));
        }
    }
    None
}

/// Ensure the built-in default pack exists in the writable packs directory.
///
/// Every sound in [`BUILTIN_SOUNDS`] that is not already on disk is written,
/// and the manifest gains an entry for every built-in event it does not name.
/// Existing files and entries are never overwritten: a user who replaced a
/// sound keeps their version across upgrades, and a new built-in cue still
/// reaches them.
pub fn ensure_default_pack(soundpacks_dir: &Path) -> std::io::Result<PathBuf> {
    let default_dir = soundpacks_dir.join(DEFAULT_PACK);
    std::fs::create_dir_all(&default_dir)?;

    for sound in BUILTIN_SOUNDS {
        let path = default_dir.join(sound.path);
        if path.exists() {
            continue;
        }
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::write(&path, sound.bytes)?;
    }

    let manifest_path = default_dir.join(MANIFEST_FILE_NAME);
    if let Some(text) = default_manifest_update(&manifest_path) {
        std::fs::write(&manifest_path, text)?;
    }
    Ok(default_dir)
}

/// The default manifest text to write, or `None` to leave the file alone.
///
/// A missing manifest gets the built-in one. A readable manifest keeps
/// everything it has and only gains entries for built-in events it lacks, so
/// it is rewritten only when that adds something.
fn default_manifest_update(manifest_path: &Path) -> Option<String> {
    let Ok(text) = std::fs::read_to_string(manifest_path) else {
        return Some(PackManifest::default_pack_json());
    };
    match PackManifest::from_json(&text) {
        Ok(mut manifest) => {
            let mut changed = false;
            for sound in BUILTIN_SOUNDS {
                if !manifest.sounds.contains_key(sound.event) {
                    manifest.sounds.insert(
                        sound.event.to_string(),
                        SoundEntry::File(sound.path.to_string()),
                    );
                    changed = true;
                }
            }
            changed.then(|| manifest.to_json())
        }
        // Unparseable: leave it alone rather than destroying something the
        // user may be part-way through editing.
        Err(_) => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    /// Write a pack directory with a manifest and its audio files.
    fn write_pack(root: &Path, directory: &str, manifest: &str, files: &[&str]) -> PathBuf {
        let pack = root.join(directory);
        std::fs::create_dir_all(&pack).unwrap();
        std::fs::write(pack.join(MANIFEST_FILE_NAME), manifest).unwrap();
        for file in files {
            let path = pack.join(file);
            if let Some(parent) = path.parent() {
                std::fs::create_dir_all(parent).unwrap();
            }
            std::fs::write(path, b"audio").unwrap();
        }
        pack
    }

    const MANIFEST: &str = r#"{
        "name": "Test Pack",
        "author": "Someone",
        "version": "1.0.0",
        "sounds": {
            "transfer_complete": "transfers/done.ogg",
            "error": {"file": "general/error.ogg", "volume": 0.5}
        }
    }"#;

    #[test]
    fn pack_names_become_filesystem_safe_slugs() {
        assert_eq!(
            slugify_pack_name("My Sound Pack", "fallback"),
            "my_sound_pack"
        );
        assert_eq!(slugify_pack_name("Retro-Beeps", "fallback"), "retro_beeps");
        assert_eq!(
            slugify_pack_name("  Spaced  Out  ", "fallback"),
            "spaced_out"
        );
    }

    #[test]
    fn punctuation_collapses_rather_than_producing_double_underscores() {
        assert_eq!(slugify_pack_name("A -- B", "fallback"), "a_b");
        assert_eq!(slugify_pack_name("!!!pack!!!", "fallback"), "pack");
    }

    #[test]
    fn a_name_with_nothing_usable_falls_back() {
        assert_eq!(slugify_pack_name("!!!", "fallback"), "fallback");
        assert_eq!(slugify_pack_name("", "fallback"), "fallback");
    }

    #[test]
    fn a_complete_pack_validates() {
        let dir = TempDir::new().unwrap();
        let pack = write_pack(
            dir.path(),
            "test",
            MANIFEST,
            &["transfers/done.ogg", "general/error.ogg"],
        );
        let manifest = validate_pack(&pack).unwrap();
        assert_eq!(manifest.name, "Test Pack");
        assert_eq!(manifest.sounds.len(), 2);
    }

    #[test]
    fn a_missing_folder_is_reported() {
        let dir = TempDir::new().unwrap();
        assert_eq!(
            validate_pack(&dir.path().join("nope")),
            Err(PackError::Missing)
        );
    }

    #[test]
    fn a_file_where_a_pack_should_be_is_reported() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("notapack");
        std::fs::write(&path, b"x").unwrap();
        assert_eq!(validate_pack(&path), Err(PackError::NotADirectory));
    }

    #[test]
    fn a_folder_without_a_manifest_is_reported() {
        let dir = TempDir::new().unwrap();
        let pack = dir.path().join("empty");
        std::fs::create_dir(&pack).unwrap();
        assert_eq!(validate_pack(&pack), Err(PackError::NoManifest));
    }

    #[test]
    fn a_manifest_naming_a_missing_file_is_rejected() {
        // Otherwise the pack would install and then be silent, with nothing to
        // tell the user why.
        let dir = TempDir::new().unwrap();
        let pack = write_pack(dir.path(), "test", MANIFEST, &["transfers/done.ogg"]);
        let error = validate_pack(&pack).unwrap_err();
        assert!(
            matches!(error, PackError::MissingFiles(files) if files.contains("general/error.ogg"))
        );
    }

    #[test]
    fn every_valid_pack_in_the_directory_is_listed() {
        let dir = TempDir::new().unwrap();
        write_pack(
            dir.path(),
            "alpha",
            MANIFEST,
            &["transfers/done.ogg", "general/error.ogg"],
        );
        write_pack(
            dir.path(),
            "beta",
            MANIFEST,
            &["transfers/done.ogg", "general/error.ogg"],
        );

        let packs = available_packs(dir.path());
        assert_eq!(packs.len(), 2);
        assert!(packs.contains_key("alpha"));
        assert!(packs.contains_key("beta"));
    }

    #[test]
    fn one_broken_pack_does_not_hide_the_others() {
        let dir = TempDir::new().unwrap();
        write_pack(
            dir.path(),
            "good",
            MANIFEST,
            &["transfers/done.ogg", "general/error.ogg"],
        );
        write_pack(dir.path(), "broken", "{not json", &[]);
        // A stray folder with no manifest is simply not a pack.
        std::fs::create_dir(dir.path().join("notapack")).unwrap();

        let packs = available_packs(dir.path());
        assert_eq!(packs.len(), 1);
        assert!(packs.contains_key("good"));
    }

    #[test]
    fn scanning_a_missing_directory_yields_nothing() {
        let dir = TempDir::new().unwrap();
        assert!(available_packs(&dir.path().join("nope")).is_empty());
    }

    #[test]
    fn the_display_name_falls_back_to_the_directory() {
        let dir = TempDir::new().unwrap();
        let path = write_pack(dir.path(), "nameless", r#"{"name":"","sounds":{}}"#, &[]);
        let pack = InstalledPack {
            directory: "nameless".into(),
            path,
            manifest: PackManifest::from_json(r#"{"name":"","sounds":{}}"#).unwrap(),
        };
        assert_eq!(pack.display_name(), "nameless");
    }

    #[test]
    fn an_event_resolves_to_its_file_and_volume() {
        let dir = TempDir::new().unwrap();
        write_pack(
            dir.path(),
            "test",
            MANIFEST,
            &["transfers/done.ogg", "general/error.ogg"],
        );

        let (file, volume) = resolve_sound("error", "test", dir.path()).unwrap();
        assert!(file.ends_with("general/error.ogg") || file.ends_with(r"general\error.ogg"));
        assert_eq!(volume, 0.5);
    }

    #[test]
    fn an_event_the_pack_omits_falls_back_to_the_default_pack() {
        // A partial pack should still make a sound for events it skipped.
        let dir = TempDir::new().unwrap();
        write_pack(
            dir.path(),
            "partial",
            r#"{"name":"Partial","sounds":{"error":"e.ogg"}}"#,
            &["e.ogg"],
        );
        write_pack(
            dir.path(),
            DEFAULT_PACK,
            r#"{"name":"Default","sounds":{"startup":"s.ogg"}}"#,
            &["s.ogg"],
        );

        assert!(resolve_sound("startup", "partial", dir.path()).is_some());
    }

    #[test]
    fn an_event_no_pack_defines_resolves_to_nothing() {
        let dir = TempDir::new().unwrap();
        write_pack(
            dir.path(),
            "test",
            MANIFEST,
            &["transfers/done.ogg", "general/error.ogg"],
        );
        assert!(resolve_sound("startup", "test", dir.path()).is_none());
    }

    #[test]
    fn a_manifest_entry_whose_file_is_gone_resolves_to_nothing() {
        let dir = TempDir::new().unwrap();
        write_pack(dir.path(), "test", MANIFEST, &["transfers/done.ogg"]);
        assert!(resolve_sound("error", "test", dir.path()).is_none());
    }

    #[test]
    fn the_default_pack_is_created_with_every_built_in_sound() {
        let dir = TempDir::new().unwrap();
        let packs = soundpacks_dir(dir.path());
        let default = ensure_default_pack(&packs).unwrap();

        let manifest = validate_pack(&default).unwrap();
        assert_eq!(manifest.sounds.len(), BUILTIN_SOUNDS.len());
        for sound in BUILTIN_SOUNDS {
            let written = std::fs::read(default.join(sound.path)).unwrap();
            assert_eq!(written, sound.bytes, "{} differs on disk", sound.path);
            assert!(resolve_sound(sound.event, DEFAULT_PACK, &packs).is_some());
        }
    }

    #[test]
    fn a_users_replacement_sound_is_not_overwritten() {
        // A user who swapped in their own connect chime keeps it across
        // upgrades; only files that are missing get written.
        let dir = TempDir::new().unwrap();
        let packs = soundpacks_dir(dir.path());
        let theirs = packs
            .join(DEFAULT_PACK)
            .join("connections/connect_success.ogg");
        std::fs::create_dir_all(theirs.parent().unwrap()).unwrap();
        std::fs::write(&theirs, b"my chime").unwrap();

        ensure_default_pack(&packs).unwrap();

        assert_eq!(std::fs::read(&theirs).unwrap(), b"my chime");
        assert!(packs
            .join(DEFAULT_PACK)
            .join("connections/disconnect.ogg")
            .exists());
    }

    #[test]
    fn a_user_edited_default_manifest_keeps_its_entries_and_gains_the_rest() {
        // Overwriting it would silently discard the user's customisation, but
        // a built-in cue added in a later release still has to reach them.
        let dir = TempDir::new().unwrap();
        let packs = soundpacks_dir(dir.path());
        write_pack(
            &packs,
            DEFAULT_PACK,
            r#"{"name":"Mine","sounds":{"error":{"file":"e.ogg","volume":0.5}}}"#,
            &["e.ogg"],
        );

        ensure_default_pack(&packs).unwrap();

        let manifest = validate_pack(&packs.join(DEFAULT_PACK)).unwrap();
        assert_eq!(manifest.name, "Mine");
        assert_eq!(manifest.sounds["error"].file_name("error"), "e.ogg");
        assert_eq!(manifest.sounds["error"].volume(), Some(0.5));
        assert_eq!(manifest.sounds.len(), BUILTIN_SOUNDS.len());
        assert!(manifest.sounds.contains_key("connect_waiting"));
    }

    #[test]
    fn a_complete_default_manifest_is_not_rewritten() {
        let dir = TempDir::new().unwrap();
        let packs = soundpacks_dir(dir.path());
        let manifest_path = packs.join(DEFAULT_PACK).join(MANIFEST_FILE_NAME);
        std::fs::create_dir_all(manifest_path.parent().unwrap()).unwrap();
        // Hand-formatted, so a rewrite would be visible.
        let text = PackManifest::default_pack_json().replace("  ", "\t");
        std::fs::write(&manifest_path, &text).unwrap();

        ensure_default_pack(&packs).unwrap();

        assert_eq!(std::fs::read_to_string(&manifest_path).unwrap(), text);
    }

    #[test]
    fn an_empty_placeholder_default_manifest_is_filled_in() {
        // Earlier builds wrote a manifest with no sounds at all.
        let dir = TempDir::new().unwrap();
        let packs = soundpacks_dir(dir.path());
        write_pack(
            &packs,
            DEFAULT_PACK,
            r#"{"name":"Default","sounds":{}}"#,
            &[],
        );

        ensure_default_pack(&packs).unwrap();

        let manifest = validate_pack(&packs.join(DEFAULT_PACK)).unwrap();
        assert_eq!(manifest.sounds.len(), BUILTIN_SOUNDS.len());
    }

    #[test]
    fn an_unparseable_default_manifest_is_not_destroyed() {
        let dir = TempDir::new().unwrap();
        let packs = soundpacks_dir(dir.path());
        write_pack(&packs, DEFAULT_PACK, "{half written", &[]);

        ensure_default_pack(&packs).unwrap();

        let text =
            std::fs::read_to_string(packs.join(DEFAULT_PACK).join(MANIFEST_FILE_NAME)).unwrap();
        assert_eq!(text, "{half written");
    }
}
