"""Головне вікно File Toolkit: вкладки «Конвертер» і «Архіватор»."""

from __future__ import annotations

import os
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

WINDOW_TITLE = "File Toolkit — офлайн конвертер та архіватор"
WINDOW_SIZE = (900, 620)
MIN_SIZE = (760, 520)

CONVERTER_TAB = "Конвертер"
ARCHIVE_TAB = "Архіватор"

SELECT_FILES_TITLE = "Вибір файлів"
ADD_FILES_TITLE = "Вибір файлів для архіву"
ADD_FOLDER_TITLE = "Вибір папки для архіву"

FILE_FILTER = [("Усі файли", "*.*")]


def _path_key(path: Path) -> str:
    """Ключ для порівняння шляхів без урахування регістру (Windows)."""
    return os.path.normcase(str(path))


class App(ctk.CTk):
    """Головне вікно програми."""

    def __init__(self) -> None:
        super().__init__()
        self.title(WINDOW_TITLE)
        self.minsize(*MIN_SIZE)
        self._centre_window()

        self._converter_files: list[Path] = []
        self._archive_items: list[Path] = []

        self._build_layout()
        self._refresh_converter_list()
        self._refresh_archive_list()
        self._set_status("Готово")

    # --- побудова інтерфейсу -------------------------------------------------

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.tabs = ctk.CTkTabview(self)
        self.tabs.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="nsew")

        self._build_converter_tab(self.tabs.add(CONVERTER_TAB))
        self._build_archive_tab(self.tabs.add(ARCHIVE_TAB))

        self.status_label = ctk.CTkLabel(self, text="", anchor="w", height=28)
        self.status_label.grid(row=1, column=0, padx=20, pady=(0, 10), sticky="ew")

    def _build_converter_tab(self, tab: ctk.CTkFrame) -> None:
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)

        toolbar = ctk.CTkFrame(tab, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(4, 10))

        ctk.CTkButton(
            toolbar, text="Вибрати файли", command=self._choose_converter_files
        ).pack(side="left")
        ctk.CTkButton(
            toolbar,
            text="Очистити",
            command=self._clear_converter_files,
            fg_color="gray30",
            hover_color="gray25",
        ).pack(side="left", padx=(8, 0))

        self._converter_counter = ctk.CTkLabel(tab, text="", anchor="w")
        self._converter_counter.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        self._converter_list = ctk.CTkScrollableFrame(tab, label_text="Вибрані файли")
        self._converter_list.grid(row=2, column=0, sticky="nsew")

    def _build_archive_tab(self, tab: ctk.CTkFrame) -> None:
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)

        toolbar = ctk.CTkFrame(tab, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(4, 10))

        ctk.CTkButton(
            toolbar, text="Додати файли", command=self._choose_archive_files
        ).pack(side="left")
        ctk.CTkButton(
            toolbar, text="Додати папку", command=self._choose_archive_folder
        ).pack(side="left", padx=(8, 0))
        ctk.CTkButton(
            toolbar,
            text="Очистити",
            command=self._clear_archive_items,
            fg_color="gray30",
            hover_color="gray25",
        ).pack(side="left", padx=(8, 0))

        self._archive_counter = ctk.CTkLabel(tab, text="", anchor="w")
        self._archive_counter.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        self._archive_list = ctk.CTkScrollableFrame(
            tab, label_text="Файли та папки для архіву"
        )
        self._archive_list.grid(row=2, column=0, sticky="nsew")

    # --- конвертер: вибір файлів --------------------------------------------

    def _choose_converter_files(self) -> None:
        chosen = filedialog.askopenfilenames(
            parent=self, title=SELECT_FILES_TITLE, filetypes=FILE_FILTER
        )
        added = sum(1 for raw in chosen if self._append_path(self._converter_files, Path(raw)))
        if not added:
            return
        self._refresh_converter_list()
        self._set_status(
            f"Додано файлів: {added}. Усього: {len(self._converter_files)}"
        )

    def _clear_converter_files(self) -> None:
        if not self._converter_files:
            self._set_status("Список файлів уже порожній")
            return
        self._converter_files.clear()
        self._refresh_converter_list()
        self._set_status("Список файлів очищено")

    def _refresh_converter_list(self) -> None:
        self._fill_list(self._converter_list, self._converter_files)
        self._converter_counter.configure(
            text=f"Вибрано файлів: {len(self._converter_files)}"
        )

    # --- архіватор: вибір файлів і папок ------------------------------------

    def _choose_archive_files(self) -> None:
        chosen = filedialog.askopenfilenames(
            parent=self, title=ADD_FILES_TITLE, filetypes=FILE_FILTER
        )
        added = sum(1 for raw in chosen if self._append_path(self._archive_items, Path(raw)))
        if not added:
            return
        self._refresh_archive_list()
        self._set_status(f"Додано до архіву: {added}. Усього: {len(self._archive_items)}")

    def _choose_archive_folder(self) -> None:
        chosen = filedialog.askdirectory(
            parent=self, title=ADD_FOLDER_TITLE, mustexist=True
        )
        if not chosen or not self._append_path(self._archive_items, Path(chosen)):
            return
        self._refresh_archive_list()
        self._set_status(
            f"Додано папку: {chosen}. Усього: {len(self._archive_items)}"
        )

    def _clear_archive_items(self) -> None:
        if not self._archive_items:
            self._set_status("Список архіву вже порожній")
            return
        self._archive_items.clear()
        self._refresh_archive_list()
        self._set_status("Список архіву очищено")

    def _refresh_archive_list(self) -> None:
        labels = [
            f"{index}. [{'папка' if path.is_dir() else 'файл'}] {path.name}"
            for index, path in enumerate(self._archive_items, start=1)
        ]
        self._fill_list(self._archive_list, labels)
        self._archive_counter.configure(
            text=f"Вибрано елементів: {len(self._archive_items)}"
        )

    # --- спільні допоміжні методи -------------------------------------------

    def _append_path(self, items: list[Path], path: Path) -> bool:
        """Додає шлях до списку, якщо його там ще немає."""
        if any(_path_key(existing) == _path_key(path) for existing in items):
            return False
        items.append(path)
        return True

    def _fill_list(self, container: ctk.CTkScrollableFrame, entries) -> None:
        for child in container.winfo_children():
            child.destroy()
        for index, entry in enumerate(entries, start=1):
            text = entry if isinstance(entry, str) else f"{index}. {entry.name}"
            ctk.CTkLabel(container, text=text, anchor="w").pack(
                fill="x", padx=8, pady=2
            )

    def _set_status(self, message: str) -> None:
        self.status_label.configure(text=message)

    def _centre_window(self) -> None:
        width, height = WINDOW_SIZE
        x = max((self.winfo_screenwidth() - width) // 2, 0)
        y = max((self.winfo_screenheight() - height) // 3, 0)
        self.geometry(f"{width}x{height}+{x}+{y}")
