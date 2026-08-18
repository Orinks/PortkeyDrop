//! The installer detects a running copy by the app's single-instance mutex.
//!
//! `AppMutex` in the Inno Setup script has to name the same mutex the app
//! creates. Nothing links the two: rename the constant and Setup simply stops
//! detecting anything, then installs over a running copy and fails on a file
//! that is still open. The symptom appears at install time, on a user's
//! machine, with no sign of it here.

use portkeydrop_app::single_instance::MUTEX_NAME;

#[test]
fn the_installer_watches_for_the_mutex_the_app_creates() {
    let script = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("installer")
        .join("portkeydrop.iss");
    let text = std::fs::read_to_string(&script).expect("the Inno Setup script");

    let declared = text
        .lines()
        .find_map(|line| line.trim().strip_prefix("AppMutex="))
        .map(str::trim)
        .expect("an AppMutex directive; without one Setup installs over a running copy");

    assert_eq!(
        declared, MUTEX_NAME,
        "the installer watches for {declared} but the app creates {MUTEX_NAME}"
    );
}
