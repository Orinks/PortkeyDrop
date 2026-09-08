//! Messages from background work back to the UI thread.
//!
//! Connecting, listing, and transferring all happen off the UI thread, and
//! wxWidgets objects may only be touched from the UI thread. Rather than
//! marshalling closures (which would have to be `Send`, and widgets are not),
//! background work posts one of these values down a channel and a timer on the
//! frame drains it.

use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{Receiver, Sender};
use std::sync::Arc;

use portkeydrop_core::protocols::{HostKeyDecision, RemoteFile};
use portkeydrop_core::updater::UpdateInfo;

/// Something that happened away from the UI thread.
#[derive(Debug)]
pub enum AppEvent {
    /// A connection attempt succeeded; the client is already stored.
    Connected { host: String, cwd: String },
    /// A connection attempt failed.
    ConnectFailed { message: String },
    /// SFTP authentication is about to ask the SSH agent to sign, which can
    /// make an external agent (Bitwarden, a smartcard) pop a dialog behind the
    /// window. The UI starts the "waiting to connect" cue; `Connected` or
    /// `ConnectFailed` stops it.
    ConnectAwaitingAgent,
    /// A remote listing finished.
    RemoteListed {
        path: String,
        files: Vec<RemoteFile>,
    },
    /// A remote listing failed.
    RemoteListFailed { path: String, message: String },
    /// A remote directory change finished; the caller should list it.
    RemoteChangedDirectory { path: String },
    /// The transfer queue changed in some way.
    TransfersChanged,
    /// A remote file operation finished.
    RemoteOperationDone {
        message: String,
        sound: &'static str,
    },
    /// A remote file operation failed.
    RemoteOperationFailed {
        message: String,
        sound: &'static str,
    },
    /// An update check finished.
    UpdateCheckDone(Box<UpdateOutcome>),
    /// Bytes fetched so far for an update download; `total` is 0 when the
    /// server did not say how big the file is.
    UpdateDownloadProgress { downloaded: u64, total: u64 },
    /// An update download has stopped, one way or another.
    UpdateDownloadDone(Box<DownloadOutcome>),
    /// A command chosen from the notification area menu.
    ///
    /// Routed through the channel rather than run where it was raised: acting
    /// on one can destroy the tray icon, and doing that inside the icon's own
    /// event handler leaves wxWidgets returning into freed memory.
    TrayCommand(i32),
    /// A line for the activity log.
    Log { message: String },
    /// An unknown SSH host key; the worker is blocked on `reply`.
    ///
    /// The UI thread shows the dialog and sends the answer. Dropping this
    /// without answering is a rejection: that is the safe choice if the
    /// window has gone.
    HostKeyPrompt {
        host: String,
        algorithm: String,
        fingerprint: String,
        reply: Sender<HostKeyDecision>,
    },
}

/// The result of an update check.
#[derive(Debug)]
pub enum UpdateOutcome {
    /// An update is available. Carries everything needed to fetch it, so the
    /// offer can lead straight into a download instead of a dead end.
    Available(Box<UpdateInfo>),
    /// Nothing newer than the running build.
    UpToDate,
    /// The check could not be completed.
    Failed { message: String },
}

/// The result of downloading an update.
#[derive(Debug)]
pub enum DownloadOutcome {
    /// The file arrived and matched its published checksum.
    Ready { path: PathBuf, version: String },
    /// The user pressed Cancel.
    Cancelled,
    /// The download failed; the partial file has already been removed.
    Failed { message: String },
}

/// The sending half, handed to background threads.
#[derive(Clone)]
pub struct EventSender {
    sender: Sender<AppEvent>,
    transfers_pending: Arc<AtomicBool>,
}

/// The receiving half, drained by the UI timer.
pub struct EventReceiver {
    receiver: Receiver<AppEvent>,
    transfers_pending: Arc<AtomicBool>,
}

const EVENTS_PER_TICK: usize = 256;

/// Create a channel for background events.
pub fn channel() -> (EventSender, EventReceiver) {
    let (sender, receiver) = std::sync::mpsc::channel();
    let transfers_pending = Arc::new(AtomicBool::new(false));
    (
        EventSender {
            sender,
            transfers_pending: Arc::clone(&transfers_pending),
        },
        EventReceiver {
            receiver,
            transfers_pending,
        },
    )
}

/// Send an event, ignoring a closed channel.
///
/// A closed channel means the window has gone; that is not an error worth
/// propagating out of a worker thread.
pub fn post(sender: &EventSender, event: AppEvent) {
    // A transfer event requests a current snapshot, not a per-chunk update.
    let transfer_change = matches!(event, AppEvent::TransfersChanged);
    if transfer_change && sender.transfers_pending.swap(true, Ordering::AcqRel) {
        return;
    }
    if sender.sender.send(event).is_err() {
        if transfer_change {
            sender.transfers_pending.store(false, Ordering::Release);
        }
        log::debug!("dropping a background event: the window has closed");
    }
}

/// Take a bounded batch; yield to keyboard events even with busy producers.
pub fn drain(receiver: &EventReceiver) -> Vec<AppEvent> {
    receiver
        .receiver
        .try_iter()
        .take(EVENTS_PER_TICK)
        .inspect(|event| {
            if matches!(event, AppEvent::TransfersChanged) {
                // Reset before reading the UI snapshot, so concurrent changes
                // either appear in that snapshot or queue another notification.
                receiver.transfers_pending.store(false, Ordering::Release);
            }
        })
        .collect()
}

/// Tell the UI thread that SFTP auth is about to contact the SSH agent.
///
/// Fire-and-forget: unlike [`ask_host_key`] the worker does not wait for a
/// reply, it just carries on trying to authenticate.
pub fn notify_awaiting_agent(sender: &EventSender) {
    post(sender, AppEvent::ConnectAwaitingAgent);
}

/// Ask the UI thread what to do about an untrusted host key.
///
/// Posts a prompt and blocks until the UI answers. If the window has gone,
/// the channel is closed and the key is refused.
pub fn ask_host_key(
    sender: &EventSender,
    host: &str,
    algorithm: &str,
    fingerprint: &str,
) -> HostKeyDecision {
    let (reply, reply_rx) = std::sync::mpsc::channel();
    post(
        sender,
        AppEvent::HostKeyPrompt {
            host: host.to_string(),
            algorithm: algorithm.to_string(),
            fingerprint: fingerprint.to_string(),
            reply,
        },
    );
    reply_rx.recv().unwrap_or(HostKeyDecision::Reject)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn progress_notifications_coalesce_and_allow_later_wakeups() {
        let (sender, receiver) = channel();
        for _ in 0..10_000 {
            post(&sender, AppEvent::TransfersChanged);
        }
        post(&sender, AppEvent::TrayCommand(42));
        let batch = drain(&receiver);
        assert_eq!(batch.len(), 2);
        assert!(matches!(batch[0], AppEvent::TransfersChanged));
        assert!(matches!(batch[1], AppEvent::TrayCommand(42)));
        post(&sender, AppEvent::TransfersChanged);
        assert_eq!(drain(&receiver).len(), 1);
    }

    #[test]
    fn event_drain_yields_to_keyboard_and_preserves_remaining_order() {
        let (sender, receiver) = channel();
        for id in 0..10_000 {
            post(&sender, AppEvent::TrayCommand(id));
        }
        let first = drain(&receiver);
        assert!(!first.is_empty() && first.len() < 10_000);
        let mut next = 0;
        for event in first {
            assert!(matches!(event, AppEvent::TrayCommand(id) if id == next));
            next += 1;
        }
        loop {
            let batch = drain(&receiver);
            if batch.is_empty() {
                break;
            }
            for event in batch {
                assert!(matches!(event, AppEvent::TrayCommand(id) if id == next));
                next += 1;
            }
        }
        assert_eq!(next, 10_000);
    }

    #[test]
    fn events_arrive_in_the_order_they_were_sent() {
        let (sender, receiver) = channel();
        post(
            &sender,
            AppEvent::Log {
                message: "first".into(),
            },
        );
        post(
            &sender,
            AppEvent::Log {
                message: "second".into(),
            },
        );

        let events = drain(&receiver);
        assert_eq!(events.len(), 2);
        match (&events[0], &events[1]) {
            (AppEvent::Log { message: first }, AppEvent::Log { message: second }) => {
                assert_eq!(first, "first");
                assert_eq!(second, "second");
            }
            _ => panic!("unexpected events"),
        }
    }

    #[test]
    fn a_tray_command_survives_the_round_trip() {
        // The whole point of routing these through the channel is that they
        // run later, outside the tray icon's event handler.
        let (sender, receiver) = channel();
        post(&sender, AppEvent::TrayCommand(4242));
        assert!(matches!(
            drain(&receiver).first(),
            Some(AppEvent::TrayCommand(4242))
        ));
    }

    #[test]
    fn draining_an_empty_channel_yields_nothing_and_does_not_block() {
        let (_sender, receiver) = channel();
        assert!(drain(&receiver).is_empty());
    }

    #[test]
    fn draining_takes_everything_so_a_second_drain_is_empty() {
        let (sender, receiver) = channel();
        post(&sender, AppEvent::TransfersChanged);
        assert_eq!(drain(&receiver).len(), 1);
        assert!(drain(&receiver).is_empty());
    }

    #[test]
    fn posting_after_the_window_closed_is_not_an_error() {
        // A worker thread outliving the window must not panic on the way out.
        let (sender, receiver) = channel();
        drop(receiver);
        post(&sender, AppEvent::TransfersChanged);
    }

    #[test]
    fn events_can_be_sent_from_another_thread() {
        let (sender, receiver) = channel();
        std::thread::spawn(move || {
            post(
                &sender,
                AppEvent::Connected {
                    host: "h".into(),
                    cwd: "/".into(),
                },
            );
        })
        .join()
        .unwrap();

        let events = drain(&receiver);
        assert!(matches!(events.first(), Some(AppEvent::Connected { .. })));
    }

    #[test]
    fn an_agent_notice_is_posted_without_waiting_for_a_reply() {
        let (sender, receiver) = channel();
        notify_awaiting_agent(&sender);
        assert!(matches!(
            drain(&receiver).first(),
            Some(AppEvent::ConnectAwaitingAgent)
        ));
    }

    #[test]
    fn a_host_key_prompt_carries_the_offer_and_the_answer() {
        // The connect worker blocks on the reply; the UI thread is what
        // actually talks to the user. This is that round trip without a
        // display.
        let (sender, receiver) = channel();
        let worker = std::thread::spawn(move || {
            ask_host_key(&sender, "example.com", "ssh-ed25519", "SHA256:abc")
        });

        match receiver.receiver.recv().expect("the prompt is posted") {
            AppEvent::HostKeyPrompt {
                host,
                algorithm,
                fingerprint,
                reply,
            } => {
                assert_eq!(host, "example.com");
                assert_eq!(algorithm, "ssh-ed25519");
                assert_eq!(fingerprint, "SHA256:abc");
                reply
                    .send(HostKeyDecision::AcceptPermanent)
                    .expect("the worker is waiting");
            }
            other => panic!("expected a host key prompt, got {other:?}"),
        }

        assert_eq!(
            worker.join().expect("the worker finished"),
            HostKeyDecision::AcceptPermanent
        );
    }

    #[test]
    fn a_host_key_prompt_with_no_answer_is_a_rejection() {
        // Closing the window while the worker is waiting must not hang, and
        // must not accept the key.
        let (sender, receiver) = channel();
        let worker = std::thread::spawn(move || {
            ask_host_key(&sender, "example.com", "ssh-ed25519", "SHA256:abc")
        });

        let event = receiver.receiver.recv().expect("the prompt is posted");
        drop(event);

        assert_eq!(
            worker.join().expect("the worker finished"),
            HostKeyDecision::Reject
        );
    }
}
