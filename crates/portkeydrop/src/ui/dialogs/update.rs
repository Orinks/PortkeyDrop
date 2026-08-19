//! The update-available offer and the wording around installing one.
//!
//! An update check that only reports a version is a dead end: the user is told
//! something newer exists and given a Close button. This module is the other
//! half — the offer with a Download button, and the messages shown while the
//! download runs and once it lands.
//!
//! The wording lives in free functions so it can be tested without a display.

use std::path::Path;

use pulldown_cmark::{Event, Options, Parser, Tag, TagEnd};

use portkeydrop_core::transfer::format_bytes;
use portkeydrop_core::updater::UpdateInfo;
use wxdragon::prelude::*;

pub const TITLE: &str = "Update Available";

/// Title for the progress window.
pub const DOWNLOAD_TITLE: &str = "Downloading Update";

/// Which release stream an update came from, as the user sees it.
pub fn channel_label(is_nightly: bool) -> &'static str {
    if is_nightly {
        "Nightly"
    } else {
        "Stable"
    }
}

/// Caption for the offer, naming the stream the update came from.
pub fn offer_caption(is_nightly: bool) -> String {
    format!("{} {TITLE}", channel_label(is_nightly))
}

/// The line above the release notes.
pub fn offer_header(current: &str, new: &str, is_nightly: bool) -> String {
    format!(
        "A new {} update is available.\nCurrent: {current}    Latest: {new}",
        channel_label(is_nightly).to_lowercase()
    )
}

/// End the current line, without stacking up blank ones.
fn end_line(text: &mut String) {
    if !text.is_empty() && !text.ends_with('\n') {
        text.push('\n');
    }
}

/// End the current block, leaving exactly one blank line behind it.
fn end_block(text: &mut String) {
    if text.is_empty() {
        return;
    }
    end_line(text);
    if !text.ends_with("\n\n") {
        text.push('\n');
    }
}

/// Render release notes written in markdown as plain text.
///
/// GitHub release bodies are markdown, and a screen reader reads the markup
/// out loud: "pound pound What's new", "star star fixed star star". Stripping
/// it and keeping the structure as blank lines and indented bullets is the
/// difference between notes that can be listened to and notes that cannot.
pub fn markdown_to_text(markdown: &str) -> String {
    let mut options = Options::empty();
    options.insert(Options::ENABLE_STRIKETHROUGH);
    options.insert(Options::ENABLE_TABLES);

    let mut text = String::new();
    // One entry per open list; `Some` counts an ordered list's next number.
    let mut lists: Vec<Option<u64>> = Vec::new();
    // Set between an item's bullet and its first text, so nothing gets a
    // chance to break the line in between.
    let mut fresh_item = false;

    for event in Parser::new_ext(markdown, options) {
        match event {
            Event::Start(Tag::Heading { .. } | Tag::CodeBlock(_)) => end_block(&mut text),
            Event::End(TagEnd::Heading(_) | TagEnd::CodeBlock) => end_block(&mut text),
            // A loose list wraps each item's text in a paragraph. Ending a
            // block there would strand the text under its own bullet, so
            // inside a list a paragraph is only ever a line.
            Event::Start(Tag::Paragraph) => {
                if lists.is_empty() {
                    end_block(&mut text);
                } else if !fresh_item {
                    end_line(&mut text);
                }
            }
            Event::End(TagEnd::Paragraph) => {
                if lists.is_empty() {
                    end_block(&mut text);
                } else {
                    end_line(&mut text);
                }
            }
            // A nested list belongs to the item above it, so it starts on the
            // next line rather than after a blank one.
            Event::Start(Tag::List(first)) => {
                if lists.is_empty() {
                    end_block(&mut text);
                } else {
                    end_line(&mut text);
                }
                lists.push(first);
                fresh_item = false;
            }
            Event::End(TagEnd::List(_)) => {
                lists.pop();
                if lists.is_empty() {
                    end_block(&mut text);
                } else {
                    end_line(&mut text);
                }
            }
            Event::Start(Tag::Item) => {
                end_line(&mut text);
                let indent = "  ".repeat(lists.len().saturating_sub(1));
                match lists.last_mut() {
                    Some(Some(number)) => {
                        text.push_str(&format!("{indent}{number}. "));
                        *number += 1;
                    }
                    _ => text.push_str(&format!("{indent}- ")),
                }
                fresh_item = true;
            }
            Event::End(TagEnd::Item) => {
                end_line(&mut text);
                fresh_item = false;
            }
            Event::Text(run) | Event::Code(run) => {
                text.push_str(&run);
                fresh_item = false;
            }
            Event::SoftBreak => text.push(' '),
            Event::HardBreak => end_line(&mut text),
            Event::Rule => {
                end_block(&mut text);
                text.push_str("---");
                end_block(&mut text);
            }
            _ => {}
        }
    }

    text.trim().to_string()
}

/// The release notes, or a stand-in when the release published none.
///
/// An empty read-only box gives a screen reader nothing to read, which is
/// indistinguishable from the notes having failed to load.
pub fn notes_body(notes: &str) -> String {
    let trimmed = markdown_to_text(notes);
    if trimmed.is_empty() {
        "No release notes were published for this version.".to_string()
    } else {
        trimmed
    }
}

/// How far along the download is, as a whole percentage.
///
/// `None` when the server did not send a length: there is nothing to be a
/// percentage of, and guessing would move the bar dishonestly.
pub fn percent_done(downloaded: u64, total: u64) -> Option<u8> {
    if total == 0 {
        return None;
    }
    let percent = downloaded.saturating_mul(100) / total;
    Some(percent.min(100) as u8)
}

/// The line under the progress bar.
pub fn progress_status(artifact: &str, downloaded: u64, total: u64) -> String {
    if total == 0 {
        format!(
            "Downloading {artifact}: {} so far",
            format_bytes(downloaded)
        )
    } else {
        format!(
            "Downloading {artifact}: {} of {}",
            format_bytes(downloaded),
            format_bytes(total)
        )
    }
}

/// What is spoken as the download passes each announcement step.
pub fn progress_announcement(percent: u8) -> String {
    format!("Downloading update, {percent} percent")
}

/// Asked once the download has been verified.
pub fn restart_question(version: &str) -> String {
    format!(
        "Portkey Drop {version} was downloaded and verified.\n\nThe app will close and reopen \
         to finish installing it. Continue?"
    )
}

/// Shown when this kind of install cannot replace itself.
///
/// The path matters more than the apology: without it the download is a file
/// the user cannot find.
pub fn manual_install_message(path: &Path) -> String {
    format!(
        "The update was downloaded, but this kind of install cannot update itself.\n\nThe new \
         version was saved to:\n{}\n\nInstall it, then start Portkey Drop again.",
        path.display()
    )
}

/// Shown when the update was fetched but could not be started.
pub fn apply_failed_message(path: &Path, error: &str) -> String {
    format!(
        "The update was downloaded but could not be started: {error}\n\nThe new version was \
         saved to:\n{}\n\nInstall it, then start Portkey Drop again.",
        path.display()
    )
}

/// Offer an update, returning whether the user asked to download it.
///
/// The release notes get the focus rather than the Download button: this is a
/// window to read before deciding, and Enter still activates the default
/// button from anywhere in the dialog.
pub fn show_offer(parent: &dyn WxWidget, current_version: &str, update: &UpdateInfo) -> bool {
    let dialog = Dialog::builder(parent, &offer_caption(update.is_nightly))
        .with_size(560, 460)
        .with_style(DialogStyle::DefaultDialogStyle | DialogStyle::ResizeBorder)
        .build();

    let sizer = BoxSizer::builder(Orientation::Vertical).build();

    let header = StaticText::builder(&dialog)
        .with_label(&offer_header(
            current_version,
            &update.version,
            update.is_nightly,
        ))
        .build();
    sizer.add(&header, 0, SizerFlag::Expand | SizerFlag::All, 8);

    // This label must sit immediately before the notes: a screen reader takes
    // the control's name from the preceding sibling.
    let notes_label = StaticText::builder(&dialog)
        .with_label("What's new:")
        .build();
    sizer.add(&notes_label, 0, SizerFlag::Left | SizerFlag::All, 8);

    let notes = TextCtrl::builder(&dialog)
        .with_style(TextCtrlStyle::MultiLine | TextCtrlStyle::ReadOnly)
        .build();
    notes.set_value(&notes_body(&update.release_notes));
    notes.set_name("What's new");
    sizer.add(&notes, 1, SizerFlag::Expand | SizerFlag::All, 8);

    super::add_ok_cancel(&dialog, &sizer, "&Download Update");

    dialog.set_sizer(sizer, true);
    // Escape has to close this even where the platform would not wire it up:
    // an offer the user cannot dismiss with Escape is a trap.
    dialog.set_escape_id(ID_CANCEL);
    notes.set_focus();
    notes.set_insertion_point(0);

    let answer = dialog.show_modal();
    dialog.destroy();
    answer == ID_OK
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_caption_and_header_name_the_release_stream() {
        // The user picks a channel in Settings; an offer that does not say
        // which one it came from cannot be judged against that choice.
        assert_eq!(offer_caption(true), "Nightly Update Available");
        assert_eq!(offer_caption(false), "Stable Update Available");

        let header = offer_header("0.6.0", "0.7.0", true);
        assert!(header.contains("nightly"), "{header}");
        assert!(
            header.contains("0.6.0") && header.contains("0.7.0"),
            "{header}"
        );
    }

    #[test]
    fn markdown_release_notes_are_flattened_for_reading() {
        // Raw markup is read out symbol by symbol, so the notes box gets text.
        let rendered = markdown_to_text("## What's new\n\nFixed **the** thing.");
        assert_eq!(rendered, "What's new\n\nFixed the thing.");
    }

    #[test]
    fn lists_keep_their_shape_without_their_markup() {
        let rendered = markdown_to_text("- one\n- two\n  - nested\n");
        assert_eq!(rendered, "- one\n- two\n  - nested");

        let ordered = markdown_to_text("1. first\n2. second\n");
        assert_eq!(ordered, "1. first\n2. second");
    }

    #[test]
    fn a_loose_list_reads_like_a_tight_one() {
        // Blank lines between items make pulldown-cmark wrap each in a
        // paragraph; the text still belongs on the bullet's own line.
        assert_eq!(markdown_to_text("- one\n\n- two\n"), "- one\n- two");
    }

    #[test]
    fn a_link_keeps_its_text_and_drops_its_url() {
        // The URL is not actionable in a read-only box and reads as noise.
        assert_eq!(
            markdown_to_text("See [the notes](https://example.com/x)."),
            "See the notes."
        );
    }

    #[test]
    fn missing_release_notes_still_give_the_reader_something() {
        assert_eq!(
            notes_body("   \n  "),
            "No release notes were published for this version."
        );
        assert_eq!(notes_body("  Fixed **the** thing.\n"), "Fixed the thing.");
    }

    #[test]
    fn progress_is_a_percentage_only_when_the_total_is_known() {
        assert_eq!(percent_done(0, 200), Some(0));
        assert_eq!(percent_done(50, 200), Some(25));
        assert_eq!(percent_done(200, 200), Some(100));
        // A server that sends more than it promised must not push the bar
        // past the end.
        assert_eq!(percent_done(400, 200), Some(100));
        assert_eq!(percent_done(400, 0), None);
    }

    #[test]
    fn the_status_line_reports_bytes_with_or_without_a_total() {
        assert_eq!(
            progress_status("portkeydrop.exe", 1024, 4096),
            "Downloading portkeydrop.exe: 1.0 KB of 4.0 KB"
        );
        assert_eq!(
            progress_status("portkeydrop.exe", 1024, 0),
            "Downloading portkeydrop.exe: 1.0 KB so far"
        );
    }

    #[test]
    fn a_manual_install_is_told_where_the_file_landed() {
        let message = manual_install_message(Path::new("/tmp/PortkeyDrop.tar.gz"));
        assert!(message.contains("PortkeyDrop.tar.gz"), "{message}");
        assert!(message.contains("cannot update itself"), "{message}");
    }

    #[test]
    fn a_failed_apply_reports_the_error_and_the_path() {
        let message = apply_failed_message(Path::new("/tmp/update.exe"), "access denied");
        assert!(message.contains("access denied"), "{message}");
        assert!(message.contains("update.exe"), "{message}");
    }

    #[test]
    fn the_restart_question_names_the_version_and_says_what_happens() {
        let question = restart_question("0.7.0");
        assert!(question.contains("0.7.0"), "{question}");
        assert!(question.contains("close and reopen"), "{question}");
    }
}
