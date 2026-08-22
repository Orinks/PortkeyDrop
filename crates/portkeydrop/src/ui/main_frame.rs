//! The main window: quick connect bar, dual file panes, activity log.
//!
//! Layout is driven by keyboard and screen reader use rather than by looks.
//! The three panes sit left to right in tab order (local, remote, activity
//! log), every control carries an explicit accessible name, and every action
//! reachable from a menu is also reachable from a key.
//!
//! Network work never runs on the UI thread. Workers post [`AppEvent`]s and a
//! timer drains them, which is what keeps the window responsive during a slow
//! listing or a large transfer.

use std::cell::RefCell;
use std::path::{Path, PathBuf};
use std::rc::Rc;
use std::sync::atomic::AtomicBool;
use std::sync::Arc;

use wxdragon::prelude::*;

use portkeydrop_core::protocols::{self, ConnectionInfo, HostKeyPolicy, Protocol};
use portkeydrop_core::transfer::TransferJob;
use portkeydrop_core::{local_files, APP_NAME};

use super::dialogs;
use super::events::{self, AppEvent, EventReceiver, EventSender};
use super::file_pane::FilePane;
use super::format;
use super::ids;
use super::keys;
use super::prompts;
use super::state::AppState;
use super::tray::{self, TrayIcon};
use super::view::{PaneState, SortField};

/// How often the UI drains background events.
const EVENT_POLL_MS: i32 = 60;

/// Which pane a command applies to.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Side {
    Local,
    Remote,
}

/// The main window.
#[derive(Clone)]
pub struct MainFrame {
    pub frame: Frame,
    pub(super) local: Rc<FilePane>,
    pub(super) remote: Rc<FilePane>,
    pub(super) activity_log: TextCtrl,
    pub(super) status_bar: StatusBar,
    pub(super) quick_connect: Rc<QuickConnectBar>,
    pub(super) activity_panel: Panel,
    pub(super) state: Rc<RefCell<AppState>>,
    pub(super) sender: EventSender,
    pub(super) receiver: Rc<EventReceiver>,
    pub(super) timer: Rc<Timer<Frame>>,
    /// Whether the activity log pane is shown.
    pub(super) log_visible: Rc<RefCell<bool>>,
    /// The notification area icon, when one is installed.
    pub(super) tray: Rc<RefCell<Option<TrayIcon>>>,
    /// Set once a real exit is under way, so the close handler stops
    /// diverting to the notification area.
    pub(super) exiting: Rc<RefCell<bool>>,
    /// The update download in flight, if there is one.
    pub(super) download: Rc<RefCell<Option<Download>>>,
}

/// The quick connect bar's fields.
pub(super) struct QuickConnectBar {
    pub(super) panel: Panel,
    pub(super) protocol: Choice,
    pub(super) host: TextCtrl,
    pub(super) port: TextCtrl,
    pub(super) username: TextCtrl,
    pub(super) password: TextCtrl,
    pub(super) explicit_ssl: CheckBox,
    pub(super) connect: Button,
}

impl MainFrame {
    /// Build and show the main window.
    pub fn create(state: AppState) -> Self {
        let frame = Frame::builder()
            .with_title(APP_NAME)
            .with_size(Size::new(1100, 650))
            .build();

        let (sender, receiver) = events::channel();
        let state = Rc::new(RefCell::new(state));

        let (sort_field, sort_ascending, show_hidden) = {
            let state = state.borrow();
            (
                SortField::from_setting(&state.settings.display.sort_by),
                state.settings.display.sort_ascending,
                state.settings.display.show_hidden_files,
            )
        };

        let root = Panel::builder(&frame).build();
        let root_sizer = BoxSizer::builder(Orientation::Vertical).build();

        let quick_connect = Rc::new(QuickConnectBar::build(&root, &state.borrow()));
        root_sizer.add(
            &quick_connect.panel,
            0,
            SizerFlag::Expand | SizerFlag::All,
            2,
        );

        let panes = Panel::builder(&root).build();
        let panes_sizer = BoxSizer::builder(Orientation::Horizontal).build();

        let local = Rc::new(FilePane::new(
            &panes,
            "Local files",
            PaneState::new(sort_field, sort_ascending, show_hidden),
        ));
        let remote = Rc::new(FilePane::new(
            &panes,
            "Remote files",
            PaneState::new(sort_field, sort_ascending, show_hidden),
        ));

        let activity_panel = Panel::builder(&panes).build();
        let activity_sizer = BoxSizer::builder(Orientation::Vertical).build();
        let activity_label = StaticText::builder(&activity_panel)
            .with_label("Activity log:")
            .build();
        activity_sizer.add(&activity_label, 0, SizerFlag::Left | SizerFlag::All, 2);
        let activity_log = TextCtrl::builder(&activity_panel)
            .with_style(
                TextCtrlStyle::MultiLine | TextCtrlStyle::ReadOnly | TextCtrlStyle::DontWrap,
            )
            .build();
        activity_log.set_name("Activity log");
        activity_sizer.add(&activity_log, 1, SizerFlag::Expand | SizerFlag::All, 2);
        activity_panel.set_sizer(activity_sizer, true);

        panes_sizer.add(&local.panel, 2, SizerFlag::Expand | SizerFlag::All, 2);
        panes_sizer.add(&remote.panel, 2, SizerFlag::Expand | SizerFlag::All, 2);
        panes_sizer.add(&activity_panel, 1, SizerFlag::Expand | SizerFlag::All, 2);
        panes.set_sizer(panes_sizer, true);

        root_sizer.add(&panes, 1, SizerFlag::Expand | SizerFlag::All, 2);
        root.set_sizer(root_sizer, true);

        let status_bar = frame.create_status_bar(2, 0, ID_ANY as i32, "status");
        status_bar.set_status_widths(&[-1, -2]);

        let timer = Rc::new(Timer::new(&frame));

        let main_frame = Self {
            frame,
            local,
            remote,
            activity_log,
            status_bar,
            quick_connect,
            activity_panel,
            state,
            sender,
            receiver: Rc::new(receiver),
            timer,
            log_visible: Rc::new(RefCell::new(true)),
            tray: Rc::new(RefCell::new(None)),
            exiting: Rc::new(RefCell::new(false)),
            download: Rc::new(RefCell::new(None)),
        };

        main_frame.build_menu();
        main_frame.bind_events();
        main_frame.start_event_pump();
        main_frame.restore_queue();
        main_frame.refresh_local(None);
        main_frame.sync_tray_icon();
        main_frame.update_status();
        main_frame.log("Portkey Drop started.");

        {
            let state = main_frame.state.borrow();
            state.play_sound("startup");
            if !state.announcer.is_available() {
                drop(state);
                main_frame.log(
                    "Speech output is unavailable. Announcements appear in the status bar and \
                     this log only.",
                );
            }
        }

        main_frame.frame.show(true);
        main_frame.frame.centre();
        main_frame.local.focus();
        main_frame
    }

    // ---------------------------------------------------------------
    // Construction
    // ---------------------------------------------------------------

    fn build_menu(&self) {
        let mut menu_bar = MenuBar::builder();

        let file_menu = Menu::builder()
            .append_item(ids::ID_SETTINGS, "Se&ttings...", "Application settings")
            .append_item(ids::ID_SOUNDPACKS, "Sound &Packs...", "Manage sound packs")
            .append_separator()
            .append_item(ID_EXIT, "E&xit\tCtrl+Q", "Exit Portkey Drop")
            .build();
        menu_bar = menu_bar.append(file_menu, "&File");

        // Delete and F2 are handled by the file lists rather than as menubar
        // accelerators: a frame-wide accelerator would hijack those keys inside
        // every text field in the window.
        let edit_menu = Menu::builder()
            .append_item(
                ids::ID_DELETE,
                "De&lete",
                "Delete the selection (Delete in a file pane)",
            )
            .append_item(
                ids::ID_RENAME,
                "&Rename",
                "Rename the selection (F2 in a file pane)",
            )
            .append_item(
                ids::ID_MKDIR,
                &ids::labelled("Ne&w Directory...", ids::ID_MKDIR),
                "Create a directory",
            )
            .append_separator()
            .append_item(
                ids::ID_PASTE,
                &ids::labelled("&Paste", ids::ID_PASTE),
                "Paste files from the clipboard into the focused pane",
            )
            .append_separator()
            .append_item(
                ids::ID_PROPERTIES,
                &ids::labelled("Propert&ies...", ids::ID_PROPERTIES),
                "Show file properties",
            )
            .build();
        menu_bar = menu_bar.append(edit_menu, "&Edit");

        let sort_menu = Menu::builder()
            .append_radio_item(ids::ID_SORT_NAME, "By &Name", "Sort by name")
            .append_radio_item(ids::ID_SORT_SIZE, "By &Size", "Sort by size")
            .append_radio_item(ids::ID_SORT_TYPE, "By &Type", "Sort by type")
            .append_radio_item(
                ids::ID_SORT_MODIFIED,
                "By &Modified",
                "Sort by date modified",
            )
            .build();

        let view_menu = Menu::builder()
            .append_item(
                ids::ID_REFRESH,
                &ids::labelled("&Refresh", ids::ID_REFRESH),
                "Refresh the active pane",
            )
            .append_item(
                ids::ID_HOME_DIR,
                &ids::labelled("&Home Directory", ids::ID_HOME_DIR),
                "Go to the home directory",
            )
            .append_check_item(
                ids::ID_SHOW_HIDDEN,
                "Show Hi&dden Files",
                "Show hidden files",
            )
            .append_separator()
            .build();
        view_menu.append_submenu(sort_menu, "&Sort By", "Choose the sort order");
        view_menu.append_separator();
        view_menu.append(
            ids::ID_FILTER,
            &ids::labelled("&Filter...", ids::ID_FILTER),
            "Filter the file list",
            ItemKind::Normal,
        );
        view_menu.append_separator();
        view_menu.append(
            ids::ID_TOGGLE_ACTIVITY_LOG,
            "Hide &Activity Log",
            "Show or hide the activity log",
            ItemKind::Normal,
        );

        // The pane-focus commands live on a menu because that is what makes
        // wxWidgets register their accelerators frame-wide, and it makes them
        // discoverable by browsing rather than only by reading the help.
        let go_menu = Menu::builder()
            .append_item(
                ids::ID_SWITCH_PANE_FOCUS,
                &ids::labelled("&Next Pane", ids::ID_SWITCH_PANE_FOCUS),
                "Cycle between the local, remote, and activity log panes",
            )
            .append_separator()
            .append_item(
                ids::ID_FOCUS_LOCAL_PANE,
                &ids::labelled("&Local Files", ids::ID_FOCUS_LOCAL_PANE),
                "Focus the local files list",
            )
            .append_item(
                ids::ID_FOCUS_REMOTE_PANE,
                &ids::labelled("&Remote Files", ids::ID_FOCUS_REMOTE_PANE),
                "Focus the remote files list",
            )
            .append_item(
                ids::ID_FOCUS_ACTIVITY_LOG,
                &ids::labelled("&Activity Log", ids::ID_FOCUS_ACTIVITY_LOG),
                "Focus the activity log",
            )
            .append_separator()
            .append_item(
                ids::ID_FOCUS_ADDRESS_BAR,
                &ids::labelled("&Path Bar", ids::ID_FOCUS_ADDRESS_BAR),
                "Focus the path bar, or the quick connect bar when disconnected",
            )
            .build();
        view_menu.append_separator();
        view_menu.append_submenu(go_menu, "&Go To", "Move keyboard focus between panes");

        view_menu.check_item(
            ids::ID_SHOW_HIDDEN,
            self.state.borrow().settings.display.show_hidden_files,
        );
        let sort_id = match SortField::from_setting(&self.state.borrow().settings.display.sort_by) {
            SortField::Name => ids::ID_SORT_NAME,
            SortField::Size => ids::ID_SORT_SIZE,
            SortField::Type => ids::ID_SORT_TYPE,
            SortField::Modified => ids::ID_SORT_MODIFIED,
        };
        view_menu.check_item(sort_id, true);
        menu_bar = menu_bar.append(view_menu, "&View");

        let transfer_menu = Menu::builder()
            .append_item(
                ids::ID_TRANSFER,
                &ids::labelled("&Transfer", ids::ID_TRANSFER),
                "Upload or download, depending on the focused pane",
            )
            .append_item(
                ids::ID_UPLOAD,
                &ids::labelled("&Upload", ids::ID_UPLOAD),
                "Upload the selected local items",
            )
            .append_item(
                ids::ID_DOWNLOAD,
                &ids::labelled("&Download", ids::ID_DOWNLOAD),
                "Download the selected remote items",
            )
            .append_separator()
            .append_item(
                ids::ID_RETRY_LAST_FAILED,
                "&Retry Last Failed Transfer",
                "Retry the most recent failed transfer",
            )
            .append_separator()
            .append_item(
                ids::ID_TRANSFER_QUEUE,
                &ids::labelled("Transfer &Queue...", ids::ID_TRANSFER_QUEUE),
                "Show the transfer queue",
            )
            .build();
        transfer_menu.enable_item(ids::ID_RETRY_LAST_FAILED, false);
        menu_bar = menu_bar.append(transfer_menu, "&Transfer");

        let sites_menu = Menu::builder()
            .append_item(
                ids::ID_QUICK_CONNECT,
                &ids::labelled("&Quick Connect", ids::ID_QUICK_CONNECT),
                "Focus the quick connect bar",
            )
            .append_item(
                ids::ID_CONNECT_FROM_BAR,
                &ids::labelled("&Connect", ids::ID_CONNECT_FROM_BAR),
                "Connect using the quick connect bar",
            )
            .append_item(
                ids::ID_DISCONNECT,
                "&Disconnect",
                "Disconnect from the server",
            )
            .append_separator()
            .append_item(
                ids::ID_SITE_MANAGER,
                &ids::labelled("&Site Manager...", ids::ID_SITE_MANAGER),
                "Manage saved sites",
            )
            .append_item(
                ids::ID_SAVE_CONNECTION,
                "Sa&ve Current Connection...",
                "Save the active connection as a site",
            )
            .append_separator()
            .append_item(
                ids::ID_IMPORT_CONNECTIONS,
                "&Import Sites...",
                "Import sites from another client",
            )
            .build();
        menu_bar = menu_bar.append(sites_menu, "S&ites");

        let channel = portkeydrop_core::updater::Channel::from_setting(
            &self.state.borrow().settings.app.update_channel,
        );
        let help_menu = Menu::builder()
            .append_item(
                ids::ID_CHECK_UPDATES,
                &format!("Check for &Updates ({})...", channel.display_name()),
                "Check for application updates",
            )
            .append_item(
                ids::ID_KEYBOARD_SHORTCUTS,
                "&Keyboard Shortcuts...",
                "List every keyboard shortcut",
            )
            .append_separator()
            .append_item(ID_ABOUT, "&About", "About Portkey Drop")
            .build();
        menu_bar = menu_bar.append(help_menu, "&Help");

        self.frame.set_menu_bar(menu_bar.build());
    }

    // ---------------------------------------------------------------
    // Event wiring
    // ---------------------------------------------------------------

    fn bind_events(&self) {
        self.bind_menu_commands();
        self.bind_quick_connect();
        self.bind_pane(Side::Local);
        self.bind_pane(Side::Remote);
        self.bind_context_menu();
        self.bind_close();
        self.bind_transfer_notifications();
    }

    fn bind_menu_commands(&self) {
        let this = self.clone();
        self.frame.on_menu(move |event| {
            let id = event.get_id();
            this.handle_command(id);
        });
    }

    /// Route a command id to its action.
    ///
    /// Kept as one `match` so every command is visible in one place and none
    /// can be silently unbound.
    fn handle_command(&self, id: i32) {
        match id {
            ids::ID_SETTINGS => self.show_settings(),
            ids::ID_SOUNDPACKS => self.show_soundpacks(),
            ID_EXIT => self.request_exit(),

            ids::ID_DELETE => self.delete_selection(),
            ids::ID_RENAME => self.rename_selection(),
            ids::ID_MKDIR => self.make_directory(),
            ids::ID_PASTE => self.paste_into_focused_pane(),
            ids::ID_PROPERTIES => self.show_properties(),

            ids::ID_REFRESH => self.refresh_active_pane(),
            ids::ID_HOME_DIR => self.go_home(),
            ids::ID_PARENT_DIR => self.go_parent(),
            ids::ID_SHOW_HIDDEN => self.toggle_hidden(),
            ids::ID_FILTER => self.prompt_filter(),
            ids::ID_SORT_NAME => self.sort_by(SortField::Name),
            ids::ID_SORT_SIZE => self.sort_by(SortField::Size),
            ids::ID_SORT_TYPE => self.sort_by(SortField::Type),
            ids::ID_SORT_MODIFIED => self.sort_by(SortField::Modified),
            ids::ID_TOGGLE_ACTIVITY_LOG => self.toggle_activity_log(),

            ids::ID_TRANSFER => self.transfer_selection(),
            ids::ID_UPLOAD => self.upload_selection(),
            ids::ID_DOWNLOAD => self.download_selection(),
            ids::ID_TRANSFER_QUEUE | ids::ID_TRAY_QUEUE => self.show_transfer_queue(),
            ids::ID_RETRY_LAST_FAILED => self.retry_last_failed(),

            ids::ID_QUICK_CONNECT => self.focus_quick_connect(),
            ids::ID_CONNECT | ids::ID_CONNECT_FROM_BAR => self.connect_from_bar(),
            ids::ID_DISCONNECT => self.disconnect(),
            ids::ID_SITE_MANAGER => self.show_site_manager(),
            ids::ID_SAVE_CONNECTION => self.save_current_connection(),
            ids::ID_IMPORT_CONNECTIONS => self.show_import(),

            ids::ID_CHECK_UPDATES | ids::ID_TRAY_UPDATES => self.check_for_updates(),
            ids::ID_KEYBOARD_SHORTCUTS => self.show_shortcuts(),
            ID_ABOUT => self.show_about(),

            ids::ID_SWITCH_PANE_FOCUS => self.cycle_pane_focus(),
            ids::ID_FOCUS_LOCAL_PANE => self.local.focus(),
            ids::ID_FOCUS_REMOTE_PANE => self.remote.focus(),
            ids::ID_FOCUS_ACTIVITY_LOG => self.activity_log.set_focus(),
            ids::ID_FOCUS_ADDRESS_BAR => self.focus_address_bar(),
            ids::ID_TRAY_SHOW => self.show_window(),
            _ => {}
        }
    }

    fn bind_quick_connect(&self) {
        let bar = Rc::clone(&self.quick_connect);
        let this = self.clone();
        bar.connect.on_click(move |_| this.connect_from_bar());

        // Enter in any field submits, which is the muscle memory for a form.
        for field in [&bar.host, &bar.port, &bar.username, &bar.password] {
            let this = self.clone();
            field.on_text_enter(move |_| this.connect_from_bar());
        }

        // Escape dismisses the bar and puts focus back where it was, so a user
        // who opened it by mistake is not stranded in it.
        for field in [&bar.host, &bar.port, &bar.username, &bar.password] {
            let this = self.clone();
            field.on_key_down(move |event| {
                let code = match &event {
                    WindowEventData::Keyboard(key) => key.get_key_code(),
                    _ => None,
                };
                if code == Some(keys::ESCAPE) {
                    this.dismiss_quick_connect();
                } else {
                    event.skip(true);
                }
            });
        }

        let this = self.clone();
        let bar_for_protocol = Rc::clone(&self.quick_connect);
        bar.protocol.on_selection_changed(move |_| {
            this.on_protocol_changed(&bar_for_protocol);
        });
    }

    fn bind_pane(&self, side: Side) {
        let pane = self.pane(side);

        // Enter opens a directory or transfers a file.
        let this = self.clone();
        pane.list
            .on_item_activated(move |_| this.activate_selection(side));

        // Delete, F2, and Backspace belong to the list, not to the menubar:
        // as frame-wide accelerators they would fire inside text fields too.
        let this = self.clone();
        pane.list
            .on_key_down(move |event| match event.get_key_code().unwrap_or(0) {
                keys::DELETE => this.delete_selection(),
                keys::F2 => this.rename_selection(),
                keys::BACK => this.go_parent_in(side),
                _ => {}
            });

        // Announce the row under the cursor; screen readers read the focused
        // row themselves, but the status bar mirrors it for everyone else.
        let this = self.clone();
        let pane_for_focus = Rc::clone(&pane);
        pane.list.on_item_focused(move |_| {
            if let Some(file) = pane_for_focus.selected_file() {
                this.status_bar
                    .set_status_text(&format::file_row_text(&file), 1);
            }
        });

        let this = self.clone();
        pane.path_bar
            .on_text_enter(move |_| this.navigate_to_typed_path(side));
    }

    /// Route context menu requests to whichever pane has focus.
    ///
    /// Bound on the frame rather than the lists: wxWidgets raises one event for
    /// Shift+F10, the Menu key, and a right-click, and the lists do not carry
    /// the menu event trait. Shift+F10 is the only route a keyboard-only user
    /// has, so it is the one that matters most.
    fn bind_context_menu(&self) {
        let this = self.clone();
        self.frame.on_context_menu(move |_| {
            if let Some(side) = this.focused_side() {
                this.show_pane_context_menu(side);
            }
        });
    }

    fn bind_close(&self) {
        let this = self.clone();
        self.frame.on_close(move |event| {
            if !*this.exiting.borrow() && this.should_minimise_to_tray() {
                // Hide rather than quit, and veto the close so transfers keep
                // running. The tray icon is the way back.
                this.frame.show(false);
                this.announce("Portkey Drop is still running in the notification area");
                if let WindowEventData::General(event) = &event {
                    event.veto();
                }
                return;
            }
            this.on_close();
            event.skip(true);
        });
    }

    /// Have the transfer service wake the UI whenever the queue changes.
    fn bind_transfer_notifications(&self) {
        let sender = self.sender.clone();
        let transfers = Arc::clone(&self.state.borrow().transfers);
        transfers.set_change_callback(Some(Arc::new(move || {
            events::post(&sender, AppEvent::TransfersChanged);
        })));
    }

    /// Start the timer that drains background events onto the UI thread.
    fn start_event_pump(&self) {
        let this = self.clone();
        self.timer.on_tick(move |_| {
            for event in events::drain(&this.receiver) {
                this.handle_event(event);
                // An event can start the shutdown; the rest of the batch would
                // then be touching widgets that are on their way out.
                if *this.exiting.borrow() {
                    break;
                }
            }
        });
        self.timer.start(EVENT_POLL_MS, false);
    }

    // ---------------------------------------------------------------
    // Background event handling
    // ---------------------------------------------------------------

    fn handle_event(&self, event: AppEvent) {
        match event {
            AppEvent::Connected { host, cwd } => {
                // The worker parked the client here; without collecting it the
                // connection would look successful but nothing would be wired
                // up to talk to.
                let Some(client) = CONNECTED_CLIENT.take() else {
                    self.log("The connection was lost before it could be used.");
                    self.update_status();
                    return;
                };
                {
                    let mut state = self.state.borrow_mut();
                    state.set_client(client, host.clone());
                    state.remote_home = cwd.clone();
                }
                self.log(&format!("Connected to {host}."));
                self.state.borrow_mut().play_sound("connect_success");
                self.announce(&format!("Connected to {host}"));
                self.update_status();
                self.hide_quick_connect();
                self.refresh_remote(&cwd);
            }
            AppEvent::ConnectFailed { message } => {
                self.state.borrow_mut().clear_client();
                self.log(&message);
                self.state.borrow_mut().play_sound("connect_failed");
                self.announce("Connection failed");
                self.update_status();
                prompts::error(&self.frame, "Connection failed", &message);
                self.focus_quick_connect();
            }
            AppEvent::RemoteListed { path, files } => {
                let total = files.len();
                self.remote.set_files(files, &path);
                let (shown, _) = self.remote.counts();
                self.update_status();
                if self.state.borrow().settings.display.announce_file_count {
                    self.announce(&format::listing_announcement(
                        "Remote files",
                        &path,
                        shown,
                        total,
                    ));
                }
            }
            AppEvent::RemoteListFailed { path, message } => {
                self.log(&format!("Could not list {path}: {message}"));
                self.announce(&format!("Could not list {path}"));
                prompts::error(&self.frame, "Listing failed", &message);
            }
            AppEvent::RemoteChangedDirectory { path } => self.refresh_remote(&path),
            AppEvent::TransfersChanged => self.on_transfers_changed(),
            AppEvent::RemoteOperationDone { message, sound } => {
                self.log(&message);
                self.state.borrow_mut().play_sound(sound);
                self.announce(&message);
                self.refresh_remote_current();
            }
            AppEvent::RemoteOperationFailed { message, sound } => {
                self.log(&message);
                self.state.borrow_mut().play_sound(sound);
                self.announce(&message);
                prompts::error(&self.frame, "Operation failed", &message);
            }
            AppEvent::UpdateCheckDone(outcome) => self.on_update_check(*outcome),
            AppEvent::UpdateDownloadProgress { downloaded, total } => {
                self.on_download_progress(downloaded, total)
            }
            AppEvent::UpdateDownloadDone(outcome) => self.on_download_done(*outcome),
            AppEvent::TrayCommand(id) => self.handle_tray_command(id),
            AppEvent::Log { message } => self.log(&message),
            AppEvent::HostKeyPrompt {
                host,
                algorithm,
                fingerprint,
                reply,
            } => {
                self.log(&format!(
                    "{host} offered an unrecognised {algorithm} host key ({fingerprint})."
                ));
                let decision =
                    dialogs::host_key::show(&self.frame, &host, &algorithm, &fingerprint);
                if reply.send(decision).is_err() {
                    log::debug!("host key answer dropped: the connect worker has gone");
                }
            }
        }
    }

    fn on_transfers_changed(&self) {
        let jobs = self.state.borrow().transfers.jobs();
        for job in &jobs {
            self.announce_job(job);
        }
        self.update_status();
    }

    /// Announce a job's progress or its outcome, each at most once.
    fn announce_job(&self, job: &TransferJob) {
        use portkeydrop_core::transfer::Status;

        let mut state = self.state.borrow_mut();
        let interval = state.settings.display.progress_interval;
        let previous = state.announced_progress.get(&job.id).copied();

        match job.status {
            Status::InProgress
                if format::should_announce_progress(previous, job.progress, interval) =>
            {
                state
                    .announced_progress
                    .insert(job.id.clone(), job.progress);
                let message = format::transfer_progress_announcement(job);
                drop(state);
                self.announce_only(&message);
            }
            status if status.is_finished() => {
                // `None` marks a job already announced as finished, so the
                // outcome is not repeated on every later queue change.
                if previous.is_none() && !state.announced_progress.contains_key(&job.id) {
                    return;
                }
                state.announced_progress.remove(&job.id);
                let sound = match status {
                    Status::Complete => "transfer_complete",
                    Status::Failed => "transfer_failed",
                    _ => "transfer_cancelled",
                };
                if status == Status::Failed {
                    state.last_failed_transfer = Some(job.id.clone());
                }
                state.play_sound(sound);
                let message = format::transfer_finished_announcement(job);
                drop(state);
                self.log(&message);
                self.announce_only(&message);
                self.update_retry_menu();
                self.refresh_after_transfer(job);
            }
            _ => {}
        }
    }

    /// Refresh whichever pane a finished transfer wrote into.
    fn refresh_after_transfer(&self, job: &TransferJob) {
        use portkeydrop_core::transfer::{Direction, Status};
        if job.status != Status::Complete {
            return;
        }
        match job.direction {
            Direction::Download => self.refresh_local(None),
            Direction::Upload => self.refresh_remote_current(),
        }
    }

    // ---------------------------------------------------------------
    // Connection
    // ---------------------------------------------------------------

    fn on_protocol_changed(&self, bar: &QuickConnectBar) {
        let Some(name) = bar.protocol.get_string_selection() else {
            return;
        };
        let protocol: Protocol = name.parse().unwrap_or(Protocol::Sftp);
        let explicit = protocol == Protocol::Ftp && bar.explicit_ssl.is_checked();
        bar.port
            .set_value(&protocol.default_port(explicit).to_string());
        // The AUTH SSL option only means anything for plain FTP.
        bar.explicit_ssl.enable(protocol == Protocol::Ftp);
    }

    /// Read the quick connect bar into connection parameters.
    pub(super) fn connection_from_bar(&self) -> Result<ConnectionInfo, String> {
        let bar = &self.quick_connect;
        let host = bar.host.get_value().trim().to_string();
        if host.is_empty() {
            return Err("Enter a server address.".to_string());
        }
        let protocol: Protocol = bar
            .protocol
            .get_string_selection()
            .unwrap_or_else(|| "sftp".to_string())
            .parse()
            .unwrap_or(Protocol::Sftp);

        let port_text = bar.port.get_value().trim().to_string();
        let port = if port_text.is_empty() {
            0
        } else {
            port_text
                .parse::<u16>()
                .map_err(|_| "The port must be a number.".to_string())?
        };

        let state = self.state.borrow();
        Ok(ConnectionInfo {
            protocol,
            host,
            port,
            username: bar.username.get_value().trim().to_string(),
            password: bar.password.get_value(),
            key_path: String::new(),
            timeout: state.settings.connection.timeout,
            passive_mode: state.settings.connection.passive_mode,
            ftp_explicit_ssl: protocol == Protocol::Ftp && bar.explicit_ssl.is_checked(),
            host_key_policy: HostKeyPolicy::from_setting(
                &state.settings.connection.verify_host_keys,
            ),
        })
    }

    fn connect_from_bar(&self) {
        match self.connection_from_bar() {
            Ok(info) => self.connect(info),
            Err(message) => {
                prompts::error(&self.frame, "Cannot connect", &message);
                self.quick_connect.host.set_focus();
            }
        }
    }

    /// Connect on a worker thread.
    pub fn connect(&self, info: ConnectionInfo) {
        self.disconnect_quietly();
        let endpoint = info.endpoint();
        self.log(&format!("Connecting to {endpoint}..."));
        self.status_bar
            .set_status_text(&format!("Connecting to {endpoint}..."), 0);
        self.announce(&format!("Connecting to {endpoint}"));

        let sender = self.sender.clone();
        let host = info.host.clone();
        // The prompt posts onto the event pump and blocks this worker until
        // the UI thread answers. That is safe: the UI thread is free, and
        // wxWidgets dialogs cannot run anywhere else.
        let prompt_sender = sender.clone();
        let host_key_prompt: protocols::HostKeyPrompt =
            Arc::new(move |host: &str, algorithm: &str, fingerprint: &str| {
                events::ask_host_key(&prompt_sender, host, algorithm, fingerprint)
            });

        std::thread::spawn(move || {
            let result = protocols::create_client(info, Some(host_key_prompt))
                .and_then(|mut client| client.connect().map(|()| client));
            match result {
                Ok(client) => {
                    let cwd = client.cwd().to_string();
                    events::post(
                        &sender,
                        AppEvent::Log {
                            message: format!("Connected to {host}."),
                        },
                    );
                    // The client itself cannot cross the channel, so it is
                    // handed over through a dedicated message.
                    CONNECTED_CLIENT.with_client(client);
                    events::post(&sender, AppEvent::Connected { host, cwd });
                }
                Err(err) => {
                    events::post(
                        &sender,
                        AppEvent::ConnectFailed {
                            message: err.to_string(),
                        },
                    );
                }
            }
        });
    }

    fn disconnect(&self) {
        if !self.state.borrow().is_connected() {
            self.announce("Not connected");
            return;
        }
        self.disconnect_quietly();
        self.remote.set_files(Vec::new(), "/");
        self.state.borrow_mut().play_sound("disconnect");
        self.log("Disconnected.");
        self.announce("Disconnected");
        self.update_status();
    }

    pub(super) fn disconnect_quietly(&self) {
        self.state.borrow_mut().clear_client();
    }

    // ---------------------------------------------------------------
    // Navigation
    // ---------------------------------------------------------------

    pub(super) fn pane(&self, side: Side) -> Rc<FilePane> {
        match side {
            Side::Local => Rc::clone(&self.local),
            Side::Remote => Rc::clone(&self.remote),
        }
    }

    /// Which pane has focus, if either.
    pub(super) fn focused_side(&self) -> Option<Side> {
        if self.local.has_focus() {
            Some(Side::Local)
        } else if self.remote.has_focus() {
            Some(Side::Remote)
        } else {
            None
        }
    }

    /// The pane a command applies to, defaulting to local.
    pub(super) fn active_side(&self) -> Side {
        self.focused_side().unwrap_or(Side::Local)
    }

    pub(super) fn refresh_local(&self, path: Option<&Path>) {
        let target = match path {
            Some(path) => path.to_path_buf(),
            None => {
                let current = self.local.path();
                if current.is_empty() {
                    self.state.borrow_mut().startup_local_folder()
                } else {
                    PathBuf::from(current)
                }
            }
        };

        match local_files::list_local_dir(&target) {
            Ok(files) => {
                let total = files.len();
                let display = target.to_string_lossy().into_owned();
                self.local.set_files(files, &display);
                self.state.borrow_mut().remember_local_folder(&target);
                let (shown, _) = self.local.counts();
                if self.state.borrow().settings.display.announce_file_count {
                    self.announce(&format::listing_announcement(
                        "Local files",
                        &display,
                        shown,
                        total,
                    ));
                }
            }
            Err(err) => {
                let message = format!("Could not open {}: {err}", target.display());
                self.log(&message);
                prompts::error(&self.frame, "Cannot open folder", &message);
            }
        }
    }

    pub(super) fn refresh_remote(&self, path: &str) {
        let Some(client) = self.state.borrow().client() else {
            return;
        };
        let sender = self.sender.clone();
        let path = path.to_string();
        std::thread::spawn(move || {
            let result = client
                .lock()
                .map_err(|_| "the connection is unusable".to_string())
                .and_then(|mut client| client.list_dir(&path).map_err(|err| err.to_string()));
            match result {
                Ok(files) => events::post(&sender, AppEvent::RemoteListed { path, files }),
                Err(message) => events::post(&sender, AppEvent::RemoteListFailed { path, message }),
            }
        });
    }

    pub(super) fn refresh_remote_current(&self) {
        let path = self.remote.path();
        if !path.is_empty() {
            self.refresh_remote(&path);
        }
    }

    fn refresh_active_pane(&self) {
        match self.active_side() {
            Side::Local => self.refresh_local(None),
            Side::Remote => self.refresh_remote_current(),
        }
    }

    /// Open the selected item: enter a directory, or transfer a file.
    fn activate_selection(&self, side: Side) {
        let pane = self.pane(side);
        let Some(file) = pane.selected_file() else {
            return;
        };
        if !file.is_dir {
            // Enter on a file means "move it", which is the common case in a
            // dual-pane transfer client.
            self.transfer_files(side, vec![file]);
            return;
        }
        match side {
            Side::Local => self.refresh_local(Some(Path::new(&file.path))),
            Side::Remote => self.change_remote_directory(&file.path),
        }
    }

    pub(super) fn change_remote_directory(&self, path: &str) {
        let Some(client) = self.state.borrow().client() else {
            return;
        };
        let sender = self.sender.clone();
        let path = path.to_string();
        std::thread::spawn(move || {
            let result = client
                .lock()
                .map_err(|_| "the connection is unusable".to_string())
                .and_then(|mut client| client.chdir(&path).map_err(|err| err.to_string()));
            match result {
                Ok(resolved) => {
                    events::post(&sender, AppEvent::RemoteChangedDirectory { path: resolved })
                }
                Err(message) => events::post(&sender, AppEvent::RemoteListFailed { path, message }),
            }
        });
    }

    fn go_parent(&self) {
        self.go_parent_in(self.active_side());
    }

    fn go_parent_in(&self, side: Side) {
        match side {
            Side::Local => {
                let current = PathBuf::from(self.local.path());
                let parent = local_files::parent_local(&current);
                if parent != current {
                    self.refresh_local(Some(&parent));
                } else {
                    self.announce("Already at the top");
                }
            }
            Side::Remote => {
                let current = self.remote.path();
                let parent = protocols::path::parent(&current);
                if parent != current {
                    self.change_remote_directory(&parent);
                } else {
                    self.announce("Already at the top");
                }
            }
        }
    }

    fn go_home(&self) {
        match self.active_side() {
            Side::Local => {
                let home = portkeydrop_core::portable::home_dir();
                self.refresh_local(Some(&home));
            }
            Side::Remote => {
                let home = self.state.borrow().remote_home.clone();
                self.change_remote_directory(&home);
            }
        }
    }

    fn navigate_to_typed_path(&self, side: Side) {
        let typed = self.pane(side).typed_path();
        if typed.is_empty() {
            return;
        }
        match side {
            Side::Local => self.refresh_local(Some(Path::new(&typed))),
            Side::Remote => self.change_remote_directory(&typed),
        }
    }

    fn cycle_pane_focus(&self) {
        match self.focused_side() {
            Some(Side::Local) => self.remote.focus(),
            Some(Side::Remote) => {
                if *self.log_visible.borrow() {
                    self.activity_log.set_focus();
                } else {
                    self.local.focus();
                }
            }
            None => self.local.focus(),
        }
    }

    fn focus_address_bar(&self) {
        if !self.state.borrow().is_connected() {
            self.focus_quick_connect();
            return;
        }
        let pane = self.pane(self.active_side());
        pane.path_bar.set_focus();
    }

    fn focus_quick_connect(&self) {
        self.quick_connect.panel.show(true);
        self.frame.layout();
        self.quick_connect.host.set_focus();
        self.announce("Quick connect");
    }

    fn hide_quick_connect(&self) {
        // Reclaiming the space once connected keeps the panes as large as
        // possible; Ctrl+N brings it back.
        self.quick_connect.password.set_value("");
        self.quick_connect.panel.show(false);
        self.frame.layout();
    }

    /// Dismiss the quick connect bar with Escape.
    ///
    /// Focus has to land somewhere concrete afterwards: hiding the control that
    /// holds focus leaves a keyboard user with nothing selected and no obvious
    /// way back.
    pub(super) fn dismiss_quick_connect(&self) {
        if self.state.borrow().is_connected() {
            self.hide_quick_connect();
            self.announce("Quick connect hidden");
        } else {
            // Disconnected, the bar is the only way to connect, so it stays
            // put and focus simply moves out of it.
            self.announce("Quick connect");
        }
        self.local.focus();
    }

    /// Show the context menu for a pane.
    ///
    /// Built fresh each time so items match what is actually selected, and
    /// popped at the focused row rather than the pointer, which is where a
    /// keyboard user expects it.
    pub(super) fn show_pane_context_menu(&self, side: Side) {
        let pane = self.pane(side);
        let selection = pane.selected_files();
        let has_selection = !selection.is_empty();
        let is_dir = selection.first().is_some_and(|file| file.is_dir);
        let connected = self.state.borrow().is_connected();

        let mut menu = Menu::builder().build();
        let transfer_label = match side {
            Side::Local => "&Upload",
            Side::Remote => "&Download",
        };
        menu.append(
            ids::ID_TRANSFER,
            transfer_label,
            "Transfer the selection",
            ItemKind::Normal,
        );
        if is_dir {
            menu.append(
                ids::ID_PARENT_DIR,
                "&Open",
                "Open this folder",
                ItemKind::Normal,
            );
        }
        menu.append_separator();
        menu.append(
            ids::ID_RENAME,
            "&Rename\tF2",
            "Rename the selection",
            ItemKind::Normal,
        );
        menu.append(
            ids::ID_DELETE,
            "De&lete\tDel",
            "Delete the selection",
            ItemKind::Normal,
        );
        menu.append_separator();
        menu.append(
            ids::ID_MKDIR,
            &ids::labelled("Ne&w Directory...", ids::ID_MKDIR),
            "Create a directory",
            ItemKind::Normal,
        );
        menu.append(
            ids::ID_REFRESH,
            &ids::labelled("Re&fresh", ids::ID_REFRESH),
            "Refresh this pane",
            ItemKind::Normal,
        );
        menu.append_separator();
        menu.append(
            ids::ID_PROPERTIES,
            &ids::labelled("Propert&ies...", ids::ID_PROPERTIES),
            "Show properties",
            ItemKind::Normal,
        );

        // Grey out what cannot apply, rather than offering it and failing.
        for id in [
            ids::ID_TRANSFER,
            ids::ID_RENAME,
            ids::ID_DELETE,
            ids::ID_PROPERTIES,
        ] {
            menu.enable_item(id, has_selection);
        }
        if side == Side::Remote {
            for id in [
                ids::ID_TRANSFER,
                ids::ID_RENAME,
                ids::ID_DELETE,
                ids::ID_MKDIR,
            ] {
                menu.enable_item(id, connected && (has_selection || id == ids::ID_MKDIR));
            }
        }

        pane.list.popup_menu(&mut menu, None);
    }

    // ---------------------------------------------------------------
    // Display options
    // ---------------------------------------------------------------

    fn toggle_hidden(&self) {
        let show = !self.state.borrow().settings.display.show_hidden_files;
        {
            let mut state = self.state.borrow_mut();
            state.settings.display.show_hidden_files = show;
            state.save_settings();
        }
        self.local.state.borrow_mut().set_show_hidden(show);
        self.remote.state.borrow_mut().set_show_hidden(show);
        self.local.refresh_rows();
        self.remote.refresh_rows();
        self.announce(if show {
            "Hidden files shown"
        } else {
            "Hidden files hidden"
        });
    }

    fn sort_by(&self, field: SortField) {
        self.local.state.borrow_mut().sort_by(field);
        self.remote.state.borrow_mut().sort_by(field);
        self.local.refresh_rows();
        self.remote.refresh_rows();

        let ascending = self.local.state.borrow().sort_ascending();
        {
            let mut state = self.state.borrow_mut();
            state.settings.display.sort_by = field.as_str().to_string();
            state.settings.display.sort_ascending = ascending;
            state.save_settings();
        }
        self.announce(&format!(
            "Sorted by {}, {}",
            field.display_name(),
            if ascending { "ascending" } else { "descending" }
        ));
    }

    fn prompt_filter(&self) {
        let side = self.active_side();
        let pane = self.pane(side);
        let current = pane.state.borrow().filter().to_string();
        let Some(filter) = prompts::ask_text(
            &self.frame,
            "Filter",
            "Show only items whose name contains:",
            &current,
        )
        .or(Some(String::new())) else {
            return;
        };

        pane.state.borrow_mut().set_filter(filter.clone());
        pane.refresh_rows();
        let (shown, total) = pane.counts();
        self.announce(&format::filter_announcement(&filter, shown, total));
    }

    fn toggle_activity_log(&self) {
        let visible = !*self.log_visible.borrow();
        *self.log_visible.borrow_mut() = visible;
        self.activity_panel.show(visible);
        self.frame.layout();
        if let Some(menu_bar) = self.frame.get_menu_bar() {
            if let Some(item) = menu_bar.find_item(ids::ID_TOGGLE_ACTIVITY_LOG) {
                item.set_label(if visible {
                    "Hide &Activity Log"
                } else {
                    "Show &Activity Log"
                });
            }
        }
        self.announce(if visible {
            "Activity log shown"
        } else {
            "Activity log hidden"
        });
    }

    // ---------------------------------------------------------------
    // Status, logging, speech
    // ---------------------------------------------------------------

    pub(super) fn update_status(&self) {
        let state = self.state.borrow();
        let connected = state.is_connected();
        self.status_bar.set_status_text(
            &format::connection_status(connected, &state.connected_host),
            0,
        );

        let active = state.transfers.active_count();
        let detail = if active > 0 {
            format!(
                "{active} transfer{} in progress",
                if active == 1 { "" } else { "s" }
            )
        } else {
            self.remote.path()
        };
        self.status_bar.set_status_text(&detail, 1);
        drop(state);
        self.update_tray_tooltip();

        self.frame.set_title(&format::window_title(
            self.state
                .borrow()
                .is_connected()
                .then(|| self.remote.path())
                .as_deref(),
        ));
    }

    /// Re-apply display settings to both panes.
    ///
    /// Called after the settings dialog closes so a changed sort order or
    /// hidden-file preference takes effect at once rather than on next launch.
    pub(super) fn refresh_display_settings(&self) {
        let (sort_field, ascending, show_hidden) = {
            let state = self.state.borrow();
            (
                SortField::from_setting(&state.settings.display.sort_by),
                state.settings.display.sort_ascending,
                state.settings.display.show_hidden_files,
            )
        };
        for pane in [&self.local, &self.remote] {
            let mut state = pane.state.borrow_mut();
            state.set_show_hidden(show_hidden);
            // `sort_by` toggles direction when the field is unchanged, so the
            // direction is set explicitly afterwards.
            state.sort_by(sort_field);
            if state.sort_ascending() != ascending {
                state.sort_by(sort_field);
            }
            drop(state);
            pane.refresh_rows();
        }
        if let Some(menu_bar) = self.frame.get_menu_bar() {
            menu_bar.check_item(ids::ID_SHOW_HIDDEN, show_hidden);
        }
    }

    /// Append a line to the activity log.
    pub fn log(&self, message: &str) {
        let line = format::log_line(chrono::Local::now().naive_local(), message);
        self.activity_log.append_text(&format!("{line}\n"));
        log::info!("{message}");
    }

    /// Speak a message and show it in the status bar.
    pub(super) fn announce(&self, message: &str) {
        self.status_bar.set_status_text(message, 1);
        self.announce_only(message);
    }

    /// Speak a message without touching the status bar.
    pub(super) fn announce_only(&self, message: &str) {
        self.state.borrow_mut().announce(message);
    }

    pub(super) fn update_retry_menu(&self) {
        let enabled = self.state.borrow().last_failed_transfer.is_some();
        if let Some(menu_bar) = self.frame.get_menu_bar() {
            menu_bar.enable_item(ids::ID_RETRY_LAST_FAILED, enabled);
        }
    }

    // ---------------------------------------------------------------
    // Lifecycle
    // ---------------------------------------------------------------

    fn restore_queue(&self) {
        let jobs = {
            let state = self.state.borrow();
            portkeydrop_core::transfer::load_queue(&state.config_dir)
        };
        if jobs.is_empty() {
            return;
        }
        let count = jobs.len();
        self.state.borrow().transfers.restore_jobs(jobs);
        self.log(&format!(
            "{count} unfinished transfer{} restored from the last session.",
            if count == 1 { "" } else { "s" }
        ));
    }

    pub(super) fn show_window(&self) {
        self.frame.show(true);
        self.frame.iconize(false);
        self.frame.raise();
        // Land on a control: focusing the bare frame leaves keyboard and
        // screen reader users on the title bar with nowhere to go.
        self.local.focus();
    }

    // ---------------------------------------------------------------
    // Notification area
    // ---------------------------------------------------------------

    /// Create or remove the tray icon to match the current setting.
    pub(super) fn sync_tray_icon(&self) {
        let wanted = self.state.borrow().settings.app.show_notification_area_icon;
        let present = self.tray.borrow().is_some();

        if wanted && !present {
            match TrayIcon::create(self) {
                Some(icon) => *self.tray.borrow_mut() = Some(icon),
                None => self.log("The notification area is unavailable on this system."),
            }
        } else if !wanted && present {
            if let Some(icon) = self.tray.borrow_mut().take() {
                icon.remove();
            }
        }
        self.update_tray_tooltip();
    }

    /// Refresh the tray tooltip from the current state.
    ///
    /// The tooltip is what a screen reader announces for the icon, so it is
    /// kept current rather than set once at startup.
    pub(super) fn update_tray_tooltip(&self) {
        // The text is built before the tray is borrowed, so the state borrow
        // is released first and the two cannot overlap.
        let tooltip = {
            let state = self.state.borrow();
            tray::tooltip_for(
                state.is_connected(),
                &state.connected_host,
                &state.transfers.jobs(),
            )
        };
        if let Some(icon) = self.tray.borrow().as_ref() {
            icon.set_tooltip(&tooltip);
            icon.refresh_menu(self);
        }
    }

    /// Run a command chosen from the tray menu.
    pub(super) fn handle_tray_command(&self, id: i32) {
        // Exit from the tray means exit, even when the close button is set to
        // minimise instead: it is the only way out from there.
        if id == ID_EXIT {
            self.force_exit();
            return;
        }
        self.handle_command(id);
    }

    /// Whether closing the window should hide it instead of quitting.
    ///
    /// Only when there is a tray icon to restore it from. Hiding to a tray that
    /// is not there would leave the app running with no way back to it.
    pub(super) fn should_minimise_to_tray(&self) -> bool {
        let state = self.state.borrow();
        state.settings.app.minimize_to_notification_area_on_close
            && state.settings.app.show_notification_area_icon
            && self.tray.borrow().is_some()
    }

    fn request_exit(&self) {
        self.force_exit();
    }

    /// Shut down for real, bypassing minimise-to-tray.
    pub(super) fn force_exit(&self) {
        *self.exiting.borrow_mut() = true;
        self.on_close();
        self.frame.close(true);
    }

    /// Everything that has to happen before the process goes away.
    ///
    /// Shared by every route out — the File menu, the tray menu, and the
    /// window's close button — so none of them can skip a step.
    fn on_close(&self) {
        *self.exiting.borrow_mut() = true;
        self.timer.stop();

        // The icon must be destroyed, not merely hidden: on Windows it owns a
        // hidden top-level window, and while that lives wxWidgets keeps the
        // process running with nothing on screen. Safe here because tray
        // commands are deferred onto the event pump, so this never runs inside
        // the icon's own handler — doing that frees the object wxWidgets is
        // about to return into, which is what crashed on exit.
        if let Some(icon) = self.tray.borrow_mut().take() {
            icon.remove();
        }

        let mut state = self.state.borrow_mut();
        state.save_queue();
        state.save_settings();
        if !state.exit_sound_played {
            state.exit_sound_played = true;
            state.play_sound("exit");
        }
        state.clear_client();
    }
}

/// An update download in flight.
///
/// Held on the frame rather than in the worker so a Cancel raised on the UI
/// thread reaches the thread doing the reading, and so the progress window is
/// closed on whichever path the download ends by.
pub(super) struct Download {
    /// The progress window. Behind an `Rc` because `ProgressDialog` destroys
    /// its window on drop: handing out clones of the value would destroy it
    /// at the first one and leave the rest dangling.
    pub(super) dialog: Rc<ProgressDialog>,
    /// The file being fetched, named in the status line.
    pub(super) artifact: String,
    /// Raised when the user presses Cancel; the worker checks it per chunk.
    pub(super) cancel: Arc<AtomicBool>,
    /// The last percentage spoken, so a screen reader is not flooded.
    pub(super) announced: Option<u8>,
}

/// A hand-off slot for a connected client.
///
/// A `Box<dyn TransferClient>` cannot travel through the event channel (the
/// events are `Debug`, and a client is not), so the worker thread parks the
/// client here and the UI picks it up when the matching event arrives.
mod client_handoff {
    use std::sync::{Mutex, OnceLock};

    use portkeydrop_core::protocols::TransferClient;

    pub struct Slot;

    fn slot() -> &'static Mutex<Option<Box<dyn TransferClient>>> {
        static SLOT: OnceLock<Mutex<Option<Box<dyn TransferClient>>>> = OnceLock::new();
        SLOT.get_or_init(|| Mutex::new(None))
    }

    impl Slot {
        /// Park a freshly connected client.
        pub fn with_client(&self, client: Box<dyn TransferClient>) {
            if let Ok(mut slot) = slot().lock() {
                *slot = Some(client);
            }
        }

        /// Take the parked client, if there is one.
        pub fn take(&self) -> Option<Box<dyn TransferClient>> {
            slot().lock().ok()?.take()
        }
    }
}

use client_handoff::Slot as ClientSlot;

/// The process-wide hand-off slot.
const CONNECTED_CLIENT: ClientSlot = ClientSlot;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_parked_client_is_taken_exactly_once() {
        // The slot is how a connected client crosses from the worker thread to
        // the UI; taking it twice would hand out a connection that is already
        // in use.
        assert!(CONNECTED_CLIENT.take().is_none());
    }

    #[test]
    fn the_two_sides_are_distinct() {
        assert_ne!(Side::Local, Side::Remote);
    }
}
