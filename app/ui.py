"""Головне вікно File Toolkit: вкладки «Конвертер» і «Архіватор»."""

from __future__ import annotations

import os
import queue
import threading
import tkinter
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox

import customtkinter as ctk

from app import converter
from app.converter import ImageOptions, ResizeMode, TargetFormat

WINDOW_TITLE = "File Toolkit — офлайн конвертер та архіватор"
WINDOW_SIZE = (980, 700)
MIN_SIZE = (820, 600)

CONVERTER_TAB = "Конвертер"
ARCHIVE_TAB = "Архіватор"

SELECT_FILES_TITLE = "Вибір файлів"
ADD_FILES_TITLE = "Вибір файлів для архіву"
ADD_FOLDER_TITLE = "Вибір папки для архіву"
CHOOSE_OUTPUT_TITLE = "Папка для результатів"

FILE_FILTER = [("Усі файли", "*.*")]
IMAGE_FILTER = [
    ("Зображення", "*.png *.jpg *.jpeg *.webp *.bmp"),
    ("Усі файли", "*.*"),
]

SAME_FOLDER_TEXT = "Поруч з оригіналами"
OTHER_COLOR_LABEL = "Інший колір…"
BACKGROUND_CHOICES = {
    "Білий": "#FFFFFF",
    "Чорний": "#000000",
}

RESIZE_LABELS = {
    ResizeMode.NONE: "Без змін",
    ResizeMode.LONGEST_SIDE: "Довша сторона",
    ResizeMode.PERCENT: "Відсоток",
    ResizeMode.BOX: "Точний розмір",
}

UNSUPPORTED_COLOR = "#e0a13c"
HINT_COLOR = "gray60"
SETTINGS_LABEL_WIDTH = 96
PROGRESS_POLL_MS = 100
MAX_FAILURE_LINES = 8


def _path_key(path: Path) -> str:
    """Ключ для порівняння шляхів без урахування регістру (Windows)."""
    return os.path.normcase(str(path))


class App(ctk.CTk):
    """Головне вікно програми."""

    def __init__(self) -> None:
        super().__init__()
        self.title(WINDOW_TITLE)
        self._layout_ready = False

        self._converter_files: list[Path] = []
        self._archive_items: list[Path] = []

        # Стан конвертера.
        self._queue: queue.Queue = queue.Queue()
        self._cancel_event = threading.Event()
        self._converter_running = False
        self._quality_syncing = False
        self._background_hex = BACKGROUND_CHOICES["Білий"]
        self._output_dir: Path | None = None
        self._last_output_dir: Path | None = None
        self._skipped_unsupported = 0
        self._conversion_total = 0

        self._build_layout()
        self._refresh_converter_list()
        self._refresh_archive_list()
        self._on_format_change()
        self._on_resize_mode_change()
        self._set_status("Готово")
        self._layout_ready = True
        self._centre_window()

    def _set_scaling(self, new_widget_scaling, new_window_scaling):
        """Коли DPI-масштаб уточнюється, підганяємо розмір вікна ще раз."""
        super()._set_scaling(new_widget_scaling, new_window_scaling)
        if getattr(self, "_layout_ready", False):
            self.after_idle(self._centre_window)

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
        tab.grid_rowconfigure(3, weight=1)

        toolbar = ctk.CTkFrame(tab, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(4, 8))

        self._choose_files_button = ctk.CTkButton(
            toolbar, text="Вибрати файли", command=self._choose_converter_files
        )
        self._choose_files_button.pack(side="left")
        self._clear_files_button = ctk.CTkButton(
            toolbar,
            text="Очистити",
            command=self._clear_converter_files,
            fg_color="gray30",
            hover_color="gray25",
        )
        self._clear_files_button.pack(side="left", padx=(8, 0))

        self._build_converter_settings(tab)

        self._converter_counter = ctk.CTkLabel(tab, text="", anchor="w")
        self._converter_counter.grid(row=2, column=0, sticky="ew", pady=(0, 6))

        self._converter_list = ctk.CTkScrollableFrame(
            tab, label_text="Вибрані файли", height=90
        )
        self._converter_list.grid(row=3, column=0, sticky="nsew")

        self._build_converter_progress(tab)

    def _build_converter_settings(self, tab: ctk.CTkFrame) -> None:
        settings = ctk.CTkFrame(tab)
        settings.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        # Рядок 1: формат і якість.
        format_row = self._settings_row(settings)
        self._row_label(format_row, "Формат:")
        self._format_menu = ctk.CTkOptionMenu(
            format_row,
            values=[converter.TARGET_FORMAT_LABELS[fmt] for fmt in TargetFormat],
            width=150,
            command=self._on_format_change,
        )
        self._format_menu.set(converter.TARGET_FORMAT_LABELS[TargetFormat.SOURCE])
        self._format_menu.pack(side="left", padx=(0, 18))

        self._quality_label = ctk.CTkLabel(
            format_row, text="Якість:", width=SETTINGS_LABEL_WIDTH, anchor="w"
        )
        self._quality_label.pack(side="left")

        self._quality_slider = ctk.CTkSlider(
            format_row,
            from_=converter.MIN_QUALITY,
            to=converter.MAX_QUALITY,
            number_of_steps=converter.MAX_QUALITY - converter.MIN_QUALITY,
            width=170,
            command=self._on_quality_slider,
        )
        self._quality_slider.set(converter.DEFAULT_QUALITY)
        self._quality_slider.pack(side="left", padx=(0, 8))

        self._quality_var = ctk.StringVar(value=str(converter.DEFAULT_QUALITY))
        self._quality_entry = ctk.CTkEntry(
            format_row, width=54, justify="center", textvariable=self._quality_var
        )
        self._quality_entry.pack(side="left")
        self._quality_entry.bind("<Return>", self._on_quality_entry)
        self._quality_entry.bind("<FocusOut>", self._on_quality_entry)

        self._quality_hint = ctk.CTkLabel(
            format_row,
            text="",
            text_color=HINT_COLOR,
            font=ctk.CTkFont(size=11),
            anchor="w",
        )
        self._quality_hint.pack(side="left", padx=(12, 0))

        # Рядок 2: розмір.
        size_row = self._settings_row(settings)
        self._row_label(size_row, "Розмір:")
        self._resize_menu = ctk.CTkOptionMenu(
            size_row,
            values=list(RESIZE_LABELS.values()),
            width=150,
            command=self._on_resize_mode_change,
        )
        self._resize_menu.set(RESIZE_LABELS[ResizeMode.NONE])
        self._resize_menu.pack(side="left", padx=(0, 18))

        self._size_params = ctk.CTkFrame(size_row, fg_color="transparent", height=35)
        self._size_params.pack(side="left")

        self._size_frames: dict[ResizeMode, ctk.CTkFrame] = {}
        self._longest_side_var = ctk.StringVar(value="1920")
        self._percent_var = ctk.StringVar(value="100")
        self._box_width_var = ctk.StringVar(value="1920")
        self._box_height_var = ctk.StringVar(value="1080")

        longest_frame = ctk.CTkFrame(self._size_params, fg_color="transparent")
        ctk.CTkEntry(
            longest_frame, width=72, justify="center", textvariable=self._longest_side_var
        ).pack(side="left")
        ctk.CTkLabel(longest_frame, text="px (довша сторона)").pack(
            side="left", padx=(6, 0)
        )
        self._size_frames[ResizeMode.LONGEST_SIDE] = longest_frame

        percent_frame = ctk.CTkFrame(self._size_params, fg_color="transparent")
        ctk.CTkEntry(
            percent_frame, width=72, justify="center", textvariable=self._percent_var
        ).pack(side="left")
        ctk.CTkLabel(percent_frame, text="% від оригіналу").pack(
            side="left", padx=(6, 0)
        )
        self._size_frames[ResizeMode.PERCENT] = percent_frame

        box_frame = ctk.CTkFrame(self._size_params, fg_color="transparent")
        ctk.CTkEntry(
            box_frame, width=66, justify="center", textvariable=self._box_width_var
        ).pack(side="left")
        ctk.CTkLabel(box_frame, text="×").pack(side="left", padx=4)
        ctk.CTkEntry(
            box_frame, width=66, justify="center", textvariable=self._box_height_var
        ).pack(side="left")
        ctk.CTkLabel(box_frame, text="px").pack(side="left", padx=(6, 0))
        self._size_frames[ResizeMode.BOX] = box_frame

        self._keep_aspect_var = ctk.BooleanVar(value=True)
        self._keep_aspect_check = ctk.CTkCheckBox(
            size_row,
            text="Пропорції",
            variable=self._keep_aspect_var,
            onvalue=True,
            offvalue=False,
        )
        self._keep_aspect_check.pack(side="left", padx=(18, 0))

        self._no_upscale_var = ctk.BooleanVar(value=True)
        self._no_upscale_check = ctk.CTkCheckBox(
            size_row,
            text="Не збільшувати",
            variable=self._no_upscale_var,
            onvalue=True,
            offvalue=False,
        )
        self._no_upscale_check.pack(side="left", padx=(12, 0))

        # Рядок 3: підкладка для прозорості та папка призначення.
        folder_row = self._settings_row(settings)
        self._row_label(folder_row, "Підкладка:")
        self._background_menu = ctk.CTkOptionMenu(
            folder_row,
            values=list(BACKGROUND_CHOICES) + [OTHER_COLOR_LABEL],
            width=130,
            command=self._on_background_change,
        )
        self._background_menu.set("Білий")
        self._background_menu.pack(side="left", padx=(0, 16))

        self._background_hint = ctk.CTkLabel(
            folder_row,
            text="фон для прозорих пікселів",
            text_color=HINT_COLOR,
            font=ctk.CTkFont(size=11),
            anchor="w",
        )
        self._background_hint.pack(side="left", padx=(0, 16))

        self._row_label(folder_row, "Папка:")
        self._use_source_folder = True
        self._output_text = ctk.StringVar(value=SAME_FOLDER_TEXT)
        self._output_entry = ctk.CTkEntry(
            folder_row, textvariable=self._output_text, state="disabled", width=200
        )
        self._output_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._browse_output_button = ctk.CTkButton(
            folder_row,
            text="Оглянути…",
            width=100,
            command=self._choose_output_dir,
            fg_color="gray30",
            hover_color="gray25",
        )
        self._browse_output_button.pack(side="left")
        self._reset_output_button = ctk.CTkButton(
            folder_row,
            text="Скинути",
            width=90,
            command=self._reset_output_dir,
            state="disabled",
            fg_color="gray30",
            hover_color="gray25",
        )
        self._reset_output_button.pack(side="left", padx=(8, 0))

    def _settings_row(self, parent: ctk.CTkFrame) -> ctk.CTkFrame:
        """Рядок налаштувань: підпис ліворуч, елементи керування праворуч."""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=4)
        return row

    def _row_label(self, parent: ctk.CTkFrame, text: str) -> ctk.CTkLabel:
        label = ctk.CTkLabel(
            parent, text=text, width=SETTINGS_LABEL_WIDTH, anchor="w"
        )
        label.pack(side="left")
        return label

    def _build_converter_progress(self, tab: ctk.CTkFrame) -> None:
        progress_frame = ctk.CTkFrame(tab, fg_color="transparent")
        progress_frame.grid(row=4, column=0, sticky="ew", pady=(10, 6))

        self._progress_bar = ctk.CTkProgressBar(progress_frame, height=10)
        self._progress_bar.set(0)
        self._progress_bar.pack(side="left", fill="x", expand=True, padx=(0, 12))

        self._progress_label = ctk.CTkLabel(
            progress_frame, text="Оброблено 0 з 0", anchor="e", width=240
        )
        self._progress_label.pack(side="left")

        actions = ctk.CTkFrame(tab, fg_color="transparent")
        actions.grid(row=5, column=0, sticky="ew")

        self._convert_button = ctk.CTkButton(
            actions, text="Конвертувати", command=self._start_conversion
        )
        self._convert_button.pack(side="left")

        self._cancel_button = ctk.CTkButton(
            actions,
            text="Скасувати",
            command=self._cancel_conversion,
            state="disabled",
            fg_color="gray30",
            hover_color="gray25",
        )
        self._cancel_button.pack(side="left", padx=(8, 0))

        self._open_folder_button = ctk.CTkButton(
            actions,
            text="Відкрити папку",
            command=self._open_output_folder,
            state="disabled",
            fg_color="gray30",
            hover_color="gray25",
        )
        self._open_folder_button.pack(side="right")

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
            parent=self, title=SELECT_FILES_TITLE, filetypes=IMAGE_FILTER
        )
        added = sum(1 for raw in chosen if self._append_path(self._converter_files, Path(raw)))
        if not added:
            return
        self._reset_conversion_progress()
        self._refresh_converter_list()
        self._set_status(
            f"Додано файлів: {added}. Усього: {len(self._converter_files)}"
        )

    def _clear_converter_files(self) -> None:
        if not self._converter_files:
            self._set_status("Список файлів уже порожній")
            return
        self._converter_files.clear()
        self._reset_conversion_progress()
        self._refresh_converter_list()
        self._set_status("Список файлів очищено")

    def _refresh_converter_list(self) -> None:
        entries: list[str | tuple[str, str]] = []
        unsupported = 0
        for index, path in enumerate(self._converter_files, start=1):
            if converter.is_supported_image(path):
                entries.append(f"{index}. {path.name}")
            else:
                unsupported += 1
                entries.append(
                    (
                        f"{index}. {path.name} — формат не підтримується",
                        UNSUPPORTED_COLOR,
                    )
                )
        self._fill_list(self._converter_list, entries)

        supported = len(self._converter_files) - unsupported
        text = f"Вибрано файлів: {len(self._converter_files)} (підтримується: {supported})"
        if unsupported:
            text += f", непідтримуваних: {unsupported}"
        self._converter_counter.configure(text=text)

    # --- конвертер: налаштування --------------------------------------------

    def _current_target(self) -> TargetFormat:
        label = self._format_menu.get()
        for fmt, fmt_label in converter.TARGET_FORMAT_LABELS.items():
            if fmt_label == label:
                return fmt
        return TargetFormat.SOURCE

    def _current_resize_mode(self) -> ResizeMode:
        label = self._resize_menu.get()
        for mode, mode_label in RESIZE_LABELS.items():
            if mode_label == label:
                return mode
        return ResizeMode.NONE

    def _on_format_change(self, _choice: str | None = None) -> None:
        target = self._current_target()
        if target is TargetFormat.BMP:
            self._quality_label.configure(text="Стиснення:")
            self._quality_hint.configure(text="BMP не стискається")
            self._set_quality_enabled(False)
        elif target is TargetFormat.PNG:
            self._quality_label.configure(text="Стиснення:")
            self._quality_hint.configure(text="100 — найменший файл")
            self._set_quality_enabled(True)
        else:
            self._quality_label.configure(text="Якість:")
            self._quality_hint.configure(text="менше — легший файл")
            self._set_quality_enabled(True)

        # Прозорість втрачається лише в JPG і BMP (і може — у режимі
        # «Як у вихідному», тому підкладка лишається доступною).
        alpha_target = target in converter.ALPHA_FORMATS
        state = "disabled" if alpha_target else "normal"
        self._background_menu.configure(state=state)
        self._background_hint.configure(
            text=(
                "прозорість зберігається"
                if alpha_target
                else "фон для прозорих пікселів"
            )
        )

    def _set_quality_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self._quality_slider.configure(state=state)
        self._quality_entry.configure(state=state)

    def _on_quality_slider(self, value: float) -> None:
        if self._quality_syncing:
            return
        self._quality_syncing = True
        try:
            self._quality_var.set(str(round(value)))
        finally:
            self._quality_syncing = False

    def _on_quality_entry(self, _event=None) -> None:
        if self._quality_syncing:
            return
        text = self._quality_var.get().strip()
        try:
            value = int(text)
        except ValueError:
            value = None
        if value is None or not converter.MIN_QUALITY <= value <= converter.MAX_QUALITY:
            # Повертаємо останнє коректне значення зі слайдера.
            self._quality_var.set(str(round(self._quality_slider.get())))
            self._set_status(
                f"Якість має бути від {converter.MIN_QUALITY} до {converter.MAX_QUALITY}"
            )
            return
        self._quality_syncing = True
        try:
            self._quality_slider.set(value)
            self._quality_var.set(str(value))
        finally:
            self._quality_syncing = False

    def _on_resize_mode_change(self, _choice: str | None = None) -> None:
        mode = self._current_resize_mode()
        for frame in self._size_frames.values():
            frame.pack_forget()
        frame = self._size_frames.get(mode)
        if frame is not None:
            frame.pack(side="left")
        self._keep_aspect_check.configure(
            state="normal" if mode is ResizeMode.BOX else "disabled"
        )

    def _on_background_change(self, choice: str) -> None:
        if choice == OTHER_COLOR_LABEL:
            rgb, _hex = colorchooser.askcolor(
                color=self._background_hex,
                title="Колір підкладки",
                parent=self,
            )
            if rgb is None:
                # Користувач передумав — повертаємось до попереднього вибору.
                self._background_menu.set(self._background_name(self._background_hex))
                return
            self._background_hex = _hex
            self._background_menu.set(OTHER_COLOR_LABEL)
            self._background_hint.configure(text=f"Підкладка: {_hex}")
            return

        self._background_hex = BACKGROUND_CHOICES[choice]
        self._on_format_change()

    def _background_name(self, color: str) -> str:
        for name, value in BACKGROUND_CHOICES.items():
            if value.upper() == color.upper():
                return name
        return OTHER_COLOR_LABEL

    def _set_output_dir(self, path: Path | None) -> None:
        """Запам'ятовує папку результатів; None — поруч з оригіналами."""
        self._output_dir = path
        self._use_source_folder = path is None
        self._output_text.set(str(path) if path is not None else SAME_FOLDER_TEXT)
        self._reset_output_button.configure(
            state="disabled" if path is None else "normal"
        )

    def _choose_output_dir(self) -> None:
        chosen = filedialog.askdirectory(
            parent=self,
            title=CHOOSE_OUTPUT_TITLE,
            mustexist=True,
            initialdir=str(self._output_dir) if self._output_dir else None,
        )
        if not chosen:
            return
        self._set_output_dir(Path(chosen))
        self._set_status(f"Папка результатів: {chosen}")

    def _reset_output_dir(self) -> None:
        self._set_output_dir(None)
        self._set_status("Результати зберігатимуться поруч з оригіналами")

    def _collect_options(self) -> ImageOptions:
        """Збирає налаштування з інтерфейсу; ValueError — з текстом для статусу."""
        mode = self._current_resize_mode()
        box = None
        if mode is ResizeMode.BOX:
            box = (
                self._parse_number(self._box_width_var.get(), "Ширина", 1, 100000),
                self._parse_number(self._box_height_var.get(), "Висота", 1, 100000),
            )
        return ImageOptions(
            target=self._current_target(),
            quality=self._parse_number(
                self._quality_var.get(),
                "Якість",
                converter.MIN_QUALITY,
                converter.MAX_QUALITY,
            ),
            resize=mode,
            longest_side=self._parse_number(
                self._longest_side_var.get(), "Довша сторона", 1, 100000
            ),
            percent=self._parse_number(self._percent_var.get(), "Відсоток", 1, 100),
            box=box,
            keep_aspect=self._keep_aspect_var.get(),
            allow_upscale=not self._no_upscale_var.get(),
            background=self._background_hex,
        )

    @staticmethod
    def _parse_number(text: str, name: str, minimum: int, maximum: int) -> int:
        try:
            value = int(str(text).strip())
        except ValueError as exc:
            raise ValueError(f"{name}: потрібне ціле число") from exc
        if not minimum <= value <= maximum:
            raise ValueError(f"{name}: припустимо від {minimum} до {maximum}")
        return value

    # --- конвертер: запуск і прогрес ----------------------------------------

    def _start_conversion(self) -> None:
        if self._converter_running:
            return

        sources = [path for path in self._converter_files if converter.is_supported_image(path)]
        self._skipped_unsupported = len(self._converter_files) - len(sources)
        if not sources:
            self._set_status(
                "Немає файлів для конвертації — додайте PNG, JPG, WebP або BMP"
            )
            return

        try:
            options = self._collect_options()
        except ValueError as exc:
            self._set_status(f"Перевірте налаштування: {exc}")
            return

        output_dir = None
        if not self._use_source_folder:
            output_dir = self._output_dir
            if output_dir is None or not output_dir.is_dir():
                self._set_status("Виберіть існуючу папку для результатів")
                return

        self._cancel_event.clear()
        self._last_output_dir = None
        self._conversion_total = len(sources)
        self._set_converter_busy(True)
        self._progress_bar.set(0)
        self._progress_label.configure(text=f"Оброблено 0 з {len(sources)}")
        self._set_status(f"Конвертація: {len(sources)} файлів…")

        thread = threading.Thread(
            target=self._conversion_worker,
            args=(sources, options, output_dir),
            daemon=True,
        )
        thread.start()
        self.after(PROGRESS_POLL_MS, self._poll_conversion_queue)

    def _conversion_worker(
        self,
        sources: list[Path],
        options: ImageOptions,
        output_dir: Path | None,
    ) -> None:
        """Виконується у фоновому потоці й лише кладе події в чергу."""
        try:
            results = converter.convert_batch(
                sources,
                options,
                output_dir,
                on_progress=self._report_progress,
                should_cancel=self._cancel_event.is_set,
            )
        except Exception as exc:  # несподівана помилка не має «вбити» інтерфейс
            self._queue.put(("error", str(exc)))
            return
        self._queue.put(("done", results))

    def _report_progress(self, done: int, total: int, source: Path | None) -> None:
        self._queue.put(("progress", done, total, source))

    def _poll_conversion_queue(self) -> None:
        finished = False
        while True:
            try:
                event = self._queue.get_nowait()
            except queue.Empty:
                break
            kind = event[0]
            if kind == "progress":
                _, done, total, source = event
                self._progress_bar.set(done / total if total else 0)
                text = f"Оброблено {done} з {total}"
                if source is not None:
                    text += f": {source.name}"
                self._progress_label.configure(text=text)
            elif kind == "done":
                self._finish_conversion(event[1])
                finished = True
            elif kind == "error":
                self._set_converter_busy(False)
                self._set_status(f"Помилка конвертації: {event[1]}")
                finished = True

        if not finished:
            self.after(PROGRESS_POLL_MS, self._poll_conversion_queue)

    def _finish_conversion(self, results: list[converter.ConversionResult]) -> None:
        self._set_converter_busy(False)
        cancelled = self._cancel_event.is_set()
        total = max(self._conversion_total, len(results))
        succeeded = [result for result in results if result.ok]
        failed = [result for result in results if not result.ok]

        self._progress_bar.set(len(results) / total if total else 0)
        self._progress_label.configure(text=f"Оброблено {len(results)} з {total}")
        if succeeded:
            self._last_output_dir = succeeded[-1].destination.parent
            self._open_folder_button.configure(state="normal")
        if failed:
            self._show_failures(failed)

        if cancelled:
            summary = f"Скасовано: оброблено {len(results)} з {total}"
        else:
            summary = f"Готово: {len(succeeded)} з {total}"
        if failed:
            summary += f", помилок: {len(failed)}"
        if self._skipped_unsupported:
            summary += f", пропущено непідтримуваних: {self._skipped_unsupported}"
        self._set_status(summary)

    def _show_failures(self, failed: list[converter.ConversionResult]) -> None:
        lines = [f"• {result.source.name}: {result.message}" for result in failed[:MAX_FAILURE_LINES]]
        if len(failed) > MAX_FAILURE_LINES:
            lines.append(f"…та ще {len(failed) - MAX_FAILURE_LINES}")
        messagebox.showwarning("Не вдалося конвертувати", "\n".join(lines), parent=self)

    def _cancel_conversion(self) -> None:
        if not self._converter_running:
            return
        self._cancel_event.set()
        self._cancel_button.configure(state="disabled")
        self._set_status("Скасування… дочекайтесь завершення поточного файлу")

    def _set_converter_busy(self, busy: bool) -> None:
        self._converter_running = busy
        state = "disabled" if busy else "normal"
        for widget in (
            self._choose_files_button,
            self._clear_files_button,
            self._convert_button,
            self._format_menu,
            self._resize_menu,
            self._background_menu,
            self._browse_output_button,
            self._keep_aspect_check,
            self._no_upscale_check,
        ):
            widget.configure(state=state)
        self._cancel_button.configure(state="normal" if busy else "disabled")

        if busy:
            self._set_quality_enabled(False)
            self._output_entry.configure(state="disabled")
            self._reset_output_button.configure(state="disabled")
        else:
            self._on_format_change()
            self._on_resize_mode_change()
            self._output_entry.configure(state="disabled")
            self._reset_output_button.configure(
                state="disabled" if self._use_source_folder else "normal"
            )

    def _open_output_folder(self) -> None:
        folder = self._last_output_dir
        if folder is None or not folder.is_dir():
            self._set_status("Папка з результатами ще не готова")
            return
        try:
            os.startfile(folder)  # type: ignore[attr-defined]
        except OSError as exc:
            self._set_status(f"Не вдалося відкрити папку: {exc}")

    def _reset_conversion_progress(self) -> None:
        self._conversion_total = 0
        self._progress_bar.set(0)
        self._progress_label.configure(text="Оброблено 0 з 0")
        self._last_output_dir = None
        self._open_folder_button.configure(state="disabled")

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
            color = None
            if isinstance(entry, tuple):
                text, color = entry
            elif isinstance(entry, str):
                text = entry
            else:
                text = f"{index}. {entry.name}"
            ctk.CTkLabel(
                container,
                text=text,
                anchor="w",
                text_color=color,
            ).pack(fill="x", padx=8, pady=2)

    def _set_status(self, message: str) -> None:
        self.status_label.configure(text=message)

    def _centre_window(self) -> None:
        """Підганяє вікно під вміст і екран та центрує його."""
        self.update_idletasks()
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()

        # winfo_req* і wm_geometry працюють в однакових одиницях Tk,
        # тому вікно вміщає вміст незалежно від DPI-масштабу.
        width = min(max(self.winfo_reqwidth(), WINDOW_SIZE[0]), screen_width - 40)
        height = min(max(self.winfo_reqheight(), WINDOW_SIZE[1]), screen_height - 80)

        tkinter.Wm.wm_minsize(
            self, min(MIN_SIZE[0], width), min(MIN_SIZE[1], height)
        )
        x = max((screen_width - width) // 2, 0)
        y = max((screen_height - height) // 3, 0)
        tkinter.Wm.wm_geometry(self, f"{width}x{height}+{x}+{y}")
