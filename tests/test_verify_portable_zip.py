from __future__ import annotations

import zipfile

from scripts.verify_portable_zip import verify_portable_zip


def test_verify_portable_zip_accepts_accessiweather_style_portable_layout(tmp_path) -> None:
    zip_path = tmp_path / "PortkeyDrop_Portable_v0.3.0.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("PortkeyDrop/PortkeyDrop.exe", b"fake")
        archive.writestr("PortkeyDrop/.portable", "1\n")
        archive.writestr("PortkeyDrop/data/", b"")

    ok, errors = verify_portable_zip(zip_path)

    assert ok is True
    assert errors == []


def test_verify_portable_zip_rejects_legacy_portable_root_without_marker(tmp_path) -> None:
    zip_path = tmp_path / "PortkeyDrop_Portable_v0.3.0.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("PortkeyDrop_portable/PortkeyDrop.exe", b"fake")
        archive.writestr("PortkeyDrop_portable/data/", b"")

    ok, errors = verify_portable_zip(zip_path)

    assert ok is False
    assert "missing PortkeyDrop/.portable marker" in errors
