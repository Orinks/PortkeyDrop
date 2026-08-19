//! Checking for and downloading updates from GitHub Releases.
//!
//! Every download is checksum-verified when the release publishes one. A
//! failed check is treated as a hard error and the file is deleted: an update
//! is code about to be executed, so "probably fine" is not good enough.

pub mod apply;
pub mod release;

use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::Duration;

pub use apply::{
    apply_update, can_auto_apply, plan_restart, ApplyContext, RestartKind, RestartPlan,
};
pub use release::{
    find_checksum_asset, is_update_available, parse_checksum_file, parse_nightly_date,
    select_asset, select_latest_release, Channel, ChecksumAlgorithm, ExpectedChecksum, Release,
    ReleaseAsset,
};

use sha2::{Digest, Sha256, Sha512};

/// Repository the updater checks.
pub const GITHUB_OWNER: &str = "Orinks";
pub const GITHUB_REPO: &str = "PortkeyDrop";

/// How many releases to fetch when looking for an update.
const RELEASES_PER_PAGE: u32 = 20;

/// Reported as `(bytes downloaded, total bytes)`; total is 0 when unknown.
pub type DownloadProgress<'a> = &'a mut dyn FnMut(u64, u64) -> bool;

/// An update the user can be offered.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UpdateInfo {
    /// Version as shown to the user.
    pub version: String,
    pub download_url: String,
    pub artifact_name: String,
    pub release_notes: String,
    pub is_nightly: bool,
    pub is_prerelease: bool,
    /// Expected checksum, when the release publishes one.
    pub checksum: Option<ExpectedChecksum>,
}

/// Why an update check or download failed.
#[derive(Debug, thiserror::Error)]
pub enum UpdateError {
    #[error("could not reach the update server: {0}")]
    Network(String),
    #[error("the update server's response could not be read: {0}")]
    Response(String),
    #[error("this release has no download for your platform")]
    NoAsset,
    #[error(
        "the downloaded file does not match the checksum published with the release, so it \
         was discarded. Try again, or download the update from the releases page."
    )]
    ChecksumMismatch,
    #[error("the download was cancelled")]
    Cancelled,
    #[error(transparent)]
    Io(#[from] std::io::Error),
}

/// Checks GitHub for updates and downloads them.
pub struct UpdateService {
    owner: String,
    repo: String,
    client: reqwest::blocking::Client,
}

impl UpdateService {
    /// A service for the app's own repository.
    pub fn new() -> Result<Self, UpdateError> {
        Self::for_repository(GITHUB_OWNER, GITHUB_REPO)
    }

    /// A service for a specific repository.
    pub fn for_repository(owner: &str, repo: &str) -> Result<Self, UpdateError> {
        let client = reqwest::blocking::Client::builder()
            .timeout(Duration::from_secs(30))
            .user_agent(concat!("PortkeyDrop/", env!("CARGO_PKG_VERSION")))
            .build()
            .map_err(|err| UpdateError::Network(err.to_string()))?;
        Ok(Self {
            owner: owner.to_string(),
            repo: repo.to_string(),
            client,
        })
    }

    /// The releases API URL.
    pub fn releases_url(&self) -> String {
        format!(
            "https://api.github.com/repos/{}/{}/releases?per_page={RELEASES_PER_PAGE}",
            self.owner, self.repo
        )
    }

    /// The releases page a user can be pointed at.
    pub fn releases_page_url(&self) -> String {
        format!("https://github.com/{}/{}/releases", self.owner, self.repo)
    }

    /// Fetch the release list.
    pub fn fetch_releases(&self) -> Result<Vec<Release>, UpdateError> {
        let response = self
            .client
            .get(self.releases_url())
            .header(reqwest::header::ACCEPT, "application/vnd.github+json")
            .send()
            .map_err(|err| UpdateError::Network(err.to_string()))?;

        if !response.status().is_success() {
            return Err(UpdateError::Network(format!(
                "the update server replied {}",
                response.status()
            )));
        }
        response
            .json()
            .map_err(|err| UpdateError::Response(err.to_string()))
    }

    /// Look for an update newer than what is running.
    ///
    /// Returns `None` when the current build is already up to date.
    pub fn check_for_update(
        &self,
        current_version: &str,
        current_nightly_date: Option<&str>,
        channel: Channel,
        portable: bool,
        system: &str,
    ) -> Result<Option<UpdateInfo>, UpdateError> {
        let releases = self.fetch_releases()?;
        let Some(release) = select_latest_release(&releases, channel) else {
            return Ok(None);
        };
        if !is_update_available(release, current_version, current_nightly_date) {
            return Ok(None);
        }
        self.describe_update(release, portable, system).map(Some)
    }

    /// Build the offer for a release, resolving its artifact and checksum.
    pub fn describe_update(
        &self,
        release: &Release,
        portable: bool,
        system: &str,
    ) -> Result<UpdateInfo, UpdateError> {
        let asset = select_asset(release, portable, system).ok_or(UpdateError::NoAsset)?;
        let checksum = self.fetch_checksum(release, &asset.name);

        Ok(UpdateInfo {
            version: release.display_version(),
            download_url: asset.browser_download_url.clone(),
            artifact_name: asset.name.clone(),
            release_notes: release.body.clone(),
            is_nightly: release.is_nightly(),
            is_prerelease: release.prerelease,
            checksum,
        })
    }

    /// Fetch and parse the checksum for an artifact, if one is published.
    fn fetch_checksum(&self, release: &Release, artifact_name: &str) -> Option<ExpectedChecksum> {
        let asset = find_checksum_asset(release, artifact_name)?;
        let response = self.client.get(&asset.browser_download_url).send().ok()?;
        if !response.status().is_success() {
            return None;
        }
        let text = response.text().ok()?;
        parse_checksum_file(&text, artifact_name)
    }

    /// Download an update into `destination_dir`, returning the file's path.
    ///
    /// When the release published a checksum, a mismatch deletes the download
    /// and fails: this file is about to be executed.
    pub fn download_update(
        &self,
        update: &UpdateInfo,
        destination_dir: &Path,
        mut progress: Option<DownloadProgress<'_>>,
    ) -> Result<PathBuf, UpdateError> {
        std::fs::create_dir_all(destination_dir)?;
        let destination = destination_dir.join(&update.artifact_name);

        let mut response = self
            .client
            .get(&update.download_url)
            .send()
            .map_err(|err| UpdateError::Network(err.to_string()))?;
        if !response.status().is_success() {
            return Err(UpdateError::Network(format!(
                "the download failed with {}",
                response.status()
            )));
        }
        let total = response.content_length().unwrap_or(0);

        let download = (|| -> Result<(), UpdateError> {
            let mut file = std::fs::File::create(&destination)?;
            let mut buffer = vec![0u8; 64 * 1024];
            let mut downloaded = 0u64;
            loop {
                let read = std::io::Read::read(&mut response, &mut buffer)?;
                if read == 0 {
                    break;
                }
                file.write_all(&buffer[..read])?;
                downloaded += read as u64;
                if let Some(report) = progress.as_deref_mut() {
                    if !report(downloaded, total) {
                        return Err(UpdateError::Cancelled);
                    }
                }
            }
            file.flush()?;
            Ok(())
        })();

        if let Err(err) = download {
            let _ = std::fs::remove_file(&destination);
            return Err(err);
        }

        if let Some(expected) = update.checksum.as_ref() {
            match verify_checksum(&destination, expected) {
                Ok(true) => log::info!("{} matches its published checksum", update.artifact_name),
                Ok(false) | Err(_) => {
                    // An unverifiable update is not installed. Leaving the file
                    // behind would invite someone to run it by hand.
                    let _ = std::fs::remove_file(&destination);
                    return Err(UpdateError::ChecksumMismatch);
                }
            }
        } else {
            log::warn!(
                "{} has no published checksum to verify",
                update.artifact_name
            );
        }

        Ok(destination)
    }
}

/// Hash a file and compare it against the expected digest.
pub fn verify_checksum(path: &Path, expected: &ExpectedChecksum) -> std::io::Result<bool> {
    let mut file = std::fs::File::open(path)?;
    let digest = match expected.algorithm {
        ChecksumAlgorithm::Sha256 => {
            let mut hasher = Sha256::new();
            std::io::copy(&mut file, &mut hasher)?;
            hex(&hasher.finalize())
        }
        ChecksumAlgorithm::Sha512 => {
            let mut hasher = Sha512::new();
            std::io::copy(&mut file, &mut hasher)?;
            hex(&hasher.finalize())
        }
    };
    Ok(digest.eq_ignore_ascii_case(&expected.digest))
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

/// The platform name the asset picker expects.
pub fn current_system() -> &'static str {
    if cfg!(windows) {
        "windows"
    } else if cfg!(target_os = "macos") {
        "macos"
    } else {
        "linux"
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn service() -> UpdateService {
        UpdateService::for_repository("Orinks", "PortkeyDrop").unwrap()
    }

    #[test]
    fn the_releases_url_names_the_repository() {
        let url = service().releases_url();
        assert!(url.contains("Orinks/PortkeyDrop"));
        assert!(url.contains("per_page=20"));
    }

    #[test]
    fn the_releases_page_url_is_a_link_a_user_can_open() {
        assert_eq!(
            service().releases_page_url(),
            "https://github.com/Orinks/PortkeyDrop/releases"
        );
    }

    #[test]
    fn a_matching_sha256_verifies() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("artifact.bin");
        std::fs::write(&path, b"hello world").unwrap();

        // Precomputed SHA-256 of "hello world".
        let expected = ExpectedChecksum {
            algorithm: ChecksumAlgorithm::Sha256,
            digest: "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9".into(),
        };
        assert!(verify_checksum(&path, &expected).unwrap());
    }

    #[test]
    fn a_mismatched_checksum_is_reported() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("artifact.bin");
        std::fs::write(&path, b"hello world").unwrap();

        let expected = ExpectedChecksum {
            algorithm: ChecksumAlgorithm::Sha256,
            digest: "0".repeat(64),
        };
        assert!(!verify_checksum(&path, &expected).unwrap());
    }

    #[test]
    fn checksum_comparison_ignores_hex_case() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("artifact.bin");
        std::fs::write(&path, b"hello world").unwrap();

        let expected = ExpectedChecksum {
            algorithm: ChecksumAlgorithm::Sha256,
            digest: "B94D27B9934D3E08A52E52D7DA7DABFAC484EFE37A5380EE9088F7ACE2EFCDE9".into(),
        };
        assert!(verify_checksum(&path, &expected).unwrap());
    }

    #[test]
    fn a_matching_sha512_verifies() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("artifact.bin");
        std::fs::write(&path, b"").unwrap();

        // SHA-512 of the empty string.
        let expected = ExpectedChecksum {
            algorithm: ChecksumAlgorithm::Sha512,
            digest: "cf83e1357eefb8bdf1542850d66d8007d620e4050b5715dc83f4a921d36ce9ce\
                     47d0d13c5d85f2b0ff8318d2877eec2f63b931bd47417a81a538327af927da3e"
                .into(),
        };
        assert!(verify_checksum(&path, &expected).unwrap());
    }

    #[test]
    fn verifying_a_missing_file_is_an_error() {
        let dir = TempDir::new().unwrap();
        let expected = ExpectedChecksum {
            algorithm: ChecksumAlgorithm::Sha256,
            digest: "0".repeat(64),
        };
        assert!(verify_checksum(&dir.path().join("nope"), &expected).is_err());
    }

    #[test]
    fn the_current_system_is_one_the_asset_picker_understands() {
        assert!(["windows", "macos", "linux"].contains(&current_system()));
    }

    #[test]
    fn a_checksum_mismatch_explains_what_to_do_next() {
        // This message is the whole user-facing outcome of a failed update, so
        // it has to say what happened and what they can do.
        let message = UpdateError::ChecksumMismatch.to_string();
        assert!(message.contains("discarded"));
        assert!(message.contains("releases page"));
    }
}
