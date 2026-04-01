# Load .env BEFORE any other imports that might need environment variables
from dotenv import load_dotenv

load_dotenv()

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

import neo4j

from codememory.ingestion.git_graph import GitGraphIngestor
from codememory.ingestion.graph import KnowledgeGraphBuilder
from codememory.ingestion.watcher import start_continuous_watch
from codememory.config import Config, find_repo_root, DEFAULT_CONFIG
from codememory.telemetry import TelemetryStore, resolve_telemetry_db_path


def print_banner():
    """Print the Agentic Memory banner."""
    print(r"""
    ╔═══════════════════════════════════════════════════════════════╗
    ║                                                               ║
    ║   ███╗   ██╗███████╗██╗  ██╗██╗   ██╗███████╗                 ║
    ║   ████╗  ██║██╔════╝╚██╗██╔╝██║   ██║██╔════╝                 ║
    ║   ██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║███████╗                 ║
    ║   ██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║╚════██║                 ║
    ║   ██║ ╚████║███████╗██╔╝ ██╗╚██████╔╝███████║                 ║
    ║   ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝                 ║
    ║                                                               ║
    ║            Structural Code Graph with Neo4j & MCP              ║
    ║                                                               ║
    ╚═══════════════════════════════════════════════════════════════╝
    """)


def _load_repo_env(repo_root: Optional[Path], env_file_arg: Optional[str] = None) -> None:
    """Load an explicit env file or the repository-local .env if present."""
    if env_file_arg:
        env_file = Path(env_file_arg).expanduser().resolve()
        if not env_file.exists():
            print(f"❌ Invalid --env-file path: {env_file}")
            sys.exit(1)
        load_dotenv(dotenv_path=env_file, override=False)
        return

    if repo_root:
        repo_env = repo_root / ".env"
        if repo_env.exists():
            load_dotenv(dotenv_path=repo_env, override=False)


def _is_json_mode(args: argparse.Namespace) -> bool:
    """Return whether the current command should emit machine-readable JSON."""
    return bool(getattr(args, "json", False))


def _emit_json(
    ok: bool,
    *,
    error: Optional[str] = None,
    data: Any = None,
    metrics: Optional[dict[str, Any]] = None,
) -> None:
    """Emit the standardized command envelope."""
    print(
        json.dumps(
            {
                "ok": ok,
                "error": error,
                "data": data,
                "metrics": metrics or {},
            },
            default=str,
        )
    )


def _exit_with_error(
    args: argparse.Namespace,
    *,
    error: str,
    human_lines: Optional[list[str]] = None,
    exit_code: int = 1,
) -> None:
    """Emit a standardized failure payload and exit non-zero."""
    if _is_json_mode(args):
        _emit_json(ok=False, error=error, data=None, metrics={})
    else:
        for line in human_lines or [f"❌ {error}"]:
            print(line)
    raise SystemExit(exit_code)


def _emit_success(
    args: argparse.Namespace, *, data: Any, metrics: Optional[dict[str, Any]] = None
) -> bool:
    """Emit success JSON if requested. Returns True when JSON output was emitted."""
    if not _is_json_mode(args):
        return False
    _emit_json(ok=True, error=None, data=data, metrics=metrics or {})
    return True


def _resolve_repo_and_config(
    args: argparse.Namespace,
    *,
    require_initialized: bool = True,
) -> tuple[Path, Config]:
    """Resolve repository root and config object from optional --repo arg."""
    if getattr(args, "repo", None):
        repo_root = Path(args.repo).expanduser().resolve()
        if not repo_root.exists() or not repo_root.is_dir():
            _exit_with_error(
                args,
                error=f"Invalid repository path: {repo_root}",
                human_lines=[f"❌ Invalid repository path: {repo_root}"],
            )
    else:
        repo_root = find_repo_root()

    _load_repo_env(repo_root, getattr(args, "env_file", None) or os.getenv("CODEMEMORY_ENV_FILE"))

    config = Config(repo_root)
    if require_initialized and not config.exists():
        _exit_with_error(
            args,
            error="Agentic Memory is not initialized in this repository.",
            human_lines=[
                "❌ Agentic Memory is not initialized in this repository.",
                "   Run 'codememory init' to get started.",
            ],
        )

    return repo_root, config


def cmd_init(args):
    """Initialize Agentic Memory in the current repository."""
    repo_root = Path.cwd()

    # Check if already initialized
    config = Config(repo_root)
    if config.exists():
        print(f"⚠️  This repository is already initialized with Agentic Memory.")
        print(f"    Config location: {config.config_file}")
        print(
            f"\n   To reconfigure, edit the config file or delete .codememory/ and run init again."
        )
        return

    print_banner()
    print(f"🚀 Initializing Agentic Memory in: {repo_root}\n")

    # ============================================================
    # Step 1: Neo4j Configuration
    # ============================================================
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("Step 1: Neo4j Database Configuration")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    print("Agentic Memory requires Neo4j 5.18+ with vector search support.")
    print("\nOptions:")
    print("  1. Local Neo4j (Docker)")
    print("  2. Neo4j Aura (Cloud)")
    print("  3. Custom URL")
    print("  4. Use environment variables (NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD)")

    neo_choice = input("\nChoose Neo4j setup [1-4] (default: 1): ").strip() or "1"

    neo4j_config = DEFAULT_CONFIG["neo4j"].copy()

    if neo_choice == "1":
        print("\n📦 Using local Neo4j (Docker)")
        print("   We'll use: bolt://localhost:7687")
        print("   Start with: docker run -p 7474:7474 -p 7687:7687 neo4j:5.25")
        neo4j_config["uri"] = "bolt://localhost:7687"
        neo4j_config["user"] = "neo4j"
        neo4j_config["password"] = (
            input("   Enter Neo4j password (default: password): ").strip() or "password"
        )

    elif neo_choice == "2":
        print("\n☁️  Using Neo4j Aura (Cloud)")
        print("   Get your free instance at: https://neo4j.com/cloud/aura/")
        neo4j_config["uri"] = input("   Enter Aura connection URL (neo4j+s://...): ").strip()
        neo4j_config["user"] = "neo4j"
        neo4j_config["password"] = input("   Enter Aura password: ").strip()

    elif neo_choice == "3":
        print("\n🔗 Custom Neo4j URL")
        neo4j_config["uri"] = input("   Enter Neo4j URI: ").strip()
        neo4j_config["user"] = (
            input("   Enter Neo4j username (default: neo4j): ").strip() or "neo4j"
        )
        neo4j_config["password"] = input("   Enter Neo4j password: ").strip()

    else:  # choice == "4"
        print("\n🔐 Using environment variables")
        print("   Set NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD in your environment")
        print("   (These will override config file values)")

    # ============================================================
    # Step 2: OpenAI Configuration
    # ============================================================
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("Step 2: OpenAI API Configuration")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    print("OpenAI API is used for semantic search (embeddings).")
    print("Without it, you can still use structural queries (dependencies, impact).")
    print("\nOptions:")
    print("  1. Enter API key now (will be stored in .codememory/config.json)")
    print("  2. Use environment variable OPENAI_API_KEY")
    print("  3. Skip for now (semantic search won't work)")

    openai_choice = input("\nChoose option [1-3] (default: 2): ").strip() or "2"

    openai_config = DEFAULT_CONFIG["openai"].copy()

    if openai_choice == "1":
        api_key = input("   Enter OpenAI API key (sk-...): ").strip()
        openai_config["api_key"] = api_key
    elif openai_choice == "2":
        print("   ✅ Will use OPENAI_API_KEY environment variable")
    else:
        print("   ⚠️  Semantic search will be disabled")

    # ============================================================
    # Step 3: Indexing Options
    # ============================================================
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("Step 3: Indexing Options")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    print("Supported file extensions (default: .py, .js, .ts, .tsx, .jsx)")
    extensions_input = input(
        "   Enter extensions (comma-separated, or press Enter for defaults): "
    ).strip()
    if extensions_input:
        indexing_config = DEFAULT_CONFIG["indexing"].copy()
        indexing_config["extensions"] = [
            e.strip() if e.strip().startswith(".") else f".{e.strip()}"
            for e in extensions_input.split(",")
        ]
    else:
        indexing_config = DEFAULT_CONFIG["indexing"].copy()

    # ============================================================
    # Step 4: Save Config
    # ============================================================
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("Step 4: Save Configuration")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    final_config = {
        "neo4j": neo4j_config,
        "openai": openai_config,
        "indexing": indexing_config,
    }

    config.save(final_config)
    config.ensure_graphignore(indexing_config.get("ignore_dirs", []))

    print(f"✅ Configuration saved to: {config.config_file}")
    print(f"✅ Ignore patterns saved to: {config.graphignore_file}")

    # ============================================================
    # Step 5: Test Connection & Initial Index
    # ============================================================
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("Step 5: Test Connection & Initial Index")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    do_index = input("Run initial indexing now? [Y/n]: ").strip().lower()
    if do_index != "n":
        try:
            neo4j_cfg = config.get_neo4j_config()
            openai_key = config.get_openai_key()
            indexing_cfg = config.get_indexing_config()
            ignore_dirs = set(indexing_cfg.get("ignore_dirs", []))
            ignore_files = set(indexing_cfg.get("ignore_files", []))
            extensions = set(indexing_cfg.get("extensions", []))
            graphignore_patterns = set(config.get_graphignore_patterns())

            print("\n🔍 Testing Neo4j connection...")
            builder = KnowledgeGraphBuilder(
                uri=neo4j_cfg["uri"],
                user=neo4j_cfg["user"],
                password=neo4j_cfg["password"],
                openai_key=openai_key,
                repo_root=repo_root,
                ignore_dirs=ignore_dirs,
                ignore_files=ignore_files,
                ignore_patterns=graphignore_patterns,
            )

            # Test connection
            builder.setup_database()
            print("✅ Neo4j connection successful!\n")

            builder.close()

            print("📂 Starting initial indexing...")
            builder = KnowledgeGraphBuilder(
                uri=neo4j_cfg["uri"],
                user=neo4j_cfg["user"],
                password=neo4j_cfg["password"],
                openai_key=openai_key,
                repo_root=repo_root,
                ignore_dirs=ignore_dirs,
                ignore_files=ignore_files,
                ignore_patterns=graphignore_patterns,
            )

            metrics = builder.run_pipeline(repo_root, supported_extensions=extensions)
            builder.close()

            print(f"\n✅ Indexing complete!")
            print(f"   Processed {metrics['embedding_calls']} entities")
            print(f"   Cost: ${metrics['cost_usd']:.4f} USD")

        except (OSError, IOError) as e:
            print(f"\n❌ Error during indexing: {e}")
            print(f"   Your config has been saved. You can index later with:")
            print(f"   codememory index")

    # ============================================================
    # Done!
    # ============================================================
    print("\n" + "━" * 67)
    print("✅ Agentic Memory initialized successfully!")
    print("━" * 67)
    print(f"\nConfig file: {config.config_file}")
    print(f"\nNext steps:")
    print(f"  • codememory status    - Show repository status")
    print(f"  • codememory watch     - Start continuous monitoring")
    print(f"  • codememory serve     - Start MCP server for AI agents")
    print(f"  • codememory search    - Test semantic search")
    print()


def cmd_status(args):
    """Show status of Agentic Memory for the current repository."""
    repo_root, config = _resolve_repo_and_config(args, require_initialized=True)

    if not _is_json_mode(args):
        print(f"📊 Agentic Memory Status")
        print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"Repository: {repo_root}")
        print(f"Config:     {config.config_file}")

    # Try to connect and get stats
    builder = None
    try:
        neo4j_cfg = config.get_neo4j_config()
        openai_key = config.get_openai_key()

        builder = KnowledgeGraphBuilder(
            uri=neo4j_cfg["uri"],
            user=neo4j_cfg["user"],
            password=neo4j_cfg["password"],
            openai_key=openai_key,
            repo_root=repo_root,
        )

        with builder.driver.session() as session:
            # Get stats
            files = session.run("MATCH (f:File) RETURN count(f) as count").single()["count"]
            functions = session.run("MATCH (fn:Function) RETURN count(fn) as count").single()[
                "count"
            ]
            classes = session.run("MATCH (c:Class) RETURN count(c) as count").single()["count"]
            chunks = session.run("MATCH (ch:Chunk) RETURN count(ch) as count").single()["count"]

            # Get last update
            last_update = session.run("""
                MATCH (f:File)
                RETURN max(f.last_updated) as last_updated
            """).single()["last_updated"]

            stats = {
                "files": files,
                "functions": functions,
                "classes": classes,
                "chunks": chunks,
                "last_sync": last_update,
            }
            if _emit_success(
                args,
                data={
                    "repository": str(repo_root),
                    "config": str(config.config_file),
                    "stats": stats,
                },
                metrics={},
            ):
                return

            print(f"\n📈 Graph Statistics:")
            print(f"   Files:     {files:,}")
            print(f"   Functions: {functions:,}")
            print(f"   Classes:   {classes:,}")
            print(f"   Chunks:    {chunks:,}")
            if last_update:
                print(f"   Last sync: {last_update}")

    except (neo4j.exceptions.DatabaseError, neo4j.exceptions.ServiceUnavailable) as e:
        _exit_with_error(
            args,
            error=f"Could not connect to Neo4j: {e}",
            human_lines=[
                f"\n⚠️  Could not connect to Neo4j: {e}",
                "   Make sure Neo4j is running and check your config.",
            ],
        )
    finally:
        if builder is not None:
            builder.close()


def cmd_index(args):
    """Run a one-time full pipeline ingestion."""
    repo_root, config = _resolve_repo_and_config(args, require_initialized=True)

    if not args.quiet and not _is_json_mode(args):
        print(f"📂 Indexing repository: {repo_root}")

    neo4j_cfg = config.get_neo4j_config()
    openai_key = config.get_openai_key()
    indexing_cfg = config.get_indexing_config()
    ignore_dirs = set(indexing_cfg.get("ignore_dirs", []))
    ignore_files = set(indexing_cfg.get("ignore_files", []))
    extensions = set(indexing_cfg.get("extensions", []))
    graphignore_patterns = set(config.get_graphignore_patterns())

    builder = KnowledgeGraphBuilder(
        uri=neo4j_cfg["uri"],
        user=neo4j_cfg["user"],
        password=neo4j_cfg["password"],
        openai_key=openai_key,
        repo_root=repo_root,
        ignore_dirs=ignore_dirs,
        ignore_files=ignore_files,
        ignore_patterns=graphignore_patterns,
    )

    try:
        metrics = builder.run_pipeline(repo_root, supported_extensions=extensions)
        if _emit_success(
            args,
            data={"repository": str(repo_root)},
            metrics=metrics,
        ):
            return
        if not args.quiet:
            print(f"\n✅ Indexing complete!")
            print(f"   Processed {metrics['embedding_calls']} entities")
            print(f"   Cost: ${metrics['cost_usd']:.4f} USD")
    except Exception as e:
        _exit_with_error(
            args,
            error=f"Indexing failed: {e}",
            human_lines=[f"❌ Indexing failed: {e}"],
        )
    finally:
        builder.close()


def cmd_watch(args):
    """Start continuous file watching and ingestion."""
    repo_root, config = _resolve_repo_and_config(args, require_initialized=True)

    print(f"👀 Starting Observer on: {repo_root}")

    neo4j_cfg = config.get_neo4j_config()
    openai_key = config.get_openai_key()
    indexing_cfg = config.get_indexing_config()
    graphignore_patterns = set(config.get_graphignore_patterns())

    start_continuous_watch(
        repo_path=repo_root,
        neo4j_uri=neo4j_cfg["uri"],
        neo4j_user=neo4j_cfg["user"],
        neo4j_password=neo4j_cfg["password"],
        openai_key=openai_key,
        ignore_dirs=set(indexing_cfg.get("ignore_dirs", [])),
        ignore_files=set(indexing_cfg.get("ignore_files", [])),
        ignore_patterns=graphignore_patterns,
        supported_extensions=set(indexing_cfg.get("extensions", [])),
        initial_scan=not args.no_scan,
    )


def cmd_serve(args):
    """Start the MCP server."""
    from codememory.server.app import run_server

    repo_root = None
    if args.repo:
        repo_root = Path(args.repo).expanduser().resolve()
        if not repo_root.exists() or not repo_root.is_dir():
            print(f"❌ Invalid --repo path: {repo_root}")
            sys.exit(1)

    _load_repo_env(repo_root, args.env_file or os.getenv("CODEMEMORY_ENV_FILE"))

    if repo_root:
        config = Config(repo_root)
        if not config.exists():
            print(
                f"⚠️  No .codememory/config.json found in {repo_root}, using environment variables"
            )
    else:
        auto_root = find_repo_root()
        config = Config(auto_root)
        if not config.exists():
            print(f"⚠️  No local config found, using environment variables")

    print(f"🧠 Starting MCP Interface on port {args.port}")
    if repo_root:
        print(f"📂 Using repository root: {repo_root}")
    run_server(port=args.port, repo_root=repo_root)


def cmd_search(args):
    """Run a semantic search query (for testing)."""
    repo_root, config = _resolve_repo_and_config(args, require_initialized=True)

    neo4j_cfg = config.get_neo4j_config()
    openai_key = config.get_openai_key()

    if not openai_key:
        _exit_with_error(
            args,
            error="OpenAI API key not configured.",
            human_lines=[
                "❌ OpenAI API key not configured.",
                "   Set OPENAI_API_KEY environment variable or add it to .codememory/config.json",
            ],
        )

    builder = KnowledgeGraphBuilder(
        uri=neo4j_cfg["uri"],
        user=neo4j_cfg["user"],
        password=neo4j_cfg["password"],
        openai_key=openai_key,
    )

    try:
        results = builder.semantic_search(args.query, limit=args.limit)
        if _emit_success(
            args,
            data={
                "query": args.query,
                "limit": args.limit,
                "results": results,
            },
            metrics={"result_count": len(results)},
        ):
            return

        if not results:
            print("No relevant code found.")
            return

        print(f"\nFound {len(results)} result(s):\n")
        for i, r in enumerate(results, 1):
            name = r.get("name", "Unknown")
            score = r.get("score", 0)
            text = r.get("text", "")[:300]
            sig = r.get("sig", "")

            print(f"{i}. **{name}** [`{sig}`] - Score: {score:.2f}")
            print(f"   {text}...\n")
    except Exception as e:
        _exit_with_error(
            args,
            error=f"Search failed: {e}",
            human_lines=[f"❌ Search failed: {e}"],
        )
    finally:
        builder.close()


def cmd_deps(args):
    """Show direct dependency relationships for a file."""
    repo_root, config = _resolve_repo_and_config(args, require_initialized=True)

    neo4j_cfg = config.get_neo4j_config()
    openai_key = config.get_openai_key()
    builder = KnowledgeGraphBuilder(
        uri=neo4j_cfg["uri"],
        user=neo4j_cfg["user"],
        password=neo4j_cfg["password"],
        openai_key=openai_key,
    )

    try:
        deps = builder.get_file_dependencies(args.path)
        imports = deps.get("imports", [])
        imported_by = deps.get("imported_by", [])

        if _emit_success(
            args,
            data={
                "path": args.path,
                "imports": imports,
                "imported_by": imported_by,
            },
            metrics={
                "imports_count": len(imports),
                "imported_by_count": len(imported_by),
            },
        ):
            return

        print(f"## Dependencies for `{args.path}`\n")
        if imports:
            print("### Imports")
            for imp in imports:
                print(f"- {imp}")
        else:
            print("### Imports")
            print("No imports found.")

        print()
        if imported_by:
            print("### Imported By")
            for dep in imported_by:
                print(f"- {dep}")
        else:
            print("### Imported By")
            print("No dependents found.")
    except Exception as e:
        _exit_with_error(
            args,
            error=f"Dependency analysis failed: {e}",
            human_lines=[f"❌ Dependency analysis failed: {e}"],
        )
    finally:
        builder.close()


def cmd_impact(args):
    """Show transitive impact analysis for a file."""
    repo_root, config = _resolve_repo_and_config(args, require_initialized=True)

    neo4j_cfg = config.get_neo4j_config()
    openai_key = config.get_openai_key()
    builder = KnowledgeGraphBuilder(
        uri=neo4j_cfg["uri"],
        user=neo4j_cfg["user"],
        password=neo4j_cfg["password"],
        openai_key=openai_key,
    )

    try:
        result = builder.identify_impact(args.path, max_depth=args.max_depth)
        affected_files = result.get("affected_files", [])
        total_count = result.get("total_count", len(affected_files))

        if _emit_success(
            args,
            data={
                "path": args.path,
                "max_depth": args.max_depth,
                "affected_files": affected_files,
            },
            metrics={"total_count": total_count, "max_depth": args.max_depth},
        ):
            return

        print(f"## Impact Analysis for `{args.path}`\n")
        if total_count == 0:
            print("No files depend on this file. Changes are isolated.")
            return

        print(f"Total affected files: {total_count}\n")
        for entry in affected_files:
            print(f"- {entry.get('path')} (depth={entry.get('depth')})")
    except Exception as e:
        _exit_with_error(
            args,
            error=f"Impact analysis failed: {e}",
            human_lines=[f"❌ Impact analysis failed: {e}"],
        )
    finally:
        builder.close()


def cmd_git_init(args):
    """Enable git graph config and initialize GitRepo metadata/constraints."""
    repo_root, config = _resolve_repo_and_config(args, require_initialized=True)
    git_cfg = config.get_git_config()
    if not git_cfg.get("enabled"):
        config.save_git_config({"enabled": True})

    neo4j_cfg = config.get_neo4j_config()
    ingestor = GitGraphIngestor(
        uri=neo4j_cfg["uri"],
        user=neo4j_cfg["user"],
        password=neo4j_cfg["password"],
        repo_root=repo_root,
        config=config,
    )

    try:
        repo_meta = ingestor.initialize()
        refreshed_git_cfg = config.get_git_config()
        data = {
            "repository": str(repo_root),
            "git": {
                "enabled": bool(refreshed_git_cfg.get("enabled")),
                "auto_incremental": bool(refreshed_git_cfg.get("auto_incremental", True)),
                "sync_trigger": refreshed_git_cfg.get("sync_trigger", "commit"),
                "checkpoint": refreshed_git_cfg.get("checkpoint", {}),
            },
            "graph": repo_meta,
        }
        if _emit_success(args, data=data, metrics={}):
            return

        print(f"✅ Git graph initialized for repository: {repo_root}")
    except Exception as e:
        _exit_with_error(
            args,
            error=f"Git init failed: {e}",
            human_lines=[f"❌ Git init failed: {e}"],
        )
    finally:
        ingestor.close()


def cmd_git_sync(args):
    """Sync git history into Neo4j as full or incremental run."""
    repo_root, config = _resolve_repo_and_config(args, require_initialized=True)
    git_cfg = config.get_git_config()
    if not git_cfg.get("enabled"):
        _exit_with_error(
            args,
            error="Git graph is not initialized for this repository.",
            human_lines=[
                "❌ Git graph is not initialized for this repository.",
                "   Run 'codememory git-init' first.",
            ],
        )

    neo4j_cfg = config.get_neo4j_config()
    ingestor = GitGraphIngestor(
        uri=neo4j_cfg["uri"],
        user=neo4j_cfg["user"],
        password=neo4j_cfg["password"],
        repo_root=repo_root,
        config=config,
    )

    try:
        result = ingestor.sync(full=args.full)
        if _emit_success(
            args,
            data={"repository": str(repo_root), "sync": result},
            metrics={
                "commits_seen": result["commits_seen"],
                "commits_synced": result["commits_synced"],
                "checkpoint_reset": result["checkpoint_reset"],
            },
        ):
            return

        print(f"✅ Git sync complete: {result['commits_synced']} commit(s) ingested")
    except Exception as e:
        _exit_with_error(
            args,
            error=f"Git sync failed: {e}",
            human_lines=[f"❌ Git sync failed: {e}"],
        )
    finally:
        ingestor.close()


def cmd_git_status(args):
    """Show git graph sync status for a repository."""
    repo_root, config = _resolve_repo_and_config(args, require_initialized=True)
    git_cfg = config.get_git_config()
    if not git_cfg.get("enabled"):
        _exit_with_error(
            args,
            error="Git graph is not initialized for this repository.",
            human_lines=[
                "❌ Git graph is not initialized for this repository.",
                "   Run 'codememory git-init' first.",
            ],
        )

    neo4j_cfg = config.get_neo4j_config()
    ingestor = GitGraphIngestor(
        uri=neo4j_cfg["uri"],
        user=neo4j_cfg["user"],
        password=neo4j_cfg["password"],
        repo_root=repo_root,
        config=config,
    )

    try:
        status = ingestor.status()
        if _emit_success(
            args,
            data={"repository": str(repo_root), "status": status},
            metrics={"pending_commits": status["pending_commits"]},
        ):
            return

        print(f"📌 Git checkpoint: {status['checkpoint_sha'] or 'none'}")
        print(f"🧾 Pending commits: {status['pending_commits']}")
    except Exception as e:
        _exit_with_error(
            args,
            error=f"Git status failed: {e}",
            human_lines=[f"❌ Git status failed: {e}"],
        )
    finally:
        ingestor.close()


def cmd_annotate_interaction(
    args: argparse.Namespace,
    *,
    annotation_mode: str,
    prompt_prefix: str,
) -> None:
    """
    Manually annotate the latest MCP tool-use burst as prompted/unprompted.

    This is intentionally user-driven: you run it after an agent response to label
    whether the tool usage was explicitly prompted by you.
    """
    if annotation_mode not in {"prompted", "unprompted"}:
        _exit_with_error(
            args,
            error=f"Invalid annotation mode: {annotation_mode}",
            human_lines=[f"❌ Invalid annotation mode: {annotation_mode}"],
        )

    cleaned_prefix = prompt_prefix.strip()
    if not cleaned_prefix:
        _exit_with_error(
            args,
            error="Prompt prefix is required.",
            human_lines=["❌ Prompt prefix is required."],
        )

    repo_root = find_repo_root()
    db_path = resolve_telemetry_db_path(repo_root)
    store = TelemetryStore(db_path)

    wait_seconds = max(0, int(getattr(args, "wait_seconds", 45)))
    idle_seconds = max(1, int(getattr(args, "idle_seconds", 3)))
    lookback_seconds = max(15, int(getattr(args, "lookback_seconds", 180)))
    recent_seconds = max(5, int(getattr(args, "recent_seconds", 90)))
    client_filter = getattr(args, "client", None) or os.getenv("CODEMEMORY_CLIENT")
    specific_call_ids = getattr(args, "tool_call_id", None) or []

    annotation_id = (
        getattr(args, "annotation_id", None) or TelemetryStore.new_annotation_id()
    )
    store.create_pending_annotation(
        annotation_id=annotation_id,
        prompt_prefix=cleaned_prefix,
        annotation_mode=annotation_mode,
        client_id=client_filter,
    )

    if specific_call_ids:
        updated = store.apply_annotation_to_calls(
            annotation_id=annotation_id,
            prompt_prefix=cleaned_prefix,
            annotation_mode=annotation_mode,
            call_ids=[int(x) for x in specific_call_ids],
        )
        if updated == 0:
            store.delete_pending_annotation(annotation_id)
            print(
                "ℹ️ No matching tool-call IDs found. Pending annotation entry was removed."
            )
            return

        print(f"✅ Annotated {updated} tool call(s) as `{annotation_mode}`.")
        print(f"   Annotation ID: {annotation_id}")
        print(f"   Prompt Prefix: {cleaned_prefix}")
        print(f"   Tool Call IDs: {', '.join(str(x) for x in specific_call_ids)}")
        return

    print(
        f"🧾 Waiting up to {wait_seconds}s for latest tool-use burst to settle "
        f"(idle={idle_seconds}s)..."
    )
    if client_filter:
        print(f"   Client filter: {client_filter}")

    deadline = time.time() + wait_seconds
    matched_burst = []
    while True:
        burst = store.get_latest_unannotated_burst(
            lookback_seconds=lookback_seconds,
            idle_seconds=idle_seconds,
            client_id=client_filter,
        )

        if burst:
            newest_epoch = int(burst[-1]["epoch_ms"])
            now_epoch = int(time.time() * 1000)
            is_recent = now_epoch - newest_epoch <= (recent_seconds * 1000)
            is_idle = now_epoch - newest_epoch >= (idle_seconds * 1000)

            if is_recent and is_idle:
                matched_burst = burst
                break

        if time.time() >= deadline:
            break
        time.sleep(0.75)

    if not matched_burst:
        store.delete_pending_annotation(annotation_id)
        print("ℹ️ No tool usage matched this prompt window.")
        print("   Pending annotation entry was removed (no-op).")
        return

    call_ids = [int(row["id"]) for row in matched_burst]
    updated = store.apply_annotation_to_calls(
        annotation_id=annotation_id,
        prompt_prefix=cleaned_prefix,
        annotation_mode=annotation_mode,
        call_ids=call_ids,
    )
    if updated == 0:
        store.delete_pending_annotation(annotation_id)
        print(
            "ℹ️ Tool usage was detected but changed before annotation. "
            "Pending entry removed."
        )
        return

    first_id = call_ids[0]
    last_id = call_ids[-1]
    print(f"✅ Annotated {updated} tool call(s) as `{annotation_mode}`.")
    print(f"   Annotation ID: {annotation_id}")
    print(f"   Prompt Prefix: {cleaned_prefix}")
    print(f"   Tool Call ID Range: {first_id}..{last_id}")


def cmd_web_init(args: argparse.Namespace) -> None:
    """Initialize web research vector indexes and constraints."""
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "password")

    try:
        from codememory.core.connection import ConnectionManager
        conn = ConnectionManager(uri, user, password)
        conn.setup_database()
        conn.driver.close()
        print("web-init: research_embeddings vector index ready.")
    except Exception as e:
        print(f"web-init failed: {e}")
        sys.exit(1)


def cmd_web_ingest(args: argparse.Namespace) -> None:
    """Ingest a web URL or local PDF into research memory."""
    import asyncio
    url = args.url
    if not url:
        print("web-ingest: URL argument required.")
        sys.exit(1)

    from codememory.core.extraction_llm import resolve_extraction_llm_config  # noqa: PLC0415
    from codememory.core.runtime_embedding import build_embedding_service  # noqa: PLC0415

    extraction_llm = resolve_extraction_llm_config()
    if not extraction_llm.api_key:
        print("web-ingest: extraction LLM API key environment variable required.")
        sys.exit(1)

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "password")

    try:
        from codememory.web.crawler import crawl_url
        from codememory.web.pipeline import ResearchIngestionPipeline
        from codememory.core.connection import ConnectionManager
        from codememory.core.entity_extraction import EntityExtractionService

        # Detect format: PDF files (local or URL ending in .pdf) skip crawling
        is_pdf = url.lower().endswith(".pdf")
        is_local_file = os.path.isfile(url)

        if is_pdf or is_local_file:
            fmt = "pdf"
            if is_local_file:
                content_path = url
                content_text = ""
                print(f"web-ingest: Processing PDF {content_path}...")
            else:
                # Remote PDF URL — download first
                import httpx
                import tempfile
                print(f"web-ingest: Downloading PDF {url}...")
                resp = httpx.get(url, follow_redirects=True, timeout=60.0)
                resp.raise_for_status()
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                    f.write(resp.content)
                    content_path = f.name
                content_text = ""
                print(f"web-ingest: Processing PDF {content_path}...")
        else:
            # Web URL — crawl via Crawl4AI
            fmt = "markdown"
            content_path = None
            print(f"web-ingest: Crawling {url}...")
            content_text = asyncio.run(crawl_url(url))
            print(f"web-ingest: Got {len(content_text)} chars of markdown.")

        conn = ConnectionManager(neo4j_uri, neo4j_user, password)
        embedder = build_embedding_service("web")
        extractor = EntityExtractionService(
            api_key=extraction_llm.api_key,
            model=extraction_llm.model,
            provider=extraction_llm.provider,
            base_url=extraction_llm.base_url,
        )
        pipeline = ResearchIngestionPipeline(conn, embedder, extractor)

        source: dict = {
            "type": "report",
            "content": content_text,
            "project_id": "cli",
            "session_id": f"web-ingest-{url}",
            "source_agent": "user",
            "title": url,
            "research_question": None,
            "findings": [],
            "citations": [{"url": url, "title": url, "snippet": ""}],
            "ingestion_mode": "manual",
            "format": fmt,
        }
        if is_pdf or is_local_file:
            source["path"] = content_path if is_local_file else content_path

        result = pipeline.ingest(source)
        print(f"web-ingest: Done. {result.get('chunks', 0)} chunks ingested.")
        conn.driver.close()
    except Exception as e:
        print(f"web-ingest failed: {e}")
        sys.exit(1)


def cmd_web_search(args: argparse.Namespace) -> None:
    """Search web research memory (not yet implemented)."""
    print("web-search: Not yet implemented.")
    sys.exit(0)


def _resolve_scheduler_dependencies() -> tuple[Any, Any, str]:
    """Build the shared dependencies required by research scheduler commands."""
    from codememory.core.extraction_llm import resolve_extraction_llm_config  # noqa: PLC0415
    from codememory.core.runtime_embedding import build_embedding_service  # noqa: PLC0415

    extraction_llm = resolve_extraction_llm_config()
    brave_api_key = os.getenv("BRAVE_SEARCH_API_KEY") or os.getenv("BRAVE_API_KEY")
    if not extraction_llm.api_key:
        print("web-schedule: extraction LLM API key environment variable required.")
        sys.exit(1)
    if not brave_api_key:
        print("web-schedule: BRAVE_SEARCH_API_KEY or BRAVE_API_KEY environment variable required.")
        sys.exit(1)

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "password")

    from codememory.core.connection import ConnectionManager  # noqa: PLC0415
    from codememory.core.entity_extraction import EntityExtractionService  # noqa: PLC0415
    from codememory.web.pipeline import ResearchIngestionPipeline  # noqa: PLC0415

    conn = ConnectionManager(neo4j_uri, neo4j_user, password)
    try:
        embedder = build_embedding_service("web")
    except ValueError as exc:
        print(f"web-schedule: {exc}")
        sys.exit(1)
    extractor = EntityExtractionService(
        api_key=extraction_llm.api_key,
        model=extraction_llm.model,
        provider=extraction_llm.provider,
        base_url=extraction_llm.base_url,
    )
    pipeline = ResearchIngestionPipeline(conn, embedder, extractor)
    return pipeline, extraction_llm, brave_api_key


def _coerce_extraction_llm_config(value: Any) -> Any:
    """Accept both the new config object and the legacy raw API-key string."""
    if hasattr(value, "api_key") and hasattr(value, "model"):
        return value

    from codememory.core.extraction_llm import resolve_extraction_llm_config  # noqa: PLC0415

    if isinstance(value, str):
        return resolve_extraction_llm_config(api_key=value)
    return resolve_extraction_llm_config()


def cmd_web_schedule(args: argparse.Namespace) -> None:
    """Create a recurring research schedule."""
    from codememory.core.scheduler import ResearchScheduler  # noqa: PLC0415

    pipeline, extraction_llm, brave_api_key = _resolve_scheduler_dependencies()
    extraction_llm = _coerce_extraction_llm_config(extraction_llm)
    scheduler = ResearchScheduler(
        connection_manager=pipeline._conn,  # type: ignore[attr-defined]
        extraction_llm_api_key=extraction_llm.api_key,
        extraction_llm_model=extraction_llm.model,
        extraction_llm_provider=extraction_llm.provider,
        extraction_llm_base_url=extraction_llm.base_url,
        brave_api_key=brave_api_key,
        pipeline=pipeline,
    )
    try:
        schedule_id = scheduler.create_schedule(
            template=args.template,
            variables=args.variables,
            cron_expr=args.cron_expr,
            project_id=args.project_id,
            max_runs_per_day=args.max_runs_per_day,
        )
        print(f"web-schedule: created schedule {schedule_id}")
    except Exception as e:
        print(f"web-schedule failed: {e}")
        sys.exit(1)
    finally:
        scheduler.close()


def cmd_web_run_research(args: argparse.Namespace) -> None:
    """Run a scheduled or ad hoc research session immediately."""
    from codememory.core.scheduler import ResearchScheduler  # noqa: PLC0415

    if not args.schedule_id and not (args.project_id and args.template):
        print(
            "web-run-research: provide --schedule-id or "
            "(--project-id and --template, optionally --variables)."
        )
        sys.exit(1)

    pipeline, extraction_llm, brave_api_key = _resolve_scheduler_dependencies()
    extraction_llm = _coerce_extraction_llm_config(extraction_llm)
    scheduler = ResearchScheduler(
        connection_manager=pipeline._conn,  # type: ignore[attr-defined]
        extraction_llm_api_key=extraction_llm.api_key,
        extraction_llm_model=extraction_llm.model,
        extraction_llm_provider=extraction_llm.provider,
        extraction_llm_base_url=extraction_llm.base_url,
        brave_api_key=brave_api_key,
        pipeline=pipeline,
        start_scheduler=False,
    )
    try:
        result = scheduler.run_research_session(
            schedule_id=args.schedule_id,
            ad_hoc_template=args.template,
            ad_hoc_variables=args.variables,
            project_id=args.project_id,
        )
        print(f"web-run-research: {json.dumps(result)}")
    except Exception as e:
        print(f"web-run-research failed: {e}")
        sys.exit(1)
    finally:
        scheduler.close()


def cmd_chat_init(args: argparse.Namespace) -> None:
    """Initialize conversation memory: create vector indexes at correct dimensions.

    Calls setup_database() to create indexes (if absent), then
    fix_vector_index_dimensions() to drop-and-recreate research_embeddings
    and chat_embeddings at 768d in case they exist at the wrong 3072d.
    """
    from dotenv import load_dotenv  # noqa: PLC0415

    load_dotenv()

    neo4j_uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "")

    from codememory.core.connection import ConnectionManager  # noqa: PLC0415

    conn = ConnectionManager(neo4j_uri, neo4j_user, password)
    try:
        conn.setup_database()
        print("chat-init: Vector indexes and constraints created (or already exist).")
        conn.fix_vector_index_dimensions()
        print(
            "chat-init: research_embeddings and chat_embeddings reset to 768d. Done."
        )
    finally:
        conn.driver.close()


def cmd_chat_ingest(args: argparse.Namespace) -> None:
    """Ingest conversation turns from a JSONL/JSON file or stdin.

    Reads turns from args.source (file path), or stdin if args.source is '-'
    or None. Applies --project-id, --session-id, --source-agent as defaults.
    Calls setup_database() automatically before ingesting.

    Input formats:
        JSONL: one turn object per line.
        JSON: a JSON array of turn objects.

    Each turn must have at minimum: role, content.
    turn_index is auto-assigned (0-based line position) if absent.
    session_id comes from --session-id flag if not in turn data.
    project_id comes from --project-id flag if not in turn data.
    """
    import json  # noqa: PLC0415
    import sys  # noqa: PLC0415
    import time  # noqa: PLC0415

    from dotenv import load_dotenv  # noqa: PLC0415

    load_dotenv()

    neo4j_uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "")
    from codememory.core.extraction_llm import resolve_extraction_llm_config  # noqa: PLC0415
    from codememory.core.runtime_embedding import build_embedding_service  # noqa: PLC0415

    extraction_llm = resolve_extraction_llm_config()

    from codememory.core.connection import ConnectionManager  # noqa: PLC0415
    from codememory.core.entity_extraction import EntityExtractionService  # noqa: PLC0415
    from codememory.chat.pipeline import ConversationIngestionPipeline  # noqa: PLC0415

    # Auto-initialize indexes (setup_database is idempotent, IF NOT EXISTS)
    conn = ConnectionManager(neo4j_uri, neo4j_user, password)
    conn.setup_database()

    embedder = build_embedding_service("chat")
    extractor = EntityExtractionService(
        api_key=extraction_llm.api_key or "",
        model=extraction_llm.model,
        provider=extraction_llm.provider,
        base_url=extraction_llm.base_url,
    )
    pipeline = ConversationIngestionPipeline(conn, embedder, extractor)

    # Determine input source
    source_path = getattr(args, "source", None)
    if source_path and source_path != "-":
        try:
            with open(source_path, encoding="utf-8") as f:
                raw = f.read().strip()
        except OSError as e:
            print(f"chat-ingest: Cannot open {source_path}: {e}", file=sys.stderr)
            sys.exit(1)

        # Detect JSON array vs JSONL
        if raw.startswith("["):
            try:
                turns_raw = json.loads(raw)
            except json.JSONDecodeError as e:
                print(f"chat-ingest: Invalid JSON: {e}", file=sys.stderr)
                sys.exit(1)
        else:
            turns_raw = []
            for line_num, line in enumerate(raw.splitlines(), start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    turns_raw.append(json.loads(line))
                except json.JSONDecodeError as e:
                    print(
                        f"chat-ingest: Invalid JSON on line {line_num}: {e}",
                        file=sys.stderr,
                    )
                    sys.exit(1)
    else:
        # Stdin JSONL
        turns_raw = []
        for line_num, line in enumerate(sys.stdin, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                turns_raw.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(
                    f"chat-ingest: Invalid JSON on stdin line {line_num}: {e}",
                    file=sys.stderr,
                )
                sys.exit(1)

    if not turns_raw:
        print("chat-ingest: No turns found in input.")
        conn.driver.close()
        return

    project_id_flag = getattr(args, "project_id", None)
    session_id_flag = getattr(args, "session_id", None)
    source_agent_flag = getattr(args, "source_agent", None)

    turns_ingested = 0
    turns_skipped = 0
    total_entities = 0
    start_time = time.monotonic()

    print(f"chat-ingest: Processing {len(turns_raw)} turn(s)...")

    for auto_index, turn_raw in enumerate(turns_raw):
        # Apply flag defaults where turn data is absent
        turn: dict = dict(turn_raw)
        turn.setdefault("project_id", project_id_flag or "cli")
        # --session-id flag OVERRIDES per-turn session_id if provided
        if session_id_flag:
            turn["session_id"] = session_id_flag
        elif "session_id" not in turn:
            turn["session_id"] = f"chat-ingest-{auto_index}"
        if source_agent_flag:
            turn.setdefault("source_agent", source_agent_flag)
        # Auto-assign turn_index if absent
        if "turn_index" not in turn:
            turn["turn_index"] = auto_index
        turn.setdefault("source_key", "chat_cli")
        turn.setdefault("ingestion_mode", "manual")

        try:
            result = pipeline.ingest(turn)
            turns_ingested += 1
            total_entities += result.get("entities_count", 0)
            print(
                f"  [{auto_index + 1}/{len(turns_raw)}] "
                f"turn_index={result['turn_index']} role={result['role']} "
                f"entities={result['entities_count']} embedded={result['embedded']}"
            )
        except ValueError as e:
            print(f"  [{auto_index + 1}] SKIPPED: {e}", file=sys.stderr)
            turns_skipped += 1
        except Exception as e:
            print(f"  [{auto_index + 1}] ERROR: {e}", file=sys.stderr)
            turns_skipped += 1

    duration_s = time.monotonic() - start_time
    conn.driver.close()

    print(
        f"\nchat-ingest: Done. "
        f"turns_ingested={turns_ingested} "
        f"turns_skipped={turns_skipped} "
        f"entities_extracted={total_entities} "
        f"duration_s={duration_s:.1f}"
    )


def cmd_chat_search(args: argparse.Namespace) -> None:
    """Search conversation memory by semantic similarity.

    Embeds the query via Gemini then queries the chat_embeddings vector index.
    Outputs results as a formatted table to stdout.

    Args:
        args: Parsed arguments with query, project_id, limit, role.
    """
    import json as _json  # noqa: PLC0415
    import sys  # noqa: PLC0415

    from dotenv import load_dotenv  # noqa: PLC0415

    load_dotenv()

    neo4j_uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "")
    from codememory.core.connection import ConnectionManager  # noqa: PLC0415
    from codememory.core.runtime_embedding import build_embedding_service  # noqa: PLC0415

    query = args.query
    project_id = getattr(args, "project_id", None)
    role_filter = getattr(args, "role", None)
    limit = getattr(args, "limit", 10)
    output_json = getattr(args, "json", False)

    conn = ConnectionManager(neo4j_uri, neo4j_user, password)
    embedder = build_embedding_service("chat")

    try:
        query_embedding = embedder.embed(query)

        with conn.session() as session:
            cypher = (
                "CALL db.index.vector.queryNodes("
                "  'chat_embeddings', $limit, $embedding"
                ") YIELD node, score "
                "WHERE ($project_id IS NULL OR node.project_id = $project_id)"
                "  AND ($role IS NULL OR node.role = $role) "
                "RETURN "
                "    node.session_id     AS session_id, "
                "    node.turn_index     AS turn_index, "
                "    node.role           AS role, "
                "    node.content        AS content, "
                "    node.source_agent   AS source_agent, "
                "    node.timestamp      AS timestamp, "
                "    score "
                "ORDER BY score DESC "
                "LIMIT $limit"
            )
            result = session.run(
                cypher,
                embedding=query_embedding,
                project_id=project_id,
                role=role_filter,
                limit=limit,
            )
            rows = [dict(r) for r in result]

        if output_json:
            print(_json.dumps(rows, indent=2, default=str))
        else:
            if not rows:
                print(f"chat-search: No results for query: {query!r}")
            else:
                print(f"chat-search: {len(rows)} result(s) for {query!r}\n")
                for i, row in enumerate(rows, start=1):
                    session_id = row.get("session_id", "?")
                    turn_index = row.get("turn_index", "?")
                    role = row.get("role", "?")
                    content = str(row.get("content", ""))
                    # Truncate long content for display
                    display_content = content[:120] + "..." if len(content) > 120 else content
                    score = row.get("score", 0.0)
                    print(
                        f"  {i}. [{role}] session={session_id} turn={turn_index} "
                        f"score={score:.4f}"
                    )
                    print(f"     {display_content}")
                    print()

    except Exception as e:
        print(f"chat-search: Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.driver.close()


def _temporal_backfill_statements() -> list[tuple[str, str, dict[str, Any]]]:
    """Return ordered temporal backfill Cypher statements.

    The migration is idempotent because every statement guards on
    `WHERE r.valid_from IS NULL`.
    """
    legacy_timestamp = "2026-01-01T00:00:00+00:00"
    migration_timestamp = "2026-03-25T00:00:00+00:00"
    memory_tail = (
        "SET r.valid_from = coalesce(m.ingested_at, $legacy_timestamp),\n"
        "    r.valid_to = null,\n"
        "    r.confidence = 0.5,\n"
        "    r.support_count = 1,\n"
        "    r.contradiction_count = 0"
    )
    return [
        (
            "ABOUT",
            "MATCH (m)-[r:ABOUT]->()\n"
            "WHERE r.valid_from IS NULL\n"
            f"{memory_tail}",
            {"legacy_timestamp": legacy_timestamp},
        ),
        (
            "MENTIONS",
            "MATCH (m)-[r:MENTIONS]->()\n"
            "WHERE r.valid_from IS NULL\n"
            f"{memory_tail}",
            {"legacy_timestamp": legacy_timestamp},
        ),
        (
            "BELONGS_TO",
            "MATCH (m)-[r:BELONGS_TO]->()\n"
            "WHERE r.valid_from IS NULL\n"
            f"{memory_tail}",
            {"legacy_timestamp": legacy_timestamp},
        ),
        (
            "HAS_CHUNK",
            "MATCH (m:Memory:Research:Report)-[r:HAS_CHUNK]->()\n"
            "WHERE r.valid_from IS NULL\n"
            f"{memory_tail}",
            {"legacy_timestamp": legacy_timestamp},
        ),
        (
            "PART_OF_RESEARCH",
            "MATCH (m:Memory:Research:Chunk)-[r:PART_OF]->(:Memory:Research:Report)\n"
            "WHERE r.valid_from IS NULL\n"
            f"{memory_tail}",
            {"legacy_timestamp": legacy_timestamp},
        ),
        (
            "PART_OF_CONVERSATION",
            "MATCH (m:Memory:Conversation:Turn)-[r:PART_OF]->(:Memory:Conversation:Session)\n"
            "WHERE r.valid_from IS NULL\n"
            f"{memory_tail}",
            {"legacy_timestamp": legacy_timestamp},
        ),
        (
            "HAS_TURN",
            "MATCH (m:Memory:Conversation:Session)-[r:HAS_TURN]->()\n"
            "WHERE r.valid_from IS NULL\n"
            "SET r.valid_from = coalesce(m.started_at, m.ingested_at, $legacy_timestamp),\n"
            "    r.valid_to = null,\n"
            "    r.confidence = 0.5,\n"
            "    r.support_count = 1,\n"
            "    r.contradiction_count = 0",
            {"legacy_timestamp": legacy_timestamp},
        ),
        (
            "CITES",
            "MATCH (m:Memory:Research:Finding)-[r:CITES]->()\n"
            "WHERE r.valid_from IS NULL\n"
            f"{memory_tail}",
            {"legacy_timestamp": legacy_timestamp},
        ),
        (
            "DEFINES",
            "MATCH ()-[r:DEFINES]->()\n"
            "WHERE r.valid_from IS NULL\n"
            "SET r.valid_from = $migration_timestamp,\n"
            "    r.valid_to = null,\n"
            "    r.confidence = 0.5,\n"
            "    r.support_count = 1,\n"
            "    r.contradiction_count = 0",
            {"migration_timestamp": migration_timestamp},
        ),
        (
            "HAS_METHOD",
            "MATCH ()-[r:HAS_METHOD]->()\n"
            "WHERE r.valid_from IS NULL\n"
            "SET r.valid_from = $migration_timestamp,\n"
            "    r.valid_to = null,\n"
            "    r.confidence = 0.5,\n"
            "    r.support_count = 1,\n"
            "    r.contradiction_count = 0",
            {"migration_timestamp": migration_timestamp},
        ),
        (
            "DESCRIBES",
            "MATCH ()-[r:DESCRIBES]->()\n"
            "WHERE r.valid_from IS NULL\n"
            "SET r.valid_from = $migration_timestamp,\n"
            "    r.valid_to = null,\n"
            "    r.confidence = 0.5,\n"
            "    r.support_count = 1,\n"
            "    r.contradiction_count = 0",
            {"migration_timestamp": migration_timestamp},
        ),
        (
            "IMPORTS",
            "MATCH ()-[r:IMPORTS]->()\n"
            "WHERE r.valid_from IS NULL\n"
            "SET r.valid_from = $migration_timestamp,\n"
            "    r.valid_to = null,\n"
            "    r.confidence = 0.5,\n"
            "    r.support_count = 1,\n"
            "    r.contradiction_count = 0",
            {"migration_timestamp": migration_timestamp},
        ),
        (
            "CALLS",
            "MATCH ()-[r:CALLS]->()\n"
            "WHERE r.valid_from IS NULL\n"
            "SET r.valid_from = $migration_timestamp,\n"
            "    r.valid_to = null,\n"
            "    r.confidence = 0.5,\n"
            "    r.support_count = 1,\n"
            "    r.contradiction_count = 0",
            {"migration_timestamp": migration_timestamp},
        ),
        (
            "PART_OF_PR",
            "MATCH ()-[r:PART_OF_PR]->()\n"
            "WHERE r.valid_from IS NULL\n"
            "SET r.valid_from = $migration_timestamp,\n"
            "    r.valid_to = null,\n"
            "    r.confidence = 0.5,\n"
            "    r.support_count = 1,\n"
            "    r.contradiction_count = 0",
            {"migration_timestamp": migration_timestamp},
        ),
    ]


def cmd_migrate_temporal(args: argparse.Namespace) -> None:
    """Backfill temporal fields on existing graph relationships."""
    from codememory.core.connection import ConnectionManager  # noqa: PLC0415

    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "password")

    conn = ConnectionManager(uri, user, password)
    try:
        with conn.session() as session:
            for rel_name, cypher, params in _temporal_backfill_statements():
                result = session.run(cypher, **params)
                summary = result.consume()
                properties_set = summary.counters.properties_set
                print(
                    f"migrate-temporal: {rel_name} backfill complete "
                    f"({properties_set} properties set)."
                )
        print(
            "migrate-temporal: backfill complete. "
            f"{len(_temporal_backfill_statements())} relationship types processed."
        )
    except neo4j.exceptions.ServiceUnavailable:
        print("migrate-temporal: Neo4j unavailable — is Docker running?")
        sys.exit(1)
    finally:
        conn.driver.close()


def main():
    parser = argparse.ArgumentParser(
        description="Agentic Memory: Structural Code Graph with Neo4j and MCP",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Quick Start:
  codememory init              # Initialize in current repo (interactive wizard)
  codememory status            # Show repository status

Commands:
  codememory index             # One-time full index
  codememory watch             # Continuous monitoring
  codememory serve             # Start MCP server
  codememory search <query>    # Test semantic search
  codememory git-init          # Enable git graph integration
  codememory git-sync          # Sync local git history into Neo4j
  codememory git-status        # Show git graph sync status

For more information, visit: https://github.com/jarmen423/agentic-memory
        """,
    )

    parser.add_argument(
        "--prompted",
        metavar="PROMPT_PREFIX",
        help=(
            "Annotate the latest tool-use burst as prompted. "
            "Example: --prompted \"check our auth\""
        ),
    )
    parser.add_argument(
        "--unprompted",
        metavar="PROMPT_PREFIX",
        help=(
            "Annotate the latest tool-use burst as unprompted. "
            "Example: --unprompted \"check our auth\""
        ),
    )
    parser.add_argument(
        "--annotation-id",
        type=str,
        help="Optional custom annotation identifier.",
    )
    parser.add_argument(
        "--tool-call-id",
        type=int,
        action="append",
        help="Annotate specific tool call ID(s) directly (repeatable).",
    )
    parser.add_argument(
        "--client",
        type=str,
        help="Optional client filter (matches CODEMEMORY_CLIENT recorded in telemetry).",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=45,
        help="How long to wait for a response burst to settle before giving up.",
    )
    parser.add_argument(
        "--idle-seconds",
        type=int,
        default=3,
        help="Silence window used to consider a response burst complete.",
    )
    parser.add_argument(
        "--lookback-seconds",
        type=int,
        default=180,
        help="How far back to search for unannotated tool calls.",
    )
    parser.add_argument(
        "--recent-seconds",
        type=int,
        default=90,
        help="Maximum age of last tool call for matching a response burst.",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: init (interactive setup wizard)
    init_parser = subparsers.add_parser(
        "init", help="Initialize Agentic Memory in current repository (interactive wizard)"
    )

    # Command: status
    status_parser = subparsers.add_parser("status", help="Show repository status and statistics")
    status_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output",
    )

    # Command: index (one-time full pipeline)
    index_parser = subparsers.add_parser("index", help="Run a one-time full pipeline ingestion")
    index_parser.add_argument("--quiet", "-q", action="store_true", help="Suppress progress output")
    index_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output",
    )

    # Command: watch (continuous monitoring)
    watch_parser = subparsers.add_parser("watch", help="Start continuous ingestion and monitoring")
    watch_parser.add_argument(
        "--no-scan",
        action="store_true",
        help="Skip initial full scan (start watching immediately)",
    )
    watch_parser.add_argument(
        "--env-file",
        type=str,
        help="Optional .env file to load before starting the watcher",
    )

    # Command: serve (MCP server)
    serve_parser = subparsers.add_parser("serve", help="Start the MCP server")
    serve_parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    serve_parser.add_argument(
        "--repo",
        type=str,
        help="Repository root to use for .codememory/config.json resolution",
    )
    serve_parser.add_argument(
        "--env-file",
        type=str,
        help="Optional .env file to load before starting the server",
    )

    # Command: search (test semantic search)
    search_parser = subparsers.add_parser(
        "search", help="Test semantic search (requires OpenAI API key)"
    )
    search_parser.add_argument("query", help="Natural language search query")
    search_parser.add_argument(
        "--limit", "-l", type=int, default=5, help="Maximum results to return"
    )
    search_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output",
    )

    # Command: deps (file dependency checks)
    deps_parser = subparsers.add_parser(
        "deps", help="Show direct dependency relationships for a file"
    )
    deps_parser.add_argument("path", help="Relative path to a file in the graph")
    deps_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output",
    )

    # Command: impact (transitive dependency impact)
    impact_parser = subparsers.add_parser(
        "impact", help="Analyze transitive impact of changing a file"
    )
    impact_parser.add_argument("path", help="Relative path to a file in the graph")
    impact_parser.add_argument(
        "--max-depth",
        type=int,
        default=3,
        help="Maximum dependency depth to traverse",
    )
    impact_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output",
    )

    # Command: git-init
    git_init_parser = subparsers.add_parser(
        "git-init", help="Enable git graph configuration and create repo metadata nodes"
    )
    git_init_parser.add_argument(
        "--repo",
        type=str,
        help="Repository root path (defaults to detected current repository)",
    )
    git_init_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output",
    )

    # Command: git-sync
    git_sync_parser = subparsers.add_parser(
        "git-sync", help="Sync local git commit history into Git* graph labels"
    )
    git_sync_parser.add_argument(
        "--repo",
        type=str,
        help="Repository root path (defaults to detected current repository)",
    )
    git_sync_parser.add_argument(
        "--full",
        action="store_true",
        help="Run full history sync instead of incremental checkpoint sync",
    )
    git_sync_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output",
    )

    # Command: git-status
    git_status_parser = subparsers.add_parser(
        "git-status", help="Show git graph setup and sync checkpoint status"
    )
    git_status_parser.add_argument(
        "--repo",
        type=str,
        help="Repository root path (defaults to detected current repository)",
    )
    git_status_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output",
    )

    # Web Research commands (Phase 2 stubs)
    subparsers.add_parser("web-init", help="Initialize web research module")
    web_ingest_parser = subparsers.add_parser("web-ingest", help="Ingest a web URL")
    web_ingest_parser.add_argument("url", nargs="?", help="URL to ingest")
    web_search_parser = subparsers.add_parser("web-search", help="Search web research memory")
    web_search_parser.add_argument("query", nargs="?", help="Search query")
    web_schedule_parser = subparsers.add_parser(
        "web-schedule",
        help="Create a recurring research schedule",
    )
    web_schedule_parser.add_argument(
        "--template",
        required=True,
        help="Research query template with {variable} placeholders",
    )
    web_schedule_parser.add_argument(
        "--variables",
        nargs="+",
        required=True,
        help="Variable names to fill via the scheduler LLM",
    )
    web_schedule_parser.add_argument(
        "--cron",
        dest="cron_expr",
        required=True,
        help="Cron expression, for example '0 9 * * 1'",
    )
    web_schedule_parser.add_argument(
        "--project-id",
        required=True,
        help="Project identifier for the schedule",
    )
    web_schedule_parser.add_argument(
        "--max-runs-per-day",
        type=int,
        default=5,
        help="Maximum number of successful runs allowed for this schedule",
    )
    web_run_research_parser = subparsers.add_parser(
        "web-run-research",
        help="Trigger a research run (scheduled or ad hoc)",
    )
    web_run_research_parser.add_argument(
        "--schedule-id",
        help="Existing schedule UUID to run immediately",
    )
    web_run_research_parser.add_argument(
        "--project-id",
        help="Project ID for an ad hoc research run",
    )
    web_run_research_parser.add_argument(
        "--template",
        help="Ad hoc research query template",
    )
    web_run_research_parser.add_argument(
        "--variables",
        nargs="+",
        help="Variable names to fill for an ad hoc research run",
    )
    subparsers.add_parser(
        "migrate-temporal",
        help="Backfill temporal fields on all existing relationships (safe to re-run)",
    )

    # Conversation Memory commands (Phase 4)
    subparsers.add_parser("chat-init", help="Initialize conversation memory module")
    chat_ingest_parser = subparsers.add_parser("chat-ingest", help="Ingest conversation logs")
    chat_ingest_parser.add_argument("source", nargs="?", help="Path to conversation log (or '-' for stdin)")
    chat_ingest_parser.add_argument(
        "--project-id",
        type=str,
        dest="project_id",
        required=True,
        help="Project ID to apply to all turns in the input",
    )
    chat_ingest_parser.add_argument(
        "--session-id",
        type=str,
        dest="session_id",
        help="Session ID to apply to all turns (overrides per-turn session_id)",
    )
    chat_ingest_parser.add_argument(
        "--source-agent",
        type=str,
        dest="source_agent",
        help="Source agent name (e.g. 'claude') applied if not in turn data",
    )

    # Command: chat-search
    chat_search_parser = subparsers.add_parser(
        "chat-search",
        help="Search conversation memory by semantic similarity",
    )
    chat_search_parser.add_argument("query", help="Natural language search query")
    chat_search_parser.add_argument(
        "--project-id",
        type=str,
        dest="project_id",
        help="Filter results to a specific project",
    )
    chat_search_parser.add_argument(
        "--role",
        type=str,
        choices=["user", "assistant"],
        help="Filter results by role (user or assistant)",
    )
    chat_search_parser.add_argument(
        "--limit",
        "-l",
        type=int,
        default=10,
        help="Maximum number of results to return (default: 10)",
    )
    chat_search_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output",
    )

    args = parser.parse_args()

    if args.prompted and args.unprompted:
        _exit_with_error(
            args,
            error="Use either --prompted or --unprompted, not both.",
            human_lines=["❌ Use either --prompted or --unprompted, not both."],
        )

    if args.prompted or args.unprompted:
        if args.command:
            _exit_with_error(
                args,
                error="Annotation flags cannot be combined with subcommands.",
                human_lines=[
                    "❌ Annotation flags cannot be combined with subcommands.",
                    "   Use: codememory --unprompted \"check our auth\"",
                ],
            )

        mode = "prompted" if args.prompted else "unprompted"
        prompt_prefix = args.prompted or args.unprompted or ""
        cmd_annotate_interaction(
            args,
            annotation_mode=mode,
            prompt_prefix=prompt_prefix,
        )
        return

    # Dispatch to command handlers
    if args.command == "init":
        cmd_init(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "index":
        cmd_index(args)
    elif args.command == "watch":
        cmd_watch(args)
    elif args.command == "serve":
        cmd_serve(args)
    elif args.command == "search":
        cmd_search(args)
    elif args.command == "deps":
        cmd_deps(args)
    elif args.command == "impact":
        cmd_impact(args)
    elif args.command == "git-init":
        cmd_git_init(args)
    elif args.command == "git-sync":
        cmd_git_sync(args)
    elif args.command == "git-status":
        cmd_git_status(args)
    elif args.command == "web-init":
        cmd_web_init(args)
    elif args.command == "web-ingest":
        cmd_web_ingest(args)
    elif args.command == "web-search":
        cmd_web_search(args)
    elif args.command == "web-schedule":
        cmd_web_schedule(args)
    elif args.command == "web-run-research":
        cmd_web_run_research(args)
    elif args.command == "migrate-temporal":
        cmd_migrate_temporal(args)
    elif args.command == "chat-init":
        cmd_chat_init(args)
    elif args.command == "chat-ingest":
        cmd_chat_ingest(args)
    elif args.command == "chat-search":
        cmd_chat_search(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
