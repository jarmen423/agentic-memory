"""Python semantic call analysis for repo-local CALLS edge generation.

This module plays the same role for Python that the TypeScript call analyzer
already plays for JS/TS code:

- the canonical parser still defines structural ownership boundaries,
- the semantic analyzer resolves "what concrete symbol does this call target?",
- the graph layer later maps those semantic targets back into repo-scoped
  `Function` nodes.

The implementation intentionally avoids repo-specific heuristics. It uses:

1. Python's built-in ``ast`` module to find call expressions within each
   function or method that the canonical parser already extracted, and
2. ``basedpyright-langserver`` over stdio to resolve each call site's
   definition the same way a real language-server-backed editor would.

That gives Phase 11 a generic Python semantic path without requiring every repo
to teach Agentic Memory custom symbol rules.
"""

from __future__ import annotations

import ast
import json
import logging
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)


class PythonCallAnalyzerError(RuntimeError):
    """Base error raised when the Python semantic analyzer fails."""


class PythonCallAnalyzerUnavailableError(PythonCallAnalyzerError):
    """Raised when the local environment cannot run the Python analyzer."""


@dataclass(frozen=True)
class _AnalyzerConfig:
    """Resolved configuration for the local basedpyright language server."""

    command: tuple[str, ...]
    disabled_reason: str | None = None


@dataclass(frozen=True)
class PythonOutgoingCall:
    """One analyzer-resolved outgoing Python call target.

    Attributes:
        rel_path: Repo-relative path of the resolved target definition.
        name: Unqualified function or method name.
        kind: Best-effort symbol kind (`function` or `method`).
        container_name: Optional class name for methods.
        qualified_name_guess: Repo-local best-effort qualified name the graph
            layer can try to map directly onto its own function identity model.
        definition_line: 1-based target definition line when available.
        definition_column: 1-based target definition column when available.
    """

    rel_path: str
    name: str
    kind: str | None = None
    container_name: str | None = None
    qualified_name_guess: str | None = None
    definition_line: int | None = None
    definition_column: int | None = None


@dataclass(frozen=True)
class PythonFunctionCallAnalysis:
    """Outgoing call analysis for one Python function or method."""

    qualified_name: str
    name: str
    outgoing_calls: tuple[PythonOutgoingCall, ...]


@dataclass(frozen=True)
class PythonFileCallAnalysis:
    """Analyzer output for one Python file."""

    rel_path: str
    functions: dict[str, PythonFunctionCallAnalysis]
    diagnostics: tuple[dict[str, Any], ...] = ()
    drop_reason_counts: dict[str, int] | None = None


@dataclass(frozen=True)
class _CallSite:
    """One call expression inside a function body."""

    call_name: str
    line_zero: int
    column_zero: int


@dataclass(frozen=True)
class _FunctionSymbol:
    """Python function or method definition discovered from AST."""

    qualified_name: str
    name: str
    parent_class: str
    kind: str
    name_line: int
    name_column: int
    call_sites: tuple[_CallSite, ...]


class _FunctionScopeCollector(ast.NodeVisitor):
    """Collect Python function/method definitions and call sites from one AST."""

    def __init__(self, source_lines: list[str]) -> None:
        self._source_lines = source_lines
        self._class_stack: list[str] = []
        self.functions: list[_FunctionSymbol] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802 - ast API
        self._class_stack.append(node.name)
        try:
            self.generic_visit(node)
        finally:
            self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802 - ast API
        self._record_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802 - ast API
        self._record_function(node)
        self.generic_visit(node)

    def _record_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        parent_class = self._class_stack[-1] if self._class_stack else ""
        qualified_name = f"{parent_class}.{node.name}" if parent_class else node.name
        name_line, name_column = _definition_name_position(node, self._source_lines)
        call_sites = _extract_call_sites(node, self._source_lines)
        self.functions.append(
            _FunctionSymbol(
                qualified_name=qualified_name,
                name=node.name,
                parent_class=parent_class,
                kind="method" if parent_class else "function",
                name_line=name_line,
                name_column=name_column,
                call_sites=call_sites,
            )
        )


class _CallSiteCollector(ast.NodeVisitor):
    """Collect call sites while skipping nested ownership boundaries."""

    def __init__(self, source_lines: list[str]) -> None:
        self._source_lines = source_lines
        self.call_sites: list[_CallSite] = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802 - ast API
        site = _call_site_from_expr(node.func, self._source_lines)
        if site is not None:
            self.call_sites.append(site)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802 - ast API
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802 - ast API
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802 - ast API
        return


class _LspClient:
    """Minimal stdio JSON-RPC client for one language-server session."""

    def __init__(self, command: tuple[str, ...]) -> None:
        self._proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._next_request_id = 1

    def close(self) -> None:
        """Shut down the subprocess without leaking handles."""
        if self._proc.poll() is None:
            try:
                self.notify("exit", {})
            finally:
                self._proc.kill()
        if self._proc.stdout is not None:
            self._proc.stdout.close()
        if self._proc.stdin is not None:
            self._proc.stdin.close()
        if self._proc.stderr is not None:
            self._proc.stderr.close()

    def initialize(self, repo_root: Path) -> None:
        """Initialize the language server for one workspace root."""
        self.request(
            "initialize",
            {
                "processId": None,
                "clientInfo": {"name": "agentic-memory"},
                "rootUri": repo_root.as_uri(),
                "capabilities": {},
                "workspaceFolders": [
                    {
                        "uri": repo_root.as_uri(),
                        "name": repo_root.name,
                    }
                ],
                "initializationOptions": {},
            },
        )
        self.notify("initialized", {})

    def did_open(self, path: Path, text: str) -> None:
        """Tell the language server about one open Python document."""
        self.notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": path.as_uri(),
                    "languageId": "python",
                    "version": 1,
                    "text": text,
                }
            },
        )

    def definition(self, path: Path, *, line_zero: int, column_zero: int) -> list[dict[str, Any]]:
        """Resolve one call site to definition locations."""
        result = self.request(
            "textDocument/definition",
            {
                "textDocument": {"uri": path.as_uri()},
                "position": {
                    "line": line_zero,
                    "character": column_zero,
                },
            },
        )
        if result is None:
            return []
        if isinstance(result, list):
            return [row for row in result if isinstance(row, dict)]
        if isinstance(result, dict):
            return [result]
        return []

    def request(self, method: str, params: dict[str, Any]) -> Any:
        """Send one JSON-RPC request and wait for its matching response."""
        request_id = self._next_request_id
        self._next_request_id += 1
        self._send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
        )

        while True:
            message = self._recv()
            if message.get("id") == request_id:
                if "error" in message:
                    raise PythonCallAnalyzerError(str(message["error"]))
                return message.get("result")

    def notify(self, method: str, params: dict[str, Any]) -> None:
        """Send one JSON-RPC notification."""
        self._send(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            }
        )

    def _send(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload)
        message = f"Content-Length: {len(body.encode('utf-8'))}\r\n\r\n{body}".encode("utf-8")
        if self._proc.stdin is None:
            raise PythonCallAnalyzerError("Language server stdin is unavailable.")
        self._proc.stdin.write(message)
        self._proc.stdin.flush()

    def _recv(self) -> dict[str, Any]:
        if self._proc.stdout is None:
            raise PythonCallAnalyzerError("Language server stdout is unavailable.")

        headers: dict[str, str] = {}
        while True:
            line = self._proc.stdout.readline()
            if not line:
                stderr = ""
                if self._proc.stderr is not None:
                    stderr = self._proc.stderr.read().decode("utf-8", errors="ignore").strip()
                raise PythonCallAnalyzerError(
                    stderr or "basedpyright language server exited unexpectedly."
                )
            if line == b"\r\n":
                break
            key, value = line.decode("ascii").split(":", 1)
            headers[key.lower()] = value.strip()

        length = int(headers["content-length"])
        body = self._proc.stdout.read(length)
        return json.loads(body)


class PythonCallAnalyzer:
    """Batch Python semantic call analysis through basedpyright."""

    def __init__(self, config: _AnalyzerConfig | None = None) -> None:
        self._config = config or self._build_config()

    def is_available(self) -> bool:
        """Return ``True`` when the local Python analyzer can run."""
        return self._config.disabled_reason is None

    @property
    def disabled_reason(self) -> str | None:
        """Human-readable reason the Python analyzer is unavailable, if any."""
        return self._config.disabled_reason

    def analyze_files(
        self,
        *,
        repo_root: Path,
        files: list[dict[str, Any]],
        timeout_seconds: int = 60,
    ) -> dict[str, PythonFileCallAnalysis]:
        """Resolve outgoing calls for a batch of Python files.

        Args:
            repo_root: Absolute repository root.
            files: Parser-driven request rows with ``path`` plus function
                metadata (`qualified_name`, `name`, `name_line`, `name_column`).
            timeout_seconds: Reserved for API parity with the TS analyzer. The
                current implementation uses a long-lived stdio process instead of
                one subprocess per request, so timeout handling is delegated to
                the caller/process boundary for now.

        Returns:
            Mapping of repo-relative file paths to analyzer results.
        """
        _ = timeout_seconds
        if not files:
            return {}

        if not self.is_available():
            raise PythonCallAnalyzerUnavailableError(
                self.disabled_reason or "Python call analyzer is unavailable."
            )

        client = _LspClient(self._config.command)
        results: dict[str, PythonFileCallAnalysis] = {}
        symbol_cache: dict[str, dict[tuple[int, int], _FunctionSymbol]] = {}

        try:
            client.initialize(repo_root)
            for file_request in files:
                rel_path = str(file_request.get("path") or "")
                if not rel_path:
                    continue

                full_path = (repo_root / rel_path).resolve()
                diagnostics: list[dict[str, Any]] = []
                drop_reason_counts: dict[str, int] = {}

                if not full_path.exists():
                    diagnostics.append(
                        {
                            "kind": "missing_file",
                            "level": "error",
                            "message": f"File not found: {full_path}",
                        }
                    )
                    results[rel_path] = PythonFileCallAnalysis(
                        rel_path=rel_path,
                        functions={},
                        diagnostics=tuple(diagnostics),
                        drop_reason_counts=drop_reason_counts,
                    )
                    continue

                code = full_path.read_text(encoding="utf8", errors="ignore")
                client.did_open(full_path, code)

                function_symbols = _function_symbols_from_code(code, diagnostics)
                symbol_cache[rel_path] = {
                    (row.name_line, row.name_column): row for row in function_symbols
                }
                by_qualified_name = {row.qualified_name: row for row in function_symbols}

                functions: dict[str, PythonFunctionCallAnalysis] = {}
                for request_function in file_request.get("functions", []):
                    qualified_name = str(
                        request_function.get("qualified_name")
                        or request_function.get("name")
                        or ""
                    )
                    request_name_line = int(request_function.get("name_line") or 0)
                    request_name_column = int(request_function.get("name_column") or 0)
                    symbol = by_qualified_name.get(qualified_name) or symbol_cache[rel_path].get(
                        (request_name_line, request_name_column)
                    )
                    if symbol is None:
                        _increment(drop_reason_counts, "missing_function_scope")
                        continue

                    outgoing_calls: list[PythonOutgoingCall] = []
                    for call_site in symbol.call_sites:
                        definition_locations = client.definition(
                            full_path,
                            line_zero=call_site.line_zero,
                            column_zero=call_site.column_zero,
                        )
                        if not definition_locations:
                            _increment(drop_reason_counts, "no_definition")
                            continue

                        resolved_target = self._resolve_definition_target(
                            repo_root=repo_root,
                            locations=definition_locations,
                            symbol_cache=symbol_cache,
                            diagnostics=diagnostics,
                        )
                        if resolved_target is None:
                            _increment(drop_reason_counts, "unresolved_target_symbol")
                            continue

                        if resolved_target.qualified_name_guess == symbol.qualified_name and resolved_target.rel_path == rel_path:
                            continue
                        outgoing_calls.append(resolved_target)

                    functions[qualified_name] = PythonFunctionCallAnalysis(
                        qualified_name=qualified_name,
                        name=symbol.name,
                        outgoing_calls=_dedupe_python_outgoing_calls(outgoing_calls),
                    )

                diagnostics.extend(_drop_reason_diagnostics(drop_reason_counts))
                results[rel_path] = PythonFileCallAnalysis(
                    rel_path=rel_path,
                    functions=functions,
                    diagnostics=tuple(diagnostics),
                    drop_reason_counts=drop_reason_counts,
                )

        finally:
            client.close()

        return results

    def _resolve_definition_target(
        self,
        *,
        repo_root: Path,
        locations: list[dict[str, Any]],
        symbol_cache: dict[str, dict[tuple[int, int], _FunctionSymbol]],
        diagnostics: list[dict[str, Any]],
    ) -> PythonOutgoingCall | None:
        """Map LSP definition results back to a repo-local Python function symbol."""
        repo_local_targets: list[PythonOutgoingCall] = []

        for location in locations:
            uri = str(location.get("uri") or "")
            rel_path = _rel_path_from_uri(repo_root, uri)
            if rel_path is None:
                continue

            range_row = location.get("range") or {}
            start = range_row.get("start") or {}
            name_line = int(start.get("line", -1)) + 1
            name_column = int(start.get("character", -1)) + 1
            per_file_symbols = symbol_cache.get(rel_path)
            if per_file_symbols is None:
                target_path = (repo_root / rel_path).resolve()
                if not target_path.exists():
                    continue
                target_code = target_path.read_text(encoding="utf8", errors="ignore")
                target_diagnostics: list[dict[str, Any]] = []
                target_symbols = _function_symbols_from_code(target_code, target_diagnostics)
                diagnostics.extend(target_diagnostics)
                per_file_symbols = {
                    (row.name_line, row.name_column): row for row in target_symbols
                }
                symbol_cache[rel_path] = per_file_symbols

            function_symbol = per_file_symbols.get((name_line, name_column))
            if function_symbol is None:
                continue

            repo_local_targets.append(
                PythonOutgoingCall(
                    rel_path=rel_path,
                    name=function_symbol.name,
                    kind=function_symbol.kind,
                    container_name=function_symbol.parent_class or None,
                    qualified_name_guess=function_symbol.qualified_name,
                    definition_line=function_symbol.name_line,
                    definition_column=function_symbol.name_column,
                )
            )

        if not repo_local_targets:
            return None

        deduped = _dedupe_python_outgoing_calls(repo_local_targets)
        if len(deduped) == 1:
            return deduped[0]

        return None

    def _build_config(self) -> _AnalyzerConfig:
        """Resolve the local language-server command."""
        executable_names = ["basedpyright-langserver"]
        if sys.platform.startswith("win"):
            executable_names.insert(0, "basedpyright-langserver.exe")

        for executable_name in executable_names:
            command_path = shutil.which(executable_name)
            if command_path:
                return _AnalyzerConfig(command=(command_path, "--stdio"))

        local_scripts_dir = Path(sys.executable).resolve().parent
        for executable_name in executable_names:
            candidate = local_scripts_dir / executable_name
            if candidate.exists():
                return _AnalyzerConfig(command=(str(candidate), "--stdio"))

        return _AnalyzerConfig(
            command=(),
            disabled_reason=(
                "basedpyright-langserver is not available. Install basedpyright "
                "or ensure the language server is on PATH."
            ),
        )


def _function_symbols_from_code(
    code: str,
    diagnostics: list[dict[str, Any]],
) -> list[_FunctionSymbol]:
    """Parse one Python file into function symbols plus call-site positions."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        diagnostics.append(
            {
                "kind": "parse_error",
                "level": "error",
                "message": str(exc),
            }
        )
        return []

    collector = _FunctionScopeCollector(code.splitlines())
    collector.visit(tree)
    return collector.functions


def _definition_name_position(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    source_lines: list[str],
) -> tuple[int, int]:
    """Return the 1-based location of a function name token."""
    line_text = source_lines[node.lineno - 1] if node.lineno - 1 < len(source_lines) else ""
    segment = line_text[node.col_offset :]
    prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
    name_offset = segment.find(prefix)
    if name_offset == -1:
        return node.lineno, node.col_offset + 1
    return node.lineno, node.col_offset + name_offset + len(prefix) + 1


def _extract_call_sites(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    source_lines: list[str],
) -> tuple[_CallSite, ...]:
    """Collect call sites for one function body without descending into nested scopes."""
    collector = _CallSiteCollector(source_lines)
    for statement in node.body:
        collector.visit(statement)
    return tuple(collector.call_sites)


def _call_site_from_expr(expr: ast.expr, source_lines: list[str]) -> _CallSite | None:
    """Convert a call expression target into the position to ask the LSP about."""
    if isinstance(expr, ast.Name):
        return _CallSite(
            call_name=expr.id,
            line_zero=expr.lineno - 1,
            column_zero=expr.col_offset,
        )

    if isinstance(expr, ast.Attribute):
        line_index = (expr.end_lineno or expr.lineno) - 1
        line_text = source_lines[line_index] if line_index < len(source_lines) else ""
        attr_column = max((expr.end_col_offset or expr.col_offset) - len(expr.attr), 0)
        if attr_column > len(line_text):
            attr_column = expr.col_offset
        return _CallSite(
            call_name=expr.attr,
            line_zero=line_index,
            column_zero=attr_column,
        )

    return None


def _rel_path_from_uri(repo_root: Path, uri: str) -> str | None:
    """Convert a file URI into a repo-relative path when the target stays local."""
    if not uri:
        return None

    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None

    absolute_path = Path(unquote(parsed.path.lstrip("/"))).resolve()
    try:
        rel_path = absolute_path.relative_to(repo_root.resolve())
    except ValueError:
        return None
    return str(rel_path).replace("\\", "/")


def _dedupe_python_outgoing_calls(
    calls: list[PythonOutgoingCall],
) -> tuple[PythonOutgoingCall, ...]:
    """Return stable deduplicated outgoing-call rows."""
    deduped: list[PythonOutgoingCall] = []
    seen: set[tuple[str, str, str | None]] = set()
    for call in calls:
        key = (call.rel_path, call.name, call.qualified_name_guess)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(call)
    return tuple(deduped)


def _increment(counter: dict[str, int], reason: str) -> None:
    """Increment one diagnostic counter in place."""
    counter[reason] = counter.get(reason, 0) + 1


def _drop_reason_diagnostics(drop_reason_counts: dict[str, int]) -> list[dict[str, Any]]:
    """Convert drop counters into stable diagnostic rows."""
    return [
        {
            "kind": "drop_reason_count",
            "level": "info",
            "reason": reason,
            "count": int(count),
        }
        for reason, count in sorted(drop_reason_counts.items())
    ]
