"""TypeScript-backed semantic call analysis for JS/TS code ingestion.

This module gives the Python graph builder access to the same semantic
resolution machinery that powers TypeScript's call hierarchy features in IDEs.
Tree-sitter remains the source of truth for structural extraction, but
TypeScript's language service is better at answering "which concrete symbol
does this JS/TS call expression resolve to across the repo?".

Why this layer exists:
- Tree-sitter is excellent for syntax and ownership boundaries.
- Whole-project symbol resolution is a different problem than parsing.
- Phase 11 needs higher-confidence JS/TS `CALLS` edges before those edges can
  participate in graph traversal.

The helper returns repo-relative call targets so the graph layer can keep using
its own repo-scoped identity model (`repo_id + path + qualified_name`).
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class TypeScriptCallAnalyzerError(RuntimeError):
    """Base error raised when the TypeScript helper fails."""


class TypeScriptCallAnalyzerUnavailableError(TypeScriptCallAnalyzerError):
    """Raised when the local environment cannot run the TypeScript helper."""


@dataclass(frozen=True)
class _AnalyzerConfig:
    """Resolved configuration for the local TypeScript helper process."""

    command: tuple[str, ...]
    cwd: str
    disabled_reason: str | None = None


@dataclass(frozen=True)
class TypeScriptOutgoingCall:
    """One analyzer-resolved outgoing JS/TS call target.

    Attributes:
        rel_path: Repo-relative path of the target definition.
        name: Unqualified target symbol name reported by TypeScript.
        kind: TypeScript call-hierarchy kind such as ``function`` or ``method``.
        container_name: Optional parent container such as a class name.
        qualified_name_guess: Best-effort ``container.name`` representation that
            the graph layer can try to map onto its own qualified-name scheme.
        definition_line: 1-based line for the resolved target definition when
            TypeScript can provide it.
        definition_column: 1-based column for the resolved target definition
            when TypeScript can provide it.
    """

    rel_path: str
    name: str
    kind: str | None = None
    container_name: str | None = None
    qualified_name_guess: str | None = None
    definition_line: int | None = None
    definition_column: int | None = None


@dataclass(frozen=True)
class TypeScriptFunctionCallAnalysis:
    """Outgoing call analysis for one JS/TS function or method."""

    qualified_name: str
    name: str
    outgoing_calls: tuple[TypeScriptOutgoingCall, ...]


@dataclass(frozen=True)
class TypeScriptFileCallAnalysis:
    """Analyzer output for one JS/TS file.

    ``functions`` is keyed by the parser's qualified-name contract so the graph
    builder can merge analyzer results back into the repo-scoped function nodes
    it already created during Pass 2.
    """

    rel_path: str
    functions: dict[str, TypeScriptFunctionCallAnalysis]
    diagnostics: tuple[dict[str, Any], ...] = ()
    drop_reason_counts: dict[str, int] | None = None


class TypeScriptCallAnalyzer:
    """Batch JS/TS call analysis through the installed TypeScript service."""

    def __init__(self, config: _AnalyzerConfig | None = None) -> None:
        self._config = config or self._build_config()

    def is_available(self) -> bool:
        """Return ``True`` when the local helper can run."""
        return self._config.disabled_reason is None

    @property
    def disabled_reason(self) -> str | None:
        """Human-readable reason the analyzer is unavailable, if any."""
        return self._config.disabled_reason

    def analyze_files(
        self,
        *,
        repo_root: Path,
        files: list[dict[str, Any]],
        timeout_seconds: int = 60,
    ) -> dict[str, TypeScriptFileCallAnalysis]:
        """Resolve outgoing calls for a batch of JS/TS files.

        Args:
            repo_root: Absolute root of the repository being analyzed.
            files: Per-file request payloads. Each row must include ``path`` and
                a ``functions`` list with ``qualified_name``, ``name``,
                ``name_line``, and ``name_column`` values from the canonical
                parser.
            timeout_seconds: Maximum helper runtime for the whole batch.

        Returns:
            Mapping of repo-relative file path to structured analyzer results.

        Raises:
            TypeScriptCallAnalyzerUnavailableError: When local Node/TypeScript
                tooling is missing.
            TypeScriptCallAnalyzerError: When the helper exits unsuccessfully or
                returns invalid JSON.
        """
        if not files:
            return {}

        if not self.is_available():
            raise TypeScriptCallAnalyzerUnavailableError(
                self.disabled_reason or "TypeScript call analyzer is unavailable."
            )

        payload = {
            "repoRoot": str(repo_root.resolve()),
            "files": files,
        }

        try:
            completed = subprocess.run(
                self._config.command,
                input=json.dumps(payload),
                capture_output=True,
                cwd=self._config.cwd,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise TypeScriptCallAnalyzerError(
                f"TypeScript call analyzer timed out after {timeout_seconds}s."
            ) from exc
        except OSError as exc:
            raise TypeScriptCallAnalyzerUnavailableError(str(exc)) from exc

        try:
            response = json.loads(completed.stdout or "{}")
        except json.JSONDecodeError as exc:
            if completed.returncode != 0:
                stderr = completed.stderr.strip()
                raise TypeScriptCallAnalyzerError(
                    stderr or "TypeScript call analyzer returned invalid JSON."
                ) from exc
            raise TypeScriptCallAnalyzerError("TypeScript call analyzer returned invalid JSON.") from exc

        if completed.returncode != 0:
            stderr = completed.stderr.strip()
            message = str(response.get("error") or stderr or "TypeScript call analyzer exited with a non-zero status.")
            raise TypeScriptCallAnalyzerError(message)

        if not response.get("ok", False):
            message = str(response.get("error") or "TypeScript call analyzer failed.")
            raise TypeScriptCallAnalyzerError(message)

        results: dict[str, TypeScriptFileCallAnalysis] = {}
        for file_row in response.get("files", []):
            rel_path = str(file_row.get("path") or "")
            functions: dict[str, TypeScriptFunctionCallAnalysis] = {}

            for function_row in file_row.get("functions", []):
                qualified_name = str(
                    function_row.get("qualified_name") or function_row.get("name") or ""
                )
                if not qualified_name:
                    continue

                outgoing_calls = tuple(
                    TypeScriptOutgoingCall(
                        rel_path=str(call_row.get("path") or ""),
                        name=str(call_row.get("name") or ""),
                        kind=(
                            str(call_row["kind"])
                            if call_row.get("kind") is not None
                            else None
                        ),
                        container_name=(
                            str(call_row["container_name"])
                            if call_row.get("container_name") is not None
                            else None
                        ),
                        qualified_name_guess=(
                            str(call_row["qualified_name_guess"])
                            if call_row.get("qualified_name_guess") is not None
                            else None
                        ),
                        definition_line=(
                            int(call_row["definition_line"])
                            if call_row.get("definition_line") is not None
                            else None
                        ),
                        definition_column=(
                            int(call_row["definition_column"])
                            if call_row.get("definition_column") is not None
                            else None
                        ),
                    )
                    for call_row in function_row.get("outgoing", [])
                    if call_row.get("path") and call_row.get("name")
                )

                functions[qualified_name] = TypeScriptFunctionCallAnalysis(
                    qualified_name=qualified_name,
                    name=str(function_row.get("name") or qualified_name),
                    outgoing_calls=outgoing_calls,
                )

            diagnostics = tuple(file_row.get("diagnostics", ()))
            drop_reason_counts = {
                str(reason): int(count)
                for reason, count in (file_row.get("drop_reason_counts") or {}).items()
            }
            if diagnostics:
                logger.debug(
                    "TypeScript analyzer diagnostics for %s: %s",
                    rel_path,
                    diagnostics,
                )

            if rel_path:
                results[rel_path] = TypeScriptFileCallAnalysis(
                    rel_path=rel_path,
                    functions=functions,
                    diagnostics=diagnostics,
                    drop_reason_counts=drop_reason_counts,
                )

        return results

    def _build_config(self) -> _AnalyzerConfig:
        """Resolve the local Node helper command and prerequisites."""
        workspace_root = Path(__file__).resolve().parents[3]
        script_path = workspace_root / "scripts" / "query_typescript_calls.js"
        if not script_path.exists():
            return _AnalyzerConfig(
                command=(),
                cwd=str(workspace_root),
                disabled_reason=f"TypeScript helper script not found: {script_path}",
            )

        node_path = shutil.which("node")
        if not node_path:
            return _AnalyzerConfig(
                command=(),
                cwd=str(workspace_root),
                disabled_reason="node is not available on PATH.",
            )

        typescript_runtime = workspace_root / "node_modules" / "typescript" / "lib" / "typescript.js"
        if not typescript_runtime.exists():
            return _AnalyzerConfig(
                command=(),
                cwd=str(workspace_root),
                disabled_reason=(
                    "Local TypeScript runtime is missing at "
                    f"{typescript_runtime}. Run npm install first."
                ),
            )

        return _AnalyzerConfig(
            command=(node_path, str(script_path)),
            cwd=str(workspace_root),
        )
