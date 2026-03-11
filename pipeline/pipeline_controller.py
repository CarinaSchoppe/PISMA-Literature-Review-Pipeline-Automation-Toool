"""High-level orchestration for discovery, enrichment, screening, and reporting."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Event
from typing import Any

from models.paper import PaperMetadata, ScreeningResult
from tqdm import tqdm

from acquisition.full_text_extractor import FullTextExtractor
from acquisition.pdf_fetcher import PDFFetcher
from analysis.ai_screener import AIScreener
from citation.citation_expander import CitationExpander
from config import AnalysisPassConfig, ResearchConfig
from database import DatabaseManager
from discovery.arxiv_client import ArxivClient
from discovery.core_client import COREClient
from discovery.crossref_client import CrossrefClient
from discovery.europe_pmc_client import EuropePMCClient
from discovery.fixture_client import FixtureDiscoveryClient
from discovery.google_scholar_client import GoogleScholarClient
from discovery.manual_import_client import ManualImportClient
from discovery.null_citation_provider import NullCitationProvider
from discovery.openalex_client import OpenAlexClient
from discovery.pubmed_client import PubMedClient
from discovery.semantic_scholar_client import SemanticScholarClient
from discovery.springer_client import SpringerClient
from reporting.report_generator import ReportGenerator
from utils.deduplication import deduplicate_papers
from utils.http import configure_http_logging, configure_http_runtime
from utils.text_processing import stable_hash

LOGGER = logging.getLogger(__name__)


class PipelineStoppedError(RuntimeError):
    """Raised when the user requests a controlled stop of the active pipeline run."""


class PipelineController:
    """Coordinate the end-to-end literature review workflow for one run configuration."""

    def __init__(
        self,
        config: ResearchConfig,
        *,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
        stop_event: Event | None = None,
    ) -> None:
        self.config = config.finalize()
        self.event_sink = event_sink
        self.stop_event = stop_event or Event()
        self._active_executors: list[ThreadPoolExecutor] = []
        configure_http_logging(
            enabled=self.config.log_http_requests and self.config.verbosity in {"verbose", "ultra_verbose"},
            log_payloads=self.config.log_http_payloads and self.config.verbosity == "ultra_verbose",
        )
        configure_http_runtime(
            cache_enabled=self.config.http_cache_enabled,
            cache_dir=self.config.http_cache_dir,
            cache_ttl_seconds=self.config.http_cache_ttl_seconds,
            retry_max_attempts=self.config.http_retry_max_attempts,
            retry_base_delay_seconds=self.config.http_retry_base_delay_seconds,
            retry_max_delay_seconds=self.config.http_retry_max_delay_seconds,
        )
        self.database = DatabaseManager(self.config.database_path)
        self.database.initialize()
        self.fixture_client = FixtureDiscoveryClient(self.config) if self.config.fixture_data_path else None
        self.manual_import_clients = self._build_manual_import_clients()
        self.openalex_client = OpenAlexClient(self.config)
        self.semantic_scholar_client = SemanticScholarClient(self.config)
        self.crossref_client = CrossrefClient(self.config)
        self.springer_client = SpringerClient(self.config)
        self.arxiv_client = ArxivClient(self.config)
        self.pubmed_client = PubMedClient(self.config)
        self.europe_pmc_client = EuropePMCClient(self.config)
        self.core_client = COREClient(self.config)
        self.google_scholar_client = GoogleScholarClient(self.config, should_stop=self.stop_event.is_set)
        self.pdf_fetcher = PDFFetcher(self.config)
        self.full_text_extractor = FullTextExtractor(max_chars=self.config.full_text_max_chars)
        self.pass_screeners = self._build_pass_screeners()
        self.ai_screener = self._summary_screener()
        citation_provider = self.fixture_client or (self.openalex_client if self.config.openalex_enabled else NullCitationProvider())
        self.citation_expander = CitationExpander(self.config, self.database, citation_provider)
        self.report_generator = ReportGenerator(self.config, self.ai_screener)
        if self.config.citation_snowballing_enabled and isinstance(citation_provider, NullCitationProvider):
            LOGGER.info("Citation snowballing is enabled, but no citation-capable API source is active; skipping expansion.")
        if self._requires_local_llm_serial_execution():
            LOGGER.info("Local Hugging Face inference is active; screening parallelism is reduced to 1 worker.")

    def run(self) -> dict[str, str | int]:
        """Execute the configured workflow and return paths plus summary statistics."""

        try:
            self._check_stop()
            self._emit_event("stage_started", stage="pipeline")
            pipeline_started = time.perf_counter()
            LOGGER.info(
                "Starting literature pipeline in %s mode for topic '%s'.",
                self.config.run_mode,
                self.config.research_topic,
            )
            self._log_verbose("Search query: %s", self.config.search_query)
            self._log_trace("Effective configuration: %s", self.config.model_dump(mode="json"))
            snapshot_path = self.config.save_snapshot()
            self._log_trace("Configuration snapshot written to %s.", snapshot_path)
            if self.config.reset_query_records:
                deleted_records = self.database.delete_papers_for_query(self.config.query_key or "")
                LOGGER.info("Deleted %s existing records for query '%s' before the run.", deleted_records, self.config.query_key)
                self._emit_event("query_records_deleted", deleted_count=deleted_records, query_key=self.config.query_key)
            if self.config.clear_screening_cache:
                cleared_cache = self.database.clear_screening_cache(self.config.screening_context_key)
                LOGGER.info("Cleared %s screening-cache entries for the current screening context.", cleared_cache)
                self._emit_event(
                    "screening_cache_cleared",
                    deleted_count=cleared_cache,
                    screening_context_key=self.config.screening_context_key,
                )
            if self.config.partial_rerun_mode != "off":
                return self._run_partial_rerun()
            if self.config.skip_discovery:
                self._emit_event("stage_started", stage="load_existing")
                load_started = time.perf_counter()
                stored = self._apply_discovery_limits(self.database.get_papers_for_query(self.config.query_key or ""))
                discovered = list(stored)
                deduplicated = list(stored)
                self._emit_event("stage_finished", stage="load_existing", record_count=len(stored))
                LOGGER.info(
                    "Skipping discovery and loading %s stored records for query '%s'.",
                    len(stored),
                    self.config.query_key,
                )
                self._log_verbose("Loading stored records took %.2f seconds.", time.perf_counter() - load_started)
            else:
                self._emit_event("stage_started", stage="discovery")
                discovery_started = time.perf_counter()
                discovered = self._discover()
                self._emit_event("stage_finished", stage="discovery", record_count=len(discovered))
                LOGGER.info("Discovery completed with %s records.", len(discovered))
                deduplicated = deduplicate_papers(
                    discovered,
                    title_similarity_threshold=self.config.title_similarity_threshold,
                )
                deduplicated = self._apply_discovery_limits(deduplicated)
                LOGGER.info("Deduplication completed with %s unique records.", len(deduplicated))
                stored = self.database.upsert_papers(deduplicated, self.config.query_key or "")
                self._log_verbose("Stored %s records in SQLite.", len(stored))
                self._log_verbose("Discovery and deduplication took %.2f seconds.", time.perf_counter() - discovery_started)
            if self._below_minimum_discovery_threshold(len(deduplicated)):
                reason = (
                    f"Discovered {len(deduplicated)} unique records, below the configured minimum of "
                    f"{self.config.min_discovered_records}."
                )
                LOGGER.error(reason)
                self._emit_event("run_failed", stage="discovery", reason=reason)
                final_papers = self._normalize_papers_for_current_context(
                    self.database.get_papers_for_query(self.config.query_key or "")
                )
                return self._finalize_run_result(
                    final_papers=final_papers,
                    discovered_count=len(discovered),
                    deduplicated_count=len(deduplicated),
                    snowballing_added_count=0,
                    screening_stats={"screened_count": 0, "full_text_screened_count": 0},
                    run_status="failed_min_discovered_records",
                    run_error=reason,
                    emit_completed_event=False,
                )

            expanded: list[PaperMetadata] = []
            self._check_stop()
            if self.config.skip_discovery:
                LOGGER.info("Skip discovery is enabled; citation snowballing is skipped for this run.")
            elif self.config.max_discovered_records is not None and len(stored) >= self.config.max_discovered_records:
                LOGGER.info(
                    "Skipping citation snowballing because the discovery cap of %s records is already reached.",
                    self.config.max_discovered_records,
                )
            else:
                expanded = self.citation_expander.expand(stored)
            if expanded:
                LOGGER.info("Citation snowballing discovered %s additional records.", len(expanded))
                expanded_deduplicated = deduplicate_papers(
                    expanded,
                    title_similarity_threshold=self.config.title_similarity_threshold,
                )
                if self.config.max_discovered_records is not None:
                    remaining_capacity = max(self.config.max_discovered_records - len(stored), 0)
                    expanded_deduplicated = expanded_deduplicated[:remaining_capacity]
                if expanded_deduplicated:
                    self.database.upsert_papers(expanded_deduplicated, self.config.query_key or "")
            elif self.config.citation_snowballing_enabled:
                self._log_verbose("Citation snowballing returned no additional records.")

            current_papers = self._apply_discovery_limits(
                self.database.get_papers_for_query(self.config.query_key or "")
            )
            self._log_verbose("Loaded %s records for enrichment.", len(current_papers))
            enriched_papers = self._enrich_with_pdfs(current_papers)
            if enriched_papers:
                self.database.upsert_papers(enriched_papers, self.config.query_key or "")

            if self.config.run_mode == "collect":
                LOGGER.info("Run mode is collect; AI screening is skipped.")
                screening_stats = {"screened_count": 0, "full_text_screened_count": 0}
            else:
                screening_stats = self._screen_papers()
                if self.config.download_pdfs and self.config.pdf_download_mode == "relevant_only":
                    relevant_pdf_updates = self._download_relevant_pdfs(
                        self._apply_discovery_limits(
                            self.database.get_papers_for_query(self.config.query_key or "")
                        )
                    )
                    if relevant_pdf_updates:
                        self.database.upsert_papers(relevant_pdf_updates, self.config.query_key or "")
            final_papers = self._apply_discovery_limits(
                self._normalize_papers_for_current_context(
                    self.database.get_papers_for_query(self.config.query_key or "")
                )
            )
            self._log_verbose("Pipeline finished in %.2f seconds.", time.perf_counter() - pipeline_started)
            return self._finalize_run_result(
                final_papers=final_papers,
                discovered_count=len(discovered),
                deduplicated_count=len(deduplicated),
                snowballing_added_count=len(expanded) if expanded else 0,
                screening_stats=screening_stats,
                run_status="completed",
            )
        except PipelineStoppedError as exc:
            LOGGER.warning("Pipeline stopped on request: %s", exc)
            self._emit_event("run_stopped", stage="pipeline", reason=str(exc))
            database_count = 0
            if self.config.query_key:
                database_count = self.database.count_papers(self.config.query_key)
            return {
                "discovered_count": 0,
                "deduplicated_count": 0,
                "database_count": database_count,
                "run_status": "stopped",
                "run_error": str(exc),
                "log_file": str(self.config.log_file_path) if self.config.log_file_path else "",
            }
        finally:
            self.close()

    def close(self) -> None:
        """Release external resources held by the controller."""

        for executor in list(self._active_executors):
            executor.shutdown(wait=False, cancel_futures=True)
        self._active_executors.clear()
        self.database.close()

    def request_stop(self) -> None:
        """Signal the controller to stop as soon as the current operation reaches a safe boundary."""

        self.stop_event.set()
        for executor in list(self._active_executors):
            executor.shutdown(wait=False, cancel_futures=True)
        self._emit_event("stop_requested", stage="pipeline")

    def _run_partial_rerun(self) -> dict[str, str | int]:
        """Execute only the downstream stages requested by the partial-rerun mode."""

        mode = self.config.partial_rerun_mode
        self._emit_event("stage_started", stage="partial_rerun", mode=mode)
        rerun_started = time.perf_counter()
        LOGGER.info("Running partial rerun mode '%s'.", mode)
        stored_papers = self._apply_discovery_limits(self.database.get_papers_for_query(self.config.query_key or ""))
        if not stored_papers:
            reason = "Partial rerun requested, but no stored records exist for the current query."
            LOGGER.error(reason)
            self._emit_event("run_failed", stage="partial_rerun", reason=reason)
            return {
                "discovered_count": 0,
                "deduplicated_count": 0,
                "database_count": 0,
                "run_status": "failed_partial_rerun",
                "run_error": reason,
            }

        screening_stats = {"screened_count": 0, "full_text_screened_count": 0}
        if mode == "pdfs_screening_reporting":
            LOGGER.info("Refreshing PDF metadata before screening.")
            enriched_papers = self._enrich_with_pdfs(stored_papers)
            if enriched_papers:
                self.database.upsert_papers(enriched_papers, self.config.query_key or "")

        if mode in {"screening_and_reporting", "pdfs_screening_reporting"} and self.config.run_mode != "collect":
            screening_stats = self._screen_papers()
            if self.config.download_pdfs and self.config.pdf_download_mode == "relevant_only":
                relevant_pdf_updates = self._download_relevant_pdfs(
                    self._apply_discovery_limits(self.database.get_papers_for_query(self.config.query_key or ""))
                )
                if relevant_pdf_updates:
                    self.database.upsert_papers(relevant_pdf_updates, self.config.query_key or "")

        final_papers = self._apply_discovery_limits(
            self._normalize_papers_for_current_context(
                self.database.get_papers_for_query(self.config.query_key or "")
            )
        )
        self._log_verbose("Partial rerun '%s' finished in %.2f seconds.", mode, time.perf_counter() - rerun_started)
        return self._finalize_run_result(
            final_papers=final_papers,
            discovered_count=len(stored_papers),
            deduplicated_count=len(stored_papers),
            snowballing_added_count=0,
            screening_stats=screening_stats,
            run_status="completed_partial",
            extra_result_fields={"partial_rerun_mode": mode},
        )

    def _finalize_run_result(
        self,
        *,
        final_papers: list[PaperMetadata],
        discovered_count: int,
        deduplicated_count: int,
        snowballing_added_count: int,
        screening_stats: dict[str, int],
        run_status: str,
        run_error: str | None = None,
        emit_completed_event: bool = True,
        extra_result_fields: dict[str, Any] | None = None,
    ) -> dict[str, str | int]:
        """Generate reports, emit artifact events, and build the final result payload."""

        stats = self._build_report_stats(
            final_papers=final_papers,
            discovered_count=discovered_count,
            deduplicated_count=deduplicated_count,
            snowballing_added_count=snowballing_added_count,
            screening_stats=screening_stats,
        )
        report_paths = self.report_generator.generate(final_papers, stats=stats)
        self._log_verbose("Generated %s report artifacts.", len(report_paths))
        self._emit_report_artifacts(report_paths)
        if emit_completed_event and run_status.startswith("completed"):
            self._emit_event("run_completed", stage="pipeline", report_paths=report_paths)
        return {
            **report_paths,
            "discovered_count": discovered_count,
            "deduplicated_count": deduplicated_count,
            "database_count": len(final_papers),
            "run_status": run_status,
            "log_file": str(self.config.log_file_path) if self.config.log_file_path else "",
            **(extra_result_fields or {}),
            **({"run_error": run_error} if run_error else {}),
        }

    def _build_report_stats(
        self,
        *,
        final_papers: list[PaperMetadata],
        discovered_count: int,
        deduplicated_count: int,
        snowballing_added_count: int,
        screening_stats: dict[str, int],
    ) -> dict[str, Any]:
        """Build the shared reporting stats payload used by full and partial runs."""

        return {
            "discovered_count": discovered_count,
            "deduplicated_count": deduplicated_count,
            "snowballing_added_count": snowballing_added_count,
            "decision_counts": self._decision_counts(final_papers),
            "screened_count": len([paper for paper in final_papers if paper.inclusion_decision]),
            "newly_screened_count": screening_stats["screened_count"],
            "full_text_screened_count": screening_stats["full_text_screened_count"],
            "run_mode": self.config.run_mode,
            "partial_rerun_mode": self.config.partial_rerun_mode,
        }

    def _discover(self) -> list[PaperMetadata]:
        """Collect metadata from fixtures, manual imports, and enabled API clients."""

        self._check_stop()
        if self.fixture_client:
            self._log_verbose("Loading discovery records from fixture file %s.", self.config.fixture_data_path)
            return self.fixture_client.search()
        imported: list[PaperMetadata] = []
        for manual_client in self.manual_import_clients:
            self._check_stop()
            self._log_verbose("Importing discovery records from %s.", manual_client.path)
            imported.extend(manual_client.search())

        discovered: list[PaperMetadata] = list(imported)
        clients = self._build_discovery_clients(allow_empty=bool(imported))
        if not clients:
            return discovered
        if self.config.enable_async_network_stages:
            return discovered + self._discover_async(clients)
        with ThreadPoolExecutor(max_workers=min(self.config.effective_discovery_workers, len(clients))) as executor:
            self._active_executors.append(executor)
            try:
                future_map = {
                    executor.submit(self._discover_from_source, name, callable_): name
                    for name, callable_ in clients.items()
                }
                for future in tqdm(
                    as_completed(future_map),
                    total=len(future_map),
                    desc="Discovery sources",
                    unit="source",
                    disable=self.config.disable_progress_bars,
                ):
                    self._check_stop()
                    source_name = future_map[future]
                    try:
                        source_records = future.result()
                        discovered.extend(source_records)
                        self._emit_event(
                            "source_completed",
                            source=source_name,
                            record_count=len(source_records),
                        )
                        if self.config.max_discovered_records is not None:
                            limited = deduplicate_papers(
                                discovered,
                                title_similarity_threshold=self.config.title_similarity_threshold,
                            )
                            # The cap is enforced on the merged global result set, not per source.
                            if len(limited) >= self.config.max_discovered_records:
                                LOGGER.info(
                                    "Discovery cap of %s unique records reached; trimming the result set.",
                                    self.config.max_discovered_records,
                                )
                                self._emit_event(
                                    "discovery_limit_reached",
                                    limit=self.config.max_discovered_records,
                                    record_count=len(limited),
                                )
                                return limited[: self.config.max_discovered_records]
                    except Exception as exc:  # noqa: BLE001
                        LOGGER.exception("Discovery failed for %s: %s", source_name, exc)
            finally:
                if executor in self._active_executors:
                    self._active_executors.remove(executor)
        return discovered

    def _discover_async(self, clients: dict[str, Callable[[], list[PaperMetadata]]]) -> list[PaperMetadata]:
        """Run discovery sources through an asyncio coordination layer for network-heavy runs."""

        return asyncio.run(self._discover_async_impl(clients))

    async def _discover_async_impl(self, clients: dict[str, Callable[[], list[PaperMetadata]]]) -> list[PaperMetadata]:
        """Coordinate discovery sources asynchronously while preserving the current source contract."""

        discovered: list[PaperMetadata] = []
        semaphore = asyncio.Semaphore(max(1, min(self.config.effective_discovery_workers, len(clients))))

        async def run_source(name: str, search_callable: Callable[[], list[PaperMetadata]]) -> tuple[str, list[PaperMetadata]]:
            async with semaphore:
                return name, await asyncio.to_thread(self._discover_from_source, name, search_callable)

        tasks = [asyncio.create_task(run_source(name, callable_)) for name, callable_ in clients.items()]
        for task in tasks:
            task.set_name(f"discover:{task.get_name()}")
        for completed in asyncio.as_completed(tasks):
            self._check_stop()
            try:
                source_name, source_records = await completed
                discovered.extend(source_records)
                self._emit_event("source_completed", source=source_name, record_count=len(source_records))
                if self.config.max_discovered_records is not None:
                    limited = deduplicate_papers(
                        discovered,
                        title_similarity_threshold=self.config.title_similarity_threshold,
                    )
                    if len(limited) >= self.config.max_discovered_records:
                        LOGGER.info(
                            "Discovery cap of %s unique records reached; trimming the result set.",
                            self.config.max_discovered_records,
                        )
                        self._emit_event(
                            "discovery_limit_reached",
                            limit=self.config.max_discovered_records,
                            record_count=len(limited),
                        )
                        for task in tasks:
                            task.cancel()
                        return limited[: self.config.max_discovered_records]
            except Exception as exc:  # noqa: BLE001
                LOGGER.exception("Async discovery source failed: %s", exc)
        return discovered

    def _build_discovery_clients(self, *, allow_empty: bool = False) -> dict[str, Callable[[], list[PaperMetadata]]]:
        """Return the enabled discovery clients for the current configuration."""

        clients: dict[str, Callable[[], list[PaperMetadata]]] = {}
        if self.config.openalex_enabled:
            clients["openalex"] = self.openalex_client.search
        if self.config.semantic_scholar_enabled:
            clients["semantic_scholar"] = self.semantic_scholar_client.search
        if self.config.crossref_enabled:
            clients["crossref"] = self.crossref_client.search
        if self.config.springer_enabled:
            clients["springer"] = self.springer_client.search
        if self.config.arxiv_enabled:
            clients["arxiv"] = self.arxiv_client.search
        if self.config.include_pubmed:
            clients["pubmed"] = self.pubmed_client.search
        if self.config.europe_pmc_enabled:
            clients["europe_pmc"] = self.europe_pmc_client.search
        if self.config.core_enabled:
            clients["core"] = self.core_client.search
        if self.config.google_scholar_enabled:
            clients["google_scholar"] = self.google_scholar_client.search
        if not clients and not allow_empty:
            raise ValueError("At least one discovery source must be enabled")
        return clients

    def _enrich_with_pdfs(self, papers: list[PaperMetadata]) -> list[PaperMetadata]:
        """Resolve PDF metadata and optionally download files for discovered papers."""

        self._log_verbose("Checking PDF availability for %s papers.", len(papers))
        return self._process_pdf_batch_queue(
            papers,
            self._enrich_paper_with_pdf,
            desc="PDF metadata and downloads",
        )

    def _download_relevant_pdfs(self, papers: list[PaperMetadata]) -> list[PaperMetadata]:
        """Download PDFs only for papers that survive final thresholding."""

        relevant_papers = [paper for paper in papers if self._paper_meets_pdf_download_threshold(paper)]
        if not relevant_papers:
            return []
        self._log_verbose(
            "Downloading PDFs for %s relevant papers into %s.",
            len(relevant_papers),
            self.config.relevant_pdfs_dir,
        )
        return self._process_pdf_batch_queue(
            relevant_papers,
            self._download_one_relevant_pdf,
            desc="Relevant PDF downloads",
        )

    def _screen_papers(self) -> dict[str, int]:
        """Run screening passes on the highest-priority papers still requiring analysis."""

        if not self.config.resolved_analysis_passes:
            return {"screened_count": 0, "full_text_screened_count": 0}
        candidates = self.database.get_papers_for_analysis(
            self.config.query_key or "",
            min(
                self.config.max_papers_to_analyze,
                self.config.max_discovered_records or self.config.max_papers_to_analyze,
            ),
            resume_mode=self.config.resume_mode,
            screening_context_key=self.config.screening_context_key,
        )
        if not candidates:
            LOGGER.info("No papers require screening for the current context.")
            return {"screened_count": 0, "full_text_screened_count": 0}

        LOGGER.info("Preparing %s papers for screening.", len(candidates))
        prepared_candidates = self._map_papers_with_executor(
            candidates,
            self._prepare_paper_for_screening,
            desc="Screening preparation",
        )
        full_text_screened_count = len(
            [paper for paper in prepared_candidates if paper.raw_payload.get("full_text_excerpt")]
        )
        results: list[tuple[int, ScreeningResult, dict[str, Any]]] = []
        cached_results: list[tuple[int, ScreeningResult, dict[str, Any]]] = []
        uncached_candidates: list[PaperMetadata] = []
        for paper in prepared_candidates:
            if paper.database_id is None:
                continue
            cache_key = self._paper_cache_key(paper)
            cached = self.database.get_cached_screening_entry(cache_key, self.config.screening_context_key)
            if cached is None:
                uncached_candidates.append(paper)
            else:
                cached_results.append((paper.database_id, cached[0], cached[1]))

        if cached_results:
            LOGGER.info("Reused %s cached screening results.", len(cached_results))

        screening_workers = self._screening_worker_count()
        with ThreadPoolExecutor(max_workers=screening_workers) as executor:
            self._active_executors.append(executor)
            try:
                future_map = {
                    executor.submit(self._screen_paper_with_passes, paper): paper
                    for paper in uncached_candidates
                    if paper.database_id is not None
                }
                for future in tqdm(
                    as_completed(future_map),
                    total=len(future_map),
                    desc="AI screening",
                    unit="paper",
                    disable=self.config.disable_progress_bars,
                ):
                    self._check_stop()
                    paper = future_map[future]
                    try:
                        result, screening_details = future.result()
                        self.database.cache_screening_result(
                            paper=paper,
                            paper_cache_key=self._paper_cache_key(paper),
                            screening_context_key=self.config.screening_context_key,
                            result=result,
                            screening_details=screening_details,
                        )
                        results.append((paper.database_id or 0, result, screening_details))
                    except Exception as exc:  # noqa: BLE001
                        LOGGER.exception("Screening failed for %s: %s", paper.title, exc)
            finally:
                if executor in self._active_executors:
                    self._active_executors.remove(executor)

        for database_id, result, screening_details in [*cached_results, *results]:
            self.database.update_screening_result(database_id, result, screening_details=screening_details)
        return {
            "screened_count": len(cached_results) + len(results),
            "full_text_screened_count": full_text_screened_count,
        }

    def _prepare_paper_for_screening(self, paper: PaperMetadata) -> PaperMetadata:
        """Attach an extracted full-text excerpt when configured and available."""

        if not self.config.analyze_full_text or not paper.pdf_path:
            return paper
        full_text_excerpt = self.full_text_extractor.extract_excerpt(paper.pdf_path)
        if not full_text_excerpt:
            return paper
        return paper.model_copy(update={"raw_payload": {**paper.raw_payload, "full_text_excerpt": full_text_excerpt}})

    def _screen_paper_with_passes(self, paper: PaperMetadata) -> tuple[ScreeningResult, dict[str, Any]]:
        """Apply all configured screening passes to one paper and keep pass-level metadata."""

        passes: dict[str, dict[str, Any]] = {}
        final_result: ScreeningResult | None = None
        final_pass_name = ""
        for analysis_pass in self.config.resolved_analysis_passes:
            self._check_stop()
            if (
                final_result is not None
                and analysis_pass.min_input_score is not None
                and (final_result.relevance_score or 0.0) < analysis_pass.min_input_score
            ):
                self._log_verbose(
                    "Skipping pass '%s' for '%s' because the previous score %.2f is below %.2f.",
                    analysis_pass.name,
                    paper.title,
                    final_result.relevance_score or 0.0,
                    analysis_pass.min_input_score,
                )
                passes[analysis_pass.name] = {
                    "skipped": True,
                    "skip_reason": "below_min_input_score",
                    "llm_provider": analysis_pass.llm_provider,
                    "model_name": analysis_pass.model_name,
                    "threshold": analysis_pass.threshold,
                    "decision_mode": analysis_pass.decision_mode,
                    "min_input_score": analysis_pass.min_input_score,
                }
                self._emit_event(
                    "screening_result",
                    paper_title=paper.title,
                    pass_name=analysis_pass.name,
                    decision="skipped",
                    relevance_score=final_result.relevance_score,
                    provider=analysis_pass.llm_provider,
                )
                continue
            self._log_verbose(
                "Analyzing '%s' with pass '%s' using %s.",
                paper.title,
                analysis_pass.name,
                analysis_pass.llm_provider,
            )
            screener = self.pass_screeners.get(analysis_pass.name)
            if screener is None:
                screener = AIScreener(self._config_for_analysis_pass(analysis_pass))
            result = screener.screen(paper).model_copy(update={"screening_context_key": self.config.screening_context_key})
            passes[analysis_pass.name] = {
                **result.model_dump(mode="json"),
                "threshold": analysis_pass.threshold,
                "decision_mode": analysis_pass.decision_mode,
                "llm_provider": analysis_pass.llm_provider,
                "model_name": analysis_pass.model_name,
                "min_input_score": analysis_pass.min_input_score,
                "skipped": False,
            }
            if self.config.log_screening_decisions and self.config.verbosity in {"verbose", "ultra_verbose"}:
                LOGGER.info(
                    "Screened '%s' in pass '%s': decision=%s score=%.2f provider=%s",
                    paper.title,
                    analysis_pass.name,
                    result.decision,
                    result.relevance_score,
                    analysis_pass.llm_provider,
                )
            self._emit_event(
                "screening_result",
                paper_title=paper.title,
                pass_name=analysis_pass.name,
                decision=result.decision,
                relevance_score=result.relevance_score,
                provider=analysis_pass.llm_provider,
            )
            final_result = result
            final_pass_name = analysis_pass.name

        if final_result is None:
            raise ValueError("At least one analysis pass must be configured in analyze mode")

        screening_details = {
            **final_result.model_dump(mode="json"),
            "screening_context_key": self.config.screening_context_key,
            "final_pass": final_pass_name,
            "passes": passes,
        }
        return final_result, screening_details

    def _paper_cache_key(self, paper: PaperMetadata) -> str:
        """Build a stable cache key from metadata plus optional full-text context."""

        fingerprint = stable_hash(
            "|".join(
                [
                    paper.identity_key,
                    paper.title,
                    paper.abstract,
                    paper.raw_payload.get("full_text_excerpt", ""),
                ]
            ),
            length=32,
        )
        return f"{paper.identity_key}|{fingerprint}"

    def _normalize_papers_for_current_context(self, papers: list[PaperMetadata]) -> list[PaperMetadata]:
        """Clear stale screening fields when they were computed under a different screening context."""

        normalized: list[PaperMetadata] = []
        for paper in papers:
            context_key = paper.screening_details.get("screening_context_key")
            if context_key == self.config.screening_context_key:
                normalized.append(paper)
                continue
            normalized.append(
                paper.model_copy(
                    update={
                        "relevance_score": None,
                        "relevance_explanation": None,
                        "inclusion_decision": None,
                        "extracted_passage": None,
                        "methodology_category": None,
                        "domain_category": None,
                        "screening_details": {},
                    }
                )
            )
        return normalized

    def _decision_counts(self, papers: list[PaperMetadata]) -> dict[str, int]:
        """Count include, maybe, exclude, and unreviewed labels for reporting."""

        counts = {"include": 0, "exclude": 0, "maybe": 0, "unreviewed": 0}
        for paper in papers:
            decision = paper.inclusion_decision or "unreviewed"
            counts[decision] = counts.get(decision, 0) + 1
        return counts

    def _discover_from_source(
        self,
        source_name: str,
        search_callable: Callable[[], list[PaperMetadata]],
    ) -> list[PaperMetadata]:
        """Run one discovery client and emit source-level progress events."""

        self._log_verbose("Querying %s.", source_name)
        self._emit_event("source_requested", source=source_name)
        source_started = time.perf_counter()
        records = search_callable()
        self._log_verbose("%s returned %s records in %.2f seconds.", source_name, len(records), time.perf_counter() - source_started)
        return records

    def _config_for_analysis_pass(self, analysis_pass: AnalysisPassConfig) -> ResearchConfig:
        """Create a per-pass config view with pass-specific model and threshold settings."""

        api_updates: dict[str, Any] = {}
        if analysis_pass.model_name:
            provider_model_field = {
                "openai_compatible": "openai_model",
                "gemini": "gemini_model",
                "ollama": "ollama_model",
                "huggingface_local": "huggingface_model",
            }.get(analysis_pass.llm_provider)
            if provider_model_field:
                api_updates[provider_model_field] = analysis_pass.model_name
        api_settings = (
            self.config.api_settings.model_copy(update=api_updates)
            if api_updates
            else self.config.api_settings
        )
        return self.config.model_copy(
            update={
                "llm_provider": analysis_pass.llm_provider,
                "relevance_threshold": analysis_pass.threshold,
                "decision_mode": analysis_pass.decision_mode,
                "maybe_threshold_margin": analysis_pass.maybe_threshold_margin,
                "api_settings": api_settings,
            }
        )

    def _summary_config(self) -> ResearchConfig:
        resolved_passes = self.config.resolved_analysis_passes
        if not resolved_passes:
            return self.config
        return self._config_for_analysis_pass(resolved_passes[-1])

    def _build_pass_screeners(self) -> dict[str, AIScreener]:
        """Instantiate one screener per configured analysis pass."""

        screeners: dict[str, AIScreener] = {}
        for analysis_pass in self.config.resolved_analysis_passes:
            screeners[analysis_pass.name] = AIScreener(self._config_for_analysis_pass(analysis_pass))
        return screeners

    def _summary_screener(self) -> AIScreener:
        """Return the screener responsible for final review-summary generation."""

        resolved_passes = self.config.resolved_analysis_passes
        if not resolved_passes:
            return AIScreener(self.config)
        return self.pass_screeners[resolved_passes[-1].name]

    def _requires_local_llm_serial_execution(self) -> bool:
        return self.config.topic_prefilter_enabled or any(
            analysis_pass.llm_provider == "huggingface_local"
            for analysis_pass in self.config.resolved_analysis_passes
        )

    def _screening_worker_count(self) -> int:
        """Reduce concurrency for local model inference that is not safe to parallelize heavily."""

        if self._requires_local_llm_serial_execution():
            return 1
        return self.config.effective_screening_workers

    def _paper_meets_pdf_download_threshold(self, paper: PaperMetadata) -> bool:
        if paper.relevance_score is None:
            return False
        return (paper.relevance_score >= self._final_threshold()) and paper.inclusion_decision != "exclude"

    def _final_threshold(self) -> float:
        resolved_passes = self.config.resolved_analysis_passes
        if resolved_passes:
            return resolved_passes[-1].threshold
        return self.config.relevance_threshold

    def _enrich_paper_with_pdf(self, paper: PaperMetadata) -> PaperMetadata:
        """Resolve PDF metadata and optional downloads for one paper without aborting the whole batch."""

        self._check_stop()
        download_now = self.config.download_pdfs and self.config.pdf_download_mode == "all"
        if paper.pdf_path or (paper.pdf_link and not download_now):
            return paper
        try:
            self._log_debug("Fetching PDF metadata for '%s'.", paper.title)
            return self.pdf_fetcher.fetch_for_paper(
                paper,
                download=download_now,
                target_dir=Path(self.config.papers_dir),
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("PDF enrichment failed for %s: %s", paper.title, exc)
            return paper

    def _download_one_relevant_pdf(self, paper: PaperMetadata) -> PaperMetadata:
        """Download the PDF for one retained paper while keeping per-paper failures non-fatal."""

        self._check_stop()
        try:
            return self.pdf_fetcher.fetch_for_paper(
                paper,
                download=True,
                target_dir=Path(self.config.relevant_pdfs_dir or self.config.papers_dir),
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Relevant PDF download failed for %s: %s", paper.title, exc)
            return paper

    def _process_pdf_batch_queue(
        self,
        papers: list[PaperMetadata],
        worker: Callable[[PaperMetadata], PaperMetadata],
        *,
        desc: str,
    ) -> list[PaperMetadata]:
        """Process PDF work in bounded batches so downloads do not burst all at once."""

        if not papers:
            return []
        batch_size = max(1, self.config.pdf_batch_size)
        if len(papers) <= batch_size:
            return self._map_papers_with_executor(papers, worker, desc=desc)

        processed: list[PaperMetadata] = []
        total_batches = (len(papers) + batch_size - 1) // batch_size
        for batch_index, batch_start in enumerate(range(0, len(papers), batch_size), start=1):
            self._check_stop()
            batch = papers[batch_start: batch_start + batch_size]
            batch_desc = f"{desc} batch {batch_index}/{total_batches}"
            self._log_verbose("%s queued %s papers.", batch_desc, len(batch))
            self._emit_event(
                "pdf_batch_started",
                stage=desc,
                batch_index=batch_index,
                total_batches=total_batches,
                batch_size=len(batch),
            )
            processed.extend(self._map_papers_with_executor(batch, worker, desc=batch_desc))
            self._emit_event(
                "pdf_batch_finished",
                stage=desc,
                batch_index=batch_index,
                total_batches=total_batches,
                batch_size=len(batch),
            )
        return processed

    def _map_papers_with_executor(
        self,
        papers: list[PaperMetadata],
        worker: Callable[[PaperMetadata], PaperMetadata],
        *,
        desc: str,
    ) -> list[PaperMetadata]:
        """Process a paper batch in parallel when useful while preserving the original order."""

        if not papers:
            return []
        worker_count = self._parallel_worker_count(len(papers))
        if worker_count == 1:
            return [
                worker(paper)
                for paper in tqdm(
                    papers,
                    desc=desc,
                    unit="paper",
                    disable=self.config.disable_progress_bars,
                )
            ]
        if self.config.enable_async_network_stages:
            return self._map_papers_async(papers, worker, desc=desc, worker_count=worker_count)

        self._log_verbose("%s is using %s worker threads.", desc, worker_count)
        ordered_results: list[PaperMetadata | None] = [None] * len(papers)
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            self._active_executors.append(executor)
            try:
                future_map = {
                    executor.submit(worker, paper): index
                    for index, paper in enumerate(papers)
                }
                for future in tqdm(
                    as_completed(future_map),
                    total=len(future_map),
                    desc=desc,
                    unit="paper",
                    disable=self.config.disable_progress_bars,
                ):
                    self._check_stop()
                    ordered_results[future_map[future]] = future.result()
            finally:
                if executor in self._active_executors:
                    self._active_executors.remove(executor)
        return [result if result is not None else paper for result, paper in zip(ordered_results, papers)]

    def _map_papers_async(
        self,
        papers: list[PaperMetadata],
        worker: Callable[[PaperMetadata], PaperMetadata],
        *,
        desc: str,
        worker_count: int,
    ) -> list[PaperMetadata]:
        """Run IO-heavy per-paper work through an asyncio coordination layer."""

        self._log_verbose("%s is using async orchestration with %s workers.", desc, worker_count)
        return asyncio.run(self._map_papers_async_impl(papers, worker, desc=desc, worker_count=worker_count))

    async def _map_papers_async_impl(
        self,
        papers: list[PaperMetadata],
        worker: Callable[[PaperMetadata], PaperMetadata],
        *,
        desc: str,
        worker_count: int,
    ) -> list[PaperMetadata]:
        """Preserve paper order while running synchronous workers through asyncio."""

        ordered_results: list[PaperMetadata | None] = [None] * len(papers)
        semaphore = asyncio.Semaphore(max(1, worker_count))

        async def run_worker(index: int, paper: PaperMetadata) -> tuple[int, PaperMetadata]:
            async with semaphore:
                return index, await asyncio.to_thread(worker, paper)

        tasks = [asyncio.create_task(run_worker(index, paper)) for index, paper in enumerate(papers)]
        for completed in asyncio.as_completed(tasks):
            self._check_stop()
            index, result = await completed
            ordered_results[index] = result
        return [result if result is not None else paper for result, paper in zip(ordered_results, papers)]

    def _parallel_worker_count(self, item_count: int) -> int:
        """Return a bounded thread count for IO-bound per-paper stages."""

        if item_count <= 1:
            return 1
        return max(1, min(self.config.effective_io_workers, item_count))

    def _log_verbose(self, message: str, *args: Any) -> None:
        if self.config.verbosity in {"verbose", "ultra_verbose"}:
            LOGGER.info(message, *args)

    def _log_debug(self, message: str, *args: Any) -> None:
        if self.config.verbosity == "ultra_verbose":
            LOGGER.debug(message, *args)

    def _log_trace(self, message: str, *args: Any) -> None:
        """Emit one TRACE-level message only in ultra-verbose runs."""

        if self.config.verbosity == "ultra_verbose":
            LOGGER.log(5, message, *args)

    def _build_manual_import_clients(self) -> list[ManualImportClient]:
        clients: list[ManualImportClient] = []
        import_specs = [
            (self.config.manual_source_path, "manual_import"),
            (self.config.google_scholar_import_path, "google_scholar_import"),
            (self.config.researchgate_import_path, "researchgate_import"),
        ]
        for path, source_name in import_specs:
            if path:
                clients.append(ManualImportClient(self.config, path=path, source_name=source_name))
        return clients

    def _apply_discovery_limits(self, papers: list[PaperMetadata]) -> list[PaperMetadata]:
        """Trim the current paper set to the configured global discovery cap, if any."""

        if self.config.max_discovered_records is None:
            return papers
        return papers[: self.config.max_discovered_records]

    def _below_minimum_discovery_threshold(self, discovered_count: int) -> bool:
        """Check whether discovery found enough unique records to justify screening."""

        return self.config.min_discovered_records > 0 and discovered_count < self.config.min_discovered_records

    def _emit_event(self, event_type: str, **payload: Any) -> None:
        """Send a structured event to the UI or any other external observer."""

        if self.event_sink is None:
            return
        self.event_sink({"event_type": event_type, **payload})

    def _emit_report_artifacts(self, report_paths: dict[str, str]) -> None:
        """Emit one event per generated artifact so the UI can refresh its result tabs."""

        for label, path in report_paths.items():
            self._emit_event("artifact_written", label=label, path=path)

    def _check_stop(self) -> None:
        """Raise a controlled stop exception when the user has requested cancellation."""

        if self.stop_event.is_set():
            raise PipelineStoppedError("Stopped by user request")



