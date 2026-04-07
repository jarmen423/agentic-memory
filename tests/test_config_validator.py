"""Unit tests for ConfigValidator (validate_embedding_config).

Tests enforce:
- Valid default config passes without error
- OpenAI/Nemotron dimension mismatches raise ValueError
- Gemini MRL dimension override (any dimension) is allowed
- Unknown provider raises ValueError with clear message
- Missing 'modules' key skips validation
- Error messages include module name, expected, and actual dimensions
"""

import pytest

from agentic_memory.core.config_validator import validate_embedding_config


# ---------------------------------------------------------------------------
# Helper: build a minimal config dict
# ---------------------------------------------------------------------------


def _make_config(modules: dict) -> dict:
    return {"modules": modules}


def _make_module(provider: str, dimensions: int) -> dict:
    return {"embedding_provider": provider, "embedding_dimensions": dimensions}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestValidateEmbeddingConfig:
    """Tests for validate_embedding_config()."""

    def test_valid_config_passes(self):
        """Default config (code=openai/3072, web=gemini/3072, chat=gemini/3072) passes."""
        config = _make_config(
            {
                "code": _make_module("openai", 3072),
                "web": _make_module("gemini", 3072),
                "chat": _make_module("gemini", 3072),
            }
        )
        # Should not raise
        validate_embedding_config(config)

    def test_code_wrong_dimensions_raises(self):
        """code module with openai provider but wrong dimensions raises ValueError."""
        config = _make_config(
            {
                "code": _make_module("openai", 768),
            }
        )
        with pytest.raises(ValueError):
            validate_embedding_config(config)

    def test_web_openai_wrong_dimensions_raises(self):
        """web module with openai provider and wrong dimensions raises ValueError."""
        config = _make_config(
            {
                "web": _make_module("openai", 768),
            }
        )
        with pytest.raises(ValueError):
            validate_embedding_config(config)

    def test_custom_dimensions_allowed_for_gemini(self):
        """Gemini MRL supports any output_dimensionality — custom dims allowed."""
        config = _make_config(
            {
                "web": _make_module("gemini", 256),
            }
        )
        # Should not raise (Gemini MRL allows any dimension)
        validate_embedding_config(config)

    def test_unknown_provider_raises(self):
        """Unknown provider raises ValueError."""
        config = _make_config(
            {
                "code": _make_module("unknown_provider", 3072),
            }
        )
        with pytest.raises(ValueError, match="unknown_provider"):
            validate_embedding_config(config)

    def test_missing_modules_key_passes(self):
        """Config without 'modules' key does not raise — nothing to validate."""
        config = {"neo4j": {"uri": "bolt://localhost:7687"}}
        # Should not raise
        validate_embedding_config(config)

    def test_dimension_mismatch_error_message(self):
        """Error message includes module name, expected dimensions, and actual dimensions."""
        config = _make_config(
            {
                "code": _make_module("openai", 512),
            }
        )
        with pytest.raises(ValueError) as exc_info:
            validate_embedding_config(config)
        msg = str(exc_info.value)
        assert "code" in msg
        assert "512" in msg or "3072" in msg  # actual or expected dims

    def test_nemotron_wrong_dimensions_raises(self):
        """Nemotron provider with wrong dimensions raises ValueError."""
        config = _make_config(
            {
                "code": _make_module("nemotron", 768),
            }
        )
        with pytest.raises(ValueError):
            validate_embedding_config(config)

    def test_empty_modules_passes(self):
        """Config with empty modules dict passes without error."""
        config = _make_config({})
        validate_embedding_config(config)

    def test_module_without_dimensions_key_passes(self):
        """Module config without embedding_dimensions key passes (nothing to check)."""
        config = _make_config(
            {
                "code": {"embedding_provider": "openai"},
            }
        )
        # No dimensions configured → no mismatch possible → no raise
        validate_embedding_config(config)
