//! Unknown SSH host key prompt.
//!
//! Reject is the default: Enter and Escape both refuse the key. The other two
//! buttons accept it for this session or remember it.

use portkeydrop_core::protocols::HostKeyDecision;
use wxdragon::prelude::*;

/// Window title, and the accessible name of the dialog.
pub const TITLE: &str = "Unknown Host Key";

/// Accept-once button id, above wxWidgets' reserved range.
const ID_ACCEPT_ONCE: i32 = 6101;
/// Accept-permanently button id.
const ID_ACCEPT_PERMANENT: i32 = 6102;

/// The line above the key details.
pub fn intro_text() -> &'static str {
    "The server identity could not be verified."
}

/// Host, algorithm, and fingerprint, one per line.
pub fn details_text(host: &str, algorithm: &str, fingerprint: &str) -> String {
    format!("Host: {host}\nKey type: {algorithm}\nFingerprint: {fingerprint}")
}

/// The question under the details.
pub fn question_text() -> &'static str {
    "Do you want to connect?"
}

/// Map a modal return code onto a decision.
///
/// Anything that is not one of the two accept buttons — Escape, the title-bar
/// close box, or Reject itself — is a refusal.
pub fn decision_from_code(code: i32) -> HostKeyDecision {
    if code == ID_ACCEPT_ONCE {
        HostKeyDecision::AcceptOnce
    } else if code == ID_ACCEPT_PERMANENT {
        HostKeyDecision::AcceptPermanent
    } else {
        HostKeyDecision::Reject
    }
}

/// Ask what to do about an untrusted host key.
pub fn show(
    parent: &dyn WxWidget,
    host: &str,
    algorithm: &str,
    fingerprint: &str,
) -> HostKeyDecision {
    let dialog = Dialog::builder(parent, TITLE)
        .with_size(520, 280)
        .with_style(DialogStyle::DefaultDialogStyle | DialogStyle::ResizeBorder)
        .build();

    let sizer = BoxSizer::builder(Orientation::Vertical).build();

    let intro = StaticText::builder(&dialog)
        .with_label(intro_text())
        .build();
    sizer.add(&intro, 0, SizerFlag::Expand | SizerFlag::All, 8);

    // This label must sit immediately before the details: a screen reader
    // takes the control's name from the preceding sibling.
    let details_label = StaticText::builder(&dialog)
        .with_label("Host key details:")
        .build();
    sizer.add(&details_label, 0, SizerFlag::Left | SizerFlag::All, 8);

    let details = TextCtrl::builder(&dialog)
        .with_style(TextCtrlStyle::MultiLine | TextCtrlStyle::ReadOnly)
        .build();
    details.set_value(&details_text(host, algorithm, fingerprint));
    details.set_name("Host key details");
    sizer.add(&details, 1, SizerFlag::Expand | SizerFlag::All, 8);

    let question = StaticText::builder(&dialog)
        .with_label(question_text())
        .build();
    sizer.add(&question, 0, SizerFlag::Expand | SizerFlag::All, 8);

    let buttons = BoxSizer::builder(Orientation::Horizontal).build();

    let accept_permanent = Button::builder(&dialog)
        .with_id(ID_ACCEPT_PERMANENT)
        .with_label("&Accept Permanently")
        .build();
    accept_permanent.set_name("Accept Permanently");
    let accept_once = Button::builder(&dialog)
        .with_id(ID_ACCEPT_ONCE)
        .with_label("Accept &Once")
        .build();
    accept_once.set_name("Accept Once");
    // ID_NO so the title-bar close box and Escape share Reject's meaning.
    let reject = Button::builder(&dialog)
        .with_id(ID_NO)
        .with_label("&Reject")
        .build();
    reject.set_name("Reject");

    buttons.add(&accept_permanent, 0, SizerFlag::All, 4);
    buttons.add(&accept_once, 0, SizerFlag::All, 4);
    buttons.add(&reject, 0, SizerFlag::All, 4);
    sizer.add_sizer(&buttons, 0, SizerFlag::AlignRight | SizerFlag::All, 8);

    // Custom ids do not close a modal dialog on their own.
    accept_permanent.on_click(move |_| dialog.end_modal(ID_ACCEPT_PERMANENT));
    accept_once.on_click(move |_| dialog.end_modal(ID_ACCEPT_ONCE));
    reject.on_click(move |_| dialog.end_modal(ID_NO));

    dialog.set_sizer(sizer, true);
    dialog.set_escape_id(ID_NO);
    // Reject is the safest default: Enter refuses without the user having to
    // find the button, and a screen reader announces it first.
    reject.set_default();
    reject.set_focus();

    let answer = dialog.show_modal();
    dialog.destroy();
    decision_from_code(answer)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_title_is_the_accessible_name() {
        // SetName on a dialog is not what screen readers read; the title is.
        assert_eq!(TITLE, "Unknown Host Key");
    }

    #[test]
    fn the_details_name_the_host_the_algorithm_and_the_fingerprint() {
        let text = details_text("example.com", "ssh-ed25519", "SHA256:abc");
        assert!(text.contains("example.com"), "{text}");
        assert!(text.contains("ssh-ed25519"), "{text}");
        assert!(text.contains("SHA256:abc"), "{text}");
        assert!(text.contains("Host:"), "{text}");
        assert!(text.contains("Key type:"), "{text}");
        assert!(text.contains("Fingerprint:"), "{text}");
    }

    #[test]
    fn accept_once_and_permanent_are_distinct_from_reject() {
        assert_eq!(
            decision_from_code(ID_ACCEPT_ONCE),
            HostKeyDecision::AcceptOnce
        );
        assert_eq!(
            decision_from_code(ID_ACCEPT_PERMANENT),
            HostKeyDecision::AcceptPermanent
        );
        assert_eq!(decision_from_code(ID_NO), HostKeyDecision::Reject);
        assert_eq!(decision_from_code(ID_CANCEL), HostKeyDecision::Reject);
        assert_eq!(decision_from_code(0), HostKeyDecision::Reject);
    }

    #[test]
    fn the_question_asks_whether_to_connect() {
        assert!(question_text().contains("connect"));
        assert!(intro_text().contains("verified"));
    }
}
