"""Local semantic topic prefilter based on lightweight Hugging Face embedding models."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, ClassVar, Literal

from config import ResearchConfig, TopicKeywordRuleConfig
from models.paper import PaperMetadata
from utils.text_processing import extract_keyphrases, keyword_overlap_score, normalize_title

LOGGER = logging.getLogger(__name__)
TopicPrefilterLabel = Literal["HIGH_RELEVANCE", "REVIEW", "LOW_RELEVANCE"]
ResearchFitLabel = Literal["STRONG_FIT", "NEAR_FIT", "WEAK_FIT"]


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
    research_fit_label: ResearchFitLabel
    weighted_keyword_score: float
    min_keyword_matches: int
    matched_keyword_count: int
    keyword_rule_count: int
    matched_keywords: list[str] = field(default_factory=list)
    extracted_topics: list[str] = field(default_factory=list)
    keyword_match_details: list[dict[str, Any]] = field(default_factory=list)
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
        self._keyword_rules = self._build_keyword_rules()
        try:
            LOGGER.info(
                "Initializing local topic prefilter model '%s'. The first run can take longer while loading local model files.",
                self.model_name,
            )
            torch, auto_tokenizer, auto_model = load_embedding_runtime()
            self._torch = torch
            self._device = self._resolve_device(torch, config.api_settings.huggingface_device)
            self._tokenizer, self._model = self._load_cached_model(auto_tokenizer, auto_model)
            self._model.to(self._device)
            self._model.eval()
            self.enabled = True
            LOGGER.info("Local topic prefilter model '%s' is ready on device '%s'.", self.model_name, self._device)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Could not initialize local topic prefilter model '%s': %s", self.model_name, exc)

    def score_paper(self, paper: PaperMetadata) -> TopicMatchResult | None:
        """Compare the review brief to one paper and return a semantic topic-match score."""

        if not self.enabled or self._tokenizer is None or self._model is None or self._torch is None:
            return None
        paper_text, sections = self._build_paper_text(paper)
        if not paper_text:
            return None
        extracted_topics = self._extract_paper_topics(paper, paper_text)
        keyword_match_details = self._keyword_match_details(paper_text, extracted_topics)
        matched_keywords = [
            detail["keyword"]
            for detail in keyword_match_details
            if bool(detail.get("met_threshold"))
        ]
        matched_keyword_count = len(matched_keywords)
        weighted_keyword_score = self._weighted_keyword_score(keyword_match_details)
        research_fit_label = self._classify_research_fit(weighted_keyword_score, matched_keyword_count)
        try:
            LOGGER.debug("Local topic prefilter embedding generation started for '%s'.", paper.title)
            review_embedding, paper_embedding = self._embed_texts([self._review_text, paper_text])
            LOGGER.debug("Local topic prefilter embedding generation finished for '%s'.", paper.title)
            cosine_similarity = float((review_embedding * paper_embedding).sum().item())
            similarity = max(0.0, min(1.0, cosine_similarity))
            score = similarity * 100.0
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Local topic prefiltering failed for '%s': %s", paper.title, exc)
            return None

        classification = self._classify_similarity(similarity)
        LOGGER.debug(
            "Local topic prefilter similarity for '%s': similarity=%.4f classification=%s research_fit=%s.",
            paper.title,
            similarity,
            classification,
            research_fit_label,
        )
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
        should_exclude = self.config.topic_prefilter_filter_low_relevance and classification == "LOW_RELEVANCE"
        explanation_parts = [
            f"Local semantic topic prefilter using {self.model_name} measured cosine similarity {similarity:.2f} ({score:.1f}/100).",
            f"Semantic label: {classification}.",
            f"Research fit: {research_fit_label} with weighted keyword score {weighted_keyword_score:.1f}/100.",
            (
                f"Matched {matched_keyword_count} strongly aligned weighted keywords out of a required minimum of "
                f"{self.config.topic_prefilter_min_keyword_matches}."
            ),
            f"Review threshold {self.review_threshold:.2f}, HIGH threshold {self.high_threshold:.2f}.",
            (
                f"Strong-fit threshold {self.config.topic_prefilter_match_threshold:.1f}, "
                f"near-fit threshold {self.config.topic_prefilter_near_fit_threshold:.1f}."
            ),
            (
                f"Review focus used for matching: topic '{self.config.research_topic}', "
                f"question '{self.config.research_question}', objective '{self.config.review_objective}'."
            ),
            f"Source text sections used: {', '.join(sections)}.",
        ]
        if matched_keywords:
            explanation_parts.append(f"Strong keyword matches: {', '.join(matched_keywords)}.")
        if extracted_topics:
            explanation_parts.append(f"Extracted paper topics: {', '.join(extracted_topics[:8])}.")
        if should_exclude:
            explanation_parts.append("Automatic filtering is enabled for LOW_RELEVANCE papers, so this paper will be excluded.")
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
            research_fit_label=research_fit_label,
            weighted_keyword_score=round(weighted_keyword_score, 2),
            min_keyword_matches=self.config.topic_prefilter_min_keyword_matches,
            matched_keyword_count=matched_keyword_count,
            keyword_rule_count=len(keyword_match_details),
            matched_keywords=matched_keywords,
            extracted_topics=extracted_topics,
            keyword_match_details=keyword_match_details,
            source_sections=sections,
            explanation=" ".join(explanation_parts),
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
            f"Research topic: {self.config.research_topic}".strip(),
            f"Research question: {self.config.research_question}".strip(),
            f"Review objective: {self.config.review_objective}".strip(),
            f"Search keywords: {'; '.join(self.config.search_keywords)}".strip(),
            f"Inclusion criteria: {'; '.join(self.config.inclusion_criteria)}".strip(),
            f"Weighted research keywords: {'; '.join(self.config.topic_prefilter_weighted_keywords)}".strip(),
        ]
        weighted_focus = [
            self.config.research_topic,
            self.config.research_question,
            self.config.review_objective,
        ]
        return " ".join(part.strip() for part in [*parts, *weighted_focus] if part and part.strip())

    def _build_keyword_rules(self) -> list[TopicKeywordRuleConfig]:
        """Build weighted keyword rules from explicit entries or sensible defaults."""

        if self.config.resolved_topic_prefilter_keyword_rules:
            return list(self.config.resolved_topic_prefilter_keyword_rules)
        weighted_terms: list[tuple[str, float]] = []
        weighted_terms.extend(self._dedupe_weighted_terms([self.config.research_topic], 1.6))
        weighted_terms.extend(self._dedupe_weighted_terms([self.config.research_question], 1.35, weighted_terms))
        weighted_terms.extend(self._dedupe_weighted_terms([self.config.review_objective], 1.2, weighted_terms))
        weighted_terms.extend(self._dedupe_weighted_terms(self.config.search_keywords, 1.0, weighted_terms))
        weighted_terms.extend(self._dedupe_weighted_terms(self.config.inclusion_criteria, 0.9, weighted_terms))
        return [
            TopicKeywordRuleConfig(
                keyword=term,
                weight=weight,
                threshold=self.config.topic_prefilter_match_threshold,
            )
            for term, weight in weighted_terms
        ]

    def _dedupe_weighted_terms(
        self,
        terms: list[str],
        weight: float,
        existing: list[tuple[str, float]] | None = None,
    ) -> list[tuple[str, float]]:
        """Add unique normalized terms with a shared weight."""

        existing_terms = {normalize_title(term) for term, _value in existing or []}
        deduped: list[tuple[str, float]] = []
        for term in terms:
            normalized = normalize_title(term)
            if not normalized or normalized in existing_terms:
                continue
            deduped.append((term.strip(), weight))
            existing_terms.add(normalized)
        return deduped

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

    def _extract_paper_topics(self, paper: PaperMetadata, paper_text: str) -> list[str]:
        """Extract lightweight topics and merge them with any explicit metadata keywords."""

        explicit_keywords = self._paper_keywords(paper)
        combined_candidates = [*explicit_keywords, *extract_keyphrases(paper_text, limit=12)]
        seen: set[str] = set()
        topics: list[str] = []
        for candidate in combined_candidates:
            normalized = normalize_title(candidate)
            if not normalized or normalized in seen:
                continue
            topics.append(candidate.strip())
            seen.add(normalized)
            if len(topics) >= 12:
                break
        return topics

    def _keyword_match_details(self, paper_text: str, extracted_topics: list[str]) -> list[dict[str, Any]]:
        """Return per-keyword research-fit evidence for one paper."""

        normalized_text = normalize_title(paper_text)
        normalized_paper_tokens = set(normalized_text.split())
        normalized_topics = [(topic, normalize_title(topic)) for topic in extracted_topics]
        details: list[dict[str, Any]] = []
        for rule in self._keyword_rules:
            normalized_keyword = normalize_title(rule.keyword)
            keyword_tokens = [token for token in normalized_keyword.split() if len(token) >= 4]
            if not normalized_keyword or not keyword_tokens:
                continue
            best_score = 0.0
            best_topic = ""
            if normalized_keyword in normalized_text:
                best_score = 1.0
                best_topic = rule.keyword
            else:
                for topic, normalized_topic in normalized_topics:
                    topic_tokens = [token for token in normalized_topic.split() if len(token) >= 4]
                    if not topic_tokens:
                        continue
                    overlap = len(set(keyword_tokens) & set(topic_tokens))
                    candidate_score = overlap / max(len(set(keyword_tokens)), 1)
                    if candidate_score > best_score:
                        best_score = candidate_score
                        best_topic = topic
                if best_score < 1.0:
                    overlap = len(set(keyword_tokens) & normalized_paper_tokens)
                    token_score = overlap / max(len(set(keyword_tokens)), 1)
                    if token_score > best_score:
                        best_score = token_score
                        best_topic = "paper text"
            match_percent = round(best_score * 100.0, 2)
            threshold_delta = round(match_percent - rule.threshold, 2)
            met_threshold = threshold_delta >= 0.0
            status = "matched" if threshold_delta >= 0.0 else "near" if threshold_delta >= -5.0 else "missed"
            details.append(
                {
                    "keyword": rule.keyword,
                    "weight": round(rule.weight, 2),
                    "match_score": round(best_score, 4),
                    "match_percent": match_percent,
                    "threshold_percent": round(rule.threshold, 2),
                    "threshold_delta": threshold_delta,
                    "met_threshold": met_threshold,
                    "status": status,
                    "best_topic": best_topic,
                }
            )
        return sorted(details, key=lambda detail: (detail["match_score"], detail["weight"]), reverse=True)

    def _weighted_keyword_score(self, keyword_match_details: list[dict[str, Any]]) -> float:
        """Collapse per-keyword evidence into one weighted 0-100 score."""

        if not keyword_match_details:
            return 0.0
        total_weight = sum(float(detail["weight"]) for detail in keyword_match_details) or 1.0
        matched_weight = sum(float(detail["weight"]) * float(detail["match_score"]) for detail in keyword_match_details)
        return (matched_weight / total_weight) * 100.0

    def _classify_research_fit(self, weighted_keyword_score: float, matched_keyword_count: int) -> ResearchFitLabel:
        """Map weighted keyword evidence to a research-fit label."""

        if (
            weighted_keyword_score >= self.config.topic_prefilter_match_threshold
            and matched_keyword_count >= self.config.topic_prefilter_min_keyword_matches
        ):
            return "STRONG_FIT"
        if (
            weighted_keyword_score >= self.config.topic_prefilter_near_fit_threshold
            or matched_keyword_count >= max(self.config.topic_prefilter_min_keyword_matches - 1, 0)
        ):
            return "NEAR_FIT"
        return "WEAK_FIT"

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
