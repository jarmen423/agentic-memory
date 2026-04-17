"""Experiment 2 — Multi-hop Clinical Reasoning: Graph vs Vector.

Hypothesis:
    Neo4j Cypher multi-hop graph traversal outperforms flat vector similarity
    search on multi-constraint cohort queries (e.g., "providers who treated
    patients with condition X AND medication Y").

What this script does:
    1. Generates (or loads) multi-hop cohort query tasks from the Synthea CSV.
    2. For each task, runs two retrieval methods:
         a. Cypher multi-hop: a parameterised Cypher query that traverses
            Patient → Condition, Patient → Medication, Patient → Encounter →
            Provider in a single query.
         b. Vector-only: embeds the natural-language query, retrieves the
            top-K most similar Memory nodes, then extracts provider IDs from
            those nodes' metadata.
    3. Scores both methods against the CSV-derived ground truth using
       Precision / Recall / F1 over provider_ids.
    4. Writes results and prints a comparison table.

Usage (after running ingest_synthea.py):
    python experiments/healthcare/exp2_multihop.py \\
        --data-dir "G:/My Drive/.../synthea_2017_02_27/" \\
        --project-id synthea-experiment \\
        --output-dir experiments/healthcare/results

Required environment variables:
    NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD   — same as ingest_synthea.py
    EMBEDDING_PROVIDER + API key             — for vector-only retrieval

Cypher query used (parameterised):
    MATCH (pat:Entity:Patient)-[:DIAGNOSED_WITH]->(cond:Memory:Healthcare:Condition)
    WHERE toLower(cond.description) CONTAINS toLower($condition_description)
    WITH collect(pat.name) AS cond_patients
    MATCH (pat2:Entity:Patient)-[:PRESCRIBED]->(med:Memory:Healthcare:Medication)
    WHERE toLower(med.description) CONTAINS toLower($medication_description)
      AND pat2.name IN cond_patients
    WITH collect(pat2.name) AS matched_patients
    MATCH (enc:Memory:Healthcare:Encounter)-[:TREATED_BY]->(prov:Entity:Provider)
    MATCH (pat3:Entity:Patient)-[:HAD_ENCOUNTER]->(enc)
    WHERE pat3.name IN matched_patients
    RETURN DISTINCT prov.name AS provider_id, count(enc) AS encounter_count
    ORDER BY encounter_count DESC
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from experiments.healthcare.eval_runner import (
    EvalResult,
    aggregate_cohort_results,
    print_summary_table,
    save_results,
    score_cohort_task,
)
from experiments.healthcare.qa_generator import SyntheaQAGenerator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("exp2_multihop")

# Multi-hop Cypher query — three hops:
#   Patient → DIAGNOSED_WITH → Condition (filter by description)
#   Patient → PRESCRIBED → Medication (filter by description)
#   Patient → HAD_ENCOUNTER → Encounter → TREATED_BY → Provider
_COHORT_CYPHER = """\
MATCH (pat:Entity:Patient)-[:DIAGNOSED_WITH]->(cond:Memory:Healthcare:Condition {project_id: $project_id})
WHERE toLower(cond.description) CONTAINS toLower($condition_description)
WITH collect(DISTINCT pat.name) AS cond_patients

MATCH (pat2:Entity:Patient)-[:PRESCRIBED]->(med:Memory:Healthcare:Medication {project_id: $project_id})
WHERE toLower(med.description) CONTAINS toLower($medication_description)
  AND pat2.name IN cond_patients
WITH collect(DISTINCT pat2.name) AS matched_patients

MATCH (enc:Memory:Healthcare:Encounter {project_id: $project_id})-[:TREATED_BY]->(prov:Entity:Provider)
MATCH (pat3:Entity:Patient)-[:HAD_ENCOUNTER]->(enc)
WHERE pat3.name IN matched_patients
RETURN DISTINCT prov.name AS provider_id, count(enc) AS encounter_count
ORDER BY encounter_count DESC
"""

# Vector-only: embed query text → cosine similarity → top-K Encounter nodes →
# extract provider_id from node properties
_VECTOR_SEARCH_CYPHER = """\
CALL db.index.vector.queryNodes('healthcare_embeddings', $top_k, $query_vector)
YIELD node, score
WHERE node:Encounter AND node.project_id = $project_id AND score >= $min_score
RETURN DISTINCT node.provider_id AS provider_id, max(score) AS max_score
ORDER BY max_score DESC
"""


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Experiment 2: Cypher multi-hop vs vector-only cohort retrieval.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--data-dir",
        required=True,
        help="Path to extracted Synthea CSV directory.",
    )
    parser.add_argument(
        "--project-id",
        default="synthea-experiment",
        help="Project ID (must match the ingestion run).",
    )
    parser.add_argument(
        "--tasks-file",
        default=None,
        help="Optional: load pre-generated cohort tasks from this JSON file.",
    )
    parser.add_argument(
        "--output-dir",
        default="experiments/healthcare/results",
        help="Directory to write result JSON files.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=50,
        help="Number of nodes to retrieve in vector-only mode.",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.75,
        help="Minimum cosine similarity score threshold for vector-only mode.",
    )
    return parser.parse_args()


def retrieve_cypher_multihop(
    conn,
    task: dict[str, Any],
    project_id: str,
) -> tuple[list[str], float]:
    """Run the multi-hop Cypher query for a cohort task.

    Args:
        conn: ConnectionManager instance with an active Neo4j driver.
        task: Cohort task dict from QA generator.

    Returns:
        Tuple of (provider_id_list ordered by encounter_count, latency_ms).
    """
    t0 = time.perf_counter()
    try:
        with conn.session() as s:
            result = s.run(
                _COHORT_CYPHER,
                project_id=project_id,
                condition_description=task["condition_description"],
                medication_description=task["medication_description"],
            )
            providers = [record["provider_id"] for record in result if record["provider_id"]]
    except Exception as exc:
        logger.warning("Cypher multihop failed for task %s: %s", task.get("id"), exc)
        return [], 0.0

    latency_ms = (time.perf_counter() - t0) * 1000
    logger.debug(
        "Cypher [%s]: %d providers in %.1fms", task.get("id"), len(providers), latency_ms
    )
    return providers, latency_ms


def retrieve_vector_only(
    conn,
    embedder,
    task: dict[str, Any],
    project_id: str,
    top_k: int,
    min_score: float,
) -> tuple[list[str], float]:
    """Run vector-only retrieval for a cohort task.

    Embeds the natural-language query string, calls the healthcare_embeddings
    vector index, and extracts provider_id from the returned Encounter nodes.

    Args:
        conn: ConnectionManager instance.
        embedder: EmbeddingService instance.
        task: Cohort task dict.
        top_k: Number of vector-similar nodes to retrieve.
        min_score: Minimum cosine similarity threshold.

    Returns:
        Tuple of (provider_id_list, latency_ms).
    """
    t0 = time.perf_counter()
    try:
        # Embed the natural-language query text
        query_vector = embedder.embed(task["query"])

        with conn.session() as s:
            result = s.run(
                _VECTOR_SEARCH_CYPHER,
                project_id=project_id,
                query_vector=query_vector,
                top_k=top_k,
                min_score=min_score,
            )
            providers = [record["provider_id"] for record in result if record["provider_id"]]
    except Exception as exc:
        logger.warning("Vector retrieval failed for task %s: %s", task.get("id"), exc)
        return [], 0.0

    latency_ms = (time.perf_counter() - t0) * 1000
    logger.debug(
        "Vector [%s]: %d providers in %.1fms", task.get("id"), len(providers), latency_ms
    )
    return providers, latency_ms


def run_experiment(args: argparse.Namespace) -> None:
    """Main experiment loop.

    Args:
        args: Parsed argument namespace.
    """
    from agentic_memory.core.connection import ConnectionManager
    from agentic_memory.core.embedding import EmbeddingService

    # Build Neo4j connection
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")
    if not all([uri, user, password]):
        logger.error("NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD must be set.")
        sys.exit(1)
    conn = ConnectionManager(uri, user, password)

    # Build embedding service for vector-only retrieval
    provider = os.getenv("EMBEDDING_PROVIDER", "gemini")
    api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("OPENAI_API_KEY")
    embedder = EmbeddingService(provider=provider, api_key=api_key)

    # Generate or load cohort tasks
    if args.tasks_file:
        logger.info("Loading tasks from %s", args.tasks_file)
        tasks = SyntheaQAGenerator.load_tasks(args.tasks_file)
    else:
        logger.info("Generating cohort QA tasks from %s", args.data_dir)
        generator = SyntheaQAGenerator(args.data_dir)
        tasks = generator.generate_cohort_qa()
        task_path = Path(args.output_dir) / "exp2_tasks_generated.json"
        SyntheaQAGenerator.save_tasks(tasks, task_path)
        logger.info("Tasks saved to %s", task_path)

    logger.info("Running Experiment 2 on %d cohort tasks...", len(tasks))

    # --- Method A: Cypher multi-hop ---
    cypher_results: list[EvalResult] = []
    cypher_config = {"method": "cypher_multihop", "hops": 3, "project_id": args.project_id}
    for task in tasks:
        providers, latency = retrieve_cypher_multihop(conn, task, args.project_id)
        result = score_cohort_task(
            task=task,
            retrieved_provider_ids=providers,
            retrieval_config=cypher_config,
            latency_ms=latency,
        )
        cypher_results.append(result)
        logger.info(
            "Cypher [%s]: P=%.3f R=%.3f F1=%.3f retrieved=%d gt=%d",
            task["id"],
            result.precision,
            result.recall,
            result.f1,
            len(providers),
            task.get("provider_count", "?"),
        )

    cypher_agg = aggregate_cohort_results(cypher_results)

    # --- Method B: Vector-only ---
    vector_results: list[EvalResult] = []
    vector_config = {
        "method": "vector_only",
        "top_k": args.top_k,
        "min_score": args.min_score,
        "project_id": args.project_id,
    }
    for task in tasks:
        providers, latency = retrieve_vector_only(
            conn,
            embedder,
            task,
            args.project_id,
            top_k=args.top_k,
            min_score=args.min_score,
        )
        result = score_cohort_task(
            task=task,
            retrieved_provider_ids=providers,
            retrieval_config=vector_config,
            latency_ms=latency,
        )
        vector_results.append(result)
        logger.info(
            "Vector [%s]: P=%.3f R=%.3f F1=%.3f retrieved=%d",
            task["id"],
            result.precision,
            result.recall,
            result.f1,
            len(providers),
        )

    vector_agg = aggregate_cohort_results(vector_results)

    # --- Save results ---
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    save_results(
        results=cypher_results,
        aggregate=cypher_agg,
        output_path=Path(args.output_dir) / f"exp2_cypher_{timestamp}.json",
        metadata={"experiment": "exp2_multihop", "method": "cypher", "timestamp": timestamp},
    )
    save_results(
        results=vector_results,
        aggregate=vector_agg,
        output_path=Path(args.output_dir) / f"exp2_vector_{timestamp}.json",
        metadata={"experiment": "exp2_multihop", "method": "vector", "timestamp": timestamp},
    )

    # --- Print comparison table ---
    print_summary_table(
        configs=["cypher_multihop", "vector_only"],
        aggregates=[cypher_agg, vector_agg],
        experiment_id="exp2",
    )

    # Hypothesis check
    cypher_f1 = cypher_agg["mean_f1"]
    vector_f1 = vector_agg["mean_f1"]
    delta = cypher_f1 - vector_f1
    print(f"Cypher F1={cypher_f1:.4f}  Vector F1={vector_f1:.4f}  Δ={delta:+.4f}")
    if delta > 0:
        print("✓ Hypothesis SUPPORTED: multi-hop graph traversal outperforms vector-only.")
    else:
        print("✗ Hypothesis NOT supported at this dataset size / query set.")

    conn.close()


if __name__ == "__main__":
    run_experiment(parse_args())
