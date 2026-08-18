//! One labelled file browser pane.
//!
//! Accessibility drives the layout here. Each pane is a path field and a report
//! list, both given explicit accessible names, with a `StaticText` placed
//! immediately before the list: on Windows, NVDA takes a list's name from the
//! preceding sibling, so that label is what makes the pane announce itself as
//! "Local files" rather than "list".

use std::cell::RefCell;
use std::rc::Rc;

use wxdragon::prelude::*;
use wxdragon::widgets::list_ctrl::{ListColumnFormat, ListItemState, ListNextItemFlag};

use portkeydrop_core::protocols::RemoteFile;

use super::format::{file_row, FILE_COLUMNS};
use super::view::{CursorPosition, PaneState};

/// A file browser pane and the state behind it.
pub struct FilePane {
    pub panel: Panel,
    pub path_bar: TextCtrl,
    pub list: ListCtrl,
    /// Human-readable pane name, used in announcements.
    pub title: String,
    pub state: Rc<RefCell<PaneState>>,
}

impl FilePane {
    /// Build a pane under `parent`.
    ///
    /// `title` is both the visible label and the accessible name, so what a
    /// sighted user reads and what a screen reader says are the same thing.
    pub fn new(parent: &Panel, title: &str, state: PaneState) -> Self {
        let panel = Panel::builder(parent).build();
        let sizer = BoxSizer::builder(Orientation::Vertical).build();

        let path_label = StaticText::builder(&panel)
            .with_label(&format!("{title} path:"))
            .build();
        sizer.add(&path_label, 0, SizerFlag::Left | SizerFlag::All, 2);

        let path_bar = TextCtrl::builder(&panel)
            .with_style(TextCtrlStyle::ProcessEnter)
            .build();
        path_bar.set_name(&format!("{title} path"));
        sizer.add(&path_bar, 0, SizerFlag::Expand | SizerFlag::All, 2);

        // This label must sit immediately before the list: NVDA reads the
        // preceding sibling as the list's name.
        let list_label = StaticText::builder(&panel)
            .with_label(&format!("{title}:"))
            .build();
        sizer.add(&list_label, 0, SizerFlag::Left | SizerFlag::All, 2);

        let list = ListCtrl::builder(&panel)
            .with_style(ListCtrlStyle::Report)
            .build();
        list.set_name(title);
        for (index, (heading, width)) in FILE_COLUMNS.iter().enumerate() {
            list.insert_column(index as i64, heading, ListColumnFormat::Left, *width);
        }
        sizer.add(&list, 1, SizerFlag::Expand | SizerFlag::All, 2);

        panel.set_sizer(sizer, true);

        Self {
            panel,
            path_bar,
            list,
            title: title.to_string(),
            state: Rc::new(RefCell::new(state)),
        }
    }

    /// Replace the pane's contents and redraw, keeping the cursor where it was.
    pub fn set_files(&self, files: Vec<RemoteFile>, path: &str) {
        let cursor = {
            let state = self.state.borrow();
            state.capture_cursor(self.focused_row())
        };
        self.state.borrow_mut().set_files(files, path);
        self.path_bar.set_value(path);
        self.redraw(&cursor);
    }

    /// Redraw the rows from the current state.
    pub fn refresh_rows(&self) {
        let cursor = {
            let state = self.state.borrow();
            state.capture_cursor(self.focused_row())
        };
        self.redraw(&cursor);
    }

    fn redraw(&self, cursor: &CursorPosition) {
        self.list.delete_all_items();
        let state = self.state.borrow();
        for (row, file) in state.visible_files().iter().enumerate() {
            let cells = file_row(file);
            self.list.insert_item(row as i64, &cells[0], None);
            for (column, value) in cells.iter().enumerate().skip(1) {
                self.list
                    .set_item_text_by_column(row as i64, column as i32, value);
            }
        }
        if let Some(row) = state.restore_cursor(cursor) {
            self.focus_row(row);
        }
    }

    /// The focused row, if any.
    pub fn focused_row(&self) -> Option<usize> {
        let focused = self
            .list
            .get_next_item(-1, ListNextItemFlag::All, ListItemState::Focused);
        if focused >= 0 {
            return Some(focused as usize);
        }
        let selected = self.list.get_first_selected_item();
        (selected >= 0).then_some(selected as usize)
    }

    /// Every selected row, in order.
    pub fn selected_rows(&self) -> Vec<usize> {
        let mut rows = Vec::new();
        let mut item = self
            .list
            .get_next_item(-1, ListNextItemFlag::All, ListItemState::Selected);
        while item >= 0 {
            rows.push(item as usize);
            item = self.list.get_next_item(
                item as i64,
                ListNextItemFlag::All,
                ListItemState::Selected,
            );
        }
        rows
    }

    /// The selected files, falling back to the focused row.
    ///
    /// The fallback matters for keyboard use: arrowing to a row focuses it
    /// without necessarily selecting it, and a command that then did nothing
    /// would look broken.
    pub fn selected_files(&self) -> Vec<RemoteFile> {
        let state = self.state.borrow();
        let rows = self.selected_rows();
        if !rows.is_empty() {
            return state.files_at(&rows);
        }
        self.focused_row()
            .and_then(|row| state.file_at(row).cloned())
            .map(|file| vec![file])
            .unwrap_or_default()
    }

    /// The single focused or selected file.
    pub fn selected_file(&self) -> Option<RemoteFile> {
        self.selected_files().into_iter().next()
    }

    /// Move focus and selection to a row.
    pub fn focus_row(&self, row: usize) {
        let row = row as i64;
        self.list.set_item_state(
            row,
            ListItemState::Focused | ListItemState::Selected,
            ListItemState::Focused | ListItemState::Selected,
        );
        self.list.ensure_visible(row);
    }

    /// Put keyboard focus on the file list.
    pub fn focus(&self) {
        self.list.set_focus();
        // Land on a row rather than an empty list, so the first arrow press
        // moves within the list instead of just entering it.
        if self.focused_row().is_none() && self.list.get_item_count() > 0 {
            self.focus_row(0);
        }
    }

    /// Whether this pane's list currently has focus.
    pub fn has_focus(&self) -> bool {
        self.list.has_focus()
    }

    /// The current directory.
    pub fn path(&self) -> String {
        self.state.borrow().path.clone()
    }

    /// The path as typed into the path bar.
    pub fn typed_path(&self) -> String {
        self.path_bar.get_value().trim().to_string()
    }

    /// How many rows are shown, and how many were listed.
    pub fn counts(&self) -> (usize, usize) {
        let state = self.state.borrow();
        (state.visible_count(), state.total_count())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ui::view::SortField;

    #[test]
    fn the_column_set_matches_what_the_panes_draw() {
        // The pane inserts one column per entry and fills one cell per entry;
        // a mismatch would silently drop a column's contents.
        assert_eq!(FILE_COLUMNS.len(), 5);
        assert_eq!(FILE_COLUMNS[0].0, "Name");
    }

    #[test]
    fn pane_state_drives_what_a_pane_would_show() {
        // The widget layer only reads from PaneState, so this is what the pane
        // renders without needing a display to test it.
        let mut state = PaneState::new(SortField::Name, true, false);
        state.set_files(
            vec![
                RemoteFile::file("b.txt", "/b.txt", 10),
                RemoteFile::dir("a-dir", "/a-dir"),
                RemoteFile::file(".hidden", "/.hidden", 1),
            ],
            "/",
        );
        let names: Vec<String> = state
            .visible_files()
            .iter()
            .map(|file| file.name.clone())
            .collect();
        assert_eq!(names, vec!["a-dir", "b.txt"]);
    }
}
