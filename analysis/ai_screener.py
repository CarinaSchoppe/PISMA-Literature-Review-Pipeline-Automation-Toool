from __future__ import annotations

import json
import logging
from typing import Any

from models.paper import PaperMetadata, ScreeningResult

from config import ResearchConfig
from .llm_clients import build_llm_client
from .relevance_scoring import RelevanceScorer

LOGGER = logging.getLogger(__name__)


class AIScreener:
    def __init__(self, config: ResearchConfig) -> None:
        self.config = config
        self.scorer = RelevanceScorer(config)
        self.llm_client = build_llm_client(config)
        self.llm_enabled = self.llm_client.enabled

    def screen(self, paper: PaperMetadata) -> ScreeningResult:
        if self.scorer.has_hard_exclusion(paper):
            LOGGER.info("Hard exclusion triggered for '%s'.", paper.title)
            return self.scorer.deep_score(paper, stage_one_decision="exclude")

        if not self.llm_enabled:
            stage_one = self.scorer.quick_screen(paper)
            if self.config.log_screening_decisions and self.config.verbosity in {"verbose", "debug"}:
                LOGGER.info("Heuristic Stage 1 for '%s': %s", paper.title, stage_one)
            return self.scorer.deep_score(paper, stage_one_decision=stage_one)

        stage_one = self._llm_stage_one(paper) or self.scorer.quick_screen(paper)
        if self.config.log_screening_decisions and self.config.verbosity in {"verbose", "debug"}:
            LOGGER.info("LLM Stage 1 for '%s': %s", paper.title, stage_one)
        if stage_one == "exclude":
            return self.scorer.deep_score(paper, stage_one_decision=stage_one)

        llm_result = self._llm_stage_two(paper, stage_one)
        if llm_result:
            return llm_result
        return self.scorer.deep_score(paper, stage_one_decision=stage_one)

    def summarize_review(self, papers: list[PaperMetadata]) -> str | None:
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
        try:
            return ScreeningResult(
                stage_one_decision=stage_one,
                relevance_score=float(parsed.get("relevance_score", 0.0)),
                explanation=str(parsed.get("explanation", "")),
                extracted_passage=str(parsed.get("extracted_passage", "")),
                methodology_category=str(parsed.get("methodology_category", "unspecified")),
                domain_category=str(parsed.get("domain_category", "general")),
                decision=str(parsed.get("decision", "maybe")).lower(),
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

    def _chat_completion(self, *, system_prompt: str, user_prompt: str) -> str | None:
        if self.config.log_llm_prompts and self.config.verbosity == "debug":
            LOGGER.debug("LLM system prompt: %s", system_prompt[:1000])
            LOGGER.debug("LLM user prompt: %s", user_prompt[:2000])
        response = self.llm_client.chat(system_prompt=system_prompt, user_prompt=user_prompt)
        if self.config.log_llm_responses and self.config.verbosity == "debug" and response.content:
            LOGGER.debug("LLM response: %s", response.content[:2000])
        return response.content

    def _parse_json_response(self, text: str) -> dict[str, Any]:
        candidate = text.strip()
        if candidate.startswith("```"):
            candidate = candidate.strip("`")
            candidate = candidate.replace("json", "", 1).strip()
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end == -1:
            return {}
        candidate = candidate[start : end + 1]
        try:
            parsed = json.loads(candidate)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            LOGGER.warning("Failed to decode JSON response: %s", candidate[:500])
            return {}
