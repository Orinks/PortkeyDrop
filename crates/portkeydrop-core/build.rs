//! Stamp the nightly build's date into the binary.
//!
//! A nightly's version number is the same as the release it was cut after, so
//! the version alone cannot say which nightly is running. Without the date the
//! updater has nothing to compare a nightly release against and offers every
//! one of them, including the one already installed.
//!
//! Release builds leave this empty, and the version number carries the answer.

fn main() {
    println!("cargo:rerun-if-env-changed=PORTKEYDROP_NIGHTLY_DATE");

    let stamp = std::env::var("PORTKEYDROP_NIGHTLY_DATE").unwrap_or_default();
    let stamp = stamp.trim();

    // Anything but eight digits is treated as absent rather than trusted:
    // the updater compares these as strings, so a stray value would compare
    // in ways nobody intended.
    let stamp = if stamp.len() == 8 && stamp.chars().all(|c| c.is_ascii_digit()) {
        stamp
    } else {
        if !stamp.is_empty() {
            println!(
                "cargo:warning=PORTKEYDROP_NIGHTLY_DATE={stamp:?} is not YYYYMMDD; \
                 this build will not know which nightly it is"
            );
        }
        ""
    };

    println!("cargo:rustc-env=PORTKEYDROP_NIGHTLY_DATE={stamp}");
}
