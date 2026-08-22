//! Reaching the terminal that launched a GUI build.
//!
//! Release builds link as a Windows GUI application. A console-subsystem
//! binary makes Windows open a console window behind the app on every launch
//! -- a terminal nobody asked for, sitting in the alt-tab list and reading as
//! a second window to a screen reader.
//!
//! The cost is that `--help` and `--version` have nowhere to print, so those
//! paths borrow the console of whatever started us first. Elsewhere this is a
//! no-op: on Unix the process already owns its terminal, and a debug build
//! keeps its console so panics stay visible while developing.

/// Borrow the console of the process that launched this one, if there is one.
///
/// Call this before printing anything a user asked for on the command line.
/// It does nothing when the process already has a console of its own.
pub fn attach_to_parent() {
    #[cfg(windows)]
    windows::attach_to_parent();
}

#[cfg(windows)]
mod windows {
    use std::ptr;

    use windows_sys::Win32::Foundation::{
        GENERIC_READ, GENERIC_WRITE, HANDLE, INVALID_HANDLE_VALUE,
    };
    use windows_sys::Win32::Storage::FileSystem::{
        CreateFileW, FILE_ATTRIBUTE_NORMAL, FILE_SHARE_READ, FILE_SHARE_WRITE, OPEN_EXISTING,
    };
    use windows_sys::Win32::System::Console::{
        AttachConsole, GetStdHandle, SetStdHandle, ATTACH_PARENT_PROCESS, STD_ERROR_HANDLE,
        STD_HANDLE, STD_INPUT_HANDLE, STD_OUTPUT_HANDLE,
    };

    pub fn attach_to_parent() {
        // Fails when the process already has a console, which is exactly when
        // there is nothing to do.
        if unsafe { AttachConsole(ATTACH_PARENT_PROCESS) } == 0 {
            return;
        }

        // Attaching gives the process a console but not the handles to write
        // to it, so any standard handle it does not already have is opened on
        // the console device.
        adopt("CONOUT$", STD_OUTPUT_HANDLE);
        adopt("CONOUT$", STD_ERROR_HANDLE);
        adopt("CONIN$", STD_INPUT_HANDLE);
    }

    /// Open one standard handle on a console device, unless it already has one.
    ///
    /// A shell hands its children the standard handles it wants them to use,
    /// which is how `portkeydrop --version > file` works at all. Overwriting
    /// those would send the output to the console instead of the file.
    fn adopt(device: &str, handle: STD_HANDLE) {
        if is_usable(unsafe { GetStdHandle(handle) }) {
            return;
        }

        let name: Vec<u16> = device.encode_utf16().chain(std::iter::once(0)).collect();

        let file = unsafe {
            CreateFileW(
                name.as_ptr(),
                GENERIC_READ | GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                ptr::null(),
                OPEN_EXISTING,
                FILE_ATTRIBUTE_NORMAL,
                ptr::null_mut(),
            )
        };

        // Nothing to fall back to if the device will not open: the caller is
        // about to print into the void, which is no worse than before.
        if is_usable(file) {
            unsafe { SetStdHandle(handle, file) };
        }
    }

    /// Whether a handle is one that can actually be written to or read from.
    ///
    /// A process with no console gets a null standard handle; a failed open
    /// gets `INVALID_HANDLE_VALUE`.
    fn is_usable(handle: HANDLE) -> bool {
        !handle.is_null() && handle != INVALID_HANDLE_VALUE
    }
}
