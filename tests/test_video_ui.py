"""Тести налаштувань вкладки «Відео» (без відкриття вікна)."""

from __future__ import annotations

import unittest

from app import ui, video_converter
from app.video_converter import MaxHeight, OutputFormat, QualityPreset


class VideoTabChoicesTests(unittest.TestCase):
    def test_target_labels_cover_all_formats(self) -> None:
        self.assertEqual(set(ui.VIDEO_TARGET_LABELS), set(OutputFormat))
        labels = list(ui.VIDEO_TARGET_LABELS.values())
        self.assertTrue(all(label.strip() for label in labels))
        self.assertEqual(len(labels), len(set(labels)))

    def test_quality_labels_cover_all_presets(self) -> None:
        self.assertEqual(set(ui.VIDEO_QUALITY_LABELS), set(QualityPreset))
        self.assertEqual(
            set(ui.VIDEO_QUALITY_LABELS.values()),
            set(video_converter.QUALITY_LABELS.values()),
        )
        self.assertEqual(ui.VIDEO_QUALITY_LABELS[QualityPreset.BALANCED], "Баланс")

    def test_height_labels_cover_all_options(self) -> None:
        self.assertEqual(set(ui.VIDEO_HEIGHT_LABELS), set(MaxHeight))
        self.assertEqual(ui.VIDEO_HEIGHT_LABELS[MaxHeight.P720], "720p")
        self.assertEqual(ui.VIDEO_HEIGHT_LABELS[MaxHeight.NONE], "Без змін")

    def test_video_filter_lists_all_supported_extensions(self) -> None:
        patterns = " ".join(pattern for _name, pattern in ui.VIDEO_FILTER)
        for suffix in video_converter.SUPPORTED_INPUT_SUFFIXES:
            with self.subTest(suffix=suffix):
                self.assertIn(f"*{suffix}", patterns)
        self.assertIn(("Усі файли", "*.*"), ui.VIDEO_FILTER)

    def test_settings_depend_on_target_format(self) -> None:
        for target in (OutputFormat.MP4, OutputFormat.WEBM, OutputFormat.MKV):
            with self.subTest(target=target):
                self.assertTrue(ui.video_height_enabled(target))
                self.assertTrue(ui.video_sound_enabled(target))
                self.assertTrue(ui.video_quality_enabled(target))

        self.assertTrue(ui.video_height_enabled(OutputFormat.GIF))
        self.assertFalse(ui.video_sound_enabled(OutputFormat.GIF))
        self.assertTrue(ui.video_quality_enabled(OutputFormat.GIF))

        for target in (OutputFormat.MP3, OutputFormat.WAV):
            with self.subTest(target=target):
                self.assertFalse(ui.video_height_enabled(target))
                self.assertFalse(ui.video_sound_enabled(target))
        self.assertTrue(ui.video_quality_enabled(OutputFormat.MP3))
        self.assertFalse(ui.video_quality_enabled(OutputFormat.WAV))

    def test_video_page_is_between_data_and_archive(self) -> None:
        self.assertEqual(
            list(ui.NAV_LABELS),
            [ui.CONVERTER_TAB, ui.DATA_TAB, ui.VIDEO_TAB, ui.ARCHIVE_TAB],
        )
        self.assertEqual(ui.NAV_LABELS[ui.VIDEO_TAB], "Відео")
        self.assertEqual(ui.PAGE_TITLES[ui.VIDEO_TAB], "Конвертер відео")


if __name__ == "__main__":
    unittest.main()
