//! Key codes.
//!
//! The toolkit binding does not re-export wxWidgets' `wxKeyCode` values, so
//! they are declared here. Naming them matters for more than tidiness: a bare
//! `WXK_DELETE` in a `match` arm is not a constant but a fresh binding, which
//! matches *every* key — the tests below exist to keep that mistake from coming
//! back.

/// Backspace.
pub const BACK: i32 = 8;
/// Tab.
pub const TAB: i32 = 9;
/// Enter, on the main keyboard.
pub const RETURN: i32 = 13;
/// Escape.
pub const ESCAPE: i32 = 27;
/// Space.
pub const SPACE: i32 = 32;
/// Delete.
pub const DELETE: i32 = 127;

/// F1. The function keys run consecutively from here.
pub const F1: i32 = 340;
/// F2, used for rename.
pub const F2: i32 = F1 + 1;
/// F5, a common refresh key.
pub const F5: i32 = F1 + 4;
/// F6, used to cycle panes.
pub const F6: i32 = F1 + 5;
/// F10, used with Shift for the context menu.
pub const F10: i32 = F1 + 9;

/// Left arrow. The arrows run consecutively from here.
pub const LEFT: i32 = 314;
/// Up arrow.
pub const UP: i32 = LEFT + 1;
/// Right arrow.
pub const RIGHT: i32 = LEFT + 2;
/// Down arrow.
pub const DOWN: i32 = LEFT + 3;

/// `[`. Finder uses Command+[ for back; the same chord with Ctrl is used
/// on the other platforms so the help window can say Ctrl everywhere.
pub const OPEN_BRACKET: i32 = b'[' as i32;

/// Enter, on the numeric keypad.
pub const NUMPAD_ENTER: i32 = 385;

/// What a key in a file list should do.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ListCommand {
    /// Delete the selection.
    Delete,
    /// Rename the selection.
    Rename,
    /// Go to the parent directory.
    Parent,
}

/// Modifier keys on a file-list key event.
///
/// `cmd` is wxWidgets' command key: Command on macOS, Control on Windows
/// and Linux. Using that, rather than Alt on every platform, is what makes
/// Finder's Command+Up reach the same command as Explorer's Alt+Up.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct KeyMods {
    /// Option on macOS, Alt elsewhere.
    pub alt: bool,
    /// Command on macOS, Control elsewhere.
    pub cmd: bool,
}

/// Whether a key code means "activate this item".
///
/// Both Enter keys count: a numeric keypad's Enter reports a different code,
/// and a user who reaches for it should not find nothing happens.
pub fn is_enter(code: i32) -> bool {
    code == RETURN || code == NUMPAD_ENTER
}

/// The command a file-list key should run, if any.
///
/// Parent directory is several chords because each platform's file manager
/// teaches a different one: Backspace and Alt+Left/Up on Windows and Linux,
/// Command+Up and Command+[ on macOS. They must not be frame-wide accelerators
/// or they would fire inside the path bar — and Command+Up in a text field
/// is "go to the start of the document".
pub fn list_command(code: i32, mods: KeyMods) -> Option<ListCommand> {
    match (code, mods.alt, mods.cmd) {
        (DELETE, false, false) => Some(ListCommand::Delete),
        (F2, false, false) => Some(ListCommand::Rename),
        (BACK, false, false) => Some(ListCommand::Parent),
        (LEFT, true, false) | (UP, true, false) => Some(ListCommand::Parent),
        (UP, false, true) | (OPEN_BRACKET, false, true) => Some(ListCommand::Parent),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_editing_keys_have_their_wxwidgets_values() {
        assert_eq!(BACK, 8);
        assert_eq!(RETURN, 13);
        assert_eq!(ESCAPE, 27);
        assert_eq!(DELETE, 127);
    }

    #[test]
    fn the_function_keys_run_consecutively_from_f1() {
        assert_eq!(F1, 340);
        assert_eq!(F2, 341);
        assert_eq!(F5, 344);
        assert_eq!(F6, 345);
        assert_eq!(F10, 349);
    }

    #[test]
    fn the_arrow_keys_run_consecutively_from_left() {
        assert_eq!(LEFT, 314);
        assert_eq!(UP, 315);
        assert_eq!(RIGHT, 316);
        assert_eq!(DOWN, 317);
    }

    #[test]
    fn every_key_this_app_binds_is_distinct() {
        // Two keys sharing a value would silently merge two commands.
        let codes = [
            BACK,
            TAB,
            RETURN,
            ESCAPE,
            SPACE,
            DELETE,
            F2,
            F5,
            F6,
            F10,
            LEFT,
            UP,
            RIGHT,
            DOWN,
            OPEN_BRACKET,
            NUMPAD_ENTER,
        ];
        let mut sorted = codes.to_vec();
        sorted.sort_unstable();
        sorted.dedup();
        assert_eq!(sorted.len(), codes.len());
    }

    #[test]
    fn both_enter_keys_activate() {
        assert!(is_enter(RETURN));
        assert!(is_enter(NUMPAD_ENTER));
        assert!(!is_enter(SPACE));
        assert!(!is_enter(DELETE));
    }

    #[test]
    fn matching_on_these_constants_discriminates_between_keys() {
        // The bug this guards against: an unqualified name in a match arm is a
        // binding, not a constant, so the first arm swallows every key.
        fn classify(code: i32) -> &'static str {
            match code {
                DELETE => "delete",
                F2 => "rename",
                BACK => "parent",
                _ => "other",
            }
        }
        assert_eq!(classify(DELETE), "delete");
        assert_eq!(classify(F2), "rename");
        assert_eq!(classify(BACK), "parent");
        assert_eq!(classify(SPACE), "other");
    }

    fn none() -> KeyMods {
        KeyMods::default()
    }

    fn alt() -> KeyMods {
        KeyMods {
            alt: true,
            cmd: false,
        }
    }

    fn cmd() -> KeyMods {
        KeyMods {
            alt: false,
            cmd: true,
        }
    }

    #[test]
    fn the_file_list_keys_run_their_commands() {
        assert_eq!(list_command(DELETE, none()), Some(ListCommand::Delete));
        assert_eq!(list_command(F2, none()), Some(ListCommand::Rename));
        assert_eq!(list_command(BACK, none()), Some(ListCommand::Parent));
        assert_eq!(list_command(LEFT, alt()), Some(ListCommand::Parent));
        assert_eq!(list_command(UP, alt()), Some(ListCommand::Parent));
    }

    #[test]
    fn macos_parent_chords_use_the_command_key() {
        // Finder: Command+Up is enclosing folder, Command+[ is back.
        // wxWidgets reports that key as cmd, not alt.
        assert_eq!(list_command(UP, cmd()), Some(ListCommand::Parent));
        assert_eq!(list_command(OPEN_BRACKET, cmd()), Some(ListCommand::Parent));
        assert_eq!(OPEN_BRACKET, 91);
    }

    #[test]
    fn unmodified_arrows_stay_with_the_list() {
        // Left and Up without a modifier move the cursor; treating them as
        // parent would make the list unnavigable.
        assert_eq!(list_command(LEFT, none()), None);
        assert_eq!(list_command(UP, none()), None);
        assert_eq!(list_command(RIGHT, alt()), None);
        assert_eq!(list_command(DOWN, alt()), None);
        assert_eq!(list_command(BACK, alt()), None);
        assert_eq!(list_command(SPACE, none()), None);
    }

    #[test]
    fn command_left_is_not_parent() {
        // Command+Left is beginning-of-line in text and is not Finder's
        // enclosing-folder shortcut. Command+Backspace is Move to Trash.
        assert_eq!(list_command(LEFT, cmd()), None);
        assert_eq!(list_command(BACK, cmd()), None);
        assert_eq!(
            list_command(
                UP,
                KeyMods {
                    alt: true,
                    cmd: true
                }
            ),
            None
        );
    }
}
