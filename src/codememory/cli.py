# Load .env BEFORE any other imports that might need environment variables
from dotenv import load_dotenv
load_dotenv()

import argparse
import sys
import os
from pathlib import Path

from codememory.ingestion.watcher import start_continuous_watch
# We will import the server runner later

def main():
    parser = argparse.ArgumentParser(description="Agentic Memory: Structural Code Graph")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Command: watch
    watch_parser = subparsers.add_parser("watch", help="Start continuous ingestion")
    watch_parser.add_argument("path", help="Path to the repository to watch")
    watch_parser.add_argument("--neo4j-uri", default=os.getenv("NEO4J_URI", "bolt://localhost:7687"))
    watch_parser.add_argument("--neo4j-user", default=os.getenv("NEO4J_USER", "neo4j"))
    watch_parser.add_argument("--neo4j-password", default=os.getenv("NEO4J_PASSWORD", "password"))

    # Command: serve
    serve_parser = subparsers.add_parser("serve", help="Start the MCP Agent Interface")
    serve_parser.add_argument("--port", type=int, default=8000)

    args = parser.parse_args()

    if args.command == "watch":
        repo_path = Path(args.path).resolve()
        if not repo_path.exists():
            print(f"❌ Error: Path {repo_path} does not exist.")
            sys.exit(1)
        
        print(f"👀 Starting Observer on: {repo_path}")
        start_continuous_watch(
            repo_path=repo_path,
            neo4j_uri=args.neo4j_uri,
            neo4j_user=args.neo4j_user,
            neo4j_password=args.neo4j_password
        )

    elif args.command == "serve":
        from codememory.server.app import run_server
        print(f"🧠 Starting MCP Interface on port {args.port}")
        run_server(port=args.port)

    else:
        parser.print_help()

if __name__ == "__main__":
    main()