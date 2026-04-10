"""Runtime resolution helpers for module embedding providers."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from codememory.config import Config, find_repo_root
from codememory.core.embedding import EmbeddingService


@dataclass(frozen=True)
class EmbeddingRuntimeConfig:
    """Resolved runtime settings for a module embedding service."""

    module_name: str
    provider: str
    api_key: str | None
    model: str
    dimensions: int
    base_url: str | None = None


_PROVIDER_DEFAULTS: dict[str, dict[str, object]] = {
    "openai": {
        "model": "text-embedding-3-large",
        "dimensions": 3072,
        "base_url": None,
        "api_envs": ("OPENAI_API_KEY",),
    },
    "gemini": {
        "model": "gemini-embedding-2-preview",
        "dimensions": 3072,
        "base_url": None,
        "api_envs": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    },
    "nemotron": {
        "model": "nvidia/nv-embedqa-e5-v5",
        "dimensions": 4096,
        "base_url": "https://integrate.api.nvidia.com/v1",
        "api_envs": ("NVIDIA_API_KEY", "NEMOTRON_API_KEY"),
    },
}


def _repo_config(config: Config | None = None, repo_root: Path | None = None) -> Config:
    """Return a config object using the explicit or detected repository root."""
    if config is not None:
        return config
    resolved_root = repo_root or find_repo_root() or Path.cwd()
    return Config(resolved_root)


def _env_override(module_name: str, suffix: str) -> str | None:
    """Resolve module-specific env vars before global embedding env vars."""
    module_prefix = module_name.strip().upper()
    return os.getenv(f"{module_prefix}_EMBEDDING_{suffix}") or os.getenv(
        f"EMBEDDING_{suffix}"
    )


def _provider_api_key(provider: str, config: Config) -> str | None:
    """Resolve provider API key from config or provider-specific env vars."""
    provider_cfg = config.get_embedding_provider_config(provider)
    configured_key = provider_cfg.get("api_key")
    if configured_key:
        return str(configured_key)

    for env_name in _PROVIDER_DEFAULTS[provider]["api_envs"] or ():
        candidate = os.getenv(str(env_name))
        if candidate:
            return candidate
    return None


def resolve_embedding_runtime(
    module_name: str,
    *,
    config: Config | None = None,
    repo_root: Path | None = None,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    output_dimensions: int | None = None,
) -> EmbeddingRuntimeConfig:
    """Resolve embedding provider settings for one module from config and env."""
    cfg = _repo_config(config=config, repo_root=repo_root)
    module_cfg = cfg.get_module_config(module_name)
    configured_provider = str(module_cfg.get("embedding_provider") or "").strip().lower()
    provider_override = provider or _env_override(module_name, "PROVIDER")

    resolved_provider = (
        provider_override
        or module_cfg.get("embedding_provider")
        or "gemini"
    ).strip().lower()
    if resolved_provider not in _PROVIDER_DEFAULTS:
        supported = ", ".join(sorted(_PROVIDER_DEFAULTS))
        raise ValueError(
            f"Unsupported embedding provider '{resolved_provider}'. "
            f"Must be one of: {supported}"
        )

    provider_overridden = bool(provider_override) and resolved_provider != configured_provider
    provider_defaults = _PROVIDER_DEFAULTS[resolved_provider]
    resolved_model = (
        model
        or _env_override(module_name, "MODEL")
        or (None if provider_overridden else module_cfg.get("embedding_model"))
        or str(provider_defaults["model"])
    )
    resolved_dimensions = output_dimensions
    if resolved_dimensions is None:
        env_dimensions = _env_override(module_name, "DIMENSIONS")
        if env_dimensions:
            resolved_dimensions = int(env_dimensions)
        else:
            resolved_dimensions = int(
                (None if provider_overridden else module_cfg.get("embedding_dimensions"))
                or provider_defaults["dimensions"]
            )

    resolved_base_url = (
        base_url
        or _env_override(module_name, "BASE_URL")
        or cfg.get_embedding_provider_config(resolved_provider).get("base_url")
        or provider_defaults["base_url"]
    )
    resolved_api_key = (
        api_key
        or _env_override(module_name, "API_KEY")
        or _provider_api_key(resolved_provider, cfg)
    )

    return EmbeddingRuntimeConfig(
        module_name=module_name,
        provider=resolved_provider,
        api_key=resolved_api_key,
        model=str(resolved_model),
        dimensions=int(resolved_dimensions),
        base_url=str(resolved_base_url) if resolved_base_url else None,
    )


def build_embedding_service(
    module_name: str,
    *,
    config: Config | None = None,
    repo_root: Path | None = None,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    output_dimensions: int | None = None,
) -> EmbeddingService:
    """Build an EmbeddingService using the shared runtime resolver."""
    runtime = resolve_embedding_runtime(
        module_name,
        config=config,
        repo_root=repo_root,
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        output_dimensions=output_dimensions,
    )
    if not runtime.api_key:
        raise ValueError(
            f"No API key resolved for embedding provider '{runtime.provider}' "
            f"for module '{module_name}'."
        )
    return EmbeddingService(
        provider=runtime.provider,
        api_key=runtime.api_key,
        model=runtime.model,
        base_url=runtime.base_url,
        output_dimensions=runtime.dimensions,
    )
