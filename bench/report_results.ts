import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

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
  tsx bench/report_results.ts --input bench/results/phase-09-raw.jsonl

Writes:
  bench/results/phase-09-report.md
  bench/results/phase-09-report.json
`;

const getArg = (args: string[], name: string): string | undefined => {
  const index = args.indexOf(name);
  return index === -1 ? undefined : args[index + 1];
};

const readJsonl = (filePath: string): BenchmarkRow[] =>
  fs
    .readFileSync(path.resolve(filePath), "utf8")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => JSON.parse(line) as BenchmarkRow);

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

const buildMarkdown = (rows: BenchmarkRow[], aggregates: Record<string, number>): string => `# Phase 9 Benchmark Report

Generated from ${rows.length} benchmark row(s).

## Summary

| Metric | Value |
| --- | ---: |
| Mean baseline latency (ms) | ${round(aggregates.mean_baseline_latency_ms)} |
| P95 baseline latency (ms) | ${round(aggregates.p95_baseline_latency_ms)} |
| Mean temporal latency (ms) | ${round(aggregates.mean_temporal_latency_ms)} |
| P95 temporal latency (ms) | ${round(aggregates.p95_temporal_latency_ms)} |
| Average token reduction (%) | ${round(aggregates.avg_token_reduction_pct)} |
| Fallback rate (%) | ${round(aggregates.fallback_rate_pct)} |
| Temporal consistency rate (%) | ${round(aggregates.temporal_consistency_rate_pct)} |

## Query Rows

| Query ID | Domain | Baseline ms | Temporal ms | Token Reduction % | Fallback | Consistent |
| --- | --- | ---: | ---: | ---: | --- | --- |
${rows
  .map(
    (row) =>
      `| ${row.query_id} | ${row.domain} | ${round(row.baseline_latency_ms)} | ${round(row.temporal_latency_ms)} | ${round(row.token_reduction_pct)} | ${row.fallback_used ? "yes" : "no"} | ${row.temporal_consistent ? "yes" : "no"} |`,
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
    mean_baseline_latency_ms: mean(rows.map((row) => row.baseline_latency_ms)),
    p95_baseline_latency_ms: p95(rows.map((row) => row.baseline_latency_ms)),
    mean_temporal_latency_ms: mean(rows.map((row) => row.temporal_latency_ms)),
    p95_temporal_latency_ms: p95(rows.map((row) => row.temporal_latency_ms)),
    avg_token_reduction_pct: mean(rows.map((row) => row.token_reduction_pct)),
    fallback_rate_pct: pct(rows.filter((row) => row.fallback_used).length, rows.length),
    temporal_consistency_rate_pct: pct(
      rows.filter((row) => row.temporal_consistent).length,
      rows.length,
    ),
  };

  const resultsDir = path.resolve("bench/results");
  fs.mkdirSync(resultsDir, { recursive: true });
  const reportMarkdownPath = path.join(resultsDir, "phase-09-report.md");
  const reportJsonPath = path.join(resultsDir, "phase-09-report.json");

  fs.writeFileSync(reportMarkdownPath, buildMarkdown(rows, aggregates), "utf8");
  fs.writeFileSync(
    reportJsonPath,
    JSON.stringify({ aggregates, rows }, null, 2),
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
