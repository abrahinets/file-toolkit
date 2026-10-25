"""Логіка конвертації зображень: PNG, JPG, WebP, BMP.

Модуль навмисно не залежить від інтерфейсу, щоб його можна було
тестувати окремо. Усі повідомлення про помилки — українською, щоб
інтерфейс міг показувати їх без перекладу.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable, Iterable, Sequence

from PIL import Image, ImageColor, ImageOps, UnidentifiedImageError

# Обмеження на кількість пікселів захищає від «бомб декомпресії».
# 200 Мпкс — це, наприклад, панорама 17000×11700.
MAX_IMAGE_PIXELS = 200_000_000
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

SUPPORTED_INPUT_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp"})

MIN_QUALITY = 1
MAX_QUALITY = 100
DEFAULT_QUALITY = 85

# Скільки місця приблизно потрібно на виході відносно вхідного файлу.
SPACE_FACTOR = 2.0
SPACE_RESERVE_BYTES = 1_000_000

WARNING_ANIMATED = "Використано перший кадр (анімоване зображення)"


class ConvertError(Exception):
    """Помилка конвертації з готовим текстом для інтерфейсу."""


class UnsupportedFormatError(ConvertError):
    """Формат файлу не підтримується."""


class CorruptedImageError(ConvertError):
    """Файл пошкоджений або не є зображенням."""


class SourceMissingError(ConvertError):
    """Вихідний файл не знайдено."""


class DestinationBusyError(ConvertError):
    """Файл або папка призначення зайняті іншою програмою."""


class NoSpaceError(ConvertError):
    """На диску недостатньо місця."""


class TargetFormat(StrEnum):
    """Цільовий формат. SOURCE — зберегти формат оригіналу."""

    SOURCE = "source"
    PNG = "png"
    JPEG = "jpg"
    WEBP = "webp"
    BMP = "bmp"


class ResizeMode(StrEnum):
    """Режим зміни розміру."""

    NONE = "none"
    LONGEST_SIDE = "longest_side"
    PERCENT = "percent"
    BOX = "box"


TARGET_FORMAT_LABELS = {
    TargetFormat.SOURCE: "Як у вихідному",
    TargetFormat.PNG: "PNG",
    TargetFormat.JPEG: "JPG",
    TargetFormat.WEBP: "WebP",
    TargetFormat.BMP: "BMP",
}

TARGET_FORMAT_SUFFIXES = {
    TargetFormat.PNG: ".png",
    TargetFormat.JPEG: ".jpg",
    TargetFormat.WEBP: ".webp",
    TargetFormat.BMP: ".bmp",
}

# Формати, які вміють зберігати прозорість.
ALPHA_FORMATS = frozenset({TargetFormat.PNG, TargetFormat.WEBP})

# Формати, які приймають EXIF/ICC під час запису.
METADATA_FORMATS = frozenset(
    {TargetFormat.PNG, TargetFormat.JPEG, TargetFormat.WEBP}
)

_PIL_FORMATS = {
    "PNG": TargetFormat.PNG,
    "JPEG": TargetFormat.JPEG,
    "WEBP": TargetFormat.WEBP,
    "BMP": TargetFormat.BMP,
}


@dataclass(frozen=True)
class ImageOptions:
    """Налаштування конвертації зображень."""

    target: TargetFormat = TargetFormat.SOURCE
    quality: int = DEFAULT_QUALITY
    resize: ResizeMode = ResizeMode.NONE
    longest_side: int = 1920
    percent: int = 100
    box: tuple[int, int] | None = None
    keep_aspect: bool = True
    allow_upscale: bool = False
    background: str = "#FFFFFF"
    overwrite: bool = False
    preserve_metadata: bool = True

    def __post_init__(self) -> None:
        if not MIN_QUALITY <= self.quality <= MAX_QUALITY:
            raise ValueError(
                f"Якість має бути від {MIN_QUALITY} до {MAX_QUALITY}, а не {self.quality}"
            )
        if not 1 <= self.percent <= 100:
            raise ValueError("Відсоток має бути від 1 до 100")
        if self.longest_side < 1:
            raise ValueError("Довша сторона має бути більшою за 0")
        if self.resize is ResizeMode.BOX:
            if not self.box or len(self.box) != 2:
                raise ValueError("Для точного розміру потрібні ширина і висота")
            if min(self.box) < 1:
                raise ValueError("Ширина і висота мають бути більшими за 0")
        # Перевіряємо, що колір підкладки коректний, ще до обробки файлів.
        try:
            ImageColor.getrgb(self.background)
        except ValueError as exc:
            raise ValueError(f"Невідомий колір підкладки: {self.background}") from exc


@dataclass
class ConversionResult:
    """Результат конвертації одного файлу."""

    source: Path
    destination: Path | None
    ok: bool
    message: str = ""
    source_size: int = 0
    result_size: int = 0


ProgressCallback = Callable[[int, int, Path | None], None]
CancelCallback = Callable[[], bool]


# --- допоміжні функції ------------------------------------------------------


def is_supported_image(path: Path) -> bool:
    """Чи підтримується файл за розширенням (швидка перевірка для списку)."""
    return Path(path).suffix.lower() in SUPPORTED_INPUT_SUFFIXES


def resolve_target(source: Path, target: TargetFormat) -> TargetFormat:
    """Перетворює SOURCE на конкретний формат за розширенням файлу."""
    if target is not TargetFormat.SOURCE:
        return target
    suffix = Path(source).suffix.lower()
    if suffix == ".jpeg":
        return TargetFormat.JPEG
    for fmt, fmt_suffix in TARGET_FORMAT_SUFFIXES.items():
        if fmt_suffix == suffix:
            return fmt
    raise UnsupportedFormatError(f"Формат не підтримується: {suffix or 'без розширення'}")


def build_destination(
    source: Path,
    output_dir: Path | None,
    options: ImageOptions,
    taken: Iterable[Path] = (),
) -> Path:
    """Підбирає вільне ім'я для результату, не перезаписуючи оригінал."""
    source = Path(source)
    target = resolve_target(source, options.target)
    directory = Path(output_dir) if output_dir else source.parent
    suffix = TARGET_FORMAT_SUFFIXES[target]

    used = {_path_key(path) for path in taken}
    used.add(_path_key(source))

    stem = source.stem
    index = 0
    while True:
        name = f"{stem}{suffix}" if index == 0 else f"{stem}_{index}{suffix}"
        candidate = directory / name
        if options.overwrite and _path_key(candidate) != _path_key(source):
            return candidate
        if _path_key(candidate) not in used and not candidate.exists():
            return candidate
        index += 1


def convert_image(
    source: Path,
    destination: Path,
    options: ImageOptions,
) -> ConversionResult:
    """Конвертує один файл. Помилки — підкласи ConvertError."""
    source = Path(source)
    destination = Path(destination)

    if not source.is_file():
        raise SourceMissingError(f"Файл не знайдено: {source}")
    if _path_key(source) == _path_key(destination):
        raise ConvertError("Джерело та призначення збігаються — оригінал не перезаписуємо")

    source_size = source.stat().st_size
    warning = ""

    try:
        with Image.open(source) as opened:
            pil_format = opened.format
            if pil_format not in _PIL_FORMATS:
                raise UnsupportedFormatError(
                    f"Формат не підтримується: {pil_format or 'невідомий'}"
                )
            opened.load()
            if getattr(opened, "n_frames", 1) > 1:
                warning = WARNING_ANIMATED
            image = ImageOps.exif_transpose(opened)
    except UnsupportedFormatError:
        raise
    except UnidentifiedImageError as exc:
        suffix = source.suffix.lower()
        if suffix not in SUPPORTED_INPUT_SUFFIXES:
            raise UnsupportedFormatError(
                f"Формат не підтримується: {suffix or 'без розширення'}"
            ) from exc
        raise CorruptedImageError("Файл пошкоджений або не є зображенням") from exc
    except Image.DecompressionBombError as exc:
        raise CorruptedImageError(
            f"Зображення завелике (понад {MAX_IMAGE_PIXELS // 1_000_000} Мпкс)"
        ) from exc
    except OSError as exc:
        raise CorruptedImageError("Файл пошкоджений або не є зображенням") from exc

    # Ім'я файлу й формат запису узгоджуємо з тим, що обрав користувач
    # (або з розширенням оригіналу в режимі «Як у вихідному»).
    target = resolve_target(source, options.target)

    metadata = _read_metadata(image) if options.preserve_metadata else (None, None)

    image = _resize(image, options)
    image = _prepare_mode(image, target, options.background)

    _check_free_space(destination.parent, source_size)

    save_format = _SAVE_FORMATS[target]
    save_kwargs = _save_kwargs(target, options, metadata)
    _atomic_save(image, destination, save_format, save_kwargs)

    result_size = destination.stat().st_size if destination.exists() else 0
    return ConversionResult(
        source=source,
        destination=destination,
        ok=True,
        message=warning,
        source_size=source_size,
        result_size=result_size,
    )


def convert_batch(
    sources: Sequence[Path],
    options: ImageOptions,
    output_dir: Path | None = None,
    *,
    on_progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
) -> list[ConversionResult]:
    """Конвертує пакет файлів, не зупиняючись на помилках окремих файлів.

    Повертає результати лише для оброблених файлів: якщо спрацювало
    скасування, решта файлів просто не обробляється.
    """
    sources = [Path(source) for source in sources]
    total = len(sources)
    results: list[ConversionResult] = []
    taken: list[Path] = []

    for index, source in enumerate(sources):
        if should_cancel is not None and should_cancel():
            break
        if on_progress is not None:
            on_progress(index, total, source)
        try:
            destination = build_destination(source, output_dir, options, taken)
            taken.append(destination)
            results.append(convert_image(source, destination, options))
        except ConvertError as exc:
            results.append(
                ConversionResult(
                    source=source,
                    destination=None,
                    ok=False,
                    message=str(exc),
                    source_size=_safe_size(source),
                )
            )

    if on_progress is not None:
        on_progress(len(results), total, None)
    return results


# --- внутрішні кроки --------------------------------------------------------

_SAVE_FORMATS = {
    TargetFormat.PNG: "PNG",
    TargetFormat.JPEG: "JPEG",
    TargetFormat.WEBP: "WEBP",
    TargetFormat.BMP: "BMP",
}


def _path_key(path: Path) -> str:
    """Ключ для порівняння шляхів без урахування регістру (Windows)."""
    return os.path.normcase(os.path.abspath(str(path)))


def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _read_metadata(image: Image.Image) -> tuple[bytes | None, bytes | None]:
    """EXIF та ICC-профіль; пошкоджені метадані просто ігноруємо."""
    exif = None
    icc = None
    try:
        raw_exif = image.info.get("exif")
        if raw_exif:
            exif = bytes(raw_exif)
    except (OSError, ValueError):
        exif = None
    try:
        raw_icc = image.info.get("icc_profile")
        if raw_icc:
            icc = bytes(raw_icc)
    except (OSError, ValueError):
        icc = None
    return exif, icc


def _resize(image: Image.Image, options: ImageOptions) -> Image.Image:
    mode = options.resize
    if mode is ResizeMode.NONE:
        return image

    width, height = image.size
    if width < 1 or height < 1:
        return image

    if mode is ResizeMode.PERCENT:
        scale = options.percent / 100
    elif mode is ResizeMode.LONGEST_SIDE:
        longest = max(width, height)
        scale = options.longest_side / longest
    elif mode is ResizeMode.BOX:
        box_width, box_height = options.box or (width, height)
        if options.keep_aspect:
            scale = min(box_width / width, box_height / height)
        else:
            if not options.allow_upscale and box_width >= width and box_height >= height:
                return image
            return image.resize((box_width, box_height), Image.Resampling.LANCZOS)
    else:  # pragma: no cover - усі режими перелічені вище
        return image

    if scale >= 1 and not options.allow_upscale:
        return image

    new_size = (
        max(1, round(width * scale)),
        max(1, round(height * scale)),
    )
    if new_size == (width, height):
        return image
    return image.resize(new_size, Image.Resampling.LANCZOS)


def _has_alpha(image: Image.Image) -> bool:
    return image.mode in ("RGBA", "LA", "PA") or (
        image.mode == "P" and "transparency" in image.info
    )


def _prepare_mode(image: Image.Image, target: TargetFormat, background: str) -> Image.Image:
    """Приводить режим зображення до сумісного з цільовим форматом."""
    if target in ALPHA_FORMATS:
        if image.mode in ("1", "L", "LA", "P", "PA", "RGB", "RGBA"):
            return image
        return image.convert("RGBA" if _has_alpha(image) else "RGB")

    # JPG і BMP не підтримують прозорість — накладаємо на підкладку.
    if _has_alpha(image):
        rgba = image.convert("RGBA")
        base = Image.new("RGBA", rgba.size, ImageColor.getrgb(background) + (255,))
        base.alpha_composite(rgba)
        return base.convert("RGB")
    if image.mode in ("RGB",):
        return image
    return image.convert("RGB")


def _save_kwargs(
    target: TargetFormat,
    options: ImageOptions,
    metadata: tuple[bytes | None, bytes | None],
) -> dict:
    kwargs: dict = {}
    if target is TargetFormat.PNG:
        # Для PNG «якість» — це сила стиснення: 100 → 9, 1 → 0.
        kwargs["compress_level"] = round(
            (MAX_QUALITY - options.quality) / (MAX_QUALITY - MIN_QUALITY) * 9
        )
        kwargs["optimize"] = True
    elif target is TargetFormat.JPEG:
        kwargs["quality"] = options.quality
        kwargs["optimize"] = True
        kwargs["progressive"] = True
        # При високій якості не «розмиваємо» кольори підвибіркою 4:2:0.
        kwargs["subsampling"] = 0 if options.quality >= 95 else 2
    elif target is TargetFormat.WEBP:
        kwargs["quality"] = options.quality
        kwargs["method"] = 4

    if target in METADATA_FORMATS:
        exif, icc = metadata
        if exif:
            kwargs["exif"] = exif
        if icc:
            kwargs["icc_profile"] = icc
    return kwargs


def _check_free_space(directory: Path, source_size: int) -> None:
    needed = int(source_size * SPACE_FACTOR) + SPACE_RESERVE_BYTES
    probe = directory if directory.exists() else _nearest_existing(directory)
    try:
        free = shutil.disk_usage(probe).free
    except OSError:
        return
    if free < needed:
        raise NoSpaceError(
            f"Недостатньо місця на диску: потрібно ~{needed // 1024} КБ"
        )


def _nearest_existing(directory: Path) -> Path:
    current = directory
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def _atomic_save(
    image: Image.Image,
    destination: Path,
    save_format: str,
    save_kwargs: dict,
) -> None:
    """Пише в тимчасовий файл і підміняє його лише після успіху."""
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DestinationBusyError("Папка призначення недоступна") from exc

    temp_path: Path | None = None
    try:
        handle, temp_name = tempfile.mkstemp(
            prefix=".file-toolkit-", suffix=".tmp", dir=destination.parent
        )
        os.close(handle)
        temp_path = Path(temp_name)
        image.save(temp_path, format=save_format, **save_kwargs)
        os.replace(temp_path, destination)
        temp_path = None
    except PermissionError as exc:
        raise DestinationBusyError("Файл відкритий в іншій програмі") from exc
    except OSError as exc:
        if getattr(exc, "winerror", None) == 112 or exc.errno == 28:
            raise NoSpaceError("Недостатньо місця на диску") from exc
        raise ConvertError(f"Не вдалося записати файл: {exc}") from exc
    finally:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
