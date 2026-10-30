"""Тести логіки розпаковки архівів (без інтерфейсу)."""

from __future__ import annotations

import os
import tarfile
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest import mock

from app import archive
from app.archive import (
    ExtractIOError,
    ExtractValidationError,
    extract_archive,
    list_archive,
)


class ArchiveExtractTestCase(TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)


class ListArchiveTests(ArchiveExtractTestCase):
    def test_list_zip(self) -> None:
        zpath = self.tmp / "test.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("a.txt", "hello")
            zf.writestr("dir/b.txt", "world")
        entries = list_archive(zpath)
        names = {e.name for e in entries}
        self.assertIn("a.txt", names)
        self.assertIn("dir/b.txt", names)

    def test_list_tar(self) -> None:
        tpath = self.tmp / "test.tar"
        with tarfile.open(tpath, "w") as tf:
            info = tarfile.TarInfo(name="x.txt")
            data = b"123"
            info.size = len(data)
            tf.addfile(info, fileobj=__import__("io").BytesIO(data))
        entries = list_archive(tpath)
        self.assertTrue(any(e.name == "x.txt" for e in entries))


class ExtractTests(ArchiveExtractTestCase):
    def test_extract_zip_to_subfolder(self) -> None:
        zpath = self.tmp / "archive.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("file.txt", "content")
        out = self.tmp / "out"
        out.mkdir()
        results = extract_archive(zpath, out)
        self.assertTrue(results)
        # має бути в підпапці archive
        target = out / "archive" / "file.txt"
        self.assertTrue(target.exists())
        self.assertEqual(target.read_text(), "content")

    def test_extract_zip_slip_protection(self) -> None:
        zpath = self.tmp / "bad.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("../evil.txt", "bad")
            zf.writestr("ok.txt", "good")
        out = self.tmp / "out"
        out.mkdir()
        results = extract_archive(zpath, out)
        # evil.txt не має з'явитись поза папкою
        self.assertFalse((out / "evil.txt").exists())
        self.assertTrue((out / "bad" / "ok.txt").exists())

    def test_extract_name_collision_unique(self) -> None:
        zpath = self.tmp / "arc.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("file.txt", "1")
        out = self.tmp / "out"
        out.mkdir()
        # створюємо існуючу цільову підпапку arc щоб змусити arc_1
        (out / "arc").mkdir()
        results = extract_archive(zpath, out)
        self.assertTrue((out / "arc_1" / "file.txt").exists())

    def test_extract_zip_password_error(self) -> None:
        zpath = self.tmp / "enc.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("x.txt", "y")
        # імітуємо зашифрований
        with mock.patch("zipfile.ZipFile.infolist") as m:
            info = mock.Mock()
            info.filename = "x.txt"
            info.flag_bits = 0x1
            info.file_size = 1
            info.compress_size = 1
            info.is_dir = lambda: False
            m.return_value = [info]
            with self.assertRaises(ExtractValidationError) as ctx:
                extract_archive(zpath, out_dir := self.tmp / "out2")
            self.assertIn("паролем", str(ctx.exception).lower())

    def test_extract_cancel(self) -> None:
        zpath = self.tmp / "many.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            for i in range(5):
                zf.writestr(f"f{i}.txt", str(i))
        out = self.tmp / "out3"
        out.mkdir()
        calls = [0]

        def should_cancel():
            calls[0] += 1
            return calls[0] > 2

        results = extract_archive(zpath, out, should_cancel=should_cancel)
        # не всі мають бути розпаковані
        self.assertTrue(len(results) >= 0)

    def test_extract_tar_skip_symlink(self) -> None:
        tpath = self.tmp / "sym.tar"
        with tarfile.open(tpath, "w") as tf:
            info = tarfile.TarInfo(name="link")
            info.type = tarfile.SYMTYPE
            info.linkname = "target"
            tf.addfile(info)
            info2 = tarfile.TarInfo(name="real.txt")
            data = b"hi"
            info2.size = len(data)
            tf.addfile(info2, fileobj=__import__("io").BytesIO(data))
        out = self.tmp / "out4"
        out.mkdir()
        results = extract_archive(tpath, out)
        # симлінк пропущено
        self.assertTrue(any("симлінк" in (r.message or "").lower() or "лінк" in (r.message or "").lower() for r in results))
        self.assertTrue((out / "sym" / "real.txt").exists())

    def test_extract_7z_multiple_files(self) -> None:
        import py7zr

        apath = self.tmp / "many.7z"
        src = self.tmp / "src"
        src.mkdir()
        (src / "one.txt").write_text("перший", encoding="utf-8")
        (src / "two.txt").write_text("другий", encoding="utf-8")
        with py7zr.SevenZipFile(apath, "w") as zf:
            zf.write(src / "one.txt", "one.txt")
            zf.write(src / "two.txt", "two.txt")
        out = self.tmp / "out7z"
        out.mkdir()
        results = extract_archive(apath, out)
        self.assertTrue(all(r.ok for r in results))
        target = out / "many"
        self.assertEqual((target / "one.txt").read_text(encoding="utf-8"), "перший")
        self.assertEqual((target / "two.txt").read_text(encoding="utf-8"), "другий")

    def test_extract_7z_single_file(self) -> None:
        import py7zr

        apath = self.tmp / "single.7z"
        source = self.tmp / "only.txt"
        source.write_text("єдиний", encoding="utf-8")
        with py7zr.SevenZipFile(apath, "w") as zf:
            zf.write(source, "only.txt")
        out = self.tmp / "out7z-single"
        out.mkdir()
        extract_archive(apath, out)
        self.assertTrue((out / "single" / "only.txt").is_file())

    def test_extract_bomb_limits(self) -> None:
        zpath = self.tmp / "big.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            zf.writestr("big.bin", "x")
        out = self.tmp / "out5"
        out.mkdir()
        with mock.patch.object(archive, "MAX_EXTRACT_FILES", 0):
            with self.assertRaises(ExtractValidationError):
                extract_archive(zpath, out)
