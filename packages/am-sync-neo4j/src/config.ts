import path from "node:path";

import type { SyncConfig } from "./types";

const requireEnv = (name: string): string => {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
};

export const loadConfig = (): SyncConfig => ({
  stdbUri: requireEnv("STDB_URI"),
  stdbModuleName: process.env.STDB_MODULE_NAME ?? "agentic-memory-temporal",
  stdbBindingsModule: requireEnv("STDB_BINDINGS_MODULE"),
  stdbConfirmedReads: process.env.STDB_CONFIRMED_READS !== "false",
  neo4jUri: process.env.NEO4J_URI ?? "bolt://127.0.0.1:7687",
  neo4jUser: process.env.NEO4J_USER ?? "neo4j",
  neo4jPassword: requireEnv("NEO4J_PASSWORD"),
  checkpointPath:
    process.env.AM_SYNC_CHECKPOINT_PATH ??
    path.resolve(".cache", "am-sync-neo4j", "checkpoints.json"),
  ...(process.env.STDB_TOKEN ? { stdbToken: process.env.STDB_TOKEN } : {}),
});
