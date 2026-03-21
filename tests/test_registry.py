"""Unit tests for source registry."""

import pytest

from codememory.core.registry import SOURCE_REGISTRY, register_source


@pytest.fixture(autouse=True)
def clear_registry():
    """Clear SOURCE_REGISTRY before each test to ensure isolation."""
    SOURCE_REGISTRY.clear()
    yield
    SOURCE_REGISTRY.clear()


@pytest.mark.unit
def test_register_source():
    """register_source stores labels under the given source_key."""
    register_source("code_treesitter", ["Memory", "Code", "Chunk"])
    assert SOURCE_REGISTRY["code_treesitter"] == ["Memory", "Code", "Chunk"]


@pytest.mark.unit
def test_register_multiple_sources():
    """Registering two sources keeps both entries in SOURCE_REGISTRY."""
    register_source("code_treesitter", ["Memory", "Code", "Chunk"])
    register_source("web_crawler", ["Memory", "Research", "Page"])
    assert SOURCE_REGISTRY["code_treesitter"] == ["Memory", "Code", "Chunk"]
    assert SOURCE_REGISTRY["web_crawler"] == ["Memory", "Research", "Page"]


@pytest.mark.unit
def test_overwrite_source():
    """Re-registering the same key overwrites the previous label list."""
    register_source("code_treesitter", ["Memory", "Code", "Chunk"])
    register_source("code_treesitter", ["Memory", "Code", "File"])
    assert SOURCE_REGISTRY["code_treesitter"] == ["Memory", "Code", "File"]


@pytest.mark.unit
def test_unregistered_key():
    """Accessing an unregistered key returns None via .get()."""
    assert SOURCE_REGISTRY.get("nonexistent") is None
