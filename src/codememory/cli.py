# Load .env BEFORE any other imports that might need environment variables
from dotenv import load_dotenv
load_dotenv()

import argparse
import sys
import os
from pathlib import Path

from codememory.ingestion.watcher import start_continuous_watch
from codememory.ingestion.graph import KnowledgeGraphBuilder
from codememory.config import Config, find_repo_root, DEFAULT_CONFIG


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


def cmd_init(args):
    """Initialize Agentic Memory in the current repository."""
    repo_root = Path.cwd()

    # Check if already initialized
    config = Config(repo_root)
    if config.exists():
        print(f"⚠️  This repository is already initialized with Agentic Memory.")
        print(f"    Config location: {config.config_file}")
        print(f"\n   To reconfigure, edit the config file or delete .codememory/ and run init again.")
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
        neo4j_config["password"] = input("   Enter Neo4j password (default: password): ").strip() or "password"

    elif neo_choice == "2":
        print("\n☁️  Using Neo4j Aura (Cloud)")
        print("   Get your free instance at: https://neo4j.com/cloud/aura/")
        neo4j_config["uri"] = input("   Enter Aura connection URL (neo4j+s://...): ").strip()
        neo4j_config["user"] = "neo4j"
        neo4j_config["password"] = input("   Enter Aura password: ").strip()

    elif neo_choice == "3":
        print("\n🔗 Custom Neo4j URL")
        neo4j_config["uri"] = input("   Enter Neo4j URI: ").strip()
        neo4j_config["user"] = input("   Enter Neo4j username (default: neo4j): ").strip() or "neo4j"
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
    extensions_input = input("   Enter extensions (comma-separated, or press Enter for defaults): ").strip()
    if extensions_input:
        indexing_config = DEFAULT_CONFIG["indexing"].copy()
        indexing_config["extensions"] = [e.strip() if e.strip().startswith(".") else f".{e.strip()}"
                                         for e in extensions_input.split(",")]
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

    print(f"✅ Configuration saved to: {config.config_file}")

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

            print("\n🔍 Testing Neo4j connection...")
            builder = KnowledgeGraphBuilder(
                uri=neo4j_cfg["uri"],
                user=neo4j_cfg["user"],
                password=neo4j_cfg["password"],
                openai_key=openai_key,
                repo_root=repo_root,
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
            )

            metrics = builder.run_pipeline(repo_root)
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
    repo_root = find_repo_root()
    config = Config(repo_root)

    if not config.exists():
        print(f"❌ Agentic Memory is not initialized in this repository.")
        print(f"   Run 'codememory init' to get started.")
        return

    print(f"📊 Agentic Memory Status")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"Repository: {repo_root}")
    print(f"Config:     {config.config_file}")

    # Try to connect and get stats
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
            functions = session.run("MATCH (fn:Function) RETURN count(fn) as count").single()["count"]
            classes = session.run("MATCH (c:Class) RETURN count(c) as count").single()["count"]
            chunks = session.run("MATCH (ch:Chunk) RETURN count(ch) as count").single()["count"]

            print(f"\n📈 Graph Statistics:")
            print(f"   Files:     {files:,}")
            print(f"   Functions: {functions:,}")
            print(f"   Classes:   {classes:,}")
            print(f"   Chunks:    {chunks:,}")

            # Get last update
            last_update = session.run("""
                MATCH (f:File)
                RETURN max(f.last_updated) as last_updated
            """).single()["last_updated"]

            if last_update:
                print(f"   Last sync: {last_update}")

        builder.close()

    except (neo4j.exceptions.DatabaseError, neo4j.exceptions.ServiceUnavailable) as e:
        print(f"\n⚠️  Could not connect to Neo4j: {e}")
        print(f"   Make sure Neo4j is running and check your config.")


def cmd_index(args):
    """Run a one-time full pipeline ingestion."""
    repo_root = find_repo_root()
    config = Config(repo_root)

    if not config.exists():
        print(f"❌ Agentic Memory is not initialized in this repository.")
        print(f"   Run 'codememory init' to get started.")
        sys.exit(1)

    if not args.quiet:
        print(f"📂 Indexing repository: {repo_root}")

    neo4j_cfg = config.get_neo4j_config()
    openai_key = config.get_openai_key()

    builder = KnowledgeGraphBuilder(
        uri=neo4j_cfg["uri"],
        user=neo4j_cfg["user"],
        password=neo4j_cfg["password"],
        openai_key=openai_key,
        repo_root=repo_root,
    )

    try:
        metrics = builder.run_pipeline(repo_root)
        if not args.quiet:
            print(f"\n✅ Indexing complete!")
            print(f"   Processed {metrics['embedding_calls']} entities")
            print(f"   Cost: ${metrics['cost_usd']:.4f} USD")
    finally:
        builder.close()


def cmd_watch(args):
    """Start continuous file watching and ingestion."""
    repo_root = find_repo_root()
    config = Config(repo_root)

    if not config.exists():
        print(f"❌ Agentic Memory is not initialized in this repository.")
        print(f"   Run 'codememory init' to get started.")
        sys.exit(1)

    print(f"👀 Starting Observer on: {repo_root}")

    neo4j_cfg = config.get_neo4j_config()
    openai_key = config.get_openai_key()

    start_continuous_watch(
        repo_path=repo_root,
        neo4j_uri=neo4j_cfg["uri"],
        neo4j_user=neo4j_cfg["user"],
        neo4j_password=neo4j_cfg["password"],
        initial_scan=not args.no_scan,
    )


def cmd_serve(args):
    """Start the MCP server."""
    from codememory.server.app import run_server

    repo_root = find_repo_root()
    config = Config(repo_root)

    if not config.exists():
        print(f"⚠️  No local config found, using environment variables")

    print(f"🧠 Starting MCP Interface on port {args.port}")
    run_server(port=args.port)


def cmd_search(args):
    """Run a semantic search query (for testing)."""
    repo_root = find_repo_root()
    config = Config(repo_root)

    if not config.exists():
        print(f"❌ Agentic Memory is not initialized in this repository.")
        print(f"   Run 'codememory init' to get started.")
        sys.exit(1)

    neo4j_cfg = config.get_neo4j_config()
    openai_key = config.get_openai_key()

    if not openai_key:
        print(f"❌ OpenAI API key not configured.")
        print(f"   Set OPENAI_API_KEY environment variable or add it to .codememory/config.json")
        sys.exit(1)

    builder = KnowledgeGraphBuilder(
        uri=neo4j_cfg["uri"],
        user=neo4j_cfg["user"],
        password=neo4j_cfg["password"],
        openai_key=openai_key,
    )

    try:
        results = builder.semantic_search(args.query, limit=args.limit)

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
    finally:
        builder.close()


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

For more information, visit: https://github.com/jarmen423/agentic-memory
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: init (interactive setup wizard)
    init_parser = subparsers.add_parser(
        "init", help="Initialize Agentic Memory in current repository (interactive wizard)"
    )

    # Command: status
    status_parser = subparsers.add_parser(
        "status", help="Show repository status and statistics"
    )

    # Command: index (one-time full pipeline)
    index_parser = subparsers.add_parser(
        "index", help="Run a one-time full pipeline ingestion"
    )
    index_parser.add_argument(
        "--quiet", "-q", action="store_true", help="Suppress progress output"
    )

    # Command: watch (continuous monitoring)
    watch_parser = subparsers.add_parser(
        "watch", help="Start continuous ingestion and monitoring"
    )
    watch_parser.add_argument(
        "--no-scan",
        action="store_true",
        help="Skip initial full scan (start watching immediately)",
    )

    # Command: serve (MCP server)
    serve_parser = subparsers.add_parser("serve", help="Start the MCP server")
    serve_parser.add_argument("--port", type=int, default=8000, help="Port to listen on")

    # Command: search (test semantic search)
    search_parser = subparsers.add_parser(
        "search", help="Test semantic search (requires OpenAI API key)"
    )
    search_parser.add_argument("query", help="Natural language search query")
    search_parser.add_argument(
        "--limit", "-l", type=int, default=5, help="Maximum results to return"
    )

    args = parser.parse_args()

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
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
