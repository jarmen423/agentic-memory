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
  high_stakes?: boolean;
};

type TraceRecord =
  | ConversationRelationRecord
  | ResearchClaimRecord
  | ResearchRelationRecord
  | QueryRecord;

type CandidateRow = Record<string, unknown>;
type CandidateSerializer = (row: CandidateRow) => string;
type CandidateFormatter = (rows: CandidateRow[]) => string;
type CandidateMatcher = (queryRow: QueryRecord, row: CandidateRow) => boolean;

type ModeMetrics = {
  latency_ms: number;
  token_estimate: number;
  result_count: number;
  hit_rank: number | null;
  reciprocal_rank: number;
  ndcg_at_10: number;
  success_at_5: boolean;
  recall_at_10: boolean;
  rerank_applied: boolean;
  rerank_provider: string | null;
  rerank_model: string | null;
  rerank_fallback_reason: string | null;
  rerank_abstained: boolean;
};

type BenchmarkRow = {
  query_id: string;
  domain: string;
  high_stakes: boolean;
  temporal_seed_discovery_ms: number;
  temporal_bridge_ms: number;
  temporal_hydration_ms: number;
  temporal_fallback_used: boolean;
  baseline: ModeMetrics;
  temporal: ModeMetrics;
  baseline_rerank: ModeMetrics;
  temporal_rerank: ModeMetrics;
  // Legacy compatibility fields kept so old notebooks/scripts can still
  // inspect the raw JSONL without understanding the nested mode snapshots.
  baseline_latency_ms: number;
  temporal_latency_ms: number;
  baseline_token_estimate: number;
  temporal_token_estimate: number;
  token_reduction_pct: number;
  baseline_result_count: number;
  temporal_result_count: number;
  fallback_used: boolean;
  temporal_consistent: boolean;
};

type RerankSettings = {
  enabled: boolean;
  provider: "cohere";
  model: string;
  timeout_ms: number;
  max_tokens_per_doc: number;
  abstain_threshold: number;
  client_name: string;
};

type RerankOutcome = {
  rows: CandidateRow[];
  latency_ms: number;
  applied: boolean;
  provider: string | null;
  model: string | null;
  fallback_reason: string | null;
  abstained: boolean;
};

type RerankResultItem = {
  index: number;
  relevance_score: number;
};

const DEFAULT_RERANK_MODEL = "rerank-v4.0-fast";
const DEFAULT_RERANK_TIMEOUT_MS = 2500;
const DEFAULT_RERANK_MAX_TOKENS_PER_DOC = 2048;
const DEFAULT_RERANK_ABSTAIN_THRESHOLD = 0.35;

const usage = `Usage:
  tsx bench/run_queries.ts --input bench/fixtures/smoke-traces.jsonl

This script replays benchmark traces and emits one JSONL row per query with
mode-level metrics for:
  - baseline first-stage retrieval
  - temporal/structural retrieval
  - baseline + learned rerank
  - temporal + learned rerank

The raw rows are written to bench/results/phase-09-raw.jsonl by default.
`;

const getArg = (args: string[], name: string): string | undefined => {
  const index = args.indexOf(name);
  return index === -1 ? undefined : args[index + 1];
};

const envFlag = (name: string, defaultValue = false): boolean => {
  const raw = process.env[name];
  if (!raw) {
    return defaultValue;
  }
  return ["1", "true", "yes", "on"].includes(raw.trim().toLowerCase());
};

const envInt = (name: string, defaultValue: number): number => {
  const raw = process.env[name];
  if (!raw) {
    return defaultValue;
  }
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : defaultValue;
};

const envFloat = (name: string, defaultValue: number): number => {
  const raw = process.env[name];
  if (!raw) {
    return defaultValue;
  }
  const parsed = Number.parseFloat(raw);
  return Number.isFinite(parsed) ? parsed : defaultValue;
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

/**
 * Load rerank settings from the same environment variables used by the Python
 * server code so the benchmark can replay the same provider/model choices.
 */
const loadRerankSettings = (): RerankSettings => ({
  enabled: envFlag("AM_RERANK_ENABLED", false),
  provider: "cohere",
  model: process.env.AM_RERANK_MODEL?.trim() || DEFAULT_RERANK_MODEL,
  timeout_ms: envInt("AM_RERANK_TIMEOUT_MS", DEFAULT_RERANK_TIMEOUT_MS),
  max_tokens_per_doc: envInt(
    "AM_RERANK_MAX_TOKENS_PER_DOC",
    DEFAULT_RERANK_MAX_TOKENS_PER_DOC,
  ),
  abstain_threshold: envFloat(
    "AM_RERANK_ABSTAIN_THRESHOLD",
    DEFAULT_RERANK_ABSTAIN_THRESHOLD,
  ),
  client_name: process.env.AM_RERANK_CLIENT_NAME?.trim() || "agentic-memory-bench",
});

const buildYamlCard = (fields: Array<[string, unknown]>): string => {
  const lines: string[] = [];
  for (const [key, value] of fields) {
    if (value === null || value === undefined) {
      continue;
    }
    if (typeof value === "string") {
      const trimmed = value.trim();
      if (!trimmed) {
        continue;
      }
      if (trimmed.includes("\n")) {
        lines.push(`${key}: |-`);
        lines.push(...trimmed.split(/\r?\n/).map((line) => `  ${line}`));
      } else {
        lines.push(`${key}: ${trimmed}`);
      }
      continue;
    }
    if (Array.isArray(value)) {
      const items = value.map((item) => String(item).trim()).filter(Boolean);
      if (items.length === 0) {
        continue;
      }
      lines.push(`${key}:`);
      lines.push(...items.map((item) => `  - ${item}`));
      continue;
    }
    lines.push(`${key}: ${String(value)}`);
  }
  return lines.join("\n");
};

const serializeBaselineCandidate: CandidateSerializer = (row) =>
  buildYamlCard([
    ["source_kind", row.sourceKind],
    ["source_id", row.sourceId],
    ["seed_name", row.seedName],
    ["seed_kind", row.seedKind],
    ["snippet", row.snippet],
  ]);

const serializeTemporalCandidate: CandidateSerializer = (row) => {
  const subject = row.subject as Record<string, unknown> | undefined;
  const object = row.object as Record<string, unknown> | undefined;
  const evidence = Array.isArray(row.evidence) ? (row.evidence[0] as Record<string, unknown> | undefined) : undefined;
  return buildYamlCard([
    ["subject", subject?.name],
    ["predicate", row.predicate],
    ["object", object?.name],
    ["source_kind", evidence?.sourceKind],
    ["source_id", evidence?.sourceId],
    ["snippet", evidence?.rawExcerpt],
  ]);
};

const formatBaselineResults: CandidateFormatter = (rows) =>
  rows
    .map(
      (row, index) =>
        `${index + 1}. [Baseline] ${String(row.sourceKind)} ${String(row.sourceId)}\n${String(row.snippet)}`,
    )
    .join("\n\n");

const formatTemporalResults: CandidateFormatter = (rows) =>
  rows
    .map((row, index) => {
      const subject = (row.subject as Record<string, unknown> | undefined)?.name ?? "unknown";
      const predicate = row.predicate ?? "RELATED_TO";
      const obj = (row.object as Record<string, unknown> | undefined)?.name ?? "unknown";
      const evidence = Array.isArray(row.evidence) ? (row.evidence[0] as Record<string, unknown> | undefined) : undefined;
      const snippet = evidence?.rawExcerpt ?? "";
      return `${index + 1}. [Temporal] ${String(subject)} -[${String(predicate)}]-> ${String(obj)}\n${String(snippet)}`;
    })
    .join("\n\n");

const baselineCandidateMatches: CandidateMatcher = (queryRow, row) => {
  if (!queryRow.expected_entity) {
    return false;
  }
  const needle = queryRow.expected_entity.toLowerCase();
  return [row.seedName, row.seedKind, row.snippet, row.sourceId]
    .map((value) => String(value ?? "").toLowerCase())
    .some((value) => value.includes(needle));
};

const temporalCandidateMatches: CandidateMatcher = (queryRow, row) => {
  if (!queryRow.expected_entity) {
    return false;
  }
  const needle = queryRow.expected_entity.toLowerCase();
  const subject = String((row.subject as Record<string, unknown> | undefined)?.name ?? "").toLowerCase();
  const obj = String((row.object as Record<string, unknown> | undefined)?.name ?? "").toLowerCase();
  const evidenceText = Array.isArray(row.evidence)
    ? row.evidence
        .map((item) => String((item as Record<string, unknown>).rawExcerpt ?? ""))
        .join(" ")
        .toLowerCase()
    : "";
  return subject.includes(needle) || obj.includes(needle) || evidenceText.includes(needle);
};

const findHitRank = (
  rows: CandidateRow[],
  queryRow: QueryRecord,
  matcher: CandidateMatcher,
): number | null => {
  if (!queryRow.expected_entity) {
    return rows.length > 0 ? 1 : null;
  }
  for (let index = 0; index < rows.length; index += 1) {
    if (matcher(queryRow, rows[index])) {
      return index + 1;
    }
  }
  return null;
};

const reciprocalRank = (rank: number | null): number => (rank && rank > 0 ? 1 / rank : 0);

const ndcgAt10 = (rank: number | null): number =>
  rank && rank > 0 && rank <= 10 ? 1 / Math.log2(rank + 1) : 0;

const buildModeMetrics = (
  rows: CandidateRow[],
  {
    formatter,
    matcher,
    queryRow,
    latencyMs,
    rerankApplied = false,
    rerankProvider = null,
    rerankModel = null,
    rerankFallbackReason = null,
    rerankAbstained = false,
  }: {
    formatter: CandidateFormatter;
    matcher: CandidateMatcher;
    queryRow: QueryRecord;
    latencyMs: number;
    rerankApplied?: boolean;
    rerankProvider?: string | null;
    rerankModel?: string | null;
    rerankFallbackReason?: string | null;
    rerankAbstained?: boolean;
  },
): ModeMetrics => {
  const text = formatter(rows);
  const hitRank = findHitRank(rows, queryRow, matcher);
  return {
    latency_ms: latencyMs,
    token_estimate: estimateTokens(text),
    result_count: rows.length,
    hit_rank: hitRank,
    reciprocal_rank: reciprocalRank(hitRank),
    ndcg_at_10: ndcgAt10(hitRank),
    success_at_5: hitRank !== null && hitRank <= 5,
    recall_at_10: hitRank !== null && hitRank <= 10,
    rerank_applied: rerankApplied,
    rerank_provider: rerankProvider,
    rerank_model: rerankModel,
    rerank_fallback_reason: rerankFallbackReason,
    rerank_abstained: rerankAbstained,
  };
};

/**
 * First-stage benchmark retrieval intentionally stays simple: it approximates
 * dense/lexical candidate generation from the replay fixture rather than
 * hitting the live service. The rerank stage is where we optionally use the
 * hosted provider to measure final ordering quality and latency.
 */
const baselineCandidates = (
  queryRow: QueryRecord,
  records: TraceRecord[],
): CandidateRow[] => {
  const terms = tokenize(queryRow.query);
  const candidates = records
    .filter(
      (row): row is ConversationRelationRecord | ResearchClaimRecord | ResearchRelationRecord =>
        row.type !== "query",
    )
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
          score: scoreTrace(
            terms,
            `${row.content} ${row.subject} ${row.object} ${row.predicate}`,
            0.5,
          ),
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
  baselineRows: CandidateRow[],
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

const reorderByScores = (
  rows: CandidateRow[],
  scores: RerankResultItem[],
): CandidateRow[] => {
  const ordered: CandidateRow[] = [];
  const seen = new Set<number>();
  for (const score of scores) {
    const candidate = rows[score.index];
    if (!candidate) {
      continue;
    }
    ordered.push(candidate);
    seen.add(score.index);
  }
  rows.forEach((row, index) => {
    if (!seen.has(index)) {
      ordered.push(row);
    }
  });
  return ordered;
};

const rerankRows = async ({
  query,
  rows,
  serializer,
  highStakes,
}: {
  query: string;
  rows: CandidateRow[];
  serializer: CandidateSerializer;
  highStakes: boolean;
}): Promise<RerankOutcome> => {
  const settings = loadRerankSettings();
  if (!settings.enabled) {
    return {
      rows,
      latency_ms: 0,
      applied: false,
      provider: settings.provider,
      model: settings.model,
      fallback_reason: "disabled",
      abstained: false,
    };
  }
  if (rows.length < 2) {
    return {
      rows,
      latency_ms: 0,
      applied: false,
      provider: settings.provider,
      model: settings.model,
      fallback_reason: "too_few_candidates",
      abstained: false,
    };
  }

  const apiKey = process.env.COHERE_API_KEY?.trim();
  if (!apiKey) {
    return {
      rows,
      latency_ms: 0,
      applied: false,
      provider: settings.provider,
      model: settings.model,
      fallback_reason: "missing_api_key",
      abstained: false,
    };
  }

  const startedAt = performance.now();
  try {
    const response = await fetch("https://api.cohere.com/v2/rerank", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${apiKey}`,
        "Content-Type": "application/json",
        "X-Client-Name": settings.client_name,
      },
      body: JSON.stringify({
        model: settings.model,
        query,
        documents: rows.map(serializer),
        top_n: rows.length,
        max_tokens_per_doc: settings.max_tokens_per_doc,
      }),
      signal: AbortSignal.timeout(settings.timeout_ms),
    });
    if (!response.ok) {
      throw new Error(`HTTP_${response.status}`);
    }
    const body = (await response.json()) as { results?: RerankResultItem[] };
    const scores = Array.isArray(body.results) ? body.results : [];
    if (scores.length === 0) {
      return {
        rows,
        latency_ms: performance.now() - startedAt,
        applied: false,
        provider: settings.provider,
        model: settings.model,
        fallback_reason: "empty_results",
        abstained: false,
      };
    }

    const topScore = scores[0]?.relevance_score ?? null;
    const abstained = Boolean(
      highStakes && topScore !== null && topScore < settings.abstain_threshold,
    );
    return {
      rows: abstained ? [] : reorderByScores(rows, scores),
      latency_ms: performance.now() - startedAt,
      applied: true,
      provider: settings.provider,
      model: settings.model,
      fallback_reason: null,
      abstained,
    };
  } catch (error) {
    return {
      rows,
      latency_ms: performance.now() - startedAt,
      applied: false,
      provider: settings.provider,
      model: settings.model,
      fallback_reason: error instanceof Error ? error.message : String(error),
      abstained: false,
    };
  }
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
      `[bench] Temporal helper unavailable, queries will record temporal_fallback_used=true. ${error instanceof Error ? error.message : String(error)}`,
    );
  }

  const results: BenchmarkRow[] = [];
  for (const queryRow of queryRows) {
    const baselineStart = performance.now();
    const baselineRows = baselineCandidates(queryRow, allRows);
    const baselineLatencyMs = performance.now() - baselineStart;
    const baselineMetrics = buildModeMetrics(baselineRows, {
      formatter: formatBaselineResults,
      matcher: baselineCandidateMatches,
      queryRow,
      latencyMs: baselineLatencyMs,
    });

    const seedStart = performance.now();
    const seedEntities = deriveSeedEntities(queryRow, baselineRows);
    const temporalSeedDiscoveryMs = performance.now() - seedStart;

    let temporalRows: CandidateRow[] = [];
    let temporalBridgeMs = 0;
    let temporalHydrationMs = 0;
    let temporalLatencyMs = 0;
    let temporalFallbackUsed = false;

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
        temporalRows = (temporalPayload.results as CandidateRow[] | undefined) ?? [];
        temporalBridgeMs = Number(
          (temporalPayload.timingsMs as Record<string, unknown> | undefined)?.procedure ?? 0,
        );
        temporalHydrationMs = Number(
          (temporalPayload.timingsMs as Record<string, unknown> | undefined)?.hydrate ?? 0,
        );
      } catch (error) {
        temporalFallbackUsed = true;
        console.warn(
          `[bench] Temporal retrieve failed for ${queryRow.query_id}: ${error instanceof Error ? error.message : String(error)}`,
        );
      }
      temporalLatencyMs = performance.now() - temporalStart;
    } else {
      temporalFallbackUsed = true;
    }

    if (temporalRows.length === 0) {
      temporalFallbackUsed = true;
    }

    const temporalEffectiveRows = temporalRows.length > 0 ? temporalRows : baselineRows;
    const temporalFormatter = temporalRows.length > 0 ? formatTemporalResults : formatBaselineResults;
    const temporalMatcher = temporalRows.length > 0 ? temporalCandidateMatches : baselineCandidateMatches;
    const temporalSerializer = temporalRows.length > 0 ? serializeTemporalCandidate : serializeBaselineCandidate;

    const formattingStart = performance.now();
    temporalFormatter(temporalEffectiveRows);
    temporalHydrationMs += performance.now() - formattingStart;
    const temporalMetrics = buildModeMetrics(temporalEffectiveRows, {
      formatter: temporalFormatter,
      matcher: temporalMatcher,
      queryRow,
      latencyMs: temporalLatencyMs,
    });

    const baselineRerank = await rerankRows({
      query: queryRow.query,
      rows: baselineRows,
      serializer: serializeBaselineCandidate,
      highStakes: Boolean(queryRow.high_stakes),
    });
    const baselineRerankMetrics = buildModeMetrics(baselineRerank.rows, {
      formatter: formatBaselineResults,
      matcher: baselineCandidateMatches,
      queryRow,
      latencyMs: baselineMetrics.latency_ms + baselineRerank.latency_ms,
      rerankApplied: baselineRerank.applied,
      rerankProvider: baselineRerank.provider,
      rerankModel: baselineRerank.model,
      rerankFallbackReason: baselineRerank.fallback_reason,
      rerankAbstained: baselineRerank.abstained,
    });

    const temporalRerank = await rerankRows({
      query: queryRow.query,
      rows: temporalEffectiveRows,
      serializer: temporalSerializer,
      highStakes: Boolean(queryRow.high_stakes),
    });
    const temporalRerankMetrics = buildModeMetrics(temporalRerank.rows, {
      formatter: temporalFormatter,
      matcher: temporalMatcher,
      queryRow,
      latencyMs: temporalMetrics.latency_ms + temporalRerank.latency_ms,
      rerankApplied: temporalRerank.applied,
      rerankProvider: temporalRerank.provider,
      rerankModel: temporalRerank.model,
      rerankFallbackReason: temporalRerank.fallback_reason,
      rerankAbstained: temporalRerank.abstained,
    });

    const tokenReductionPct =
      baselineMetrics.token_estimate > 0
        ? ((baselineMetrics.token_estimate - temporalMetrics.token_estimate) /
            baselineMetrics.token_estimate) *
          100
        : 0;

    results.push({
      query_id: queryRow.query_id,
      domain: queryRow.domain,
      high_stakes: Boolean(queryRow.high_stakes),
      temporal_seed_discovery_ms: temporalSeedDiscoveryMs,
      temporal_bridge_ms: temporalBridgeMs,
      temporal_hydration_ms: temporalHydrationMs,
      temporal_fallback_used: temporalFallbackUsed,
      baseline: baselineMetrics,
      temporal: temporalMetrics,
      baseline_rerank: baselineRerankMetrics,
      temporal_rerank: temporalRerankMetrics,
      baseline_latency_ms: baselineMetrics.latency_ms,
      temporal_latency_ms: temporalMetrics.latency_ms,
      baseline_token_estimate: baselineMetrics.token_estimate,
      temporal_token_estimate: temporalMetrics.token_estimate,
      token_reduction_pct: tokenReductionPct,
      baseline_result_count: baselineMetrics.result_count,
      temporal_result_count: temporalMetrics.result_count,
      fallback_used: temporalFallbackUsed,
      temporal_consistent: temporalMetrics.recall_at_10,
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
        temporal_fallback_count: results.filter((row) => row.temporal_fallback_used).length,
        rerank_applied_count: results.filter(
          (row) => row.baseline_rerank.rerank_applied || row.temporal_rerank.rerank_applied,
        ).length,
        rerank_abstention_count: results.filter(
          (row) => row.baseline_rerank.rerank_abstained || row.temporal_rerank.rerank_abstained,
        ).length,
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
