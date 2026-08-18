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
        format!("PortkeyDrop-{version}-macOS.dmg"),
        "checksums.txt".to_string(),
    ]
}

/// The nightly naming, which uses a date stamp instead of a version.
fn nightly_assets(stamp: &str) -> Vec<String> {
    vec![
        format!("PortkeyDrop-nightly-{stamp}-windows-setup.exe"),
        format!("PortkeyDrop-nightly-{stamp}-windows-portable.zip"),
        format!("PortkeyDrop-nightly-{stamp}-macOS.dmg"),
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

#[test]
fn a_mac_picks_the_disk_image() {
    // Only a DMG can be installed without the user finishing the job in
    // Finder: the macOS apply script mounts it and swaps the bundle, and
    // falls back to merely opening anything else.
    let release = release_with(stable_assets("0.6.0"));
    for portable in [true, false] {
        let asset = select_asset(&release, portable, "macos").expect("an asset for macOS");
        assert_eq!(asset.name, "PortkeyDrop-0.6.0-macOS.dmg");
    }
}

#[test]
fn a_mac_does_not_get_handed_a_windows_build() {
    // The Windows ZIP sorts before the DMG in the asset list, and the
    // fallback arm returns whichever candidate comes first.
    let release = release_with(nightly_assets("20260818"));
    let asset = select_asset(&release, false, "macos").expect("an asset for macOS");
    assert!(asset.name.ends_with(".dmg"), "got {}", asset.name);
}
