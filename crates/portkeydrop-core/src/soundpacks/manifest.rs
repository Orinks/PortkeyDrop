//! The `pack.json` manifest.
//!
//! A sound may be written either as a bare file name or as an object with a
//! per-event volume. Both spellings appear in packs in the wild, so both are
//! accepted.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

use super::builtin::BUILTIN_SOUNDS;
use super::PackError;

/// One sound in a manifest.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(untagged)]
pub enum SoundEntry {
    /// `"transfer_complete": "done.ogg"`
    File(String),
    /// `"transfer_complete": {"file": "done.ogg", "volume": 0.5}`
    Detailed {
        #[serde(default, skip_serializing_if = "Option::is_none")]
        file: Option<String>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        volume: Option<f64>,
    },
}

impl SoundEntry {
    /// The file name for `event`, defaulting to `<event>.wav`.
    pub fn file_name(&self, event: &str) -> String {
        let named = match self {
            SoundEntry::File(file) => Some(file.clone()),
            SoundEntry::Detailed { file, .. } => file.clone(),
        };
        named
            .filter(|name| !name.trim().is_empty())
            .unwrap_or_else(|| format!("{event}.wav"))
    }

    /// The volume written on this entry, if any.
    pub fn volume(&self) -> Option<f64> {
        match self {
            SoundEntry::File(_) => None,
            SoundEntry::Detailed { volume, .. } => *volume,
        }
    }
}

/// A parsed `pack.json`.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct PackManifest {
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub author: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub version: String,
    /// Event key to sound.
    #[serde(default)]
    pub sounds: BTreeMap<String, SoundEntry>,
    /// Fallback volumes, for entries written as a bare file name.
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub volumes: BTreeMap<String, f64>,
}

impl PackManifest {
    /// Parse manifest JSON.
    ///
    /// `name` and `sounds` are required; a pack without them is not usable and
    /// saying so is more helpful than defaulting silently.
    pub fn from_json(text: &str) -> Result<Self, PackError> {
        let value: serde_json::Value =
            serde_json::from_str(text).map_err(|err| PackError::InvalidJson(err.to_string()))?;
        let object = value.as_object().ok_or(PackError::MissingField("name"))?;
        if !object.contains_key("name") {
            return Err(PackError::MissingField("name"));
        }
        if !object.contains_key("sounds") {
            return Err(PackError::MissingField("sounds"));
        }
        if !object["sounds"].is_object() {
            return Err(PackError::MissingField("sounds"));
        }

        let manifest: PackManifest =
            serde_json::from_value(value).map_err(|err| PackError::InvalidJson(err.to_string()))?;

        for (event, volume) in &manifest.volumes {
            if !(0.0..=1.0).contains(volume) || !volume.is_finite() {
                return Err(PackError::VolumeOutOfRange {
                    event: event.clone(),
                    value: volume.to_string(),
                });
            }
        }
        for (event, entry) in &manifest.sounds {
            if let Some(volume) = entry.volume() {
                if !(0.0..=1.0).contains(&volume) || !volume.is_finite() {
                    return Err(PackError::VolumeOutOfRange {
                        event: event.clone(),
                        value: volume.to_string(),
                    });
                }
            }
        }

        Ok(manifest)
    }

    /// The playback volume for an event, clamped into range.
    ///
    /// An entry's own volume wins over the pack-level `volumes` table.
    pub fn volume_for(&self, event: &str, entry: &SoundEntry) -> f32 {
        let volume = entry
            .volume()
            .or_else(|| self.volumes.get(event).copied())
            .unwrap_or(1.0);
        if volume.is_finite() {
            volume.clamp(0.0, 1.0) as f32
        } else {
            1.0
        }
    }

    /// Serialise as pretty-printed JSON with a trailing newline.
    pub fn to_json(&self) -> String {
        serde_json::to_string_pretty(self).expect("a manifest always serialises") + "\n"
    }

    /// The manifest for the built-in default pack, listing every sound in
    /// [`BUILTIN_SOUNDS`].
    pub fn default_pack_manifest() -> Self {
        PackManifest {
            name: "Default".into(),
            author: "Portkey Drop".into(),
            description:
                "Built-in Portkey Drop sound pack with short, gentle transfer and app cues.".into(),
            version: "1.0.0".into(),
            sounds: BUILTIN_SOUNDS
                .iter()
                .map(|sound| {
                    (
                        sound.event.to_string(),
                        SoundEntry::File(sound.path.to_string()),
                    )
                })
                .collect(),
            volumes: BTreeMap::new(),
        }
    }

    /// The manifest written for a freshly created default pack.
    pub fn default_pack_json() -> String {
        Self::default_pack_manifest().to_json()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_bare_file_name_entry_parses() {
        let manifest =
            PackManifest::from_json(r#"{"name":"P","sounds":{"error":"e.ogg"}}"#).unwrap();
        let entry = &manifest.sounds["error"];
        assert_eq!(entry.file_name("error"), "e.ogg");
        assert_eq!(entry.volume(), None);
    }

    #[test]
    fn a_detailed_entry_parses_with_its_volume() {
        let manifest = PackManifest::from_json(
            r#"{"name":"P","sounds":{"error":{"file":"e.ogg","volume":0.25}}}"#,
        )
        .unwrap();
        let entry = &manifest.sounds["error"];
        assert_eq!(entry.file_name("error"), "e.ogg");
        assert_eq!(entry.volume(), Some(0.25));
    }

    #[test]
    fn an_entry_without_a_file_name_defaults_to_the_event_name() {
        let manifest =
            PackManifest::from_json(r#"{"name":"P","sounds":{"error":{"volume":0.5}}}"#).unwrap();
        assert_eq!(manifest.sounds["error"].file_name("error"), "error.wav");

        let manifest = PackManifest::from_json(r#"{"name":"P","sounds":{"error":""}}"#).unwrap();
        assert_eq!(manifest.sounds["error"].file_name("error"), "error.wav");
    }

    #[test]
    fn a_manifest_without_a_name_is_rejected() {
        assert_eq!(
            PackManifest::from_json(r#"{"sounds":{}}"#),
            Err(PackError::MissingField("name"))
        );
    }

    #[test]
    fn a_manifest_without_sounds_is_rejected() {
        assert_eq!(
            PackManifest::from_json(r#"{"name":"P"}"#),
            Err(PackError::MissingField("sounds"))
        );
    }

    #[test]
    fn a_sounds_field_that_is_not_an_object_is_rejected() {
        assert_eq!(
            PackManifest::from_json(r#"{"name":"P","sounds":[]}"#),
            Err(PackError::MissingField("sounds"))
        );
    }

    #[test]
    fn malformed_json_is_reported_as_such() {
        assert!(matches!(
            PackManifest::from_json("{not json"),
            Err(PackError::InvalidJson(_))
        ));
    }

    #[test]
    fn a_volume_outside_zero_to_one_is_rejected() {
        // Silently clamping would leave a pack author wondering why their
        // "volume": 5 did nothing.
        assert!(matches!(
            PackManifest::from_json(r#"{"name":"P","sounds":{},"volumes":{"error":5.0}}"#),
            Err(PackError::VolumeOutOfRange { .. })
        ));
        assert!(matches!(
            PackManifest::from_json(
                r#"{"name":"P","sounds":{"error":{"file":"e.ogg","volume":-1}}}"#
            ),
            Err(PackError::VolumeOutOfRange { .. })
        ));
    }

    #[test]
    fn the_boundary_volumes_are_accepted() {
        assert!(
            PackManifest::from_json(r#"{"name":"P","sounds":{},"volumes":{"a":0.0,"b":1.0}}"#)
                .is_ok()
        );
    }

    #[test]
    fn an_entry_volume_wins_over_the_pack_level_table() {
        let manifest = PackManifest::from_json(
            r#"{"name":"P","sounds":{"error":{"file":"e.ogg","volume":0.25}},
                "volumes":{"error":0.9}}"#,
        )
        .unwrap();
        assert_eq!(
            manifest.volume_for("error", &manifest.sounds["error"]),
            0.25
        );
    }

    #[test]
    fn a_bare_entry_takes_its_volume_from_the_pack_level_table() {
        let manifest = PackManifest::from_json(
            r#"{"name":"P","sounds":{"error":"e.ogg"},"volumes":{"error":0.9}}"#,
        )
        .unwrap();
        assert_eq!(manifest.volume_for("error", &manifest.sounds["error"]), 0.9);
    }

    #[test]
    fn an_event_with_no_volume_anywhere_plays_at_full() {
        let manifest =
            PackManifest::from_json(r#"{"name":"P","sounds":{"error":"e.ogg"}}"#).unwrap();
        assert_eq!(manifest.volume_for("error", &manifest.sounds["error"]), 1.0);
    }

    #[test]
    fn optional_metadata_fields_default_to_empty() {
        let manifest = PackManifest::from_json(r#"{"name":"P","sounds":{}}"#).unwrap();
        assert_eq!(manifest.author, "");
        assert_eq!(manifest.description, "");
        assert_eq!(manifest.version, "");
    }

    #[test]
    fn the_generated_default_manifest_lists_every_built_in_sound() {
        let manifest = PackManifest::from_json(&PackManifest::default_pack_json()).unwrap();
        assert_eq!(manifest.name, "Default");
        assert_eq!(manifest.sounds.len(), BUILTIN_SOUNDS.len());
        for sound in BUILTIN_SOUNDS {
            assert_eq!(
                manifest.sounds[sound.event].file_name(sound.event),
                sound.path
            );
        }
    }

    #[test]
    fn a_manifest_round_trips_through_json_without_null_fields() {
        // The default pack setup rewrites a user's manifest to add missing
        // entries, so what it writes back must be as clean as what it read.
        let manifest = PackManifest::from_json(
            r#"{"name":"P","sounds":{"error":{"volume":0.5},"exit":"x.ogg"}}"#,
        )
        .unwrap();
        let text = manifest.to_json();
        assert!(!text.contains("null"), "{text}");
        assert!(!text.contains("volumes"), "{text}");
        assert_eq!(PackManifest::from_json(&text).unwrap(), manifest);
    }
}
