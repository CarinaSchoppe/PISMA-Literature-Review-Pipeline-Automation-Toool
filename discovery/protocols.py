"""Typing protocols for pluggable discovery and citation backends."""

from __future__ import annotations

from typing import Protocol

from models.paper import PaperMetadata


class DiscoveryClientProtocol(Protocol):
    """Protocol for clients that can discover papers from an external source."""

    def search(self) -> list[PaperMetadata]:
        """Return normalized papers discovered from the provider."""

        ...


class CitationProviderProtocol(Protocol):
    """Protocol for clients that can expand references and citations around a paper."""

    def fetch_references(self, paper: PaperMetadata, limit: int = 20) -> list[PaperMetadata]:
        """Return papers referenced by the given paper."""

        ...

    def fetch_citations(self, paper: PaperMetadata, limit: int = 20) -> list[PaperMetadata]:
        """Return papers that cite the given paper."""

        ...
