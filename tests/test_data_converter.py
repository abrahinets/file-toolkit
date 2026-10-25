"""Тести логіки конвертації даних (без інтерфейсу)."""

from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

from app import data_converter
from app.data_converter import (
    CorruptedDataError,
    DataConvertError,
    DataOptions,
    DataTooLargeError,
    DestinationBusyError,
    NoSpaceError,
    OutputFormat,
    SourceMissingError,
    TxtLayout,
    UnsupportedDataFormatError,
    build_destination,
    convert_data,
    convert_data_batch,
    detect_encoding,
    is_supported_data,
    read_source,
)


class DataConverterTestCase(unittest.TestCase):
    """Спільна тимчасова папка для кожного тесту."""

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, name: str, text: str) -> Path:
        path = self.tmp / name
        path.write_text(text, encoding="utf-8", newline="")
        return path

    def write_bytes(self, name: str, payload: bytes) -> Path:
        path = self.tmp / name
        path.write_bytes(payload)
        return path

    def convert(
        self,
        source: Path,
        target: OutputFormat,
        *,
        name: str | None = None,
        **kwargs,
    ) -> tuple[Path, data_converter.DataConversionResult]:
        options = DataOptions(target=target, **kwargs)
        suffix = data_converter.OUTPUT_SUFFIXES[target]
        destination = self.tmp / (name or f"{source.stem}-out{suffix}")
        result = convert_data(source, destination, options)
        self.assertTrue(result.ok)
        return destination, result

    def read_json(self, path: Path) -> object:
        return json.loads(path.read_text(encoding="utf-8"))

    def read_rows(self, path: Path) -> list[list[str]]:
        with path.open(encoding="utf-8", newline="") as stream:
            return list(csv.reader(stream))

    def table(self, source: Path, target=OutputFormat.JSON) -> data_converter.Table:
        document = read_source(source, DataOptions(target=target))
        self.assertIsInstance(document, data_converter.Table)
        return document

    # --- JSON -> CSV/TXT ----------------------------------------------------

    def test_json_objects_to_csv(self) -> None:
        source = self.write(
            "people.json",
            json.dumps(
                [
                    {"name": "Олена", "age": 30},
                    {"name": "Іван", "city": "Львів"},
                ],
                ensure_ascii=False,
            ),
        )
        destination, _ = self.convert(source, OutputFormat.CSV)
        self.assertEqual(
            self.read_rows(destination),
            [
                ["name", "age", "city"],
                ["Олена", "30", ""],
                ["Іван", "", "Львів"],
            ],
        )

    def test_json_quotes_and_unicode_to_csv(self) -> None:
        values = ["a,b", 'say "hi"', "line1\nline2", "🙂", "крапка;з комою"]
        source = self.write(
            "cells.json",
            json.dumps([{"cell": value} for value in values], ensure_ascii=False),
        )
        destination, _ = self.convert(source, OutputFormat.CSV)
        rows = self.read_rows(destination)
        self.assertEqual(rows[0], ["cell"])
        self.assertEqual([row[0] for row in rows[1:]], values)

    def test_json_list_of_lists_to_csv(self) -> None:
        source = self.write("matrix.json", '[["a", "b"], ["c", "d"]]')
        destination, _ = self.convert(source, OutputFormat.CSV)
        self.assertEqual(self.read_rows(destination), [["a", "b"], ["c", "d"]])

    def test_json_object_to_csv(self) -> None:
        source = self.write("one.json", '{"name": "x", "age": 1}')
        destination, _ = self.convert(source, OutputFormat.CSV)
        self.assertEqual(
            self.read_rows(destination), [["name", "age"], ["x", "1"]]
        )

    def test_json_nested_values_to_csv(self) -> None:
        source = self.write(
            "nested.json", '{"meta": {"b": 1}, "tags": [1, 2], "flag": true}'
        )
        destination, _ = self.convert(source, OutputFormat.CSV)
        self.assertEqual(
            self.read_rows(destination),
            [["meta", "tags", "flag"], ['{"b":1}', "[1,2]", "true"]],
        )

    def test_json_empty_array_warns(self) -> None:
        source = self.write("empty.json", "[]")
        destination, result = self.convert(source, OutputFormat.CSV)
        self.assertEqual(destination.read_text(encoding="utf-8"), "")
        self.assertIn("порожній масив", result.message)

    def test_broken_json_reports_position(self) -> None:
        source = self.write("broken.json", '{"a": }')
        with self.assertRaises(CorruptedDataError) as caught:
            self.convert(source, OutputFormat.CSV)
        self.assertIn("рядок 1", str(caught.exception))

    def test_json_mixed_types_rejected(self) -> None:
        source = self.write("mixed.json", '[{"a": 1}, 2]')
        with self.assertRaises(UnsupportedDataFormatError):
            self.convert(source, OutputFormat.CSV)

    def test_json_object_to_txt(self) -> None:
        source = self.write(
            "config.json",
            json.dumps(
                {"name": "Олена", "tags": ["a", "b"], "meta": {}},
                ensure_ascii=False,
            ),
        )
        destination, _ = self.convert(source, OutputFormat.TXT)
        self.assertEqual(
            destination.read_text(encoding="utf-8").splitlines(),
            ["name: Олена", "tags:", "  - a", "  - b", "meta: {}"],
        )

    # --- CSV -----------------------------------------------------------------

    def test_csv_semicolon_autodetect(self) -> None:
        source = self.write("semi.csv", "ім'я;вік\nОлена;30\n")
        destination, _ = self.convert(source, OutputFormat.JSON)
        self.assertEqual(
            self.read_json(destination), [{"ім'я": "Олена", "вік": "30"}]
        )

    def test_csv_quoted_multiline_cell(self) -> None:
        source = self.write(
            "quoted.csv", 'text,note\n"a,b","line1\nline2"\n'
        )
        destination, _ = self.convert(source, OutputFormat.JSON)
        self.assertEqual(
            self.read_json(destination), [{"text": "a,b", "note": "line1\nline2"}]
        )

    def test_csv_without_header(self) -> None:
        source = self.write("noheader.csv", "1,2\n3,4\n")
        destination, _ = self.convert(
            source, OutputFormat.JSON, has_header=False
        )
        self.assertEqual(self.read_json(destination), [["1", "2"], ["3", "4"]])

    def test_csv_type_detection(self) -> None:
        source = self.write(
            "types.csv",
            'name,num,flag,empty,zero,code\n'
            'x,42,true,,007,"+380"\n'
            'y,3.5,false,,null,"1,5"\n',
        )
        destination, _ = self.convert(
            source, OutputFormat.JSON, detect_types=True
        )
        self.assertEqual(
            self.read_json(destination),
            [
                {
                    "name": "x",
                    "num": 42,
                    "flag": True,
                    "empty": None,
                    "zero": "007",
                    "code": "+380",
                },
                {
                    "name": "y",
                    "num": 3.5,
                    "flag": False,
                    "empty": None,
                    "zero": None,
                    "code": "1,5",
                },
            ],
        )

        plain, _ = self.convert(
            source,
            OutputFormat.JSON,
            name="types-plain.json",
            detect_types=False,
        )
        self.assertEqual(self.read_json(plain)[0]["num"], "42")
        self.assertEqual(self.read_json(plain)[1]["zero"], "null")

    def test_csv_header_normalisation(self) -> None:
        source = self.write("headers.csv", ",b,b\n1,2,3\n")
        destination, _ = self.convert(source, OutputFormat.JSON)
        self.assertEqual(
            self.read_json(destination),
            [{"column_1": "1", "b": "2", "b_2": "3"}],
        )

    def test_csv_ragged_rows(self) -> None:
        source = self.write("ragged.csv", "a,b\n1\n2,3,4\n")
        destination, result = self.convert(source, OutputFormat.JSON)
        self.assertEqual(
            self.read_json(destination),
            [{"a": "1", "b": "", "column_3": ""},
             {"a": "2", "b": "3", "column_3": "4"}],
        )
        self.assertIn("2", result.message)

    def test_csv_encoding_autodetect(self) -> None:
        payload = "ім'я;вік\nОлена;30\n".encode("cp1251")
        source = self.write_bytes("cp1251.csv", payload)
        destination, result = self.convert(source, OutputFormat.JSON)
        self.assertIn("Windows-1251", result.message)
        self.assertEqual(
            self.read_json(destination), [{"ім'я": "Олена", "вік": "30"}]
        )

        bom = self.write_bytes(
            "bom.csv", b"\xef\xbb\xbf" + "a,b\n1,2\n".encode("utf-8")
        )
        bom_destination, _ = self.convert(
            bom, OutputFormat.JSON, name="bom-out.json"
        )
        self.assertEqual(self.read_json(bom_destination), [{"a": "1", "b": "2"}])

    def test_csv_broken_structure(self) -> None:
        source = self.write("broken.csv", 'a,b\n"unclosed,1\n')
        with self.assertRaises(CorruptedDataError):
            self.convert(source, OutputFormat.JSON)

    def test_empty_sources_warn(self) -> None:
        for name, suffix in (("empty.csv", ".csv"), ("empty.txt", ".txt")):
            with self.subTest(name=name):
                source = self.write(name, "")
                document = read_source(
                    source, DataOptions(target=OutputFormat.JSON)
                )
                self.assertEqual(document.rows, [])
                self.assertIn("порожній", document.warnings[0].lower())

    def test_csv_to_txt_aligned(self) -> None:
        source = self.write("aligned.csv", "a,b\n1,22\n")
        destination, _ = self.convert(source, OutputFormat.TXT)
        self.assertEqual(
            destination.read_text(encoding="utf-8").splitlines(),
            ["a  b", "1  22"],
        )

    def test_csv_to_txt_keeps_newline_marker(self) -> None:
        source = self.write("multiline.csv", 'text\n"line1\nline2"\n')
        destination, _ = self.convert(source, OutputFormat.TXT)
        self.assertEqual(
            destination.read_text(encoding="utf-8").splitlines(),
            ["text", "line1\\nline2"],
        )

    def test_csv_to_txt_delimited(self) -> None:
        source = self.write("delimited.csv", "a,b\n1,2\n")
        destination, _ = self.convert(
            source,
            OutputFormat.TXT,
            name="delimited-out.txt",
            txt_layout=TxtLayout.DELIMITED,
            output_delimiter="|",
        )
        self.assertEqual(
            destination.read_text(encoding="utf-8").splitlines(),
            ["a|b", "1|2"],
        )

    # --- TXT -----------------------------------------------------------------

    def test_txt_lines_to_json(self) -> None:
        source = self.write("lines.txt", "перший\nдругий\n")
        destination, _ = self.convert(source, OutputFormat.JSON)
        self.assertEqual(self.read_json(destination), ["перший", "другий"])

    def test_txt_delimited_to_csv(self) -> None:
        source = self.write("table.txt", "a\tb\n1\t2\n")
        destination, _ = self.convert(source, OutputFormat.CSV)
        self.assertEqual(self.read_rows(destination), [["a", "b"], ["1", "2"]])

    def test_txt_crlf_lines(self) -> None:
        source = self.write_bytes("crlf.txt", b"a\tb\r\n1\t2\r\n")
        document = self.table(source)
        self.assertEqual(document.header, ["a", "b"])
        self.assertEqual(document.rows, [["1", "2"]])

    # --- JSON як вихід -------------------------------------------------------

    def test_json_minify_and_sort_keys(self) -> None:
        source = self.write("pretty.json", '{"b": 1, "a": [2, 3]}')
        destination, _ = self.convert(
            source, OutputFormat.JSON, json_indent=0, sort_keys=True
        )
        self.assertEqual(
            destination.read_text(encoding="utf-8"),
            '{"a": [2, 3], "b": 1}\n',
        )

    def test_json_to_json_roundtrip(self) -> None:
        payload = [{"a": [1, {"b": None}], "c": "кирилиця"}]
        source = self.write(
            "roundtrip.json", json.dumps(payload, ensure_ascii=False)
        )
        destination, _ = self.convert(source, OutputFormat.JSON)
        self.assertEqual(self.read_json(destination), payload)

    # --- файли ---------------------------------------------------------------

    def test_build_destination_collisions(self) -> None:
        source = self.write("data.csv", "a\n1\n")
        options = DataOptions(target=OutputFormat.JSON)
        first = build_destination(source, None, options)
        self.assertEqual(first, self.tmp / "data.json")

        first.write_text("{}", encoding="utf-8")
        second = build_destination(source, None, options, taken=[first])
        self.assertEqual(second, self.tmp / "data_1.json")

        overwrite = build_destination(
            source, None, DataOptions(target=OutputFormat.JSON, overwrite=True)
        )
        self.assertEqual(overwrite, self.tmp / "data.json")

        json_source = self.write("data.json", "{}")
        guarded = build_destination(
            json_source,
            None,
            DataOptions(target=OutputFormat.JSON, overwrite=True),
        )
        self.assertNotEqual(guarded, json_source)

    def test_single_column_roundtrip(self) -> None:
        source = self.write("single.json", '["a", "b"]')
        csv_path, _ = self.convert(source, OutputFormat.CSV)
        self.assertEqual(self.read_rows(csv_path), [["a"], ["b"]])

        back, _ = self.convert(
            csv_path, OutputFormat.JSON, name="single-back.json", has_header=False
        )
        self.assertEqual(self.read_json(back), ["a", "b"])

    def test_batch_progress_and_failure(self) -> None:
        good_one = self.write("one.json", '[{"a": 1}]')
        broken = self.write("bad.json", "{oops")
        good_two = self.write("two.csv", "a\n2\n")
        events: list[tuple[int, int, Path | None]] = []

        results = convert_data_batch(
            [good_one, broken, good_two],
            DataOptions(target=OutputFormat.JSON),
            on_progress=lambda done, total, path: events.append((done, total, path)),
        )

        self.assertEqual(len(results), 3)
        self.assertEqual([result.ok for result in results], [True, False, True])
        self.assertTrue(results[1].message)
        self.assertEqual(len({result.destination for result in results if result.ok}), 2)
        self.assertEqual(events[0], (0, 3, good_one))
        self.assertEqual(events[-1], (3, 3, None))

    def test_batch_cancel_stops(self) -> None:
        source = self.write("cancel.json", "[]")
        results = convert_data_batch(
            [source, source],
            DataOptions(target=OutputFormat.JSON),
            should_cancel=lambda: True,
        )
        self.assertEqual(results, [])

    def test_cancel_inside_file_cleans_temp(self) -> None:
        source = self.write(
            "big.csv", "a,b\n" + "".join(f"{index},{index}\n" for index in range(3000))
        )
        destination = self.tmp / "big-out.json"
        calls = {"count": 0}

        def should_cancel() -> bool:
            calls["count"] += 1
            return calls["count"] >= 3

        with self.assertRaises(data_converter.ConversionCancelled):
            convert_data(
                source,
                destination,
                DataOptions(target=OutputFormat.JSON),
                should_cancel=should_cancel,
            )

        self.assertFalse(destination.exists())
        leftovers = [
            path for path in self.tmp.iterdir() if path.name.startswith(".file-toolkit-")
        ]
        self.assertEqual(leftovers, [])

    def test_permission_error_is_busy(self) -> None:
        source = self.write("busy.csv", "a\n1\n")
        with mock.patch(
            "app.data_converter.os.replace", side_effect=PermissionError
        ):
            with self.assertRaises(DestinationBusyError):
                convert_data(
                    source,
                    self.tmp / "busy-out.json",
                    DataOptions(target=OutputFormat.JSON),
                )
        leftovers = [
            path for path in self.tmp.iterdir() if path.name.startswith(".file-toolkit-")
        ]
        self.assertEqual(leftovers, [])

    def test_no_space_error(self) -> None:
        source = self.write("space.csv", "a\n1\n")
        with mock.patch(
            "app.data_converter.shutil.disk_usage",
            return_value=SimpleNamespace(free=0),
        ):
            with self.assertRaises(NoSpaceError):
                convert_data(
                    source,
                    self.tmp / "space-out.json",
                    DataOptions(target=OutputFormat.JSON),
                )

    def test_limits(self) -> None:
        source = self.write("limit.csv", "a,b\n1,2\n3,4\n")
        with mock.patch.object(data_converter, "MAX_INPUT_BYTES", 4):
            with self.assertRaises(DataTooLargeError):
                convert_data(
                    source,
                    self.tmp / "limit-out.json",
                    DataOptions(target=OutputFormat.JSON),
                )

        with mock.patch.object(data_converter, "MAX_ROWS", 2):
            with self.assertRaises(DataTooLargeError):
                convert_data(
                    source,
                    self.tmp / "rows-out.json",
                    DataOptions(target=OutputFormat.JSON),
                )

    def test_options_validation(self) -> None:
        bad_options = [
            {"delimiter": "||"},
            {"delimiter": '"'},
            {"output_delimiter": "||"},
            {"json_indent": 9},
            {"input_encoding": "koi8-r"},
            {"output_encoding": "latin-1"},
            {"newline": "\r"},
        ]
        for kwargs in bad_options:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    DataOptions(target=OutputFormat.JSON, **kwargs)

    def test_unsupported_and_same_path(self) -> None:
        source = self.write("data.xml", "<a/>")
        with self.assertRaises(UnsupportedDataFormatError):
            read_source(source, DataOptions(target=OutputFormat.JSON))

        json_source = self.write("same.json", "{}")
        with self.assertRaises(DataConvertError):
            convert_data(
                json_source,
                json_source,
                DataOptions(target=OutputFormat.JSON),
            )

        with self.assertRaises(SourceMissingError):
            read_source(
                self.tmp / "missing.json", DataOptions(target=OutputFormat.JSON)
            )

    def test_output_encodings(self) -> None:
        source = self.write("cyr.csv", "ім'я\nОлена\n")

        bom, _ = self.convert(
            source,
            OutputFormat.CSV,
            name="bom-out.csv",
            output_encoding="utf-8-sig",
        )
        self.assertTrue(bom.read_bytes().startswith(b"\xef\xbb\xbf"))

        cp, _ = self.convert(
            source,
            OutputFormat.CSV,
            name="cp-out.csv",
            output_encoding="cp1251",
        )
        self.assertIn("Олена", cp.read_bytes().decode("cp1251"))

    def test_wrong_encoding_reported(self) -> None:
        source = self.write_bytes(
            "wrong.csv", "ім'я\nОлена\n".encode("cp1251")
        )
        with self.assertRaises(CorruptedDataError):
            self.convert(source, OutputFormat.JSON, input_encoding="utf-8")

    def test_supported_suffixes_and_encoding_detection(self) -> None:
        self.assertTrue(is_supported_data(Path("a.JSON")))
        self.assertTrue(is_supported_data(Path("a.csv")))
        self.assertTrue(is_supported_data(Path("a.txt")))
        self.assertFalse(is_supported_data(Path("a.xml")))

        plain = self.write("plain.txt", "текст")
        self.assertEqual(detect_encoding(plain), "utf-8")

        bom = self.write_bytes("with-bom.txt", b"\xef\xbb\xbf" + "текст".encode())
        self.assertEqual(detect_encoding(bom), "utf-8-sig")

        cp = self.write_bytes("cp.txt", "текст".encode("cp1251"))
        self.assertEqual(detect_encoding(cp), "cp1251")


if __name__ == "__main__":
    unittest.main()
