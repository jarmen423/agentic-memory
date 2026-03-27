import fs from "node:fs";
import path from "node:path";

import type { SyncCheckpointState } from "./types";

const EMPTY_STATE: SyncCheckpointState = { rows: {} };

export class FileCheckpointStore {
  readonly path: string;

  private state: SyncCheckpointState = EMPTY_STATE;

  constructor(pathname: string) {
    this.path = pathname;
  }

  load(): void {
    if (!fs.existsSync(this.path)) {
      this.state = { rows: {} };
      return;
    }
    const raw = fs.readFileSync(this.path, "utf8");
    this.state = JSON.parse(raw) as SyncCheckpointState;
  }

  shouldApply(scope: string, primaryKey: string, signature: string): boolean {
    const current = this.state.rows[`${scope}:${primaryKey}`];
    return current !== signature;
  }

  record(scope: string, primaryKey: string, signature: string): void {
    this.state.rows[`${scope}:${primaryKey}`] = signature;
  }

  flush(): void {
    fs.mkdirSync(path.dirname(this.path), { recursive: true });
    fs.writeFileSync(this.path, JSON.stringify(this.state, null, 2));
  }
}
