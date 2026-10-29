"""Логіка конвертації відео через ffmpeg з пакета imageio-ffmpeg.

Модуль навмисно не залежить від інтерфейсу, щоб його можна було
тестувати окремо. Усі повідомлення про помилки — українською, щоб
інтерфейс міг показувати їх без перекладу.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
from collections import deque
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from pathlib import Path
from typing import Callable, Iterable, Sequence

SUPPORTED_INPUT_SUFFIXES = frozenset(
    {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv"}
)

# Скільки місця приблизно потрібно на виході відносно вхідного файлу.
# GIF зазвичай роздувається сильніше, тому для нього запас більший.
SPACE_FACTOR = 2.0
GIF_SPACE_FACTOR = 3.0
SPACE_RESERVE_BYTES = 1_000_000

PROBE_TIMEOUT = 30.0
TERMINATE_TIMEOUT = 3.0
STDERR_TAIL_LINES = 80
MAX_ERROR_TEXT = 300

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)")
_TIMESTAMP_RE = re.compile(r"^(\d+):(\d{2}):(\d{2}(?:\.\d+)?)$")
_VIDEO_SIZE_RE = re.compile(r"(\d{2,5})x(\d{2,5})")


class VideoConvertError(Exception):
    """Помилка конвертації відео з готовим текстом для інтерфейсу."""


class UnsupportedVideoFormatError(VideoConvertError):
    """Формат відео не підтримується."""


class CorruptedVideoError(VideoConvertError):
    """Файл пошкоджений або не є відео."""


class NoVideoStreamError(VideoConvertError):
    """У файлі немає відеодоріжки."""


class NoAudioStreamError(VideoConvertError):
    """У файлі немає звукової доріжки."""


class SourceMissingError(VideoConvertError):
    """Вихідний файл не знайдено."""


class DestinationBusyError(VideoConvertError):
    """Файл або папка призначення зайняті іншою програмою."""


class NoSpaceError(VideoConvertError):
    """На диску недостатньо місця."""


class FfmpegMissingError(VideoConvertError):
    """Не знайдено бінарник ffmpeg."""


class ConversionCancelled(VideoConvertError):
    """Конвертацію скасовано користувачем."""


class OutputFormat(StrEnum):
    """Цільовий формат відео або звуку."""

    MP4 = "mp4"
    WEBM = "webm"
    MKV = "mkv"
    GIF = "gif"
    MP3 = "mp3"
    WAV = "wav"


class QualityPreset(StrEnum):
    """Пресет якості."""

    SMALLER = "smaller"
    BALANCED = "balanced"
    BETTER = "better"


class MaxHeight(IntEnum):
    """Максимальна висота відео; NONE — не змінювати."""

    P480 = 480
    P720 = 720
    P1080 = 1080
    NONE = 0


OUTPUT_SUFFIXES = {
    OutputFormat.MP4: ".mp4",
    OutputFormat.WEBM: ".webm",
    OutputFormat.MKV: ".mkv",
    OutputFormat.GIF: ".gif",
    OutputFormat.MP3: ".mp3",
    OutputFormat.WAV: ".wav",
}

OUTPUT_FORMAT_LABELS = {
    OutputFormat.MP4: "MP4 (H.264)",
    OutputFormat.WEBM: "WebM",
    OutputFormat.MKV: "MKV",
    OutputFormat.GIF: "GIF",
    OutputFormat.MP3: "MP3 (звук)",
    OutputFormat.WAV: "WAV (звук)",
}

QUALITY_LABELS = {
    QualityPreset.SMALLER: "Менший файл",
    QualityPreset.BALANCED: "Баланс",
    QualityPreset.BETTER: "Краща якість",
}

HEIGHT_LABELS = {
    MaxHeight.P480: "480p",
    MaxHeight.P720: "720p",
    MaxHeight.P1080: "1080p",
    MaxHeight.NONE: "Без змін",
}

AUDIO_OUTPUT_FORMATS = frozenset({OutputFormat.MP3, OutputFormat.WAV})
VIDEO_OUTPUT_FORMATS = frozenset(
    {OutputFormat.MP4, OutputFormat.WEBM, OutputFormat.MKV, OutputFormat.GIF}
)

_MUXERS = {
    OutputFormat.MP4: "mp4",
    OutputFormat.WEBM: "webm",
    OutputFormat.MKV: "matroska",
    OutputFormat.GIF: "gif",
    OutputFormat.MP3: "mp3",
    OutputFormat.WAV: "wav",
}

_X264_CRF = {
    QualityPreset.SMALLER: 28,
    QualityPreset.BALANCED: 23,
    QualityPreset.BETTER: 18,
}

_VP9_CRF = {
    QualityPreset.SMALLER: 40,
    QualityPreset.BALANCED: 33,
    QualityPreset.BETTER: 28,
}

_VIDEO_AUDIO_KBPS = {
    QualityPreset.SMALLER: 96,
    QualityPreset.BALANCED: 128,
    QualityPreset.BETTER: 192,
}

_MP3_KBPS = {
    QualityPreset.SMALLER: 128,
    QualityPreset.BALANCED: 192,
    QualityPreset.BETTER: 256,
}

_GIF_FPS = {
    QualityPreset.SMALLER: 10,
    QualityPreset.BALANCED: 12,
    QualityPreset.BETTER: 15,
}

_GIF_COLORS = {
    QualityPreset.SMALLER: 128,
    QualityPreset.BALANCED: 256,
    QualityPreset.BETTER: 256,
}


@dataclass(frozen=True)
class VideoOptions:
    """Налаштування конвертації відео."""

    target: OutputFormat = OutputFormat.MP4
    quality: QualityPreset = QualityPreset.BALANCED
    max_height: MaxHeight = MaxHeight.P720
    no_audio: bool = False
    crf: int | None = None
    overwrite: bool = False

    def __post_init__(self) -> None:
        if self.crf is not None and not 0 <= self.crf <= 63:
            raise ValueError("CRF має бути від 0 до 63")


@dataclass(frozen=True, slots=True)
class MediaInfo:
    """Те, що вдалося дізнатися про файл із виводу ffmpeg."""

    duration: float | None
    width: int | None
    height: int | None
    has_video: bool
    has_audio: bool


@dataclass(slots=True)
class VideoConversionResult:
    """Результат конвертації одного файлу."""

    source: Path
    destination: Path | None
    ok: bool
    message: str = ""
    source_size: int = 0
    result_size: int = 0
    duration: float | None = None


ProgressCallback = Callable[[int, int, Path | None, float | None], None]
FractionCallback = Callable[[float | None], None]
CancelCallback = Callable[[], bool]


# --- допоміжні функції ------------------------------------------------------


def is_supported_video(path: Path) -> bool:
    """Чи підтримується файл за розширенням (швидка перевірка для списку)."""
    return Path(path).suffix.lower() in SUPPORTED_INPUT_SUFFIXES


def build_destination(
    source: Path,
    output_dir: Path | None,
    options: VideoOptions,
    taken: Iterable[Path] = (),
) -> Path:
    """Підбирає вільне ім'я для результату, не перезаписуючи оригінал."""
    source = Path(source)
    directory = Path(output_dir) if output_dir else source.parent
    suffix = OUTPUT_SUFFIXES[options.target]

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


# --- ffmpeg -----------------------------------------------------------------


def _get_ffmpeg_exe() -> str:
    """Шлях до ffmpeg із пакета imageio-ffmpeg (кешується)."""
    global _FFMPEG_EXE
    if _FFMPEG_EXE:
        return _FFMPEG_EXE
    try:
        import imageio_ffmpeg
    except Exception as exc:  # pragma: no cover - залежність є в requirements
        raise FfmpegMissingError(
            "Не знайдено ffmpeg. Перевстановіть File Toolkit (imageio-ffmpeg)."
        ) from exc
    try:
        exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:
        raise FfmpegMissingError(
            "Не знайдено ffmpeg. Перевстановіть File Toolkit (imageio-ffmpeg)."
        ) from exc
    if not exe or not Path(exe).is_file():
        raise FfmpegMissingError(
            "Не знайдено ffmpeg. Перевстановіть File Toolkit (imageio-ffmpeg)."
        )
    _FFMPEG_EXE = str(exe)
    return _FFMPEG_EXE


_FFMPEG_EXE: str | None = None


def _popen(args: list[str], **kwargs) -> subprocess.Popen:
    """Обгортка над Popen — точка підміни процесу в тестах."""
    return subprocess.Popen(args, **kwargs)


def _windows_startup_kwargs() -> dict:
    """Не показувати чорне консольне вікно на Windows."""
    if os.name != "nt":
        return {}
    kwargs: dict = {}
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if creationflags:
        kwargs["creationflags"] = creationflags
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    kwargs["startupinfo"] = startupinfo
    return kwargs


def _path_key(path: Path) -> str:
    """Ключ для порівняння шляхів без урахування регістру (Windows)."""
    return os.path.normcase(os.path.abspath(str(path)))


def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _parse_timestamp(value: str) -> float | None:
    match = _TIMESTAMP_RE.match(value.strip())
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _parse_media_info(text: str) -> MediaInfo:
    """Розбирає вивід `ffmpeg -i`, де ffmpeg пише інформацію в stderr."""
    duration = None
    match = _DURATION_RE.search(text)
    if match:
        hours, minutes, seconds = match.groups()
        duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    has_video = False
    has_audio = False
    width: int | None = None
    height: int | None = None

    for line in text.splitlines():
        if "Stream #" not in line:
            continue
        if "Video:" in line and "(attached pic)" not in line:
            has_video = True
            size = _VIDEO_SIZE_RE.search(line)
            if size and width is None:
                width, height = int(size.group(1)), int(size.group(2))
        elif "Audio:" in line:
            has_audio = True

    if not has_video and not has_audio:
        raise CorruptedVideoError("Файл пошкоджений або не є відео")
    return MediaInfo(
        duration=duration,
        width=width,
        height=height,
        has_video=has_video,
        has_audio=has_audio,
    )


def probe_media(path: Path) -> MediaInfo:
    """Читає тривалість і доріжки через `ffmpeg -i` (без ffprobe)."""
    path = Path(path)
    if not path.is_file():
        raise SourceMissingError(f"Файл не знайдено: {path}")

    exe = _get_ffmpeg_exe()
    args = [exe, "-hide_banner", "-nostdin", "-i", str(path)]
    try:
        process = _popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_windows_startup_kwargs(),
        )
    except FileNotFoundError as exc:
        raise FfmpegMissingError(
            "Не знайдено ffmpeg. Перевстановіть File Toolkit (imageio-ffmpeg)."
        ) from exc
    except PermissionError as exc:
        raise DestinationBusyError("Файл зайнятий іншою програмою") from exc
    except OSError as exc:
        raise VideoConvertError(f"Не вдалося запустити ffmpeg: {exc}") from exc

    try:
        try:
            stdout, stderr = process.communicate(timeout=PROBE_TIMEOUT)
        except subprocess.TimeoutExpired as exc:
            _stop_process(process)
            raise CorruptedVideoError(
                "Не вдалося прочитати відео: ffmpeg не відповів"
            ) from exc
    finally:
        if process.poll() is None:
            _stop_process(process)

    text = f"{stderr or ''}\n{stdout or ''}"
    lowered = text.lower()
    if "no such file or directory" in lowered:
        raise SourceMissingError(f"Файл не знайдено: {path}")
    if "permission denied" in lowered or "access is denied" in lowered:
        raise DestinationBusyError("Файл зайнятий іншою програмою")
    return _parse_media_info(text)


def build_command(
    source: Path,
    output: Path,
    options: VideoOptions,
    info: MediaInfo | None = None,
) -> list[str]:
    """Складає argv для ffmpeg. Окремо винесено для тестів."""
    exe = _get_ffmpeg_exe()
    target = options.target
    args = [exe, "-hide_banner", "-nostdin", "-y", "-i", str(source)]

    if target in AUDIO_OUTPUT_FORMATS:
        args += ["-map", "0:a:0", "-vn"]
    elif target is not OutputFormat.GIF:
        # Для GIF фільтр сам дає єдиний відеовихід, тому мапимо його нижче.
        args += ["-map", "0:v:0", "-map", "0:a:0?", "-sn", "-dn"]

    args += ["-progress", "pipe:1", "-nostats", "-loglevel", "error"]

    if target in (OutputFormat.MP4, OutputFormat.MKV):
        args += _x264_args(options)
        if options.no_audio:
            args += ["-an"]
        else:
            args += [
                "-c:a",
                "aac",
                "-b:a",
                f"{_VIDEO_AUDIO_KBPS[options.quality]}k",
            ]
        if target is OutputFormat.MP4:
            args += ["-movflags", "+faststart"]
        args += _video_filter_args(info, options)

    elif target is OutputFormat.WEBM:
        args += [
            "-c:v",
            "libvpx-vp9",
            "-crf",
            str(_crf_for(options, target)),
            "-b:v",
            "0",
            "-row-mt",
            "1",
            "-cpu-used",
            "2",
        ]
        if options.no_audio:
            args += ["-an"]
        else:
            args += [
                "-c:a",
                "libopus",
                "-b:a",
                f"{_VIDEO_AUDIO_KBPS[options.quality]}k",
            ]
        args += _video_filter_args(info, options)

    elif target is OutputFormat.GIF:
        args += [
            "-filter_complex",
            _gif_filter(info, options),
            "-map",
            "[out]",
            "-loop",
            "0",
            "-an",
        ]

    elif target is OutputFormat.MP3:
        args += [
            "-c:a",
            "libmp3lame",
            "-b:a",
            f"{_MP3_KBPS[options.quality]}k",
        ]

    elif target is OutputFormat.WAV:
        args += ["-c:a", "pcm_s16le"]

    args += ["-f", _MUXERS[target], str(output)]
    return args


def convert_video(
    source: Path,
    destination: Path,
    options: VideoOptions,
    *,
    on_fraction: FractionCallback | None = None,
    should_cancel: CancelCallback | None = None,
) -> VideoConversionResult:
    """Конвертує один файл. Помилки — підкласи VideoConvertError."""
    source = Path(source)
    destination = Path(destination)

    if not source.is_file():
        raise SourceMissingError(f"Файл не знайдено: {source}")
    if not is_supported_video(source):
        suffix = source.suffix.lower() or "без розширення"
        raise UnsupportedVideoFormatError(
            f"Формат не підтримується: {suffix}. "
            "Підтримуються: MP4, MKV, AVI, MOV, WebM, FLV, WMV"
        )
    if _path_key(source) == _path_key(destination):
        raise VideoConvertError(
            "Джерело та призначення збігаються — оригінал не перезаписуємо"
        )
    if should_cancel is not None and should_cancel():
        raise ConversionCancelled("Скасовано")

    source_size = _safe_size(source)
    info = probe_media(source)

    if options.target in AUDIO_OUTPUT_FORMATS:
        if not info.has_audio:
            raise NoAudioStreamError("У цьому файлі немає звукової доріжки")
    elif not info.has_video:
        raise NoVideoStreamError("У цьому файлі немає відеодоріжки")

    _check_free_space(destination.parent, source_size, options.target)

    temp_path = _make_temp(destination)
    try:
        command = build_command(source, temp_path, options, info)
        warning = ""
        if (
            options.target in VIDEO_OUTPUT_FORMATS
            and options.target is not OutputFormat.GIF
            and not options.no_audio
            and not info.has_audio
        ):
            warning = "У відео немає звуку — результат без звукової доріжки"
        _run_ffmpeg(
            command,
            info.duration,
            options.target,
            on_fraction,
            should_cancel,
        )
        if not temp_path.exists() or temp_path.stat().st_size == 0:
            raise VideoConvertError("ffmpeg не створив файл результату")
        try:
            os.replace(temp_path, destination)
        except PermissionError as exc:
            raise DestinationBusyError("Файл відкритий в іншій програмі") from exc
        except OSError as exc:
            if getattr(exc, "winerror", None) == 112 or exc.errno == 28:
                raise NoSpaceError("Недостатньо місця на диску") from exc
            raise VideoConvertError(f"Не вдалося записати файл: {exc}") from exc
        temp_path = None
    finally:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass

    result_size = destination.stat().st_size if destination.exists() else 0
    return VideoConversionResult(
        source=source,
        destination=destination,
        ok=True,
        message=warning,
        source_size=source_size,
        result_size=result_size,
        duration=info.duration,
    )


def convert_video_batch(
    sources: Sequence[Path],
    options: VideoOptions,
    output_dir: Path | None = None,
    *,
    on_progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
) -> list[VideoConversionResult]:
    """Конвертує пакет файлів, не зупиняючись на помилках окремих файлів."""
    sources = [Path(source) for source in sources]
    total = len(sources)
    results: list[VideoConversionResult] = []
    taken: list[Path] = []

    for index, source in enumerate(sources):
        if should_cancel is not None and should_cancel():
            break
        if on_progress is not None:
            on_progress(index, total, source, 0.0)
        try:
            destination = build_destination(source, output_dir, options, taken)
            taken.append(destination)

            def report_fraction(value: float | None, i: int = index, s: Path = source) -> None:
                if on_progress is not None:
                    on_progress(i, total, s, value)

            results.append(
                convert_video(
                    source,
                    destination,
                    options,
                    on_fraction=report_fraction,
                    should_cancel=should_cancel,
                )
            )
        except ConversionCancelled:
            break
        except VideoConvertError as exc:
            results.append(
                VideoConversionResult(
                    source=source,
                    destination=None,
                    ok=False,
                    message=str(exc),
                    source_size=_safe_size(source),
                )
            )

    if on_progress is not None:
        on_progress(len(results), total, None, None)
    return results


# --- внутрішні кроки --------------------------------------------------------


def _x264_args(options: VideoOptions) -> list[str]:
    return [
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        str(_crf_for(options, options.target)),
        "-pix_fmt",
        "yuv420p",
    ]


def _crf_for(options: VideoOptions, target: OutputFormat) -> int:
    if options.crf is not None:
        value = options.crf
        if target in (OutputFormat.MP4, OutputFormat.MKV):
            value = min(value, 51)
        return value
    if target is OutputFormat.WEBM:
        return _VP9_CRF[options.quality]
    return _X264_CRF[options.quality]


def _scale_needed(
    info: MediaInfo | None, max_height: MaxHeight
) -> bool:
    limit = max_height.value
    if not limit:
        return False
    if info is None or info.height is None:
        return True
    return info.height > limit


def _video_filter_args(
    info: MediaInfo | None, options: VideoOptions
) -> list[str]:
    if not _scale_needed(info, options.max_height):
        return []
    height = options.max_height.value
    return ["-vf", f"scale=-2:min(ih\\,{height})"]


def _gif_filter(info: MediaInfo | None, options: VideoOptions) -> str:
    fps = _GIF_FPS[options.quality]
    colors = _GIF_COLORS[options.quality]
    filters = [f"fps={fps}"]
    if _scale_needed(info, options.max_height):
        filters.append(
            f"scale=-2:min(ih\\,{options.max_height.value}):flags=lanczos"
        )
    filters.append(
        "split[s0][s1];[s0]palettegen="
        f"max_colors={colors}:stats_mode=diff[p];"
        "[s1][p]paletteuse=dither=bayer:bayer_scale=3[out]"
    )
    return ",".join(filters)


def _check_free_space(
    directory: Path, source_size: int, target: OutputFormat
) -> None:
    factor = GIF_SPACE_FACTOR if target is OutputFormat.GIF else SPACE_FACTOR
    needed = int(source_size * factor) + SPACE_RESERVE_BYTES
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


def _make_temp(destination: Path) -> Path:
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DestinationBusyError("Папка призначення недоступна") from exc

    try:
        handle, temp_name = tempfile.mkstemp(
            prefix=".file-toolkit-",
            suffix=f".tmp{destination.suffix}",
            dir=destination.parent,
        )
        os.close(handle)
    except PermissionError as exc:
        raise DestinationBusyError("Папка призначення недоступна") from exc
    except OSError as exc:
        if getattr(exc, "winerror", None) == 112 or exc.errno == 28:
            raise NoSpaceError("Недостатньо місця на диску") from exc
        raise VideoConvertError(f"Не вдалося створити тимчасовий файл: {exc}") from exc
    return Path(temp_name)


def _run_ffmpeg(
    command: list[str],
    duration: float | None,
    target: OutputFormat,
    on_fraction: FractionCallback | None,
    should_cancel: CancelCallback | None,
) -> None:
    try:
        process = _popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            **_windows_startup_kwargs(),
        )
    except FileNotFoundError as exc:
        raise FfmpegMissingError(
            "Не знайдено ffmpeg. Перевстановіть File Toolkit (imageio-ffmpeg)."
        ) from exc
    except PermissionError as exc:
        raise DestinationBusyError("Файл зайнятий іншою програмою") from exc
    except OSError as exc:
        raise VideoConvertError(f"Не вдалося запустити ffmpeg: {exc}") from exc

    tail: deque[str] = deque(maxlen=STDERR_TAIL_LINES)
    reader = threading.Thread(
        target=_drain_stream, args=(process.stderr, tail), daemon=True
    )
    reader.start()

    try:
        for line in process.stdout:
            if should_cancel is not None and should_cancel():
                _stop_process(process)
                raise ConversionCancelled("Скасовано")
            _handle_progress_line(line, duration, on_fraction)
        returncode = process.wait()
        reader.join(timeout=2.0)

        if should_cancel is not None and should_cancel():
            raise ConversionCancelled("Скасовано")
        if returncode != 0:
            raise _error_from_stderr("".join(tail), target)
        if on_fraction is not None:
            on_fraction(1.0)
    except ConversionCancelled:
        if process.poll() is None:
            _stop_process(process)
        raise
    except VideoConvertError:
        if process.poll() is None:
            _stop_process(process)
        raise
    except OSError as exc:
        if process.poll() is None:
            _stop_process(process)
        raise VideoConvertError(f"Не вдалося конвертувати відео: {exc}") from exc
    finally:
        if process.poll() is None:
            _stop_process(process)
        _close_stream(process.stdout)
        _close_stream(process.stderr)


def _drain_stream(stream, tail: deque[str]) -> None:
    try:
        for line in stream:
            tail.append(line)
    except (OSError, ValueError):
        pass


def _close_stream(stream) -> None:
    if stream is None:
        return
    close = getattr(stream, "close", None)
    if close is None:
        return
    try:
        close()
    except (OSError, ValueError):
        pass


def _stop_process(process) -> None:
    try:
        process.terminate()
    except OSError:
        pass
    try:
        process.wait(timeout=TERMINATE_TIMEOUT)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        process.kill()
    except OSError:
        pass
    try:
        process.wait(timeout=TERMINATE_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError):
        pass


def _handle_progress_line(
    line: str,
    duration: float | None,
    on_fraction: FractionCallback | None,
) -> None:
    if on_fraction is None or "=" not in line:
        return
    key, _, value = line.partition("=")
    key = key.strip()
    value = value.strip()

    if key == "progress" and value == "end":
        on_fraction(1.0)
        return

    seconds: float | None = None
    if key in ("out_time_us", "out_time_ms"):
        try:
            seconds = int(value) / 1_000_000
        except ValueError:
            seconds = None
    elif key == "out_time":
        seconds = _parse_timestamp(value)

    if seconds is None or duration is None or duration <= 0:
        return
    on_fraction(max(0.0, min(0.999, seconds / duration)))


def _error_from_stderr(text: str, target: OutputFormat) -> VideoConvertError:
    lowered = text.lower()
    if "no space left" in lowered or "not enough space" in lowered:
        return NoSpaceError("Недостатньо місця на диску")
    if "permission denied" in lowered or "access is denied" in lowered:
        return DestinationBusyError("Файл зайнятий іншою програмою")
    if "does not contain any stream" in lowered:
        if target in AUDIO_OUTPUT_FORMATS:
            return NoAudioStreamError("У цьому файлі немає звукової доріжки")
        return NoVideoStreamError("У цьому файлі немає відеодоріжки")
    damaged = (
        "invalid data found",
        "moov atom not found",
        "could not find codec parameters",
        "error opening input",
        "end of file",
    )
    if any(marker in lowered for marker in damaged):
        return CorruptedVideoError("Файл пошкоджений або не є відео")
    if "unknown encoder" in lowered:
        return VideoConvertError("ffmpeg не підтримує потрібний кодек")

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    detail = lines[-1] if lines else "невідома помилка ffmpeg"
    if len(detail) > MAX_ERROR_TEXT:
        detail = detail[:MAX_ERROR_TEXT] + "…"
    return VideoConvertError(f"Не вдалося конвертувати відео: {detail}")
