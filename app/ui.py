"""Головне вікно File Toolkit: вкладки «Конвертер», «Дані» і «Архіватор»."""

from __future__ import annotations

import os
import queue
import threading
import tkinter
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox

import customtkinter as ctk

from app import archive, converter, data_converter
from app.archive import ArchiveResult, ExtractOptions, ExtractResult, ZipOptions
from app.converter import ImageOptions, ResizeMode, TargetFormat
from app.data_converter import DataOptions, OutputFormat, TxtLayout

WINDOW_TITLE = "File Toolkit — офлайн конвертер та архіватор"
WINDOW_SIZE = (980, 700)
MIN_SIZE = (820, 600)

CONVERTER_TAB = "Конвертер"
DATA_TAB = "Дані"
ARCHIVE_TAB = "Архіватор"

SELECT_FILES_TITLE = "Вибір файлів"
SELECT_DATA_FILES_TITLE = "Вибір файлів даних"
ADD_FILES_TITLE = "Вибір файлів для архіву"
ADD_FOLDER_TITLE = "Вибір папки для архіву"
CHOOSE_OUTPUT_TITLE = "Папка для результатів"

FILE_FILTER = [("Усі файли", "*.*")]
IMAGE_FILTER = [
    ("Зображення", "*.png *.jpg *.jpeg *.webp *.bmp"),
    ("Усі файли", "*.*"),
]
DATA_FILTER = [
    ("Дані", "*.json *.csv *.txt"),
    ("JSON", "*.json"),
    ("CSV", "*.csv"),
    ("TXT", "*.txt"),
    ("Усі файли", "*.*"),
]

DATA_TARGET_LABELS = {
    fmt: data_converter.OUTPUT_FORMAT_LABELS[fmt] for fmt in OutputFormat
}

# «Авто» для файлу — визначити самому (Sniffer для CSV, табуляція для TXT),
# для результату — кома для CSV і табуляція для TXT.
DELIMITER_CHOICES: dict[str, str | None] = {
    "Авто": None,
    "Кома": ",",
    "Крапка з комою": ";",
    "Табуляція": "\t",
    "Риска": "|",
}
INPUT_ENCODING_CHOICES = {
    "Авто": data_converter.AUTO_ENCODING,
    "UTF-8": "utf-8",
    "UTF-8 з BOM": "utf-8-sig",
    "Windows-1251": "cp1251",
}
OUTPUT_ENCODING_CHOICES = {
    "UTF-8": "utf-8",
    "UTF-8 з BOM": "utf-8-sig",
    "Windows-1251": "cp1251",
}
NEWLINE_CHOICES = {
    "LF (Unix)": "\n",
    "CRLF (Windows)": "\r\n",
}
JSON_INDENT_CHOICES = {
    "Без відступів": 0,
    "2 пробіли": 2,
    "4 пробіли": 4,
    "8 пробілів": 8,
}
TXT_LAYOUT_CHOICES = {
    "Вирівняний": TxtLayout.ALIGNED,
    "З роздільником": TxtLayout.DELIMITED,
}

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
DATA_SETTINGS_LABEL_WIDTH = 160
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
        self._data_files: list[Path] = []
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

        # Окремий стан вкладки «Дані».
        self._data_queue: queue.Queue = queue.Queue()
        self._data_cancel_event = threading.Event()
        self._data_running = False
        self._data_output_dir: Path | None = None
        self._data_last_output_dir: Path | None = None
        self._data_use_source_folder = True
        self._data_skipped_unsupported = 0
        self._data_total = 0

        # Окремий стан вкладки «Архіватор».
        self._archive_queue: queue.Queue = queue.Queue()
        self._archive_cancel_event = threading.Event()
        self._archive_running = False
        self._archive_output_dir: Path | None = None
        self._archive_last_output_dir: Path | None = None
        self._archive_use_source_folder = True
        self._archive_total = 0
        self._archive_zip_name_manually_edited = False

        # Стан розпаковки.
        self._archive_mode = "create"  # create | extract
        self._extract_archive_path: Path | None = None
        self._extract_entries: list = []
        self._extract_output_dir: Path | None = None
        self._extract_use_default_dir = True
        self._extract_queue: queue.Queue = queue.Queue()
        self._extract_cancel_event = threading.Event()
        self._extract_running = False
        self._extract_total = 0
        self._extract_last_output_dir: Path | None = None

        self._build_layout()
        self._refresh_converter_list()
        self._refresh_data_list()
        self._refresh_archive_list()
        self._on_format_change()
        self._on_resize_mode_change()
        self._refresh_data_controls()
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
        self._build_data_tab(self.tabs.add(DATA_TAB))
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

    def _row_label(
        self, parent: ctk.CTkFrame, text: str, width: int = SETTINGS_LABEL_WIDTH
    ) -> ctk.CTkLabel:
        label = ctk.CTkLabel(parent, text=text, width=width, anchor="w")
        label.pack(side="left")
        return label

    def _build_data_tab(self, tab: ctk.CTkFrame) -> None:
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(3, weight=1)

        toolbar = ctk.CTkFrame(tab, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(4, 8))

        self._data_choose_button = ctk.CTkButton(
            toolbar, text="Вибрати файли", command=self._choose_data_files
        )
        self._data_choose_button.pack(side="left")
        self._data_clear_button = ctk.CTkButton(
            toolbar,
            text="Очистити",
            command=self._clear_data_files,
            fg_color="gray30",
            hover_color="gray25",
        )
        self._data_clear_button.pack(side="left", padx=(8, 0))

        self._build_data_settings(tab)

        self._data_counter = ctk.CTkLabel(tab, text="", anchor="w")
        self._data_counter.grid(row=2, column=0, sticky="ew", pady=(0, 6))

        self._data_list = ctk.CTkScrollableFrame(
            tab, label_text="Вибрані файли даних", height=90
        )
        self._data_list.grid(row=3, column=0, sticky="nsew")

        self._build_data_progress(tab)

    def _build_data_settings(self, tab: ctk.CTkFrame) -> None:
        settings = ctk.CTkFrame(tab)
        settings.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        # Рядок 1: формат результату та налаштування JSON.
        format_row = self._settings_row(settings)
        self._row_label(
            format_row, "Формат результату:", DATA_SETTINGS_LABEL_WIDTH
        )
        self._data_format_menu = ctk.CTkOptionMenu(
            format_row,
            values=list(DATA_TARGET_LABELS.values()),
            width=140,
            command=self._on_data_format_change,
        )
        self._data_format_menu.set(DATA_TARGET_LABELS[OutputFormat.JSON])
        self._data_format_menu.pack(side="left", padx=(0, 16))

        ctk.CTkLabel(format_row, text="Відступ JSON:", width=120, anchor="w").pack(
            side="left"
        )
        self._data_indent_menu = ctk.CTkOptionMenu(
            format_row, values=list(JSON_INDENT_CHOICES), width=130
        )
        self._data_indent_menu.set("2 пробіли")
        self._data_indent_menu.pack(side="left", padx=(0, 16))

        self._data_sort_var = ctk.BooleanVar(value=False)
        self._data_sort_check = ctk.CTkCheckBox(
            format_row,
            text="Сортувати ключі",
            variable=self._data_sort_var,
            onvalue=True,
            offvalue=False,
        )
        self._data_sort_check.pack(side="left")

        # Рядок 2: окремі роздільники для читання і для запису.
        delimiter_row = self._settings_row(settings)
        self._row_label(
            delimiter_row, "Роздільник файлу:", DATA_SETTINGS_LABEL_WIDTH
        )
        self._data_input_delimiter_menu = ctk.CTkOptionMenu(
            delimiter_row, values=list(DELIMITER_CHOICES), width=130
        )
        self._data_input_delimiter_menu.set("Авто")
        self._data_input_delimiter_menu.pack(side="left", padx=(0, 14))

        self._row_label(
            delimiter_row, "Роздільник результату:", DATA_SETTINGS_LABEL_WIDTH
        )
        self._data_output_delimiter_menu = ctk.CTkOptionMenu(
            delimiter_row,
            values=list(DELIMITER_CHOICES),
            width=130,
            command=self._on_data_output_delimiter_change,
        )
        self._data_output_delimiter_menu.set("Авто")
        self._data_output_delimiter_menu.pack(side="left", padx=(0, 16))

        self._data_header_var = ctk.BooleanVar(value=True)
        self._data_header_check = ctk.CTkCheckBox(
            delimiter_row,
            text="Є заголовки",
            variable=self._data_header_var,
            onvalue=True,
            offvalue=False,
        )
        self._data_header_check.pack(side="left")

        # Рядок 3: кодування і переноси рядків.
        encoding_row = self._settings_row(settings)
        self._row_label(
            encoding_row, "Кодування файлу:", DATA_SETTINGS_LABEL_WIDTH
        )
        self._data_input_encoding_menu = ctk.CTkOptionMenu(
            encoding_row, values=list(INPUT_ENCODING_CHOICES), width=140
        )
        self._data_input_encoding_menu.set("Авто")
        self._data_input_encoding_menu.pack(side="left", padx=(0, 14))

        self._row_label(
            encoding_row, "Кодування результату:", DATA_SETTINGS_LABEL_WIDTH
        )
        self._data_output_encoding_menu = ctk.CTkOptionMenu(
            encoding_row, values=list(OUTPUT_ENCODING_CHOICES), width=140
        )
        self._data_output_encoding_menu.set("UTF-8")
        self._data_output_encoding_menu.pack(side="left", padx=(0, 16))

        ctk.CTkLabel(encoding_row, text="Переноси:", width=90, anchor="w").pack(
            side="left"
        )
        self._data_newline_menu = ctk.CTkOptionMenu(
            encoding_row, values=list(NEWLINE_CHOICES), width=120
        )
        self._data_newline_menu.set("LF (Unix)")
        self._data_newline_menu.pack(side="left")

        # Рядок 4: вигляд TXT, типи та папка призначення.
        folder_row = self._settings_row(settings)
        self._row_label(folder_row, "Вигляд TXT:", DATA_SETTINGS_LABEL_WIDTH)
        self._data_txt_layout_menu = ctk.CTkOptionMenu(
            folder_row,
            values=list(TXT_LAYOUT_CHOICES),
            width=140,
            command=self._on_data_txt_layout_change,
        )
        self._data_txt_layout_menu.set("Вирівняний")
        self._data_txt_layout_menu.pack(side="left", padx=(0, 16))

        self._data_types_var = ctk.BooleanVar(value=False)
        self._data_types_check = ctk.CTkCheckBox(
            folder_row,
            text="Визначати типи",
            variable=self._data_types_var,
            onvalue=True,
            offvalue=False,
        )
        self._data_types_check.pack(side="left", padx=(0, 16))

        ctk.CTkLabel(folder_row, text="Папка:", width=70, anchor="w").pack(
            side="left"
        )
        self._data_output_text = ctk.StringVar(value=SAME_FOLDER_TEXT)
        self._data_output_entry = ctk.CTkEntry(
            folder_row, textvariable=self._data_output_text, state="disabled", width=120
        )
        self._data_output_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._data_browse_output_button = ctk.CTkButton(
            folder_row,
            text="Оглянути…",
            width=100,
            command=self._choose_data_output_dir,
            fg_color="gray30",
            hover_color="gray25",
        )
        self._data_browse_output_button.pack(side="left")
        self._data_reset_output_button = ctk.CTkButton(
            folder_row,
            text="Скинути",
            width=90,
            command=self._reset_data_output_dir,
            state="disabled",
            fg_color="gray30",
            hover_color="gray25",
        )
        self._data_reset_output_button.pack(side="left", padx=(8, 0))

    def _build_data_progress(self, tab: ctk.CTkFrame) -> None:
        progress_frame = ctk.CTkFrame(tab, fg_color="transparent")
        progress_frame.grid(row=4, column=0, sticky="ew", pady=(10, 6))

        self._data_progress_bar = ctk.CTkProgressBar(progress_frame, height=10)
        self._data_progress_bar.set(0)
        self._data_progress_bar.pack(side="left", fill="x", expand=True, padx=(0, 12))

        self._data_progress_label = ctk.CTkLabel(
            progress_frame, text="Оброблено 0 з 0", anchor="e", width=240
        )
        self._data_progress_label.pack(side="left")

        actions = ctk.CTkFrame(tab, fg_color="transparent")
        actions.grid(row=5, column=0, sticky="ew")

        self._data_convert_button = ctk.CTkButton(
            actions, text="Конвертувати", command=self._start_data_conversion
        )
        self._data_convert_button.pack(side="left")

        self._data_cancel_button = ctk.CTkButton(
            actions,
            text="Скасувати",
            command=self._cancel_data_conversion,
            state="disabled",
            fg_color="gray30",
            hover_color="gray25",
        )
        self._data_cancel_button.pack(side="left", padx=(8, 0))

        self._data_open_folder_button = ctk.CTkButton(
            actions,
            text="Відкрити папку",
            command=self._open_data_output_folder,
            state="disabled",
            fg_color="gray30",
            hover_color="gray25",
        )
        self._data_open_folder_button.pack(side="right")

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
        tab.grid_rowconfigure(1, weight=1)

        mode_frame = ctk.CTkFrame(tab, fg_color="transparent")
        mode_frame.grid(row=0, column=0, sticky="ew", pady=(4, 8))
        self._archive_mode_var = ctk.StringVar(value="Створити ZIP")
        self._archive_mode_menu = ctk.CTkOptionMenu(
            mode_frame,
            values=["Створити ZIP", "Розпакувати"],
            variable=self._archive_mode_var,
            command=self._on_archive_mode_change,
            width=160,
        )
        self._archive_mode_menu.pack(side="left")

        self._archive_create_container = ctk.CTkFrame(tab, fg_color="transparent")
        self._archive_create_container.grid(row=1, column=0, sticky="nsew")
        self._archive_create_container.grid_columnconfigure(0, weight=1)
        self._archive_create_container.grid_rowconfigure(3, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        create_toolbar = ctk.CTkFrame(self._archive_create_container, fg_color="transparent")
        create_toolbar.grid(row=0, column=0, sticky="ew", pady=(4, 8))

        self._archive_add_files_button = ctk.CTkButton(
            create_toolbar, text="Додати файли", command=self._choose_archive_files
        )
        self._archive_add_files_button.pack(side="left")
        self._archive_add_folder_button = ctk.CTkButton(
            create_toolbar, text="Додати папку", command=self._choose_archive_folder
        )
        self._archive_add_folder_button.pack(side="left", padx=(8, 0))
        self._archive_clear_button = ctk.CTkButton(
            create_toolbar,
            text="Очистити",
            command=self._clear_archive_items,
            fg_color="gray30",
            hover_color="gray25",
        )
        self._archive_clear_button.pack(side="left", padx=(8, 0))

        self._build_archive_settings(self._archive_create_container)

        self._archive_counter = ctk.CTkLabel(self._archive_create_container, text="", anchor="w")
        self._archive_counter.grid(row=2, column=0, sticky="ew", pady=(0, 6))

        self._archive_list = ctk.CTkScrollableFrame(
            self._archive_create_container, label_text="Файли та папки для архіву", height=90
        )
        self._archive_list.grid(row=3, column=0, sticky="nsew")

        self._build_archive_progress(self._archive_create_container)

        # Розпаковка
        self._archive_extract_container = ctk.CTkFrame(tab, fg_color="transparent")
        self._archive_extract_container.grid(row=1, column=0, sticky="nsew")
        self._archive_extract_container.grid_columnconfigure(0, weight=1)
        self._archive_extract_container.grid_rowconfigure(3, weight=1)
        self._archive_extract_container.grid_remove()
        tab.grid_rowconfigure(1, weight=1)

        extract_toolbar = ctk.CTkFrame(self._archive_extract_container, fg_color="transparent")
        extract_toolbar.grid(row=0, column=0, sticky="ew", pady=(4, 8))
        self._extract_choose_button = ctk.CTkButton(
            extract_toolbar, text="Вибрати архів", command=self._choose_extract_archive
        )
        self._extract_choose_button.pack(side="left")
        self._extract_clear_button = ctk.CTkButton(
            extract_toolbar,
            text="Очистити",
            command=self._clear_extract_archive,
            fg_color="gray30",
            hover_color="gray25",
        )
        self._extract_clear_button.pack(side="left", padx=(8, 0))

        extract_settings = ctk.CTkFrame(self._archive_extract_container)
        extract_settings.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        dest_row = self._settings_row(extract_settings)
        self._row_label(dest_row, "Папка призначення:")
        self._extract_output_text = ctk.StringVar(value="У нову підпапку біля архіву (за замовчуванням)")
        self._extract_output_entry = ctk.CTkEntry(
            dest_row, textvariable=self._extract_output_text, state="disabled", width=260
        )
        self._extract_output_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._extract_browse_button = ctk.CTkButton(
            dest_row,
            text="Оглянути…",
            width=100,
            command=self._choose_extract_output_dir,
            fg_color="gray30",
            hover_color="gray25",
        )
        self._extract_browse_button.pack(side="left")
        self._extract_reset_button = ctk.CTkButton(
            dest_row,
            text="Скинути",
            width=90,
            command=self._reset_extract_output_dir,
            state="disabled",
            fg_color="gray30",
            hover_color="gray25",
        )
        self._extract_reset_button.pack(side="left", padx=(8, 0))

        self._extract_counter = ctk.CTkLabel(self._archive_extract_container, text="", anchor="w")
        self._extract_counter.grid(row=2, column=0, sticky="ew", pady=(0, 6))

        self._extract_list = ctk.CTkScrollableFrame(
            self._archive_extract_container, label_text="Вміст архіву", height=90
        )
        self._extract_list.grid(row=3, column=0, sticky="nsew")
        self._archive_extract_container.grid_rowconfigure(3, weight=1)

        extract_progress = ctk.CTkFrame(self._archive_extract_container, fg_color="transparent")
        extract_progress.grid(row=4, column=0, sticky="ew", pady=(10, 6))
        self._extract_progress_bar = ctk.CTkProgressBar(extract_progress, height=10)
        self._extract_progress_bar.set(0)
        self._extract_progress_bar.pack(side="left", fill="x", expand=True, padx=(0, 12))
        self._extract_progress_label = ctk.CTkLabel(
            extract_progress, text="Оброблено 0 з 0", anchor="e", width=240
        )
        self._extract_progress_label.pack(side="left")

        extract_actions = ctk.CTkFrame(self._archive_extract_container, fg_color="transparent")
        extract_actions.grid(row=5, column=0, sticky="ew")
        self._extract_button = ctk.CTkButton(
            extract_actions, text="Розпакувати все", command=self._start_archive_extract
        )
        self._extract_button.pack(side="left")
        self._extract_cancel_button = ctk.CTkButton(
            extract_actions,
            text="Скасувати",
            command=self._cancel_archive_extract,
            state="disabled",
            fg_color="gray30",
            hover_color="gray25",
        )
        self._extract_cancel_button.pack(side="left", padx=(8, 0))
        self._extract_open_button = ctk.CTkButton(
            extract_actions,
            text="Відкрити папку",
            command=self._open_extract_output_folder,
            state="disabled",
            fg_color="gray30",
            hover_color="gray25",
        )
        self._extract_open_button.pack(side="right")

        self._on_archive_mode_change("Створити ZIP")

    def _build_archive_settings(self, tab: ctk.CTkFrame) -> None:
        settings = ctk.CTkFrame(tab)
        settings.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        # Рядок 1: ім'я архіву
        name_row = self._settings_row(settings)
        self._row_label(name_row, "Ім'я архіву:")
        self._archive_zip_name_var = ctk.StringVar(value="archive")
        self._archive_zip_name_entry = ctk.CTkEntry(
            name_row, textvariable=self._archive_zip_name_var, width=200
        )
        self._archive_zip_name_entry.pack(side="left", padx=(0, 8))
        self._archive_zip_name_entry.bind("<KeyRelease>", self._on_archive_name_changed)
        self._archive_zip_name_entry.bind("<FocusOut>", self._on_archive_name_changed)
        ctk.CTkLabel(name_row, text=".zip", anchor="w").pack(side="left")

        # Рядок 2: рівень стиснення та папка
        comp_row = self._settings_row(settings)
        self._row_label(comp_row, "Рівень стиснення:")
        self._archive_compression_var = ctk.StringVar(value="Нормальне (6)")
        self._archive_compression_menu = ctk.CTkOptionMenu(
            comp_row,
            values=["Без стиснення (0)", "Швидке (3)", "Нормальне (6)", "Максимальне (9)"],
            variable=self._archive_compression_var,
            width=170,
        )
        self._archive_compression_menu.pack(side="left", padx=(0, 18))

        self._row_label(comp_row, "Папка:")
        self._archive_use_source_folder = True
        self._archive_output_text = ctk.StringVar(value=SAME_FOLDER_TEXT)
        self._archive_output_entry = ctk.CTkEntry(
            comp_row, textvariable=self._archive_output_text, state="disabled", width=180
        )
        self._archive_output_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._archive_browse_button = ctk.CTkButton(
            comp_row,
            text="Оглянути…",
            width=100,
            command=self._choose_archive_output_dir,
            fg_color="gray30",
            hover_color="gray25",
        )
        self._archive_browse_button.pack(side="left")
        self._archive_reset_button = ctk.CTkButton(
            comp_row,
            text="Скинути",
            width=90,
            command=self._reset_archive_output_dir,
            state="disabled",
            fg_color="gray30",
            hover_color="gray25",
        )
        self._archive_reset_button.pack(side="left", padx=(8, 0))

    def _build_archive_progress(self, tab: ctk.CTkFrame) -> None:
        progress_frame = ctk.CTkFrame(tab, fg_color="transparent")
        progress_frame.grid(row=4, column=0, sticky="ew", pady=(10, 6))

        self._archive_progress_bar = ctk.CTkProgressBar(progress_frame, height=10)
        self._archive_progress_bar.set(0)
        self._archive_progress_bar.pack(side="left", fill="x", expand=True, padx=(0, 12))

        self._archive_progress_label = ctk.CTkLabel(
            progress_frame, text="Оброблено 0 з 0", anchor="e", width=240
        )
        self._archive_progress_label.pack(side="left")

        actions = ctk.CTkFrame(tab, fg_color="transparent")
        actions.grid(row=5, column=0, sticky="ew")

        self._archive_create_button = ctk.CTkButton(
            actions, text="Створити ZIP", command=self._start_archive_creation
        )
        self._archive_create_button.pack(side="left")

        self._archive_cancel_button = ctk.CTkButton(
            actions,
            text="Скасувати",
            command=self._cancel_archive_creation,
            state="disabled",
            fg_color="gray30",
            hover_color="gray25",
        )
        self._archive_cancel_button.pack(side="left", padx=(8, 0))

        self._archive_open_folder_button = ctk.CTkButton(
            actions,
            text="Відкрити папку",
            command=self._open_archive_output_folder,
            state="disabled",
            fg_color="gray30",
            hover_color="gray25",
        )
        self._archive_open_folder_button.pack(side="right")

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

    # --- дані: вибір файлів -------------------------------------------------

    def _choose_data_files(self) -> None:
        chosen = filedialog.askopenfilenames(
            parent=self, title=SELECT_DATA_FILES_TITLE, filetypes=DATA_FILTER
        )
        added = sum(
            1 for raw in chosen if self._append_path(self._data_files, Path(raw))
        )
        if not added:
            return
        self._reset_data_progress()
        self._refresh_data_list()
        self._set_status(
            f"Додано файлів даних: {added}. Усього: {len(self._data_files)}"
        )

    def _clear_data_files(self) -> None:
        if not self._data_files:
            self._set_status("Список файлів даних уже порожній")
            return
        self._data_files.clear()
        self._reset_data_progress()
        self._refresh_data_list()
        self._set_status("Список файлів даних очищено")

    def _refresh_data_list(self) -> None:
        entries: list[str | tuple[str, str]] = []
        unsupported = 0
        for index, path in enumerate(self._data_files, start=1):
            if data_converter.is_supported_data(path):
                entries.append(f"{index}. {path.name}")
            else:
                unsupported += 1
                entries.append(
                    (
                        f"{index}. {path.name} — формат не підтримується",
                        UNSUPPORTED_COLOR,
                    )
                )
        self._fill_list(self._data_list, entries)

        supported = len(self._data_files) - unsupported
        text = f"Вибрано файлів: {len(self._data_files)} (підтримується: {supported})"
        if unsupported:
            text += f", непідтримуваних: {unsupported}"
        self._data_counter.configure(text=text)

    # --- дані: налаштування -------------------------------------------------

    def _current_data_target(self) -> OutputFormat:
        label = self._data_format_menu.get()
        for fmt, fmt_label in DATA_TARGET_LABELS.items():
            if fmt_label == label:
                return fmt
        return OutputFormat.JSON

    def _current_data_txt_layout(self) -> TxtLayout:
        return TXT_LAYOUT_CHOICES.get(
            self._data_txt_layout_menu.get(), TxtLayout.ALIGNED
        )

    def _on_data_format_change(self, _choice: str | None = None) -> None:
        self._refresh_data_controls()

    def _on_data_txt_layout_change(self, _choice: str | None = None) -> None:
        self._refresh_data_controls()

    def _on_data_output_delimiter_change(self, choice: str) -> None:
        if choice == "Авто":
            self._set_status(
                "Роздільник результату «Авто»: кома для CSV, табуляція для TXT"
            )
        else:
            self._set_status(f"Роздільник результату: {choice}")

    def _refresh_data_controls(self) -> None:
        """Вмикає лише ті налаштування, які впливають на вибраний формат."""
        if self._data_running:
            return

        target = self._current_data_target()
        is_json = target is OutputFormat.JSON
        is_csv = target is OutputFormat.CSV
        is_txt = target is OutputFormat.TXT
        delimited_txt = (
            is_txt and self._current_data_txt_layout() is TxtLayout.DELIMITED
        )

        self._set_enabled(self._data_indent_menu, is_json)
        self._set_enabled(self._data_sort_check, is_json or is_txt)
        self._set_enabled(self._data_types_check, is_json)
        self._set_enabled(self._data_txt_layout_menu, is_txt)
        # Для вирівняного TXT роздільник результату не використовується.
        self._set_enabled(
            self._data_output_delimiter_menu, is_csv or delimited_txt
        )

    @staticmethod
    def _set_enabled(widget, enabled: bool) -> None:
        widget.configure(state="normal" if enabled else "disabled")

    def _collect_data_options(self) -> DataOptions:
        """Збирає налаштування вкладки «Дані»; ValueError — з текстом для статусу."""
        return DataOptions(
            target=self._current_data_target(),
            delimiter=DELIMITER_CHOICES[self._data_input_delimiter_menu.get()],
            output_delimiter=DELIMITER_CHOICES[
                self._data_output_delimiter_menu.get()
            ],
            has_header=self._data_header_var.get(),
            detect_types=self._data_types_var.get(),
            json_indent=JSON_INDENT_CHOICES[self._data_indent_menu.get()],
            sort_keys=self._data_sort_var.get(),
            txt_layout=self._current_data_txt_layout(),
            input_encoding=INPUT_ENCODING_CHOICES[
                self._data_input_encoding_menu.get()
            ],
            output_encoding=OUTPUT_ENCODING_CHOICES[
                self._data_output_encoding_menu.get()
            ],
            newline=NEWLINE_CHOICES[self._data_newline_menu.get()],
        )

    def _set_data_output_dir(self, path: Path | None) -> None:
        """Папка результатів даних; None — поруч з оригіналами."""
        self._data_output_dir = path
        self._data_use_source_folder = path is None
        self._data_output_text.set(
            str(path) if path is not None else SAME_FOLDER_TEXT
        )
        if not self._data_running:
            self._data_reset_output_button.configure(
                state="disabled" if path is None else "normal"
            )

    def _choose_data_output_dir(self) -> None:
        chosen = filedialog.askdirectory(
            parent=self,
            title=CHOOSE_OUTPUT_TITLE,
            mustexist=True,
            initialdir=str(self._data_output_dir) if self._data_output_dir else None,
        )
        if not chosen:
            return
        self._set_data_output_dir(Path(chosen))
        self._set_status(f"Папка результатів даних: {chosen}")

    def _reset_data_output_dir(self) -> None:
        self._set_data_output_dir(None)
        self._set_status("Результати даних зберігатимуться поруч з оригіналами")

    # --- дані: запуск і прогрес ---------------------------------------------

    def _start_data_conversion(self) -> None:
        if self._data_running:
            return

        sources = [
            path
            for path in self._data_files
            if data_converter.is_supported_data(path)
        ]
        self._data_skipped_unsupported = len(self._data_files) - len(sources)
        if not sources:
            self._set_status(
                "Немає файлів для конвертації — додайте JSON, CSV або TXT"
            )
            return

        try:
            options = self._collect_data_options()
        except ValueError as exc:
            self._set_status(f"Перевірте налаштування: {exc}")
            return

        output_dir = None
        if not self._data_use_source_folder:
            output_dir = self._data_output_dir
            if output_dir is None or not output_dir.is_dir():
                self._set_status("Виберіть існуючу папку для результатів")
                return

        self._data_cancel_event.clear()
        self._data_last_output_dir = None
        self._data_total = len(sources)
        self._set_data_busy(True)
        self._data_progress_bar.set(0)
        self._data_progress_label.configure(text=f"Оброблено 0 з {len(sources)}")
        self._set_status(f"Конвертація даних: {len(sources)} файлів…")

        thread = threading.Thread(
            target=self._data_worker,
            args=(sources, options, output_dir),
            daemon=True,
        )
        thread.start()
        self.after(PROGRESS_POLL_MS, self._poll_data_queue)

    def _data_worker(
        self,
        sources: list[Path],
        options: DataOptions,
        output_dir: Path | None,
    ) -> None:
        """Виконується у фоновому потоці й лише кладе події в чергу."""
        try:
            results = data_converter.convert_data_batch(
                sources,
                options,
                output_dir,
                on_progress=self._report_data_progress,
                should_cancel=self._data_cancel_event.is_set,
            )
        except Exception as exc:  # несподівана помилка не має «вбити» інтерфейс
            self._data_queue.put(("error", str(exc)))
            return
        self._data_queue.put(("done", results))

    def _report_data_progress(
        self, done: int, total: int, source: Path | None
    ) -> None:
        self._data_queue.put(("progress", done, total, source))

    def _poll_data_queue(self) -> None:
        finished = False
        while True:
            try:
                event = self._data_queue.get_nowait()
            except queue.Empty:
                break
            kind = event[0]
            if kind == "progress":
                _, done, total, source = event
                self._data_progress_bar.set(done / total if total else 0)
                text = f"Оброблено {done} з {total}"
                if source is not None:
                    text += f": {source.name}"
                self._data_progress_label.configure(text=text)
            elif kind == "done":
                self._finish_data_conversion(event[1])
                finished = True
            elif kind == "error":
                self._set_data_busy(False)
                self._set_status(f"Помилка конвертації даних: {event[1]}")
                finished = True

        if not finished:
            self.after(PROGRESS_POLL_MS, self._poll_data_queue)

    def _finish_data_conversion(
        self, results: list[data_converter.DataConversionResult]
    ) -> None:
        self._set_data_busy(False)
        cancelled = self._data_cancel_event.is_set()
        total = max(self._data_total, len(results))
        succeeded = [result for result in results if result.ok]
        failed = [result for result in results if not result.ok]

        self._data_progress_bar.set(len(results) / total if total else 0)
        self._data_progress_label.configure(text=f"Оброблено {len(results)} з {total}")
        if succeeded:
            last_destination = succeeded[-1].destination
            if last_destination is not None:
                self._data_last_output_dir = last_destination.parent
                self._data_open_folder_button.configure(state="normal")
        if failed:
            self._show_data_failures(failed)

        if cancelled:
            summary = f"Скасовано: оброблено {len(results)} з {total}"
        else:
            summary = f"Готово: {len(succeeded)} з {total}"
        if failed:
            summary += f", помилок: {len(failed)}"
        if self._data_skipped_unsupported:
            summary += f", пропущено непідтримуваних: {self._data_skipped_unsupported}"
        self._set_status(summary)

    def _show_data_failures(
        self, failed: list[data_converter.DataConversionResult]
    ) -> None:
        lines = [
            f"• {result.source.name}: {result.message}"
            for result in failed[:MAX_FAILURE_LINES]
        ]
        if len(failed) > MAX_FAILURE_LINES:
            lines.append(f"…та ще {len(failed) - MAX_FAILURE_LINES}")
        messagebox.showwarning(
            "Не вдалося конвертувати дані", "\n".join(lines), parent=self
        )

    def _cancel_data_conversion(self) -> None:
        if not self._data_running:
            return
        self._data_cancel_event.set()
        self._data_cancel_button.configure(state="disabled")
        self._set_status("Скасування… дочекайтесь завершення поточного файлу")

    def _set_data_busy(self, busy: bool) -> None:
        self._data_running = busy
        state = "disabled" if busy else "normal"
        for widget in (
            self._data_choose_button,
            self._data_clear_button,
            self._data_convert_button,
            self._data_format_menu,
            self._data_indent_menu,
            self._data_sort_check,
            self._data_input_delimiter_menu,
            self._data_output_delimiter_menu,
            self._data_header_check,
            self._data_input_encoding_menu,
            self._data_output_encoding_menu,
            self._data_newline_menu,
            self._data_txt_layout_menu,
            self._data_types_check,
            self._data_browse_output_button,
            self._data_reset_output_button,
        ):
            widget.configure(state=state)
        self._data_cancel_button.configure(state="normal" if busy else "disabled")

        if not busy:
            self._refresh_data_controls()
            self._data_reset_output_button.configure(
                state="disabled" if self._data_use_source_folder else "normal"
            )

    def _open_data_output_folder(self) -> None:
        folder = self._data_last_output_dir
        if folder is None or not folder.is_dir():
            self._set_status("Папка з результатами ще не готова")
            return
        try:
            os.startfile(folder)  # type: ignore[attr-defined]
        except OSError as exc:
            self._set_status(f"Не вдалося відкрити папку: {exc}")

    def _reset_data_progress(self) -> None:
        self._data_total = 0
        self._data_progress_bar.set(0)
        self._data_progress_label.configure(text="Оброблено 0 з 0")
        self._data_last_output_dir = None
        self._data_open_folder_button.configure(state="disabled")

    # --- архіватор: вибір файлів і папок ------------------------------------

    def _on_archive_name_changed(self, _event=None) -> None:
        if self._archive_running:
            return
        self._archive_zip_name_manually_edited = True

    def _update_archive_suggested_name(self) -> None:
        if self._archive_running:
            return
        if self._archive_zip_name_manually_edited:
            return
        if not self._archive_items:
            self._archive_zip_name_var.set("archive")
            return
        name = archive.default_zip_name(self._archive_items)
        if name.lower().endswith(".zip"):
            name = name[:-4]
        self._archive_zip_name_var.set(name)

    def _choose_archive_files(self) -> None:
        chosen = filedialog.askopenfilenames(
            parent=self, title=ADD_FILES_TITLE, filetypes=FILE_FILTER
        )
        added = sum(1 for raw in chosen if self._append_path(self._archive_items, Path(raw)))
        if not added:
            return
        self._reset_archive_progress()
        self._update_archive_suggested_name()
        self._refresh_archive_list()
        self._set_status(f"Додано до архіву: {added}. Усього: {len(self._archive_items)}")

    def _choose_archive_folder(self) -> None:
        chosen = filedialog.askdirectory(
            parent=self, title=ADD_FOLDER_TITLE, mustexist=True
        )
        if not chosen or not self._append_path(self._archive_items, Path(chosen)):
            return
        self._reset_archive_progress()
        self._update_archive_suggested_name()
        self._refresh_archive_list()
        self._set_status(
            f"Додано папку: {chosen}. Усього: {len(self._archive_items)}"
        )

    def _clear_archive_items(self) -> None:
        if not self._archive_items:
            self._set_status("Список архіву вже порожній")
            return
        self._archive_items.clear()
        self._archive_zip_name_manually_edited = False
        self._update_archive_suggested_name()
        self._reset_archive_progress()
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

    def _set_archive_output_dir(self, path: Path | None) -> None:
        self._archive_output_dir = path
        self._archive_use_source_folder = path is None
        self._archive_output_text.set(str(path) if path is not None else SAME_FOLDER_TEXT)
        if not self._archive_running:
            self._archive_reset_button.configure(
                state="disabled" if path is None else "normal"
            )

    def _choose_archive_output_dir(self) -> None:
        chosen = filedialog.askdirectory(
            parent=self,
            title=CHOOSE_OUTPUT_TITLE,
            mustexist=True,
            initialdir=str(self._archive_output_dir) if self._archive_output_dir else None,
        )
        if not chosen:
            return
        self._set_archive_output_dir(Path(chosen))
        self._set_status(f"Папка для архіву: {chosen}")

    def _reset_archive_output_dir(self) -> None:
        self._set_archive_output_dir(None)
        self._set_status("Архів зберігатиметься поруч з першим обраним елементом")

    def _get_archive_compression_level(self) -> int:
        val = self._archive_compression_var.get()
        if "0" in val:
            return 0
        if "3" in val:
            return 3
        if "9" in val:
            return 9
        return 6

    def _start_archive_creation(self) -> None:
        if self._archive_running:
            return
        if not self._archive_items:
            self._set_status("Додайте файли або папки для архівування")
            return
        zip_name = self._archive_zip_name_var.get().strip()
        if not zip_name:
            self._set_status("Вкажіть ім'я архіву")
            return
        # перевірка заборонених символів
        invalid = set('\\/:*?"<>|')
        if any(c in invalid for c in zip_name):
            self._set_status("Ім'я архіву містить недопустимі символи")
            return
        if not zip_name.lower().endswith(".zip"):
            zip_name_clean = zip_name
        else:
            zip_name_clean = zip_name[:-4]

        if self._archive_use_source_folder:
            dest_dir = self._archive_items[0].parent
        else:
            dest_dir = self._archive_output_dir
            if dest_dir is None or not dest_dir.is_dir():
                self._set_status("Виберіть існуючу папку для архіву")
                return

        try:
            options = ZipOptions(compression_level=self._get_archive_compression_level())
        except Exception as exc:
            self._set_status(f"Помилка налаштувань: {exc}")
            return

        self._archive_cancel_event.clear()
        self._archive_last_output_dir = None
        self._archive_total = len(self._archive_items)
        self._set_archive_busy(True)
        self._archive_progress_bar.set(0)
        self._archive_progress_label.configure(text="Оброблено 0 з ?")
        self._set_status(f"Створення архіву {zip_name_clean}.zip…")

        thread = threading.Thread(
            target=self._archive_worker,
            args=(list(self._archive_items), dest_dir, zip_name_clean, options),
            daemon=True,
        )
        thread.start()
        self.after(PROGRESS_POLL_MS, self._poll_archive_queue)

    def _archive_worker(
        self,
        sources: list[Path],
        dest_dir: Path,
        zip_name: str,
        options: ZipOptions,
    ) -> None:
        try:
            results = archive.create_zip(
                sources,
                dest_dir,
                zip_name,
                options,
                on_progress=self._report_archive_progress,
                should_cancel=self._archive_cancel_event.is_set,
            )
        except Exception as exc:
            self._archive_queue.put(("error", str(exc)))
            return
        self._archive_queue.put(("done", results))

    def _report_archive_progress(self, done: int, total: int, source: Path | None) -> None:
        self._archive_queue.put(("progress", done, total, source))

    def _poll_archive_queue(self) -> None:
        finished = False
        while True:
            try:
                event = self._archive_queue.get_nowait()
            except queue.Empty:
                break
            kind = event[0]
            if kind == "progress":
                _, done, total, source = event
                if total:
                    self._archive_progress_bar.set(done / total)
                text = f"Оброблено {done}" if not total else f"Оброблено {done} з {total}"
                if source is not None:
                    try:
                        text += f": {Path(source).name}"
                    except Exception:
                        pass
                self._archive_progress_label.configure(text=text)
            elif kind == "done":
                self._finish_archive_creation(event[1])
                finished = True
            elif kind == "error":
                self._set_archive_busy(False)
                self._set_status(f"Помилка архівування: {event[1]}")
                finished = True
        if not finished:
            self.after(PROGRESS_POLL_MS, self._poll_archive_queue)

    def _finish_archive_creation(self, results: list[ArchiveResult]) -> None:
        self._set_archive_busy(False)
        cancelled = self._archive_cancel_event.is_set()
        succeeded = [r for r in results if r.ok and r.destination is not None and r.source is None]
        failed = [r for r in results if not r.ok]
        skipped = failed  # файли що не вдалось прочитати/записати

        # оновлюємо прогрес
        total = max(self._archive_total, len(results))
        self._archive_progress_bar.set(1.0)
        self._archive_progress_label.configure(text=f"Готово: {len(results)}")

        if succeeded:
            dest = succeeded[-1].destination
            if dest is not None:
                self._archive_last_output_dir = dest.parent
                self._archive_open_folder_button.configure(state="normal")
        if skipped:
            self._show_archive_failures(skipped)

        if cancelled:
            summary = "Скасовано"
        else:
            summary = "Готово"
        if succeeded:
            summary += f": архів створено ({succeeded[-1].destination.name if succeeded[-1].destination else ''})"
        if skipped:
            summary += f", пропущено: {len(skipped)}"
        self._set_status(summary.strip())

    def _show_archive_failures(self, failed: list[ArchiveResult]) -> None:
        lines = []
        for r in failed[:MAX_FAILURE_LINES]:
            name = r.source.name if r.source else "?"
            msg = r.message or "Помилка"
            lines.append(f"• {name}: {msg}")
        if len(failed) > MAX_FAILURE_LINES:
            lines.append(f"…та ще {len(failed) - MAX_FAILURE_LINES}")
        messagebox.showwarning("Пропущені файли", "\n".join(lines), parent=self)

    def _cancel_archive_creation(self) -> None:
        if not self._archive_running:
            return
        self._archive_cancel_event.set()
        self._archive_cancel_button.configure(state="disabled")
        self._set_status("Скасування… дочекайтесь завершення")

    def _set_archive_busy(self, busy: bool) -> None:
        self._archive_running = busy
        state = "disabled" if busy else "normal"
        for widget in (
            self._archive_add_files_button,
            self._archive_add_folder_button,
            self._archive_clear_button,
            self._archive_zip_name_entry,
            self._archive_compression_menu,
            self._archive_browse_button,
            self._archive_reset_button,
        ):
            widget.configure(state=state)
        self._archive_create_button.configure(state="disabled" if busy else "normal")
        self._archive_cancel_button.configure(state="normal" if busy else "disabled")
        if not busy:
            self._archive_reset_button.configure(
                state="disabled" if self._archive_use_source_folder else "normal"
            )

    def _open_archive_output_folder(self) -> None:
        folder = self._archive_last_output_dir
        if folder is None or not folder.is_dir():
            self._set_status("Папка з архівом ще не готова")
            return
        try:
            os.startfile(folder)  # type: ignore[attr-defined]
        except OSError as exc:
            self._set_status(f"Не вдалося відкрити папку: {exc}")

    def _reset_archive_progress(self) -> None:
        self._archive_total = 0
        self._archive_progress_bar.set(0)
        self._archive_progress_label.configure(text="Оброблено 0 з 0")
        self._archive_last_output_dir = None
        self._archive_open_folder_button.configure(state="disabled")

    # --- архіватор: розпаковка -----------------------------------------------
    def _on_archive_mode_change(self, choice: str | None = None) -> None:
        if choice is None:
            choice = self._archive_mode_var.get()
        if choice == "Розпакувати":
            self._archive_mode = "extract"
            self._archive_create_container.grid_remove()
            self._archive_extract_container.grid()
        else:
            self._archive_mode = "create"
            self._archive_extract_container.grid_remove()
            self._archive_create_container.grid()
        self._set_status("Режим: " + choice)

    def _choose_extract_archive(self) -> None:
        chosen = filedialog.askopenfilename(
            parent=self,
            title="Вибір архіву для розпаковки",
            filetypes=[
                ("Архіви", "*.zip *.tar *.tar.gz *.tgz *.tar.bz2 *.tbz2 *.tar.xz *.txz *.7z"),
                ("ZIP", "*.zip"),
                ("TAR", "*.tar"),
                ("GZIP", "*.tar.gz *.tgz"),
                ("BZIP2", "*.tar.bz2 *.tbz2"),
                ("XZ", "*.tar.xz *.txz"),
                ("7z", "*.7z"),
                ("Усі файли", "*.*"),
            ],
        )
        if not chosen:
            return
        path = Path(chosen)
        if not archive.is_supported_extract_archive(path):
            self._set_status("Непідтримуваний формат архіву")
            messagebox.showwarning("Помилка", "Непідтримуваний формат архіву", parent=self)
            return
        try:
            entries = archive.list_archive(path)
        except Exception as exc:
            self._set_status(f"Помилка: {exc}")
            messagebox.showwarning("Помилка", str(exc), parent=self)
            return
        self._extract_archive_path = path
        self._extract_entries = list(entries)
        self._extract_use_default_dir = True
        self._extract_output_dir = None
        self._extract_output_text.set("У нову підпапку біля архіву (за замовчуванням)")
        self._extract_reset_button.configure(state="disabled")
        self._reset_extract_progress()
        self._refresh_extract_list()
        self._set_status(f"Обрано архів: {path.name}")
        self._extract_open_button.configure(state="disabled")

    def _clear_extract_archive(self) -> None:
        self._extract_archive_path = None
        self._extract_entries = []
        self._extract_use_default_dir = True
        self._extract_output_dir = None
        self._extract_output_text.set("У нову підпапку біля архіву (за замовчуванням)")
        self._extract_reset_button.configure(state="disabled")
        self._reset_extract_progress()
        self._refresh_extract_list()
        self._set_status("Архів очищено")

    def _refresh_extract_list(self) -> None:
        entries = []
        for e in self._extract_entries:
            if e.is_dir:
                entries.append(f"[папка] {e.name}")
            else:
                sz = e.size
                entries.append(f"[файл] {e.name} ({sz} байт)")
        if not entries and self._extract_archive_path is not None:
            entries = ["(порожній архів або немає файлів)"]
        elif not entries:
            entries = []
        self._fill_list(self._extract_list, entries)
        count = len([e for e in self._extract_entries if not e.is_dir])
        self._extract_counter.configure(text=f"Файлів у архіві: {count}, записів: {len(self._extract_entries)}")

    def _set_extract_output_dir(self, path: Path | None) -> None:
        self._extract_output_dir = path
        self._extract_use_default_dir = path is None
        if path is None:
            self._extract_output_text.set("У нову підпапку біля архіву (за замовчуванням)")
        else:
            self._extract_output_text.set(str(path))
        if not self._extract_running:
            self._extract_reset_button.configure(state="disabled" if path is None else "normal")

    def _choose_extract_output_dir(self) -> None:
        chosen = filedialog.askdirectory(parent=self, title=CHOOSE_OUTPUT_TITLE, mustexist=True)
        if not chosen:
            return
        self._set_extract_output_dir(Path(chosen))
        self._set_status(f"Папка для розпаковки: {chosen}")

    def _reset_extract_output_dir(self) -> None:
        self._set_extract_output_dir(None)
        self._set_status("Розпаковуватиметься у нову підпапку з ім'ям архіву")

    def _start_archive_extract(self) -> None:
        if self._extract_running:
            return
        if not self._extract_archive_path or not self._extract_archive_path.exists():
            self._set_status("Виберіть архів для розпаковки")
            return
        if self._extract_use_default_dir:
            dest_dir = self._extract_archive_path.parent
        else:
            dest_dir = self._extract_output_dir
            if dest_dir is None or not dest_dir.is_dir():
                self._set_status("Виберіть існуючу папку для розпаковки")
                return
        self._extract_cancel_event.clear()
        self._extract_last_output_dir = None
        self._extract_total = len([e for e in self._extract_entries if not e.is_dir]) or len(self._extract_entries)
        self._set_extract_busy(True)
        self._extract_progress_bar.set(0)
        self._extract_progress_label.configure(text=f"Оброблено 0 з {self._extract_total}")
        self._set_status(f"Розпаковка {self._extract_archive_path.name}…")
        thread = threading.Thread(
            target=self._extract_worker,
            args=(self._extract_archive_path, dest_dir),
            daemon=True,
        )
        thread.start()
        self.after(PROGRESS_POLL_MS, self._poll_extract_queue)

    def _extract_worker(self, source: Path, dest_dir: Path) -> None:
        try:
            results = archive.extract_archive(
                source,
                dest_dir,
                options=ExtractOptions(),
                on_progress=self._report_extract_progress,
                should_cancel=self._extract_cancel_event.is_set,
            )
        except Exception as exc:
            self._extract_queue.put(("error", str(exc)))
            return
        self._extract_queue.put(("done", results))

    def _report_extract_progress(self, done: int, total: int, source: Path | None) -> None:
        self._extract_queue.put(("progress", done, total, source))

    def _poll_extract_queue(self) -> None:
        finished = False
        while True:
            try:
                event = self._extract_queue.get_nowait()
            except queue.Empty:
                break
            kind = event[0]
            if kind == "progress":
                _, done, total, source = event
                if total:
                    self._extract_progress_bar.set(done / total)
                text = f"Оброблено {done}" if not total else f"Оброблено {done} з {total}"
                if source is not None:
                    try:
                        text += f": {Path(source).name}"
                    except Exception:
                        pass
                self._extract_progress_label.configure(text=text)
            elif kind == "done":
                self._finish_archive_extract(event[1])
                finished = True
            elif kind == "error":
                self._set_extract_busy(False)
                self._set_status(f"Помилка розпаковки: {event[1]}")
                messagebox.showwarning("Помилка", str(event[1]), parent=self)
                finished = True
        if not finished:
            self.after(PROGRESS_POLL_MS, self._poll_extract_queue)

    def _finish_archive_extract(self, results: list[ExtractResult]) -> None:
        self._set_extract_busy(False)
        cancelled = self._extract_cancel_event.is_set()
        succeeded = [r for r in results if r.ok and r.destination is not None]
        failed = [r for r in results if not r.ok]
        skipped = [r for r in failed if r.entry is None or "пропущено" in (r.message or "").lower()]
        others = [r for r in failed if r not in skipped]

        total = max(self._extract_total, len([r for r in results if r.ok]) + len(failed))
        self._extract_progress_bar.set(1.0)
        self._extract_progress_label.configure(text=f"Готово: {len(succeeded)} файлів")

        if succeeded:
            dest = succeeded[-1].destination
            if dest is not None:
                self._extract_last_output_dir = dest.parent
                self._extract_open_button.configure(state="normal")
        if others or skipped:
            self._show_extract_failures(results)
        if cancelled:
            summary = "Скасовано"
        else:
            summary = "Готово"
        summary += f": розпаковано {len(succeeded)}"
        if others:
            summary += f", помилок: {len(others)}"
        if skipped:
            summary += f", пропущено: {len(skipped)}"
        self._set_status(summary.strip())

    def _show_extract_failures(self, results: list[ExtractResult]) -> None:
        lines = []
        for r in results:
            if r.ok:
                continue
            if r.entry is None and r.message:
                lines.append(f"• {r.message}")
                continue
            name = r.entry.name if r.entry else (r.destination.name if r.destination else "?")
            msg = r.message or "Помилка"
            lines.append(f"• {name}: {msg}")
        if not lines:
            return
        if len(lines) > MAX_FAILURE_LINES:
            lines = lines[:MAX_FAILURE_LINES] + [f"…та ще {len(lines) - MAX_FAILURE_LINES}"]
        messagebox.showwarning("Результат розпаковки", "\n".join(lines), parent=self)

    def _cancel_archive_extract(self) -> None:
        if not self._extract_running:
            return
        self._extract_cancel_event.set()
        self._extract_cancel_button.configure(state="disabled")
        self._set_status("Скасування… дочекайтесь завершення")

    def _set_extract_busy(self, busy: bool) -> None:
        self._extract_running = busy
        state = "disabled" if busy else "normal"
        for widget in (
            self._extract_choose_button,
            self._extract_clear_button,
            self._extract_browse_button,
            self._extract_reset_button,
        ):
            widget.configure(state=state)
        self._extract_button.configure(state="disabled" if busy else "normal")
        self._extract_cancel_button.configure(state="normal" if busy else "disabled")
        if not busy:
            self._extract_reset_button.configure(
                state="disabled" if self._extract_use_default_dir else "normal"
            )

    def _open_extract_output_folder(self) -> None:
        folder = self._extract_last_output_dir
        if folder is None or not folder.is_dir():
            self._set_status("Папка з розпакованими файлами ще не готова")
            return
        try:
            os.startfile(folder)  # type: ignore[attr-defined]
        except OSError as exc:
            self._set_status(f"Не вдалося відкрити папку: {exc}")

    def _reset_extract_progress(self) -> None:
        self._extract_total = 0
        self._extract_progress_bar.set(0)
        self._extract_progress_label.configure(text="Оброблено 0 з 0")
        self._extract_last_output_dir = None
        self._extract_open_button.configure(state="disabled")

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
