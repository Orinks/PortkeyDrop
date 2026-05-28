"""Win32 mutex-backed single-instance support for PortkeyDrop."""

from __future__ import annotations

import ctypes
import logging
import sys

logger = logging.getLogger(__name__)

SINGLE_INSTANCE_MUTEX_NAME = "Local\\PortkeyDrop.SingleInstance"
ERROR_ALREADY_EXISTS = 183
SW_SHOWNORMAL = 1
SW_RESTORE = 9
APP_WINDOW_TITLE = "Portkey Drop"


class SingleInstanceManager:
    """Coordinates one running PortkeyDrop instance per Windows session."""

    def __init__(self, mutex_name: str = SINGLE_INSTANCE_MUTEX_NAME) -> None:
        self.mutex_name = mutex_name
        self._mutex_handle: int | None = None
        self._lock_acquired = False

    def try_acquire_lock(self) -> bool:
        """
        Acquire the process-wide mutex.

        Non-Windows platforms run without single-instance enforcement until a
        native strategy is added.
        """
        if sys.platform != "win32":
            self._lock_acquired = True
            return True

        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel32.CreateMutexW(None, False, self.mutex_name)
            if not handle:
                logger.warning("CreateMutexW failed; allowing startup to continue")
                return True

            if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
                logger.info("Another PortkeyDrop instance already owns the mutex")
                kernel32.CloseHandle(handle)
                self._mutex_handle = None
                self._lock_acquired = False
                return False

            if self._existing_window_is_present():
                logger.info(
                    "Found an existing PortkeyDrop window without the mutex; "
                    "treating it as the running instance"
                )
                kernel32.CloseHandle(handle)
                self._mutex_handle = None
                self._lock_acquired = False
                return False

            self._mutex_handle = handle
            self._lock_acquired = True
            logger.info("Acquired PortkeyDrop single-instance mutex")
            return True
        except Exception as exc:
            logger.warning("Single-instance mutex check failed; allowing startup: %s", exc)
            return True

    def request_existing_instance_show(self) -> bool:
        """Ask the existing instance to become visible."""
        if sys.platform != "win32":
            return False

        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            hwnd = self._find_portkeydrop_window(user32)
            if not hwnd:
                logger.info("No existing PortkeyDrop window found to restore")
                return False

            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.ShowWindow(hwnd, SW_SHOWNORMAL)
            user32.SetForegroundWindow(hwnd)
            return True
        except Exception as exc:
            logger.warning("Failed to show existing PortkeyDrop instance: %s", exc)
            return False

    def _existing_window_is_present(self) -> bool:
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            return bool(self._find_portkeydrop_window(user32))
        except Exception:
            return False

    def _find_portkeydrop_window(self, user32) -> int:
        """Find the primary PortkeyDrop top-level window."""
        hwnd = user32.FindWindowW(None, APP_WINDOW_TITLE)
        if hwnd:
            return int(hwnd)

        found_hwnd = 0
        try:
            enum_windows_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

            def _enum_window_callback(candidate_hwnd, _lparam):
                nonlocal found_hwnd
                title = self._get_window_title(user32, candidate_hwnd).strip()
                if self._is_portkeydrop_window_title(title):
                    found_hwnd = int(candidate_hwnd)
                    return False
                return True

            user32.EnumWindows(enum_windows_proc(_enum_window_callback), None)
        except Exception:
            return 0

        return found_hwnd

    @staticmethod
    def _is_portkeydrop_window_title(title: str) -> bool:
        """Return True for PortkeyDrop's main window titles."""
        return title == APP_WINDOW_TITLE or title.startswith(f"{APP_WINDOW_TITLE} - ")

    @staticmethod
    def _get_window_title(user32, hwnd) -> str:
        try:
            length = int(user32.GetWindowTextLengthW(hwnd))
            if length <= 0:
                return ""
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            return buffer.value
        except Exception:
            return ""

    def release_lock(self) -> None:
        """Release the owned mutex handle."""
        if not self._mutex_handle:
            self._lock_acquired = False
            return

        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CloseHandle(self._mutex_handle)
            logger.info("Released PortkeyDrop single-instance mutex")
        except Exception as exc:
            logger.debug("Failed to close single-instance mutex handle: %s", exc)
        finally:
            self._mutex_handle = None
            self._lock_acquired = False

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_val, _exc_tb):
        self.release_lock()
