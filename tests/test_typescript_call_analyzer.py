"""Integration-style tests for the TypeScript semantic call analyzer.

These tests intentionally exercise the real Node helper against tiny temporary
repositories. They prove that the local TypeScript stack can resolve cross-file
function and method calls before the graph layer starts trusting those results.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from agentic_memory.ingestion.parser import CodeParser
from agentic_memory.ingestion.typescript_call_analyzer import (
    TypeScriptCallAnalyzer,
    TypeScriptCallAnalyzerError,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "code_graph" / "multi_repo_collision"


def _build_analyzer_request(code_parser: CodeParser, rel_path: str, code: str) -> dict[str, object]:
    """Convert parser output into the request contract expected by the analyzer."""
    parsed = code_parser.parse_file(code, Path(rel_path).suffix)
    return {
        "path": rel_path,
        "functions": [
            {
                "name": function_row["name"],
                "qualified_name": function_row["qualified_name"],
                "parent_class": function_row.get("parent_class") or "",
                "name_line": function_row["name_line"],
                "name_column": function_row["name_column"],
            }
            for function_row in parsed["functions"]
        ],
    }


def _copy_fixture_repo(tmp_path: Path, fixture_name: str) -> Path:
    """Copy one on-disk fixture repo into pytest's temp directory.

    Keeping these repos on disk makes the multi-repo collision tests easier to
    inspect and extend. They are small but intentionally shaped like real repos:
    each one has the same relative paths and overlapping symbol names so we can
    prove the analyzer does not leak state across repo boundaries.
    """
    source = FIXTURE_ROOT / fixture_name
    target = tmp_path / fixture_name
    shutil.copytree(source, target)
    return target


def test_typescript_call_analyzer_resolves_cross_file_calls(tmp_path: Path) -> None:
    """TypeScript analysis should resolve function and method targets across files."""
    repo_root = tmp_path
    src_dir = repo_root / "src"
    src_dir.mkdir()

    files = {
        "src/a.ts": 'import { bar } from "./b";\nexport function foo() {\n  bar();\n}\n',
        "src/b.ts": "export function bar() {}\nexport class B {\n  work() {}\n}\n",
        "src/c.ts": 'import { B } from "./b";\nexport class A {\n  run() {\n    const b = new B();\n    b.work();\n  }\n}\n',
        "tsconfig.json": json.dumps(
            {
                "compilerOptions": {
                    "allowJs": True,
                    "module": "esnext",
                    "moduleResolution": "node",
                    "target": "es2022",
                },
                "include": ["src/**/*"],
            }
        ),
    }
    for rel_path, contents in files.items():
        target_path = repo_root / rel_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(contents, encoding="utf8")

    analyzer = TypeScriptCallAnalyzer()
    if not analyzer.is_available():
        pytest.skip(analyzer.disabled_reason or "TypeScript analyzer is unavailable.")

    code_parser = CodeParser()
    results = analyzer.analyze_files(
        repo_root=repo_root,
        files=[
            _build_analyzer_request(code_parser, "src/a.ts", files["src/a.ts"]),
            _build_analyzer_request(code_parser, "src/c.ts", files["src/c.ts"]),
        ],
    )

    foo_calls = results["src/a.ts"].functions["foo"].outgoing_calls
    assert [(call.rel_path, call.name, call.qualified_name_guess) for call in foo_calls] == [
        ("src/b.ts", "bar", "bar")
    ]
    assert foo_calls[0].definition_line == 1
    assert foo_calls[0].definition_column == 17

    run_calls = results["src/c.ts"].functions["A.run"].outgoing_calls
    assert [(call.rel_path, call.name, call.qualified_name_guess) for call in run_calls] == [
        ("src/b.ts", "work", "B.work")
    ]
    assert run_calls[0].definition_line == 3


def test_typescript_call_analyzer_reports_dropped_external_targets(tmp_path: Path) -> None:
    """Analyzer diagnostics should count dropped non-repo targets explicitly."""
    repo_root = tmp_path
    src_dir = repo_root / "src"
    src_dir.mkdir()

    files = {
        "src/app.ts": (
            "import { localHelper } from './local';\n"
            "export function runApp() {\n"
            "  console.log('hello');\n"
            "  localHelper();\n"
            "}\n"
        ),
        "src/local.ts": "export function localHelper() {}\n",
        "tsconfig.json": json.dumps(
            {
                "compilerOptions": {
                    "allowJs": True,
                    "module": "esnext",
                    "moduleResolution": "node",
                    "target": "es2022",
                },
                "include": ["src/**/*"],
            }
        ),
    }
    for rel_path, contents in files.items():
        target_path = repo_root / rel_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(contents, encoding="utf8")

    analyzer = TypeScriptCallAnalyzer()
    if not analyzer.is_available():
        pytest.skip(analyzer.disabled_reason or "TypeScript analyzer is unavailable.")

    code_parser = CodeParser()
    results = analyzer.analyze_files(
        repo_root=repo_root,
        files=[_build_analyzer_request(code_parser, "src/app.ts", files["src/app.ts"])],
    )

    file_result = results["src/app.ts"]
    assert file_result.drop_reason_counts["external_target"] >= 1
    assert any(
        row.get("kind") == "drop_reason_count" and row.get("reason") == "external_target"
        for row in file_result.diagnostics
    )


def test_typescript_call_analyzer_keeps_duplicate_paths_repo_local(tmp_path: Path) -> None:
    """Analyzer results should stay repo-local even when two repos share the same paths.

    Both fixture repos contain:
    - the same relative file paths (`src/app.ts`, `src/shared/helpers.ts`)
    - overlapping symbol names (`helper`, `Service.execute`)

    The differentiator is one repo-local function (`alphaOnly` vs `betaOnly`).
    If analyzer state leaks between runs, the second repo can accidentally inherit
    symbols from the first repo despite identical paths and overlapping names.
    """
    repo_alpha = _copy_fixture_repo(tmp_path, "repo_alpha")
    repo_beta = _copy_fixture_repo(tmp_path, "repo_beta")

    analyzer = TypeScriptCallAnalyzer()
    if not analyzer.is_available():
        pytest.skip(analyzer.disabled_reason or "TypeScript analyzer is unavailable.")

    code_parser = CodeParser()

    alpha_code = (repo_alpha / "src" / "app.ts").read_text(encoding="utf8")
    beta_code = (repo_beta / "src" / "app.ts").read_text(encoding="utf8")

    alpha_results = analyzer.analyze_files(
        repo_root=repo_alpha,
        files=[_build_analyzer_request(code_parser, "src/app.ts", alpha_code)],
    )
    beta_results = analyzer.analyze_files(
        repo_root=repo_beta,
        files=[_build_analyzer_request(code_parser, "src/app.ts", beta_code)],
    )

    alpha_calls = {
        (call.rel_path, call.name, call.qualified_name_guess)
        for call in alpha_results["src/app.ts"].functions["runApp"].outgoing_calls
    }
    beta_calls = {
        (call.rel_path, call.name, call.qualified_name_guess)
        for call in beta_results["src/app.ts"].functions["runApp"].outgoing_calls
    }

    assert ("src/shared/helpers.ts", "helper", "helper") in alpha_calls
    assert ("src/shared/helpers.ts", "alphaOnly", "alphaOnly") in alpha_calls
    assert ("src/shared/helpers.ts", "betaOnly", "betaOnly") not in alpha_calls

    assert ("src/shared/helpers.ts", "helper", "helper") in beta_calls
    assert ("src/shared/helpers.ts", "betaOnly", "betaOnly") in beta_calls
    assert ("src/shared/helpers.ts", "alphaOnly", "alphaOnly") not in beta_calls


def test_typescript_call_analyzer_batches_large_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Large JS/TS analysis runs should be split into smaller helper batches."""
    analyzer = TypeScriptCallAnalyzer()
    analyzer._config = analyzer._config.__class__(command=("node", "fake.js"), cwd=".")

    calls: list[dict[str, object]] = []

    def fake_run(*args, **kwargs):
        payload = json.loads(kwargs["input"])
        calls.append(payload)
        only_file = payload["files"][0]["path"]
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "files": [
                        {
                            "path": only_file,
                            "functions": [],
                            "diagnostics": [],
                            "drop_reason_counts": {},
                        }
                    ],
                }
            ),
            stderr="",
        )

    monkeypatch.setattr(
        "agentic_memory.ingestion.typescript_call_analyzer.subprocess.run",
        fake_run,
    )

    results = analyzer.analyze_files(
        repo_root=Path("."),
        files=[
            {"path": "src/a.ts", "functions": []},
            {"path": "src/b.ts", "functions": []},
            {"path": "src/c.ts", "functions": []},
        ],
        batch_size=1,
    )

    assert len(calls) == 3
    assert set(results) == {"src/a.ts", "src/b.ts", "src/c.ts"}


def test_typescript_call_analyzer_can_continue_after_batch_failure() -> None:
    """One failing helper batch should not erase the rest of the repo's results."""
    analyzer = TypeScriptCallAnalyzer()
    analyzer._config = analyzer._config.__class__(command=("node", "fake.js"), cwd=".")
    observed_batches: list[list[str]] = []

    def fake_run_batch(*, repo_root: Path, files: list[dict[str, object]], timeout_seconds: int):
        batch_paths = [str(file_row["path"]) for file_row in files]
        observed_batches.append(batch_paths)
        if batch_paths == ["src/a.ts"]:
            raise TypeScriptCallAnalyzerError("TypeScript call analyzer timed out after 30s.")
        return {
            "ok": True,
            "files": [
                {
                    "path": "src/b.ts",
                    "functions": [
                        {
                            "qualified_name": "bar",
                            "name": "bar",
                            "outgoing": [],
                        }
                    ],
                    "diagnostics": [],
                    "drop_reason_counts": {},
                }
            ],
        }

    analyzer._run_batch = fake_run_batch  # type: ignore[method-assign]

    results = analyzer.analyze_files(
        repo_root=Path("."),
        files=[
            {"path": "src/a.ts", "functions": [{"qualified_name": "foo", "name": "foo"}]},
            {"path": "src/b.ts", "functions": [{"qualified_name": "bar", "name": "bar"}]},
        ],
        batch_size=1,
        timeout_seconds=30,
        continue_on_batch_failure=True,
    )

    assert observed_batches == [["src/a.ts"], ["src/b.ts"]]
    assert len(analyzer.last_run_issues) == 1
    assert analyzer.last_run_issues[0].status == "failed"
    assert results["src/a.ts"].diagnostics[0]["kind"] == "batch_failed"
    assert "timed out" in results["src/a.ts"].diagnostics[0]["message"]
    assert "src/b.ts" in results
