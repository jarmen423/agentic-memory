import { ScheduleAt } from "spacetimedb";
import { SenderError, t } from "spacetimedb/server";

import { hashU128 } from "../lib/hash";
import { computeMdlLiteScore, decayRelevance, variance } from "../lib/mdl";
import { DEFAULT_MAINTENANCE_INTERVAL_US, MaintenanceJob, spacetimedb } from "../schema";

const JOB_KINDS = ["nightly_decay", "archive_expired", "mdl_prune"] as const;
const stringifyWithBigInt = (value: unknown): string =>
  JSON.stringify(value, (_key, innerValue) =>
    typeof innerValue === "bigint" ? innerValue.toString() : innerValue,
  );

const ensureOwner = (ctx: any): void => {
  const owner = ctx.db.owner?.id?.find?.(ctx.sender);
  if (!owner) {
    throw new SenderError("maintenance reducers are owner-only");
  }
};

const projectMatches = (rowProjectId: string, filterProjectId: string | null | undefined): boolean =>
  !filterProjectId || rowProjectId === filterProjectId;

const archiveEdge = (ctx: any, edge: any, reason: string, nowUs: bigint): void => {
  const archiveId = hashU128(edge.edgeId, nowUs, reason);
  if (!ctx.db.edge_archive.archiveId.find(archiveId)) {
    ctx.db.edge_archive.insert({
      archiveId,
      projectId: edge.projectId,
      edgeId: edge.edgeId,
      archivedAtUs: nowUs,
      reason,
      snapshotJson: stringifyWithBigInt(edge),
    });
  }
  ctx.db.edge.edgeId.delete(edge.edgeId);
};

const runNightlyDecay = (ctx: any, projectId: string | null | undefined, nowUs: bigint): void => {
  for (const edge of ctx.db.edge.iter()) {
    if (!projectMatches(edge.projectId, projectId)) {
      continue;
    }
    const nextRelevance = decayRelevance(edge.relevance, edge.lastReinforcedAtUs, nowUs);
    if (Math.abs(nextRelevance - edge.relevance) < 1e-6) {
      continue;
    }
    ctx.db.edge.edgeId.update({
      ...edge,
      relevance: nextRelevance,
      updatedAtUs: nowUs,
    });
  }
};

const runArchiveExpired = (ctx: any, projectId: string | null | undefined, nowUs: bigint): void => {
  for (const edge of ctx.db.edge.iter()) {
    if (!projectMatches(edge.projectId, projectId)) {
      continue;
    }
    if (edge.validToUs === null || edge.validToUs === undefined || edge.validToUs >= nowUs) {
      continue;
    }
    archiveEdge(ctx, edge, "expired_interval", nowUs);
  }
};

const runMdlPrune = (ctx: any, projectId: string | null | undefined, nowUs: bigint): void => {
  for (const stats of ctx.db.edge_stats.iter()) {
    if (!projectMatches(stats.projectId, projectId)) {
      continue;
    }

    const n = Number(stats.n);
    if (n < 3) {
      continue;
    }

    const mdlScore = computeMdlLiteScore({ n, m2TUs: stats.m2TUs });
    const familyVariance = variance({ n, m2TUs: stats.m2TUs });
    if (familyVariance < 3_600_000_000_000 || mdlScore < 8) {
      continue;
    }

    const familyEdges = (Array.from(ctx.db.edge.iter()) as any[]).filter(
      (edge: any) =>
        edge.projectId === stats.projectId &&
        edge.subjId === stats.subjId &&
        edge.pred === stats.pred,
    );
    if (familyEdges.length < 2) {
      continue;
    }

    familyEdges.sort((a: any, b: any) => {
      const scoreA = a.supportCount * a.confidence * a.relevance;
      const scoreB = b.supportCount * b.confidence * b.relevance;
      return scoreB - scoreA;
    });

    const dominant = familyEdges[0];
    for (const edge of familyEdges.slice(1)) {
      const degraded = Math.max(0, edge.relevance * 0.5);
      const updated = {
        ...edge,
        relevance: degraded,
        updatedAtUs: nowUs,
      };

      if (edge.edgeId !== dominant.edgeId && (degraded < 0.1 || edge.contradictionCount > 0)) {
        archiveEdge(ctx, updated, "mdl_prune", nowUs);
      } else {
        ctx.db.edge.edgeId.update(updated);
      }
    }
  }
};

const dispatchMaintenance = (
  ctx: any,
  jobKind: string,
  projectId: string | null | undefined,
  nowUs: bigint,
): void => {
  switch (jobKind) {
    case "nightly_decay":
      runNightlyDecay(ctx, projectId, nowUs);
      return;
    case "archive_expired":
      runArchiveExpired(ctx, projectId, nowUs);
      return;
    case "mdl_prune":
      runMdlPrune(ctx, projectId, nowUs);
      return;
    default:
      throw new SenderError(`unknown maintenance job: ${jobKind}`);
  }
};

export const seed_maintenance_jobs = spacetimedb.reducer(
  { name: "seed_maintenance_jobs" },
  {
    projectId: t.option(t.string()),
    intervalMicros: t.option(t.i64()),
    metadataJson: t.option(t.string()),
  },
  (ctx: any, args: any) => {
    ensureOwner(ctx);
    const intervalMicros = args.intervalMicros ?? DEFAULT_MAINTENANCE_INTERVAL_US;
    for (const jobKind of JOB_KINDS) {
      const exists = Array.from(ctx.db.maintenance_job.iter()).some(
        (job: any) =>
          job.jobKind === jobKind &&
          job.projectId === args.projectId &&
          job.intervalMicros === intervalMicros,
      );
      if (exists) {
        continue;
      }

      ctx.db.maintenance_job.insert({
        scheduledId: 0n,
        scheduledAt: ScheduleAt.interval(intervalMicros),
        projectId: args.projectId,
        jobKind,
        intervalMicros,
        metadataJson: args.metadataJson,
      });
    }
  },
);

export const run_maintenance = spacetimedb.reducer(
  { name: "run_maintenance" },
  { arg: MaintenanceJob.rowType },
  (ctx: any, { arg }: any) => {
    ensureOwner(ctx);
    dispatchMaintenance(ctx, arg.jobKind, arg.projectId, ctx.timestamp.microsSinceUnixEpoch);
  },
);

export const run_maintenance_now = spacetimedb.reducer(
  { name: "run_maintenance_now" },
  {
    projectId: t.option(t.string()),
    jobKind: t.string(),
  },
  (ctx: any, args: any) => {
    ensureOwner(ctx);
    dispatchMaintenance(ctx, args.jobKind, args.projectId, ctx.timestamp.microsSinceUnixEpoch);
  },
);
