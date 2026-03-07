"""Tests for transfer queue persistence (save_queue / load_queue)."""

from __future__ import annotations

import json
import threading
from pathlib import Path


from portkeydrop.dialogs.transfer import (
    TransferDirection,
    TransferJob,
    TransferService,
    TransferStatus,
    load_queue,
    save_queue,
)


# ── TransferJob.to_dict ─────────────────────────────────────────────


class TestTransferJobToDict:
    def test_serializes_all_fields(self):
        job = TransferJob(
            id="abc123",
            direction=TransferDirection.UPLOAD,
            source="/home/user/file.txt",
            destination="/srv/file.txt",
            protocol="sftp",
            total_bytes=1024,
            transferred_bytes=512,
            status=TransferStatus.PENDING,
            error=None,
        )
        d = job.to_dict()
        assert d == {
            "id": "abc123",
            "direction": "upload",
            "source": "/home/user/file.txt",
            "destination": "/srv/file.txt",
            "protocol": "sftp",
            "total_bytes": 1024,
            "transferred_bytes": 512,
            "status": "pending",
            "error": "",
        }

    def test_excludes_cancel_event(self):
        job = TransferJob()
        d = job.to_dict()
        assert "cancel_event" not in d

    def test_excludes_client(self):
        job = TransferJob()
        d = job.to_dict()
        assert "_client" not in d
        assert "client" not in d

    def test_serializes_failed_status(self):
        job = TransferJob(status=TransferStatus.FAILED, error="connection lost")
        d = job.to_dict()
        assert d["status"] == "failed"
        assert d["error"] == "connection lost"

    def test_serializes_restored_status(self):
        job = TransferJob(status=TransferStatus.RESTORED)
        d = job.to_dict()
        assert d["status"] == "pending (restored)"

    def test_error_none_serializes_as_empty_string(self):
        job = TransferJob(error=None)
        d = job.to_dict()
        assert d["error"] == ""


# ── TransferJob.from_dict ───────────────────────────────────────────


class TestTransferJobFromDict:
    def test_deserializes_all_fields(self):
        data = {
            "id": "def456",
            "direction": "download",
            "source": "/data/report.csv",
            "destination": "/tmp/report.csv",
            "protocol": "sftp",
            "total_bytes": 2048,
            "transferred_bytes": 0,
            "status": "pending",
            "error": "",
        }
        job = TransferJob.from_dict(data)
        assert job.id == "def456"
        assert job.direction == TransferDirection.DOWNLOAD
        assert job.source == "/data/report.csv"
        assert job.destination == "/tmp/report.csv"
        assert job.protocol == "sftp"
        assert job.total_bytes == 2048
        assert job.transferred_bytes == 0
        assert job.status == TransferStatus.RESTORED
        assert job.error is None

    def test_always_sets_restored_status(self):
        data = {"status": "failed", "error": "timeout"}
        job = TransferJob.from_dict(data)
        assert job.status == TransferStatus.RESTORED

    def test_creates_fresh_cancel_event(self):
        job = TransferJob.from_dict({"id": "xyz"})
        assert isinstance(job.cancel_event, threading.Event)
        assert not job.cancel_event.is_set()

    def test_handles_missing_fields(self):
        job = TransferJob.from_dict({})
        assert job.source == ""
        assert job.destination == ""
        assert job.direction == TransferDirection.DOWNLOAD

    def test_handles_upload_direction(self):
        job = TransferJob.from_dict({"direction": "upload"})
        assert job.direction == TransferDirection.UPLOAD

    def test_missing_id_generates_new_uuid(self):
        job = TransferJob.from_dict({})
        assert isinstance(job.id, str)
        assert len(job.id) > 0

    def test_error_empty_string_becomes_none(self):
        job = TransferJob.from_dict({"error": ""})
        assert job.error is None

    def test_error_string_preserved(self):
        job = TransferJob.from_dict({"error": "network error"})
        assert job.error == "network error"


# ── save_queue ──────────────────────────────────────────────────────


def _make_service_with_jobs(jobs):
    """Create a TransferService with pre-populated jobs (no threads started)."""
    svc = TransferService.__new__(TransferService)
    import threading
    import queue

    svc._notify_window = None
    svc._lock = threading.Lock()
    svc._jobs = list(jobs)
    svc._queue = queue.Queue()
    return svc


class TestSaveQueue:
    def test_saves_pending_jobs(self, tmp_path):
        job = TransferJob(id="1", status=TransferStatus.PENDING, source="/a.txt")
        svc = _make_service_with_jobs([job])
        save_queue(svc, tmp_path)

        data = json.loads((tmp_path / "queue.json").read_text())
        assert len(data) == 1
        assert data[0]["source"] == "/a.txt"

    def test_saves_failed_jobs(self, tmp_path):
        job = TransferJob(id="1", status=TransferStatus.FAILED, error="oops")
        svc = _make_service_with_jobs([job])
        save_queue(svc, tmp_path)

        data = json.loads((tmp_path / "queue.json").read_text())
        assert len(data) == 1
        assert data[0]["error"] == "oops"

    def test_saves_restored_jobs(self, tmp_path):
        job = TransferJob(id="1", status=TransferStatus.RESTORED)
        svc = _make_service_with_jobs([job])
        save_queue(svc, tmp_path)

        data = json.loads((tmp_path / "queue.json").read_text())
        assert len(data) == 1

    def test_skips_completed_jobs(self, tmp_path):
        job = TransferJob(id="1", status=TransferStatus.COMPLETE)
        svc = _make_service_with_jobs([job])
        save_queue(svc, tmp_path)

        data = json.loads((tmp_path / "queue.json").read_text())
        assert len(data) == 0

    def test_skips_in_progress_jobs(self, tmp_path):
        job = TransferJob(id="1", status=TransferStatus.IN_PROGRESS)
        svc = _make_service_with_jobs([job])
        save_queue(svc, tmp_path)

        data = json.loads((tmp_path / "queue.json").read_text())
        assert len(data) == 0

    def test_skips_cancelled_jobs(self, tmp_path):
        job = TransferJob(id="1", status=TransferStatus.CANCELLED)
        svc = _make_service_with_jobs([job])
        save_queue(svc, tmp_path)

        data = json.loads((tmp_path / "queue.json").read_text())
        assert len(data) == 0

    def test_creates_directory_if_missing(self, tmp_path):
        config_dir = tmp_path / "new_dir"
        job = TransferJob(id="1", status=TransferStatus.PENDING)
        svc = _make_service_with_jobs([job])
        save_queue(svc, config_dir)

        assert (config_dir / "queue.json").exists()

    def test_empty_queue_writes_empty_array(self, tmp_path):
        svc = _make_service_with_jobs([])
        save_queue(svc, tmp_path)

        data = json.loads((tmp_path / "queue.json").read_text())
        assert data == []

    def test_multiple_jobs(self, tmp_path):
        svc = _make_service_with_jobs(
            [
                TransferJob(id="1", status=TransferStatus.PENDING, source="/a.txt"),
                TransferJob(id="2", status=TransferStatus.FAILED, source="/b.txt"),
                TransferJob(id="3", status=TransferStatus.COMPLETE, source="/c.txt"),
            ]
        )
        save_queue(svc, tmp_path)

        data = json.loads((tmp_path / "queue.json").read_text())
        assert len(data) == 2
        assert {d["source"] for d in data} == {"/a.txt", "/b.txt"}

    def test_handles_write_error_gracefully(self, tmp_path):
        """save_queue should not raise on write errors."""
        job = TransferJob(id="1", status=TransferStatus.PENDING)
        svc = _make_service_with_jobs([job])
        # Pass a file path as config dir to trigger error
        bad_dir = tmp_path / "queue.json"
        bad_dir.write_text("not a dir")
        save_queue(svc, bad_dir)  # should not raise


# ── load_queue ──────────────────────────────────────────────────────


class TestLoadQueue:
    def test_loads_jobs_with_restored_status(self, tmp_path):
        data = [
            {"id": "a1", "direction": "upload", "source": "/x.txt", "status": "pending"},
            {"id": "a2", "direction": "download", "source": "/y.txt", "status": "failed"},
        ]
        (tmp_path / "queue.json").write_text(json.dumps(data))

        jobs = load_queue(tmp_path)
        assert len(jobs) == 2
        assert all(j.status == TransferStatus.RESTORED for j in jobs)
        assert jobs[0].direction == TransferDirection.UPLOAD
        assert jobs[1].source == "/y.txt"

    def test_returns_empty_list_for_missing_file(self, tmp_path):
        assert load_queue(tmp_path) == []

    def test_returns_empty_list_for_empty_file(self, tmp_path):
        (tmp_path / "queue.json").write_text("")
        assert load_queue(tmp_path) == []

    def test_returns_empty_list_for_invalid_json(self, tmp_path):
        (tmp_path / "queue.json").write_text("{bad json")
        assert load_queue(tmp_path) == []

    def test_returns_empty_list_for_non_array_json(self, tmp_path):
        (tmp_path / "queue.json").write_text('{"not": "an array"}')
        assert load_queue(tmp_path) == []

    def test_skips_non_dict_entries(self, tmp_path):
        data = [{"id": "x1", "source": "/a.txt"}, "not a dict", 42]
        (tmp_path / "queue.json").write_text(json.dumps(data))

        jobs = load_queue(tmp_path)
        assert len(jobs) == 1

    def test_returns_empty_for_missing_directory(self):
        assert load_queue(Path("/nonexistent/path")) == []


# ── TransferService.restore_jobs ────────────────────────────────────


class TestTransferServiceRestoreJobs:
    def test_adds_jobs_to_service(self):
        svc = _make_service_with_jobs([])
        jobs = [
            TransferJob(id="j1", status=TransferStatus.RESTORED, source="/a.txt"),
            TransferJob(id="j2", status=TransferStatus.RESTORED, source="/b.txt"),
        ]
        svc.restore_jobs(jobs)

        assert len(svc.jobs) == 2
        assert svc.jobs[0].source == "/a.txt"
        assert svc.jobs[1].source == "/b.txt"

    def test_preserves_existing_jobs(self):
        existing = TransferJob(id="e1", status=TransferStatus.IN_PROGRESS)
        svc = _make_service_with_jobs([existing])

        restored = [TransferJob(id="r1", status=TransferStatus.RESTORED)]
        svc.restore_jobs(restored)

        assert len(svc.jobs) == 2
        assert svc.jobs[0].status == TransferStatus.IN_PROGRESS

    def test_empty_list_is_noop(self):
        svc = _make_service_with_jobs([])
        svc.restore_jobs([])
        assert len(svc.jobs) == 0


# ── Round-trip ──────────────────────────────────────────────────────


class TestRoundTrip:
    def test_save_then_load_preserves_data(self, tmp_path):
        svc = _make_service_with_jobs(
            [
                TransferJob(
                    id="r1",
                    direction=TransferDirection.UPLOAD,
                    source="/home/user/data.csv",
                    destination="/srv/data.csv",
                    total_bytes=4096,
                    transferred_bytes=0,
                    status=TransferStatus.PENDING,
                ),
                TransferJob(
                    id="r2",
                    direction=TransferDirection.DOWNLOAD,
                    source="/srv/log.txt",
                    destination="/home/user/log.txt",
                    total_bytes=999,
                    transferred_bytes=500,
                    status=TransferStatus.FAILED,
                    error="network error",
                ),
            ]
        )
        save_queue(svc, tmp_path)
        loaded = load_queue(tmp_path)

        assert len(loaded) == 2
        assert loaded[0].direction == TransferDirection.UPLOAD
        assert loaded[0].source == "/home/user/data.csv"
        assert loaded[0].destination == "/srv/data.csv"
        assert loaded[0].total_bytes == 4096
        assert loaded[0].status == TransferStatus.RESTORED

        assert loaded[1].direction == TransferDirection.DOWNLOAD
        assert loaded[1].error == "network error"
        assert loaded[1].status == TransferStatus.RESTORED

    def test_passwords_not_persisted(self, tmp_path):
        """Ensure no password-like fields appear in the JSON file."""
        job = TransferJob(id="p1", status=TransferStatus.PENDING, source="/a.txt")
        svc = _make_service_with_jobs([job])
        save_queue(svc, tmp_path)

        raw = (tmp_path / "queue.json").read_text()
        assert "password" not in raw.lower()

    def test_restored_jobs_can_be_re_saved(self, tmp_path):
        """Restored jobs should survive another save cycle."""
        job = TransferJob(id="rs1", status=TransferStatus.RESTORED, source="/x.txt")
        svc = _make_service_with_jobs([job])
        save_queue(svc, tmp_path)

        loaded = load_queue(tmp_path)
        assert len(loaded) == 1
        assert loaded[0].status == TransferStatus.RESTORED


# ── RESTORED status ─────────────────────────────────────────────────


class TestRestoredStatus:
    def test_restored_value(self):
        assert TransferStatus.RESTORED.value == "pending (restored)"

    def test_display_status_shows_pending_restored(self):
        """Dialog _refresh uses status.value for non-IN_PROGRESS jobs."""
        job = TransferJob(status=TransferStatus.RESTORED)
        assert job.status.value == "pending (restored)"
