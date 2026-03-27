import fs from "node:fs";
import path from "node:path";
import { performance } from "node:perf_hooks";
import { fileURLToPath } from "node:url";

import { createHelperFromEnv } from "../packages/am-temporal-kg/scripts/query_temporal.ts";
import { estimateTokens } from "./measure_tokens.ts";

type ConversationRelationRecord = {
  type: "conversation_relation";
  project_id: string;
  session_id: string;
  turn_index: number;
  entity_name: string;
  entity_type: string;
  predicate?: string;
  content: string;
  captured_at: string;
};

type ResearchClaimRecord = {
  type: "research_claim";
  project_id: string;
  source_key: string;
  content_hash: string;
  subject: string;
  subject_kind?: string;
  predicate: string;
  object: string;
  object_kind?: string;
  content: string;
  captured_at: string;
  source_kind?: string;
};

type ResearchRelationRecord = {
  type: "research_relation";
  project_id: string;
  source_key: string;
  content_hash: string;
  source_kind: "research_chunk" | "research_finding";
  entity_name: string;
  entity_type: string;
  predicate?: string;
  content: string;
  captured_at: string;
};

type QueryRecord = {
  type: "query";
  query_id: string;
  domain: "conversation" | "research";
  project_id: string;
  query: string;
  as_of?: string;
  expected_entity?: string;
  seed_entities?: Array<{ name: string; kind?: string }>;
};

type TraceRecord =
  | ConversationRelationRecord
  | ResearchClaimRecord
  | ResearchRelationRecord
  | QueryRecord;

type BenchmarkRow = {
  query_id: string;
  domain: string;
  baseline_latency_ms: number;
  temporal_latency_ms: number;
  temporal_seed_discovery_ms: number;
  temporal_bridge_ms: number;
  temporal_hydration_ms: number;
  baseline_token_estimate: number;
  temporal_token_estimate: number;
  token_reduction_pct: number;
  baseline_result_count: number;
  temporal_result_count: number;
  fallback_used: boolean;
  temporal_consistent: boolean;
};

const usage = `Usage:
  tsx bench/run_queries.ts --input bench/fixtures/smoke-traces.jsonl

This script expects a mixed JSONL file containing trace rows and query rows.
It writes raw benchmark rows to bench/results/phase-09-raw.jsonl by default.
`;

const getArg = (args: string[], name: string): string | undefined => {
  const index = args.indexOf(name);
  return index === -1 ? undefined : args[index + 1];
};

const readJsonl = (filePath: string): TraceRecord[] =>
  fs
    .readFileSync(path.resolve(filePath), "utf8")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => JSON.parse(line) as TraceRecord);

const toMicros = (value?: string): number | undefined => {
  if (!value) {
    return undefined;
  }
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? undefined : parsed * 1000;
};

const tokenize = (value: string): string[] =>
  Array.from(
    new Set(
      value
        .toLowerCase()
        .split(/[^a-z0-9]+/)
        .filter((token) => token.length > 2),
    ),
  );

const scoreTrace = (
  queryTerms: string[],
  haystack: string,
  modifier = 0,
): number => {
  const lowered = haystack.toLowerCase();
  let score = modifier;
  for (const term of queryTerms) {
    if (lowered.includes(term)) {
      score += 1;
    }
  }
  return score;
};

const baselineCandidates = (
  queryRow: QueryRecord,
  records: TraceRecord[],
): Array<Record<string, unknown>> => {
  const terms = tokenize(queryRow.query);
  const candidates = records
    .filter((row): row is ConversationRelationRecord | ResearchClaimRecord | ResearchRelationRecord => row.type !== "query")
    .filter((row) => row.project_id === queryRow.project_id)
    .filter((row) =>
      queryRow.domain === "conversation"
        ? row.type === "conversation_relation"
        : row.type === "research_claim" || row.type === "research_relation",
    )
    .map((row) => {
      if (row.type === "conversation_relation") {
        return {
          score: scoreTrace(terms, `${row.content} ${row.entity_name} ${row.entity_type}`, 0.25),
          snippet: row.content,
          seedName: row.entity_name,
          seedKind: row.entity_type,
          sourceKind: "conversation_turn",
          sourceId: `${row.session_id}:${row.turn_index}`,
        };
      }
      if (row.type === "research_claim") {
        return {
          score: scoreTrace(terms, `${row.content} ${row.subject} ${row.object} ${row.predicate}`, 0.5),
          snippet: row.content,
          seedName: row.object,
          seedKind: row.object_kind ?? "unknown",
          sourceKind: row.source_kind ?? "research_finding",
          sourceId: `${row.source_key}:${row.content_hash}`,
        };
      }
      return {
        score: scoreTrace(terms, `${row.content} ${row.entity_name} ${row.entity_type}`, 0.25),
        snippet: row.content,
        seedName: row.entity_name,
        seedKind: row.entity_type,
        sourceKind: row.source_kind,
        sourceId: `${row.source_key}:${row.content_hash}`,
      };
    })
    .filter((row) => Number(row.score) > 0)
    .sort((left, right) => Number(right.score) - Number(left.score));

  return candidates.slice(0, 5);
};

const deriveSeedEntities = (
  queryRow: QueryRecord,
  baselineRows: Array<Record<string, unknown>>,
): Array<{ name: string; kind?: string }> => {
  if (queryRow.seed_entities && queryRow.seed_entities.length > 0) {
    return queryRow.seed_entities;
  }

  const seen = new Set<string>();
  const seeds: Array<{ name: string; kind?: string }> = [];
  for (const row of baselineRows) {
    const name = row.seedName;
    if (typeof name !== "string") {
      continue;
    }
    const kind = typeof row.seedKind === "string" ? row.seedKind : undefined;
    const key = `${name.toLowerCase()}::${kind ?? "unknown"}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    seeds.push({ name, ...(kind ? { kind } : {}) });
    if (seeds.length >= 5) {
      break;
    }
  }
  return seeds;
};

const formatBaselineResults = (rows: Array<Record<string, unknown>>): string =>
  rows
    .map(
      (row, index) =>
        `${index + 1}. [Baseline] ${String(row.sourceKind)} ${String(row.sourceId)}\n${String(row.snippet)}`,
    )
    .join("\n\n");

const formatTemporalResults = (rows: Array<Record<string, unknown>>): string =>
  rows
    .map((row, index) => {
      const subject = (row.subject as Record<string, unknown> | undefined)?.name ?? "unknown";
      const predicate = row.predicate ?? "RELATED_TO";
      const obj = (row.object as Record<string, unknown> | undefined)?.name ?? "unknown";
      const evidence = Array.isArray(row.evidence) ? row.evidence[0] as Record<string, unknown> : undefined;
      const snippet = evidence?.rawExcerpt ?? "";
      return `${index + 1}. [Temporal] ${String(subject)} -[${String(predicate)}]-> ${String(obj)}\n${String(snippet)}`;
    })
    .join("\n\n");

const checkTemporalConsistency = (
  queryRow: QueryRecord,
  temporalRows: Array<Record<string, unknown>>,
): boolean => {
  if (!queryRow.expected_entity) {
    return temporalRows.length > 0;
  }
  const needle = queryRow.expected_entity.toLowerCase();
  return temporalRows.some((row) => {
    const subject = String((row.subject as Record<string, unknown> | undefined)?.name ?? "").toLowerCase();
    const obj = String((row.object as Record<string, unknown> | undefined)?.name ?? "").toLowerCase();
    const evidenceText = Array.isArray(row.evidence)
      ? row.evidence
          .map((item) => String((item as Record<string, unknown>).rawExcerpt ?? ""))
          .join(" ")
          .toLowerCase()
      : "";
    return subject.includes(needle) || obj.includes(needle) || evidenceText.includes(needle);
  });
};

const runCli = async (): Promise<void> => {
  const args = process.argv.slice(2);
  if (args.includes("--help") || args.includes("-h")) {
    console.log(usage);
    return;
  }

  const inputPath = getArg(args, "--input") ?? "bench/fixtures/smoke-traces.jsonl";
  const outputPath = getArg(args, "--out") ?? "bench/results/phase-09-raw.jsonl";
  const allRows = readJsonl(inputPath);
  const queryRows = allRows.filter((row): row is QueryRecord => row.type === "query");
  if (queryRows.length === 0) {
    throw new Error("No query rows found in the input JSONL.");
  }

  let helper: ReturnType<typeof createHelperFromEnv> | null = null;
  try {
    helper = createHelperFromEnv();
  } catch (error) {
    console.warn(
      `[bench] Temporal helper unavailable, queries will record fallback_used=true. ${error instanceof Error ? error.message : String(error)}`,
    );
  }

  const results: BenchmarkRow[] = [];
  for (const queryRow of queryRows) {
    const baselineStart = performance.now();
    const baselineRows = baselineCandidates(queryRow, allRows);
    const baselineLatencyMs = performance.now() - baselineStart;
    const baselineText = formatBaselineResults(baselineRows);
    const baselineTokens = estimateTokens(baselineText);

    const seedStart = performance.now();
    const seedEntities = deriveSeedEntities(queryRow, baselineRows);
    const temporalSeedDiscoveryMs = performance.now() - seedStart;

    let temporalRows: Array<Record<string, unknown>> = [];
    let temporalBridgeMs = 0;
    let temporalHydrationMs = 0;
    let temporalLatencyMs = 0;
    let fallbackUsed = false;

    if (helper && seedEntities.length > 0) {
      const temporalStart = performance.now();
      try {
        const temporalPayload = await helper.retrieve({
          op: "retrieve",
          projectId: queryRow.project_id,
          seedEntities,
          asOfUs: toMicros(queryRow.as_of),
          maxEdges: 6,
        });
        temporalRows = (temporalPayload.results as Array<Record<string, unknown>> | undefined) ?? [];
        temporalBridgeMs = Number(
          (temporalPayload.timingsMs as Record<string, unknown> | undefined)?.procedure ?? 0,
        );
        temporalHydrationMs = Number(
          (temporalPayload.timingsMs as Record<string, unknown> | undefined)?.hydrate ?? 0,
        );
      } catch (error) {
        fallbackUsed = true;
        console.warn(
          `[bench] Temporal retrieve failed for ${queryRow.query_id}: ${error instanceof Error ? error.message : String(error)}`,
        );
      }
      temporalLatencyMs = performance.now() - temporalStart;
    } else {
      fallbackUsed = true;
    }

    if (temporalRows.length === 0) {
      fallbackUsed = true;
    }

    const formattingStart = performance.now();
    const temporalText = temporalRows.length > 0 ? formatTemporalResults(temporalRows) : baselineText;
    temporalHydrationMs += performance.now() - formattingStart;
    const temporalTokens = estimateTokens(temporalText);
    const tokenReductionPct =
      baselineTokens > 0 ? ((baselineTokens - temporalTokens) / baselineTokens) * 100 : 0;

    results.push({
      query_id: queryRow.query_id,
      domain: queryRow.domain,
      baseline_latency_ms: baselineLatencyMs,
      temporal_latency_ms: temporalLatencyMs,
      temporal_seed_discovery_ms: temporalSeedDiscoveryMs,
      temporal_bridge_ms: temporalBridgeMs,
      temporal_hydration_ms: temporalHydrationMs,
      baseline_token_estimate: baselineTokens,
      temporal_token_estimate: temporalTokens,
      token_reduction_pct: tokenReductionPct,
      baseline_result_count: baselineRows.length,
      temporal_result_count: temporalRows.length,
      fallback_used: fallbackUsed,
      temporal_consistent: checkTemporalConsistency(queryRow, temporalRows),
    });
  }

  if (helper) {
    await helper.close();
  }

  fs.mkdirSync(path.dirname(path.resolve(outputPath)), { recursive: true });
  fs.writeFileSync(
    path.resolve(outputPath),
    results.map((row) => JSON.stringify(row)).join("\n") + "\n",
    "utf8",
  );

  console.log(
    JSON.stringify(
      {
        queries: results.length,
        output: path.resolve(outputPath),
        fallback_count: results.filter((row) => row.fallback_used).length,
      },
      null,
      2,
    ),
  );
};

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))) {
  void runCli().catch((error) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  });
}
