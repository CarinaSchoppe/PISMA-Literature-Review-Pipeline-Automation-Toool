"""Offline fixture-based discovery client used for deterministic tests and demos."""

from __future__ import annotations

import json
from pathlib import Path

from config import ResearchConfig
from models.paper import PaperMetadata


class FixtureDiscoveryClient:
    """Serve discovery and citation results from a local JSON fixture file."""

    def __init__(self, config: ResearchConfig) -> None:
        self.config = config
        if not config.fixture_data_path:
            raise ValueError("fixture_data_path must be provided for fixture discovery")
        self.fixture_path = Path(config.fixture_data_path)
        self._papers = self._load_fixture()

    def search(self) -> list[PaperMetadata]:
        """Return all fixture papers as discovery results for the active query."""

        return [paper.model_copy(update={"query_key": self.config.query_key}) for paper in self._papers]

    def fetch_references(self, paper: PaperMetadata, limit: int = 20) -> list[PaperMetadata]:
        """Resolve reference links within the fixture dataset."""

        matched = self._match(paper)
        if not matched:
            return []
        return self._resolve_links(matched.references[:limit])

    def fetch_citations(self, paper: PaperMetadata, limit: int = 20) -> list[PaperMetadata]:
        """Resolve citation links within the fixture dataset."""

        matched = self._match(paper)
        if not matched:
            return []
        return self._resolve_links(matched.citations[:limit])

    def _load_fixture(self) -> list[PaperMetadata]:
        """Load fixture records from disk and validate them as paper models."""

        payload = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("Fixture data must be a JSON array of paper objects")
        return [PaperMetadata(**item) for item in payload]

    def _match(self, paper: PaperMetadata) -> PaperMetadata | None:
        """Find the fixture record corresponding to the provided paper."""

        for candidate in self._papers:
            if paper.doi and candidate.doi == paper.doi:
                return candidate
            if candidate.normalized_title == paper.normalized_title:
                return candidate
        return None

    def _resolve_links(self, identifiers: list[str]) -> list[PaperMetadata]:
        """Resolve citation labels or identifiers back to fixture records."""

        matched: list[PaperMetadata] = []
        for identifier in identifiers:
            for candidate in self._papers:
                if candidate.doi == identifier or candidate.title == identifier or candidate.identity_key == identifier:
                    matched.append(candidate.model_copy(update={"query_key": self.config.query_key}))
                    break
        return matched
