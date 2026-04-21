import { t } from "spacetimedb/server";

import { ModuleHealthRow, spacetimedb } from "../schema";

const countRows = (rows: Iterable<unknown>): bigint => {
  let count = 0n;
  for (const _row of rows) {
    count += 1n;
  }
  return count;
};

export const module_health = spacetimedb.view(
  { name: "module_health", public: true },
  t.array(ModuleHealthRow),
  (ctx: any) => [
    {
      generatedAtUs: ctx.timestamp.microsSinceUnixEpoch,
      nodeCount: countRows(ctx.db.node.iter()),
      edgeCount: countRows(ctx.db.edge.iter()),
      evidenceCount: countRows(ctx.db.evidence.iter()),
      archiveCount: countRows(ctx.db.edge_archive.iter()),
      maintenanceJobCount: countRows(ctx.db.maintenance_job.iter()),
    },
  ],
);
