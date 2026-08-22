//! Bringing an existing installation's configuration into a portable copy.
//!
//! A portable build launched from a stick starts with nothing: no sites, no
//! known hosts, no settings. When there is an installed copy on the same
//! machine, offering to copy its configuration across is the difference
//! between the stick being ready to use and being an empty app.
//!
//! Both offers here are made once. The file copy stops being offered as soon
//! as the portable folder has the files; the keyring import leaves a marker,
//! because declining it is an answer and re-asking every launch is not.

use std::path::Path;

use wxdragon::prelude::*;

use portkeydrop_core::migration;

use crate::ui::main_frame::MainFrame;
use crate::ui::prompts;

/// Window title.
pub const TITLE: &str = "Set Up This Portable Copy";

/// Offer both portable-mode carry-overs, in the order that matters.
///
/// Returns whether anything was copied, so the caller knows to re-read what is
/// now on disk.
pub fn offer(frame: &MainFrame) -> bool {
    let (config_dir, portable) = {
        let state = frame.state.borrow();
        (state.config_dir.clone(), state.portable)
    };
    if !portable {
        return false;
    }

    let copied = offer_config_copy(frame, &config_dir);
    // After a copy the site list has been replaced, so the keyring question is
    // asked against the sites that actually came across.
    offer_keyring_import(frame, &config_dir);
    copied
}

/// Offer to copy an installed copy's configuration into the portable folder.
fn offer_config_copy(frame: &MainFrame, config_dir: &Path) -> bool {
    let Some(source) = migration::standard_source_dir(config_dir) else {
        return false;
    };
    let candidates = migration::migration_candidates(&source);
    if candidates.is_empty() {
        return false;
    }

    let dialog = Dialog::builder(&frame.frame, TITLE)
        .with_size(520, 380)
        .with_style(DialogStyle::DefaultDialogStyle | DialogStyle::ResizeBorder)
        .build();

    let sizer = BoxSizer::builder(Orientation::Vertical).build();

    let intro = StaticText::builder(&dialog)
        .with_label(&format!(
            "Portkey Drop is installed on this computer as well. Its settings can be copied \
             into this portable copy so you start with your sites and preferences already in \
             place.\n\nThe installed copy is left exactly as it is.\n\nCopying from: {}",
            source.display()
        ))
        .build();
    sizer.add(&intro, 0, SizerFlag::Expand | SizerFlag::All, 8);

    // The label must sit immediately before the list: a screen reader on
    // Windows takes a list's name from the preceding sibling.
    let list_label = StaticText::builder(&dialog)
        .with_label("Copy these:")
        .build();
    sizer.add(&list_label, 0, SizerFlag::Left | SizerFlag::All, 6);

    let items = CheckListBox::builder(&dialog).build();
    items.set_name("Copy these");
    for (label, _) in &candidates {
        items.append(label);
    }
    for index in 0..candidates.len() {
        items.check(index as u32, true);
    }
    sizer.add(&items, 1, SizerFlag::Expand | SizerFlag::All, 6);

    let (copy, skip) = super::add_ok_cancel(&dialog, &sizer, "&Copy Selected");
    skip.set_label("&Not Now");
    copy.set_name("Copy Selected");
    skip.set_name("Not Now");

    dialog.set_sizer(sizer, true);
    items.set_focus();

    let accepted = dialog.show_modal() == ID_OK;
    let chosen: Vec<&str> = if accepted {
        candidates
            .iter()
            .enumerate()
            .filter(|(index, _)| items.is_checked(*index as u32))
            .map(|(_, (_, file_name))| *file_name)
            .collect()
    } else {
        Vec::new()
    };
    dialog.destroy();

    if chosen.is_empty() {
        return false;
    }

    match migration::migrate_files(&chosen, &source, config_dir) {
        Ok(copied) if copied.is_empty() => false,
        Ok(copied) => {
            frame.log(&format!(
                "Copied {} item{} from the installed copy.",
                copied.len(),
                if copied.len() == 1 { "" } else { "s" }
            ));
            true
        }
        Err(err) => {
            prompts::error(
                &frame.frame,
                "Could not copy the settings",
                &format!("{err}\n\nThis portable copy starts with its own fresh settings."),
            );
            false
        }
    }
}

/// Offer to lift saved passwords out of the system keyring into the vault.
///
/// A portable install stores passwords in `vault.enc` so they travel with the
/// data folder. Passwords saved by an installed copy are in the machine's
/// keyring instead, where nothing in portable mode would ever look for them --
/// so without this the sites arrive with every password blank.
fn offer_keyring_import(frame: &MainFrame, config_dir: &Path) {
    if migration::keyring_import_offered(config_dir) {
        return;
    }
    let waiting = frame
        .state
        .borrow()
        .sites
        .keyring_passwords_to_import()
        .len();
    if waiting == 0 {
        return;
    }

    let message = format!(
        "{waiting} saved password{} for these sites {} in this computer's keyring, which a \
         portable copy cannot read from another machine.\n\nCopy {} into this copy's encrypted \
         vault so they travel with the data folder?\n\nThe keyring entries are left in place.",
        if waiting == 1 { "" } else { "s" },
        if waiting == 1 { "is" } else { "are" },
        if waiting == 1 { "it" } else { "them" },
    );
    let accepted = prompts::confirm(&frame.frame, "Copy Saved Passwords", &message);

    if accepted {
        let imported = frame.state.borrow_mut().sites.import_keyring_passwords();
        match imported {
            Ok(count) => frame.log(&format!(
                "Copied {count} saved password{} into the portable vault.",
                if count == 1 { "" } else { "s" }
            )),
            Err(err) => prompts::error(
                &frame.frame,
                "Could not copy the passwords",
                &format!("{err}"),
            ),
        }
    }

    // Answered either way: asking again on every launch would be worse than
    // never asking.
    if let Err(err) = migration::mark_keyring_import_offered(config_dir) {
        log::warn!("could not record the keyring import answer: {err}");
    }
}
