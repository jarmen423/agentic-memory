#!/usr/bin/env node

/**
 * Explicit SpacetimeDB target wrapper for Agentic Memory local-stack commands.
 *
 * Why this script exists:
 *
 * - `spacetime publish` supports `--server`, but `spacetime generate` does not.
 * - Relying on a saved `local` alias or an ambient default server made the
 *   onboarding flow fragile and machine-specific.
 * - The local stack now treats the SpacetimeDB target as explicit operator
 *   input via `STDB_URI`, then temporarily points the CLI at that server when
 *   generation requires a default target.
 *
 * Supported commands:
 *
 * - `publish-temporal`
 * - `generate-temporal-bindings`
 */

import { spawnSync } from "node:child_process";

const TEMPORAL_SERVER_ALIAS = process.env.STDB_SERVER_ALIAS?.trim() || "agentic-memory-temporal-target";
const STDB_URI = requireEnv(
  "STDB_URI",
  "Set STDB_URI to the real SpacetimeDB host, for example http://127.0.0.1:3001.",
);
const STDB_MODULE_NAME = process.env.STDB_MODULE_NAME?.trim() || "agentic-memory-temporal";
const SPACETIME_BIN = process.env.SPACETIME_BIN?.trim() || "spacetime";

function requireEnv(name, helpText) {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`Missing required environment variable ${name}. ${helpText}`);
  }
  return value;
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    stdio: options.capture ? ["inherit", "pipe", "pipe"] : "inherit",
    encoding: "utf-8",
    shell: false,
    ...options,
  });
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    const stderr = result.stderr?.trim();
    const stdout = result.stdout?.trim();
    throw new Error(
      [
        `Command failed: ${command} ${args.join(" ")}`,
        stderr || stdout || `exit code ${result.status}`,
      ].join("\n"),
    );
  }
  return result;
}

function readServerList() {
  return run(SPACETIME_BIN, ["server", "list"], { capture: true }).stdout ?? "";
}

function parseDefaultServerName(serverListOutput) {
  const lines = serverListOutput
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  for (const line of lines) {
    if (!line.startsWith("***")) {
      continue;
    }
    const columns = line.split(/\s+/);
    return columns.at(-1) ?? null;
  }
  return null;
}

function hasAlias(serverListOutput, alias) {
  return serverListOutput
    .split(/\r?\n/)
    .some((line) => line.trim().split(/\s+/).at(-1) === alias);
}

function ensureTargetAlias(alias, url) {
  const serverListOutput = readServerList();
  if (hasAlias(serverListOutput, alias)) {
    run(SPACETIME_BIN, ["server", "edit", alias, "--url", url, "--no-fingerprint", "-y"]);
    return;
  }
  run(SPACETIME_BIN, ["server", "add", alias, "--url", url, "--no-fingerprint"]);
}

function withDefaultServer(alias, callback) {
  const previousDefault = parseDefaultServerName(readServerList());
  run(SPACETIME_BIN, ["server", "set-default", alias]);
  try {
    callback();
  } finally {
    if (previousDefault && previousDefault !== alias) {
      run(SPACETIME_BIN, ["server", "set-default", previousDefault]);
    }
  }
}

function publishTemporal() {
  run(SPACETIME_BIN, [
    "publish",
    "--server",
    STDB_URI,
    "--yes",
    "--delete-data",
    "--module-path",
    ".",
    STDB_MODULE_NAME,
  ]);
}

function generateTemporalBindings() {
  ensureTargetAlias(TEMPORAL_SERVER_ALIAS, STDB_URI);
  withDefaultServer(TEMPORAL_SERVER_ALIAS, () => {
    run(SPACETIME_BIN, [
      "generate",
      STDB_MODULE_NAME,
      "--lang",
      "typescript",
      "--out-dir",
      "./generated-bindings",
      "--module-path",
      ".",
    ]);
  });
}

function main() {
  const command = process.argv[2];
  switch (command) {
    case "publish-temporal":
      publishTemporal();
      return;
    case "generate-temporal-bindings":
      generateTemporalBindings();
      return;
    default:
      throw new Error(
        `Unsupported command ${String(command)}. Use publish-temporal or generate-temporal-bindings.`,
      );
  }
}

try {
  main();
} catch (error) {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(`${message}\n`);
  process.exitCode = 1;
}
