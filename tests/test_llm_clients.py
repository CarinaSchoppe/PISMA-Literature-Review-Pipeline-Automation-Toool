"""Tests for the pluggable LLM client adapters used by the screening layer."""

from __future__ import annotations

import builtins
import types
import unittest
from unittest.mock import patch

from analysis.llm_clients import (
    BaseLLMClient,
    GeminiLLMClient,
    HuggingFaceLocalLLMClient,
    OpenAICompatibleLLMClient,
    build_llm_client,
    load_transformers_runtime,
)
from config import ResearchConfig


class _FakeGenerator:
    """Minimal fake text-generation pipeline used to isolate the HF client adapter."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, dict[str, object]]] = []

    def __call__(self, messages: object, **kwargs: object) -> list[dict[str, object]]:
        self.calls.append((messages, kwargs))
        return [
            {
                "generated_text": [
                    {"role": "system", "content": "stub"},
                    {"role": "assistant", "content": "{\"decision\": \"include\"}"},
                ]
            }
        ]


class _FakeTorch:
    """Subset of torch dtypes needed by the local HF client tests."""

    float16 = "float16"
    bfloat16 = "bfloat16"


class LLMClientTests(unittest.TestCase):
    """Exercise local-runtime success and fallback behavior for LLM client creation."""

    def test_base_client_returns_disabled_response(self) -> None:
        client = BaseLLMClient()

        response = client.chat(system_prompt="system", user_prompt="user")

        self.assertIsNone(response.content)
        self.assertFalse(response.enabled)
        self.assertEqual(response.provider_name, "heuristic")

    def test_openai_compatible_client_handles_missing_and_successful_payloads(self) -> None:
        with patch("analysis.llm_clients.request_json", side_effect=[None, {"choices": []}, {"choices": [{"message": {"content": "ok"}}]}]):
            client = OpenAICompatibleLLMClient(
                base_url="https://example.org/v1/",
                model="gpt-5.4",
                api_key="secret",
                temperature=0.2,
                timeout_seconds=5,
            )

            first = client.chat(system_prompt="sys", user_prompt="user")
            second = client.chat(system_prompt="sys", user_prompt="user")
            third = client.chat(system_prompt="sys", user_prompt="user")

        self.assertIsNone(first.content)
        self.assertIsNone(second.content)
        self.assertEqual(third.content, "ok")
        self.assertEqual(client.base_url, "https://example.org/v1")
        self.assertIn("Authorization", client.session.headers)

    def test_gemini_client_handles_missing_and_successful_payloads(self) -> None:
        with patch(
                "analysis.llm_clients.request_json",
                side_effect=[
                    None,
                    {"candidates": []},
                    {"candidates": [{"content": {"parts": [{"text": "first"}, {"text": "second"}]}}]},
                ],
        ):
            client = GeminiLLMClient(
                base_url="https://generativelanguage.googleapis.com/v1beta/",
                model="gemini-2.5-flash",
                api_key="secret",
                temperature=0.2,
                timeout_seconds=5,
            )

            first = client.chat(system_prompt="sys", user_prompt="user")
            second = client.chat(system_prompt="sys", user_prompt="user")
            third = client.chat(system_prompt="sys", user_prompt="user")

        self.assertIsNone(first.content)
        self.assertIsNone(second.content)
        self.assertEqual(third.content, "first\nsecond")
        self.assertEqual(client.base_url, "https://generativelanguage.googleapis.com/v1beta")

    def test_load_transformers_runtime_raises_helpful_error_without_dependencies(self) -> None:
        original_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
            if name in {"torch", "transformers"}:
                raise ImportError("missing runtime")
            return original_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=fake_import):
            with self.assertRaisesRegex(RuntimeError, "requires 'transformers'"):
                load_transformers_runtime()
            self.assertIs(fake_import("json"), original_import("json"))

    def test_load_transformers_runtime_can_import_fake_runtime(self) -> None:
        original_import = builtins.__import__
        fake_torch = types.SimpleNamespace(float16="float16")
        fake_transformers = types.SimpleNamespace(pipeline="pipeline")

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
            if name == "torch":
                return fake_torch
            if name == "transformers":
                return fake_transformers
            return original_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=fake_import):
            torch_module, pipeline_func = load_transformers_runtime()
            self.assertIs(fake_import("json"), original_import("json"))

        self.assertIs(torch_module, fake_torch)
        self.assertEqual(pipeline_func, "pipeline")

    def test_build_huggingface_client_uses_local_runtime(self) -> None:
        fake_generator = _FakeGenerator()

        def fake_pipeline(**kwargs: object) -> _FakeGenerator:
            self.assertEqual(kwargs["model"], "Qwen/Qwen3-8B")
            self.assertEqual(kwargs["task"], "text-generation")
            return fake_generator

        config = ResearchConfig(
            research_topic="AI-assisted literature reviews",
            search_keywords=["llm", "screening"],
            llm_provider="huggingface_local",
            include_pubmed=False,
            api_settings={
                "huggingface_model": "Qwen/Qwen3-8B",
                "huggingface_task": "text-generation",
                "huggingface_max_new_tokens": 256,
            },
        ).finalize()

        with patch("analysis.llm_clients.load_transformers_runtime", return_value=(_FakeTorch, fake_pipeline)):
            client = build_llm_client(config)
            response = client.chat(system_prompt="system", user_prompt="user")

        self.assertTrue(client.enabled)
        self.assertEqual(client.provider_name, "huggingface_local")
        self.assertEqual(response.content, "{\"decision\": \"include\"}")
        self.assertEqual(fake_generator.calls[0][1]["max_new_tokens"], 256)

    def test_build_huggingface_client_falls_back_when_runtime_missing(self) -> None:
        config = ResearchConfig(
            research_topic="AI-assisted literature reviews",
            search_keywords=["llm", "screening"],
            llm_provider="huggingface_local",
            include_pubmed=False,
        ).finalize()

        with patch("analysis.llm_clients.load_transformers_runtime", side_effect=RuntimeError("missing runtime")):
            client = build_llm_client(config)

        self.assertFalse(client.enabled)
        self.assertEqual(client.provider_name, "huggingface_local")

    def test_huggingface_client_helper_methods_and_error_branch(self) -> None:
        class ExplodingGenerator:
            def __call__(self, messages: object, **kwargs: object):  # noqa: ANN001
                raise RuntimeError("boom")

        def fake_pipeline(**kwargs: object) -> ExplodingGenerator:
            self.assertEqual(kwargs["device_map"], "auto")
            self.assertEqual(kwargs["dtype"], _FakeTorch.float16)
            return ExplodingGenerator()

        with patch("analysis.llm_clients.load_transformers_runtime", return_value=(_FakeTorch, fake_pipeline)), patch(
                "analysis.llm_clients.importlib.util.find_spec",
                return_value=object(),
        ):
            client = HuggingFaceLocalLLMClient(
                model_id="Qwen/Qwen3-14B",
                task="text-generation",
                temperature=0.0,
                max_new_tokens=128,
                device="auto",
                dtype="float16",
                cache_dir="cache-dir",
                trust_remote_code=True,
            )

        self.assertTrue(client.enabled)
        self.assertEqual(client._resolve_dtype(_FakeTorch, "auto"), "auto")
        self.assertEqual(client._resolve_dtype(_FakeTorch, "float16"), "float16")
        self.assertIsNone(client._resolve_dtype(_FakeTorch, "missing"))
        with patch("analysis.llm_clients.importlib.util.find_spec", return_value=object()):
            self.assertTrue(client._accelerate_available())
        self.assertEqual(client._extract_generated_content([{"generated_text": "plain"}]), "plain")
        self.assertEqual(
            client._extract_generated_content([{"generated_text": [{"content": "assistant output"}]}]),
            "assistant output",
        )
        self.assertEqual(client._extract_generated_content([{"generated_text": ["assistant output"]}]), "assistant output")
        self.assertIsNone(client._extract_generated_content([{"generated_text": {"unexpected": "shape"}}]))
        self.assertIsNone(client._extract_generated_content([]))
        response = client.chat(system_prompt="sys", user_prompt="user")
        self.assertIsNone(response.content)

    def test_huggingface_client_handles_explicit_device_and_disabled_chat(self) -> None:
        fake_generator = _FakeGenerator()

        def fake_pipeline(**kwargs: object) -> _FakeGenerator:
            self.assertEqual(kwargs["device"], "cpu")
            return fake_generator

        with patch("analysis.llm_clients.load_transformers_runtime", return_value=(_FakeTorch, fake_pipeline)):
            client = HuggingFaceLocalLLMClient(
                model_id="Qwen/Qwen3-14B",
                task="text-generation",
                temperature=0.2,
                max_new_tokens=64,
                device="cpu",
                dtype="auto",
                cache_dir=None,
                trust_remote_code=False,
            )

        self.assertTrue(client.enabled)
        client.enabled = False
        client._generator = None
        response = client.chat(system_prompt="sys", user_prompt="user")
        self.assertFalse(response.enabled)
        self.assertIsNone(response.content)

    def test_build_llm_client_selects_expected_provider(self) -> None:
        heuristic = ResearchConfig(
            research_topic="Topic",
            search_keywords=["llm"],
            llm_provider="heuristic",
            include_pubmed=False,
        ).finalize()
        auto = ResearchConfig(
            research_topic="Topic",
            search_keywords=["llm"],
            llm_provider="auto",
            include_pubmed=False,
            api_settings={"openai_api_key": "key", "openai_model": "gpt-5.4"},
        ).finalize()
        ollama = ResearchConfig(
            research_topic="Topic",
            search_keywords=["llm"],
            llm_provider="ollama",
            include_pubmed=False,
        ).finalize()
        gemini = ResearchConfig(
            research_topic="Topic",
            search_keywords=["llm"],
            llm_provider="gemini",
            include_pubmed=False,
            api_settings={"gemini_api_key": "gem-key", "gemini_model": "gemini-2.5-flash"},
        ).finalize()

        heuristic_client = build_llm_client(heuristic)
        auto_client = build_llm_client(auto)
        ollama_client = build_llm_client(ollama)
        gemini_client = build_llm_client(gemini)

        self.assertIsInstance(heuristic_client, BaseLLMClient)
        self.assertIsInstance(auto_client, OpenAICompatibleLLMClient)
        self.assertEqual(auto_client.provider_name, "openai_compatible")
        self.assertIsInstance(ollama_client, OpenAICompatibleLLMClient)
        self.assertEqual(ollama_client.provider_name, "ollama")
        self.assertIsInstance(gemini_client, GeminiLLMClient)
        self.assertEqual(gemini_client.provider_name, "gemini")
