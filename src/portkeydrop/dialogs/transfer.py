"""Transfer queue dialog for Portkey Drop."""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from portkeydrop.protocols import TransferClient

logger = logging.getLogger(__name__)


class TransferDirection(Enum):
    UPLOAD = "upload"
    DOWNLOAD = "download"


class TransferStatus(Enum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TransferItem:
    """Represents a single transfer."""

    id: int = 0
    direction: TransferDirection = TransferDirection.DOWNLOAD
    remote_path: str = ""
    local_path: str = ""
    total_bytes: int = 0
    transferred_bytes: int = 0
    status: TransferStatus = TransferStatus.QUEUED
    error: str = ""
    cancel_event: threading.Event = field(default_factory=threading.Event)

    @property
    def progress_pct(self) -> int:
        if self.total_bytes <= 0:
            return 0
        return min(100, int(self.transferred_bytes * 100 / self.total_bytes))

    @property
    def display_status(self) -> str:
        if self.status == TransferStatus.IN_PROGRESS:
            return f"{self.progress_pct}%"
        return self.status.value


class TransferManager:
    """Manages background file transfers."""

    def __init__(self, notify_window=None) -> None:
        self._transfers: list[TransferItem] = []
        self._next_id = 1
        self._notify_window = notify_window
        self._lock = threading.Lock()

    @property
    def transfers(self) -> list[TransferItem]:
        with self._lock:
            return list(self._transfers)

    def add_download(
        self, client: TransferClient, remote_path: str, local_path: str, total_bytes: int = 0
    ) -> TransferItem:
        item = TransferItem(
            id=self._next_id,
            direction=TransferDirection.DOWNLOAD,
            remote_path=remote_path,
            local_path=local_path,
            total_bytes=total_bytes,
        )
        self._next_id += 1
        with self._lock:
            self._transfers.append(item)
        thread = threading.Thread(target=self._run_download, args=(client, item), daemon=True)
        thread.start()
        return item

    def add_upload(
        self, client: TransferClient, local_path: str, remote_path: str, total_bytes: int = 0
    ) -> TransferItem:
        item = TransferItem(
            id=self._next_id,
            direction=TransferDirection.UPLOAD,
            local_path=local_path,
            remote_path=remote_path,
            total_bytes=total_bytes,
        )
        self._next_id += 1
        with self._lock:
            self._transfers.append(item)
        thread = threading.Thread(target=self._run_upload, args=(client, item), daemon=True)
        thread.start()
        return item

    def add_recursive_download(
        self, client: TransferClient, remote_path: str, local_path: str
    ) -> TransferItem:
        """Queue a recursive folder download."""
        item = TransferItem(
            id=self._next_id,
            direction=TransferDirection.DOWNLOAD,
            remote_path=remote_path,
            local_path=local_path,
            total_bytes=0,
        )
        self._next_id += 1
        with self._lock:
            self._transfers.append(item)
        thread = threading.Thread(
            target=self._run_recursive_download, args=(client, item), daemon=True
        )
        thread.start()
        return item

    def add_recursive_upload(
        self, client: TransferClient, local_path: str, remote_path: str
    ) -> TransferItem:
        """Queue a recursive folder upload."""
        item = TransferItem(
            id=self._next_id,
            direction=TransferDirection.UPLOAD,
            local_path=local_path,
            remote_path=remote_path,
            total_bytes=0,
        )
        self._next_id += 1
        with self._lock:
            self._transfers.append(item)
        thread = threading.Thread(
            target=self._run_recursive_upload, args=(client, item), daemon=True
        )
        thread.start()
        return item

    def cancel(self, transfer_id: int) -> None:
        with self._lock:
            for t in self._transfers:
                if t.id == transfer_id:
                    t.cancel_event.set()
                    t.status = TransferStatus.CANCELLED
                    break
        self._notify()

    def _run_download(self, client: TransferClient, item: TransferItem) -> None:
        item.status = TransferStatus.IN_PROGRESS
        self._notify()
        try:
            with open(item.local_path, "wb") as f:

                def callback(transferred: int, total: int) -> None:
                    if item.cancel_event.is_set():
                        raise InterruptedError("Transfer cancelled")
                    item.transferred_bytes = transferred
                    item.total_bytes = total
                    self._notify()

                client.download(item.remote_path, f, callback=callback)
            item.status = TransferStatus.COMPLETED
        except InterruptedError:
            item.status = TransferStatus.CANCELLED
        except Exception as e:
            item.status = TransferStatus.FAILED
            item.error = str(e)
        self._notify()

    def _run_upload(self, client: TransferClient, item: TransferItem) -> None:
        item.status = TransferStatus.IN_PROGRESS
        self._notify()
        try:
            with open(item.local_path, "rb") as f:

                def callback(transferred: int, total: int) -> None:
                    if item.cancel_event.is_set():
                        raise InterruptedError("Transfer cancelled")
                    item.transferred_bytes = transferred
                    item.total_bytes = total
                    self._notify()

                client.upload(f, item.remote_path, callback=callback)
            item.status = TransferStatus.COMPLETED
        except InterruptedError:
            item.status = TransferStatus.CANCELLED
        except Exception as e:
            item.status = TransferStatus.FAILED
            item.error = str(e)
        self._notify()

    def _run_recursive_download(self, client: TransferClient, item: TransferItem) -> None:
        """Recursively download a remote directory."""

        item.status = TransferStatus.IN_PROGRESS
        self._notify()
        try:
            # Collect all files first to calculate total size
            file_queue: list[tuple[str, str, int]] = []  # (remote, local, size)
            self._collect_remote_files(client, item.remote_path, item.local_path, file_queue)
            item.total_bytes = sum(size for _, _, size in file_queue)
            item.transferred_bytes = 0
            self._notify()

            for remote_file, local_file, size in file_queue:
                if item.cancel_event.is_set():
                    raise InterruptedError("Transfer cancelled")
                os.makedirs(os.path.dirname(local_file), exist_ok=True)
                with open(local_file, "wb") as f:
                    base_transferred = item.transferred_bytes

                    def callback(transferred: int, total: int) -> None:
                        if item.cancel_event.is_set():
                            raise InterruptedError("Transfer cancelled")
                        item.transferred_bytes = base_transferred + transferred
                        self._notify()

                    client.download(remote_file, f, callback=callback)
                item.transferred_bytes = item.transferred_bytes  # ensure accurate after file done
            item.status = TransferStatus.COMPLETED
        except InterruptedError:
            item.status = TransferStatus.CANCELLED
        except Exception as e:
            item.status = TransferStatus.FAILED
            item.error = str(e)
            logger.exception("Recursive download failed: %s", item.remote_path)
        self._notify()

    def _collect_remote_files(
        self,
        client: TransferClient,
        remote_dir: str,
        local_dir: str,
        file_queue: list[tuple[str, str, int]],
    ) -> None:
        """Walk a remote directory tree and collect files to download."""
        for entry in client.list_dir(remote_dir):
            if entry.name in (".", ".."):
                continue
            local_path = os.path.join(local_dir, entry.name)
            if entry.is_dir:
                self._collect_remote_files(client, entry.path, local_path, file_queue)
            else:
                file_queue.append((entry.path, local_path, entry.size))

    def _run_recursive_upload(self, client: TransferClient, item: TransferItem) -> None:
        """Recursively upload a local directory."""
        item.status = TransferStatus.IN_PROGRESS
        self._notify()
        try:
            # Collect all files first
            file_queue: list[tuple[str, str, int]] = []  # (local, remote, size)
            self._collect_local_files(item.local_path, item.remote_path, file_queue)
            item.total_bytes = sum(size for _, _, size in file_queue)
            item.transferred_bytes = 0
            self._notify()

            # Collect directories to create
            dirs_to_create: set[str] = set()
            for _, remote_file, _ in file_queue:
                remote_parent = os.path.dirname(remote_file).replace("\\", "/")
                while remote_parent and remote_parent != item.remote_path:
                    dirs_to_create.add(remote_parent)
                    remote_parent = os.path.dirname(remote_parent).replace("\\", "/")

            # Create directories (sorted so parents come first)
            for d in sorted(dirs_to_create):
                try:
                    client.mkdir(d)
                except Exception:
                    pass  # may already exist

            for local_file, remote_file, size in file_queue:
                if item.cancel_event.is_set():
                    raise InterruptedError("Transfer cancelled")
                with open(local_file, "rb") as f:
                    base_transferred = item.transferred_bytes

                    def callback(transferred: int, total: int) -> None:
                        if item.cancel_event.is_set():
                            raise InterruptedError("Transfer cancelled")
                        item.transferred_bytes = base_transferred + transferred
                        self._notify()

                    client.upload(f, remote_file, callback=callback)
            item.status = TransferStatus.COMPLETED
        except InterruptedError:
            item.status = TransferStatus.CANCELLED
        except Exception as e:
            item.status = TransferStatus.FAILED
            item.error = str(e)
            logger.exception("Recursive upload failed: %s", item.local_path)
        self._notify()

    def _collect_local_files(
        self,
        local_dir: str,
        remote_dir: str,
        file_queue: list[tuple[str, str, int]],
    ) -> None:
        """Walk a local directory tree and collect files to upload."""
        for entry in os.scandir(local_dir):
            remote_path = f"{remote_dir.rstrip('/')}/{entry.name}"
            if entry.is_dir(follow_symlinks=True):
                self._collect_local_files(entry.path, remote_path, file_queue)
            elif entry.is_file(follow_symlinks=True):
                file_queue.append((entry.path, remote_path, entry.stat().st_size))

    def _notify(self) -> None:
        if self._notify_window:
            try:
                import wx

                evt = wx.PyCommandEvent(wx.NewEventType(), -1)
                wx.PostEvent(self._notify_window, evt)
            except Exception:
                pass


def _get_wx_event_binder():
    """Lazy creation of wx event type and binder."""
    import wx

    evt_type = wx.NewEventType()
    return wx.PyEventBinder(evt_type, 1), evt_type


def create_transfer_dialog(parent, transfer_manager: TransferManager):
    """Create and return a TransferDialog. Requires wx."""
    import wx
    from pathlib import PurePosixPath

    class TransferDialog(wx.Dialog):
        """Dialog showing active and completed transfers."""

        def __init__(self, parent_win, tm):
            super().__init__(
                parent_win,
                title="Transfer Queue",
                style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.CLOSE_BOX,
                size=(500, 350),
            )
            self._transfer_manager = tm
            self._build_ui()
            self._refresh()
            self.SetName("Transfer Queue Dialog")

            # Auto-refresh timer (every 1 second)
            self._timer = wx.Timer(self)
            self.Bind(wx.EVT_TIMER, self._on_timer, self._timer)
            self._timer.Start(1000)

            # Escape to close
            self.Bind(wx.EVT_CHAR_HOOK, self._on_key)
            self.Bind(wx.EVT_CLOSE, self._on_close)

        def _build_ui(self):
            sizer = wx.BoxSizer(wx.VERTICAL)

            self.transfer_list = wx.ListCtrl(self, style=wx.LC_REPORT)
            self.transfer_list.SetName("Transfer Queue")
            self.transfer_list.InsertColumn(0, "File", width=200)
            self.transfer_list.InsertColumn(1, "Direction", width=80)
            self.transfer_list.InsertColumn(2, "Progress", width=80)
            self.transfer_list.InsertColumn(3, "Status", width=100)
            sizer.Add(self.transfer_list, 1, wx.EXPAND | wx.ALL, 8)

            btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
            self.cancel_btn = wx.Button(self, label="&Cancel Selected")
            self.cancel_btn.SetName("Cancel Selected Transfer")
            self.close_btn = wx.Button(self, wx.ID_CLOSE, label="&Close")
            btn_sizer.Add(self.cancel_btn, 0, wx.RIGHT, 8)
            btn_sizer.Add(self.close_btn, 0)
            sizer.Add(btn_sizer, 0, wx.ALL | wx.ALIGN_RIGHT, 8)

            self.SetSizer(sizer)

            self.cancel_btn.Bind(wx.EVT_BUTTON, self._on_cancel)
            self.close_btn.Bind(wx.EVT_BUTTON, lambda e: self.Close())

        def _on_key(self, event):
            if event.GetKeyCode() == wx.WXK_ESCAPE:
                self.Close()
            else:
                event.Skip()

        def _on_close(self, event):
            self._timer.Stop()
            # Clear parent's reference so a new one can be created
            parent = self.GetParent()
            if parent and hasattr(parent, "_transfer_dlg"):
                parent._transfer_dlg = None
            self.Destroy()

        def _on_timer(self, event):
            self._refresh()

        def _on_cancel(self, event):
            idx = self.transfer_list.GetFirstSelected()
            if idx == wx.NOT_FOUND:
                return
            transfers = self._transfer_manager.transfers
            if 0 <= idx < len(transfers):
                self._transfer_manager.cancel(transfers[idx].id)
                self._refresh()

        def _refresh(self):
            self.transfer_list.DeleteAllItems()
            for t in self._transfer_manager.transfers:
                name = PurePosixPath(t.remote_path).name
                idx = self.transfer_list.InsertItem(self.transfer_list.GetItemCount(), name)
                self.transfer_list.SetItem(idx, 1, t.direction.value)
                self.transfer_list.SetItem(idx, 2, f"{t.progress_pct}%")
                self.transfer_list.SetItem(idx, 3, t.display_status)

    return TransferDialog(parent, transfer_manager)
