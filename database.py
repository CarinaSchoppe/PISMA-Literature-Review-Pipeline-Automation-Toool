"""SQLite persistence layer for papers, cached screening runs, and incremental resume support."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from models.paper import PaperMetadata, ScreeningResult
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from utils.text_processing import canonical_doi


class Base(DeclarativeBase):
    """Shared SQLAlchemy declarative base for the local SQLite schema."""

    pass


class PaperRecord(Base):
    """ORM mapping for normalized paper metadata and screening outcomes."""

    __tablename__ = "papers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    query_key: Mapped[str] = mapped_column(String(32), index=True)
    normalized_title: Mapped[str] = mapped_column(String(512), index=True)
    title: Mapped[str] = mapped_column(Text)
    authors_json: Mapped[str] = mapped_column(Text, default="[]")
    abstract: Mapped[str] = mapped_column(Text, default="")
    year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    venue: Mapped[str] = mapped_column(Text, default="")
    doi: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    source: Mapped[str] = mapped_column(Text, default="")
    citation_count: Mapped[int] = mapped_column(Integer, default=0)
    reference_count: Mapped[int] = mapped_column(Integer, default=0)
    pdf_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    open_access: Mapped[bool] = mapped_column(Boolean, default=False)
    relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    relevance_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    inclusion_decision: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    references_json: Mapped[str] = mapped_column(Text, default="[]")
    citations_json: Mapped[str] = mapped_column(Text, default="[]")
    extracted_passage: Mapped[str | None] = mapped_column(Text, nullable=True)
    methodology_category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    domain_category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    external_ids_json: Mapped[str] = mapped_column(Text, default="{}")
    raw_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    screening_details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ScreeningCacheRecord(Base):
    """ORM mapping for reusable screening results keyed by paper fingerprint and context."""

    __tablename__ = "screening_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    screening_context_key: Mapped[str] = mapped_column(String(64), index=True)
    paper_cache_key: Mapped[str] = mapped_column(String(128), index=True)
    doi: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    normalized_title: Mapped[str] = mapped_column(String(512), index=True)
    title: Mapped[str] = mapped_column(Text)
    venue: Mapped[str] = mapped_column(Text, default="")
    year: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    decision: Mapped[str] = mapped_column(String(32), index=True)
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0)
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class DatabaseManager:
    """High-level repository for storing, updating, and reusing pipeline artifacts."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)
        self.engine = create_engine(f"sqlite:///{self.database_path}", future=True)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False, class_=Session)

    def initialize(self) -> None:
        """Create the schema and apply lightweight forward-only compatibility migrations."""

        Base.metadata.create_all(self.engine)
        self._ensure_schema()

    def close(self) -> None:
        """Dispose of the SQLAlchemy engine and close all pooled connections."""

        self.engine.dispose()

    def upsert_papers(self, papers: Iterable[PaperMetadata], query_key: str) -> list[PaperMetadata]:
        """Insert new papers or merge them into existing rows for the active query."""

        stored: list[PaperMetadata] = []
        with self.SessionLocal() as session:
            for paper in papers:
                existing = self._find_existing(session, query_key, paper)
                if existing is None:
                    record = self._create_record(paper, query_key)
                    session.add(record)
                    session.flush()
                    stored.append(self._record_to_model(record))
                else:
                    self._merge_record(existing, paper)
                    session.flush()
                    stored.append(self._record_to_model(existing))
            session.commit()
        return stored

    def get_papers_for_query(self, query_key: str) -> list[PaperMetadata]:
        """Load all papers associated with one query key from the database."""

        with self.SessionLocal() as session:
            stmt = select(PaperRecord).where(PaperRecord.query_key == query_key)
            return [self._record_to_model(record) for record in session.scalars(stmt).all()]

    def get_papers_for_analysis(
        self,
        query_key: str,
        limit: int,
        resume_mode: bool = True,
        screening_context_key: str | None = None,
    ) -> list[PaperMetadata]:
        """Return the highest-priority papers that still require screening work."""

        with self.SessionLocal() as session:
            stmt = select(PaperRecord).where(PaperRecord.query_key == query_key)
            stmt = stmt.order_by(PaperRecord.citation_count.desc(), PaperRecord.year.desc().nullslast()).limit(limit)
            records = session.scalars(stmt).all()
            models = [self._record_to_model(record) for record in records]
            if not resume_mode:
                return models
            filtered: list[PaperMetadata] = []
            for paper in models:
                context_matches = (
                    paper.screening_details.get("screening_context_key") == screening_context_key
                    if screening_context_key
                    else bool(paper.inclusion_decision)
                )
                if paper.relevance_score is None or not paper.inclusion_decision or not context_matches:
                    filtered.append(paper)
            return filtered

    def update_screening_result(
        self,
        database_id: int,
        result: ScreeningResult,
        screening_details: dict[str, Any] | None = None,
    ) -> None:
        """Persist the final screening result for one paper row."""

        with self.SessionLocal() as session:
            record = session.get(PaperRecord, database_id)
            if record is None:
                return
            record.relevance_score = float(result.relevance_score)
            record.relevance_explanation = result.explanation
            record.extracted_passage = result.extracted_passage
            record.methodology_category = result.methodology_category
            record.domain_category = result.domain_category
            record.inclusion_decision = result.decision
            payload = screening_details or result.model_dump(mode="json")
            record.screening_details_json = json.dumps(payload)
            session.commit()

    def get_cached_screening_entry(
        self,
        paper_cache_key: str,
        screening_context_key: str,
    ) -> tuple[ScreeningResult, dict[str, Any]] | None:
        """Load a cached screening payload for a paper fingerprint and context, if available."""

        with self.SessionLocal() as session:
            stmt = (
                select(ScreeningCacheRecord)
                .where(ScreeningCacheRecord.paper_cache_key == paper_cache_key)
                .where(ScreeningCacheRecord.screening_context_key == screening_context_key)
                .order_by(ScreeningCacheRecord.updated_at.desc())
                .limit(1)
            )
            record = session.scalars(stmt).first()
            if record is None:
                return None
            payload = json.loads(record.result_json or "{}")
            if "passes" in payload:
                result_payload = payload.get("final_result", {})
                return ScreeningResult(**result_payload), payload
            return ScreeningResult(**payload), payload

    def get_cached_screening_result(self, paper_cache_key: str, screening_context_key: str) -> ScreeningResult | None:
        """Return only the cached screening result object without the full metadata payload."""

        cached = self.get_cached_screening_entry(paper_cache_key, screening_context_key)
        if cached is None:
            return None
        return cached[0]

    def cache_screening_result(
        self,
        *,
        paper: PaperMetadata,
        paper_cache_key: str,
        screening_context_key: str,
        result: ScreeningResult,
        screening_details: dict[str, Any] | None = None,
    ) -> None:
        """Store or refresh a reusable screening cache entry."""

        with self.SessionLocal() as session:
            stmt = (
                select(ScreeningCacheRecord)
                .where(ScreeningCacheRecord.paper_cache_key == paper_cache_key)
                .where(ScreeningCacheRecord.screening_context_key == screening_context_key)
            )
            existing = session.scalars(stmt).first()
            payload = json.dumps(screening_details or result.model_dump(mode="json"))
            if existing is None:
                session.add(
                    ScreeningCacheRecord(
                        screening_context_key=screening_context_key,
                        paper_cache_key=paper_cache_key,
                        doi=paper.doi,
                        normalized_title=paper.normalized_title,
                        title=paper.title,
                        venue=paper.venue,
                        year=paper.year,
                        decision=result.decision,
                        relevance_score=float(result.relevance_score),
                        result_json=payload,
                    )
                )
            else:
                existing.decision = result.decision
                existing.relevance_score = float(result.relevance_score)
                existing.result_json = payload
            session.commit()

    def update_pdf_info(self, database_id: int, *, pdf_link: str | None, pdf_path: str | None, open_access: bool) -> None:
        """Persist resolved PDF metadata for a paper already stored in SQLite."""

        with self.SessionLocal() as session:
            record = session.get(PaperRecord, database_id)
            if record is None:
                return
            record.pdf_link = pdf_link or record.pdf_link
            record.pdf_path = pdf_path or record.pdf_path
            record.open_access = open_access or record.open_access
            session.commit()

    def update_citations(self, database_id: int, references: list[str], citations: list[str]) -> None:
        """Persist reference and citation labels collected during snowballing."""

        with self.SessionLocal() as session:
            record = session.get(PaperRecord, database_id)
            if record is None:
                return
            record.references_json = json.dumps(references)
            record.citations_json = json.dumps(citations)
            record.reference_count = max(record.reference_count, len(references))
            record.citation_count = max(record.citation_count, len(citations), record.citation_count)
            session.commit()

    def count_papers(self, query_key: str) -> int:
        """Count all stored papers for one query key."""

        with self.SessionLocal() as session:
            stmt = select(PaperRecord).where(PaperRecord.query_key == query_key)
            return len(session.scalars(stmt).all())

    def get_decision_counts(self, query_key: str) -> dict[str, int]:
        """Summarize inclusion decisions for reporting and UI display."""

        papers = self.get_papers_for_query(query_key)
        counts = {"include": 0, "exclude": 0, "maybe": 0, "unreviewed": 0}
        for paper in papers:
            decision = paper.inclusion_decision or "unreviewed"
            counts[decision] = counts.get(decision, 0) + 1
        return counts

    def _find_existing(self, session: Session, query_key: str, paper: PaperMetadata) -> PaperRecord | None:
        """Find an existing row by DOI first and normalized title second."""

        if paper.doi:
            stmt = select(PaperRecord).where(
                PaperRecord.query_key == query_key,
                PaperRecord.doi == canonical_doi(paper.doi),
            )
            existing = session.scalars(stmt).first()
            if existing:
                return existing
        stmt = select(PaperRecord).where(
            PaperRecord.query_key == query_key,
            PaperRecord.normalized_title == paper.normalized_title,
        )
        return session.scalars(stmt).first()

    def _create_record(self, paper: PaperMetadata, query_key: str) -> PaperRecord:
        """Map a validated paper model into a new ORM record."""

        return PaperRecord(
            query_key=query_key,
            normalized_title=paper.normalized_title,
            title=paper.title,
            authors_json=json.dumps(paper.authors),
            abstract=paper.abstract,
            year=paper.year,
            venue=paper.venue,
            doi=paper.doi,
            source=paper.source,
            citation_count=paper.citation_count,
            reference_count=paper.reference_count,
            pdf_link=paper.pdf_link,
            pdf_path=paper.pdf_path,
            open_access=paper.open_access,
            relevance_score=paper.relevance_score,
            relevance_explanation=paper.relevance_explanation,
            inclusion_decision=paper.inclusion_decision,
            references_json=json.dumps(paper.references),
            citations_json=json.dumps(paper.citations),
            extracted_passage=paper.extracted_passage,
            methodology_category=paper.methodology_category,
            domain_category=paper.domain_category,
            external_ids_json=json.dumps(paper.external_ids),
            raw_payload_json=json.dumps(paper.raw_payload),
            screening_details_json=json.dumps(paper.screening_details),
        )

    def _merge_record(self, record: PaperRecord, paper: PaperMetadata) -> None:
        """Merge new metadata into an existing ORM row without losing earlier fields."""

        existing_model = self._record_to_model(record)
        merged = existing_model.merge_with(paper)
        record.normalized_title = merged.normalized_title
        record.title = merged.title
        record.authors_json = json.dumps(merged.authors)
        record.abstract = merged.abstract
        record.year = merged.year
        record.venue = merged.venue
        record.doi = merged.doi
        record.source = merged.source
        record.citation_count = merged.citation_count
        record.reference_count = merged.reference_count
        record.pdf_link = merged.pdf_link
        record.pdf_path = merged.pdf_path
        record.open_access = merged.open_access
        record.references_json = json.dumps(merged.references)
        record.citations_json = json.dumps(merged.citations)
        record.external_ids_json = json.dumps(merged.external_ids)
        record.raw_payload_json = json.dumps(merged.raw_payload)
        if merged.screening_details:
            record.screening_details_json = json.dumps(merged.screening_details)

    def _record_to_model(self, record: PaperRecord) -> PaperMetadata:
        """Convert an ORM row back into the pipeline's Pydantic model."""

        return PaperMetadata(
            database_id=record.id,
            query_key=record.query_key,
            title=record.title,
            authors=json.loads(record.authors_json or "[]"),
            abstract=record.abstract or "",
            year=record.year,
            venue=record.venue or "",
            doi=record.doi,
            source=record.source or "",
            citation_count=record.citation_count or 0,
            reference_count=record.reference_count or 0,
            pdf_link=record.pdf_link,
            pdf_path=record.pdf_path,
            open_access=bool(record.open_access),
            relevance_score=record.relevance_score,
            relevance_explanation=record.relevance_explanation,
            inclusion_decision=record.inclusion_decision,
            references=json.loads(record.references_json or "[]"),
            citations=json.loads(record.citations_json or "[]"),
            extracted_passage=record.extracted_passage,
            methodology_category=record.methodology_category,
            domain_category=record.domain_category,
            external_ids=json.loads(record.external_ids_json or "{}"),
            raw_payload=json.loads(record.raw_payload_json or "{}"),
            screening_details=json.loads(record.screening_details_json or "{}"),
        )

    def _ensure_schema(self) -> None:
        """Apply additive schema migrations for databases created by earlier project versions."""

        required_columns = {
            "papers": {
                "screening_details_json": "TEXT DEFAULT '{}'",
            },
        }
        with self.engine.begin() as connection:
            for table_name, columns in required_columns.items():
                # The project intentionally keeps migrations simple and append-only for local SQLite files.
                existing = {
                    row[1]
                    for row in connection.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
                }
                for column_name, definition in columns.items():
                    if column_name not in existing:
                        connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"))
