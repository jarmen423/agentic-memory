import { ScheduleAt } from "spacetimedb";
import { schema, table, t } from "spacetimedb/server";

export const EvidenceInput = t.object("EvidenceInput", {
  sourceKind: t.string(),
  sourceId: t.string(),
  sourceUri: t.option(t.string()),
  capturedAtUs: t.i64(),
  rawExcerpt: t.option(t.string()),
  hash: t.string(),
});

export const RetrievalResult = t.object("RetrievalResult", {
  edgeId: t.u128(),
  subjId: t.u128(),
  pred: t.string(),
  objId: t.u128(),
  validFromUs: t.i64(),
  validToUs: t.option(t.i64()),
  relevance: t.f32(),
  confidence: t.f32(),
  supportCount: t.u32(),
  contradictionCount: t.u32(),
  evidenceIds: t.array(t.u128()),
});

export const ModuleHealthRow = t.object("ModuleHealthRow", {
  generatedAtUs: t.i64(),
  nodeCount: t.u64(),
  edgeCount: t.u64(),
  evidenceCount: t.u64(),
  archiveCount: t.u64(),
  maintenanceJobCount: t.u64(),
});

export const Node = table(
  {
    name: "node",
    public: true,
    indexes: [
      {
        accessor: "project_kind_idx",
        algorithm: "btree",
        columns: ["projectId", "kind"] as const,
      },
      {
        accessor: "project_name_norm_idx",
        algorithm: "btree",
        columns: ["projectId", "nameNorm"] as const,
      },
    ],
  },
  {
    nodeId: t.u128().primaryKey(),
    projectId: t.string(),
    kind: t.string(),
    name: t.string(),
    nameNorm: t.string(),
    createdAtUs: t.i64(),
    updatedAtUs: t.i64(),
  },
);

export const Evidence = table(
  {
    name: "evidence",
    public: true,
    indexes: [
      {
        accessor: "project_source_kind_idx",
        algorithm: "btree",
        columns: ["projectId", "sourceKind"] as const,
      },
      {
        accessor: "project_source_id_idx",
        algorithm: "btree",
        columns: ["projectId", "sourceId"] as const,
      },
    ],
  },
  {
    evidenceId: t.u128().primaryKey(),
    projectId: t.string(),
    sourceKind: t.string(),
    sourceId: t.string(),
    sourceUri: t.option(t.string()),
    capturedAtUs: t.i64(),
    rawExcerpt: t.option(t.string()),
    hash: t.string(),
  },
);

export const Edge = table(
  {
    name: "edge",
    public: true,
    indexes: [
      {
        accessor: "project_subj_pred_idx",
        algorithm: "btree",
        columns: ["projectId", "subjId", "pred"] as const,
      },
      {
        accessor: "project_obj_pred_idx",
        algorithm: "btree",
        columns: ["projectId", "objId", "pred"] as const,
      },
      {
        accessor: "project_valid_from_idx",
        algorithm: "btree",
        columns: ["projectId", "validFromUs"] as const,
      },
      {
        accessor: "project_valid_to_idx",
        algorithm: "btree",
        columns: ["projectId", "validToUs"] as const,
      },
    ],
  },
  {
    edgeId: t.u128().primaryKey(),
    familyId: t.u128(),
    projectId: t.string(),
    subjId: t.u128(),
    pred: t.string(),
    objId: t.u128(),
    validFromUs: t.i64(),
    validToUs: t.option(t.i64()),
    createdAtUs: t.i64(),
    updatedAtUs: t.i64(),
    confidence: t.f32(),
    supportCount: t.u32(),
    contradictionCount: t.u32(),
    relevance: t.f32(),
    lastReinforcedAtUs: t.i64(),
  },
);

export const EdgeEvidence = table(
  {
    name: "edge_evidence",
    public: true,
    indexes: [
      { accessor: "edge_id_idx", algorithm: "btree", columns: ["edgeId"] as const },
      {
        accessor: "evidence_id_idx",
        algorithm: "btree",
        columns: ["evidenceId"] as const,
      },
    ],
  },
  {
    linkId: t.u128().primaryKey(),
    edgeId: t.u128(),
    evidenceId: t.u128(),
    linkedAtUs: t.i64(),
  },
);

export const EdgeStats = table(
  {
    name: "edge_stats",
    indexes: [
      {
        accessor: "project_subj_pred_idx",
        algorithm: "btree",
        columns: ["projectId", "subjId", "pred"] as const,
      },
    ],
  },
  {
    statsId: t.u128().primaryKey(),
    projectId: t.string(),
    subjId: t.u128(),
    pred: t.string(),
    objId: t.u128(),
    n: t.u32(),
    meanTUs: t.f64(),
    m2TUs: t.f64(),
    segmentCount: t.u32(),
    lastSegmentStartUs: t.i64(),
    latestObservationUs: t.i64(),
  },
);

export const EdgeArchive = table(
  {
    name: "edge_archive",
    public: true,
    indexes: [
      {
        accessor: "project_archived_at_idx",
        algorithm: "btree",
        columns: ["projectId", "archivedAtUs"] as const,
      },
    ],
  },
  {
    archiveId: t.u128().primaryKey(),
    projectId: t.string(),
    edgeId: t.u128(),
    archivedAtUs: t.i64(),
    reason: t.string(),
    snapshotJson: t.string(),
  },
);

export const MaintenanceJob = table(
  {
    name: "maintenance_job",
  },
  {
    scheduledId: t.u64().primaryKey().autoInc(),
    scheduledAt: t.scheduleAt(),
    projectId: t.option(t.string()),
    jobKind: t.string(),
    intervalMicros: t.i64(),
    metadataJson: t.option(t.string()),
  },
);

export const spacetimedb = schema({
  node: Node,
  evidence: Evidence,
  edge: Edge,
  edge_evidence: EdgeEvidence,
  edge_stats: EdgeStats,
  edge_archive: EdgeArchive,
  maintenance_job: MaintenanceJob,
});

export const DEFAULT_MAINTENANCE_INTERVAL_US = 86_400_000_000n;

export const scheduleEveryDay = (): ScheduleAt =>
  ScheduleAt.interval(DEFAULT_MAINTENANCE_INTERVAL_US);

export default spacetimedb;
