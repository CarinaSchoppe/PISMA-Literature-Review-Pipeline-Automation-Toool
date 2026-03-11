"""Tests for SQLite persistence, caching, and small repository helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, text

from database import DatabaseManager
from models.paper import PaperMetadata, ScreeningResult


class DatabaseManagerTests(unittest.TestCase):
    """Exercise upserts, cache storage, and update helpers on a real temp database."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.database_path = Path(self.temp_dir.name) / "review.db"
        self.database = DatabaseManager(self.database_path)
        self.database.initialize()
        self.addCleanup(self.database.close)

    def test_upsert_update_cache_and_decision_helpers(self) -> None:
        paper = PaperMetadata(
            title="Paper A",
            authors=["Ada"],
            abstract="Abstract",
            year=2024,
            venue="Venue",
            doi="10.1000/a",
            source="fixture",
            references=["ref1"],
            citations=["cit1"],
        )
        stored = self.database.upsert_papers([paper], "query-1")
        updated = stored[0]

        self.database.update_pdf_info(updated.database_id or 0, pdf_link="https://example.org/a.pdf", pdf_path="papers/a.pdf", open_access=True)
        self.database.update_citations(updated.database_id or 0, ["ref1", "ref2"], ["cit1", "cit2"])
        result = ScreeningResult(
            stage_one_decision="include",
            relevance_score=88,
            explanation="Strong fit",
            extracted_passage="Key sentence",
            methodology_category="survey",
            domain_category="ai",
            decision="include",
            screening_context_key="ctx",
        )
        details = {"final_result": result.model_dump(mode="json"), "passes": {"fast": {"decision": "include"}}}
        self.database.update_screening_result(updated.database_id or 0, result, screening_details=details)
        self.database.cache_screening_result(
            paper=updated,
            paper_cache_key="paper-key",
            screening_context_key="ctx",
            result=result,
            screening_details=details,
        )

        cached_result, cached_payload = self.database.get_cached_screening_entry("paper-key", "ctx") or (None, None)
        analysis_candidates = self.database.get_papers_for_analysis("query-1", limit=10, resume_mode=True, screening_context_key="different")
        stored_papers = self.database.get_papers_for_query("query-1")

        self.assertIsNotNone(cached_result)
        self.assertEqual(cached_result.relevance_score, 88)
        self.assertIn("passes", cached_payload)
        self.assertEqual(len(analysis_candidates), 1)
        self.assertEqual(stored_papers[0].pdf_path, "papers/a.pdf")
        self.assertEqual(self.database.count_papers("query-1"), 1)
        self.assertEqual(self.database.get_decision_counts("query-1")["include"], 1)

    def test_get_cached_screening_result_and_missing_updates_are_safe(self) -> None:
        self.assertIsNone(self.database.get_cached_screening_result("missing", "ctx"))
        self.database.update_pdf_info(999, pdf_link=None, pdf_path=None, open_access=False)
        self.database.update_citations(999, [], [])
        self.database.update_screening_result(999, ScreeningResult(decision="exclude"), screening_details={})

    def test_delete_papers_and_clear_screening_cache_support_targeted_resets(self) -> None:
        stored = self.database.upsert_papers(
            [
                PaperMetadata(title="Paper A", doi="10.1000/a", source="fixture"),
                PaperMetadata(title="Paper B", doi="10.1000/b", source="fixture"),
            ],
            "query-2",
        )
        result = ScreeningResult(stage_one_decision="include", relevance_score=88, decision="include")
        self.database.cache_screening_result(
            paper=stored[0],
            paper_cache_key="cache-a",
            screening_context_key="ctx-a",
            result=result,
            screening_details={"final_result": result.model_dump(mode="json")},
        )
        self.database.cache_screening_result(
            paper=stored[1],
            paper_cache_key="cache-b",
            screening_context_key="ctx-b",
            result=result,
            screening_details={"final_result": result.model_dump(mode="json")},
        )

        self.assertEqual(self.database.clear_screening_cache("ctx-a"), 1)
        self.assertEqual(self.database.clear_screening_cache(), 1)
        self.assertEqual(self.database.delete_papers_for_query("query-2"), 2)
        self.assertEqual(self.database.count_papers("query-2"), 0)

    def test_initialize_can_add_missing_schema_columns_to_existing_tables(self) -> None:
        legacy_path = Path(self.temp_dir.name) / "legacy_review.db"
        engine = create_engine(f"sqlite:///{legacy_path}")
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE papers (
                        database_id INTEGER PRIMARY KEY,
                        query_key TEXT,
                        title TEXT
                    )
                    """
                )
            )
        engine.dispose()

        upgraded = DatabaseManager(legacy_path)
        upgraded.initialize()
        self.addCleanup(upgraded.close)

        with upgraded.engine.connect() as connection:
            columns = {
                row[1]
                for row in connection.execute(text("PRAGMA table_info(papers)")).fetchall()
            }

        self.assertIn("screening_details_json", columns)


if __name__ == "__main__":  # pragma: no cover - direct module execution helper
    unittest.main()
