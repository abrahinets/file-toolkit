"""Точка входу File Toolkit."""

from __future__ import annotations

import customtkinter as ctk

from app.ui import App


def main() -> None:
    """Налаштовує тему та запускає головне вікно."""
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    App().mainloop()


if __name__ == "__main__":
    main()
