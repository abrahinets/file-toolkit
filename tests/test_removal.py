"""Тести видалення окремих елементів зі списків файлів."""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from app.ui import remove_item_at, remove_item_path


class RemoveItemAtTests(unittest.TestCase):
    def test_removes_item_by_index(self) -> None:
        items = [Path("a.png"), Path("b.png"), Path("c.png")]
        self.assertEqual(remove_item_at(items, 1), Path("b.png"))
        self.assertEqual(items, [Path("a.png"), Path("c.png")])

    def test_out_of_range_keeps_list(self) -> None:
        items = [Path("a.png")]
        for index in (-1, 1, 99):
            with self.subTest(index=index):
                self.assertIsNone(remove_item_at(items, index))
        self.assertEqual(items, [Path("a.png")])

    def test_empty_list(self) -> None:
        self.assertIsNone(remove_item_at([], 0))

    def test_removing_last_item_leaves_empty_list(self) -> None:
        items = [Path("only.png")]
        self.assertEqual(remove_item_at(items, 0), Path("only.png"))
        self.assertEqual(items, [])


class RemoveItemPathTests(unittest.TestCase):
    def test_removes_matching_path(self) -> None:
        items = [Path("C:/Temp/a.png"), Path("C:/Temp/b.png")]
        self.assertTrue(remove_item_path(items, Path("C:/Temp/a.png")))
        self.assertEqual(items, [Path("C:/Temp/b.png")])

    def test_missing_path_keeps_list(self) -> None:
        items = [Path("C:/Temp/a.png")]
        self.assertFalse(remove_item_path(items, Path("C:/Temp/other.png")))
        self.assertEqual(items, [Path("C:/Temp/a.png")])

    @unittest.skipUnless(os.name == "nt", "регістр шляхів важливий лише на Windows")
    def test_windows_paths_compared_without_case(self) -> None:
        items = [Path("C:/Temp/Photo.PNG")]
        self.assertTrue(remove_item_path(items, Path("c:/temp/photo.png")))
        self.assertEqual(items, [])

    @unittest.skipUnless(os.name == "nt", "регістр шляхів важливий лише на Windows")
    def test_removes_only_first_duplicate(self) -> None:
        items = [Path("C:/Temp/a.png"), Path("c:/temp/A.png")]
        self.assertTrue(remove_item_path(items, Path("C:/Temp/a.png")))
        self.assertEqual(len(items), 1)


if __name__ == "__main__":
    unittest.main()
