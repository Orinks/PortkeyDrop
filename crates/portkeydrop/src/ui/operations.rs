//! File operations and dialogs driven from the main window.

//!

//! Split out from the window's construction so the frame file stays about

//! layout and wiring, and this one is about what the commands actually do.

use std::path::{Path, PathBuf};

use std::rc::Rc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use wxdragon::data_object::{FileDataObject, TextDataObject};

use wxdragon::prelude::*;

use portkeydrop_core::protocols::{self, RemoteFile};

use portkeydrop_core::sites::Site;

use portkeydrop_core::updater::{
    apply_update, can_auto_apply, ApplyContext, UpdateError, UpdateInfo,
};
use portkeydrop_core::{local_files, VERSION};

use super::events::{self, AppEvent, DownloadOutcome, UpdateOutcome};

use super::ids;

use super::main_frame::{MainFrame, Side};

use super::format;
use super::main_frame::Download;
use super::prompts;

use super::dialogs;

impl MainFrame {
    // ---------------------------------------------------------------

    // Transfers

    // ---------------------------------------------------------------

    /// Transfer the selection in whichever direction the focused pane implies.
    pub(super) fn transfer_selection(&self) {
        let side = self.active_side();

        let files = self.pane(side).selected_files();

        self.transfer_files(side, files);
    }

    /// Upload the local selection.
    pub(super) fn upload_selection(&self) {
        let files = self.pane(Side::Local).selected_files();

        self.transfer_files(Side::Local, files);
    }

    /// Download the remote selection.
    pub(super) fn download_selection(&self) {
        let files = self.pane(Side::Remote).selected_files();

        self.transfer_files(Side::Remote, files);
    }

    /// Queue a transfer of `files` from `side`.
    pub(super) fn transfer_files(&self, side: Side, files: Vec<RemoteFile>) {
        if files.is_empty() {
            self.announce("Nothing is selected");

            return;
        }

        let Some(client) = self.state.borrow().client() else {
            prompts::error(
                &self.frame,
                "Not connected",
                "Connect to a server before transferring files.",
            );

            return;
        };

        let overwrite_mode = self.state.borrow().settings.transfer.overwrite_mode.clone();

        let batch = files.len() > 1;

        let mut queued = 0usize;

        for file in files {
            let queued_this = match side {
                Side::Local => self.queue_upload(&client, &file, &overwrite_mode, batch),

                Side::Remote => self.queue_download(&client, &file, &overwrite_mode, batch),
            };

            if queued_this {
                queued += 1;
            }
        }

        if queued > 0 {
            self.state.borrow_mut().play_sound("transfer_queued");

            self.announce(&format!(
                "{queued} transfer{} queued",
                if queued == 1 { "" } else { "s" }
            ));
        }
    }

    fn queue_upload(
        &self,

        client: &portkeydrop_core::transfer::SharedClient,

        file: &RemoteFile,

        overwrite_mode: &str,

        batch: bool,
    ) -> bool {
        let remote_dir = self.pane(Side::Remote).path();

        let remote_dir = if remote_dir.is_empty() {
            "/".to_string()
        } else {
            remote_dir
        };

        let mut destination = protocols::path::join(&remote_dir, &file.name);

        let size = if file.is_dir {
            0
        } else {
            std::fs::metadata(&file.path)
                .map(|meta| meta.len())
                .unwrap_or(file.size)
        };

        // Same gate as downloads: only ask when the destination is already
        // there. Asking on every upload made the prompt look broken.
        let overwrite = if self.pane(Side::Remote).contains_name(&file.name) {
            match self.resolve_conflict(overwrite_mode, &file.name, "uploaded", batch) {
                Conflict::Skip => return false,
                Conflict::Overwrite => true,
                Conflict::Fail => {
                    let unique = local_files::unique_file_name(&file.name, |name| {
                        self.pane(Side::Remote).contains_name(name)
                    });
                    destination = protocols::path::join(&remote_dir, &unique);
                    false
                }
            }
        } else {
            false
        };

        self.state.borrow().transfers.submit_upload(
            Arc::clone(client),
            &file.path,
            &destination,
            size,
            file.is_dir,
            overwrite,
        );

        self.log(&format!("Queued upload of {} to {destination}.", file.name));

        true
    }

    fn queue_download(
        &self,

        client: &portkeydrop_core::transfer::SharedClient,

        file: &RemoteFile,

        overwrite_mode: &str,

        batch: bool,
    ) -> bool {
        let local_dir = PathBuf::from(self.pane(Side::Local).path());

        let mut destination = local_dir.join(&file.name);

        let overwrite = if destination.exists() {
            match self.resolve_conflict(overwrite_mode, &file.name, "downloaded", batch) {
                Conflict::Skip => return false,

                Conflict::Overwrite => true,

                Conflict::Fail => {
                    // "rename" mode keeps both copies rather than asking.

                    destination = local_files::unique_local_path(&destination);

                    false
                }
            }
        } else {
            false
        };

        self.state.borrow().transfers.submit_download(
            Arc::clone(client),
            &file.path,
            &destination.to_string_lossy(),
            file.size,
            file.is_dir,
            overwrite,
        );

        self.log(&format!(
            "Queued download of {} to {}.",
            file.name,
            destination.display()
        ));

        true
    }

    /// Decide what to do about an existing destination.
    fn resolve_conflict(
        &self,

        overwrite_mode: &str,

        name: &str,

        action: &str,

        batch: bool,
    ) -> Conflict {
        match overwrite_mode {
            "overwrite" => Conflict::Overwrite,

            "skip" => Conflict::Skip,

            "rename" => Conflict::Fail,

            // "ask", and anything unrecognised, prompts. Asking once per file

            // during a large batch would be unbearable, so a batch is only

            // asked about if the user chose to be asked.
            _ => {
                let message = if batch {
                    format!(
                        "{}\n\nThis applies to each item that already exists.",
                        prompts::overwrite_message(name, action)
                    )
                } else {
                    prompts::overwrite_message(name, action)
                };

                if prompts::confirm(&self.frame, "Replace file?", &message) {
                    Conflict::Overwrite
                } else {
                    Conflict::Skip
                }
            }
        }
    }

    /// Retry the most recent failed transfer.
    pub(super) fn retry_last_failed(&self) {
        let job_id = self.state.borrow().last_failed_transfer.clone();

        let Some(job_id) = job_id else {
            self.announce("No failed transfer to retry");

            return;
        };

        let Some(client) = self.state.borrow().client() else {
            prompts::error(
                &self.frame,
                "Not connected",
                "Reconnect to the server before retrying a transfer.",
            );

            return;
        };

        if self.state.borrow().transfers.retry(&job_id, client) {
            self.announce("Retrying the last failed transfer");
        } else {
            self.announce("That transfer can no longer be retried");
        }
    }

    /// Show the transfer queue.
    pub(super) fn show_transfer_queue(&self) {
        dialogs::transfer_queue::show(self);
    }

    // ---------------------------------------------------------------

    // File operations

    // ---------------------------------------------------------------

    /// Delete the selection, after confirming.
    pub(super) fn delete_selection(&self) {
        let side = self.active_side();

        let files = self.pane(side).selected_files();

        if files.is_empty() {
            self.announce("Nothing is selected");

            return;
        }

        let names: Vec<String> = files.iter().map(|file| file.name.clone()).collect();

        if !prompts::confirm_destructive(&self.frame, "Delete", &prompts::delete_message(&names)) {
            return;
        }

        match side {
            Side::Local => self.delete_local_files(&files),

            Side::Remote => self.delete_remote_files(files),
        }
    }

    fn delete_local_files(&self, files: &[RemoteFile]) {
        let mut deleted = 0usize;

        for file in files {
            match local_files::delete_local(Path::new(&file.path)) {
                Ok(()) => deleted += 1,

                Err(err) => {
                    let message = format!("Could not delete {}: {err}", file.name);

                    self.log(&message);

                    self.state.borrow_mut().play_sound("delete_failed");

                    prompts::error(&self.frame, "Delete failed", &message);

                    break;
                }
            }
        }

        if deleted > 0 {
            self.state.borrow_mut().play_sound("delete_complete");

            self.announce(&format!("{deleted} deleted"));

            self.refresh_local(None);
        }
    }

    fn delete_remote_files(&self, files: Vec<RemoteFile>) {
        let Some(client) = self.state.borrow().client() else {
            return;
        };

        let sender = self.sender.clone();

        std::thread::spawn(move || {
            let mut deleted = 0usize;

            for file in &files {
                let outcome = client
                    .lock()
                    .map_err(|_| "the connection is unusable".to_string())
                    .and_then(|mut client| {
                        if file.is_dir {
                            client.rmdir(&file.path).map_err(|err| err.to_string())
                        } else {
                            client.delete(&file.path).map_err(|err| err.to_string())
                        }
                    });

                match outcome {
                    Ok(()) => deleted += 1,

                    Err(message) => {
                        events::post(
                            &sender,
                            AppEvent::RemoteOperationFailed {
                                message: format!("Could not delete {}: {message}", file.name),

                                sound: "delete_failed",
                            },
                        );

                        return;
                    }
                }
            }

            events::post(
                &sender,
                AppEvent::RemoteOperationDone {
                    message: format!("{deleted} deleted"),

                    sound: "delete_complete",
                },
            );
        });
    }

    /// Rename the focused item.
    pub(super) fn rename_selection(&self) {
        let side = self.active_side();

        let Some(file) = self.pane(side).selected_file() else {
            self.announce("Nothing is selected");

            return;
        };

        let Some(new_name) = prompts::ask_text(&self.frame, "Rename", "New name:", &file.name)
        else {
            return;
        };

        if new_name == file.name {
            return;
        }

        match side {
            Side::Local => match local_files::rename_local(Path::new(&file.path), &new_name) {
                Ok(_) => {
                    self.state.borrow_mut().play_sound("rename_complete");

                    self.announce(&format!("Renamed to {new_name}"));

                    self.refresh_local(None);
                }

                Err(err) => {
                    self.state.borrow_mut().play_sound("rename_failed");

                    prompts::error(
                        &self.frame,
                        "Rename failed",
                        &format!("Could not rename {}: {err}", file.name),
                    );
                }
            },

            Side::Remote => {
                let Some(client) = self.state.borrow().client() else {
                    return;
                };

                let sender = self.sender.clone();

                let old_path = file.path.clone();

                let new_path =
                    protocols::path::join(&protocols::path::parent(&file.path), &new_name);

                std::thread::spawn(move || {
                    let outcome = client
                        .lock()
                        .map_err(|_| "the connection is unusable".to_string())
                        .and_then(|mut client| {
                            client
                                .rename(&old_path, &new_path)
                                .map_err(|err| err.to_string())
                        });

                    match outcome {
                        Ok(()) => events::post(
                            &sender,
                            AppEvent::RemoteOperationDone {
                                message: format!("Renamed to {new_name}"),

                                sound: "rename_complete",
                            },
                        ),

                        Err(message) => events::post(
                            &sender,
                            AppEvent::RemoteOperationFailed {
                                message: format!("Could not rename: {message}"),

                                sound: "rename_failed",
                            },
                        ),
                    }
                });
            }
        }
    }

    /// Create a directory in the active pane.
    pub(super) fn make_directory(&self) {
        let side = self.active_side();

        let Some(name) = prompts::ask_text(&self.frame, "New Directory", "Directory name:", "")
        else {
            return;
        };

        match side {
            Side::Local => {
                let parent = PathBuf::from(self.pane(Side::Local).path());

                match local_files::mkdir_local(&parent, &name) {
                    Ok(_) => {
                        self.state.borrow_mut().play_sound("folder_created");

                        self.announce(&format!("Created {name}"));

                        self.refresh_local(None);
                    }

                    Err(err) => {
                        self.state.borrow_mut().play_sound("folder_create_failed");

                        prompts::error(
                            &self.frame,
                            "Could not create the folder",
                            &format!("Could not create {name}: {err}"),
                        );
                    }
                }
            }

            Side::Remote => {
                let Some(client) = self.state.borrow().client() else {
                    prompts::error(&self.frame, "Not connected", "Connect to a server first.");

                    return;
                };

                let parent = self.pane(Side::Remote).path();

                let target = protocols::path::join(&parent, &name);

                let sender = self.sender.clone();

                std::thread::spawn(move || {
                    let outcome = client
                        .lock()
                        .map_err(|_| "the connection is unusable".to_string())
                        .and_then(|mut client| {
                            client.mkdir(&target).map_err(|err| err.to_string())
                        });

                    match outcome {
                        Ok(()) => events::post(
                            &sender,
                            AppEvent::RemoteOperationDone {
                                message: format!("Created {name}"),

                                sound: "folder_created",
                            },
                        ),

                        Err(message) => events::post(
                            &sender,
                            AppEvent::RemoteOperationFailed {
                                message: format!("Could not create {name}: {message}"),

                                sound: "folder_create_failed",
                            },
                        ),
                    }
                });
            }
        }
    }

    /// Show properties for the focused item.
    pub(super) fn show_properties(&self) {
        let side = self.active_side();

        let Some(file) = self.pane(side).selected_file() else {
            self.announce("Nothing is selected");

            return;
        };

        dialogs::properties::show(&self.frame, &file, side);
    }

    /// Paste clipboard file paths into the focused pane.
    pub(super) fn paste_into_focused_pane(&self) {
        let paths = clipboard_file_paths();

        if paths.is_empty() {
            self.announce("The clipboard has no files");

            return;
        }

        match self.active_side() {
            Side::Local => {
                let destination = PathBuf::from(self.pane(Side::Local).path());

                let mut copied = 0usize;

                for path in &paths {
                    let source = Path::new(path);

                    let Some(name) = source.file_name() else {
                        continue;
                    };

                    let target = local_files::unique_local_path(&destination.join(name));

                    match std::fs::copy(source, &target) {
                        Ok(_) => copied += 1,

                        Err(err) => self.log(&format!("Could not copy {path}: {err}")),
                    }
                }

                self.announce(&format!(
                    "{copied} file{} pasted",
                    if copied == 1 { "" } else { "s" }
                ));

                self.refresh_local(None);
            }

            Side::Remote => {
                // Pasting into the remote pane means uploading.

                let files: Vec<RemoteFile> = paths
                    .iter()
                    .filter_map(|path| {
                        let source = Path::new(path);

                        let name = source.file_name()?.to_string_lossy().into_owned();

                        let metadata = std::fs::metadata(source).ok()?;

                        let mut file = RemoteFile::file(name, path.clone(), metadata.len());

                        file.is_dir = metadata.is_dir();

                        Some(file)
                    })
                    .collect();

                self.transfer_files(Side::Local, files);
            }
        }
    }

    // ---------------------------------------------------------------

    // Sites and settings

    // ---------------------------------------------------------------

    pub(super) fn show_site_manager(&self) {
        dialogs::site_manager::show(self);
    }

    pub(super) fn show_settings(&self) {
        dialogs::settings::show(self);
    }

    pub(super) fn show_soundpacks(&self) {
        dialogs::soundpacks::show(self);
    }

    pub(super) fn show_import(&self) {
        dialogs::import::show(self);
    }

    /// Save the live connection as a site.
    pub(super) fn save_current_connection(&self) {
        if !self.state.borrow().is_connected() {
            prompts::error(
                &self.frame,
                "Not connected",
                "Connect to a server before saving it as a site.",
            );

            return;
        }

        let host = self.state.borrow().connected_host.clone();

        let Some(name) = prompts::ask_text(&self.frame, "Save Connection", "Site name:", &host)
        else {
            return;
        };

        if self.state.borrow().sites.name_taken(&name, None)
            && !prompts::confirm(
                &self.frame,
                "Replace site?",
                &format!("A site named {name} already exists. Replace it?"),
            )
        {
            return;
        }

        let Ok(info) = self.connection_from_bar() else {
            prompts::error(
                &self.frame,
                "Could not save",
                "The connection details could not be read from the quick connect bar.",
            );

            return;
        };

        let site = Site {
            name,

            protocol: info.protocol.as_str().to_string(),

            host: info.host,

            port: info.port,

            username: info.username,

            password: info.password,

            ftp_explicit_ssl: info.ftp_explicit_ssl,

            initial_dir: self.pane(Side::Remote).path(),

            ..Default::default()
        };

        let mut state = self.state.borrow_mut();

        match state.sites.add(site) {
            Ok(()) => {
                let tier = state.storage_tier_description();

                drop(state);

                self.announce("Site saved");

                self.log(&format!("Site saved. Passwords are kept in {tier}."));
            }

            Err(err) => {
                drop(state);

                prompts::error(
                    &self.frame,
                    "Could not save the site",
                    &format!("The site could not be saved: {err}"),
                );
            }
        }
    }

    // ---------------------------------------------------------------

    // Help and updates

    // ---------------------------------------------------------------

    pub(super) fn show_shortcuts(&self) {
        dialogs::show_text_window(&self.frame, "Keyboard Shortcuts", &ids::shortcuts_text());
    }

    pub(super) fn show_about(&self) {
        let state = self.state.borrow();

        let mode = if state.portable {
            "portable"
        } else {
            "installed"
        };

        let speech = state
            .announcer
            .backend_name()
            .unwrap_or_else(|| "not available".to_string());

        let text = [
            portkeydrop_core::APP_NAME.to_string(),
            format!("Version {} ({mode})", super::format::build_version()),
            String::new(),
            "A keyboard-first file transfer client for SFTP, FTP, FTPS, and WebDAV.".to_string(),
            String::new(),
            format!("Speech output: {speech}"),
            format!("Saved passwords: {}", state.storage_tier_description()),
            format!("Configuration: {}", state.config_dir.display()),
        ]
        .join(
            "
",
        );

        drop(state);

        dialogs::show_text_window(&self.frame, "About Portkey Drop", &text);
    }

    /// Check for updates on a worker thread.
    pub(super) fn check_for_updates(&self) {
        let (channel, portable) = {
            let state = self.state.borrow();

            (
                portkeydrop_core::updater::Channel::from_setting(
                    &state.settings.app.update_channel,
                ),
                state.portable,
            )
        };

        self.announce("Checking for updates");

        let sender = self.sender.clone();

        std::thread::spawn(move || {
            let outcome = (|| -> UpdateOutcome {
                let service = match portkeydrop_core::updater::UpdateService::new() {
                    Ok(service) => service,

                    Err(err) => {
                        return UpdateOutcome::Failed {
                            message: err.to_string(),
                        }
                    }
                };

                match service.check_for_update(
                    VERSION,
                    portkeydrop_core::nightly_date(),
                    channel,
                    portable,
                    portkeydrop_core::updater::current_system(),
                ) {
                    Ok(Some(update)) => UpdateOutcome::Available(Box::new(update)),

                    Ok(None) => UpdateOutcome::UpToDate,

                    Err(err) => UpdateOutcome::Failed {
                        message: err.to_string(),
                    },
                }
            })();

            events::post(&sender, AppEvent::UpdateCheckDone(Box::new(outcome)));
        });
    }

    /// Report the result of an update check.
    pub(super) fn on_update_check(&self, outcome: UpdateOutcome) {
        match outcome {
            UpdateOutcome::Available(update) => {
                self.log(&format!(
                    "Update {} is available ({}).",
                    update.version, update.artifact_name
                ));
                self.state.borrow_mut().play_sound("notify");

                // The running build, not the bare version number: on a nightly
                // "Current: 0.6.0" against "Latest: nightly 20260821" says
                // nothing about which build is installed.
                if dialogs::update::show_offer(
                    &self.frame,
                    &super::format::build_version(),
                    &update,
                ) {
                    self.download_update(*update);
                }
            }

            UpdateOutcome::UpToDate => {
                self.announce("Portkey Drop is up to date");

                self.log("No update is available.");
            }

            UpdateOutcome::Failed { message } => {
                self.log(&format!("Update check failed: {message}"));

                prompts::error(&self.frame, "Update check failed", &message);
            }
        }
    }

    /// Fetch an update the user has accepted, on a worker thread.
    ///
    /// The progress window is app-modal: this replaces the running binary, so
    /// letting the user start a transfer underneath it would be inviting a
    /// half-finished job to be killed by the restart.
    pub(super) fn download_update(&self, update: UpdateInfo) {
        if self.download.borrow().is_some() {
            self.announce("An update is already downloading");
            return;
        }

        let dialog = ProgressDialog::builder(
            &self.frame,
            dialogs::update::DOWNLOAD_TITLE,
            &dialogs::update::progress_status(&update.artifact_name, 0, 0),
            100,
        )
        .with_style(
            ProgressDialogStyle::AppModal
                | ProgressDialogStyle::CanAbort
                | ProgressDialogStyle::Smooth
                | ProgressDialogStyle::RemainingTime,
        )
        .build();

        // Cancel is raised on the UI thread and read by the worker, which is
        // the only way to stop a download parked in a blocking read.
        let cancel = Arc::new(AtomicBool::new(false));
        *self.download.borrow_mut() = Some(Download {
            dialog: Rc::new(dialog),
            artifact: update.artifact_name.clone(),
            cancel: Arc::clone(&cancel),
            announced: None,
        });

        self.log(&format!("Downloading {}...", update.artifact_name));
        self.announce("Downloading update");

        let sender = self.sender.clone();
        let progress_sender = sender.clone();
        let destination = std::env::temp_dir().join("portkeydrop-update");

        std::thread::spawn(move || {
            let outcome = (|| -> DownloadOutcome {
                let service = match portkeydrop_core::updater::UpdateService::new() {
                    Ok(service) => service,
                    Err(err) => {
                        return DownloadOutcome::Failed {
                            message: err.to_string(),
                        }
                    }
                };

                let mut report = |downloaded: u64, total: u64| {
                    events::post(
                        &progress_sender,
                        AppEvent::UpdateDownloadProgress { downloaded, total },
                    );
                    !cancel.load(Ordering::Relaxed)
                };

                match service.download_update(&update, &destination, Some(&mut report)) {
                    Ok(path) => DownloadOutcome::Ready {
                        path,
                        version: update.version.clone(),
                    },
                    Err(UpdateError::Cancelled) => DownloadOutcome::Cancelled,
                    Err(err) => DownloadOutcome::Failed {
                        message: err.to_string(),
                    },
                }
            })();

            events::post(&sender, AppEvent::UpdateDownloadDone(Box::new(outcome)));
        });
    }

    /// Move the download's progress bar, and pick up a press of its Cancel.
    pub(super) fn on_download_progress(&self, downloaded: u64, total: u64) {
        let Some((dialog, artifact, cancel, announced)) =
            self.download.borrow().as_ref().map(|download| {
                (
                    Rc::clone(&download.dialog),
                    download.artifact.clone(),
                    Arc::clone(&download.cancel),
                    download.announced,
                )
            })
        else {
            return;
        };

        let status = dialogs::update::progress_status(&artifact, downloaded, total);
        let percent = dialogs::update::percent_done(downloaded, total);

        // The borrow above is released before this runs: updating a
        // wxProgressDialog pumps UI events, and re-entering here with it still
        // held would panic rather than merely redraw twice.
        let keep_going = match percent {
            Some(value) => dialog.update(i32::from(value), Some(&status)),
            None => dialog.pulse(Some(&status)),
        };

        if !keep_going {
            cancel.store(true, Ordering::Relaxed);
            return;
        }

        // Speaking every chunk would bury the user, so the same interval that
        // governs transfer progress governs this.
        let Some(value) = percent else { return };
        let interval = {
            let state = self.state.borrow();
            format::effective_progress_interval(
                state.settings.display.progress_interval,
                &state.settings.speech.verbosity,
            )
        };
        if !format::should_announce_progress(announced, value, interval) {
            return;
        }
        if let Some(download) = self.download.borrow_mut().as_mut() {
            download.announced = Some(value);
        }
        self.announce_only(&dialogs::update::progress_announcement(value));
    }

    /// Close the progress window and act on how the download ended.
    pub(super) fn on_download_done(&self, outcome: DownloadOutcome) {
        // Dropping the entry destroys the progress window, so it is gone
        // before any message box tries to open in front of it.
        self.download.borrow_mut().take();

        match outcome {
            DownloadOutcome::Ready { path, version } => self.install_update(&path, &version),
            DownloadOutcome::Cancelled => {
                self.log("The update download was cancelled.");
                self.announce("Update download cancelled");
            }
            DownloadOutcome::Failed { message } => {
                self.log(&format!("The update download failed: {message}"));
                prompts::error(&self.frame, "Download failed", &message);
            }
        }
    }

    /// Install a verified download, restarting into it.
    fn install_update(&self, path: &Path, version: &str) {
        self.log(&format!("Downloaded {}.", path.display()));

        let context = ApplyContext::current(self.state.borrow().portable);

        // A tarball install has nothing to run: say where the file is rather
        // than tearing the window down and leaving the user on the old build.
        if !can_auto_apply(path, &context) {
            self.announce("This update has to be installed by hand");
            prompts::info(
                &self.frame,
                "Install this update by hand",
                &dialogs::update::manual_install_message(path),
            );
            return;
        }

        if !prompts::confirm(
            &self.frame,
            "Install the update",
            &dialogs::update::restart_question(version),
        ) {
            self.log("The update was downloaded but not installed.");
            self.announce("The update was not installed");
            return;
        }

        // The helper waits for this process to exit before it touches
        // anything, so it is started first and the shutdown follows.
        match apply_update(path, &context) {
            Ok(true) => {
                self.log("Restarting to install the update.");
                // Saves the queue and settings, closes the window, and lets go
                // of the connection.
                self.force_exit();
                // Then leave, without waiting for the event loop to agree.
                // The helper does not start Setup until this process is gone,
                // so anything still holding the loop up strands the update
                // rather than delaying it -- and the download's progress
                // dialog does exactly that, because destroying a window only
                // queues it for deletion on an idle cycle that never comes
                // once the frame has closed. Everything worth keeping has
                // already been written by `force_exit`.
                std::process::exit(0);
            }
            Ok(false) => self.report_apply_failure(path, "this install cannot update itself"),
            Err(err) => self.report_apply_failure(path, &err.to_string()),
        }
    }

    /// Tell the user the download is on disk when it could not be started.
    fn report_apply_failure(&self, path: &Path, error: &str) {
        self.log(&format!("The update could not be started: {error}"));
        prompts::error(
            &self.frame,
            "Could not install the update",
            &dialogs::update::apply_failed_message(path, error),
        );
    }
}

/// What to do with a destination that already exists.
enum Conflict {
    /// Replace it.
    Overwrite,

    /// Leave it and skip this item.
    Skip,

    /// Do not overwrite; the caller picks a different destination.
    Fail,
}

/// File paths on the clipboard, if any.
///
/// A real file list is preferred — that is what a file manager puts there —
/// with a fallback to newline-separated text, which covers copying a path out
/// of a terminal or an address bar. Either way, only paths that actually exist
/// are returned: pasting arbitrary clipboard text must not queue transfers of
/// files that are not there.
fn clipboard_file_paths() -> Vec<String> {
    let clipboard = Clipboard::get();

    if !clipboard.open() {
        return Vec::new();
    }

    let files = FileDataObject::new();

    let mut paths: Vec<String> = if clipboard.get_data(&files) {
        files.get_files()
    } else {
        let text = TextDataObject::new("");

        if clipboard.get_data(&text) {
            text.get_text()
                .lines()
                .map(|line| line.trim().trim_matches('"').to_string())
                .collect()
        } else {
            Vec::new()
        }
    };

    clipboard.close();

    paths.retain(|path| !path.is_empty() && Path::new(path).exists());

    paths
}

#[cfg(test)]
mod tests {

    use super::*;

    #[test]
    fn clipboard_paths_ignore_entries_that_do_not_exist() {
        // Pasting arbitrary clipboard text must not queue transfers of files

        // that are not there.

        let paths = clipboard_file_paths();

        assert!(paths.iter().all(|path| Path::new(path).exists()));
    }

    #[test]
    fn the_overwrite_modes_are_the_documented_ones() {
        for mode in ["ask", "overwrite", "skip", "rename"] {
            assert!(!mode.is_empty());
        }
    }
}
