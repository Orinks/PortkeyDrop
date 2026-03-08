"""Tests for resume interrupted downloads from offset (issue #106)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock


from portkeydrop.protocols import RemoteFile
from portkeydrop.services.transfer_service import (
    TransferDirection,
    TransferJob,
    TransferService,
    TransferStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(
    *,
    transferred_bytes: int = 0,
    total_bytes: int = 1000,
    remote_mtime: float | None = None,
    status: TransferStatus = TransferStatus.PENDING,
) -> TransferJob:
    return TransferJob(
        direction=TransferDirection.DOWNLOAD,
        source="/remote/file.bin",
        destination="/tmp/file.bin",
        total_bytes=total_bytes,
        transferred_bytes=transferred_bytes,
        status=status,
        _remote_mtime=remote_mtime,
    )


def _make_client(size: int = 1000, mtime: datetime | None = None) -> MagicMock:
    client = MagicMock()
    client.stat.return_value = RemoteFile(
        name="file.bin",
        path="/remote/file.bin",
        size=size,
        modified=mtime,
    )
    client.download.side_effect = lambda src, fh, callback=None, offset=0: None
    return client


# ---------------------------------------------------------------------------
# retry() preserves transferred_bytes
# ---------------------------------------------------------------------------


class TestRetryPreservesProgress:
    def test_retry_keeps_transferred_bytes(self):
        svc = TransferService(notify_window=None)
        job = _make_job(transferred_bytes=500, status=TransferStatus.FAILED)
        job.error = "Connection lost"
        with svc._lock:
            svc._jobs.append(job)

        client = MagicMock()
        retried = svc.retry(job.id, client)

        assert retried is not None
        assert retried.transferred_bytes == 500

    def test_retry_keeps_total_bytes(self):
        svc = TransferService(notify_window=None)
        job = _make_job(transferred_bytes=300, total_bytes=1000, status=TransferStatus.FAILED)
        job.error = "Timeout"
        with svc._lock:
            svc._jobs.append(job)

        client = MagicMock()
        retried = svc.retry(job.id, client)

        assert retried is not None
        assert retried.total_bytes == 1000
        assert retried.transferred_bytes == 300


# ---------------------------------------------------------------------------
# _resolve_download_offset
# ---------------------------------------------------------------------------


class TestResolveDownloadOffset:
    def test_first_attempt_returns_zero(self):
        """First download (transferred_bytes=0) always starts from 0."""
        svc = TransferService(notify_window=None)
        job = _make_job(transferred_bytes=0)
        client = _make_client()

        offset = svc._resolve_download_offset(job, client)
        assert offset == 0

    def test_resume_when_partial_file_matches(self, tmp_path):
        """Resume when partial file exists and remote file unchanged."""
        partial = tmp_path / "file.bin"
        partial.write_bytes(b"x" * 500)

        mtime = datetime(2025, 1, 15, 12, 0, 0)
        svc = TransferService(notify_window=None)
        job = _make_job(
            transferred_bytes=500,
            total_bytes=1000,
            remote_mtime=mtime.timestamp(),
        )
        job.destination = str(partial)

        client = _make_client(size=1000, mtime=mtime)
        offset = svc._resolve_download_offset(job, client)
        assert offset == 500

    def test_restart_when_partial_file_missing(self, tmp_path):
        """Fall back to full restart when partial file doesn't exist."""
        svc = TransferService(notify_window=None)
        job = _make_job(transferred_bytes=500)
        job.destination = str(tmp_path / "nonexistent.bin")

        client = _make_client()
        offset = svc._resolve_download_offset(job, client)
        assert offset == 0
        assert job.transferred_bytes == 0

    def test_restart_when_partial_file_size_mismatch(self, tmp_path):
        """Fall back when local file size != transferred_bytes."""
        partial = tmp_path / "file.bin"
        partial.write_bytes(b"x" * 300)  # only 300, not 500

        svc = TransferService(notify_window=None)
        job = _make_job(transferred_bytes=500)
        job.destination = str(partial)

        client = _make_client()
        offset = svc._resolve_download_offset(job, client)
        assert offset == 0
        assert job.transferred_bytes == 0

    def test_restart_when_remote_size_changed(self, tmp_path):
        """Fall back when remote file size has changed."""
        partial = tmp_path / "file.bin"
        partial.write_bytes(b"x" * 500)

        mtime = datetime(2025, 1, 15, 12, 0, 0)
        svc = TransferService(notify_window=None)
        job = _make_job(
            transferred_bytes=500,
            total_bytes=1000,
            remote_mtime=mtime.timestamp(),
        )
        job.destination = str(partial)

        # Remote file grew from 1000 to 2000
        client = _make_client(size=2000, mtime=mtime)
        offset = svc._resolve_download_offset(job, client)
        assert offset == 0
        assert job.transferred_bytes == 0

    def test_restart_when_remote_mtime_changed(self, tmp_path):
        """Fall back when remote file mtime has changed."""
        partial = tmp_path / "file.bin"
        partial.write_bytes(b"x" * 500)

        old_mtime = datetime(2025, 1, 15, 12, 0, 0)
        new_mtime = datetime(2025, 1, 16, 8, 0, 0)
        svc = TransferService(notify_window=None)
        job = _make_job(
            transferred_bytes=500,
            total_bytes=1000,
            remote_mtime=old_mtime.timestamp(),
        )
        job.destination = str(partial)

        client = _make_client(size=1000, mtime=new_mtime)
        offset = svc._resolve_download_offset(job, client)
        assert offset == 0
        assert job.transferred_bytes == 0

    def test_resume_when_mtime_not_available(self, tmp_path):
        """Resume is allowed when both old and new mtime are None."""
        partial = tmp_path / "file.bin"
        partial.write_bytes(b"x" * 500)

        svc = TransferService(notify_window=None)
        job = _make_job(
            transferred_bytes=500,
            total_bytes=1000,
            remote_mtime=None,
        )
        job.destination = str(partial)

        client = _make_client(size=1000, mtime=None)
        offset = svc._resolve_download_offset(job, client)
        assert offset == 500

    def test_restart_when_stat_fails(self, tmp_path):
        """Fall back when remote stat raises."""
        partial = tmp_path / "file.bin"
        partial.write_bytes(b"x" * 500)

        svc = TransferService(notify_window=None)
        job = _make_job(transferred_bytes=500)
        job.destination = str(partial)

        client = MagicMock()
        client.stat.side_effect = OSError("connection lost")
        offset = svc._resolve_download_offset(job, client)
        assert offset == 0
        assert job.transferred_bytes == 0


# ---------------------------------------------------------------------------
# _run_download integration (with mocked client)
# ---------------------------------------------------------------------------


class TestRunDownloadResume:
    def test_fresh_download_opens_wb(self, tmp_path):
        """First download opens file in 'wb' mode."""
        dest = tmp_path / "file.bin"
        client = _make_client(size=100, mtime=datetime(2025, 1, 1))
        client.download.side_effect = lambda src, fh, callback=None, offset=0: fh.write(b"x" * 100)

        svc = TransferService(notify_window=None)
        job = _make_job(transferred_bytes=0, total_bytes=100)
        job.destination = str(dest)
        job._client = client

        svc._run_download(job)

        assert dest.read_bytes() == b"x" * 100
        client.download.assert_called_once()
        _, kwargs = client.download.call_args
        assert kwargs.get("offset", 0) == 0

    def test_resumed_download_opens_rplusb_and_seeks(self, tmp_path):
        """Resumed download opens in 'r+b' mode with seek and passes offset."""
        dest = tmp_path / "file.bin"
        dest.write_bytes(b"A" * 500)  # partial data

        mtime = datetime(2025, 6, 1)
        client = _make_client(size=1000, mtime=mtime)
        client.download.side_effect = lambda src, fh, callback=None, offset=0: fh.write(b"B" * 500)

        svc = TransferService(notify_window=None)
        job = _make_job(
            transferred_bytes=500,
            total_bytes=1000,
            remote_mtime=mtime.timestamp(),
        )
        job.destination = str(dest)
        job._client = client

        svc._run_download(job)

        content = dest.read_bytes()
        assert content[:500] == b"A" * 500  # original partial data preserved
        assert content[500:] == b"B" * 500  # new data appended
        _, kwargs = client.download.call_args
        assert kwargs["offset"] == 500

    def test_resumed_download_progress_includes_offset(self, tmp_path):
        """Progress callback values should include the resume offset."""
        dest = tmp_path / "file.bin"
        dest.write_bytes(b"A" * 500)

        mtime = datetime(2025, 6, 1)

        def fake_download(src, fh, callback=None, offset=0):
            if callback:
                callback(250, 1000)
                callback(500, 1000)

        client = _make_client(size=1000, mtime=mtime)
        client.download.side_effect = fake_download

        svc = TransferService(notify_window=None)
        job = _make_job(
            transferred_bytes=500,
            total_bytes=1000,
            remote_mtime=mtime.timestamp(),
        )
        job.destination = str(dest)
        job._client = client

        svc._run_download(job)

        # After callback(250, 1000): transferred_bytes = 500 + 250 = 750
        # After callback(500, 1000): transferred_bytes = 500 + 500 = 1000
        assert job.transferred_bytes == 1000

    def test_fallback_to_full_restart_on_mtime_change(self, tmp_path):
        """When remote file changed, restart from 0 despite partial file."""
        dest = tmp_path / "file.bin"
        dest.write_bytes(b"A" * 500)

        old_mtime = datetime(2025, 1, 1)
        new_mtime = datetime(2025, 6, 1)
        client = _make_client(size=1000, mtime=new_mtime)
        client.download.side_effect = lambda src, fh, callback=None, offset=0: fh.write(b"N" * 1000)

        svc = TransferService(notify_window=None)
        job = _make_job(
            transferred_bytes=500,
            total_bytes=1000,
            remote_mtime=old_mtime.timestamp(),
        )
        job.destination = str(dest)
        job._client = client

        svc._run_download(job)

        # Should have restarted: file opened in wb, offset=0
        _, kwargs = client.download.call_args
        assert kwargs["offset"] == 0
        assert dest.read_bytes() == b"N" * 1000


# ---------------------------------------------------------------------------
# _snapshot_remote_metadata
# ---------------------------------------------------------------------------


class TestSnapshotRemoteMetadata:
    def test_records_mtime_and_size(self):
        svc = TransferService(notify_window=None)
        mtime = datetime(2025, 3, 15, 10, 30, 0)
        job = _make_job(total_bytes=0)
        client = _make_client(size=2048, mtime=mtime)

        svc._snapshot_remote_metadata(job, client)

        assert job._remote_mtime == mtime.timestamp()
        assert job.total_bytes == 2048

    def test_no_crash_when_stat_fails(self):
        svc = TransferService(notify_window=None)
        job = _make_job()
        client = MagicMock()
        client.stat.side_effect = OSError("no connection")

        svc._snapshot_remote_metadata(job, client)
        # Should not raise
        assert job._remote_mtime is None

    def test_does_not_overwrite_existing_total_bytes(self):
        svc = TransferService(notify_window=None)
        job = _make_job(total_bytes=5000)
        client = _make_client(size=5000)

        svc._snapshot_remote_metadata(job, client)
        assert job.total_bytes == 5000
