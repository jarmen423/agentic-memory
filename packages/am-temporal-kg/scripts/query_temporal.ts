import crypto from "node:crypto";
import path from "node:path";
import readline from "node:readline";
import { performance } from "node:perf_hooks";
import { pathToFileURL } from "node:url";

import { hashU128, normalizeName, normalizePredicate } from "../src/lib/hash";

type SeedEntity = {
  name: string;
  kind?: string | null;
  score?: number | null;
};

type EvidenceInput = {
  sourceKind: string;
  sourceId: string;
  sourceUri?: string | null;
  capturedAtUs?: number | null;
  rawExcerpt?: string | null;
  hash?: string | null;
};

type RetrieveRequest = {
  op: "retrieve";
  projectId: string;
  seedEntities: SeedEntity[];
  asOfUs?: number | null;
  maxEdges?: number | null;
  maxHops?: number | null;
  alpha?: number | null;
  halfLifeHours?: number | null;
  minRelevance?: number | null;
};

type IngestClaimRequest = {
  op: "ingest_claim";
  projectId: string;
  subjectKind?: string | null;
  subjectName: string;
  predicate: string;
  objectKind?: string | null;
  objectName: string;
  validFromUs?: number | null;
  validToUs?: number | null;
  confidence?: number | null;
  evidence: EvidenceInput;
  nowUs?: number | null;
};

type IngestRelationRequest = {
  op: "ingest_relation";
  projectId: string;
  subjectKind: string;
  subjectName: string;
  predicate: string;
  objectKind: string;
  objectName: string;
  validFromUs?: number | null;
  validToUs?: number | null;
  confidence?: number | null;
  evidence: EvidenceInput;
  nowUs?: number | null;
};

type BridgeRequest = RetrieveRequest | IngestClaimRequest | IngestRelationRequest;

type HelperConfig = {
  stdbUri: string;
  stdbModuleName: string;
  stdbBindingsModule: string;
  stdbConfirmedReads: boolean;
  stdbToken?: string;
};

type NodeRow = {
  nodeId: bigint;
  projectId: string;
  kind: string;
  name: string;
  nameNorm: string;
  createdAtUs: bigint;
  updatedAtUs: bigint;
};

type EvidenceRow = {
  evidenceId: bigint;
  projectId: string;
  sourceKind: string;
  sourceId: string;
  sourceUri?: string;
  capturedAtUs: bigint;
  rawExcerpt?: string;
  hash: string;
};

type RetrievalResultRow = {
  edgeId: bigint;
  subjId: bigint;
  pred: string;
  objId: bigint;
  validFromUs: bigint;
  validToUs?: bigint;
  relevance: number;
  confidence: number;
  supportCount: number;
  contradictionCount: number;
  evidenceIds: bigint[];
};

type EvidenceReducerInput = {
  sourceKind: string;
  sourceId: string;
  sourceUri?: string;
  capturedAtUs: bigint;
  rawExcerpt?: string;
  hash: string;
};

type IngestTemporalClaimArgs = {
  projectId: string;
  subjectKind: string;
  subjectName: string;
  predicate: string;
  objectKind: string;
  objectName: string;
  validFromUs: bigint;
  validToUs?: bigint;
  confidence: number;
  evidence: EvidenceReducerInput;
  nowUs: bigint;
};

type IngestTemporalEdgeArgs = {
  projectId: string;
  subjId: bigint;
  pred: string;
  objId: bigint;
  validFromUs: bigint;
  validToUs?: bigint;
  confidence: number;
  evidence: EvidenceReducerInput;
  nowUs: bigint;
};

type UpsertNodeArgs = {
  projectId: string;
  kind: string;
  name: string;
  nowUs: bigint;
};

type TemporalRetrieveArgs = {
  projectId: string;
  seedNodeIds: bigint[];
  asOfUs: bigint;
  maxEdges: number;
  maxHops: number;
  alpha: number;
  halfLifeHours: number;
  minRelevance: number;
};

type BindingsModule = {
  DbConnection: {
    builder(): {
      withUri(uri: string): any;
      withDatabaseName(name: string): any;
      withConfirmedReads(enabled: boolean): any;
      withToken(token: string): any;
      onConnect(callback: (connection: GeneratedConnection) => void): any;
      onConnectError(callback: (_ctx: unknown, error: Error) => void): any;
      onDisconnect(callback: (_ctx: unknown, error: Error | null) => void): any;
      build(): void;
    };
  };
};

type GeneratedConnection = {
  db: {
    node: { iter(): Iterable<NodeRow> };
    evidence: { iter(): Iterable<EvidenceRow> };
  };
  reducers: {
    ingestTemporalClaim(args: IngestTemporalClaimArgs): Promise<void>;
    ingestTemporalEdge(args: IngestTemporalEdgeArgs): Promise<void>;
    upsertNode(args: UpsertNodeArgs): Promise<void>;
  };
  procedures: {
    temporalPprRetrieve(args: TemporalRetrieveArgs): Promise<RetrievalResultRow[]>;
  };
  subscriptionBuilder(): {
    onApplied(callback: () => void): any;
    onError(callback: (_ctx: unknown, error: Error) => void): any;
    subscribe(queries: string[]): unknown;
  };
  disconnect(): void;
};

type JsonRecord = Record<string, unknown>;

const toImportSpecifier = (value: string): string => {
  if (
    value.startsWith("http://") ||
    value.startsWith("https://") ||
    value.startsWith("file://")
  ) {
    return value;
  }
  return pathToFileURL(path.resolve(value)).href;
};

const toErrorPayload = (error: unknown): JsonRecord => {
  if (error instanceof Error) {
    return {
      message: error.message,
      name: error.name,
      stack: error.stack,
    };
  }
  return {
    message: String(error),
    name: "Error",
  };
};

const stableHash = (parts: Record<string, unknown>): string =>
  crypto.createHash("sha256").update(JSON.stringify(parts)).digest("hex");

const toMicros = (value?: number | null): bigint => BigInt(Math.trunc(value ?? Date.now() * 1000));

const toOptionalMicros = (value?: number | null): bigint | null =>
  value === null || value === undefined ? null : BigInt(Math.trunc(value));

const normalizeEvidence = (
  projectId: string,
  evidence: EvidenceInput,
  fallbackCapturedAtUs: bigint,
): EvidenceReducerInput => {
  const capturedAtUs = toMicros(evidence.capturedAtUs ?? Number(fallbackCapturedAtUs));
  return {
    sourceKind: evidence.sourceKind,
    sourceId: evidence.sourceId,
    sourceUri: evidence.sourceUri ?? undefined,
    capturedAtUs,
    rawExcerpt: evidence.rawExcerpt ?? undefined,
    hash:
      evidence.hash ??
      stableHash({
        projectId,
        sourceKind: evidence.sourceKind,
        sourceId: evidence.sourceId,
        sourceUri: evidence.sourceUri ?? null,
        rawExcerpt: evidence.rawExcerpt ?? null,
        capturedAtUs: capturedAtUs.toString(),
      }),
  };
};

const serializeNode = (row: NodeRow | undefined): JsonRecord | null =>
  row
    ? {
        nodeId: row.nodeId.toString(),
        projectId: row.projectId,
        kind: row.kind,
        name: row.name,
        nameNorm: row.nameNorm,
        createdAtUs: Number(row.createdAtUs),
        updatedAtUs: Number(row.updatedAtUs),
      }
    : null;

const serializeEvidence = (row: EvidenceRow | undefined): JsonRecord | null =>
  row
    ? {
        evidenceId: row.evidenceId.toString(),
        projectId: row.projectId,
        sourceKind: row.sourceKind,
        sourceId: row.sourceId,
        sourceUri: row.sourceUri ?? null,
        capturedAtUs: Number(row.capturedAtUs),
        rawExcerpt: row.rawExcerpt ?? null,
        hash: row.hash,
      }
    : null;

const serializeRetrievalResult = (
  row: RetrievalResultRow,
  nodeById: Map<string, NodeRow>,
  evidenceById: Map<string, EvidenceRow>,
  rank: number,
): JsonRecord => ({
  rank,
  edgeId: row.edgeId.toString(),
  subject: serializeNode(nodeById.get(row.subjId.toString())),
  predicate: row.pred,
  object: serializeNode(nodeById.get(row.objId.toString())),
  validFromUs: Number(row.validFromUs),
  validToUs: row.validToUs === null || row.validToUs === undefined ? null : Number(row.validToUs),
  relevance: row.relevance,
  confidence: row.confidence,
  supportCount: Number(row.supportCount),
  contradictionCount: Number(row.contradictionCount),
  evidence: row.evidenceIds
    .map((evidenceId) => serializeEvidence(evidenceById.get(evidenceId.toString())))
    .filter((item): item is JsonRecord => item !== null),
});

export class TemporalQueryHelper {
  private readonly config: HelperConfig;

  private readonly bindingsPromise: Promise<BindingsModule>;

  private connectionPromise: Promise<GeneratedConnection> | null = null;

  constructor(config: HelperConfig) {
    this.config = config;
    this.bindingsPromise = this.loadBindings();
  }

  private async loadBindings(): Promise<BindingsModule> {
    const moduleValue = (await import(toImportSpecifier(this.config.stdbBindingsModule))) as Partial<BindingsModule>;
    if (!moduleValue.DbConnection?.builder) {
      throw new Error("Generated bindings module must export DbConnection.builder().");
    }
    return moduleValue as BindingsModule;
  }

  private async connect(): Promise<GeneratedConnection> {
    const bindings = await this.bindingsPromise;

    return new Promise<GeneratedConnection>((resolve, reject) => {
      let settled = false;
      let builder = bindings.DbConnection
        .builder()
        .withUri(this.config.stdbUri)
        .withDatabaseName(this.config.stdbModuleName)
        .withConfirmedReads(this.config.stdbConfirmedReads)
        .onConnect((connection: GeneratedConnection) => {
          connection
            .subscriptionBuilder()
            .onApplied(() => {
              if (!settled) {
                settled = true;
                resolve(connection);
              }
            })
            .onError((_ctx: unknown, error: Error) => {
              if (!settled) {
                settled = true;
                reject(error);
                return;
              }
              console.error("[am-temporal-kg] subscription error", error);
            })
            .subscribe([
              "SELECT * FROM node",
              "SELECT * FROM edge",
              "SELECT * FROM evidence",
              "SELECT * FROM edge_evidence",
              "SELECT * FROM edge_archive",
            ]);
        })
        .onConnectError((_ctx: unknown, error: Error) => {
          if (!settled) {
            settled = true;
            reject(error);
          }
        })
        .onDisconnect((_ctx: unknown, error: Error | null) => {
          this.connectionPromise = null;
          if (error) {
            console.error("[am-temporal-kg] disconnected", error);
          }
        });

      if (this.config.stdbToken) {
        builder = builder.withToken(this.config.stdbToken);
      }

      builder.build();
    });
  }

  private async getConnection(): Promise<GeneratedConnection> {
    if (this.connectionPromise === null) {
      this.connectionPromise = this.connect();
    }
    return this.connectionPromise;
  }

  private async getNodeCache(connection: GeneratedConnection): Promise<Map<string, NodeRow>> {
    const rows = Array.from(connection.db.node.iter()) as NodeRow[];
    return new Map(rows.map((row) => [row.nodeId.toString(), row]));
  }

  private async getEvidenceCache(connection: GeneratedConnection): Promise<Map<string, EvidenceRow>> {
    const rows = Array.from(connection.db.evidence.iter()) as EvidenceRow[];
    return new Map(rows.map((row) => [row.evidenceId.toString(), row]));
  }

  private resolveSeedNodeIds(connection: GeneratedConnection, projectId: string, seedEntities: SeedEntity[]): bigint[] {
    const rows = Array.from(connection.db.node.iter()) as NodeRow[];
    const seedIds: bigint[] = [];
    const seen = new Set<string>();

    for (const seed of seedEntities) {
      const normalized = normalizeName(seed.name);
      const exactMatches = rows.filter(
        (row) =>
          row.projectId === projectId &&
          row.nameNorm === normalized &&
          (seed.kind ? row.kind === seed.kind : true),
      );
      const matches = exactMatches.length > 0
        ? exactMatches
        : rows.filter((row) => row.projectId === projectId && row.nameNorm === normalized);

      for (const row of matches) {
        const key = row.nodeId.toString();
        if (!seen.has(key)) {
          seen.add(key);
          seedIds.push(row.nodeId);
        }
      }
    }

    return seedIds;
  }

  async retrieve(request: RetrieveRequest): Promise<JsonRecord> {
    const totalStart = performance.now();
    const connection = await this.getConnection();

    const resolveStart = performance.now();
    const seedNodeIds = this.resolveSeedNodeIds(connection, request.projectId, request.seedEntities);
    const resolveSeedsMs = performance.now() - resolveStart;

    if (seedNodeIds.length === 0) {
      return {
        results: [],
        seedNodeIds: [],
        timingsMs: {
          resolveSeeds: resolveSeedsMs,
          procedure: 0,
          hydrate: 0,
          total: performance.now() - totalStart,
        },
      };
    }

    const args: TemporalRetrieveArgs = {
      projectId: request.projectId,
      seedNodeIds,
      asOfUs: toMicros(request.asOfUs),
      maxEdges: request.maxEdges ?? 10,
      maxHops: request.maxHops ?? 2,
      alpha: request.alpha ?? 0.85,
      halfLifeHours: request.halfLifeHours ?? 24,
      minRelevance: request.minRelevance ?? 0.05,
    };

    const procedureStart = performance.now();
    const rawResults = await connection.procedures.temporalPprRetrieve(args);
    const procedureMs = performance.now() - procedureStart;

    const hydrateStart = performance.now();
    const nodeById = await this.getNodeCache(connection);
    const evidenceById = await this.getEvidenceCache(connection);
    const results = rawResults.map((row: RetrievalResultRow, index: number) =>
      serializeRetrievalResult(row, nodeById, evidenceById, index + 1),
    );
    const hydrateMs = performance.now() - hydrateStart;

    return {
      results,
      seedNodeIds: seedNodeIds.map((value) => value.toString()),
      timingsMs: {
        resolveSeeds: resolveSeedsMs,
        procedure: procedureMs,
        hydrate: hydrateMs,
        total: performance.now() - totalStart,
      },
    };
  }

  async ingestClaim(request: IngestClaimRequest): Promise<JsonRecord> {
    const connection = await this.getConnection();
    const nowUs = toMicros(request.nowUs);
    const args: IngestTemporalClaimArgs = {
      projectId: request.projectId,
      subjectKind: request.subjectKind ?? "unknown",
      subjectName: request.subjectName,
      predicate: normalizePredicate(request.predicate),
      objectKind: request.objectKind ?? "unknown",
      objectName: request.objectName,
      validFromUs: toMicros(request.validFromUs ?? Number(nowUs)),
      validToUs: toOptionalMicros(request.validToUs) ?? undefined,
      confidence: request.confidence ?? 1.0,
      evidence: normalizeEvidence(request.projectId, request.evidence, nowUs),
      nowUs,
    };
    await connection.reducers.ingestTemporalClaim(args);
    return { subjectName: args.subjectName, predicate: args.predicate, objectName: args.objectName };
  }

  async ingestRelation(request: IngestRelationRequest): Promise<JsonRecord> {
    const connection = await this.getConnection();
    const nowUs = toMicros(request.nowUs);

    const subjectParams: UpsertNodeArgs = {
      projectId: request.projectId,
      kind: request.subjectKind,
      name: request.subjectName,
      nowUs,
    };
    const objectParams: UpsertNodeArgs = {
      projectId: request.projectId,
      kind: request.objectKind,
      name: request.objectName,
      nowUs,
    };

    await connection.reducers.upsertNode(subjectParams);
    await connection.reducers.upsertNode(objectParams);

    const subjId = hashU128(request.projectId, request.subjectKind, normalizeName(request.subjectName));
    const objId = hashU128(request.projectId, request.objectKind, normalizeName(request.objectName));

    const args: IngestTemporalEdgeArgs = {
      projectId: request.projectId,
      subjId,
      pred: normalizePredicate(request.predicate),
      objId,
      validFromUs: toMicros(request.validFromUs ?? Number(nowUs)),
      validToUs: toOptionalMicros(request.validToUs) ?? undefined,
      confidence: request.confidence ?? 1.0,
      evidence: normalizeEvidence(request.projectId, request.evidence, nowUs),
      nowUs,
    };

    await connection.reducers.ingestTemporalEdge(args);
    return {
      subjectNodeId: subjId.toString(),
      objectNodeId: objId.toString(),
      predicate: args.pred,
    };
  }

  async close(): Promise<void> {
    if (this.connectionPromise === null) {
      return;
    }
    const connection = await this.connectionPromise;
    connection.disconnect();
    this.connectionPromise = null;
  }
}

export const createHelperFromEnv = (): TemporalQueryHelper => {
  const stdbBindingsModule = process.env.STDB_BINDINGS_MODULE;
  if (!stdbBindingsModule) {
    throw new Error("Missing required environment variable: STDB_BINDINGS_MODULE");
  }

  return new TemporalQueryHelper({
    stdbUri: process.env.STDB_URI ?? "http://127.0.0.1:3000",
    stdbModuleName: process.env.STDB_MODULE_NAME ?? "agentic-memory-temporal",
    stdbBindingsModule,
    stdbConfirmedReads: process.env.STDB_CONFIRMED_READS !== "false",
    ...(process.env.STDB_TOKEN ? { stdbToken: process.env.STDB_TOKEN } : {}),
  });
};

const writeResponse = (payload: JsonRecord): void => {
  process.stdout.write(
    `${JSON.stringify(payload, (_key, value) => (typeof value === "bigint" ? value.toString() : value))}\n`,
  );
};

export const runBridgeServer = async (): Promise<void> => {
  const helper = createHelperFromEnv();
  const rl = readline.createInterface({
    input: process.stdin,
    crlfDelay: Infinity,
  });

  process.on("SIGINT", () => {
    void helper.close().finally(() => process.exit(0));
  });
  process.on("SIGTERM", () => {
    void helper.close().finally(() => process.exit(0));
  });

  for await (const line of rl) {
    if (!line.trim()) {
      continue;
    }

    let request: BridgeRequest;
    try {
      request = JSON.parse(line) as BridgeRequest;
    } catch (error) {
      writeResponse({ ok: false, error: { ...toErrorPayload(error), code: "invalid_json" } });
      continue;
    }

    try {
      let payload: JsonRecord;
      if (request.op === "retrieve") {
        payload = await helper.retrieve(request);
      } else if (request.op === "ingest_claim") {
        payload = await helper.ingestClaim(request);
      } else if (request.op === "ingest_relation") {
        payload = await helper.ingestRelation(request);
      } else {
        throw new Error(`Unsupported op: ${(request as BridgeRequest).op}`);
      }

      writeResponse({ ok: true, ...payload });
    } catch (error) {
      writeResponse({ ok: false, error: { ...toErrorPayload(error), code: "bridge_error" } });
    }
  }

  await helper.close();
};

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  void runBridgeServer().catch((error) => {
    writeResponse({ ok: false, error: { ...toErrorPayload(error), code: "fatal_bridge_error" } });
    process.exitCode = 1;
  });
}
