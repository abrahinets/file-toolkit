"""Прості тести каркасу: модулі імпортуються, вікно не відкривається."""

from __future__ import annotations

import importlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class ImportTests(unittest.TestCase):
    def test_logic_modules_import(self) -> None:
        for name in ("app.converter", "app.data_converter", "app.archive"):
            with self.subTest(module=name):
                self.assertIsNotNone(importlib.import_module(name))

    def test_ui_module_imports_without_opening_window(self) -> None:
        module = importlib.import_module("app.ui")
        self.assertTrue(hasattr(module, "App"))

    def test_entry_point_compiles(self) -> None:
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        compile(source, "main.py", "exec")

    def test_app_package_has_version(self) -> None:
        package = importlib.import_module("app")
        self.assertTrue(package.__version__)


if __name__ == "__main__":
    unittest.main()
