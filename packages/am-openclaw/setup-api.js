/**
 * OpenClaw setup-time hooks for the Agentic Memory plugin.
 *
 * This file lives at the package root, not under `src/`, because OpenClaw's
 * setup registry looks for `setup-api.{js,ts,...}` beside `openclaw.plugin.json`.
 *
 * The goal of this migration is pragmatic:
 *
 * - a plain `openclaw plugins install --link ...` already claims the memory slot
 * - current Agentic Memory capture also needs the ContextEngine slot so turn
 *   lifecycle hooks can reach the backend
 * - the plugin should default to `capture_only`, which means "capture memory,
 *   but do not assemble custom context"
 *
 * So when OpenClaw sees this plugin installed or enabled, this migration fills
 * in the missing config defaults that the plain install path does not yet write
 * on its own.
 */

import { definePluginEntry } from "openclaw/plugin-sdk/core";

const PLUGIN_ID = "agentic-memory";
const DEFAULT_CONTEXT_ENGINE_ID = "agentic-memory";
const DEFAULT_MODE = "capture_only";

/**
 * Narrow an unknown value to a plain object record.
 *
 * OpenClaw config payloads are untyped at this integration boundary, so setup
 * hooks defensively check each nested object before reading or cloning fields.
 *
 * @param {unknown} value
 * @returns {value is Record<string, unknown>}
 */
function isRecord(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

/**
 * Decide whether the current config already references Agentic Memory strongly
 * enough that we should apply the capture-first defaults.
 *
 * We intentionally look for install records, enabled entries, or slot
 * selection. That keeps the migration focused on real plugin installs and
 * avoids unexpectedly rewriting unrelated configs.
 *
 * @param {Record<string, unknown>} config
 * @returns {boolean}
 */
function shouldApplyAgenticMemoryDefaults(config) {
  const plugins = isRecord(config.plugins) ? config.plugins : {};
  const entries = isRecord(plugins.entries) ? plugins.entries : {};
  const installs = isRecord(plugins.installs) ? plugins.installs : {};
  const slots = isRecord(plugins.slots) ? plugins.slots : {};
  const entry = isRecord(entries[PLUGIN_ID]) ? entries[PLUGIN_ID] : null;

  return (
    entry?.enabled === true ||
    isRecord(installs[PLUGIN_ID]) ||
    slots.memory === PLUGIN_ID ||
    slots.contextEngine === DEFAULT_CONTEXT_ENGINE_ID
  );
}

export default definePluginEntry({
  id: PLUGIN_ID,
  name: "Agentic Memory Setup",
  description: "Setup-time config migrations for Agentic Memory",
  register(api) {
    api.registerConfigMigration((config) => {
      if (!isRecord(config) || !shouldApplyAgenticMemoryDefaults(config)) {
        return null;
      }

      const next = structuredClone(config);
      const changes = [];

      if (!isRecord(next.plugins)) {
        next.plugins = {};
      }
      if (!isRecord(next.plugins.entries)) {
        next.plugins.entries = {};
      }
      if (!isRecord(next.plugins.slots)) {
        next.plugins.slots = {};
      }

      const rawEntry = isRecord(next.plugins.entries[PLUGIN_ID]) ? next.plugins.entries[PLUGIN_ID] : {};
      const rawConfig = isRecord(rawEntry.config) ? rawEntry.config : {};

      if (rawConfig.mode !== "capture_only" && rawConfig.mode !== "augment_context") {
        rawConfig.mode = DEFAULT_MODE;
        changes.push('defaulted plugins.entries.agentic-memory.config.mode to "capture_only"');
      }

      if (rawConfig.contextEngineId !== DEFAULT_CONTEXT_ENGINE_ID) {
        rawConfig.contextEngineId = DEFAULT_CONTEXT_ENGINE_ID;
        changes.push('defaulted plugins.entries.agentic-memory.config.contextEngineId to "agentic-memory"');
      }

      rawEntry.config = rawConfig;
      next.plugins.entries[PLUGIN_ID] = rawEntry;

      if (next.plugins.slots.contextEngine !== DEFAULT_CONTEXT_ENGINE_ID) {
        next.plugins.slots.contextEngine = DEFAULT_CONTEXT_ENGINE_ID;
        changes.push('switched plugins.slots.contextEngine to "agentic-memory" for capture-first turn ingestion');
      }

      return changes.length > 0 ? { config: next, changes } : null;
    });
  },
});
