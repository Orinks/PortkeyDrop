from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

CHANGELOG_PATH = Path("CHANGELOG.md")
USER_FACING_PATH_PREFIXES = (
    "crates/",
    "installer/",
)
USER_FACING_PATHS = {
    # A deliberate dependency or toolchain change can alter behaviour. The
    # lock file is left out: routine `cargo update` churn would demand a
    # changelog entry for every refresh.
    "Cargo.toml",
    "rust-toolchain.toml",
}
USER_FACING_SUFFIXES = ()
# Tests live inside the crates they cover, and a test-only change has nothing
# to tell a user.
NON_USER_FACING_PATH_FRAGMENTS = ("/tests/", "/benches/")
SECTION_ORDER = ("Added", "Changed", "Fixed", "Improved", "Removed", "Deprecated", "Security")
# Written into a commit message to opt a change out of the CHANGELOG gate --
# for work that touches user-facing files without changing anything a user
# would notice, such as a refactor or a rename.
SKIP_CHANGELOG_MARKERS = ("changelog: none", "[skip changelog]")
# Written into a commit message to force a nightly that the changelog would
# not otherwise justify -- a dependency bump, a security fix in a library, a
# build users need for a reason that has no user-facing bullet.
NIGHTLY_BUILD_MARKERS = ("nightly: build", "[nightly build]")


@dataclass(frozen=True)
class ChangelogSection:
    title: str
    entries: tuple[str, ...]


def run_git(args: list[str]) -> str:
    return subprocess.check_output(["git", *args], text=True, encoding="utf-8").strip()


def is_user_facing_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if any(fragment in normalized for fragment in NON_USER_FACING_PATH_FRAGMENTS):
        return False
    return (
        normalized in USER_FACING_PATHS
        or (bool(USER_FACING_SUFFIXES) and normalized.endswith(USER_FACING_SUFFIXES))
        or normalized.startswith(USER_FACING_PATH_PREFIXES)
    )


def changed_files(base: str, head: str) -> list[str]:
    output = run_git(["diff", "--name-only", f"{base}..{head}"])
    return [line for line in output.splitlines() if line]


def ref_is_ancestor(ancestor: str, descendant: str) -> bool:
    try:
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return False
    return True


def commit_messages(base: str, head: str) -> list[str]:
    output = run_git(["log", "--no-merges", "--format=%B%x00", f"{base}..{head}"])
    return [message.strip() for message in output.split("\0") if message.strip()]


def has_marker(message: str, markers: tuple[str, ...]) -> bool:
    """Whether a commit message carries one of `markers` as a trailer.

    The marker has to be a line of its own. Matching it anywhere in the
    message means a commit that merely writes about the marker -- release
    tooling changes, a PR description quoting the docs -- silently triggers
    it, which is how the gate ends up firing on prose.
    """
    return any(line.strip().casefold() in markers for line in message.splitlines())


def messages_skip_changelog(messages: list[str]) -> bool:
    """Whether every commit in the range opted out of the changelog gate.

    Every one, not any: a single marker must not exempt a range that also
    carries real user-facing work, which is the failure mode that lets a
    change ship with no note attached to it.
    """
    if not messages:
        return False
    return all(has_marker(message, SKIP_CHANGELOG_MARKERS) for message in messages)


def commits_skip_changelog(base: str, head: str) -> bool:
    return messages_skip_changelog(commit_messages(base, head))


def messages_request_nightly_build(messages: list[str]) -> bool:
    """Whether any commit asked for a nightly outright.

    The changelog decides most nightlies, but some builds matter for reasons
    that never become a user-facing bullet. Rather than shipping those with
    "no user-facing changes" as their notes, the commit says so explicitly.
    """
    return any(has_marker(message, NIGHTLY_BUILD_MARKERS) for message in messages)


def commits_request_nightly_build(base: str, head: str) -> bool:
    return messages_request_nightly_build(commit_messages(base, head))


def excluded_entries_from_notes(path: str) -> set[str]:
    if not path:
        return set()
    notes_path = Path(path)
    if not notes_path.exists():
        return set()
    return {
        normalize_entry(entry)
        for section in parse_sections(notes_path.read_text(encoding="utf-8"))
        for entry in section.entries
    }


def extract_release_block(text: str, heading_pattern: str) -> str:
    match = re.search(heading_pattern, text, re.IGNORECASE | re.MULTILINE)
    if not match:
        return ""
    start = match.end()
    next_heading = re.search(r"^## ", text[start:], re.MULTILINE)
    end = start + next_heading.start() if next_heading else len(text)
    return text[start:end].strip()


def parse_sections(markdown: str) -> list[ChangelogSection]:
    sections: list[ChangelogSection] = []
    current_title = ""
    current_entries: list[str] = []
    current_entry: list[str] = []

    def flush_entry() -> None:
        nonlocal current_entry
        if current_entry:
            current_entries.append("\n".join(current_entry).rstrip())
            current_entry = []

    def flush_section() -> None:
        nonlocal current_entries
        flush_entry()
        if current_title and current_entries:
            sections.append(ChangelogSection(current_title, tuple(current_entries)))
        current_entries = []

    for line in markdown.splitlines():
        heading = re.match(r"^#{2,3}\s+(.+?)\s*$", line)
        if heading:
            flush_section()
            current_title = heading.group(1)
            continue

        if re.match(r"^-\s+", line):
            flush_entry()
            current_entry.append(line)
            continue

        if current_entry and (line.startswith("  ") or not line.strip()):
            current_entry.append(line)

    flush_section()
    return sections


def format_sections(sections: list[ChangelogSection]) -> str:
    if not sections:
        return "- No user-facing changes"

    by_title = {section.title: section.entries for section in sections}
    ordered_titles = [title for title in SECTION_ORDER if title in by_title]
    ordered_titles.extend(
        section.title for section in sections if section.title not in ordered_titles
    )

    chunks: list[str] = []
    for title in ordered_titles:
        entries = by_title[title]
        chunks.append(f"## {title}\n" + "\n".join(dict.fromkeys(entries)))
    return "\n\n".join(chunks).strip()


def normalize_entry(entry: str) -> str:
    entry = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", entry)
    entry = re.sub(r"`([^`]+)`", r"\1", entry)
    entry = re.sub(r"\*\*([^*]+)\*\*", r"\1", entry)
    entry = re.sub(r"__([^_]+)__", r"\1", entry)
    entry = re.sub(r"\*([^*]+)\*", r"\1", entry)
    entry = re.sub(r"_([^_]+)_", r"\1", entry)
    entry = re.sub(r"^[-*+]\s+", "", entry.strip())
    entry = re.sub(r"\s+--\s+", " - ", entry)
    entry = re.sub(r"\s+[-\u2013\u2014]\s+", " - ", entry)
    entry = re.sub(r"\s+", " ", entry)
    return entry.casefold().strip()


def changelog_at(ref: str) -> str:
    try:
        return run_git(["show", f"{ref}:{CHANGELOG_PATH.as_posix()}"])
    except subprocess.CalledProcessError:
        return ""


def unreleased_added_entries(base: str, head: str) -> list[str]:
    base_entries = {
        entry
        for section in parse_sections(
            extract_release_block(changelog_at(base), r"^## \[?Unreleased\]?.*$")
        )
        for entry in section.entries
    }
    head_text = run_git(["show", f"{head}:{CHANGELOG_PATH.as_posix()}"])
    return [
        entry
        for section in parse_sections(extract_release_block(head_text, r"^## \[?Unreleased\]?.*$"))
        for entry in section.entries
        if entry not in base_entries
    ]


def sections_added_since(
    base_ref: str,
    head_text: str,
    extra_excluded_entries: set[str] | None = None,
) -> list[ChangelogSection]:
    base_entries = {
        normalize_entry(entry)
        for section in parse_sections(
            extract_release_block(changelog_at(base_ref), r"^## \[?Unreleased\]?.*$")
        )
        for entry in section.entries
    }
    if extra_excluded_entries:
        base_entries.update(extra_excluded_entries)

    added_sections: list[ChangelogSection] = []
    for section in parse_sections(extract_release_block(head_text, r"^## \[?Unreleased\]?.*$")):
        entries = tuple(
            entry for entry in section.entries if normalize_entry(entry) not in base_entries
        )
        if entries:
            added_sections.append(ChangelogSection(section.title, entries))

    return added_sections


def check_command(args: argparse.Namespace) -> int:
    files = changed_files(args.base, args.head)
    user_facing = [path for path in files if is_user_facing_path(path)]
    if not user_facing:
        print("No user-facing paths changed.")
        return 0

    if commits_skip_changelog(args.base, args.head):
        print("Every commit opted out of the changelog gate.")
        return 0

    if CHANGELOG_PATH.as_posix() not in files:
        print("User-facing paths changed without updating CHANGELOG.md:", file=sys.stderr)
        for path in user_facing:
            print(f"- {path}", file=sys.stderr)
        return 1

    entries = unreleased_added_entries(args.base, args.head)
    if not entries:
        print(
            "CHANGELOG.md changed, but no new bullet was added under ## [Unreleased].",
            file=sys.stderr,
        )
        return 1

    print("Found CHANGELOG.md Unreleased entries for user-facing changes.")
    return 0


def notes_command(args: argparse.Namespace) -> int:
    changelog_text = CHANGELOG_PATH.read_text(encoding="utf-8")
    if args.kind == "nightly":
        excluded_entries = excluded_entries_from_notes(args.exclude_notes)
        excluded_entries.update(excluded_entries_from_notes(args.exclude_stable_notes))
        if not args.previous_tag:
            notes = format_sections(
                parse_sections(extract_release_block(changelog_text, r"^## \[?Unreleased\]?.*$"))
            )
        else:
            notes = format_sections(
                sections_added_since(args.previous_tag, changelog_text, excluded_entries)
            )
    else:
        version = args.version.removeprefix("v")
        block = extract_release_block(
            changelog_text,
            rf"^## \[{re.escape(version)}\](?:\s+-\s+\d{{4}}-\d{{2}}-\d{{2}})?\s*$",
        )
        if not block:
            block = extract_release_block(changelog_text, r"^## \[?Unreleased\]?.*$")
        notes = format_sections(parse_sections(block))

    Path(args.output).write_text(notes + "\n", encoding="utf-8")
    print(f"Wrote release notes to {args.output}.")
    return 0


def should_build_nightly_command(args: argparse.Namespace) -> int:
    """Decide whether tonight's commits are worth a nightly.

    Gating on which files changed builds a nightly whenever any source file
    moved and then has nothing to say about it, which is how a release goes
    out reading "No user-facing changes". Gating on whether there is anything
    new to tell the user means a nightly always comes with its reason.
    """
    if not args.previous_tag:
        print("should_build=true")
        print("No previous nightly tag found; building once.", file=sys.stderr)
        return 0

    latest_stable_tag = getattr(args, "latest_stable_tag", "")
    if latest_stable_tag and ref_is_ancestor(args.head, latest_stable_tag):
        print("should_build=false")
        print("The latest stable release already contains this commit.", file=sys.stderr)
        return 0

    baseline_tag = args.previous_tag
    if latest_stable_tag and ref_is_ancestor(args.previous_tag, latest_stable_tag):
        baseline_tag = latest_stable_tag

    if commits_request_nightly_build(baseline_tag, args.head):
        print("should_build=true")
        print("A commit asked for a nightly build.", file=sys.stderr)
        return 0

    changelog_text = CHANGELOG_PATH.read_text(encoding="utf-8")
    excluded_entries = excluded_entries_from_notes(args.exclude_notes)
    excluded_entries.update(excluded_entries_from_notes(args.exclude_stable_notes))
    sections = sections_added_since(baseline_tag, changelog_text, excluded_entries)

    if sections:
        print("should_build=true")
        print("New changelog entries found for a nightly build.", file=sys.stderr)
    else:
        print("should_build=false")
        print("Nothing new to tell the user, and no nightly marker.", file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate and extract curated changelog entries.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="Require Unreleased changelog entries.")
    check.add_argument("--base", required=True)
    check.add_argument("--head", default="HEAD")
    check.set_defaults(func=check_command)

    should_build = subparsers.add_parser(
        "should-build-nightly", help="Decide whether a nightly build is warranted."
    )
    should_build.add_argument("--previous-tag", default="")
    should_build.add_argument("--head", default="HEAD")
    should_build.add_argument("--exclude-notes", default="")
    should_build.add_argument("--latest-stable-tag", default="")
    should_build.add_argument("--exclude-stable-notes", default="")
    should_build.set_defaults(func=should_build_nightly_command)

    notes = subparsers.add_parser("notes", help="Generate release notes from CHANGELOG.md.")
    notes.add_argument("--kind", choices=("nightly", "stable"), required=True)
    notes.add_argument("--version", default="")
    notes.add_argument("--previous-tag", default="")
    notes.add_argument("--exclude-notes", default="")
    notes.add_argument("--exclude-stable-notes", default="")
    notes.add_argument("--output", default="notes.md")
    notes.set_defaults(func=notes_command)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
