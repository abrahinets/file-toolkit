"""Збірка File Toolkit у теку з .exe через PyInstaller.

Запуск:  .\\venv\\Scripts\\python.exe build.py
Результат: dist\\FileToolkit\\FileToolkit.exe (--onedir, без консольного вікна).

.spec не зберігається в репозиторії: він генерується під час збірки в build/.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_NAME = "FileToolkit"
ENTRY_POINT = ROOT / "main.py"
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"

# Пакети з даними/бінарниками, які PyInstaller не завжди підхоплює сам:
# теми й шрифти customtkinter, бекенди стиснення py7zr, ffmpeg з imageio-ffmpeg.
COLLECT_ALL = ("customtkinter", "py7zr", "imageio_ffmpeg")

# Нічого з цього в програмі не використовується, але може потрапити в збірку.
EXCLUDES = ("pytest", "IPython", "matplotlib", "numpy", "pandas", "PyQt5", "PySide6")


def build_command() -> list[str]:
    """Складає аргументи PyInstaller. Окремо — щоб можна було перевірити тестами."""
    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",  # без консольного вікна
        "--name",
        APP_NAME,
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR),
        "--specpath",
        str(BUILD_DIR),
        "--noupx",
    ]
    for package in COLLECT_ALL:
        args += ["--collect-all", package]
    for module in EXCLUDES:
        args += ["--exclude-module", module]
    args.append(str(ENTRY_POINT))
    return args


def folder_size(path: Path) -> int:
    """Сумарний розмір усіх файлів у теці."""
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def main() -> int:
    if not ENTRY_POINT.is_file():
        print(f"Не знайдено {ENTRY_POINT}", file=sys.stderr)
        return 1

    target = DIST_DIR / APP_NAME
    if target.exists():
        shutil.rmtree(target)

    print("Збірка:", " ".join(build_command()[2:]), flush=True)
    completed = subprocess.run(build_command(), cwd=ROOT)
    if completed.returncode != 0:
        print("Збірка не вдалась", file=sys.stderr)
        return completed.returncode

    exe = target / f"{APP_NAME}.exe"
    if not exe.is_file():
        print(f"Не знайдено {exe}", file=sys.stderr)
        return 1

    size = folder_size(target)
    print(f"Готово: {exe}")
    print(f"Розмір теки: {size / (1024 * 1024):.1f} МБ ({size} байт)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
