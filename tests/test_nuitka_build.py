from __future__ import annotations

import tomllib
import zipfile
from pathlib import Path

import pytest

from installer import build, build_nuitka


def _pyproject_version() -> str:
    with (build_nuitka.ROOT / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)["project"]["version"]


def test_get_version_reads_pyproject() -> None:
    assert build_nuitka.get_version() == _pyproject_version()


def test_write_inno_version_file_uses_pyproject_version(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(build_nuitka, "DIST_DIR", tmp_path)

    version_file = build_nuitka.write_inno_version_file()

    assert version_file == tmp_path / "version.txt"
    assert version_file.read_text(encoding="utf-8") == f"[version]\nvalue={_pyproject_version()}\n"


def test_windows_nuitka_command_uses_standalone_dir_and_pyproject_version() -> None:
    numeric_version = build_nuitka._nuitka_version(_pyproject_version())
    command = build_nuitka.build_nuitka_command(
        output_dir=Path("dist"),
        build_tag="nightly-20260526",
        assume_platform="Windows",
    )

    assert command[:3] == [build_nuitka.sys.executable, "-m", "nuitka"]
    assert "--mode=standalone" in command
    assert "--jobs=1" in command
    assert "--windows-console-mode=disable" in command
    assert "--include-package-data=desktop_notifier" not in command
    assert "--nofollow-import-to=chardet" in command
    assert "--nofollow-import-to=chardet.*" in command
    assert "--output-filename=PortkeyDrop" in command
    assert "--report=dist/compilation-report.xml" in command
    assert f"--product-version={numeric_version}" in command
    assert f"--file-version={numeric_version}" in command
    assert "--include-package-data=prism:_native/*" in command
    assert (
        "--include-data-dir=src/portkeydrop/default_soundpacks=portkeydrop/default_soundpacks"
        in command
    )
    assert "installer/nuitka_entry.py" in command
    assert "src/portkeydrop/main.py" not in command
    assert "--mode=onefile" not in command


def test_macos_nuitka_command_uses_app_mode() -> None:
    command = build_nuitka.build_nuitka_command(
        output_dir=Path("dist"),
        build_tag=None,
        assume_platform="Darwin",
    )

    assert "--mode=app" in command
    assert "--macos-app-name=PortkeyDrop" in command


def test_linux_nuitka_command_excludes_host_glib_and_openssl_stack() -> None:
    command = build_nuitka.build_nuitka_command(
        output_dir=Path("dist"),
        build_tag=None,
        assume_platform="Linux",
    )

    assert "--mode=standalone" in command
    for pattern in build_nuitka.LINUX_SYSTEM_DLL_EXCLUDES:
        assert f"--noinclude-dlls={pattern}" in command


def test_nuitka_is_available_as_build_extra() -> None:
    pyproject = (build_nuitka.ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert '"nuitka' in pyproject


def test_production_build_workflow_uses_nuitka() -> None:
    workflow = (build_nuitka.ROOT / ".github" / "workflows" / "build.yml").read_text(
        encoding="utf-8"
    )

    assert "NUITKA_CACHE_DIR:" in workflow
    assert "actions/cache/restore@v5" in workflow
    assert "actions/cache/save@v5" in workflow
    assert "choco install innosetup" in workflow
    assert "python installer/build_nuitka.py" in workflow
    assert "python -m PyInstaller" not in workflow
    assert "pyinstaller" not in workflow.lower()
    assert "scripts/generate_build_meta.py" in workflow
    assert "dist/PortkeyDrop_Setup_*.exe" in workflow
    assert "dist/PortkeyDrop_Portable_*.zip" in workflow
    assert "dist/PortkeyDrop_macOS_*.zip" in workflow


def test_stage_nuitka_distribution_copies_output_to_dist_shape(tmp_path, monkeypatch) -> None:
    build_dir = tmp_path / "build" / "nuitka"
    nuitka_dist = build_dir / "__main__.dist"
    nuitka_dist.mkdir(parents=True)
    (nuitka_dist / "PortkeyDrop.exe").write_bytes(b"fake-exe")
    (nuitka_dist / "wx").mkdir()

    dist_dir = tmp_path / "dist"
    monkeypatch.setattr(build_nuitka, "BUILD_DIR", build_dir)
    monkeypatch.setattr(build_nuitka, "DIST_DIR", dist_dir)
    monkeypatch.setattr(build_nuitka.platform, "system", lambda: "Windows")

    staged = build_nuitka.stage_nuitka_distribution()

    assert staged == dist_dir / "PortkeyDrop_dir"
    assert (staged / "PortkeyDrop.exe").read_bytes() == b"fake-exe"
    assert (staged / "wx").is_dir()


def test_stage_nuitka_distribution_copies_macos_app_to_dist_shape(tmp_path, monkeypatch) -> None:
    build_dir = tmp_path / "build" / "nuitka"
    nuitka_app = build_dir / "__main__.app"
    executable = nuitka_app / "Contents" / "MacOS" / "PortkeyDrop"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"fake-app")

    dist_dir = tmp_path / "dist"
    monkeypatch.setattr(build_nuitka, "BUILD_DIR", build_dir)
    monkeypatch.setattr(build_nuitka, "DIST_DIR", dist_dir)

    staged = build_nuitka.stage_nuitka_distribution()

    assert staged == dist_dir / "PortkeyDrop.app"
    assert (staged / "Contents" / "MacOS" / "PortkeyDrop").read_bytes() == b"fake-app"


def test_stage_nuitka_distribution_copies_linux_output_to_archive_source_shape(
    tmp_path, monkeypatch
) -> None:
    build_dir = tmp_path / "build" / "nuitka"
    nuitka_dist = build_dir / "__main__.dist"
    nuitka_dist.mkdir(parents=True)
    (nuitka_dist / "PortkeyDrop").write_bytes(b"fake-linux-exe")

    dist_dir = tmp_path / "dist"
    monkeypatch.setattr(build_nuitka, "BUILD_DIR", build_dir)
    monkeypatch.setattr(build_nuitka, "DIST_DIR", dist_dir)
    monkeypatch.setattr(build_nuitka.platform, "system", lambda: "Linux")

    staged = build_nuitka.stage_nuitka_distribution()

    assert staged == dist_dir / "PortkeyDrop"
    assert (staged / "PortkeyDrop").read_bytes() == b"fake-linux-exe"


def test_stage_nuitka_distribution_fails_when_output_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(build_nuitka, "BUILD_DIR", tmp_path / "build" / "nuitka")

    with pytest.raises(FileNotFoundError, match="Nuitka standalone/app output"):
        build_nuitka.stage_nuitka_distribution()


def test_create_windows_installer_delegates_to_shared_installer_builder(
    tmp_path, monkeypatch
) -> None:
    called = False
    original_dist_dir = build.DIST_DIR

    def fake_create_windows_installer() -> bool:
        nonlocal called
        called = True
        assert tmp_path == build.DIST_DIR
        return True

    monkeypatch.setattr(build_nuitka, "DIST_DIR", tmp_path)
    monkeypatch.setattr(build, "create_windows_installer", fake_create_windows_installer)

    assert build_nuitka.create_windows_installer() is True
    assert called is True
    assert original_dist_dir == build.DIST_DIR


def test_nuitka_windows_main_builds_installer_before_portable_zip(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(build_nuitka, "write_inno_version_file", lambda: Path("version.txt"))
    monkeypatch.setattr(build_nuitka, "ensure_nuitka_available", lambda: None)
    monkeypatch.setattr(build_nuitka, "build_nuitka_command", lambda **_: ["nuitka"])
    monkeypatch.setattr(build_nuitka, "run_command", lambda _command: calls.append("compile"))
    monkeypatch.setattr(build_nuitka, "stage_nuitka_distribution", lambda: calls.append("stage"))
    monkeypatch.setattr(build_nuitka.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        build_nuitka,
        "create_windows_installer",
        lambda: calls.append("installer") or True,
    )
    monkeypatch.setattr(
        build_nuitka,
        "create_portable_zip",
        lambda: calls.append("portable") or True,
    )
    monkeypatch.setattr(build_nuitka.sys, "argv", ["build_nuitka.py"])

    assert build_nuitka.main() == 0
    assert calls == ["compile", "stage", "installer", "portable"]


def test_windows_portable_zip_uses_separate_staging_dir(tmp_path, monkeypatch) -> None:
    dist_dir = tmp_path / "dist"
    installer_stage = dist_dir / "PortkeyDrop_dir"
    installer_stage.mkdir(parents=True)
    (installer_stage / "PortkeyDrop.exe").write_bytes(b"fake-exe")

    monkeypatch.setattr(build, "DIST_DIR", dist_dir)
    monkeypatch.setattr(build, "IS_WINDOWS", True)
    monkeypatch.setattr(build, "IS_MACOS", False)
    monkeypatch.setattr(build, "IS_LINUX", False)

    assert build.create_portable_zip() is True

    zip_path = dist_dir / f"PortkeyDrop_Portable_v{build.get_version()}.zip"
    assert not (installer_stage / "data").exists()

    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())

    assert "PortkeyDrop_portable/PortkeyDrop.exe" in names
    assert "PortkeyDrop_portable/data/" in names
