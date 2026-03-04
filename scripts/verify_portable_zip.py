#!/usr/bin/env python3
"""Validate Windows packaging artifacts for runtime deps and portable mode."""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path


RUNTIME_PACKAGES = ("prism", "prismatoid")


def _normalize(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _package_matches(entries: list[str]) -> list[str]:
    matches: list[str] = []
    for name in entries:
        if any(name.startswith(f"{pkg}/") for pkg in RUNTIME_PACKAGES):
            matches.append(name)
    return matches


def verify_runtime_dir(runtime_dir: Path, require_no_data: bool) -> tuple[bool, list[str]]:
    errors: list[str] = []

    if not runtime_dir.exists():
        return False, [f"missing runtime dir: {runtime_dir}"]

    for pkg in RUNTIME_PACKAGES:
        pkg_dir = runtime_dir / pkg
        if not pkg_dir.exists() or not pkg_dir.is_dir():
            errors.append(f"missing runtime package directory: {pkg}/")
            continue

        if not any(path.is_file() for path in pkg_dir.rglob("*")):
            errors.append(f"runtime package has no files: {pkg}/")

    if require_no_data and (runtime_dir / "data").exists():
        errors.append("runtime dir must not contain data/ (portable-only)")

    if errors:
        return False, errors

    print(f"Validated runtime dir: {runtime_dir}")
    for pkg in RUNTIME_PACKAGES:
        count = sum(1 for p in (runtime_dir / pkg).rglob("*") if p.is_file())
        print(f"Found {pkg}/ files: {count}")

    return True, []


def verify_portable_zip(zip_path: Path) -> tuple[bool, list[str]]:
    if not zip_path.exists():
        return False, [f"missing zip: {zip_path}"]

    with zipfile.ZipFile(zip_path) as zf:
        entries = sorted({_normalize(info.filename) for info in zf.infolist()})

    errors: list[str] = []

    if not any(name == "data/" or name.startswith("data/") for name in entries):
        errors.append("missing required data/ directory contents")

    runtime_entries = _package_matches(entries)
    if not runtime_entries:
        errors.append("missing prism/prismatoid runtime files in portable zip")

    if errors:
        return False, errors

    print(f"Validated portable zip: {zip_path}")
    print("Found prism/prismatoid entries:")
    for name in runtime_entries[:20]:
        print(f"  {name}")
    if len(runtime_entries) > 20:
        print(f"  ... and {len(runtime_entries) - 20} more")

    return True, []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", type=Path, help="Path to unpacked runtime directory")
    parser.add_argument("--portable-zip", type=Path, help="Path to portable zip")
    parser.add_argument(
        "--require-runtime-no-data",
        action="store_true",
        help="Fail if runtime dir contains data/ (portable marker must be portable-only)",
    )
    args = parser.parse_args()

    if not args.runtime_dir and not args.portable_zip:
        parser.error("Provide at least one of --runtime-dir or --portable-zip")

    all_errors: list[str] = []

    if args.runtime_dir:
        ok, errors = verify_runtime_dir(args.runtime_dir, args.require_runtime_no_data)
        if not ok:
            all_errors.extend(errors)

    if args.portable_zip:
        ok, errors = verify_portable_zip(args.portable_zip)
        if not ok:
            all_errors.extend(errors)

    if all_errors:
        print("Validation failed", file=sys.stderr)
        for err in all_errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
