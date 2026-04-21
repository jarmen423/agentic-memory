import { SenderError, t } from "spacetimedb/server";

import { hashU128, normalizeName, normalizePredicate } from "../lib/hash";
import { updateRunningStats } from "../lib/mdl";
import { midpointMicros, overlaps } from "../lib/time";
import { EvidenceInput, TemporalClaimInput, spacetimedb } from "../schema";

const clamp01 = (value: number): number => Math.max(0, Math.min(1, value));

type EdgeIngestOptions = {
  updateStats?: boolean;
  applyContradictions?: boolean;
};

const upsertNodeRow = (
  ctx: any,
  args: { projectId: string; kind: string; name: string; nowUs: bigint },
): bigint => {
  const nameNorm = normalizeName(args.name);
  const nodeId = hashU128(args.projectId, args.kind, nameNorm);
  const existing = ctx.db.node.nodeId.find(nodeId);

  const row = {
    nodeId,
    projectId: args.projectId,
    kind: args.kind,
    name: args.name,
    nameNorm,
    createdAtUs: existing?.createdAtUs ?? args.nowUs,
    updatedAtUs: args.nowUs,
  };

  if (existing) {
    ctx.db.node.nodeId.update(row);
  } else {
    ctx.db.node.insert(row);
  }

  return nodeId;
};

const upsertEvidenceRow = (
  ctx: any,
  args: {
    projectId: string;
    evidence: {
      sourceKind: string;
      sourceId: string;
      sourceUri: string | null;
      capturedAtUs: bigint;
      rawExcerpt: string | null;
      hash: string;
    };
  },
): bigint => {
  const evidenceId = hashU128(
    args.projectId,
    args.evidence.sourceKind,
    args.evidence.sourceId,
    args.evidence.hash,
    args.evidence.capturedAtUs,
  );
  const existing = ctx.db.evidence.evidenceId.find(evidenceId);
  if (!existing) {
    ctx.db.evidence.insert({
      evidenceId,
      projectId: args.projectId,
      sourceKind: args.evidence.sourceKind,
      sourceId: args.evidence.sourceId,
      sourceUri: args.evidence.sourceUri,
      capturedAtUs: args.evidence.capturedAtUs,
      rawExcerpt: args.evidence.rawExcerpt,
      hash: args.evidence.hash,
    });
  }
  return evidenceId;
};

const linkEvidence = (
  ctx: any,
  edgeId: bigint,
  evidenceId: bigint,
  linkedAtUs: bigint,
): void => {
  const linkId = hashU128(edgeId, evidenceId);
  if (!ctx.db.edge_evidence.linkId.find(linkId)) {
    ctx.db.edge_evidence.insert({
      linkId,
      edgeId,
      evidenceId,
      linkedAtUs,
    });
  }
};

const updateEdgeStats = (
  ctx: any,
  args: {
    projectId: string;
    subjId: bigint;
    pred: string;
    objId: bigint;
    validFromUs: bigint;
    validToUs: bigint | null;
  },
): void => {
  const statsId = hashU128(args.projectId, args.subjId, args.pred, args.objId);
  const observationUs = midpointMicros(args.validFromUs, args.validToUs ?? undefined);
  const existing = ctx.db.edge_stats.statsId.find(statsId);
  const next = updateRunningStats(
    existing
      ? {
          n: Number(existing.n),
          meanTUs: existing.meanTUs,
          m2TUs: existing.m2TUs,
          segmentCount: Number(existing.segmentCount),
          lastSegmentStartUs: existing.lastSegmentStartUs,
          latestObservationUs: existing.latestObservationUs,
        }
      : null,
    observationUs,
  );

  const row = {
    statsId,
    projectId: args.projectId,
    subjId: args.subjId,
    pred: args.pred,
    objId: args.objId,
    n: next.n,
    meanTUs: next.meanTUs,
    m2TUs: next.m2TUs,
    segmentCount: next.segmentCount,
    lastSegmentStartUs: next.lastSegmentStartUs,
    latestObservationUs: next.latestObservationUs,
  };

  if (existing) {
    ctx.db.edge_stats.statsId.update(row);
  } else {
    ctx.db.edge_stats.insert(row);
  }
};

const applyContradictions = (
  ctx: any,
  edgeId: bigint,
  nowUs: bigint,
): void => {
  const inserted = ctx.db.edge.edgeId.find(edgeId);
  if (!inserted) {
    return;
  }

  for (const candidate of ctx.db.edge.iter()) {
    if (
      candidate.edgeId === inserted.edgeId ||
      candidate.projectId !== inserted.projectId ||
      candidate.subjId !== inserted.subjId ||
      candidate.pred !== inserted.pred ||
      candidate.objId === inserted.objId
    ) {
      continue;
    }

    if (
      !overlaps(
        inserted.validFromUs,
        inserted.validToUs ?? undefined,
        candidate.validFromUs,
        candidate.validToUs ?? undefined,
      )
    ) {
      continue;
    }

    ctx.db.edge.edgeId.update({
      ...candidate,
      contradictionCount: Number(candidate.contradictionCount) + 1,
      relevance: clamp01(candidate.relevance * 0.9),
      updatedAtUs: nowUs,
    });
    ctx.db.edge.edgeId.update({
      ...inserted,
      contradictionCount: Number(inserted.contradictionCount) + 1,
      relevance: clamp01(inserted.relevance * 0.9),
      updatedAtUs: nowUs,
    });
  }
};

const ingestTemporalEdgeRow = (
  ctx: any,
  args: {
    projectId: string;
    subjId: bigint;
    pred: string;
    objId: bigint;
    validFromUs: bigint;
    validToUs: bigint | null;
    confidence: number;
    evidence: {
      sourceKind: string;
      sourceId: string;
      sourceUri: string | null;
      capturedAtUs: bigint;
      rawExcerpt: string | null;
      hash: string;
    };
    nowUs: bigint;
  },
  options: EdgeIngestOptions = {},
): void => {
  // Normal application reducers still compute derived metadata inline. The
  // backfill-only reducers below pass explicit false flags so bulk historical
  // replay can preserve raw facts/evidence without paying the O(graph-size)
  // contradiction scan or per-edge stats maintenance cost on every insert.
  const shouldUpdateStats = options.updateStats ?? true;
  const shouldApplyContradictions = options.applyContradictions ?? true;
  const pred = normalizePredicate(args.pred);
  const subject = ctx.db.node.nodeId.find(args.subjId);
  const object = ctx.db.node.nodeId.find(args.objId);

  if (!subject || !object) {
    throw new SenderError("subject and object nodes must exist before edge ingest");
  }

  const edgeId = hashU128(
    args.projectId,
    args.subjId,
    pred,
    args.objId,
    args.validFromUs,
    args.validToUs ?? "open",
  );
  const familyId = hashU128(args.projectId, args.subjId, pred, args.objId);
  const existing = ctx.db.edge.edgeId.find(edgeId);

  const nextEdge = {
    edgeId,
    familyId,
    projectId: args.projectId,
    subjId: args.subjId,
    pred,
    objId: args.objId,
    validFromUs: args.validFromUs,
    validToUs: args.validToUs,
    createdAtUs: existing?.createdAtUs ?? args.nowUs,
    updatedAtUs: args.nowUs,
    confidence: clamp01(Math.max(existing?.confidence ?? 0, args.confidence)),
    supportCount: Number(existing?.supportCount ?? 0) + 1,
    contradictionCount: Number(existing?.contradictionCount ?? 0),
    relevance: clamp01(Math.max(existing?.relevance ?? 0, args.confidence)),
    lastReinforcedAtUs: args.nowUs,
  };

  if (existing) {
    ctx.db.edge.edgeId.update(nextEdge);
  } else {
    ctx.db.edge.insert(nextEdge);
  }

  const evidenceId = upsertEvidenceRow(ctx, {
    projectId: args.projectId,
    evidence: args.evidence,
  });
  linkEvidence(ctx, edgeId, evidenceId, args.nowUs);
  if (shouldUpdateStats) {
    updateEdgeStats(ctx, {
      projectId: args.projectId,
      subjId: args.subjId,
      pred,
      objId: args.objId,
      validFromUs: args.validFromUs,
      validToUs: args.validToUs,
    });
  }
  if (shouldApplyContradictions) {
    applyContradictions(ctx, edgeId, args.nowUs);
  }
};

export const upsert_node = spacetimedb.reducer(
  { name: "upsert_node" },
  {
    projectId: t.string(),
    kind: t.string(),
    name: t.string(),
    nowUs: t.i64(),
  },
  (ctx: any, args: any) => {
    if (!args.projectId.trim()) {
      throw new SenderError("projectId is required");
    }
    if (!args.kind.trim()) {
      throw new SenderError("kind is required");
    }
    if (!args.name.trim()) {
      throw new SenderError("name is required");
    }

    upsertNodeRow(ctx, args);
  },
);

export const ingest_temporal_edge = spacetimedb.reducer(
  { name: "ingest_temporal_edge" },
  {
    projectId: t.string(),
    subjId: t.u128(),
    pred: t.string(),
    objId: t.u128(),
    validFromUs: t.i64(),
    validToUs: t.option(t.i64()),
    confidence: t.f32(),
    evidence: EvidenceInput,
    nowUs: t.i64(),
  },
  (ctx: any, args: any) => {
    ingestTemporalEdgeRow(ctx, {
      projectId: args.projectId,
      subjId: args.subjId,
      pred: args.pred,
      objId: args.objId,
      validFromUs: args.validFromUs,
      validToUs: args.validToUs,
      confidence: args.confidence,
      evidence: {
        sourceKind: args.evidence.sourceKind,
        sourceId: args.evidence.sourceId,
        sourceUri: args.evidence.sourceUri,
        capturedAtUs: args.evidence.capturedAtUs,
        rawExcerpt: args.evidence.rawExcerpt,
        hash: args.evidence.hash,
      },
      nowUs: args.nowUs,
    });
  },
);

export const ingest_temporal_claim = spacetimedb.reducer(
  { name: "ingest_temporal_claim" },
  {
    projectId: t.string(),
    subjectKind: t.string(),
    subjectName: t.string(),
    predicate: t.string(),
    objectKind: t.string(),
    objectName: t.string(),
    validFromUs: t.i64(),
    validToUs: t.option(t.i64()),
    confidence: t.f32(),
    evidence: EvidenceInput,
    nowUs: t.i64(),
  },
  (ctx: any, args: any) => {
    const subjId = upsertNodeRow(ctx, {
      projectId: args.projectId,
      kind: args.subjectKind,
      name: args.subjectName,
      nowUs: args.nowUs,
    });
    const objId = upsertNodeRow(ctx, {
      projectId: args.projectId,
      kind: args.objectKind,
      name: args.objectName,
      nowUs: args.nowUs,
    });

    ingestTemporalEdgeRow(ctx, {
      projectId: args.projectId,
      subjId,
      pred: args.predicate,
      objId,
      validFromUs: args.validFromUs,
      validToUs: args.validToUs,
      confidence: args.confidence,
      evidence: {
        sourceKind: args.evidence.sourceKind,
        sourceId: args.evidence.sourceId,
        sourceUri: args.evidence.sourceUri,
        capturedAtUs: args.evidence.capturedAtUs,
        rawExcerpt: args.evidence.rawExcerpt,
        hash: args.evidence.hash,
      },
      nowUs: args.nowUs,
    });
  },
);

export const ingest_temporal_claims = spacetimedb.reducer(
  { name: "ingest_temporal_claims" },
  {
    claims: t.array(TemporalClaimInput),
  },
  (ctx: any, args: any) => {
    for (const claim of args.claims) {
      const subjId = upsertNodeRow(ctx, {
        projectId: claim.projectId,
        kind: claim.subjectKind,
        name: claim.subjectName,
        nowUs: claim.nowUs,
      });
      const objId = upsertNodeRow(ctx, {
        projectId: claim.projectId,
        kind: claim.objectKind,
        name: claim.objectName,
        nowUs: claim.nowUs,
      });

      ingestTemporalEdgeRow(ctx, {
        projectId: claim.projectId,
        subjId,
        pred: claim.predicate,
        objId,
        validFromUs: claim.validFromUs,
        validToUs: claim.validToUs,
        confidence: claim.confidence,
        evidence: {
          sourceKind: claim.evidence.sourceKind,
          sourceId: claim.evidence.sourceId,
          sourceUri: claim.evidence.sourceUri,
          capturedAtUs: claim.evidence.capturedAtUs,
          rawExcerpt: claim.evidence.rawExcerpt,
          hash: claim.evidence.hash,
        },
        nowUs: claim.nowUs,
      });
    }
  },
);

export const ingest_temporal_claim_backfill = spacetimedb.reducer(
  { name: "ingest_temporal_claim_backfill" },
  {
    projectId: t.string(),
    subjectKind: t.string(),
    subjectName: t.string(),
    predicate: t.string(),
    objectKind: t.string(),
    objectName: t.string(),
    validFromUs: t.i64(),
    validToUs: t.option(t.i64()),
    confidence: t.f32(),
    evidence: EvidenceInput,
    nowUs: t.i64(),
  },
  (ctx: any, args: any) => {
    // This reducer exists only for bulk historical backfills. It intentionally
    // keeps raw nodes/edges/evidence identical to the normal path while
    // skipping optional derived summaries that can be rebuilt later.
    const subjId = upsertNodeRow(ctx, {
      projectId: args.projectId,
      kind: args.subjectKind,
      name: args.subjectName,
      nowUs: args.nowUs,
    });
    const objId = upsertNodeRow(ctx, {
      projectId: args.projectId,
      kind: args.objectKind,
      name: args.objectName,
      nowUs: args.nowUs,
    });

    ingestTemporalEdgeRow(
      ctx,
      {
        projectId: args.projectId,
        subjId,
        pred: args.predicate,
        objId,
        validFromUs: args.validFromUs,
        validToUs: args.validToUs,
        confidence: args.confidence,
        evidence: {
          sourceKind: args.evidence.sourceKind,
          sourceId: args.evidence.sourceId,
          sourceUri: args.evidence.sourceUri,
          capturedAtUs: args.evidence.capturedAtUs,
          rawExcerpt: args.evidence.rawExcerpt,
          hash: args.evidence.hash,
        },
        nowUs: args.nowUs,
      },
      {
        updateStats: false,
        applyContradictions: false,
      },
    );
  },
);

export const ingest_temporal_claims_backfill = spacetimedb.reducer(
  { name: "ingest_temporal_claims_backfill" },
  {
    claims: t.array(TemporalClaimInput),
  },
  (ctx: any, args: any) => {
    // Batched variant of the backfill reducer above. Keeping this reducer-side
    // avoids paying one Python->Node->SpacetimeDB round-trip per claim.
    for (const claim of args.claims) {
      const subjId = upsertNodeRow(ctx, {
        projectId: claim.projectId,
        kind: claim.subjectKind,
        name: claim.subjectName,
        nowUs: claim.nowUs,
      });
      const objId = upsertNodeRow(ctx, {
        projectId: claim.projectId,
        kind: claim.objectKind,
        name: claim.objectName,
        nowUs: claim.nowUs,
      });

      ingestTemporalEdgeRow(
        ctx,
        {
          projectId: claim.projectId,
          subjId,
          pred: claim.predicate,
          objId,
          validFromUs: claim.validFromUs,
          validToUs: claim.validToUs,
          confidence: claim.confidence,
          evidence: {
            sourceKind: claim.evidence.sourceKind,
            sourceId: claim.evidence.sourceId,
            sourceUri: claim.evidence.sourceUri,
            capturedAtUs: claim.evidence.capturedAtUs,
            rawExcerpt: claim.evidence.rawExcerpt,
            hash: claim.evidence.hash,
          },
          nowUs: claim.nowUs,
        },
        {
          updateStats: false,
          applyContradictions: false,
        },
      );
    }
  },
);
