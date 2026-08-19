//! Importing sites from other FTP/SFTP clients.
//!
//! Pick a source, review what was found, tick the ones to keep. Nothing is
//! written until the user confirms, and existing sites are never replaced —
//! an import adds, it does not overwrite.

use std::cell::RefCell;
use std::rc::Rc;

use wxdragon::prelude::*;

use portkeydrop_core::importers::{self, ImportSource, ImportedSite};

use crate::ui::main_frame::MainFrame;
use crate::ui::prompts;

/// Window title.
pub const TITLE: &str = "Import Sites";

const ID_BROWSE: Id = 7300;
const ID_SCAN: Id = 7301;
const ID_SELECT_ALL: Id = 7302;
const ID_SELECT_NONE: Id = 7303;

/// Show the import dialog.
pub fn show(frame: &MainFrame) {
    let dialog = Dialog::builder(&frame.frame, TITLE)
        .with_size(640, 480)
        .with_style(DialogStyle::DefaultDialogStyle | DialogStyle::ResizeBorder)
        .build();

    let sizer = BoxSizer::builder(Orientation::Vertical).build();

    // Only sources with something to import are offered, plus "from file".
    let sources = importers::available_sources();
    let source_picker =
        super::add_labelled(&dialog, &sizer, "Import &from:", "Import from", |dialog| {
            Choice::builder(dialog).build()
        });
    for source in &sources {
        let suffix = if source.is_available() && *source != ImportSource::FromFile {
            " (found on this computer)"
        } else {
            ""
        };
        source_picker.append(&format!("{}{suffix}", source.label()));
    }
    if !sources.is_empty() {
        source_picker.set_selection(0);
    }
    let location = super::add_labelled(&dialog, &sizer, "&Location:", "Location", |dialog| {
        TextCtrl::builder(dialog).build()
    });

    let actions = BoxSizer::builder(Orientation::Horizontal).build();
    let browse = Button::builder(&dialog)
        .with_id(ID_BROWSE)
        .with_label("&Browse...")
        .build();
    let scan = Button::builder(&dialog)
        .with_id(ID_SCAN)
        .with_label("&Scan")
        .build();
    actions.add(&browse, 0, SizerFlag::All, 4);
    actions.add(&scan, 0, SizerFlag::All, 4);
    sizer.add_sizer(&actions, 0, SizerFlag::Left | SizerFlag::All, 4);

    let found_label = StaticText::builder(&dialog)
        .with_label("Sites found:")
        .build();
    sizer.add(&found_label, 0, SizerFlag::Left | SizerFlag::All, 6);

    let found = CheckListBox::builder(&dialog).build();
    found.set_name("Sites found");
    sizer.add(&found, 1, SizerFlag::Expand | SizerFlag::All, 6);

    let selection = BoxSizer::builder(Orientation::Horizontal).build();
    let select_all = Button::builder(&dialog)
        .with_id(ID_SELECT_ALL)
        .with_label("Select &All")
        .build();
    let select_none = Button::builder(&dialog)
        .with_id(ID_SELECT_NONE)
        .with_label("Select &None")
        .build();
    selection.add(&select_all, 0, SizerFlag::All, 4);
    selection.add(&select_none, 0, SizerFlag::All, 4);
    sizer.add_sizer(&selection, 0, SizerFlag::Left | SizerFlag::All, 4);

    let (import, _cancel) = super::add_ok_cancel(&dialog, &sizer, "&Import");
    import.enable(false);

    dialog.set_sizer(sizer, true);

    let discovered: Rc<RefCell<Vec<ImportedSite>>> = Rc::new(RefCell::new(Vec::new()));

    let selected_source = {
        let sources = sources.clone();
        move || -> Option<ImportSource> {
            let index = source_picker.get_selection()? as usize;
            sources.get(index).copied()
        }
    };

    // Show the default location for whichever source is picked.
    let update_location = {
        let selected_source = selected_source.clone();
        move || {
            if let Some(source) = selected_source() {
                location.set_value(&source.default_location().unwrap_or_default());
            }
        }
    };
    update_location();

    {
        let update_location = update_location.clone();
        source_picker.on_selection_changed(move |_| update_location());
    }

    {
        let selected_source = selected_source.clone();
        browse.on_click(move |_| {
            let start = location.get_value();
            let picked = match selected_source() {
                // Cyberduck keeps one file per bookmark, so a folder is what
                // the user wants to point at.
                Some(ImportSource::Cyberduck) => {
                    prompts::ask_directory(&dialog, "Choose a bookmarks folder", &start)
                }
                _ => prompts::ask_open_file(
                    &dialog,
                    "Choose a configuration file",
                    "Configuration files (*.xml;*.ini;*.duck)|*.xml;*.ini;*.duck|All files (*.*)|*.*",
                    &start,
                ),
            };
            if let Some(path) = picked {
                location.set_value(&path);
            }
        });
    }

    let scan_now = {
        let discovered = Rc::clone(&discovered);
        let selected_source = selected_source.clone();
        move || {
            let Some(source) = selected_source() else {
                return;
            };
            let raw = location.get_value().trim().to_string();
            // The registry sentinel is a label, not a path, so it is not passed
            // through as one.
            let path = (!raw.is_empty() && raw != importers::WINSCP_REGISTRY_SENTINEL)
                .then(|| std::path::PathBuf::from(&raw));

            match importers::load_from_source(source, path.as_deref()) {
                Ok(sites) => {
                    found.clear();
                    for site in &sites {
                        found.append(&describe(site));
                    }
                    for index in 0..sites.len() {
                        found.check(index as u32, true);
                    }
                    import.enable(!sites.is_empty());
                    if sites.is_empty() {
                        prompts::info(
                            &dialog,
                            "Nothing to import",
                            "No saved connections were found there.",
                        );
                    }
                    *discovered.borrow_mut() = sites;
                }
                Err(err) => {
                    found.clear();
                    discovered.borrow_mut().clear();
                    import.enable(false);
                    prompts::error(&dialog, "Could not read that", &err.to_string());
                }
            }
        }
    };

    {
        let scan_now = scan_now.clone();
        scan.on_click(move |_| scan_now());
    }

    {
        let discovered = Rc::clone(&discovered);
        select_all.on_click(move |_| {
            for index in 0..discovered.borrow().len() {
                found.check(index as u32, true);
            }
        });
    }

    {
        let discovered = Rc::clone(&discovered);
        select_none.on_click(move |_| {
            for index in 0..discovered.borrow().len() {
                found.check(index as u32, false);
            }
        });
    }

    // Scan straight away when the picked source has a known location, so the
    // common case needs no clicks at all.
    scan_now();

    source_picker.set_focus();
    if dialog.show_modal() == ID_OK {
        let chosen: Vec<ImportedSite> = discovered
            .borrow()
            .iter()
            .enumerate()
            .filter(|(index, _)| found.is_checked(*index as u32))
            .map(|(_, site)| site.clone())
            .collect();
        let imported = import_sites(frame, &chosen);
        frame.log(&format!(
            "{imported} site{} imported.",
            if imported == 1 { "" } else { "s" }
        ));
    }
    dialog.destroy();
}

/// One line describing a discovered site.
pub fn describe(site: &ImportedSite) -> String {
    let target = if site.username.is_empty() {
        site.host.clone()
    } else {
        format!("{}@{}", site.username, site.host)
    };
    let port = if site.port > 0 {
        format!(":{}", site.port)
    } else {
        String::new()
    };
    let password = if site.password.is_empty() {
        ""
    } else {
        ", password recovered"
    };
    format!("{} — {} {target}{port}{password}", site.name, site.protocol)
}

/// Add the chosen sites, returning how many were saved.
///
/// A name already in use gets a numbered suffix rather than replacing the
/// existing site: an import should never quietly overwrite a working
/// connection.
fn import_sites(frame: &MainFrame, sites: &[ImportedSite]) -> usize {
    let mut state = frame.state.borrow_mut();
    let mut imported = 0;
    for site in sites {
        let mut new_site = site.to_site();
        new_site.name = unique_name(&state.sites, &new_site.name);
        match state.sites.add(new_site) {
            Ok(()) => imported += 1,
            Err(err) => log::error!("could not import the site {}: {err}", site.name),
        }
    }
    imported
}

/// A site name not already taken.
fn unique_name(sites: &portkeydrop_core::sites::SiteManager, wanted: &str) -> String {
    let wanted = if wanted.trim().is_empty() {
        "Imported site"
    } else {
        wanted.trim()
    };
    if !sites.name_taken(wanted, None) {
        return wanted.to_string();
    }
    for counter in 2..1000 {
        let candidate = format!("{wanted} ({counter})");
        if !sites.name_taken(&candidate, None) {
            return candidate;
        }
    }
    wanted.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn site() -> ImportedSite {
        let mut site = ImportedSite::new("Work", "sftp", "sftp.example.com");
        site.username = "alice".into();
        site.port = 2222;
        site
    }

    #[test]
    fn a_discovered_site_is_described_by_name_protocol_and_target() {
        assert_eq!(describe(&site()), "Work — sftp alice@sftp.example.com:2222");
    }

    #[test]
    fn a_default_port_is_left_out_of_the_description() {
        let site = ImportedSite { port: 0, ..site() };
        assert_eq!(describe(&site), "Work — sftp alice@sftp.example.com");
    }

    #[test]
    fn a_site_without_a_username_is_described_by_host_alone() {
        let site = ImportedSite {
            username: String::new(),
            ..site()
        };
        assert!(describe(&site).contains("sftp.example.com"));
        assert!(!describe(&site).contains('@'));
    }

    #[test]
    fn a_recovered_password_is_called_out() {
        // Worth saying: it tells the user they will not have to retype it, and
        // that the other client was storing it recoverably.
        let site = ImportedSite {
            password: "hunter2".into(),
            ..site()
        };
        let text = describe(&site);
        assert!(text.contains("password recovered"));
        // The password itself must never appear in the list.
        assert!(!text.contains("hunter2"));
    }

    #[test]
    fn the_registry_sentinel_is_a_label_not_a_path() {
        // Passing it through as a path would try to open a file with that name.
        assert!(importers::WINSCP_REGISTRY_SENTINEL.starts_with("Registry "));
    }
}
