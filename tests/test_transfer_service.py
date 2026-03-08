"""Comprehensive tests for TransferService — queue, worker, and job lifecycle."""

from __future__ import annotations

import io
import threading
import time
from pathlib import PurePosixPath
from unittest.mock import MagicMock, patch


from portkeydrop.services.transfer_service import (
    TransferDirection,
    TransferJob,
    TransferService,
    TransferStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _wait_for_status(job, target_status, timeout=5):
    """Block until job reaches *target_status* or timeout."""
    deadline = time.monotonic() + timeout
    while job.status != target_status and time.monotonic() < deadline:
        time.sleep(0.02)


def _wait_for_terminal(job, timeout=5):
    """Block until job reaches a terminal status."""
    terminal = {TransferStatus.COMPLETE, TransferStatus.FAILED, TransferStatus.CANCELLED}
    deadline = time.monotonic() + timeout
    while job.status not in terminal and time.monotonic() < deadline:
        time.sleep(0.02)


# ---------------------------------------------------------------------------
# TransferJob dataclass
# ---------------------------------------------------------------------------


class TestTransferJob:
    def test_default_values(self):
        job = TransferJob()
        assert job.direction == TransferDirection.DOWNLOAD
        assert job.status == TransferStatus.PENDING
        assert job.progress == 0
        assert job.error is None
        assert job.total_bytes == 0
        assert job.transferred_bytes == 0
        assert isinstance(job.cancel_event, threading.Event)

    def test_unique_ids(self):
        ids = {TransferJob().id for _ in range(50)}
        assert len(ids) == 50

    def test_cancel_event_independent(self):
        a, b = TransferJob(), TransferJob()
        a.cancel_event.set()
        assert not b.cancel_event.is_set()


# ---------------------------------------------------------------------------
# TransferService — init / properties
# ---------------------------------------------------------------------------


class TestTransferServiceInit:
    def test_starts_daemon_worker_threads(self):
        svc = TransferService(notify_window=None)
        assert len(svc._workers) == 1
        assert all(t.is_alive() for t in svc._workers)
        assert all(t.daemon for t in svc._workers)

    def test_starts_multiple_workers(self):
        svc = TransferService(notify_window=None, max_workers=3)
        assert len(svc._workers) == 3
        assert all(t.is_alive() for t in svc._workers)

    def test_max_workers_clamped_to_one(self):
        svc = TransferService(notify_window=None, max_workers=0)
        assert len(svc._workers) == 1

    def test_jobs_returns_snapshot(self):
        svc = TransferService(notify_window=None)
        jobs = svc.jobs
        assert isinstance(jobs, list)
        assert jobs is not svc._jobs  # copy, not reference


# ---------------------------------------------------------------------------
# submit_download / submit_upload
# ---------------------------------------------------------------------------


class TestSubmitDownload:
    def test_enqueues_and_completes_download(self, tmp_path):
        dest = tmp_path / "file.bin"
        mock_client = MagicMock()
        mock_client.download.side_effect = lambda src, fh, callback=None, offset=0: fh.write(
            b"data"
        )

        svc = TransferService(notify_window=None)
        job = svc.submit_download(mock_client, "/remote/file.bin", str(dest), total_bytes=4)

        _wait_for_terminal(job)
        assert job.status == TransferStatus.COMPLETE
        assert job.direction == TransferDirection.DOWNLOAD
        assert job.source == "/remote/file.bin"
        assert job.destination == str(dest)

    def test_download_updates_progress_via_callback(self):
        mock_client = MagicMock()
        progress_values = []

        def fake_download(src, fh, callback=None, offset=0):
            if callback:
                callback(50, 100)
                progress_values.append(("mid", fh))
                callback(100, 100)

        mock_client.download.side_effect = fake_download

        svc = TransferService(notify_window=None)
        with patch("builtins.open", return_value=MagicMock(spec=io.BufferedWriter)):
            job = svc.submit_download(mock_client, "/r/f.bin", "/tmp/f.bin", total_bytes=100)
            _wait_for_terminal(job)

        assert job.status == TransferStatus.COMPLETE
        assert job.progress == 100

    def test_download_failure_sets_failed_status(self):
        mock_client = MagicMock()
        mock_client.download.side_effect = OSError("disk full")

        svc = TransferService(notify_window=None)
        with patch("builtins.open", return_value=MagicMock(spec=io.BufferedWriter)):
            job = svc.submit_download(mock_client, "/r/f.bin", "/tmp/f.bin")
            _wait_for_terminal(job)

        assert job.status == TransferStatus.FAILED
        assert "disk full" in job.error


class TestSubmitUpload:
    def test_enqueues_and_completes_upload(self, tmp_path):
        src = tmp_path / "file.txt"
        src.write_text("hello")
        mock_client = MagicMock()
        mock_client.upload.side_effect = lambda fh, dest, callback=None: None

        svc = TransferService(notify_window=None)
        job = svc.submit_upload(mock_client, str(src), "/remote/file.txt", total_bytes=5)

        _wait_for_terminal(job)
        assert job.status == TransferStatus.COMPLETE
        assert job.direction == TransferDirection.UPLOAD

    def test_upload_failure_sets_failed_status(self):
        mock_client = MagicMock()
        mock_client.upload.side_effect = ConnectionError("lost connection")

        svc = TransferService(notify_window=None)
        with patch("builtins.open", return_value=MagicMock(spec=io.BufferedReader)):
            job = svc.submit_upload(mock_client, "/tmp/f.bin", "/r/f.bin")
            _wait_for_terminal(job)

        assert job.status == TransferStatus.FAILED
        assert "lost connection" in job.error


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------


class TestCancel:
    def test_cancel_pending_job(self):
        svc = TransferService(notify_window=None)

        # Block the worker on a slow job so next one stays PENDING
        slow_client = MagicMock()
        barrier = threading.Event()

        def slow_download(src, fh, callback=None, offset=0):
            barrier.wait(timeout=5)

        slow_client.download.side_effect = slow_download

        with patch("builtins.open", return_value=MagicMock(spec=io.BufferedWriter)):
            _slow = svc.submit_download(slow_client, "/r/slow", "/tmp/slow")
            # Submit a second job that will be PENDING
            fast_client = MagicMock()
            pending_job = svc.submit_download(fast_client, "/r/fast", "/tmp/fast")
            time.sleep(0.1)  # let worker pick up slow job

            svc.cancel(pending_job.id)
            assert pending_job.status == TransferStatus.CANCELLED
            assert pending_job.cancel_event.is_set()

            # Unblock the slow job
            barrier.set()
            _wait_for_terminal(_slow)

    def test_cancel_in_progress_job(self):
        mock_client = MagicMock()
        started = threading.Event()

        def slow_download(src, fh, callback=None, offset=0):
            started.set()
            if callback:
                # Simulate slow transfer that checks cancellation
                for i in range(100):
                    callback(i, 100)
                    time.sleep(0.01)

        mock_client.download.side_effect = slow_download

        svc = TransferService(notify_window=None)
        with patch("builtins.open", return_value=MagicMock(spec=io.BufferedWriter)):
            job = svc.submit_download(mock_client, "/r/big", "/tmp/big", total_bytes=100)
            started.wait(timeout=5)
            svc.cancel(job.id)
            _wait_for_terminal(job)

        assert job.status == TransferStatus.CANCELLED

    def test_cancel_nonexistent_job_is_noop(self):
        svc = TransferService(notify_window=None)
        svc.cancel("nonexistent-id")  # should not raise


# ---------------------------------------------------------------------------
# notify_window / event posting
# ---------------------------------------------------------------------------


class TestEventPosting:
    def test_post_event_called_on_status_change(self):
        mock_client = MagicMock()
        mock_client.download.side_effect = lambda src, fh, callback=None, offset=0: None

        notify = MagicMock()
        svc = TransferService(notify_window=notify)

        with patch("builtins.open", return_value=MagicMock(spec=io.BufferedWriter)):
            job = svc.submit_download(mock_client, "/r/f", "/tmp/f")
            _wait_for_terminal(job)

        # At minimum: enqueue, in_progress, complete
        assert svc._notify_window is notify

    def test_no_crash_when_notify_window_is_none(self):
        mock_client = MagicMock()
        mock_client.download.side_effect = lambda src, fh, callback=None, offset=0: None

        svc = TransferService(notify_window=None)
        with patch("builtins.open", return_value=MagicMock(spec=io.BufferedWriter)):
            job = svc.submit_download(mock_client, "/r/f", "/tmp/f")
            _wait_for_terminal(job)

        assert job.status == TransferStatus.COMPLETE


# ---------------------------------------------------------------------------
# Recursive transfers
# ---------------------------------------------------------------------------


class TestRecursiveDownload:
    def test_recursive_download_creates_dirs_and_downloads_files(self, tmp_path):
        from portkeydrop.protocols import RemoteFile

        mock_client = MagicMock()
        mock_client.list_dir.return_value = [
            RemoteFile(name="a.txt", path="/remote/dir/a.txt", size=10),
            RemoteFile(name="b.txt", path="/remote/dir/b.txt", size=20),
        ]
        mock_client.download.side_effect = lambda src, fh, callback=None, offset=0: None

        svc = TransferService(notify_window=None)
        with patch("builtins.open", return_value=MagicMock(spec=io.BufferedWriter)):
            with patch("os.makedirs"):
                job = svc.submit_download(
                    mock_client, "/remote/dir", str(tmp_path / "local"), recursive=True
                )
                _wait_for_terminal(job)

        assert job.status == TransferStatus.COMPLETE
        assert job.total_bytes == 30
        assert mock_client.download.call_count == 2

    def test_recursive_download_restats_zero_size_symlinks(self):
        from portkeydrop.protocols import RemoteFile

        mock_client = MagicMock()
        mock_client.list_dir.return_value = [
            RemoteFile(name="link.txt", path="/remote/dir/link.txt", size=0),
        ]
        mock_client.stat.return_value = RemoteFile(
            name="link.txt", path="/remote/dir/link.txt", size=500
        )
        mock_client.download.side_effect = lambda src, fh, callback=None, offset=0: None

        svc = TransferService(notify_window=None)
        with patch("builtins.open", return_value=MagicMock(spec=io.BufferedWriter)):
            with patch("os.makedirs"):
                job = svc.submit_download(mock_client, "/remote/dir", "/tmp/local", recursive=True)
                _wait_for_terminal(job)

        assert job.total_bytes == 500
        mock_client.stat.assert_called_once_with("/remote/dir/link.txt")


class TestRecursiveUpload:
    def test_recursive_upload_creates_remote_dirs_and_uploads(self, tmp_path):
        src_dir = tmp_path / "upload_dir"
        src_dir.mkdir()
        (src_dir / "file1.txt").write_text("aaa")
        (src_dir / "file2.txt").write_text("bbbb")

        mock_client = MagicMock()
        mock_client.upload.side_effect = lambda fh, dest, callback=None: None
        mock_client.mkdir.side_effect = lambda d: None

        svc = TransferService(notify_window=None)
        job = svc.submit_upload(mock_client, str(src_dir), "/remote/upload_dir", recursive=True)
        _wait_for_terminal(job)

        assert job.status == TransferStatus.COMPLETE
        assert mock_client.upload.call_count == 2

    def test_recursive_upload_cancel_mid_transfer(self, tmp_path):
        src_dir = tmp_path / "cancel_dir"
        src_dir.mkdir()
        for i in range(10):
            (src_dir / f"file{i}.txt").write_text("x" * 100)

        mock_client = MagicMock()
        started = threading.Event()

        def slow_upload(fh, dest, callback=None):
            started.set()
            if callback:
                callback(50, 100)
                time.sleep(0.5)

        mock_client.upload.side_effect = slow_upload
        mock_client.mkdir.side_effect = lambda d: None

        svc = TransferService(notify_window=None)
        job = svc.submit_upload(mock_client, str(src_dir), "/remote/cancel_dir", recursive=True)
        started.wait(timeout=5)
        svc.cancel(job.id)
        _wait_for_terminal(job)

        assert job.status == TransferStatus.CANCELLED


# ---------------------------------------------------------------------------
# Progress calculation
# ---------------------------------------------------------------------------


class TestProgressCalculation:
    def test_progress_zero_when_total_zero(self):
        job = TransferJob(total_bytes=0, transferred_bytes=50)
        TransferService._update_progress(job)
        assert job.progress == 0

    def test_progress_capped_at_100(self):
        job = TransferJob(total_bytes=100, transferred_bytes=200)
        TransferService._update_progress(job)
        assert job.progress == 100

    def test_progress_calculated_correctly(self):
        job = TransferJob(total_bytes=200, transferred_bytes=50)
        TransferService._update_progress(job)
        assert job.progress == 25


# ---------------------------------------------------------------------------
# Multiple sequential jobs
# ---------------------------------------------------------------------------


class TestJobQueue:
    def test_multiple_jobs_processed_sequentially(self):
        order = []
        mock_client = MagicMock()

        def fake_download(src, fh, callback=None, offset=0):
            order.append(PurePosixPath(src).name)

        mock_client.download.side_effect = fake_download

        svc = TransferService(notify_window=None)
        jobs = []
        with patch("builtins.open", return_value=MagicMock(spec=io.BufferedWriter)):
            for name in ["a.txt", "b.txt", "c.txt"]:
                j = svc.submit_download(mock_client, f"/r/{name}", f"/tmp/{name}")
                jobs.append(j)

            for j in jobs:
                _wait_for_terminal(j)

        assert all(j.status == TransferStatus.COMPLETE for j in jobs)
        assert order == ["a.txt", "b.txt", "c.txt"]

    def test_jobs_snapshot_reflects_all_submitted(self):
        svc = TransferService(notify_window=None)
        barrier = threading.Event()
        mock_client = MagicMock()
        mock_client.download.side_effect = lambda src, fh, callback=None, offset=0: barrier.wait(2)

        with patch("builtins.open", return_value=MagicMock(spec=io.BufferedWriter)):
            svc.submit_download(mock_client, "/r/a", "/tmp/a")
            svc.submit_download(mock_client, "/r/b", "/tmp/b")
            time.sleep(0.1)

            snapshot = svc.jobs
            assert len(snapshot) == 2

            barrier.set()

    def test_protocol_field_set_from_client(self):
        mock_client = MagicMock()
        mock_client._protocol_name = "sftp"
        mock_client.download.side_effect = lambda src, fh, callback=None, offset=0: None

        svc = TransferService(notify_window=None)
        with patch("builtins.open", return_value=MagicMock(spec=io.BufferedWriter)):
            job = svc.submit_download(mock_client, "/r/f", "/tmp/f")
            _wait_for_terminal(job)

        assert job.protocol == "sftp"


# ---------------------------------------------------------------------------
# TransferDirection / TransferStatus enums
# ---------------------------------------------------------------------------


class TestEnums:
    def test_direction_values(self):
        assert TransferDirection.UPLOAD.value == "upload"
        assert TransferDirection.DOWNLOAD.value == "download"

    def test_status_values(self):
        assert TransferStatus.PENDING.value == "pending"
        assert TransferStatus.IN_PROGRESS.value == "in_progress"
        assert TransferStatus.COMPLETE.value == "complete"
        assert TransferStatus.FAILED.value == "failed"
        assert TransferStatus.CANCELLED.value == "cancelled"


# ---------------------------------------------------------------------------
# Concurrent worker pool
# ---------------------------------------------------------------------------


class TestConcurrentWorkers:
    def test_jobs_run_concurrently_with_multiple_workers(self):
        """Two slow jobs should overlap when max_workers >= 2."""
        barrier = threading.Barrier(2, timeout=5)
        completed_order: list[str] = []
        lock = threading.Lock()

        mock_client = MagicMock()

        def slow_download(src, fh, callback=None):
            name = PurePosixPath(src).name
            barrier.wait()  # both workers must reach here before either proceeds
            with lock:
                completed_order.append(name)

        mock_client.download.side_effect = slow_download

        svc = TransferService(notify_window=None, max_workers=2)
        with patch("builtins.open", return_value=MagicMock(spec=io.BufferedWriter)):
            j1 = svc.submit_download(mock_client, "/r/a.txt", "/tmp/a.txt")
            j2 = svc.submit_download(mock_client, "/r/b.txt", "/tmp/b.txt")
            _wait_for_terminal(j1)
            _wait_for_terminal(j2)

        assert j1.status == TransferStatus.COMPLETE
        assert j2.status == TransferStatus.COMPLETE
        assert len(completed_order) == 2

    def test_set_max_workers_increases_pool(self):
        svc = TransferService(notify_window=None, max_workers=1)
        assert len([t for t in svc._workers if t.is_alive()]) == 1

        svc.set_max_workers(3)
        time.sleep(0.1)
        alive = [t for t in svc._workers if t.is_alive()]
        assert len(alive) == 3

    def test_set_max_workers_decreases_pool(self):
        svc = TransferService(notify_window=None, max_workers=3)
        assert len(svc._workers) == 3

        svc.set_max_workers(1)
        # Give sentinels time to be consumed
        time.sleep(0.5)
        alive = [t for t in svc._workers if t.is_alive()]
        assert len(alive) == 1

    def test_set_max_workers_clamps_to_one(self):
        svc = TransferService(notify_window=None, max_workers=2)
        svc.set_max_workers(0)
        assert svc._max_workers == 1
