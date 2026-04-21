"""Retrieval evaluation helpers for Agentic Memory.

This package contains the Python-side evaluation harness used to measure
retrieval quality across the code, research, and conversation domains. It is
intentionally separate from the existing TypeScript temporal benchmark harness:

- ``bench/run_queries.ts`` remains the phase-09 temporal replay benchmark
- this package runs gold-query retrieval evaluation against the Python search
  stack directly

The package is designed so future agents can discover:

- where gold query fixtures live
- how smoke vs live evaluation differs
- which metrics are considered the retrieval quality source of truth
"""

