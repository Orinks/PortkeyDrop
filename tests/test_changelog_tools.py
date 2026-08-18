from __future__ import annotations

from scripts.changelog_tools import (
    excluded_entries_from_notes,
    messages_request_nightly_build,
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


def test_a_commit_can_ask_for_a_nightly_the_changelog_would_not_justify() -> None:
    # Some builds matter for reasons that never become a user-facing bullet:
    # a dependency bump, a fix inside a library. Without this the only way to
    # ship one is a release whose notes say nothing.
    assert messages_request_nightly_build(["fix(deps): bump russh\n\nnightly: build"])
    assert messages_request_nightly_build(["chore: refresh vendored DLL [nightly build]"])
    assert messages_request_nightly_build(["Nightly: Build"])


def test_ordinary_commits_do_not_ask_for_a_nightly() -> None:
    assert not messages_request_nightly_build(
        ["fix(sftp): reconnect after an idle timeout", "docs: describe the nightly channel"]
    )
    assert not messages_request_nightly_build([])


def test_entries_already_announced_are_read_back_out_of_the_notes(tmp_path) -> None:
    # A nightly must not re-announce what the previous nightly, or the stable
    # release it followed, already told the user.
    notes = tmp_path / "previous-notes.md"
    notes.write_text(
        "## Fixed\n- The **Cancel** button on the download dialog now cancels.\n",
        encoding="utf-8",
    )
    excluded = excluded_entries_from_notes(str(notes))
    assert normalize_entry("- The Cancel button on the download dialog now cancels.") in excluded


def test_missing_notes_file_excludes_nothing() -> None:
    assert excluded_entries_from_notes("") == set()
    assert excluded_entries_from_notes("no-such-notes.md") == set()
