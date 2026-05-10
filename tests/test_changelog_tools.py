from __future__ import annotations

from scripts.changelog_tools import (
    ChangelogSection,
    extract_release_block,
    format_sections,
    is_user_facing_path,
    normalize_entry,
    parse_sections,
)


def test_extract_unreleased_block_stops_at_next_release() -> None:
    changelog = """# Changelog

## Unreleased

### Added
- New useful thing.

## [0.1.0] - 2026-01-01

### Fixed
- Old fix.
"""

    block = extract_release_block(changelog, r"^## \[?Unreleased\]?.*$")

    assert "New useful thing" in block
    assert "Old fix" not in block


def test_parse_sections_keeps_multiline_entries() -> None:
    block = """### Added
- First entry wraps
  onto the next line.
- Second entry.

### Fixed
- Fixed entry.
"""

    sections = parse_sections(block)

    assert sections == [
        ChangelogSection(
            "Added",
            ("- First entry wraps\n  onto the next line.", "- Second entry."),
        ),
        ChangelogSection("Fixed", ("- Fixed entry.",)),
    ]


def test_format_sections_uses_release_note_headings() -> None:
    notes = format_sections(
        [
            ChangelogSection("Fixed", ("- Corrected a failed transfer retry.",)),
            ChangelogSection("Added", ("- Added WebDAV connections.",)),
        ]
    )

    assert (
        notes
        == "## Added\n- Added WebDAV connections.\n\n## Fixed\n- Corrected a failed transfer retry."
    )


def test_user_facing_paths_match_release_build_surface() -> None:
    assert is_user_facing_path("src/portkeydrop/app.py")
    assert is_user_facing_path("installer/build.py")
    assert is_user_facing_path("scripts/generate_build_meta.py")
    assert is_user_facing_path("installer/portkeydrop.spec")
    assert not is_user_facing_path(".github/workflows/ci.yml")
    assert not is_user_facing_path("tests/test_app.py")


def test_normalize_entry_matches_curated_release_body_wording() -> None:
    changelog_entry = (
        "- **Connection imports** -- PortkeyDrop now previews imported FileZilla sites."
    )
    release_body_entry = (
        "- **Connection imports** - PortkeyDrop now previews imported FileZilla sites."
    )

    assert normalize_entry(changelog_entry) == normalize_entry(release_body_entry)
