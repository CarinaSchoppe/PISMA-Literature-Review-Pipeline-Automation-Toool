"""Import client for CSV or JSON metadata exports from external literature tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from config import ResearchConfig
from models.paper import PaperMetadata


class ManualImportClient:
    """Load manually exported literature records into the shared paper model."""

    def __init__(
            self,
            config: ResearchConfig,
            path: Path | None = None,
            source_name: str = "manual_import",
    ) -> None:
        self.config = config
        source_path = path or config.manual_source_path
        resolved_path = Path(source_path) if source_path is not None else None
        if resolved_path is None:
            raise ValueError("A path must be set for manual import")
        self.path = resolved_path
        self.source_name = source_name

    def search(self) -> list[PaperMetadata]:
        """Read the configured import file and convert each row into a paper record."""

        rows = self._load_rows()
        papers: list[PaperMetadata] = []
        for row in rows:
            title = str(row.get("title", "")).strip()
            if not title:
                continue
            authors = row.get("authors", [])
            if isinstance(authors, str):
                authors = [part.strip() for part in authors.replace("|", ";").split(";") if part.strip()]
            papers.append(
                PaperMetadata(
                    query_key=self.config.query_key,
                    title=title,
                    authors=authors,
                    abstract=str(row.get("abstract", "") or ""),
                    year=int(row["year"]) if str(row.get("year", "")).isdigit() else None,
                    venue=str(row.get("venue", "") or row.get("journal", "") or ""),
                    doi=row.get("doi"),
                    source=str(row.get("source", self.source_name)),
                    citation_count=int(row.get("citation_count", 0) or 0),
                    reference_count=int(row.get("reference_count", 0) or 0),
                    pdf_link=row.get("pdf_link"),
                    open_access=self._to_bool(row.get("open_access", False)),
                    raw_payload=dict(row),
                )
            )
        return papers

    def _load_rows(self) -> list[dict[str, Any]]:
        """Load CSV or JSON rows from the configured manual import file."""

        if self.path.suffix.lower() == ".json":
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                return [dict(item) for item in payload]
            raise ValueError("Manual JSON import must be a list of objects")
        dataframe = pd.read_csv(self.path)
        return dataframe.to_dict(orient="records")

    def _to_bool(self, value: Any) -> bool:
        """Normalize permissive truthy values commonly found in export files."""

        if isinstance(value, bool):
            return value
        if value is None:
            return False
        normalized = str(value).strip().lower()
        return normalized in {"true", "1", "yes", "y"}
