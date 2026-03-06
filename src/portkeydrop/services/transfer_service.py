"""Transfer service — owns queue, worker thread, and job lifecycle.

TransferDialog is a disposable observer; closing it never cancels a transfer.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from portkeydrop.protocols import TransferClient

logger = logging.getLogger(__name__)

# Lazy wx event plumbing (created once on first use)
_TRANSFER_EVENT_BINDER: Any | None = None
_TRANSFER_EVENT_TYPE: Any | None = None


class TransferDirection(Enum):
    UPLOAD = "upload"
    DOWNLOAD = "download"


class TransferStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RESTORED = "pending (restored)"


@dataclass
class TransferJob:
    """Represents a single queued transfer."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    direction: TransferDirection = TransferDirection.DOWNLOAD
    source: str = ""
    destination: str = ""
    protocol: str = ""
    status: TransferStatus = TransferStatus.PENDING
    error: str | None = None
    progress: int = 0  # 0-100
    total_bytes: int = 0
    transferred_bytes: int = 0
    cancel_event: threading.Event = field(default_factory=threading.Event)
    # Internal: client + recursive flag (not part of the public data model)
    _client: TransferClient | None = field(default=None, repr=False)
    _recursive: bool = field(default=False, repr=False)

    def to_dict(self) -> dict:
        """Serialize to a dict for JSON persistence. Excludes client/event fields."""
        return {
            "id": self.id,
            "direction": self.direction.value,
            "source": self.source,
            "destination": self.destination,
            "protocol": self.protocol,
            "total_bytes": self.total_bytes,
            "transferred_bytes": self.transferred_bytes,
            "status": self.status.value,
            "error": self.error or "",
        }

    @classmethod
    def from_dict(cls, data: dict) -> TransferJob:
        """Deserialize from a dict. Restored jobs always get RESTORED status."""
        return cls(
            id=data.get("id") or uuid.uuid4().hex,
            direction=TransferDirection(data.get("direction", "download")),
            source=data.get("source", ""),
            destination=data.get("destination", ""),
            protocol=data.get("protocol", ""),
            total_bytes=data.get("total_bytes", 0),
            transferred_bytes=data.get("transferred_bytes", 0),
            status=TransferStatus.RESTORED,
            error=data.get("error") or None,
        )


class TransferService:
    """Owns the transfer queue and a single daemon worker thread."""

    def __init__(self, notify_window: Any | None = None) -> None:
        self._notify_window = notify_window
        self._queue: queue.Queue[TransferJob] = queue.Queue()
        self._jobs: list[TransferJob] = []
        self._lock = threading.Lock()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def jobs(self) -> list[TransferJob]:
        with self._lock:
            return list(self._jobs)

    def submit_download(
        self,
        client: TransferClient,
        remote_path: str,
        local_path: str,
        total_bytes: int = 0,
        *,
        recursive: bool = False,
    ) -> TransferJob:
        job = TransferJob(
            direction=TransferDirection.DOWNLOAD,
            source=remote_path,
            destination=local_path,
            protocol=getattr(client, "_protocol_name", "sftp"),
            total_bytes=total_bytes,
            _client=client,
            _recursive=recursive,
        )
        self._enqueue(job)
        return job

    def submit_upload(
        self,
        client: TransferClient,
        local_path: str,
        remote_path: str,
        total_bytes: int = 0,
        *,
        recursive: bool = False,
    ) -> TransferJob:
        job = TransferJob(
            direction=TransferDirection.UPLOAD,
            source=local_path,
            destination=remote_path,
            protocol=getattr(client, "_protocol_name", "sftp"),
            total_bytes=total_bytes,
            _client=client,
            _recursive=recursive,
        )
        self._enqueue(job)
        return job

    def restore_jobs(self, jobs: list[TransferJob]) -> None:
        """Add restored jobs to the job list without starting transfers."""
        with self._lock:
            self._jobs.extend(jobs)
        self._post_event()

    def cancel(self, job_id: str) -> None:
        with self._lock:
            for j in self._jobs:
                if j.id == job_id:
                    j.cancel_event.set()
                    if j.status in (TransferStatus.PENDING, TransferStatus.RESTORED):
                        j.status = TransferStatus.CANCELLED
                    break
        self._post_event()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _enqueue(self, job: TransferJob) -> None:
        with self._lock:
            self._jobs.append(job)
        self._queue.put(job)
        self._post_event()

    def _worker_loop(self) -> None:
        while True:
            job = self._queue.get()
            if job.cancel_event.is_set():
                job.status = TransferStatus.CANCELLED
                self._post_event()
                continue
            try:
                job.status = TransferStatus.IN_PROGRESS
                self._post_event()
                if job.direction == TransferDirection.DOWNLOAD:
                    if job._recursive:
                        self._run_recursive_download(job)
                    else:
                        self._run_download(job)
                else:
                    if job._recursive:
                        self._run_recursive_upload(job)
                    else:
                        self._run_upload(job)
                if job.status == TransferStatus.IN_PROGRESS:
                    job.status = TransferStatus.COMPLETE
            except InterruptedError:
                job.status = TransferStatus.CANCELLED
            except Exception as exc:
                job.status = TransferStatus.FAILED
                job.error = str(exc)
                logger.exception("Transfer failed: %s", job.id)
            self._update_progress(job)
            self._post_event()

    # --- single-file transfers ---

    def _run_download(self, job: TransferJob) -> None:
        assert job._client is not None
        with open(job.destination, "wb") as f:

            def _cb(transferred: int, total: int) -> None:
                if job.cancel_event.is_set():
                    raise InterruptedError("Transfer cancelled")
                job.transferred_bytes = transferred
                if total > 0:
                    job.total_bytes = total
                self._update_progress(job)
                self._post_event()

            job._client.download(job.source, f, callback=_cb)

    def _run_upload(self, job: TransferJob) -> None:
        assert job._client is not None
        with open(job.source, "rb") as f:

            def _cb(transferred: int, total: int) -> None:
                if job.cancel_event.is_set():
                    raise InterruptedError("Transfer cancelled")
                job.transferred_bytes = transferred
                if total > 0:
                    job.total_bytes = total
                self._update_progress(job)
                self._post_event()

            job._client.upload(f, job.destination, callback=_cb)

    # --- recursive transfers ---

    def _run_recursive_download(self, job: TransferJob) -> None:
        assert job._client is not None
        client = job._client
        file_queue: list[tuple[str, str, int]] = []
        self._collect_remote_files(client, job.source, job.destination, file_queue)
        # Re-stat zero-size entries (symlink targets)
        for i, (remote_file, local_file, size) in enumerate(file_queue):
            if size == 0:
                try:
                    real_size = client.stat(remote_file).size
                    if real_size > 0:
                        file_queue[i] = (remote_file, local_file, real_size)
                except Exception:
                    pass
        job.total_bytes = sum(s for _, _, s in file_queue)
        job.transferred_bytes = 0
        self._update_progress(job)
        self._post_event()

        for remote_file, local_file, _size in file_queue:
            if job.cancel_event.is_set():
                raise InterruptedError("Transfer cancelled")
            os.makedirs(os.path.dirname(local_file), exist_ok=True)
            base = job.transferred_bytes
            with open(local_file, "wb") as f:

                def _cb(transferred: int, total: int, _base=base) -> None:
                    if job.cancel_event.is_set():
                        raise InterruptedError("Transfer cancelled")
                    job.transferred_bytes = _base + transferred
                    self._update_progress(job)
                    self._post_event()

                client.download(remote_file, f, callback=_cb)

    def _run_recursive_upload(self, job: TransferJob) -> None:
        assert job._client is not None
        client = job._client
        file_queue: list[tuple[str, str, int]] = []
        self._collect_local_files(job.source, job.destination, file_queue)
        job.total_bytes = sum(s for _, _, s in file_queue)
        job.transferred_bytes = 0
        self._update_progress(job)
        self._post_event()

        # Create directories
        dirs_to_create: set[str] = set()
        for _, remote_file, _ in file_queue:
            remote_parent = os.path.dirname(remote_file).replace("\\", "/")
            while remote_parent and remote_parent != job.destination:
                dirs_to_create.add(remote_parent)
                remote_parent = os.path.dirname(remote_parent).replace("\\", "/")
        for d in sorted(dirs_to_create):
            try:
                client.mkdir(d)
            except Exception:
                pass

        for local_file, remote_file, _size in file_queue:
            if job.cancel_event.is_set():
                raise InterruptedError("Transfer cancelled")
            base = job.transferred_bytes
            with open(local_file, "rb") as f:

                def _cb(transferred: int, total: int, _base=base) -> None:
                    if job.cancel_event.is_set():
                        raise InterruptedError("Transfer cancelled")
                    job.transferred_bytes = _base + transferred
                    self._update_progress(job)
                    self._post_event()

                client.upload(f, remote_file, callback=_cb)

    # --- helpers ---

    def _collect_remote_files(
        self,
        client: TransferClient,
        remote_dir: str,
        local_dir: str,
        file_queue: list[tuple[str, str, int]],
    ) -> None:
        for entry in client.list_dir(remote_dir):
            if entry.name in (".", ".."):
                continue
            local_path = os.path.join(local_dir, entry.name)
            if entry.is_dir:
                self._collect_remote_files(client, entry.path, local_path, file_queue)
            else:
                file_queue.append((entry.path, local_path, entry.size))

    def _collect_local_files(
        self,
        local_dir: str,
        remote_dir: str,
        file_queue: list[tuple[str, str, int]],
    ) -> None:
        for entry in os.scandir(local_dir):
            remote_path = f"{remote_dir.rstrip('/')}/{entry.name}"
            if entry.is_dir(follow_symlinks=True):
                self._collect_local_files(entry.path, remote_path, file_queue)
            elif entry.is_file(follow_symlinks=True):
                file_queue.append((entry.path, remote_path, entry.stat().st_size))

    @staticmethod
    def _update_progress(job: TransferJob) -> None:
        if job.total_bytes > 0:
            job.progress = min(100, int(job.transferred_bytes * 100 / job.total_bytes))
        else:
            job.progress = 0

    def _post_event(self) -> None:
        if self._notify_window is None:
            return
        try:
            import wx

            _binder, evt_type = _get_wx_event_binder()
            evt = wx.PyCommandEvent(evt_type, -1)
            wx.PostEvent(self._notify_window, evt)
        except Exception:
            pass


# ------------------------------------------------------------------
# wx event helpers (lazy)
# ------------------------------------------------------------------


def _get_wx_event_binder():
    global _TRANSFER_EVENT_BINDER, _TRANSFER_EVENT_TYPE
    if _TRANSFER_EVENT_BINDER is not None and _TRANSFER_EVENT_TYPE is not None:
        return _TRANSFER_EVENT_BINDER, _TRANSFER_EVENT_TYPE
    import wx

    _TRANSFER_EVENT_TYPE = wx.NewEventType()
    _TRANSFER_EVENT_BINDER = wx.PyEventBinder(_TRANSFER_EVENT_TYPE, 1)
    return _TRANSFER_EVENT_BINDER, _TRANSFER_EVENT_TYPE


def get_transfer_event_binder():
    binder, _event_type = _get_wx_event_binder()
    return binder
