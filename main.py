"""Точка входу File Toolkit."""

from __future__ import annotations

import sys
from pathlib import Path


def run_self_test(report_path: Path) -> int:
    """Перевіряє зібрану програму без вікна й пише звіт у файл.

    Використовується після збірки .exe, де консольного виводу немає:
    конвертації виконуються у тимчасовій папці, результат — у текстовому звіті.
    """
    import subprocess
    import tempfile

    from app import __version__, archive, converter, data_converter, video_converter

    folder = Path(tempfile.mkdtemp(prefix="file-toolkit-selftest-"))
    lines: list[str] = [
        f"File Toolkit {__version__} self-test",
        f"frozen: {getattr(sys, 'frozen', False)}",
        f"folder: {folder}",
    ]
    failures = 0

    def check(name: str, func) -> None:
        nonlocal failures
        try:
            detail = func()
        except Exception as exc:  # звіт має містити всі кроки, а не лише першу помилку
            failures += 1
            lines.append(f"FAIL {name}: {type(exc).__name__}: {exc}")
        else:
            lines.append(f"OK   {name}: {detail}")

    def check_gui() -> str:
        import customtkinter

        themes = Path(customtkinter.__file__).parent / "assets" / "themes"
        if not (themes / "blue.json").is_file():
            raise RuntimeError(f"немає тем customtkinter: {themes}")
        return f"customtkinter {customtkinter.__version__}"

    def check_dnd() -> str:
        import tkinter

        from tkinterdnd2 import DND_FILES, TkinterDnD

        root = TkinterDnD.Tk()
        root.withdraw()
        try:
            version = TkinterDnD._require(root)
            frame = tkinter.Frame(root)
            frame.drop_target_register(DND_FILES)
            bound = bool(frame.dnd_bind("<<Drop>>", lambda _event: None))
        finally:
            root.destroy()
        if version is None or not bound:
            raise RuntimeError(f"tkdnd недоступний: {version}")
        return f"tkdnd {version}, ціль перетягування зареєстровано"

    def check_image() -> str:
        from PIL import Image

        from app.converter import ImageOptions, TargetFormat

        source = folder / "selftest.png"
        Image.new("RGB", (64, 48), (200, 60, 120)).save(source)
        destination = folder / "selftest.jpg"
        result = converter.convert_image(
            source, destination, ImageOptions(target=TargetFormat.JPEG)
        )
        if not result.ok or not destination.is_file():
            raise RuntimeError(result.message or "файл не створено")
        return f"PNG → JPG, {destination.stat().st_size} байт"

    def check_data() -> str:
        from app.data_converter import DataOptions, OutputFormat

        source = folder / "selftest.json"
        source.write_text(
            '[{"name": "Анна", "age": 30}, {"name": "Богдан", "age": 25}]',
            encoding="utf-8",
        )
        destination = folder / "selftest.csv"
        result = data_converter.convert_data(
            source,
            destination,
            DataOptions(target=OutputFormat.CSV, output_delimiter=","),
        )
        if not result.ok or not destination.is_file():
            raise RuntimeError(result.message or "файл не створено")
        return f"JSON → CSV, {destination.stat().st_size} байт"

    def check_zip() -> str:
        from app.archive import ExtractOptions, create_zip, extract_archive, list_archive

        first = folder / "one.txt"
        second = folder / "two.txt"
        first.write_text("перший", encoding="utf-8")
        second.write_text("другий", encoding="utf-8")
        create_zip([first, second], folder, "selftest")
        zip_path = folder / "selftest.zip"
        entries = list_archive(zip_path)
        target = folder / "unpacked"
        target.mkdir(exist_ok=True)
        extract_archive(zip_path, target, ExtractOptions())
        unpacked = sorted(path.name for path in target.rglob("*") if path.is_file())
        if unpacked != ["one.txt", "two.txt"]:
            raise RuntimeError(f"розпаковано: {unpacked}")
        return f"ZIP: {len(entries)} записи, розпаковано {len(unpacked)} файли"

    def check_seven_zip() -> str:
        import py7zr

        from app.archive import ExtractOptions, extract_archive

        archive_path = folder / "selftest.7z"
        with py7zr.SevenZipFile(archive_path, "w") as seven:
            seven.write(folder / "one.txt", "one.txt")
        target = folder / "unpacked-7z"
        target.mkdir(exist_ok=True)
        results = extract_archive(archive_path, target, ExtractOptions())
        unpacked = [path for path in target.rglob("one.txt") if path.is_file()]
        if not unpacked:
            raise RuntimeError(f"результат: {results}")
        return f"py7zr {py7zr.__version__}, 7z розпаковано"

    def check_video() -> str:
        from app.video_converter import MaxHeight, OutputFormat, VideoOptions

        ffmpeg = video_converter._get_ffmpeg_exe()
        source = folder / "selftest.mp4"
        subprocess.run(
            [
                ffmpeg, "-hide_banner", "-nostdin", "-y",
                "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=22050",
                "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", str(source),
            ],
            capture_output=True,
            check=True,
            timeout=120,
        )
        destination = folder / "selftest.mp3"
        result = video_converter.convert_video(
            source,
            destination,
            VideoOptions(target=OutputFormat.MP3, max_height=MaxHeight.NONE),
        )
        if not result.ok or not destination.is_file():
            raise RuntimeError(result.message or "файл не створено")
        return f"MP4 → MP3 через {Path(ffmpeg).name}, {destination.stat().st_size} байт"

    check("customtkinter", check_gui)
    check("drag and drop", check_dnd)
    check("image", check_image)
    check("data", check_data)
    check("zip", check_zip)
    check("7z", check_seven_zip)
    check("video", check_video)

    lines.append(f"failures: {failures}")
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if failures == 0 else 1


def main(argv: list[str] | None = None) -> int:
    """Запускає вікно програми або самоперевірку `--self-test <звіт>`."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--self-test":
        if len(args) < 2:
            return 2
        return run_self_test(Path(args[1]))

    import customtkinter as ctk

    from app.ui import App

    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    App().mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
