//! Menu and command identifiers, and the keyboard shortcuts bound to them.
//!
//! Keeping the accelerator alongside the label means the Keyboard Shortcuts
//! window is generated from the same table the menus are built from, so the two
//! cannot drift apart.

use wxdragon::id::Id;

/// Base for this app's ids, above wxWidgets' own reserved range.
const BASE: Id = 6000;

pub const ID_CONNECT: Id = BASE + 1;
pub const ID_DISCONNECT: Id = BASE + 2;
pub const ID_SITE_MANAGER: Id = BASE + 3;
pub const ID_QUICK_CONNECT: Id = BASE + 4;
pub const ID_SAVE_CONNECTION: Id = BASE + 5;
pub const ID_IMPORT_CONNECTIONS: Id = BASE + 6;

pub const ID_TRANSFER: Id = BASE + 10;
pub const ID_UPLOAD: Id = BASE + 11;
pub const ID_DOWNLOAD: Id = BASE + 12;
pub const ID_TRANSFER_QUEUE: Id = BASE + 13;
pub const ID_RETRY_LAST_FAILED: Id = BASE + 14;

pub const ID_REFRESH: Id = BASE + 20;
pub const ID_HOME_DIR: Id = BASE + 21;
pub const ID_PARENT_DIR: Id = BASE + 22;
pub const ID_SHOW_HIDDEN: Id = BASE + 23;
pub const ID_FILTER: Id = BASE + 24;
pub const ID_SORT_NAME: Id = BASE + 25;
pub const ID_SORT_SIZE: Id = BASE + 26;
pub const ID_SORT_TYPE: Id = BASE + 27;
pub const ID_SORT_MODIFIED: Id = BASE + 28;
pub const ID_TOGGLE_ACTIVITY_LOG: Id = BASE + 29;

pub const ID_DELETE: Id = BASE + 40;
pub const ID_RENAME: Id = BASE + 41;
pub const ID_MKDIR: Id = BASE + 42;
pub const ID_PROPERTIES: Id = BASE + 43;
pub const ID_PASTE: Id = BASE + 44;

pub const ID_SETTINGS: Id = BASE + 50;
pub const ID_SOUNDPACKS: Id = BASE + 51;
pub const ID_CHECK_UPDATES: Id = BASE + 52;
pub const ID_KEYBOARD_SHORTCUTS: Id = BASE + 53;

pub const ID_SWITCH_PANE_FOCUS: Id = BASE + 60;
pub const ID_FOCUS_LOCAL_PANE: Id = BASE + 61;
pub const ID_FOCUS_REMOTE_PANE: Id = BASE + 62;
pub const ID_FOCUS_ACTIVITY_LOG: Id = BASE + 63;
pub const ID_FOCUS_ADDRESS_BAR: Id = BASE + 64;
pub const ID_CONNECT_FROM_BAR: Id = BASE + 65;

pub const ID_TRAY_SHOW: Id = BASE + 70;
pub const ID_TRAY_QUEUE: Id = BASE + 71;
pub const ID_TRAY_UPDATES: Id = BASE + 72;

/// How a shortcut reaches its command.
///
/// Recorded so the audit test can tell "deliberately handled by a control"
/// apart from "nobody bound this at all" — the mistake that left F6 and the
/// pane-focus keys dead while the help window still advertised them.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Binding {
    /// A menu item carries the accelerator, so wxWidgets registers it
    /// frame-wide and the command is also discoverable by browsing the menus.
    Menu(Id),
    /// A control handles the key itself. Frame-wide accelerators are wrong for
    /// these: Delete and F2 as menubar accelerators would fire inside every
    /// text field in the window.
    Control,
    /// A dialog handles the key while it is open.
    Dialog,
}

/// One entry in the keyboard shortcut reference.
pub struct Shortcut {
    /// Section heading in the Keyboard Shortcuts window.
    pub section: &'static str,
    /// The key combination as the user types it.
    pub keys: &'static str,
    /// What it does.
    pub description: &'static str,
    /// Where the key is actually handled.
    pub binding: Binding,
}

/// The accelerator to put on a menu item, taken from the shortcut table.
///
/// Menus read their accelerators from here rather than repeating the string,
/// so the help window and the menus cannot disagree.
pub fn accelerator_for(command: Id) -> Option<&'static str> {
    SHORTCUTS
        .iter()
        .find(|shortcut| shortcut.binding == Binding::Menu(command))
        .map(|shortcut| shortcut.keys)
}

/// A menu label with its accelerator from the shortcut table appended.
pub fn labelled(label: &str, command: Id) -> String {
    menu_label(label, accelerator_for(command))
}

pub const SHORTCUTS: &[Shortcut] = &[
    Shortcut {
        section: "Connection",
        keys: "Ctrl+N",
        description: "Focus the quick connect bar",
        binding: Binding::Menu(ID_QUICK_CONNECT),
    },
    Shortcut {
        section: "Connection",
        keys: "Enter",
        description: "Connect, from any quick connect field",
        binding: Binding::Control,
    },
    Shortcut {
        section: "Connection",
        keys: "Ctrl+Enter",
        description: "Connect using the quick connect bar, from anywhere",
        binding: Binding::Menu(ID_CONNECT_FROM_BAR),
    },
    Shortcut {
        section: "Connection",
        keys: "Escape",
        description: "Hide the quick connect bar while connected",
        binding: Binding::Control,
    },
    Shortcut {
        section: "Connection",
        keys: "Ctrl+S",
        description: "Site Manager",
        binding: Binding::Menu(ID_SITE_MANAGER),
    },
    Shortcut {
        section: "Navigation",
        keys: "F6",
        description: "Cycle between panes: local, remote, activity log",
        binding: Binding::Menu(ID_SWITCH_PANE_FOCUS),
    },
    Shortcut {
        section: "Navigation",
        keys: "Ctrl+1",
        description: "Focus local files",
        binding: Binding::Menu(ID_FOCUS_LOCAL_PANE),
    },
    Shortcut {
        section: "Navigation",
        keys: "Ctrl+2",
        description: "Focus remote files",
        binding: Binding::Menu(ID_FOCUS_REMOTE_PANE),
    },
    Shortcut {
        section: "Navigation",
        keys: "Ctrl+3",
        description: "Focus the activity log",
        binding: Binding::Menu(ID_FOCUS_ACTIVITY_LOG),
    },
    Shortcut {
        section: "Navigation",
        keys: "Ctrl+L",
        description: "Focus the path bar, or the quick connect bar",
        binding: Binding::Menu(ID_FOCUS_ADDRESS_BAR),
    },
    Shortcut {
        section: "Navigation",
        keys: "Enter",
        description: "Open the selected directory",
        binding: Binding::Control,
    },
    Shortcut {
        section: "Navigation",
        keys: "Backspace",
        description: "Go to the parent directory",
        binding: Binding::Control,
    },
    Shortcut {
        section: "Navigation",
        keys: "Alt+Left",
        description: "Go to the parent directory",
        binding: Binding::Control,
    },
    Shortcut {
        section: "Navigation",
        keys: "Alt+Up",
        description: "Go to the parent directory",
        binding: Binding::Control,
    },
    Shortcut {
        section: "Navigation",
        keys: "Ctrl+Up",
        description: "Go to the parent directory",
        binding: Binding::Control,
    },
    Shortcut {
        section: "Navigation",
        keys: "Ctrl+[",
        description: "Go to the parent directory",
        binding: Binding::Control,
    },
    Shortcut {
        section: "Navigation",
        keys: "Ctrl+H",
        description: "Go to the home directory",
        binding: Binding::Menu(ID_HOME_DIR),
    },
    Shortcut {
        section: "Transfers",
        keys: "Ctrl+T",
        description: "Transfer the selection: upload from local, download from remote",
        binding: Binding::Menu(ID_TRANSFER),
    },
    Shortcut {
        section: "Transfers",
        keys: "Ctrl+U",
        description: "Upload the selected local items",
        binding: Binding::Menu(ID_UPLOAD),
    },
    Shortcut {
        section: "Transfers",
        keys: "Ctrl+D",
        description: "Download the selected remote items",
        binding: Binding::Menu(ID_DOWNLOAD),
    },
    Shortcut {
        section: "Transfers",
        keys: "Ctrl+V",
        description: "Paste files from the clipboard into the focused pane",
        binding: Binding::Menu(ID_PASTE),
    },
    Shortcut {
        section: "Transfers",
        keys: "Ctrl+Shift+T",
        description: "Show the transfer queue",
        binding: Binding::Menu(ID_TRANSFER_QUEUE),
    },
    Shortcut {
        section: "File operations",
        keys: "Delete",
        description: "Delete the selection",
        binding: Binding::Control,
    },
    Shortcut {
        section: "File operations",
        keys: "F2",
        description: "Rename the selection",
        binding: Binding::Control,
    },
    Shortcut {
        section: "File operations",
        keys: "Ctrl+Shift+N",
        description: "New directory",
        binding: Binding::Menu(ID_MKDIR),
    },
    Shortcut {
        section: "File operations",
        keys: "Ctrl+I",
        description: "File properties",
        binding: Binding::Menu(ID_PROPERTIES),
    },
    Shortcut {
        section: "File operations",
        keys: "Ctrl+R",
        description: "Refresh the active pane",
        binding: Binding::Menu(ID_REFRESH),
    },
    Shortcut {
        section: "File operations",
        keys: "Ctrl+F",
        description: "Filter the file list",
        binding: Binding::Menu(ID_FILTER),
    },
    Shortcut {
        section: "File operations",
        keys: "Shift+F10",
        description: "Context menu",
        binding: Binding::Control,
    },
];

/// The Keyboard Shortcuts window's text, grouped by section.
pub fn shortcuts_text() -> String {
    let mut out = String::new();
    let mut current_section = "";
    for shortcut in SHORTCUTS {
        if shortcut.section != current_section {
            if !out.is_empty() {
                out.push('\n');
            }
            out.push_str(shortcut.section);
            out.push('\n');
            current_section = shortcut.section;
        }
        out.push_str(&format!(
            "  {:<16}{}\n",
            shortcut.keys, shortcut.description
        ));
    }
    out
}

/// A menu label with its accelerator appended, as wxWidgets expects.
pub fn menu_label(label: &str, accelerator: Option<&str>) -> String {
    match accelerator {
        Some(keys) => format!("{label}\t{keys}"),
        None => label.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashSet;

    #[test]
    fn every_command_id_is_distinct() {
        // A duplicate would silently route one menu item to another's handler.
        let ids = [
            ID_CONNECT,
            ID_DISCONNECT,
            ID_SITE_MANAGER,
            ID_QUICK_CONNECT,
            ID_SAVE_CONNECTION,
            ID_IMPORT_CONNECTIONS,
            ID_TRANSFER,
            ID_UPLOAD,
            ID_DOWNLOAD,
            ID_TRANSFER_QUEUE,
            ID_RETRY_LAST_FAILED,
            ID_REFRESH,
            ID_HOME_DIR,
            ID_PARENT_DIR,
            ID_SHOW_HIDDEN,
            ID_FILTER,
            ID_SORT_NAME,
            ID_SORT_SIZE,
            ID_SORT_TYPE,
            ID_SORT_MODIFIED,
            ID_TOGGLE_ACTIVITY_LOG,
            ID_DELETE,
            ID_RENAME,
            ID_MKDIR,
            ID_PROPERTIES,
            ID_PASTE,
            ID_SETTINGS,
            ID_SOUNDPACKS,
            ID_CHECK_UPDATES,
            ID_KEYBOARD_SHORTCUTS,
            ID_SWITCH_PANE_FOCUS,
            ID_FOCUS_LOCAL_PANE,
            ID_FOCUS_REMOTE_PANE,
            ID_FOCUS_ACTIVITY_LOG,
            ID_FOCUS_ADDRESS_BAR,
            ID_CONNECT_FROM_BAR,
            ID_TRAY_SHOW,
            ID_TRAY_QUEUE,
            ID_TRAY_UPDATES,
        ];
        let unique: HashSet<i32> = ids.iter().copied().collect();
        assert_eq!(unique.len(), ids.len(), "duplicate command id");
    }

    #[test]
    fn command_ids_sit_above_the_reserved_range() {
        // wxWidgets reserves the low ids for its own stock items.
        const { assert!(ID_CONNECT > wxdragon::id::ID_HIGHEST) };
    }

    #[test]
    fn the_shortcut_reference_covers_every_documented_group() {
        let text = shortcuts_text();
        for section in ["Connection", "Navigation", "Transfers", "File operations"] {
            assert!(text.contains(section), "missing section {section}");
        }
    }

    #[test]
    fn the_shortcut_reference_lists_the_transfer_keys() {
        let text = shortcuts_text();
        assert!(text.contains("Ctrl+T"));
        assert!(text.contains("Ctrl+U"));
        assert!(text.contains("Ctrl+D"));
        assert!(text.contains("Ctrl+Shift+T"));
    }

    #[test]
    fn each_shortcut_appears_under_its_own_section_once() {
        let text = shortcuts_text();
        assert_eq!(text.matches("Navigation\n").count(), 1);
        // Enter is listed under both Connection and Navigation, which is
        // intentional: it does different things in each context.
        assert_eq!(
            SHORTCUTS.iter().filter(|item| item.keys == "Enter").count(),
            2
        );
    }

    #[test]
    fn every_shortcut_entry_is_filled_in() {
        for shortcut in SHORTCUTS {
            assert!(!shortcut.keys.is_empty());
            assert!(!shortcut.description.is_empty());
            assert!(!shortcut.section.is_empty());
        }
    }

    #[test]
    fn every_menu_bound_shortcut_resolves_to_its_accelerator() {
        // The regression this guards: the help window advertised F6 and the
        // pane-focus keys while no menu item carried them, so they did nothing.
        for shortcut in SHORTCUTS {
            if let Binding::Menu(command) = shortcut.binding {
                assert_eq!(
                    accelerator_for(command),
                    Some(shortcut.keys),
                    "{} is advertised but no menu item claims it",
                    shortcut.keys
                );
            }
        }
    }

    #[test]
    fn the_navigation_keys_are_menu_bound() {
        // These are the ones that silently went missing. A menu item is what
        // makes wxWidgets register the accelerator frame-wide.
        for keys in ["F6", "Ctrl+1", "Ctrl+2", "Ctrl+3", "Ctrl+L", "Ctrl+Enter"] {
            let shortcut = SHORTCUTS
                .iter()
                .find(|shortcut| shortcut.keys == keys)
                .unwrap_or_else(|| panic!("{keys} is not in the shortcut table"));
            assert!(
                matches!(shortcut.binding, Binding::Menu(_)),
                "{keys} must be on a menu item to work frame-wide"
            );
        }
    }

    #[test]
    fn keys_that_must_not_be_frame_wide_are_control_bound() {
        // Delete and F2 as menubar accelerators would fire inside every text
        // field in the window, so they belong to the file lists.
        for keys in [
            "Delete",
            "F2",
            "Backspace",
            "Alt+Left",
            "Alt+Up",
            "Ctrl+Up",
            "Ctrl+[",
            "Escape",
            "Shift+F10",
        ] {
            let shortcut = SHORTCUTS
                .iter()
                .find(|shortcut| shortcut.keys == keys)
                .unwrap();
            assert_eq!(
                shortcut.binding,
                Binding::Control,
                "{keys} must be handled by a control, not the menubar"
            );
        }
    }

    #[test]
    fn one_command_does_not_claim_two_accelerators() {
        let mut commands: Vec<Id> = SHORTCUTS
            .iter()
            .filter_map(|shortcut| match shortcut.binding {
                Binding::Menu(command) => Some(command),
                _ => None,
            })
            .collect();
        let total = commands.len();
        commands.sort_unstable();
        commands.dedup();
        assert_eq!(commands.len(), total, "a command has two accelerators");
    }

    #[test]
    fn menu_labels_pull_their_accelerator_from_the_table() {
        assert_eq!(labelled("&Refresh", ID_REFRESH), "&Refresh	Ctrl+R");
        // A command with no advertised shortcut gets a bare label.
        assert_eq!(labelled("&Disconnect", ID_DISCONNECT), "&Disconnect");
    }

    #[test]
    fn menu_labels_carry_their_accelerator_after_a_tab() {
        assert_eq!(menu_label("&Refresh", Some("Ctrl+R")), "&Refresh\tCtrl+R");
        assert_eq!(menu_label("&Disconnect", None), "&Disconnect");
    }
}
