"""Local semantic topic prefilter based on lightweight Hugging Face embedding models."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, ClassVar, Literal

from config import ResearchConfig
from models.paper import PaperMetadata
from utils.text_processing import keyword_overlap_score, normalize_title

LOGGER = logging.getLogger(__name__)
TopicPrefilterLabel = Literal["HIGH_RELEVANCE", "REVIEW", "LOW_RELEVANCE"]


@dataclass
class TopicMatchResult:
    """Structured semantic topic-match result used before deeper screening."""

    similarity: float
    score: float
    threshold: float
    review_threshold: float
    high_threshold: float
    model_name: str
    enabled: bool
    classification: TopicPrefilterLabel
    should_exclude: bool
    keyword_overlap_score: float
    matched_keywords: list[str] = field(default_factory=list)
    source_sections: list[str] = field(default_factory=list)
    explanation: str = ""


class BaseTopicMatcher:
    """Disabled matcher used when semantic topic gating is turned off."""

    enabled = False
    model_name = "disabled"

    def __init__(self, config: ResearchConfig) -> None:
        self.config = config

    def score_paper(self, paper: PaperMetadata) -> TopicMatchResult | None:
        """Return no topic-match result when the prefilter is disabled."""

        return None


def load_embedding_runtime() -> tuple[Any, Any, Any]:
    """Import the optional local embedding runtime on demand."""

    try:
        import torch
        from transformers import AutoModel, AutoTokenizer
    except ImportError as exc:  # pragma: no cover - exercised through unit mocks
        raise RuntimeError(
            "Local topic prefiltering requires 'transformers' and a supported backend such as 'torch'."
        ) from exc
    return torch, AutoTokenizer, AutoModel


class LocalTopicMatcher(BaseTopicMatcher):
    """Semantic topic matcher built on a small local sentence-embedding model."""

    enabled = False
    _MODEL_CACHE: ClassVar[dict[tuple[str, str | None, bool], tuple[Any, Any]]] = {}
    _CACHE_LOCK: ClassVar[Lock] = Lock()

    def __init__(self, config: ResearchConfig) -> None:
        super().__init__(config)
        self.review_threshold = config.topic_prefilter_review_threshold
        self.high_threshold = config.topic_prefilter_high_threshold
        self.threshold = self.review_threshold * 100.0
        self.model_name = config.api_settings.topic_prefilter_model
        self._torch: Any | None = None
        self._tokenizer: Any | None = None
        self._model: Any | None = None
        self._device: Any | None = None
        self._review_text = self._build_review_text()
        try:
            torch, auto_tokenizer, auto_model = load_embedding_runtime()
            self._torch = torch
            self._device = self._resolve_device(torch, config.api_settings.huggingface_device)
            self._tokenizer, self._model = self._load_cached_model(auto_tokenizer, auto_model)
            self._model.to(self._device)
            self._model.eval()
            self.enabled = True
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Could not initialize local topic prefilter model '%s': %s", self.model_name, exc)

    def score_paper(self, paper: PaperMetadata) -> TopicMatchResult | None:
        """Compare the review brief to one paper and return a semantic topic-match score."""

        if not self.enabled or self._tokenizer is None or self._model is None or self._torch is None:
            return None
        paper_text, sections = self._build_paper_text(paper)
        if not paper_text:
            return None
        try:
            review_embedding, paper_embedding = self._embed_texts([self._review_text, paper_text])
            cosine_similarity = float((review_embedding * paper_embedding).sum().item())
            similarity = max(0.0, min(1.0, cosine_similarity))
            score = similarity * 100.0
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Local topic prefiltering failed for '%s': %s", paper.title, exc)
            return None

        classification = self._classify_similarity(similarity)
        keyword_overlap = keyword_overlap_score(
            paper_text,
            [
                self.config.research_topic,
                self.config.research_question,
                self.config.review_objective,
                *self.config.search_keywords,
                *self.config.inclusion_criteria,
            ],
        )
        matched_keywords = self._matched_keywords(paper_text)
        should_exclude = self.config.topic_prefilter_filter_low_relevance and classification == "LOW_RELEVANCE"
        explanation = (
            f"Local semantic topic prefilter using {self.model_name} measured cosine similarity {similarity:.2f} "
            f"({score:.1f}/100) against the review brief. The configured REVIEW threshold is "
            f"{self.review_threshold:.2f} and the HIGH_RELEVANCE threshold is {self.high_threshold:.2f}. "
            f"The paper was classified as {classification}. Source text sections used: {', '.join(sections)}."
        )
        if matched_keywords:
            explanation += f" Matched review keywords: {', '.join(matched_keywords)}."
        if should_exclude:
            explanation += " Automatic filtering is enabled for LOW_RELEVANCE papers, so this paper will be excluded."
        return TopicMatchResult(
            similarity=round(similarity, 4),
            score=round(score, 2),
            threshold=round(self.threshold, 2),
            review_threshold=round(self.review_threshold, 4),
            high_threshold=round(self.high_threshold, 4),
            model_name=self.model_name,
            enabled=True,
            classification=classification,
            should_exclude=should_exclude,
            keyword_overlap_score=round(keyword_overlap, 4),
            matched_keywords=matched_keywords,
            source_sections=sections,
            explanation=explanation,
        )

    def _load_cached_model(self, auto_tokenizer: Any, auto_model: Any) -> tuple[Any, Any]:
        """Load or reuse one local embedding model instance for the current config."""

        cache_key = (
            self.model_name,
            self.config.api_settings.huggingface_cache_dir,
            self.config.api_settings.huggingface_trust_remote_code,
        )
        with self._CACHE_LOCK:
            if cache_key not in self._MODEL_CACHE:
                tokenizer = auto_tokenizer.from_pretrained(
                    self.model_name,
                    cache_dir=self.config.api_settings.huggingface_cache_dir,
                    trust_remote_code=self.config.api_settings.huggingface_trust_remote_code,
                )
                model = auto_model.from_pretrained(
                    self.model_name,
                    cache_dir=self.config.api_settings.huggingface_cache_dir,
                    trust_remote_code=self.config.api_settings.huggingface_trust_remote_code,
                )
                self._MODEL_CACHE[cache_key] = (tokenizer, model)
            return self._MODEL_CACHE[cache_key]

    def _build_review_text(self) -> str:
        """Assemble the semantic query text from the review brief fields."""

        parts = [
            self.config.research_topic,
            self.config.research_question,
            self.config.review_objective,
            " ".join(self.config.search_keywords),
            " ".join(self.config.inclusion_criteria),
        ]
        return " ".join(part.strip() for part in parts if part and part.strip())

    def _build_paper_text(self, paper: PaperMetadata) -> tuple[str, list[str]]:
        """Select the paper text window used for semantic topic comparison."""

        parts: list[str] = []
        sections: list[str] = []
        if paper.title:
            parts.append(paper.title)
            sections.append("title")
        if self.config.topic_prefilter_text_mode != "title_only" and paper.abstract:
            parts.append(paper.abstract)
            sections.append("abstract")
        keywords = self._paper_keywords(paper)
        if keywords:
            parts.append(" ".join(keywords))
            sections.append("keywords")
        if self.config.topic_prefilter_text_mode == "title_abstract_full_text":
            full_text_excerpt = str(paper.raw_payload.get("full_text_excerpt", "") or "")
            if full_text_excerpt.strip():
                parts.append(full_text_excerpt)
                sections.append("full_text_excerpt")
        combined = " ".join(part.strip() for part in parts if part and part.strip())
        return combined[: self.config.topic_prefilter_max_chars], sections

    def _paper_keywords(self, paper: PaperMetadata) -> list[str]:
        """Extract keyword-like metadata from the normalized paper payload."""

        for key in ("keywords", "keyword", "index_terms", "subject_terms"):
            raw_value = paper.raw_payload.get(key)
            if not raw_value:
                continue
            if isinstance(raw_value, str):
                return [item.strip() for item in raw_value.replace("|", ";").replace(",", ";").split(";") if item.strip()]
            if isinstance(raw_value, list):
                return [str(item).strip() for item in raw_value if str(item).strip()]
        return []

    def _matched_keywords(self, paper_text: str) -> list[str]:
        """Return review keywords that are visibly present in the paper text window."""

        normalized = normalize_title(paper_text)
        matched: list[str] = []
        for keyword in [*self.config.search_keywords, *self.config.inclusion_criteria]:
            normalized_keyword = normalize_title(keyword)
            if normalized_keyword and normalized_keyword in normalized and keyword not in matched:
                matched.append(keyword)
        return matched

    def _classify_similarity(self, similarity: float) -> TopicPrefilterLabel:
        """Map cosine similarity to the configured topic-prefilter classification label."""

        if similarity >= self.high_threshold:
            return "HIGH_RELEVANCE"
        if similarity >= self.review_threshold:
            return "REVIEW"
        return "LOW_RELEVANCE"

    def _resolve_device(self, torch: Any, configured_device: str) -> Any:
        """Resolve the configured runtime device into a concrete torch device."""

        normalized = str(configured_device or "auto").strip().lower()
        if normalized == "auto":
            return torch.device("cuda" if torch.cuda.is_available() else "cpu")
        if normalized == "cuda" and not torch.cuda.is_available():
            return torch.device("cpu")
        return torch.device(normalized)

    def _embed_texts(self, texts: list[str]) -> Any:
        """Encode and normalize text embeddings for cosine similarity scoring."""

        assert self._tokenizer is not None
        assert self._model is not None
        assert self._torch is not None

        encoded = self._tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=256,
            return_tensors="pt",
        )
        encoded = {key: value.to(self._device) for key, value in encoded.items()}
        with self._torch.no_grad():
            output = self._model(**encoded)
        token_embeddings = output.last_hidden_state
        attention_mask = encoded["attention_mask"].unsqueeze(-1).expand(token_embeddings.size()).float()
        pooled = (token_embeddings * attention_mask).sum(dim=1) / attention_mask.sum(dim=1).clamp(min=1e-9)
        return self._torch.nn.functional.normalize(pooled, p=2, dim=1)


def build_topic_matcher(config: ResearchConfig) -> BaseTopicMatcher:
    """Build the configured topic prefilter matcher, or a disabled no-op matcher."""

    if not config.topic_prefilter_enabled:
        return BaseTopicMatcher(config)
    return LocalTopicMatcher(config)
