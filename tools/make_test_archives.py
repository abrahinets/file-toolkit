#!/usr/bin/env python3
"""Генерує тестові архіви для перевірки розпаковки."""
from __future__ import annotations

import os
import tarfile
import zipfile
from pathlib import Path

try:
    import py7zr
except Exception:
    py7zr = None


def main() -> None:
    out_dir = Path("test_archives")
    out_dir.mkdir(parents=True, exist_ok=True)

    # test.zip з папкою та вкладеними файлами
    zip_path = out_dir / "test.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("folder/readme.txt", "Hello from folder\n")
        zf.writestr("folder/sub/nested.txt", "Nested content\n")
        zf.writestr("root.txt", "Root file\n")

    # test.tar.gz
    tar_gz_path = out_dir / "test.tar.gz"
    with tarfile.open(tar_gz_path, "w:gz") as tf:
        data1 = b"Hello tar.gz\n"
        info1 = tarfile.TarInfo(name="folder/readme.txt")
        info1.size = len(data1)
        tf.addfile(info1, fileobj=__import__("io").BytesIO(data1))
        data2 = b"Nested\n"
        info2 = tarfile.TarInfo(name="folder/sub/nested.txt")
        info2.size = len(data2)
        tf.addfile(info2, fileobj=__import__("io").BytesIO(data2))

    # test.7z
    seven_path = out_dir / "test.7z"
    if py7zr is not None:
        with py7zr.SevenZipFile(seven_path, "w") as z7:
            tmp1 = out_dir / "_tmp_readme.txt"
            tmp1.write_text("Hello 7z\n", encoding="utf-8")
            z7.write(tmp1, arcname="folder/readme.txt")
            tmp2 = out_dir / "_tmp_nested.txt"
            tmp2.write_text("Nested 7z\n", encoding="utf-8")
            z7.write(tmp2, arcname="folder/sub/nested.txt")
            try:
                tmp1.unlink()
                tmp2.unlink()
            except Exception:
                pass
    else:
        # якщо py7zr не встановлено - створюємо порожній файл як маркер
        seven_path.write_bytes(b"")

    # evil.zip з файлом із шляхом ../evil.txt
    evil_path = out_dir / "evil.zip"
    with zipfile.ZipFile(evil_path, "w") as zf:
        zf.writestr("../evil.txt", "malicious\n")
        zf.writestr("safe.txt", "safe\n")

    print("Готово:", zip_path, tar_gz_path, seven_path, evil_path)


if __name__ == "__main__":
    main()
