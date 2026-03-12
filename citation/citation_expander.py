"""Backward and forward citation expansion over the seeded paper set."""

from __future__ import annotations

from tqdm import tqdm

from config import ResearchConfig
from database import DatabaseManager
from discovery.protocols import CitationProviderProtocol
from models.paper import PaperMetadata
from utils.deduplication import deduplicate_papers


class CitationExpander:
    """Expand the current review set through reference and citation lookups."""

    def __init__(
            self,
            config: ResearchConfig,
            database: DatabaseManager,
            citation_provider: CitationProviderProtocol,
    ) -> None:
        self.config = config
        self.database = database
        self.citation_provider = citation_provider

    def expand(self, papers: list[PaperMetadata]) -> list[PaperMetadata]:
        """Return newly discovered papers found through backward and forward snowballing."""

        if not self.config.citation_snowballing_enabled:
            return []

        seed_limit = min(len(papers), max(5, self.config.max_papers_to_analyze // 2))
        ranked = sorted(papers, key=lambda paper: (paper.citation_count, paper.year or 0), reverse=True)
        seeds = ranked[:seed_limit]

        discovered: list[PaperMetadata] = []
        for seed in tqdm(
                seeds,
                desc="Citation expansion",
                unit="paper",
                disable=self.config.disable_progress_bars,
        ):
            backward = self.citation_provider.fetch_references(seed, limit=10)
            forward = self.citation_provider.fetch_citations(seed, limit=10)
            references = [paper.citation_label for paper in backward]
            citations = [paper.citation_label for paper in forward]
            if seed.database_id is not None:
                self.database.update_citations(seed.database_id, references, citations)
            for paper in [*backward, *forward]:
                discovered.append(paper.model_copy(update={"query_key": self.config.query_key}))

        return deduplicate_papers(
            discovered,
            title_similarity_threshold=self.config.title_similarity_threshold,
        )
