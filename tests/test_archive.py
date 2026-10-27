"""Тести логіки архівування (без інтерфейсу)."""

from __future__ import annotations

import os
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest import mock

from app import archive
from app.archive import (
    ArchiveIOError,
    ArchiveValidationError,
    ZipOptions,
    create_zip,
    default_zip_name,
    estimate_size_bytes,
    is_supported_archive_source,
)


class ArchiveTestCase(TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)


class HelperTests(ArchiveTestCase):
    def test_is_supported_archive_source(self) -> None:
        f = self.tmp / "a.txt"
        f.write_text("x")
        self.assertTrue(is_supported_archive_source(f))
        d = self.tmp / "dir"
        d.mkdir()
        self.assertTrue(is_supported_archive_source(d))
        self.assertFalse(is_supported_archive_source(self.tmp / "nope"))

    def test_default_zip_name(self) -> None:
        f = self.tmp / "file.txt"
        f.write_text("x")
        self.assertEqual(default_zip_name([f]), "file.zip")
        d = self.tmp / "mydir"
        d.mkdir()
        self.assertEqual(default_zip_name([d]), "mydir.zip")
        self.assertEqual(default_zip_name([f, d]), "archive.zip")

    def test_estimate_size_bytes(self) -> None:
        f = self.tmp / "a.bin"
        f.write_bytes(b"abc")
        d = self.tmp / "dir"
        d.mkdir()
        (d / "b.bin").write_bytes(b"12345")
        self.assertEqual(estimate_size_bytes([f, d]), 8)


class CreateZipTests(ArchiveTestCase):
    def test_create_zip_single_file(self) -> None:
        f = self.tmp / "hello.txt"
        f.write_text("hello")
        out_dir = self.tmp / "out"
        out_dir.mkdir()
        results = create_zip([f], out_dir, "test")
        self.assertTrue(results)
        zpath = out_dir / "test.zip"
        self.assertTrue(zpath.exists())
        with zipfile.ZipFile(zpath) as zf:
            self.assertIn("hello.txt", zf.namelist())

    def test_create_zip_multiple_files(self) -> None:
        f1 = self.tmp / "a.txt"
        f2 = self.tmp / "b.txt"
        f1.write_text("a")
        f2.write_text("b")
        out_dir = self.tmp / "out"
        out_dir.mkdir()
        results = create_zip([f1, f2], out_dir, "multi")
        zpath = out_dir / "multi.zip"
        self.assertTrue(zpath.exists())
        with zipfile.ZipFile(zpath) as zf:
            names = set(zf.namelist())
            self.assertIn("a.txt", names)
            self.assertIn("b.txt", names)

    def test_create_zip_folder_preserves_structure(self) -> None:
        d = self.tmp / "project"
        d.mkdir()
        (d / "readme.md").write_text("hi")
        sub = d / "src"
        sub.mkdir()
        (sub / "main.py").write_text("print(1)")
        out_dir = self.tmp / "out"
        out_dir.mkdir()
        create_zip([d], out_dir, "proj")
        zpath = out_dir / "proj.zip"
        with zipfile.ZipFile(zpath) as zf:
            names = set(zf.namelist())
            self.assertIn("project/readme.md", names)
            self.assertIn("project/src/main.py", names)

    def test_zip_name_collision_uses_underscore_suffix(self) -> None:
        f = self.tmp / "f.txt"
        f.write_text("x")
        out_dir = self.tmp / "out"
        out_dir.mkdir()
        (out_dir / "archive.zip").write_bytes(b"x")
        create_zip([f], out_dir, "archive")
        self.assertTrue((out_dir / "archive_1.zip").exists())

    def test_same_filename_from_different_folders_no_conflict(self) -> None:
        d1 = self.tmp / "d1"
        d2 = self.tmp / "d2"
        d1.mkdir()
        d2.mkdir()
        (d1 / "file.txt").write_text("1")
        (d2 / "file.txt").write_text("2")
        out_dir = self.tmp / "out"
        out_dir.mkdir()
        create_zip([d1, d2], out_dir, "dup")
        zpath = out_dir / "dup.zip"
        with zipfile.ZipFile(zpath) as zf:
            names = zf.namelist()
            # обидва мають бути присутні, можливо з суфіксом
            self.assertTrue(any(n.endswith("file.txt") and n.startswith("d1/") for n in names))
            self.assertTrue(any(n.endswith("file.txt") and n.startswith("d2/") for n in names))

    def test_archive_not_added_to_itself(self) -> None:
        f = self.tmp / "a.txt"
        f.write_text("a")
        out_dir = self.tmp / "out"
        out_dir.mkdir()
        create_zip([f], out_dir, "result")
        zpath = out_dir / "result.zip"
        self.assertTrue(zpath.exists())
        # тепер спробуємо додати архів разом з файлом у ту ж папку призначення - архів має бути виключений
        create_zip([f, zpath], out_dir, "result2")
        zpath2 = out_dir / "result2.zip"
        self.assertTrue(zpath2.exists())
        with zipfile.ZipFile(zpath2) as zf:
            names = zf.namelist()
            self.assertIn("a.txt", names)
            # архів не має потрапити сам у себе
            self.assertNotIn("result.zip", names)

    def test_empty_folder_added_as_record(self) -> None:
        d = self.tmp / "emptydir"
        d.mkdir()
        out_dir = self.tmp / "out"
        out_dir.mkdir()
        create_zip([d], out_dir, "empty")
        zpath = out_dir / "empty.zip"
        with zipfile.ZipFile(zpath) as zf:
            names = zf.namelist()
            # має бути запис порожньої папки
            self.assertTrue(any(n == "emptydir/" or n.startswith("emptydir_") and n.endswith("/") for n in names))

    def test_stored_when_compression_level_zero(self) -> None:
        f = self.tmp / "big.txt"
        f.write_bytes(b"x" * 1000)
        out_dir = self.tmp / "out"
        out_dir.mkdir()
        create_zip([f], out_dir, "stored", options=ZipOptions(compression_level=0))
        zpath = out_dir / "stored.zip"
        with zipfile.ZipFile(zpath) as zf:
            info = zf.getinfo("big.txt")
            self.assertEqual(info.compress_type, zipfile.ZIP_STORED)

    def test_cancel_deletes_tmp(self) -> None:
        f1 = self.tmp / "1.txt"
        f2 = self.tmp / "2.txt"
        f1.write_text("1")
        f2.write_text("2")
        out_dir = self.tmp / "out"
        out_dir.mkdir()
        calls = [0]

        def should_cancel():
            calls[0] += 1
            return calls[0] > 1

        results = create_zip([f1, f2], out_dir, "cancel", should_cancel=should_cancel)
        # архів не має бути створений
        self.assertFalse((out_dir / "cancel.zip").exists())
        self.assertFalse((out_dir / "cancel.zip.tmp").exists())

    def test_unreadable_file_skipped_but_reported(self) -> None:
        f = self.tmp / "bad.txt"
        f.write_text("x")
        out_dir = self.tmp / "out"
        out_dir.mkdir()
        # симулюємо помилку читання
        original_write = zipfile.ZipFile.write

        def broken_write(self_zf, filename, arcname=None, compress_type=None):
            if str(filename).endswith("bad.txt"):
                raise PermissionError("немає доступу")
            return original_write(self_zf, filename, arcname=arcname, compress_type=compress_type)

        with mock.patch.object(zipfile.ZipFile, "write", broken_write):
            results = create_zip([f], out_dir, "bad")
        # архів все ще створюється? за логікою - ми записуємо окремі файли, помилка запису фіксується в результаті
        # але якщо всі файли провалились - може не створитись; перевіряємо що є результат з помилкою
        self.assertTrue(any(not r.ok and r.source and r.source.name == "bad.txt" for r in results))

    def test_no_space_error(self) -> None:
        f = self.tmp / "a.txt"
        f.write_text("x")
        out_dir = self.tmp / "out"
        out_dir.mkdir()
        with mock.patch("shutil.disk_usage") as m:
            m.return_value = type("u", (), {"free": 10})()
            with self.assertRaises(ArchiveIOError):
                create_zip([f], out_dir, "nospace")

    def test_validation_errors(self) -> None:
        out_dir = self.tmp / "out"
        out_dir.mkdir()
        with self.assertRaises(ArchiveValidationError):
            create_zip([], out_dir, "x")
        with self.assertRaises(ArchiveValidationError):
            create_zip([self.tmp / "nope.txt"], out_dir, "x")
