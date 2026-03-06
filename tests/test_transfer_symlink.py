"""Tests for symlink-related download progress fixes (#52)."""

from __future__ import annotations

import io
import time
from unittest.mock import MagicMock, patch

from portkeydrop.services.transfer_service import TransferService, TransferStatus
from portkeydrop.protocols import RemoteFile


def _wait_for_job(job, timeout=5):
    deadline = time.monotonic() + timeout
    while (
        job.status in (TransferStatus.PENDING, TransferStatus.IN_PROGRESS)
        and time.monotonic() < deadline
    ):
        time.sleep(0.05)


class TestCallbackTotalBytesGuard:
    """Fix 2: callback must not overwrite job.total_bytes with 0."""

    def test_download_callback_preserves_total_bytes_when_zero_reported(self):
        mock_client = MagicMock()

        def fake_download(remote_path, local_file, callback=None):
            if callback:
                callback(500, 1000)
                callback(600, 0)

        mock_client.download.side_effect = fake_download

        svc = TransferService(notify_window=None)

        with patch("builtins.open", return_value=MagicMock(spec=io.BufferedWriter)):
            job = svc.submit_download(mock_client, "/remote/file.bin", "/tmp/file.bin", 1000)
            _wait_for_job(job)

        assert job.total_bytes == 1000
        assert job.transferred_bytes == 600
        assert job.status == TransferStatus.COMPLETE

    def test_upload_callback_preserves_total_bytes_when_zero_reported(self):
        mock_client = MagicMock()

        def fake_upload(local_file, remote_path, callback=None):
            if callback:
                callback(200, 500)
                callback(400, 0)

        mock_client.upload.side_effect = fake_upload

        svc = TransferService(notify_window=None)

        with patch("builtins.open", return_value=MagicMock(spec=io.BufferedReader)):
            job = svc.submit_upload(mock_client, "/tmp/file.bin", "/remote/file.bin", 500)
            _wait_for_job(job)

        assert job.total_bytes == 500
        assert job.transferred_bytes == 400
        assert job.status == TransferStatus.COMPLETE

    def test_download_callback_updates_total_bytes_when_positive(self):
        mock_client = MagicMock()

        def fake_download(remote_path, local_file, callback=None):
            if callback:
                callback(100, 2000)

        mock_client.download.side_effect = fake_download

        svc = TransferService(notify_window=None)

        with patch("builtins.open", return_value=MagicMock(spec=io.BufferedWriter)):
            job = svc.submit_download(mock_client, "/remote/file.bin", "/tmp/file.bin", 0)
            _wait_for_job(job)

        assert job.total_bytes == 2000
        assert job.status == TransferStatus.COMPLETE


class TestRecursiveDownloadRestat:
    """Fix 3: recursive download re-stats files with size=0."""

    def test_recursive_download_restats_zero_size_files(self):
        mock_client = MagicMock()
        mock_client.list_dir.return_value = [
            RemoteFile(name="normal.txt", path="/remote/dir/normal.txt", size=500),
            RemoteFile(name="symlink.txt", path="/remote/dir/symlink.txt", size=0),
        ]
        mock_client.stat.return_value = RemoteFile(
            name="symlink.txt", path="/remote/dir/symlink.txt", size=750
        )

        def fake_download(remote_path, local_file, callback=None):
            if callback:
                size = 500 if "normal" in remote_path else 750
                callback(size, size)

        mock_client.download.side_effect = fake_download

        svc = TransferService(notify_window=None)

        with patch("builtins.open", return_value=MagicMock(spec=io.BufferedWriter)):
            with patch("os.makedirs"):
                job = svc.submit_download(
                    mock_client, "/remote/dir", "/tmp/local_dir", recursive=True
                )
                _wait_for_job(job)

        assert job.total_bytes == 1250
        assert job.status == TransferStatus.COMPLETE
        mock_client.stat.assert_called_once_with("/remote/dir/symlink.txt")

    def test_recursive_download_skips_restat_for_nonzero_files(self):
        mock_client = MagicMock()
        mock_client.list_dir.return_value = [
            RemoteFile(name="file1.txt", path="/remote/dir/file1.txt", size=100),
            RemoteFile(name="file2.txt", path="/remote/dir/file2.txt", size=200),
        ]

        def fake_download(remote_path, local_file, callback=None):
            if callback:
                size = 100 if "file1" in remote_path else 200
                callback(size, size)

        mock_client.download.side_effect = fake_download

        svc = TransferService(notify_window=None)

        with patch("builtins.open", return_value=MagicMock(spec=io.BufferedWriter)):
            with patch("os.makedirs"):
                job = svc.submit_download(
                    mock_client, "/remote/dir", "/tmp/local_dir", recursive=True
                )
                _wait_for_job(job)

        assert job.total_bytes == 300
        assert job.status == TransferStatus.COMPLETE
        mock_client.stat.assert_not_called()

    def test_recursive_download_handles_stat_failure_gracefully(self):
        mock_client = MagicMock()
        mock_client.list_dir.return_value = [
            RemoteFile(name="broken_link.txt", path="/remote/dir/broken_link.txt", size=0),
        ]
        mock_client.stat.side_effect = OSError("No such file")

        def fake_download(remote_path, local_file, callback=None):
            if callback:
                callback(0, 0)

        mock_client.download.side_effect = fake_download

        svc = TransferService(notify_window=None)

        with patch("builtins.open", return_value=MagicMock(spec=io.BufferedWriter)):
            with patch("os.makedirs"):
                job = svc.submit_download(
                    mock_client, "/remote/dir", "/tmp/local_dir", recursive=True
                )
                _wait_for_job(job)

        assert job.total_bytes == 0
        assert job.status == TransferStatus.COMPLETE
        mock_client.stat.assert_called_once_with("/remote/dir/broken_link.txt")
