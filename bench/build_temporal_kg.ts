import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { createHelperFromEnv } from "../packages/am-temporal-kg/scripts/query_temporal.ts";

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

type TraceRecord =
  | ConversationRelationRecord
  | ResearchClaimRecord
  | ResearchRelationRecord
  | Record<string, unknown>;

const usage = `Usage:
  tsx bench/build_temporal_kg.ts --input bench/fixtures/smoke-traces.jsonl

Accepted trace rows:
  - conversation_relation
  - research_claim
  - research_relation

Rows of type "query" are ignored by this script.
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

const toMicros = (isoString: string): number => {
  const parsed = Date.parse(isoString);
  if (Number.isNaN(parsed)) {
    throw new Error(`Invalid ISO timestamp: ${isoString}`);
  }
  return parsed * 1000;
};

const runCli = async (): Promise<void> => {
  const args = process.argv.slice(2);
  if (args.includes("--help") || args.includes("-h")) {
    console.log(usage);
    return;
  }

  const inputPath = getArg(args, "--input") ?? "bench/fixtures/smoke-traces.jsonl";
  const helper = createHelperFromEnv();
  const rows = readJsonl(inputPath);

  let nodesWritten = 0;
  let edgesWritten = 0;
  let evidenceWritten = 0;

  for (const row of rows) {
    if (row.type === "conversation_relation") {
      const sourceId = `${row.session_id}:${row.turn_index}`;
      await helper.ingestRelation({
        op: "ingest_relation",
        projectId: row.project_id,
        subjectKind: "conversation_turn",
        subjectName: sourceId,
        predicate: row.predicate ?? "MENTIONS",
        objectKind: row.entity_type,
        objectName: row.entity_name,
        validFromUs: toMicros(row.captured_at),
        evidence: {
          sourceKind: "conversation_turn",
          sourceId,
          capturedAtUs: toMicros(row.captured_at),
          rawExcerpt: row.content,
        },
      });
      nodesWritten += 2;
      edgesWritten += 1;
      evidenceWritten += 1;
      continue;
    }

    if (row.type === "research_claim") {
      await helper.ingestClaim({
        op: "ingest_claim",
        projectId: row.project_id,
        subjectKind: row.subject_kind ?? "unknown",
        subjectName: row.subject,
        predicate: row.predicate,
        objectKind: row.object_kind ?? "unknown",
        objectName: row.object,
        validFromUs: toMicros(row.captured_at),
        evidence: {
          sourceKind: row.source_kind ?? "research_finding",
          sourceId: `${row.source_key}:${row.content_hash}`,
          capturedAtUs: toMicros(row.captured_at),
          rawExcerpt: row.content,
        },
      });
      nodesWritten += 2;
      edgesWritten += 1;
      evidenceWritten += 1;
      continue;
    }

    if (row.type === "research_relation") {
      const sourceId = `${row.source_key}:${row.content_hash}`;
      await helper.ingestRelation({
        op: "ingest_relation",
        projectId: row.project_id,
        subjectKind: row.source_kind,
        subjectName: sourceId,
        predicate: row.predicate ?? "MENTIONS",
        objectKind: row.entity_type,
        objectName: row.entity_name,
        validFromUs: toMicros(row.captured_at),
        evidence: {
          sourceKind: row.source_kind,
          sourceId,
          capturedAtUs: toMicros(row.captured_at),
          rawExcerpt: row.content,
        },
      });
      nodesWritten += 2;
      edgesWritten += 1;
      evidenceWritten += 1;
    }
  }

  await helper.close();

  console.log(
    JSON.stringify(
      {
        input: path.resolve(inputPath),
        nodes_written: nodesWritten,
        edges_written: edgesWritten,
        evidence_written: evidenceWritten,
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
