"""Transfer queue dialog for AccessiTransfer."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from accessitransfer.protocols import TransferClient


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
                style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
                size=(500, 350),
            )
            self._transfer_manager = tm
            self._build_ui()
            self._refresh()
            self.SetName("Transfer Queue Dialog")

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
