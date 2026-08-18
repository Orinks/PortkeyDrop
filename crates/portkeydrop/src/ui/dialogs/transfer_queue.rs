//! The transfer queue.
//!
//! A disposable observer over the transfer service's job list. Closing it never
//! cancels anything — that is the whole reason the queue lives in the service
//! and not in this window.

use std::cell::RefCell;
use std::rc::Rc;

use wxdragon::prelude::*;
use wxdragon::widgets::list_ctrl::{ListColumnFormat, ListItemState, ListNextItemFlag};

use portkeydrop_core::transfer::Status;

use crate::ui::format::{queue_row, QUEUE_COLUMNS};
use crate::ui::main_frame::MainFrame;
use crate::ui::prompts;

/// Window title.
pub const TITLE: &str = "Transfer Queue";

/// How often the queue refreshes while it is open.
const REFRESH_MS: i32 = 250;

const ID_CANCEL_JOB: Id = 7100;
const ID_RETRY_JOB: Id = 7101;
const ID_REMOVE_JOB: Id = 7102;
const ID_CLEAR_FINISHED: Id = 7103;

/// Show the transfer queue.
pub fn show(frame: &MainFrame) {
    let dialog = Dialog::builder(&frame.frame, TITLE)
        .with_size(760, 420)
        .with_style(DialogStyle::DefaultDialogStyle | DialogStyle::ResizeBorder)
        .build();

    let sizer = BoxSizer::builder(Orientation::Vertical).build();

    let label = StaticText::builder(&dialog)
        .with_label("Transfers:")
        .build();
    sizer.add(&label, 0, SizerFlag::Left | SizerFlag::All, 8);

    let list = ListCtrl::builder(&dialog)
        .with_style(ListCtrlStyle::Report)
        .build();
    list.set_name("Transfers");
    for (index, (heading, width)) in QUEUE_COLUMNS.iter().enumerate() {
        list.insert_column(index as i64, heading, ListColumnFormat::Left, *width);
    }
    sizer.add(&list, 1, SizerFlag::Expand | SizerFlag::All, 8);

    let buttons = BoxSizer::builder(Orientation::Horizontal).build();
    let cancel_job = Button::builder(&dialog)
        .with_id(ID_CANCEL_JOB)
        .with_label("&Cancel")
        .build();
    let retry_job = Button::builder(&dialog)
        .with_id(ID_RETRY_JOB)
        .with_label("&Retry")
        .build();
    let remove_job = Button::builder(&dialog)
        .with_id(ID_REMOVE_JOB)
        .with_label("Re&move")
        .build();
    let clear_finished = Button::builder(&dialog)
        .with_id(ID_CLEAR_FINISHED)
        .with_label("Clear &Finished")
        .build();
    let close = Button::builder(&dialog)
        .with_id(ID_OK)
        .with_label("Cl&ose")
        .build();
    for button in [
        &cancel_job,
        &retry_job,
        &remove_job,
        &clear_finished,
        &close,
    ] {
        buttons.add(button, 0, SizerFlag::All, 4);
    }
    sizer.add_sizer(&buttons, 0, SizerFlag::AlignRight | SizerFlag::All, 8);

    // Close is the default: Enter in a queue of running transfers must not
    // cancel or remove anything by accident.
    close.set_default();
    dialog.set_sizer(sizer, true);

    // The job ids behind each row, so a button acts on the right job even as
    // the list is redrawn underneath it.
    let job_ids: Rc<RefCell<Vec<String>>> = Rc::new(RefCell::new(Vec::new()));

    let refresh = {
        let job_ids = Rc::clone(&job_ids);
        let frame = frame.clone();
        move || {
            let jobs = frame.state.borrow().transfers.jobs();
            let selected = selected_row(&list);

            list.delete_all_items();
            let mut ids = Vec::with_capacity(jobs.len());
            for (row, job) in jobs.iter().enumerate() {
                let cells = queue_row(job);
                list.insert_item(row as i64, &cells[0], None);
                for (column, value) in cells.iter().enumerate().skip(1) {
                    list.set_item_text_by_column(row as i64, column as i32, value);
                }
                ids.push(job.id.clone());
            }
            *job_ids.borrow_mut() = ids;

            // Keep the cursor where it was, clamped if the list shrank.
            if let Some(row) = selected {
                let row = row.min(jobs.len().saturating_sub(1));
                if !jobs.is_empty() {
                    list.set_item_state(
                        row as i64,
                        ListItemState::Focused | ListItemState::Selected,
                        ListItemState::Focused | ListItemState::Selected,
                    );
                }
            }
        }
    };
    refresh();

    // Poll rather than subscribe: the service's callback fires on a worker
    // thread, and widgets may only be touched from the UI thread.
    let timer = Timer::new(&dialog);
    {
        let refresh = refresh.clone();
        timer.on_tick(move |_| refresh());
    }
    timer.start(REFRESH_MS, false);

    let selected_job = {
        let job_ids = Rc::clone(&job_ids);
        move || -> Option<String> {
            let row = selected_row(&list)?;
            job_ids.borrow().get(row).cloned()
        }
    };

    {
        let frame = frame.clone();
        let selected_job = selected_job.clone();
        let refresh = refresh.clone();
        cancel_job.on_click(move |_| {
            if let Some(id) = selected_job() {
                frame.state.borrow().transfers.cancel(&id);
                refresh();
            }
        });
    }

    {
        let frame = frame.clone();
        let selected_job = selected_job.clone();
        let refresh = refresh.clone();
        retry_job.on_click(move |_| {
            let Some(id) = selected_job() else {
                return;
            };
            let Some(client) = frame.state.borrow().client() else {
                prompts::error(
                    &dialog,
                    "Not connected",
                    "Reconnect to the server before retrying a transfer.",
                );
                return;
            };
            if !frame.state.borrow().transfers.retry(&id, client) {
                prompts::info(
                    &dialog,
                    "Cannot retry",
                    "Only a failed or restored transfer can be retried.",
                );
            }
            refresh();
        });
    }

    {
        let frame = frame.clone();
        let selected_job = selected_job.clone();
        let refresh = refresh.clone();
        remove_job.on_click(move |_| {
            let Some(id) = selected_job() else {
                return;
            };
            if !frame.state.borrow().transfers.remove_job(&id) {
                // A running transfer stays in the list; removing its row would
                // hide work that is still happening.
                prompts::info(
                    &dialog,
                    "Cannot remove",
                    "That transfer is still running. Cancel it first.",
                );
            }
            refresh();
        });
    }

    {
        let frame = frame.clone();
        let refresh = refresh.clone();
        clear_finished.on_click(move |_| {
            let finished: Vec<String> = frame
                .state
                .borrow()
                .transfers
                .jobs()
                .into_iter()
                .filter(|job| job.status.is_finished())
                .map(|job| job.id)
                .collect();
            for id in finished {
                frame.state.borrow().transfers.remove_job(&id);
            }
            refresh();
        });
    }

    list.set_focus();
    dialog.show_modal();
    timer.stop();
    dialog.destroy();
    // The queue is saved on the way out so a transfer queued here survives a
    // crash before the next scheduled save.
    frame.state.borrow().save_queue();
}

/// The selected row, if any.
fn selected_row(list: &ListCtrl) -> Option<usize> {
    let row = list.get_next_item(-1, ListNextItemFlag::All, ListItemState::Selected);
    (row >= 0).then_some(row as usize)
}

/// Which buttons apply to a job in a given state.
///
/// Split out so the rules are testable without a window.
pub fn available_actions(status: Status) -> Vec<&'static str> {
    let mut actions = Vec::new();
    if !status.is_finished() {
        actions.push("cancel");
    }
    if matches!(status, Status::Failed | Status::Restored) {
        actions.push("retry");
    }
    if status.is_finished() {
        actions.push("remove");
    }
    actions
}

#[cfg(test)]
mod tests {
    use super::*;
    use portkeydrop_core::transfer::{Direction, TransferJob};

    fn job(status: Status) -> TransferJob {
        let mut job = TransferJob::new(Direction::Download, "/remote/a.txt", "/local/a.txt");
        job.status = status;
        job
    }

    #[test]
    fn a_running_transfer_can_be_cancelled_but_not_removed() {
        // Removing its row would hide work that is still happening.
        let actions = available_actions(Status::InProgress);
        assert!(actions.contains(&"cancel"));
        assert!(!actions.contains(&"remove"));
    }

    #[test]
    fn a_failed_transfer_can_be_retried_or_removed() {
        let actions = available_actions(Status::Failed);
        assert!(actions.contains(&"retry"));
        assert!(actions.contains(&"remove"));
        assert!(!actions.contains(&"cancel"));
    }

    #[test]
    fn a_restored_transfer_can_be_retried() {
        // This is the whole point of restoring: pick up where the last session
        // left off.
        assert!(available_actions(Status::Restored).contains(&"retry"));
    }

    #[test]
    fn a_completed_transfer_can_only_be_removed() {
        assert_eq!(available_actions(Status::Complete), vec!["remove"]);
    }

    #[test]
    fn a_cancelled_transfer_can_only_be_removed() {
        assert_eq!(available_actions(Status::Cancelled), vec!["remove"]);
    }

    #[test]
    fn a_pending_transfer_can_be_cancelled() {
        assert_eq!(available_actions(Status::Pending), vec!["cancel"]);
    }

    #[test]
    fn the_queue_columns_match_what_a_row_provides() {
        // A mismatch would silently drop a column's contents.
        assert_eq!(QUEUE_COLUMNS.len(), queue_row(&job(Status::Pending)).len());
    }
}
