"""Local semantic topic prefilter based on lightweight Hugging Face embedding models."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from config import ResearchConfig
from models.paper import PaperMetadata

LOGGER = logging.getLogger(__name__)


@dataclass
class TopicMatchResult:
    """Structured semantic topic-match result used before deeper screening."""

    score: float
    threshold: float
    model_name: str
    enabled: bool
    should_exclude: bool
    explanation: str


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

    def __init__(self, config: ResearchConfig) -> None:
        super().__init__(config)
        self.threshold = config.topic_prefilter_threshold
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
            self._tokenizer = auto_tokenizer.from_pretrained(
                self.model_name,
                cache_dir=config.api_settings.huggingface_cache_dir,
                trust_remote_code=config.api_settings.huggingface_trust_remote_code,
            )
            self._model = auto_model.from_pretrained(
                self.model_name,
                cache_dir=config.api_settings.huggingface_cache_dir,
                trust_remote_code=config.api_settings.huggingface_trust_remote_code,
            )
            self._model.to(self._device)
            self._model.eval()
            self.enabled = True
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Could not initialize local topic prefilter model '%s': %s", self.model_name, exc)

    def score_paper(self, paper: PaperMetadata) -> TopicMatchResult | None:
        """Compare the review brief to one paper and return a semantic topic-match score."""

        if not self.enabled or self._tokenizer is None or self._model is None or self._torch is None:
            return None
        paper_text = self._build_paper_text(paper)
        if not paper_text:
            return None
        try:
            review_embedding, paper_embedding = self._embed_texts([self._review_text, paper_text])
            cosine_similarity = float((review_embedding * paper_embedding).sum().item())
            score = max(0.0, min(100.0, cosine_similarity * 100.0))
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Local topic prefiltering failed for '%s': %s", paper.title, exc)
            return None

        should_exclude = score < self.threshold
        explanation = (
            f"Local semantic topic prefilter using {self.model_name} scored this paper at {score:.1f}/100 "
            f"against the review brief. The configured threshold is {self.threshold:.1f}. "
            f"This paper {'failed' if should_exclude else 'passed'} the topic gate."
        )
        return TopicMatchResult(
            score=round(score, 2),
            threshold=self.threshold,
            model_name=self.model_name,
            enabled=True,
            should_exclude=should_exclude,
            explanation=explanation,
        )

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

    def _build_paper_text(self, paper: PaperMetadata) -> str:
        """Select the paper text window used for semantic topic comparison."""

        parts = [paper.title]
        if self.config.topic_prefilter_text_mode != "title_only":
            parts.append(paper.abstract)
        if self.config.topic_prefilter_text_mode == "title_abstract_full_text":
            parts.append(str(paper.raw_payload.get("full_text_excerpt", "") or ""))
        return " ".join(part.strip() for part in parts if part and part.strip())[: self.config.topic_prefilter_max_chars]

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
