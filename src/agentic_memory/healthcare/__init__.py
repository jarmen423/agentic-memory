"""Healthcare ingestion domain for Agentic Memory.

This package provides a complete pipeline for ingesting Synthea synthetic
clinical data (CSV format) into the Neo4j memory graph and SpacetimeDB
temporal layer. It is the foundation for two experiments:

  Experiment 1 — Temporal Decay:
      Validates that SpacetimeDB PPR temporal decay improves retrieval rank
      of the most-recent clinical fact vs flat vector search.

  Experiment 2 — Multi-hop Clinical Reasoning:
      Validates that Neo4j Cypher graph traversal outperforms vector-only
      search for multi-constraint cohort queries (e.g., patients with
      condition X AND medication Y, and the providers who treated them).

Modules:
  csv_loader      — SyntheaCSVLoader: reads all 7 Synthea CSV tables
  embed_text      — build_*_embed_text(): constructs prose summaries for embedding
  embedding_payloads — reusable row → embedding-input helpers for export/import
  temporal_mapper — condition/medication/observation → SpacetimeDB claim dicts
  graph_writer_hc — HealthcareGraphWriter: clinical relationship patterns
  pipeline        — HealthcareIngestionPipeline: main orchestration class
"""
