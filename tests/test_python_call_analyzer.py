"""Integration-style tests for the Python semantic call analyzer.

These tests use the real basedpyright language server against small temporary
repositories. The goal is the same as the TypeScript analyzer tests: prove that
Agentic Memory can resolve repo-local semantic call targets before the graph
layer starts trusting those edges.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_memory.ingestion.parser import CodeParser
from agentic_memory.ingestion.python_call_analyzer import PythonCallAnalyzer


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


def test_python_call_analyzer_resolves_cross_file_calls(tmp_path: Path) -> None:
    """Python analysis should resolve cross-file functions and methods."""
    repo_root = tmp_path
    files = {
        "pyrightconfig.json": "{}\n",
        "a.py": "from b import bar\n\n\ndef foo():\n    bar()\n",
        "b.py": "def bar():\n    return 1\n\n\nclass Worker:\n    def run(self):\n        return 2\n",
        "c.py": (
            "from b import Worker\n\n\nclass Service:\n"
            "    def execute(self):\n"
            "        worker = Worker()\n"
            "        worker.run()\n"
        ),
    }
    for rel_path, contents in files.items():
        target = repo_root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf8")

    analyzer = PythonCallAnalyzer()
    if not analyzer.is_available():
        pytest.skip(analyzer.disabled_reason or "Python analyzer is unavailable.")

    code_parser = CodeParser()
    results = analyzer.analyze_files(
        repo_root=repo_root,
        files=[
            _build_analyzer_request(code_parser, "a.py", files["a.py"]),
            _build_analyzer_request(code_parser, "c.py", files["c.py"]),
        ],
    )

    foo_calls = results["a.py"].functions["foo"].outgoing_calls
    assert [(call.rel_path, call.name, call.qualified_name_guess) for call in foo_calls] == [
        ("b.py", "bar", "bar")
    ]

    execute_calls = results["c.py"].functions["Service.execute"].outgoing_calls
    assert ("b.py", "run", "Worker.run") in [
        (call.rel_path, call.name, call.qualified_name_guess) for call in execute_calls
    ]
    assert not (results["c.py"].drop_reason_counts or {}).get("unresolved_target_symbol", 0)
    assert (results["c.py"].drop_reason_counts or {}).get("non_function_target", 0) >= 1


def test_python_call_analyzer_keeps_duplicate_paths_repo_local(tmp_path: Path) -> None:
    """Analyzer results should stay repo-local when two repos share the same paths."""
    analyzer = PythonCallAnalyzer()
    if not analyzer.is_available():
        pytest.skip(analyzer.disabled_reason or "Python analyzer is unavailable.")

    code_parser = CodeParser()
    for repo_name, unique_name in [("repo_alpha", "alpha_only"), ("repo_beta", "beta_only")]:
        repo_root = tmp_path / repo_name
        files = {
            "pyrightconfig.json": "{}\n",
            "src/app.py": "from src.shared.helpers import helper, " + unique_name + "\n\n\ndef run_app():\n    helper()\n    " + unique_name + "()\n",
            "src/shared/helpers.py": (
                "def helper():\n    return 1\n\n\n"
                f"def {unique_name}():\n    return 2\n"
            ),
        }
        for rel_path, contents in files.items():
            target = repo_root / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents, encoding="utf8")

    alpha_root = tmp_path / "repo_alpha"
    beta_root = tmp_path / "repo_beta"
    alpha_code = (alpha_root / "src" / "app.py").read_text(encoding="utf8")
    beta_code = (beta_root / "src" / "app.py").read_text(encoding="utf8")

    alpha_results = analyzer.analyze_files(
        repo_root=alpha_root,
        files=[_build_analyzer_request(code_parser, "src/app.py", alpha_code)],
    )
    beta_results = analyzer.analyze_files(
        repo_root=beta_root,
        files=[_build_analyzer_request(code_parser, "src/app.py", beta_code)],
    )

    alpha_calls = {
        (call.rel_path, call.name, call.qualified_name_guess)
        for call in alpha_results["src/app.py"].functions["run_app"].outgoing_calls
    }
    beta_calls = {
        (call.rel_path, call.name, call.qualified_name_guess)
        for call in beta_results["src/app.py"].functions["run_app"].outgoing_calls
    }

    assert ("src/shared/helpers.py", "helper", "helper") in alpha_calls
    assert ("src/shared/helpers.py", "alpha_only", "alpha_only") in alpha_calls
    assert ("src/shared/helpers.py", "beta_only", "beta_only") not in alpha_calls

    assert ("src/shared/helpers.py", "helper", "helper") in beta_calls
    assert ("src/shared/helpers.py", "beta_only", "beta_only") in beta_calls
    assert ("src/shared/helpers.py", "alpha_only", "alpha_only") not in beta_calls


def test_python_call_analyzer_reports_external_targets_separately(tmp_path: Path) -> None:
    """External Python calls should not be counted as repo-local mapping failures.

    Phase 11 diagnostics need to distinguish two different outcomes:

    - basedpyright resolved a call successfully, but the target lives outside the
      indexed repository and should therefore stay out of the CALLS graph
    - basedpyright pointed at a repo-local location that we still failed to map
      back to a function symbol

    This regression keeps builtins and stdlib calls in the `external_target`
    bucket instead of inflating `unresolved_target_symbol`.
    """
    repo_root = tmp_path
    files = {
        "pyrightconfig.json": "{}\n",
        "main.py": (
            "from pathlib import Path\n\n\n"
            "def run() -> None:\n"
            "    print('hello')\n"
            "    Path.cwd()\n"
        ),
    }
    for rel_path, contents in files.items():
        target = repo_root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf8")

    analyzer = PythonCallAnalyzer()
    if not analyzer.is_available():
        pytest.skip(analyzer.disabled_reason or "Python analyzer is unavailable.")

    code_parser = CodeParser()
    results = analyzer.analyze_files(
        repo_root=repo_root,
        files=[_build_analyzer_request(code_parser, "main.py", files["main.py"])],
    )

    analysis = results["main.py"]
    assert analysis.functions["run"].outgoing_calls == ()
    assert (analysis.drop_reason_counts or {}).get("external_target", 0) >= 2
    assert not (analysis.drop_reason_counts or {}).get("unresolved_target_symbol", 0)
