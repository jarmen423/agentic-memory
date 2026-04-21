import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

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
};

type LegacyBenchmarkRow = {
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

type RawBenchmarkRow = BenchmarkRow | LegacyBenchmarkRow;

const usage = `Usage:
  tsx bench/report_results.ts --input bench/results/phase-09-raw.jsonl

Writes:
  bench/results/phase-09-report.md
  bench/results/phase-09-report.json
`;

const MODE_DEFINITIONS = [
  { key: "baseline", label: "Baseline" },
  { key: "temporal", label: "Temporal / Structural" },
  { key: "baseline_rerank", label: "Baseline + Rerank" },
  { key: "temporal_rerank", label: "Temporal + Rerank" },
] as const;

type ModeKey = (typeof MODE_DEFINITIONS)[number]["key"];

const getArg = (args: string[], name: string): string | undefined => {
  const index = args.indexOf(name);
  return index === -1 ? undefined : args[index + 1];
};

const mean = (values: number[]): number =>
  values.length === 0 ? 0 : values.reduce((sum, value) => sum + value, 0) / values.length;

const p95 = (values: number[]): number => {
  if (values.length === 0) {
    return 0;
  }
  const sorted = [...values].sort((left, right) => left - right);
  const index = Math.min(sorted.length - 1, Math.ceil(sorted.length * 0.95) - 1);
  return sorted[index];
};

const pct = (numerator: number, denominator: number): number =>
  denominator === 0 ? 0 : (numerator / denominator) * 100;

const round = (value: number): number => Math.round(value * 100) / 100;

const buildModeMetrics = (
  partial: Partial<ModeMetrics> & {
    latency_ms?: number;
    token_estimate?: number;
    result_count?: number;
  },
): ModeMetrics => ({
  latency_ms: partial.latency_ms ?? 0,
  token_estimate: partial.token_estimate ?? 0,
  result_count: partial.result_count ?? 0,
  hit_rank: partial.hit_rank ?? null,
  reciprocal_rank: partial.reciprocal_rank ?? 0,
  ndcg_at_10: partial.ndcg_at_10 ?? 0,
  success_at_5: partial.success_at_5 ?? false,
  recall_at_10: partial.recall_at_10 ?? false,
  rerank_applied: partial.rerank_applied ?? false,
  rerank_provider: partial.rerank_provider ?? null,
  rerank_model: partial.rerank_model ?? null,
  rerank_fallback_reason: partial.rerank_fallback_reason ?? null,
  rerank_abstained: partial.rerank_abstained ?? false,
});

const normalizeLegacyRow = (row: LegacyBenchmarkRow): BenchmarkRow => {
  const temporalHit = row.temporal_consistent;
  return {
    query_id: row.query_id,
    domain: row.domain,
    high_stakes: false,
    temporal_seed_discovery_ms: row.temporal_seed_discovery_ms,
    temporal_bridge_ms: row.temporal_bridge_ms,
    temporal_hydration_ms: row.temporal_hydration_ms,
    temporal_fallback_used: row.fallback_used,
    baseline: buildModeMetrics({
      latency_ms: row.baseline_latency_ms,
      token_estimate: row.baseline_token_estimate,
      result_count: row.baseline_result_count,
    }),
    temporal: buildModeMetrics({
      latency_ms: row.temporal_latency_ms,
      token_estimate: row.temporal_token_estimate,
      result_count: row.temporal_result_count,
      hit_rank: temporalHit ? 1 : null,
      reciprocal_rank: temporalHit ? 1 : 0,
      ndcg_at_10: temporalHit ? 1 : 0,
      success_at_5: temporalHit,
      recall_at_10: temporalHit,
    }),
    baseline_rerank: buildModeMetrics({
      latency_ms: row.baseline_latency_ms,
      token_estimate: row.baseline_token_estimate,
      result_count: row.baseline_result_count,
      rerank_fallback_reason: "legacy_row_missing_rerank_metrics",
    }),
    temporal_rerank: buildModeMetrics({
      latency_ms: row.temporal_latency_ms,
      token_estimate: row.temporal_token_estimate,
      result_count: row.temporal_result_count,
      hit_rank: temporalHit ? 1 : null,
      reciprocal_rank: temporalHit ? 1 : 0,
      ndcg_at_10: temporalHit ? 1 : 0,
      success_at_5: temporalHit,
      recall_at_10: temporalHit,
      rerank_fallback_reason: "legacy_row_missing_rerank_metrics",
    }),
  };
};

const normalizeRow = (row: RawBenchmarkRow): BenchmarkRow => {
  if ("baseline" in row && "temporal" in row) {
    return {
      query_id: row.query_id,
      domain: row.domain,
      high_stakes: row.high_stakes ?? false,
      temporal_seed_discovery_ms: row.temporal_seed_discovery_ms ?? 0,
      temporal_bridge_ms: row.temporal_bridge_ms ?? 0,
      temporal_hydration_ms: row.temporal_hydration_ms ?? 0,
      temporal_fallback_used: row.temporal_fallback_used ?? false,
      baseline: buildModeMetrics(row.baseline),
      temporal: buildModeMetrics(row.temporal),
      baseline_rerank: buildModeMetrics(row.baseline_rerank),
      temporal_rerank: buildModeMetrics(row.temporal_rerank),
    };
  }
  return normalizeLegacyRow(row as LegacyBenchmarkRow);
};

const readJsonl = (filePath: string): BenchmarkRow[] =>
  fs
    .readFileSync(path.resolve(filePath), "utf8")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => normalizeRow(JSON.parse(line) as RawBenchmarkRow));

const aggregateMode = (
  rows: BenchmarkRow[],
  modeKey: ModeKey,
): Record<string, number> => {
  const modeRows = rows.map((row) => row[modeKey]);
  return {
    mean_latency_ms: mean(modeRows.map((row) => row.latency_ms)),
    p95_latency_ms: p95(modeRows.map((row) => row.latency_ms)),
    mean_token_estimate: mean(modeRows.map((row) => row.token_estimate)),
    mean_result_count: mean(modeRows.map((row) => row.result_count)),
    mrr_at_10: mean(modeRows.map((row) => row.reciprocal_rank)),
    ndcg_at_10: mean(modeRows.map((row) => row.ndcg_at_10)),
    success_at_5_pct: pct(
      modeRows.filter((row) => row.success_at_5).length,
      rows.length,
    ),
    recall_at_10_pct: pct(
      modeRows.filter((row) => row.recall_at_10).length,
      rows.length,
    ),
    rerank_applied_pct: pct(
      modeRows.filter((row) => row.rerank_applied).length,
      rows.length,
    ),
    rerank_abstained_pct: pct(
      modeRows.filter((row) => row.rerank_abstained).length,
      rows.length,
    ),
    rerank_fallback_pct: pct(
      modeRows.filter((row) => Boolean(row.rerank_fallback_reason)).length,
      rows.length,
    ),
  };
};

const buildMarkdown = (
  rows: BenchmarkRow[],
  aggregates: Record<string, number>,
  modeSummaries: Record<ModeKey, Record<string, number>>,
): string => `# Retrieval Benchmark Report

Generated from ${rows.length} benchmark row(s).

## Global Summary

| Metric | Value |
| --- | ---: |
| High-stakes query count | ${rows.filter((row) => row.high_stakes).length} |
| Temporal fallback rate (%) | ${round(aggregates.temporal_fallback_rate_pct)} |
| Mean temporal seed discovery (ms) | ${round(aggregates.mean_temporal_seed_discovery_ms)} |
| Mean temporal bridge time (ms) | ${round(aggregates.mean_temporal_bridge_ms)} |
| Mean temporal hydration time (ms) | ${round(aggregates.mean_temporal_hydration_ms)} |

## Mode Summary

| Mode | Mean Latency (ms) | P95 Latency (ms) | Mean Tokens | Mean Results | MRR@10 | NDCG@10 | Success@5 (%) | Recall@10 (%) | Rerank Applied (%) | Rerank Abstained (%) | Rerank Fallback (%) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
${MODE_DEFINITIONS.map(({ key, label }) => {
  const summary = modeSummaries[key];
  return `| ${label} | ${round(summary.mean_latency_ms)} | ${round(summary.p95_latency_ms)} | ${round(summary.mean_token_estimate)} | ${round(summary.mean_result_count)} | ${round(summary.mrr_at_10)} | ${round(summary.ndcg_at_10)} | ${round(summary.success_at_5_pct)} | ${round(summary.recall_at_10_pct)} | ${round(summary.rerank_applied_pct)} | ${round(summary.rerank_abstained_pct)} | ${round(summary.rerank_fallback_pct)} |`;
}).join("\n")}

## Query Rows

| Query ID | Domain | High Stakes | Temporal Fallback | Baseline Hit Rank | Temporal Hit Rank | Baseline+Rerank Hit Rank | Temporal+Rerank Hit Rank |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
${rows
  .map(
    (row) =>
      `| ${row.query_id} | ${row.domain} | ${row.high_stakes ? "yes" : "no"} | ${row.temporal_fallback_used ? "yes" : "no"} | ${row.baseline.hit_rank ?? "-"} | ${row.temporal.hit_rank ?? "-"} | ${row.baseline_rerank.hit_rank ?? "-"} | ${row.temporal_rerank.hit_rank ?? "-"} |`,
  )
  .join("\n")}
`;

const runCli = (): void => {
  const args = process.argv.slice(2);
  if (args.includes("--help") || args.includes("-h")) {
    console.log(usage);
    return;
  }

  const inputPath = getArg(args, "--input") ?? "bench/results/phase-09-raw.jsonl";
  const rows = readJsonl(inputPath);
  if (rows.length === 0) {
    throw new Error("No benchmark rows found.");
  }

  const aggregates = {
    temporal_fallback_rate_pct: pct(
      rows.filter((row) => row.temporal_fallback_used).length,
      rows.length,
    ),
    mean_temporal_seed_discovery_ms: mean(
      rows.map((row) => row.temporal_seed_discovery_ms),
    ),
    mean_temporal_bridge_ms: mean(rows.map((row) => row.temporal_bridge_ms)),
    mean_temporal_hydration_ms: mean(rows.map((row) => row.temporal_hydration_ms)),
  };

  const modeSummaries = Object.fromEntries(
    MODE_DEFINITIONS.map(({ key }) => [key, aggregateMode(rows, key)]),
  ) as Record<ModeKey, Record<string, number>>;

  const resultsDir = path.resolve("bench/results");
  fs.mkdirSync(resultsDir, { recursive: true });
  const reportMarkdownPath = path.join(resultsDir, "phase-09-report.md");
  const reportJsonPath = path.join(resultsDir, "phase-09-report.json");

  fs.writeFileSync(
    reportMarkdownPath,
    buildMarkdown(rows, aggregates, modeSummaries),
    "utf8",
  );
  fs.writeFileSync(
    reportJsonPath,
    JSON.stringify({ aggregates, mode_summaries: modeSummaries, rows }, null, 2),
    "utf8",
  );

  console.log(
    JSON.stringify(
      {
        markdown: reportMarkdownPath,
        json: reportJsonPath,
      },
      null,
      2,
    ),
  );
};

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url))) {
  runCli();
}
