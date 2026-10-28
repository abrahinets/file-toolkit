"""Логіка роботи з архівами.

Модуль навмисно не залежить від інтерфейсу, щоб його можна було
тестувати окремо. Усі повідомлення про помилки — українською.
"""

from __future__ import annotations

import io
import os
import shutil
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

try:
    import py7zr
except Exception:  # pragma: no cover - необов'язкова залежність
    py7zr = None


class ArchiveError(Exception):
    """Базовий клас помилок архівування."""


class ArchiveValidationError(ArchiveError):
    """Некоректні налаштування чи шляхи."""


class ArchiveIOError(ArchiveError):
    """Помилки читання/запису чи недостатнього місця."""


@dataclass(slots=True)
class ZipOptions:
    """Налаштування створення ZIP-архіву."""

    compression_level: int = 6

    def __post_init__(self) -> None:
        if not 0 <= self.compression_level <= 9:
            raise ValueError("Рівень стиснення має бути від 0 до 9")


@dataclass(slots=True)
class ArchiveResult:
    """Результат архівування."""

    source: Path | None
    destination: Path | None
    ok: bool
    message: str = ""


ProgressCallback = Callable[[int, int, Path | None], None]
CancelCallback = Callable[[], bool]

SPACE_RESERVE_BYTES = 1_000_000


def _path_key(path: Path) -> str:
    """Ключ для порівняння шляхів без урахування регістру (Windows)."""
    return os.path.normcase(str(path))


def is_supported_archive_source(path: Path) -> bool:
    """Чи можна додати шлях до архіву (файл або директорія)."""
    try:
        p = Path(path)
    except Exception:
        return False
    return p.exists()


def default_zip_name(sources: list[Path]) -> str:
    """Пропоноване ім'я ZIP-архіву."""
    if not sources:
        return "archive.zip"
    if len(sources) == 1:
        p = Path(sources[0])
        if p.is_dir():
            return f"{p.name}.zip"
        return f"{p.stem}.zip"
    return "archive.zip"


def estimate_size_bytes(sources: list[Path]) -> int:
    """Оцінка розміру вхідних даних (сума розмірів файлів рекурсивно)."""
    total = 0
    for src in sources:
        p = Path(src)
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                continue
        elif p.is_dir():
            for root, _dirs, files in os.walk(p, followlinks=False):
                for name in files:
                    fp = Path(root) / name
                    try:
                        if fp.is_symlink():
                            continue
                        total += fp.stat().st_size
                    except OSError:
                        continue
    return total


def _ensure_free_space(dest_dir: Path, required_bytes: int) -> None:
    """Перевірка вільного місця на диску."""
    try:
        usage = shutil.disk_usage(dest_dir)
    except OSError as exc:
        raise ArchiveIOError(f"Не вдалося перевірити вільне місце: {exc}") from exc
    needed = required_bytes + SPACE_RESERVE_BYTES
    if usage.free < needed:
        raise ArchiveIOError("На диску недостатньо місця")


def _unique_zip_name(dest_dir: Path, base_name: str) -> Path:
    """Унікалізує ім'я ZIP-файлу через _1, _2, не перезаписуючи існуючі."""
    dest_dir = Path(dest_dir)
    if not base_name.lower().endswith(".zip"):
        base_name = f"{base_name}.zip"
    stem = Path(base_name).stem
    suffix = ".zip"
    candidate = dest_dir / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    index = 1
    while True:
        candidate = dest_dir / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _is_zip_in_dir(zip_path: Path, target_dir: Path) -> bool:
    try:
        return _path_key(zip_path.resolve().parent) == _path_key(target_dir.resolve())
    except Exception:
        return _path_key(zip_path.parent) == _path_key(target_dir)


def _collect_files(
    sources: list[Path],
    dest_zip_path: Path | None = None,
) -> tuple[list[tuple[Path, str]], list[tuple[Path, str]]]:
    """Збирає файли для архівування.

    Повертає (entries, skipped_empty_or_errors).
    entries: (absolute_path, arcname_inside_zip)
    Додає порожні папки як записи (arcname із '/').
    Виключає архів (і .tmp) що потрапляє сам у себе, якщо зберігається в ту ж папку.
    Конфлікти однакових імен файлів з різних папок вирішує суфіксом _1, _2.
    """
    dest_zip_path = Path(dest_zip_path) if dest_zip_path is not None else None
    dest_dir = dest_zip_path.parent if dest_zip_path is not None else None

    entries: list[tuple[Path, str]] = []
    skipped: list[tuple[Path, str]] = []

    # Для унікалізації arcname файлів
    used_arc: set[str] = set()
    # Для унікалізації порожніх папок
    used_dir_arc: set[str] = set()

    def _get_unique_file_arcname(base_arc: str) -> str:
        # base_arc без слешу
        if base_arc not in used_arc:
            used_arc.add(base_arc)
            return base_arc
        p = Path(base_arc)
        stem = p.stem
        ext = p.suffix
        index = 1
        while True:
            candidate = f"{stem}_{index}{ext}" if ext else f"{stem}_{index}"
            if candidate not in used_arc:
                used_arc.add(candidate)
                return candidate
            index += 1

    def _get_unique_dir_arcname(base_arc: str) -> str:
        # base_arc завершується /
        base_clean = base_arc.rstrip("/")
        if base_arc not in used_dir_arc:
            used_dir_arc.add(base_arc)
            return base_arc
        index = 1
        while True:
            candidate = f"{base_clean}_{index}/"
            if candidate not in used_dir_arc:
                used_dir_arc.add(candidate)
                return candidate
            index += 1

    for src in sources:
        p = Path(src)
        if not p.exists():
            skipped.append((p, "Шлях не існує"))
            continue
        # Перевірка чи це архів, що зберігається в ту ж папку - виключаємо
        if dest_zip_path is not None and dest_dir is not None:
            try:
                if p.is_file():
                    if _is_zip_in_dir(p, dest_dir):
                        name_l = p.name.lower()
                        if name_l == dest_zip_path.name.lower() or name_l.endswith(".zip") or name_l.endswith(".tmp"):
                            continue  # пропускаємо, не додаємо до архіву
                elif p.is_dir():
                    pass
            except Exception:
                pass

        if p.is_file():
            # Пропускаємо, якщо це архів у тій самій папці
            if dest_zip_path is not None and dest_dir is not None:
                try:
                    if _is_zip_in_dir(p, dest_dir):
                        name_l = p.name.lower()
                        if name_l.endswith(".zip") or name_l.endswith(".tmp"):
                            continue
                except Exception:
                    pass
            arcname = _get_unique_file_arcname(p.name)
            entries.append((p, arcname))
        elif p.is_dir():
            # Додаємо порожні папки та рекурсивно файли
            # Зберігаємо ім'я верхньої папки як корінь
            dir_root_name = p.name
            # Перевіряємо чи взагалі є щось
            try:
                has_anything = False
                for root, dirs, files in os.walk(p, followlinks=False):
                    # перевіряємо файли
                    for fname in files:
                        fpath = Path(root) / fname
                        try:
                            if fpath.is_symlink():
                                continue
                            if fpath.is_file():
                                has_anything = True
                                break
                        except Exception:
                            continue
                    if has_anything:
                        break
                    # якщо є підпапки - теж є вміст потенційно
                    if dirs:
                        has_anything = True
                        break
            except Exception:
                has_anything = False

            if not has_anything:
                # перевіряємо чи дійсно порожня
                try:
                    items = os.listdir(p)
                except Exception:
                    items = []
                if not items:
                    arcname_dir = _get_unique_dir_arcname(f"{dir_root_name}/")
                    entries.append((p, arcname_dir))
                    continue

            # Обходимо рекурсивно
            for root, dirs, files in os.walk(p, followlinks=False):
                root_path = Path(root)
                # Додаємо порожні підпапки
                for d in list(dirs):
                    dpath = root_path / d
                    try:
                        if dpath.is_symlink():
                            dirs.remove(d)
                            continue
                    except Exception:
                        pass
                    try:
                        entries_list = os.listdir(dpath)
                        if not entries_list:
                            rel = dpath.relative_to(p)
                            arc_dir = f"{dir_root_name}/{rel.as_posix()}/"
                            entries.append((dpath, _get_unique_dir_arcname(arc_dir)))
                            try:
                                dirs.remove(d)
                            except ValueError:
                                pass
                            continue
                    except Exception:
                        continue
                # Файли
                for fname in files:
                    fpath = root_path / fname
                    try:
                        if fpath.is_symlink():
                            continue
                    except Exception:
                        pass
                    try:
                        if not fpath.is_file():
                            continue
                    except Exception:
                        continue
                    # Виключаємо архів якщо в тій же папці
                    if dest_zip_path is not None and dest_dir is not None:
                        try:
                            if _is_zip_in_dir(fpath, dest_dir):
                                if _path_key(fpath) == _path_key(dest_zip_path):
                                    continue
                                if fpath.name.lower().endswith(".tmp"):
                                    continue
                        except Exception:
                            pass
                    try:
                        rel = fpath.relative_to(p)
                        base_arc = f"{dir_root_name}/{rel.as_posix()}"
                    except Exception:
                        base_arc = f"{dir_root_name}/{fname}"
                    arcname_f = _get_unique_file_arcname(base_arc)
                    entries.append((fpath, arcname_f))
        else:
            skipped.append((p, "Непідтримуваний тип"))

    return entries, skipped


def create_zip(
    sources: list[Path],
    dest_dir: Path,
    zip_name: str,
    options: ZipOptions | None = None,
    on_progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
) -> list[ArchiveResult]:
    """Створює ZIP-архів з обраних файлів і папок."""
    if options is None:
        options = ZipOptions()

    sources = [Path(s) for s in sources]
    dest_dir = Path(dest_dir)

    if not sources:
        raise ArchiveValidationError("Список файлів для архівування порожній")
    for s in sources:
        if not s.exists():
            raise ArchiveValidationError(f"Шлях не існує: {s}")
    if not dest_dir.exists() or not dest_dir.is_dir():
        raise ArchiveValidationError("Папка призначення не існує")

    # Унікалізуємо ім'я ZIP через _1, _2
    final_path = _unique_zip_name(dest_dir, zip_name)
    tmp_path = final_path.with_suffix(final_path.suffix + ".tmp")

    entries, skipped_collect = _collect_files(sources, final_path)

    # Фільтруємо записи - виключаємо архів
    filtered_entries: list[tuple[Path, str]] = []
    for spath, arc in entries:
        try:
            if spath.is_file():
                if _is_zip_in_dir(spath, dest_dir):
                    if _path_key(spath) == _path_key(final_path):
                        continue
                    if spath.name.lower().endswith(".tmp"):
                        continue
        except Exception:
            pass
        filtered_entries.append((spath, arc))

    if not filtered_entries:
        raise ArchiveValidationError("Немає файлів для архівування")

    # Оцінка місця
    try:
        required = estimate_size_bytes([s for s, _ in filtered_entries if Path(s).is_file()])
        _ensure_free_space(dest_dir, required)
    except ArchiveIOError:
        raise
    except Exception:
        pass  # не блокуємо через помилку оцінки

    results: list[ArchiveResult] = []
    # Додаємо пропущені при зборі
    for sp, msg in skipped_collect:
        results.append(ArchiveResult(source=sp, destination=None, ok=False, message=msg))

    total = len(filtered_entries)
    done = 0

    compression = zipfile.ZIP_STORED if options.compression_level == 0 else zipfile.ZIP_DEFLATED
    compresslevel = None if compression == zipfile.ZIP_STORED else options.compression_level

    try:
        if compression == zipfile.ZIP_STORED:
            zf = zipfile.ZipFile(tmp_path, "w", compression=compression)
        else:
            zf = zipfile.ZipFile(tmp_path, "w", compression=compression, compresslevel=compresslevel)
    except Exception as exc:
        raise ArchiveIOError(f"Не вдалося створити архів: {exc}") from exc

    try:
        for spath, arcname in filtered_entries:
            if should_cancel and should_cancel():
                break
            if on_progress:
                try:
                    on_progress(done, total, Path(spath))
                except Exception:
                    pass
            spath_p = Path(spath)
            try:
                if arcname.endswith("/"):
                    # Порожня папка
                    try:
                        zf.writestr(zipfile.ZipInfo(arcname), "")
                    except Exception as exc:
                        results.append(
                            ArchiveResult(source=spath_p, destination=None, ok=False, message=str(exc))
                        )
                    done += 1
                    continue
                if not spath_p.exists() or not spath_p.is_file():
                    results.append(
                        ArchiveResult(
                            source=spath_p,
                            destination=None,
                            ok=False,
                            message="Файл не знайдено або недоступний",
                        )
                    )
                    done += 1
                    continue
                try:
                    zf.write(spath_p, arcname)
                    results.append(ArchiveResult(source=spath_p, destination=None, ok=True, message=""))
                except Exception as exc:
                    results.append(
                        ArchiveResult(source=spath_p, destination=None, ok=False, message=str(exc))
                    )
            finally:
                done += 1
        if should_cancel and should_cancel():
            # Скасовано - видаляємо тимчасовий
            try:
                zf.close()
            except Exception:
                pass
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass
            return results
        try:
            zf.close()
        except Exception as exc:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass
            raise ArchiveIOError(f"Помилка запису архіву: {exc}") from exc
        try:
            os.replace(tmp_path, final_path)
        except Exception as exc:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass
            raise ArchiveIOError(f"Не вдалося зберегти архів: {exc}") from exc
        # Додаємо фінальний успішний результат якщо немає явного
        if not any(r.destination == final_path and r.ok for r in results):
            results.append(ArchiveResult(source=None, destination=final_path, ok=True, message=""))
        else:
            # оновлюємо destination для успішних
            for r in results:
                if r.ok and r.destination is None and r.source is not None:
                    pass  # лишаємо як є
        # Встановлюємо destination для успішних записів файлів
        updated = []
        for r in results:
            if r.ok and r.source is not None and r.destination is None:
                updated.append(ArchiveResult(source=r.source, destination=final_path, ok=True, message=r.message))
            elif r.ok and r.source is None and r.destination is None:
                updated.append(ArchiveResult(source=None, destination=final_path, ok=True, message=""))
            else:
                updated.append(r)
        return updated
    except ArchiveError:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
        raise
    except Exception as exc:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass
        raise ArchiveIOError(f"Неочікувана помилка: {exc}") from exc



class ExtractError(Exception):
    """Базовий клас помилок розпаковки."""


class ExtractValidationError(ExtractError):
    """Некоректний архів/шляхи/формат."""


class ExtractIOError(ExtractError):
    """Помилки читання/запису чи недостатнього місця."""


@dataclass(slots=True)
class ZipOptions:
    """Налаштування створення ZIP-архіву."""

    compression_level: int = 6

    def __post_init__(self) -> None:
        if not 0 <= self.compression_level <= 9:
            raise ValueError("Рівень стиснення має бути від 0 до 9")


@dataclass(slots=True)
class ArchiveResult:
    """Результат архівування."""

    source: Path | None
    destination: Path | None
    ok: bool
    message: str = ""


@dataclass(slots=True)
class ExtractEntry:
    """Елемент вмісту архіву."""

    name: str
    is_dir: bool
    size: int = 0
    compressed_size: int = 0


@dataclass(slots=True)
class ExtractOptions:
    """Налаштування розпаковки."""

    overwrite: bool = False


@dataclass(slots=True)
class ExtractResult:
    """Результат розпаковки."""

    entry: ExtractEntry | None
    source: Path | None
    destination: Path | None
    ok: bool
    message: str = ""


ProgressCallback = Callable[[int, int, Path | None], None]
CancelCallback = Callable[[], bool]

SPACE_RESERVE_BYTES = 1_000_000
MAX_EXTRACT_TOTAL_BYTES = 10 * 1024 * 1024 * 1024  # 10 ГБ
MAX_EXTRACT_FILES = 100000


SUPPORTED_EXTRACT_EXTS = {
    ".zip",
    ".tar",
    ".tgz",
    ".tar.gz",
    ".tbz2",
    ".tar.bz2",
    ".txz",
    ".tar.xz",
    ".7z",
}


def _path_key(path: Path) -> str:
    """Ключ для порівняння шляхів без урахування регістру (Windows)."""
    return os.path.normcase(str(path))


def is_supported_archive_source(path: Path) -> bool:
    """Чи можна додати шлях до архіву (файл або директорія)."""
    try:
        p = Path(path)
    except Exception:
        return False
    return p.exists()


def default_zip_name(sources: list[Path]) -> str:
    """Пропоноване ім'я ZIP-архіву."""
    if not sources:
        return "archive.zip"
    if len(sources) == 1:
        p = Path(sources[0])
        if p.is_dir():
            return f"{p.name}.zip"
        return f"{p.stem}.zip"
    return "archive.zip"


def estimate_size_bytes(sources: list[Path]) -> int:
    """Оцінка розміру вхідних даних (сума розмірів файлів рекурсивно)."""
    total = 0
    for src in sources:
        p = Path(src)
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                continue
        elif p.is_dir():
            for root, _dirs, files in os.walk(p, followlinks=False):
                for name in files:
                    fp = Path(root) / name
                    try:
                        if fp.is_symlink():
                            continue
                        total += fp.stat().st_size
                    except OSError:
                        continue
    return total


def _ensure_free_space(dest_dir: Path, required_bytes: int) -> None:
    """Перевірка вільного місця на диску."""
    try:
        usage = shutil.disk_usage(dest_dir)
    except OSError as exc:
        raise ArchiveIOError(f"Не вдалося перевірити вільне місце: {exc}") from exc
    needed = required_bytes + SPACE_RESERVE_BYTES
    if usage.free < needed:
        raise ArchiveIOError("На диску недостатньо місця")


def _unique_zip_name(dest_dir: Path, base_name: str) -> Path:
    """Унікалізує ім'я ZIP-файлу через _1, _2, не перезаписуючи існуючі."""
    dest_dir = Path(dest_dir)
    if not base_name.lower().endswith(".zip"):
        base_name = f"{base_name}.zip"
    stem = Path(base_name).stem
    suffix = ".zip"
    candidate = dest_dir / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate
    index = 1
    while True:
        candidate = dest_dir / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _is_zip_in_dir(zip_path: Path, target_dir: Path) -> bool:
    try:
        return _path_key(zip_path.resolve().parent) == _path_key(target_dir.resolve())
    except Exception:
        return _path_key(zip_path.parent) == _path_key(target_dir)


def _is_under_directory(base: Path, target: Path) -> bool:
    try:
        base_res = base.resolve()
        target_res = target.resolve()
        return str(target_res).startswith(str(base_res) + os.sep) or target_res == base_res
    except Exception:
        return True


def _safe_extract_path(dest_dir: Path, member_name: str) -> Path | None:
    """Безпечний шлях для розпаковки (захист від path traversal)."""
    if not member_name:
        return None
    # Забороняємо абсолютні шляхи
    if os.path.isabs(member_name):
        return None
    # Нормалізуємо
    norm = member_name.replace("\\", "/")
    parts = norm.split("/")
    safe_parts = []
    for p in parts:
        if p in ("", "."):
            continue
        if p == "..":
            return None
        safe_parts.append(p)
    if not safe_parts:
        return None
    rel = Path(*safe_parts)
    target = (dest_dir / rel).resolve()
    base_res = dest_dir.resolve()
    try:
        if str(target).startswith(str(base_res) + os.sep) or target == base_res:
            return target
    except Exception:
        pass
    return None


def _unique_path(dest_dir: Path, path: Path) -> Path:
    """Унікалізує шлях через _1, _2 якщо існує."""
    path = Path(path)
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    index = 1
    while True:
        candidate = parent / f"{stem}_{index}{suffix}" if suffix else parent / f"{stem}_{index}"
        if not candidate.exists():
            return candidate
        index += 1


def is_supported_extract_archive(path: Path) -> bool:
    try:
        p = Path(path)
    except Exception:
        return False
    if not p.exists() or not p.is_file():
        return False
    name = p.name.lower()
    if name.endswith((".tar.gz", ".tar.bz2", ".tar.xz")):
        return True
    return p.suffix.lower() in SUPPORTED_EXTRACT_EXTS or name.endswith((".tgz", ".tbz2", ".txz"))


def detect_archive_format(path: Path) -> str:
    p = Path(path)
    name = p.name.lower()
    if name.endswith(".7z") or p.suffix.lower() == ".7z":
        return "7z"
    if name.endswith((".tar.gz", ".tgz")) or p.suffix.lower() == ".tgz":
        return "tar.gz"
    if name.endswith((".tar.bz2", ".tbz2")):
        return "tar.bz2"
    if name.endswith((".tar.xz", ".txz")):
        return "tar.xz"
    if name.endswith(".tar") or p.suffix.lower() == ".tar":
        return "tar"
    if p.suffix.lower() == ".zip":
        return "zip"
    raise ExtractValidationError("Непідтримуваний формат архіву")


def _unique_extract_dir(base_dir: Path, name: str) -> Path:
    candidate = base_dir / name
    if not candidate.exists():
        return candidate
    index = 1
    while True:
        candidate = base_dir / f"{name}_{index}"
        if not candidate.exists():
            return candidate
        index += 1


def list_archive(path: Path) -> list[ExtractEntry]:
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise ExtractValidationError("Архів не знайдено")
    fmt = detect_archive_format(p)
    entries: list[ExtractEntry] = []
    try:
        if fmt == "zip":
            with zipfile.ZipFile(p, "r") as zf:
                for info in zf.infolist():
                    name = info.filename
                    if not name:
                        continue
                    # перевірка на захист
                    if os.path.isabs(name) or ".." in name.replace("\\", "/").split("/"):
                        continue
                    is_dir = name.endswith("/") or info.is_dir()
                    entries.append(
                        ExtractEntry(
                            name=name,
                            is_dir=is_dir,
                            size=info.file_size or 0,
                            compressed_size=info.compress_size or 0,
                        )
                    )
            return entries
        if fmt.startswith("tar"):
            mode = "r:*"
            try:
                with tarfile.open(p, mode, filter="data") as tf:
                    for member in tf.getmembers():
                        name = member.name
                        if not name:
                            continue
                        if os.path.isabs(name) or ".." in name.replace("\\", "/").split("/"):
                            continue
                        if member.issym() or member.islnk():
                            continue
                        is_dir = member.isdir() or name.endswith("/")
                        entries.append(
                            ExtractEntry(
                                name=name,
                                is_dir=is_dir,
                                size=member.size or 0,
                                compressed_size=0,
                            )
                        )
            except TypeError:
                with tarfile.open(p, "r:*") as tf:
                    for member in tf.getmembers():
                        name = member.name
                        if not name:
                            continue
                        if os.path.isabs(name) or ".." in name.replace("\\", "/").split("/"):
                            continue
                        if member.issym() or member.islnk():
                            continue
                        is_dir = member.isdir() or name.endswith("/")
                        entries.append(ExtractEntry(name=name, is_dir=is_dir, size=member.size or 0))
            return entries
        if fmt == "7z":
            if py7zr is None:
                raise ExtractValidationError("Для розпаковки 7z потрібен py7zr")
            try:
                with py7zr.SevenZipFile(p, mode="r") as z:
                    for f in z.list():
                        name = f.filename
                        if not name:
                            continue
                        if os.path.isabs(name) or ".." in name.replace("\\", "/").split("/"):
                            continue
                        # py7zr не показує симлінки простим способом - пропускаємо небезпечне
                        is_dir = name.endswith("/")
                        entries.append(ExtractEntry(name=name, is_dir=is_dir, size=getattr(f, "uncompressed", 0) or 0))
            except Exception as exc:
                if "password" in str(exc).lower():
                    raise ExtractValidationError("Архів захищений паролем, це не підтримується") from exc
                raise ExtractValidationError(f"Не вдалося прочитати архів: {exc}") from exc
            return entries
    except ExtractError:
        raise
    except Exception as exc:
        raise ExtractValidationError(f"Не вдалося прочитати архів: {exc}") from exc
    raise ExtractValidationError("Непідтримуваний формат архіву")


def extract_archive(
    source: Path,
    dest_dir: Path,
    options: ExtractOptions | None = None,
    on_progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
) -> list[ExtractResult]:
    if options is None:
        options = ExtractOptions()
    source = Path(source)
    dest_dir = Path(dest_dir)
    if not source.exists() or not source.is_file():
        raise ExtractValidationError("Архів не знайдено")
    if not is_supported_extract_archive(source):
        raise ExtractValidationError("Непідтримуваний формат архіву")
    fmt = detect_archive_format(source)
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Визначаємо цільову папку за замовчуванням - нова підпапка з ім'ям архіву
    target_root = _unique_extract_dir(dest_dir, source.stem)
    target_root.mkdir(parents=True, exist_ok=True)

    results: list[ExtractResult] = []
    skipped_links = 0

    try:
        if fmt == "zip":
            try:
                with zipfile.ZipFile(source, "r") as zf:
                    # перевірка на пароль
                    for info in zf.infolist():
                        try:
                            if info.flag_bits & 0x1:
                                raise ExtractValidationError("Архів захищений паролем, це не підтримується")
                        except ExtractError:
                            raise
                        except Exception:
                            pass
                    members = [m for m in zf.infolist() if m.filename]
                    total_files = 0
                    total_size = 0
                    for m in members:
                        name = m.filename
                        if os.path.isabs(name) or ".." in name.replace("\\", "/").split("/"):
                            continue
                        if name.endswith("/"):
                            continue
                        total_files += 1
                        total_size += m.file_size or 0
                    if total_files > MAX_EXTRACT_FILES:
                        raise ExtractValidationError("Архів містить забагато файлів (перевищено ліміт)")
                    if total_size > MAX_EXTRACT_TOTAL_BYTES:
                        raise ExtractValidationError("Архів занадто великий для розпаковки (перевищено ліміт)")
                    done = 0
                    for info in members:
                        if should_cancel and should_cancel():
                            break
                        name = info.filename
                        if os.path.isabs(name) or ".." in name.replace("\\", "/").split("/"):
                            results.append(
                                ExtractResult(entry=ExtractEntry(name=name, is_dir=False), source=source, destination=None, ok=False, message="Небезпечний шлях")
                            )
                            continue
                        if name.endswith("/") or info.is_dir():
                            safe_d = _safe_extract_path(target_root, name)
                            if safe_d is not None:
                                try:
                                    safe_d.mkdir(parents=True, exist_ok=True)
                                except Exception as exc:
                                    results.append(ExtractResult(entry=ExtractEntry(name=name, is_dir=True), source=source, destination=safe_d, ok=False, message=str(exc)))
                            if not (name.endswith("/") or info.is_dir()):
                                pass
                            done += 1
                            if on_progress:
                                try:
                                    on_progress(done, total_files, target_root / name)
                                except Exception:
                                    pass
                            continue
                        safe_p = _safe_extract_path(target_root, name)
                        if safe_p is None:
                            results.append(ExtractResult(entry=ExtractEntry(name=name, is_dir=False), source=source, destination=None, ok=False, message="Небезпечний шлях"))
                            done += 1
                            if on_progress:
                                try:
                                    on_progress(done, total_files, target_root / name)
                                except Exception:
                                    pass
                            continue
                        try:
                            safe_p.parent.mkdir(parents=True, exist_ok=True)
                        except Exception:
                            pass
                        out_path = safe_p
                        if out_path.exists() and not options.overwrite:
                            out_path = _unique_path(out_path.parent, out_path)
                        try:
                            with zf.open(info) as src_f, open(out_path, "wb") as dst_f:
                                shutil.copyfileobj(src_f, dst_f)
                            results.append(ExtractResult(entry=ExtractEntry(name=name, is_dir=False, size=info.file_size or 0), source=source, destination=out_path, ok=True, message=""))
                        except Exception as exc:
                            results.append(ExtractResult(entry=ExtractEntry(name=name, is_dir=False), source=source, destination=out_path, ok=False, message=str(exc)))
                        done += 1
                        if on_progress:
                            try:
                                on_progress(done, total_files, out_path)
                            except Exception:
                                pass
                    if should_cancel and should_cancel():
                        return results
                    return results
            except ExtractError:
                raise
            except RuntimeError as exc:
                if "password" in str(exc).lower():
                    raise ExtractValidationError("Архів захищений паролем, це не підтримується") from exc
                raise ExtractIOError(f"Помилка розпаковки: {exc}") from exc
            except Exception as exc:
                if "password" in str(exc).lower() or "encrypted" in str(exc).lower():
                    raise ExtractValidationError("Архів захищений паролем, це не підтримується") from exc
                raise ExtractIOError(f"Помилка розпаковки: {exc}") from exc

        if fmt.startswith("tar"):
            mode = "r:*"
            try:
                try:
                    tf = tarfile.open(source, mode, filter="data")
                except TypeError:
                    tf = tarfile.open(source, mode)
                with tf:
                    members = []
                    for m in tf.getmembers():
                        name = m.name
                        if not name:
                            continue
                        if os.path.isabs(name) or ".." in name.replace("\\", "/").split("/"):
                            continue
                        if m.issym() or m.islnk():
                            skipped_links += 1
                            continue
                        members.append(m)
                    total_files = 0
                    total_size = 0
                    for m in members:
                        if m.isdir() or m.name.endswith("/"):
                            continue
                        total_files += 1
                        total_size += m.size or 0
                    if total_files > MAX_EXTRACT_FILES:
                        raise ExtractValidationError("Архів містить забагато файлів (перевищено ліміт)")
                    if total_size > MAX_EXTRACT_TOTAL_BYTES:
                        raise ExtractValidationError("Архів занадто великий для розпаковки (перевищено ліміт)")
                    done = 0
                    for m in members:
                        if should_cancel and should_cancel():
                            break
                        name = m.name
                        if m.issym() or m.islnk():
                            skipped_links += 1
                            continue
                        if m.isdir() or name.endswith("/"):
                            safe_d = _safe_extract_path(target_root, name)
                            if safe_d is not None:
                                try:
                                    safe_d.mkdir(parents=True, exist_ok=True)
                                except Exception as exc:
                                    results.append(ExtractResult(entry=ExtractEntry(name=name, is_dir=True), source=source, destination=safe_d, ok=False, message=str(exc)))
                            done += 1
                            if on_progress:
                                try:
                                    on_progress(done, total_files, target_root / name)
                                except Exception:
                                    pass
                            continue
                        safe_p = _safe_extract_path(target_root, name)
                        if safe_p is None:
                            results.append(ExtractResult(entry=ExtractEntry(name=name, is_dir=False), source=source, destination=None, ok=False, message="Небезпечний шлях"))
                            done += 1
                            if on_progress:
                                try:
                                    on_progress(done, total_files, target_root / name)
                                except Exception:
                                    pass
                            continue
                        try:
                            safe_p.parent.mkdir(parents=True, exist_ok=True)
                        except Exception:
                            pass
                        out_path = safe_p
                        if out_path.exists() and not options.overwrite:
                            out_path = _unique_path(out_path.parent, out_path)
                        try:
                            f = tf.extractfile(m)
                            if f is None:
                                results.append(ExtractResult(entry=ExtractEntry(name=name, is_dir=False), source=source, destination=out_path, ok=False, message="Не вдалося прочитати"))
                            else:
                                with f, open(out_path, "wb") as dst_f:
                                    shutil.copyfileobj(f, dst_f)
                                results.append(ExtractResult(entry=ExtractEntry(name=name, is_dir=False, size=m.size or 0), source=source, destination=out_path, ok=True, message=""))
                        except Exception as exc:
                            results.append(ExtractResult(entry=ExtractEntry(name=name, is_dir=False), source=source, destination=out_path, ok=False, message=str(exc)))
                        done += 1
                        if on_progress:
                            try:
                                on_progress(done, total_files, out_path)
                            except Exception:
                                pass
                    if skipped_links:
                        results.append(ExtractResult(entry=None, source=source, destination=None, ok=False, message=f"Пропущено симлінків/жорстких лінків: {skipped_links}"))
                    if should_cancel and should_cancel():
                        return results
                    return results
            except ExtractError:
                raise
            except Exception as exc:
                raise ExtractIOError(f"Помилка розпаковки: {exc}") from exc

        if fmt == "7z":
            if py7zr is None:
                raise ExtractValidationError("Для розпаковки 7z потрібен py7zr")
            try:
                with py7zr.SevenZipFile(source, mode="r") as z:
                    try:
                        files = z.getnames()
                    except Exception:
                        files = []
                    # оцінка
                    total_files = 0
                    total_size = 0
                    for f in z.list():
                        name = f.filename
                        if not name:
                            continue
                        if os.path.isabs(name) or ".." in name.replace("\\", "/").split("/"):
                            continue
                        if name.endswith("/"):
                            continue
                        # спроба визначити симлінк - у py7zr важко, пропускаємо якщо є підозра
                        total_files += 1
                        total_size += getattr(f, "uncompressed", 0) or 0
                    if total_files > MAX_EXTRACT_FILES:
                        raise ExtractValidationError("Архів містить забагато файлів (перевищено ліміт)")
                    if total_size > MAX_EXTRACT_TOTAL_BYTES:
                        raise ExtractValidationError("Архів занадто великий для розпаковки (перевищено ліміт)")
                    done = 0
                    for f in z.list():
                        if should_cancel and should_cancel():
                            break
                        name = f.filename
                        if not name:
                            continue
                        if os.path.isabs(name) or ".." in name.replace("\\", "/").split("/"):
                            results.append(ExtractResult(entry=ExtractEntry(name=name, is_dir=False), source=source, destination=None, ok=False, message="Небезпечний шлях"))
                            continue
                        if name.endswith("/"):
                            safe_d = _safe_extract_path(target_root, name)
                            if safe_d is not None:
                                try:
                                    safe_d.mkdir(parents=True, exist_ok=True)
                                except Exception as exc:
                                    results.append(ExtractResult(entry=ExtractEntry(name=name, is_dir=True), source=source, destination=safe_d, ok=False, message=str(exc)))
                            continue
                        # спроба виявити симлінк - пропускаємо за наявності атрибутів
                        try:
                            if getattr(f, "is_symlink", False) or getattr(f, "is_hardlink", False):
                                skipped_links += 1
                                continue
                        except Exception:
                            pass
                        safe_p = _safe_extract_path(target_root, name)
                        if safe_p is None:
                            results.append(ExtractResult(entry=ExtractEntry(name=name, is_dir=False), source=source, destination=None, ok=False, message="Небезпечний шлях"))
                            continue
                        try:
                            safe_p.parent.mkdir(parents=True, exist_ok=True)
                        except Exception:
                            pass
                        out_path = safe_p
                        if out_path.exists() and not options.overwrite:
                            out_path = _unique_path(out_path.parent, out_path)
                        try:
                            # екстрагуємо окремий файл
                            z.extract(targets=[name], path=target_root)
                            # py7zr може розпакувати в оригінальній структурі - знаходимо
                            extracted = target_root / name
                            if extracted != out_path and extracted.exists():
                                try:
                                    if out_path.exists():
                                        out_path.unlink()
                                    extracted.rename(out_path)
                                except Exception:
                                    pass
                            results.append(ExtractResult(entry=ExtractEntry(name=name, is_dir=False), source=source, destination=out_path, ok=True, message=""))
                        except Exception as exc:
                            if "password" in str(exc).lower():
                                raise ExtractValidationError("Архів захищений паролем, це не підтримується") from exc
                            results.append(ExtractResult(entry=ExtractEntry(name=name, is_dir=False), source=source, destination=out_path, ok=False, message=str(exc)))
                        done += 1
                        if on_progress:
                            try:
                                on_progress(done, total_files, out_path)
                            except Exception:
                                pass
                    if skipped_links:
                        results.append(ExtractResult(entry=None, source=source, destination=None, ok=False, message=f"Пропущено симлінків/жорстких лінків: {skipped_links}"))
                    if should_cancel and should_cancel():
                        return results
                    return results
            except ExtractError:
                raise
            except Exception as exc:
                if "password" in str(exc).lower():
                    raise ExtractValidationError("Архів захищений паролем, це не підтримується") from exc
                raise ExtractIOError(f"Помилка розпаковки: {exc}") from exc

        raise ExtractValidationError("Непідтримуваний формат архіву")
    except ExtractError:
        raise
    except Exception as exc:
        raise ExtractIOError(f"Неочікувана помилка: {exc}") from exc
