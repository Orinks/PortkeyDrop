"""Tests for portable migration helpers."""

from __future__ import annotations

from pathlib import Path

from portkeydrop.migration import (
    get_migration_candidates,
    has_migration_candidates,
    migrate_files,
)


def test_has_migration_candidates_true_when_standard_has_missing_file(tmp_path: Path) -> None:
    portable_dir = tmp_path / "portable"
    standard_dir = tmp_path / "standard"
    portable_dir.mkdir()
    standard_dir.mkdir()
    (standard_dir / "sites.json").write_text('{"sites": []}')

    assert has_migration_candidates(portable_dir, standard_dir) is True


def test_has_migration_candidates_false_when_no_migratable_files(tmp_path: Path) -> None:
    portable_dir = tmp_path / "portable"
    standard_dir = tmp_path / "standard"
    portable_dir.mkdir()
    standard_dir.mkdir()
    (portable_dir / "sites.json").write_text('{"sites": []}')
    (standard_dir / "sites.json").write_text('{"sites": []}')

    assert has_migration_candidates(portable_dir, standard_dir) is False


def test_get_migration_candidates_lists_existing_files(tmp_path: Path) -> None:
    standard_dir = tmp_path / "standard"
    standard_dir.mkdir()
    (standard_dir / "known_hosts").write_text("example")
    (standard_dir / "settings.json").write_text("{}")

    assert get_migration_candidates(standard_dir) == [
        ("Known SSH hosts", "known_hosts"),
        ("App settings", "settings.json"),
    ]


def test_migrate_files_copies_selected_files(tmp_path: Path) -> None:
    standard_dir = tmp_path / "standard"
    portable_dir = tmp_path / "portable"
    standard_dir.mkdir()
    portable_dir.mkdir()
    (standard_dir / "sites.json").write_text('{"sites": [1]}')
    (standard_dir / "known_hosts").write_text("hostkey")

    migrate_files(["sites.json"], standard_dir, portable_dir)

    assert (portable_dir / "sites.json").read_text() == '{"sites": [1]}'
    assert not (portable_dir / "known_hosts").exists()
