"""Tests for config-driven embedding runtime resolution."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from codememory.config import Config
from codememory.core.runtime_embedding import build_embedding_service, resolve_embedding_runtime


def _write_config(repo_root: Path, payload: dict) -> Config:
    config = Config(repo_root)
    config.config_dir.mkdir(parents=True, exist_ok=True)
    config.config_file.write_text(json.dumps(payload), encoding="utf-8")
    return config


def test_resolve_embedding_runtime_preserves_default_web_behavior(tmp_path):
    """Default config still resolves web embeddings to Gemini settings."""
    config = Config(tmp_path)

    runtime = resolve_embedding_runtime("web", config=config)

    assert runtime.module_name == "web"
    assert runtime.provider == "gemini"
    assert runtime.model == "gemini-embedding-2-preview"
    assert runtime.dimensions == 3072
    assert runtime.base_url is None


def test_build_embedding_service_uses_nemotron_from_module_env(monkeypatch, tmp_path):
    """Module-scoped env overrides can switch a live path to Nemotron."""
    monkeypatch.setenv("WEB_EMBEDDING_PROVIDER", "nemotron")
    monkeypatch.setenv("WEB_EMBEDDING_MODEL", "nvidia/custom-embed")
    monkeypatch.setenv("WEB_EMBEDDING_BASE_URL", "https://nim.example/v1")
    monkeypatch.setenv("WEB_EMBEDDING_DIMENSIONS", "4096")
    monkeypatch.setenv("NVIDIA_API_KEY", "nim-key")

    with patch("codememory.core.runtime_embedding.EmbeddingService") as mock_service:
        build_embedding_service("web", config=Config(tmp_path))

    mock_service.assert_called_once_with(
        provider="nemotron",
        api_key="nim-key",
        model="nvidia/custom-embed",
        base_url="https://nim.example/v1",
        output_dimensions=4096,
    )


def test_resolve_embedding_runtime_allows_global_env_override_then_falls_back_to_repo_config(
    tmp_path, monkeypatch
):
    """Global env override wins first, then repo config takes over once removed."""
    config = _write_config(
        tmp_path,
        {
            "modules": {
                "code": {
                    "embedding_provider": "openai",
                    "embedding_model": "text-embedding-3-small",
                    "embedding_dimensions": 1536,
                },
                "web": {
                    "embedding_provider": "gemini",
                    "embedding_model": "gemini-embedding-2-preview",
                    "embedding_dimensions": 3072,
                },
                "chat": {
                    "embedding_provider": "gemini",
                    "embedding_model": "gemini-embedding-2-preview",
                    "embedding_dimensions": 3072,
                },
            },
            "openai": {"api_key": "repo-openai-key"},
        },
    )
    monkeypatch.setenv("EMBEDDING_PROVIDER", "nemotron")

    runtime = resolve_embedding_runtime("code", config=config)

    assert runtime.provider == "nemotron"

    monkeypatch.delenv("EMBEDDING_PROVIDER")
    runtime = resolve_embedding_runtime("code", config=config)
    assert runtime.provider == "openai"
    assert runtime.model == "text-embedding-3-small"
    assert runtime.dimensions == 1536
    assert runtime.api_key == "repo-openai-key"


def test_embedding_runtime_is_independent_from_extraction_provider(monkeypatch, tmp_path):
    """Extraction env overrides do not alter embedding provider resolution."""
    monkeypatch.setenv("EXTRACTION_LLM_PROVIDER", "cerebras")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")

    runtime = resolve_embedding_runtime("chat", config=Config(tmp_path))

    assert runtime.provider == "gemini"
    assert runtime.api_key == "gemini-key"
