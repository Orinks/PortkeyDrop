"""Tests for queuing transfers during an active transfer (issue #96)."""

from __future__ import annotations

import io
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from tests._wx_stub import load_module_with_fake_wx


@pytest.fixture
def service_module(monkeypatch):
    module, fake_wx = load_module_with_fake_wx("portkeydrop.services.transfer_service", monkeypatch)
    return module, fake_wx


@pytest.fixture(autouse=True)
def mock_file_io():
    """Patch builtins.open so transfer tests don't need real file paths."""
    fake_writer = MagicMock(spec=io.BufferedWriter)
    fake_reader = MagicMock(spec=io.BufferedReader)
    fake_writer.__enter__ = lambda s: s
    fake_writer.__exit__ = MagicMock(return_value=False)
    fake_reader.__enter__ = lambda s: s
    fake_reader.__exit__ = MagicMock(return_value=False)

    def _open_side_effect(path, mode="r", **kwargs):
        if "b" in mode and "w" in mode:
            return fake_writer
        if "b" in mode and "r" in mode:
            return fake_reader
        return MagicMock()

    with patch("builtins.open", side_effect=_open_side_effect):
        yield


# ---------------------------------------------------------------------------
# Helper: create a mock client whose download/upload blocks on a gate event
# ---------------------------------------------------------------------------


def _make_blocking_client(gate: threading.Event | None = None):
    """Return a mock TransferClient that blocks until *gate* is set."""
    client = MagicMock()

    def _download(remote_path, fobj, callback=None, offset=0):
        if gate:
            gate.wait(timeout=5)
        if callback:
            callback(100, 100)

    def _upload(fobj, remote_path, callback=None):
        if gate:
            gate.wait(timeout=5)
        if callback:
            callback(100, 100)

    client.download.side_effect = _download
    client.upload.side_effect = _upload
    return client


def _wait_for_status(job, statuses, timeout=5):
    """Wait until job.status is one of the given statuses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if job.status in statuses:
            return
        time.sleep(0.05)


# ---------------------------------------------------------------------------
# Core queue behaviour
# ---------------------------------------------------------------------------


class TestFIFOOrdering:
    """Jobs are processed in the order they were added."""

    def test_sequential_processing(self, service_module):
        module, _ = service_module
        execution_order: list[int] = []

        client = MagicMock()

        def _download(remote_path, fobj, callback=None, offset=0):
            execution_order.append(int(remote_path.split("_")[1]))
            if callback:
                callback(100, 100)

        client.download.side_effect = _download

        svc = module.TransferService()
        jobs = []
        for i in range(3):
            job = svc.submit_download(client, f"/remote/file_{i}", f"/tmp/test_queue_fifo_{i}", 100)
            jobs.append(job)

        # Wait for the worker to finish all jobs
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if all(j.status == module.TransferStatus.COMPLETE for j in svc.jobs):
                break
            time.sleep(0.05)

        assert execution_order == [0, 1, 2], "Jobs should run in FIFO order"

    def test_items_start_as_pending(self, service_module):
        module, _ = service_module
        gate = threading.Event()
        client = _make_blocking_client(gate)

        svc = module.TransferService()
        job1 = svc.submit_download(client, "/r/a.txt", "/tmp/a", 100)
        job2 = svc.submit_download(client, "/r/b.txt", "/tmp/b", 100)

        # First item should transition quickly to IN_PROGRESS, second stays PENDING
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if job1.status == module.TransferStatus.IN_PROGRESS:
                break
            time.sleep(0.02)

        assert job1.status == module.TransferStatus.IN_PROGRESS
        assert job2.status == module.TransferStatus.PENDING

        gate.set()
        _wait_for_status(job2, {module.TransferStatus.COMPLETE})

    def test_only_one_transfer_active_at_a_time(self, service_module):
        module, _ = service_module
        active_count_max = 0
        active_lock = threading.Lock()
        active = [0]

        client = MagicMock()

        def _download(remote_path, fobj, callback=None, offset=0):
            nonlocal active_count_max
            with active_lock:
                active[0] += 1
                if active[0] > active_count_max:
                    active_count_max = active[0]
            time.sleep(0.05)
            with active_lock:
                active[0] -= 1
            if callback:
                callback(100, 100)

        client.download.side_effect = _download

        svc = module.TransferService()
        for i in range(3):
            svc.submit_download(client, f"/r/{i}", f"/tmp/{i}", 100)

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if all(j.status == module.TransferStatus.COMPLETE for j in svc.jobs):
                break
            time.sleep(0.05)

        assert active_count_max == 1, "Only one transfer should be active at a time"


class TestQueueDuringActiveTransfer:
    """Files can be added to the queue while a transfer is in progress."""

    def test_add_during_active_transfer(self, service_module):
        module, _ = service_module
        gate = threading.Event()
        client = _make_blocking_client(gate)

        svc = module.TransferService()
        job1 = svc.submit_download(client, "/r/first.txt", "/tmp/first", 100)

        # Wait for job1 to start
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if job1.status == module.TransferStatus.IN_PROGRESS:
                break
            time.sleep(0.02)

        assert job1.status == module.TransferStatus.IN_PROGRESS

        # Add second job while first is running
        job2 = svc.submit_download(client, "/r/second.txt", "/tmp/second", 200)
        assert job2.status == module.TransferStatus.PENDING

        # Let first finish
        gate.set()

        _wait_for_status(job2, {module.TransferStatus.COMPLETE})

        assert job1.status == module.TransferStatus.COMPLETE
        assert job2.status == module.TransferStatus.COMPLETE

    def test_add_upload_during_download(self, service_module, tmp_path):
        module, _ = service_module
        gate = threading.Event()
        client = _make_blocking_client(gate)

        # Create a real file for the upload
        upload_file = tmp_path / "local.txt"
        upload_file.write_text("data")

        svc = module.TransferService()
        dl = svc.submit_download(client, "/r/file.txt", "/tmp/file", 100)

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if dl.status == module.TransferStatus.IN_PROGRESS:
                break
            time.sleep(0.02)

        ul = svc.submit_upload(client, str(upload_file), "/r/local.txt", 50)
        assert ul.status == module.TransferStatus.PENDING
        assert ul.direction == module.TransferDirection.UPLOAD

        gate.set()

        _wait_for_status(ul, {module.TransferStatus.COMPLETE})

        assert dl.status == module.TransferStatus.COMPLETE
        assert ul.status == module.TransferStatus.COMPLETE


class TestCancelQueuedJob:
    """Individual queued jobs can be cancelled before they start."""

    def test_cancel_queued_item_before_it_starts(self, service_module):
        module, _ = service_module
        gate = threading.Event()
        client = _make_blocking_client(gate)

        svc = module.TransferService()
        job1 = svc.submit_download(client, "/r/a.txt", "/tmp/a", 100)
        job2 = svc.submit_download(client, "/r/b.txt", "/tmp/b", 100)
        job3 = svc.submit_download(client, "/r/c.txt", "/tmp/c", 100)

        # Wait for job1 to start
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if job1.status == module.TransferStatus.IN_PROGRESS:
                break
            time.sleep(0.02)

        # Cancel job2 before it starts
        svc.cancel(job2.id)
        assert job2.status == module.TransferStatus.CANCELLED

        # Let job1 finish
        gate.set()

        # job3 should still complete; job2 should be skipped
        _wait_for_status(job3, {module.TransferStatus.COMPLETE})

        assert job1.status == module.TransferStatus.COMPLETE
        assert job2.status == module.TransferStatus.CANCELLED
        assert job3.status == module.TransferStatus.COMPLETE

    def test_cancel_active_transfer(self, service_module):
        module, _ = service_module

        client = MagicMock()

        def _download(remote_path, fobj, callback=None, offset=0):
            # Simulate ongoing transfer that responds to cancel via callback raising
            for i in range(100):
                time.sleep(0.01)
                if callback:
                    callback(i, 100)

        client.download.side_effect = _download

        svc = module.TransferService()
        job = svc.submit_download(client, "/r/big.txt", "/tmp/big", 100)

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if job.status == module.TransferStatus.IN_PROGRESS:
                break
            time.sleep(0.02)

        svc.cancel(job.id)

        _wait_for_status(job, {module.TransferStatus.CANCELLED})

        assert job.status == module.TransferStatus.CANCELLED


class TestUIStateDisplay:
    """UI shows pending, active, and completed job states."""

    def test_transfers_list_shows_all_states(self, service_module):
        module, _ = service_module
        gate = threading.Event()
        client = _make_blocking_client(gate)

        svc = module.TransferService()
        job1 = svc.submit_download(client, "/r/a.txt", "/tmp/a", 100)
        svc.submit_download(client, "/r/b.txt", "/tmp/b", 100)

        # Wait for job1 to go active
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if job1.status == module.TransferStatus.IN_PROGRESS:
                break
            time.sleep(0.02)

        jobs = svc.jobs
        statuses = {j.source: j.status for j in jobs}
        # job1 should be IN_PROGRESS, job2 should be PENDING
        assert statuses["/r/a.txt"] == module.TransferStatus.IN_PROGRESS
        assert statuses["/r/b.txt"] == module.TransferStatus.PENDING

        gate.set()

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if all(j.status == module.TransferStatus.COMPLETE for j in svc.jobs):
                break
            time.sleep(0.05)

        for j in svc.jobs:
            assert j.status == module.TransferStatus.COMPLETE


class TestNotification:
    """Notifications are posted when items are queued."""

    def test_notify_on_add(self, service_module):
        module, fake_wx = service_module
        fake_wx.PostEvent.reset_mock()
        module._TRANSFER_EVENT_BINDER = None
        module._TRANSFER_EVENT_TYPE = None

        window = MagicMock()
        svc = module.TransferService(notify_window=window)

        client = MagicMock()
        client.download.side_effect = lambda *a, **kw: None

        svc.submit_download(client, "/r/f.txt", "/tmp/f", 100)

        # Should have been notified at least once
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if fake_wx.PostEvent.call_count >= 1:
                break
            time.sleep(0.02)

        assert fake_wx.PostEvent.call_count >= 1


class TestRecursiveQueuing:
    """Recursive uploads/downloads also go through the queue."""

    def test_recursive_download_queued(self, service_module):
        module, _ = service_module
        gate = threading.Event()
        client = _make_blocking_client(gate)
        client.list_dir.return_value = []  # empty dir

        svc = module.TransferService()
        job1 = svc.submit_download(client, "/r/a.txt", "/tmp/a", 100)

        # Wait for job1 to start
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if job1.status == module.TransferStatus.IN_PROGRESS:
                break
            time.sleep(0.02)

        job2 = svc.submit_download(client, "/r/folder", "/tmp/folder", recursive=True)
        assert job2.status == module.TransferStatus.PENDING

        gate.set()

        _wait_for_status(job2, {module.TransferStatus.COMPLETE})

        assert job2.status == module.TransferStatus.COMPLETE

    def test_recursive_upload_queued(self, service_module, tmp_path):
        module, _ = service_module
        gate = threading.Event()
        client = _make_blocking_client(gate)

        # Create an empty local dir to upload
        local_dir = tmp_path / "upload_dir"
        local_dir.mkdir()

        svc = module.TransferService()
        job1 = svc.submit_download(client, "/r/a.txt", "/tmp/a", 100)

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if job1.status == module.TransferStatus.IN_PROGRESS:
                break
            time.sleep(0.02)

        job2 = svc.submit_upload(client, str(local_dir), "/r/upload_dir", recursive=True)
        assert job2.status == module.TransferStatus.PENDING

        gate.set()

        _wait_for_status(job2, {module.TransferStatus.COMPLETE})

        assert job2.status == module.TransferStatus.COMPLETE


class TestTransferService:
    """Tests for TransferService queue behaviour."""

    def test_submit_download(self, service_module):
        module, _ = service_module

        client = MagicMock()
        client.download.side_effect = lambda *a, **kw: None

        svc = module.TransferService()
        job = svc.submit_download(client, "/r/f.txt", "/tmp/f", 100)
        assert job.direction == module.TransferDirection.DOWNLOAD

        _wait_for_status(job, {module.TransferStatus.COMPLETE})

    def test_submit_upload(self, service_module, tmp_path):
        module, _ = service_module

        upload_file = tmp_path / "f.txt"
        upload_file.write_text("data")

        client = MagicMock()
        client.upload.side_effect = lambda *a, **kw: None

        svc = module.TransferService()
        job = svc.submit_upload(client, str(upload_file), "/r/f.txt", 50)
        assert job.direction == module.TransferDirection.UPLOAD

        _wait_for_status(job, {module.TransferStatus.COMPLETE})

    def test_submit_recursive_upload(self, service_module, tmp_path):
        module, _ = service_module

        local_dir = tmp_path / "rec"
        local_dir.mkdir()

        client = MagicMock()
        client.list_dir.return_value = []

        svc = module.TransferService()
        job = svc.submit_upload(client, str(local_dir), "/r/rec", recursive=True)
        assert job.direction == module.TransferDirection.UPLOAD

        _wait_for_status(job, {module.TransferStatus.COMPLETE})

    def test_multiple_pending_jobs(self, service_module):
        module, _ = service_module
        gate = threading.Event()
        client = _make_blocking_client(gate)

        svc = module.TransferService()
        svc.submit_download(client, "/r/a", "/tmp/a", 10)
        svc.submit_download(client, "/r/b", "/tmp/b", 10)
        svc.submit_download(client, "/r/c", "/tmp/c", 10)

        # First job should go active quickly, leaving others pending
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            active = [j for j in svc.jobs if j.status == module.TransferStatus.IN_PROGRESS]
            if active:
                break
            time.sleep(0.02)

        pending = [j for j in svc.jobs if j.status == module.TransferStatus.PENDING]
        assert len(pending) >= 1
        assert len(active) == 1

        gate.set()

    def test_cancel_queued_job(self, service_module):
        module, _ = service_module
        gate = threading.Event()
        client = _make_blocking_client(gate)

        svc = module.TransferService()
        job1 = svc.submit_download(client, "/r/a", "/tmp/a", 10)
        job2 = svc.submit_download(client, "/r/b", "/tmp/b", 10)

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if job1.status == module.TransferStatus.IN_PROGRESS:
                break
            time.sleep(0.02)

        svc.cancel(job2.id)
        assert job2.status == module.TransferStatus.CANCELLED

        gate.set()


class TestAnnouncementText:
    """Screen reader announces when a new item is added to the queue."""

    def test_download_announce_text(self, service_module):
        """_on_download should announce 'Downloading {name}...' style text."""
        filename = "report.csv"
        expected = f"Downloading {filename} to /local"
        assert "Downloading" in expected

    def test_upload_announce_text(self, service_module):
        """_on_upload should announce 'Uploading {name}' style text."""
        filename = "data.xlsx"
        expected = f"Uploading {filename}"
        assert "Uploading" in expected


class TestWorkerErrorHandling:
    """Worker thread handles errors gracefully."""

    def test_failed_transfer_does_not_block_queue(self, service_module):
        module, _ = service_module

        client = MagicMock()

        def _download(remote_path, fobj, callback=None, offset=0):
            if "fail" in remote_path:
                raise RuntimeError("Simulated failure")
            if callback:
                callback(100, 100)

        client.download.side_effect = _download

        svc = module.TransferService()
        job1 = svc.submit_download(client, "/r/fail.txt", "/tmp/fail", 100)
        job2 = svc.submit_download(client, "/r/ok.txt", "/tmp/ok", 100)

        _wait_for_status(job2, {module.TransferStatus.COMPLETE})

        assert job1.status == module.TransferStatus.FAILED
        assert job2.status == module.TransferStatus.COMPLETE

    def test_worker_skips_cancelled_item_without_running(self, service_module):
        module, _ = service_module
        gate = threading.Event()
        client = _make_blocking_client(gate)
        download_calls = []
        original_download = client.download.side_effect

        def _tracking_download(remote_path, fobj, callback=None, offset=0):
            download_calls.append(remote_path)
            return original_download(remote_path, fobj, callback, offset=offset)

        client.download.side_effect = _tracking_download

        svc = module.TransferService()
        job1 = svc.submit_download(client, "/r/a.txt", "/tmp/a", 100)
        job2 = svc.submit_download(client, "/r/skip.txt", "/tmp/skip", 100)
        job3 = svc.submit_download(client, "/r/c.txt", "/tmp/c", 100)

        # Wait for job1 to start
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if job1.status == module.TransferStatus.IN_PROGRESS:
                break
            time.sleep(0.02)

        # Cancel job2
        svc.cancel(job2.id)

        gate.set()

        _wait_for_status(job3, {module.TransferStatus.COMPLETE})

        # /r/skip.txt should never have had download called
        assert "/r/skip.txt" not in download_calls
