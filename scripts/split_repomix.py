"""Split repomix-output.md into cleaner NotebookLM sources.

Runs repomix to get a fresh snapshot of the repo, then splits it into
topic-bounded files that are easier for NotebookLM to ground against.
The splitter adds a second-stage skip/dedupe guard so stale generated
artifacts from a reused snapshot do not leak into the output.

Default output files (docs/notebooklm/):
    00_index.md                  — index of generated NotebookLM sources
    01_reference.md              — stable repo docs and published guidance
    02_project_state.md          — current project state and codebase maps
    03_planning_research.md      — research notes, execution logs, handoffs
    04_planning_phases_01_05.md  — early implementation history
    05_planning_phases_06_plus.md — later implementation history
    06_agentic_memory.md         — src/agentic_memory/
    07_codememory.md             — src/codememory/
    08_server_and_clients.md     — src/am_server/, packages/, desktop_shell/
    09_tests_memory_core.md      — memory-core and MCP-facing tests
    10_tests_product_surfaces.md — am_server/openclaw/system-flow tests
    11_infra.md                  — scripts, config, CI, benchmarks, tooling

Usage:
    python scripts/split_repomix.py              # regenerates repomix snapshot first
    python scripts/split_repomix.py --no-repomix # skip repomix, reuse existing file
    python scripts/split_repomix.py --input path/to/repomix-output.md
    python scripts/split_repomix.py --max-words 400000
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from fnmatch import fnmatch
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = REPO_ROOT / "repomix-output.md"
OUTPUT_DIR = REPO_ROOT / "docs" / "notebooklm"

# NotebookLM limit per uploaded source. Set conservatively below the stated
# 500,000-word ceiling to leave headroom for the preamble we add.
DEFAULT_MAX_WORDS = 450_000

# Directories that can balloon to huge sizes and should never be in the snapshot.
REPOMIX_IGNORE = [
    ".venv",
    ".venv/**",
    "venv",
    "venv/**",
    "node_modules",
    "node_modules/**",
    "dist",
    "dist/**",
    "build",
    "build/**",
    "*.egg-info",
    "*.egg-info/**",
    "__pycache__",
    "__pycache__/**",
    ".pytest_cache",
    ".pytest_cache/**",
    "htmlcov",
    "htmlcov/**",
    "packages/am-temporal-kg/generated-bindings",
    "packages/am-temporal-kg/generated-bindings/**",
    "docs/notebooklm",
    "docs/notebooklm/**",
]

# Secondary guard during split time. This protects against stale artifacts in a
# reused repomix snapshot, which the repomix ignore list alone cannot fix.
SECONDARY_SKIP_PATTERNS = [
    *REPOMIX_IGNORE,
    "docs/notebooklm_context.md",
    "repomix-output.md",
]

# Ordered list of (key, label, description). Order determines output filename
# numbering and the order buckets are presented in the generated index.
SPLITS: list[tuple[str, str, str]] = [
    (
        "01_reference",
        "Reference Docs",
        "Stable repo documentation and published guidance: docs/, examples/, "
        "skills/, root READMEs/specs, and .github workflow docs. Use this for "
        "the current documented shape of the project.",
    ),
    (
        "02_project_state",
        "Project State & Codebase Maps",
        "High-signal planning state: .planning/PROJECT, ROADMAP, STATE, PRDs, "
        "config, and .planning/codebase/ maps. This is the best concise view of "
        "what the repo is trying to do right now.",
    ),
    (
        "03_planning_research",
        "Planning Research & Execution Notes",
        "Supporting research notes, execution logs, handoffs, and .claude plans. "
        "Useful historical context, but not authoritative behavior.",
    ),
    (
        "04_planning_phases_01_05",
        "Planning History: Phases 01-05",
        "Early implementation history for phases 01-05. Useful for original "
        "design decisions and superseded reasoning.",
    ),
    (
        "05_planning_phases_06_plus",
        "Planning History: Phases 06+",
        "Later implementation history for phases 06 onward. Use when you need "
        "phase-specific rationale or execution detail.",
    ),
    (
        "06_agentic_memory",
        "agentic_memory Package",
        "Full source for src/agentic_memory/ — the primary memory engine, "
        "retrieval logic, ingestion, temporal bridge, MCP tools, and CLI.",
    ),
    (
        "07_codememory",
        "codememory Package",
        "Full source for src/codememory/ — the parallel code-memory subsystem.",
    ),
    (
        "08_server_and_clients",
        "Server & Client Surfaces",
        "src/am_server/, packages/, and desktop_shell/. This is the HTTP/API "
        "surface area plus browser, dashboard, proxy, and integration clients.",
    ),
    (
        "09_tests_memory_core",
        "Tests: Memory Core & MCP",
        "Unit and subsystem tests for agentic_memory/codememory internals and "
        "the MCP-facing memory interfaces.",
    ),
    (
        "10_tests_product_surfaces",
        "Tests: Product Surfaces & System Flows",
        "am_server, OpenClaw, integration, e2e, load, and chaos tests. This is "
        "the best source for external contracts and end-to-end behavior.",
    ),
    (
        "11_infra",
        "Infrastructure, Tooling & Config",
        "Scripts, CI, config, benchmarks, docker, and root operational files "
        "that do not belong to a product or test subsystem.",
    ),
]

SPLIT_KEYS = [key for key, _, _ in SPLITS]
SPLIT_META = {key: {"label": label, "description": desc} for key, label, desc in SPLITS}

REFERENCE_ROOT_FILES = {
    "README.md",
    "SPEC.md",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "GIT-INTEGRATION-SPEC.md",
    "SPEC-browser-extension-and-ACP-proxy.md",
    "GRAPHRAG_README.md",
    "DOCUMENTATION_SUMMARY.md",
    "4-stage-ingestion-with-prep.md",
    "TODO.md",
    "TODO-high-value-feature-ideas.md",
}

PROJECT_STATE_ROOT_FILES = {
    ".planning/PROJECT.md",
    ".planning/ROADMAP.md",
    ".planning/STATE.md",
    ".planning/config.json",
}

PROJECT_STATE_PREFIXES = (
    ".planning/codebase/",
)

PLANNING_RESEARCH_PREFIXES = (
    ".planning/research/",
    ".planning/execution/",
    ".planning/execution-publication/",
    ".claude/",
)

PRODUCT_SURFACE_TEST_PREFIXES = (
    "tests/chaos/",
    "tests/e2e/",
    "tests/integration/",
    "tests/load/",
)

PRODUCT_SURFACE_TEST_MARKERS = (
    "openclaw",
    "am_server",
    "product_state",
)


def normalize_repo_path(fname: str) -> str:
    """Normalize repomix paths to stable forward-slash repo-relative paths."""

    normalized = fname.replace("\\", "/").strip()
    if normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized.startswith("/"):
        normalized = normalized[1:]
    return normalized


def matches_any(path: str, patterns: list[str]) -> bool:
    """Return True when a normalized path matches any fnmatch pattern."""

    return any(path == pattern or fnmatch(path, pattern) for pattern in patterns)


def should_skip_file(path: str) -> bool:
    """Return True when a normalized path should be dropped from output."""

    return matches_any(path, SECONDARY_SKIP_PATTERNS)


def is_project_state_file(path: str) -> bool:
    """Return True for current-state planning/docs files."""

    if path in PROJECT_STATE_ROOT_FILES:
        return True
    if any(path.startswith(prefix) for prefix in PROJECT_STATE_PREFIXES):
        return True
    if path.startswith(".planning/PRD"):
        return True
    return False


def is_product_surface_test(path: str) -> bool:
    """Return True for tests that describe HTTP/product/system surfaces."""

    if any(path.startswith(prefix) for prefix in PRODUCT_SURFACE_TEST_PREFIXES):
        return True
    filename = path.rsplit("/", 1)[-1].lower()
    stem = filename.removesuffix(".py")
    return any(marker in stem for marker in PRODUCT_SURFACE_TEST_MARKERS)


def categorize(fname: str) -> str:
    """Return the split key for a given normalized file path."""

    # --- 01: Stable reference docs ---
    if fname.startswith("docs/") or fname.startswith("examples/") or fname.startswith("skills/"):
        return "01_reference"
    if fname.startswith(".github/") or fname in REFERENCE_ROOT_FILES:
        return "01_reference"

    # --- 02: Current project state and codebase maps ---
    if is_project_state_file(fname):
        return "02_project_state"

    # --- 03: Research, execution logs, handoffs, scratch planning ---
    if any(fname.startswith(prefix) for prefix in PLANNING_RESEARCH_PREFIXES):
        return "03_planning_research"

    # --- 04 / 05: Phase histories ---
    if fname.startswith(".planning/phases/"):
        phase_dir = fname.split("/", 3)[2]
        phase_prefix = phase_dir.split("-", 1)[0]
        if phase_prefix.isdigit() and int(phase_prefix) <= 5:
            return "04_planning_phases_01_05"
        return "05_planning_phases_06_plus"

    # --- 06 / 07 / 08: Code buckets ---
    if fname.startswith("src/agentic_memory/"):
        return "06_agentic_memory"
    if fname.startswith("src/codememory/"):
        return "07_codememory"
    if fname.startswith("src/am_server/") or fname.startswith("packages/") or fname.startswith("desktop_shell/"):
        return "08_server_and_clients"

    # --- 09 / 10: Tests, kept separate from package source ---
    if fname.startswith("tests/"):
        if is_product_surface_test(fname):
            return "10_tests_product_surfaces"
        return "09_tests_memory_core"

    # --- 11: Everything else (scripts, config, tooling, root files) ---
    return "11_infra"


def count_words(lines: list[str]) -> int:
    """Count whitespace-delimited words across a list of lines."""

    return sum(len(line.split()) for line in lines)


def run_repomix(output_path: Path) -> None:
    """Run repomix to produce a fresh snapshot of the repo."""

    repomix_bin = shutil.which("repomix")
    if repomix_bin is None:
        raise SystemExit(
            "Error: repomix not found on PATH.\n"
            "Install it with:  npm install -g repomix\n"
            "Or rerun with:    --no-repomix  to use an existing file."
        )

    with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        ignore_str = ",".join(REPOMIX_IGNORE)
        print(f"Running repomix -> {output_path.name} ...")
        result = subprocess.run(
            [repomix_bin, "--output", str(tmp_path), "--ignore", ignore_str],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(result.stderr, file=sys.stderr)
            raise SystemExit(f"repomix failed (exit {result.returncode})")
        shutil.move(str(tmp_path), str(output_path))
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    print(f"  repomix done. {output_path.stat().st_size / 1024:.0f} KB written.\n")


def iter_files(lines: list[str]) -> list[tuple[int, str]]:
    """Detect repomix format and return [(line_index, filename)].

    Markdown snapshots wrap each file body in a fenced code block. Some repo
    files also contain literal "## File:" lines, so we only treat a markdown
    header as a real file boundary when it appears outside fenced code blocks.
    """

    xml_starts = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('<file path="') and stripped.endswith('">'):
            xml_starts.append((i, stripped[len('<file path="'):-2]))
    if xml_starts:
        return xml_starts

    md_starts = []
    fence_len: int | None = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            tick_count = len(stripped) - len(stripped.lstrip("`"))
            if fence_len is None:
                fence_len = tick_count
            elif tick_count >= fence_len:
                fence_len = None
            continue

        if fence_len is None and line.startswith("## File: "):
            md_starts.append((i, line[9:].strip()))
    return md_starts


def file_block_count(content_lines: list[str]) -> int:
    """Count how many file blocks are present in a bucket."""

    return sum(
        1
        for line in content_lines
        if line.startswith("## File: ") or line.strip().startswith('<file path="')
    )


def subdivide(key: str, content_lines: list[str], max_words: int) -> list[tuple[str, list[str]]]:
    """Split a bucket that exceeds max_words into equal halves by file count."""

    if count_words(content_lines) <= max_words:
        return [(key, content_lines)]

    block_starts = [
        i for i, line in enumerate(content_lines)
        if line.startswith("## File: ") or line.strip().startswith('<file path="')
    ]

    if len(block_starts) <= 1:
        print(f"  ! {key}: single file exceeds limit - cannot subdivide further")
        return [(key, content_lines)]

    mid = len(block_starts) // 2
    split_line = block_starts[mid]
    part_a = content_lines[:split_line]
    part_b = content_lines[split_line:]

    results: list[tuple[str, list[str]]] = []
    for suffix, part in [("a", part_a), ("b", part_b)]:
        results.extend(subdivide(f"{key}{suffix}", part, max_words))
    return results


def cleanup_generated_outputs(output_dir: Path) -> None:
    """Remove old numbered NotebookLM outputs before writing new ones."""

    if not output_dir.exists():
        return

    for path in output_dir.glob("[0-9][0-9]_*.md"):
        path.unlink(missing_ok=True)
    (output_dir / "00_index.md").unlink(missing_ok=True)


def write_index(
    output_dir: Path,
    input_path: Path,
    final_parts: list[tuple[str, str, list[str]]],
    skipped_paths: list[str],
    duplicate_paths: list[str],
    max_words: int,
) -> None:
    """Write a small index that explains the generated source set."""

    lines = [
        "# NotebookLM Source Index",
        "",
        "*Generated by `scripts/split_repomix.py`*",
        "",
        f"Input snapshot: `{input_path.name}`",
        "",
        "This folder is a retrieval-oriented slice of the repo. Buckets are scoped to",
        "stable docs, planning state, code subsystems, tests, and infrastructure so",
        "NotebookLM citations are more precise than a single monolithic repomix dump.",
        "",
        "## Generated Sources",
        "",
    ]

    for part_key, base_key, content_lines in final_parts:
        meta = SPLIT_META[base_key]
        lines.append(f"- `{part_key}.md` — {meta['label']} ({file_block_count(content_lines)} files, {count_words(content_lines):,} words)")

    lines.extend(
        [
            "",
            "## Guards Applied",
            "",
            f"- Secondary skip filter dropped {len(skipped_paths)} snapshot artifact(s) matching generated-output or ignored-path patterns.",
            f"- Duplicate-path filter dropped {len(duplicate_paths)} repeated file block(s).",
            f"- Auto-subdivision target: {max_words:,} words per source.",
        ]
    )

    if skipped_paths:
        lines.extend(
            [
                "",
                "Skipped examples:",
                *[f"- `{path}`" for path in skipped_paths[:10]],
            ]
        )

    if duplicate_paths:
        lines.extend(
            [
                "",
                "Duplicate examples:",
                *[f"- `{path}`" for path in duplicate_paths[:10]],
            ]
        )

    (output_dir / "00_index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def split(input_path: Path, output_dir: Path, max_words: int) -> None:
    """Split repomix output into topic-bounded NotebookLM sources."""

    print(f"Reading {input_path} ({input_path.stat().st_size / 1024:.0f} KB)")

    with input_path.open("r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    file_starts = iter_files(lines)
    if not file_starts:
        raise SystemExit("Error: could not find any file entries in repomix output.")

    fmt = "xml" if lines[file_starts[0][0]].strip().startswith("<file") else "markdown"
    print(f"  Detected format: {fmt} ({len(file_starts)} file blocks)\n")

    buckets: dict[str, list[str]] = {key: [] for key in SPLIT_KEYS}
    seen_paths: set[str] = set()
    skipped_paths: list[str] = []
    duplicate_paths: list[str] = []
    kept_blocks = 0

    for idx, (start, raw_name) in enumerate(file_starts):
        end = file_starts[idx + 1][0] if idx + 1 < len(file_starts) else len(lines)
        fname = normalize_repo_path(raw_name)

        if should_skip_file(fname):
            skipped_paths.append(fname)
            continue
        if fname in seen_paths:
            duplicate_paths.append(fname)
            continue

        seen_paths.add(fname)
        buckets[categorize(fname)].extend(lines[start:end])
        kept_blocks += 1

    print(f"  Kept {kept_blocks} unique file blocks")
    print(f"  Skipped {len(skipped_paths)} ignored/generated artifact blocks")
    print(f"  Dropped {len(duplicate_paths)} duplicate path blocks\n")

    final_parts: list[tuple[str, str, list[str]]] = []
    for key in SPLIT_KEYS:
        if not buckets[key]:
            continue
        for part_key, part_lines in subdivide(key, buckets[key], max_words):
            final_parts.append((part_key, key, part_lines))

    output_dir.mkdir(parents=True, exist_ok=True)
    cleanup_generated_outputs(output_dir)

    over_limit: list[str] = []
    for part_key, base_key, content_lines in final_parts:
        out_path = output_dir / f"{part_key}.md"
        meta = SPLIT_META[base_key]
        words = count_words(content_lines)
        files = file_block_count(content_lines)
        if words > max_words:
            over_limit.append(part_key)

        with out_path.open("w", encoding="utf-8") as f:
            suffix = f" ({part_key})" if part_key != base_key else ""
            f.write(f"# {meta['label']}{suffix}\n\n")
            f.write("*Split from repomix-output.md by `scripts/split_repomix.py`*\n\n")
            f.write(f"{meta['description']}\n\n")
            f.write("---\n\n")
            f.writelines(content_lines)

        size_kb = sum(len(line.encode()) for line in content_lines) / 1024
        status = " ! OVER LIMIT" if words > max_words else ""
        print(f"  {out_path.name:<40} {size_kb:>7.0f} KB {words:>8,} words ({files} files){status}")

    write_index(output_dir, input_path, final_parts, skipped_paths, duplicate_paths, max_words)

    total_kb = sum(sum(len(line.encode()) for line in part_lines) / 1024 for _, _, part_lines in final_parts)
    print(f"\n  {'TOTAL':<40} {total_kb:>7.0f} KB")

    if over_limit:
        print(f"\n  ! These files still exceed {max_words:,} words: {over_limit}")
        print("    Tighten ignore patterns or increase --max-words if this is expected.")
    else:
        print(f"\nDone. Files written to: {output_dir}")


def main() -> None:
    """CLI entry point."""

    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Path to repomix-output.md (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--no-repomix",
        action="store_true",
        help="Skip running repomix and reuse the existing snapshot file",
    )
    parser.add_argument(
        "--max-words",
        type=int,
        default=DEFAULT_MAX_WORDS,
        help=f"Per-file word limit before auto-subdivision (default: {DEFAULT_MAX_WORDS:,})",
    )
    args = parser.parse_args()

    if not args.no_repomix:
        run_repomix(args.input)
    elif not args.input.exists():
        raise SystemExit(
            f"Error: input file not found: {args.input}\n"
            "Remove --no-repomix to generate it automatically."
        )

    split(args.input, OUTPUT_DIR, args.max_words)


if __name__ == "__main__":
    main()
