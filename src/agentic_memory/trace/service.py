"""Just-in-time code tracing built on the code graph plus an extraction LLM.

The old Phase 11 CALLS rollout tried to build a global call graph during every
indexing run. That made indexing expensive and still produced weak real-repo
coverage. This service inverts that model:

- precompute only durable static structure during indexing
- trace one function only when an operator or agent actually needs it
- cache the result separately from trusted structural edges

The service is intentionally conservative. It never guesses between ambiguous
symbols and it only accepts LLM-resolved targets that map back to repo-local
function signatures already known to the graph.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from agentic_memory.core.extraction_llm import (
    build_extraction_openai_client,
    resolve_extraction_llm_config,
)
from agentic_memory.ingestion.graph import KnowledgeGraphBuilder

logger = logging.getLogger(__name__)

TRACE_PROMPT = """\
You are tracing one function inside a code repository.

Your job:
- inspect the root function and the provided graph context
- infer likely repo-local outgoing behavioral edges from that root function only
- choose targets only from the provided candidate signatures
- do not invent repo-local functions that are not in the candidate list

Edge types:
- direct_call: a normal call expression to a repo-local function or method target
- callback: the root passes or stores a callable that later invokes a repo-local target
- message_flow: the root emits a message/event/request that later triggers a repo-local target

Rules:
- return JSON only
- use only the provided candidate signatures for resolved edges
- if a likely target cannot be chosen safely, put it in unresolved instead
- do not include self-edges
- confidence must be between 0.0 and 1.0

Return format:
{
  "edges": [
    {
      "callee_signature": "path:qualified_name",
      "edge_type": "direct_call|callback|message_flow",
      "confidence": 0.0,
      "rationale": "short explanation",
      "evidence": "brief code evidence"
    }
  ],
  "unresolved": [
    {
      "target_name": "string",
      "reason": "why unresolved",
      "evidence": "brief code evidence"
    }
  ]
}
"""

RELATIONSHIP_TYPE_BY_EDGE_TYPE = {
    "direct_call": "JIT_CALLS_DIRECT",
    "callback": "JIT_CALLS_CALLBACK",
    "message_flow": "JIT_MESSAGE_FLOW",
}
RECURSIVE_EDGE_TYPES = {"direct_call"}


@dataclass
class TraceFunctionResult:
    """Normalized one-hop trace result for one function root."""

    root_signature: str
    root_qualified_name: str
    root_path: str
    cache_hit: bool
    edges: list[dict[str, Any]]
    unresolved: list[dict[str, Any]]
    model: str


class TraceExecutionService:
    """Trace code execution paths on demand using graph context plus an LLM.

    Args:
        graph: Live graph builder for code-domain lookups and cache persistence.
        client: Optional OpenAI-compatible client override for tests.
        model: Optional model override. Defaults to the configured extraction LLM.
        provider: Optional extraction provider override.
        api_key: Optional extraction API key override.
        base_url: Optional provider base URL override.
    """

    def __init__(
        self,
        *,
        graph: KnowledgeGraphBuilder,
        client: Any | None = None,
        model: str | None = None,
        provider: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self.graph = graph
        resolved = resolve_extraction_llm_config(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url,
        )
        self.model = resolved.model
        self.provider = resolved.provider
        self._client = client or build_extraction_openai_client(resolved)

    def trace_execution_path(
        self,
        *,
        start_symbol: str,
        repo_id: str | None = None,
        max_depth: int = 2,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Trace a function and recursively expand direct calls to bounded depth."""
        resolution = self.graph.resolve_function_symbol(start_symbol, repo_id=repo_id)
        status = str(resolution.get("status") or "not_found")
        diagnostics_repo_id = repo_id or self.graph.repo_id
        diagnostics = self.graph.get_call_diagnostics(repo_id=diagnostics_repo_id)

        if status != "resolved":
            return {
                "status": status,
                "start_symbol": start_symbol,
                "match_type": resolution.get("match_type"),
                "candidates": resolution.get("candidates", []),
                "diagnostics": diagnostics,
                "traces": [],
                "total_edges": 0,
                "total_unresolved": 0,
            }

        root = dict(resolution["candidate"])
        resolved_repo_id = repo_id or self.graph.repo_id
        safe_depth = max(1, int(max_depth))
        queue: list[tuple[str, int]] = [(str(root["signature"]), 1)]
        visited: set[str] = set()
        trace_rows: list[dict[str, Any]] = []
        cache_hits = 0
        cache_misses = 0

        while queue:
            signature, depth = queue.pop(0)
            if signature in visited:
                continue
            visited.add(signature)

            hop = self.trace_function(
                signature=signature,
                repo_id=resolved_repo_id,
                force_refresh=force_refresh,
            )
            trace_rows.append(
                {
                    "depth": depth,
                    "root_signature": hop.root_signature,
                    "root_qualified_name": hop.root_qualified_name,
                    "root_path": hop.root_path,
                    "cache_hit": hop.cache_hit,
                    "edges": hop.edges,
                    "unresolved": hop.unresolved,
                }
            )
            if hop.cache_hit:
                cache_hits += 1
            else:
                cache_misses += 1

            if depth >= safe_depth:
                continue
            for edge in hop.edges:
                if edge["edge_type"] in RECURSIVE_EDGE_TYPES:
                    next_signature = str(edge["callee_signature"])
                    if next_signature not in visited:
                        queue.append((next_signature, depth + 1))

        return {
            "status": "resolved",
            "start_symbol": start_symbol,
            "root": root,
            "diagnostics": diagnostics,
            "max_depth": safe_depth,
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "traces": trace_rows,
            "total_edges": sum(len(row["edges"]) for row in trace_rows),
            "total_unresolved": sum(len(row["unresolved"]) for row in trace_rows),
        }

    def trace_function(
        self,
        *,
        signature: str,
        repo_id: str | None = None,
        force_refresh: bool = False,
    ) -> TraceFunctionResult:
        """Trace one function root and optionally reuse a valid cached result."""
        resolved_repo_id = repo_id or self.graph.repo_id
        if resolved_repo_id is None:
            raise ValueError("repo_id is required for trace execution")

        if not force_refresh:
            cached = self.graph.get_cached_jit_trace(signature, repo_id=resolved_repo_id)
            if cached is not None:
                edges = [self._normalize_cached_edge(edge) for edge in cached.get("edges", [])]
                context = self.graph.get_function_trace_context(signature, repo_id=resolved_repo_id)
                if context is None:
                    raise ValueError(f"Function signature not found in graph: {signature}")
                root = context["root"]
                return TraceFunctionResult(
                    root_signature=signature,
                    root_qualified_name=str(root.get("qualified_name") or root.get("name") or ""),
                    root_path=str(root.get("path") or ""),
                    cache_hit=True,
                    edges=edges,
                    unresolved=list(cached.get("unresolved") or []),
                    model=str(cached.get("model") or self.model),
                )

        context = self.graph.get_function_trace_context(signature, repo_id=resolved_repo_id)
        if context is None:
            raise ValueError(f"Function signature not found in graph: {signature}")

        llm_payload = self._run_llm_trace(context)
        normalized_edges, unresolved = self._normalize_llm_payload(
            context=context,
            payload=llm_payload,
        )

        root = context["root"]
        trace_id = str(uuid.uuid4())
        self.graph.store_jit_trace_result(
            repo_id=resolved_repo_id,
            root_signature=signature,
            root_file_ohash=str(root.get("file_ohash") or ""),
            trace_id=trace_id,
            model=self.model,
            max_depth=1,
            edges=normalized_edges,
            unresolved=unresolved,
        )

        return TraceFunctionResult(
            root_signature=signature,
            root_qualified_name=str(root.get("qualified_name") or root.get("name") or ""),
            root_path=str(root.get("path") or ""),
            cache_hit=False,
            edges=normalized_edges,
            unresolved=unresolved,
            model=self.model,
        )

    def _run_llm_trace(self, context: dict[str, Any]) -> dict[str, Any]:
        """Ask the extraction LLM to map one function's outgoing behavioral edges."""
        root = context["root"]
        payload = {
            "root_function": {
                "signature": root["signature"],
                "qualified_name": root["qualified_name"],
                "name": root["name"],
                "parent_class": root.get("parent_class") or "",
                "path": root["path"],
                "code": root.get("code") or "",
                "imports": root.get("imports") or [],
                "imported_by": root.get("imported_by") or [],
            },
            "siblings": context.get("siblings") or [],
            "classes": context.get("classes") or [],
            "candidate_functions": context.get("candidate_functions") or [],
        }

        response = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": TRACE_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=True),
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        content = response.choices[0].message.content or "{}"
        return json.loads(content)

    def _normalize_llm_payload(
        self,
        *,
        context: dict[str, Any],
        payload: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Validate LLM output against graph-known candidate signatures."""
        root = context["root"]
        root_signature = str(root["signature"])
        valid_candidates = {
            str(candidate["signature"]): candidate
            for candidate in (context.get("candidate_functions") or [])
        }
        normalized_edges: list[dict[str, Any]] = []
        seen_pairs: set[tuple[str, str]] = set()

        for raw_edge in payload.get("edges") or []:
            if not isinstance(raw_edge, dict):
                continue
            callee_signature = str(raw_edge.get("callee_signature") or "").strip()
            edge_type = str(raw_edge.get("edge_type") or "").strip().lower()
            if (
                not callee_signature
                or callee_signature == root_signature
                or callee_signature not in valid_candidates
                or edge_type not in RELATIONSHIP_TYPE_BY_EDGE_TYPE
            ):
                continue
            pair_key = (edge_type, callee_signature)
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            candidate = valid_candidates[callee_signature]
            confidence = float(raw_edge.get("confidence") or 0.0)
            confidence = max(0.0, min(confidence, 1.0))
            normalized_edges.append(
                {
                    "caller_signature": root_signature,
                    "callee_signature": callee_signature,
                    "callee_qualified_name": candidate.get("qualified_name") or candidate.get("name"),
                    "callee_name": candidate.get("name") or "",
                    "callee_path": candidate.get("path") or "",
                    "edge_type": edge_type,
                    "relationship_type": RELATIONSHIP_TYPE_BY_EDGE_TYPE[edge_type],
                    "confidence": confidence,
                    "rationale": str(raw_edge.get("rationale") or "").strip(),
                    "evidence": str(raw_edge.get("evidence") or "").strip(),
                }
            )

        unresolved: list[dict[str, Any]] = []
        for raw_unresolved in payload.get("unresolved") or []:
            if not isinstance(raw_unresolved, dict):
                continue
            unresolved.append(
                {
                    "target_name": str(raw_unresolved.get("target_name") or "").strip(),
                    "reason": str(raw_unresolved.get("reason") or "").strip(),
                    "evidence": str(raw_unresolved.get("evidence") or "").strip(),
                }
            )
        return normalized_edges, unresolved

    def _normalize_cached_edge(self, edge: dict[str, Any]) -> dict[str, Any]:
        """Normalize persisted cache rows back to the public trace edge shape."""
        relationship_type = str(edge.get("relationship_type") or "")
        edge_type = str(edge.get("edge_type") or "").strip().lower()
        if not edge_type:
            reverse_map = {value: key for key, value in RELATIONSHIP_TYPE_BY_EDGE_TYPE.items()}
            edge_type = reverse_map.get(relationship_type, "direct_call")
        return {
            "caller_signature": edge.get("caller_signature"),
            "callee_signature": edge.get("callee_signature"),
            "callee_qualified_name": edge.get("callee_qualified_name"),
            "callee_name": edge.get("callee_name"),
            "callee_path": edge.get("callee_path"),
            "edge_type": edge_type,
            "relationship_type": relationship_type or RELATIONSHIP_TYPE_BY_EDGE_TYPE.get(edge_type, "JIT_CALLS_DIRECT"),
            "confidence": float(edge.get("confidence") or 0.0),
            "rationale": edge.get("rationale") or "",
            "evidence": edge.get("evidence") or "",
        }
