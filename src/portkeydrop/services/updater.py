"""GitHub release updater for Portkey Drop."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import subprocess
import sys
import tempfile
import textwrap
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from portkeydrop.portable import is_portable_mode

logger = logging.getLogger(__name__)

GITHUB_OWNER = "Orinks"
GITHUB_REPO = "PortkeyDrop"
GITHUB_RELEASES_URL = "https://api.github.com/repos/{owner}/{repo}/releases?per_page=20"
NIGHTLY_TAG_PATTERN = re.compile(r"nightly-(\d{8})", re.IGNORECASE)

ProgressCallback = Callable[[int, int], None]


@dataclass(frozen=True)
class UpdateInfo:
    """Resolved update metadata for one release artifact."""

    version: str
    download_url: str
    artifact_name: str
    release_notes: str
    is_nightly: bool
    is_prerelease: bool


@dataclass(frozen=True)
class RestartPlan:
    """How to apply the downloaded update."""

    kind: str
    command: list[str]
    script_path: Path | None = None


class ChecksumVerificationError(Exception):
    """Raised when a downloaded artifact fails checksum verification."""


def parse_nightly_date(tag_name: str) -> str | None:
    """Extract YYYYMMDD from nightly tags."""
    match = NIGHTLY_TAG_PATTERN.search(tag_name or "")
    return match.group(1) if match else None


def is_nightly_release(release: dict[str, Any]) -> bool:
    """Return True if release tag matches nightly format."""
    return parse_nightly_date(release.get("tag_name", "")) is not None


def get_release_identifier(release: dict[str, Any]) -> tuple[str, str]:
    """Return (identifier, release_type) where type is stable/nightly."""
    tag = str(release.get("tag_name", ""))
    nightly = parse_nightly_date(tag)
    if nightly:
        return nightly, "nightly"
    return tag.lstrip("v"), "stable"


def _parse_stable_version(value: str) -> tuple[int, ...] | None:
    value = value.lstrip("v")
    match = re.match(r"^(\d+(?:\.\d+)*)", value)
    if not match:
        return None
    try:
        return tuple(int(part) for part in match.group(1).split("."))
    except ValueError:
        return None


def is_update_available(
    release: dict[str, Any],
    current_version: str,
    current_nightly_date: str | None = None,
) -> bool:
    """Return whether *release* is newer than current version/build."""
    identifier, release_type = get_release_identifier(release)

    if release_type == "nightly":
        if current_nightly_date:
            return identifier > current_nightly_date
        return True

    new_v = _parse_stable_version(identifier)
    cur_v = _parse_stable_version(current_version)
    if not new_v or not cur_v:
        return False
    return new_v > cur_v


def select_latest_release(releases: list[dict[str, Any]], channel: str) -> dict[str, Any] | None:
    """Pick the newest release for the configured channel."""
    channel = channel.lower()
    filtered: list[dict[str, Any]] = []

    for release in releases:
        is_prerelease = bool(release.get("prerelease"))
        nightly = is_nightly_release(release)
        if channel == "stable" and (is_prerelease or nightly):
            continue
        if channel == "nightly" and not nightly:
            continue
        filtered.append(release)

    def sort_key(item: dict[str, Any]) -> str:
        return str(item.get("published_at") or item.get("created_at") or "")

    return max(filtered, key=sort_key, default=None)


def find_checksum_asset(release: dict[str, Any], artifact_name: str) -> dict[str, Any] | None:
    """Find a checksum asset matching artifact_name or generic checksums file."""
    assets = release.get("assets", [])
    lower_artifact = artifact_name.lower()

    for ext in (".sha256", ".sha512"):
        for asset in assets:
            name = str(asset.get("name", "")).lower()
            if name == lower_artifact + ext:
                return asset

    generic_names = {
        "checksums.sha256",
        "sha256sums",
        "checksums.sha512",
        "sha512sums",
        "checksums.txt",
    }
    for asset in assets:
        name = str(asset.get("name", "")).lower()
        if name in generic_names:
            return asset
    return None


def parse_checksum_file(content: str, artifact_name: str) -> tuple[str, str] | None:
    """Extract checksum tuple (algo, hex) from checksum file content."""
    lines = content.strip().splitlines()
    lower_artifact = artifact_name.lower()

    for line in lines:
        line = line.strip()
        if not line:
            continue

        parts = line.split(None, 1)
        digest = parts[0]
        digest_len = len(digest)
        if digest_len == 64:
            algo = "sha256"
        elif digest_len == 128:
            algo = "sha512"
        elif digest_len == 32:
            algo = "md5"
        else:
            continue

        if len(parts) == 1 and len(lines) == 1:
            return algo, digest.lower()

        if len(parts) == 2:
            filename = parts[1].lstrip("*").strip().lower()
            if filename == lower_artifact:
                return algo, digest.lower()

    return None


def verify_file_checksum(file_path: Path, algorithm: str, expected_hash: str) -> bool:
    """Hash the downloaded artifact and compare with expected hash."""
    digest = hashlib.new(algorithm)
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest().lower() == expected_hash.lower()


def select_asset(
    release: dict[str, Any],
    *,
    portable: bool,
    platform_system: str | None = None,
) -> dict[str, Any] | None:
    """Pick the best artifact for this platform/mode."""
    system = (platform_system or platform.system()).lower()
    assets = release.get("assets", [])

    deny_extensions = (
        ".sha256",
        ".sha512",
        ".md5",
        ".sig",
        ".asc",
        ".txt",
        ".json",
    )

    filtered = []
    for asset in assets:
        name = str(asset.get("name", ""))
        lower = name.lower()
        if any(lower.endswith(ext) for ext in deny_extensions):
            continue
        if "signature" in lower or "verify" in lower:
            continue
        filtered.append(asset)

    if "windows" in system:
        if portable:
            for asset in filtered:
                name = str(asset.get("name", "")).lower()
                if "portable" in name and name.endswith(".zip"):
                    return asset
            for asset in filtered:
                if str(asset.get("name", "")).lower().endswith(".zip"):
                    return asset
        for ext in (".exe", ".msi"):
            for asset in filtered:
                if str(asset.get("name", "")).lower().endswith(ext):
                    return asset
    elif "darwin" in system or "mac" in system:
        for ext in (".dmg", ".pkg"):
            for asset in filtered:
                if str(asset.get("name", "")).lower().endswith(ext):
                    return asset
    else:
        for ext in (".appimage", ".deb", ".rpm", ".tar.gz"):
            for asset in filtered:
                if str(asset.get("name", "")).lower().endswith(ext):
                    return asset

    return filtered[0] if filtered else (assets[0] if assets else None)


def build_portable_update_script(zip_path: Path, target_dir: Path, exe_path: Path) -> str:
    """Build update script for Windows portable ZIP update apply."""
    return textwrap.dedent(
        f"""
        @echo off
        set "PID={os.getpid()}"
        set "ZIP_PATH={zip_path}"
        set "TARGET_DIR={target_dir}"
        set "EXE_PATH={exe_path}"
        set "EXTRACT_DIR={target_dir / "update_tmp"}"

        :WAIT_LOOP
        tasklist /FI "PID eq %PID%" 2>NUL | find /I /N "%PID%" >NUL
        if "%ERRORLEVEL%"=="0" (
            timeout /t 1 /nobreak >NUL
            goto WAIT_LOOP
        )

        if exist "%EXTRACT_DIR%" rd /s /q "%EXTRACT_DIR%"
        powershell -Command "Expand-Archive -Path '%ZIP_PATH%' -DestinationPath '%EXTRACT_DIR%' -Force"

        set "COPY_SRC=%EXTRACT_DIR%"
        if not exist "%EXTRACT_DIR%\\PortkeyDrop.exe" (
            for /d %%D in ("%EXTRACT_DIR%\\*") do (
                if exist "%%D\\PortkeyDrop.exe" set "COPY_SRC=%%D"
            )
        )

        xcopy "%COPY_SRC%\\*" "%TARGET_DIR%\\" /E /H /Y /Q
        rd /s /q "%EXTRACT_DIR%"
        del "%ZIP_PATH%"
        timeout /t 2 /nobreak >NUL
        start "" "%EXE_PATH%" --updated
        (goto) 2>nul & del "%~f0"
        """
    ).strip()


def build_macos_update_script(update_path: Path, app_path: Path) -> str:
    """Build shell script to apply a macOS ZIP/DMG update."""
    app_dir = app_path.parent
    return textwrap.dedent(
        f"""
        #!/bin/bash
        sleep 2
        if [[ "{update_path}" == *.zip ]]; then
            unzip -o "{update_path}" -d "{app_dir}"
        elif [[ "{update_path}" == *.dmg ]]; then
            hdiutil attach "{update_path}" -nobrowse -quiet
            cp -R /Volumes/*/*.app "{app_dir}/"
            hdiutil detach /Volumes/* -quiet
        fi
        open "{app_path}" --args --updated
        rm -f "$0" "{update_path}"
        """
    ).strip()


def plan_restart(
    update_path: Path,
    *,
    portable: bool,
    platform_system: str | None = None,
) -> RestartPlan:
    """Return restart plan for platform/update artifact."""
    system = (platform_system or platform.system()).lower()

    if "windows" in system and portable:
        exe_path = Path(sys.executable).resolve()
        script_path = exe_path.parent / "portkeydrop_portable_update.bat"
        return RestartPlan("portable", [str(script_path)], script_path=script_path)
    if "windows" in system:
        return RestartPlan("windows_installer", [str(update_path)])
    if "darwin" in system or "mac" in system:
        temp_dir = Path(tempfile.mkdtemp(prefix="portkeydrop_update_"))
        script_path = temp_dir / "portkeydrop_update.sh"
        return RestartPlan("macos_script", ["bash", str(script_path)], script_path=script_path)
    return RestartPlan("unsupported", [str(update_path)])


def apply_update(
    update_path: Path,
    *,
    portable: bool,
    platform_system: str | None = None,
) -> None:
    """Launch update installer/script and exit current process."""
    plan = plan_restart(update_path, portable=portable, platform_system=platform_system)

    if plan.kind == "portable" and plan.script_path:
        exe_path = Path(sys.executable).resolve()
        script_content = build_portable_update_script(update_path, exe_path.parent, exe_path)
        plan.script_path.write_text(script_content, encoding="utf-8")
        subprocess.Popen([str(plan.script_path)], shell=False, cwd=str(exe_path.parent))
        os._exit(0)

    if plan.kind == "macos_script" and plan.script_path:
        exe_path = Path(sys.executable).resolve()
        app_path = exe_path.parent.parent.parent
        script_content = build_macos_update_script(update_path, app_path)
        plan.script_path.write_text(script_content, encoding="utf-8")
        plan.script_path.chmod(0o700)
        subprocess.Popen(["bash", str(plan.script_path)], shell=False)
        os._exit(0)

    if plan.kind == "windows_installer":
        subprocess.Popen(plan.command, shell=False)
        os._exit(0)

    logger.warning("Manual update required: %s", update_path)


class UpdateService:
    """Updater service backed by GitHub Releases API."""

    def __init__(
        self,
        app_name: str,
        owner: str = GITHUB_OWNER,
        repo: str = GITHUB_REPO,
        timeout: float = 30.0,
    ) -> None:
        self.app_name = app_name
        self.owner = owner
        self.repo = repo
        self.timeout = timeout

    def _json_get(self, url: str) -> Any:
        req = Request(
            url,
            headers={
                "User-Agent": self.app_name,
                "Accept": "application/vnd.github+json",
            },
        )
        with urlopen(req, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def fetch_releases(self) -> list[dict[str, Any]]:
        """Fetch recent release entries from GitHub API."""
        url = GITHUB_RELEASES_URL.format(owner=self.owner, repo=self.repo)
        payload = self._json_get(url)
        return payload if isinstance(payload, list) else []

    def check_for_updates(
        self,
        *,
        current_version: str,
        current_nightly_date: str | None = None,
        channel: str = "stable",
        portable: bool | None = None,
        platform_system: str | None = None,
    ) -> tuple[UpdateInfo, dict[str, Any]] | None:
        """Resolve update info and matching release metadata if update exists."""
        releases = self.fetch_releases()
        latest = select_latest_release(releases, channel)
        if not latest:
            return None

        if not is_update_available(latest, current_version, current_nightly_date):
            return None

        portable_flag = portable if portable is not None else is_portable_mode()
        asset = select_asset(latest, portable=portable_flag, platform_system=platform_system)
        if not asset:
            return None

        identifier, release_type = get_release_identifier(latest)
        info = UpdateInfo(
            version=identifier,
            download_url=str(asset.get("browser_download_url", "")),
            artifact_name=str(asset.get("name", "")),
            release_notes=str(latest.get("body", "")),
            is_nightly=release_type == "nightly",
            is_prerelease=bool(latest.get("prerelease")),
        )
        return info, latest

    def _download_file(
        self,
        url: str,
        dest_path: Path,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        req = Request(url, headers={"User-Agent": self.app_name})
        with urlopen(req, timeout=self.timeout) as response:
            total = int(response.headers.get("Content-Length", "0") or 0)
            downloaded = 0
            with dest_path.open("wb") as handle:
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    handle.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded, total)

    def download_update(
        self,
        update_info: UpdateInfo,
        dest_dir: Path | None = None,
        progress_callback: ProgressCallback | None = None,
        release: dict[str, Any] | None = None,
    ) -> Path:
        """Download update artifact and verify checksum when checksum asset exists."""
        if dest_dir is None:
            dest_dir = Path(tempfile.mkdtemp(prefix="portkeydrop_update_"))
        dest_dir.mkdir(parents=True, exist_ok=True)

        dest_path = dest_dir / update_info.artifact_name
        self._download_file(update_info.download_url, dest_path, progress_callback)
        logger.info("Downloaded update to %s", dest_path)

        if release:
            checksum_asset = find_checksum_asset(release, update_info.artifact_name)
            checksum_url = (
                str(checksum_asset.get("browser_download_url", "")) if checksum_asset else ""
            )
            if checksum_url:
                try:
                    req = Request(checksum_url, headers={"User-Agent": self.app_name})
                    with urlopen(req, timeout=self.timeout) as response:
                        checksum_content = response.read().decode("utf-8")
                    parsed = parse_checksum_file(checksum_content, update_info.artifact_name)
                    if parsed:
                        algo, expected_hash = parsed
                        if not verify_file_checksum(dest_path, algo, expected_hash):
                            dest_path.unlink(missing_ok=True)
                            raise ChecksumVerificationError(
                                f"Checksum verification failed for {update_info.artifact_name}"
                            )
                        logger.info(
                            "Checksum verified (%s) for %s", algo, update_info.artifact_name
                        )
                except OSError:
                    logger.warning(
                        "Could not fetch checksum file for %s", update_info.artifact_name
                    )

        return dest_path
