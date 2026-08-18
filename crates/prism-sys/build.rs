//! Stage the vendored Prism shared library next to the build output.
//!
//! Prism is loaded at run time (see `src/loader.rs`), so nothing is linked
//! here. What this script does is copy the vendored shared object into the
//! Cargo target directory so `cargo run` and `cargo test` find it without the
//! developer having to touch PATH.

use std::env;
use std::fs;
use std::path::{Path, PathBuf};

/// Shared-library file name for the target platform.
fn library_file_name(target_os: &str) -> &'static str {
    match target_os {
        "windows" => "prism.dll",
        "macos" => "libprism.dylib",
        _ => "libprism.so",
    }
}

/// Walk up from `OUT_DIR` to the profile directory (`target/debug`), which is
/// where Cargo places binaries and where the loader looks first.
fn profile_dir(out_dir: &Path) -> Option<PathBuf> {
    // OUT_DIR is <target>/<profile>/build/<pkg>-<hash>/out
    out_dir.ancestors().nth(3).map(Path::to_path_buf)
}

fn main() {
    println!("cargo:rerun-if-changed=vendor");

    let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap());
    let out_dir = PathBuf::from(env::var("OUT_DIR").unwrap());
    let target_os = env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();
    let file_name = library_file_name(&target_os);

    let vendored = manifest_dir.join("vendor").join("bin").join(file_name);
    println!(
        "cargo:vendor_dir={}",
        manifest_dir.join("vendor").join("bin").display()
    );

    if !vendored.is_file() {
        println!(
            "cargo:warning=prism-sys: {} is not vendored for this platform; \
             speech output will be unavailable unless the library is installed system-wide",
            file_name
        );
        return;
    }

    let Some(profile_dir) = profile_dir(&out_dir) else {
        return;
    };
    let destination = profile_dir.join(file_name);
    // Copy failures are not fatal: the loader also searches the vendor
    // directory and the system library path.
    if let Err(err) = fs::copy(&vendored, &destination) {
        println!("cargo:warning=prism-sys: could not stage {file_name}: {err}");
    }
}
