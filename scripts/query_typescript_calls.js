#!/usr/bin/env node
"use strict";

/**
 * Batch TypeScript call analysis helper for Agentic Memory.
 *
 * This script reads one JSON request from stdin, uses the installed TypeScript
 * language service to resolve outgoing call hierarchy entries, and writes one
 * JSON response to stdout.
 *
 * Why this exists:
 * - Tree-sitter gives the Python ingestion pipeline reliable ownership
 *   boundaries for functions and methods.
 * - TypeScript's semantic engine is better suited to answering cross-file
 *   "what does this call resolve to?" questions for JS/TS code.
 * - Keeping the semantic resolver in Node lets Python stay focused on graph
 *   orchestration while still benefiting from the IDE-grade analysis stack.
 */

const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");

const SUPPORTED_EXTENSIONS = new Set([".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"]);
const SUPPORTED_CALL_KINDS = new Set(["function", "method"]);
const IGNORED_DIRECTORIES = new Set([
  ".git",
  ".next",
  ".venv",
  "__pycache__",
  "build",
  "coverage",
  "dist",
  "node_modules",
  "out",
  "venv",
]);

function normalizeRelPath(value) {
  return value.split(path.sep).join("/");
}

function isSupportedFile(filePath) {
  return SUPPORTED_EXTENSIONS.has(path.extname(filePath).toLowerCase());
}

function isPathInsideRoot(rootPath, candidatePath) {
  const relative = path.relative(rootPath, candidatePath);
  return relative !== "" && !relative.startsWith("..") && !path.isAbsolute(relative);
}

function readStdin() {
  return new Promise((resolve, reject) => {
    let buffer = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => {
      buffer += chunk;
    });
    process.stdin.on("end", () => resolve(buffer));
    process.stdin.on("error", reject);
  });
}

function compilerOptionsFallback() {
  return {
    allowJs: true,
    esModuleInterop: true,
    jsx: ts.JsxEmit.Preserve,
    module: ts.ModuleKind.ESNext,
    moduleResolution: ts.ModuleResolutionKind.Node10,
    noEmit: true,
    skipLibCheck: true,
    target: ts.ScriptTarget.ES2022,
  };
}

function scanRepoFiles(repoRoot) {
  const discovered = [];

  function walk(currentDir) {
    let entries;
    try {
      entries = fs.readdirSync(currentDir, { withFileTypes: true });
    } catch (error) {
      if (error && ["EACCES", "ENOENT", "EPERM"].includes(error.code)) {
        return;
      }
      throw error;
    }

    for (const entry of entries) {
      if (entry.isSymbolicLink()) {
        continue;
      }

      if (entry.isDirectory()) {
        if (IGNORED_DIRECTORIES.has(entry.name)) {
          continue;
        }
        walk(path.join(currentDir, entry.name));
        continue;
      }

      const absolutePath = path.join(currentDir, entry.name);
      if (isSupportedFile(absolutePath)) {
        discovered.push(path.resolve(absolutePath));
      }
    }
  }

  walk(repoRoot);
  return discovered;
}

function loadProjectContext(repoRoot, requestedAbsolutePaths) {
  const configPath =
    ts.findConfigFile(repoRoot, ts.sys.fileExists, "tsconfig.json") ||
    ts.findConfigFile(repoRoot, ts.sys.fileExists, "jsconfig.json");

  if (configPath) {
    const configFile = ts.readConfigFile(configPath, ts.sys.readFile);
    if (configFile.error) {
      throw new Error(ts.flattenDiagnosticMessageText(configFile.error.messageText, "\n"));
    }

    const parsed = ts.parseJsonConfigFileContent(
      configFile.config,
      ts.sys,
      path.dirname(configPath),
      undefined,
      configPath,
    );

    const fileSet = new Set(
      parsed.fileNames.filter((fileName) => isSupportedFile(fileName)).map((fileName) => path.resolve(fileName)),
    );
    for (const requestedPath of requestedAbsolutePaths) {
      fileSet.add(path.resolve(requestedPath));
    }

    return {
      compilerOptions: {
        ...parsed.options,
        allowJs: parsed.options.allowJs ?? true,
        noEmit: true,
        skipLibCheck: true,
      },
      diagnostics: [],
      fileNames: [...fileSet],
      projectFile: configPath,
    };
  }

  return {
    compilerOptions: compilerOptionsFallback(),
    diagnostics: [
      {
        kind: "missing_tsconfig",
        level: "info",
        message: "No tsconfig.json or jsconfig.json found. Falling back to repo scan.",
      },
    ],
    fileNames: [...new Set([...scanRepoFiles(repoRoot), ...requestedAbsolutePaths.map((filePath) => path.resolve(filePath))])],
    projectFile: null,
  };
}

function createLanguageService(repoRoot, fileNames, compilerOptions) {
  const versions = new Map(fileNames.map((fileName) => [path.resolve(fileName), "0"]));

  const host = {
    directoryExists: ts.sys.directoryExists,
    fileExists: ts.sys.fileExists,
    getCompilationSettings: () => compilerOptions,
    getCurrentDirectory: () => repoRoot,
    getDefaultLibFileName: (options) => ts.getDefaultLibFilePath(options),
    getDirectories: ts.sys.getDirectories,
    getScriptFileNames: () => [...versions.keys()],
    getScriptSnapshot: (fileName) => {
      const absolute = path.resolve(fileName);
      if (!fs.existsSync(absolute)) {
        return undefined;
      }
      return ts.ScriptSnapshot.fromString(fs.readFileSync(absolute, "utf8"));
    },
    getScriptVersion: (fileName) => versions.get(path.resolve(fileName)) ?? "0",
    readDirectory: ts.sys.readDirectory,
    readFile: ts.sys.readFile,
  };

  return ts.createLanguageService(host, ts.createDocumentRegistry());
}

function guessQualifiedName(item) {
  return item.containerName ? `${item.containerName}.${item.name}` : item.name;
}

function incrementCount(counter, key) {
  counter[key] = (counter[key] ?? 0) + 1;
}

function dedupeOutgoingCalls(outgoingCalls) {
  const seen = new Set();
  const deduped = [];

  for (const outgoingCall of outgoingCalls) {
    const key = [
      outgoingCall.path,
      outgoingCall.name,
      outgoingCall.kind ?? "",
      outgoingCall.container_name ?? "",
      outgoingCall.qualified_name_guess ?? "",
      String(outgoingCall.definition_line ?? ""),
      String(outgoingCall.definition_column ?? ""),
    ].join("::");

    if (seen.has(key)) {
      continue;
    }

    seen.add(key);
    deduped.push(outgoingCall);
  }

  return deduped;
}

function definitionLocation(program, absoluteTargetPath, target) {
  const sourceFile = program?.getSourceFile(absoluteTargetPath);
  const span = target?.selectionSpan ?? target?.span;
  if (!sourceFile || !span || typeof span.start !== "number") {
    return {
      definitionLine: null,
      definitionColumn: null,
    };
  }

  const point = ts.getLineAndCharacterOfPosition(sourceFile, span.start);
  return {
    definitionLine: point.line + 1,
    definitionColumn: point.character + 1,
  };
}

function buildOutgoingCalls({ repoRoot, rawOutgoingCalls, program, dropReasonCounts }) {
  const outgoingCalls = [];

  for (const callRow of rawOutgoingCalls) {
    const target = callRow.to;
    if (!target || !target.file) {
      incrementCount(dropReasonCounts, "missing_target");
      continue;
    }

    if (!SUPPORTED_CALL_KINDS.has(target.kind)) {
      incrementCount(dropReasonCounts, "unsupported_target_kind");
      continue;
    }

    const absoluteTargetPath = path.resolve(target.file);
    if (!isPathInsideRoot(repoRoot, absoluteTargetPath)) {
      incrementCount(dropReasonCounts, "external_target");
      continue;
    }

    if (!isSupportedFile(absoluteTargetPath)) {
      incrementCount(dropReasonCounts, "unsupported_target_extension");
      continue;
    }

    const { definitionLine, definitionColumn } = definitionLocation(
      program,
      absoluteTargetPath,
      target,
    );

    outgoingCalls.push({
      path: normalizeRelPath(path.relative(repoRoot, absoluteTargetPath)),
      name: target.name,
      kind: target.kind,
      container_name: target.containerName ?? null,
      qualified_name_guess: guessQualifiedName(target),
      definition_line: definitionLine,
      definition_column: definitionColumn,
    });
  }

  return dedupeOutgoingCalls(outgoingCalls);
}

function analyzeFile({ languageService, repoRoot, fileRequest, globalDiagnostics }) {
  const absoluteFilePath = path.resolve(repoRoot, fileRequest.path);
  const program = languageService.getProgram();
  const diagnostics = [...globalDiagnostics];

  if (!program) {
    diagnostics.push({
      kind: "missing_program",
      level: "error",
      message: "TypeScript language service could not create a program.",
    });
    return {
      path: fileRequest.path,
      functions: [],
      diagnostics,
    };
  }

  const sourceFile = program.getSourceFile(absoluteFilePath);
  if (!sourceFile) {
    diagnostics.push({
      kind: "missing_source_file",
      level: "warning",
      message: `File is not part of the analyzed TypeScript program: ${fileRequest.path}`,
    });
    return {
      path: fileRequest.path,
      functions: [],
      diagnostics,
    };
  }

  const functions = [];
  const dropReasonCounts = {};
  for (const functionRequest of fileRequest.functions ?? []) {
    const nameLine = Number(functionRequest.name_line ?? 0);
    const nameColumn = Number(functionRequest.name_column ?? 0);
    if (!nameLine || !nameColumn) {
      diagnostics.push({
        kind: "missing_name_position",
        level: "warning",
        message: `Function ${functionRequest.qualified_name ?? functionRequest.name ?? "<unknown>"} is missing name coordinates.`,
      });
      continue;
    }

    const position = ts.getPositionOfLineAndCharacter(
      sourceFile,
      Math.max(nameLine - 1, 0),
      Math.max(nameColumn - 1, 0),
    );

    const prepared = languageService.prepareCallHierarchy(absoluteFilePath, position);
    if (!prepared) {
      diagnostics.push({
        kind: "prepare_call_hierarchy_failed",
        level: "info",
        message: `No call-hierarchy target found for ${functionRequest.qualified_name ?? functionRequest.name ?? "<unknown>"}.`,
      });
      continue;
    }

    const outgoingCalls = languageService.provideCallHierarchyOutgoingCalls(
      absoluteFilePath,
      position,
    );

    functions.push({
      qualified_name: functionRequest.qualified_name ?? functionRequest.name ?? "",
      name: functionRequest.name ?? functionRequest.qualified_name ?? "",
      outgoing: buildOutgoingCalls({
        repoRoot,
        rawOutgoingCalls: outgoingCalls ?? [],
        program,
        dropReasonCounts,
      }),
    });
  }

  for (const [reason, count] of Object.entries(dropReasonCounts).sort(([a], [b]) =>
    a.localeCompare(b),
  )) {
    diagnostics.push({
      kind: "drop_reason_count",
      level: "info",
      reason,
      count,
    });
  }

  return {
    path: fileRequest.path,
    functions,
    diagnostics,
    drop_reason_counts: dropReasonCounts,
  };
}

async function main() {
  const rawInput = await readStdin();
  const request = JSON.parse(rawInput || "{}");

  if (!request.repoRoot || !Array.isArray(request.files)) {
    throw new Error("Expected JSON payload with repoRoot and files.");
  }

  const repoRoot = path.resolve(String(request.repoRoot));
  const requestedPaths = request.files.map((fileRow) => path.resolve(repoRoot, fileRow.path));
  const projectContext = loadProjectContext(repoRoot, requestedPaths);
  const languageService = createLanguageService(
    repoRoot,
    projectContext.fileNames,
    projectContext.compilerOptions,
  );

  const files = request.files.map((fileRequest) =>
    analyzeFile({
      languageService,
      repoRoot,
      fileRequest,
      globalDiagnostics: projectContext.diagnostics,
    }),
  );

  process.stdout.write(
    JSON.stringify({
      ok: true,
      files,
      project_file: projectContext.projectFile,
    }),
  );
}

main().catch((error) => {
  process.stdout.write(
    JSON.stringify({
      ok: false,
      error: error instanceof Error ? error.message : String(error),
    }),
  );
  process.exitCode = 1;
});
