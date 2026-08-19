//! Thin wrappers over the standard dialogs.
//!
//! Every prompt goes through here so wording, button choices, and the default
//! answer stay consistent — and so the destructive ones default to "no".

use wxdragon::prelude::*;

/// Show an informational message.
pub fn info(parent: &dyn WxWidget, caption: &str, message: &str) {
    MessageDialog::builder(parent, message, caption)
        .with_style(MessageDialogStyle::OK | MessageDialogStyle::IconInformation)
        .build()
        .show_modal();
}

/// Show an error message.
pub fn error(parent: &dyn WxWidget, caption: &str, message: &str) {
    MessageDialog::builder(parent, message, caption)
        .with_style(MessageDialogStyle::OK | MessageDialogStyle::IconError)
        .build()
        .show_modal();
}

/// Ask a yes/no question, defaulting to no.
pub fn confirm(parent: &dyn WxWidget, caption: &str, message: &str) -> bool {
    MessageDialog::builder(parent, message, caption)
        .with_style(MessageDialogStyle::YesNo | MessageDialogStyle::IconQuestion)
        .build()
        .show_modal()
        == ID_YES
}

/// Ask before something destructive, defaulting to no.
///
/// Separate from [`confirm`] so the warning icon is not forgotten on the
/// prompts that most need it.
pub fn confirm_destructive(parent: &dyn WxWidget, caption: &str, message: &str) -> bool {
    MessageDialog::builder(parent, message, caption)
        .with_style(MessageDialogStyle::YesNo | MessageDialogStyle::IconWarning)
        .build()
        .show_modal()
        == ID_YES
}

/// Ask for a line of text.
pub fn ask_text(
    parent: &dyn WxWidget,
    caption: &str,
    message: &str,
    initial: &str,
) -> Option<String> {
    let dialog = TextEntryDialog::builder(parent, message, caption)
        .with_default_value(initial)
        .build();
    if dialog.show_modal() != ID_OK {
        return None;
    }
    dialog
        .get_value()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

/// Ask for a password, with the text masked.
pub fn ask_password(parent: &dyn WxWidget, caption: &str, message: &str) -> Option<String> {
    let dialog = TextEntryDialog::builder(parent, message, caption)
        .password()
        .build();
    if dialog.show_modal() != ID_OK {
        return None;
    }
    dialog.get_value()
}

/// Ask the user to pick a directory.
pub fn ask_directory(parent: &dyn WxWidget, caption: &str, initial: &str) -> Option<String> {
    let dialog = DirDialog::builder(parent, caption, initial).build();
    if dialog.show_modal() != ID_OK {
        return None;
    }
    dialog.get_path().filter(|path| !path.is_empty())
}

/// Ask the user to pick a file to open.
pub fn ask_open_file(
    parent: &dyn WxWidget,
    caption: &str,
    wildcard: &str,
    initial_dir: &str,
) -> Option<String> {
    let dialog = FileDialog::builder(parent)
        .with_message(caption)
        .with_wildcard(wildcard)
        .with_default_dir(initial_dir)
        .with_style(FileDialogStyle::Open | FileDialogStyle::FileMustExist)
        .build();
    if dialog.show_modal() != ID_OK {
        return None;
    }
    dialog.get_path().filter(|path| !path.is_empty())
}

/// Ask the user where to save a file.
pub fn ask_save_file(
    parent: &dyn WxWidget,
    caption: &str,
    wildcard: &str,
    default_name: &str,
) -> Option<String> {
    let dialog = FileDialog::builder(parent)
        .with_message(caption)
        .with_wildcard(wildcard)
        .with_default_file(default_name)
        .with_style(FileDialogStyle::Save | FileDialogStyle::OverwritePrompt)
        .build();
    if dialog.show_modal() != ID_OK {
        return None;
    }
    dialog.get_path().filter(|path| !path.is_empty())
}

/// The wording used when a transfer would replace something.
pub fn overwrite_message(name: &str, action: &str) -> String {
    format!("{name} already exists. Replace it with the {action} file?")
}

/// The wording used when deleting.
pub fn delete_message(names: &[String]) -> String {
    match names.len() {
        0 => "Nothing is selected.".to_string(),
        1 => format!("Delete {}? This cannot be undone.", names[0]),
        count => format!("Delete these {count} items? This cannot be undone."),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_overwrite_prompt_names_the_file_and_the_direction() {
        assert_eq!(
            overwrite_message("notes.txt", "downloaded"),
            "notes.txt already exists. Replace it with the downloaded file?"
        );
    }

    #[test]
    fn the_delete_prompt_says_how_many_and_that_it_is_final() {
        // Deleting is irreversible over a network; the wording has to say so.
        assert_eq!(
            delete_message(&["notes.txt".to_string()]),
            "Delete notes.txt? This cannot be undone."
        );
        assert_eq!(
            delete_message(&["a".to_string(), "b".to_string(), "c".to_string()]),
            "Delete these 3 items? This cannot be undone."
        );
    }

    #[test]
    fn deleting_nothing_says_so_rather_than_asking() {
        assert_eq!(delete_message(&[]), "Nothing is selected.");
    }
}
