"""Transfer queue dialog for Portkey Drop.

The dialog is a **stateless observer** — closing or hiding it never cancels
a running transfer.  All transfer logic lives in
:class:`~portkeydrop.services.transfer_service.TransferService`.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

# Re-export service types so existing imports keep working
from portkeydrop.services.transfer_service import (  # noqa: F401
    TransferDirection,
    TransferJob,
    TransferService,
    TransferStatus,
    get_transfer_event_binder,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def save_queue(service: TransferService, config_dir: Path) -> None:
    """Save pending and failed jobs to queue.json. Passwords are never persisted."""
    persistable = [
        j
        for j in service.jobs
        if j.status in (TransferStatus.PENDING, TransferStatus.FAILED, TransferStatus.RESTORED)
    ]
    queue_path = config_dir / "queue.json"
    try:
        config_dir.mkdir(parents=True, exist_ok=True)
        data = [j.to_dict() for j in persistable]
        queue_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        logger.exception("Failed to save transfer queue to %s", queue_path)


def load_queue(config_dir: Path) -> list[TransferJob]:
    """Load transfer queue from queue.json. Returns empty list on error or missing file."""
    queue_path = config_dir / "queue.json"
    if not queue_path.exists():
        return []
    try:
        data = json.loads(queue_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return []
        return [TransferJob.from_dict(entry) for entry in data if isinstance(entry, dict)]
    except Exception:
        logger.exception("Failed to load transfer queue from %s", queue_path)
        return []


def create_transfer_dialog(parent, transfer_service: TransferService, log_callback=None):
    """Create and return a TransferDialog.  Requires wx."""
    import wx
    from pathlib import PurePosixPath

    class TransferDialog(wx.Dialog):
        """Disposable observer over the :class:`TransferService` job list."""

        def __init__(self, parent_win, svc: TransferService, log_cb=None):
            super().__init__(
                parent_win,
                title="Transfer Queue",
                style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.CLOSE_BOX,
                size=(500, 350),
            )
            self._service = svc
            self.log_callback = log_cb
            self._build_ui()
            self._refresh()
            # Set initial focus to the list so screen readers announce the queue.
            self.transfer_list.SetFocus()

            # Auto-refresh timer (every 1 second)
            self._timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, self._on_timer, self._timer)
            self._timer.Start(1000)

            # Escape to close (hide)
            self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
            self.Bind(wx.EVT_CLOSE, self._on_close)

        def _build_ui(self):
            sizer = wx.BoxSizer(wx.VERTICAL)

            # StaticText label immediately before the list so NVDA resolves
            # "Transfer Queue" as the accessible name via HWND sibling order.
            wx.StaticText(self, label="Transfer Queue:")
            self.transfer_list = wx.ListCtrl(self, style=wx.LC_REPORT)
            self.transfer_list.InsertColumn(0, "File", width=200)
            self.transfer_list.InsertColumn(1, "Direction", width=80)
            self.transfer_list.InsertColumn(2, "Progress", width=80)
            self.transfer_list.InsertColumn(3, "Status", width=100)
            sizer.Add(self.transfer_list, 1, wx.EXPAND | wx.ALL, 8)

            btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
            # Full label gives screen reader users context without needing to read
            # surrounding UI ("Retry Selected Transfer" vs the ambiguous "Retry").
            self.retry_btn = wx.Button(self, label="&Retry Selected Transfer")
            self.retry_btn.Enable(False)
            self.cancel_btn = wx.Button(self, label="Cancel &Transfer")
            self.remove_btn = wx.Button(self, label="&Remove Transfer")
            self.bg_btn = wx.Button(self, label="Send to &Background")
            self.close_btn = wx.Button(self, wx.ID_CLOSE, label="&Close")
            self.close_btn.SetDefault()
            btn_sizer.Add(self.retry_btn, 0, wx.RIGHT, 8)
            btn_sizer.Add(self.cancel_btn, 0, wx.RIGHT, 8)
            btn_sizer.Add(self.remove_btn, 0, wx.RIGHT, 8)
            btn_sizer.Add(self.bg_btn, 0, wx.RIGHT, 8)
            btn_sizer.Add(self.close_btn, 0)
            sizer.Add(btn_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 8)

            self.SetSizer(sizer)

            self.retry_btn.Bind(wx.EVT_BUTTON, self._on_retry)
            self.cancel_btn.Bind(wx.EVT_BUTTON, self._on_cancel)
            self.remove_btn.Bind(wx.EVT_BUTTON, self._on_remove)
            self.bg_btn.Bind(wx.EVT_BUTTON, self._on_send_to_background)
            self.close_btn.Bind(wx.EVT_BUTTON, lambda e: self.Close())

        # -- event handlers --

        def _on_key(self, event):
            if event.GetKeyCode() == wx.WXK_ESCAPE:
                self.Close()
            else:
                event.Skip()

        def _on_close(self, event):
            """Hide instead of destroying — transfer keeps running."""
            self._timer.Stop()
            # Clear parent's reference so a new one can be created
            parent = self.GetParent()
            if parent and hasattr(parent, "_transfer_dlg"):
                parent._transfer_dlg = None
            self.Destroy()

        def _on_send_to_background(self, event):
            """Hide the dialog; transfer continues in background."""
            parent = self.GetParent()
            self.Hide()
            # Return keyboard focus to the main window so the screen reader
            # user does not lose their place after the dialog disappears.
            if parent:
                parent.SetFocus()

        def _on_timer(self, event):
            self._refresh()

        def _get_selected_job_id(self):
            """Return selected job id, if any."""
            idx = self.transfer_list.GetFirstSelected()
            try:
                idx = int(idx)
            except (TypeError, ValueError):
                return None
            if idx == wx.NOT_FOUND:
                return None
            jobs = self._service.jobs
            if 0 <= idx < len(jobs):
                return jobs[idx].id
            return None

        def _on_retry(self, event):
            idx = self.transfer_list.GetFirstSelected()
            if idx == wx.NOT_FOUND:
                return
            jobs = self._service.jobs
            if not (0 <= idx < len(jobs)):
                return
            job = jobs[idx]
            if job.status != TransferStatus.FAILED:
                return
            parent = self.GetParent()
            client = getattr(parent, "_client", None) if parent else None
            if client is None or not bool(getattr(client, "connected", False)):
                return
            new_job = self._service.retry(job.id, client)
            if new_job is not None:
                wx.CallAfter(self._refresh)
                filename = PurePosixPath(job.source).name or os.path.basename(job.destination)
                direction_label = job.direction.value
                status_message = f"Retrying {direction_label} of {filename}"
                announce = getattr(parent, "_announce", None) if parent else None
                if callable(announce):
                    announce(status_message)
                update_status = getattr(parent, "_update_status", None) if parent else None
                if callable(update_status):
                    current_path = ""
                    if client is not None and bool(getattr(client, "connected", False)):
                        cwd = getattr(client, "cwd", "")
                        if isinstance(cwd, str):
                            current_path = cwd
                    update_status(status_message, current_path)
            self._refresh()

        def _on_cancel(self, event):
            idx = self.transfer_list.GetFirstSelected()
            if idx == wx.NOT_FOUND:
                return
            jobs = self._service.jobs
            if 0 <= idx < len(jobs):
                job = jobs[idx]
                self._service.cancel(job.id)
                filename = PurePosixPath(job.source).name or os.path.basename(job.destination)
                parent = self.GetParent()
                status_message = (
                    f"Cancelled transfer: {filename}" if filename else "Cancelled transfer."
                )
                announce = getattr(parent, "_announce", None) if parent else None
                if callable(announce):
                    announce(status_message)
                update_status = getattr(parent, "_update_status", None) if parent else None
                if callable(update_status):
                    current_path = ""
                    client = getattr(parent, "_client", None)
                    if client is not None and bool(getattr(client, "connected", False)):
                        cwd = getattr(client, "cwd", "")
                        if isinstance(cwd, str):
                            current_path = cwd
                    update_status(status_message, current_path)
                self._refresh()

        def _on_remove(self, event):
            idx = self.transfer_list.GetFirstSelected()
            if idx == wx.NOT_FOUND:
                return
            jobs = self._service.jobs
            if 0 <= idx < len(jobs):
                job = jobs[idx]
                removed = self._service.remove_job(job.id)
                if not removed:
                    parent = self.GetParent()
                    announce = getattr(parent, "_announce", None) if parent else None
                    if callable(announce):
                        announce("Cannot remove an active transfer. Cancel it first.")
                self._refresh()

        def _refresh(self):
            jobs = self._service.jobs
            selected = self.transfer_list.GetFirstSelected()
            focused = self.transfer_list.GetFocusedItem()
            try:
                selected = int(selected)
            except (TypeError, ValueError):
                selected = wx.NOT_FOUND
            try:
                focused = int(focused)
            except (TypeError, ValueError):
                focused = wx.NOT_FOUND

            current_count = self.transfer_list.GetItemCount()
            new_count = len(jobs)

            for i, j in enumerate(jobs):
                name = PurePosixPath(j.source).name if j.source else ""
                display_status = (
                    f"{j.progress}%" if j.status == TransferStatus.IN_PROGRESS else j.status.value
                )
                cols = [name, j.direction.value, f"{j.progress}%", display_status]
                if i >= current_count:
                    row = self.transfer_list.InsertItem(i, cols[0])
                    for col_idx in range(1, len(cols)):
                        self.transfer_list.SetItem(row, col_idx, cols[col_idx])
                else:
                    for col_idx, val in enumerate(cols):
                        existing = self.transfer_list.GetItemText(i, col_idx)
                        if existing != val:
                            self.transfer_list.SetItem(i, col_idx, val)

            for i in range(current_count - 1, new_count - 1, -1):
                self.transfer_list.DeleteItem(i)

            if 0 <= selected < new_count:
                self.transfer_list.Select(selected)
            if 0 <= focused < new_count:
                self.transfer_list.Focus(focused)

            # Enable retry button only when a failed transfer is selected
            self._update_retry_btn_state()

        def _update_retry_btn_state(self):
            """Enable retry button only when a failed transfer is selected."""
            idx = self.transfer_list.GetFirstSelected()
            try:
                idx = int(idx)
            except (TypeError, ValueError):
                idx = -1
            jobs = self._service.jobs
            enable = False
            if 0 <= idx < len(jobs):
                status = getattr(jobs[idx], "status", None)
                if status == TransferStatus.FAILED:
                    enable = True
            self.retry_btn.Enable(enable)

    return TransferDialog(parent, transfer_service, log_cb=log_callback)
