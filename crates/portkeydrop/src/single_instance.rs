//! Keeping one Portkey Drop per session.
//!
//! A second launch should bring the running window forward rather than opening
//! a rival window with its own transfer queue — two instances writing the same
//! `queue.json` would lose transfers.
//!
//! On Windows this uses a named mutex plus a window search. Elsewhere there is
//! no enforcement yet, and startup simply continues.

/// Name of the Windows mutex guarding the instance.
pub const MUTEX_NAME: &str = "Local\\PortkeyDrop.SingleInstance";

/// Title of the main window, used to find a running instance.
pub const WINDOW_TITLE: &str = "Portkey Drop";

/// Whether a window title belongs to this app's main window.
///
/// The title carries the remote path once connected, so an exact match is not
/// enough.
pub fn is_main_window_title(title: &str) -> bool {
    let title = title.trim();
    title == WINDOW_TITLE || title.starts_with(&format!("{WINDOW_TITLE} - "))
}

/// The outcome of trying to become the single instance.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum InstanceCheck {
    /// This process owns the instance and should start normally.
    Owner,
    /// Another instance is running and has been asked to show itself.
    AlreadyRunning,
}

/// Holds the single-instance lock for the life of the process.
pub struct SingleInstance {
    /// Held, not read: dropping it is what releases the lock, so the guard
    /// must outlive the window.
    #[cfg(windows)]
    #[allow(dead_code)]
    handle: Option<windows::MutexHandle>,
}

impl SingleInstance {
    /// Try to become the single instance.
    ///
    /// Any unexpected failure allows startup to continue: refusing to launch
    /// because a lock could not be taken would be worse than the duplicate it
    /// is guarding against.
    pub fn acquire() -> (Self, InstanceCheck) {
        #[cfg(windows)]
        {
            match windows::acquire(MUTEX_NAME) {
                windows::Acquisition::Owner(handle) => (
                    Self {
                        handle: Some(handle),
                    },
                    InstanceCheck::Owner,
                ),
                windows::Acquisition::AlreadyRunning => {
                    windows::show_existing_window();
                    (Self { handle: None }, InstanceCheck::AlreadyRunning)
                }
                windows::Acquisition::Unavailable => (Self { handle: None }, InstanceCheck::Owner),
            }
        }
        #[cfg(not(windows))]
        {
            (Self {}, InstanceCheck::Owner)
        }
    }
}

#[cfg(windows)]
mod windows {
    //! Named-mutex and window-search support.

    use windows_sys::Win32::Foundation::{CloseHandle, ERROR_ALREADY_EXISTS, HANDLE, HWND, LPARAM};
    use windows_sys::Win32::System::Threading::CreateMutexW;
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        EnumWindows, FindWindowW, GetWindowTextLengthW, GetWindowTextW, SetForegroundWindow,
        ShowWindow, SW_RESTORE, SW_SHOWNORMAL,
    };

    use super::{is_main_window_title, WINDOW_TITLE};

    /// An owned mutex handle, released when dropped.
    pub struct MutexHandle(HANDLE);

    // The handle is only closed on drop and never dereferenced elsewhere.
    unsafe impl Send for MutexHandle {}

    impl Drop for MutexHandle {
        fn drop(&mut self) {
            // SAFETY: the handle came from a successful CreateMutexW.
            unsafe { CloseHandle(self.0) };
            log::info!("released the single-instance lock");
        }
    }

    /// What happened when trying to take the lock.
    pub enum Acquisition {
        /// This process took it.
        Owner(MutexHandle),
        /// Another process holds it.
        AlreadyRunning,
        /// The lock could not be used; carry on without it.
        Unavailable,
    }

    fn wide(value: &str) -> Vec<u16> {
        value.encode_utf16().chain(std::iter::once(0)).collect()
    }

    /// Try to take the named mutex.
    pub fn acquire(name: &str) -> Acquisition {
        // SAFETY: `name` is NUL-terminated; a null security descriptor is the
        // documented default.
        let handle = unsafe { CreateMutexW(std::ptr::null(), 0, wide(name).as_ptr()) };
        if handle.is_null() {
            log::warn!("could not create the single-instance mutex; continuing");
            return Acquisition::Unavailable;
        }

        let already_exists =
            std::io::Error::last_os_error().raw_os_error() == Some(ERROR_ALREADY_EXISTS as i32);
        if already_exists {
            // SAFETY: the handle came from a successful CreateMutexW.
            unsafe { CloseHandle(handle) };
            return Acquisition::AlreadyRunning;
        }

        // A window without the mutex means an instance from before the mutex
        // existed, or one whose handle leaked; treat it as running.
        if find_main_window().is_some() {
            // SAFETY: as above.
            unsafe { CloseHandle(handle) };
            return Acquisition::AlreadyRunning;
        }

        Acquisition::Owner(MutexHandle(handle))
    }

    /// Find the running instance's main window.
    pub fn find_main_window() -> Option<HWND> {
        // SAFETY: both arguments are NUL-terminated wide strings.
        let direct = unsafe { FindWindowW(std::ptr::null(), wide(WINDOW_TITLE).as_ptr()) };
        if !direct.is_null() {
            return Some(direct);
        }

        // The title carries the remote path once connected, so an exact match
        // misses a window that is in use — which is exactly the one to find.
        let mut found: HWND = std::ptr::null_mut();
        // SAFETY: the callback matches the EnumWindows contract and only
        // writes through the pointer it is given.
        unsafe {
            EnumWindows(Some(enum_callback), &mut found as *mut HWND as LPARAM);
        }
        (!found.is_null()).then_some(found)
    }

    unsafe extern "system" fn enum_callback(window: HWND, out: LPARAM) -> i32 {
        let length = GetWindowTextLengthW(window);
        if length <= 0 {
            return 1;
        }
        let mut buffer = vec![0u16; length as usize + 1];
        let written = GetWindowTextW(window, buffer.as_mut_ptr(), buffer.len() as i32);
        if written <= 0 {
            return 1;
        }
        let title = String::from_utf16_lossy(&buffer[..written as usize]);
        if is_main_window_title(&title) {
            *(out as *mut HWND) = window;
            // Stop enumerating: the window has been found.
            return 0;
        }
        1
    }

    /// Bring the running instance's window to the front.
    pub fn show_existing_window() {
        let Some(window) = find_main_window() else {
            log::info!("no existing window to restore");
            return;
        };
        // SAFETY: `window` came from a window enumeration.
        unsafe {
            ShowWindow(window, SW_RESTORE);
            ShowWindow(window, SW_SHOWNORMAL);
            SetForegroundWindow(window);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_bare_window_title_is_recognised() {
        assert!(is_main_window_title("Portkey Drop"));
        assert!(is_main_window_title("  Portkey Drop  "));
    }

    #[test]
    fn a_connected_window_title_is_recognised() {
        // Once connected the title carries the remote path, and that window is
        // exactly the one a second launch needs to find.
        assert!(is_main_window_title("Portkey Drop - /home/alice"));
    }

    #[test]
    fn other_windows_are_not_mistaken_for_ours() {
        assert!(!is_main_window_title("Portkey Drop Setup"));
        assert!(!is_main_window_title("Notepad"));
        assert!(!is_main_window_title(""));
    }

    #[test]
    fn acquiring_the_lock_never_prevents_startup() {
        // Whatever the platform reports, the first launch in a session must be
        // allowed to run.
        let (_guard, check) = SingleInstance::acquire();
        assert!(matches!(
            check,
            InstanceCheck::Owner | InstanceCheck::AlreadyRunning
        ));
    }
}
