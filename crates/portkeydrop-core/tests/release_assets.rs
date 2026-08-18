//! The names CI publishes have to be the names the updater looks for.
//!
//! `select_asset` matches on suffixes and on the word "portable", and the
//! release job in `.github/workflows/build.yml` builds those names with a
//! `case` statement. Nothing links the two but this test: rename an asset in
//! CI and the only symptom is every installed copy quietly failing to find
//! its update.

use portkeydrop_core::updater::{select_asset, Release, ReleaseAsset};

/// Exactly what the release job writes into `assets/` for a stable release.
fn stable_assets(version: &str) -> Vec<String> {
    vec![
        format!("PortkeyDrop-{version}-windows-setup.exe"),
        format!("PortkeyDrop-{version}-windows-portable.zip"),
        "checksums.txt".to_string(),
    ]
}

/// The nightly naming, which uses a date stamp instead of a version.
fn nightly_assets(stamp: &str) -> Vec<String> {
    vec![
        format!("PortkeyDrop-nightly-{stamp}-windows-setup.exe"),
        format!("PortkeyDrop-nightly-{stamp}-windows-portable.zip"),
        "checksums.txt".to_string(),
    ]
}

fn release_with(names: Vec<String>) -> Release {
    Release {
        tag_name: "v0.6.0".to_string(),
        name: "PortkeyDrop v0.6.0".to_string(),
        published_at: "2026-08-18T00:00:00Z".to_string(),
        assets: names
            .into_iter()
            .map(|name| ReleaseAsset {
                browser_download_url: format!("https://example.invalid/{name}"),
                name,
                size: 1,
            })
            .collect(),
        ..Release::default()
    }
}

#[test]
fn an_installed_windows_copy_picks_the_setup_exe() {
    let release = release_with(stable_assets("0.6.0"));
    let asset = select_asset(&release, false, "windows").expect("an asset for Windows");
    assert_eq!(asset.name, "PortkeyDrop-0.6.0-windows-setup.exe");
}

#[test]
fn a_portable_windows_copy_picks_the_portable_zip() {
    // A portable install that fetched the installer would relocate itself off
    // the stick it was running from.
    let release = release_with(stable_assets("0.6.0"));
    let asset = select_asset(&release, true, "windows").expect("an asset for Windows");
    assert_eq!(asset.name, "PortkeyDrop-0.6.0-windows-portable.zip");
}

#[test]
fn the_nightly_names_resolve_the_same_way() {
    let release = release_with(nightly_assets("20260818"));
    assert_eq!(
        select_asset(&release, false, "windows").map(|asset| asset.name.as_str()),
        Some("PortkeyDrop-nightly-20260818-windows-setup.exe")
    );
    assert_eq!(
        select_asset(&release, true, "windows").map(|asset| asset.name.as_str()),
        Some("PortkeyDrop-nightly-20260818-windows-portable.zip")
    );
}

#[test]
fn the_checksum_file_is_never_offered_as_the_download() {
    // It is an asset like any other; picking it would "update" the app to a
    // text file.
    let release = release_with(stable_assets("0.6.0"));
    for portable in [true, false] {
        let asset = select_asset(&release, portable, "windows").expect("an asset");
        assert_ne!(asset.name, "checksums.txt");
    }
}
