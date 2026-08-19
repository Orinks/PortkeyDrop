//! Messages from background work back to the UI thread.
//!
//! Connecting, listing, and transferring all happen off the UI thread, and
//! wxWidgets objects may only be touched from the UI thread. Rather than
//! marshalling closures (which would have to be `Send`, and widgets are not),
//! background work posts one of these values down a channel and a timer on the
//! frame drains it.

use std::path::PathBuf;
use std::sync::mpsc::{Receiver, Sender};

use portkeydrop_core::protocols::RemoteFile;
use portkeydrop_core::updater::UpdateInfo;

/// Something that happened away from the UI thread.
#[derive(Debug)]
pub enum AppEvent {
    /// A connection attempt succeeded; the client is already stored.
    Connected { host: String, cwd: String },
    /// A connection attempt failed.
    ConnectFailed { message: String },
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
pub type EventSender = Sender<AppEvent>;

/// The receiving half, drained by the UI timer.
pub type EventReceiver = Receiver<AppEvent>;

/// Create a channel for background events.
pub fn channel() -> (EventSender, EventReceiver) {
    std::sync::mpsc::channel()
}

/// Send an event, ignoring a closed channel.
///
/// A closed channel means the window has gone; that is not an error worth
/// propagating out of a worker thread.
pub fn post(sender: &EventSender, event: AppEvent) {
    if sender.send(event).is_err() {
        log::debug!("dropping a background event: the window has closed");
    }
}

/// Drain every event currently waiting, without blocking.
pub fn drain(receiver: &EventReceiver) -> Vec<AppEvent> {
    receiver.try_iter().collect()
}

#[cfg(test)]
mod tests {
    use super::*;

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
}
