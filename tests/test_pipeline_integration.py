"""Integration tests that exercise the pipeline end to end on offline fixtures."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from acquisition.pdf_fetcher import PDFFetcher
from config import ResearchConfig
from models.paper import PaperMetadata, ScreeningResult
from pipeline.pipeline_controller import PipelineController


class PipelineIntegrationTests(unittest.TestCase):
    """Verify output generation, collection mode, screening, and discovery limits."""

    def test_offline_fixture_pipeline_generates_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = ResearchConfig(
                research_topic="AI-assisted literature reviews",
                search_keywords=["large language models", "screening", "systematic review"],
                boolean_operators="AND",
                pages_to_retrieve=1,
                results_per_page=10,
                year_range_start=2020,
                year_range_end=2026,
                max_papers_to_analyze=4,
                citation_snowballing_enabled=True,
                relevance_threshold=55,
                download_pdfs=False,
                openalex_enabled=False,
                semantic_scholar_enabled=False,
                crossref_enabled=False,
                include_pubmed=False,
                max_workers=2,
                request_timeout_seconds=10,
                resume_mode=True,
                disable_progress_bars=True,
                title_similarity_threshold=0.9,
                fixture_data_path=Path("tests/fixtures/offline_papers.json"),
                data_dir=root / "data",
                papers_dir=root / "papers",
                results_dir=root / "results",
                database_path=root / "data" / "literature_review.db",
            ).finalize()

            controller = PipelineController(config)
            first_run = controller.run()
            second_run = PipelineController(config).run()

            self.assertEqual(first_run["database_count"], second_run["database_count"])
            self.assertTrue((root / "results" / "papers.csv").exists())
            self.assertTrue((root / "results" / "included_papers.csv").exists())
            self.assertTrue((root / "results" / "excluded_papers.csv").exists())
            self.assertTrue((root / "results" / "top_papers.json").exists())
            self.assertTrue((root / "results" / "citation_graph.json").exists())
            self.assertTrue((root / "results" / "prisma_flow.json").exists())
            self.assertTrue((root / "results" / "included_papers.db").exists())
            self.assertTrue((root / "results" / "excluded_papers.db").exists())
            self.assertTrue((root / "results" / "review_summary.md").exists())

            papers = pd.read_csv(root / "results" / "papers.csv")
            included = pd.read_csv(root / "results" / "included_papers.csv")
            excluded = pd.read_csv(root / "results" / "excluded_papers.csv")
            top_papers = json.loads((root / "results" / "top_papers.json").read_text(encoding="utf-8"))
            prisma = json.loads((root / "results" / "prisma_flow.json").read_text(encoding="utf-8"))
            summary = (root / "results" / "review_summary.md").read_text(encoding="utf-8")

            self.assertGreaterEqual(len(papers), 4)
            self.assertGreaterEqual(len(top_papers), 1)
            self.assertGreaterEqual(len(included), 1)
            self.assertGreaterEqual(len(excluded), 1)
            self.assertEqual(prisma["included"]["studies_included"], len(included))
            self.assertIn("Literature Review Summary", summary)
            self.assertIn("retain_reason", included.columns)
            self.assertIn("exclusion_reason", excluded.columns)
            self.assertIn("matched_excluded_title_terms", papers.columns)

            connection = sqlite3.connect(root / "results" / "excluded_papers.db")
            try:
                rows = connection.execute("SELECT COUNT(*) FROM excluded_papers").fetchone()
                self.assertIsNotNone(rows)
                self.assertGreaterEqual(rows[0], 1)
            finally:
                connection.close()

    def test_collect_mode_can_export_metadata_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = ResearchConfig(
                research_topic="AI-assisted literature reviews",
                search_keywords=["large language models", "screening", "systematic review"],
                pages_to_retrieve=1,
                results_per_page=10,
                year_range_start=2020,
                year_range_end=2026,
                max_papers_to_analyze=5,
                citation_snowballing_enabled=True,
                download_pdfs=False,
                run_mode="collect",
                output_csv=True,
                output_json=False,
                output_markdown=False,
                output_sqlite_exports=False,
                openalex_enabled=False,
                semantic_scholar_enabled=False,
                crossref_enabled=False,
                include_pubmed=False,
                max_workers=2,
                request_timeout_seconds=10,
                resume_mode=True,
                disable_progress_bars=True,
                fixture_data_path=Path("tests/fixtures/offline_papers.json"),
                data_dir=root / "data",
                papers_dir=root / "papers",
                results_dir=root / "results",
                database_path=root / "data" / "literature_review.db",
            ).finalize()

            result = PipelineController(config).run()

            self.assertIn("papers_csv", result)
            self.assertNotIn("top_papers_json", result)
            self.assertNotIn("review_summary_md", result)
            self.assertTrue((root / "results" / "papers.csv").exists())
            self.assertTrue((root / "results" / "included_papers.csv").exists())
            self.assertTrue((root / "results" / "excluded_papers.csv").exists())
            self.assertFalse((root / "results" / "top_papers.json").exists())
            self.assertFalse((root / "results" / "review_summary.md").exists())
            self.assertFalse((root / "results" / "included_papers.db").exists())

            papers = pd.read_csv(root / "results" / "papers.csv")
            self.assertTrue(papers["relevance_score"].isna().all())
            self.assertTrue(papers["inclusion_decision"].isna().all())

    def test_multi_pass_analysis_exports_per_pass_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = ResearchConfig(
                research_topic="AI-assisted literature reviews",
                research_question="Can LLMs support literature discovery and screening?",
                review_objective="Find papers on AI-assisted screening for systematic reviews.",
                inclusion_criteria=["mentions systematic review screening", "focuses on AI or LLM assistance"],
                exclusion_criteria=["irrelevant domain-only paper"],
                banned_topics=["crop irrigation", "plant growth"],
                search_keywords=["large language models", "screening", "systematic review"],
                pages_to_retrieve=1,
                results_per_page=10,
                year_range_start=2020,
                year_range_end=2026,
                max_papers_to_analyze=5,
                citation_snowballing_enabled=True,
                relevance_threshold=55,
                llm_provider="heuristic",
                analysis_passes=[
                    {
                        "name": "fast",
                        "llm_provider": "heuristic",
                        "threshold": 65,
                        "decision_mode": "strict",
                    },
                    {
                        "name": "deep",
                        "llm_provider": "heuristic",
                        "threshold": 50,
                        "decision_mode": "triage",
                        "maybe_threshold_margin": 10,
                    },
                ],
                download_pdfs=False,
                openalex_enabled=False,
                semantic_scholar_enabled=False,
                crossref_enabled=False,
                include_pubmed=False,
                max_workers=2,
                request_timeout_seconds=10,
                resume_mode=True,
                disable_progress_bars=True,
                fixture_data_path=Path("tests/fixtures/offline_papers.json"),
                data_dir=root / "data",
                papers_dir=root / "papers",
                results_dir=root / "results",
                database_path=root / "data" / "literature_review.db",
            ).finalize()

            PipelineController(config).run()

            papers = pd.read_csv(root / "results" / "papers.csv")
            prisma = json.loads((root / "results" / "prisma_flow.json").read_text(encoding="utf-8"))
            top_papers = json.loads((root / "results" / "top_papers.json").read_text(encoding="utf-8"))

            self.assertIn("pass_fast_score", papers.columns)
            self.assertIn("pass_deep_score", papers.columns)
            self.assertIn("pass_fast_decision", papers.columns)
            self.assertIn("pass_deep_decision", papers.columns)
            self.assertTrue(papers["pass_fast_score"].notna().any())
            self.assertEqual(prisma["thresholds"]["relevance_threshold"], 50)
            self.assertTrue(any("pass_fast_score" in paper for paper in top_papers))

    def test_pipeline_accepts_google_scholar_and_researchgate_imports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = ResearchConfig(
                research_topic="Evidence discovery workflows",
                search_keywords=["llm", "systematic review"],
                pages_to_retrieve=1,
                results_per_page=10,
                year_range_start=2020,
                year_range_end=2026,
                max_papers_to_analyze=5,
                citation_snowballing_enabled=True,
                run_mode="collect",
                openalex_enabled=False,
                semantic_scholar_enabled=False,
                crossref_enabled=False,
                springer_enabled=False,
                arxiv_enabled=False,
                include_pubmed=False,
                google_scholar_import_path=Path("tests/fixtures/google_scholar_import.json"),
                researchgate_import_path=Path("tests/fixtures/researchgate_import.csv"),
                disable_progress_bars=True,
                data_dir=root / "data",
                papers_dir=root / "papers",
                results_dir=root / "results",
                database_path=root / "data" / "literature_review.db",
            ).finalize()

            result = PipelineController(config).run()

            self.assertEqual(result["database_count"], 2)
            papers = pd.read_csv(root / "results" / "papers.csv")
            self.assertIn("google_scholar_import", set(papers["source"]))
            self.assertIn("researchgate_import", set(papers["source"]))

    def test_google_scholar_live_results_are_deduplicated_after_multi_page_collection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = ResearchConfig(
                research_topic="AI governance",
                search_keywords=["llm", "policy"],
                pages_to_retrieve=1,
                results_per_page=1,
                discovery_strategy="precise",
                google_scholar_enabled=True,
                google_scholar_pages=2,
                google_scholar_results_per_page=1,
                run_mode="collect",
                openalex_enabled=False,
                semantic_scholar_enabled=False,
                crossref_enabled=False,
                springer_enabled=False,
                arxiv_enabled=False,
                include_pubmed=False,
                disable_progress_bars=True,
                data_dir=root / "data",
                papers_dir=root / "papers",
                results_dir=root / "results",
                database_path=root / "data" / "literature_review.db",
            ).finalize()

            duplicate_page = (
                '<div class="gs_r gs_or gs_scl">'
                '<h3 class="gs_rt"><a href="https://example.org/paper-a">AI Governance in Hospitals</a></h3>'
                '<div class="gs_a">Ada Lovelace - Journal of AI Policy - 2024</div>'
                '<div class="gs_rs">A study of AI governance. DOI 10.1000/xyz123</div>'
                "</div>"
            )

            with patch("discovery.google_scholar_client.request_text", side_effect=lambda *args, **kwargs: duplicate_page):
                result = PipelineController(config).run()

            self.assertEqual(result["discovered_count"], 2)
            self.assertEqual(result["deduplicated_count"], 1)
            self.assertEqual(result["database_count"], 1)
            papers = pd.read_csv(root / "results" / "papers.csv")
            self.assertEqual(len(papers), 1)
            self.assertEqual(papers.iloc[0]["doi"], "10.1000/xyz123")

    def test_relevant_pdf_downloads_can_be_routed_to_configured_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            relevant_dir = root / "relevant_keep"
            calls: list[tuple[str, bool | None, str]] = []

            def fake_fetch(
                    self: PDFFetcher,
                    paper,
                    *,
                    download: bool | None = None,
                    target_dir: Path | None = None,
            ):
                calls.append((paper.title, download, str(target_dir or "")))
                pdf_path = paper.pdf_path
                if download:
                    pdf_path = str((target_dir or root / "papers") / f"{paper.database_id or 0}.pdf")
                return paper.model_copy(
                    update={
                        "pdf_link": paper.pdf_link or "https://example.org/fake.pdf",
                        "pdf_path": pdf_path,
                        "open_access": True,
                    }
                )

            config = ResearchConfig(
                research_topic="AI-assisted literature reviews",
                search_keywords=["large language models", "screening", "systematic review"],
                pages_to_retrieve=1,
                results_per_page=10,
                year_range_start=2020,
                year_range_end=2026,
                max_papers_to_analyze=5,
                citation_snowballing_enabled=True,
                relevance_threshold=50,
                download_pdfs=True,
                pdf_download_mode="relevant_only",
                openalex_enabled=False,
                semantic_scholar_enabled=False,
                crossref_enabled=False,
                include_pubmed=False,
                max_workers=2,
                request_timeout_seconds=10,
                resume_mode=True,
                disable_progress_bars=True,
                fixture_data_path=Path("tests/fixtures/offline_papers.json"),
                data_dir=root / "data",
                papers_dir=root / "papers",
                relevant_pdfs_dir=relevant_dir,
                results_dir=root / "results",
                database_path=root / "data" / "literature_review.db",
            ).finalize()

            with patch.object(PDFFetcher, "fetch_for_paper", new=fake_fetch):
                PipelineController(config).run()

            included = pd.read_csv(root / "results" / "included_papers.csv")
            self.assertTrue(any(download is False for _, download, _ in calls))
            self.assertTrue(any(download is True and path == str(relevant_dir) for _, download, path in calls))
            self.assertFalse(included.empty)
            self.assertTrue(included["pdf_path"].dropna().str.contains("relevant_keep").all())

    def test_max_discovered_records_caps_stored_results(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = ResearchConfig(
                research_topic="AI-assisted literature reviews",
                search_keywords=["large language models", "screening", "systematic review"],
                pages_to_retrieve=1,
                results_per_page=10,
                max_discovered_records=2,
                run_mode="collect",
                openalex_enabled=False,
                semantic_scholar_enabled=False,
                crossref_enabled=False,
                include_pubmed=False,
                disable_progress_bars=True,
                fixture_data_path=Path("tests/fixtures/offline_papers.json"),
                data_dir=root / "data",
                papers_dir=root / "papers",
                results_dir=root / "results",
                database_path=root / "data" / "literature_review.db",
            ).finalize()

            result = PipelineController(config).run()

            self.assertEqual(result["database_count"], 2)
            papers = pd.read_csv(root / "results" / "papers.csv")
            self.assertEqual(len(papers), 2)

    def test_citation_expansion_respects_remaining_discovery_capacity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture_path = root / "seed.json"
            fixture_path.write_text(
                json.dumps(
                    [
                        {
                            "title": "Seed paper",
                            "authors": ["Ada Lovelace"],
                            "abstract": "Seed abstract",
                            "year": 2024,
                            "source": "fixture",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            config = ResearchConfig(
                research_topic="AI-assisted literature reviews",
                search_keywords=["large language models", "screening"],
                pages_to_retrieve=1,
                results_per_page=10,
                max_discovered_records=2,
                citation_snowballing_enabled=True,
                run_mode="collect",
                openalex_enabled=False,
                semantic_scholar_enabled=False,
                crossref_enabled=False,
                include_pubmed=False,
                disable_progress_bars=True,
                fixture_data_path=fixture_path,
                data_dir=root / "data",
                papers_dir=root / "papers",
                results_dir=root / "results",
                database_path=root / "data" / "literature_review.db",
            ).finalize()

            expanded = [
                PaperMetadata(title="Expanded 1", source="fixture"),
                PaperMetadata(title="Expanded 2", source="fixture"),
            ]

            with patch("citation.citation_expander.CitationExpander.expand", return_value=expanded):
                result = PipelineController(config).run()

            self.assertEqual(result["database_count"], 2)
            papers = pd.read_csv(root / "results" / "papers.csv")
            self.assertEqual(len(papers), 2)

    def test_reset_query_records_and_clear_screening_cache_are_executed_before_reruns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base_kwargs = {
                "research_topic": "AI-assisted literature reviews",
                "search_keywords": ["large language models", "screening", "systematic review"],
                "pages_to_retrieve": 1,
                "results_per_page": 10,
                "max_papers_to_analyze": 3,
                "citation_snowballing_enabled": False,
                "openalex_enabled": False,
                "semantic_scholar_enabled": False,
                "crossref_enabled": False,
                "include_pubmed": False,
                "disable_progress_bars": True,
                "fixture_data_path": Path("tests/fixtures/offline_papers.json"),
                "data_dir": root / "data",
                "papers_dir": root / "papers",
                "results_dir": root / "results",
                "database_path": root / "data" / "literature_review.db",
            }
            first_config = ResearchConfig(**base_kwargs).finalize()
            first_result = PipelineController(first_config).run()

            self.assertEqual(first_result["run_status"], "completed")
            connection = sqlite3.connect(root / "data" / "literature_review.db")
            try:
                cache_count = connection.execute("SELECT COUNT(*) FROM screening_cache").fetchone()[0]
                paper_count = connection.execute("SELECT COUNT(*) FROM papers").fetchone()[0]
            finally:
                connection.close()
            self.assertGreater(cache_count, 0)
            self.assertGreater(paper_count, 0)

            events: list[dict[str, object]] = []
            rerun_config = ResearchConfig(
                **base_kwargs,
                reset_query_records=True,
                clear_screening_cache=True,
            ).finalize()
            rerun_result = PipelineController(rerun_config, event_sink=events.append).run()

            self.assertEqual(rerun_result["run_status"], "completed")
            deleted_events = [event for event in events if event["event_type"] == "query_records_deleted"]
            cleared_events = [event for event in events if event["event_type"] == "screening_cache_cleared"]
            self.assertTrue(deleted_events)
            self.assertTrue(cleared_events)
            self.assertGreater(deleted_events[0]["deleted_count"], 0)
            self.assertGreater(cleared_events[0]["deleted_count"], 0)

    def test_min_discovered_records_can_fail_run_before_screening(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = ResearchConfig(
                research_topic="AI-assisted literature reviews",
                search_keywords=["large language models", "screening", "systematic review"],
                pages_to_retrieve=1,
                results_per_page=10,
                min_discovered_records=99,
                run_mode="analyze",
                openalex_enabled=False,
                semantic_scholar_enabled=False,
                crossref_enabled=False,
                include_pubmed=False,
                disable_progress_bars=True,
                fixture_data_path=Path("tests/fixtures/offline_papers.json"),
                data_dir=root / "data",
                papers_dir=root / "papers",
                results_dir=root / "results",
                database_path=root / "data" / "literature_review.db",
            ).finalize()

            result = PipelineController(config).run()

            self.assertEqual(result["run_status"], "failed_min_discovered_records")
            papers = pd.read_csv(root / "results" / "papers.csv")
            self.assertTrue(papers["inclusion_decision"].isna().all())

    def test_skip_discovery_can_analyze_existing_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base_kwargs = {
                "research_topic": "AI-assisted literature reviews",
                "search_keywords": ["large language models", "screening", "systematic review"],
                "pages_to_retrieve": 1,
                "results_per_page": 10,
                "year_range_start": 2020,
                "year_range_end": 2026,
                "max_papers_to_analyze": 5,
                "openalex_enabled": False,
                "semantic_scholar_enabled": False,
                "crossref_enabled": False,
                "include_pubmed": False,
                "disable_progress_bars": True,
                "fixture_data_path": Path("tests/fixtures/offline_papers.json"),
                "data_dir": root / "data",
                "papers_dir": root / "papers",
                "results_dir": root / "results",
                "database_path": root / "data" / "literature_review.db",
            }

            collect_config = ResearchConfig(
                **base_kwargs,
                run_mode="collect",
                citation_snowballing_enabled=False,
            ).finalize()
            analyze_config = ResearchConfig(
                **{**base_kwargs, "fixture_data_path": None},
                run_mode="analyze",
                skip_discovery=True,
                citation_snowballing_enabled=True,
                llm_provider="heuristic",
                relevance_threshold=50,
            ).finalize()

            PipelineController(collect_config).run()
            result = PipelineController(analyze_config).run()

            self.assertEqual(result["run_status"], "completed")
            papers = pd.read_csv(root / "results" / "papers.csv")
            self.assertTrue(papers["inclusion_decision"].notna().any())

    def test_partial_rerun_reporting_only_can_regenerate_reports_incrementally(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base_kwargs = {
                "research_topic": "AI-assisted literature reviews",
                "search_keywords": ["large language models", "screening", "systematic review"],
                "pages_to_retrieve": 1,
                "results_per_page": 10,
                "year_range_start": 2020,
                "year_range_end": 2026,
                "max_papers_to_analyze": 5,
                "openalex_enabled": False,
                "semantic_scholar_enabled": False,
                "crossref_enabled": False,
                "include_pubmed": False,
                "disable_progress_bars": True,
                "fixture_data_path": Path("tests/fixtures/offline_papers.json"),
                "data_dir": root / "data",
                "papers_dir": root / "papers",
                "results_dir": root / "results",
                "database_path": root / "data" / "literature_review.db",
            }
            initial_config = ResearchConfig(
                **base_kwargs,
                run_mode="analyze",
                citation_snowballing_enabled=False,
                llm_provider="heuristic",
                relevance_threshold=50,
            ).finalize()
            rerun_config = ResearchConfig(
                **{**base_kwargs, "fixture_data_path": None},
                run_mode="analyze",
                partial_rerun_mode="reporting_only",
                incremental_report_regeneration=True,
                citation_snowballing_enabled=False,
                llm_provider="heuristic",
                relevance_threshold=50,
            ).finalize()

            PipelineController(initial_config).run()
            papers_csv = root / "results" / "papers.csv"
            included_db = root / "results" / "included_papers.db"
            initial_mtime = papers_csv.stat().st_mtime_ns
            initial_db_mtime = included_db.stat().st_mtime_ns
            time.sleep(0.01)

            result = PipelineController(rerun_config).run()
            second_mtime = papers_csv.stat().st_mtime_ns
            second_db_mtime = included_db.stat().st_mtime_ns

            self.assertEqual(result["run_status"], "completed_partial")
            self.assertEqual(result["partial_rerun_mode"], "reporting_only")
            self.assertEqual(initial_mtime, second_mtime)
            self.assertEqual(initial_db_mtime, second_db_mtime)

    def test_partial_rerun_can_rescreen_existing_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base_kwargs = {
                "research_topic": "AI-assisted literature reviews",
                "search_keywords": ["large language models", "screening", "systematic review"],
                "pages_to_retrieve": 1,
                "results_per_page": 10,
                "max_papers_to_analyze": 5,
                "openalex_enabled": False,
                "semantic_scholar_enabled": False,
                "crossref_enabled": False,
                "include_pubmed": False,
                "disable_progress_bars": True,
                "fixture_data_path": Path("tests/fixtures/offline_papers.json"),
                "data_dir": root / "data",
                "papers_dir": root / "papers",
                "results_dir": root / "results",
                "database_path": root / "data" / "literature_review.db",
            }
            collect_config = ResearchConfig(
                **base_kwargs,
                run_mode="collect",
                citation_snowballing_enabled=False,
            ).finalize()
            partial_config = ResearchConfig(
                **{**base_kwargs, "fixture_data_path": None},
                run_mode="analyze",
                partial_rerun_mode="screening_and_reporting",
                citation_snowballing_enabled=False,
                llm_provider="heuristic",
                relevance_threshold=50,
            ).finalize()

            PipelineController(collect_config).run()
            result = PipelineController(partial_config).run()

            self.assertEqual(result["run_status"], "completed_partial")
            papers = pd.read_csv(root / "results" / "papers.csv")
            self.assertTrue(papers["inclusion_decision"].notna().any())

    def test_controller_can_stop_before_work_begins(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = ResearchConfig(
                research_topic="AI-assisted literature reviews",
                search_keywords=["large language models", "screening", "systematic review"],
                openalex_enabled=False,
                semantic_scholar_enabled=False,
                crossref_enabled=False,
                include_pubmed=False,
                disable_progress_bars=True,
                fixture_data_path=Path("tests/fixtures/offline_papers.json"),
                data_dir=root / "data",
                papers_dir=root / "papers",
                results_dir=root / "results",
                database_path=root / "data" / "literature_review.db",
            ).finalize()

            controller = PipelineController(config)
            controller.request_stop()
            result = controller.run()

            self.assertEqual(result["run_status"], "stopped")

    def test_pass_chain_can_skip_expensive_follow_up_models_below_entry_score(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = ResearchConfig(
                research_topic="AI-assisted literature reviews",
                search_keywords=["large language models", "screening"],
                openalex_enabled=False,
                semantic_scholar_enabled=False,
                crossref_enabled=False,
                include_pubmed=False,
                disable_progress_bars=True,
                data_dir=root / "data",
                papers_dir=root / "papers",
                results_dir=root / "results",
                database_path=root / "data" / "literature_review.db",
                analysis_passes=[
                    {
                        "name": "fast",
                        "llm_provider": "heuristic",
                        "threshold": 60,
                        "decision_mode": "strict",
                    },
                    {
                        "name": "deep",
                        "llm_provider": "ollama",
                        "threshold": 85,
                        "decision_mode": "triage",
                        "maybe_threshold_margin": 10,
                        "model_name": "gpt-oss:20b",
                        "min_input_score": 70,
                    },
                ],
            ).finalize()

            controller = PipelineController(config)
            try:
                class FakeScreener:
                    def __init__(self, result: ScreeningResult) -> None:
                        self.result = result
                        self.calls = 0

                    def screen(self, paper: PaperMetadata) -> ScreeningResult:
                        self.calls += 1
                        return self.result

                fast = FakeScreener(
                    ScreeningResult(
                        stage_one_decision="maybe",
                        relevance_score=65,
                        decision="maybe",
                        explanation="Fast pass result",
                    )
                )
                deep = FakeScreener(
                    ScreeningResult(
                        stage_one_decision="include",
                        relevance_score=92,
                        decision="include",
                        explanation="Deep pass result",
                    )
                )
                controller.pass_screeners = {"fast": fast, "deep": deep}
                paper = PaperMetadata(database_id=1, title="Example paper", abstract="Example abstract", source="fixture")

                result, screening_details = controller._screen_paper_with_passes(paper)

                self.assertEqual(fast.calls, 1)
                self.assertEqual(deep.calls, 0)
                self.assertEqual(result.relevance_score, 65)
                self.assertTrue(screening_details["passes"]["deep"]["skipped"])
                self.assertEqual(screening_details["passes"]["deep"]["model_name"], "gpt-oss:20b")
                self.assertEqual(screening_details["passes"]["deep"]["min_input_score"], 70.0)
            finally:
                controller.close()
