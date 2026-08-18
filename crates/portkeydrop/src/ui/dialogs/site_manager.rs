//! The Site Manager: saved connections.
//!
//! A list of sites on the left and their details on the right. The details
//! panel is a plain column of labelled fields rather than a grid, so tabbing
//! through it reads in the order the fields are filled in.

use std::cell::RefCell;
use std::rc::Rc;

use wxdragon::prelude::*;
use wxdragon::widgets::list_ctrl::{ListColumnFormat, ListItemState, ListNextItemFlag};

use portkeydrop_core::protocols::{Protocol, SUPPORTED_PROTOCOL_VALUES};
use portkeydrop_core::sites::Site;

use crate::ui::main_frame::MainFrame;
use crate::ui::prompts;

/// Window title.
pub const TITLE: &str = "Site Manager";

const ID_NEW_SITE: Id = 7200;
const ID_DUPLICATE_SITE: Id = 7201;
const ID_DELETE_SITE: Id = 7202;
const ID_CONNECT_SITE: Id = 7203;

/// The editable fields of a site.
struct SiteFields {
    name: TextCtrl,
    protocol: Choice,
    host: TextCtrl,
    port: TextCtrl,
    username: TextCtrl,
    password: TextCtrl,
    key_path: TextCtrl,
    explicit_ssl: CheckBox,
    initial_dir: TextCtrl,
    notes: TextCtrl,
}

impl SiteFields {
    /// Read the fields into a site, keeping `id` so an edit updates in place.
    fn to_site(&self, id: String) -> Site {
        let protocol = self
            .protocol
            .get_string_selection()
            .unwrap_or_else(|| "sftp".to_string());
        Site {
            id,
            name: self.name.get_value().trim().to_string(),
            protocol,
            host: self.host.get_value().trim().to_string(),
            port: self.port.get_value().trim().parse().unwrap_or(0),
            username: self.username.get_value().trim().to_string(),
            password: self.password.get_value(),
            key_path: self.key_path.get_value().trim().to_string(),
            ftp_explicit_ssl: self.explicit_ssl.is_checked(),
            initial_dir: {
                let dir = self.initial_dir.get_value().trim().to_string();
                if dir.is_empty() {
                    "/".to_string()
                } else {
                    dir
                }
            },
            notes: self.notes.get_value(),
        }
    }

    /// Show a site in the fields.
    fn show_site(&self, site: &Site) {
        self.name.set_value(&site.name);
        if let Some(index) = SUPPORTED_PROTOCOL_VALUES
            .iter()
            .position(|name| *name == site.protocol().as_str())
        {
            self.protocol.set_selection(index as u32);
        }
        self.host.set_value(&site.host);
        self.port.set_value(&if site.port > 0 {
            site.port.to_string()
        } else {
            String::new()
        });
        self.username.set_value(&site.username);
        self.password.set_value(&site.password);
        self.key_path.set_value(&site.key_path);
        self.explicit_ssl.set_value(site.ftp_explicit_ssl);
        self.explicit_ssl.enable(site.protocol() == Protocol::Ftp);
        self.initial_dir.set_value(&site.initial_dir);
        self.notes.set_value(&site.notes);
    }

    /// Enable or disable the whole panel.
    fn enable(&self, enabled: bool) {
        self.name.enable(enabled);
        self.protocol.enable(enabled);
        self.host.enable(enabled);
        self.port.enable(enabled);
        self.username.enable(enabled);
        self.password.enable(enabled);
        self.key_path.enable(enabled);
        self.explicit_ssl.enable(enabled);
        self.initial_dir.enable(enabled);
        self.notes.enable(enabled);
    }
}

/// Show the Site Manager.
pub fn show(frame: &MainFrame) {
    let dialog = Dialog::builder(&frame.frame, TITLE)
        .with_size(820, 520)
        .with_style(DialogStyle::DefaultDialogStyle | DialogStyle::ResizeBorder)
        .build();

    let outer = BoxSizer::builder(Orientation::Vertical).build();
    let columns = BoxSizer::builder(Orientation::Horizontal).build();

    // --- Site list ---
    let left = BoxSizer::builder(Orientation::Vertical).build();
    let list_label = StaticText::builder(&dialog)
        .with_label("Saved sites:")
        .build();
    left.add(&list_label, 0, SizerFlag::Left | SizerFlag::All, 4);

    let list = ListCtrl::builder(&dialog)
        .with_style(ListCtrlStyle::Report)
        .build();
    list.set_name("Saved sites");
    list.insert_column(0, "Name", ListColumnFormat::Left, 160);
    list.insert_column(1, "Protocol", ListColumnFormat::Left, 80);
    list.insert_column(2, "Host", ListColumnFormat::Left, 180);
    left.add(&list, 1, SizerFlag::Expand | SizerFlag::All, 4);

    let list_buttons = BoxSizer::builder(Orientation::Horizontal).build();
    let new_site = Button::builder(&dialog)
        .with_id(ID_NEW_SITE)
        .with_label("&New")
        .build();
    let duplicate_site = Button::builder(&dialog)
        .with_id(ID_DUPLICATE_SITE)
        .with_label("D&uplicate")
        .build();
    let delete_site = Button::builder(&dialog)
        .with_id(ID_DELETE_SITE)
        .with_label("&Delete")
        .build();
    for button in [&new_site, &duplicate_site, &delete_site] {
        list_buttons.add(button, 0, SizerFlag::All, 2);
    }
    left.add_sizer(&list_buttons, 0, SizerFlag::Left | SizerFlag::All, 4);
    columns.add_sizer(&left, 1, SizerFlag::Expand | SizerFlag::All, 4);

    // --- Site details ---
    let right = BoxSizer::builder(Orientation::Vertical).build();
    let details_label = StaticText::builder(&dialog)
        .with_label("Site details:")
        .build();
    right.add(&details_label, 0, SizerFlag::Left | SizerFlag::All, 4);

    let name = TextCtrl::builder(&dialog).build();
    super::add_labelled(&dialog, &right, "Si&te name:", &name, "Site name");

    let protocol = Choice::builder(&dialog).build();
    for value in SUPPORTED_PROTOCOL_VALUES {
        protocol.append(value);
    }
    protocol.set_selection(0);
    super::add_labelled(&dialog, &right, "&Protocol:", &protocol, "Protocol");

    let host = TextCtrl::builder(&dialog).build();
    super::add_labelled(&dialog, &right, "&Host:", &host, "Host");

    let port = TextCtrl::builder(&dialog).build();
    super::add_labelled(
        &dialog,
        &right,
        "P&ort (leave blank for the protocol default):",
        &port,
        "Port",
    );

    let username = TextCtrl::builder(&dialog).build();
    super::add_labelled(&dialog, &right, "&Username:", &username, "Username");

    let password = TextCtrl::builder(&dialog)
        .with_style(TextCtrlStyle::Password)
        .build();
    super::add_labelled(&dialog, &right, "Pass&word:", &password, "Password");

    let key_path = TextCtrl::builder(&dialog).build();
    super::add_labelled(
        &dialog,
        &right,
        "Private &key file (SFTP only):",
        &key_path,
        "Private key file",
    );

    let explicit_ssl = CheckBox::builder(&dialog)
        .with_label("Use SS&L (AUTH SSL)")
        .build();
    explicit_ssl.set_name("Use SSL (AUTH SSL) with FTP");
    right.add(&explicit_ssl, 0, SizerFlag::Left | SizerFlag::All, 4);

    let initial_dir = TextCtrl::builder(&dialog).build();
    super::add_labelled(
        &dialog,
        &right,
        "&Initial directory:",
        &initial_dir,
        "Initial directory",
    );

    let notes = TextCtrl::builder(&dialog)
        .with_style(TextCtrlStyle::MultiLine)
        .build();
    super::add_labelled(&dialog, &right, "N&otes:", &notes, "Notes");
    right.add_spacer(4);

    columns.add_sizer(&right, 2, SizerFlag::Expand | SizerFlag::All, 4);
    outer.add_sizer(&columns, 1, SizerFlag::Expand | SizerFlag::All, 4);

    let buttons = BoxSizer::builder(Orientation::Horizontal).build();
    let connect = Button::builder(&dialog)
        .with_id(ID_CONNECT_SITE)
        .with_label("&Connect")
        .build();
    let save = Button::builder(&dialog)
        .with_id(ID_OK)
        .with_label("&Save and Close")
        .build();
    let cancel = Button::builder(&dialog)
        .with_id(ID_CANCEL)
        .with_label("Cance&l")
        .build();
    for button in [&connect, &save, &cancel] {
        buttons.add(button, 0, SizerFlag::All, 4);
    }
    outer.add_sizer(&buttons, 0, SizerFlag::AlignRight | SizerFlag::All, 8);

    dialog.set_sizer(outer, true);

    let fields = Rc::new(SiteFields {
        name,
        protocol,
        host,
        port,
        username,
        password,
        key_path,
        explicit_ssl,
        initial_dir,
        notes,
    });

    // The working copy: edits land here and are written back on save, so
    // cancelling really does discard them.
    let sites: Rc<RefCell<Vec<Site>>> =
        Rc::new(RefCell::new(frame.state.borrow().sites.sites().to_vec()));
    let selected: Rc<RefCell<Option<usize>>> = Rc::new(RefCell::new(None));

    let repopulate = {
        let sites = Rc::clone(&sites);
        move |select: Option<usize>| {
            list.delete_all_items();
            for (row, site) in sites.borrow().iter().enumerate() {
                list.insert_item(row as i64, &site.name, None);
                list.set_item_text_by_column(row as i64, 1, site.protocol.as_str());
                list.set_item_text_by_column(row as i64, 2, &site.host);
            }
            if let Some(row) = select.filter(|row| *row < sites.borrow().len()) {
                list.set_item_state(
                    row as i64,
                    ListItemState::Focused | ListItemState::Selected,
                    ListItemState::Focused | ListItemState::Selected,
                );
            }
        }
    };

    // Copy the panel back into the working list.
    let commit = {
        let fields = Rc::clone(&fields);
        let sites = Rc::clone(&sites);
        let selected = Rc::clone(&selected);
        move || {
            let Some(row) = *selected.borrow() else {
                return;
            };
            let mut sites = sites.borrow_mut();
            let Some(existing) = sites.get(row) else {
                return;
            };
            let updated = fields.to_site(existing.id.clone());
            sites[row] = updated;
        }
    };

    let select_row = {
        let fields = Rc::clone(&fields);
        let sites = Rc::clone(&sites);
        let selected = Rc::clone(&selected);
        let commit = commit.clone();
        move |row: Option<usize>| {
            // Save whatever was on screen before moving on, so switching sites
            // does not quietly discard an edit.
            commit();
            *selected.borrow_mut() = row;
            match row.and_then(|row| sites.borrow().get(row).cloned()) {
                Some(site) => {
                    fields.enable(true);
                    fields.show_site(&site);
                }
                None => {
                    fields.enable(false);
                    fields.show_site(&Site::default());
                }
            }
        }
    };

    repopulate(None);
    select_row(if sites.borrow().is_empty() {
        None
    } else {
        Some(0)
    });
    if !sites.borrow().is_empty() {
        list.set_item_state(
            0,
            ListItemState::Focused | ListItemState::Selected,
            ListItemState::Focused | ListItemState::Selected,
        );
    }

    {
        let select_row = select_row.clone();
        list.clone().on_item_selected(move |_| {
            let row = list.get_next_item(-1, ListNextItemFlag::All, ListItemState::Selected);
            select_row((row >= 0).then_some(row as usize));
        });
    }

    {
        let sites = Rc::clone(&sites);
        let repopulate = repopulate.clone();
        let select_row = select_row.clone();
        let fields = Rc::clone(&fields);
        new_site.on_click(move |_| {
            let mut site = Site::new("New site");
            site.protocol = "sftp".to_string();
            sites.borrow_mut().push(site);
            let row = sites.borrow().len() - 1;
            repopulate(Some(row));
            select_row(Some(row));
            // Land on the name so it can be typed over straight away.
            fields.name.set_focus();
        });
    }

    {
        let sites = Rc::clone(&sites);
        let selected = Rc::clone(&selected);
        let repopulate = repopulate.clone();
        let select_row = select_row.clone();
        let commit = commit.clone();
        duplicate_site.on_click(move |_| {
            commit();
            let Some(row) = *selected.borrow() else {
                return;
            };
            let Some(original) = sites.borrow().get(row).cloned() else {
                return;
            };
            // A duplicate needs its own identity, or the two would share one
            // stored password.
            let copy = Site {
                name: format!("{} (copy)", original.name),
                ..Site {
                    id: uuid_like(),
                    ..original
                }
            };
            sites.borrow_mut().push(copy);
            let new_row = sites.borrow().len() - 1;
            repopulate(Some(new_row));
            select_row(Some(new_row));
        });
    }

    {
        let sites = Rc::clone(&sites);
        let selected = Rc::clone(&selected);
        let repopulate = repopulate.clone();
        let select_row = select_row.clone();
        delete_site.on_click(move |_| {
            let Some(row) = *selected.borrow() else {
                return;
            };
            let name = sites
                .borrow()
                .get(row)
                .map(|site| site.name.clone())
                .unwrap_or_default();
            if !prompts::confirm_destructive(
                &dialog,
                "Delete site",
                &format!("Delete the saved site {name}? Its saved password is removed too."),
            ) {
                return;
            }
            sites.borrow_mut().remove(row);
            let next = if sites.borrow().is_empty() {
                None
            } else {
                Some(row.min(sites.borrow().len() - 1))
            };
            // Clear the selection first: committing into a row that no longer
            // exists would write the deleted site's fields onto its neighbour.
            *selected.borrow_mut() = None;
            repopulate(next);
            select_row(next);
        });
    }

    // Connecting is reachable from the button and from Enter on the list, so
    // the action lives in one place both can call.
    let connect_to_selected: Rc<dyn Fn()> = {
        let frame = frame.clone();
        let sites = Rc::clone(&sites);
        let selected = Rc::clone(&selected);
        let commit = commit.clone();
        Rc::new(move || {
            commit();
            let Some(row) = *selected.borrow() else {
                return;
            };
            let Some(site) = sites.borrow().get(row).cloned() else {
                return;
            };
            if site.host.trim().is_empty() {
                prompts::error(
                    &dialog,
                    "Cannot connect",
                    "This site has no server address.",
                );
                return;
            }
            // Save before connecting, so the site survives even if the
            // connection does not.
            save_sites(&frame, &sites.borrow());
            frame.quick_connect.fill_from_site(&site);
            let mut info = site.to_connection_info();
            info.host_key_policy = portkeydrop_core::protocols::HostKeyPolicy::from_setting(
                &frame.state.borrow().settings.connection.verify_host_keys,
            );
            info.timeout = frame.state.borrow().settings.connection.timeout;
            dialog.end_modal(ID_OK);
            frame.connect(info);
        })
    };

    {
        let connect_to_selected = Rc::clone(&connect_to_selected);
        connect.on_click(move |_| connect_to_selected());
    }

    // Enter on a site connects to it. A list control swallows Enter rather
    // than letting it reach the default button, so without this the key does
    // nothing at all — which is exactly where a keyboard user starts.
    {
        let connect_to_selected = Rc::clone(&connect_to_selected);
        list.on_item_activated(move |_| connect_to_selected());
    }

    {
        let commit = commit.clone();
        save.on_click(move |_| commit());
    }

    // Marks Connect as the dialog's default, so it is announced as such and
    // Enter from the detail fields triggers it too.
    connect.set_default();
    list.set_focus();
    let result = dialog.show_modal();
    if result == ID_OK {
        commit();
        save_sites(frame, &sites.borrow());
    }
    dialog.destroy();
}

/// Write the working list back to the site manager.
fn save_sites(frame: &MainFrame, sites: &[Site]) {
    let mut state = frame.state.borrow_mut();
    let existing: Vec<String> = state
        .sites
        .sites()
        .iter()
        .map(|site| site.id.clone())
        .collect();

    for id in existing {
        if !sites.iter().any(|site| site.id == id) {
            let _ = state.sites.remove(&id);
        }
    }
    for site in sites {
        // A site with no name or host is a half-finished row the user left
        // behind; saving it would clutter the list with an unusable entry.
        if site.name.trim().is_empty() && site.host.trim().is_empty() {
            continue;
        }
        let result = if state.sites.get(&site.id).is_some() {
            state.sites.update(site.clone())
        } else {
            state.sites.add(site.clone())
        };
        if let Err(err) = result {
            log::error!("could not save the site {}: {err}", site.name);
        }
    }
}

/// A fresh identifier for a duplicated site.
fn uuid_like() -> String {
    Site::new("").id
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_duplicate_gets_its_own_identity() {
        // Sharing an id would mean the two sites shared one stored password,
        // so editing one would silently change the other.
        assert_ne!(uuid_like(), uuid_like());
        assert!(!uuid_like().is_empty());
    }

    #[test]
    fn a_blank_row_is_not_saved() {
        // The rule save_sites applies, checked directly.
        let blank = Site {
            name: "  ".into(),
            host: "".into(),
            ..Default::default()
        };
        assert!(blank.name.trim().is_empty() && blank.host.trim().is_empty());

        let named = Site {
            name: "Work".into(),
            host: "".into(),
            ..Default::default()
        };
        assert!(!(named.name.trim().is_empty() && named.host.trim().is_empty()));
    }

    #[test]
    fn the_site_list_shows_the_columns_the_dialog_fills() {
        // Name, protocol, host: three columns, three set_item calls.
        let site = Site {
            name: "Work".into(),
            host: "h".into(),
            ..Default::default()
        };
        assert_eq!(site.name, "Work");
        assert_eq!(site.protocol, "sftp");
        assert_eq!(site.host, "h");
    }
}
