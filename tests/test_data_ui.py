"""Тести налаштувань вкладки «Дані» (без відкриття вікна)."""

from __future__ import annotations

import unittest

from app import data_converter, ui
from app.data_converter import DataOptions, OutputFormat, TxtLayout


class DataTabChoicesTests(unittest.TestCase):
    def test_target_labels_cover_all_formats(self) -> None:
        self.assertEqual(set(ui.DATA_TARGET_LABELS), set(OutputFormat))
        for label in ui.DATA_TARGET_LABELS.values():
            self.assertTrue(label.strip())

    def test_delimiter_choices_are_valid(self) -> None:
        for label, value in ui.DELIMITER_CHOICES.items():
            with self.subTest(label=label):
                if value is None:
                    continue
                self.assertEqual(len(value), 1)
                self.assertNotIn(value, '"\r\n')

    def test_encoding_choices_match_logic(self) -> None:
        self.assertEqual(
            set(ui.INPUT_ENCODING_CHOICES.values()),
            set(data_converter.INPUT_ENCODINGS),
        )
        self.assertEqual(
            set(ui.OUTPUT_ENCODING_CHOICES.values()),
            set(data_converter.OUTPUT_ENCODINGS),
        )
        self.assertIn(
            data_converter.AUTO_ENCODING, ui.INPUT_ENCODING_CHOICES.values()
        )

    def test_newline_indent_and_layout_choices(self) -> None:
        self.assertEqual(
            set(ui.NEWLINE_CHOICES.values()), set(data_converter.NEWLINES)
        )
        for value in ui.JSON_INDENT_CHOICES.values():
            self.assertTrue(0 <= value <= 8)
        self.assertIn(2, ui.JSON_INDENT_CHOICES.values())
        self.assertEqual(set(ui.TXT_LAYOUT_CHOICES.values()), set(TxtLayout))

    def test_input_and_output_delimiters_stay_separate(self) -> None:
        options = DataOptions(
            target=OutputFormat.CSV,
            delimiter=ui.DELIMITER_CHOICES["Крапка з комою"],
            output_delimiter=ui.DELIMITER_CHOICES["Риска"],
        )
        self.assertEqual(options.delimiter, ";")
        self.assertEqual(options.output_delimiter, "|")

    def test_auto_delimiters_mean_detection_and_default(self) -> None:
        options = DataOptions(
            delimiter=ui.DELIMITER_CHOICES["Авто"],
            output_delimiter=ui.DELIMITER_CHOICES["Авто"],
        )
        self.assertIsNone(options.delimiter)
        self.assertIsNone(options.output_delimiter)


if __name__ == "__main__":
    unittest.main()
