"""Tests for updater service behavior."""

from __future__ import annotations


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
