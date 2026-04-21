export type TemporalNodeRow = {
  nodeId: bigint;
  projectId: string;
  kind: string;
  name: string;
  nameNorm: string;
  createdAtUs: bigint;
  updatedAtUs: bigint;
};

export type TemporalEdgeRow = {
  edgeId: bigint;
  familyId: bigint;
  projectId: string;
  subjId: bigint;
  pred: string;
  objId: bigint;
  validFromUs: bigint;
  validToUs: bigint | null;
  createdAtUs: bigint;
  updatedAtUs: bigint;
  confidence: number;
  supportCount: number;
  contradictionCount: number;
  relevance: number;
  lastReinforcedAtUs: bigint;
};

export type TemporalEvidenceRow = {
  evidenceId: bigint;
  projectId: string;
  sourceKind: string;
  sourceId: string;
  sourceUri: string | null;
  capturedAtUs: bigint;
  rawExcerpt: string | null;
  hash: string;
};

export type TemporalEdgeEvidenceRow = {
  linkId: bigint;
  edgeId: bigint;
  evidenceId: bigint;
  linkedAtUs: bigint;
};

export type TemporalArchiveRow = {
  archiveId: bigint;
  projectId: string;
  edgeId: bigint;
  archivedAtUs: bigint;
  reason: string;
  snapshotJson: string;
};

export type SyncConfig = {
  stdbUri: string;
  stdbModuleName: string;
  stdbBindingsModule: string;
  stdbToken?: string;
  stdbConfirmedReads: boolean;
  neo4jUri: string;
  neo4jUser: string;
  neo4jPassword: string;
  checkpointPath: string;
};

export type SyncCheckpointState = {
  rows: Record<string, string>;
};
