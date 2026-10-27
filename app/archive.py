"""Логіка роботи з архівами.

Модуль навмисно не залежить від інтерфейсу, щоб його можна було
тестувати окремо. Усі повідомлення про помилки — українською.
"""

from __future__ import annotations

import os
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


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
