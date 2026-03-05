#!/usr/bin/env python3
"""Validate Windows packaging artifacts for runtime deps and portable mode."""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path


RUNTIME_MODULE_TOKENS = ("prism", "prismatoid")


def _normalize(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def _contains_runtime_tokens(entries: list[str]) -> list[str]:
    matches: list[str] = []
    for name in entries:
        low = name.lower()
        if any(token in low for token in RUNTIME_MODULE_TOKENS):
            matches.append(name)
    return matches


def verify_runtime_dir(runtime_dir: Path, require_no_data: bool) -> tuple[bool, list[str]]:
    errors: list[str] = []

    if not runtime_dir.exists():
        return False, [f"missing runtime dir: {runtime_dir}"]

    if require_no_data and (runtime_dir / "data").exists():
        errors.append("runtime dir must not contain data/ (portable-only)")

    if errors:
        return False, errors

    print(f"Validated runtime dir: {runtime_dir}")
    return True, []


def verify_pyz_contains_runtime_modules(pyz_path: Path) -> tuple[bool, list[str]]:
    if not pyz_path.exists():
        return False, [f"missing pyz archive: {pyz_path}"]

    data = pyz_path.read_bytes().lower()
    found = [token for token in RUNTIME_MODULE_TOKENS if token.encode("utf-8") in data]

    if not found:
        return False, [f"missing prism/prismatoid markers in PYZ archive ({pyz_path})"]

    print(f"Validated runtime modules in PYZ: {pyz_path}")
    print(f"Found runtime token markers: {', '.join(found)}")
    return True, []


def verify_portable_zip(zip_path: Path) -> tuple[bool, list[str]]:
    if not zip_path.exists():
        return False, [f"missing zip: {zip_path}"]

    with zipfile.ZipFile(zip_path) as zf:
        entries = sorted({_normalize(info.filename) for info in zf.infolist()})

    errors: list[str] = []

    if not any(name == "data/" or name.startswith("data/") for name in entries):
        errors.append("missing required data/ directory contents")

    if errors:
        return False, errors

    print(f"Validated portable zip: {zip_path}")
    print("Found data/ directory contents for portable mode")
    return True, []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-dir", type=Path, help="Path to unpacked runtime directory")
    parser.add_argument("--pyz-path", type=Path, help="Path to PyInstaller PYZ archive")
    parser.add_argument("--portable-zip", type=Path, help="Path to portable zip")
    parser.add_argument(
        "--require-runtime-no-data",
        action="store_true",
        help="Fail if runtime dir contains data/ (portable marker must be portable-only)",
    )
    args = parser.parse_args()

    if not args.runtime_dir and not args.pyz_path and not args.portable_zip:
        parser.error("Provide at least one of --runtime-dir, --pyz-path, or --portable-zip")

    all_errors: list[str] = []

    if args.runtime_dir:
        ok, errors = verify_runtime_dir(args.runtime_dir, args.require_runtime_no_data)
        if not ok:
            all_errors.extend(errors)

    if args.pyz_path:
        ok, errors = verify_pyz_contains_runtime_modules(args.pyz_path)
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
