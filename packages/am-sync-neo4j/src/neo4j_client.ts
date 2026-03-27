import neo4j, { type Driver } from "neo4j-driver";

import {
  archiveParams,
  edgeEvidenceParams,
  edgeParams,
  evidenceParams,
  nodeParams,
  sanitizeRelationType,
} from "./mappers";
import type {
  SyncConfig,
  TemporalArchiveRow,
  TemporalEdgeEvidenceRow,
  TemporalEdgeRow,
  TemporalEvidenceRow,
  TemporalNodeRow,
} from "./types";

export class Neo4jSyncClient {
  private readonly driver: Driver;

  constructor(config: SyncConfig) {
    this.driver = neo4j.driver(
      config.neo4jUri,
      neo4j.auth.basic(config.neo4jUser, config.neo4jPassword),
    );
  }

  async close(): Promise<void> {
    await this.driver.close();
  }

  async syncNode(row: TemporalNodeRow): Promise<void> {
    const session = this.driver.session();
    try {
      await session.executeWrite((tx) =>
        tx.run(
          `
          MERGE (n:TemporalNode {node_id: $node_id})
          SET n.project_id = $project_id,
              n.kind = $kind,
              n.name = $name,
              n.name_norm = $name_norm,
              n.created_at_us = $created_at_us,
              n.updated_at_us = $updated_at_us,
              n.created_at_iso = $created_at_iso,
              n.updated_at_iso = $updated_at_iso,
              n.deleted = false
          `,
          nodeParams(row),
        ),
      );
    } finally {
      await session.close();
    }
  }

  async markNodeDeleted(nodeId: bigint): Promise<void> {
    const session = this.driver.session();
    try {
      await session.executeWrite((tx) =>
        tx.run(
          `
          MATCH (n:TemporalNode {node_id: $node_id})
          SET n.deleted = true,
              n.deleted_at = datetime()
          `,
          { node_id: nodeId.toString() },
        ),
      );
    } finally {
      await session.close();
    }
  }

  async syncEdge(row: TemporalEdgeRow): Promise<void> {
    const session = this.driver.session();
    const relType = sanitizeRelationType(row.pred);
    try {
      await session.executeWrite((tx) =>
        tx.run(
          `
          MERGE (subj:TemporalNode {node_id: $subj_id})
          MERGE (obj:TemporalNode {node_id: $obj_id})
          MERGE (edge:TemporalEdge {edge_id: $edge_id})
          SET edge.project_id = $project_id,
              edge.family_id = $family_id,
              edge.pred = $pred,
              edge.valid_from_us = $valid_from_us,
              edge.valid_to_us = $valid_to_us,
              edge.valid_from_iso = $valid_from_iso,
              edge.valid_to_iso = $valid_to_iso,
              edge.created_at_us = $created_at_us,
              edge.updated_at_us = $updated_at_us,
              edge.last_reinforced_at_us = $last_reinforced_at_us,
              edge.confidence = $confidence,
              edge.support_count = $support_count,
              edge.contradiction_count = $contradiction_count,
              edge.relevance = $relevance,
              edge.archived = false,
              edge.deleted = false
          MERGE (subj)-[:EDGE_SUBJECT]->(edge)
          MERGE (edge)-[:EDGE_OBJECT]->(obj)
          MERGE (subj)-[r:${relType} {edge_id: $edge_id}]->(obj)
          SET r.project_id = $project_id,
              r.family_id = $family_id,
              r.pred = $pred,
              r.valid_from_us = $valid_from_us,
              r.valid_to_us = $valid_to_us,
              r.valid_from_iso = $valid_from_iso,
              r.valid_to_iso = $valid_to_iso,
              r.created_at_us = $created_at_us,
              r.updated_at_us = $updated_at_us,
              r.last_reinforced_at_us = $last_reinforced_at_us,
              r.confidence = $confidence,
              r.support_count = $support_count,
              r.contradiction_count = $contradiction_count,
              r.relevance = $relevance,
              r.archived = false,
              r.deleted = false
          `,
          edgeParams(row),
        ),
      );
    } finally {
      await session.close();
    }
  }

  async markEdgeDeleted(edgeId: bigint): Promise<void> {
    const session = this.driver.session();
    try {
      await session.executeWrite((tx) =>
        tx.run(
          `
          MATCH (edge:TemporalEdge {edge_id: $edge_id})
          SET edge.deleted = true,
              edge.deleted_at = datetime()
          WITH edge
          OPTIONAL MATCH (:TemporalNode)-[r {edge_id: $edge_id}]->(:TemporalNode)
          SET r.deleted = true,
              r.deleted_at = datetime()
          `,
          { edge_id: edgeId.toString() },
        ),
      );
    } finally {
      await session.close();
    }
  }

  async syncEvidence(row: TemporalEvidenceRow): Promise<void> {
    const session = this.driver.session();
    try {
      await session.executeWrite((tx) =>
        tx.run(
          `
          MERGE (e:TemporalEvidence {evidence_id: $evidence_id})
          SET e.project_id = $project_id,
              e.source_kind = $source_kind,
              e.source_id = $source_id,
              e.source_uri = $source_uri,
              e.captured_at_us = $captured_at_us,
              e.captured_at_iso = $captured_at_iso,
              e.raw_excerpt = $raw_excerpt,
              e.hash = $hash,
              e.deleted = false
          `,
          evidenceParams(row),
        ),
      );
    } finally {
      await session.close();
    }
  }

  async markEvidenceDeleted(evidenceId: bigint): Promise<void> {
    const session = this.driver.session();
    try {
      await session.executeWrite((tx) =>
        tx.run(
          `
          MATCH (e:TemporalEvidence {evidence_id: $evidence_id})
          SET e.deleted = true,
              e.deleted_at = datetime()
          `,
          { evidence_id: evidenceId.toString() },
        ),
      );
    } finally {
      await session.close();
    }
  }

  async syncEdgeEvidence(row: TemporalEdgeEvidenceRow): Promise<void> {
    const session = this.driver.session();
    try {
      await session.executeWrite((tx) =>
        tx.run(
          `
          MATCH (e:TemporalEvidence {evidence_id: $evidence_id})
          MATCH (edge:TemporalEdge {edge_id: $edge_id})
          MERGE (e)-[r:SUPPORTS {link_id: $link_id}]->(edge)
          SET r.linked_at_us = $linked_at_us,
              r.linked_at_iso = $linked_at_iso
          `,
          edgeEvidenceParams(row),
        ),
      );
    } finally {
      await session.close();
    }
  }

  async applyArchive(row: TemporalArchiveRow): Promise<void> {
    const session = this.driver.session();
    try {
      await session.executeWrite((tx) =>
        tx.run(
          `
          MERGE (archive:TemporalArchive {archive_id: $archive_id})
          SET archive.project_id = $project_id,
              archive.edge_id = $edge_id,
              archive.archived_at_us = $archived_at_us,
              archive.archived_at_iso = $archived_at_iso,
              archive.reason = $reason,
              archive.snapshot_json = $snapshot_json
          WITH archive
          MATCH (edge:TemporalEdge {edge_id: $edge_id})
          SET edge.archived = true,
              edge.archived_at_us = $archived_at_us,
              edge.archived_at_iso = $archived_at_iso,
              edge.archive_reason = $reason
          WITH archive
          OPTIONAL MATCH (:TemporalNode)-[r {edge_id: $edge_id}]->(:TemporalNode)
          SET r.archived = true,
              r.archived_at_us = $archived_at_us,
              r.archived_at_iso = $archived_at_iso,
              r.archive_reason = $reason
          `,
          archiveParams(row),
        ),
      );
    } finally {
      await session.close();
    }
  }
}
