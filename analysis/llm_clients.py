"""Adapters for hosted and local LLM backends used by the screening layer."""

from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass
from typing import Any

from config import ResearchConfig
from utils.http import RateLimiter, build_session, request_json

LOGGER = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """Minimal normalized response returned by any configured LLM adapter."""

    content: str | None
    enabled: bool
    provider_name: str


class BaseLLMClient:
    """Fallback LLM client used when screening should stay heuristic only."""

    enabled = False
    provider_name = "heuristic"

    def chat(self, *, system_prompt: str, user_prompt: str) -> LLMResponse:
        return LLMResponse(content=None, enabled=False, provider_name=self.provider_name)


class OpenAICompatibleLLMClient(BaseLLMClient):
    """Client for OpenAI-compatible chat-completions endpoints, including Ollama."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        temperature: float,
        timeout_seconds: int,
        provider_name: str = "openai_compatible",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds
        self.enabled = True
        self.provider_name = provider_name
        self.session = build_session(
            "PRISMA-Literature-Review/1.0",
            extra_headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        self.limiter = RateLimiter(calls_per_second=1.0)

    def chat(self, *, system_prompt: str, user_prompt: str) -> LLMResponse:
        """Submit a chat completion request and normalize the first assistant message."""

        payload = request_json(
            self.session,
            "POST",
            f"{self.base_url}/chat/completions",
            limiter=self.limiter,
            timeout=max(60, self.timeout_seconds),
            json={
                "model": self.model,
                "temperature": self.temperature,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        if not payload:
            return LLMResponse(content=None, enabled=True, provider_name=self.provider_name)
        choices = payload.get("choices") or []
        if not choices:
            return LLMResponse(content=None, enabled=True, provider_name=self.provider_name)
        return LLMResponse(
            content=choices[0].get("message", {}).get("content"),
            enabled=True,
            provider_name=self.provider_name,
        )


class GeminiLLMClient(BaseLLMClient):
    """Client for Google's Gemini GenerateContent API."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        temperature: float,
        timeout_seconds: int,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds
        self.enabled = True
        self.provider_name = "gemini"
        self.session = build_session(
            "PRISMA-Literature-Review/1.0",
            extra_headers={"Content-Type": "application/json"},
        )
        self.limiter = RateLimiter(calls_per_second=1.0)

    def chat(self, *, system_prompt: str, user_prompt: str) -> LLMResponse:
        """Submit a Gemini generateContent request and normalize the first text response."""

        payload = request_json(
            self.session,
            "POST",
            f"{self.base_url}/models/{self.model}:generateContent",
            limiter=self.limiter,
            timeout=max(60, self.timeout_seconds),
            params={"key": self.api_key},
            json={
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                "generationConfig": {"temperature": self.temperature},
            },
        )
        if not payload:
            return LLMResponse(content=None, enabled=True, provider_name=self.provider_name)
        return LLMResponse(
            content=self._extract_text(payload),
            enabled=True,
            provider_name=self.provider_name,
        )

    def _extract_text(self, payload: dict[str, Any]) -> str | None:
        """Flatten Gemini candidate parts into a single assistant text response."""

        candidates = payload.get("candidates") or []
        if not candidates:
            return None
        content = candidates[0].get("content") or {}
        parts = content.get("parts") or []
        chunks = [
            str(part.get("text", "")).strip()
            for part in parts
            if isinstance(part, dict) and str(part.get("text", "")).strip()
        ]
        return "\n".join(chunks) or None


def load_transformers_runtime() -> tuple[Any, Any]:
    """Import the optional local Hugging Face runtime on demand."""

    try:
        import torch
        from transformers import pipeline
    except ImportError as exc:  # pragma: no cover - exercised through unit mocks
        raise RuntimeError(
            "Local Hugging Face inference requires 'transformers' and a supported backend such as 'torch'."
        ) from exc
    return torch, pipeline


class HuggingFaceLocalLLMClient(BaseLLMClient):
    """Local text-generation client backed by `transformers.pipeline`."""

    def __init__(
        self,
        *,
        model_id: str,
        task: str,
        temperature: float,
        max_new_tokens: int,
        device: str,
        dtype: str,
        cache_dir: str | None,
        trust_remote_code: bool,
    ) -> None:
        self.provider_name = "huggingface_local"
        self.enabled = False
        self.temperature = temperature
        self.max_new_tokens = max_new_tokens
        self.model_id = model_id
        self._generator = None
        try:
            torch, pipeline = load_transformers_runtime()
            pipeline_kwargs = {
                "task": task,
                "model": model_id,
                "trust_remote_code": trust_remote_code,
            }
            if cache_dir:
                pipeline_kwargs["model_kwargs"] = {"cache_dir": cache_dir}
            resolved_dtype = self._resolve_dtype(torch, dtype)
            if resolved_dtype is not None:
                pipeline_kwargs["dtype"] = resolved_dtype
            if device == "auto":
                if self._accelerate_available():
                    pipeline_kwargs["device_map"] = "auto"
                else:
                    LOGGER.warning(
                        "Accelerate is not installed; loading Hugging Face model '%s' without device_map auto.",
                        model_id,
                    )
                    pipeline_kwargs["device"] = -1
            elif device:
                pipeline_kwargs["device"] = device
            self._generator = pipeline(**pipeline_kwargs)
            self.enabled = True
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Could not initialize local Hugging Face model '%s': %s", model_id, exc)

    def chat(self, *, system_prompt: str, user_prompt: str) -> LLMResponse:
        """Generate a response from a local model using chat-style messages."""

        if not self.enabled or self._generator is None:
            return LLMResponse(content=None, enabled=False, provider_name=self.provider_name)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        generation_kwargs: dict[str, Any] = {
            "max_new_tokens": self.max_new_tokens,
            "return_full_text": False,
        }
        if self.temperature > 0:
            generation_kwargs["do_sample"] = True
            generation_kwargs["temperature"] = self.temperature
        else:
            generation_kwargs["do_sample"] = False
        try:
            output = self._generator(messages, **generation_kwargs)
            return LLMResponse(
                content=self._extract_generated_content(output),
                enabled=True,
                provider_name=self.provider_name,
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Local Hugging Face generation failed for '%s': %s", self.model_id, exc)
            return LLMResponse(content=None, enabled=True, provider_name=self.provider_name)

    def _resolve_dtype(self, torch: Any, dtype_name: str) -> Any | None:
        """Map a config string like `float16` to a torch dtype object when possible."""

        normalized = (dtype_name or "auto").strip().lower()
        if normalized == "auto":
            return "auto"
        attr_name = normalized.replace("-", "").replace(" ", "")
        return getattr(torch, attr_name, None)

    def _accelerate_available(self) -> bool:
        """Detect whether `accelerate` is available for automatic device placement."""

        return importlib.util.find_spec("accelerate") is not None

    def _extract_generated_content(self, output: Any) -> str | None:
        """Normalize different pipeline output shapes into one plain text response."""

        if not output:
            return None
        first_item = output[0] if isinstance(output, list) else output
        generated = first_item.get("generated_text") if isinstance(first_item, dict) else first_item
        if isinstance(generated, str):
            return generated
        if isinstance(generated, list) and generated:
            last_item = generated[-1]
            if isinstance(last_item, dict):
                return str(last_item.get("content", "")).strip() or None
            return str(last_item).strip() or None
        return None


def build_llm_client(config: ResearchConfig) -> BaseLLMClient:
    """Select and instantiate the concrete LLM adapter for the active configuration."""

    provider = config.llm_provider
    settings = config.api_settings

    if provider == "heuristic":
        return BaseLLMClient()

    if provider in {"auto", "openai_compatible"} and settings.openai_api_key:
        return OpenAICompatibleLLMClient(
            base_url=settings.openai_base_url,
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            temperature=settings.llm_temperature,
            timeout_seconds=config.request_timeout_seconds,
            provider_name="openai_compatible",
        )

    if provider in {"auto", "gemini"} and settings.gemini_api_key:
        return GeminiLLMClient(
            base_url=settings.gemini_base_url,
            model=settings.gemini_model,
            api_key=settings.gemini_api_key,
            temperature=settings.llm_temperature,
            timeout_seconds=config.request_timeout_seconds,
        )

    if provider == "ollama":
        return OpenAICompatibleLLMClient(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            api_key=settings.ollama_api_key,
            temperature=settings.llm_temperature,
            timeout_seconds=config.request_timeout_seconds,
            provider_name="ollama",
        )

    if provider == "huggingface_local":
        return HuggingFaceLocalLLMClient(
            model_id=settings.huggingface_model,
            task=settings.huggingface_task,
            temperature=settings.llm_temperature,
            max_new_tokens=settings.huggingface_max_new_tokens,
            device=settings.huggingface_device,
            dtype=settings.huggingface_dtype,
            cache_dir=settings.huggingface_cache_dir,
            trust_remote_code=settings.huggingface_trust_remote_code,
        )

    return BaseLLMClient()
