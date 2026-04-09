"""
Purpose: Generates comprehensive documentation for m26pipeline codebase for NotebookLM AI analysis.

Extended: This script walks through Python backend services and frontend projects,
extracting docstrings, source code, and monitoring configurations into a single
Markdown document optimized for NotebookLM's context window. Enables AI-powered
code analysis, architecture understanding, and technical Q&A.

Dependencies: 
- Python standard library (os, sys, pkgutil, importlib, inspect, pathlib)
- All packages listed in PACKAGES must be importable

Role: Documentation generation for m26pipeline. Run manually to update context
documentation when codebase structure changes significantly. Output stored in
docs/notebooklm_context.md for upload to NotebookLM.

Key Technologies/APIs:
- importlib.import_module(): Dynamic package loading
- pkgutil.walk_packages(): Recursive module discovery
- inspect.getdoc(): Docstring extraction
- Path.walk(): Filesystem traversal for frontend files
"""

import os
import sys
import pkgutil
import importlib
import inspect
from pathlib import Path

# Add project root to sys.path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Core Python packages to document (all importable backend services)
PACKAGES = [
    "command_service",      # Purchase execution service
    "sales_service",        # Sales data polling and processing
    "session_service",      # Session management and auth
    "shared",               # Shared utilities and helpers
    "realtime_api",         # WebSocket API for realtime auction data
    "companion_collect",    # Data collection companion service
    "scripts"               # Utility scripts and tools
]

# Frontend projects to document (current production frontends)
FRONTEND_PROJECTS = [
    "mutdashboard-tauri",   # Current desktop app (Tauri + SolidJS + Rust)
]

# Monitoring configs to document
MONITORING_CONFIGS = [
    "monitoring/prometheus.yml",
    "monitoring/alerts.yml",
    "monitoring/alertmanager.yml"
]


def get_docstring(obj):
    """Extracts docstring from Python object.
    
    Extended: Safely retrieves documentation strings from modules, classes,
    functions, and methods. Returns empty string if no docstring exists to
    prevent None-related errors during document generation.
    
    Args:
        obj: Any Python object (module, class, function, method)
    
    Returns:
        str: Formatted docstring or empty string if none exists
    
    Key Technologies/APIs:
        - inspect.getdoc(): Retrieves and formats docstrings
    """
    return inspect.getdoc(obj) or ""


def document_module(module_name, out_file):
    """Documents a single Python module's classes and functions.
    
    Extended: Recursively extracts and formats docstrings from a Python module,
    including module-level docs, all classes with their methods, and standalone
    functions. Implements robust filtering to exclude third-party library pollution
    (Pydantic, builtins, typing, etc.) and inherited BaseModel methods. Includes
    actual source code for functions/methods to provide implementation context.
    Handles import errors gracefully.
    
    Args:
        module_name (str): Fully qualified module name (e.g., "sales_service.app")
        out_file: File handle for writing Markdown output
    
    Key Technologies/APIs:
        - importlib.import_module(): Dynamic module loading
        - inspect.getmembers(): Introspection of module contents
        - inspect.isclass/isroutine: Type checking for documentation filtering
        - inspect.getsource(): Extract actual source code for implementation details
    """
    # Third-party packages to exclude from documentation (prevent pollution)
    THIRD_PARTY_EXCLUDE = (
        'pydantic', 'pydantic_core', 'builtins', 'typing', 'typing_extensions',
        'http', 'email', 'json', 'dataclasses', 'abc', 'collections',
        'httpx', 'fastapi', 'starlette', 'uvicorn'
    )
    
    # Inherited BaseModel methods to skip (prevent Pydantic pollution)
    BASEMODEL_METHODS = {
        'model_validate', 'model_validate_json', 'model_dump', 'model_dump_json',
        'model_copy', 'model_construct', 'model_json_schema', 'model_fields',
        'model_computed_fields', 'model_config', 'copy', 'dict', 'json',
        'parse_obj', 'parse_raw', 'parse_file', 'schema', 'schema_json',
        'construct', 'update_forward_refs', '__get_validators__', '__modify_schema__'
    }
    
    try:
        mod = importlib.import_module(module_name)
    except Exception as e:
        print(f"  Error importing {module_name}: {e}")
        return

    # Track if this module has any documented content (prevent empty sections)
    has_content = False
    module_content = []  # Buffer content to write only if non-empty
    
    # Module docstring
    doc = get_docstring(mod)
    if doc:
        module_content.append(f"{doc}\n\n")
        has_content = True

    # Classes
    for name, obj in inspect.getmembers(mod, inspect.isclass):
        # SECURITY: Skip third-party classes (critical Pydantic pollution fix)
        if obj.__module__ != module_name:
            continue
        if any(obj.__module__.startswith(pkg) for pkg in THIRD_PARTY_EXCLUDE):
            continue
            
        class_content = []
        class_content.append(f"### Class: `{name}`\n\n")
        doc = get_docstring(obj)
        if doc:
            class_content.append(f"{doc}\n\n")
        
        # Methods
        method_count = 0
        for m_name, m_obj in inspect.getmembers(obj, inspect.isroutine):
            # Skip private methods (except __init__), dunder methods, Pydantic methods
            if m_name.startswith("__") and m_name != "__init__":
                continue
            if m_name.startswith("_") and m_name != "__init__":
                continue
            if m_name in BASEMODEL_METHODS:
                continue
            
            doc = get_docstring(m_obj)
            if doc:
                class_content.append(f"#### Method: `{m_name}`\n\n")
                class_content.append(f"```python\n{doc}\n```\n\n")
                
                # Extract source code for implementation context
                try:
                    source = inspect.getsource(m_obj)
                    class_content.append(f"**Source Code:**\n\n```python\n{source}\n```\n\n")
                except (TypeError, OSError):
                    pass  # Source not available (built-in or dynamically created)
                
                method_count += 1
        
        # Only add class if it has documented methods
        if method_count > 0:
            module_content.extend(class_content)
            has_content = True

    # Functions
    for name, obj in inspect.getmembers(mod, inspect.isroutine):
        # SECURITY: Skip third-party functions
        if obj.__module__ != module_name:
            continue
        if any(obj.__module__.startswith(pkg) for pkg in THIRD_PARTY_EXCLUDE):
            continue
            
        module_content.append(f"### Function: `{name}`\n\n")
        doc = get_docstring(obj)
        if doc:
            module_content.append(f"```python\n{doc}\n```\n\n")
            
            # Extract source code for implementation context
            try:
                source = inspect.getsource(obj)
                module_content.append(f"**Source Code:**\n\n```python\n{source}\n```\n\n")
            except (TypeError, OSError):
                pass  # Source not available
            
            has_content = True
    
    # Only write module section if it has actual content (prevent empty sections)
    if has_content:
        out_file.write(f"\n## Module: `{module_name}`\n\n")
        out_file.writelines(module_content)


def document_frontend(project_path, out_file):
    """Documents frontend project source code files.
    
    Extended: Walks through a frontend project directory, extracting all TypeScript,
    TSX, and CSS files for full-text inclusion in documentation. Filters out build
    artifacts (node_modules, dist) to keep output focused on source code. Critical
    for providing NotebookLM full context on frontend implementation, component
    structure, and UI logic. Handles errors gracefully if project path doesn't exist.
    
    Args:
        project_path (str): Relative path to frontend project from repo root
        out_file: File handle for writing Markdown output
    
    Key Technologies/APIs:
        - os.walk(): Recursive directory traversal
        - Path.read_text(): UTF-8 file reading with encoding handling
    """
    base_path = REPO_ROOT / project_path
    if not base_path.exists():
        print(f"  Warning: Frontend path {project_path} not found.")
        return

    out_file.write(f"\n# Frontend Project: {project_path}\n\n")
    
    src_path = base_path / "src"
    if not src_path.exists():
        src_path = base_path # fallback

    for root, _, files in os.walk(src_path):
        for file in files:
            if file.endswith((".ts", ".tsx", ".css")):
                file_path = Path(root) / file
                rel_path = file_path.relative_to(base_path)
                
                # Filter out heavy binary-like files or node_modules just in case
                if "node_modules" in str(rel_path) or "dist" in str(rel_path):
                    continue
                    
                print(f"  Adding frontend file: {rel_path}...")
                out_file.write(f"\n## File: {rel_path}\n\n")
                
                try:
                    content = file_path.read_text(encoding="utf-8")
                    out_file.write("SOURCE CODE START:\n\n")
                    out_file.write(content)
                    out_file.write("\n\nSOURCE CODE END.\n\n")
                except Exception as e:
                    out_file.write(f"Error reading file: {e}\n\n")


def main():
    """Main execution function for documentation generation.
    
    Extended: Orchestrates the complete documentation generation pipeline:
    1. Creates output directory if needed
    2. Generates table of contents
    3. Documents all Python backend packages (with recursive module walking)
    4. Documents all frontend projects (full source code)
    5. Includes monitoring configurations (Prometheus, alerts)
    
    Output is a single comprehensive Markdown file optimized for NotebookLM's
    context window, enabling AI-powered code search, architecture understanding,
    and technical Q&A across the entire m26pipeline codebase.
    
    Key Technologies/APIs:
        - pkgutil.walk_packages(): Discovers all submodules in a package
        - Path.mkdir(): Creates output directory
        - File I/O: UTF-8 encoded Markdown generation
    """
    output_path = REPO_ROOT / "docs" / "notebooklm_context.md"
    output_path.parent.mkdir(exist_ok=True)
    
    print(f"Generating merged Markdown to {output_path}...")
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# M26 Pipeline: Full Stack Context for NotebookLM\n\n")
        f.write("> This document contains the complete back-end logic (docstrings) and front-end source code (plain text).\n\n")
        
        f.write("## Table of Contents\n")
        f.write("1. [Back-end (Python API)](#back-end-python-api)\n")
        for pkg in PACKAGES:
            f.write(f"   - [{pkg}](#package-{pkg.replace('_', '-')})\n")
        f.write("2. [Front-end (Tauri Desktop App)](#front-end-tauri-desktop-app)\n")
        for fe in FRONTEND_PROJECTS:
            f.write(f"   - [{fe}](#frontend-project-{fe.replace('/', '-').replace('_', '-')})\n")
        f.write("\n---\n\n")

        # Backend first (docstrings - already plain text)
        f.write("# Back-end (Python API)\n\n")
        
        for pkg_name in PACKAGES:
            print(f"Processing package: {pkg_name}...")
            f.write(f"\n## Package: {pkg_name}\n\n")
            try:
                pkg = importlib.import_module(pkg_name)
                document_module(pkg_name, f)
                if hasattr(pkg, "__path__"):
                    for info in pkgutil.walk_packages(pkg.__path__, pkg_name + "."):
                        if not info.ispkg:
                            document_module(info.name, f)
            except Exception as e:
                print(f"Error processing package {pkg_name}: {e}")

        f.write("\n---\n\n")
        
        # Frontend second (plain text - no code blocks)
        f.write("# Front-end (Tauri Desktop App)\n\n")
        f.write("## Overview: Frontend Architecture\n")
        f.write("The frontend is MutDashboard, a Tauri-based desktop application combining:\n")
        f.write("- **Frontend**: SolidJS for reactive UI\n")
        f.write("- **Backend**: Rust (Tauri) for native desktop integration and performance\n")
        f.write("- **Communication**: WebSocket connection to `realtime_api` for live auction data\n")
        f.write("- **Data Format**: Protobuf-encoded messages for efficient real-time updates\n\n")

        for fe_proj in FRONTEND_PROJECTS:
            print(f"Processing frontend: {fe_proj}...")
            document_frontend(fe_proj, f)

        f.write("\n---\n\n")
        
        # Monitoring configs (Prometheus/Grafana)
        f.write("# Monitoring Infrastructure\n\n")
        f.write("The following Prometheus and Grafana configurations define metrics, alerts, and dashboards for the pipeline.\n\n")
        
        for config_path in MONITORING_CONFIGS:
            full_path = REPO_ROOT / config_path
            if not full_path.exists():
                continue
            
            print(f"Processing monitoring config: {config_path}...")
            f.write(f"\n## Config: {config_path}\n\n")
            
            try:
                content = full_path.read_text(encoding="utf-8")
                f.write("CONFIG START:\n\n")
                f.write(content)
                f.write("\n\nCONFIG END.\n\n")
            except Exception as e:
                f.write(f"Error reading config: {e}\n\n")

    print(f"Success! Generated {output_path}")


if __name__ == "__main__":
    main()
