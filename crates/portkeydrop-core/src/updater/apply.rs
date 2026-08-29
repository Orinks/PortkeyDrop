//! Applying a downloaded update.
//!
//! A running program cannot replace its own executable, so every path here
//! ends the same way: write a small script, launch it, and exit. The script
//! waits for this process to go away, swaps the files, and starts the new
//! build.
//!
//! Where no such mechanism exists — a Linux tarball, say — that is reported
//! rather than half-attempted, so the user is told to install it themselves
//! instead of watching nothing happen.

use std::path::{Path, PathBuf};

/// How an update will be applied.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RestartKind {
    /// Windows portable: a batch file swaps the folder contents.
    WindowsPortable,
    /// Windows installed: run the downloaded installer.
    WindowsInstaller,
    /// macOS: a shell script replaces the `.app` bundle.
    MacosScript,
    /// Linux AppImage: a shell script replaces the AppImage in place.
    AppImageScript,
    /// Nothing automatic is possible; the user installs it.
    Manual,
}

impl RestartKind {
    /// Whether this update can be applied without the user doing it by hand.
    pub fn is_automatic(self) -> bool {
        self != RestartKind::Manual
    }
}

/// What to run to apply an update.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RestartPlan {
    pub kind: RestartKind,
    /// Command and arguments to launch.
    pub command: Vec<String>,
    /// Script to write before launching, if the plan needs one.
    pub script_path: Option<PathBuf>,
}

/// The environment an update is being applied in.
///
/// Passed explicitly rather than read from the process so the platform rules
/// are testable on any machine.
#[derive(Debug, Clone)]
pub struct ApplyContext {
    /// Lowercase platform name: `windows`, `macos`, `linux`.
    pub system: String,
    /// Whether this is a portable install.
    pub portable: bool,
    /// Path of the running executable.
    pub executable: PathBuf,
    /// Path of the running AppImage, when launched from one.
    pub appimage: Option<PathBuf>,
    /// Directory for generated scripts.
    pub script_dir: PathBuf,
}

impl ApplyContext {
    /// Build a context describing the current process.
    pub fn current(portable: bool) -> Self {
        let system = if cfg!(windows) {
            "windows"
        } else if cfg!(target_os = "macos") {
            "macos"
        } else {
            "linux"
        };
        let executable = std::env::current_exe().unwrap_or_else(|_| PathBuf::from("portkeydrop"));
        Self {
            system: system.to_string(),
            portable,
            executable: executable.clone(),
            appimage: running_appimage_path(std::env::var("APPIMAGE").ok().as_deref()),
            script_dir: executable
                .parent()
                .map(Path::to_path_buf)
                .unwrap_or_else(std::env::temp_dir),
        }
    }
}

/// The AppImage this process was launched from, if any.
///
/// The AppImage runtime exports `APPIMAGE` with the absolute path of the
/// mounted file; without it this is not an AppImage deployment.
pub fn running_appimage_path(appimage_env: Option<&str>) -> Option<PathBuf> {
    let raw = appimage_env?.trim();
    if raw.is_empty() {
        return None;
    }
    let path = PathBuf::from(raw);
    path.is_file().then_some(path)
}

/// Decide how to apply an update.
pub fn plan_restart(update_path: &Path, context: &ApplyContext) -> RestartPlan {
    let system = context.system.to_ascii_lowercase();

    if system.contains("windows") {
        if context.portable {
            let script_path = context.script_dir.join("portkeydrop_portable_update.bat");
            return RestartPlan {
                kind: RestartKind::WindowsPortable,
                command: vec![script_path.to_string_lossy().into_owned()],
                script_path: Some(script_path),
            };
        }
        let script_path = context.script_dir.join("portkeydrop_installer_update.bat");
        return RestartPlan {
            kind: RestartKind::WindowsInstaller,
            command: vec![script_path.to_string_lossy().into_owned()],
            script_path: Some(script_path),
        };
    }

    if system.contains("mac") || system.contains("darwin") {
        let script_path = context.script_dir.join("portkeydrop_update.sh");
        return RestartPlan {
            kind: RestartKind::MacosScript,
            command: vec![
                "bash".to_string(),
                script_path.to_string_lossy().into_owned(),
            ],
            script_path: Some(script_path),
        };
    }

    // Linux only self-updates when running as an AppImage and the download is
    // one too; a tarball or .deb has nowhere to put itself.
    let is_appimage_download = update_path
        .to_string_lossy()
        .to_ascii_lowercase()
        .ends_with(".appimage");
    if context.appimage.is_some() && is_appimage_download {
        let script_path = context.script_dir.join("portkeydrop_appimage_update.sh");
        return RestartPlan {
            kind: RestartKind::AppImageScript,
            command: vec![
                "bash".to_string(),
                script_path.to_string_lossy().into_owned(),
            ],
            script_path: Some(script_path),
        };
    }

    RestartPlan {
        kind: RestartKind::Manual,
        command: vec![update_path.to_string_lossy().into_owned()],
        script_path: None,
    }
}

/// Whether an update can be applied automatically.
///
/// Worth checking before tearing down the UI: when this is false the window
/// should stay up and tell the user where the file is.
pub fn can_auto_apply(update_path: &Path, context: &ApplyContext) -> bool {
    plan_restart(update_path, context).kind.is_automatic()
}

/// The batch file that swaps a Windows portable install.
pub fn build_portable_update_script(
    zip_path: &Path,
    target_dir: &Path,
    exe_path: &Path,
    process_id: u32,
) -> String {
    format!(
        r#"@echo off
setlocal
set "PID={process_id}"
set "ZIP_PATH={zip}"
set "TARGET_DIR={target}"
set "EXE_PATH={exe}"

rem Wait for Portkey Drop to exit before touching its files. findstr rather
rem than find: installing Git with its Unix tools puts a find.exe earlier on
rem PATH, and that one errors here instead of matching, so the loop would fall
rem straight through and the files would be replaced under the running app.
:wait
tasklist /FI "PID eq %PID%" /NH 2>nul | findstr /C:"%PID%" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait
)

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Expand-Archive -LiteralPath '%ZIP_PATH%' -DestinationPath '%TARGET_DIR%' -Force"
if errorlevel 1 (
    echo Portkey Drop could not be updated automatically.
    echo The downloaded file is still at %ZIP_PATH%.
    pause
    exit /b 1
)

del /f /q "%ZIP_PATH%" >nul 2>&1
start "" "%EXE_PATH%"
del /f /q "%~f0" >nul 2>&1
"#,
        zip = zip_path.display(),
        target = target_dir.display(),
        exe = exe_path.display(),
    )
}

/// The batch file that runs a Windows installer once this process has gone.
///
/// Setup guards itself with `AppMutex`, so launching it from a still-running
/// app makes it stop and ask the user to close Portkey Drop by hand. Waiting
/// for the process to exit first means Setup opens straight onto its own first
/// page. The installer offers to relaunch the app on its last page, so this
/// does not start it again.
pub fn build_installer_update_script(installer_path: &Path, process_id: u32) -> String {
    format!(
        r#"@echo off
setlocal
set "PID={process_id}"
set "INSTALLER={installer}"

rem Wait for Portkey Drop to exit so Setup does not find its mutex and stop to
rem ask for it to be closed. findstr rather than find: installing Git with its
rem Unix tools puts a find.exe earlier on PATH, and that one errors here
rem instead of matching, so the wait would be skipped and we would be back to
rem Setup asking for the app to be closed.
:wait
tasklist /FI "PID eq %PID%" /NH 2>nul | findstr /C:"%PID%" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait
)

start "" /wait "%INSTALLER%"
del /f /q "%INSTALLER%" >nul 2>&1
del /f /q "%~f0" >nul 2>&1
"#,
        installer = installer_path.display(),
    )
}

/// The shell script that replaces a macOS app bundle.
pub fn build_macos_update_script(update_path: &Path, app_path: &Path, process_id: u32) -> String {
    format!(
        r#"#!/bin/bash
set -u
PID={process_id}
UPDATE_PATH="{update}"
APP_PATH="{app}"

# Wait for Portkey Drop to exit before replacing its bundle.
while kill -0 "$PID" 2>/dev/null; do
    sleep 1
done

if [[ "$UPDATE_PATH" == *.dmg ]]; then
    MOUNT_POINT=$(mktemp -d /tmp/portkeydrop_update.XXXXXX)
    hdiutil attach "$UPDATE_PATH" -nobrowse -quiet -mountpoint "$MOUNT_POINT" || exit 1
    NEW_APP=$(find "$MOUNT_POINT" -maxdepth 1 -name '*.app' -print -quit)
    if [[ -n "$NEW_APP" ]]; then
        rm -rf "$APP_PATH"
        cp -R "$NEW_APP" "$APP_PATH"
    fi
    hdiutil detach "$MOUNT_POINT" -quiet
    rmdir "$MOUNT_POINT" 2>/dev/null
else
    open "$UPDATE_PATH"
    exit 0
fi

open "$APP_PATH"
rm -f "$0"
"#,
        update = update_path.display(),
        app = app_path.display(),
    )
}

/// The shell script that replaces a running AppImage.
pub fn build_appimage_update_script(
    update_path: &Path,
    appimage_path: &Path,
    process_id: u32,
) -> String {
    format!(
        r#"#!/bin/bash
set -u
PID={process_id}
UPDATE_PATH="{update}"
APPIMAGE_PATH="{appimage}"

# Wait for Portkey Drop to exit before replacing the AppImage.
while kill -0 "$PID" 2>/dev/null; do
    sleep 1
done

# Keep the old build until the new one is in place, so a failed copy is
# recoverable rather than leaving nothing to run.
BACKUP_PATH="$APPIMAGE_PATH.old"
mv -f "$APPIMAGE_PATH" "$BACKUP_PATH" 2>/dev/null
if ! cp -f "$UPDATE_PATH" "$APPIMAGE_PATH"; then
    mv -f "$BACKUP_PATH" "$APPIMAGE_PATH" 2>/dev/null
    exit 1
fi

chmod +x "$APPIMAGE_PATH"
rm -f "$BACKUP_PATH" "$UPDATE_PATH"
"$APPIMAGE_PATH" &
rm -f "$0"
"#,
        update = update_path.display(),
        appimage = appimage_path.display(),
    )
}

/// Write the script a plan needs, if any, and make it executable.
pub fn write_plan_script(
    plan: &RestartPlan,
    update_path: &Path,
    context: &ApplyContext,
) -> std::io::Result<()> {
    let Some(script_path) = plan.script_path.as_ref() else {
        return Ok(());
    };
    let process_id = std::process::id();

    let contents = match plan.kind {
        RestartKind::WindowsPortable => {
            let target_dir = context
                .executable
                .parent()
                .unwrap_or(&context.executable)
                .to_path_buf();
            build_portable_update_script(update_path, &target_dir, &context.executable, process_id)
        }
        RestartKind::MacosScript => {
            // The executable lives at Foo.app/Contents/MacOS/foo, so the
            // bundle is three levels up.
            let app_path = context
                .executable
                .ancestors()
                .nth(3)
                .unwrap_or(&context.executable)
                .to_path_buf();
            build_macos_update_script(update_path, &app_path, process_id)
        }
        RestartKind::AppImageScript => {
            let appimage = context
                .appimage
                .clone()
                .unwrap_or_else(|| context.executable.clone());
            build_appimage_update_script(update_path, &appimage, process_id)
        }
        RestartKind::WindowsInstaller => build_installer_update_script(update_path, process_id),
        RestartKind::Manual => return Ok(()),
    };

    if let Some(parent) = script_path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(script_path, contents)?;

    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(script_path, std::fs::Permissions::from_mode(0o700))?;
    }
    Ok(())
}

/// Launch the update and report whether it started.
///
/// On success the caller should exit immediately: the script is waiting for
/// this process to go away before it touches any files.
pub fn apply_update(update_path: &Path, context: &ApplyContext) -> std::io::Result<bool> {
    let plan = plan_restart(update_path, context);
    if !plan.kind.is_automatic() {
        log::warn!(
            "this update must be installed manually: {}",
            update_path.display()
        );
        return Ok(false);
    }

    write_plan_script(&plan, update_path, context)?;

    let (program, arguments) = plan.command.split_first().ok_or_else(|| {
        std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "the update plan has no command",
        )
    })?;

    let mut command = std::process::Command::new(program);
    command.args(arguments);
    if let Some(parent) = context.executable.parent() {
        command.current_dir(parent);
    }
    command.spawn()?;
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn context(system: &str, portable: bool, dir: &TempDir) -> ApplyContext {
        ApplyContext {
            system: system.into(),
            portable,
            executable: dir.path().join("portkeydrop.exe"),
            appimage: None,
            script_dir: dir.path().to_path_buf(),
        }
    }

    #[test]
    fn a_windows_install_runs_the_installer_from_a_batch_file() {
        // Not the installer directly: Setup guards itself with AppMutex and
        // would stop to ask for the running app to be closed.
        let dir = TempDir::new().unwrap();
        let plan = plan_restart(
            Path::new("C:/tmp/Setup.exe"),
            &context("windows", false, &dir),
        );
        assert_eq!(plan.kind, RestartKind::WindowsInstaller);
        let script = plan.script_path.clone().expect("the plan needs a script");
        assert!(script.ends_with("portkeydrop_installer_update.bat"));
        assert_eq!(plan.command, vec![script.to_string_lossy().into_owned()]);
    }

    #[test]
    fn the_installer_script_waits_for_this_process_before_starting_setup() {
        let script = build_installer_update_script(Path::new("C:/tmp/Setup.exe"), 4242);
        assert!(
            script.contains(r#"set "PID=4242""#),
            "it knows the process id"
        );
        let wait_at = script
            .find(r#"/FI "PID eq %PID%""#)
            .expect("it waits on the process id");
        let start_at = script
            .find("start \"\" /wait")
            .expect("it starts the installer");
        assert!(
            wait_at < start_at,
            "setup must not be started until the app has gone"
        );
        assert!(script.contains("C:/tmp/Setup.exe"));
    }

    #[test]
    fn the_wait_loops_match_with_findstr_not_find() {
        // Installing Git with its Unix tools puts a find.exe ahead of the
        // Windows one on PATH; it errors here instead of matching, so the loop
        // falls straight through and the update runs while the app is still
        // up, which is the whole thing the wait exists to prevent. Nothing
        // shadows findstr.
        for script in [
            build_installer_update_script(Path::new("C:/tmp/Setup.exe"), 1),
            build_portable_update_script(
                Path::new("C:/tmp/p.zip"),
                Path::new("C:/app"),
                Path::new("C:/app/portkeydrop.exe"),
                1,
            ),
        ] {
            assert!(
                script.contains(r#"findstr /C:"%PID%""#),
                "the wait does not match with findstr"
            );
            assert!(
                !script.contains("| find "),
                "the wait uses find, which a Unix find on PATH shadows"
            );
        }
    }

    #[test]
    fn the_installer_script_does_not_relaunch_the_app() {
        // Setup's own last page offers that; doing it here too would open two.
        let script = build_installer_update_script(Path::new("C:/tmp/Setup.exe"), 1);
        assert!(!script.contains("portkeydrop.exe"));
    }

    #[test]
    fn the_installer_script_is_written_before_it_is_launched() {
        let dir = TempDir::new().unwrap();
        let context = context("windows", false, &dir);
        let update = Path::new("C:/tmp/Setup.exe");
        let plan = plan_restart(update, &context);
        write_plan_script(&plan, update, &context).unwrap();
        let written = std::fs::read_to_string(plan.script_path.unwrap()).unwrap();
        assert!(written.contains("Setup.exe"));
    }

    #[test]
    fn a_windows_portable_install_uses_a_batch_file() {
        let dir = TempDir::new().unwrap();
        let plan = plan_restart(Path::new("C:/tmp/p.zip"), &context("windows", true, &dir));
        assert_eq!(plan.kind, RestartKind::WindowsPortable);
        assert!(plan
            .script_path
            .unwrap()
            .ends_with("portkeydrop_portable_update.bat"));
    }

    #[test]
    fn macos_uses_a_shell_script() {
        let dir = TempDir::new().unwrap();
        let plan = plan_restart(Path::new("/tmp/app.dmg"), &context("macos", false, &dir));
        assert_eq!(plan.kind, RestartKind::MacosScript);
        assert_eq!(plan.command[0], "bash");
    }

    #[test]
    fn a_linux_appimage_updates_itself_in_place() {
        let dir = TempDir::new().unwrap();
        let appimage = dir.path().join("PortkeyDrop.AppImage");
        std::fs::write(&appimage, b"appimage").unwrap();
        let context = ApplyContext {
            appimage: Some(appimage),
            ..context("linux", false, &dir)
        };

        let plan = plan_restart(Path::new("/tmp/new.AppImage"), &context);
        assert_eq!(plan.kind, RestartKind::AppImageScript);
    }

    #[test]
    fn a_linux_tarball_must_be_installed_by_hand() {
        // There is nowhere for a tarball to install itself, and pretending
        // otherwise would leave the user staring at a window that did nothing.
        let dir = TempDir::new().unwrap();
        let plan = plan_restart(Path::new("/tmp/app.tar.gz"), &context("linux", false, &dir));
        assert_eq!(plan.kind, RestartKind::Manual);
        assert!(!can_auto_apply(
            Path::new("/tmp/app.tar.gz"),
            &context("linux", false, &dir)
        ));
    }

    #[test]
    fn a_non_appimage_download_is_manual_even_when_running_as_an_appimage() {
        let dir = TempDir::new().unwrap();
        let appimage = dir.path().join("PortkeyDrop.AppImage");
        std::fs::write(&appimage, b"appimage").unwrap();
        let context = ApplyContext {
            appimage: Some(appimage),
            ..context("linux", false, &dir)
        };

        assert_eq!(
            plan_restart(Path::new("/tmp/app.deb"), &context).kind,
            RestartKind::Manual
        );
    }

    #[test]
    fn an_appimage_download_is_manual_when_not_running_as_one() {
        let dir = TempDir::new().unwrap();
        let plan = plan_restart(
            Path::new("/tmp/new.AppImage"),
            &context("linux", false, &dir),
        );
        assert_eq!(plan.kind, RestartKind::Manual);
    }

    #[test]
    fn every_automatic_plan_is_reported_as_automatic() {
        assert!(RestartKind::WindowsPortable.is_automatic());
        assert!(RestartKind::WindowsInstaller.is_automatic());
        assert!(RestartKind::MacosScript.is_automatic());
        assert!(RestartKind::AppImageScript.is_automatic());
        assert!(!RestartKind::Manual.is_automatic());
    }

    #[test]
    fn the_appimage_environment_variable_must_point_at_a_real_file() {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("App.AppImage");
        std::fs::write(&path, b"x").unwrap();

        assert_eq!(
            running_appimage_path(Some(&path.to_string_lossy())),
            Some(path)
        );
        assert_eq!(running_appimage_path(Some("/nowhere/App.AppImage")), None);
        assert_eq!(running_appimage_path(Some("")), None);
        assert_eq!(running_appimage_path(None), None);
    }

    #[test]
    fn the_portable_script_waits_for_the_process_and_names_the_paths() {
        let script = build_portable_update_script(
            Path::new(r"C:\tmp\p.zip"),
            Path::new(r"C:\app"),
            Path::new(r"C:\app\portkeydrop.exe"),
            4242,
        );
        // Extracting over a running executable would fail, so the wait is the
        // load-bearing part of this script.
        assert!(script.contains("set \"PID=4242\""));
        assert!(script.contains("tasklist"));
        assert!(script.contains(r"C:\tmp\p.zip"));
        assert!(script.contains(r"C:\app\portkeydrop.exe"));
        assert!(script.contains("Expand-Archive"));
    }

    #[test]
    fn the_portable_script_tells_the_user_where_the_download_is_if_it_fails() {
        let script = build_portable_update_script(
            Path::new(r"C:\tmp\p.zip"),
            Path::new(r"C:\app"),
            Path::new(r"C:\app\portkeydrop.exe"),
            1,
        );
        assert!(script.contains("could not be updated automatically"));
        assert!(script.contains("%ZIP_PATH%"));
    }

    #[test]
    fn the_macos_script_waits_and_replaces_the_bundle() {
        let script = build_macos_update_script(
            Path::new("/tmp/app.dmg"),
            Path::new("/Applications/Portkey Drop.app"),
            4242,
        );
        assert!(script.contains("PID=4242"));
        assert!(script.contains("kill -0"));
        assert!(script.contains("hdiutil attach"));
        assert!(script.contains("/Applications/Portkey Drop.app"));
    }

    #[test]
    fn the_appimage_script_keeps_a_backup_until_the_copy_succeeds() {
        // Without the backup a failed copy would leave nothing to run at all.
        let script = build_appimage_update_script(
            Path::new("/tmp/new.AppImage"),
            Path::new("/home/a/PortkeyDrop.AppImage"),
            4242,
        );
        assert!(script.contains("BACKUP_PATH"));
        assert!(script.contains("mv -f \"$BACKUP_PATH\" \"$APPIMAGE_PATH\""));
        assert!(script.contains("chmod +x"));
    }

    #[test]
    fn writing_a_plans_script_produces_a_runnable_file() {
        let dir = TempDir::new().unwrap();
        let context = context("windows", true, &dir);
        let update = dir.path().join("p.zip");
        let plan = plan_restart(&update, &context);

        write_plan_script(&plan, &update, &context).unwrap();

        let script = plan.script_path.unwrap();
        assert!(script.exists());
        assert!(std::fs::read_to_string(&script)
            .unwrap()
            .contains("Expand-Archive"));
    }

    #[test]
    fn a_plan_with_no_script_writes_nothing() {
        let dir = TempDir::new().unwrap();
        let context = context("windows", false, &dir);
        let update = dir.path().join("Setup.exe");
        let plan = plan_restart(&update, &context);
        assert!(write_plan_script(&plan, &update, &context).is_ok());
    }

    #[test]
    fn a_manual_update_is_not_launched() {
        let dir = TempDir::new().unwrap();
        let update = dir.path().join("app.tar.gz");
        std::fs::write(&update, b"tarball").unwrap();
        assert!(!apply_update(&update, &context("linux", false, &dir)).unwrap());
    }
}
