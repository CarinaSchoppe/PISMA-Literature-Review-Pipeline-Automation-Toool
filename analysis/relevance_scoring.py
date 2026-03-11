"""Heuristic relevance scoring used for screening and non-LLM fallback operation."""

from __future__ import annotations

import math
from typing import cast

from models.paper import DecisionLabel, PaperMetadata, ScreeningResult

from config import ResearchConfig
from utils.text_processing import extract_salient_sentence, keyword_overlap_score, normalize_title

METHODOLOGY_PATTERNS = {
    "systematic review": ["systematic review", "meta-analysis", "scoping review", "literature review", "prisma"],
    "experimental": ["experiment", "benchmark", "evaluation", "ablation", "trial", "controlled"],
    "survey": ["survey", "questionnaire", "cross-sectional"],
    "qualitative": ["qualitative", "interview", "focus group", "thematic analysis"],
    "quantitative": ["quantitative", "regression", "dataset", "statistical", "machine learning"],
    "case study": ["case study", "case report", "implementation"],
}

DOMAIN_PATTERNS = {
    "healthcare": ["clinical", "patient", "hospital", "medical", "health", "disease", "therapy"],
    "computer science": ["algorithm", "model", "dataset", "neural", "software", "ai", "machine learning"],
    "education": ["student", "curriculum", "learning", "classroom", "pedagogy"],
    "psychology": ["behavior", "cognitive", "mental", "psychology", "emotion"],
    "social science": ["policy", "society", "governance", "community", "social"],
}

THEORY_TERMS = {
    "framework",
    "model",
    "hypothesis",
    "mechanism",
    "conceptual",
    "theory",
    "novel",
    "contribution",
}


class RelevanceScorer:
    """Score papers against the review brief using transparent heuristic criteria."""

    def __init__(self, config: ResearchConfig) -> None:
        self.config = config

    def has_hard_exclusion(self, paper: PaperMetadata) -> bool:
        """Return whether banned themes or excluded title markers force rejection."""

        combined_text = f"{paper.title}. {paper.abstract}"
        return bool(self._matched_terms(combined_text, self.config.banned_topics)) or bool(
            self._matched_terms(paper.title, self.config.excluded_title_terms)
        )

    def quick_screen(self, paper: PaperMetadata) -> str:
        """Return a fast include/maybe/exclude triage decision from lightweight signals."""

        combined_text = f"{paper.title}. {paper.abstract}"
        topic_keywords = [
            self.config.research_topic,
            self.config.research_question,
            self.config.review_objective,
            *self.config.search_keywords,
            *self.config.inclusion_criteria,
        ]
        overlap = keyword_overlap_score(combined_text, topic_keywords)
        exclusion_penalty = keyword_overlap_score(combined_text, self.config.exclusion_criteria) * 0.2
        year_bonus = 0.1 if paper.year and paper.year >= self.config.year_range_start else 0.0
        score = overlap + year_bonus - exclusion_penalty
        if self.has_hard_exclusion(paper):
            return "exclude"
        if overlap >= 0.55:
            return "include"
        if score >= 0.22:
            return "maybe"
        return "exclude"

    def deep_score(self, paper: PaperMetadata, stage_one_decision: str | None = None) -> ScreeningResult:
        """Compute the final relevance score, explanation, and structured decision payload."""

        combined_text = normalize_title(f"{paper.title}. {paper.abstract}")
        methodology_category = self._classify_methodology(combined_text)
        domain_category = self._classify_domain(combined_text)
        matched_inclusion = self._matched_terms(combined_text, self.config.inclusion_criteria)
        matched_exclusion = self._matched_terms(combined_text, self.config.exclusion_criteria)
        matched_banned = self._matched_terms(combined_text, self.config.banned_topics)
        matched_excluded_title_terms = self._matched_terms(paper.title, self.config.excluded_title_terms)
        topic_score = keyword_overlap_score(
            combined_text,
            [
                self.config.research_topic,
                self.config.research_question,
                self.config.review_objective,
                *self.config.search_keywords,
                *self.config.inclusion_criteria,
            ],
        ) * 100
        exclusion_penalty = keyword_overlap_score(combined_text, self.config.exclusion_criteria) * 20
        banned_penalty = 100.0 if matched_banned else 0.0
        excluded_title_penalty = 100.0 if matched_excluded_title_terms else 0.0
        methodology_score = 90.0 if methodology_category != "unspecified" else 35.0
        theoretical_score = min(100.0, 15.0 * sum(term in combined_text for term in THEORY_TERMS))
        recency_score = self._recency_score(paper.year)
        citation_score = self._citation_score(paper.citation_count)

        relevance_score = (
            0.40 * topic_score
            + 0.20 * methodology_score
            + 0.15 * theoretical_score
            + 0.10 * recency_score
            + 0.15 * citation_score
                          ) - exclusion_penalty - banned_penalty - excluded_title_penalty
        stage_one = cast(DecisionLabel, stage_one_decision or self.quick_screen(paper))
        extracted_passage = extract_salient_sentence(paper.abstract or paper.title, self.config.search_keywords)
        decision = cast(
            DecisionLabel,
            self._decision_from_score(
                relevance_score,
                stage_one,
                matched_banned=bool(matched_banned),
                matched_excluded_title_terms=bool(matched_excluded_title_terms),
            ),
        )
        retain_reason = (
            f"Kept because the paper matches the review focus and scored {relevance_score:.1f} against the "
            f"{self.config.relevance_threshold:.1f} threshold."
            if decision == "include"
            else ""
        )
        exclusion_reason = ""
        if decision == "exclude":
            if matched_banned:
                exclusion_reason = f"Excluded because banned topics were detected: {', '.join(matched_banned)}."
            elif matched_excluded_title_terms:
                exclusion_reason = (
                    "Excluded because title markers indicate a non-target publication type: "
                    f"{', '.join(matched_excluded_title_terms)}."
                )
            elif matched_exclusion:
                exclusion_reason = (
                    f"Excluded because exclusion criteria matched: {', '.join(matched_exclusion)}."
                )
            else:
                exclusion_reason = (
                    f"Excluded because the score {relevance_score:.1f} was below the "
                    f"{self.config.relevance_threshold:.1f} threshold."
                )

        explanation = (
            f"Topic match {topic_score:.1f}/100, methodology {methodology_score:.1f}/100, "
            f"theory contribution {theoretical_score:.1f}/100, recency {recency_score:.1f}/100, "
            f"citation strength {citation_score:.1f}/100, exclusion penalty {exclusion_penalty:.1f}, "
            f"banned penalty {banned_penalty:.1f}, title penalty {excluded_title_penalty:.1f}. "
            f"Stage 1 decision: {stage_one}."
        )
        return ScreeningResult(
            stage_one_decision=stage_one,
            relevance_score=round(relevance_score, 2),
            explanation=explanation,
            extracted_passage=extracted_passage,
            methodology_category=methodology_category,
            domain_category=domain_category,
            decision=decision,
            matched_inclusion_criteria=matched_inclusion,
            matched_exclusion_criteria=matched_exclusion,
            matched_banned_topics=matched_banned,
            matched_excluded_title_terms=matched_excluded_title_terms,
            retain_reason=retain_reason,
            exclusion_reason=exclusion_reason,
            screening_context_key=self.config.screening_context_key,
            evaluation_breakdown={
                "topical_match": round(topic_score, 2),
                "methodological_relevance": round(methodology_score, 2),
                "theoretical_contribution": round(theoretical_score, 2),
                "recency": round(recency_score, 2),
                "citation_strength": round(citation_score, 2),
                "exclusion_penalty": round(exclusion_penalty, 2),
                "banned_penalty": round(banned_penalty, 2),
                "excluded_title_penalty": round(excluded_title_penalty, 2),
            },
        )

    def _classify_methodology(self, text: str) -> str:
        for label, patterns in METHODOLOGY_PATTERNS.items():
            if any(pattern in text for pattern in patterns):
                return label
        return "unspecified"

    def _classify_domain(self, text: str) -> str:
        for label, patterns in DOMAIN_PATTERNS.items():
            if any(pattern in text for pattern in patterns):
                return label
        return "general"

    def _recency_score(self, year: int | None) -> float:
        if not year:
            return 40.0
        span = max(self.config.year_range_end - self.config.year_range_start, 1)
        return max(0.0, min(100.0, 100.0 * (year - self.config.year_range_start) / span))

    def _citation_score(self, citation_count: int) -> float:
        if citation_count <= 0:
            return 10.0
        return min(100.0, math.log10(citation_count + 1) / math.log10(501) * 100.0)

    def _decision_from_score(
            self,
            score: float,
            stage_one: str,
            *,
            matched_banned: bool = False,
            matched_excluded_title_terms: bool = False,
    ) -> str:
        """Translate score and gating signals into the configured decision mode."""

        if matched_banned or matched_excluded_title_terms:
            return "exclude"
        if self.config.decision_mode == "strict":
            return "include" if score >= self.config.relevance_threshold else "exclude"
        if stage_one == "exclude" and score < self.config.relevance_threshold:
            return "exclude"
        if score >= self.config.relevance_threshold:
            return "include"
        if score >= self.config.relevance_threshold - self.config.maybe_threshold_margin:
            return "maybe"
        return "exclude"

    def _matched_terms(self, text: str, terms: list[str]) -> list[str]:
        normalized = normalize_title(text)
        matches: list[str] = []
        for term in terms:
            candidate = normalize_title(term)
            if candidate and candidate in normalized:
                matches.append(term)
        return matches
