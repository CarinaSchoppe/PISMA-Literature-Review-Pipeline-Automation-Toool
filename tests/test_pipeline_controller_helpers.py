"""Focused unit tests for `PipelineController` helper methods and lightweight branches."""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from config import ResearchConfig
from models.paper import PaperMetadata, ScreeningResult
from pipeline.pipeline_controller import PipelineController


class PipelineControllerHelperTests(unittest.TestCase):
    """Exercise controller branches that are awkward to hit through full integration runs."""

    def _config(self, root: Path, **overrides) -> ResearchConfig:
        payload = {
            "research_topic": "AI-assisted literature reviews",
            "search_keywords": ["large language models", "screening"],
            "openalex_enabled": False,
            "semantic_scholar_enabled": False,
            "crossref_enabled": False,
            "include_pubmed": False,
            "disable_progress_bars": True,
            "data_dir": root / "data",
            "papers_dir": root / "papers",
            "results_dir": root / "results",
            "database_path": root / "data" / "literature_review.db",
        }
        payload.update(overrides)
        return ResearchConfig(**payload).finalize()

    def test_build_discovery_clients_respects_enabled_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            controller = PipelineController(
                self._config(
                    root,
                    openalex_enabled=True,
                    semantic_scholar_enabled=True,
                    crossref_enabled=True,
                    springer_enabled=True,
                    arxiv_enabled=True,
                    include_pubmed=True,
                    europe_pmc_enabled=True,
                    core_enabled=True,
                )
            )
            try:
                clients = controller._build_discovery_clients()
                self.assertEqual(
                    set(clients),
                    {"openalex", "semantic_scholar", "crossref", "springer", "arxiv", "pubmed", "europe_pmc", "core"},
                )
            finally:
                controller.close()

    def test_build_discovery_clients_raises_without_any_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            controller = PipelineController(self._config(root))
            try:
                with self.assertRaises(ValueError):
                    controller._build_discovery_clients()
                self.assertEqual(controller._build_discovery_clients(allow_empty=True), {})
            finally:
                controller.close()

    def test_build_manual_import_clients_collects_all_supported_import_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manual_json = root / "manual.json"
            google_json = root / "google.json"
            researchgate_csv = root / "researchgate.csv"
            manual_json.write_text(json.dumps([{"title": "Manual paper"}]), encoding="utf-8")
            google_json.write_text(json.dumps([{"title": "Scholar paper"}]), encoding="utf-8")
            researchgate_csv.write_text("title\nResearchGate paper\n", encoding="utf-8")

            controller = PipelineController(
                self._config(
                    root,
                    manual_source_path=manual_json,
                    google_scholar_import_path=google_json,
                    researchgate_import_path=researchgate_csv,
                )
            )
            try:
                self.assertEqual(len(controller.manual_import_clients), 3)
            finally:
                controller.close()

    def test_discover_uses_fixture_and_manual_import_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture_config = self._config(root, fixture_data_path=Path("tests/fixtures/offline_papers.json"))
            fixture_controller = PipelineController(fixture_config)
            try:
                fixture_results = fixture_controller._discover()
                self.assertGreaterEqual(len(fixture_results), 1)
            finally:
                fixture_controller.close()

            manual_json = root / "manual.json"
            manual_json.write_text(json.dumps([{"title": "Manual paper", "authors": "Ada; Grace"}]), encoding="utf-8")
            manual_config = self._config(root, manual_source_path=manual_json)
            manual_controller = PipelineController(manual_config)
            try:
                results = manual_controller._discover()
                self.assertEqual(len(results), 1)
                self.assertEqual(results[0].authors, ["Ada", "Grace"])
            finally:
                manual_controller.close()

    def test_helper_methods_for_pass_configs_thresholds_and_summary_screener(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self._config(
                root,
                max_discovered_records=2,
                min_discovered_records=1,
                relevance_threshold=77,
                max_workers=8,
                discovery_workers=3,
                io_workers=2,
                screening_workers=4,
                analysis_passes=[
                    {
                        "name": "fast",
                        "llm_provider": "huggingface_local",
                        "threshold": 60,
                        "decision_mode": "strict",
                        "model_name": "Qwen/Qwen3-14B",
                    },
                    {
                        "name": "deep",
                        "llm_provider": "ollama",
                        "threshold": 85,
                        "decision_mode": "triage",
                        "maybe_threshold_margin": 12,
                        "model_name": "gpt-oss:20b",
                    },
                ],
            )
            with patch("analysis.ai_screener.build_llm_client", return_value=Mock(enabled=False)):
                controller = PipelineController(config)
            try:
                fast_config = controller._config_for_analysis_pass(config.resolved_analysis_passes[0])
                deep_config = controller._config_for_analysis_pass(config.resolved_analysis_passes[1])

                self.assertEqual(fast_config.api_settings.huggingface_model, "Qwen/Qwen3-14B")
                self.assertEqual(deep_config.api_settings.ollama_model, "gpt-oss:20b")
                self.assertEqual(deep_config.relevance_threshold, 85)
                self.assertEqual(controller._summary_config().api_settings.ollama_model, "gpt-oss:20b")
                self.assertTrue(controller._requires_local_llm_serial_execution())
                self.assertEqual(controller._screening_worker_count(), 1)
                self.assertEqual(config.effective_discovery_workers, 3)
                self.assertEqual(config.effective_io_workers, 2)
                self.assertEqual(config.effective_screening_workers, 4)
                self.assertEqual(controller._parallel_worker_count(10), 2)
                self.assertEqual(controller._final_threshold(), 85)
                self.assertEqual(len(controller._apply_discovery_limits([PaperMetadata(title="A"), PaperMetadata(title="B"), PaperMetadata(title="C")])), 2)
                self.assertTrue(controller._below_minimum_discovery_threshold(0))
                self.assertIs(controller._summary_screener(), controller.pass_screeners["deep"])
            finally:
                controller.close()

    def test_prepare_normalize_counts_and_cache_key_helpers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            controller = PipelineController(self._config(root, analyze_full_text=True))
            try:
                paper = PaperMetadata(
                    database_id=1,
                    title="Example paper",
                    abstract="Abstract",
                    source="fixture",
                    pdf_path="paper.pdf",
                    raw_payload={"full_text_excerpt": ""},
                )
                with patch.object(controller.full_text_extractor, "extract_excerpt", return_value="Extracted text"):
                    prepared = controller._prepare_paper_for_screening(paper)
                self.assertEqual(prepared.raw_payload["full_text_excerpt"], "Extracted text")

                unchanged = controller._prepare_paper_for_screening(PaperMetadata(title="No PDF", source="fixture"))
                self.assertEqual(unchanged.title, "No PDF")

                normalized = controller._normalize_papers_for_current_context(
                    [
                        PaperMetadata(
                            title="Screened",
                            source="fixture",
                            inclusion_decision="include",
                            relevance_score=88,
                            relevance_explanation="context",
                            screening_details={"screening_context_key": "old"},
                        )
                    ]
                )
                self.assertIsNone(normalized[0].inclusion_decision)
                self.assertEqual(
                    controller._decision_counts(
                        [
                            PaperMetadata(title="A", source="fixture", inclusion_decision="include"),
                            PaperMetadata(title="B", source="fixture", inclusion_decision="exclude"),
                            PaperMetadata(title="C", source="fixture", inclusion_decision="maybe"),
                            PaperMetadata(title="D", source="fixture"),
                        ]
                    ),
                    {"include": 1, "exclude": 1, "maybe": 1, "unreviewed": 1},
                )
                self.assertEqual(controller._paper_cache_key(paper), controller._paper_cache_key(paper))
            finally:
                controller.close()

    def test_emit_event_and_report_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            events: list[dict[str, object]] = []
            controller = PipelineController(self._config(root), event_sink=events.append)
            try:
                controller._emit_event("custom", stage="x")
                controller._emit_report_artifacts({"papers_csv": "results/papers.csv"})
                controller._discover_from_source("manual", lambda: [PaperMetadata(title="Paper", source="manual")])
            finally:
                controller.close()

        self.assertEqual(events[0]["event_type"], "custom")
        self.assertEqual(events[1]["event_type"], "artifact_written")

    def test_close_and_request_stop_shutdown_active_executors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            events: list[dict[str, object]] = []
            controller = PipelineController(self._config(root), event_sink=events.append)
            executor_one = Mock()
            executor_two = Mock()
            controller._active_executors = [executor_one, executor_two]

            controller.request_stop()
            controller.close()

        executor_one.shutdown.assert_called()
        executor_two.shutdown.assert_called()
        self.assertTrue(any(event["event_type"] == "stop_requested" for event in events))

    def test_pdf_threshold_logic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            controller = PipelineController(self._config(root, relevance_threshold=80))
            try:
                below = PaperMetadata(title="Low", source="fixture", relevance_score=50, inclusion_decision="include")
                included = PaperMetadata(title="High", source="fixture", relevance_score=90, inclusion_decision="include")
                excluded = PaperMetadata(title="Excluded", source="fixture", relevance_score=95, inclusion_decision="exclude")

                self.assertFalse(controller._paper_meets_pdf_download_threshold(below))
                self.assertTrue(controller._paper_meets_pdf_download_threshold(included))
                self.assertFalse(controller._paper_meets_pdf_download_threshold(excluded))
            finally:
                controller.close()

    def test_screen_papers_handles_no_passes_no_candidates_and_cached_results(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            no_pass_controller = PipelineController(self._config(root, run_mode="collect"))
            try:
                self.assertEqual(no_pass_controller._screen_papers(), {"screened_count": 0, "full_text_screened_count": 0})
            finally:
                no_pass_controller.close()

            controller = PipelineController(
                self._config(
                    root,
                    run_mode="analyze",
                    analysis_passes=[{"name": "fast", "llm_provider": "heuristic", "threshold": 60}],
                )
            )
            try:
                paper_cached = PaperMetadata(database_id=1, title="Cached", abstract="A", source="fixture")
                paper_fresh = PaperMetadata(database_id=2, title="Fresh", abstract="B", source="fixture")
                cached_result = ScreeningResult(stage_one_decision="include", relevance_score=80, decision="include")
                fresh_result = ScreeningResult(stage_one_decision="maybe", relevance_score=70, decision="maybe")

                controller.database.get_papers_for_analysis = Mock(return_value=[paper_cached, paper_fresh])
                controller.database.get_cached_screening_entry = Mock(side_effect=[(cached_result, {"cached": True}), None])
                controller.database.cache_screening_result = Mock()
                controller.database.update_screening_result = Mock()
                controller._prepare_paper_for_screening = Mock(side_effect=lambda paper: paper)
                controller._screen_paper_with_passes = Mock(return_value=(fresh_result, {"fresh": True}))

                stats = controller._screen_papers()

                self.assertEqual(stats["screened_count"], 2)
                self.assertEqual(stats["full_text_screened_count"], 0)
                controller.database.cache_screening_result.assert_called_once()
                self.assertEqual(controller.database.update_screening_result.call_count, 2)
            finally:
                controller.close()

    def test_enrich_download_and_screen_helper_branches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            controller = PipelineController(
                self._config(
                    root,
                    run_mode="analyze",
                    download_pdfs=True,
                    pdf_download_mode="all",
                    verbosity="debug",
                    analysis_passes=[{"name": "fast", "llm_provider": "heuristic", "threshold": 60}],
                )
            )
            try:
                existing = PaperMetadata(title="Existing PDF", source="fixture", pdf_path="paper.pdf")
                linked = PaperMetadata(title="Linked PDF", source="fixture", pdf_link="https://example.org/file.pdf")
                missing = PaperMetadata(title="Needs fetch", source="fixture")

                def fake_fetch_for_paper(paper: PaperMetadata, **_kwargs):  # noqa: ANN001
                    if paper.title == "Broken":
                        raise RuntimeError("boom")
                    return paper.model_copy(update={"pdf_link": paper.pdf_link or "https://example.org/fetched.pdf"})

                with patch.object(controller.pdf_fetcher, "fetch_for_paper", side_effect=fake_fetch_for_paper), patch(
                    "pipeline.pipeline_controller.LOGGER.debug"
                ) as log_debug:
                    enriched = controller._enrich_with_pdfs([existing, linked, missing, PaperMetadata(title="Broken", source="fixture")])

                self.assertEqual(len(enriched), 4)
                self.assertEqual(enriched[0].title, "Existing PDF")
                self.assertEqual(enriched[1].title, "Linked PDF")
                self.assertEqual(enriched[2].title, "Needs fetch")
                log_debug.assert_called()

                with patch.object(
                    controller.pdf_fetcher,
                    "fetch_for_paper",
                    side_effect=[PaperMetadata(title="Relevant", source="fixture", pdf_path="kept.pdf"), RuntimeError("boom")],
                ):
                    downloaded = controller._download_relevant_pdfs(
                        [
                            PaperMetadata(title="Low", source="fixture", relevance_score=10, inclusion_decision="include"),
                            PaperMetadata(title="Relevant", source="fixture", relevance_score=99, inclusion_decision="include"),
                            PaperMetadata(title="Broken", source="fixture", relevance_score=99, inclusion_decision="include"),
                        ]
                    )
                self.assertEqual(len(downloaded), 2)

                with patch.object(controller.full_text_extractor, "extract_excerpt", return_value=""):
                    unchanged = controller._prepare_paper_for_screening(
                        PaperMetadata(title="No excerpt", source="fixture", pdf_path="paper.pdf")
                    )
                self.assertEqual(unchanged.title, "No excerpt")

                controller.database.get_papers_for_analysis = Mock(
                    return_value=[
                        PaperMetadata(database_id=None, title="Skip me", source="fixture"),
                        PaperMetadata(database_id=2, title="Raise", abstract="A", source="fixture"),
                    ]
                )
                controller.database.get_cached_screening_entry = Mock(return_value=None)
                controller.database.cache_screening_result = Mock()
                controller.database.update_screening_result = Mock()
                controller._prepare_paper_for_screening = Mock(side_effect=lambda paper: paper)
                controller._screen_paper_with_passes = Mock(side_effect=RuntimeError("screening failed"))

                stats = controller._screen_papers()
                self.assertEqual(stats["screened_count"], 0)
                controller.database.update_screening_result.assert_not_called()
            finally:
                controller.close()

    def test_discover_executor_limit_and_exception_branches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            events: list[dict[str, object]] = []
            capped_controller = PipelineController(
                self._config(root, max_discovered_records=1, openalex_enabled=True),
                event_sink=events.append,
            )
            try:
                capped_controller.fixture_client = None
                capped_controller.manual_import_clients = []
                capped_controller._build_discovery_clients = Mock(
                    return_value={
                        "one": lambda: [PaperMetadata(title="Paper 1", source="one")],
                        "two": lambda: [PaperMetadata(title="Paper 2", source="two")],
                    }
                )
                limited = capped_controller._discover()
                self.assertEqual(len(limited), 1)
                self.assertTrue(any(event["event_type"] == "discovery_limit_reached" for event in events))
            finally:
                capped_controller.close()

            failing_controller = PipelineController(self._config(root, openalex_enabled=True))
            try:
                failing_controller.fixture_client = None
                failing_controller.manual_import_clients = []

                def boom():
                    raise RuntimeError("boom")

                failing_controller._build_discovery_clients = Mock(return_value={"broken": boom})
                results = failing_controller._discover()
                self.assertEqual(results, [])
            finally:
                failing_controller.close()

    def test_discover_can_use_async_network_layer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            controller = PipelineController(self._config(root, max_workers=4, openalex_enabled=True, enable_async_network_stages=True))
            try:
                controller.fixture_client = None
                controller.manual_import_clients = []
                controller._build_discovery_clients = Mock(
                    return_value={
                        "one": lambda: [PaperMetadata(title="Paper 1", source="one")],
                        "two": lambda: [PaperMetadata(title="Paper 2", source="two")],
                    }
                )
                results = controller._discover()
                self.assertEqual({paper.title for paper in results}, {"Paper 1", "Paper 2"})
            finally:
                controller.close()

    def test_async_discovery_can_hit_global_cap_and_cancel_remaining_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            events: list[dict[str, object]] = []
            controller = PipelineController(
                self._config(root, max_workers=4, max_discovered_records=1, openalex_enabled=True, enable_async_network_stages=True),
                event_sink=events.append,
            )
            try:
                controller.fixture_client = None
                controller.manual_import_clients = []
                controller._build_discovery_clients = Mock(
                    return_value={
                        "one": lambda: [PaperMetadata(title="Paper 1", source="one")],
                        "two": lambda: [PaperMetadata(title="Paper 2", source="two")],
                    }
                )
                limited = controller._discover()
                self.assertEqual(len(limited), 1)
                self.assertTrue(any(event["event_type"] == "discovery_limit_reached" for event in events))
            finally:
                controller.close()

    def test_async_discovery_handles_source_exceptions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            controller = PipelineController(self._config(root, openalex_enabled=True, enable_async_network_stages=True))
            try:
                controller.fixture_client = None
                controller.manual_import_clients = []
                controller._build_discovery_clients = Mock(
                    return_value={
                        "good": lambda: [PaperMetadata(title="Paper 1", source="good")],
                        "broken": Mock(side_effect=RuntimeError("boom")),
                    }
                )
                results = controller._discover()
                self.assertEqual([paper.title for paper in results], ["Paper 1"])
            finally:
                controller.close()

    def test_parallel_mapping_preserves_order_and_caps_worker_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            controller = PipelineController(self._config(root, max_workers=4, verbosity="verbose"))
            try:
                papers = [
                    PaperMetadata(title="Paper A", source="fixture"),
                    PaperMetadata(title="Paper B", source="fixture"),
                    PaperMetadata(title="Paper C", source="fixture"),
                ]

                def worker(paper: PaperMetadata) -> PaperMetadata:
                    delays = {"Paper A": 0.03, "Paper B": 0.01, "Paper C": 0.02}
                    time.sleep(delays[paper.title])
                    return paper.model_copy(update={"venue": f"done-{paper.title}"})

                with patch("pipeline.pipeline_controller.LOGGER.info"):
                    results = controller._map_papers_with_executor(papers, worker, desc="Parallel stage")
                    empty_results = controller._map_papers_with_executor([], worker, desc="Empty stage")
                    serial_results = controller._map_papers_with_executor([papers[0]], worker, desc="Serial stage")

                self.assertEqual([paper.title for paper in results], ["Paper A", "Paper B", "Paper C"])
                self.assertEqual([paper.venue for paper in results], ["done-Paper A", "done-Paper B", "done-Paper C"])
                self.assertEqual(empty_results, [])
                self.assertEqual([paper.venue for paper in serial_results], ["done-Paper A"])
                self.assertEqual(controller._parallel_worker_count(1), 1)
                self.assertEqual(controller._parallel_worker_count(3), 3)
                self.assertEqual(controller._parallel_worker_count(20), 4)
            finally:
                controller.close()

    def test_pdf_batch_queue_splits_work_into_configured_batches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            controller = PipelineController(self._config(root, pdf_batch_size=2))
            try:
                papers = [
                    PaperMetadata(title="A", source="fixture"),
                    PaperMetadata(title="B", source="fixture"),
                    PaperMetadata(title="C", source="fixture"),
                    PaperMetadata(title="D", source="fixture"),
                    PaperMetadata(title="E", source="fixture"),
                ]
                batch_descriptions: list[str] = []

                def fake_map(batch: list[PaperMetadata], _worker, *, desc: str):  # noqa: ANN001
                    batch_descriptions.append(desc)
                    return batch

                controller._map_papers_with_executor = Mock(side_effect=fake_map)
                processed = controller._process_pdf_batch_queue(papers, lambda paper: paper, desc="PDF queue")

                self.assertEqual([paper.title for paper in processed], ["A", "B", "C", "D", "E"])
                self.assertEqual(
                    batch_descriptions,
                    ["PDF queue batch 1/3", "PDF queue batch 2/3", "PDF queue batch 3/3"],
                )
            finally:
                controller.close()

    def test_pdf_batch_queue_returns_empty_without_work(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            controller = PipelineController(self._config(root, pdf_batch_size=3))
            try:
                self.assertEqual(controller._process_pdf_batch_queue([], lambda paper: paper, desc="Empty queue"), [])
            finally:
                controller.close()

    def test_map_papers_async_preserves_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            controller = PipelineController(self._config(root, max_workers=3, enable_async_network_stages=True))
            try:
                papers = [
                    PaperMetadata(title="Paper A", source="fixture"),
                    PaperMetadata(title="Paper B", source="fixture"),
                    PaperMetadata(title="Paper C", source="fixture"),
                ]

                def worker(paper: PaperMetadata) -> PaperMetadata:
                    delays = {"Paper A": 0.03, "Paper B": 0.01, "Paper C": 0.02}
                    time.sleep(delays[paper.title])
                    return paper.model_copy(update={"venue": f"done-{paper.title}"})

                results = controller._map_papers_async(papers, worker, desc="Async stage", worker_count=3)
                self.assertEqual([paper.title for paper in results], ["Paper A", "Paper B", "Paper C"])
                self.assertEqual([paper.venue for paper in results], ["done-Paper A", "done-Paper B", "done-Paper C"])
            finally:
                controller.close()

    def test_map_papers_with_executor_can_delegate_to_async_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            controller = PipelineController(self._config(root, max_workers=3, enable_async_network_stages=True))
            try:
                papers = [
                    PaperMetadata(title="Paper A", source="fixture"),
                    PaperMetadata(title="Paper B", source="fixture"),
                ]
                async_results = [paper.model_copy(update={"venue": "async"}) for paper in papers]
                with patch.object(controller, "_map_papers_async", return_value=async_results) as async_mock:
                    results = controller._map_papers_with_executor(papers, lambda paper: paper, desc="Async delegate")
                self.assertEqual(results, async_results)
                async_mock.assert_called_once()
            finally:
                controller.close()

    def test_partial_rerun_returns_failure_when_no_stored_records_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            controller = PipelineController(self._config(root, partial_rerun_mode="reporting_only"))
            try:
                controller.database.get_papers_for_query = Mock(return_value=[])
                result = controller._run_partial_rerun()
                self.assertEqual(result["run_status"], "failed_partial_rerun")
            finally:
                controller.close()

    def test_partial_rerun_can_refresh_pdfs_and_download_relevant_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            controller = PipelineController(
                self._config(
                    root,
                    run_mode="analyze",
                    partial_rerun_mode="pdfs_screening_reporting",
                    download_pdfs=True,
                    pdf_download_mode="relevant_only",
                )
            )
            try:
                stored = [PaperMetadata(database_id=1, title="Stored", source="fixture")]
                enriched = [stored[0].model_copy(update={"pdf_link": "https://example.org/paper.pdf"})]
                relevant = [stored[0].model_copy(update={"pdf_path": "papers/paper.pdf"})]
                controller.database.get_papers_for_query = Mock(side_effect=[stored, stored, stored])
                controller.database.upsert_papers = Mock()
                controller._enrich_with_pdfs = Mock(return_value=enriched)
                controller._screen_papers = Mock(return_value={"screened_count": 1, "full_text_screened_count": 0})
                controller._download_relevant_pdfs = Mock(return_value=relevant)
                controller._finalize_run_result = Mock(return_value={"run_status": "completed_partial"})

                result = controller._run_partial_rerun()

                self.assertEqual(result["run_status"], "completed_partial")
                self.assertEqual(controller.database.upsert_papers.call_count, 2)
                controller._download_relevant_pdfs.assert_called_once()
            finally:
                controller.close()

    def test_screen_papers_uses_parallel_preparation_helper(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            controller = PipelineController(
                self._config(
                    root,
                    run_mode="analyze",
                    analysis_passes=[{"name": "fast", "llm_provider": "heuristic", "threshold": 60}],
                )
            )
            try:
                paper = PaperMetadata(database_id=2, title="Prepared", abstract="A", source="fixture")
                result = ScreeningResult(stage_one_decision="include", relevance_score=75, decision="include")

                controller.database.get_papers_for_analysis = Mock(return_value=[paper])
                controller.database.get_cached_screening_entry = Mock(return_value=None)
                controller.database.cache_screening_result = Mock()
                controller.database.update_screening_result = Mock()
                controller._screen_paper_with_passes = Mock(return_value=(result, {"fresh": True}))
                controller._map_papers_with_executor = Mock(return_value=[paper])

                stats = controller._screen_papers()

                self.assertEqual(stats["screened_count"], 1)
                controller._map_papers_with_executor.assert_called_once()
            finally:
                controller.close()

    def test_prepare_and_download_helpers_cover_blank_excerpt_and_no_relevant_pdfs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            controller = PipelineController(self._config(root, analyze_full_text=True))
            try:
                paper = PaperMetadata(title="Full text", source="fixture", pdf_path="paper.pdf")
                with patch.object(controller.full_text_extractor, "extract_excerpt", return_value=""):
                    prepared = controller._prepare_paper_for_screening(paper)
                self.assertEqual(prepared, paper)
                self.assertEqual(
                    controller._download_relevant_pdfs(
                        [PaperMetadata(title="Low", source="fixture", relevance_score=10, inclusion_decision="exclude")]
                    ),
                    [],
                )
            finally:
                controller.close()

    def test_screen_paper_with_passes_covers_missing_screener_logging_and_empty_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = self._config(
                root,
                run_mode="analyze",
                verbosity="verbose",
                analysis_passes=[{"name": "fast", "llm_provider": "heuristic", "threshold": 60}],
            )
            controller = PipelineController(config)
            try:
                controller.pass_screeners = {}
                paper = PaperMetadata(database_id=1, title="Example", abstract="Abstract", source="fixture")
                result, details = controller._screen_paper_with_passes(paper)
                self.assertEqual(details["final_pass"], "fast")
                self.assertEqual(result.screening_context_key, controller.config.screening_context_key)
            finally:
                controller.close()

            no_pass_controller = PipelineController(self._config(root, run_mode="collect"))
            try:
                with self.assertRaises(ValueError):
                    no_pass_controller._screen_paper_with_passes(PaperMetadata(title="No passes", source="fixture"))
                self.assertEqual(no_pass_controller._summary_config().research_topic, no_pass_controller.config.research_topic)
                self.assertEqual(no_pass_controller._final_threshold(), no_pass_controller.config.relevance_threshold)
                self.assertFalse(no_pass_controller._paper_meets_pdf_download_threshold(PaperMetadata(title="Unset", source="fixture")))
                with patch("pipeline.pipeline_controller.LOGGER.info") as info_mock, patch(
                    "pipeline.pipeline_controller.LOGGER.debug"
                ) as debug_mock:
                    no_pass_controller._log_verbose("hello %s", "world")
                    no_pass_controller._log_debug("debug %s", "world")
                info_mock.assert_not_called()
                debug_mock.assert_not_called()
            finally:
                no_pass_controller.close()


if __name__ == "__main__":
    unittest.main()
