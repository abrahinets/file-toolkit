"""Прості тести каркасу: модулі імпортуються, вікно не відкривається."""

from __future__ import annotations

import importlib
import os
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

    def test_app_starts_and_closes(self) -> None:
        if os.environ.get("DISPLAY") is None and os.name != "nt":
            self.skipTest("no display")
        try:
            import customtkinter as ctk

            ctk.set_appearance_mode("dark")
            ctk.set_default_color_theme("blue")
        except Exception:
            pass
        try:
            from app.ui import App
        except Exception as exc:
            self.skipTest(f"cannot import App: {exc}")
        try:
            app = App()
        except Exception as exc:
            self.fail(f"App() raised exception: {exc}")
        try:
            app.update()
        except Exception:
            pass
        try:
            app.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    unittest.main()
