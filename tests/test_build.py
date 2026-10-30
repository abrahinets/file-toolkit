"""Тести скрипта збірки build.py (PyInstaller не запускається)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import build


class BuildCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.command = build.build_command()

    def test_uses_onedir_windowed_build(self) -> None:
        self.assertIn("--onedir", self.command)
        self.assertIn("--windowed", self.command)
        self.assertNotIn("--onefile", self.command)
        self.assertNotIn("--console", self.command)

    def test_entry_point_and_name(self) -> None:
        self.assertEqual(self.command[-1], str(build.ENTRY_POINT))
        self.assertTrue(build.ENTRY_POINT.is_file())
        self.assertEqual(
            self.command[self.command.index("--name") + 1], "FileToolkit"
        )
        self.assertIn(str(build.DIST_DIR), self.command)

    def test_collects_data_and_binaries(self) -> None:
        collected = [
            self.command[index + 1]
            for index, value in enumerate(self.command)
            if value == "--collect-all"
        ]
        for package in ("customtkinter", "py7zr", "imageio_ffmpeg", "tkinterdnd2"):
            with self.subTest(package=package):
                self.assertIn(package, collected)

    def test_runs_pyinstaller_with_current_interpreter(self) -> None:
        self.assertEqual(self.command[0], sys.executable)
        self.assertEqual(self.command[1:3], ["-m", "PyInstaller"])

    def test_spec_is_written_outside_repository_root(self) -> None:
        spec_dir = Path(self.command[self.command.index("--specpath") + 1])
        self.assertEqual(spec_dir, build.BUILD_DIR)
        self.assertNotEqual(spec_dir, build.ROOT)


if __name__ == "__main__":
    unittest.main()
