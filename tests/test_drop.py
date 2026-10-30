"""Тести обробки перетягнутих шляхів (без відкриття вікна)."""

from __future__ import annotations

import unittest
from pathlib import Path

from app import ui


class ParseDroppedPathsTests(unittest.TestCase):
    def test_braced_paths_with_spaces(self) -> None:
        data = "{C:/Мої файли/фото 1.png} C:/temp/фото2.jpg"
        self.assertEqual(
            ui.parse_dropped_paths(data),
            [Path("C:/Мої файли/фото 1.png"), Path("C:/temp/фото2.jpg")],
        )

    def test_single_plain_path(self) -> None:
        self.assertEqual(ui.parse_dropped_paths("C:/temp/a.zip"), [Path("C:/temp/a.zip")])

    def test_extra_braces_are_removed(self) -> None:
        self.assertEqual(
            ui.parse_dropped_paths("{C:/temp/one.json}"), [Path("C:/temp/one.json")]
        )

    def test_tuple_from_tkdnd(self) -> None:
        data = ("C:/temp/a.csv", "C:/temp/b.csv")
        self.assertEqual(
            ui.parse_dropped_paths(data), [Path("C:/temp/a.csv"), Path("C:/temp/b.csv")]
        )

    def test_duplicates_are_dropped_case_insensitively(self) -> None:
        data = ("C:/Temp/A.PNG", "C:/Temp/A.PNG", "c:/temp/a.png")
        self.assertEqual(len(ui.parse_dropped_paths(data)), 1)

    def test_empty_values(self) -> None:
        for value in (None, "", "   ", (), []):
            with self.subTest(value=value):
                self.assertEqual(ui.parse_dropped_paths(value), [])

    def test_unsupported_files_are_kept(self) -> None:
        # Відбір не робимо: непідтримувані файли показуються у списку підсвіченими.
        paths = ui.parse_dropped_paths("{C:/temp/readme.xyz} C:/temp/photo.png")
        self.assertEqual(len(paths), 2)


class DropZoneHelperTests(unittest.TestCase):
    def test_make_drop_zone_is_noop_without_tkdnd(self) -> None:
        class FakeApp:
            _dnd_ready = False

        class FakeWidget:
            def drop_target_register(self, *_args):
                raise AssertionError("не має викликатись без tkdnd")

        # Не повинно кидати виняток і не повинно торкатись віджетів.
        ui.App._make_drop_zone(FakeApp(), (FakeWidget(),), lambda _event: None)

    def test_add_dropped_files_keeps_order_and_counts(self) -> None:
        class FakeApp:
            _append_path = ui.App._append_path

            def __init__(self) -> None:
                self.items: list[Path] = [Path("C:/temp/first.png")]
                self.status = ""
                self.refreshed = 0
                self.reset = 0

            def _set_status(self, message: str) -> None:
                self.status = message

        app = FakeApp()
        ui.App._add_dropped_files(
            app,
            app.items,
            [Path("C:/temp/second.png"), Path("C:/temp/first.png")],
            lambda: setattr(app, "refreshed", app.refreshed + 1),
            lambda: setattr(app, "reset", app.reset + 1),
            "Додано файлів",
        )
        self.assertEqual([path.name for path in app.items], ["first.png", "second.png"])
        self.assertIn("Додано файлів: 1", app.status)
        self.assertEqual(app.refreshed, 1)
        self.assertEqual(app.reset, 1)


if __name__ == "__main__":
    unittest.main()
