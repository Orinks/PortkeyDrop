//! The app's dialogs.
//!
//! Each is built the same way: a vertical sizer of labelled controls ending in
//! OK/Cancel, every control given an accessible name, and the initial focus put
//! on the first thing the user will want to change.

pub mod host_key;
pub mod import;
pub mod migration;
pub mod properties;
pub mod settings;
pub mod site_manager;
pub mod soundpacks;
pub mod transfer_queue;
pub mod update;

use wxdragon::prelude::*;

/// Show a read-only text window, sized to be readable and scrollable.
///
/// Used for About, Keyboard Shortcuts, and release notes: content the user
/// reads rather than edits. The text control is focusable and read-only so a
/// screen reader can review it line by line.
pub fn show_text_window(parent: &dyn WxWidget, caption: &str, body: &str) {
    let dialog = Dialog::builder(parent, caption)
        .with_size(560, 420)
        .with_style(DialogStyle::DefaultDialogStyle | DialogStyle::ResizeBorder)
        .build();

    let sizer = BoxSizer::builder(Orientation::Vertical).build();
    let text = TextCtrl::builder(&dialog)
        .with_style(TextCtrlStyle::MultiLine | TextCtrlStyle::ReadOnly | TextCtrlStyle::DontWrap)
        .build();
    text.set_value(body);
    text.set_name(caption);
    sizer.add(&text, 1, SizerFlag::Expand | SizerFlag::All, 8);

    let close = Button::builder(&dialog)
        .with_id(ID_OK)
        .with_label("&Close")
        .build();
    sizer.add(&close, 0, SizerFlag::AlignRight | SizerFlag::All, 8);

    dialog.set_sizer(sizer, true);
    // Focus the text, not the button: the point of this window is to read it.
    text.set_focus();
    dialog.show_modal();
    dialog.destroy();
}

/// Add a labelled control to a sizer, wiring the label to the control's name.
///
/// The control is built by the closure rather than passed in, so its label is
/// always created first. On Windows a screen reader takes a control's name from
/// the preceding sibling in creation order, so building the control first pairs
/// it with the *previous* field's label -- and leaves the first control in a
/// dialog with no label at all. Taking a closure makes that ordering impossible
/// to get wrong. It is also what makes the Alt+letter mnemonic in `label` reach
/// the right control.
pub fn add_labelled<W: WxWidget>(
    parent: &Dialog,
    sizer: &BoxSizer,
    label: &str,
    accessible_name: &str,
    build: impl FnOnce(&Dialog) -> W,
) -> W {
    let static_text = StaticText::builder(parent).with_label(label).build();
    sizer.add(&static_text, 0, SizerFlag::Left | SizerFlag::Top, 8);
    let control = build(parent);
    control.set_name(accessible_name);
    sizer.add(&control, 0, SizerFlag::Expand | SizerFlag::All, 4);
    control
}

/// A standard OK / Cancel row.
pub fn add_ok_cancel(dialog: &Dialog, sizer: &BoxSizer, ok_label: &str) -> (Button, Button) {
    let row = BoxSizer::builder(Orientation::Horizontal).build();
    let ok = Button::builder(dialog)
        .with_id(ID_OK)
        .with_label(ok_label)
        .build();
    let cancel = Button::builder(dialog)
        .with_id(ID_CANCEL)
        .with_label("&Cancel")
        .build();
    row.add(&ok, 0, SizerFlag::All, 4);
    row.add(&cancel, 0, SizerFlag::All, 4);
    sizer.add_sizer(&row, 0, SizerFlag::AlignRight | SizerFlag::All, 8);
    // Enter should do the obvious thing, and screen readers announce which
    // button is the default.
    ok.set_default();
    (ok, cancel)
}

#[cfg(test)]
mod tests {
    #[test]
    fn the_dialog_modules_are_all_present() {
        // A compile-time check that every dialog the menus reference exists.
        // Adding a menu item without its dialog would otherwise fail only when
        // the user clicked it.
        fn _assert_modules() {
            let _ = super::host_key::TITLE;
            let _ = super::import::TITLE;
            let _ = super::migration::TITLE;
            let _ = super::properties::TITLE;
            let _ = super::settings::TITLE;
            let _ = super::site_manager::TITLE;
            let _ = super::soundpacks::TITLE;
            let _ = super::transfer_queue::TITLE;
            let _ = super::update::TITLE;
        }
    }
}
