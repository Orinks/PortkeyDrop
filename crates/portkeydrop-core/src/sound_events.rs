//! Catalogue of sound events the app can play.
//!
//! The sections here drive both the settings UI (grouped checkboxes for
//! muting) and sound-pack validation, so the ordering is deliberate and
//! user-visible.

/// Events muted out of the box. Empty: every event plays by default.
pub const DEFAULT_MUTED_SOUND_EVENTS: &[&str] = &[];

/// One group of related sound events, as shown in Settings.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SoundEventSection {
    /// Group heading.
    pub title: &'static str,
    /// One-line description shown under the heading.
    pub description: &'static str,
    /// `(event key, human label)` pairs in display order.
    pub events: &'static [(&'static str, &'static str)],
}

/// Every sound event, grouped for display.
pub const SOUND_EVENT_SECTIONS: &[SoundEventSection] = &[
    SoundEventSection {
        title: "Transfers",
        description: "File transfer queue and result sounds.",
        events: &[
            ("transfer_queued", "Transfer queued"),
            ("transfer_started", "Transfer started"),
            ("transfer_complete", "Transfer complete"),
            ("transfer_failed", "Transfer failed"),
            ("transfer_cancelled", "Transfer cancelled"),
        ],
    },
    SoundEventSection {
        title: "Connections",
        description: "Server connection lifecycle sounds.",
        events: &[
            ("connect_waiting", "Waiting to connect"),
            ("connect_success", "Connected"),
            ("connect_failed", "Connection failed"),
            ("disconnect", "Disconnected"),
        ],
    },
    SoundEventSection {
        title: "File operations",
        description: "Remote and local file operation result sounds.",
        events: &[
            ("delete_complete", "Delete complete"),
            ("delete_failed", "Delete failed"),
            ("rename_complete", "Rename complete"),
            ("rename_failed", "Rename failed"),
            ("folder_created", "Folder created"),
            ("folder_create_failed", "Folder creation failed"),
        ],
    },
    SoundEventSection {
        title: "General",
        description: "General application feedback sounds.",
        events: &[
            ("success", "General success"),
            ("error", "General error"),
            ("notify", "General notification"),
            ("startup", "App startup"),
            ("exit", "App exit"),
        ],
    },
];

/// Every `(event key, label)` pair, flattened in section order.
pub fn user_mutable_sound_events() -> Vec<(&'static str, &'static str)> {
    SOUND_EVENT_SECTIONS
        .iter()
        .flat_map(|section| section.events.iter().copied())
        .collect()
}

/// Whether `event` is a key the app knows how to play.
pub fn is_known_sound_event(event: &str) -> bool {
    SOUND_EVENT_SECTIONS
        .iter()
        .any(|section| section.events.iter().any(|(key, _)| *key == event))
}

/// Normalise a muted-event list: trim, drop blanks, drop duplicates, keep order.
pub fn normalize_muted_sound_events<I, S>(events: I) -> Vec<String>
where
    I: IntoIterator<Item = S>,
    S: AsRef<str>,
{
    let mut normalized: Vec<String> = Vec::new();
    for item in events {
        let event = item.as_ref().trim();
        if event.is_empty() || normalized.iter().any(|seen| seen == event) {
            continue;
        }
        normalized.push(event.to_string());
    }
    normalized
}

/// Normalise a muted-event list and drop keys outside the shared catalogue.
///
/// Keeps a settings file written by a newer build from resurrecting events
/// this build cannot play.
pub fn normalize_known_muted_sound_events<I, S>(events: I) -> Vec<String>
where
    I: IntoIterator<Item = S>,
    S: AsRef<str>,
{
    normalize_muted_sound_events(events)
        .into_iter()
        .filter(|event| is_known_sound_event(event))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_event_key_is_unique_across_sections() {
        let events = user_mutable_sound_events();
        let mut keys: Vec<&str> = events.iter().map(|(key, _)| *key).collect();
        let total = keys.len();
        keys.sort_unstable();
        keys.dedup();
        assert_eq!(
            keys.len(),
            total,
            "duplicate sound event key in the catalogue"
        );
    }

    #[test]
    fn the_catalogue_covers_the_documented_events() {
        assert!(is_known_sound_event("transfer_complete"));
        assert!(is_known_sound_event("connect_waiting"));
        assert!(is_known_sound_event("connect_failed"));
        assert!(is_known_sound_event("folder_create_failed"));
        assert!(is_known_sound_event("exit"));
        assert!(!is_known_sound_event("not_a_real_event"));
    }

    #[test]
    fn nothing_is_muted_by_default() {
        assert!(DEFAULT_MUTED_SOUND_EVENTS.is_empty());
    }

    #[test]
    fn normalizing_trims_drops_blanks_and_dedupes_preserving_order() {
        let result = normalize_muted_sound_events([
            "  transfer_failed  ",
            "",
            "success",
            "transfer_failed",
            "   ",
        ]);
        assert_eq!(result, vec!["transfer_failed", "success"]);
    }

    #[test]
    fn normalizing_an_empty_list_yields_an_empty_list() {
        let empty: Vec<String> = Vec::new();
        assert!(normalize_muted_sound_events(empty).is_empty());
    }

    #[test]
    fn unknown_keys_are_dropped_by_the_known_only_normalizer() {
        let result = normalize_known_muted_sound_events(["success", "made_up_event", "disconnect"]);
        assert_eq!(result, vec!["success", "disconnect"]);
    }
}
