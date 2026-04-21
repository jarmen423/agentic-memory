import { t } from "spacetimedb/server";

import { halfLifeHoursToMicros, temporalDistanceMicros } from "../lib/time";
import { RetrievalResult, spacetimedb } from "../schema";

type ScoredEdge = {
  edgeId: bigint;
  subjId: bigint;
  pred: string;
  objId: bigint;
  validFromUs: bigint;
  validToUs: bigint | null;
  relevance: number;
  confidence: number;
  supportCount: number;
  contradictionCount: number;
  evidenceIds: bigint[];
  transitionWeight: number;
};

const nodeKey = (value: bigint): string => value.toString();

const clampAlpha = (value: number): number => Math.max(0.05, Math.min(0.95, value));

const txDb = (tx: any): any => tx.db ?? tx;

const collectNeighborhood = (
  tx: any,
  projectId: string,
  seedNodeIds: bigint[],
  maxHops: number,
  maxNodes: number,
): Set<bigint> => {
  const db = txDb(tx);
  const visited = new Set<bigint>(seedNodeIds);
  let frontier = new Set<bigint>(seedNodeIds);

  for (let hop = 0; hop < Math.max(1, maxHops); hop += 1) {
    const next = new Set<bigint>();
    for (const edge of db.edge.iter()) {
      if (edge.projectId !== projectId) {
        continue;
      }
      if (frontier.has(edge.subjId)) {
        next.add(edge.objId);
      }
      if (frontier.has(edge.objId)) {
        next.add(edge.subjId);
      }
      if (visited.size + next.size >= maxNodes) {
        break;
      }
    }

    for (const nodeId of next) {
      visited.add(nodeId);
    }
    frontier = next;
    if (frontier.size === 0 || visited.size >= maxNodes) {
      break;
    }
  }

  return visited;
};

const buildEvidenceMap = (tx: any): Map<string, bigint[]> => {
  const db = txDb(tx);
  const byEdgeId = new Map<string, bigint[]>();
  for (const link of db.edge_evidence.iter()) {
    const key = link.edgeId.toString();
    const existing = byEdgeId.get(key) ?? [];
    existing.push(link.evidenceId);
    byEdgeId.set(key, existing);
  }
  return byEdgeId;
};

const buildAdjacency = (
  tx: any,
  projectId: string,
  nodeIds: Set<bigint>,
  asOfUs: bigint,
  halfLifeHours: number,
  minRelevance: number,
  evidenceByEdgeId: Map<string, bigint[]>,
): Map<string, ScoredEdge[]> => {
  const db = txDb(tx);
  const halfLifeMicros = halfLifeHoursToMicros(halfLifeHours);
  const adjacency = new Map<string, ScoredEdge[]>();

  for (const edge of db.edge.iter()) {
    if (
      edge.projectId !== projectId ||
      !nodeIds.has(edge.subjId) ||
      !nodeIds.has(edge.objId) ||
      edge.relevance < minRelevance
    ) {
      continue;
    }

    const temporalDistance = temporalDistanceMicros(asOfUs, edge.validFromUs, edge.validToUs ?? undefined);
    const temporalWeight = Math.pow(2, -temporalDistance / Math.max(halfLifeMicros, 1));
    const transitionWeight = Math.max(
      1e-9,
      edge.confidence * edge.relevance * temporalWeight / (1 + edge.contradictionCount),
    );

    const scored: ScoredEdge = {
      edgeId: edge.edgeId,
      subjId: edge.subjId,
      pred: edge.pred,
      objId: edge.objId,
      validFromUs: edge.validFromUs,
      validToUs: edge.validToUs,
      relevance: edge.relevance,
      confidence: edge.confidence,
      supportCount: Number(edge.supportCount),
      contradictionCount: Number(edge.contradictionCount),
      evidenceIds: evidenceByEdgeId.get(edge.edgeId.toString()) ?? [],
      transitionWeight,
    };

    const key = nodeKey(edge.subjId);
    const bucket = adjacency.get(key) ?? [];
    bucket.push(scored);
    adjacency.set(key, bucket);
  }

  return adjacency;
};

const runPersonalizedPageRank = (
  nodeIds: Set<bigint>,
  seedNodeIds: bigint[],
  adjacency: Map<string, ScoredEdge[]>,
  alpha: number,
): Map<string, number> => {
  const seeds = seedNodeIds.length > 0 ? seedNodeIds : Array.from(nodeIds);
  const seedWeight = 1 / Math.max(seeds.length, 1);
  const ranks = new Map<string, number>();
  const personalization = new Map<string, number>();

  for (const nodeId of nodeIds) {
    const key = nodeKey(nodeId);
    const base = seeds.some((seed) => seed === nodeId) ? seedWeight : 0;
    ranks.set(key, base);
    personalization.set(key, base);
  }

  for (let iteration = 0; iteration < 12; iteration += 1) {
    const next = new Map<string, number>();
    for (const nodeId of nodeIds) {
      const key = nodeKey(nodeId);
      next.set(key, (1 - alpha) * (personalization.get(key) ?? 0));
    }

    for (const [sourceKey, edges] of adjacency.entries()) {
      const sourceRank = ranks.get(sourceKey) ?? 0;
      if (sourceRank === 0 || edges.length === 0) {
        continue;
      }
      const totalWeight = edges.reduce((sum, edge) => sum + edge.transitionWeight, 0);
      if (totalWeight === 0) {
        continue;
      }
      for (const edge of edges) {
        const contribution = alpha * sourceRank * (edge.transitionWeight / totalWeight);
        const targetKey = nodeKey(edge.objId);
        next.set(targetKey, (next.get(targetKey) ?? 0) + contribution);
      }
    }

    let delta = 0;
    for (const nodeId of nodeIds) {
      const key = nodeKey(nodeId);
      delta += Math.abs((next.get(key) ?? 0) - (ranks.get(key) ?? 0));
    }
    ranks.clear();
    for (const [key, value] of next.entries()) {
      ranks.set(key, value);
    }
    if (delta < 1e-6) {
      break;
    }
  }

  return ranks;
};

export const temporal_ppr_retrieve = spacetimedb.procedure(
  { name: "temporal_ppr_retrieve" },
  {
    projectId: t.string(),
    seedNodeIds: t.array(t.u128()),
    asOfUs: t.i64(),
    maxEdges: t.u32(),
    maxHops: t.u32(),
    alpha: t.f32(),
    halfLifeHours: t.f32(),
    minRelevance: t.f32(),
  },
  t.array(RetrievalResult),
  (ctx: any, args: any) =>
    ctx.withTx((tx: any) => {
      const maxNodes = Math.max(Number(args.maxEdges) * 6, 32);
      const neighborhood = collectNeighborhood(
        tx,
        args.projectId,
        args.seedNodeIds,
        Number(args.maxHops),
        maxNodes,
      );
      const evidenceByEdgeId = buildEvidenceMap(tx);
      const adjacency = buildAdjacency(
        tx,
        args.projectId,
        neighborhood,
        args.asOfUs,
        args.halfLifeHours,
        args.minRelevance,
        evidenceByEdgeId,
      );
      const ranks = runPersonalizedPageRank(
        neighborhood,
        args.seedNodeIds,
        adjacency,
        clampAlpha(args.alpha),
      );

      const rankedEdges: Array<ScoredEdge & { score: number }> = [];
      for (const [sourceKey, edges] of adjacency.entries()) {
        const totalWeight = edges.reduce((sum, edge) => sum + edge.transitionWeight, 0);
        if (totalWeight === 0) {
          continue;
        }
        for (const edge of edges) {
          const connectedRank = Math.max(
            ranks.get(sourceKey) ?? 0,
            ranks.get(nodeKey(edge.objId)) ?? 0,
          );
          rankedEdges.push({
            ...edge,
            score: connectedRank * (edge.transitionWeight / totalWeight),
          });
        }
      }

      rankedEdges.sort((a, b) => b.score - a.score);

      return rankedEdges.slice(0, Number(args.maxEdges)).map((edge) => ({
        edgeId: edge.edgeId,
        subjId: edge.subjId,
        pred: edge.pred,
        objId: edge.objId,
        validFromUs: edge.validFromUs,
        validToUs: edge.validToUs,
        relevance: edge.relevance,
        confidence: edge.confidence,
        supportCount: edge.supportCount,
        contradictionCount: edge.contradictionCount,
        evidenceIds: edge.evidenceIds,
      }));
    }),
);
