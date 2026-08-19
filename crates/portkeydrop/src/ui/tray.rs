//! The notification area (system tray) icon.
//!
//! For a screen reader user the icon itself is almost irrelevant — what matters
//! is the tooltip, which is what gets announced, and the menu, which is the only
//! way to act on it. Both are built here from the app's live state rather than
//! being set once and left stale.
//!
//! Windows exposes the notification area to the keyboard through Win+B; the
//! activation that follows arrives as one of several events depending on the
//! wxWidgets build, so every plausible one is bound.

use std::rc::Rc;

use wxdragon::prelude::*;
use wxdragon::widgets::taskbar_icon::{TaskBarIcon, TaskBarIconType};

use portkeydrop_core::transfer::{Status, TransferJob};

use super::ids;
use super::main_frame::MainFrame;

/// Width and height of the generated icon, in pixels.
const ICON_SIZE: u32 = 32;

/// The app's blue, matching the window's accent.
const ICON_BACKGROUND: [u8; 3] = [42, 92, 170];

/// The notification area icon and its menu.
pub struct TrayIcon {
    icon: Rc<TaskBarIcon>,
    /// The menu wxWidgets shows by itself where it reports no click events.
    /// Held here because it does not take ownership of the one it is given.
    #[cfg(not(target_os = "windows"))]
    menu: std::cell::RefCell<Menu>,
}

impl TrayIcon {
    /// Create the icon and wire it to the window.
    ///
    /// Returns `None` when the platform refuses to install it, which is normal
    /// on a Linux desktop with no tray; the app carries on without one.
    pub fn create(frame: &MainFrame) -> Option<Self> {
        let icon = Rc::new(
            TaskBarIcon::builder()
                .with_icon_type(TaskBarIconType::Default)
                .build(),
        );

        let bitmap = icon_bitmap()?;
        if !icon.set_icon(&bitmap, &tooltip_for(false, "", &[])) {
            log::info!("the notification area would not accept an icon");
            icon.destroy();
            return None;
        }

        // Only Windows reports every mouse event on a notification area icon.
        // Linux reports the two below; macOS reports none, and opens the menu
        // by itself, which is that platform's own convention.
        //
        // Showing the window is the common case, so it is on the plain click
        // as well as the double click.
        #[cfg(any(target_os = "windows", target_os = "linux"))]
        {
            let frame = frame.clone();
            icon.on_left_down(move |_| frame.show_window());
        }
        #[cfg(any(target_os = "windows", target_os = "linux"))]
        {
            let frame = frame.clone();
            icon.on_left_double_click(move |_| frame.show_window());
        }
        #[cfg(target_os = "windows")]
        {
            // Win+B then Enter surfaces as this on some wxWidgets builds, and
            // it is the only keyboard route to the icon.
            let frame = frame.clone();
            icon.on_left_up(move |_| frame.show_window());
        }

        // Right-click, and the keyboard's context-menu route, open the menu.
        #[cfg(target_os = "windows")]
        {
            let frame = frame.clone();
            let icon_for_menu = Rc::clone(&icon);
            icon.on_right_up(move |_| {
                let mut menu = build_menu(&frame);
                icon_for_menu.popup_menu(&mut menu);
            });
        }

        // Everywhere else wxWidgets shows the menu itself, so it is handed one
        // to keep. It does not take ownership, hence the copy held below.
        #[cfg(not(target_os = "windows"))]
        let menu = {
            let mut menu = build_menu(frame);
            icon.set_popup_menu(&mut menu);
            std::cell::RefCell::new(menu)
        };

        // The selection is posted rather than acted on: running it here would
        // let Exit destroy this icon while wxWidgets is still dispatching from
        // it, which crashes on return.
        {
            let sender = frame.sender.clone();
            icon.on_menu(move |event| {
                super::events::post(
                    &sender,
                    super::events::AppEvent::TrayCommand(event.get_id()),
                );
            });
        }

        Some(Self {
            icon,
            #[cfg(not(target_os = "windows"))]
            menu,
        })
    }

    /// Rebuild the menu so its items match what is currently possible.
    ///
    /// Nothing to do where the menu is built fresh on each right-click. Where
    /// wxWidgets holds one and shows it itself, that copy goes stale: the
    /// queue count stops moving and Disconnect stays enabled after the
    /// connection has gone.
    #[allow(unused_variables)]
    pub fn refresh_menu(&self, frame: &MainFrame) {
        #[cfg(not(target_os = "windows"))]
        {
            let mut rebuilt = build_menu(frame);
            self.icon.set_popup_menu(&mut rebuilt);
            *self.menu.borrow_mut() = rebuilt;
        }
    }

    /// Update the tooltip to reflect the current state.
    pub fn set_tooltip(&self, text: &str) {
        if let Some(bitmap) = icon_bitmap() {
            self.icon.set_icon(&bitmap, text);
        }
    }

    /// Take the icon out of the notification area and release it.
    ///
    /// Destroying matters on the way out: the icon owns a hidden top-level
    /// window on Windows, and while that lives the app stays running with
    /// nothing on screen. It is only safe outside the icon's own event
    /// handlers, since it frees the object wxWidgets would return into.
    pub fn remove(&self) {
        self.icon.remove_icon();
        self.icon.destroy();
    }
}

/// Build the tray menu against the window's current state.
///
/// Rebuilt on each open so items reflect what is actually possible, rather than
/// offering a Disconnect that does nothing.
fn build_menu(frame: &MainFrame) -> Menu {
    let connected = frame.state.borrow().is_connected();
    let active = frame.state.borrow().transfers.active_count();

    let menu = Menu::builder()
        .append_item(
            ids::ID_TRAY_SHOW,
            "&Show Portkey Drop",
            "Bring the window to the front",
        )
        .append_separator()
        .append_item(
            ids::ID_TRAY_QUEUE,
            &format!("Transfer &Queue{}...", queue_suffix(active)),
            "Show the transfer queue",
        )
        .append_item(
            ids::ID_DISCONNECT,
            "&Disconnect",
            "Disconnect from the server",
        )
        .append_separator()
        .append_item(
            ids::ID_TRAY_UPDATES,
            "Check for &Updates...",
            "Check for application updates",
        )
        .append_separator()
        .append_item(ID_EXIT, "E&xit", "Exit Portkey Drop")
        .build();

    menu.enable_item(ids::ID_DISCONNECT, connected);
    menu
}

/// The count shown beside the queue item, or nothing when it is empty.
pub fn queue_suffix(active: usize) -> String {
    if active == 0 {
        String::new()
    } else {
        format!(" ({active})")
    }
}

/// The tooltip text for the current state.
///
/// This is what a screen reader announces for the icon, so it leads with the
/// app name and then says the thing a user actually wants to know: whether it
/// is connected, and whether anything is transferring.
pub fn tooltip_for(connected: bool, host: &str, jobs: &[TransferJob]) -> String {
    let mut parts = vec![portkeydrop_core::APP_NAME.to_string()];

    parts.push(match (connected, host.is_empty()) {
        (true, false) => format!("connected to {host}"),
        (true, true) => "connected".to_string(),
        (false, _) => "not connected".to_string(),
    });

    let active = jobs.iter().filter(|job| !job.status.is_finished()).count();
    if active > 0 {
        let transferring = jobs
            .iter()
            .find(|job| job.status == Status::InProgress)
            .map(|job| format!("{}% of {}", job.progress, job.display_name()));
        match transferring {
            Some(progress) => parts.push(format!("{active} transfers, {progress}")),
            None => parts.push(format!(
                "{active} transfer{} queued",
                if active == 1 { "" } else { "s" }
            )),
        }
    }

    // Windows truncates a tray tooltip at 127 characters.
    let text = parts.join(" — ");
    if text.chars().count() > 127 {
        text.chars().take(124).collect::<String>() + "..."
    } else {
        text
    }
}

/// Generate the icon as RGBA pixels.
///
/// Drawn in code rather than shipped as a file so the icon cannot go missing
/// from a build, which is how the Python version ended up with a blank tray on
/// some installs.
pub fn icon_rgba() -> Vec<u8> {
    let size = ICON_SIZE as usize;
    let mut pixels = vec![0u8; size * size * 4];

    // A rounded square: the corner radius is what stops it reading as a plain
    // block at 16 pixels.
    let radius = (ICON_SIZE as f32) * 0.22;
    let centre = (ICON_SIZE as f32 - 1.0) / 2.0;

    for y in 0..size {
        for x in 0..size {
            let index = (y * size + x) * 4;
            let (fx, fy) = (x as f32, y as f32);
            let inside = rounded_square_contains(fx, fy, centre, radius);
            if !inside {
                continue;
            }
            let (red, green, blue) = if glyph_contains(x, y, size) {
                (255, 255, 255)
            } else {
                (ICON_BACKGROUND[0], ICON_BACKGROUND[1], ICON_BACKGROUND[2])
            };
            pixels[index] = red;
            pixels[index + 1] = green;
            pixels[index + 2] = blue;
            pixels[index + 3] = 255;
        }
    }
    pixels
}

/// Whether a pixel falls inside the rounded square.
fn rounded_square_contains(x: f32, y: f32, centre: f32, radius: f32) -> bool {
    let half = centre + 0.5;
    let (dx, dy) = ((x - centre).abs(), (y - centre).abs());
    let inner = half - radius;
    if dx <= inner || dy <= inner {
        return dx <= half - 0.5 && dy <= half - 0.5;
    }
    let (cx, cy) = (dx - inner, dy - inner);
    (cx * cx + cy * cy).sqrt() <= radius
}

/// Whether a pixel belongs to the downward arrow glyph.
///
/// An arrow rather than a letter: it reads at 16 pixels and says "transfer",
/// where a "P" at that size is an indistinct smudge.
fn glyph_contains(x: usize, y: usize, size: usize) -> bool {
    let unit = size as f32 / 32.0;
    let (fx, fy) = (x as f32 / unit, y as f32 / unit);

    // Shaft.
    if (13.0..19.0).contains(&fx) && (7.0..19.0).contains(&fy) {
        return true;
    }
    // Head: a triangle narrowing towards the point.
    if (18.0..26.0).contains(&fy) {
        let spread = 26.0 - fy;
        return (16.0 - spread..16.0 + spread).contains(&fx);
    }
    false
}

/// The icon as a bitmap, or `None` if the toolkit refuses it.
pub fn icon_bitmap() -> Option<Bitmap> {
    Bitmap::from_rgba(&icon_rgba(), ICON_SIZE, ICON_SIZE)
}

#[cfg(test)]
mod tests {
    use super::*;
    use portkeydrop_core::transfer::Direction;

    fn job(status: Status, progress: u8) -> TransferJob {
        let mut job =
            TransferJob::new(Direction::Download, "/remote/notes.txt", "/local/notes.txt");
        job.status = status;
        job.progress = progress;
        job
    }

    #[test]
    fn the_tooltip_leads_with_the_app_name() {
        // It is the first thing announced, so it has to identify the app.
        assert!(tooltip_for(false, "", &[]).starts_with("Portkey Drop"));
    }

    #[test]
    fn the_tooltip_reports_the_connection() {
        assert!(tooltip_for(true, "example.com", &[]).contains("connected to example.com"));
        assert!(tooltip_for(true, "", &[]).contains("connected"));
        assert!(tooltip_for(false, "example.com", &[]).contains("not connected"));
    }

    #[test]
    fn a_disconnected_tooltip_does_not_name_a_host() {
        // Naming a host you are not connected to would be actively misleading.
        assert!(!tooltip_for(false, "example.com", &[]).contains("example.com"));
    }

    #[test]
    fn the_tooltip_reports_transfer_progress() {
        let jobs = vec![job(Status::InProgress, 42)];
        let tooltip = tooltip_for(true, "example.com", &jobs);
        assert!(tooltip.contains("1 transfers, 42% of notes.txt"));
    }

    #[test]
    fn queued_transfers_are_counted_without_a_percentage() {
        let jobs = vec![job(Status::Pending, 0), job(Status::Pending, 0)];
        assert!(tooltip_for(true, "h", &jobs).contains("2 transfers queued"));
    }

    #[test]
    fn one_queued_transfer_is_announced_in_the_singular() {
        let jobs = vec![job(Status::Pending, 0)];
        assert!(tooltip_for(true, "h", &jobs).contains("1 transfer queued"));
    }

    #[test]
    fn finished_transfers_are_not_counted() {
        let jobs = vec![job(Status::Complete, 100), job(Status::Failed, 10)];
        let tooltip = tooltip_for(true, "h", &jobs);
        assert!(!tooltip.contains("transfer"));
    }

    #[test]
    fn the_tooltip_stays_within_the_windows_limit() {
        // Windows silently truncates past 127 characters, which would cut a
        // sentence off mid-word for a screen reader.
        let host = "a".repeat(200);
        let tooltip = tooltip_for(true, &host, &[job(Status::InProgress, 50)]);
        assert!(
            tooltip.chars().count() <= 127,
            "tooltip was {} chars",
            tooltip.chars().count()
        );
        assert!(tooltip.ends_with("..."));
    }

    #[test]
    fn the_queue_item_shows_a_count_only_when_there_is_work() {
        assert_eq!(queue_suffix(0), "");
        assert_eq!(queue_suffix(3), " (3)");
    }

    #[test]
    fn the_icon_is_the_expected_size() {
        assert_eq!(icon_rgba().len(), (ICON_SIZE * ICON_SIZE * 4) as usize);
    }

    #[test]
    fn the_icon_has_transparent_corners_and_a_solid_middle() {
        // A rounded square, not a filled rectangle: the corners must be clear
        // or the icon reads as a blob against any tray background.
        let pixels = icon_rgba();
        let alpha_at = |x: usize, y: usize| pixels[(y * ICON_SIZE as usize + x) * 4 + 3];
        assert_eq!(alpha_at(0, 0), 0, "top-left corner should be transparent");
        assert_eq!(
            alpha_at(ICON_SIZE as usize - 1, ICON_SIZE as usize - 1),
            0,
            "bottom-right corner should be transparent"
        );
        assert_eq!(alpha_at(16, 16), 255, "the middle should be opaque");
    }

    #[test]
    fn the_glyph_is_drawn_in_white_over_the_background() {
        let pixels = icon_rgba();
        let pixel_at = |x: usize, y: usize| {
            let index = (y * ICON_SIZE as usize + x) * 4;
            (pixels[index], pixels[index + 1], pixels[index + 2])
        };
        // Middle of the arrow shaft.
        assert_eq!(pixel_at(16, 12), (255, 255, 255));
        // Clear of the arrow, so still background.
        assert_eq!(
            pixel_at(6, 16),
            (ICON_BACKGROUND[0], ICON_BACKGROUND[1], ICON_BACKGROUND[2])
        );
    }

    #[test]
    fn the_glyph_narrows_towards_the_point() {
        // The arrow head has to actually taper, or it is just a bar.
        let width_at = |y: usize| {
            (0..ICON_SIZE as usize)
                .filter(|x| glyph_contains(*x, y, ICON_SIZE as usize))
                .count()
        };
        assert!(
            width_at(19) > width_at(24),
            "the head should narrow downwards"
        );
    }
}
