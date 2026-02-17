"""Tests for local paste (file copy) logic."""

from __future__ import annotations

import shutil
from pathlib import Path


class TestPasteLocalFiles:
    """Test the file copy logic used by Ctrl+V in local pane."""

    def test_paste_single_file(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        src_file = src_dir / "hello.txt"
        src_file.write_text("hello world")

        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        dest = dest_dir / src_file.name
        shutil.copy2(str(src_file), str(dest))

        assert dest.exists()
        assert dest.read_text() == "hello world"

    def test_paste_folder(self, tmp_path):
        src_dir = tmp_path / "src" / "myfolder"
        src_dir.mkdir(parents=True)
        (src_dir / "a.txt").write_text("a")
        (src_dir / "b.txt").write_text("b")

        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        dest = dest_dir / src_dir.name
        shutil.copytree(str(src_dir), str(dest))

        assert dest.is_dir()
        assert (dest / "a.txt").read_text() == "a"
        assert (dest / "b.txt").read_text() == "b"

    def test_paste_multiple_files(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        files = []
        for name in ["one.txt", "two.txt", "three.txt"]:
            f = src_dir / name
            f.write_text(f"content of {name}")
            files.append(f)

        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        count = 0
        for f in files:
            dest = dest_dir / f.name
            shutil.copy2(str(f), str(dest))
            count += 1

        assert count == 3
        assert (dest_dir / "one.txt").read_text() == "content of one.txt"
        assert (dest_dir / "three.txt").read_text() == "content of three.txt"

    def test_paste_skips_nonexistent(self, tmp_path):
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        fake_path = tmp_path / "nonexistent.txt"
        assert not fake_path.exists()

        # Simulating the logic: skip if not exists
        count = 0
        for src_path in [str(fake_path)]:
            p = Path(src_path)
            if not p.exists():
                continue
            shutil.copy2(str(p), str(dest_dir / p.name))
            count += 1

        assert count == 0

    def test_paste_file_and_folder_mixed(self, tmp_path):
        src_dir = tmp_path / "src"
        src_dir.mkdir()

        file1 = src_dir / "doc.txt"
        file1.write_text("document")

        folder1 = src_dir / "subdir"
        folder1.mkdir()
        (folder1 / "inner.txt").write_text("inner")

        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        sources = [file1, folder1]
        count = 0
        for p in sources:
            dest = dest_dir / p.name
            if p.is_dir():
                shutil.copytree(str(p), str(dest))
            else:
                shutil.copy2(str(p), str(dest))
            count += 1

        assert count == 2
        assert (dest_dir / "doc.txt").read_text() == "document"
        assert (dest_dir / "subdir" / "inner.txt").read_text() == "inner"
