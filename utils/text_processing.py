"""Shared text normalization, query parsing, hashing, and lightweight NLP helpers."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Iterable, Iterator, Sequence

WHITESPACE_RE = re.compile(r"\s+")
TAG_RE = re.compile(r"<[^>]+>")
NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
TERM_SEPARATOR_RE = re.compile(r"[;,\n\r]+")
STOPWORDS = {
    "about",
    "after",
    "also",
    "among",
    "between",
    "from",
    "into",
    "over",
    "that",
    "their",
    "there",
    "these",
    "this",
    "through",
    "towards",
    "using",
    "with",
}
KEYPHRASE_STOPWORDS = STOPWORDS | {
    "analysis",
    "approach",
    "article",
    "based",
    "findings",
    "paper",
    "review",
    "results",
    "study",
    "system",
}


def canonical_doi(value: str) -> str:
    """Normalize DOI strings by removing common URL and prefix wrappers."""

    cleaned = value.strip().lower()
    cleaned = cleaned.replace("https://doi.org/", "").replace("http://doi.org/", "")
    cleaned = cleaned.replace("doi:", "").strip()
    return cleaned


def normalize_text(value: str) -> str:
    """Collapse repeated whitespace while preserving the original casing."""

    return WHITESPACE_RE.sub(" ", str(value or "")).strip()


def normalize_title(value: str) -> str:
    """Normalize text aggressively for matching and deduplication purposes."""

    cleaned = normalize_text(value).lower()
    return NON_ALNUM_RE.sub(" ", cleaned).strip()


def strip_markup(value: str) -> str:
    """Remove lightweight HTML or XML tags from metadata fields."""

    text = TAG_RE.sub(" ", str(value or ""))
    return normalize_text(text)


def reconstruct_inverted_abstract(index: dict[str, list[int]] | None) -> str:
    """Reconstruct an OpenAlex-style inverted abstract index into plain text."""

    if not index:
        return ""
    size = 1 + max(position for positions in index.values() for position in positions)
    tokens = [""] * size
    for token, positions in index.items():
        for position in positions:
            tokens[position] = token
    return normalize_text(" ".join(tokens))


def build_query(topic: str, keywords: Sequence[str], boolean_expression: str | None = None) -> str:
    """Assemble a human-readable source query from topic, keywords, and boolean hints."""

    cleaned_keywords = [keyword.strip() for keyword in keywords if keyword.strip()]
    if boolean_expression:
        operator = boolean_expression.strip().upper()
        if operator in {"AND", "OR", "NOT"} and cleaned_keywords:
            return f"{topic.strip()} {operator} " + f" {operator} ".join(cleaned_keywords)
        return normalize_text(f"{topic} {boolean_expression} {' '.join(cleaned_keywords)}")
    if cleaned_keywords:
        return f"{topic.strip()} AND " + " AND ".join(cleaned_keywords)
    return topic.strip()


def parse_search_terms(value: str | Sequence[str] | None) -> list[str]:
    """Normalize keyword-like input from strings, text areas, or pre-split sequences.

    Supported separators for string input are commas, semicolons, and newlines.
    Whitespace-only items are dropped and non-string sequence members are coerced.
    """

    if value is None:
        return []
    if isinstance(value, str):
        normalized = value.replace("\r\n", "\n").replace("\r", "\n")
        parts = TERM_SEPARATOR_RE.split(normalized)
        return [item.strip() for item in parts if item and item.strip()]
    return [str(item).strip() for item in value if str(item).strip()]


def extract_keyphrases(text: str, limit: int = 12) -> list[str]:
    """Extract lightweight unigram, bigram, and trigram keyphrases from free text."""

    tokens = [
        token
        for token in normalize_title(text).split()
        if len(token) >= 4 and token not in KEYPHRASE_STOPWORDS
    ]
    if not tokens:
        return []
    scores: dict[str, float] = {}
    for ngram_size in (3, 2, 1):
        for index in range(len(tokens) - ngram_size + 1):
            phrase_tokens = tokens[index : index + ngram_size]
            if len(set(phrase_tokens)) == 1 and ngram_size > 1:
                continue
            phrase = " ".join(phrase_tokens)
            scores[phrase] = scores.get(phrase, 0.0) + 1.0 + ((ngram_size - 1) * 0.35)
    ranked = sorted(scores.items(), key=lambda item: (item[1], len(item[0])), reverse=True)
    selected: list[str] = []
    for phrase, _score in ranked:
        if any(phrase in existing or existing in phrase for existing in selected):
            continue
        selected.append(phrase)
        if len(selected) >= limit:
            break
    return selected


def keyword_overlap_score(text: str, keywords: Sequence[str]) -> float:
    """Return the fraction of review keywords that appear in the provided text."""

    normalized = normalize_title(text)
    if not normalized or not keywords:
        return 0.0
    hits = 0
    valid_keywords = [keyword for keyword in keywords if keyword.strip()]
    for keyword in valid_keywords:
        normalized_keyword = normalize_title(keyword)
        if normalized_keyword and normalized_keyword in normalized:
            hits += 1
    return hits / max(len(valid_keywords), 1)


def extract_salient_sentence(text: str, keywords: Sequence[str]) -> str:
    """Select the sentence with the strongest keyword overlap for reporting."""

    sentences = re.split(r"(?<=[.!?])\s+", normalize_text(text))
    if not sentences:
        return ""
    ranked = sorted(
        sentences,
        key=lambda sentence: (
            keyword_overlap_score(sentence, keywords),
            len(sentence),
        ),
        reverse=True,
    )
    return ranked[0][:600]


def safe_year(value: object) -> int | None:
    """Parse a plausible publication year or return `None` for noisy input."""

    if value is None or value == "":
        return None
    try:
        year = int(str(value))
    except (TypeError, ValueError):
        return None
    if 1800 <= year <= 2100:
        return year
    return None


def chunked(values: Sequence[str], size: int) -> Iterator[list[str]]:
    """Yield fixed-size chunks from a sequence."""

    for index in range(0, len(values), size):
        yield list(values[index: index + size])


def make_query_key(topic: str, keywords: Sequence[str], year_start: int, year_end: int) -> str:
    """Create a stable short identifier for one discovery query context."""

    payload = f"{normalize_title(topic)}|{','.join(sorted(normalize_title(item) for item in keywords))}|{year_start}|{year_end}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def stable_hash(value: str, length: int = 16) -> str:
    """Hash normalized text deterministically and truncate it to the requested length."""

    return hashlib.sha1(normalize_text(value).encode("utf-8")).hexdigest()[:length]


def slugify_filename(value: str, max_length: int = 100) -> str:
    """Convert arbitrary text into a filesystem-friendly filename stem."""

    normalized = NON_ALNUM_RE.sub("-", normalize_title(value)).strip("-")
    if not normalized:
        normalized = "paper"
    return normalized[:max_length]


def ensure_parent_directory(path: Path) -> None:
    """Create the parent directory for a target file path if it does not exist yet."""

    path.parent.mkdir(parents=True, exist_ok=True)


def top_terms(texts: Iterable[str], limit: int = 10) -> list[str]:
    """Return the most frequent non-trivial normalized terms across multiple texts."""

    counts: dict[str, int] = {}
    for text in texts:
        for token in normalize_title(text).split():
            if len(token) < 4 or token in STOPWORDS:
                continue
            counts[token] = counts.get(token, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    return [token for token, _ in ranked[:limit]]
