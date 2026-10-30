"""Головне вікно File Toolkit: «Зображення», «Дані», «Відео» і «Архіви»."""

from __future__ import annotations

import os
import queue
import threading
import tkinter
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox

import customtkinter as ctk

try:  # без tkinterdnd2 програма працює як раніше, лише без перетягування
    from tkinterdnd2 import COPY as DND_COPY
    from tkinterdnd2 import DND_FILES, REFUSE_DROP, TkinterDnD
except Exception:  # pragma: no cover - залежить від встановленого пакета
    TkinterDnD = None
    DND_FILES = "DND_Files"
    DND_COPY = "copy"
    REFUSE_DROP = "refuse_drop"

from app import __version__, archive, converter, data_converter, video_converter
from app.archive import ArchiveResult, ExtractOptions, ExtractResult, ZipOptions
from app.converter import ImageOptions, ResizeMode, TargetFormat
from app.data_converter import DataOptions, OutputFormat, TxtLayout
from app.video_converter import MaxHeight, QualityPreset, VideoOptions

WINDOW_TITLE = "File Toolkit — офлайн конвертер та архіватор"
WINDOW_SIZE = (1120, 820)
MIN_SIZE = (980, 760)

CONVERTER_TAB = "Конвертер"
DATA_TAB = "Дані"
VIDEO_TAB = "Відео"
ARCHIVE_TAB = "Архіватор"

NAV_LABELS = {
    CONVERTER_TAB: "Зображення",
    DATA_TAB: "Дані",
    VIDEO_TAB: "Відео",
    ARCHIVE_TAB: "Архіви",
}
PAGE_TITLES = {
    CONVERTER_TAB: "Конвертер зображень",
    DATA_TAB: "Конвертер даних",
    VIDEO_TAB: "Конвертер відео",
    ARCHIVE_TAB: "Архіватор",
}

SELECT_FILES_TITLE = "Вибір файлів"
SELECT_DATA_FILES_TITLE = "Вибір файлів даних"
SELECT_VIDEO_FILES_TITLE = "Вибір відеофайлів"
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
VIDEO_FILTER = [
    ("Відео", "*.mp4 *.mkv *.avi *.mov *.webm *.flv *.wmv"),
    ("MP4", "*.mp4"),
    ("MKV", "*.mkv"),
    ("AVI", "*.avi"),
    ("MOV", "*.mov"),
    ("WebM", "*.webm"),
    ("FLV", "*.flv"),
    ("WMV", "*.wmv"),
    ("Усі файли", "*.*"),
]

DATA_TARGET_LABELS = {
    fmt: data_converter.OUTPUT_FORMAT_LABELS[fmt] for fmt in OutputFormat
}
VIDEO_TARGET_LABELS = {
    fmt: video_converter.OUTPUT_FORMAT_LABELS[fmt]
    for fmt in video_converter.OutputFormat
}
VIDEO_QUALITY_LABELS = dict(video_converter.QUALITY_LABELS)
VIDEO_HEIGHT_LABELS = dict(video_converter.HEIGHT_LABELS)

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
DROP_TITLE = "Перетягни файли сюди"
DROP_ARCHIVE_TITLE = "Перетягни архів сюди"
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

# UI theme: темна фіолетова палітра з рожевим акцентом.
BG_COLOR = "#12101F"
APP_CARD_COLOR = "#1B1740"
SIDEBAR_COLOR = "#221D42"
CARD_COLOR = "#272152"
ELEVATED_COLOR = "#2E2760"
ACCENT_COLOR = "#FF9EC4"
ACCENT_HOVER_COLOR = "#FFB3D3"
ACCENT_TEXT_COLOR = "#2A1730"
PRIMARY_FG_COLOR = "#FF9EC4"
PRIMARY_HOVER_COLOR = "#FFB3D3"
SECONDARY_FG_COLOR = "#2E2760"
SECONDARY_HOVER_COLOR = "#3A3272"
DANGER_FG_COLOR = "#3A2A3E"
DANGER_HOVER_COLOR = "#4A3350"
DISABLED_TEXT_COLOR = "#6F699C"
BORDER_COLOR = "#37315F"
BORDER_LIGHT_COLOR = "#6A61C4"
TEXT_PRIMARY = "#F4F1FF"
TEXT_SECONDARY = "#C5BFE8"
TEXT_MUTED = "#9B94C8"
MINT_COLOR = "#7EF9D0"
TRACK_COLOR = "#241F49"
FIELD_COLOR = "#241F49"
DOT_COLORS = ("#FF8FB0", "#7C7BF5", "#6EE7C4")
GROUP_CORNER_RADIUS = 12
GROUP_BORDER_WIDTH = 1
CARD_CORNER_RADIUS = 16
BTN_CORNER_RADIUS = 14

PAD_XS = 4
PAD_S = 6
PAD_M = 10
PAD_L = 14
PAD_XL = 18
PAD_XXL = 22
ROW_PAD_Y = 6
SECTION_PAD_Y = 10

BTN_HEIGHT = 34
ENTRY_HEIGHT = 34
MENU_HEIGHT = 34
CHECKBOX_HEIGHT = 28
NAV_HEIGHT = 46

APP_FONT = ("Segoe UI", 9)
APP_FONT_MEDIUM = ("Segoe UI Semibold", 9)
APP_FONT_SMALL = ("Segoe UI", 8)
APP_FONT_NAV = ("Segoe UI Semibold", 11)
APP_FONT_HEADER = ("Segoe UI Semibold", 11)
APP_FONT_PAGE_TITLE = ("Segoe UI Semibold", 20)
APP_FONT_UPLOAD = ("Segoe UI Semibold", 13)
APP_FONT_TITLE = ("Segoe UI Semibold", 9)

SETTINGS_LABEL_WIDTH = 96
DATA_SETTINGS_LABEL_WIDTH = 160
VIDEO_SETTINGS_LABEL_WIDTH = 170
PROGRESS_POLL_MS = 100
MAX_FAILURE_LINES = 8


def _path_key(path: Path) -> str:
    """Ключ для порівняння шляхів без урахування регістру (Windows)."""
    return os.path.normcase(str(path))


def remove_item_at(items: list[Path], index: int) -> Path | None:
    """Видаляє елемент списку за індексом; None, якщо такого індексу немає."""
    if 0 <= index < len(items):
        return items.pop(index)
    return None


def remove_item_path(items: list[Path], path: Path) -> bool:
    """Видаляє перший елемент з таким самим шляхом; True, якщо видалено."""
    key = _path_key(path)
    for index, existing in enumerate(items):
        if _path_key(existing) == key:
            items.pop(index)
            return True
    return False


def _split_tcl_list(text: str) -> list[str]:
    """Розбирає список у форматі Tcl (так tkdnd передає шляхи) на елементи."""
    items: list[str] = []
    current: list[str] = []
    depth = 0
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char == "\\" and depth == 0 and index + 1 < length:
            current.append(text[index + 1])
            index += 2
            continue
        if char == "{" and depth == 0 and not current:
            depth = 1
            index += 1
            continue
        if char == "}" and depth == 1:
            depth = 0
            index += 1
            continue
        if char.isspace() and depth == 0:
            if current:
                items.append("".join(current))
                current = []
            index += 1
            continue
        current.append(char)
        index += 1
    if current:
        items.append("".join(current))
    return items


def parse_dropped_paths(data: object) -> list[Path]:
    """Перетворює дані події перетягування у список унікальних шляхів.

    tkdnd віддає або готовий кортеж рядків, або рядок у форматі списку Tcl,
    де шляхи з пробілами взяті у фігурні дужки.
    """
    if data is None:
        return []
    if isinstance(data, (list, tuple)):
        raw_items = [str(item) for item in data]
    else:
        text = str(data).strip()
        if not text:
            return []
        raw_items = _split_tcl_list(text)

    paths: list[Path] = []
    seen: set[str] = set()
    for item in raw_items:
        text = item.strip()
        if len(text) >= 2 and text.startswith("{") and text.endswith("}"):
            text = text[1:-1].strip()
        if not text:
            continue
        try:
            key = os.path.normcase(os.path.abspath(text))
        except (OSError, ValueError):
            key = os.path.normcase(text)
        if key in seen:
            continue
        seen.add(key)
        paths.append(Path(text))
    return paths


def video_height_enabled(target: video_converter.OutputFormat) -> bool:
    """Висота має сенс лише для відео, не для MP3/WAV."""
    return target not in video_converter.AUDIO_OUTPUT_FORMATS


def video_sound_enabled(target: video_converter.OutputFormat) -> bool:
    """«Без звуку» не діє для GIF та витягування звуку."""
    return (
        target not in video_converter.AUDIO_OUTPUT_FORMATS
        and target is not video_converter.OutputFormat.GIF
    )


def video_quality_enabled(target: video_converter.OutputFormat) -> bool:
    """WAV не стискається, тому якість для нього не потрібна."""
    return target is not video_converter.OutputFormat.WAV


class App(ctk.CTk):
    """Головне вікно програми."""

    def __init__(self) -> None:
        super().__init__()
        self.title(WINDOW_TITLE)
        try:
            ctk.set_appearance_mode("dark")
            ctk.set_default_color_theme("blue")
        except Exception:
            pass
        self.configure(fg_color=BG_COLOR)
        self._layout_ready = False
        # tkdnd підключаємо до вікна, поки не створені віджети; без нього — False.
        self._dnd_ready = self._enable_dnd()

        self._converter_files: list[Path] = []
        self._data_files: list[Path] = []
        self._archive_items: list[Path] = []

        # Кнопки «✕» у списках — щоб вимикати їх під час роботи.
        self._converter_remove_buttons: list[ctk.CTkButton] = []
        self._data_remove_buttons: list[ctk.CTkButton] = []
        self._video_remove_buttons: list[ctk.CTkButton] = []
        self._archive_remove_buttons: list[ctk.CTkButton] = []

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

        # Окремий стан вкладки «Відео».
        self._video_files: list[Path] = []
        self._video_queue: queue.Queue = queue.Queue()
        self._video_cancel_event = threading.Event()
        self._video_running = False
        self._video_output_dir: Path | None = None
        self._video_last_output_dir: Path | None = None
        self._video_use_source_folder = True
        self._video_skipped_unsupported = 0
        self._video_total = 0

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
        self._refresh_video_list()
        self._refresh_archive_list()
        self._on_format_change()
        self._on_resize_mode_change()
        self._refresh_data_controls()
        self._on_video_format_change()
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

        self.surface = ctk.CTkFrame(
            self,
            fg_color=APP_CARD_COLOR,
            corner_radius=PAD_XL,
            border_width=GROUP_BORDER_WIDTH,
            border_color=BORDER_COLOR,
        )
        self.surface.grid(row=0, column=0, padx=PAD_M, pady=PAD_M, sticky="nsew")
        self.surface.grid_columnconfigure(1, weight=1)
        self.surface.grid_rowconfigure(1, weight=1)

        self._build_header()

        self.sidebar = ctk.CTkFrame(
            self.surface,
            fg_color=SIDEBAR_COLOR,
            corner_radius=CARD_CORNER_RADIUS,
            width=210,
        )
        self.sidebar.grid(row=1, column=0, sticky="nsw", padx=(PAD_L, 0), pady=0)

        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        for key, label in NAV_LABELS.items():
            button = ctk.CTkButton(
                self.sidebar,
                text=label,
                anchor="w",
                width=182,
                height=NAV_HEIGHT,
                corner_radius=BTN_CORNER_RADIUS,
                font=APP_FONT_NAV,
                fg_color="transparent",
                hover_color=ELEVATED_COLOR,
                text_color=TEXT_SECONDARY,
                command=lambda name=key: self._select_page(name),
            )
            button.pack(fill="x", padx=PAD_M, pady=(0, PAD_XS))
            self._nav_buttons[key] = button

        ctk.CTkLabel(
            self.sidebar,
            text="Працює офлайн",
            font=APP_FONT_SMALL,
            text_color=TEXT_MUTED,
            anchor="w",
        ).pack(side="bottom", fill="x", padx=PAD_L, pady=PAD_L)

        self.content = ctk.CTkFrame(self.surface, fg_color="transparent")
        self.content.grid(row=1, column=1, sticky="nsew", padx=PAD_XL, pady=0)
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self._pages: dict[str, ctk.CTkFrame] = {}
        self._build_converter_tab(self._add_page(CONVERTER_TAB))
        self._build_data_tab(self._add_page(DATA_TAB))
        self._build_video_tab(self._add_page(VIDEO_TAB))
        self._build_archive_tab(self._add_page(ARCHIVE_TAB))
        self._select_page(CONVERTER_TAB)

        self.status_label = ctk.CTkLabel(
            self.surface,
            text="",
            anchor="w",
            height=24,
            text_color=TEXT_MUTED,
            font=APP_FONT_SMALL,
        )
        self.status_label.grid(
            row=2, column=0, columnspan=2, padx=PAD_XL, pady=(PAD_S, PAD_M), sticky="ew"
        )

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self.surface, fg_color="transparent")
        header.grid(
            row=0, column=0, columnspan=2, padx=PAD_XL, pady=(PAD_M, PAD_M), sticky="ew"
        )

        dots = ctk.CTkFrame(header, fg_color="transparent")
        dots.pack(side="left")
        for color in DOT_COLORS:
            ctk.CTkFrame(
                dots, width=12, height=12, corner_radius=6, fg_color=color
            ).pack(side="left", padx=(0, PAD_S))

        ctk.CTkLabel(
            header,
            text="File Toolkit",
            font=APP_FONT_HEADER,
            text_color=TEXT_PRIMARY,
            anchor="w",
        ).pack(side="left", padx=(PAD_L, 0))

        ctk.CTkLabel(
            header,
            text=f"v{__version__}",
            font=APP_FONT_SMALL,
            text_color=TEXT_MUTED,
            anchor="w",
        ).pack(side="left", padx=(PAD_S, 0))

    def _add_page(self, key: str) -> ctk.CTkFrame:
        """Створює сторінку з заголовком і повертає її робочу область."""
        page = ctk.CTkFrame(self.content, fg_color="transparent")
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            page,
            text=PAGE_TITLES[key],
            font=APP_FONT_PAGE_TITLE,
            text_color=TEXT_PRIMARY,
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", pady=(PAD_XS, PAD_M))

        body = ctk.CTkFrame(page, fg_color="transparent")
        body.grid(row=1, column=0, sticky="nsew")
        self._pages[key] = page
        return body

    def _select_page(self, key: str) -> None:
        for name, page in self._pages.items():
            if name == key:
                page.grid()
            else:
                page.grid_remove()
        for name, button in self._nav_buttons.items():
            if name == key:
                button.configure(
                    fg_color=ACCENT_COLOR,
                    hover_color=ACCENT_HOVER_COLOR,
                    text_color=ACCENT_TEXT_COLOR,
                )
            else:
                button.configure(
                    fg_color="transparent",
                    hover_color=ELEVATED_COLOR,
                    text_color=TEXT_SECONDARY,
                )

    def _build_converter_tab(self, tab: ctk.CTkFrame) -> None:
        tab.configure(fg_color="transparent")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(3, weight=1, minsize=84)

        upload = ctk.CTkFrame(
            tab,
            fg_color=CARD_COLOR,
            corner_radius=CARD_CORNER_RADIUS,
            border_width=2,
            border_color=BORDER_LIGHT_COLOR,
        )
        upload.grid(row=0, column=0, sticky="ew", pady=(0, PAD_M))

        icon = ctk.CTkFrame(
            upload,
            width=24,
            height=28,
            corner_radius=5,
            fg_color="transparent",
            border_width=2,
            border_color=ACCENT_COLOR,
        )
        icon.pack(pady=(PAD_S, 0))
        icon.pack_propagate(False)

        upload_title = ctk.CTkLabel(
            upload,
            text=DROP_TITLE,
            font=APP_FONT_UPLOAD,
            text_color=TEXT_PRIMARY,
            height=24,
        )
        upload_title.pack(pady=(PAD_XS, 0))

        upload_hint = ctk.CTkLabel(
            upload,
            text="або натисни, щоб вибрати. PNG, JPG, WebP, BMP",
            font=APP_FONT,
            text_color=TEXT_MUTED,
            height=20,
        )
        upload_hint.pack()

        toolbar = ctk.CTkFrame(upload, fg_color="transparent")
        toolbar.pack(pady=(PAD_S, PAD_M))

        self._choose_files_button = ctk.CTkButton(
            toolbar,
            text="Вибрати файли",
            command=self._choose_converter_files,
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            fg_color=ACCENT_COLOR,
            hover_color=ACCENT_HOVER_COLOR,
            text_color=ACCENT_TEXT_COLOR,
            font=APP_FONT_MEDIUM,
        )
        self._choose_files_button.pack(side="left")
        self._clear_files_button = ctk.CTkButton(
            toolbar,
            text="Очистити",
            command=self._clear_converter_files,
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            fg_color=SECONDARY_FG_COLOR,
            hover_color=SECONDARY_HOVER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._clear_files_button.pack(side="left", padx=(PAD_M, 0))

        for widget in (upload, icon, upload_title, upload_hint):
            widget.bind(
                "<Button-1>",
                lambda _event: (
                    None if self._converter_running else self._choose_converter_files()
                ),
            )

        self._make_drop_zone(
            (upload, icon, upload_title, upload_hint), self._on_converter_drop
        )

        self._build_converter_settings(tab)

        self._converter_counter = ctk.CTkLabel(tab, text="", anchor="w", text_color=TEXT_SECONDARY)
        self._converter_counter.grid(row=2, column=0, sticky="ew", pady=(0, PAD_S))

        self._converter_list = ctk.CTkScrollableFrame(
            tab,
            label_text="Вибрані файли",
            height=110,
            fg_color=CARD_COLOR,
            corner_radius=CARD_CORNER_RADIUS,
            border_width=GROUP_BORDER_WIDTH,
            border_color=BORDER_COLOR,
            label_fg_color=CARD_COLOR,
            label_text_color=TEXT_SECONDARY,
        )
        self._converter_list.grid(row=3, column=0, sticky="nsew")

        self._build_converter_progress(tab)

    def _build_converter_settings(self, tab: ctk.CTkFrame) -> None:
        settings = ctk.CTkFrame(
            tab,
            fg_color=CARD_COLOR,
            corner_radius=CARD_CORNER_RADIUS,
            border_width=GROUP_BORDER_WIDTH,
            border_color=BORDER_COLOR,
        )
        settings.grid(row=1, column=0, sticky="ew", pady=(0, PAD_M))

        # Рядок 1: формат і якість.
        format_row = self._settings_row(settings)
        self._row_label(format_row, "Формат:")
        self._format_menu = ctk.CTkOptionMenu(
            format_row,
            values=[converter.TARGET_FORMAT_LABELS[fmt] for fmt in TargetFormat],
            width=150,
            height=MENU_HEIGHT,
            fg_color=ELEVATED_COLOR,
            button_color=ELEVATED_COLOR,
            button_hover_color=SECONDARY_HOVER_COLOR,
            dropdown_fg_color=CARD_COLOR,
            dropdown_hover_color=ELEVATED_COLOR,
            text_color=TEXT_PRIMARY,
            command=self._on_format_change,
        )
        self._format_menu.set(converter.TARGET_FORMAT_LABELS[TargetFormat.SOURCE])
        self._format_menu.pack(side="left", padx=(0, 18))

        self._quality_label = ctk.CTkLabel(
            format_row, text="Якість:", width=SETTINGS_LABEL_WIDTH, anchor="w", text_color=TEXT_SECONDARY
        )
        self._quality_label.pack(side="left")

        self._quality_slider = ctk.CTkSlider(
            format_row,
            from_=converter.MIN_QUALITY,
            to=converter.MAX_QUALITY,
            number_of_steps=converter.MAX_QUALITY - converter.MIN_QUALITY,
            width=170,
            fg_color=TRACK_COLOR,
            progress_color=ACCENT_COLOR,
            button_color=ACCENT_COLOR,
            button_hover_color=ACCENT_HOVER_COLOR,
            command=self._on_quality_slider,
        )
        self._quality_slider.set(converter.DEFAULT_QUALITY)
        self._quality_slider.pack(side="left", padx=(0, 8))

        self._quality_var = ctk.StringVar(value=str(converter.DEFAULT_QUALITY))
        self._quality_entry = ctk.CTkEntry(
            format_row,
            width=54,
            justify="center",
            textvariable=self._quality_var,
            height=ENTRY_HEIGHT,
            fg_color=FIELD_COLOR,
            border_color=BORDER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._quality_entry.pack(side="left")
        self._quality_entry.bind("<Return>", self._on_quality_entry)
        self._quality_entry.bind("<FocusOut>", self._on_quality_entry)

        self._quality_hint = ctk.CTkLabel(
            format_row,
            text="",
            text_color=TEXT_MUTED,
            font=APP_FONT_SMALL,
            anchor="w",
        )
        self._quality_hint.pack(side="left", padx=(PAD_L, 0))

        # Рядок 2: розмір.
        size_row = self._settings_row(settings)
        self._row_label(size_row, "Розмір:")
        self._resize_menu = ctk.CTkOptionMenu(
            size_row,
            values=list(RESIZE_LABELS.values()),
            width=150,
            height=MENU_HEIGHT,
            fg_color=ELEVATED_COLOR,
            button_color=ELEVATED_COLOR,
            button_hover_color=SECONDARY_HOVER_COLOR,
            dropdown_fg_color=CARD_COLOR,
            dropdown_hover_color=ELEVATED_COLOR,
            text_color=TEXT_PRIMARY,
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
            longest_frame,
            width=72,
            justify="center",
            textvariable=self._longest_side_var,
            height=ENTRY_HEIGHT,
            fg_color=FIELD_COLOR,
            border_color=BORDER_COLOR,
            text_color=TEXT_PRIMARY,
        ).pack(side="left")
        ctk.CTkLabel(longest_frame, text="px (довша сторона)", text_color=TEXT_SECONDARY).pack(
            side="left", padx=(6, 0)
        )
        self._size_frames[ResizeMode.LONGEST_SIDE] = longest_frame

        percent_frame = ctk.CTkFrame(self._size_params, fg_color="transparent")
        ctk.CTkEntry(
            percent_frame,
            width=72,
            justify="center",
            textvariable=self._percent_var,
            height=ENTRY_HEIGHT,
            fg_color=FIELD_COLOR,
            border_color=BORDER_COLOR,
            text_color=TEXT_PRIMARY,
        ).pack(side="left")
        ctk.CTkLabel(percent_frame, text="% від оригіналу", text_color=TEXT_SECONDARY).pack(
            side="left", padx=(6, 0)
        )
        self._size_frames[ResizeMode.PERCENT] = percent_frame

        box_frame = ctk.CTkFrame(self._size_params, fg_color="transparent")
        ctk.CTkEntry(
            box_frame,
            width=66,
            justify="center",
            textvariable=self._box_width_var,
            height=ENTRY_HEIGHT,
            fg_color=FIELD_COLOR,
            border_color=BORDER_COLOR,
            text_color=TEXT_PRIMARY,
        ).pack(side="left")
        ctk.CTkLabel(box_frame, text="×", text_color=TEXT_SECONDARY).pack(side="left", padx=4)
        ctk.CTkEntry(
            box_frame,
            width=66,
            justify="center",
            textvariable=self._box_height_var,
            height=ENTRY_HEIGHT,
            fg_color=FIELD_COLOR,
            border_color=BORDER_COLOR,
            text_color=TEXT_PRIMARY,
        ).pack(side="left")
        ctk.CTkLabel(box_frame, text="px", text_color=TEXT_SECONDARY).pack(side="left", padx=(6, 0))
        self._size_frames[ResizeMode.BOX] = box_frame

        self._keep_aspect_var = ctk.BooleanVar(value=True)
        self._keep_aspect_check = ctk.CTkCheckBox(
            size_row,
            text="Пропорції",
            variable=self._keep_aspect_var,
            onvalue=True,
            offvalue=False,
            height=CHECKBOX_HEIGHT,
            border_color=BORDER_LIGHT_COLOR,
            fg_color=ACCENT_COLOR,
            hover_color=ACCENT_HOVER_COLOR,
            checkmark_color=ACCENT_TEXT_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._keep_aspect_check.pack(side="left", padx=(18, 0))

        self._no_upscale_var = ctk.BooleanVar(value=True)
        self._no_upscale_check = ctk.CTkCheckBox(
            size_row,
            text="Не збільшувати",
            variable=self._no_upscale_var,
            onvalue=True,
            offvalue=False,
            height=CHECKBOX_HEIGHT,
            border_color=BORDER_LIGHT_COLOR,
            fg_color=ACCENT_COLOR,
            hover_color=ACCENT_HOVER_COLOR,
            checkmark_color=ACCENT_TEXT_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._no_upscale_check.pack(side="left", padx=(12, 0))

        # Рядок 3: підкладка для прозорості та папка призначення.
        folder_row = self._settings_row(settings)
        self._row_label(folder_row, "Підкладка:")
        self._background_menu = ctk.CTkOptionMenu(
            folder_row,
            values=list(BACKGROUND_CHOICES) + [OTHER_COLOR_LABEL],
            width=130,
            height=MENU_HEIGHT,
            fg_color=ELEVATED_COLOR,
            button_color=ELEVATED_COLOR,
            button_hover_color=SECONDARY_HOVER_COLOR,
            dropdown_fg_color=CARD_COLOR,
            dropdown_hover_color=ELEVATED_COLOR,
            text_color=TEXT_PRIMARY,
            command=self._on_background_change,
        )
        self._background_menu.set("Білий")
        self._background_menu.pack(side="left", padx=(0, 16))

        self._background_hint = ctk.CTkLabel(
            folder_row,
            text="фон для прозорих пікселів",
            text_color=TEXT_MUTED,
            font=APP_FONT_SMALL,
            anchor="w",
        )
        self._background_hint.pack(side="left", padx=(0, PAD_L))

        self._row_label(folder_row, "Папка:")
        self._use_source_folder = True
        self._output_text = ctk.StringVar(value=SAME_FOLDER_TEXT)
        self._output_entry = ctk.CTkEntry(
            folder_row,
            textvariable=self._output_text,
            state="disabled",
            width=200,
            height=ENTRY_HEIGHT,
            fg_color=FIELD_COLOR,
            border_color=BORDER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._output_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._browse_output_button = ctk.CTkButton(
            folder_row,
            text="Оглянути…",
            width=100,
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            command=self._choose_output_dir,
            fg_color=SECONDARY_FG_COLOR,
            hover_color=SECONDARY_HOVER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._browse_output_button.pack(side="left")
        self._reset_output_button = ctk.CTkButton(
            folder_row,
            text="Скинути",
            width=90,
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            command=self._reset_output_dir,
            state="disabled",
            fg_color=SECONDARY_FG_COLOR,
            hover_color=SECONDARY_HOVER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._reset_output_button.pack(side="left", padx=(PAD_M, 0))

    def _settings_row(
        self, parent: ctk.CTkFrame, pady: int = PAD_XS
    ) -> ctk.CTkFrame:
        """Рядок налаштувань: підпис ліворуч, елементи керування праворуч."""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=PAD_L, pady=pady)
        return row

    def _row_label(
        self, parent: ctk.CTkFrame, text: str, width: int = SETTINGS_LABEL_WIDTH
    ) -> ctk.CTkLabel:
        label = ctk.CTkLabel(parent, text=text, width=width, anchor="w", text_color=TEXT_SECONDARY)
        label.pack(side="left")
        return label

    def _build_data_tab(self, tab: ctk.CTkFrame) -> None:
        tab.configure(fg_color="transparent")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(3, weight=1, minsize=84)

        upload = ctk.CTkFrame(
            tab,
            fg_color=CARD_COLOR,
            corner_radius=CARD_CORNER_RADIUS,
            border_width=2,
            border_color=BORDER_LIGHT_COLOR,
        )
        upload.grid(row=0, column=0, sticky="ew", pady=(0, PAD_M))

        icon = ctk.CTkFrame(
            upload,
            width=24,
            height=28,
            corner_radius=5,
            fg_color="transparent",
            border_width=2,
            border_color=ACCENT_COLOR,
        )
        icon.pack(pady=(PAD_S, 0))
        icon.pack_propagate(False)

        upload_title = ctk.CTkLabel(
            upload,
            text=DROP_TITLE,
            font=APP_FONT_UPLOAD,
            text_color=TEXT_PRIMARY,
            height=24,
        )
        upload_title.pack(pady=(PAD_XS, 0))

        upload_hint = ctk.CTkLabel(
            upload,
            text="або натисни, щоб вибрати. JSON, CSV, TXT",
            font=APP_FONT,
            text_color=TEXT_MUTED,
            height=20,
        )
        upload_hint.pack()

        toolbar = ctk.CTkFrame(upload, fg_color="transparent")
        toolbar.pack(pady=(PAD_S, PAD_M))

        self._data_choose_button = ctk.CTkButton(
            toolbar,
            text="Вибрати файли",
            command=self._choose_data_files,
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            fg_color=ACCENT_COLOR,
            hover_color=ACCENT_HOVER_COLOR,
            text_color=ACCENT_TEXT_COLOR,
            font=APP_FONT_MEDIUM,
        )
        self._data_choose_button.pack(side="left")
        self._data_clear_button = ctk.CTkButton(
            toolbar,
            text="Очистити",
            command=self._clear_data_files,
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            fg_color=SECONDARY_FG_COLOR,
            hover_color=SECONDARY_HOVER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._data_clear_button.pack(side="left", padx=(PAD_M, 0))

        for widget in (upload, icon, upload_title, upload_hint):
            widget.bind(
                "<Button-1>",
                lambda _event: (
                    None if self._data_running else self._choose_data_files()
                ),
            )

        self._make_drop_zone(
            (upload, icon, upload_title, upload_hint), self._on_data_drop
        )

        self._build_data_settings(tab)

        self._data_counter = ctk.CTkLabel(tab, text="", anchor="w", text_color=TEXT_SECONDARY)
        self._data_counter.grid(row=2, column=0, sticky="ew", pady=(0, PAD_S))

        self._data_list = ctk.CTkScrollableFrame(
            tab,
            label_text="Вибрані файли даних",
            height=110,
            fg_color=CARD_COLOR,
            corner_radius=CARD_CORNER_RADIUS,
            border_width=GROUP_BORDER_WIDTH,
            border_color=BORDER_COLOR,
            label_fg_color=CARD_COLOR,
            label_text_color=TEXT_SECONDARY,
        )
        self._data_list.grid(row=3, column=0, sticky="nsew")

        self._build_data_progress(tab)

    def _build_data_settings(self, tab: ctk.CTkFrame) -> None:
        settings = ctk.CTkFrame(
            tab,
            fg_color=CARD_COLOR,
            corner_radius=CARD_CORNER_RADIUS,
            border_width=GROUP_BORDER_WIDTH,
            border_color=BORDER_COLOR,
        )
        settings.grid(row=1, column=0, sticky="ew", pady=(0, PAD_M))

        # Рядок 1: формат результату та налаштування JSON.
        format_row = self._settings_row(settings, pady=1)
        self._row_label(
            format_row, "Формат результату:", DATA_SETTINGS_LABEL_WIDTH
        )
        self._data_format_menu = ctk.CTkOptionMenu(
            format_row,
            values=list(DATA_TARGET_LABELS.values()),
            width=140,
            height=MENU_HEIGHT,
            fg_color=ELEVATED_COLOR,
            button_color=ELEVATED_COLOR,
            button_hover_color=SECONDARY_HOVER_COLOR,
            dropdown_fg_color=CARD_COLOR,
            dropdown_hover_color=ELEVATED_COLOR,
            text_color=TEXT_PRIMARY,
            command=self._on_data_format_change,
        )
        self._data_format_menu.set(DATA_TARGET_LABELS[OutputFormat.JSON])
        self._data_format_menu.pack(side="left", padx=(0, 16))

        ctk.CTkLabel(format_row, text="Відступ JSON:", width=120, anchor="w", text_color=TEXT_SECONDARY).pack(
            side="left"
        )
        self._data_indent_menu = ctk.CTkOptionMenu(
            format_row,
            values=list(JSON_INDENT_CHOICES),
            width=130,
            height=MENU_HEIGHT,
            fg_color=ELEVATED_COLOR,
            button_color=ELEVATED_COLOR,
            button_hover_color=SECONDARY_HOVER_COLOR,
            dropdown_fg_color=CARD_COLOR,
            dropdown_hover_color=ELEVATED_COLOR,
            text_color=TEXT_PRIMARY,
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
            height=CHECKBOX_HEIGHT,
            border_color=BORDER_LIGHT_COLOR,
            fg_color=ACCENT_COLOR,
            hover_color=ACCENT_HOVER_COLOR,
            checkmark_color=ACCENT_TEXT_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._data_sort_check.pack(side="left")

        # Рядок 2: окремі роздільники для читання і для запису.
        delimiter_row = self._settings_row(settings, pady=1)
        self._row_label(
            delimiter_row, "Роздільник файлу:", DATA_SETTINGS_LABEL_WIDTH
        )
        self._data_input_delimiter_menu = ctk.CTkOptionMenu(
            delimiter_row,
            values=list(DELIMITER_CHOICES),
            width=130,
            height=MENU_HEIGHT,
            fg_color=ELEVATED_COLOR,
            button_color=ELEVATED_COLOR,
            button_hover_color=SECONDARY_HOVER_COLOR,
            dropdown_fg_color=CARD_COLOR,
            dropdown_hover_color=ELEVATED_COLOR,
            text_color=TEXT_PRIMARY,
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
            height=MENU_HEIGHT,
            fg_color=ELEVATED_COLOR,
            button_color=ELEVATED_COLOR,
            button_hover_color=SECONDARY_HOVER_COLOR,
            dropdown_fg_color=CARD_COLOR,
            dropdown_hover_color=ELEVATED_COLOR,
            text_color=TEXT_PRIMARY,
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
            height=CHECKBOX_HEIGHT,
            border_color=BORDER_LIGHT_COLOR,
            fg_color=ACCENT_COLOR,
            hover_color=ACCENT_HOVER_COLOR,
            checkmark_color=ACCENT_TEXT_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._data_header_check.pack(side="left")

        # Рядок 3: кодування і переноси рядків.
        encoding_row = self._settings_row(settings, pady=1)
        self._row_label(
            encoding_row, "Кодування файлу:", DATA_SETTINGS_LABEL_WIDTH
        )
        self._data_input_encoding_menu = ctk.CTkOptionMenu(
            encoding_row,
            values=list(INPUT_ENCODING_CHOICES),
            width=140,
            height=MENU_HEIGHT,
            fg_color=ELEVATED_COLOR,
            button_color=ELEVATED_COLOR,
            button_hover_color=SECONDARY_HOVER_COLOR,
            dropdown_fg_color=CARD_COLOR,
            dropdown_hover_color=ELEVATED_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._data_input_encoding_menu.set("Авто")
        self._data_input_encoding_menu.pack(side="left", padx=(0, 14))

        self._row_label(
            encoding_row, "Кодування результату:", DATA_SETTINGS_LABEL_WIDTH
        )
        self._data_output_encoding_menu = ctk.CTkOptionMenu(
            encoding_row,
            values=list(OUTPUT_ENCODING_CHOICES),
            width=140,
            height=MENU_HEIGHT,
            fg_color=ELEVATED_COLOR,
            button_color=ELEVATED_COLOR,
            button_hover_color=SECONDARY_HOVER_COLOR,
            dropdown_fg_color=CARD_COLOR,
            dropdown_hover_color=ELEVATED_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._data_output_encoding_menu.set("UTF-8")
        self._data_output_encoding_menu.pack(side="left", padx=(0, 16))

        ctk.CTkLabel(encoding_row, text="Переноси:", width=90, anchor="w", text_color=TEXT_SECONDARY).pack(
            side="left"
        )
        self._data_newline_menu = ctk.CTkOptionMenu(
            encoding_row,
            values=list(NEWLINE_CHOICES),
            width=120,
            height=MENU_HEIGHT,
            fg_color=ELEVATED_COLOR,
            button_color=ELEVATED_COLOR,
            button_hover_color=SECONDARY_HOVER_COLOR,
            dropdown_fg_color=CARD_COLOR,
            dropdown_hover_color=ELEVATED_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._data_newline_menu.set("LF (Unix)")
        self._data_newline_menu.pack(side="left")

        # Рядок 4: вигляд TXT, типи та папка призначення.
        folder_row = self._settings_row(settings, pady=1)
        self._row_label(folder_row, "Вигляд TXT:", DATA_SETTINGS_LABEL_WIDTH)
        self._data_txt_layout_menu = ctk.CTkOptionMenu(
            folder_row,
            values=list(TXT_LAYOUT_CHOICES),
            width=140,
            height=MENU_HEIGHT,
            fg_color=ELEVATED_COLOR,
            button_color=ELEVATED_COLOR,
            button_hover_color=SECONDARY_HOVER_COLOR,
            dropdown_fg_color=CARD_COLOR,
            dropdown_hover_color=ELEVATED_COLOR,
            text_color=TEXT_PRIMARY,
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
            height=CHECKBOX_HEIGHT,
            border_color=BORDER_LIGHT_COLOR,
            fg_color=ACCENT_COLOR,
            hover_color=ACCENT_HOVER_COLOR,
            checkmark_color=ACCENT_TEXT_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._data_types_check.pack(side="left", padx=(0, 16))

        ctk.CTkLabel(folder_row, text="Папка:", width=70, anchor="w", text_color=TEXT_SECONDARY).pack(
            side="left"
        )
        self._data_output_text = ctk.StringVar(value=SAME_FOLDER_TEXT)
        self._data_output_entry = ctk.CTkEntry(
            folder_row,
            textvariable=self._data_output_text,
            state="disabled",
            width=120,
            height=ENTRY_HEIGHT,
            fg_color=FIELD_COLOR,
            border_color=BORDER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._data_output_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._data_browse_output_button = ctk.CTkButton(
            folder_row,
            text="Оглянути…",
            width=100,
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            command=self._choose_data_output_dir,
            fg_color=SECONDARY_FG_COLOR,
            hover_color=SECONDARY_HOVER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._data_browse_output_button.pack(side="left")
        self._data_reset_output_button = ctk.CTkButton(
            folder_row,
            text="Скинути",
            width=90,
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            command=self._reset_data_output_dir,
            state="disabled",
            fg_color=SECONDARY_FG_COLOR,
            hover_color=SECONDARY_HOVER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._data_reset_output_button.pack(side="left", padx=(PAD_M, 0))

    def _build_data_progress(self, tab: ctk.CTkFrame) -> None:
        progress_frame = ctk.CTkFrame(tab, fg_color="transparent")
        progress_frame.grid(row=4, column=0, sticky="ew", pady=(PAD_M, PAD_XS))

        self._data_progress_bar = ctk.CTkProgressBar(
            progress_frame,
            height=8,
            corner_radius=4,
            fg_color=TRACK_COLOR,
            progress_color=MINT_COLOR,
        )
        self._data_progress_bar.set(0)
        self._data_progress_bar.pack(side="left", fill="x", expand=True, padx=(0, PAD_L))

        self._data_progress_label = ctk.CTkLabel(
            progress_frame, text="Оброблено 0 з 0", anchor="e", width=240, text_color=TEXT_SECONDARY
        )
        self._data_progress_label.pack(side="left")

        actions = ctk.CTkFrame(tab, fg_color="transparent")
        actions.grid(row=5, column=0, sticky="ew", pady=(0, PAD_S))

        self._data_convert_button = ctk.CTkButton(
            actions,
            text="Конвертувати",
            command=self._start_data_conversion,
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            fg_color=ACCENT_COLOR,
            hover_color=ACCENT_HOVER_COLOR,
            text_color=ACCENT_TEXT_COLOR,
            font=APP_FONT_MEDIUM,
        )
        self._data_convert_button.pack(side="left")

        self._data_cancel_button = ctk.CTkButton(
            actions,
            text="Скасувати",
            command=self._cancel_data_conversion,
            state="disabled",
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            fg_color=SECONDARY_FG_COLOR,
            hover_color=SECONDARY_HOVER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._data_cancel_button.pack(side="left", padx=(PAD_M, 0))

        self._data_open_folder_button = ctk.CTkButton(
            actions,
            text="Відкрити папку",
            command=self._open_data_output_folder,
            state="disabled",
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            fg_color=SECONDARY_FG_COLOR,
            hover_color=SECONDARY_HOVER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._data_open_folder_button.pack(side="right")

    def _build_video_tab(self, tab: ctk.CTkFrame) -> None:
        tab.configure(fg_color="transparent")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(3, weight=1, minsize=84)

        upload = ctk.CTkFrame(
            tab,
            fg_color=CARD_COLOR,
            corner_radius=CARD_CORNER_RADIUS,
            border_width=2,
            border_color=BORDER_LIGHT_COLOR,
        )
        upload.grid(row=0, column=0, sticky="ew", pady=(0, PAD_M))

        icon = ctk.CTkFrame(
            upload,
            width=24,
            height=28,
            corner_radius=5,
            fg_color="transparent",
            border_width=2,
            border_color=ACCENT_COLOR,
        )
        icon.pack(pady=(PAD_S, 0))
        icon.pack_propagate(False)

        upload_title = ctk.CTkLabel(
            upload,
            text=DROP_TITLE,
            font=APP_FONT_UPLOAD,
            text_color=TEXT_PRIMARY,
            height=24,
        )
        upload_title.pack(pady=(PAD_XS, 0))

        upload_hint = ctk.CTkLabel(
            upload,
            text="або натисни, щоб вибрати. MP4, MKV, AVI, MOV, WebM, FLV, WMV",
            font=APP_FONT,
            text_color=TEXT_MUTED,
            height=20,
        )
        upload_hint.pack()

        toolbar = ctk.CTkFrame(upload, fg_color="transparent")
        toolbar.pack(pady=(PAD_S, PAD_M))

        self._video_choose_button = ctk.CTkButton(
            toolbar,
            text="Вибрати файли",
            command=self._choose_video_files,
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            fg_color=ACCENT_COLOR,
            hover_color=ACCENT_HOVER_COLOR,
            text_color=ACCENT_TEXT_COLOR,
            font=APP_FONT_MEDIUM,
        )
        self._video_choose_button.pack(side="left")
        self._video_clear_button = ctk.CTkButton(
            toolbar,
            text="Очистити",
            command=self._clear_video_files,
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            fg_color=SECONDARY_FG_COLOR,
            hover_color=SECONDARY_HOVER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._video_clear_button.pack(side="left", padx=(PAD_M, 0))

        for widget in (upload, icon, upload_title, upload_hint):
            widget.bind(
                "<Button-1>",
                lambda _event: (
                    None if self._video_running else self._choose_video_files()
                ),
            )

        self._make_drop_zone(
            (upload, icon, upload_title, upload_hint), self._on_video_drop
        )

        self._build_video_settings(tab)

        self._video_counter = ctk.CTkLabel(
            tab, text="", anchor="w", text_color=TEXT_SECONDARY
        )
        self._video_counter.grid(row=2, column=0, sticky="ew", pady=(0, PAD_S))

        self._video_list = ctk.CTkScrollableFrame(
            tab,
            label_text="Вибрані відео",
            height=110,
            fg_color=CARD_COLOR,
            corner_radius=CARD_CORNER_RADIUS,
            border_width=GROUP_BORDER_WIDTH,
            border_color=BORDER_COLOR,
            label_fg_color=CARD_COLOR,
            label_text_color=TEXT_SECONDARY,
        )
        self._video_list.grid(row=3, column=0, sticky="nsew")

        self._build_video_progress(tab)

    def _build_video_settings(self, tab: ctk.CTkFrame) -> None:
        settings = ctk.CTkFrame(
            tab,
            fg_color=CARD_COLOR,
            corner_radius=CARD_CORNER_RADIUS,
            border_width=GROUP_BORDER_WIDTH,
            border_color=BORDER_COLOR,
        )
        settings.grid(row=1, column=0, sticky="ew", pady=(0, PAD_M))

        # Рядок 1: формат результату та якість.
        format_row = self._settings_row(settings, pady=1)
        self._row_label(
            format_row, "Формат результату:", VIDEO_SETTINGS_LABEL_WIDTH
        )
        self._video_format_menu = ctk.CTkOptionMenu(
            format_row,
            values=list(VIDEO_TARGET_LABELS.values()),
            width=150,
            height=MENU_HEIGHT,
            fg_color=ELEVATED_COLOR,
            button_color=ELEVATED_COLOR,
            button_hover_color=SECONDARY_HOVER_COLOR,
            dropdown_fg_color=CARD_COLOR,
            dropdown_hover_color=ELEVATED_COLOR,
            text_color=TEXT_PRIMARY,
            command=self._on_video_format_change,
        )
        self._video_format_menu.set(
            VIDEO_TARGET_LABELS[video_converter.OutputFormat.MP4]
        )
        self._video_format_menu.pack(side="left", padx=(0, 18))

        ctk.CTkLabel(
            format_row,
            text="Якість:",
            width=70,
            anchor="w",
            text_color=TEXT_SECONDARY,
        ).pack(side="left")
        self._video_quality_menu = ctk.CTkOptionMenu(
            format_row,
            values=list(VIDEO_QUALITY_LABELS.values()),
            width=150,
            height=MENU_HEIGHT,
            fg_color=ELEVATED_COLOR,
            button_color=ELEVATED_COLOR,
            button_hover_color=SECONDARY_HOVER_COLOR,
            dropdown_fg_color=CARD_COLOR,
            dropdown_hover_color=ELEVATED_COLOR,
            text_color=TEXT_PRIMARY,
            command=self._on_video_quality_change,
        )
        self._video_quality_menu.set(
            VIDEO_QUALITY_LABELS[QualityPreset.BALANCED]
        )
        self._video_quality_menu.pack(side="left", padx=(0, 8))

        self._video_quality_hint = ctk.CTkLabel(
            format_row,
            text="",
            text_color=TEXT_MUTED,
            font=APP_FONT_SMALL,
            anchor="w",
        )
        self._video_quality_hint.pack(side="left", padx=(PAD_S, 0))

        # Рядок 2: максимальна висота та звук.
        height_row = self._settings_row(settings, pady=1)
        self._row_label(
            height_row, "Максимальна висота:", VIDEO_SETTINGS_LABEL_WIDTH
        )
        self._video_height_menu = ctk.CTkOptionMenu(
            height_row,
            values=list(VIDEO_HEIGHT_LABELS.values()),
            width=120,
            height=MENU_HEIGHT,
            fg_color=ELEVATED_COLOR,
            button_color=ELEVATED_COLOR,
            button_hover_color=SECONDARY_HOVER_COLOR,
            dropdown_fg_color=CARD_COLOR,
            dropdown_hover_color=ELEVATED_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._video_height_menu.set(VIDEO_HEIGHT_LABELS[MaxHeight.P720])
        self._video_height_menu.pack(side="left", padx=(0, 18))

        self._video_sound_var = ctk.BooleanVar(value=False)
        self._video_sound_check = ctk.CTkCheckBox(
            height_row,
            text="Без звуку",
            variable=self._video_sound_var,
            onvalue=True,
            offvalue=False,
            height=CHECKBOX_HEIGHT,
            border_color=BORDER_LIGHT_COLOR,
            fg_color=ACCENT_COLOR,
            hover_color=ACCENT_HOVER_COLOR,
            checkmark_color=ACCENT_TEXT_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._video_sound_check.pack(side="left")
        self._video_sound_hint = ctk.CTkLabel(
            height_row,
            text="",
            text_color=TEXT_MUTED,
            font=APP_FONT_SMALL,
            anchor="w",
        )
        self._video_sound_hint.pack(side="left", padx=(PAD_L, 0))

        # Рядок 3: папка призначення.
        folder_row = self._settings_row(settings, pady=1)
        ctk.CTkLabel(
            folder_row,
            text="Папка:",
            width=70,
            anchor="w",
            text_color=TEXT_SECONDARY,
        ).pack(side="left")
        self._video_output_text = ctk.StringVar(value=SAME_FOLDER_TEXT)
        self._video_output_entry = ctk.CTkEntry(
            folder_row,
            textvariable=self._video_output_text,
            state="disabled",
            width=120,
            height=ENTRY_HEIGHT,
            fg_color=FIELD_COLOR,
            border_color=BORDER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._video_output_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._video_browse_output_button = ctk.CTkButton(
            folder_row,
            text="Оглянути…",
            width=100,
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            command=self._choose_video_output_dir,
            fg_color=SECONDARY_FG_COLOR,
            hover_color=SECONDARY_HOVER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._video_browse_output_button.pack(side="left")
        self._video_reset_output_button = ctk.CTkButton(
            folder_row,
            text="Скинути",
            width=90,
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            command=self._reset_video_output_dir,
            state="disabled",
            fg_color=SECONDARY_FG_COLOR,
            hover_color=SECONDARY_HOVER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._video_reset_output_button.pack(side="left", padx=(PAD_M, 0))

    def _build_video_progress(self, tab: ctk.CTkFrame) -> None:
        progress_frame = ctk.CTkFrame(tab, fg_color="transparent")
        progress_frame.grid(row=4, column=0, sticky="ew", pady=(PAD_M, PAD_XS))

        self._video_progress_bar = ctk.CTkProgressBar(
            progress_frame,
            height=8,
            corner_radius=4,
            fg_color=TRACK_COLOR,
            progress_color=MINT_COLOR,
        )
        self._video_progress_bar.set(0)
        self._video_progress_bar.pack(
            side="left", fill="x", expand=True, padx=(0, PAD_L)
        )

        self._video_progress_label = ctk.CTkLabel(
            progress_frame,
            text="Оброблено 0 з 0",
            anchor="e",
            width=300,
            text_color=TEXT_SECONDARY,
        )
        self._video_progress_label.pack(side="left")

        actions = ctk.CTkFrame(tab, fg_color="transparent")
        actions.grid(row=5, column=0, sticky="ew", pady=(0, PAD_S))

        self._video_convert_button = ctk.CTkButton(
            actions,
            text="Конвертувати",
            command=self._start_video_conversion,
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            fg_color=ACCENT_COLOR,
            hover_color=ACCENT_HOVER_COLOR,
            text_color=ACCENT_TEXT_COLOR,
            font=APP_FONT_MEDIUM,
        )
        self._video_convert_button.pack(side="left")

        self._video_cancel_button = ctk.CTkButton(
            actions,
            text="Скасувати",
            command=self._cancel_video_conversion,
            state="disabled",
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            fg_color=SECONDARY_FG_COLOR,
            hover_color=SECONDARY_HOVER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._video_cancel_button.pack(side="left", padx=(PAD_M, 0))

        self._video_open_folder_button = ctk.CTkButton(
            actions,
            text="Відкрити папку",
            command=self._open_video_output_folder,
            state="disabled",
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            fg_color=SECONDARY_FG_COLOR,
            hover_color=SECONDARY_HOVER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._video_open_folder_button.pack(side="right")

    def _build_converter_progress(self, tab: ctk.CTkFrame) -> None:
        progress_frame = ctk.CTkFrame(tab, fg_color="transparent")
        progress_frame.grid(row=4, column=0, sticky="ew", pady=(PAD_M, PAD_XS))

        self._progress_bar = ctk.CTkProgressBar(
            progress_frame,
            height=8,
            corner_radius=4,
            fg_color=TRACK_COLOR,
            progress_color=MINT_COLOR,
        )
        self._progress_bar.set(0)
        self._progress_bar.pack(side="left", fill="x", expand=True, padx=(0, PAD_L))

        self._progress_label = ctk.CTkLabel(
            progress_frame,
            text="Оброблено 0 з 0",
            anchor="e",
            width=240,
            text_color=TEXT_SECONDARY,
        )
        self._progress_label.pack(side="left")

        actions = ctk.CTkFrame(tab, fg_color="transparent")
        actions.grid(row=5, column=0, sticky="ew", pady=(0, PAD_S))

        self._convert_button = ctk.CTkButton(
            actions,
            text="Конвертувати",
            command=self._start_conversion,
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            fg_color=ACCENT_COLOR,
            hover_color=ACCENT_HOVER_COLOR,
            text_color=ACCENT_TEXT_COLOR,
            font=APP_FONT_MEDIUM,
        )
        self._convert_button.pack(side="left")

        self._cancel_button = ctk.CTkButton(
            actions,
            text="Скасувати",
            command=self._cancel_conversion,
            state="disabled",
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            fg_color=SECONDARY_FG_COLOR,
            hover_color=SECONDARY_HOVER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._cancel_button.pack(side="left", padx=(PAD_M, 0))

        self._open_folder_button = ctk.CTkButton(
            actions,
            text="Відкрити папку",
            command=self._open_output_folder,
            state="disabled",
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            fg_color=SECONDARY_FG_COLOR,
            hover_color=SECONDARY_HOVER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._open_folder_button.pack(side="right")

    def _build_archive_tab(self, tab: ctk.CTkFrame) -> None:
        tab.configure(fg_color="transparent")
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        mode_frame = ctk.CTkFrame(tab, fg_color="transparent")
        mode_frame.grid(row=0, column=0, sticky="ew", pady=(PAD_S, PAD_M))
        self._archive_mode_var = ctk.StringVar(value="Створити ZIP")
        self._archive_mode_menu = ctk.CTkOptionMenu(
            mode_frame,
            values=["Створити ZIP", "Розпакувати"],
            variable=self._archive_mode_var,
            command=self._on_archive_mode_change,
            width=170,
            height=MENU_HEIGHT,
            fg_color=CARD_COLOR,
            button_color=ELEVATED_COLOR,
            button_hover_color=SECONDARY_HOVER_COLOR,
            dropdown_fg_color=CARD_COLOR,
            dropdown_hover_color=ELEVATED_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._archive_mode_menu.pack(side="left")

        self._archive_create_container = ctk.CTkFrame(tab, fg_color="transparent")
        self._archive_create_container.grid(row=1, column=0, sticky="nsew")
        self._archive_create_container.grid_columnconfigure(0, weight=1)
        self._archive_create_container.grid_rowconfigure(3, weight=1, minsize=84)
        tab.grid_rowconfigure(1, weight=1)

        create_toolbar = ctk.CTkFrame(self._archive_create_container, fg_color="transparent")
        create_toolbar.grid(row=0, column=0, sticky="ew", pady=(PAD_S, PAD_M))

        self._archive_add_files_button = ctk.CTkButton(
            create_toolbar,
            text="Додати файли",
            command=self._choose_archive_files,
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            fg_color=ACCENT_COLOR,
            hover_color=ACCENT_HOVER_COLOR,
            text_color=ACCENT_TEXT_COLOR,
            font=APP_FONT_MEDIUM,
        )
        self._archive_add_files_button.pack(side="left")
        self._archive_add_folder_button = ctk.CTkButton(
            create_toolbar,
            text="Додати папку",
            command=self._choose_archive_folder,
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            fg_color=SECONDARY_FG_COLOR,
            hover_color=SECONDARY_HOVER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._archive_add_folder_button.pack(side="left", padx=(PAD_M, 0))
        self._archive_clear_button = ctk.CTkButton(
            create_toolbar,
            text="Очистити",
            command=self._clear_archive_items,
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            fg_color=SECONDARY_FG_COLOR,
            hover_color=SECONDARY_HOVER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._archive_clear_button.pack(side="left", padx=(PAD_M, 0))

        ctk.CTkLabel(
            create_toolbar,
            text=DROP_TITLE,
            font=APP_FONT,
            text_color=TEXT_MUTED,
        ).pack(side="left", padx=(PAD_L, 0))

        self._build_archive_settings(self._archive_create_container)

        self._archive_counter = ctk.CTkLabel(self._archive_create_container, text="", anchor="w", text_color=TEXT_SECONDARY)
        self._archive_counter.grid(row=2, column=0, sticky="ew", pady=(0, PAD_S))

        self._archive_list = ctk.CTkScrollableFrame(
            self._archive_create_container,
            label_text="Файли та папки для архіву",
            height=110,
            fg_color=CARD_COLOR,
            corner_radius=CARD_CORNER_RADIUS,
            border_width=GROUP_BORDER_WIDTH,
            border_color=BORDER_COLOR,
            label_fg_color=CARD_COLOR,
            label_text_color=TEXT_SECONDARY,
        )
        self._archive_list.grid(row=3, column=0, sticky="nsew")

        self._build_archive_progress(self._archive_create_container)

        # Розпаковка
        self._archive_extract_container = ctk.CTkFrame(tab, fg_color="transparent")
        self._archive_extract_container.grid(row=1, column=0, sticky="nsew")
        self._archive_extract_container.grid_columnconfigure(0, weight=1)
        self._archive_extract_container.grid_rowconfigure(3, weight=1, minsize=84)
        self._archive_extract_container.grid_remove()
        tab.grid_rowconfigure(1, weight=1)

        extract_toolbar = ctk.CTkFrame(self._archive_extract_container, fg_color="transparent")
        extract_toolbar.grid(row=0, column=0, sticky="ew", pady=(PAD_S, PAD_M))
        self._extract_choose_button = ctk.CTkButton(
            extract_toolbar,
            text="Вибрати архів",
            command=self._choose_extract_archive,
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            fg_color=ACCENT_COLOR,
            hover_color=ACCENT_HOVER_COLOR,
            text_color=ACCENT_TEXT_COLOR,
            font=APP_FONT_MEDIUM,
        )
        self._extract_choose_button.pack(side="left")
        self._extract_clear_button = ctk.CTkButton(
            extract_toolbar,
            text="Очистити",
            command=self._clear_extract_archive,
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            fg_color=SECONDARY_FG_COLOR,
            hover_color=SECONDARY_HOVER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._extract_clear_button.pack(side="left", padx=(PAD_M, 0))

        ctk.CTkLabel(
            extract_toolbar,
            text=DROP_ARCHIVE_TITLE,
            font=APP_FONT,
            text_color=TEXT_MUTED,
        ).pack(side="left", padx=(PAD_L, 0))

        extract_settings = ctk.CTkFrame(
            self._archive_extract_container,
            fg_color=CARD_COLOR,
            corner_radius=CARD_CORNER_RADIUS,
            border_width=GROUP_BORDER_WIDTH,
            border_color=BORDER_COLOR,
        )
        extract_settings.grid(row=1, column=0, sticky="ew", pady=(0, PAD_M))
        dest_row = self._settings_row(extract_settings)
        self._row_label(dest_row, "Папка призначення:")
        self._extract_output_text = ctk.StringVar(value="У нову підпапку біля архіву (за замовчуванням)")
        self._extract_output_entry = ctk.CTkEntry(
            dest_row,
            textvariable=self._extract_output_text,
            state="disabled",
            width=260,
            height=ENTRY_HEIGHT,
            fg_color=FIELD_COLOR,
            border_color=BORDER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._extract_output_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._extract_browse_button = ctk.CTkButton(
            dest_row,
            text="Оглянути…",
            width=100,
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            command=self._choose_extract_output_dir,
            fg_color=SECONDARY_FG_COLOR,
            hover_color=SECONDARY_HOVER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._extract_browse_button.pack(side="left")
        self._extract_reset_button = ctk.CTkButton(
            dest_row,
            text="Скинути",
            width=90,
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            command=self._reset_extract_output_dir,
            state="disabled",
            fg_color=SECONDARY_FG_COLOR,
            hover_color=SECONDARY_HOVER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._extract_reset_button.pack(side="left", padx=(PAD_M, 0))

        self._extract_counter = ctk.CTkLabel(self._archive_extract_container, text="", anchor="w", text_color=TEXT_SECONDARY)
        self._extract_counter.grid(row=2, column=0, sticky="ew", pady=(0, PAD_S))

        self._extract_list = ctk.CTkScrollableFrame(
            self._archive_extract_container,
            label_text="Вміст архіву",
            height=110,
            fg_color=CARD_COLOR,
            corner_radius=CARD_CORNER_RADIUS,
            border_width=GROUP_BORDER_WIDTH,
            border_color=BORDER_COLOR,
            label_fg_color=CARD_COLOR,
            label_text_color=TEXT_SECONDARY,
        )
        self._extract_list.grid(row=3, column=0, sticky="nsew")
        self._archive_extract_container.grid_rowconfigure(3, weight=1, minsize=84)

        extract_progress = ctk.CTkFrame(self._archive_extract_container, fg_color="transparent")
        extract_progress.grid(row=4, column=0, sticky="ew", pady=(PAD_M, PAD_XS))
        self._extract_progress_bar = ctk.CTkProgressBar(
            extract_progress,
            height=8,
            corner_radius=4,
            fg_color=TRACK_COLOR,
            progress_color=MINT_COLOR,
        )
        self._extract_progress_bar.set(0)
        self._extract_progress_bar.pack(side="left", fill="x", expand=True, padx=(0, PAD_L))
        self._extract_progress_label = ctk.CTkLabel(
            extract_progress, text="Оброблено 0 з 0", anchor="e", width=240, text_color=TEXT_SECONDARY
        )
        self._extract_progress_label.pack(side="left")

        extract_actions = ctk.CTkFrame(self._archive_extract_container, fg_color="transparent")
        extract_actions.grid(row=5, column=0, sticky="ew", pady=(0, PAD_S))
        self._extract_button = ctk.CTkButton(
            extract_actions,
            text="Розпакувати все",
            command=self._start_archive_extract,
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            fg_color=ACCENT_COLOR,
            hover_color=ACCENT_HOVER_COLOR,
            text_color=ACCENT_TEXT_COLOR,
            font=APP_FONT_MEDIUM,
        )
        self._extract_button.pack(side="left")
        self._extract_cancel_button = ctk.CTkButton(
            extract_actions,
            text="Скасувати",
            command=self._cancel_archive_extract,
            state="disabled",
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            fg_color=SECONDARY_FG_COLOR,
            hover_color=SECONDARY_HOVER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._extract_cancel_button.pack(side="left", padx=(PAD_M, 0))
        self._extract_open_button = ctk.CTkButton(
            extract_actions,
            text="Відкрити папку",
            command=self._open_extract_output_folder,
            state="disabled",
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            fg_color=SECONDARY_FG_COLOR,
            hover_color=SECONDARY_HOVER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._extract_open_button.pack(side="right")

        self._set_archive_mode_frames("Створити ZIP")

        self._make_drop_zone(
            (
                self._archive_create_container,
                create_toolbar,
                self._archive_counter,
                self._archive_list,
                self._archive_extract_container,
                extract_toolbar,
                self._extract_counter,
                self._extract_list,
            ),
            self._on_archive_drop_any,
        )

    def _build_archive_settings(self, tab: ctk.CTkFrame) -> None:
        settings = ctk.CTkFrame(
            tab,
            fg_color=CARD_COLOR,
            corner_radius=CARD_CORNER_RADIUS,
            border_width=GROUP_BORDER_WIDTH,
            border_color=BORDER_COLOR,
        )
        settings.grid(row=1, column=0, sticky="ew", pady=(0, PAD_M))

        # Рядок 1: ім'я архіву
        name_row = self._settings_row(settings)
        self._row_label(name_row, "Ім'я архіву:")
        self._archive_zip_name_var = ctk.StringVar(value="archive")
        self._archive_zip_name_entry = ctk.CTkEntry(
            name_row,
            textvariable=self._archive_zip_name_var,
            width=200,
            height=ENTRY_HEIGHT,
            fg_color=FIELD_COLOR,
            border_color=BORDER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._archive_zip_name_entry.pack(side="left", padx=(0, 8))
        self._archive_zip_name_entry.bind("<KeyRelease>", self._on_archive_name_changed)
        self._archive_zip_name_entry.bind("<FocusOut>", self._on_archive_name_changed)
        ctk.CTkLabel(name_row, text=".zip", anchor="w", text_color=TEXT_SECONDARY).pack(side="left")

        # Рядок 2: рівень стиснення та папка
        comp_row = self._settings_row(settings)
        self._row_label(comp_row, "Рівень стиснення:")
        self._archive_compression_var = ctk.StringVar(value="Нормальне (6)")
        self._archive_compression_menu = ctk.CTkOptionMenu(
            comp_row,
            values=["Без стиснення (0)", "Швидке (3)", "Нормальне (6)", "Максимальне (9)"],
            variable=self._archive_compression_var,
            width=170,
            height=MENU_HEIGHT,
            fg_color=ELEVATED_COLOR,
            button_color=ELEVATED_COLOR,
            button_hover_color=SECONDARY_HOVER_COLOR,
            dropdown_fg_color=CARD_COLOR,
            dropdown_hover_color=ELEVATED_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._archive_compression_menu.pack(side="left", padx=(0, 18))

        self._row_label(comp_row, "Папка:")
        self._archive_use_source_folder = True
        self._archive_output_text = ctk.StringVar(value=SAME_FOLDER_TEXT)
        self._archive_output_entry = ctk.CTkEntry(
            comp_row,
            textvariable=self._archive_output_text,
            state="disabled",
            width=180,
            height=ENTRY_HEIGHT,
            fg_color=FIELD_COLOR,
            border_color=BORDER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._archive_output_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self._archive_browse_button = ctk.CTkButton(
            comp_row,
            text="Оглянути…",
            width=100,
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            command=self._choose_archive_output_dir,
            fg_color=SECONDARY_FG_COLOR,
            hover_color=SECONDARY_HOVER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._archive_browse_button.pack(side="left")
        self._archive_reset_button = ctk.CTkButton(
            comp_row,
            text="Скинути",
            width=90,
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            command=self._reset_archive_output_dir,
            state="disabled",
            fg_color=SECONDARY_FG_COLOR,
            hover_color=SECONDARY_HOVER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._archive_reset_button.pack(side="left", padx=(PAD_M, 0))

    def _build_archive_progress(self, tab: ctk.CTkFrame) -> None:
        progress_frame = ctk.CTkFrame(tab, fg_color="transparent")
        progress_frame.grid(row=4, column=0, sticky="ew", pady=(PAD_M, PAD_XS))

        self._archive_progress_bar = ctk.CTkProgressBar(
            progress_frame,
            height=8,
            corner_radius=4,
            fg_color=TRACK_COLOR,
            progress_color=MINT_COLOR,
        )
        self._archive_progress_bar.set(0)
        self._archive_progress_bar.pack(side="left", fill="x", expand=True, padx=(0, PAD_L))

        self._archive_progress_label = ctk.CTkLabel(
            progress_frame, text="Оброблено 0 з 0", anchor="e", width=240, text_color=TEXT_SECONDARY
        )
        self._archive_progress_label.pack(side="left")

        actions = ctk.CTkFrame(tab, fg_color="transparent")
        actions.grid(row=5, column=0, sticky="ew", pady=(0, PAD_S))

        self._archive_create_button = ctk.CTkButton(
            actions,
            text="Створити ZIP",
            command=self._start_archive_creation,
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            fg_color=ACCENT_COLOR,
            hover_color=ACCENT_HOVER_COLOR,
            text_color=ACCENT_TEXT_COLOR,
            font=APP_FONT_MEDIUM,
        )
        self._archive_create_button.pack(side="left")

        self._archive_cancel_button = ctk.CTkButton(
            actions,
            text="Скасувати",
            command=self._cancel_archive_creation,
            state="disabled",
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            fg_color=SECONDARY_FG_COLOR,
            hover_color=SECONDARY_HOVER_COLOR,
            text_color=TEXT_PRIMARY,
        )
        self._archive_cancel_button.pack(side="left", padx=(PAD_M, 0))

        self._archive_open_folder_button = ctk.CTkButton(
            actions,
            text="Відкрити папку",
            command=self._open_archive_output_folder,
            state="disabled",
            height=BTN_HEIGHT,
            corner_radius=BTN_CORNER_RADIUS,
            fg_color=SECONDARY_FG_COLOR,
            hover_color=SECONDARY_HOVER_COLOR,
            text_color=TEXT_PRIMARY,
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

    def _remove_converter_file(self, index: int) -> None:
        if self._converter_running:
            return
        removed = remove_item_at(self._converter_files, index)
        if removed is None:
            return
        self._reset_conversion_progress()
        self._refresh_converter_list()
        self._set_status(f"Видалено: {removed.name}")
        if not self._converter_files:
            self._set_status("Список файлів порожній")

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
        self._fill_list(
            self._converter_list,
            entries,
            self._remove_converter_file,
            self._converter_remove_buttons,
            "disabled" if self._converter_running else "normal",
        )

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

        for button in self._converter_remove_buttons:
            button.configure(state=state)

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

    def _remove_data_file(self, index: int) -> None:
        if self._data_running:
            return
        removed = remove_item_at(self._data_files, index)
        if removed is None:
            return
        self._reset_data_progress()
        self._refresh_data_list()
        self._set_status(f"Видалено: {removed.name}")
        if not self._data_files:
            self._set_status("Список файлів даних порожній")

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
        self._fill_list(
            self._data_list,
            entries,
            self._remove_data_file,
            self._data_remove_buttons,
            "disabled" if self._data_running else "normal",
        )

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

        for button in self._data_remove_buttons:
            button.configure(state=state)

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

    # --- відео: вибір файлів ------------------------------------------------

    def _choose_video_files(self) -> None:
        chosen = filedialog.askopenfilenames(
            parent=self, title=SELECT_VIDEO_FILES_TITLE, filetypes=VIDEO_FILTER
        )
        added = sum(
            1 for raw in chosen if self._append_path(self._video_files, Path(raw))
        )
        if not added:
            return
        self._reset_video_progress()
        self._refresh_video_list()
        self._set_status(
            f"Додано відео: {added}. Усього: {len(self._video_files)}"
        )

    def _clear_video_files(self) -> None:
        if not self._video_files:
            self._set_status("Список відео вже порожній")
            return
        self._video_files.clear()
        self._reset_video_progress()
        self._refresh_video_list()
        self._set_status("Список відео очищено")

    def _remove_video_file(self, index: int) -> None:
        if self._video_running:
            return
        removed = remove_item_at(self._video_files, index)
        if removed is None:
            return
        self._reset_video_progress()
        self._refresh_video_list()
        self._set_status(f"Видалено: {removed.name}")
        if not self._video_files:
            self._set_status("Список відео порожній")

    def _refresh_video_list(self) -> None:
        entries: list[str | tuple[str, str]] = []
        unsupported = 0
        for index, path in enumerate(self._video_files, start=1):
            if video_converter.is_supported_video(path):
                entries.append(f"{index}. {path.name}")
            else:
                unsupported += 1
                entries.append(
                    (
                        f"{index}. {path.name} — формат не підтримується",
                        UNSUPPORTED_COLOR,
                    )
                )
        self._fill_list(
            self._video_list,
            entries,
            self._remove_video_file,
            self._video_remove_buttons,
            "disabled" if self._video_running else "normal",
        )

        supported = len(self._video_files) - unsupported
        text = f"Вибрано файлів: {len(self._video_files)} (підтримується: {supported})"
        if unsupported:
            text += f", непідтримуваних: {unsupported}"
        self._video_counter.configure(text=text)

    # --- відео: налаштування ------------------------------------------------

    def _current_video_target(self) -> video_converter.OutputFormat:
        label = self._video_format_menu.get()
        for fmt, fmt_label in VIDEO_TARGET_LABELS.items():
            if fmt_label == label:
                return fmt
        return video_converter.OutputFormat.MP4

    def _current_video_quality(self) -> QualityPreset:
        label = self._video_quality_menu.get()
        for preset, preset_label in VIDEO_QUALITY_LABELS.items():
            if preset_label == label:
                return preset
        return QualityPreset.BALANCED

    def _current_video_height(self) -> MaxHeight:
        label = self._video_height_menu.get()
        for height, height_label in VIDEO_HEIGHT_LABELS.items():
            if height_label == label:
                return height
        return MaxHeight.P720

    def _on_video_format_change(self, _choice: str | None = None) -> None:
        self._refresh_video_controls()

    def _on_video_quality_change(self, _choice: str | None = None) -> None:
        self._refresh_video_controls()

    def _refresh_video_controls(self) -> None:
        """Вмикає лише ті налаштування, які впливають на вибраний формат."""
        if self._video_running:
            return

        target = self._current_video_target()
        self._set_enabled(self._video_height_menu, video_height_enabled(target))
        self._set_enabled(self._video_sound_check, video_sound_enabled(target))
        self._set_enabled(self._video_quality_menu, video_quality_enabled(target))

        if not video_quality_enabled(target):
            quality_hint = "WAV без стиснення"
        elif target is video_converter.OutputFormat.GIF:
            quality_hint = "впливає на fps і палітру"
        elif target is video_converter.OutputFormat.WEBM:
            quality_hint = "VP9: менше — легший файл"
        else:
            quality_hint = "менше — легший файл"
        self._video_quality_hint.configure(text=quality_hint)

        if target is video_converter.OutputFormat.GIF:
            sound_hint = "GIF завжди без звуку"
        elif target in video_converter.AUDIO_OUTPUT_FORMATS:
            sound_hint = "не застосовується"
        else:
            sound_hint = "прибрати аудіодоріжку"
        self._video_sound_hint.configure(text=sound_hint)

    def _collect_video_options(self) -> VideoOptions:
        """Збирає налаштування вкладки «Відео»."""
        return VideoOptions(
            target=self._current_video_target(),
            quality=self._current_video_quality(),
            max_height=self._current_video_height(),
            no_audio=self._video_sound_var.get(),
        )

    def _set_video_output_dir(self, path: Path | None) -> None:
        """Папка результатів відео; None — поруч з оригіналами."""
        self._video_output_dir = path
        self._video_use_source_folder = path is None
        self._video_output_text.set(
            str(path) if path is not None else SAME_FOLDER_TEXT
        )
        if not self._video_running:
            self._video_reset_output_button.configure(
                state="disabled" if path is None else "normal"
            )

    def _choose_video_output_dir(self) -> None:
        chosen = filedialog.askdirectory(
            parent=self,
            title=CHOOSE_OUTPUT_TITLE,
            mustexist=True,
            initialdir=str(self._video_output_dir) if self._video_output_dir else None,
        )
        if not chosen:
            return
        self._set_video_output_dir(Path(chosen))
        self._set_status(f"Папка результатів відео: {chosen}")

    def _reset_video_output_dir(self) -> None:
        self._set_video_output_dir(None)
        self._set_status("Відео зберігатиметься поруч з оригіналами")

    # --- відео: запуск і прогрес --------------------------------------------

    def _start_video_conversion(self) -> None:
        if self._video_running:
            return

        sources = [
            path for path in self._video_files
            if video_converter.is_supported_video(path)
        ]
        self._video_skipped_unsupported = len(self._video_files) - len(sources)
        if not sources:
            self._set_status(
                "Немає файлів для конвертації — додайте MP4, MKV, AVI, MOV, "
                "WebM, FLV або WMV"
            )
            return

        try:
            options = self._collect_video_options()
        except ValueError as exc:
            self._set_status(f"Перевірте налаштування: {exc}")
            return

        output_dir = None
        if not self._video_use_source_folder:
            output_dir = self._video_output_dir
            if output_dir is None or not output_dir.is_dir():
                self._set_status("Виберіть існуючу папку для результатів")
                return

        self._video_cancel_event.clear()
        self._video_last_output_dir = None
        self._video_total = len(sources)
        self._set_video_busy(True)
        self._video_progress_bar.set(0)
        self._video_progress_label.configure(
            text=f"Оброблено 0 з {len(sources)}"
        )
        self._set_status(f"Конвертація відео: {len(sources)} файлів…")

        thread = threading.Thread(
            target=self._video_worker,
            args=(sources, options, output_dir),
            daemon=True,
        )
        thread.start()
        self.after(PROGRESS_POLL_MS, self._poll_video_queue)

    def _video_worker(
        self,
        sources: list[Path],
        options: VideoOptions,
        output_dir: Path | None,
    ) -> None:
        """Виконується у фоновому потоці й лише кладе події в чергу."""
        try:
            results = video_converter.convert_video_batch(
                sources,
                options,
                output_dir,
                on_progress=self._report_video_progress,
                should_cancel=self._video_cancel_event.is_set,
            )
        except Exception as exc:  # несподівана помилка не має «вбити» інтерфейс
            self._video_queue.put(("error", str(exc)))
            return
        self._video_queue.put(("done", results))

    def _report_video_progress(
        self,
        done: int,
        total: int,
        source: Path | None,
        fraction: float | None,
    ) -> None:
        self._video_queue.put(("progress", done, total, source, fraction))

    def _poll_video_queue(self) -> None:
        finished = False
        while True:
            try:
                event = self._video_queue.get_nowait()
            except queue.Empty:
                break
            kind = event[0]
            if kind == "progress":
                _, done, total, source, fraction = event
                if not total:
                    continue
                if done >= total:
                    self._video_progress_bar.set(1.0)
                    text = f"Готово: {total} з {total}"
                else:
                    overall = (done + (fraction or 0.0)) / total
                    self._video_progress_bar.set(max(0.0, min(1.0, overall)))
                    text = f"Файл {done + 1} з {total}"
                    if fraction is not None:
                        text += f" · {round(fraction * 100)}%"
                    if source is not None:
                        text += f" · {source.name}"
                self._video_progress_label.configure(text=text)
            elif kind == "done":
                self._finish_video_conversion(event[1])
                finished = True
            elif kind == "error":
                self._set_video_busy(False)
                self._set_status(f"Помилка конвертації відео: {event[1]}")
                finished = True

        if not finished:
            self.after(PROGRESS_POLL_MS, self._poll_video_queue)

    def _finish_video_conversion(
        self, results: list[video_converter.VideoConversionResult]
    ) -> None:
        self._set_video_busy(False)
        cancelled = self._video_cancel_event.is_set()
        total = max(self._video_total, len(results))
        succeeded = [result for result in results if result.ok]
        failed = [result for result in results if not result.ok]

        if total:
            if cancelled:
                self._video_progress_bar.set(len(results) / total)
            else:
                self._video_progress_bar.set(1.0)
        self._video_progress_label.configure(
            text=f"Оброблено {len(results)} з {total}"
        )
        if succeeded:
            last_destination = succeeded[-1].destination
            if last_destination is not None:
                self._video_last_output_dir = last_destination.parent
                self._video_open_folder_button.configure(state="normal")
        if failed:
            self._show_video_failures(failed)

        if cancelled:
            summary = f"Скасовано: оброблено {len(results)} з {total}"
        else:
            summary = f"Готово: {len(succeeded)} з {total}"
        if failed:
            summary += f", помилок: {len(failed)}"
        if self._video_skipped_unsupported:
            summary += f", пропущено непідтримуваних: {self._video_skipped_unsupported}"
        self._set_status(summary)

    def _show_video_failures(
        self, failed: list[video_converter.VideoConversionResult]
    ) -> None:
        lines = [
            f"• {result.source.name}: {result.message}"
            for result in failed[:MAX_FAILURE_LINES]
        ]
        if len(failed) > MAX_FAILURE_LINES:
            lines.append(f"…та ще {len(failed) - MAX_FAILURE_LINES}")
        messagebox.showwarning(
            "Не вдалося конвертувати відео", "\n".join(lines), parent=self
        )

    def _cancel_video_conversion(self) -> None:
        if not self._video_running:
            return
        self._video_cancel_event.set()
        self._video_cancel_button.configure(state="disabled")
        self._set_status("Скасування… зупиняємо ffmpeg")

    def _set_video_busy(self, busy: bool) -> None:
        self._video_running = busy
        state = "disabled" if busy else "normal"
        for widget in (
            self._video_choose_button,
            self._video_clear_button,
            self._video_convert_button,
            self._video_format_menu,
            self._video_quality_menu,
            self._video_height_menu,
            self._video_sound_check,
            self._video_browse_output_button,
            self._video_reset_output_button,
        ):
            widget.configure(state=state)
        self._video_cancel_button.configure(state="normal" if busy else "disabled")

        for button in self._video_remove_buttons:
            button.configure(state=state)

        if not busy:
            self._refresh_video_controls()
            self._video_reset_output_button.configure(
                state="disabled" if self._video_use_source_folder else "normal"
            )

    def _open_video_output_folder(self) -> None:
        folder = self._video_last_output_dir
        if folder is None or not folder.is_dir():
            self._set_status("Папка з результатами ще не готова")
            return
        try:
            os.startfile(folder)  # type: ignore[attr-defined]
        except OSError as exc:
            self._set_status(f"Не вдалося відкрити папку: {exc}")

    def _reset_video_progress(self) -> None:
        self._video_total = 0
        self._video_progress_bar.set(0)
        self._video_progress_label.configure(text="Оброблено 0 з 0")
        self._video_last_output_dir = None
        self._video_open_folder_button.configure(state="disabled")

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

    def _remove_archive_item(self, index: int) -> None:
        if self._archive_running:
            return
        removed = remove_item_at(self._archive_items, index)
        if removed is None:
            return
        self._update_archive_suggested_name()
        self._reset_archive_progress()
        self._refresh_archive_list()
        self._set_status(f"Видалено: {removed.name}")
        if not self._archive_items:
            self._set_status("Список архіву порожній")

    def _refresh_archive_list(self) -> None:
        labels = [
            f"{index}. [{'папка' if path.is_dir() else 'файл'}] {path.name}"
            for index, path in enumerate(self._archive_items, start=1)
        ]
        self._fill_list(
            self._archive_list,
            labels,
            self._remove_archive_item,
            self._archive_remove_buttons,
            "disabled" if self._archive_running else "normal",
        )
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
        for button in self._archive_remove_buttons:
            button.configure(state=state)
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
    def _set_archive_mode_frames(self, choice: str) -> None:
        if choice == "Розпакувати":
            self._archive_mode = "extract"
            self._archive_create_container.grid_remove()
            self._archive_extract_container.grid()
        else:
            self._archive_mode = "create"
            self._archive_extract_container.grid_remove()
            self._archive_create_container.grid()

    def _on_archive_mode_change(self, choice: str | None = None) -> None:
        if choice is None:
            choice = self._archive_mode_var.get()
        self._set_archive_mode_frames(choice)
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
        self._set_extract_archive(Path(chosen))

    def _set_extract_archive(self, path: Path) -> bool:
        """Готує архів до розпаковки; False — формат не підтримується."""
        if not archive.is_supported_extract_archive(path):
            self._set_status("Непідтримуваний формат архіву")
            messagebox.showwarning("Помилка", "Непідтримуваний формат архіву", parent=self)
            return False
        try:
            entries = archive.list_archive(path)
        except Exception as exc:
            self._set_status(f"Помилка: {exc}")
            messagebox.showwarning("Помилка", str(exc), parent=self)
            return False
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
        return True

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

    # --- перетягування файлів -----------------------------------------------

    def _enable_dnd(self) -> bool:
        """Підключає tkdnd до вікна; без бібліотеки програма працює як раніше."""
        if TkinterDnD is None:
            return False
        try:
            TkinterDnD._require(self)
        except Exception:
            return False
        return True

    def _make_drop_zone(self, widgets, handler) -> None:
        """Реєструє віджети як цілі для перетягування (тихо, якщо tkdnd немає)."""
        if not self._dnd_ready:
            return
        for widget in widgets:
            try:
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", handler)
            except Exception:
                continue

    def _add_dropped_files(
        self,
        items: list[Path],
        paths: list[Path],
        refresh,
        reset_progress,
        status_text: str,
    ) -> None:
        """Додає перетягнуті файли так само, як ручний вибір: з підсвіткою."""
        added = sum(1 for path in paths if self._append_path(items, path))
        if not added:
            self._set_status("Ці файли вже у списку")
            return
        reset_progress()
        refresh()
        self._set_status(f"{status_text}: {added}. Усього: {len(items)}")

    def _on_converter_drop(self, event):
        if self._converter_running:
            return REFUSE_DROP
        paths = parse_dropped_paths(getattr(event, "data", None))
        if paths:
            self._add_dropped_files(
                self._converter_files,
                paths,
                self._refresh_converter_list,
                self._reset_conversion_progress,
                "Додано файлів",
            )
        return DND_COPY

    def _on_data_drop(self, event):
        if self._data_running:
            return REFUSE_DROP
        paths = parse_dropped_paths(getattr(event, "data", None))
        if paths:
            self._add_dropped_files(
                self._data_files,
                paths,
                self._refresh_data_list,
                self._reset_data_progress,
                "Додано файлів даних",
            )
        return DND_COPY

    def _on_video_drop(self, event):
        if self._video_running:
            return REFUSE_DROP
        paths = parse_dropped_paths(getattr(event, "data", None))
        if paths:
            self._add_dropped_files(
                self._video_files,
                paths,
                self._refresh_video_list,
                self._reset_video_progress,
                "Додано відео",
            )
        return DND_COPY

    def _on_archive_drop(self, event):
        if self._archive_running or self._archive_mode != "create":
            return REFUSE_DROP
        paths = parse_dropped_paths(getattr(event, "data", None))
        added = sum(1 for path in paths if self._append_path(self._archive_items, path))
        if not paths:
            return DND_COPY
        if not added:
            self._set_status("Ці елементи вже у списку")
            return DND_COPY
        self._reset_archive_progress()
        self._update_archive_suggested_name()
        self._refresh_archive_list()
        self._set_status(
            f"Додано до архіву: {added}. Усього: {len(self._archive_items)}"
        )
        return DND_COPY

    def _on_extract_drop(self, event):
        if self._extract_running or self._archive_mode != "extract":
            return REFUSE_DROP
        paths = [path for path in parse_dropped_paths(getattr(event, "data", None)) if path.is_file()]
        if not paths:
            self._set_status("Перетягни один архів: ZIP, TAR або 7z")
            return DND_COPY
        chosen = next(
            (path for path in paths if archive.is_supported_extract_archive(path)),
            None,
        )
        if chosen is None:
            self._set_status("Непідтримуваний формат архіву")
            return DND_COPY
        if self._set_extract_archive(chosen) and len(paths) > 1:
            self._set_status(
                f"Перетягнуто кілька файлів — обрано архів: {chosen.name}"
            )
        return DND_COPY

    def _on_archive_drop_any(self, event):
        """Один обробник на вкладку «Архіви»: режим визначає, що робити."""
        if self._archive_mode == "extract":
            return self._on_extract_drop(event)
        return self._on_archive_drop(event)

    def _fill_list(
        self,
        container: ctk.CTkScrollableFrame,
        entries,
        on_remove=None,
        buttons: list | None = None,
        remove_state: str = "normal",
    ) -> None:
        for child in container.winfo_children():
            child.destroy()
        if buttons is not None:
            buttons.clear()
        for index, entry in enumerate(entries, start=1):
            color = None
            if isinstance(entry, tuple):
                text, color = entry
            elif isinstance(entry, str):
                text = entry
            else:
                text = f"{index}. {entry.name}"
            if on_remove is None:
                ctk.CTkLabel(
                    container,
                    text=text,
                    anchor="w",
                    text_color=color,
                ).pack(fill="x", padx=8, pady=2)
                continue
            row = ctk.CTkFrame(container, fg_color="transparent")
            row.pack(fill="x", padx=8, pady=2)
            ctk.CTkLabel(
                row,
                text=text,
                anchor="w",
                text_color=color,
            ).pack(side="left", fill="x", expand=True)
            button = ctk.CTkButton(
                row,
                text="✕",
                width=26,
                height=22,
                corner_radius=6,
                command=lambda i=index - 1: self.after_idle(lambda: on_remove(i)),
                state=remove_state,
                fg_color=SECONDARY_FG_COLOR,
                hover_color=SECONDARY_HOVER_COLOR,
                text_color=TEXT_PRIMARY,
            )
            button.pack(side="right", padx=(PAD_S, 0))
            if buttons is not None:
                buttons.append(button)

        # Після оновлення списку показуємо його початок, а не залишок прокрутки.
        canvas = getattr(container, "_parent_canvas", None)
        if canvas is not None:
            try:
                container.after_idle(canvas.yview_moveto, 0.0)
            except Exception:
                pass

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
        height = min(max(self.winfo_reqheight(), WINDOW_SIZE[1]), screen_height - 64)

        tkinter.Wm.wm_minsize(
            self, min(MIN_SIZE[0], width), min(MIN_SIZE[1], height)
        )
        x = max((screen_width - width) // 2, 0)
        y = max((screen_height - height) // 3, 0)
        tkinter.Wm.wm_geometry(self, f"{width}x{height}+{x}+{y}")
