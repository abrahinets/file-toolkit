"""Генерує набір тестових зображень у папці test_images/.

Скрипт потрібен лише для ручних перевірок конвертера: він створює
зображення різних форматів, з прозорістю, велике фото та JPG із
EXIF-орієнтацією 6 (повернуте). У репозиторій результат не потрапляє —
папка test_images/ є в .gitignore.

Запуск:  python tools/make_test_images.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "test_images"

ORIENTATION_TAG = 0x0112
ORIENTATION_ROTATE_90 = 6

RED = (214, 64, 64)
GREEN = (58, 160, 96)
BLUE = (58, 108, 196)
DARK = (32, 38, 48)
LIGHT = (242, 244, 248)


def _gradient(
    width: int, height: int, top: tuple[int, int, int], bottom: tuple[int, int, int]
) -> Image.Image:
    """Вертикальний градієнт — дешевий фон для тестових картинок."""
    column = Image.new("RGB", (1, height))
    for y in range(height):
        ratio = y / max(height - 1, 1)
        column.putpixel(
            (0, y),
            tuple(round(start + (end - start) * ratio) for start, end in zip(top, bottom)),
        )
    return column.resize((width, height), Image.BILINEAR)


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # старі версії Pillow
        return ImageFont.load_default()


def _draw_label(
    draw: ImageDraw.ImageDraw,
    position: tuple[int, int],
    text: str,
    size: int,
    color: tuple[int, int, int] = LIGHT,
) -> None:
    draw.text(position, text, fill=color, font=_font(size))


def make_png_with_alpha() -> Image.Image:
    """PNG із прозорістю: повністю прозорий фон і напівпрозорі фігури."""
    image = Image.new("RGBA", (800, 600), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")

    draw.ellipse((80, 80, 400, 400), fill=RED + (255,))
    draw.rectangle((320, 220, 720, 520), fill=BLUE + (128,))
    draw.ellipse((420, 320, 760, 560), fill=GREEN + (200,))
    draw.rectangle((60, 470, 300, 560), fill=(255, 255, 255, 90))

    _draw_label(draw, (100, 180), "ALPHA", 72, (255, 255, 255, 255))
    return image


def make_png_opaque() -> Image.Image:
    """Звичайний PNG без прозорості."""
    image = _gradient(1024, 768, (38, 62, 104), (14, 18, 26))
    draw = ImageDraw.Draw(image)

    draw.rectangle((40, 40, 300, 220), fill=RED)
    draw.ellipse((360, 40, 620, 220), fill=GREEN)
    draw.rectangle((680, 40, 984, 220), fill=BLUE)
    for index in range(8):
        y = 300 + index * 52
        draw.rectangle((40, y, 984, y + 26), fill=(30 + index * 22, 90, 160))

    _draw_label(draw, (40, 660), "PNG opaque 1024x768", 40)
    return image


def make_jpeg() -> Image.Image:
    """Звичайний JPG із градієнтом і фігурами."""
    image = _gradient(1600, 1200, (240, 168, 96), (40, 48, 96))
    draw = ImageDraw.Draw(image)

    draw.ellipse((980, 120, 1500, 640), fill=(255, 226, 120))
    draw.polygon([(0, 1200), (520, 620), (1040, 1200)], fill=(28, 72, 72))
    draw.polygon([(420, 1200), (900, 760), (1380, 1200)], fill=(18, 46, 52))

    _draw_label(draw, (60, 60), "JPEG 1600x1200", 64)
    return image


def make_webp() -> Image.Image:
    """WebP для перевірки якості стиснення."""
    image = _gradient(1200, 900, (72, 32, 96), (16, 24, 40))
    draw = ImageDraw.Draw(image)

    for index in range(6):
        offset = index * 90
        draw.ellipse(
            (120 + offset, 240 + offset, 420 + offset, 540 + offset),
            outline=(90 + index * 24, 200 - index * 18, 240),
            width=14,
        )

    _draw_label(draw, (60, 60), "WebP 1200x900", 52)
    return image


def make_bmp() -> Image.Image:
    """BMP — формат без стиснення."""
    image = _gradient(640, 480, (18, 96, 96), (12, 20, 32))
    draw = ImageDraw.Draw(image)

    draw.rectangle((40, 40, 600, 200), fill=(240, 240, 240))
    _draw_label(draw, (70, 90), "BMP 640x480", 56, DARK)
    draw.rectangle((40, 260, 600, 440), outline=RED, width=10)
    draw.line((40, 440, 600, 260), fill=GREEN, width=8)
    return image


def make_large_image() -> Image.Image:
    """Велике зображення 4000x3000 — для перевірки чуйності інтерфейсу."""
    width, height = 4000, 3000
    image = _gradient(width, height, (46, 88, 148), (18, 22, 34))

    # Дрібний шум робить файл важчим і ближчим до справжньої фотографії.
    noise = Image.effect_noise((width // 2, height // 2), 26)
    noise = noise.resize((width, height), Image.BILINEAR)
    image = Image.blend(image, Image.merge("RGB", (noise, noise, noise)), 0.18)

    draw = ImageDraw.Draw(image)
    draw.rectangle((160, 160, 1600, 900), fill=(226, 96, 64))
    draw.ellipse((2200, 1200, 3700, 2700), fill=(64, 148, 120))
    _draw_label(draw, (200, 1000), "4000 x 3000", 180)
    _draw_label(draw, (200, 1250), "large test image", 96)
    return image


def make_jpeg_with_exif_orientation() -> Image.Image:
    """JPG із EXIF-орієнтацією 6: перегляд повертає його на 90°."""
    image = Image.new("RGB", (1200, 900), (236, 238, 242))
    draw = ImageDraw.Draw(image)

    draw.rectangle((0, 0, 1200, 160), fill=(200, 48, 48))
    _draw_label(draw, (40, 44), "TOP OF THE PHOTO", 64, (255, 255, 255))

    draw.rectangle((40, 200, 400, 560), fill=GREEN)
    draw.rectangle((800, 200, 1160, 560), fill=BLUE)
    draw.rectangle((40, 620, 1160, 860), fill=DARK)

    _draw_label(draw, (60, 700), "EXIF orientation = 6", 52)
    _draw_label(draw, (60, 780), "viewer rotates this 90 degrees", 34)
    return image


def _save(image: Image.Image, name: str, **kwargs) -> Path:
    path = OUTPUT_DIR / name
    image.save(path, **kwargs)
    return path


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    saved: list[Path] = [
        _save(make_png_with_alpha(), "png_transparent.png", format="PNG"),
        _save(make_png_opaque(), "png_opaque.png", format="PNG", optimize=True),
        _save(make_jpeg(), "photo.jpg", format="JPEG", quality=90),
        _save(make_webp(), "image.webp", format="WEBP", quality=85),
        _save(make_bmp(), "picture.bmp", format="BMP"),
        _save(make_large_image(), "large_4000x3000.png", format="PNG"),
    ]

    exif = Image.Exif()
    exif[ORIENTATION_TAG] = ORIENTATION_ROTATE_90
    saved.append(
        _save(
            make_jpeg_with_exif_orientation(),
            "photo_exif_orientation6.jpg",
            format="JPEG",
            quality=90,
            exif=exif.tobytes(),
        )
    )

    print(f"Готово: {OUTPUT_DIR}")
    for path in saved:
        with Image.open(path) as opened:
            orientation = opened.getexif().get(ORIENTATION_TAG, "—")
            size = f"{opened.width}x{opened.height}"
            print(
                f"  {path.name:<28} {opened.format:<4} {size:<10} "
                f"{path.stat().st_size / 1024:8.1f} КБ  EXIF orientation: {orientation}"
            )


if __name__ == "__main__":
    main()
