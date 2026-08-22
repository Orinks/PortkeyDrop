//! The state behind one file pane: what is loaded, what is shown, and where
//! the cursor is.
//!
//! Kept free of widget types so sorting, filtering, and cursor restoration can
//! be tested directly. The widget layer only asks it what rows to draw.

use portkeydrop_core::protocols::RemoteFile;

use super::format::DateStyle;

/// Which column a pane is sorted by.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum SortField {
    #[default]
    Name,
    Size,
    Type,
    Modified,
}

impl SortField {
    /// Parse a settings value, defaulting to name order.
    pub fn from_setting(value: &str) -> Self {
        match value.trim().to_ascii_lowercase().as_str() {
            "size" => SortField::Size,
            "type" => SortField::Type,
            "modified" => SortField::Modified,
            _ => SortField::Name,
        }
    }

    /// The settings value for this field.
    pub fn as_str(self) -> &'static str {
        match self {
            SortField::Name => "name",
            SortField::Size => "size",
            SortField::Type => "type",
            SortField::Modified => "modified",
        }
    }

    /// The name announced when the sort order changes.
    pub fn display_name(self) -> &'static str {
        match self {
            SortField::Name => "name",
            SortField::Size => "size",
            SortField::Type => "type",
            SortField::Modified => "date modified",
        }
    }
}

/// Where the cursor was, so it can be put back after a refresh.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct CursorPosition {
    /// Name of the focused item, which survives rows moving around.
    pub focused_name: Option<String>,
    /// Row index, used when the named item is gone.
    pub index: usize,
}

/// One file pane's state.
#[derive(Debug, Clone, Default)]
pub struct PaneState {
    /// Everything the last listing returned.
    all_files: Vec<RemoteFile>,
    /// Indices into `all_files`, in display order.
    visible: Vec<usize>,
    filter: String,
    show_hidden: bool,
    sort_field: SortField,
    sort_ascending: bool,
    date_style: DateStyle,
    /// Current directory.
    pub path: String,
}

impl PaneState {
    /// A pane with the given display preferences.
    pub fn new(sort_field: SortField, sort_ascending: bool, show_hidden: bool) -> Self {
        Self {
            all_files: Vec::new(),
            visible: Vec::new(),
            filter: String::new(),
            show_hidden,
            sort_field,
            sort_ascending,
            date_style: DateStyle::default(),
            path: String::new(),
        }
    }

    /// The same pane, reading modification times in the given style.
    pub fn with_date_style(mut self, date_style: DateStyle) -> Self {
        self.date_style = date_style;
        self
    }

    /// How the pane renders modification times.
    pub fn date_style(&self) -> DateStyle {
        self.date_style
    }

    /// Change how the pane renders modification times.
    ///
    /// Rows are unaffected until they are redrawn: only their text changes,
    /// so there is nothing to recompute.
    pub fn set_date_style(&mut self, date_style: DateStyle) {
        self.date_style = date_style;
    }

    /// Replace the pane's contents.
    pub fn set_files(&mut self, files: Vec<RemoteFile>, path: impl Into<String>) {
        self.all_files = files;
        self.path = path.into();
        self.recompute();
    }

    /// How many files the last listing returned.
    pub fn total_count(&self) -> usize {
        self.all_files.len()
    }

    /// How many rows are shown.
    pub fn visible_count(&self) -> usize {
        self.visible.len()
    }

    /// The rows to draw, in order.
    pub fn visible_files(&self) -> Vec<&RemoteFile> {
        self.visible
            .iter()
            .filter_map(|index| self.all_files.get(*index))
            .collect()
    }

    /// The file at a display row.
    pub fn file_at(&self, row: usize) -> Option<&RemoteFile> {
        self.all_files.get(*self.visible.get(row)?)
    }

    /// The files at the given display rows.
    pub fn files_at(&self, rows: &[usize]) -> Vec<RemoteFile> {
        rows.iter()
            .filter_map(|row| self.file_at(*row).cloned())
            .collect()
    }

    /// The current filter text.
    pub fn filter(&self) -> &str {
        &self.filter
    }

    /// Set the filter and refresh the visible rows.
    pub fn set_filter(&mut self, filter: impl Into<String>) {
        self.filter = filter.into();
        self.recompute();
    }

    /// Whether hidden files are shown.
    pub fn show_hidden(&self) -> bool {
        self.show_hidden
    }

    /// Show or hide hidden files.
    pub fn set_show_hidden(&mut self, show_hidden: bool) {
        self.show_hidden = show_hidden;
        self.recompute();
    }

    /// The current sort field.
    pub fn sort_field(&self) -> SortField {
        self.sort_field
    }

    /// Whether the sort is ascending.
    pub fn sort_ascending(&self) -> bool {
        self.sort_ascending
    }

    /// Sort by a field.
    ///
    /// Choosing the field that is already active reverses the direction, which
    /// is what a second press on the same menu item should do.
    pub fn sort_by(&mut self, field: SortField) {
        if self.sort_field == field {
            self.sort_ascending = !self.sort_ascending;
        } else {
            self.sort_field = field;
            self.sort_ascending = true;
        }
        self.recompute();
    }

    /// Capture the cursor so it can be restored after a refresh.
    pub fn capture_cursor(&self, row: Option<usize>) -> CursorPosition {
        let index = row.unwrap_or(0);
        CursorPosition {
            focused_name: row
                .and_then(|row| self.file_at(row))
                .map(|file| file.name.clone()),
            index,
        }
    }

    /// Work out where the cursor should go after a refresh.
    ///
    /// The named item is preferred, so a row that merely moved keeps focus. If
    /// it is gone — deleted, renamed, filtered out — the old index is used,
    /// clamped to the list, so focus lands on the neighbour rather than
    /// jumping to the top.
    pub fn restore_cursor(&self, position: &CursorPosition) -> Option<usize> {
        if self.visible.is_empty() {
            return None;
        }
        if let Some(name) = position.focused_name.as_deref() {
            if let Some(row) = self
                .visible_files()
                .iter()
                .position(|file| file.name == name)
            {
                return Some(row);
            }
        }
        Some(position.index.min(self.visible.len() - 1))
    }

    /// Recompute the visible rows from the filter, hidden setting, and sort.
    fn recompute(&mut self) {
        let filter = self.filter.trim().to_lowercase();
        let mut indices: Vec<usize> = self
            .all_files
            .iter()
            .enumerate()
            .filter(|(_, file)| self.show_hidden || !file.is_hidden())
            .filter(|(_, file)| filter.is_empty() || file.name.to_lowercase().contains(&filter))
            .map(|(index, _)| index)
            .collect();

        let field = self.sort_field;
        let ascending = self.sort_ascending;
        let files = &self.all_files;
        indices.sort_by(|left, right| {
            let (left, right) = (&files[*left], &files[*right]);
            // Directories always lead, in both directions: a listing where
            // folders are scattered through the files is far harder to scan.
            match right.is_dir.cmp(&left.is_dir) {
                std::cmp::Ordering::Equal => {}
                other => return other,
            }
            let ordering = match field {
                SortField::Name => compare_names(&left.name, &right.name),
                SortField::Size => left.size.cmp(&right.size),
                SortField::Type => left
                    .display_type()
                    .to_lowercase()
                    .cmp(&right.display_type().to_lowercase())
                    .then_with(|| compare_names(&left.name, &right.name)),
                SortField::Modified => left.modified.cmp(&right.modified),
            };
            if ascending {
                ordering
            } else {
                ordering.reverse()
            }
        });
        self.visible = indices;
    }
}

/// Compare file names case-insensitively, falling back to a stable tiebreak.
fn compare_names(left: &str, right: &str) -> std::cmp::Ordering {
    left.to_lowercase()
        .cmp(&right.to_lowercase())
        .then_with(|| left.cmp(right))
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::NaiveDate;

    fn at(day: u32) -> Option<chrono::NaiveDateTime> {
        Some(
            NaiveDate::from_ymd_opt(2026, 3, day)
                .unwrap()
                .and_hms_opt(0, 0, 0)
                .unwrap(),
        )
    }

    fn sample() -> Vec<RemoteFile> {
        let mut zebra = RemoteFile::file("zebra.txt", "/zebra.txt", 10);
        zebra.modified = at(1);
        let mut apple = RemoteFile::file("Apple.log", "/Apple.log", 300);
        apple.modified = at(3);
        let mut hidden = RemoteFile::file(".hidden", "/.hidden", 5);
        hidden.modified = at(2);
        let docs = RemoteFile::dir("docs", "/docs");
        vec![zebra, apple, hidden, docs]
    }

    fn pane() -> PaneState {
        let mut pane = PaneState::new(SortField::Name, true, false);
        pane.set_files(sample(), "/");
        pane
    }

    fn names(pane: &PaneState) -> Vec<String> {
        pane.visible_files()
            .iter()
            .map(|file| file.name.clone())
            .collect()
    }

    #[test]
    fn sort_settings_round_trip() {
        for field in [
            SortField::Name,
            SortField::Size,
            SortField::Type,
            SortField::Modified,
        ] {
            assert_eq!(SortField::from_setting(field.as_str()), field);
            assert!(!field.display_name().is_empty());
        }
        assert_eq!(SortField::from_setting("nonsense"), SortField::Name);
    }

    #[test]
    fn hidden_files_are_left_out_by_default() {
        assert!(!names(&pane()).contains(&".hidden".to_string()));
        assert_eq!(pane().visible_count(), 3);
        // The total still counts everything that was listed.
        assert_eq!(pane().total_count(), 4);
    }

    #[test]
    fn hidden_files_appear_when_asked_for() {
        let mut pane = pane();
        pane.set_show_hidden(true);
        assert!(names(&pane).contains(&".hidden".to_string()));
        assert_eq!(pane.visible_count(), 4);
    }

    #[test]
    fn directories_are_listed_before_files() {
        // A listing with folders scattered among files is much harder to scan.
        assert_eq!(names(&pane())[0], "docs");
    }

    #[test]
    fn directories_stay_first_when_the_order_is_reversed() {
        let mut pane = pane();
        // The pane already sorts by name, so choosing it again reverses.
        pane.sort_by(SortField::Name);
        assert!(!pane.sort_ascending());
        assert_eq!(names(&pane), vec!["docs", "zebra.txt", "Apple.log"]);
    }

    #[test]
    fn names_sort_case_insensitively() {
        // Otherwise every capitalised name is bunched ahead of the lowercase
        // ones, which is not the order anyone expects.
        assert_eq!(names(&pane()), vec!["docs", "Apple.log", "zebra.txt"]);
    }

    #[test]
    fn sorting_by_size_orders_the_files() {
        let mut pane = pane();
        pane.sort_by(SortField::Size);
        assert_eq!(names(&pane), vec!["docs", "zebra.txt", "Apple.log"]);
    }

    #[test]
    fn sorting_by_modified_orders_the_files() {
        let mut pane = pane();
        pane.sort_by(SortField::Modified);
        assert_eq!(names(&pane), vec!["docs", "zebra.txt", "Apple.log"]);
    }

    #[test]
    fn choosing_the_active_field_again_reverses_the_order() {
        let mut pane = pane();
        pane.sort_by(SortField::Size);
        assert!(pane.sort_ascending());
        pane.sort_by(SortField::Size);
        assert!(!pane.sort_ascending());
        assert_eq!(names(&pane), vec!["docs", "Apple.log", "zebra.txt"]);
    }

    #[test]
    fn choosing_a_different_field_starts_ascending() {
        let mut pane = pane();
        pane.sort_by(SortField::Size);
        pane.sort_by(SortField::Size);
        pane.sort_by(SortField::Name);
        assert!(pane.sort_ascending());
    }

    #[test]
    fn filtering_matches_any_part_of_a_name_ignoring_case() {
        let mut pane = pane();
        pane.set_filter("APP");
        assert_eq!(names(&pane), vec!["Apple.log"]);
    }

    #[test]
    fn a_filter_matching_nothing_leaves_an_empty_pane() {
        let mut pane = pane();
        pane.set_filter("nothing-matches-this");
        assert_eq!(pane.visible_count(), 0);
        assert_eq!(pane.total_count(), 4);
    }

    #[test]
    fn clearing_the_filter_brings_everything_back() {
        let mut pane = pane();
        pane.set_filter("app");
        pane.set_filter("");
        assert_eq!(pane.visible_count(), 3);
    }

    #[test]
    fn a_filter_does_not_reveal_hidden_files() {
        let mut pane = pane();
        pane.set_filter("hidden");
        assert_eq!(pane.visible_count(), 0);
    }

    #[test]
    fn rows_map_back_to_their_files() {
        let pane = pane();
        assert_eq!(pane.file_at(0).unwrap().name, "docs");
        assert!(pane.file_at(99).is_none());

        let selected = pane.files_at(&[0, 2]);
        assert_eq!(selected.len(), 2);
        assert_eq!(selected[1].name, "zebra.txt");
    }

    #[test]
    fn the_cursor_follows_an_item_that_merely_moved() {
        // Refreshing into a different sort order must not lose the user's
        // place.
        let mut pane = pane();
        let position = pane.capture_cursor(Some(2));
        assert_eq!(position.focused_name.as_deref(), Some("zebra.txt"));

        pane.sort_by(SortField::Size);
        pane.sort_by(SortField::Size);
        let row = pane.restore_cursor(&position).unwrap();
        assert_eq!(pane.file_at(row).unwrap().name, "zebra.txt");
    }

    #[test]
    fn the_cursor_lands_on_a_neighbour_when_the_item_is_gone() {
        // After deleting a file, jumping to the top of the list would lose the
        // user's position entirely.
        let mut pane = pane();
        let position = pane.capture_cursor(Some(2));

        let remaining: Vec<RemoteFile> = sample()
            .into_iter()
            .filter(|file| file.name != "zebra.txt")
            .collect();
        pane.set_files(remaining, "/");

        let row = pane.restore_cursor(&position).unwrap();
        assert_eq!(row, 1);
    }

    #[test]
    fn the_cursor_clamps_to_the_end_of_a_shorter_list() {
        let mut pane = pane();
        let position = pane.capture_cursor(Some(2));
        pane.set_files(vec![RemoteFile::dir("only", "/only")], "/");
        assert_eq!(pane.restore_cursor(&position), Some(0));
    }

    #[test]
    fn an_empty_pane_has_nowhere_to_put_the_cursor() {
        let mut pane = pane();
        let position = pane.capture_cursor(Some(0));
        pane.set_files(Vec::new(), "/");
        assert_eq!(pane.restore_cursor(&position), None);
    }

    #[test]
    fn capturing_with_no_selection_records_no_name() {
        let position = pane().capture_cursor(None);
        assert_eq!(position.focused_name, None);
        assert_eq!(position.index, 0);
    }

    #[test]
    fn replacing_the_contents_updates_the_path() {
        let mut pane = pane();
        pane.set_files(Vec::new(), "/somewhere/else");
        assert_eq!(pane.path, "/somewhere/else");
    }
}
