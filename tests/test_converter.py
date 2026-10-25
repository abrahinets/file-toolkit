"""Тести логіки конвертації зображень (без інтерфейсу)."""

from __future__ import annotations

import hashlib
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

from PIL import Image

from app import converter
from app.converter import (
    ConvertError,
    CorruptedImageError,
    DestinationBusyError,
    ImageOptions,
    NoSpaceError,
    ResizeMode,
    SourceMissingError,
    TargetFormat,
    UnsupportedFormatError,
    build_destination,
    convert_batch,
    convert_image,
    is_supported_image,
)


def _noisy_image(size: tuple[int, int] = (96, 96), mode: str = "RGB") -> Image.Image:
    """Зображення з «шумом», яке добре реагує на зміну якості стиснення."""
    image = Image.new(mode, size)
    if mode == "RGB":
        pixels = image.load()
        for x in range(size[0]):
            for y in range(size[1]):
                value = (x * 37 + y * 91) % 256
                pixels[x, y] = (value, (value * 7) % 256, (value * 13) % 256)
    return image


def _flat_image(
    size: tuple[int, int] = (80, 40), color=(200, 40, 40), mode: str = "RGB"
) -> Image.Image:
    return Image.new(mode, size, color)


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ConverterTestCase(unittest.TestCase):
    """Спільна тимчасова папка для кожного тесту."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def save(self, name: str, image: Image.Image, **kwargs) -> Path:
        path = self.tmp / name
        image.save(path, **kwargs)
        return path

    def options(self, **kwargs) -> ImageOptions:
        kwargs.setdefault("target", TargetFormat.PNG)
        return ImageOptions(**kwargs)


class HelperTests(ConverterTestCase):
    def test_is_supported_image(self) -> None:
        for name in ("a.png", "a.JPG", "a.jpeg", "a.webp", "a.BMP"):
            with self.subTest(name=name):
                self.assertTrue(is_supported_image(Path(name)))
        for name in ("a.gif", "a.tiff", "a.txt", "a"):
            with self.subTest(name=name):
                self.assertFalse(is_supported_image(Path(name)))

    def test_resolve_target(self) -> None:
        self.assertIs(
            converter.resolve_target(Path("x.jpeg"), TargetFormat.SOURCE),
            TargetFormat.JPEG,
        )
        self.assertIs(
            converter.resolve_target(Path("x.PNG"), TargetFormat.SOURCE),
            TargetFormat.PNG,
        )
        self.assertIs(
            converter.resolve_target(Path("x.gif"), TargetFormat.WEBP),
            TargetFormat.WEBP,
        )
        with self.assertRaises(UnsupportedFormatError):
            converter.resolve_target(Path("x.gif"), TargetFormat.SOURCE)

    def test_options_validation(self) -> None:
        bad_options = [
            {"quality": 0},
            {"quality": 101},
            {"percent": 0},
            {"percent": 150},
            {"longest_side": 0},
            {"resize": ResizeMode.BOX, "box": None},
            {"resize": ResizeMode.BOX, "box": (0, 10)},
            {"background": "не-колір"},
        ]
        for kwargs in bad_options:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    ImageOptions(**kwargs)

    def test_build_destination_next_to_source(self) -> None:
        source = self.tmp / "photo.png"
        destination = build_destination(source, None, self.options())
        self.assertEqual(destination, source.with_suffix(".png").with_name("photo_1.png"))

    def test_build_destination_into_other_folder(self) -> None:
        source = self.tmp / "photo.png"
        out = self.tmp / "out"
        destination = build_destination(source, out, self.options(target=TargetFormat.WEBP))
        self.assertEqual(destination, out / "photo.webp")

    def test_build_destination_avoids_existing_and_taken(self) -> None:
        source = self.tmp / "photo.png"
        out = self.tmp / "out"
        out.mkdir()
        (out / "photo.jpg").write_bytes(b"x")
        taken = [out / "photo_1.jpg"]
        destination = build_destination(
            source, out, self.options(target=TargetFormat.JPEG), taken
        )
        self.assertEqual(destination, out / "photo_2.jpg")

    def test_build_destination_never_overwrites_source(self) -> None:
        source = self.tmp / "photo.png"
        destination = build_destination(
            source, None, self.options(target=TargetFormat.PNG, overwrite=True)
        )
        self.assertNotEqual(destination, source)
        self.assertEqual(destination.name, "photo_1.png")

    def test_build_destination_overwrite_existing(self) -> None:
        source = self.tmp / "photo.png"
        out = self.tmp / "out"
        out.mkdir()
        existing = out / "photo.jpg"
        existing.write_bytes(b"old")
        destination = build_destination(
            source, out, self.options(target=TargetFormat.JPEG, overwrite=True)
        )
        self.assertEqual(destination, existing)


class FormatTests(ConverterTestCase):
    def test_png_to_each_target(self) -> None:
        source = self.save("source.png", _flat_image())
        expected = {
            TargetFormat.JPEG: ".jpg",
            TargetFormat.WEBP: ".webp",
            TargetFormat.BMP: ".bmp",
        }
        for target, suffix in expected.items():
            with self.subTest(target=target):
                out = self.tmp / f"out{suffix}"
                result = convert_image(source, out, self.options(target=target))
                self.assertTrue(result.ok)
                self.assertTrue(out.exists())
                self.assertEqual(out.suffix, suffix)
                with Image.open(out) as converted:
                    self.assertEqual(converted.size, (80, 40))
                self.assertGreater(result.result_size, 0)
                self.assertEqual(result.source_size, source.stat().st_size)

    def test_each_source_to_png(self) -> None:
        sources = {
            "photo.jpg": ("JPEG", {}),
            "photo.webp": ("WEBP", {}),
            "photo.bmp": ("BMP", {}),
        }
        for name, (pil_format, kwargs) in sources.items():
            with self.subTest(source=name):
                path = self.tmp / name
                _flat_image().save(path, format=pil_format, **kwargs)
                out = self.tmp / f"{path.stem}-converted.png"
                result = convert_image(path, out, self.options())
                self.assertTrue(result.ok, result.message)
                with Image.open(out) as converted:
                    self.assertEqual(converted.format, "PNG")
                    self.assertEqual(converted.size, (80, 40))

    def test_same_format_keeps_original_untouched(self) -> None:
        source = self.save("photo.png", _noisy_image())
        before = _file_digest(source)
        out = build_destination(source, None, self.options(target=TargetFormat.PNG))
        convert_image(source, out, self.options(target=TargetFormat.PNG))
        self.assertNotEqual(out, source)
        self.assertEqual(_file_digest(source), before)
        self.assertTrue(out.exists())

    def test_source_target_uses_original_format(self) -> None:
        source = self.save("photo.jpg", _flat_image(), format="JPEG")
        out = self.tmp / "out-copy.jpg"
        convert_image(source, out, self.options(target=TargetFormat.SOURCE))
        with Image.open(out) as converted:
            self.assertEqual(converted.format, "JPEG")


class TransparencyTests(ConverterTestCase):
    def _transparent_png(self, name: str = "alpha.png") -> Path:
        image = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
        for x in range(10, 30):
            for y in range(10, 30):
                image.putpixel((x, y), (0, 0, 255, 255))
        return self.save(name, image)

    def test_alpha_flattened_to_white_for_jpeg(self) -> None:
        source = self._transparent_png()
        out = self.tmp / "out.jpg"
        convert_image(source, out, self.options(target=TargetFormat.JPEG))
        with Image.open(out) as converted:
            self.assertEqual(converted.mode, "RGB")
            corner = converted.getpixel((0, 0))
            self.assertTrue(all(channel > 240 for channel in corner), corner)
            centre = converted.getpixel((20, 20))
            self.assertLess(abs(centre[0]), 40, centre)
            self.assertGreater(centre[2], 200, centre)

    def test_alpha_flattened_for_bmp(self) -> None:
        source = self._transparent_png()
        out = self.tmp / "out.bmp"
        convert_image(source, out, self.options(target=TargetFormat.BMP))
        with Image.open(out) as converted:
            self.assertEqual(converted.mode, "RGB")

    def test_custom_background_color(self) -> None:
        source = self._transparent_png()
        out = self.tmp / "out-black.jpg"
        convert_image(
            source,
            out,
            self.options(target=TargetFormat.JPEG, background="#000000", quality=95),
        )
        with Image.open(out) as converted:
            corner = converted.getpixel((0, 0))
            self.assertTrue(all(channel < 20 for channel in corner), corner)

    def test_alpha_preserved_in_webp(self) -> None:
        source = self._transparent_png()
        out = self.tmp / "out.webp"
        convert_image(source, out, self.options(target=TargetFormat.WEBP))
        with Image.open(out) as converted:
            self.assertEqual(converted.mode, "RGBA")
            self.assertEqual(converted.getpixel((0, 0))[3], 0)

    def test_palette_transparency_to_jpeg(self) -> None:
        image = Image.new("P", (20, 20), 0)
        image.putpalette([255, 255, 255, 0, 0, 0] + [0] * 762)
        image.info["transparency"] = 0
        source = self.tmp / "palette.png"
        image.save(source)
        out = self.tmp / "palette.jpg"
        convert_image(source, out, self.options(target=TargetFormat.JPEG))
        with Image.open(out) as converted:
            corner = converted.getpixel((0, 0))
            self.assertTrue(all(channel > 240 for channel in corner), corner)


class QualityTests(ConverterTestCase):
    def test_jpeg_quality_changes_size(self) -> None:
        source = self.save("noise.png", _noisy_image())
        low = self.tmp / "low.jpg"
        high = self.tmp / "high.jpg"
        convert_image(source, low, self.options(target=TargetFormat.JPEG, quality=30))
        convert_image(source, high, self.options(target=TargetFormat.JPEG, quality=95))
        self.assertLess(low.stat().st_size, high.stat().st_size)

    def test_webp_quality_changes_size(self) -> None:
        source = self.save("noise.png", _noisy_image())
        low = self.tmp / "low.webp"
        high = self.tmp / "high.webp"
        convert_image(source, low, self.options(target=TargetFormat.WEBP, quality=20))
        convert_image(source, high, self.options(target=TargetFormat.WEBP, quality=95))
        self.assertLess(low.stat().st_size, high.stat().st_size)

    def test_png_quality_is_compression_level(self) -> None:
        source = self.save("noise.png", _noisy_image())
        weak = self.tmp / "weak.png"
        strong = self.tmp / "strong.png"
        convert_image(source, weak, self.options(target=TargetFormat.PNG, quality=1))
        convert_image(source, strong, self.options(target=TargetFormat.PNG, quality=100))
        self.assertLessEqual(strong.stat().st_size, weak.stat().st_size)


class ResizeTests(ConverterTestCase):
    def test_longest_side_keeps_aspect(self) -> None:
        source = self.save("wide.png", _flat_image((80, 40)))
        out = self.tmp / "wide-small.png"
        convert_image(
            source,
            out,
            self.options(resize=ResizeMode.LONGEST_SIDE, longest_side=40),
        )
        with Image.open(out) as converted:
            self.assertEqual(converted.size, (40, 20))

    def test_percent(self) -> None:
        source = self.save("wide.png", _flat_image((80, 40)))
        out = self.tmp / "wide-half.png"
        convert_image(source, out, self.options(resize=ResizeMode.PERCENT, percent=50))
        with Image.open(out) as converted:
            self.assertEqual(converted.size, (40, 20))

    def test_box_keep_aspect(self) -> None:
        source = self.save("wide.png", _flat_image((400, 200)))
        out = self.tmp / "wide-box.png"
        convert_image(
            source,
            out,
            self.options(resize=ResizeMode.BOX, box=(100, 100), keep_aspect=True),
        )
        with Image.open(out) as converted:
            self.assertEqual(converted.size, (100, 50))

    def test_box_stretch(self) -> None:
        source = self.save("wide.png", _flat_image((400, 200)))
        out = self.tmp / "wide-stretch.png"
        convert_image(
            source,
            out,
            self.options(resize=ResizeMode.BOX, box=(100, 100), keep_aspect=False),
        )
        with Image.open(out) as converted:
            self.assertEqual(converted.size, (100, 100))

    def test_no_upscale_by_default(self) -> None:
        source = self.save("small.png", _flat_image((80, 40)))
        out = self.tmp / "small-same.png"
        convert_image(
            source,
            out,
            self.options(resize=ResizeMode.LONGEST_SIDE, longest_side=4000),
        )
        with Image.open(out) as converted:
            self.assertEqual(converted.size, (80, 40))

    def test_upscale_when_allowed(self) -> None:
        source = self.save("small.png", _flat_image((80, 40)))
        out = self.tmp / "small-big.png"
        convert_image(
            source,
            out,
            self.options(
                resize=ResizeMode.LONGEST_SIDE, longest_side=160, allow_upscale=True
            ),
        )
        with Image.open(out) as converted:
            self.assertEqual(converted.size, (160, 80))


class MetadataTests(ConverterTestCase):
    def test_exif_orientation_applied_and_removed(self) -> None:
        image = _flat_image((40, 20))
        exif = image.getexif()
        exif[274] = 6  # повернути на 90°
        source = self.tmp / "rotated.jpg"
        image.save(source, exif=exif.tobytes())

        out = self.tmp / "rotated-out.jpg"
        convert_image(source, out, self.options(target=TargetFormat.JPEG))
        with Image.open(out) as converted:
            self.assertEqual(converted.size, (20, 40))
            self.assertIn(converted.getexif().get(274), (None, 1))

    def test_icc_profile_preserved(self) -> None:
        icc = b"fake-icc-profile"
        source = self.tmp / "icc.jpg"
        _flat_image().save(source, format="JPEG", icc_profile=icc)

        out = self.tmp / "icc-out.jpg"
        convert_image(source, out, self.options(target=TargetFormat.JPEG))
        with Image.open(out) as converted:
            self.assertEqual(converted.info.get("icc_profile"), icc)

    def test_metadata_can_be_dropped(self) -> None:
        icc = b"fake-icc-profile"
        source = self.tmp / "icc.jpg"
        _flat_image().save(source, format="JPEG", icc_profile=icc)

        out = self.tmp / "icc-dropped.jpg"
        convert_image(
            source,
            out,
            self.options(target=TargetFormat.JPEG, preserve_metadata=False),
        )
        with Image.open(out) as converted:
            self.assertIsNone(converted.info.get("icc_profile"))

    def test_bmp_accepts_no_metadata(self) -> None:
        icc = b"fake-icc-profile"
        source = self.tmp / "icc.png"
        _flat_image().save(source, format="PNG", icc_profile=icc)
        out = self.tmp / "icc.bmp"
        result = convert_image(source, out, self.options(target=TargetFormat.BMP))
        self.assertTrue(result.ok, result.message)


class ErrorTests(ConverterTestCase):
    def test_missing_source(self) -> None:
        with self.assertRaises(SourceMissingError):
            convert_image(
                self.tmp / "missing.png",
                self.tmp / "out.png",
                self.options(),
            )

    def test_corrupted_file(self) -> None:
        broken = self.tmp / "broken.png"
        broken.write_bytes(b"this is not an image")
        with self.assertRaises(CorruptedImageError):
            convert_image(broken, self.tmp / "out.png", self.options())

    def test_unsupported_format_by_content(self) -> None:
        gif = self.tmp / "anim.gif"
        _flat_image().save(gif, format="GIF")
        with self.assertRaises(UnsupportedFormatError):
            convert_image(gif, self.tmp / "out.png", self.options())

    def test_unsupported_extension(self) -> None:
        text = self.tmp / "notes.txt"
        text.write_text("просто текст", encoding="utf-8")
        with self.assertRaises(UnsupportedFormatError):
            convert_image(text, self.tmp / "out.png", self.options())

    def test_source_equals_destination(self) -> None:
        source = self.save("same.png", _flat_image())
        with self.assertRaises(ConvertError):
            convert_image(source, source, self.options())

    def test_no_space_left(self) -> None:
        source = self.save("photo.png", _flat_image())
        usage = SimpleNamespace(total=10**9, used=10**9, free=0)
        with mock.patch.object(converter.shutil, "disk_usage", return_value=usage):
            with self.assertRaises(NoSpaceError):
                convert_image(source, self.tmp / "out.png", self.options())

    def test_destination_busy(self) -> None:
        source = self.save("photo.png", _flat_image())
        with mock.patch.object(
            converter.os, "replace", side_effect=PermissionError("locked")
        ):
            with self.assertRaises(DestinationBusyError):
                convert_image(source, self.tmp / "out.png", self.options())
        leftovers = list(self.tmp.glob(".file-toolkit-*"))
        self.assertEqual(leftovers, [])

    def test_failed_conversion_leaves_no_temp_files(self) -> None:
        source = self.save("photo.png", _flat_image())
        out_dir = self.tmp / "out"
        with mock.patch.object(
            converter.Image.Image, "save", side_effect=OSError("disk error")
        ):
            with self.assertRaises(ConvertError):
                convert_image(source, out_dir / "out.png", self.options())
        leftovers = list(out_dir.glob(".file-toolkit-*"))
        self.assertEqual(leftovers, [])


class BatchTests(ConverterTestCase):
    def test_mixed_batch_continues_after_error(self) -> None:
        good = self.save("good.png", _flat_image())
        broken = self.tmp / "broken.png"
        broken.write_bytes(b"not an image")
        results = convert_batch(
            [good, broken], self.options(target=TargetFormat.JPEG), self.tmp / "out"
        )
        self.assertEqual(len(results), 2)
        self.assertTrue(results[0].ok)
        self.assertFalse(results[1].ok)
        self.assertIn("пошкоджений", results[1].message)

    def test_progress_reports_each_file(self) -> None:
        first = self.save("one.png", _flat_image())
        second = self.save("two.png", _flat_image())
        calls: list[tuple[int, int, Path | None]] = []
        convert_batch(
            [first, second],
            self.options(target=TargetFormat.PNG),
            self.tmp / "out",
            on_progress=lambda done, total, source: calls.append((done, total, source)),
        )
        self.assertEqual(calls[0], (0, 2, first))
        self.assertEqual(calls[1], (1, 2, second))
        self.assertEqual(calls[-1], (2, 2, None))

    def test_cancel_stops_processing(self) -> None:
        sources = [
            self.save(f"file{index}.png", _flat_image()) for index in range(3)
        ]
        processed = {"count": 0}

        def should_cancel() -> bool:
            return processed["count"] > 0

        def on_progress(done: int, total: int, source: Path | None) -> None:
            if source is not None:
                processed["count"] += 1

        results = convert_batch(
            sources,
            self.options(target=TargetFormat.PNG),
            self.tmp / "out",
            on_progress=on_progress,
            should_cancel=should_cancel,
        )
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].ok)

    def test_batch_without_output_dir_saves_next_to_source(self) -> None:
        source = self.save("photo.png", _flat_image())
        results = convert_batch([source], self.options(target=TargetFormat.JPEG))
        self.assertEqual(results[0].destination, self.tmp / "photo.jpg")

    def test_batch_handles_same_names_from_different_folders(self) -> None:
        first_dir = self.tmp / "a"
        second_dir = self.tmp / "b"
        first_dir.mkdir()
        second_dir.mkdir()
        first = first_dir / "photo.png"
        second = second_dir / "photo.png"
        _flat_image().save(first)
        _flat_image().save(second)

        out = self.tmp / "out"
        results = convert_batch(
            [first, second], self.options(target=TargetFormat.JPEG), out
        )
        destinations = [result.destination for result in results]
        self.assertEqual(len(set(destinations)), 2)
        for destination in destinations:
            self.assertTrue(destination.exists())

    def test_batch_reports_unreadable_sources(self) -> None:
        missing = self.tmp / "missing.png"
        results = convert_batch([missing], self.options(), self.tmp / "out")
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0].ok)
        self.assertIn("не знайдено", results[0].message)


if __name__ == "__main__":
    unittest.main()
