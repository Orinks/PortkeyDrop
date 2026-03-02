"""Tests for symlink-related download progress fixes (#52)."""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch


from portkeydrop.dialogs.transfer import TransferManager, TransferStatus
from portkeydrop.protocols import RemoteFile


class TestCallbackTotalBytesGuard:
    """Fix 2: callback must not overwrite item.total_bytes with 0."""

    def test_download_callback_preserves_total_bytes_when_zero_reported(self):
        """If the progress callback reports total=0, item.total_bytes should
        not be overwritten when it already holds a positive value."""
        mock_client = MagicMock()
        captured_callback = {}

        def fake_download(remote_path, local_file, callback=None):
            captured_callback["fn"] = callback
            if callback:
                # First call reports real total
                callback(500, 1000)
                # Subsequent call reports total=0 (symlink stat issue)
                callback(600, 0)

        mock_client.download.side_effect = fake_download

        manager = TransferManager(notify_window=None)

        with patch("builtins.open", return_value=MagicMock(spec=io.BufferedWriter)):
            item = manager.add_download(mock_client, "/remote/file.bin", "/tmp/file.bin", 1000)
            # Wait for the thread to finish
            import time

            deadline = time.monotonic() + 5
            while item.status == TransferStatus.IN_PROGRESS and time.monotonic() < deadline:
                time.sleep(0.05)

        assert item.total_bytes == 1000
        assert item.transferred_bytes == 600
        assert item.status == TransferStatus.COMPLETED

    def test_upload_callback_preserves_total_bytes_when_zero_reported(self):
        """Upload callback should also guard total_bytes from being zeroed."""
        mock_client = MagicMock()

        def fake_upload(local_file, remote_path, callback=None):
            if callback:
                callback(200, 500)
                callback(400, 0)  # symlink-related 0

        mock_client.upload.side_effect = fake_upload

        manager = TransferManager(notify_window=None)

        with patch("builtins.open", return_value=MagicMock(spec=io.BufferedReader)):
            item = manager.add_upload(mock_client, "/tmp/file.bin", "/remote/file.bin", 500)
            import time

            deadline = time.monotonic() + 5
            while item.status == TransferStatus.IN_PROGRESS and time.monotonic() < deadline:
                time.sleep(0.05)

        assert item.total_bytes == 500
        assert item.transferred_bytes == 400
        assert item.status == TransferStatus.COMPLETED

    def test_download_callback_updates_total_bytes_when_positive(self):
        """Callback should update total_bytes when a positive value is reported."""
        mock_client = MagicMock()

        def fake_download(remote_path, local_file, callback=None):
            if callback:
                callback(100, 2000)

        mock_client.download.side_effect = fake_download

        manager = TransferManager(notify_window=None)

        with patch("builtins.open", return_value=MagicMock(spec=io.BufferedWriter)):
            item = manager.add_download(mock_client, "/remote/file.bin", "/tmp/file.bin", 0)
            import time

            deadline = time.monotonic() + 5
            while item.status == TransferStatus.IN_PROGRESS and time.monotonic() < deadline:
                time.sleep(0.05)

        assert item.total_bytes == 2000
        assert item.status == TransferStatus.COMPLETED


class TestRecursiveDownloadRestat:
    """Fix 3: recursive download re-stats files with size=0."""

    def test_recursive_download_restats_zero_size_files(self):
        """Files with size=0 in the listing should be individually re-statted
        to resolve symlink targets and get the real size."""
        mock_client = MagicMock()

        # list_dir returns one normal file and one symlinked file (size=0)
        mock_client.list_dir.return_value = [
            RemoteFile(name="normal.txt", path="/remote/dir/normal.txt", size=500),
            RemoteFile(name="symlink.txt", path="/remote/dir/symlink.txt", size=0),
        ]

        # stat on the symlinked file returns the real size
        mock_client.stat.return_value = RemoteFile(
            name="symlink.txt", path="/remote/dir/symlink.txt", size=750
        )

        def fake_download(remote_path, local_file, callback=None):
            if callback:
                size = 500 if "normal" in remote_path else 750
                callback(size, size)

        mock_client.download.side_effect = fake_download

        manager = TransferManager(notify_window=None)

        with patch("builtins.open", return_value=MagicMock(spec=io.BufferedWriter)):
            with patch("os.makedirs"):
                item = manager.add_recursive_download(mock_client, "/remote/dir", "/tmp/local_dir")
                import time

                deadline = time.monotonic() + 5
                while item.status == TransferStatus.IN_PROGRESS and time.monotonic() < deadline:
                    time.sleep(0.05)

        # Total should be 500 + 750 = 1250 (not 500 + 0 = 500)
        assert item.total_bytes == 1250
        assert item.status == TransferStatus.COMPLETED
        # stat should have been called for the zero-size file
        mock_client.stat.assert_called_once_with("/remote/dir/symlink.txt")

    def test_recursive_download_skips_restat_for_nonzero_files(self):
        """Files with size > 0 should not be re-statted."""
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

        manager = TransferManager(notify_window=None)

        with patch("builtins.open", return_value=MagicMock(spec=io.BufferedWriter)):
            with patch("os.makedirs"):
                item = manager.add_recursive_download(mock_client, "/remote/dir", "/tmp/local_dir")
                import time

                deadline = time.monotonic() + 5
                while item.status == TransferStatus.IN_PROGRESS and time.monotonic() < deadline:
                    time.sleep(0.05)

        assert item.total_bytes == 300
        assert item.status == TransferStatus.COMPLETED
        # stat should NOT have been called (no zero-size files)
        mock_client.stat.assert_not_called()

    def test_recursive_download_handles_stat_failure_gracefully(self):
        """If stat fails on a zero-size file, it should remain at size=0."""
        mock_client = MagicMock()

        mock_client.list_dir.return_value = [
            RemoteFile(name="broken_link.txt", path="/remote/dir/broken_link.txt", size=0),
        ]

        mock_client.stat.side_effect = OSError("No such file")

        def fake_download(remote_path, local_file, callback=None):
            if callback:
                callback(0, 0)

        mock_client.download.side_effect = fake_download

        manager = TransferManager(notify_window=None)

        with patch("builtins.open", return_value=MagicMock(spec=io.BufferedWriter)):
            with patch("os.makedirs"):
                item = manager.add_recursive_download(mock_client, "/remote/dir", "/tmp/local_dir")
                import time

                deadline = time.monotonic() + 5
                while item.status == TransferStatus.IN_PROGRESS and time.monotonic() < deadline:
                    time.sleep(0.05)

        assert item.total_bytes == 0
        assert item.status == TransferStatus.COMPLETED
        mock_client.stat.assert_called_once_with("/remote/dir/broken_link.txt")
