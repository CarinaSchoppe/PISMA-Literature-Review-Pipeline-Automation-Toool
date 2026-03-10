"""Tests for guided desktop UI helpers such as hover help and field explanations."""

from __future__ import annotations

import tkinter as tk
import unittest
from types import SimpleNamespace

from ui.desktop_app import DesktopWorkbench


class DesktopWorkbenchTests(unittest.TestCase):
    """Verify the guided desktop UI exposes contextual help for key settings."""

    def setUp(self) -> None:
        try:
            self.workbench = DesktopWorkbench(SimpleNamespace(config_file=None))
        except tk.TclError as exc:  # pragma: no cover - depends on local Tk availability
            self.skipTest(f"Tkinter is unavailable in this environment: {exc}")
        self.workbench.root.withdraw()

    def tearDown(self) -> None:
        if hasattr(self, "workbench"):
            try:
                self.workbench._on_close()
            except tk.TclError:
                pass

    def test_hover_help_is_enabled_by_default(self) -> None:
        self.assertTrue(self.workbench.hover_help_enabled.get())

    def test_source_fields_have_descriptive_help_text(self) -> None:
        self.assertIn("OpenAlex", self.workbench._help_text_for_field("openalex_enabled"))
        self.assertIn("Crossref", self.workbench._help_text_for_field("crossref_enabled"))
        self.assertIn("Springer", self.workbench._help_text_for_field("springer_enabled"))
        self.assertIn("Semantic Scholar", self.workbench._help_text_for_field("semantic_scholar_enabled"))

    def test_hover_help_updates_and_restores_status_bar(self) -> None:
        original_status = self.workbench.status_var.get()

        self.workbench._show_hover_help("Explain this option.")
        self.assertEqual(self.workbench.status_var.get(), "Explain this option.")

        self.workbench._clear_hover_help()
        self.assertEqual(self.workbench.status_var.get(), original_status)

    def test_disabling_hover_help_prevents_status_override(self) -> None:
        self.workbench.hover_help_enabled.set(False)
        original_status = self.workbench.status_var.get()

        self.workbench._show_hover_help("This should not appear.")

        self.assertEqual(self.workbench.status_var.get(), original_status)


if __name__ == "__main__":
    unittest.main()
