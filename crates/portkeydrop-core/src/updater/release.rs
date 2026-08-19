//! GitHub release metadata: channels, version comparison, and asset choice.
//!
//! All of this is pure data handling, deliberately separated from the HTTP
//! layer so the rules about what counts as "newer" and which file to download
//! can be tested without a network.

use serde::{Deserialize, Serialize};

/// One downloadable file attached to a release.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct ReleaseAsset {
    pub name: String,
    pub browser_download_url: String,
    pub size: u64,
}

/// A GitHub release.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct Release {
    pub tag_name: String,
    pub name: String,
    pub body: String,
    pub prerelease: bool,
    pub draft: bool,
    pub published_at: String,
    pub created_at: String,
    pub assets: Vec<ReleaseAsset>,
}

/// Which stream of releases to follow.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum Channel {
    #[default]
    Stable,
    Nightly,
}

impl Channel {
    /// Parse a settings value, defaulting to stable.
    pub fn from_setting(value: &str) -> Self {
        if value.trim().eq_ignore_ascii_case("nightly") {
            Channel::Nightly
        } else {
            Channel::Stable
        }
    }

    /// The settings value for this channel.
    pub fn as_str(self) -> &'static str {
        match self {
            Channel::Stable => "stable",
            Channel::Nightly => "nightly",
        }
    }

    /// The channel name as shown in the Help menu.
    pub fn display_name(self) -> &'static str {
        match self {
            Channel::Stable => "Stable",
            Channel::Nightly => "Nightly",
        }
    }
}

/// What a release identifies itself as.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ReleaseIdentifier {
    /// A stable release, with its version components.
    Stable { version: String, parts: Vec<u64> },
    /// A nightly build, identified by its `YYYYMMDD` date.
    Nightly { date: String },
}

/// Extract the `YYYYMMDD` date from a nightly tag.
pub fn parse_nightly_date(tag_name: &str) -> Option<String> {
    let lowered = tag_name.to_ascii_lowercase();
    let index = lowered.find("nightly-")?;
    let rest = &tag_name[index + "nightly-".len()..];
    let digits: String = rest.chars().take_while(char::is_ascii_digit).collect();
    if digits.len() == 8 {
        Some(digits)
    } else {
        None
    }
}

/// Parse the leading numeric part of a version string.
///
/// Trailing qualifiers (`-rc1`, `+build`) are ignored: they do not order
/// reliably, and treating `1.2.0-rc1` as newer than `1.2.0` would push people
/// onto pre-releases from the stable channel.
pub fn parse_version(value: &str) -> Option<Vec<u64>> {
    let value = value.trim().trim_start_matches(['v', 'V']);
    let numeric: String = value
        .chars()
        .take_while(|character| character.is_ascii_digit() || *character == '.')
        .collect();
    let numeric = numeric.trim_end_matches('.');
    if numeric.is_empty() {
        return None;
    }
    numeric.split('.').map(|part| part.parse().ok()).collect()
}

/// Compare two version component lists, padding the shorter with zeros.
fn compare_versions(left: &[u64], right: &[u64]) -> std::cmp::Ordering {
    let length = left.len().max(right.len());
    for index in 0..length {
        let a = left.get(index).copied().unwrap_or(0);
        let b = right.get(index).copied().unwrap_or(0);
        match a.cmp(&b) {
            std::cmp::Ordering::Equal => continue,
            other => return other,
        }
    }
    std::cmp::Ordering::Equal
}

impl Release {
    /// Whether this release is a nightly build.
    pub fn is_nightly(&self) -> bool {
        parse_nightly_date(&self.tag_name).is_some()
    }

    /// How this release identifies itself.
    pub fn identifier(&self) -> ReleaseIdentifier {
        if let Some(date) = parse_nightly_date(&self.tag_name) {
            return ReleaseIdentifier::Nightly { date };
        }
        let version = self.tag_name.trim_start_matches(['v', 'V']).to_string();
        let parts = parse_version(&version).unwrap_or_default();
        ReleaseIdentifier::Stable { version, parts }
    }

    /// The version string shown to the user.
    pub fn display_version(&self) -> String {
        match self.identifier() {
            ReleaseIdentifier::Stable { version, .. } => version,
            ReleaseIdentifier::Nightly { date } => format!("nightly {date}"),
        }
    }

    /// When this release was published, for ordering.
    pub fn published_key(&self) -> &str {
        if self.published_at.is_empty() {
            &self.created_at
        } else {
            &self.published_at
        }
    }
}

/// Whether `release` is newer than what is running.
///
/// `current_nightly_date` is the build date of the running nightly, if this is
/// one; without it any nightly counts as newer, which is what a user switching
/// to the nightly channel wants.
pub fn is_update_available(
    release: &Release,
    current_version: &str,
    current_nightly_date: Option<&str>,
) -> bool {
    match release.identifier() {
        ReleaseIdentifier::Nightly { date } => match current_nightly_date {
            Some(current) => date.as_str() > current,
            None => true,
        },
        ReleaseIdentifier::Stable { parts, .. } => {
            let Some(current) = parse_version(current_version) else {
                // An unreadable running version cannot be compared; offering
                // an update on that basis would be guessing.
                return false;
            };
            if parts.is_empty() {
                return false;
            }
            compare_versions(&parts, &current) == std::cmp::Ordering::Greater
        }
    }
}

/// Pick the newest release for a channel.
///
/// Drafts are never offered, and the stable channel excludes pre-releases as
/// well as nightlies.
pub fn select_latest_release(releases: &[Release], channel: Channel) -> Option<&Release> {
    releases
        .iter()
        .filter(|release| !release.draft)
        .filter(|release| match channel {
            Channel::Stable => !release.prerelease && !release.is_nightly(),
            Channel::Nightly => release.is_nightly(),
        })
        .max_by(|a, b| a.published_key().cmp(b.published_key()))
}

/// File extensions that are never the update itself.
const NON_ARTIFACT_EXTENSIONS: [&str; 7] = [
    ".sha256", ".sha512", ".md5", ".sig", ".asc", ".txt", ".json",
];

/// Whether an asset could be the update artifact.
fn is_candidate_artifact(asset: &ReleaseAsset) -> bool {
    let name = asset.name.to_ascii_lowercase();
    if NON_ARTIFACT_EXTENSIONS
        .iter()
        .any(|extension| name.ends_with(extension))
    {
        return false;
    }
    !name.contains("signature") && !name.contains("verify")
}

/// Pick the artifact for a platform and install mode.
///
/// `system` is a lowercase platform name (`windows`, `macos`, `linux`).
pub fn select_asset<'a>(
    release: &'a Release,
    portable: bool,
    system: &str,
) -> Option<&'a ReleaseAsset> {
    let candidates: Vec<&ReleaseAsset> = release
        .assets
        .iter()
        .filter(|asset| is_candidate_artifact(asset))
        .collect();

    let ends_with = |extension: &str| -> Option<&'a ReleaseAsset> {
        candidates
            .iter()
            .copied()
            .find(|asset| asset.name.to_ascii_lowercase().ends_with(extension))
    };

    let system = system.to_ascii_lowercase();
    if system.contains("windows") {
        if portable {
            // A portable install must stay portable: an installer would put
            // the app somewhere else entirely.
            if let Some(asset) = candidates.iter().copied().find(|asset| {
                let name = asset.name.to_ascii_lowercase();
                name.contains("portable") && name.ends_with(".zip")
            }) {
                return Some(asset);
            }
            if let Some(asset) = ends_with(".zip") {
                return Some(asset);
            }
        }
        for extension in [".exe", ".msi"] {
            if let Some(asset) = ends_with(extension) {
                return Some(asset);
            }
        }
    } else if system.contains("darwin") || system.contains("mac") {
        for extension in [".dmg", ".pkg"] {
            if let Some(asset) = ends_with(extension) {
                return Some(asset);
            }
        }
    } else {
        for extension in [".appimage", ".deb", ".rpm", ".tar.gz"] {
            if let Some(asset) = ends_with(extension) {
                return Some(asset);
            }
        }
    }

    candidates
        .first()
        .copied()
        .or_else(|| release.assets.first())
}

/// Find the checksum file covering an artifact.
///
/// A per-artifact file (`app.exe.sha256`) is preferred over a combined one.
pub fn find_checksum_asset<'a>(
    release: &'a Release,
    artifact_name: &str,
) -> Option<&'a ReleaseAsset> {
    let artifact = artifact_name.to_ascii_lowercase();

    for extension in [".sha256", ".sha512"] {
        let expected = format!("{artifact}{extension}");
        if let Some(asset) = release
            .assets
            .iter()
            .find(|asset| asset.name.eq_ignore_ascii_case(&expected))
        {
            return Some(asset);
        }
    }

    const COMBINED: [&str; 5] = [
        "checksums.sha256",
        "sha256sums",
        "checksums.sha512",
        "sha512sums",
        "checksums.txt",
    ];
    release
        .assets
        .iter()
        .find(|asset| COMBINED.contains(&asset.name.to_ascii_lowercase().as_str()))
}

/// A hash algorithm and expected digest.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExpectedChecksum {
    pub algorithm: ChecksumAlgorithm,
    /// Lowercase hex digest.
    pub digest: String,
}

/// Hash algorithms recognised in checksum files.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ChecksumAlgorithm {
    Sha256,
    Sha512,
}

impl ChecksumAlgorithm {
    /// The algorithm implied by a hex digest's length.
    ///
    /// MD5 is deliberately not accepted: it is not a meaningful check against
    /// a tampered download.
    fn from_digest_length(length: usize) -> Option<Self> {
        match length {
            64 => Some(ChecksumAlgorithm::Sha256),
            128 => Some(ChecksumAlgorithm::Sha512),
            _ => None,
        }
    }

    pub fn name(self) -> &'static str {
        match self {
            ChecksumAlgorithm::Sha256 => "SHA-256",
            ChecksumAlgorithm::Sha512 => "SHA-512",
        }
    }
}

/// Find an artifact's expected checksum in a checksum file.
///
/// Handles both the combined `<digest>  <file>` form and a bare digest, which
/// per-artifact files often use.
pub fn parse_checksum_file(content: &str, artifact_name: &str) -> Option<ExpectedChecksum> {
    let artifact = artifact_name.to_ascii_lowercase();
    let lines: Vec<&str> = content
        .trim()
        .lines()
        .filter(|line| !line.trim().is_empty())
        .collect();

    for line in &lines {
        let line = line.trim();
        let mut parts = line.splitn(2, char::is_whitespace);
        let digest = parts.next()?.trim();
        let Some(algorithm) = ChecksumAlgorithm::from_digest_length(digest.len()) else {
            continue;
        };
        if !digest
            .chars()
            .all(|character| character.is_ascii_hexdigit())
        {
            continue;
        }

        match parts.next() {
            // A lone digest is only unambiguous when it is the whole file.
            None if lines.len() == 1 => {
                return Some(ExpectedChecksum {
                    algorithm,
                    digest: digest.to_ascii_lowercase(),
                })
            }
            None => continue,
            Some(name) => {
                // Binary-mode entries are written `*filename`.
                let name = name
                    .trim()
                    .trim_start_matches('*')
                    .trim()
                    .to_ascii_lowercase();
                if name == artifact {
                    return Some(ExpectedChecksum {
                        algorithm,
                        digest: digest.to_ascii_lowercase(),
                    });
                }
            }
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    fn release(tag: &str, published: &str) -> Release {
        Release {
            tag_name: tag.into(),
            published_at: published.into(),
            ..Default::default()
        }
    }

    fn asset(name: &str) -> ReleaseAsset {
        ReleaseAsset {
            name: name.into(),
            browser_download_url: format!("https://example.invalid/{name}"),
            size: 1,
        }
    }

    #[test]
    fn channel_settings_round_trip() {
        assert_eq!(Channel::from_setting("stable"), Channel::Stable);
        assert_eq!(Channel::from_setting("NIGHTLY"), Channel::Nightly);
        // Anything unrecognised must not silently opt someone into nightlies.
        assert_eq!(Channel::from_setting("weekly"), Channel::Stable);
        assert_eq!(Channel::Nightly.as_str(), "nightly");
        assert_eq!(Channel::Stable.display_name(), "Stable");
    }

    #[test]
    fn nightly_tags_yield_their_date() {
        assert_eq!(
            parse_nightly_date("nightly-20260304").as_deref(),
            Some("20260304")
        );
        assert_eq!(
            parse_nightly_date("Nightly-20260304").as_deref(),
            Some("20260304")
        );
        assert_eq!(parse_nightly_date("v1.2.3"), None);
        assert_eq!(parse_nightly_date(""), None);
        // A short or malformed date is not a nightly tag.
        assert_eq!(parse_nightly_date("nightly-2026"), None);
    }

    #[test]
    fn version_strings_parse_into_components() {
        assert_eq!(parse_version("1.2.3"), Some(vec![1, 2, 3]));
        assert_eq!(parse_version("v1.2.3"), Some(vec![1, 2, 3]));
        assert_eq!(parse_version("0.6"), Some(vec![0, 6]));
        assert_eq!(parse_version("not a version"), None);
        assert_eq!(parse_version(""), None);
    }

    #[test]
    fn version_qualifiers_are_ignored() {
        // Treating 1.2.0-rc1 as newer than 1.2.0 would push stable users onto
        // pre-releases.
        assert_eq!(parse_version("1.2.0-rc1"), Some(vec![1, 2, 0]));
        assert_eq!(parse_version("1.2.0+build7"), Some(vec![1, 2, 0]));
    }

    #[test]
    fn versions_compare_component_by_component() {
        assert_eq!(
            compare_versions(&[1, 2, 3], &[1, 2, 3]),
            std::cmp::Ordering::Equal
        );
        assert_eq!(
            compare_versions(&[1, 3, 0], &[1, 2, 9]),
            std::cmp::Ordering::Greater
        );
        assert_eq!(compare_versions(&[0, 9], &[1, 0]), std::cmp::Ordering::Less);
        // 10 is newer than 9, which a string comparison would get wrong.
        assert_eq!(
            compare_versions(&[1, 10], &[1, 9]),
            std::cmp::Ordering::Greater
        );
    }

    #[test]
    fn shorter_versions_are_padded_with_zeros() {
        assert_eq!(
            compare_versions(&[1, 2], &[1, 2, 0]),
            std::cmp::Ordering::Equal
        );
        assert_eq!(
            compare_versions(&[1, 2, 1], &[1, 2]),
            std::cmp::Ordering::Greater
        );
    }

    #[test]
    fn a_newer_stable_release_is_offered() {
        assert!(is_update_available(&release("v0.7.0", ""), "0.6.0", None));
    }

    #[test]
    fn the_same_or_older_stable_release_is_not_offered() {
        assert!(!is_update_available(&release("v0.6.0", ""), "0.6.0", None));
        assert!(!is_update_available(&release("v0.5.0", ""), "0.6.0", None));
    }

    #[test]
    fn an_unreadable_running_version_offers_nothing() {
        // Offering an update on a version we cannot parse is guessing.
        assert!(!is_update_available(
            &release("v0.7.0", ""),
            "unknown",
            None
        ));
    }

    #[test]
    fn a_newer_nightly_is_offered_and_an_older_one_is_not() {
        let nightly = release("nightly-20260304", "");
        assert!(is_update_available(&nightly, "0.6.0", Some("20260301")));
        assert!(!is_update_available(&nightly, "0.6.0", Some("20260304")));
        assert!(!is_update_available(&nightly, "0.6.0", Some("20260401")));
    }

    #[test]
    fn any_nightly_is_offered_when_not_already_running_one() {
        // Someone switching to the nightly channel wants the latest build.
        assert!(is_update_available(
            &release("nightly-20260101", ""),
            "9.9.9",
            None
        ));
    }

    #[test]
    fn the_stable_channel_skips_prereleases_and_nightlies() {
        let releases = vec![
            release("v0.6.0", "2026-01-01T00:00:00Z"),
            Release {
                prerelease: true,
                ..release("v0.7.0-rc1", "2026-02-01T00:00:00Z")
            },
            release("nightly-20260304", "2026-03-04T00:00:00Z"),
        ];
        let latest = select_latest_release(&releases, Channel::Stable).unwrap();
        assert_eq!(latest.tag_name, "v0.6.0");
    }

    #[test]
    fn the_nightly_channel_takes_only_nightlies() {
        let releases = vec![
            release("v0.9.0", "2026-05-01T00:00:00Z"),
            release("nightly-20260304", "2026-03-04T00:00:00Z"),
            release("nightly-20260201", "2026-02-01T00:00:00Z"),
        ];
        let latest = select_latest_release(&releases, Channel::Nightly).unwrap();
        assert_eq!(latest.tag_name, "nightly-20260304");
    }

    #[test]
    fn drafts_are_never_offered() {
        let releases = vec![Release {
            draft: true,
            ..release("v9.9.9", "2026-09-09T00:00:00Z")
        }];
        assert!(select_latest_release(&releases, Channel::Stable).is_none());
    }

    #[test]
    fn releases_are_ordered_by_publication_falling_back_to_creation() {
        let releases = vec![
            release("v0.6.0", "2026-01-01T00:00:00Z"),
            Release {
                created_at: "2026-06-01T00:00:00Z".into(),
                ..release("v0.8.0", "")
            },
        ];
        assert_eq!(
            select_latest_release(&releases, Channel::Stable)
                .unwrap()
                .tag_name,
            "v0.8.0"
        );
    }

    #[test]
    fn an_empty_release_list_offers_nothing() {
        assert!(select_latest_release(&[], Channel::Stable).is_none());
    }

    #[test]
    fn the_display_version_reads_naturally_for_both_channels() {
        assert_eq!(release("v1.2.3", "").display_version(), "1.2.3");
        assert_eq!(
            release("nightly-20260304", "").display_version(),
            "nightly 20260304"
        );
    }

    #[test]
    fn a_windows_install_gets_the_installer() {
        let release = Release {
            assets: vec![
                asset("PortkeyDrop-Setup.exe"),
                asset("PortkeyDrop-portable.zip"),
            ],
            ..Default::default()
        };
        assert_eq!(
            select_asset(&release, false, "windows").unwrap().name,
            "PortkeyDrop-Setup.exe"
        );
    }

    #[test]
    fn a_portable_install_gets_the_portable_zip() {
        // An installer would relocate the app out of its portable folder.
        let release = Release {
            assets: vec![
                asset("PortkeyDrop-Setup.exe"),
                asset("PortkeyDrop-portable.zip"),
            ],
            ..Default::default()
        };
        assert_eq!(
            select_asset(&release, true, "windows").unwrap().name,
            "PortkeyDrop-portable.zip"
        );
    }

    #[test]
    fn a_portable_install_falls_back_to_any_zip() {
        let release = Release {
            assets: vec![asset("PortkeyDrop.zip"), asset("Setup.exe")],
            ..Default::default()
        };
        assert_eq!(
            select_asset(&release, true, "windows").unwrap().name,
            "PortkeyDrop.zip"
        );
    }

    #[test]
    fn macos_and_linux_get_their_native_artifacts() {
        let release = Release {
            assets: vec![
                asset("PortkeyDrop.dmg"),
                asset("PortkeyDrop.AppImage"),
                asset("PortkeyDrop.tar.gz"),
                asset("Setup.exe"),
            ],
            ..Default::default()
        };
        assert_eq!(
            select_asset(&release, false, "darwin").unwrap().name,
            "PortkeyDrop.dmg"
        );
        assert_eq!(
            select_asset(&release, false, "linux").unwrap().name,
            "PortkeyDrop.AppImage"
        );
    }

    #[test]
    fn checksums_and_signatures_are_never_chosen_as_the_download() {
        let release = Release {
            assets: vec![
                asset("checksums.sha256"),
                asset("PortkeyDrop.exe.sig"),
                asset("release-notes.txt"),
                asset("PortkeyDrop-Setup.exe"),
            ],
            ..Default::default()
        };
        assert_eq!(
            select_asset(&release, false, "windows").unwrap().name,
            "PortkeyDrop-Setup.exe"
        );
    }

    #[test]
    fn a_release_with_no_matching_artifact_falls_back_to_the_first_candidate() {
        let release = Release {
            assets: vec![asset("checksums.sha256"), asset("something.bin")],
            ..Default::default()
        };
        assert_eq!(
            select_asset(&release, false, "windows").unwrap().name,
            "something.bin"
        );
    }

    #[test]
    fn a_release_with_no_assets_yields_nothing() {
        assert!(select_asset(&Release::default(), false, "windows").is_none());
    }

    #[test]
    fn a_per_artifact_checksum_file_is_preferred() {
        let release = Release {
            assets: vec![asset("checksums.sha256"), asset("PortkeyDrop.exe.sha256")],
            ..Default::default()
        };
        assert_eq!(
            find_checksum_asset(&release, "PortkeyDrop.exe")
                .unwrap()
                .name,
            "PortkeyDrop.exe.sha256"
        );
    }

    #[test]
    fn a_combined_checksum_file_is_used_when_there_is_no_per_artifact_one() {
        let release = Release {
            assets: vec![asset("SHA256SUMS")],
            ..Default::default()
        };
        assert_eq!(
            find_checksum_asset(&release, "PortkeyDrop.exe")
                .unwrap()
                .name,
            "SHA256SUMS"
        );
    }

    #[test]
    fn a_release_without_checksums_yields_nothing() {
        let release = Release {
            assets: vec![asset("PortkeyDrop.exe")],
            ..Default::default()
        };
        assert!(find_checksum_asset(&release, "PortkeyDrop.exe").is_none());
    }

    #[test]
    fn a_combined_checksum_file_yields_the_matching_line() {
        let content = "\
abc123def4567890abc123def4567890abc123def4567890abc123def4567890  other.zip
1111111111111111111111111111111111111111111111111111111111111111  PortkeyDrop.exe
";
        let checksum = parse_checksum_file(content, "PortkeyDrop.exe").unwrap();
        assert_eq!(checksum.algorithm, ChecksumAlgorithm::Sha256);
        assert_eq!(checksum.digest, "1".repeat(64));
    }

    #[test]
    fn binary_mode_entries_are_matched() {
        let content = format!("{}  *PortkeyDrop.exe\n", "a".repeat(64));
        assert!(parse_checksum_file(&content, "PortkeyDrop.exe").is_some());
    }

    #[test]
    fn a_bare_digest_is_accepted_only_when_it_is_the_whole_file() {
        let single = format!("{}\n", "b".repeat(64));
        assert_eq!(
            parse_checksum_file(&single, "PortkeyDrop.exe")
                .unwrap()
                .digest,
            "b".repeat(64)
        );

        // Among several lines a bare digest names no file and must not be
        // assumed to be ours.
        let ambiguous = format!("{}\n{}\n", "b".repeat(64), "c".repeat(64));
        assert!(parse_checksum_file(&ambiguous, "PortkeyDrop.exe").is_none());
    }

    #[test]
    fn sha512_digests_are_recognised() {
        let content = format!("{}  PortkeyDrop.exe\n", "d".repeat(128));
        assert_eq!(
            parse_checksum_file(&content, "PortkeyDrop.exe")
                .unwrap()
                .algorithm,
            ChecksumAlgorithm::Sha512
        );
    }

    #[test]
    fn md5_digests_are_not_accepted() {
        // MD5 is no protection against a tampered download, so a file offering
        // only MD5 counts as having no checksum at all.
        let content = format!("{}  PortkeyDrop.exe\n", "e".repeat(32));
        assert!(parse_checksum_file(&content, "PortkeyDrop.exe").is_none());
    }

    #[test]
    fn a_checksum_for_a_different_artifact_is_not_used() {
        let content = format!("{}  SomethingElse.exe\n", "f".repeat(64));
        assert!(parse_checksum_file(&content, "PortkeyDrop.exe").is_none());
    }

    #[test]
    fn non_hex_digests_are_skipped() {
        let content = format!(
            "{}  PortkeyDrop.exe\n{}  PortkeyDrop.exe\n",
            "z".repeat(64),
            "a".repeat(64)
        );
        assert_eq!(
            parse_checksum_file(&content, "PortkeyDrop.exe")
                .unwrap()
                .digest,
            "a".repeat(64)
        );
    }

    #[test]
    fn an_empty_checksum_file_yields_nothing() {
        assert!(parse_checksum_file("", "PortkeyDrop.exe").is_none());
        assert!(parse_checksum_file("   \n\n", "PortkeyDrop.exe").is_none());
    }
}
