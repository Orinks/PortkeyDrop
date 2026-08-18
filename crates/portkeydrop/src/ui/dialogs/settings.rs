//! Application settings.
//!
//! Grouped into a notebook by area. Each page is a single column of labelled
//! controls, which keeps tab order matching reading order — a grid would put
//! the labels and their controls in separate tab stops.

use std::rc::Rc;

use wxdragon::prelude::*;

use portkeydrop_core::settings::{overwrite_mode, Settings};
use portkeydrop_core::sound_events::SOUND_EVENT_SECTIONS;

use crate::ui::main_frame::MainFrame;

/// Window title.
pub const TITLE: &str = "Settings";

/// Overwrite modes, in the order the picker lists them.
const OVERWRITE_CHOICES: [(&str, &str); 4] = [
    (overwrite_mode::ASK, "Ask each time"),
    (overwrite_mode::OVERWRITE, "Replace the existing file"),
    (overwrite_mode::SKIP, "Skip the transfer"),
    (overwrite_mode::RENAME, "Keep both, with a new name"),
];

/// Host key policies, in the order the picker lists them.
const HOST_KEY_CHOICES: [(&str, &str); 3] = [
    ("ask", "Ask before trusting a new server"),
    ("always", "Only connect to servers already trusted"),
    ("never", "Trust any server (not recommended)"),
];

/// Update channels, in the order the picker lists them.
const CHANNEL_CHOICES: [(&str, &str); 2] =
    [("stable", "Stable releases"), ("nightly", "Nightly builds")];

/// Show the settings dialog, applying changes on OK.
pub fn show(frame: &MainFrame) {
    let dialog = Dialog::builder(&frame.frame, TITLE)
        .with_size(620, 560)
        .with_style(DialogStyle::DefaultDialogStyle | DialogStyle::ResizeBorder)
        .build();

    let settings = frame.state.borrow().settings.clone();

    let outer = BoxSizer::builder(Orientation::Vertical).build();
    let notebook = Notebook::builder(&dialog).build();
    notebook.set_name("Settings pages");

    let transfers = build_transfers_page(&notebook, &settings);
    notebook.add_page(&transfers.panel, "&Transfers", true, None);

    let display = build_display_page(&notebook, &settings);
    notebook.add_page(&display.panel, "&Display", false, None);

    let connection = build_connection_page(&notebook, &settings);
    notebook.add_page(&connection.panel, "&Connection", false, None);

    let speech = build_speech_page(&notebook, &settings);
    notebook.add_page(&speech.panel, "&Speech", false, None);

    let audio = build_audio_page(&notebook, &settings, frame);
    notebook.add_page(&audio.panel, "&Sounds", false, None);

    let application = build_application_page(&notebook, &settings);
    notebook.add_page(&application.panel, "&Application", false, None);

    outer.add(&notebook, 1, SizerFlag::Expand | SizerFlag::All, 8);

    let buttons = BoxSizer::builder(Orientation::Horizontal).build();
    let ok = Button::builder(&dialog)
        .with_id(ID_OK)
        .with_label("&Save")
        .build();
    let cancel = Button::builder(&dialog)
        .with_id(ID_CANCEL)
        .with_label("&Cancel")
        .build();
    ok.set_default();
    buttons.add(&ok, 0, SizerFlag::All, 4);
    buttons.add(&cancel, 0, SizerFlag::All, 4);
    outer.add_sizer(&buttons, 0, SizerFlag::AlignRight | SizerFlag::All, 8);

    dialog.set_sizer(outer, true);

    if dialog.show_modal() == ID_OK {
        let mut updated = settings.clone();
        transfers.apply(&mut updated);
        display.apply(&mut updated);
        connection.apply(&mut updated);
        speech.apply(&mut updated);
        audio.apply(&mut updated);
        application.apply(&mut updated);

        let workers_changed =
            updated.transfer.concurrent_transfers != settings.transfer.concurrent_transfers;

        {
            let mut state = frame.state.borrow_mut();
            state.settings = updated;
            state.save_settings();
            state.apply_settings();
            if workers_changed {
                let count = state.settings.transfer.concurrent_transfers;
                state.transfers.set_worker_count(count);
            }
        }
        frame.refresh_display_settings();
        // Creating or removing the tray icon here means the preference takes
        // effect at once rather than on next launch.
        frame.sync_tray_icon();
        frame.log("Settings saved.");
    }
    dialog.destroy();
}

/// A settings page and how to read it back.
struct Page {
    panel: Panel,
    apply: Box<dyn Fn(&mut Settings)>,
}

impl Page {
    fn apply(&self, settings: &mut Settings) {
        (self.apply)(settings);
    }
}

/// Build a page panel and its vertical sizer.
fn page(notebook: &Notebook) -> (Panel, BoxSizer) {
    let panel = Panel::builder(notebook).build();
    let sizer = BoxSizer::builder(Orientation::Vertical).build();
    (panel, sizer)
}

/// Add a labelled control to a page.
fn labelled<W: WxWidget>(panel: &Panel, sizer: &BoxSizer, label: &str, control: &W, name: &str) {
    let text = StaticText::builder(panel).with_label(label).build();
    sizer.add(&text, 0, SizerFlag::Left | SizerFlag::All, 6);
    control.set_name(name);
    sizer.add(control, 0, SizerFlag::Expand | SizerFlag::All, 4);
}

/// Fill a picker and select the entry matching `current`.
fn fill_choice(choice: &Choice, entries: &[(&str, &str)], current: &str) {
    for (_, label) in entries {
        choice.append(label);
    }
    let index = entries
        .iter()
        .position(|(value, _)| *value == current)
        .unwrap_or(0);
    choice.set_selection(index as u32);
}

/// Read a picker back into its stored value.
fn choice_value(choice: &Choice, entries: &[(&str, &str)]) -> String {
    let index = choice.get_selection().unwrap_or(0) as usize;
    entries
        .get(index)
        .map(|(value, _)| value.to_string())
        .unwrap_or_else(|| entries[0].0.to_string())
}

fn build_transfers_page(notebook: &Notebook, settings: &Settings) -> Page {
    let (panel, sizer) = page(notebook);

    let concurrent = SpinCtrl::builder(&panel).with_range(1, 16).build();
    concurrent.set_value(settings.transfer.concurrent_transfers as i32);
    labelled(
        &panel,
        &sizer,
        "&Simultaneous transfers:",
        &concurrent,
        "Simultaneous transfers",
    );

    let overwrite = Choice::builder(&panel).build();
    fill_choice(
        &overwrite,
        &OVERWRITE_CHOICES,
        &settings.transfer.overwrite_mode,
    );
    labelled(
        &panel,
        &sizer,
        "&When the destination file already exists:",
        &overwrite,
        "When the destination file already exists",
    );

    let resume = CheckBox::builder(&panel)
        .with_label("&Resume interrupted downloads where they stopped")
        .build();
    resume.set_value(settings.transfer.resume_partial);
    sizer.add(&resume, 0, SizerFlag::Left | SizerFlag::All, 6);

    let timestamps = CheckBox::builder(&panel)
        .with_label("Preserve file &modification times where the server allows it")
        .build();
    timestamps.set_value(settings.transfer.preserve_timestamps);
    sizer.add(&timestamps, 0, SizerFlag::Left | SizerFlag::All, 6);

    let symlinks = CheckBox::builder(&panel)
        .with_label("&Follow symbolic links when copying folders")
        .build();
    symlinks.set_value(settings.transfer.follow_symlinks);
    sizer.add(&symlinks, 0, SizerFlag::Left | SizerFlag::All, 6);

    let download_dir = TextCtrl::builder(&panel).build();
    download_dir.set_value(&settings.transfer.default_download_dir);
    labelled(
        &panel,
        &sizer,
        "&Default download folder:",
        &download_dir,
        "Default download folder",
    );

    panel.set_sizer(sizer, true);

    let apply = {
        let (concurrent, overwrite, resume, timestamps, symlinks, download_dir) = (
            concurrent,
            overwrite,
            resume,
            timestamps,
            symlinks,
            download_dir,
        );
        move |settings: &mut Settings| {
            settings.transfer.concurrent_transfers = concurrent.value().max(1) as usize;
            settings.transfer.overwrite_mode = choice_value(&overwrite, &OVERWRITE_CHOICES);
            settings.transfer.resume_partial = resume.is_checked();
            settings.transfer.preserve_timestamps = timestamps.is_checked();
            settings.transfer.follow_symlinks = symlinks.is_checked();
            settings.transfer.default_download_dir = download_dir.get_value().trim().to_string();
        }
    };
    Page {
        panel,
        apply: Box::new(apply),
    }
}

fn build_display_page(notebook: &Notebook, settings: &Settings) -> Page {
    let (panel, sizer) = page(notebook);

    let announce = CheckBox::builder(&panel)
        .with_label("&Announce how many items a folder holds after it loads")
        .build();
    announce.set_value(settings.display.announce_file_count);
    sizer.add(&announce, 0, SizerFlag::Left | SizerFlag::All, 6);

    let interval = SpinCtrl::builder(&panel).with_range(0, 100).build();
    interval.set_value(settings.display.progress_interval as i32);
    labelled(
        &panel,
        &sizer,
        "Announce transfer &progress every this many percent (0 turns it off):",
        &interval,
        "Progress announcement interval",
    );

    let hidden = CheckBox::builder(&panel)
        .with_label("Show &hidden files")
        .build();
    hidden.set_value(settings.display.show_hidden_files);
    sizer.add(&hidden, 0, SizerFlag::Left | SizerFlag::All, 6);

    panel.set_sizer(sizer, true);

    let apply = {
        let (announce, interval, hidden) = (announce, interval, hidden);
        move |settings: &mut Settings| {
            settings.display.announce_file_count = announce.is_checked();
            settings.display.progress_interval = interval.value().max(0) as u32;
            settings.display.show_hidden_files = hidden.is_checked();
        }
    };
    Page {
        panel,
        apply: Box::new(apply),
    }
}

fn build_connection_page(notebook: &Notebook, settings: &Settings) -> Page {
    let (panel, sizer) = page(notebook);

    let timeout = SpinCtrl::builder(&panel).with_range(5, 300).build();
    timeout.set_value(settings.connection.timeout as i32);
    labelled(
        &panel,
        &sizer,
        "Connection &timeout, in seconds:",
        &timeout,
        "Connection timeout",
    );

    let retries = SpinCtrl::builder(&panel).with_range(0, 10).build();
    retries.set_value(settings.connection.max_retries as i32);
    labelled(
        &panel,
        &sizer,
        "&Retry a failed connection this many times:",
        &retries,
        "Connection retries",
    );

    let host_keys = Choice::builder(&panel).build();
    fill_choice(
        &host_keys,
        &HOST_KEY_CHOICES,
        &settings.connection.verify_host_keys,
    );
    labelled(
        &panel,
        &sizer,
        "SSH &host key checking:",
        &host_keys,
        "SSH host key checking",
    );

    let passive = CheckBox::builder(&panel)
        .with_label("Use &passive mode for FTP connections")
        .build();
    passive.set_value(settings.connection.passive_mode);
    sizer.add(&passive, 0, SizerFlag::Left | SizerFlag::All, 6);

    panel.set_sizer(sizer, true);

    let apply = {
        let (timeout, retries, host_keys, passive) = (timeout, retries, host_keys, passive);
        move |settings: &mut Settings| {
            settings.connection.timeout = timeout.value().max(1) as u64;
            settings.connection.max_retries = retries.value().max(0) as u32;
            settings.connection.verify_host_keys = choice_value(&host_keys, &HOST_KEY_CHOICES);
            settings.connection.passive_mode = passive.is_checked();
        }
    };
    Page {
        panel,
        apply: Box::new(apply),
    }
}

fn build_speech_page(notebook: &Notebook, settings: &Settings) -> Page {
    let (panel, sizer) = page(notebook);

    let note = StaticText::builder(&panel)
        .with_label(
            "Screen readers follow their own speech settings. These apply only when Portkey \
             Drop is speaking through a text-to-speech voice of its own.",
        )
        .build();
    sizer.add(&note, 0, SizerFlag::Left | SizerFlag::All, 6);

    let rate = Slider::builder(&panel)
        .with_min_value(0)
        .with_max_value(100)
        .build();
    rate.set_value(settings.speech.rate);
    labelled(&panel, &sizer, "Speech &rate:", &rate, "Speech rate");

    let volume = Slider::builder(&panel)
        .with_min_value(0)
        .with_max_value(100)
        .build();
    volume.set_value(settings.speech.volume);
    labelled(&panel, &sizer, "Speech &volume:", &volume, "Speech volume");

    panel.set_sizer(sizer, true);

    let apply = {
        let (rate, volume) = (rate, volume);
        move |settings: &mut Settings| {
            settings.speech.rate = rate.get_value();
            settings.speech.volume = volume.get_value();
        }
    };
    Page {
        panel,
        apply: Box::new(apply),
    }
}

fn build_audio_page(notebook: &Notebook, settings: &Settings, frame: &MainFrame) -> Page {
    let (panel, sizer) = page(notebook);

    let enabled = CheckBox::builder(&panel).with_label("Play &sounds").build();
    enabled.set_value(settings.audio.sound_enabled);
    sizer.add(&enabled, 0, SizerFlag::Left | SizerFlag::All, 6);

    let packs_dir = portkeydrop_core::soundpacks::soundpacks_dir(&frame.state.borrow().config_dir);
    let packs = portkeydrop_core::soundpacks::available_packs(&packs_dir);
    let pack_directories: Vec<String> = packs.keys().cloned().collect();

    let pack = Choice::builder(&panel).build();
    for directory in &pack_directories {
        let label = packs
            .get(directory)
            .map(|pack| pack.display_name().to_string())
            .unwrap_or_else(|| directory.clone());
        pack.append(&label);
    }
    let selected = pack_directories
        .iter()
        .position(|directory| *directory == settings.audio.sound_pack)
        .unwrap_or(0);
    if !pack_directories.is_empty() {
        pack.set_selection(selected as u32);
    }
    labelled(&panel, &sizer, "Sound &pack:", &pack, "Sound pack");

    // One checkbox per event, grouped by section, so a user can silence just
    // the ones that get in the way.
    let events_label = StaticText::builder(&panel)
        .with_label("Play these sounds:")
        .build();
    sizer.add(&events_label, 0, SizerFlag::Left | SizerFlag::All, 6);

    let events = CheckListBox::builder(&panel).build();
    events.set_name("Sounds to play");
    let mut event_keys: Vec<String> = Vec::new();
    for section in SOUND_EVENT_SECTIONS {
        for (key, label) in section.events {
            events.append(&format!("{}: {label}", section.title));
            event_keys.push(key.to_string());
        }
    }
    for (index, key) in event_keys.iter().enumerate() {
        // The stored list is what is *muted*, so a box is ticked when the
        // event is absent from it.
        let muted = settings
            .audio
            .muted_sound_events
            .iter()
            .any(|event| event == key);
        events.check(index as u32, !muted);
    }
    sizer.add(&events, 1, SizerFlag::Expand | SizerFlag::All, 4);

    panel.set_sizer(sizer, true);

    let apply = {
        let event_keys = Rc::new(event_keys);
        let pack_directories = Rc::new(pack_directories);
        move |settings: &mut Settings| {
            settings.audio.sound_enabled = enabled.is_checked();
            if let Some(index) = pack.get_selection() {
                if let Some(directory) = pack_directories.get(index as usize) {
                    settings.audio.sound_pack = directory.clone();
                }
            }
            settings.audio.muted_sound_events = event_keys
                .iter()
                .enumerate()
                .filter(|(index, _)| !events.is_checked(*index as u32))
                .map(|(_, key)| key.clone())
                .collect();
        }
    };
    Page {
        panel,
        apply: Box::new(apply),
    }
}

fn build_application_page(notebook: &Notebook, settings: &Settings) -> Page {
    let (panel, sizer) = page(notebook);

    let remember = CheckBox::builder(&panel)
        .with_label("&Reopen the last local folder on startup")
        .build();
    remember.set_value(settings.app.remember_last_local_folder_on_startup);
    sizer.add(&remember, 0, SizerFlag::Left | SizerFlag::All, 6);

    let auto_update = CheckBox::builder(&panel)
        .with_label("Check for &updates automatically")
        .build();
    auto_update.set_value(settings.app.auto_update_enabled);
    sizer.add(&auto_update, 0, SizerFlag::Left | SizerFlag::All, 6);

    let interval = SpinCtrl::builder(&panel).with_range(1, 168).build();
    interval.set_value(settings.app.update_check_interval_hours as i32);
    labelled(
        &panel,
        &sizer,
        "Check for updates every this many &hours:",
        &interval,
        "Update check interval",
    );

    let channel = Choice::builder(&panel).build();
    fill_choice(&channel, &CHANNEL_CHOICES, &settings.app.update_channel);
    labelled(
        &panel,
        &sizer,
        "Update &channel:",
        &channel,
        "Update channel",
    );

    let tray = CheckBox::builder(&panel)
        .with_label("Show an icon in the &notification area")
        .build();
    tray.set_value(settings.app.show_notification_area_icon);
    sizer.add(&tray, 0, SizerFlag::Left | SizerFlag::All, 6);

    let minimize = CheckBox::builder(&panel)
        .with_label("&Minimise to the notification area instead of closing")
        .build();
    minimize.set_value(settings.app.minimize_to_notification_area_on_close);
    sizer.add(&minimize, 0, SizerFlag::Left | SizerFlag::All, 6);

    panel.set_sizer(sizer, true);

    let apply = {
        let (remember, auto_update, interval, channel, tray, minimize) =
            (remember, auto_update, interval, channel, tray, minimize);
        move |settings: &mut Settings| {
            settings.app.remember_last_local_folder_on_startup = remember.is_checked();
            settings.app.auto_update_enabled = auto_update.is_checked();
            settings.app.update_check_interval_hours = interval.value().max(1) as u32;
            settings.app.update_channel = choice_value(&channel, &CHANNEL_CHOICES);
            settings.app.show_notification_area_icon = tray.is_checked();
            settings.app.minimize_to_notification_area_on_close = minimize.is_checked();
        }
    };
    Page {
        panel,
        apply: Box::new(apply),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_overwrite_mode_is_offered() {
        // A mode the settings file can hold but the picker cannot show would
        // be silently rewritten on the next save.
        let offered: Vec<&str> = OVERWRITE_CHOICES.iter().map(|(value, _)| *value).collect();
        assert!(offered.contains(&overwrite_mode::ASK));
        assert!(offered.contains(&overwrite_mode::OVERWRITE));
        assert!(offered.contains(&overwrite_mode::SKIP));
        assert!(offered.contains(&overwrite_mode::RENAME));
    }

    #[test]
    fn every_host_key_policy_is_offered() {
        let offered: Vec<&str> = HOST_KEY_CHOICES.iter().map(|(value, _)| *value).collect();
        assert_eq!(offered, vec!["ask", "always", "never"]);
    }

    #[test]
    fn the_least_safe_host_key_policy_is_marked_as_such() {
        // "Trust any server" disables the protection host key checking exists
        // for; the label has to say so.
        let (_, label) = HOST_KEY_CHOICES
            .iter()
            .find(|(value, _)| *value == "never")
            .unwrap();
        assert!(label.contains("not recommended"));
    }

    #[test]
    fn both_update_channels_are_offered() {
        let offered: Vec<&str> = CHANNEL_CHOICES.iter().map(|(value, _)| *value).collect();
        assert_eq!(offered, vec!["stable", "nightly"]);
    }

    #[test]
    fn every_choice_has_a_readable_label() {
        for entries in [
            &OVERWRITE_CHOICES[..],
            &HOST_KEY_CHOICES[..],
            &CHANNEL_CHOICES[..],
        ] {
            for (value, label) in entries {
                assert!(!label.is_empty(), "{value} has no label");
                // The label is what gets read aloud, so it must not be the raw
                // stored value.
                assert_ne!(label, value);
            }
        }
    }

    #[test]
    fn the_sound_page_lists_every_event() {
        let total: usize = SOUND_EVENT_SECTIONS
            .iter()
            .map(|section| section.events.len())
            .sum();
        assert_eq!(
            total,
            portkeydrop_core::sound_events::user_mutable_sound_events().len()
        );
        assert!(total > 0);
    }
}
