"""Deduplication helpers for merging overlapping records across discovery sources."""

from __future__ import annotations

from typing import Iterable

from models.paper import PaperMetadata
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def deduplicate_papers(
    papers: Iterable[PaperMetadata],
    *,
    title_similarity_threshold: float = 0.92,
) -> list[PaperMetadata]:
    """Merge papers that share a DOI or exceed the configured title similarity threshold."""

    unique_by_identity: dict[str, PaperMetadata] = {}
    title_only: list[PaperMetadata] = []

    for paper in papers:
        if paper.doi:
            if paper.identity_key in unique_by_identity:
                unique_by_identity[paper.identity_key] = unique_by_identity[paper.identity_key].merge_with(paper)
            else:
                unique_by_identity[paper.identity_key] = paper
            continue
        title_only.append(paper)

    if not title_only:
        return list(unique_by_identity.values())

    texts = [paper.normalized_title for paper in title_only]
    # Character n-grams work reasonably well here because titles are short and noisy across sources.
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5))
    matrix = vectorizer.fit_transform(texts)
    similarities = cosine_similarity(matrix)

    consumed: set[int] = set()
    for index, paper in enumerate(title_only):
        if index in consumed:
            continue
        merged = paper
        consumed.add(index)
        for candidate_index in range(index + 1, len(title_only)):
            if similarities[index, candidate_index] >= title_similarity_threshold:
                merged = merged.merge_with(title_only[candidate_index])
                consumed.add(candidate_index)
        unique_by_identity[merged.identity_key] = (
            unique_by_identity[merged.identity_key].merge_with(merged)
            if merged.identity_key in unique_by_identity
            else merged
        )

    return list(unique_by_identity.values())
