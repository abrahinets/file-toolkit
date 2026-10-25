"""Логіка конвертації даних: JSON, CSV, TXT.

Модуль навмисно не залежить від інтерфейсу і використовує лише
стандартну бібліотеку, щоб його можна було тестувати окремо.
Усі повідомлення про помилки — українською, щоб інтерфейс показував
їх без перекладу.
"""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Callable, Iterable, Sequence

SUPPORTED_INPUT_SUFFIXES = frozenset({".json", ".csv", ".txt"})

# Ліміти захищають від випадкового «з'їдання» пам'яті величезним файлом.
MAX_INPUT_BYTES = 200 * 1024 * 1024
MAX_ROWS = 1_000_000

# Як часто перевіряти скасування всередині великого файлу.
CANCEL_CHECK_ROWS = 1000
SAMPLE_BYTES = 65536
SNIFF_LINES = 20

# Скільки місця приблизно потрібно на виході відносно вхідного файлу.
SPACE_FACTOR = 2.0
SPACE_RESERVE_BYTES = 1_000_000

DEFAULT_CSV_DELIMITER = ","
DEFAULT_TXT_DELIMITER = "\t"
DELIMITER_CANDIDATES = ",;\t|"

AUTO_ENCODING = "auto"
INPUT_ENCODINGS = (AUTO_ENCODING, "utf-8", "utf-8-sig", "cp1251")
OUTPUT_ENCODINGS = ("utf-8", "utf-8-sig", "cp1251")
NEWLINES = ("\n", "\r\n")

ENCODING_LABELS = {
    "utf-8": "UTF-8",
    "utf-8-sig": "UTF-8 з BOM",
    "cp1251": "Windows-1251",
    "latin-1": "latin-1",
}

WARNING_EMPTY_FILE = "Файл порожній"
WARNING_EMPTY_ARRAY = "JSON містить порожній масив"
WARNING_EMPTY_OBJECT = "JSON містить порожній об'єкт"
WARNING_EMPTY_VALUE = "JSON містить null — таблиця порожня"
WARNING_NO_DELIMITER = "Роздільник не знайдено — текст читається як один стовпець"
WARNING_RAGGED = "Рядків з іншою кількістю колонок: {count}"
WARNING_ENCODING = "Кодування визначено як {label}"

# Клітинка не може бути довшою за весь файл, а стандартний ліміт csv — лише
# 131072 символи, тому піднімаємо його до ліміту вхідного файлу.
csv.field_size_limit(MAX_INPUT_BYTES)

# Провідний «+» не вважаємо числом, щоб телефон «+380…» лишався текстом.
_INT_RE = re.compile(r"-?(?:0|[1-9]\d*)\Z")
_FLOAT_RE = re.compile(r"-?(?:\d+\.\d*|\.\d+|\d+[eE][+-]?\d+|\d+\.\d*[eE][+-]?\d+)\Z")


class DataConvertError(Exception):
    """Помилка конвертації з готовим текстом для інтерфейсу."""


class UnsupportedDataFormatError(DataConvertError):
    """Формат файлу або пара форматів не підтримується."""


class CorruptedDataError(DataConvertError):
    """Файл пошкоджений або не є текстом у вказаному кодуванні."""


class SourceMissingError(DataConvertError):
    """Вихідний файл не знайдено."""


class DestinationBusyError(DataConvertError):
    """Файл або папка призначення зайняті іншою програмою."""


class NoSpaceError(DataConvertError):
    """На диску недостатньо місця."""


class DataTooLargeError(DataConvertError):
    """Перевищено ліміт розміру файлу або кількості рядків."""


class ConversionCancelled(DataConvertError):
    """Обробку скасовано користувачем; файл не вважається помилкою."""


class OutputFormat(StrEnum):
    """Цільовий формат даних."""

    JSON = "json"
    CSV = "csv"
    TXT = "txt"


class TxtLayout(StrEnum):
    """Як подавати таблицю у TXT."""

    ALIGNED = "aligned"
    DELIMITED = "delimited"


OUTPUT_SUFFIXES = {
    OutputFormat.JSON: ".json",
    OutputFormat.CSV: ".csv",
    OutputFormat.TXT: ".txt",
}

OUTPUT_FORMAT_LABELS = {
    OutputFormat.JSON: "JSON",
    OutputFormat.CSV: "CSV",
    OutputFormat.TXT: "TXT",
}


@dataclass(frozen=True)
class DataOptions:
    """Налаштування конвертації даних."""

    target: OutputFormat = OutputFormat.JSON
    delimiter: str | None = None
    output_delimiter: str | None = None
    has_header: bool = True
    detect_types: bool = False
    json_indent: int | None = 2
    sort_keys: bool = False
    txt_layout: TxtLayout = TxtLayout.ALIGNED
    input_encoding: str = AUTO_ENCODING
    output_encoding: str = "utf-8"
    newline: str = "\n"
    overwrite: bool = False

    def __post_init__(self) -> None:
        for name, value in (
            ("Роздільник", self.delimiter),
            ("Роздільник результату", self.output_delimiter),
        ):
            if value is not None and (len(value) != 1 or value in '"\r\n'):
                raise ValueError(
                    f"{name} має бути одним символом, крім лапок і переносів рядка"
                )
        if self.json_indent is not None and not 0 <= self.json_indent <= 8:
            raise ValueError("Відступ JSON має бути від 0 до 8")
        if self.input_encoding not in INPUT_ENCODINGS:
            raise ValueError(f"Невідоме кодування файлу: {self.input_encoding}")
        if self.output_encoding not in OUTPUT_ENCODINGS:
            raise ValueError(f"Невідоме кодування результату: {self.output_encoding}")
        if self.newline not in NEWLINES:
            raise ValueError("Переноси рядків: LF або CRLF")


@dataclass
class Table:
    """Табличне подання даних: заголовок (може бути відсутній) і рядки."""

    header: list[str] | None = None
    rows: list[list[str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class JsonValue:
    """Довільне JSON-значення, яке не зводиться до таблиці."""

    value: object
    warnings: list[str] = field(default_factory=list)


@dataclass
class DataConversionResult:
    """Результат конвертації одного файлу."""

    source: Path
    destination: Path | None
    ok: bool
    message: str = ""
    source_size: int = 0
    result_size: int = 0


ProgressCallback = Callable[[int, int, Path | None], None]
CancelCallback = Callable[[], bool]


# --- допоміжні перевірки ----------------------------------------------------


def is_supported_data(path: Path) -> bool:
    """Чи підтримується файл за розширенням (швидка перевірка для списку)."""
    return Path(path).suffix.lower() in SUPPORTED_INPUT_SUFFIXES


def detect_encoding(path: Path) -> str:
    """Визначає кодування за BOM, потім пробує UTF-8, Windows-1251, latin-1."""
    try:
        with open(path, "rb") as stream:
            sample = stream.read(SAMPLE_BYTES)
    except OSError as exc:
        raise DataConvertError(f"Не вдалося прочитати файл: {exc}") from exc

    if sample.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if not sample:
        return "utf-8"

    for encoding in ("utf-8", "cp1251"):
        try:
            sample.decode(encoding)
        except UnicodeDecodeError:
            continue
        return encoding
    return "latin-1"


def detect_delimiter(path: Path, encoding: str = "utf-8") -> str:
    """Підбирає роздільник CSV: Sniffer, далі підрахунок символів."""
    sample = _read_sample(path, encoding)
    if not sample.strip():
        return DEFAULT_CSV_DELIMITER
    try:
        return csv.Sniffer().sniff(sample, delimiters=DELIMITER_CANDIDATES).delimiter
    except csv.Error:
        pass

    counts = {
        candidate: sum(line.count(candidate) for line in sample.splitlines()[:SNIFF_LINES])
        for candidate in DELIMITER_CANDIDATES
    }
    best = max(counts, key=counts.get)
    return best if counts[best] else DEFAULT_CSV_DELIMITER


# --- читання ----------------------------------------------------------------


def read_source(
    path: Path,
    options: DataOptions,
    *,
    should_cancel: CancelCallback | None = None,
) -> Table | JsonValue:
    """Читає файл у проміжне подання (таблиця або довільний JSON)."""
    path = Path(path)
    if not path.is_file():
        raise SourceMissingError(f"Файл не знайдено: {path}")

    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_INPUT_SUFFIXES:
        raise UnsupportedDataFormatError(
            f"Формат не підтримується: {suffix or 'без розширення'}"
        )

    _check_input_size(path)
    _check_cancel(should_cancel)

    if suffix == ".json":
        return load_json(path, options, should_cancel=should_cancel)
    if suffix == ".csv":
        return load_csv(path, options, should_cancel=should_cancel)
    return load_txt(path, options, should_cancel=should_cancel)


def load_json(
    path: Path,
    options: DataOptions,
    *,
    should_cancel: CancelCallback | None = None,
) -> Table | JsonValue:
    """Читає JSON. Для CSV/TXT корінь зводиться до таблиці."""
    encoding, warnings = _resolve_input_encoding(path, options)
    text = _read_text(path, encoding)
    _check_cancel(should_cancel)

    if not text.strip():
        raise CorruptedDataError("JSON пошкоджений: файл порожній")

    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CorruptedDataError(
            f"JSON пошкоджений: рядок {exc.lineno}, стовпець {exc.colno}"
        ) from exc

    if options.target is OutputFormat.JSON:
        return JsonValue(value, warnings)
    # Об'єкт і скаляр у TXT зручніше показувати як «ключ: значення».
    if options.target is OutputFormat.TXT and not isinstance(value, list):
        return JsonValue(value, warnings)

    table = _json_to_table(value)
    table.warnings = warnings + table.warnings
    return table


def load_csv(
    path: Path,
    options: DataOptions,
    *,
    should_cancel: CancelCallback | None = None,
) -> Table:
    """Читає CSV з авто-визначенням роздільника та кодування."""
    encoding, warnings = _resolve_input_encoding(path, options)
    delimiter = options.delimiter or detect_delimiter(path, encoding)

    rows: list[list[str]] = []
    try:
        with open(path, "r", encoding=encoding, newline="") as stream:
            reader = csv.reader(stream, delimiter=delimiter, strict=True)
            for index, row in enumerate(reader, start=1):
                if index % CANCEL_CHECK_ROWS == 0:
                    _check_cancel(should_cancel)
                rows.append(row)
                if len(rows) > MAX_ROWS:
                    raise DataTooLargeError(f"Забагато рядків: більше {MAX_ROWS}")
    except UnicodeDecodeError as exc:
        raise CorruptedDataError(
            f"Не вдалося прочитати файл у кодуванні {_encoding_label(encoding)}"
        ) from exc
    except csv.Error as exc:
        raise CorruptedDataError(f"Файл CSV пошкоджений: {exc}") from exc
    except OSError as exc:
        raise DataConvertError(f"Не вдалося прочитати файл: {exc}") from exc

    if not rows:
        return Table(None, [], warnings + [WARNING_EMPTY_FILE])

    if options.has_header:
        header = _normalise_header(rows[0])
        data_rows = rows[1:]
    else:
        header = None
        data_rows = rows
    return _normalise_table(header, data_rows, warnings)


def load_txt(
    path: Path,
    options: DataOptions,
    *,
    should_cancel: CancelCallback | None = None,
) -> Table:
    """Читає TXT: порожній роздільник — один стовпець, інакше — таблиця."""
    encoding, warnings = _resolve_input_encoding(path, options)
    text = _read_text(path, encoding)

    if not text.strip():
        return Table(None, [], warnings + [WARNING_EMPTY_FILE])

    lines = text.splitlines()
    if len(lines) > MAX_ROWS:
        raise DataTooLargeError(f"Забагато рядків: більше {MAX_ROWS}")
    _check_cancel(should_cancel)

    delimiter = options.delimiter or DEFAULT_TXT_DELIMITER
    if not any(delimiter in line for line in lines):
        warnings.append(WARNING_NO_DELIMITER)
        return _normalise_table(None, [[line] for line in lines], warnings)

    rows: list[list[str]] = []
    try:
        reader = csv.reader(lines, delimiter=delimiter, strict=True)
        for index, row in enumerate(reader, start=1):
            if index % CANCEL_CHECK_ROWS == 0:
                _check_cancel(should_cancel)
            rows.append(row)
    except csv.Error as exc:
        raise CorruptedDataError(f"Файл TXT пошкоджений: {exc}") from exc

    if options.has_header:
        header = _normalise_header(rows[0])
        data_rows = rows[1:]
    else:
        header = None
        data_rows = rows
    return _normalise_table(header, data_rows, warnings)


# --- запис ------------------------------------------------------------------


def build_destination(
    source: Path,
    output_dir: Path | None,
    options: DataOptions,
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


def convert_data(
    source: Path,
    destination: Path,
    options: DataOptions,
    *,
    should_cancel: CancelCallback | None = None,
) -> DataConversionResult:
    """Конвертує один файл. Помилки — підкласи DataConvertError."""
    source = Path(source)
    destination = Path(destination)

    if not source.is_file():
        raise SourceMissingError(f"Файл не знайдено: {source}")
    if _path_key(source) == _path_key(destination):
        raise DataConvertError(
            "Джерело та призначення збігаються — оригінал не перезаписуємо"
        )

    source_size = source.stat().st_size
    document = read_source(source, options, should_cancel=should_cancel)
    warnings = list(getattr(document, "warnings", []) or [])

    _check_free_space(destination.parent, source_size)
    _atomic_write(
        destination,
        options,
        lambda handle: _render(
            document, options, handle, should_cancel=should_cancel
        ),
    )

    result_size = destination.stat().st_size if destination.exists() else 0
    return DataConversionResult(
        source=source,
        destination=destination,
        ok=True,
        message="; ".join(warnings),
        source_size=source_size,
        result_size=result_size,
    )


def convert_data_batch(
    sources: Sequence[Path],
    options: DataOptions,
    output_dir: Path | None = None,
    *,
    on_progress: ProgressCallback | None = None,
    should_cancel: CancelCallback | None = None,
) -> list[DataConversionResult]:
    """Конвертує пакет файлів, не зупиняючись на помилках окремих файлів."""
    sources = [Path(source) for source in sources]
    total = len(sources)
    results: list[DataConversionResult] = []
    taken: list[Path] = []

    for index, source in enumerate(sources):
        if should_cancel is not None and should_cancel():
            break
        if on_progress is not None:
            on_progress(index, total, source)
        try:
            destination = build_destination(source, output_dir, options, taken)
            taken.append(destination)
            results.append(
                convert_data(
                    source,
                    destination,
                    options,
                    should_cancel=should_cancel,
                )
            )
        except ConversionCancelled:
            break
        except DataConvertError as exc:
            results.append(
                DataConversionResult(
                    source=source,
                    destination=None,
                    ok=False,
                    message=str(exc),
                    source_size=_safe_size(source),
                )
            )

    if on_progress is not None:
        on_progress(len(results), total, None)
    return results


# --- перетворення подань ----------------------------------------------------


def _json_to_table(value: object) -> Table:
    """Зводить JSON-значення до таблиці для CSV/TXT."""
    if isinstance(value, dict):
        if not value:
            return Table(None, [], [WARNING_EMPTY_OBJECT])
        header = list(value)
        return Table(header, [[_cell_text(value[key]) for key in header]])

    if isinstance(value, list):
        if not value:
            return Table(None, [], [WARNING_EMPTY_ARRAY])
        if all(isinstance(item, dict) for item in value):
            header: list[str] = []
            seen: set[str] = set()
            for item in value:
                for key in item:
                    if key not in seen:
                        seen.add(key)
                        header.append(key)
            rows = [[_cell_text(item.get(key)) for key in header] for item in value]
            return _normalise_table(header, rows)
        if all(isinstance(item, list) for item in value):
            rows = [[_cell_text(cell) for cell in row] for row in value]
            return _normalise_table(None, rows)
        if all(not isinstance(item, (dict, list)) for item in value):
            return _normalise_table(None, [[_cell_text(item)] for item in value])
        raise UnsupportedDataFormatError(
            "JSON містить змішані типи — таблицю з нього не скласти"
        )

    return Table(None, [[_cell_text(value)]])


def _to_json_value(document: Table | JsonValue, options: DataOptions) -> object:
    """Готує значення для запису в JSON."""
    if isinstance(document, JsonValue):
        return document.value

    table = document
    if table.header is not None:
        return [
            {
                name: _json_cell(cell, options)
                for name, cell in zip(table.header, row)
            }
            for row in table.rows
        ]
    if table.rows and all(len(row) == 1 for row in table.rows):
        return [_json_cell(row[0], options) for row in table.rows]
    return [[_json_cell(cell, options) for cell in row] for row in table.rows]


def _as_table(document: Table | JsonValue) -> Table:
    if isinstance(document, Table):
        return document
    return _json_to_table(document.value)


def _render(
    document: Table | JsonValue,
    options: DataOptions,
    handle,
    *,
    should_cancel: CancelCallback | None = None,
) -> None:
    """Записує документ у відкритий текстовий потік."""
    if options.target is OutputFormat.JSON:
        value = _to_json_value(document, options)
        _write_lines(handle, _json_lines(value, options), options, should_cancel)
    elif options.target is OutputFormat.CSV:
        _write_csv(handle, _as_table(document), options, should_cancel)
    elif isinstance(document, JsonValue):
        lines = _value_lines(document.value, 0, options)
        _write_lines(handle, lines, options, should_cancel)
    else:
        _write_txt(handle, document, options, should_cancel)


def _json_lines(value: object, options: DataOptions) -> list[str]:
    indent = options.json_indent or None
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            indent=indent,
            sort_keys=options.sort_keys,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise DataConvertError(f"Не вдалося подати дані як JSON: {exc}") from exc
    return text.splitlines() or [""]


def _write_csv(
    handle,
    table: Table,
    options: DataOptions,
    should_cancel: CancelCallback | None,
) -> None:
    delimiter = _output_delimiter(options)
    writer = csv.writer(handle, delimiter=delimiter, lineterminator=options.newline)
    if table.header:
        writer.writerow(table.header)
    for index, row in enumerate(table.rows, start=1):
        if index % CANCEL_CHECK_ROWS == 0:
            _check_cancel(should_cancel)
        writer.writerow(row)


def _write_txt(
    handle,
    table: Table,
    options: DataOptions,
    should_cancel: CancelCallback | None,
) -> None:
    if options.txt_layout is TxtLayout.DELIMITED:
        delimiter = _output_delimiter(options)
        writer = csv.writer(
            handle, delimiter=delimiter, lineterminator=options.newline
        )
        if table.header:
            writer.writerow([_inline(cell) for cell in table.header])
        for index, row in enumerate(table.rows, start=1):
            if index % CANCEL_CHECK_ROWS == 0:
                _check_cancel(should_cancel)
            writer.writerow([_inline(cell) for cell in row])
        return

    header = [_inline(cell) for cell in (table.header or [])]
    rows = [[_inline(cell) for cell in row] for row in table.rows]
    all_rows = ([header] if header else []) + rows
    if not all_rows:
        return

    width = max(len(row) for row in all_rows)
    widths = [
        max(len(row[column]) if column < len(row) else 0 for row in all_rows)
        for column in range(width)
    ]

    for index, row in enumerate(all_rows, start=1):
        if index % CANCEL_CHECK_ROWS == 0:
            _check_cancel(should_cancel)
        cells = [
            (row[column] if column < len(row) else "").ljust(widths[column])
            for column in range(width)
        ]
        handle.write("  ".join(cells).rstrip())
        handle.write(options.newline)


def _value_lines(
    value: object, indent: int = 0, options: DataOptions | None = None
) -> list[str]:
    """Подає довільний JSON як рядки «ключ: значення» з відступами."""
    prefix = "  " * indent
    if isinstance(value, dict):
        if not value:
            return [prefix + "{}"]
        items = value.items()
        if options is not None and options.sort_keys:
            items = sorted(items)
        lines: list[str] = []
        for key, item in items:
            if isinstance(item, (dict, list)) and item:
                lines.append(f"{prefix}{key}:")
                lines.extend(_value_lines(item, indent + 1, options))
            else:
                lines.append(f"{prefix}{key}: {_plain_text(item)}")
        return lines
    if isinstance(value, list):
        if not value:
            return [prefix + "[]"]
        lines = []
        for item in value:
            if isinstance(item, (dict, list)) and item:
                lines.append(prefix + "-")
                lines.extend(_value_lines(item, indent + 1, options))
            else:
                lines.append(f"{prefix}- {_plain_text(item)}")
        return lines
    return [prefix + _plain_text(value)]


# --- внутрішні кроки --------------------------------------------------------


def _cell_text(value: object) -> str:
    """Текстове подання клітинки для таблиці."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _plain_text(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    if isinstance(value, str):
        return _inline(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _inline(cell: str) -> str:
    """Переноси рядків у клітинці замінюємо видимим позначенням."""
    return cell.replace("\r\n", "\\n").replace("\r", "\\n").replace("\n", "\\n")


def _infer_type(cell: str) -> object:
    """Обережне визначення типів: «007» і телефони лишаються текстом."""
    if cell == "" or cell == "null":
        return None
    lowered = cell.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    if _INT_RE.match(cell):
        return int(cell)
    if _FLOAT_RE.match(cell):
        try:
            return float(cell)
        except ValueError:
            return cell
    return cell


def _json_cell(cell: str, options: DataOptions) -> object:
    return _infer_type(cell) if options.detect_types else cell


def _normalise_header(names: list[str]) -> list[str]:
    """Прибирає порожні назви та робить дублікати унікальними."""
    header: list[str] = []
    seen: set[str] = set()
    for index, raw in enumerate(names, start=1):
        base = raw.strip() or f"column_{index}"
        candidate = base
        counter = 1
        while candidate in seen:
            counter += 1
            candidate = f"{base}_{counter}"
        seen.add(candidate)
        header.append(candidate)
    return header


def _normalise_table(
    header: list[str] | None,
    rows: list[list[str]],
    warnings: list[str] | None = None,
) -> Table:
    """Вирівнює ширину рядків і додає попередження про різну кількість."""
    collected = list(warnings or [])
    header_len = len(header) if header is not None else None
    width = max([header_len or 0] + [len(row) for row in rows])

    if header_len is None:
        ragged = sum(1 for row in rows if len(row) != width)
        normalised_header = None
    else:
        ragged = sum(1 for row in rows if len(row) != header_len)
        normalised_header = list(header or [])
        if len(normalised_header) < width:
            normalised_header.extend(
                f"column_{index}"
                for index in range(len(normalised_header) + 1, width + 1)
            )

    if ragged:
        collected.append(WARNING_RAGGED.format(count=ragged))

    normalised_rows = [row + [""] * (width - len(row)) for row in rows]
    return Table(normalised_header, normalised_rows, collected)


def _resolve_input_encoding(
    path: Path, options: DataOptions
) -> tuple[str, list[str]]:
    if options.input_encoding != AUTO_ENCODING:
        return options.input_encoding, []
    encoding = detect_encoding(path)
    if encoding in ("cp1251", "latin-1"):
        return encoding, [WARNING_ENCODING.format(label=_encoding_label(encoding))]
    return encoding, []


def _encoding_label(encoding: str) -> str:
    return ENCODING_LABELS.get(encoding.lower(), encoding)


def _read_sample(path: Path, encoding: str, size: int = SAMPLE_BYTES) -> str:
    try:
        with open(path, "rb") as stream:
            raw = stream.read(size)
    except OSError as exc:
        raise DataConvertError(f"Не вдалося прочитати файл: {exc}") from exc
    return raw.decode(encoding, errors="replace")


def _read_text(path: Path, encoding: str) -> str:
    try:
        with open(path, "r", encoding=encoding, newline=None) as stream:
            return stream.read()
    except UnicodeDecodeError as exc:
        raise CorruptedDataError(
            f"Не вдалося прочитати файл у кодуванні {_encoding_label(encoding)}"
        ) from exc
    except OSError as exc:
        raise DataConvertError(f"Не вдалося прочитати файл: {exc}") from exc


def _check_input_size(path: Path) -> None:
    try:
        size = Path(path).stat().st_size
    except OSError as exc:
        raise DataConvertError(f"Не вдалося прочитати файл: {exc}") from exc
    if size > MAX_INPUT_BYTES:
        raise DataTooLargeError(
            "Файл завеликий: "
            f"{size // (1024 * 1024)} МБ, максимум {MAX_INPUT_BYTES // (1024 * 1024)} МБ"
        )


def _check_cancel(should_cancel: CancelCallback | None) -> None:
    if should_cancel is not None and should_cancel():
        raise ConversionCancelled("Скасовано")


def _safe_size(path: Path) -> int:
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0


def _path_key(path: Path) -> str:
    """Ключ для порівняння шляхів без урахування регістру (Windows)."""
    return os.path.normcase(os.path.abspath(str(path)))


def _output_delimiter(options: DataOptions) -> str:
    """Роздільник результату: для TXT без налаштування — табуляція."""
    if options.output_delimiter is not None:
        return options.output_delimiter
    if options.target is OutputFormat.TXT:
        return DEFAULT_TXT_DELIMITER
    return DEFAULT_CSV_DELIMITER


def _write_lines(
    handle,
    lines: Iterable[str],
    options: DataOptions,
    should_cancel: CancelCallback | None,
) -> None:
    for index, line in enumerate(lines, start=1):
        if index % CANCEL_CHECK_ROWS == 0:
            _check_cancel(should_cancel)
        handle.write(line)
        handle.write(options.newline)


def _check_free_space(directory: Path, source_size: int) -> None:
    needed = int(source_size * SPACE_FACTOR) + SPACE_RESERVE_BYTES
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


def _atomic_write(
    destination: Path,
    options: DataOptions,
    write_fn: Callable[[object], None],
) -> None:
    """Пише в тимчасовий файл і підміняє його лише після успіху."""
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DestinationBusyError("Папка призначення недоступна") from exc

    temp_path: Path | None = None
    try:
        handle, temp_name = tempfile.mkstemp(
            prefix=".file-toolkit-", suffix=".tmp", dir=destination.parent
        )
        os.close(handle)
        temp_path = Path(temp_name)
        with open(temp_path, "w", encoding=options.output_encoding, newline="") as stream:
            write_fn(stream)
        os.replace(temp_path, destination)
        temp_path = None
    except ConversionCancelled:
        raise
    except PermissionError as exc:
        raise DestinationBusyError("Файл відкритий в іншій програмі") from exc
    except UnicodeEncodeError as exc:
        raise DataConvertError(
            "Не всі символи подаються в кодуванні "
            f"{_encoding_label(options.output_encoding)}"
        ) from exc
    except OSError as exc:
        if getattr(exc, "winerror", None) == 112 or exc.errno == 28:
            raise NoSpaceError("Недостатньо місця на диску") from exc
        raise DataConvertError(f"Не вдалося записати файл: {exc}") from exc
    finally:
        if temp_path is not None and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
