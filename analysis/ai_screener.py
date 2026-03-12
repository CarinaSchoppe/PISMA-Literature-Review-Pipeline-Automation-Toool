"""Heuristic and LLM-backed screening logic for topic relevance assessment."""

from __future__ import annotations

import json
import logging
from typing import Any, cast

from config import ResearchConfig
from models.paper import DecisionLabel, PaperMetadata, ScreeningResult
from .llm_clients import build_llm_client
from .relevance_scoring import RelevanceScorer
from .topic_prefilter import build_topic_matcher

LOGGER = logging.getLogger(__name__)


class AIScreener:
    """Apply staged relevance screening and optional review summarization."""

    def __init__(self, config: ResearchConfig) -> None:
        self.config = config
        self.topic_matcher = build_topic_matcher(config)
        self.scorer = RelevanceScorer(config, topic_matcher=self.topic_matcher)
        self.llm_client = build_llm_client(config)
        self.llm_enabled = self.llm_client.enabled

    def screen(self, paper: PaperMetadata) -> ScreeningResult:
        """Screen one paper using hard exclusions, local topic matching, and optional LLM passes."""

        if self.scorer.has_hard_exclusion(paper):
            LOGGER.info("Hard exclusion triggered for '%s'.", paper.title)
            return self.scorer.deep_score(paper, stage_one_decision="exclude")

        topic_match = self.scorer.evaluate_topic_match(paper)
        if topic_match and self.config.log_screening_decisions and self.config.verbosity in {"verbose", "ultra_verbose"}:
            LOGGER.info(
                "Local topic prefilter for '%s': %s (%.2f / %s).",
                paper.title,
                topic_match.classification,
                topic_match.similarity,
                topic_match.model_name,
            )
        if topic_match and topic_match.should_exclude:
            return self.scorer.deep_score(paper, stage_one_decision="exclude", topic_match=topic_match)

        if not self.llm_enabled:
            LOGGER.debug("LLM screening is disabled for '%s'; falling back to heuristic screening.", paper.title)
            stage_one = self.scorer.quick_screen(paper, topic_match=topic_match)
            if self.config.log_screening_decisions and self.config.verbosity in {"verbose", "ultra_verbose"}:
                LOGGER.info("Heuristic Stage 1 for '%s': %s", paper.title, stage_one)
            return self.scorer.deep_score(paper, stage_one_decision=stage_one, topic_match=topic_match)

        LOGGER.debug("Starting LLM Stage 1 for '%s'.", paper.title)
        stage_one = self._llm_stage_one(paper) or self.scorer.quick_screen(paper, topic_match=topic_match)
        if self.config.log_screening_decisions and self.config.verbosity in {"verbose", "ultra_verbose"}:
            LOGGER.info("LLM Stage 1 for '%s': %s", paper.title, stage_one)
        if stage_one == "exclude":
            return self.scorer.deep_score(paper, stage_one_decision=stage_one, topic_match=topic_match)

        LOGGER.debug("Starting LLM Stage 2 for '%s' after Stage 1 decision '%s'.", paper.title, stage_one)
        llm_result = self._llm_stage_two(paper, stage_one)
        if llm_result is not None:
            LOGGER.info(
                "LLM Stage 2 completed for '%s': decision=%s score=%.2f",
                paper.title,
                llm_result.decision,
                llm_result.relevance_score,
            )
            return self._enrich_with_topic_match(llm_result, topic_match)
        return self.scorer.deep_score(paper, stage_one_decision=stage_one, topic_match=topic_match)

    def summarize_review(self, papers: list[PaperMetadata]) -> str | None:
        """Summarize a shortlist into narrative review text when an LLM is available."""

        if not self.llm_enabled or not papers:
            return None
        shortlist = [
            {
                "title": paper.title,
                "year": paper.year,
                "venue": paper.venue,
                "score": paper.relevance_score,
                "decision": paper.inclusion_decision,
                "methodology": paper.methodology_category,
                "domain": paper.domain_category,
                "abstract": (paper.abstract or "")[:1200],
                "full_text_excerpt": (paper.raw_payload.get("full_text_excerpt") or "")[:1200],
            }
            for paper in papers[:12]
        ]
        prompt = (
                "Write a concise literature review summary in Markdown with sections: "
                "Theme Overview, Methods, Gaps, and Recommended Core Papers. "
                "Base the summary only on this JSON payload and review brief:\n"
                f"{self.config.screening_brief}\n"
                + json.dumps(shortlist, ensure_ascii=True)
        )
        payload = self._chat_completion(
            system_prompt="You are a rigorous research synthesis assistant.",
            user_prompt=prompt,
        )
        return payload if payload else None

    def _llm_stage_one(self, paper: PaperMetadata) -> str | None:
        """Ask an LLM for the quick include/maybe/exclude triage label."""

        prompt = (
            "Classify the paper for Stage 1 screening. Return only JSON with key 'decision' "
            "and value one of include, maybe, exclude.\n"
            f"{self.config.screening_brief}\n"
            f"Title: {paper.title}\n"
            f"Abstract: {paper.abstract[:2500]}\n"
            f"Full-text excerpt: {(paper.raw_payload.get('full_text_excerpt') or '')[:4000]}"
        )
        response = self._chat_completion(
            system_prompt="You perform rapid relevance screening for literature reviews.",
            user_prompt=prompt,
        )
        if not response:
            return None
        parsed = self._parse_json_response(response)
        decision = str(parsed.get("decision", "")).lower()
        if decision in {"include", "maybe", "exclude"}:
            return decision
        return None

    def _llm_stage_two(self, paper: PaperMetadata, stage_one: str) -> ScreeningResult | None:
        """Ask an LLM for structured scoring details and decision rationale."""

        prompt = (
            "Assess the paper and return JSON with keys: relevance_score (0-100), explanation, "
            "extracted_passage, methodology_category, domain_category, decision, retain_reason, "
            "exclusion_reason, matched_inclusion_criteria, matched_exclusion_criteria, matched_banned_topics. "
            "Also return matched_excluded_title_terms. "
            "Use the criteria topical match, methodological relevance, theoretical contribution, "
            "recency, citation strength.\n"
            f"{self.config.screening_brief}\n"
            f"Stage 1 decision: {stage_one}\n"
            f"Title: {paper.title}\n"
            f"Abstract: {paper.abstract[:5000]}\n"
            f"Full-text excerpt: {(paper.raw_payload.get('full_text_excerpt') or '')[: self.config.full_text_max_chars]}"
        )
        response = self._chat_completion(
            system_prompt="You are a senior research screener. Return strict JSON only.",
            user_prompt=prompt,
        )
        if not response:
            return None
        parsed = self._parse_json_response(response)
        if not parsed:
            LOGGER.warning(
                "LLM Stage 2 returned no valid JSON for '%s'; falling back to heuristic scoring.",
                paper.title,
            )
            return None

        decision = str(parsed.get("decision", "")).lower().strip()
        if decision not in {"include", "maybe", "exclude"}:
            LOGGER.warning(
                "LLM Stage 2 returned an invalid decision for '%s'; falling back to heuristic scoring.",
                paper.title,
            )
            return None

        if "relevance_score" not in parsed:
            LOGGER.warning(
                "LLM Stage 2 returned no relevance score for '%s'; falling back to heuristic scoring.",
                paper.title,
            )
            return None
        try:
            return ScreeningResult(
                stage_one_decision=cast(DecisionLabel, stage_one),
                relevance_score=float(parsed.get("relevance_score", 0.0)),
                explanation=str(parsed.get("explanation", "")),
                extracted_passage=str(parsed.get("extracted_passage", "")),
                methodology_category=str(parsed.get("methodology_category", "unspecified")),
                domain_category=str(parsed.get("domain_category", "general")),
                decision=cast(DecisionLabel, decision),
                matched_inclusion_criteria=list(parsed.get("matched_inclusion_criteria", []) or []),
                matched_exclusion_criteria=list(parsed.get("matched_exclusion_criteria", []) or []),
                matched_banned_topics=list(parsed.get("matched_banned_topics", []) or []),
                matched_excluded_title_terms=list(parsed.get("matched_excluded_title_terms", []) or []),
                retain_reason=str(parsed.get("retain_reason", "")),
                exclusion_reason=str(parsed.get("exclusion_reason", "")),
                screening_context_key=self.config.screening_context_key,
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Could not parse LLM screening response for '%s': %s", paper.title, exc)
            return None

    def _enrich_with_topic_match(
            self,
            result: ScreeningResult,
            topic_match: Any | None,
    ) -> ScreeningResult:
        """Attach local semantic topic-match details to an LLM-produced screening result."""

        if topic_match is None:
            return result
        explanation = result.explanation or ""
        if topic_match.explanation and topic_match.explanation not in explanation:
            explanation = f"{explanation} {topic_match.explanation}".strip()
        payload = result.model_dump()
        payload.update(
            {
                "topic_prefilter_score": topic_match.score,
                "topic_prefilter_similarity": topic_match.similarity,
                "topic_prefilter_model": topic_match.model_name,
                "topic_prefilter_threshold": topic_match.threshold,
                "topic_prefilter_label": topic_match.classification,
                "topic_prefilter_keyword_overlap": topic_match.keyword_overlap_score,
                "topic_prefilter_research_fit_label": topic_match.research_fit_label,
                "topic_prefilter_weighted_score": topic_match.weighted_keyword_score,
                "topic_prefilter_min_keyword_matches": topic_match.min_keyword_matches,
                "topic_prefilter_matched_keyword_count": topic_match.matched_keyword_count,
                "topic_prefilter_keyword_rule_count": topic_match.keyword_rule_count,
                "topic_prefilter_extracted_topics": list(topic_match.extracted_topics),
                "topic_prefilter_keyword_details": list(topic_match.keyword_match_details),
                "explanation": explanation,
            }
        )
        return ScreeningResult(**payload)

    def _chat_completion(self, *, system_prompt: str, user_prompt: str) -> str | None:
        """Send a chat-style prompt to the configured LLM client."""

        if self.config.log_llm_prompts and self.config.verbosity == "ultra_verbose":
            LOGGER.debug("LLM system prompt: %s", system_prompt[:1000])
            LOGGER.debug("LLM user prompt: %s", user_prompt[:2000])
        response = self.llm_client.chat(system_prompt=system_prompt, user_prompt=user_prompt)
        if self.config.log_llm_responses and self.config.verbosity == "ultra_verbose" and response.content:
            LOGGER.debug("LLM response: %s", response.content[:2000])
        return response.content

    def _parse_json_response(self, text: str) -> dict[str, Any]:
        """Extract a JSON object from a raw LLM response, including fenced code blocks."""

        candidate = text.strip()
        if candidate.startswith("```"):
            candidate = candidate.strip("`")
            candidate = candidate.replace("json", "", 1).strip()
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1:
            return {}
        candidate = candidate[start: end + 1]
        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            LOGGER.warning("Failed to decode JSON response: %s", candidate[:500])
            return {}
