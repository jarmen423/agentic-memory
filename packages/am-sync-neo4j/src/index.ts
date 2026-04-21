import "dotenv/config";

import { FileCheckpointStore } from "./checkpoints";
import { loadConfig } from "./config";
import { primaryKeyForRow, rowSignature } from "./mappers";
import { Neo4jSyncClient } from "./neo4j_client";
import { connectSpacetime } from "./stdb_client";

process.on("uncaughtException", (error) => {
  console.error("[am-sync-neo4j] uncaught exception", error);
});
process.on("unhandledRejection", (error) => {
  console.error("[am-sync-neo4j] unhandled rejection", error);
});

const config = loadConfig();
const checkpointStore = new FileCheckpointStore(config.checkpointPath);
checkpointStore.load();

const neo4jClient = new Neo4jSyncClient(config);
const spacetimeConnection = await connectSpacetime(config, {
  onNodeUpsert: async (row) => {
    const primaryKey = primaryKeyForRow(row as Record<string, unknown>);
    const signature = rowSignature(row);
    if (!checkpointStore.shouldApply("node", primaryKey, signature)) {
      return;
    }
    await neo4jClient.syncNode(row);
    checkpointStore.record("node", primaryKey, signature);
    checkpointStore.flush();
  },
  onNodeDelete: async (row) => {
    await neo4jClient.markNodeDeleted(row.nodeId);
  },
  onEdgeUpsert: async (row) => {
    const primaryKey = primaryKeyForRow(row as Record<string, unknown>);
    const signature = rowSignature(row);
    if (!checkpointStore.shouldApply("edge", primaryKey, signature)) {
      return;
    }
    await neo4jClient.syncEdge(row);
    checkpointStore.record("edge", primaryKey, signature);
    checkpointStore.flush();
  },
  onEdgeDelete: async (row) => {
    await neo4jClient.markEdgeDeleted(row.edgeId);
  },
  onEvidenceUpsert: async (row) => {
    const primaryKey = primaryKeyForRow(row as Record<string, unknown>);
    const signature = rowSignature(row);
    if (!checkpointStore.shouldApply("evidence", primaryKey, signature)) {
      return;
    }
    await neo4jClient.syncEvidence(row);
    checkpointStore.record("evidence", primaryKey, signature);
    checkpointStore.flush();
  },
  onEvidenceDelete: async (row) => {
    await neo4jClient.markEvidenceDeleted(row.evidenceId);
  },
  onEdgeEvidenceUpsert: async (row) => {
    const primaryKey = primaryKeyForRow(row as Record<string, unknown>);
    const signature = rowSignature(row);
    if (!checkpointStore.shouldApply("edge_evidence", primaryKey, signature)) {
      return;
    }
    await neo4jClient.syncEdgeEvidence(row);
    checkpointStore.record("edge_evidence", primaryKey, signature);
    checkpointStore.flush();
  },
  onArchive: async (row) => {
    const primaryKey = primaryKeyForRow(row as Record<string, unknown>);
    const signature = rowSignature(row);
    if (!checkpointStore.shouldApply("edge_archive", primaryKey, signature)) {
      return;
    }
    await neo4jClient.applyArchive(row);
    checkpointStore.record("edge_archive", primaryKey, signature);
    checkpointStore.flush();
  },
});

console.log(
  `[am-sync-neo4j] connected to ${config.stdbModuleName} at ${config.stdbUri} and syncing to ${config.neo4jUri}`,
);

const shutdown = async (): Promise<void> => {
  console.log("[am-sync-neo4j] shutting down");
  try {
    checkpointStore.flush();
    spacetimeConnection.disconnect();
    await neo4jClient.close();
  } finally {
    process.exit(0);
  }
};

process.on("SIGINT", () => {
  void shutdown();
});
process.on("SIGTERM", () => {
  void shutdown();
});

await new Promise<void>(() => {
  // Keep the worker alive; subscriptions run through callbacks.
});
