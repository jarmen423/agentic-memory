import path from "node:path";

import type {
  SyncConfig,
  TemporalArchiveRow,
  TemporalEdgeEvidenceRow,
  TemporalEdgeRow,
  TemporalEvidenceRow,
  TemporalNodeRow,
} from "./types";

type GeneratedConnection = {
  db: {
    node: any;
    edge: any;
    evidence: any;
    edge_evidence: any;
    edge_archive: any;
  };
  subscriptionBuilder(): {
    onApplied(callback: () => void): any;
    onError(callback: (_ctx: unknown, error: Error) => void): any;
    subscribe(queries: string[]): unknown;
  };
  disconnect(): void;
};

type SpacetimeHandlers = {
  onNodeUpsert(row: TemporalNodeRow): Promise<void> | void;
  onNodeDelete(row: TemporalNodeRow): Promise<void> | void;
  onEdgeUpsert(row: TemporalEdgeRow): Promise<void> | void;
  onEdgeDelete(row: TemporalEdgeRow): Promise<void> | void;
  onEvidenceUpsert(row: TemporalEvidenceRow): Promise<void> | void;
  onEvidenceDelete(row: TemporalEvidenceRow): Promise<void> | void;
  onEdgeEvidenceUpsert(row: TemporalEdgeEvidenceRow): Promise<void> | void;
  onArchive(row: TemporalArchiveRow): Promise<void> | void;
};

const toImportSpecifier = (value: string): string => {
  if (
    value.startsWith("http://") ||
    value.startsWith("https://") ||
    value.startsWith("file://")
  ) {
    return value;
  }
  return path.resolve(value);
};

const fireAndForget = (promiseLike: Promise<void> | void, label: string): void => {
  void Promise.resolve(promiseLike).catch((error) => {
    console.error(`[am-sync-neo4j] ${label} failed`, error);
  });
};

const registerRowCallbacks = (connection: GeneratedConnection, handlers: SpacetimeHandlers): void => {
  connection.db.node.onInsert((_ctx: unknown, row: TemporalNodeRow) =>
    fireAndForget(handlers.onNodeUpsert(row), "node insert"),
  );
  connection.db.node.onUpdate((_ctx: unknown, _oldRow: TemporalNodeRow, row: TemporalNodeRow) =>
    fireAndForget(handlers.onNodeUpsert(row), "node update"),
  );
  connection.db.node.onDelete((_ctx: unknown, row: TemporalNodeRow) =>
    fireAndForget(handlers.onNodeDelete(row), "node delete"),
  );

  connection.db.edge.onInsert((_ctx: unknown, row: TemporalEdgeRow) =>
    fireAndForget(handlers.onEdgeUpsert(row), "edge insert"),
  );
  connection.db.edge.onUpdate((_ctx: unknown, _oldRow: TemporalEdgeRow, row: TemporalEdgeRow) =>
    fireAndForget(handlers.onEdgeUpsert(row), "edge update"),
  );
  connection.db.edge.onDelete((_ctx: unknown, row: TemporalEdgeRow) =>
    fireAndForget(handlers.onEdgeDelete(row), "edge delete"),
  );

  connection.db.evidence.onInsert((_ctx: unknown, row: TemporalEvidenceRow) =>
    fireAndForget(handlers.onEvidenceUpsert(row), "evidence insert"),
  );
  connection.db.evidence.onUpdate(
    (_ctx: unknown, _oldRow: TemporalEvidenceRow, row: TemporalEvidenceRow) =>
      fireAndForget(handlers.onEvidenceUpsert(row), "evidence update"),
  );
  connection.db.evidence.onDelete((_ctx: unknown, row: TemporalEvidenceRow) =>
    fireAndForget(handlers.onEvidenceDelete(row), "evidence delete"),
  );

  connection.db.edge_evidence.onInsert((_ctx: unknown, row: TemporalEdgeEvidenceRow) =>
    fireAndForget(handlers.onEdgeEvidenceUpsert(row), "edge_evidence insert"),
  );
  connection.db.edge_evidence.onUpdate(
    (_ctx: unknown, _oldRow: TemporalEdgeEvidenceRow, row: TemporalEdgeEvidenceRow) =>
      fireAndForget(handlers.onEdgeEvidenceUpsert(row), "edge_evidence update"),
  );

  connection.db.edge_archive.onInsert((_ctx: unknown, row: TemporalArchiveRow) =>
    fireAndForget(handlers.onArchive(row), "edge_archive insert"),
  );
  connection.db.edge_archive.onUpdate((_ctx: unknown, _oldRow: TemporalArchiveRow, row: TemporalArchiveRow) =>
    fireAndForget(handlers.onArchive(row), "edge_archive update"),
  );
}

export const connectSpacetime = async (
  config: SyncConfig,
  handlers: SpacetimeHandlers,
): Promise<GeneratedConnection> => {
  const bindings = (await import(toImportSpecifier(config.stdbBindingsModule))) as {
    DbConnection?: { builder(): any };
  };

  if (!bindings.DbConnection?.builder) {
    throw new Error("Generated bindings module must export DbConnection.builder()");
  }

  return new Promise<GeneratedConnection>((resolve, reject) => {
    let settled = false;
    let builder = bindings.DbConnection!.builder()
      .withUri(config.stdbUri)
      .withDatabaseName(config.stdbModuleName)
      .withConfirmedReads(config.stdbConfirmedReads)
      .onConnect((connection: GeneratedConnection) => {
        registerRowCallbacks(connection, handlers);
        connection.subscriptionBuilder()
          .onApplied(() => {
            console.log("[am-sync-neo4j] subscription applied");
          })
          .onError((_ctx: unknown, error: Error) => {
            console.error("[am-sync-neo4j] subscription error", error);
          })
          .subscribe([
            "SELECT * FROM node",
            "SELECT * FROM edge",
            "SELECT * FROM evidence",
            "SELECT * FROM edge_evidence",
            "SELECT * FROM edge_archive",
          ]);

        if (!settled) {
          settled = true;
          resolve(connection);
        }
      })
      .onConnectError((_ctx: unknown, error: Error) => {
        console.error("[am-sync-neo4j] connect error", error);
        if (!settled) {
          settled = true;
          reject(error);
        }
      })
      .onDisconnect((_ctx: unknown, error: Error | null) => {
        if (error) {
          console.error("[am-sync-neo4j] disconnected", error);
        } else {
          console.log("[am-sync-neo4j] disconnected");
        }
      });

    if (config.stdbToken) {
      builder = builder.withToken(config.stdbToken);
    }

    builder.build();
  });
};
