import crypto from "node:crypto";

import neo4j from "neo4j-driver";

import type {
  TemporalArchiveRow,
  TemporalEdgeEvidenceRow,
  TemporalEdgeRow,
  TemporalEvidenceRow,
  TemporalNodeRow,
} from "./types";

export const serializeWithBigInt = (value: unknown): string =>
  JSON.stringify(value, (_key, innerValue) =>
    typeof innerValue === "bigint" ? innerValue.toString() : innerValue,
  );

export const rowSignature = (value: unknown): string =>
  crypto.createHash("sha256").update(serializeWithBigInt(value)).digest("hex");

export const primaryKeyForRow = (row: Record<string, unknown>): string => {
  const candidate =
    row.nodeId ??
    row.edgeId ??
    row.evidenceId ??
    row.linkId ??
    row.archiveId;
  return String(candidate ?? crypto.createHash("sha1").update(serializeWithBigInt(row)).digest("hex"));
};

const neoInt = (value: bigint | number | null | undefined) =>
  value === null || value === undefined ? null : neo4j.int(value.toString());

const isoFromMicros = (value: bigint | null | undefined): string | null => {
  if (value === null || value === undefined) {
    return null;
  }
  return new Date(Number(value / 1000n)).toISOString();
};

export const sanitizeRelationType = (predicate: string): string => {
  const normalized = predicate
    .trim()
    .toUpperCase()
    .replace(/[\s-]+/g, "_")
    .replace(/[^A-Z0-9_]/g, "");
  return normalized.length > 0 ? normalized : "REFERENCES";
};

export const nodeParams = (row: TemporalNodeRow) => ({
  node_id: row.nodeId.toString(),
  project_id: row.projectId,
  kind: row.kind,
  name: row.name,
  name_norm: row.nameNorm,
  created_at_us: neoInt(row.createdAtUs),
  updated_at_us: neoInt(row.updatedAtUs),
  created_at_iso: isoFromMicros(row.createdAtUs),
  updated_at_iso: isoFromMicros(row.updatedAtUs),
});

export const edgeParams = (row: TemporalEdgeRow) => ({
  edge_id: row.edgeId.toString(),
  family_id: row.familyId.toString(),
  project_id: row.projectId,
  subj_id: row.subjId.toString(),
  obj_id: row.objId.toString(),
  pred: row.pred,
  valid_from_us: neoInt(row.validFromUs),
  valid_to_us: neoInt(row.validToUs),
  created_at_us: neoInt(row.createdAtUs),
  updated_at_us: neoInt(row.updatedAtUs),
  last_reinforced_at_us: neoInt(row.lastReinforcedAtUs),
  valid_from_iso: isoFromMicros(row.validFromUs),
  valid_to_iso: isoFromMicros(row.validToUs),
  confidence: row.confidence,
  support_count: neoInt(row.supportCount),
  contradiction_count: neoInt(row.contradictionCount),
  relevance: row.relevance,
});

export const evidenceParams = (row: TemporalEvidenceRow) => ({
  evidence_id: row.evidenceId.toString(),
  project_id: row.projectId,
  source_kind: row.sourceKind,
  source_id: row.sourceId,
  source_uri: row.sourceUri ?? null,
  captured_at_us: neoInt(row.capturedAtUs),
  captured_at_iso: isoFromMicros(row.capturedAtUs),
  raw_excerpt: row.rawExcerpt ?? null,
  hash: row.hash,
});

export const edgeEvidenceParams = (row: TemporalEdgeEvidenceRow) => ({
  link_id: row.linkId.toString(),
  edge_id: row.edgeId.toString(),
  evidence_id: row.evidenceId.toString(),
  linked_at_us: neoInt(row.linkedAtUs),
  linked_at_iso: isoFromMicros(row.linkedAtUs),
});

export const archiveParams = (row: TemporalArchiveRow) => ({
  archive_id: row.archiveId.toString(),
  edge_id: row.edgeId.toString(),
  project_id: row.projectId,
  archived_at_us: neoInt(row.archivedAtUs),
  archived_at_iso: isoFromMicros(row.archivedAtUs),
  reason: row.reason,
  snapshot_json: row.snapshotJson,
});
