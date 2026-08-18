//! Managing sound packs.
//!
//! Install from a ZIP, export, remove, and preview. Preview matters: it is the
//! only way to tell what a pack sounds like without triggering a real transfer.

use std::cell::RefCell;
use std::rc::Rc;

use wxdragon::prelude::*;

use portkeydrop_core::sound_events::SOUND_EVENT_SECTIONS;
use portkeydrop_core::soundpacks::{self, PackInstaller};

use crate::ui::main_frame::MainFrame;
use crate::ui::prompts;

/// Window title.
pub const TITLE: &str = "Sound Packs";

const ID_INSTALL: Id = 7400;
const ID_EXPORT: Id = 7401;
const ID_REMOVE: Id = 7402;
const ID_PREVIEW: Id = 7403;
const ID_USE_PACK: Id = 7404;

/// Show the sound pack manager.
pub fn show(frame: &MainFrame) {
    let dialog = Dialog::builder(&frame.frame, TITLE)
        .with_size(640, 480)
        .with_style(DialogStyle::DefaultDialogStyle | DialogStyle::ResizeBorder)
        .build();

    let packs_dir = soundpacks::soundpacks_dir(&frame.state.borrow().config_dir);
    let installer = match PackInstaller::new(packs_dir.clone()) {
        Ok(installer) => Rc::new(installer),
        Err(err) => {
            prompts::error(
                &frame.frame,
                "Cannot manage sound packs",
                &format!("The sound packs folder could not be opened: {err}"),
            );
            return;
        }
    };

    let sizer = BoxSizer::builder(Orientation::Vertical).build();

    let list_label = StaticText::builder(&dialog)
        .with_label("Installed sound packs:")
        .build();
    sizer.add(&list_label, 0, SizerFlag::Left | SizerFlag::All, 6);

    let list = ListBox::builder(&dialog).build();
    list.set_name("Installed sound packs");
    sizer.add(&list, 1, SizerFlag::Expand | SizerFlag::All, 6);

    let details = TextCtrl::builder(&dialog)
        .with_style(TextCtrlStyle::MultiLine | TextCtrlStyle::ReadOnly)
        .build();
    details.set_name("Sound pack details");
    sizer.add(&details, 1, SizerFlag::Expand | SizerFlag::All, 6);

    let preview_label = StaticText::builder(&dialog)
        .with_label("&Preview this sound:")
        .build();
    sizer.add(&preview_label, 0, SizerFlag::Left | SizerFlag::All, 6);

    let event_picker = Choice::builder(&dialog).build();
    event_picker.set_name("Preview this sound");
    let mut event_keys: Vec<String> = Vec::new();
    for section in SOUND_EVENT_SECTIONS {
        for (key, label) in section.events {
            event_picker.append(&format!("{}: {label}", section.title));
            event_keys.push(key.to_string());
        }
    }
    if !event_keys.is_empty() {
        event_picker.set_selection(0);
    }
    sizer.add(&event_picker, 0, SizerFlag::Expand | SizerFlag::All, 4);

    let buttons = BoxSizer::builder(Orientation::Horizontal).build();
    let preview = Button::builder(&dialog)
        .with_id(ID_PREVIEW)
        .with_label("&Play")
        .build();
    let use_pack = Button::builder(&dialog)
        .with_id(ID_USE_PACK)
        .with_label("&Use This Pack")
        .build();
    let install = Button::builder(&dialog)
        .with_id(ID_INSTALL)
        .with_label("&Install...")
        .build();
    let export = Button::builder(&dialog)
        .with_id(ID_EXPORT)
        .with_label("&Export...")
        .build();
    let remove = Button::builder(&dialog)
        .with_id(ID_REMOVE)
        .with_label("&Remove")
        .build();
    let close = Button::builder(&dialog)
        .with_id(ID_OK)
        .with_label("&Close")
        .build();
    for button in [&preview, &use_pack, &install, &export, &remove, &close] {
        buttons.add(button, 0, SizerFlag::All, 4);
    }
    sizer.add_sizer(&buttons, 0, SizerFlag::AlignRight | SizerFlag::All, 8);

    close.set_default();
    dialog.set_sizer(sizer, true);

    let directories: Rc<RefCell<Vec<String>>> = Rc::new(RefCell::new(Vec::new()));

    let repopulate = {
        let directories = Rc::clone(&directories);
        let packs_dir = packs_dir.clone();
        let frame = frame.clone();
        move || {
            let packs = soundpacks::available_packs(&packs_dir);
            list.clear();
            let mut names = Vec::new();
            let active = frame.state.borrow().settings.audio.sound_pack.clone();
            for (directory, pack) in &packs {
                let marker = if *directory == active {
                    "  (in use)"
                } else {
                    ""
                };
                list.append(&format!("{}{marker}", pack.display_name()));
                names.push(directory.clone());
            }
            *directories.borrow_mut() = names;
            if list.get_count() > 0 {
                list.set_selection(0, true);
            }
        }
    };

    let selected_directory = {
        let directories = Rc::clone(&directories);
        move || -> Option<String> {
            let index = list.get_selection()? as usize;
            directories.borrow().get(index).cloned()
        }
    };

    let show_details = {
        let packs_dir = packs_dir.clone();
        let selected_directory = selected_directory.clone();
        move || {
            let Some(directory) = selected_directory() else {
                details.set_value("");
                return;
            };
            let packs = soundpacks::available_packs(&packs_dir);
            let Some(pack) = packs.get(&directory) else {
                details.set_value("");
                return;
            };
            details.set_value(&describe_pack(
                pack.display_name(),
                &pack.manifest.author,
                &pack.manifest.version,
                &pack.manifest.description,
                pack.manifest.sounds.len(),
            ));
        }
    };

    repopulate();
    show_details();

    {
        let show_details = show_details.clone();
        list.on_selection_changed(move |_| show_details());
    }

    {
        let frame = frame.clone();
        let selected_directory = selected_directory.clone();
        let packs_dir = packs_dir.clone();
        let event_keys = Rc::new(event_keys);
        preview.on_click(move |_| {
            let Some(directory) = selected_directory() else {
                return;
            };
            let Some(index) = event_picker.get_selection() else {
                return;
            };
            let Some(event) = event_keys.get(index as usize) else {
                return;
            };
            match soundpacks::resolve_sound(event, &directory, &packs_dir) {
                Some((file, volume)) => {
                    if !soundpacks::play_sound_file(&file, volume) {
                        prompts::info(
                            &dialog,
                            "Nothing played",
                            "That sound could not be played. Check that audio output is \
                             available and that the file is a supported format.",
                        );
                    }
                }
                None => prompts::info(
                    &dialog,
                    "No sound for that event",
                    "This pack does not define a sound for that event, and neither does the \
                     default pack.",
                ),
            }
            let _ = &frame;
        });
    }

    // Selecting a pack is reachable from the button and from Enter on the
    // list, so the action lives in one place.
    let use_selected_pack: Rc<dyn Fn()> = {
        let frame = frame.clone();
        let selected_directory = selected_directory.clone();
        let repopulate = repopulate.clone();
        Rc::new(move || {
            let Some(directory) = selected_directory() else {
                return;
            };
            {
                let mut state = frame.state.borrow_mut();
                state.settings.audio.sound_pack = directory.clone();
                state.save_settings();
                state.apply_settings();
            }
            frame.log(&format!("Sound pack changed to {directory}."));
            repopulate();
        })
    };

    {
        let use_selected_pack = Rc::clone(&use_selected_pack);
        use_pack.on_click(move |_| use_selected_pack());
    }

    // Enter on a pack selects it, rather than doing nothing.
    {
        let use_selected_pack = Rc::clone(&use_selected_pack);
        list.on_item_double_clicked(move |_| use_selected_pack());
    }

    {
        let installer = Rc::clone(&installer);
        let repopulate = repopulate.clone();
        install.on_click(move |_| {
            let Some(path) = prompts::ask_open_file(
                &dialog,
                "Choose a sound pack",
                "Sound pack archives (*.zip)|*.zip|All files (*.*)|*.*",
                "",
            ) else {
                return;
            };
            match installer.install_from_zip(std::path::Path::new(&path), None) {
                Ok(directory) => {
                    prompts::info(
                        &dialog,
                        "Sound pack installed",
                        &format!("Installed as {directory}."),
                    );
                    repopulate();
                }
                Err(err) => prompts::error(
                    &dialog,
                    "Could not install that sound pack",
                    &err.to_string(),
                ),
            }
        });
    }

    {
        let installer = Rc::clone(&installer);
        let selected_directory = selected_directory.clone();
        export.on_click(move |_| {
            let Some(directory) = selected_directory() else {
                return;
            };
            let Some(path) = prompts::ask_save_file(
                &dialog,
                "Export sound pack",
                "Sound pack archives (*.zip)|*.zip",
                &format!("{directory}.zip"),
            ) else {
                return;
            };
            match installer.export_pack(&directory, std::path::Path::new(&path)) {
                Ok(()) => {
                    prompts::info(&dialog, "Sound pack exported", &format!("Saved to {path}."))
                }
                Err(err) => prompts::error(
                    &dialog,
                    "Could not export that sound pack",
                    &err.to_string(),
                ),
            }
        });
    }

    {
        let installer = Rc::clone(&installer);
        let selected_directory = selected_directory.clone();
        let repopulate = repopulate.clone();
        let frame = frame.clone();
        remove.on_click(move |_| {
            let Some(directory) = selected_directory() else {
                return;
            };
            if !prompts::confirm_destructive(
                &dialog,
                "Remove sound pack",
                &format!("Remove the sound pack {directory}? Its files are deleted."),
            ) {
                return;
            }
            match installer.uninstall(&directory) {
                Ok(()) => {
                    // Falling back to the default keeps every event making a
                    // sound rather than going silent.
                    if frame.state.borrow().settings.audio.sound_pack == directory {
                        let mut state = frame.state.borrow_mut();
                        state.settings.audio.sound_pack = soundpacks::DEFAULT_PACK.to_string();
                        state.save_settings();
                        state.apply_settings();
                    }
                    repopulate();
                }
                Err(err) => prompts::error(
                    &dialog,
                    "Could not remove that sound pack",
                    &err.to_string(),
                ),
            }
        });
    }

    list.set_focus();
    dialog.show_modal();
    dialog.destroy();
}

/// The details text for a pack.
pub fn describe_pack(
    name: &str,
    author: &str,
    version: &str,
    description: &str,
    sound_count: usize,
) -> String {
    let mut lines = vec![format!("Name: {name}")];
    if !author.trim().is_empty() {
        lines.push(format!("Author: {author}"));
    }
    if !version.trim().is_empty() {
        lines.push(format!("Version: {version}"));
    }
    lines.push(format!(
        "Sounds: {sound_count} event{}",
        if sound_count == 1 { "" } else { "s" }
    ));
    if !description.trim().is_empty() {
        lines.push(String::new());
        lines.push(description.trim().to_string());
    }
    lines.join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_full_pack_description_lists_everything() {
        let text = describe_pack("Retro Beeps", "Someone", "1.2.0", "Old-school sounds.", 12);
        assert!(text.contains("Name: Retro Beeps"));
        assert!(text.contains("Author: Someone"));
        assert!(text.contains("Version: 1.2.0"));
        assert!(text.contains("Sounds: 12 events"));
        assert!(text.contains("Old-school sounds."));
    }

    #[test]
    fn missing_metadata_is_left_out_rather_than_shown_empty() {
        let text = describe_pack("Bare", "", "", "", 3);
        assert!(text.contains("Name: Bare"));
        assert!(!text.contains("Author:"));
        assert!(!text.contains("Version:"));
        assert_eq!(text.lines().count(), 2);
    }

    #[test]
    fn a_single_sound_is_counted_in_the_singular() {
        assert!(describe_pack("One", "", "", "", 1).contains("Sounds: 1 event"));
        assert!(!describe_pack("One", "", "", "", 1).contains("1 events"));
    }

    #[test]
    fn a_pack_with_no_sounds_still_describes_itself() {
        assert!(describe_pack("Empty", "", "", "", 0).contains("Sounds: 0 events"));
    }

    #[test]
    fn the_preview_picker_covers_every_event() {
        let total: usize = SOUND_EVENT_SECTIONS.iter().map(|s| s.events.len()).sum();
        assert_eq!(
            total,
            portkeydrop_core::sound_events::user_mutable_sound_events().len()
        );
    }
}
