//! The audio for the default pack, compiled into the binary.
//!
//! Shipping the files inside the executable means a fresh install, a nightly,
//! and a portable copy all have sound on first launch with no installer step
//! to forget. [`super::ensure_default_pack`] writes them to the packs
//! directory, where the user can replace any of them.

/// One sound in the built-in pack.
pub struct BuiltinSound {
    /// The event key, see [`crate::sound_events`].
    pub event: &'static str,
    /// Path inside the pack directory, `/`-separated.
    pub path: &'static str,
    /// The encoded audio.
    pub bytes: &'static [u8],
}

macro_rules! sound {
    ($event:literal, $path:literal) => {
        BuiltinSound {
            event: $event,
            path: $path,
            bytes: include_bytes!(concat!("../../assets/soundpacks/default/", $path)),
        }
    };
}

/// Every sound the default pack ships with.
pub const BUILTIN_SOUNDS: &[BuiltinSound] = &[
    sound!("transfer_queued", "transfers/transfer_queued.ogg"),
    sound!("transfer_started", "transfers/transfer_started.ogg"),
    sound!("transfer_complete", "transfers/transfer_complete.ogg"),
    sound!("transfer_failed", "transfers/transfer_failed.ogg"),
    sound!("transfer_cancelled", "transfers/transfer_cancelled.ogg"),
    sound!("connect_waiting", "connections/connect_waiting.ogg"),
    sound!("connect_success", "connections/connect_success.ogg"),
    sound!("connect_failed", "connections/connect_failed.ogg"),
    sound!("disconnect", "connections/disconnect.ogg"),
    sound!("delete_complete", "file_operations/delete_complete.ogg"),
    sound!("delete_failed", "file_operations/delete_failed.ogg"),
    sound!("rename_complete", "file_operations/rename_complete.ogg"),
    sound!("rename_failed", "file_operations/rename_failed.ogg"),
    sound!("folder_created", "file_operations/folder_created.ogg"),
    sound!(
        "folder_create_failed",
        "file_operations/folder_create_failed.ogg"
    ),
    sound!("success", "general/success.ogg"),
    sound!("error", "general/error.ogg"),
    sound!("notify", "general/notify.ogg"),
    sound!("startup", "general/startup.ogg"),
    sound!("exit", "general/exit.ogg"),
];

#[cfg(test)]
mod tests {
    use super::*;
    use crate::sound_events::{is_known_sound_event, SOUND_EVENT_SECTIONS};
    use crate::soundpacks::can_decode;
    use std::collections::HashSet;
    use tempfile::TempDir;

    #[test]
    fn every_built_in_sound_is_a_known_event() {
        for sound in BUILTIN_SOUNDS {
            assert!(
                is_known_sound_event(sound.event),
                "{} is not in the event catalogue",
                sound.event
            );
        }
    }

    #[test]
    fn every_catalogue_event_has_a_built_in_sound() {
        // A fresh install should make a sound for everything Settings lists,
        // otherwise muting an event there would be a switch wired to nothing.
        let shipped: HashSet<&str> = BUILTIN_SOUNDS.iter().map(|s| s.event).collect();
        for section in SOUND_EVENT_SECTIONS {
            for (event, _) in section.events {
                assert!(shipped.contains(event), "no built-in sound for {event}");
            }
        }
    }

    #[test]
    fn events_and_paths_are_unique() {
        let events: HashSet<&str> = BUILTIN_SOUNDS.iter().map(|s| s.event).collect();
        let paths: HashSet<&str> = BUILTIN_SOUNDS.iter().map(|s| s.path).collect();
        assert_eq!(events.len(), BUILTIN_SOUNDS.len());
        assert_eq!(paths.len(), BUILTIN_SOUNDS.len());
    }

    #[test]
    fn every_built_in_sound_decodes() {
        // Guards against a corrupt or misnamed asset getting compiled in.
        let dir = TempDir::new().unwrap();
        for sound in BUILTIN_SOUNDS {
            assert!(!sound.bytes.is_empty(), "{} is empty", sound.path);
            let path = dir.path().join(sound.event).with_extension("ogg");
            std::fs::write(&path, sound.bytes).unwrap();
            assert!(can_decode(&path), "{} does not decode", sound.path);
        }
    }
}
