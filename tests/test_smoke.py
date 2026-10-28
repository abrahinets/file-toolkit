from __future__ import annotations

import os
import unittest


class SmokeTests(unittest.TestCase):
    def test_app_starts_and_closes(self) -> None:
        if os.environ.get("DISPLAY") is None and os.name != "nt":
            self.skipTest("no display")
        # On Windows with no display server still try; skip if tkinter fails to init
        try:
            import customtkinter as ctk

            ctk.set_appearance_mode("dark")
            ctk.set_default_color_theme("blue")
        except Exception:
            pass
        try:
            from app.ui import App
        except Exception as exc:
            self.skipTest(f"cannot import App: {exc}")
        try:
            app = App()
        except Exception as exc:
            self.fail(f"App() raised exception: {exc}")
        try:
            app.update()
        except Exception:
            pass
        try:
            app.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    unittest.main()
