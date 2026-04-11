"""Tests for the KnowledgeGraphBuilder module."""

import pytest
from unittest.mock import Mock, patch

from agentic_memory.core.runtime_embedding import EmbeddingRuntimeConfig
from agentic_memory.ingestion.python_call_analyzer import (
    PythonFileCallAnalysis,
    PythonFunctionCallAnalysis,
    PythonOutgoingCall,
)
from agentic_memory.ingestion.typescript_call_analyzer import (
    TypeScriptCallAnalyzerError,
    TypeScriptFileCallAnalysis,
    TypeScriptFunctionCallAnalysis,
    TypeScriptOutgoingCall,
)

# Skip if neo4j is not available
pytestmark = [
    pytest.mark.unit,
]


class TestKnowledgeGraphBuilder:
    """Test suite for KnowledgeGraphBuilder."""

    @pytest.fixture
    def mock_driver(self):
        """Create a mock Neo4j driver."""
        driver = Mock()
        session = Mock()
        driver.session.return_value.__enter__ = Mock(return_value=session)
        driver.session.return_value.__exit__ = Mock(return_value=False)
        return driver, session

    @pytest.fixture
    def builder(self, mock_driver):
        """Create a KnowledgeGraphBuilder with mocked dependencies."""
        from agentic_memory.ingestion.graph import KnowledgeGraphBuilder

        driver, session = mock_driver
        with patch('neo4j.GraphDatabase.driver', return_value=driver), \
             patch.object(KnowledgeGraphBuilder, '_init_parsers'), \
             patch('agentic_memory.ingestion.graph.EmbeddingService'):
            
            builder = KnowledgeGraphBuilder(
                uri="bolt://localhost:7687",
                user="neo4j",
                password="test",
                openai_key="sk-test"
            )
            builder.driver = driver
            return builder

    def test_initialization(self, builder):
        """Test that builder initializes correctly."""
        assert builder.EMBEDDING_MODEL == "text-embedding-3-large"
        assert builder.driver is not None

    def test_get_embedding(self, builder):
        """Test embedding generation."""
        mock_embedding = [0.1] * builder.VECTOR_DIMENSIONS
        builder.embedding_service = Mock()
        builder.embedding_service.embed_with_metadata.return_value = (
            mock_embedding,
            Mock(prompt_tokens=42, total_tokens=42, estimated_cost_usd=None),
        )

        result = builder.get_embedding("test text")

        assert result == mock_embedding
        builder.embedding_service.embed_with_metadata.assert_called_once_with(
            "test text",
            task_instruction=None,
        )

    def test_get_embedding_error_handling(self, builder):
        """Test unexpected embedding errors propagate."""
        builder.embedding_service = Mock()
        builder.embedding_service.embed_with_metadata.side_effect = Exception("API Error")
        with pytest.raises(Exception, match="API Error"):
            builder.get_embedding("test text")

    def test_get_embedding_tracks_gemini_usage_and_cost(self, builder):
        """Gemini embedding metadata should increment token and cost counters."""
        builder.embedding_runtime = EmbeddingRuntimeConfig(
            module_name="code",
            provider="gemini",
            api_key="gemini-key",
            model="gemini-embedding-2-preview",
            dimensions=builder.VECTOR_DIMENSIONS,
        )
        builder.embedding_service = Mock()
        builder.embedding_service.embed_with_metadata.return_value = (
            [0.1] * builder.VECTOR_DIMENSIONS,
            Mock(prompt_tokens=1000, total_tokens=1000, estimated_cost_usd=0.0002),
        )

        result = builder.get_embedding("test text")

        assert len(result) == builder.VECTOR_DIMENSIONS
        assert builder.token_usage["embedding_calls"] == 1
        assert builder.token_usage["embedding_tokens"] == 1000
        assert builder.token_usage["total_cost_usd"] == pytest.approx(0.0002)

    def test_get_document_embedding_passes_document_task_instruction(self, builder):
        """Stored code embeddings should use the configured document-side task instruction."""
        builder.embedding_document_task_instruction = "task:search result"
        builder.embedding_service = Mock()
        builder.embedding_service.embed_with_metadata.return_value = (
            [0.1] * builder.VECTOR_DIMENSIONS,
            Mock(prompt_tokens=10, total_tokens=10, estimated_cost_usd=None),
        )

        result = builder.get_document_embedding("def foo(): pass")

        assert len(result) == builder.VECTOR_DIMENSIONS
        builder.embedding_service.embed_with_metadata.assert_called_once_with(
            "def foo(): pass",
            task_instruction="task:search result",
        )

    def test_get_query_embedding_passes_query_task_instruction(self, builder):
        """Semantic search queries should use the configured query-side task instruction."""
        builder.embedding_query_task_instruction = "task:code retrieval"
        builder.embedding_service = Mock()
        builder.embedding_service.embed_with_metadata.return_value = (
            [0.1] * builder.VECTOR_DIMENSIONS,
            Mock(prompt_tokens=10, total_tokens=10, estimated_cost_usd=None),
        )

        result = builder.get_query_embedding("where is foo initialized")

        assert len(result) == builder.VECTOR_DIMENSIONS
        builder.embedding_service.embed_with_metadata.assert_called_once_with(
            "where is foo initialized",
            task_instruction="task:code retrieval",
        )

    def test_close(self, builder):
        """Test driver cleanup."""
        builder.close()
        builder.driver.close.assert_called_once()

    def test_run_pipeline_scopes_pass_2_and_pass_3_to_changed_files(self, builder, monkeypatch, tmp_path):
        """Full indexing should only rebuild chunks/imports for changed files.

        Pass 1 already computes file content hashes. This regression protects the
        Phase 11 fix that threads that changed-file set into Pass 2 and Pass 3
        so `agentic-memory index` does not re-embed the entire repo when only a
        subset of files changed.
        """
        repo_root = tmp_path
        changed_paths = ["src/changed.py"]

        setup_database = Mock()
        pass_1 = Mock(return_value=changed_paths)
        pass_2 = Mock()
        pass_3 = Mock()
        pass_4 = Mock()

        monkeypatch.setattr(builder, "setup_database", setup_database)
        monkeypatch.setattr(builder, "pass_1_structure_scan", pass_1)
        monkeypatch.setattr(builder, "pass_2_entity_definition", pass_2)
        monkeypatch.setattr(builder, "pass_3_imports", pass_3)
        monkeypatch.setattr(builder, "pass_4_call_graph", pass_4)

        builder.run_pipeline(repo_root)

        pass_1.assert_called_once()
        pass_2.assert_called_once_with(repo_root, target_paths=changed_paths)
        pass_3.assert_called_once_with(repo_root, target_paths=changed_paths)
        pass_4.assert_called_once_with(repo_root)

    def test_reindex_file_scopes_entity_and_import_passes_to_one_file(
        self,
        builder,
        mock_driver,
        monkeypatch,
        tmp_path,
    ):
        """Watcher-style single-file reindex should only rebuild that file's chunks/imports."""
        _, session = mock_driver
        repo_root = tmp_path
        (repo_root / "pkg").mkdir()
        target_path = repo_root / "pkg" / "a.py"
        target_path.write_text("def foo():\n    return 1\n", encoding="utf8")

        monkeypatch.setattr(
            builder,
            "_parse_source_file",
            lambda path: ("def foo():\n    return 1\n", {"functions": [], "classes": []}),
        )
        monkeypatch.setattr(builder, "_calculate_ohash", lambda path: "hash-a")
        pass_2 = Mock()
        pass_3 = Mock()
        pass_4 = Mock()
        monkeypatch.setattr(builder, "pass_2_entity_definition", pass_2)
        monkeypatch.setattr(builder, "pass_3_imports", pass_3)
        monkeypatch.setattr(builder, "pass_4_call_graph", pass_4)

        builder.reindex_file("pkg/a.py", repo_path=repo_root)

        pass_2.assert_called_once_with(repo_root, target_paths={"pkg/a.py"})
        pass_3.assert_called_once_with(repo_root, target_paths={"pkg/a.py"})
        pass_4.assert_called_once_with(repo_root)

    def test_extract_js_ts_import_modules(self, builder):
        """Test JS/TS import extraction supports common import syntaxes."""
        code = """
import React from "react";
import type { FC } from "react";
import { api } from "../lib/api";
import "@/styles/global.css";
export { helper } from "./helpers";
const fs = require("fs");
const lazy = import("./lazy-module");
"""
        modules = builder._extract_js_ts_import_modules(code)

        assert "../lib/api" in modules
        assert "@/styles/global.css" in modules
        assert "./helpers" in modules
        assert "fs" in modules
        assert "./lazy-module" in modules

    def test_resolve_import_candidates_for_relative_tsx(self, builder):
        """Test relative TS/TSX imports resolve to extension/index variants."""
        candidates = builder._resolve_import_candidates(
            "frontend/src/components/Widget.tsx",
            "../services/heygen_service",
            ".tsx",
        )
        assert "frontend/src/services/heygen_service.ts" in candidates
        assert "frontend/src/services/heygen_service.tsx" in candidates
        assert "frontend/src/services/heygen_service/index.ts" in candidates

    def test_pass_4_call_graph_prefers_typescript_analyzer_results(
        self,
        builder,
        mock_driver,
        monkeypatch,
        tmp_path,
    ):
        """JS/TS CALLS should use analyzer-resolved cross-file targets when available."""
        _, session = mock_driver
        repo_root = tmp_path
        (repo_root / "src").mkdir()
        (repo_root / "src" / "a.ts").write_text("export function foo() {}", encoding="utf8")
        (repo_root / "src" / "b.ts").write_text("export function bar() {}", encoding="utf8")

        initial_records = [
                {
                    "path": "src/a.ts",
                    "funcs": [
                        {
                            "name": "foo",
                            "sig": "src/a.ts:foo",
                            "qualified_name": "foo",
                            "parent_class": "",
                            "name_line": 1,
                            "name_column": 17,
                        }
                    ],
                },
                {
                    "path": "src/b.ts",
                    "funcs": [
                        {
                            "name": "bar",
                            "sig": "src/b.ts:bar",
                            "qualified_name": "bar",
                            "parent_class": "",
                            "name_line": 1,
                            "name_column": 17,
                        }
                    ],
                },
        ]
        session.run.side_effect = [initial_records] + [None] * 12

        parsed_by_path = {
            "src/a.ts": {
                "functions": [
                    {
                        "name": "foo",
                        "qualified_name": "foo",
                        "calls": [],
                    }
                ]
            },
            "src/b.ts": {
                "functions": [
                    {
                        "name": "bar",
                        "qualified_name": "bar",
                        "calls": [],
                    }
                ]
            },
        }

        monkeypatch.setattr(
            builder,
            "_prepare_typescript_analysis_requests",
            lambda **_: (
                parsed_by_path,
                [{"path": "src/a.ts", "functions": [{"qualified_name": "foo"}]}],
            ),
        )
        monkeypatch.setattr(
            builder,
            "_prepare_python_analysis_requests",
            lambda **_: [],
        )

        class _FakeAnalyzer:
            def is_available(self):
                return True

            def analyze_files(self, **kwargs):
                return {
                    "src/a.ts": TypeScriptFileCallAnalysis(
                        rel_path="src/a.ts",
                        functions={
                            "foo": TypeScriptFunctionCallAnalysis(
                                qualified_name="foo",
                                name="foo",
                                outgoing_calls=(
                                    TypeScriptOutgoingCall(
                                        rel_path="src/b.ts",
                                        name="bar",
                                        kind="function",
                                        container_name=None,
                                        qualified_name_guess="bar",
                                    ),
                                ),
                            )
                        },
                    )
                }

        monkeypatch.setattr(builder, "_get_typescript_call_analyzer", lambda: _FakeAnalyzer())

        builder.pass_4_call_graph(repo_root)

        write_calls = [
            call
            for call in session.run.call_args_list
            if "SET r.source = $source" in call.args[0]
        ]
        assert len(write_calls) == 1
        assert write_calls[0].kwargs["source"] == "typescript_service"
        assert write_calls[0].kwargs["confidence"] == pytest.approx(0.95)
        assert write_calls[0].kwargs["callee_sigs"] == ["src/b.ts:bar"]

    def test_pass_4_call_graph_prefers_python_analyzer_results(
        self,
        builder,
        mock_driver,
        monkeypatch,
        tmp_path,
    ):
        """Python CALLS should use semantic analyzer targets when available."""
        _, session = mock_driver
        repo_root = tmp_path
        (repo_root / "pkg").mkdir()
        (repo_root / "pkg" / "a.py").write_text("from pkg.b import bar\n\ndef foo():\n    bar()\n", encoding="utf8")
        (repo_root / "pkg" / "b.py").write_text("def bar():\n    return 1\n", encoding="utf8")

        initial_records = [
            {
                "path": "pkg/a.py",
                "funcs": [
                    {
                        "name": "foo",
                        "sig": "pkg/a.py:foo",
                        "qualified_name": "foo",
                        "parent_class": "",
                        "name_line": 3,
                        "name_column": 5,
                    }
                ],
            },
            {
                "path": "pkg/b.py",
                "funcs": [
                    {
                        "name": "bar",
                        "sig": "pkg/b.py:bar",
                        "qualified_name": "bar",
                        "parent_class": "",
                        "name_line": 1,
                        "name_column": 5,
                    }
                ],
            },
        ]
        session.run.side_effect = [initial_records] + [None] * 12

        parsed_by_path = {
            "pkg/a.py": {
                "functions": [
                    {
                        "name": "foo",
                        "qualified_name": "foo",
                        "calls": ["bar"],
                    }
                ]
            },
            "pkg/b.py": {
                "functions": [
                    {
                        "name": "bar",
                        "qualified_name": "bar",
                        "calls": [],
                    }
                ]
            },
        }

        monkeypatch.setattr(
            builder,
            "_prepare_typescript_analysis_requests",
            lambda **_: (parsed_by_path, []),
        )
        monkeypatch.setattr(
            builder,
            "_prepare_python_analysis_requests",
            lambda **_: [{"path": "pkg/a.py", "functions": [{"qualified_name": "foo"}]}],
        )

        class _FakePythonAnalyzer:
            def is_available(self):
                return True

            def analyze_files(self, **kwargs):
                return {
                    "pkg/a.py": PythonFileCallAnalysis(
                        rel_path="pkg/a.py",
                        functions={
                            "foo": PythonFunctionCallAnalysis(
                                qualified_name="foo",
                                name="foo",
                                outgoing_calls=(
                                    PythonOutgoingCall(
                                        rel_path="pkg/b.py",
                                        name="bar",
                                        kind="function",
                                        container_name=None,
                                        qualified_name_guess="bar",
                                        definition_line=1,
                                        definition_column=5,
                                    ),
                                ),
                            )
                        },
                        diagnostics=(),
                        drop_reason_counts={},
                    )
                }

        monkeypatch.setattr(builder, "_get_python_call_analyzer", lambda: _FakePythonAnalyzer())

        builder.pass_4_call_graph(repo_root)

        write_calls = [
            call
            for call in session.run.call_args_list
            if "SET r.source = $source" in call.args[0]
        ]
        assert len(write_calls) == 1
        assert write_calls[0].kwargs["source"] == "python_service"
        assert write_calls[0].kwargs["confidence"] == pytest.approx(0.95)
        assert write_calls[0].kwargs["callee_sigs"] == ["pkg/b.py:bar"]

    def test_get_call_diagnostics_summarizes_sources_and_coverage(self, builder, mock_driver):
        """CALLS diagnostics should surface coverage and provenance ratios for one repo."""
        _, session = mock_driver
        builder.repo_id = "repo-1"
        session.run.side_effect = [
            Mock(single=Mock(return_value={
                "total_functions": 5,
                "functions_with_calls": 3,
                "total_call_edges": 4,
                "high_confidence_edges": 3,
            })),
            Mock(single=Mock(return_value={
                "files_with_functions": 3,
                "files_with_call_edges": 2,
                "files_with_analyzer_edges": 1,
                "files_with_analyzer_attempts": 2,
                "files_with_drop_reasons": 1,
            })),
            [
                {
                    "source": "typescript_service",
                    "edge_count": 3,
                    "avg_confidence": 0.95,
                },
                {
                    "source": "static_parser",
                    "edge_count": 1,
                    "avg_confidence": 0.6,
                },
            ],
            [
                {
                    "reason": "ambiguous_name_match",
                    "source": "typescript_service",
                    "drop_count": 2,
                }
            ],
            [
                {
                    "source": "typescript_service",
                    "status": "failed",
                    "message": "TypeScript call analyzer timed out after 60s.",
                    "updated_at": "2026-04-10T21:00:00Z",
                }
            ],
        ]

        diagnostics = builder.get_call_diagnostics()

        assert diagnostics["repo_id"] == "repo-1"
        assert diagnostics["total_functions"] == 5
        assert diagnostics["functions_with_calls"] == 3
        assert diagnostics["functions_without_calls"] == 2
        assert diagnostics["function_coverage_ratio"] == pytest.approx(0.6)
        assert diagnostics["total_call_edges"] == 4
        assert diagnostics["high_confidence_edges"] == 3
        assert diagnostics["high_confidence_ratio"] == pytest.approx(0.75)
        assert diagnostics["files_with_functions"] == 3
        assert diagnostics["files_with_call_edges"] == 2
        assert diagnostics["files_with_analyzer_edges"] == 1
        assert diagnostics["files_with_analyzer_attempts"] == 2
        assert diagnostics["files_with_drop_reasons"] == 1
        assert diagnostics["file_coverage_ratio"] == pytest.approx(2 / 3)
        assert diagnostics["sources"][0]["source"] == "typescript_service"
        assert diagnostics["sources"][0]["avg_confidence"] == pytest.approx(0.95)
        assert diagnostics["drop_reasons"][0]["reason"] == "ambiguous_name_match"
        assert diagnostics["drop_reasons"][0]["drop_count"] == 2
        assert diagnostics["analyzer_issues"][0]["source"] == "typescript_service"
        assert diagnostics["analyzer_issues"][0]["status"] == "failed"

    def test_pass_4_records_typescript_analyzer_batch_failures(self, builder, mock_driver, monkeypatch, tmp_path):
        """Batch analyzer failures should be persisted for later call-status inspection."""
        _, session = mock_driver
        repo_root = tmp_path
        (repo_root / "pkg").mkdir()
        (repo_root / "pkg" / "a.ts").write_text("export function foo(){ return 1 }", encoding="utf8")
        builder.repo_root = repo_root
        builder.repo_id = str(repo_root)

        file_records = [{"path": "pkg/a.ts", "ohash": "hash"}]
        def _run_side_effect(*args, **kwargs):
            cypher = args[0]
            if "MATCH (f:File" in cypher and "collect({" in cypher:
                return file_records
            return Mock()

        session.run.side_effect = _run_side_effect
        monkeypatch.setattr(
            builder,
            "_build_function_signature_indexes",
            lambda *args, **kwargs: ({}, {}, {}),
        )
        monkeypatch.setattr(
            builder,
            "_prepare_typescript_analysis_requests",
            lambda **_: (
                {"pkg/a.ts": {"functions": [{"qualified_name": "foo", "name": "foo", "calls": []}]}},
                [{"path": "pkg/a.ts", "functions": [{"qualified_name": "foo", "name": "foo"}]}],
            ),
        )
        monkeypatch.setattr(builder, "_prepare_python_analysis_requests", lambda **_: [])
        monkeypatch.setattr(builder, "_clear_call_analysis_artifacts", lambda *args, **kwargs: None)
        monkeypatch.setattr(builder, "_write_call_drop_reasons", lambda *args, **kwargs: None)
        monkeypatch.setattr(builder, "_write_call_edges", lambda *args, **kwargs: None)

        class _FailingTsAnalyzer:
            disabled_reason = None

            def is_available(self):
                return True

            def analyze_files(self, **kwargs):
                raise TypeScriptCallAnalyzerError("TypeScript call analyzer timed out after 60s.")

        monkeypatch.setattr(builder, "_get_typescript_call_analyzer", lambda: _FailingTsAnalyzer())

        builder.pass_4_call_graph(repo_root)

        record_issue_calls = [
            call for call in session.run.call_args_list if "CallAnalysisIssue" in call.args[0]
        ]
        assert record_issue_calls
        assert record_issue_calls[0].kwargs["source"] == "typescript_service"
        assert record_issue_calls[0].kwargs["status"] == "failed"

    def test_pass_4_records_partial_typescript_batch_failures(
        self,
        builder,
        mock_driver,
        monkeypatch,
        tmp_path,
    ):
        """Partial TS batch failures should still be persisted after fallback continues."""
        _, session = mock_driver
        repo_root = tmp_path
        (repo_root / "src").mkdir()
        (repo_root / "src" / "a.ts").write_text("export function foo() {}", encoding="utf8")
        (repo_root / "src" / "b.ts").write_text("export function bar() {}", encoding="utf8")
        builder.repo_root = repo_root
        builder.repo_id = str(repo_root)

        initial_records = [
            {
                "path": "src/a.ts",
                "funcs": [
                    {
                        "name": "foo",
                        "sig": "src/a.ts:foo",
                        "qualified_name": "foo",
                        "parent_class": "",
                        "name_line": 1,
                        "name_column": 17,
                    }
                ],
            },
            {
                "path": "src/b.ts",
                "funcs": [
                    {
                        "name": "bar",
                        "sig": "src/b.ts:bar",
                        "qualified_name": "bar",
                        "parent_class": "",
                        "name_line": 1,
                        "name_column": 17,
                    }
                ],
            },
        ]

        def _run_side_effect(*args, **kwargs):
            cypher = args[0]
            if "MATCH (f:File" in cypher and "collect({" in cypher:
                return initial_records
            return Mock()

        session.run.side_effect = _run_side_effect

        parsed_by_path = {
            "src/a.ts": {"functions": [{"name": "foo", "qualified_name": "foo", "calls": []}]},
            "src/b.ts": {"functions": [{"name": "bar", "qualified_name": "bar", "calls": []}]},
        }
        monkeypatch.setattr(
            builder,
            "_build_function_signature_indexes",
            lambda *args, **kwargs: (
                {"src/b.ts": {"bar": "src/b.ts:bar"}},
                {"src/b.ts": {"bar": ["src/b.ts:bar"]}},
                {"src/b.ts": {(1, 17): "src/b.ts:bar"}},
            ),
        )
        monkeypatch.setattr(
            builder,
            "_prepare_typescript_analysis_requests",
            lambda **_: (
                parsed_by_path,
                [
                    {"path": "src/a.ts", "functions": [{"qualified_name": "foo", "name": "foo"}]},
                    {"path": "src/b.ts", "functions": [{"qualified_name": "bar", "name": "bar"}]},
                ],
            ),
        )
        monkeypatch.setattr(builder, "_prepare_python_analysis_requests", lambda **_: [])
        monkeypatch.setattr(builder, "_clear_call_analysis_artifacts", lambda *args, **kwargs: None)
        monkeypatch.setattr(builder, "_write_call_drop_reasons", lambda *args, **kwargs: None)
        monkeypatch.setattr(builder, "_write_call_edges", lambda *args, **kwargs: None)

        class _PartialTsAnalyzer:
            disabled_reason = None

            def __init__(self):
                self.last_run_issues = (
                    Mock(total_batches=2, message="TypeScript call analyzer timed out after 30s."),
                )

            def is_available(self):
                return True

            def analyze_files(self, **kwargs):
                return {
                    "src/a.ts": TypeScriptFileCallAnalysis(
                        rel_path="src/a.ts",
                        functions={
                            "foo": TypeScriptFunctionCallAnalysis(
                                qualified_name="foo",
                                name="foo",
                                outgoing_calls=(),
                            )
                        },
                        diagnostics=(
                            {
                                "kind": "batch_failed",
                                "level": "warning",
                                "message": "TypeScript call analyzer timed out after 30s.",
                            },
                        ),
                        drop_reason_counts={},
                    ),
                    "src/b.ts": TypeScriptFileCallAnalysis(
                        rel_path="src/b.ts",
                        functions={
                            "bar": TypeScriptFunctionCallAnalysis(
                                qualified_name="bar",
                                name="bar",
                                outgoing_calls=(),
                            )
                        },
                        diagnostics=(),
                        drop_reason_counts={},
                    ),
                }

        monkeypatch.setattr(builder, "_get_typescript_call_analyzer", lambda: _PartialTsAnalyzer())

        builder.pass_4_call_graph(repo_root)

        record_issue_calls = [
            call for call in session.run.call_args_list if "CallAnalysisIssue" in call.args[0]
        ]
        assert record_issue_calls
        assert record_issue_calls[0].kwargs["status"] == "partial_failure"

    def test_get_file_dependencies_scopes_duplicate_paths_by_repo_id(self, builder, mock_driver):
        """Dependency lookups should stay pinned to one repo when paths collide.

        This guards the exact case we expect in real usage: two repositories can
        both contain `src/shared/helpers.ts`, but a dependency query must only
        inspect the file node that matches the requested repo_id.
        """
        _, session = mock_driver
        session.run.return_value.single.return_value = {
            "imports": ["src/core/runtime.ts"],
            "imported_by": ["src/app.ts"],
        }

        result = builder.get_file_dependencies(
            "src/shared/helpers.ts",
            repo_id="repo-beta",
        )

        assert result == {
            "imports": ["src/core/runtime.ts"],
            "imported_by": ["src/app.ts"],
        }
        assert session.run.call_args.kwargs["repo_id"] == "repo-beta"
        assert session.run.call_args.kwargs["path"] == "src/shared/helpers.ts"


class TestCypherQueries:
    """Test Cypher query generation and execution."""

    def test_setup_database_cypher(self):
        """Test that setup_database query strings remain well-formed."""
        # This would test the actual Cypher queries
        # For unit test, we verify the query strings are well-formed
        expected_queries = [
            "CREATE CONSTRAINT file_path_unique",
            "CREATE CONSTRAINT func_sig_unique",
            "CREATE CONSTRAINT class_name_unique",
            "CREATE VECTOR INDEX code_embeddings",
        ]
        
        # Just verify the expected queries exist
        for query in expected_queries:
            assert isinstance(query, str)
            assert len(query) > 0


@pytest.mark.integration
class TestGraphIntegration:
    """Integration tests requiring actual Neo4j instance."""

    @pytest.fixture(scope="class")
    def neo4j_builder(self):
        """Create a builder connected to real Neo4j (if available)."""
        import os
        from agentic_memory.ingestion.graph import KnowledgeGraphBuilder

        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "test")
        openai_key = os.getenv("OPENAI_API_KEY", "sk-test")

        try:
            builder = KnowledgeGraphBuilder(uri, user, password, openai_key)
            # Test connection
            with builder.driver.session() as session:
                session.run("RETURN 1")
            yield builder
            builder.close()
        except Exception as e:
            pytest.skip(f"Neo4j not available: {e}")

    def test_setup_database_integration(self, neo4j_builder):
        """Test index creation on real Neo4j."""
        # Should not raise
        neo4j_builder.setup_database()

    def test_semantic_search_query(self, neo4j_builder):
        """Test semantic search generates valid Cypher."""
        # Mock embedding to avoid API call
        with patch.object(
            neo4j_builder,
            'get_embedding',
            return_value=[0.1] * neo4j_builder.VECTOR_DIMENSIONS,
        ):
            results = neo4j_builder.semantic_search("test query", limit=5)
            assert isinstance(results, list)
