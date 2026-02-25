"""Interactive Paramiko host key policy backed by a wx dialog."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

import paramiko

try:
    import wx
except Exception:  # pragma: no cover - exercised in headless tests
    wx = SimpleNamespace(CallAfter=lambda fn, *a, **kw: fn(*a, **kw))

try:
    from portkeydrop.dialogs.host_key_dialog import HostKeyDialog
except Exception:  # pragma: no cover - wx may be unavailable in headless tests
    class HostKeyDialog:  # type: ignore[no-redef]
        REJECT = 0
        ACCEPT_ONCE = 1
        ACCEPT_PERMANENT = 2

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def ShowModal(self) -> int:
            return self.REJECT

        def Destroy(self) -> None:
            pass


class InteractiveHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    """
    Paramiko host key policy that asks the user whether to trust unknown keys.
    """

    def __init__(self, parent_window, known_hosts_path):
        self._parent = parent_window
        self._known_hosts_path = known_hosts_path

    def missing_host_key(self, client, hostname, key):
        key_type = key.get_name()
        fingerprint = ":".join(f"{b:02x}" for b in key.get_fingerprint())

        event = threading.Event()
        result = [HostKeyDialog.REJECT]

        def show_dialog():
            dlg = HostKeyDialog(self._parent, hostname, key_type, fingerprint)
            try:
                result[0] = dlg.ShowModal()
            finally:
                dlg.Destroy()
                event.set()

        wx.CallAfter(show_dialog)
        event.wait(timeout=120)

        if result[0] == HostKeyDialog.ACCEPT_PERMANENT:
            client.get_host_keys().add(hostname, key_type, key)
            try:
                client.save_host_keys(str(self._known_hosts_path))
            except Exception:
                pass
            return
        if result[0] == HostKeyDialog.ACCEPT_ONCE:
            client.get_host_keys().add(hostname, key_type, key)
            return
        raise paramiko.SSHException(f"Host key for {hostname!r} was rejected by the user.")
