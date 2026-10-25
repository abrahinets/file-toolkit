"""Генерує тестові файли даних у папці test_data/.

Скрипт потрібен лише для ручних перевірок вкладки «Дані»: він створює
CSV у Windows-1251 та UTF-8 з BOM, JSON з пропущеними полями й вкладеним
об'єктом, звичайний текст і таблицю з табуляцією. У репозиторій
результат не потрапляє — папка test_data/ є в .gitignore.

Запуск:  python tools/make_test_data.py
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "test_data"

HEADER = ["Ім'я", "Місто", "Вік", "Телефон", "Код"]

# Телефони й коди навмисно з провідними нулями: конвертер має лишати
# їх текстом, якщо визначення типів увімкнене.
PEOPLE = [
    ["Олена Коваль", "Київ", "34", "+380501234567", "007"],
    ["Тарас Шевченко", "Черкаси", "45", "+380671112233", "007"],
    # Кома всередині клітинки: у CSV з комою поле буде взято в лапки.
    ["Ірина Бондаренко", "Львів, Центр", "28", "+380631234567", "007"],
    ["Андрій Мельник", "Одеса", "39", "+380931112244", "007"],
    ["Марія Гриценко", "Харків", "52", "+380991234567", "007"],
    ["Богдан Олійник", "Дніпро", "23", "+380681112255", "007"],
    ["Софія Лисенко", "Вінниця", "31", "+380661234567", "007"],
    ["Максим Ткаченко", "Полтава", "27", "+380951112266", "007"],
    ["Анна Савченко", "Івано-Франківськ", "41", "+380971234567", "007"],
    ["Дмитро Руденко", "Запоріжжя", "36", "+380731112277", "007"],
    ["Катерина Мороз", "Житомир", "29", "+380501234568", "007"],
    ["Олексій Кравчук", "Тернопіль", "48", "+380671112288", "007"],
    ["Наталія Шевчук", "Рівне", "33", "+380631234568", "007"],
    ["Василь Поліщук", "Ужгород", "55", "+380931112299", "007"],
    ["Юлія Бойко", "Чернівці", "26", "+380991234568", "007"],
    ["Ігор Гончаренко", "Кропивницький", "38", "+380681112200", "007"],
    ["Леся Марченко", "Суми", "44", "+380661234568", "007"],
    ["Павло Довженко", "Хмельницький", "30", "+380951112211", "007"],
    ["Оксана Захарченко", "Луцьк", "37", "+380971234568", "007"],
    ["Роман Пономаренко", "Миколаїв", "42", "+380731112222", "007"],
]

# Поля, яких не буде в окремих об'єктах JSON (індекс у PEOPLE -> поле).
JSON_MISSING_FIELDS = {
    3: "Місто",
    7: "Телефон",
    11: "Вік",
    15: "Код",
}
JSON_NESTED_INDEX = 2

NOTES_LINES = [
    "Файл для перевірки конвертації TXT.",
    "Це кілька рядків звичайного тексту українською мовою.",
    "У ньому є коми, крапки та інші розділові знаки.",
    "Окремий рядок можна перетворити на елемент JSON-масиву.",
    "Останній рядок без табуляції та інших роздільників.",
]


def write_people_excel() -> Path:
    """CSV для Excel: Windows-1251, роздільник «;», 20 рядків даних."""
    path = OUTPUT_DIR / "people_excel.csv"
    with path.open("w", encoding="cp1251", newline="") as stream:
        writer = csv.writer(stream, delimiter=";", lineterminator="\r\n")
        writer.writerow(HEADER)
        writer.writerows(PEOPLE)
    return path


def write_people_utf8() -> Path:
    """Ті самі дані в UTF-8 з BOM і роздільником «,»."""
    path = OUTPUT_DIR / "people_utf8.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream, delimiter=",", lineterminator="\r\n")
        writer.writerow(HEADER)
        writer.writerows(PEOPLE)
    return path


def build_people_json() -> list[dict[str, object]]:
    """Масив об'єктів: частина без окремих полів, один із вкладеним об'єктом."""
    people: list[dict[str, object]] = []
    for index, row in enumerate(PEOPLE):
        person: dict[str, object] = dict(zip(HEADER, row))
        missing = JSON_MISSING_FIELDS.get(index)
        if missing is not None:
            person.pop(missing, None)
        if index == JSON_NESTED_INDEX:
            person["Адреса"] = {
                "вулиця": "Площа Ринок",
                "будинок": "7",
                "примітка": "вхід з дворика",
            }
        people.append(person)
    return people


def write_people_json() -> Path:
    """JSON-масив із кирилицею, пропущеними полями й вкладеним об'єктом."""
    path = OUTPUT_DIR / "people.json"
    text = json.dumps(build_people_json(), ensure_ascii=False, indent=2)
    path.write_text(text + "\n", encoding="utf-8", newline="\n")
    return path


def write_notes() -> Path:
    """Звичайний текст українською — для перевірки TXT→JSON і TXT→TXT."""
    path = OUTPUT_DIR / "notes.txt"
    path.write_text("\n".join(NOTES_LINES) + "\n", encoding="utf-8", newline="\n")
    return path


def write_table() -> Path:
    """Таблиця з колонками через табуляцію — для TXT→CSV/JSON."""
    path = OUTPUT_DIR / "table.txt"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(HEADER)
        writer.writerows(PEOPLE[:6])
    return path


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    saved = [
        (write_people_excel(), "Windows-1251, роздільник «;», 20 рядків"),
        (write_people_utf8(), "UTF-8 з BOM, роздільник «,», 20 рядків"),
        (write_people_json(), "JSON-масив, 20 об'єктів, є вкладений об'єкт"),
        (write_notes(), "звичайний текст, 5 рядків"),
        (write_table(), "таблиця з табуляцією, 6 рядків даних"),
    ]

    print(f"Готово: {OUTPUT_DIR}")
    for path, description in saved:
        print(f"  {path.name:<20} {path.stat().st_size:6} Б  {description}")


if __name__ == "__main__":
    main()
