#!/usr/bin/env python3
"""Nuitka build path for PortkeyDrop."""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
import sysconfig
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "src"
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build" / "nuitka"
DEFAULT_SOUNDPACKS_DIR = SRC_DIR / "portkeydrop" / "default_soundpacks"
APP_NAME = "PortkeyDrop"
SOUND_LIB_DATA_DEST = Path("sound_lib") / "lib"
LINUX_SYSTEM_DLL_EXCLUDES = (
    "libcrypto.so*",
    "libgio-2.0.so*",
    "libglib-2.0.so*",
    "libgmodule-2.0.so*",
    "libgobject-2.0.so*",
    "libgthread-2.0.so*",
    "libssl.so*",
)


def _repo_path(path: Path) -> str:
    """Return a POSIX-style path relative to the repository root."""
    return path.relative_to(ROOT).as_posix()


def _site_package_dir(package_name: str) -> Path | None:
    candidate_roots = [
        Path(sys.prefix),
        Path(sysconfig.get_path("purelib", vars={"base": sys.prefix, "platbase": sys.prefix})),
        Path(sysconfig.get_path("platlib", vars={"base": sys.prefix, "platbase": sys.prefix})),
    ]

    seen: set[Path] = set()
    for root in candidate_roots:
        candidate = root / package_name
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.exists():
            return candidate
    return None


def find_sound_lib_data_dir() -> Path | None:
    """Find sound_lib's native BASS library directory."""
    package_dir = _site_package_dir("sound_lib")
    if package_dir is None:
        return None
    lib_dir = package_dir / "lib"
    for native_name in ("bass.dll", "libbass.so"):
        if (lib_dir / native_name).exists() or any(lib_dir.glob(f"**/{native_name}")):
            return lib_dir
    return None


def stage_sound_lib_native_libraries(target_dir: Path) -> None:
    """Copy sound_lib's native BASS libraries into the staged app tree."""
    source_dir = find_sound_lib_data_dir()
    if source_dir is None:
        return

    target_lib_dir = target_dir / SOUND_LIB_DATA_DEST
    if target_lib_dir.exists():
        shutil.rmtree(target_lib_dir)
    target_lib_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, target_lib_dir)
    if platform.system() == "Linux":
        _mirror_sound_lib_flat_files_to_arch_dir(target_lib_dir)


def _mirror_sound_lib_flat_files_to_arch_dir(target_dir: Path) -> None:
    """Support sound_lib loaders that still search sound_lib/lib/x64 in frozen apps."""
    flat_files = [path for path in target_dir.iterdir() if path.is_file()]
    if not flat_files:
        return

    arch_dir = target_dir / "x64"
    arch_dir.mkdir(exist_ok=True)
    for path in flat_files:
        shutil.copy2(path, arch_dir / path.name)


def get_version() -> str:
    """Read the package version from pyproject.toml."""
    with (ROOT / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)["project"]["version"]


def _nuitka_version(version: str) -> str:
    """Convert a PEP 440-ish version into Nuitka's numeric Windows version format."""
    base = version.split("+", 1)[0].split(".dev", 1)[0].split("a", 1)[0].split("b", 1)[0]
    parts = [part for part in base.split(".") if part.isdigit()]
    return ".".join((parts + ["0", "0", "0", "0"])[:4])


def write_inno_version_file() -> Path:
    """Write the version handoff consumed by Inno Setup."""
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    version_file = DIST_DIR / "version.txt"
    version_file.write_text(f"[version]\nvalue={get_version()}\n", encoding="utf-8")
    return version_file


def _find_nuitka_output_dir() -> tuple[Path, str]:
    """Find the folder produced by Nuitka and return its packaging kind."""
    candidates = sorted(
        BUILD_DIR.glob("*.dist"), key=lambda path: path.stat().st_mtime, reverse=True
    )
    for candidate in candidates:
        if (candidate / f"{APP_NAME}.exe").exists() or (candidate / APP_NAME).exists():
            return candidate, "dist"

    app_candidates = sorted(
        BUILD_DIR.glob("*.app"), key=lambda path: path.stat().st_mtime, reverse=True
    )
    for candidate in app_candidates:
        if (candidate / "Contents" / "MacOS" / APP_NAME).exists():
            return candidate, "app"

    raise FileNotFoundError(f"Nuitka standalone/app output was not found under {BUILD_DIR}")


def stage_nuitka_distribution() -> Path:
    """Copy Nuitka standalone output into the layout expected by packaging helpers."""
    source_dir, output_kind = _find_nuitka_output_dir()
    if output_kind == "app":
        target_name = "PortkeyDrop.app"
    elif platform.system() == "Linux":
        target_name = "PortkeyDrop"
    else:
        target_name = "PortkeyDrop_dir"

    target_dir = DIST_DIR / target_name
    if target_dir.exists():
        shutil.rmtree(target_dir)
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, target_dir)
    if output_kind == "app":
        stage_macos_default_soundpacks(target_dir)
    elif platform.system() in ("Windows", "Linux"):
        stage_sound_lib_native_libraries(target_dir)
    return target_dir


def stage_macos_default_soundpacks(app_dir: Path) -> None:
    """Copy default sound packs into the macOS app Resources directory."""
    if not DEFAULT_SOUNDPACKS_DIR.exists():
        return
    target_dir = app_dir / "Contents" / "Resources" / "portkeydrop" / "default_soundpacks"
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(DEFAULT_SOUNDPACKS_DIR, target_dir)


def create_portable_zip() -> bool:
    """Create a portable archive from the staged Nuitka output."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from installer import build

    original_dist_dir = build.DIST_DIR
    try:
        build.DIST_DIR = DIST_DIR
        return build.create_portable_zip()
    finally:
        build.DIST_DIR = original_dist_dir


def create_windows_installer() -> bool:
    """Create the Windows Inno Setup installer from the staged Nuitka folder."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from installer import build

    original_dist_dir = build.DIST_DIR
    try:
        build.DIST_DIR = DIST_DIR
        return build.create_windows_installer()
    finally:
        build.DIST_DIR = original_dist_dir


def build_nuitka_command(
    *,
    output_dir: Path,
    build_tag: str | None,
    assume_platform: str | None = None,
) -> list[str]:
    """Build the Nuitka command for the current platform."""
    system = assume_platform or platform.system()
    version = get_version()
    numeric_version = _nuitka_version(version)

    mode = "--mode=app" if system == "Darwin" else "--mode=standalone"
    command = [
        sys.executable,
        "-m",
        "nuitka",
        mode,
        "--assume-yes-for-downloads",
        "--jobs=1",
        "--noinclude-pytest-mode=nofollow",
        "--nofollow-import-to=chardet",
        "--nofollow-import-to=chardet.*",
        "--include-package-data=keyring",
        "--include-package-data=prism:_native/*",
        "--include-package-data=webdav3",
        f"--output-dir={output_dir.as_posix()}",
        f"--output-filename={APP_NAME}",
        f"--report={(output_dir / 'compilation-report.xml').as_posix()}",
        f"--product-name={APP_NAME}",
        f"--file-description={APP_NAME}",
        f"--product-version={numeric_version}",
        f"--file-version={numeric_version}",
        _repo_path(ROOT / "installer" / "nuitka_entry.py"),
    ]

    if DEFAULT_SOUNDPACKS_DIR.exists() and system != "Darwin":
        command.insert(
            -1,
            f"--include-data-dir={_repo_path(DEFAULT_SOUNDPACKS_DIR)}=portkeydrop/default_soundpacks",
        )

    if build_tag:
        command.insert(-1, f"--company-name=Orinks ({build_tag})")
    else:
        command.insert(-1, "--company-name=Orinks")

    if system == "Windows":
        command.append("--windows-console-mode=disable")
        command.append("--include-module=win32timezone")
        icon = ROOT / "installer" / "app.ico"
        if icon.exists():
            command.append(f"--windows-icon-from-ico={_repo_path(icon)}")
    elif system == "Darwin":
        command.append(f"--macos-app-name={APP_NAME}")
        icon = ROOT / "installer" / "app.icns"
        if icon.exists():
            command.append(f"--macos-app-icon={_repo_path(icon)}")
    elif system == "Linux":
        command.extend(f"--noinclude-dlls={pattern}" for pattern in LINUX_SYSTEM_DLL_EXCLUDES)

    return command


def run_command(command: list[str]) -> None:
    """Run a command from the project root."""
    print("Running:", " ".join(command))
    subprocess.run(command, cwd=ROOT, check=True)


def ensure_nuitka_available() -> None:
    """Fail early with a useful message if Nuitka is not installed."""
    if shutil.which("nuitka") is None:
        try:
            subprocess.run(
                [sys.executable, "-m", "nuitka", "--version"],
                cwd=ROOT,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise RuntimeError("Nuitka is not installed. Run: pip install nuitka") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Build PortkeyDrop with Nuitka.")
    parser.add_argument("--tag", default=None, help="Build tag, e.g. nightly-20260526.")
    parser.add_argument("--skip-compile", action="store_true", help="Only write version metadata.")
    parser.add_argument(
        "--skip-installer",
        action="store_true",
        help="Skip creating the Windows Inno Setup installer.",
    )
    args = parser.parse_args()

    print(f"PortkeyDrop Nuitka build, version {get_version()}")
    write_inno_version_file()

    if args.skip_compile:
        return 0

    ensure_nuitka_available()
    run_command(build_nuitka_command(output_dir=BUILD_DIR, build_tag=args.tag))
    stage_nuitka_distribution()
    if (
        platform.system() == "Windows"
        and not args.skip_installer
        and not create_windows_installer()
    ):
        return 1
    if not create_portable_zip():
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
