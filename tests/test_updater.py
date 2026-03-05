"""Tests for updater service behavior."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from portkeydrop.services import updater


def test_parse_nightly_date_extracts_yyyymmdd():
    assert updater.parse_nightly_date("nightly-20260305") == "20260305"
    assert updater.parse_nightly_date("v0.2.0") is None


def test_select_latest_release_respects_channel():
    releases = [
        {"tag_name": "v0.1.0", "prerelease": False, "published_at": "2026-01-01T00:00:00Z"},
        {
            "tag_name": "nightly-20260201",
            "prerelease": True,
            "published_at": "2026-02-01T00:00:00Z",
        },
        {"tag_name": "v0.2.0", "prerelease": False, "published_at": "2026-02-10T00:00:00Z"},
        {
            "tag_name": "nightly-20260301",
            "prerelease": True,
            "published_at": "2026-03-01T00:00:00Z",
        },
    ]

    stable = updater.select_latest_release(releases, "stable")
    nightly = updater.select_latest_release(releases, "nightly")

    assert stable is not None
    assert stable["tag_name"] == "v0.2.0"
    assert nightly is not None
    assert nightly["tag_name"] == "nightly-20260301"


def test_is_update_available_handles_stable_and_nightly():
    stable_release = {"tag_name": "v1.3.0"}
    nightly_release = {"tag_name": "nightly-20260305"}

    assert updater.is_update_available(stable_release, current_version="1.2.0")
    assert not updater.is_update_available(stable_release, current_version="1.3.0")
    assert updater.is_update_available(
        nightly_release,
        current_version="1.0.0",
        current_nightly_date="20260301",
    )
    assert not updater.is_update_available(
        nightly_release,
        current_version="1.0.0",
        current_nightly_date="20260305",
    )


def test_select_asset_prefers_windows_installer_or_portable_zip():
    release = {
        "assets": [
            {"name": "checksums.sha256"},
            {"name": "PortkeyDrop_Portable_v0.2.0.zip"},
            {"name": "PortkeyDrop_Setup_v0.2.0.exe"},
        ]
    }

    portable_asset = updater.select_asset(release, portable=True, platform_system="Windows")
    installer_asset = updater.select_asset(release, portable=False, platform_system="Windows")

    assert portable_asset is not None
    assert portable_asset["name"].endswith(".zip")
    assert installer_asset is not None
    assert installer_asset["name"].endswith(".exe")


def test_parse_checksum_file_supports_single_line_and_manifest():
    one_line = "0" * 64
    manifest = f"{'a' * 64} *other.bin\n{'b' * 64} *target.zip\n"

    assert updater.parse_checksum_file(one_line, "target.zip") == ("sha256", one_line)
    assert updater.parse_checksum_file(manifest, "target.zip") == ("sha256", "b" * 64)


def test_plan_restart_kind_by_platform_and_mode(tmp_path, monkeypatch):
    exe_path = tmp_path / "PortkeyDrop.exe"
    exe_path.write_text("stub", encoding="utf-8")
    monkeypatch.setattr(updater.sys, "executable", str(exe_path))

    windows_portable = updater.plan_restart(
        tmp_path / "update.zip",
        portable=True,
        platform_system="Windows",
    )
    windows_installer = updater.plan_restart(
        tmp_path / "setup.exe",
        portable=False,
        platform_system="Windows",
    )
    macos = updater.plan_restart(
        tmp_path / "update.dmg",
        portable=False,
        platform_system="Darwin",
    )

    assert windows_portable.kind == "portable"
    assert windows_portable.script_path is not None
    assert windows_portable.script_path.name == "portkeydrop_portable_update.bat"
    assert windows_installer.kind == "windows_installer"
    assert windows_installer.command == [str(tmp_path / "setup.exe")]
    assert macos.kind == "macos_script"
    assert macos.script_path is not None
    assert macos.script_path.name == "portkeydrop_update.sh"


def test_check_for_updates_returns_update_info(monkeypatch):
    service = updater.UpdateService("PortkeyDropTests")
    releases = [
        {
            "tag_name": "v1.2.0",
            "prerelease": False,
            "published_at": "2026-02-02T00:00:00Z",
            "body": "notes",
            "assets": [
                {
                    "name": "PortkeyDrop_Setup_v1.2.0.exe",
                    "browser_download_url": "https://example.invalid/setup.exe",
                }
            ],
        }
    ]
    monkeypatch.setattr(service, "fetch_releases", lambda: releases)

    result = service.check_for_updates(
        current_version="1.1.0",
        channel="stable",
        portable=False,
        platform_system="Windows",
    )

    assert result is not None
    info, release = result
    assert info.version == "1.2.0"
    assert info.artifact_name.endswith(".exe")
    assert info.download_url == "https://example.invalid/setup.exe"
    assert release["tag_name"] == "v1.2.0"


def test_verify_file_checksum_round_trip(tmp_path):
    file_path = tmp_path / "artifact.bin"
    file_path.write_bytes(b"hello updater")

    import hashlib

    digest = hashlib.sha256(b"hello updater").hexdigest()
    assert updater.verify_file_checksum(file_path, "sha256", digest)
    assert not updater.verify_file_checksum(file_path, "sha256", "0" * 64)


def test_is_update_available_returns_false_for_invalid_stable_versions():
    assert not updater.is_update_available({"tag_name": "v1.bad"}, current_version="1.0.0")
    assert not updater.is_update_available({"tag_name": "v1.2.0"}, current_version="current")


def test_select_latest_release_returns_none_when_channel_has_no_matches():
    releases = [{"tag_name": "v1.0.0", "prerelease": False, "published_at": "2026-01-01T00:00:00Z"}]
    assert updater.select_latest_release(releases, "nightly") is None


def test_find_checksum_asset_prefers_exact_then_generic():
    release = {
        "assets": [
            {"name": "checksums.sha256", "browser_download_url": "https://example.invalid/generic"},
            {
                "name": "PortkeyDrop.zip.sha256",
                "browser_download_url": "https://example.invalid/exact",
            },
        ]
    }
    exact = updater.find_checksum_asset(release, "PortkeyDrop.zip")
    assert exact is not None
    assert exact["browser_download_url"].endswith("/exact")

    only_generic = {
        "assets": [{"name": "sha256sums", "browser_download_url": "https://example.invalid/g"}]
    }
    generic = updater.find_checksum_asset(only_generic, "PortkeyDrop.zip")
    assert generic is not None
    assert generic["name"] == "sha256sums"
    assert updater.find_checksum_asset({"assets": []}, "PortkeyDrop.zip") is None


def test_parse_checksum_file_supports_sha512_and_md5_and_skips_invalid():
    content = f"\n{'x' * 31} *skip.bin\n{'a' * 128} *target.zip\n{'b' * 32} *other.zip\n"
    assert updater.parse_checksum_file(content, "target.zip") == ("sha512", "a" * 128)

    md5_manifest = f"{'c' * 32} *target.zip\n"
    assert updater.parse_checksum_file(md5_manifest, "target.zip") == ("md5", "c" * 32)
    assert updater.parse_checksum_file("not-a-digest target.zip", "target.zip") is None


def test_select_asset_filters_signatures_and_handles_mac_linux_and_fallback():
    release = {
        "assets": [
            {"name": "PortkeyDrop.sig"},
            {"name": "verify.json"},
            {"name": "PortkeyDrop.dmg"},
            {"name": "PortkeyDrop.deb"},
            {"name": "PortkeyDrop-raw.bin"},
        ]
    }
    mac = updater.select_asset(release, portable=False, platform_system="Darwin")
    linux = updater.select_asset(release, portable=False, platform_system="Linux")

    assert mac is not None and mac["name"].endswith(".dmg")
    assert linux is not None and linux["name"].endswith(".deb")

    fallback = updater.select_asset(
        {"assets": [{"name": "checksums.sha256"}, {"name": "PortkeyDrop-raw.bin"}]},
        portable=False,
        platform_system="Plan9",
    )
    assert fallback is not None and fallback["name"] == "PortkeyDrop-raw.bin"


def test_script_builders_include_expected_paths(tmp_path):
    portable = updater.build_portable_update_script(
        zip_path=tmp_path / "update.zip",
        target_dir=tmp_path / "app",
        exe_path=tmp_path / "app" / "PortkeyDrop.exe",
    )
    assert "Expand-Archive" in portable
    assert "PortkeyDrop.exe" in portable

    mac = updater.build_macos_update_script(
        update_path=tmp_path / "update.dmg",
        app_path=tmp_path / "PortkeyDrop.app",
    )
    assert "hdiutil attach" in mac
    assert "open" in mac


def test_plan_restart_returns_unsupported_for_unknown_platform(tmp_path):
    plan = updater.plan_restart(tmp_path / "update.bin", portable=False, platform_system="Solaris")
    assert plan.kind == "unsupported"
    assert plan.command == [str(tmp_path / "update.bin")]


def test_apply_update_branches(monkeypatch, tmp_path):
    update_path = tmp_path / "update.zip"
    update_path.write_text("data", encoding="utf-8")
    exe_path = tmp_path / "PortkeyDrop.exe"
    exe_path.write_text("exe", encoding="utf-8")
    monkeypatch.setattr(updater.sys, "executable", str(exe_path))

    popen_calls: list[list[str]] = []

    def fake_popen(cmd, shell=False, cwd=None):
        popen_calls.append(list(cmd))
        return SimpleNamespace()

    exits: list[int] = []

    def fake_exit(code):
        exits.append(code)
        raise SystemExit(code)

    monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(updater.os, "_exit", fake_exit)

    portable_script = tmp_path / "portable.bat"
    monkeypatch.setattr(
        updater,
        "plan_restart",
        lambda *_a, **_kw: updater.RestartPlan("portable", [str(portable_script)], portable_script),
    )
    with pytest.raises(SystemExit):
        updater.apply_update(update_path, portable=True, platform_system="Windows")
    assert portable_script.exists()

    mac_script = tmp_path / "update.sh"
    monkeypatch.setattr(
        updater,
        "plan_restart",
        lambda *_a, **_kw: updater.RestartPlan(
            "macos_script", ["bash", str(mac_script)], mac_script
        ),
    )
    with pytest.raises(SystemExit):
        updater.apply_update(update_path, portable=False, platform_system="Darwin")
    assert mac_script.exists()

    monkeypatch.setattr(
        updater,
        "plan_restart",
        lambda *_a, **_kw: updater.RestartPlan("windows_installer", [str(update_path)]),
    )
    with pytest.raises(SystemExit):
        updater.apply_update(update_path, portable=False, platform_system="Windows")

    warning = MagicMock()
    monkeypatch.setattr(updater.logger, "warning", warning)
    monkeypatch.setattr(
        updater,
        "plan_restart",
        lambda *_a, **_kw: updater.RestartPlan("unsupported", [str(update_path)]),
    )
    updater.apply_update(update_path, portable=False, platform_system="Linux")
    warning.assert_called_once()
    assert exits == [0, 0, 0]
    assert any("portable.bat" in " ".join(call) for call in popen_calls)
    assert any("update.sh" in " ".join(call) for call in popen_calls)


class _FakeHTTPResponse:
    def __init__(self, data: bytes, *, headers: dict[str, str] | None = None, chunks=None):
        self._data = data
        self._offset = 0
        self.headers = headers or {}
        self._chunks = list(chunks or [])

    def read(self, size=-1):
        if self._chunks:
            return self._chunks.pop(0)
        if size < 0:
            return self._data
        if self._offset >= len(self._data):
            return b""
        chunk = self._data[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_json_get_and_fetch_releases(monkeypatch):
    service = updater.UpdateService("PortkeyDropTests")
    requests = []

    def fake_urlopen(req, timeout):
        requests.append((req.full_url, timeout, req.headers.get("User-agent")))
        body = json.dumps([{"tag_name": "v1.0.0"}]).encode("utf-8")
        return _FakeHTTPResponse(body)

    monkeypatch.setattr(updater, "urlopen", fake_urlopen)
    releases = service.fetch_releases()
    assert releases == [{"tag_name": "v1.0.0"}]
    assert requests[0][0].startswith("https://api.github.com/repos/")
    assert requests[0][2] == "PortkeyDropTests"

    monkeypatch.setattr(service, "_json_get", lambda _url: {"unexpected": "object"})
    assert service.fetch_releases() == []


def test_check_for_updates_returns_none_when_no_update_or_no_asset(monkeypatch):
    service = updater.UpdateService("PortkeyDropTests")
    monkeypatch.setattr(service, "fetch_releases", lambda: [])
    assert (
        service.check_for_updates(
            current_version="1.0.0",
            channel="stable",
            portable=False,
            platform_system="Windows",
        )
        is None
    )

    releases = [
        {
            "tag_name": "v1.0.0",
            "prerelease": False,
            "published_at": "2026-02-02T00:00:00Z",
            "assets": [],
        }
    ]
    monkeypatch.setattr(service, "fetch_releases", lambda: releases)
    assert (
        service.check_for_updates(
            current_version="1.0.0",
            channel="stable",
            portable=False,
            platform_system="Windows",
        )
        is None
    )


def test_check_for_updates_uses_portable_mode_when_portable_not_provided(monkeypatch):
    service = updater.UpdateService("PortkeyDropTests")
    releases = [
        {
            "tag_name": "v1.1.0",
            "prerelease": False,
            "published_at": "2026-02-02T00:00:00Z",
            "assets": [
                {
                    "name": "PortkeyDrop_Portable_v1.1.0.zip",
                    "browser_download_url": "https://x/y.zip",
                }
            ],
        }
    ]
    monkeypatch.setattr(service, "fetch_releases", lambda: releases)
    monkeypatch.setattr(updater, "is_portable_mode", lambda: True)

    result = service.check_for_updates(
        current_version="1.0.0", channel="stable", platform_system="Windows"
    )
    assert result is not None
    assert result[0].artifact_name.endswith(".zip")


def test_download_file_writes_chunks_and_reports_progress(monkeypatch, tmp_path):
    service = updater.UpdateService("PortkeyDropTests")
    dest = tmp_path / "file.bin"
    calls: list[tuple[int, int]] = []

    def fake_urlopen(req, timeout):
        assert req.headers.get("User-agent") == "PortkeyDropTests"
        return _FakeHTTPResponse(
            b"",
            headers={"Content-Length": "6"},
            chunks=[b"abc", b"def", b""],
        )

    monkeypatch.setattr(updater, "urlopen", fake_urlopen)
    service._download_file(
        "https://example.invalid/file.bin", dest, lambda d, t: calls.append((d, t))
    )
    assert dest.read_bytes() == b"abcdef"
    assert calls == [(3, 6), (6, 6)]


def test_download_update_with_checksum_verification(monkeypatch, tmp_path):
    service = updater.UpdateService("PortkeyDropTests")
    info = updater.UpdateInfo(
        version="1.2.3",
        download_url="https://example.invalid/PortkeyDrop.zip",
        artifact_name="PortkeyDrop.zip",
        release_notes="notes",
        is_nightly=False,
        is_prerelease=False,
    )
    payload = b"payload-data"

    def fake_download(url, dest_path, progress_callback=None):
        assert url == info.download_url
        dest_path.write_bytes(payload)
        if progress_callback:
            progress_callback(len(payload), len(payload))

    monkeypatch.setattr(service, "_download_file", fake_download)
    manifest = f"{updater.hashlib.sha256(payload).hexdigest()} *PortkeyDrop.zip\n".encode("utf-8")
    monkeypatch.setattr(updater, "urlopen", lambda req, timeout: _FakeHTTPResponse(manifest))

    release = {
        "assets": [
            {
                "name": "checksums.sha256",
                "browser_download_url": "https://example.invalid/checksums.sha256",
            }
        ]
    }
    out = service.download_update(info, dest_dir=tmp_path, release=release)
    assert out.read_bytes() == payload


def test_download_update_raises_on_checksum_mismatch(monkeypatch, tmp_path):
    service = updater.UpdateService("PortkeyDropTests")
    info = updater.UpdateInfo(
        version="1.2.3",
        download_url="https://example.invalid/PortkeyDrop.zip",
        artifact_name="PortkeyDrop.zip",
        release_notes="notes",
        is_nightly=False,
        is_prerelease=False,
    )
    monkeypatch.setattr(
        service, "_download_file", lambda _u, dest, _cb=None: dest.write_bytes(b"payload")
    )
    bad_manifest = f"{'0' * 64} *PortkeyDrop.zip\n".encode("utf-8")
    monkeypatch.setattr(updater, "urlopen", lambda req, timeout: _FakeHTTPResponse(bad_manifest))

    release = {
        "assets": [
            {
                "name": "checksums.sha256",
                "browser_download_url": "https://example.invalid/checksums.sha256",
            }
        ]
    }
    with pytest.raises(updater.ChecksumVerificationError):
        service.download_update(info, dest_dir=tmp_path, release=release)
    assert not (tmp_path / "PortkeyDrop.zip").exists()


def test_download_update_ignores_checksum_fetch_errors(monkeypatch, tmp_path):
    service = updater.UpdateService("PortkeyDropTests")
    info = updater.UpdateInfo(
        version="1.2.3",
        download_url="https://example.invalid/PortkeyDrop.zip",
        artifact_name="PortkeyDrop.zip",
        release_notes="notes",
        is_nightly=False,
        is_prerelease=False,
    )
    monkeypatch.setattr(
        service, "_download_file", lambda _u, dest, _cb=None: dest.write_bytes(b"payload")
    )
    monkeypatch.setattr(
        updater, "urlopen", lambda req, timeout: (_ for _ in ()).throw(OSError("network"))
    )
    warning = MagicMock()
    monkeypatch.setattr(updater.logger, "warning", warning)

    release = {
        "assets": [
            {
                "name": "checksums.sha256",
                "browser_download_url": "https://example.invalid/checksums.sha256",
            }
        ]
    }
    out = service.download_update(info, dest_dir=tmp_path, release=release)
    assert out.exists()
    warning.assert_called_once()


def test_download_update_uses_temp_dir_when_not_provided(monkeypatch, tmp_path):
    service = updater.UpdateService("PortkeyDropTests")
    info = updater.UpdateInfo(
        version="1.2.3",
        download_url="https://example.invalid/PortkeyDrop.zip",
        artifact_name="PortkeyDrop.zip",
        release_notes="notes",
        is_nightly=False,
        is_prerelease=False,
    )
    monkeypatch.setattr(updater.tempfile, "mkdtemp", lambda prefix: str(tmp_path / "generated"))
    monkeypatch.setattr(
        service, "_download_file", lambda _u, dest, _cb=None: dest.write_bytes(b"payload")
    )
    out = service.download_update(info, dest_dir=None, release=None)
    assert out == tmp_path / "generated" / "PortkeyDrop.zip"
    assert out.exists()
