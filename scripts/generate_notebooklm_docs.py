"""Generate docs/notebooklm/ — a directory of labeled Markdown files for NotebookLM.

This script introspects every Python package and TypeScript worker package in the
agentic-memory repository and writes a set of well-structured, labeled Markdown
documents that NotebookLM can ingest as individual sources for AI-assisted analysis.

Why split into multiple files instead of one large document:
    NotebookLM works best with focused, well-scoped sources. Splitting by logical
    boundary (static docs, each Python package, frontend packages) lets NotebookLM
    attribute context more accurately and avoids hitting per-source size limits.

Output files (all in docs/notebooklm/):
    00_index.md                — TOC and project overview (always written first)
    01_project_overview.md     — README + all docs/*.md static content
    02_agentic_memory.md       — agentic_memory Python package
    03_codememory.md           — codememory Python package
    04_am_server.md            — am_server Python package
    05_am_proxy.md             — am_proxy package (optional — skipped if absent)
    06_frontend_packages.md    — all TypeScript worker packages (am-temporal-kg,
                                  am-sync-neo4j, am-openclaw)

What gets included in Python package files:
    - Module docstrings (purpose, role, dependencies).
    - Class and method docstrings + source code.
    - Module-level function docstrings + source code.
    - Source code is emitted even when docstrings are absent ("hardening") so
      NotebookLM sees actual logic regardless of documentation coverage.

Usage:
    python scripts/generate_notebooklm_docs.py
    python scripts/generate_notebooklm_docs.py --dry-run   # print manifest only

Project context:
    agentic-memory uses a Hatch src/ layout, so all Python packages live under
    src/ rather than the repository root. This script adds both REPO_ROOT and
    REPO_ROOT/src to sys.path so that package imports resolve correctly.

Dependencies:
    - Standard library only (os, sys, pkgutil, importlib, inspect, pathlib).
    - No third-party packages required to run this script.
"""

from __future__ import annotations

import importlib
import inspect
import os
import pkgutil
import sys
from pathlib import Path
from typing import IO

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

# REPO_ROOT is two levels up from this script (scripts/ → repo root).
REPO_ROOT: Path = Path(__file__).resolve().parents[1]
SRC_DIR: Path = REPO_ROOT / "src"

# Register both paths: src/ for the three main packages, root for any root-level
# imports (e.g., top-level utility modules that live outside src/).
for _p in [str(SRC_DIR), str(REPO_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# am-proxy lives in its own packages/ sub-tree with its own src/ layout.
AM_PROXY_SRC: Path = REPO_ROOT / "packages" / "am-proxy" / "src"
if AM_PROXY_SRC.exists() and str(AM_PROXY_SRC) not in sys.path:
    sys.path.insert(0, str(AM_PROXY_SRC))

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Python packages to document (always present).
PACKAGES: list[str] = ["agentic_memory", "codememory", "am_server"]

# Python packages to document only when importable (graceful skip on absence).
OPTIONAL_PACKAGES: list[str] = ["am_proxy"]

# TypeScript worker packages relative to REPO_ROOT.
FRONTEND_PROJECTS: list[str] = [
    "packages/am-temporal-kg",
    "packages/am-sync-neo4j",
    "packages/am-openclaw",
]

# File extensions treated as frontend source files.
FRONTEND_EXTENSIONS: tuple[str, ...] = (".ts", ".tsx", ".js", ".mts", ".css")

# Static Markdown paths relative to REPO_ROOT (docs/*.md is globbed dynamically).
STATIC_DOCS: list[str] = ["README.md"]

# Output directory — all generated files go here.
OUTPUT_DIR: Path = REPO_ROOT / "docs" / "notebooklm"

# Maximum size for a static doc to be inlined (bytes). Larger files are skipped
# with a note so the output file doesn't balloon uncontrollably.
MAX_STATIC_DOC_BYTES: int = 500 * 1024  # 500 KB

# ---------------------------------------------------------------------------
# Third-party / stdlib exclusion lists
# ---------------------------------------------------------------------------

THIRD_PARTY_EXCLUDE: tuple[str, ...] = (
    "pydantic",
    "pydantic_core",
    "builtins",
    "typing",
    "typing_extensions",
    "http",
    "email",
    "json",
    "dataclasses",
    "abc",
    "collections",
    "httpx",
    "fastapi",
    "starlette",
    "uvicorn",
)

# Pydantic BaseModel auto-generated method names — skip these to reduce noise.
BASEMODEL_METHODS: frozenset[str] = frozenset(
    {
        "model_validate",
        "model_validate_json",
        "model_dump",
        "model_dump_json",
        "model_copy",
        "model_construct",
        "model_json_schema",
        "model_fields",
        "model_computed_fields",
        "model_config",
        "copy",
        "dict",
        "json",
        "parse_obj",
        "parse_raw",
        "parse_file",
        "schema",
        "schema_json",
        "construct",
        "update_forward_refs",
        "__get_validators__",
        "__modify_schema__",
    }
)

# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def get_docstring(obj: object) -> str:
    """Return the cleaned docstring for any inspectable object, or empty string.

    Args:
        obj: Any Python object (module, class, function, method).

    Returns:
        The docstring with leading/trailing whitespace normalised by
        ``inspect.getdoc``, or ``""`` if the object has no docstring.
    """
    return inspect.getdoc(obj) or ""


# ---------------------------------------------------------------------------
# Python package documentation
# ---------------------------------------------------------------------------


def document_module(module_name: str, out_file: IO[str]) -> None:
    """Introspect a single Python module and write its documentation section.

    For each module this function emits:
    - The module-level docstring (if any).
    - A subsection per public class, including class docstring, and each public
      method's docstring and source code.
    - A subsection per public module-level function, including docstring and
      source code.

    Hardening: source code is emitted even when a docstring is absent. This
    ensures NotebookLM sees actual logic in under-documented modules and can
    reason about the implementation regardless of doc coverage.

    Args:
        module_name: Fully qualified Python module name (e.g. ``"am_server.app"``).
        out_file: Open file handle to write Markdown content into.
    """
    try:
        mod = importlib.import_module(module_name)
    except Exception as exc:  # noqa: BLE001
        print(f"  [skip] Error importing {module_name}: {exc}")
        return

    has_content = False
    module_content: list[str] = []

    # --- Module docstring ---
    doc = get_docstring(mod)
    if doc:
        module_content.append(f"{doc}\n\n")
        has_content = True

    # --- Classes ---
    for name, obj in inspect.getmembers(mod, inspect.isclass):
        # Only document classes defined in this exact module (not re-exports).
        if obj.__module__ != module_name:
            continue
        if any(obj.__module__.startswith(pkg) for pkg in THIRD_PARTY_EXCLUDE):
            continue

        class_content: list[str] = [f"### Class: `{name}`\n\n"]
        doc = get_docstring(obj)
        if doc:
            class_content.append(f"{doc}\n\n")

        method_count = 0
        for m_name, m_obj in inspect.getmembers(obj, inspect.isroutine):
            # Skip private/dunder methods except __init__ (constructor is useful).
            if m_name.startswith("__") and m_name != "__init__":
                continue
            if m_name.startswith("_") and m_name != "__init__":
                continue
            if m_name in BASEMODEL_METHODS:
                continue

            doc = get_docstring(m_obj)

            # Hardening: always try to get source, even if doc is absent.
            try:
                source = inspect.getsource(m_obj)
            except (TypeError, OSError):
                source = None

            if doc or source:
                class_content.append(f"#### Method: `{m_name}`\n\n")
                if doc:
                    class_content.append(f"```\n{doc}\n```\n\n")
                if source:
                    class_content.append(
                        f"**Source:**\n\n```python\n{source}\n```\n\n"
                    )
                method_count += 1

        if method_count > 0 or get_docstring(obj):
            module_content.extend(class_content)
            has_content = True

    # --- Module-level functions ---
    for name, obj in inspect.getmembers(mod, inspect.isroutine):
        if obj.__module__ != module_name:
            continue
        if any(obj.__module__.startswith(pkg) for pkg in THIRD_PARTY_EXCLUDE):
            continue

        module_content.append(f"### Function: `{name}`\n\n")
        doc = get_docstring(obj)
        if doc:
            module_content.append(f"```\n{doc}\n```\n\n")

        # Hardening: emit source even when docstring is empty.
        try:
            source = inspect.getsource(obj)
            module_content.append(f"**Source:**\n\n```python\n{source}\n```\n\n")
        except (TypeError, OSError):
            pass

        has_content = True

    if has_content:
        out_file.write(f"\n## Module: `{module_name}`\n\n")
        out_file.writelines(module_content)


def document_package(package_name: str, out_path: Path) -> int:
    """Walk all sub-modules of a Python package and write a dedicated output file.

    Each package gets its own Markdown file so NotebookLM can treat it as an
    independent, focused source. Uses ``pkgutil.walk_packages`` to discover every
    module in the package tree.

    Args:
        package_name: Top-level package name (e.g. ``"agentic_memory"``).
        out_path: Path to the output ``.md`` file to create for this package.

    Returns:
        File size in bytes of the written output file, or 0 on import failure.
    """
    print(f"  Documenting package: {package_name}  →  {out_path.name}")

    with out_path.open("w", encoding="utf-8") as f:
        f.write(f"# Package: `{package_name}`\n\n")
        f.write(
            f"*Auto-generated by `scripts/generate_notebooklm_docs.py`. "
            f"Part of the agentic-memory full-stack context for NotebookLM.*\n\n"
        )
        f.write("---\n\n")

        try:
            package = importlib.import_module(package_name)
        except Exception as exc:  # noqa: BLE001
            f.write(f"*Could not import package: {exc}*\n\n")
            return out_path.stat().st_size

        # Document the package __init__ itself first.
        document_module(package_name, f)

        # Walk the full module tree.
        package_path = getattr(package, "__path__", [])
        for _finder, module_name, _is_pkg in pkgutil.walk_packages(
            path=package_path,
            prefix=package_name + ".",
            onerror=lambda name: print(f"    [walk error] {name}"),
        ):
            document_module(module_name, f)

    return out_path.stat().st_size


# ---------------------------------------------------------------------------
# Frontend (TypeScript) documentation
# ---------------------------------------------------------------------------


def document_frontend(projects: list[Path], out_path: Path) -> int:
    """Walk all TypeScript worker packages and write a single combined output file.

    All frontend projects are combined into one file (they are tightly coupled
    in this repo and collectively form the TypeScript layer of the stack). Each
    project is a top-level section; each source file is a subsection with a
    fenced code block.

    Args:
        projects: List of absolute paths to frontend package directories.
        out_path: Path to the output ``.md`` file to create.

    Returns:
        File size in bytes of the written output file.
    """
    print(f"  Documenting frontend packages  →  {out_path.name}")

    SKIP_DIRS = {"node_modules", "dist", ".turbo", "__pycache__"}

    with out_path.open("w", encoding="utf-8") as f:
        f.write("# Frontend TypeScript Packages\n\n")
        f.write(
            "*Auto-generated by `scripts/generate_notebooklm_docs.py`. "
            "Part of the agentic-memory full-stack context for NotebookLM.*\n\n"
        )
        f.write(
            "This file covers all TypeScript worker packages in the agentic-memory "
            "monorepo: the Temporal KG worker, the Neo4j sync worker, and the "
            "OpenClaw plugin runtime.\n\n"
        )
        f.write("---\n\n")

        for project_path in projects:
            if not project_path.exists():
                print(f"  [skip] Frontend project not found: {project_path}")
                continue

            print(f"    {project_path.name}")
            f.write(f"\n# Package: `{project_path.name}`\n\n")

            for root, dirs, files in os.walk(project_path):
                dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

                for filename in sorted(files):
                    if not filename.endswith(FRONTEND_EXTENSIONS):
                        continue

                    file_path = Path(root) / filename
                    relative = file_path.relative_to(project_path)
                    suffix = file_path.suffix.lstrip(".")
                    lang = "typescript" if suffix in ("ts", "tsx", "mts") else suffix

                    try:
                        content = file_path.read_text(encoding="utf-8", errors="replace")
                    except OSError as exc:
                        f.write(f"*Could not read {relative}: {exc}*\n\n")
                        continue

                    f.write(f"## File: `{relative}`\n\n")
                    f.write(f"```{lang}\n{content}\n```\n\n")

    return out_path.stat().st_size


# ---------------------------------------------------------------------------
# Static documentation
# ---------------------------------------------------------------------------


def write_static_docs(out_path: Path) -> int:
    """Write README.md and all docs/*.md files into a single project overview file.

    Static docs are placed in their own file so NotebookLM ingests project-level
    context (architecture, setup, API reference) as a distinct, focused source
    before encountering raw code in subsequent files.

    Files larger than MAX_STATIC_DOC_BYTES are skipped with a note to prevent
    the output from ballooning.

    Args:
        out_path: Path to the output ``.md`` file to create.

    Returns:
        File size in bytes of the written output file.
    """
    print(f"  Writing static docs  →  {out_path.name}")

    with out_path.open("w", encoding="utf-8") as f:
        f.write("# Project Overview: Agentic Memory\n\n")
        f.write(
            "*Auto-generated by `scripts/generate_notebooklm_docs.py`. "
            "Part of the agentic-memory full-stack context for NotebookLM.*\n\n"
        )
        f.write(
            "This file aggregates README and static documentation files. "
            "Read this first for project purpose, architecture, and setup context.\n\n"
        )
        f.write("---\n\n")

        candidates: list[Path] = []

        for rel in STATIC_DOCS:
            p = REPO_ROOT / rel
            if p.exists():
                candidates.append(p)

        docs_dir = REPO_ROOT / "docs"
        if docs_dir.exists():
            for md_file in sorted(docs_dir.rglob("*.md")):
                # Skip any file inside the output directory to avoid self-reference.
                if md_file.resolve().is_relative_to(OUTPUT_DIR.resolve()):
                    continue
                candidates.append(md_file)

        for path in candidates:
            size = path.stat().st_size
            relative = path.relative_to(REPO_ROOT)

            if size > MAX_STATIC_DOC_BYTES:
                f.write(
                    f"## `{relative}`\n\n"
                    f"*[Skipped: file size {size // 1024} KB exceeds limit of "
                    f"{MAX_STATIC_DOC_BYTES // 1024} KB]*\n\n"
                )
                print(f"    [skip-large] {relative} ({size // 1024} KB)")
                continue

            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                f.write(f"## `{relative}`\n\n*Could not read: {exc}*\n\n")
                continue

            print(f"    [static] {relative}")
            f.write(f"## `{relative}`\n\n{content}\n\n---\n\n")

    return out_path.stat().st_size


# ---------------------------------------------------------------------------
# Index file
# ---------------------------------------------------------------------------


def write_index(out_path: Path, manifest: list[tuple[str, Path, int]]) -> None:
    """Write a 00_index.md that serves as a table of contents for all generated files.

    The index is the first file NotebookLM should receive. It names every other
    file, describes its content, and lists its size so a reader can quickly orient.

    Args:
        out_path: Path to write the index file.
        manifest: List of (label, file_path, size_bytes) tuples describing every
            file that was written, in output order.
    """
    print(f"  Writing index  →  {out_path.name}")

    with out_path.open("w", encoding="utf-8") as f:
        f.write("# Agentic Memory: Full-Stack Context for NotebookLM\n\n")
        f.write(
            "*Auto-generated by `scripts/generate_notebooklm_docs.py`.*\n\n"
        )
        f.write(
            "This directory contains a set of focused Markdown sources for "
            "NotebookLM analysis of the agentic-memory stack. Add all files in "
            "this directory as sources in a single NotebookLM notebook.\n\n"
        )
        f.write(
            "**Stack overview:** agentic-memory is a graph-based persistent memory "
            "system for AI agents. It stores conversation turns, code context, and "
            "extracted entities in Neo4j, exposes MCP tool interfaces to AI clients, "
            "and runs TypeScript workers for background ingestion.\n\n"
        )
        f.write("---\n\n")
        f.write("## Files in This Directory\n\n")
        f.write("| File | Contents | Size |\n")
        f.write("|------|----------|------|\n")

        for label, path, size_bytes in manifest:
            size_str = f"{size_bytes / 1024:.1f} KB"
            f.write(f"| `{path.name}` | {label} | {size_str} |\n")

        f.write("\n---\n\n")
        f.write("## How to Use\n\n")
        f.write(
            "1. Open or create a NotebookLM notebook.\n"
            "2. Add each `.md` file in this directory as a separate source.\n"
            "3. Start with questions about architecture, data flow, or specific "
            "modules — NotebookLM will cite which source the answer came from.\n\n"
        )
        f.write(
            "To regenerate: `python scripts/generate_notebooklm_docs.py`\n"
        )


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------


def main() -> None:
    """Orchestrate multi-file documentation generation.

    Execution order:
    1. Resolve optional packages (attempt import; collect those that succeed).
    2. If ``--dry-run`` flag is present, print the manifest and exit.
    3. Create OUTPUT_DIR (docs/notebooklm/).
    4. Write each section to its own numbered file:
       - agentic-memory-01_project_overview.md  — static docs
       - agentic-memory-02_agentic_memory.md    — agentic_memory package
       - agentic-memory-03_codememory.md        — codememory package
       - agentic-memory-04_am_server.md         — am_server package
       - agentic-memory-05_am_proxy.md          — am_proxy package (if present)
       - agentic-memory-06_frontend_packages.md — all TypeScript packages
    5. Write agentic-memory-00_index.md last (it lists all files and their sizes).
    6. Print a size report for every file.
    """
    # --- Resolve optional packages ---
    optional_present: list[str] = []
    for pkg in OPTIONAL_PACKAGES:
        try:
            importlib.import_module(pkg)
            optional_present.append(pkg)
            print(f"  [optional] {pkg} found — will include.")
        except ImportError:
            print(f"  [optional] {pkg} not found — skipping.")

    # Build the planned manifest so --dry-run can print it without writing.
    # Each entry: (human label, filename, index number)
    planned: list[tuple[str, str]] = [
        ("Static documentation (README + docs/*.md)", "agentic-memory-01_project_overview.md"),
        ("Python package: agentic_memory", "agentic-memory-02_agentic_memory.md"),
        ("Python package: codememory", "agentic-memory-03_codememory.md"),
        ("Python package: am_server", "agentic-memory-04_am_server.md"),
    ]
    next_idx = 5
    for pkg in optional_present:
        planned.append((f"Python package: {pkg} (optional)", f"agentic-memory-0{next_idx}_{pkg}.md"))
        next_idx += 1
    planned.append(("Frontend TypeScript packages", f"agentic-memory-0{next_idx}_frontend_packages.md"))

    # --- Dry-run support ---
    if "--dry-run" in sys.argv:
        print("\n--- Dry run: planned output files ---\n")
        for label, fname in planned:
            print(f"  {fname:<35}  {label}")
        print(f"\nOutput directory: {OUTPUT_DIR}")
        print("[Dry run complete — no files written]")
        return

    # --- Create output directory ---
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"\nOutput directory: {OUTPUT_DIR}\n")

    manifest: list[tuple[str, Path, int]] = []

    # --- 01: Static docs ---
    print("[01] Static documentation")
    p = OUTPUT_DIR / "agentic-memory-01_project_overview.md"
    size = write_static_docs(p)
    manifest.append(("Static documentation (README + docs/*.md)", p, size))

    # --- 02–04: Required Python packages ---
    pkg_files = [
        ("agentic_memory", "agentic-memory-02_agentic_memory.md"),
        ("codememory",     "agentic-memory-03_codememory.md"),
        ("am_server",      "agentic-memory-04_am_server.md"),
    ]
    for pkg_name, fname in pkg_files:
        print(f"\n[{fname[:2]}] {pkg_name}")
        p = OUTPUT_DIR / fname
        size = document_package(pkg_name, p)
        manifest.append((f"Python package: `{pkg_name}`", p, size))

    # --- Optional packages ---
    idx = 5
    for pkg_name in optional_present:
        fname = f"agentic-memory-0{idx}_{pkg_name}.md"
        print(f"\n[0{idx}] {pkg_name} (optional)")
        p = OUTPUT_DIR / fname
        size = document_package(pkg_name, p)
        manifest.append((f"Python package: `{pkg_name}` (optional)", p, size))
        idx += 1

    # --- Frontend TypeScript packages ---
    fe_fname = f"agentic-memory-0{idx}_frontend_packages.md"
    print(f"\n[0{idx}] Frontend TypeScript packages")
    fe_paths = [REPO_ROOT / proj for proj in FRONTEND_PROJECTS]

    # Also include bench/ TypeScript files if present.
    bench_dir = REPO_ROOT / "bench"
    if bench_dir.exists() and any(bench_dir.rglob("*.ts")):
        fe_paths.append(bench_dir)

    p = OUTPUT_DIR / fe_fname
    size = document_frontend(fe_paths, p)
    manifest.append(("Frontend TypeScript packages", p, size))

    # --- 00: Index (written last so it has accurate sizes) ---
    print("\n[00] Index")
    write_index(OUTPUT_DIR / "agentic-memory-00_index.md", manifest)

    # --- Size report ---
    total_kb = sum(size for _, _, size in manifest) / 1024
    print(f"\n{'─' * 55}")
    print(f"{'File':<35}  {'Size':>10}")
    print(f"{'─' * 55}")
    index_size = (OUTPUT_DIR / "00_index.md").stat().st_size
    print(f"  {'agentic-memory-00_index.md':<40}  {index_size / 1024:>8.1f} KB")
    for _, path, size in manifest:
        flag = "  ⚠ large" if size > 5 * 1024 * 1024 else ""
        print(f"  {path.name:<33}  {size / 1024:>8.1f} KB{flag}")
    print(f"{'─' * 55}")
    print(f"  {'TOTAL':<33}  {total_kb:>8.1f} KB")
    print(f"\nDone. Upload all files in: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
