"""Shared configuration and client helpers for extraction-oriented LLM calls."""

from __future__ import annotations

import os
from dataclasses import dataclass

from openai import OpenAI


@dataclass(frozen=True)
class ExtractionLLMConfig:
    """Resolved provider settings for entity/claim extraction workloads."""

    provider: str
    model: str
    api_key: str | None
    base_url: str | None = None


_PROVIDER_DEFAULTS: dict[str, dict[str, str | tuple[str, ...] | None]] = {
    "groq": {
        "model": "llama-3.3-70b-versatile",
        "base_url": "https://api.groq.com/openai/v1",
        "api_envs": ("GROQ_API_KEY",),
    },
    "cerebras": {
        "model": "gpt-oss-120b",
        "base_url": "https://api.cerebras.ai/v1",
        "api_envs": ("CEREBRAS_API_KEY",),
    },
    "openai": {
        "model": "gpt-4o-mini",
        "base_url": None,
        "api_envs": ("OPENAI_API_KEY",),
    },
    "gemini": {
        "model": "gemini-2.5-flash",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_envs": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    },
}


def resolve_extraction_llm_config(
    *,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> ExtractionLLMConfig:
    """Resolve extraction LLM settings from explicit values plus env fallbacks."""

    resolved_provider = (
        provider
        or os.getenv("EXTRACTION_LLM_PROVIDER")
        or "groq"
    ).strip().lower()
    if resolved_provider not in _PROVIDER_DEFAULTS:
        supported = ", ".join(sorted(_PROVIDER_DEFAULTS))
        raise ValueError(
            f"Unsupported extraction LLM provider '{resolved_provider}'. "
            f"Must be one of: {supported}"
        )

    defaults = _PROVIDER_DEFAULTS[resolved_provider]

    resolved_model = (
        model
        or os.getenv("EXTRACTION_LLM_MODEL")
        or (
            os.getenv("GROQ_MODEL")
            if resolved_provider == "groq"
            else None
        )
        or str(defaults["model"])
    )
    resolved_base_url = (
        base_url
        or os.getenv("EXTRACTION_LLM_BASE_URL")
        or (str(defaults["base_url"]) if defaults["base_url"] else None)
    )

    resolved_api_key = api_key or os.getenv("EXTRACTION_LLM_API_KEY")
    if not resolved_api_key:
        for env_name in defaults["api_envs"] or ():
            candidate = os.getenv(str(env_name))
            if candidate:
                resolved_api_key = candidate
                break

    return ExtractionLLMConfig(
        provider=resolved_provider,
        model=resolved_model,
        api_key=resolved_api_key,
        base_url=resolved_base_url,
    )


def build_extraction_openai_client(config: ExtractionLLMConfig) -> OpenAI:
    """Build an OpenAI-compatible client for the resolved extraction provider."""

    if not config.api_key:
        raise ValueError(
            "No API key resolved for extraction LLM provider "
            f"'{config.provider}'. Set EXTRACTION_LLM_API_KEY or the "
            "provider-specific API key env var."
        )
    if config.base_url:
        return OpenAI(api_key=config.api_key, base_url=config.base_url)
    return OpenAI(api_key=config.api_key)
