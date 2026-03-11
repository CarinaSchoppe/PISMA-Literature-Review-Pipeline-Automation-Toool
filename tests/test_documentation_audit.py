"""Documentation-focused tests that do not depend on Tk availability."""

from __future__ import annotations

from pathlib import Path
import unittest


class DocumentationAuditTests(unittest.TestCase):
    """Verify user-facing files stay English-only across environments."""

    def test_core_user_facing_files_are_english_only(self) -> None:
        paths = (
            Path("README.md"),
            Path("HANDBOOK.md"),
            Path("config.py"),
            Path("main.py"),
            Path("ui/desktop_app.py"),
            Path("ui/view_model.py"),
        )
        forbidden_terms = (" beispiel", " erklaer", " erklär", " deutsch", " englisch", " ja ", " nein ")
        for path in paths:
            text = path.read_text(encoding="utf-8-sig").lower()
            self.assertEqual([term for term in forbidden_terms if term in text], [], str(path))


if __name__ == "__main__":  # pragma: no cover - direct module execution helper
    unittest.main()
