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

/// Enter, on the numeric keypad.
pub const NUMPAD_ENTER: i32 = 385;

/// Whether a key code means "activate this item".
///
/// Both Enter keys count: a numeric keypad's Enter reports a different code,
/// and a user who reaches for it should not find nothing happens.
pub fn is_enter(code: i32) -> bool {
    code == RETURN || code == NUMPAD_ENTER
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
}
