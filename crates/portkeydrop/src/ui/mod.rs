//! The wxWidgets front end.

pub mod dialogs;
pub mod events;
pub mod file_pane;
pub mod format;
pub mod ids;
pub mod keys;
pub mod main_frame;
pub mod operations;
pub mod prompts;
pub mod quick_connect;
pub mod state;
pub mod tray;
pub mod view;

pub use main_frame::{MainFrame, Side};
