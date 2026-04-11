"""
CLI entry point for the agentic_memory package.

Provides the ``agentic-memory`` (and legacy ``codememory``) command-line interface
that operators, developers, and automation scripts use to configure, index, and
serve the Agentic Memory system.

Extended:
    All user-facing operations that don't require an AI agent are surfaced here:
    initializing the system in a repository, running one-time or continuous code
    indexing, querying the Neo4j knowledge graph, managing git-graph sync, ingesting
    conversation turns, scheduling web research, and annotating MCP tool-call
    telemetry for prompted/unprompted labeling.

    The MCP server itself is started via ``cmd_serve``, which delegates to
    ``agentic_memory.server.app``.

Role:
    User-facing control plane — not imported by any server or library code.
    All commands read configuration from ``.agentic-memory/config.json`` (falling
    back to legacy ``.codememory/config.json`` when needed) and talk directly to
    Neo4j plus the configured code embedding provider.

Dependencies:
    - Neo4j 5.18+ (graph + vector index storage)
    - Configured code embedding provider (Gemini by default for code embeddings)
    - agentic_memory.config (Config, find_repo_root)
    - agentic_memory.ingestion.graph (KnowledgeGraphBuilder)
    - agentic_memory.ingestion.git_graph (GitGraphIngestor)
    - agentic_memory.ingestion.watcher (continuous file watch)
    - agentic_memory.product.state (ProductStateStore)
    - agentic_memory.telemetry (TelemetryStore)

Key Technologies:
    argparse (subcommand routing), python-dotenv (.env loading),
    Neo4j Python driver, tree-sitter (via ingestion pipeline).
"""

from dotenv import load_dotenv

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

import neo4j

from agentic_memory.ingestion.git_graph import GitGraphIngestor
from agentic_memory.ingestion.graph import KnowledgeGraphBuilder
from agentic_memory.ingestion.parser import CodeParser
from agentic_memory.ingestion.python_call_analyzer import (
    PythonCallAnalyzer,
    PythonCallAnalyzerError,
)
from agentic_memory.ingestion.typescript_call_analyzer import (
    TypeScriptCallAnalyzer,
    TypeScriptCallAnalyzerError,
)
from agentic_memory.ingestion.watcher import start_continuous_watch
from agentic_memory.product.state import ProductStateStore
from agentic_memory.config import (
    CONFIG_DIR_NAME,
    LEGACY_CONFIG_DIR_NAME,
    Config,
    DEFAULT_CONFIG,
    find_repo_root,
)
from agentic_memory.core.runtime_embedding import resolve_embedding_runtime
from agentic_memory.telemetry import TelemetryStore, resolve_telemetry_db_path

PRIMARY_CLI_NAME = "agentic-memory"


def _command_example(*parts: str) -> str:
    """Build a human-facing command example with the preferred CLI name."""
    return " ".join([PRIMARY_CLI_NAME, *parts]).strip()


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
    """Load Agentic Memory runtime env vars from an explicit or namespaced file.

    Why this helper is strict about which dotenv files it touches:

    - Target repositories often already have an application-level ``.env`` for
      their own stack.
    - Those files may legitimately define generic variables such as
      ``EMBEDDING_PROVIDER`` that are unrelated to Agentic Memory.
    - If the CLI blindly loads ``<repo>/.env`` before runtime resolution, those
      generic variables can silently override ``.agentic-memory/config.json`` and
      make indexing talk to the wrong provider.

    To avoid cross-project configuration collisions, Agentic Memory only auto-
    loads env files that it owns:

    - explicit ``--env-file``
    - ``<repo>/.agentic-memory/.env``
    - legacy fallback ``<repo>/.codememory/.env``

    The user's shell environment still wins naturally, and operators can always
    point at a custom dotenv file with ``--env-file`` when they intentionally
    want repo-root or shared env behavior.
    """
    if env_file_arg:
        env_file = Path(env_file_arg).expanduser().resolve()
        if not env_file.exists():
            print(f"❌ Invalid --env-file path: {env_file}")
            sys.exit(1)
        load_dotenv(dotenv_path=env_file, override=False)
        return

    if repo_root:
        candidate_env_files = (
            repo_root / CONFIG_DIR_NAME / ".env",
            repo_root / LEGACY_CONFIG_DIR_NAME / ".env",
        )
        for env_file in candidate_env_files:
            if env_file.exists():
                load_dotenv(dotenv_path=env_file, override=False)
                return


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


def _parse_json_arg(
    args: argparse.Namespace,
    raw_value: Optional[str],
    flag_name: str,
) -> dict[str, Any]:
    """Parse an optional JSON object argument."""
    if not raw_value:
        return {}

    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        _exit_with_error(
            args,
            error=f"Invalid JSON for {flag_name}: {exc}",
            human_lines=[f"❌ Invalid JSON for {flag_name}: {exc}"],
        )
        raise AssertionError("unreachable")

    if not isinstance(parsed, dict):
        _exit_with_error(
            args,
            error=f"{flag_name} must decode to a JSON object",
            human_lines=[f"❌ {flag_name} must decode to a JSON object"],
        )
        raise AssertionError("unreachable")

    return parsed


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
                    f"   Run '{_command_example('init')}' to get started.",
                ],
            )

    return repo_root, config


def _build_code_graph_builder(
    *,
    repo_root: Path,
    config: Config,
    ignore_dirs: Optional[set[str]] = None,
    ignore_files: Optional[set[str]] = None,
    ignore_patterns: Optional[set[str]] = None,
) -> KnowledgeGraphBuilder:
    """Create a code-domain graph builder using repo-aware embedding config."""
    neo4j_cfg = config.get_neo4j_config()
    return KnowledgeGraphBuilder(
        uri=neo4j_cfg["uri"],
        user=neo4j_cfg["user"],
        password=neo4j_cfg["password"],
        openai_key=None,
        config=config,
        repo_root=repo_root,
        ignore_dirs=ignore_dirs,
        ignore_files=ignore_files,
        ignore_patterns=ignore_patterns,
    )


def _upsert_agentic_memory_env_file(repo_root: Path, entries: dict[str, str]) -> Path:
    """Create or update ``.agentic-memory/.env`` with the provided entries.

    The init wizard offers "use environment variables" as a configuration mode.
    Agentic Memory now intentionally ignores a target repo's generic root
    ``.env`` to avoid collisions with application-specific variables such as
    ``EMBEDDING_PROVIDER``. That means the wizard needs a first-class place to
    write env-backed settings that *will* be read later.

    Args:
        repo_root: Repository root that owns the Agentic Memory config folder.
        entries: Mapping of environment variable names to desired values.

    Returns:
        Absolute path to the ``.agentic-memory/.env`` file.
    """
    env_path = repo_root / CONFIG_DIR_NAME / ".env"
    env_path.parent.mkdir(parents=True, exist_ok=True)

    existing_lines: list[str] = []
    if env_path.exists():
        existing_lines = env_path.read_text(encoding="utf-8").splitlines()

    remaining = dict(entries)
    output_lines: list[str] = []

    for line in existing_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            output_lines.append(line)
            continue

        key, _value = line.split("=", 1)
        key = key.strip()
        if key in remaining:
            output_lines.append(f"{key}={remaining.pop(key)}")
        else:
            output_lines.append(line)

    if output_lines and output_lines[-1].strip():
        output_lines.append("")

    for key, value in remaining.items():
        output_lines.append(f"{key}={value}")

    env_path.write_text("\n".join(output_lines).rstrip() + "\n", encoding="utf-8")
    return env_path


def _prompt_defaulted_value(prompt: str, default: str) -> str:
    """Prompt for a value while making the current default explicit."""
    return input(f"{prompt} (default: {default}): ").strip() or default


def cmd_init(args):
    """Initialize Agentic Memory in the current repository.

    Init has to handle two config-folder generations cleanly:

    - repos already using ``.agentic-memory`` should be treated as initialized
    - repos that only have legacy ``.codememory`` should prompt the operator to
      either keep using that legacy config or create a new ``.agentic-memory``
      config alongside it
    """
    repo_root = Path.cwd()

    config = Config(repo_root)
    if config.has_primary_config():
        print(f"⚠️  This repository is already initialized with Agentic Memory.")
        print(f"    Config location: {config.config_file}")
        print(
            f"\n   To reconfigure, edit the config file or delete .agentic-memory/ and run init again."
        )
        return

    if config.has_legacy_config():
        print("⚠️  Found a legacy CodeMemory config for this repository.")
        print(f"    Legacy config: {config.legacy_config_file}")
        use_legacy = (
            input("\nUse the existing .codememory config for this repo? [Y/n]: ")
            .strip()
            .lower()
        )
        if use_legacy != "n":
            print("\n✅ Keeping the existing legacy config.")
            print(f"   Active config: {config.legacy_config_file}")
            print(
                "\n   If you want to migrate later, run init again and answer 'n' to create"
                " a new .agentic-memory config."
            )
            return

        print("\n➡️  Creating a new .agentic-memory config and leaving .codememory untouched.")

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
    env_file_entries: dict[str, str] = {}
    should_offer_env_file = False

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
        print("   Agentic Memory reads env-backed Neo4j settings from:")
        print(f"   {repo_root / CONFIG_DIR_NAME / '.env'}")
        print("   or from exported shell environment variables.")
        print("   Root repo .env files are not auto-loaded.")
        should_offer_env_file = True
        neo4j_uri_default = os.getenv("NEO4J_URI", neo4j_config["uri"])
        neo4j_user_default = (
            os.getenv("NEO4J_USERNAME")
            or os.getenv("NEO4J_USER")
            or neo4j_config["user"]
        )
        neo4j_password_default = os.getenv("NEO4J_PASSWORD", neo4j_config["password"])
        print("   Enter the values you want Agentic Memory to write into .agentic-memory/.env.")
        env_file_entries.update(
            {
                "NEO4J_URI": _prompt_defaulted_value("   Enter NEO4J_URI", neo4j_uri_default),
                "NEO4J_USERNAME": _prompt_defaulted_value(
                    "   Enter NEO4J_USERNAME",
                    neo4j_user_default,
                ),
                "NEO4J_PASSWORD": _prompt_defaulted_value(
                    "   Enter NEO4J_PASSWORD",
                    neo4j_password_default,
                ),
            }
        )

    # ============================================================
    # Step 2: Code Embedding Provider
    # ============================================================
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("Step 2: Code Embedding Provider")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    print("By default, Agentic Memory uses Gemini for code embeddings.")
    print(
        "That keeps code memory in the same embedding family as the rest of the "
        "multimodal Agentic Memory system."
    )
    print(
        "If you want code memory completely separate, you can switch to another "
        "text embedding model such as OpenAI."
    )
    print("\nOptions:")
    print("  1. Gemini (recommended default)")
    print("  2. OpenAI")
    print("  3. Keep default provider but configure the API key later")

    raw_provider_choice = input("\nChoose provider [1-3] (default: 1): ").strip()
    pasted_provider_key = None
    if raw_provider_choice and raw_provider_choice not in {"1", "2", "3"}:
        # If a user pastes a Gemini-style key at the top-level provider prompt,
        # assume they intended to keep the default Gemini provider and store the
        # pasted key rather than throwing them onto the wrong branch.
        pasted_provider_key = raw_provider_choice
        provider_choice = "1"
    else:
        provider_choice = raw_provider_choice or "1"

    openai_config = DEFAULT_CONFIG["openai"].copy()
    gemini_config = DEFAULT_CONFIG["gemini"].copy()
    code_module_config = DEFAULT_CONFIG["modules"]["code"].copy()

    if provider_choice == "2":
        code_module_config = {
            "embedding_provider": "openai",
            "embedding_model": "text-embedding-3-large",
            "embedding_dimensions": 3072,
        }
        print("\nOpenAI selected for code embeddings.")
        print("Options:")
        print("  1. Enter API key now (will be stored in .agentic-memory/config.json)")
        print("  2. Use OPENAI_API_KEY via .agentic-memory/.env or exported shell env")
        print("  3. Skip for now (semantic code search won't work)")
        openai_choice = input("\nChoose option [1-3] (default: 2): ").strip() or "2"
        if openai_choice not in {"1", "2", "3"} and openai_choice.strip():
            # Operators often paste the API key directly at the menu prompt.
            # Treat that as "enter API key now" instead of silently falling into
            # the skip branch.
            openai_config["api_key"] = openai_choice.strip()
            print("   ✅ Detected pasted OpenAI API key and stored it in config")
        elif openai_choice == "1":
            api_key = input("   Enter OpenAI API key (sk-...): ").strip()
            openai_config["api_key"] = api_key
        elif openai_choice == "2":
            print("   ✅ Will use OPENAI_API_KEY from .agentic-memory/.env or shell env")
            should_offer_env_file = True
            existing_openai_key = os.getenv("OPENAI_API_KEY", "").strip()
            if existing_openai_key:
                env_file_entries["OPENAI_API_KEY"] = existing_openai_key
            else:
                pasted_openai_key = input(
                    "   Paste OPENAI_API_KEY now to save in .agentic-memory/.env (or press Enter to skip): "
                ).strip()
                if pasted_openai_key:
                    env_file_entries["OPENAI_API_KEY"] = pasted_openai_key
                    print("   ✅ Will save OPENAI_API_KEY into .agentic-memory/.env")
                else:
                    print("   ⚠️  No OPENAI_API_KEY captured. You'll need to set it later.")
        else:
            print("   ⚠️  Semantic code search will be disabled until a provider key is added")
    elif provider_choice == "3":
        print("\nKeeping the default Gemini provider. Configure the API key later.")
        print("   You can add it later in .agentic-memory/config.json or .agentic-memory/.env")
    else:
        print("\nGemini selected for code embeddings.")
        print("Options:")
        print("  1. Enter API key now (will be stored in .agentic-memory/config.json)")
        print("  2. Use GEMINI_API_KEY / GOOGLE_API_KEY via .agentic-memory/.env or shell env")
        print("  3. Skip for now (semantic code search won't work)")
        gemini_choice = input("\nChoose option [1-3] (default: 2): ").strip() or "2"
        if pasted_provider_key:
            gemini_config["api_key"] = pasted_provider_key.strip()
            print("   ✅ Detected pasted Gemini API key and stored it in config")
        elif gemini_choice not in {"1", "2", "3"} and gemini_choice.strip():
            # Same UX guard as the OpenAI path above. A pasted Gemini/Google key
            # should be interpreted as the key itself, not as an invalid menu
            # choice that disables semantic search.
            gemini_config["api_key"] = gemini_choice.strip()
            print("   ✅ Detected pasted Gemini API key and stored it in config")
        elif gemini_choice == "1":
            api_key = input("   Enter Gemini API key: ").strip()
            gemini_config["api_key"] = api_key
        elif gemini_choice == "2":
            print("   ✅ Will use GEMINI_API_KEY or GOOGLE_API_KEY from .agentic-memory/.env or shell env")
            should_offer_env_file = True
            existing_gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
            existing_google_key = os.getenv("GOOGLE_API_KEY", "").strip()
            if existing_gemini_key:
                env_file_entries["GEMINI_API_KEY"] = existing_gemini_key
            elif existing_google_key:
                env_file_entries["GOOGLE_API_KEY"] = existing_google_key
            else:
                pasted_gemini_key = input(
                    "   Paste GEMINI_API_KEY or GOOGLE_API_KEY now to save in .agentic-memory/.env (or press Enter to skip): "
                ).strip()
                if pasted_gemini_key:
                    env_file_entries["GOOGLE_API_KEY"] = pasted_gemini_key
                    print("   ✅ Will save GOOGLE_API_KEY into .agentic-memory/.env")
                else:
                    print("   ⚠️  No Gemini API key captured. You'll need to set it later.")
        else:
            print("   ⚠️  Semantic code search will be disabled until a provider key is added")

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
        "gemini": gemini_config,
        "indexing": indexing_config,
        "modules": {
            "code": code_module_config,
        },
    }

    config.save(final_config)
    config.ensure_graphignore(indexing_config.get("ignore_dirs", []))

    print(f"✅ Configuration saved to: {config.config_file}")
    print(f"✅ Ignore patterns saved to: {config.graphignore_file}")
    if should_offer_env_file:
        write_env_choice = (
            input(
                f"Write env-backed settings to {repo_root / CONFIG_DIR_NAME / '.env'} now? [Y/n]: "
            )
            .strip()
            .lower()
        )
        if write_env_choice != "n":
            env_path = _upsert_agentic_memory_env_file(repo_root, env_file_entries)
            print(f"✅ Environment file saved to: {env_path}")

    # ============================================================
    # Step 5: Test Connection & Initial Index
    # ============================================================
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("Step 5: Test Connection & Initial Index")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    do_index = input("Run initial indexing now? [Y/n]: ").strip().lower()
    if do_index != "n":
        try:
            indexing_cfg = config.get_indexing_config()
            ignore_dirs = set(indexing_cfg.get("ignore_dirs", []))
            ignore_files = set(indexing_cfg.get("ignore_files", []))
            extensions = set(indexing_cfg.get("extensions", []))
            graphignore_patterns = set(config.get_graphignore_patterns())

            print("\n🔍 Testing Neo4j connection...")
            builder = _build_code_graph_builder(
                repo_root=repo_root,
                config=config,
                ignore_dirs=ignore_dirs,
                ignore_files=ignore_files,
                ignore_patterns=graphignore_patterns,
            )

            # Test connection
            builder.setup_database()
            print("✅ Neo4j connection successful!\n")

            builder.close()

            print("📂 Starting initial indexing...")
            builder = _build_code_graph_builder(
                repo_root=repo_root,
                config=config,
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
            print(f"   {_command_example('index')}")

    # ============================================================
    # Done!
    # ============================================================
    print("\n" + "━" * 67)
    print("✅ Agentic Memory initialized successfully!")
    print("━" * 67)
    print(f"\nConfig file: {config.config_file}")
    print(f"\nNext steps:")
    print(f"  • {_command_example('status')}    - Show repository status")
    print(f"  • {_command_example('watch')}     - Start continuous monitoring")
    print(f"  • {_command_example('serve')}     - Start MCP server for AI agents")
    print(f"  • {_command_example('search')}    - Test semantic search")
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
        builder = _build_code_graph_builder(repo_root=repo_root, config=config)

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

    indexing_cfg = config.get_indexing_config()
    ignore_dirs = set(indexing_cfg.get("ignore_dirs", []))
    ignore_files = set(indexing_cfg.get("ignore_files", []))
    extensions = set(indexing_cfg.get("extensions", []))
    graphignore_patterns = set(config.get_graphignore_patterns())

    builder = _build_code_graph_builder(
        repo_root=repo_root,
        config=config,
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

    indexing_cfg = config.get_indexing_config()
    graphignore_patterns = set(config.get_graphignore_patterns())

    start_continuous_watch(
        repo_path=repo_root,
        config=config,
        ignore_dirs=set(indexing_cfg.get("ignore_dirs", [])),
        ignore_files=set(indexing_cfg.get("ignore_files", [])),
        ignore_patterns=graphignore_patterns,
        supported_extensions=set(indexing_cfg.get("extensions", [])),
        initial_scan=not args.no_scan,
    )


def cmd_serve(args):
    """Start the MCP server."""
    from agentic_memory.server.app import run_server

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
                f"⚠️  No .agentic-memory/config.json found in {repo_root}, using environment variables"
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

    code_runtime = resolve_embedding_runtime("code", config=config, repo_root=repo_root)
    if not code_runtime.api_key and not (
        code_runtime.provider == "gemini" and code_runtime.use_vertexai
    ):
        _exit_with_error(
            args,
            error=(
                f"Code embedding API key not configured for provider "
                f"'{code_runtime.provider}'."
            ),
            human_lines=[
                (
                    f"❌ Code embedding API key not configured for provider "
                    f"'{code_runtime.provider}'."
                ),
                (
                    "   Add the provider key to .agentic-memory/config.json or set the "
                    "matching environment variable before running semantic search."
                ),
            ],
        )

    builder = _build_code_graph_builder(repo_root=repo_root, config=config)

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


def cmd_debug_ts_calls(args):
    """Run the TypeScript call analyzer on one JS/TS file without indexing.

    This command is intentionally diagnostic. It does not write to Neo4j, does
    not generate embeddings, and does not require a working embedding provider.
    Its role is to answer one question quickly: "what outgoing calls can the
    TypeScript semantic analyzer resolve for this file right now?"
    """
    repo_root = Path(args.repo).expanduser().resolve() if getattr(args, "repo", None) else find_repo_root()
    if not repo_root.exists() or not repo_root.is_dir():
        _exit_with_error(
            args,
            error=f"Invalid repository path: {repo_root}",
            human_lines=[f"❌ Invalid repository path: {repo_root}"],
        )

    rel_path = str(args.path).replace("\\", "/").strip()
    full_path = (repo_root / rel_path).resolve()
    if not full_path.exists() or not full_path.is_file():
        _exit_with_error(
            args,
            error=f"File not found: {full_path}",
            human_lines=[f"❌ File not found: {full_path}"],
        )

    extension = full_path.suffix.lower()
    if extension not in {".js", ".jsx", ".ts", ".tsx"}:
        _exit_with_error(
            args,
            error=f"Unsupported file extension for TypeScript analyzer: {extension}",
            human_lines=[f"❌ Unsupported file extension for TypeScript analyzer: {extension}"],
        )

    parser = CodeParser()
    analyzer = TypeScriptCallAnalyzer()
    code = full_path.read_text(encoding="utf8", errors="ignore")
    parsed = parser.parse_file(code, extension)
    request = {
        "path": rel_path,
        "functions": [
            {
                "name": row["name"],
                "qualified_name": row["qualified_name"],
                "parent_class": row.get("parent_class") or "",
                "name_line": row["name_line"],
                "name_column": row["name_column"],
            }
            for row in parsed["functions"]
        ],
    }

    if not analyzer.is_available():
        _exit_with_error(
            args,
            error=analyzer.disabled_reason or "TypeScript analyzer is unavailable.",
            human_lines=[f"❌ {analyzer.disabled_reason or 'TypeScript analyzer is unavailable.'}"],
        )

    try:
        results = analyzer.analyze_files(repo_root=repo_root, files=[request])
    except TypeScriptCallAnalyzerError as exc:
        _exit_with_error(
            args,
            error=f"TypeScript call analysis failed: {exc}",
            human_lines=[f"❌ TypeScript call analysis failed: {exc}"],
        )

    file_result = results.get(rel_path)
    function_rows = []
    if file_result is not None:
        for qualified_name, analysis in file_result.functions.items():
            function_rows.append(
                {
                    "qualified_name": qualified_name,
                    "name": analysis.name,
                    "outgoing_calls": [
                        {
                            "path": call.rel_path,
                            "name": call.name,
                            "kind": call.kind,
                            "container_name": call.container_name,
                            "qualified_name_guess": call.qualified_name_guess,
                        }
                        for call in analysis.outgoing_calls
                    ],
                }
            )

    data = {
        "repository": str(repo_root),
        "path": rel_path,
        "function_count": len(parsed["functions"]),
        "functions": function_rows,
        "diagnostics": list(file_result.diagnostics) if file_result is not None else [],
    }

    if _emit_success(
        args,
        data=data,
        metrics={
            "function_count": len(parsed["functions"]),
            "analyzed_functions": len(function_rows),
        },
    ):
        return

    print(f"## TypeScript Call Analysis for `{rel_path}`\n")
    print(f"Repository: {repo_root}")
    print(f"Functions analyzed: {len(function_rows)} / {len(parsed['functions'])}\n")
    if not function_rows:
        print("No analyzer-resolved functions found.")
        return

    for row in function_rows:
        print(f"### {row['qualified_name']}")
        outgoing_calls = row["outgoing_calls"]
        if not outgoing_calls:
            print("- No outgoing calls resolved.")
            print()
            continue
        for call in outgoing_calls:
            target = call["qualified_name_guess"] or call["name"]
            print(f"- {call['path']} :: {target}")
        print()


def cmd_debug_py_calls(args):
    """Run the Python semantic call analyzer on one `.py` file without indexing.

    This mirrors `debug-ts-calls` for the Python language-service-backed path.
    It lets operators answer one question quickly: "what repo-local outgoing
    calls can the Python semantic analyzer resolve for this file right now?"
    """
    repo_root = Path(args.repo).expanduser().resolve() if getattr(args, "repo", None) else find_repo_root()
    if not repo_root.exists() or not repo_root.is_dir():
        _exit_with_error(
            args,
            error=f"Invalid repository path: {repo_root}",
            human_lines=[f"❌ Invalid repository path: {repo_root}"],
        )

    rel_path = str(args.path).replace("\\", "/").strip()
    full_path = (repo_root / rel_path).resolve()
    if not full_path.exists() or not full_path.is_file():
        _exit_with_error(
            args,
            error=f"File not found: {full_path}",
            human_lines=[f"❌ File not found: {full_path}"],
        )

    if full_path.suffix.lower() != ".py":
        _exit_with_error(
            args,
            error=f"Unsupported file extension for Python analyzer: {full_path.suffix.lower()}",
            human_lines=[
                f"❌ Unsupported file extension for Python analyzer: {full_path.suffix.lower()}"
            ],
        )

    parser = CodeParser()
    analyzer = PythonCallAnalyzer()
    code = full_path.read_text(encoding="utf8", errors="ignore")
    parsed = parser.parse_file(code, ".py")
    request = {
        "path": rel_path,
        "functions": [
            {
                "name": row["name"],
                "qualified_name": row["qualified_name"],
                "parent_class": row.get("parent_class") or "",
                "name_line": row["name_line"],
                "name_column": row["name_column"],
            }
            for row in parsed["functions"]
        ],
    }

    if not analyzer.is_available():
        _exit_with_error(
            args,
            error=analyzer.disabled_reason or "Python analyzer is unavailable.",
            human_lines=[f"❌ {analyzer.disabled_reason or 'Python analyzer is unavailable.'}"],
        )

    try:
        results = analyzer.analyze_files(repo_root=repo_root, files=[request])
    except PythonCallAnalyzerError as exc:
        _exit_with_error(
            args,
            error=f"Python call analysis failed: {exc}",
            human_lines=[f"❌ Python call analysis failed: {exc}"],
        )

    file_result = results.get(rel_path)
    function_rows = []
    if file_result is not None:
        for qualified_name, analysis in file_result.functions.items():
            function_rows.append(
                {
                    "qualified_name": qualified_name,
                    "name": analysis.name,
                    "outgoing_calls": [
                        {
                            "path": call.rel_path,
                            "name": call.name,
                            "kind": call.kind,
                            "container_name": call.container_name,
                            "qualified_name_guess": call.qualified_name_guess,
                            "definition_line": call.definition_line,
                            "definition_column": call.definition_column,
                        }
                        for call in analysis.outgoing_calls
                    ],
                }
            )

    data = {
        "repository": str(repo_root),
        "path": rel_path,
        "function_count": len(parsed["functions"]),
        "functions": function_rows,
        "diagnostics": list(file_result.diagnostics) if file_result is not None else [],
    }

    if _emit_success(
        args,
        data=data,
        metrics={
            "function_count": len(parsed["functions"]),
            "analyzed_functions": len(function_rows),
        },
    ):
        return

    print(f"## Python Call Analysis for `{rel_path}`\n")
    print(f"Repository: {repo_root}")
    print(f"Functions analyzed: {len(function_rows)} / {len(parsed['functions'])}\n")
    if not function_rows:
        print("No analyzer-resolved functions found.")
        return

    for row in function_rows:
        print(f"### {row['qualified_name']}")
        outgoing_calls = row["outgoing_calls"]
        if not outgoing_calls:
            print("- No outgoing calls resolved.")
            print()
            continue
        for call in outgoing_calls:
            target = call["qualified_name_guess"] or call["name"]
            print(f"- {call['path']} :: {target}")
        print()


def cmd_call_status(args):
    """Report CALLS-edge coverage and provenance for one repository.

    This command turns Phase 11 call-graph quality into something measurable.
    Instead of eyeballing Neo4j manually, operators can see how much of the
    current repo's call graph is analyzer-backed, how much is fallback-only,
    and how much function/file coverage we actually have before changing the
    traversal graph or enabling PPR behavior by default.
    """
    repo_root, config = _resolve_repo_and_config(args, require_initialized=True)

    builder = None
    try:
        builder = _build_code_graph_builder(repo_root=repo_root, config=config)
        diagnostics = builder.get_call_diagnostics(repo_id=str(repo_root))

        if _emit_success(
            args,
            data={
                "repository": str(repo_root),
                "diagnostics": diagnostics,
            },
            metrics={
                "total_call_edges": diagnostics["total_call_edges"],
                "function_coverage_ratio": diagnostics["function_coverage_ratio"],
                "high_confidence_ratio": diagnostics["high_confidence_ratio"],
            },
        ):
            return

        print("📞 Call Graph Status")
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print(f"Repository: {repo_root}")
        print(f"Repo ID:    {diagnostics['repo_id']}")
        print()
        print("Coverage")
        print(
            f"  Functions with calls: {diagnostics['functions_with_calls']:,} / {diagnostics['total_functions']:,}"
        )
        print(f"  Functions without calls: {diagnostics['functions_without_calls']:,}")
        print(f"  Function coverage ratio: {diagnostics['function_coverage_ratio']:.1%}")
        print(
            f"  Files with call edges: {diagnostics['files_with_call_edges']:,} / {diagnostics['files_with_functions']:,}"
        )
        print(f"  Files with analyzer edges: {diagnostics['files_with_analyzer_edges']:,}")
        print(
            f"  Files with analyzer attempts: {diagnostics.get('files_with_analyzer_attempts', 0):,}"
        )
        print(
            f"  Files with drop reasons: {diagnostics.get('files_with_drop_reasons', 0):,}"
        )
        print(f"  File coverage ratio: {diagnostics['file_coverage_ratio']:.1%}")
        print()
        print("Edges")
        print(f"  Total CALLS edges: {diagnostics['total_call_edges']:,}")
        print(
            f"  High-confidence edges (>= {diagnostics['high_confidence_threshold']:.2f}): {diagnostics['high_confidence_edges']:,}"
        )
        print(f"  High-confidence ratio: {diagnostics['high_confidence_ratio']:.1%}")
        print()
        print("Sources")
        if diagnostics["sources"]:
            for source_row in diagnostics["sources"]:
                print(
                    f"  {source_row['source']}: {source_row['edge_count']:,} edges "
                    f"(avg confidence {source_row['avg_confidence']:.2f})"
                )
        else:
            print("  No CALLS edges recorded yet.")

        drop_reasons = diagnostics.get("drop_reasons", [])
        if drop_reasons:
            print()
            print("Drop Reasons")
            for row in drop_reasons:
                print(
                    f"  {row['source']} :: {row['reason']} = {row['drop_count']:,}"
                )

        analyzer_issues = diagnostics.get("analyzer_issues", [])
        if analyzer_issues:
            print()
            print("Analyzer Issues")
            for row in analyzer_issues:
                updated_suffix = f" @ {row['updated_at']}" if row.get("updated_at") else ""
                print(
                    f"  {row['source']} [{row['status']}]"
                    f"{updated_suffix}: {row['message']}"
                )

    except (neo4j.exceptions.DatabaseError, neo4j.exceptions.ServiceUnavailable) as exc:
        _exit_with_error(
            args,
            error=f"Could not inspect CALLS edges: {exc}",
            human_lines=[
                f"❌ Could not inspect CALLS edges: {exc}",
                "   Make sure Neo4j is running and the repo has been indexed.",
            ],
        )
    finally:
        if builder is not None:
            builder.close()


def cmd_deps(args):
    """Show direct dependency relationships for a file."""
    repo_root, config = _resolve_repo_and_config(args, require_initialized=True)

    builder = _build_code_graph_builder(repo_root=repo_root, config=config)

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

    builder = _build_code_graph_builder(repo_root=repo_root, config=config)

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
                f"   Run '{_command_example('git-init')}' first.",
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
                f"   Run '{_command_example('git-init')}' first.",
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


def cmd_product_status(args: argparse.Namespace) -> None:
    """Return local product-state summary for desktop and dogfood loops."""
    store = ProductStateStore()
    repo_root = Path(args.repo).expanduser().resolve() if getattr(args, "repo", None) else None
    payload = store.status_payload(repo_root=repo_root)

    if _emit_success(
        args,
        data=payload,
        metrics=payload["summary"],
    ):
        return

    print(f"🧭 Product state: {payload['state_path']}")
    print(f"📦 Repositories tracked: {payload['summary']['repo_count']}")
    print(f"🔌 Integrations tracked: {payload['summary']['integration_count']}")
    print(f"🧪 Recorded events: {payload['summary']['event_count']}")
    print(f"✅ Onboarding complete: {payload['summary']['onboarding_completed']}")
    if payload.get("repo"):
        print(f"📁 Repo initialized: {payload['repo']['initialized']}")
        print(f"📁 Repo tracked: {payload['repo']['tracked']}")


def cmd_product_repo_add(args: argparse.Namespace) -> None:
    """Create or update a tracked repository record in product state."""
    store = ProductStateStore()
    metadata = _parse_json_arg(args, getattr(args, "metadata_json", None), "--metadata-json")
    repo = store.upsert_repo(args.path, label=args.label, metadata=metadata)

    if _emit_success(
        args,
        data={"repo": repo, "state_path": str(store.state_path)},
        metrics={"repo_count": len(store.load().get("repos", []))},
    ):
        return

    print(f"✅ Tracked repository: {repo['path']}")
    print(f"   Label: {repo['label']}")
    print(f"   Initialized: {repo['initialized']}")


def cmd_product_integration_set(args: argparse.Namespace) -> None:
    """Create or update an integration record in product state."""
    store = ProductStateStore()
    config = _parse_json_arg(args, getattr(args, "config_json", None), "--config-json")

    try:
        integration = store.upsert_integration(
            surface=args.surface,
            target=args.target,
            status=args.status,
            config=config,
            last_error=args.last_error,
        )
    except ValueError as exc:
        _exit_with_error(args, error=str(exc), human_lines=[f"❌ {exc}"])
        return

    if _emit_success(
        args,
        data={"integration": integration, "state_path": str(store.state_path)},
        metrics={"integration_count": len(store.load().get("integrations", []))},
    ):
        return

    print(f"✅ Integration updated: {integration['surface']} -> {integration['target']}")
    print(f"   Status: {integration['status']}")


def cmd_product_component_set(args: argparse.Namespace) -> None:
    """Update component health in product state."""
    store = ProductStateStore()
    details = _parse_json_arg(args, getattr(args, "details_json", None), "--details-json")

    try:
        record = store.set_component_status(args.component, status=args.status, details=details)
    except ValueError as exc:
        _exit_with_error(args, error=str(exc), human_lines=[f"❌ {exc}"])
        return

    if _emit_success(
        args,
        data={"component": args.component, "record": record, "state_path": str(store.state_path)},
        metrics={},
    ):
        return

    print(f"✅ Component updated: {args.component}")
    print(f"   Status: {record['status']}")


def cmd_product_event_record(args: argparse.Namespace) -> None:
    """Record a product event for install/integration dogfooding."""
    store = ProductStateStore()
    details = _parse_json_arg(args, getattr(args, "details_json", None), "--details-json")
    event = store.record_event(
        event_type=args.event,
        status=args.status,
        actor=args.actor,
        details=details,
    )

    if _emit_success(
        args,
        data={"event": event, "state_path": str(store.state_path)},
        metrics={"event_count": len(store.load().get("events", []))},
    ):
        return

    print(f"✅ Event recorded: {event['event_type']}")
    print(f"   Actor: {event['actor']}")
    print(f"   Status: {event['status']}")


def cmd_product_onboarding_step(args: argparse.Namespace) -> None:
    """Update onboarding progress in product state."""
    store = ProductStateStore()
    onboarding = store.update_onboarding_step(args.step, completed=not args.pending)

    if _emit_success(
        args,
        data={"onboarding": onboarding, "state_path": str(store.state_path)},
        metrics={"completed_steps": len(onboarding.get("completed_steps", []))},
    ):
        return

    print(f"✅ Onboarding updated: {args.step}")
    print(f"   Completed: {not args.pending}")


def cmd_openclaw_setup(args: argparse.Namespace) -> None:
    """Generate a local OpenClaw config artifact and register product state.

    This command is the first "magic install" path for OpenClaw power users.
    It does not try to mutate a live OpenClaw installation directly yet.
    Instead it creates a deterministic config file that the OpenClaw plugin
    package can consume directly, while also updating Agentic Memory's local
    control plane so the desktop shell and dogfood loops can observe setup
    progress.

    The important detail is that this file now follows OpenClaw's native plugin
    configuration shape:

    - `plugins.slots.*` selects which plugin IDs OpenClaw should mount.
    - `plugins.entries.agentic-memory.config` stores the runtime settings that
      the `am-openclaw` package reads through the official plugin SDK.

    Keeping this file OpenClaw-native avoids a second translation layer later
    when we package the "magic install" flow into the desktop shell.
    """
    store = ProductStateStore()
    config_path = Path(args.config_path).expanduser().resolve()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    device_id = args.device_id or os.environ.get("COMPUTERNAME") or "default-device"
    username = (os.environ.get("USERNAME") or "user").strip().lower().replace(" ", "-")
    agent_id = args.agent_id or f"claw-{username}"
    session_id = args.session_id or f"{args.workspace_id}:{device_id}:{agent_id}:bootstrap"
    enable_context_augmentation = bool(
        getattr(args, "enable_context_augmentation", False)
        or getattr(args, "enable_context_engine", False)
    )
    mode = "augment_context" if enable_context_augmentation else "capture_only"

    # Agentic Memory always occupies the OpenClaw context-engine slot today
    # because the host's per-turn lifecycle callbacks currently arrive through
    # that interface. In capture_only mode the plugin still captures turns, but
    # it intentionally does not add custom context blocks to prompts.
    openclaw_config = {
        "generated_by": PRIMARY_CLI_NAME,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "plugins": {
            "slots": {
                "memory": "agentic-memory",
                "contextEngine": "agentic-memory",
            },
            "entries": {
                "agentic-memory": {
                    "enabled": True,
                    "config": {
                        "backendUrl": args.backend_url,
                        "apiKey": f"${{{args.api_key_env}}}",
                        "workspaceId": args.workspace_id,
                        "deviceId": device_id,
                        "agentId": agent_id,
                        "contextEngineId": "agentic-memory",
                        "mode": mode,
                    },
                },
            },
        },
    }
    config_path.write_text(f"{json.dumps(openclaw_config, indent=2)}\n", encoding="utf-8")

    memory_integration = store.upsert_integration(
        surface="openclaw_memory",
        target="workspace",
        status="configured",
        config={
            "workspace_id": args.workspace_id,
            "device_id": device_id,
            "agent_id": agent_id,
            "session_id": session_id,
            "backend_url": args.backend_url,
            "config_path": str(config_path),
            "mode": mode,
        },
    )
    memory_component = store.set_component_status(
        "openclaw_memory",
        status="healthy",
        details={
            "workspace_id": args.workspace_id,
            "device_id": device_id,
            "agent_id": agent_id,
            "config_path": str(config_path),
            "mode": mode,
        },
    )

    context_integration = None
    context_component = store.set_component_status(
        "openclaw_context_engine",
        status="healthy" if mode == "augment_context" else "available",
        details={
            "workspace_id": args.workspace_id,
            "device_id": device_id,
            "agent_id": agent_id,
            "config_path": str(config_path),
            "mode": mode,
        },
    )
    if mode == "augment_context":
        context_integration = store.upsert_integration(
            surface="openclaw_context_engine",
            target="workspace",
            status="configured",
            config={
                "workspace_id": args.workspace_id,
                "device_id": device_id,
                "agent_id": agent_id,
                "session_id": session_id,
                "backend_url": args.backend_url,
                "config_path": str(config_path),
                "mode": mode,
            },
        )

    event = store.record_event(
        event_type="openclaw_setup_completed",
        actor=PRIMARY_CLI_NAME,
        status="ok",
        details={
            "workspace_id": args.workspace_id,
            "device_id": device_id,
            "agent_id": agent_id,
            "session_id": session_id,
            "backend_url": args.backend_url,
            "config_path": str(config_path),
            "mode": mode,
            "context_augmentation_enabled": mode == "augment_context",
        },
    )

    payload = {
        "config_path": str(config_path),
        "session_id": session_id,
        "backend_url": args.backend_url,
        "config": openclaw_config,
        "memory_integration": memory_integration,
        "memory_component": memory_component,
        "context_integration": context_integration,
        "context_component": context_component,
        "event": event,
    }
    if _emit_success(
        args,
        data=payload,
        metrics={
            "context_augmentation_enabled": mode == "augment_context",
            "config_written": True,
        },
    ):
        return

    print(f"🪄 OpenClaw setup written: {config_path}")
    print(f"🔗 Backend URL: {args.backend_url}")
    print(f"🧠 Memory slot: agentic-memory")
    print("🪝 Capture hook: agentic-memory context engine slot")
    print(f"🧩 Context augmentation: {'enabled' if mode == 'augment_context' else 'disabled'}")
    print(f"🪪 Session bootstrap: {session_id}")


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
    """Initialize web research vector indexes and constraints.

    Calls setup_database() for baseline schema creation, then
    fix_vector_index_dimensions() so existing research/chat indexes are reset
    to the documented Gemini default dimension of 3072 when needed.
    """
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "password")

    try:
        from agentic_memory.core.connection import ConnectionManager
        conn = ConnectionManager(uri, user, password)
        conn.setup_database()
        conn.fix_vector_index_dimensions()
        conn.driver.close()
        print("web-init: research_embeddings vector index ready (3072d). chat_embeddings reset to 3072d.")
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

    from agentic_memory.core.extraction_llm import resolve_extraction_llm_config  # noqa: PLC0415
    from agentic_memory.core.runtime_embedding import build_embedding_service  # noqa: PLC0415

    extraction_llm = resolve_extraction_llm_config()
    if not extraction_llm.api_key:
        print("web-ingest: extraction LLM API key environment variable required.")
        sys.exit(1)

    neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "password")

    try:
        from agentic_memory.web.crawler import crawl_url
        from agentic_memory.web.pipeline import ResearchIngestionPipeline
        from agentic_memory.core.connection import ConnectionManager
        from agentic_memory.core.entity_extraction import EntityExtractionService

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
        conn.setup_database()
        conn.fix_vector_index_dimensions()
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
    from agentic_memory.core.extraction_llm import resolve_extraction_llm_config  # noqa: PLC0415
    from agentic_memory.core.runtime_embedding import build_embedding_service  # noqa: PLC0415

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

    from agentic_memory.core.connection import ConnectionManager  # noqa: PLC0415
    from agentic_memory.core.entity_extraction import EntityExtractionService  # noqa: PLC0415
    from agentic_memory.web.pipeline import ResearchIngestionPipeline  # noqa: PLC0415

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

    from agentic_memory.core.extraction_llm import resolve_extraction_llm_config  # noqa: PLC0415

    if isinstance(value, str):
        return resolve_extraction_llm_config(api_key=value)
    return resolve_extraction_llm_config()


def cmd_web_schedule(args: argparse.Namespace) -> None:
    """Create a recurring research schedule."""
    from agentic_memory.core.scheduler import ResearchScheduler  # noqa: PLC0415

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
    from agentic_memory.core.scheduler import ResearchScheduler  # noqa: PLC0415

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
    and chat_embeddings at 3072d in case they exist at the wrong dimension.
    """
    from dotenv import load_dotenv  # noqa: PLC0415

    load_dotenv()

    neo4j_uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "")

    from agentic_memory.core.connection import ConnectionManager  # noqa: PLC0415

    conn = ConnectionManager(neo4j_uri, neo4j_user, password)
    try:
        conn.setup_database()
        print("chat-init: Vector indexes and constraints created (or already exist).")
        conn.fix_vector_index_dimensions()
        print(
            "chat-init: research_embeddings and chat_embeddings reset to 3072d. Done."
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
    from agentic_memory.core.extraction_llm import resolve_extraction_llm_config  # noqa: PLC0415
    from agentic_memory.core.runtime_embedding import build_embedding_service  # noqa: PLC0415

    extraction_llm = resolve_extraction_llm_config()

    from agentic_memory.core.connection import ConnectionManager  # noqa: PLC0415
    from agentic_memory.core.entity_extraction import EntityExtractionService  # noqa: PLC0415
    from agentic_memory.chat.pipeline import ConversationIngestionPipeline  # noqa: PLC0415

    # Auto-initialize indexes, then force the research/chat index dimensions
    # back to the documented Gemini default of 3072 in case an earlier run
    # created them incorrectly.
    conn = ConnectionManager(neo4j_uri, neo4j_user, password)
    conn.setup_database()
    conn.fix_vector_index_dimensions()

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
    from agentic_memory.core.connection import ConnectionManager  # noqa: PLC0415
    from agentic_memory.core.runtime_embedding import build_embedding_service  # noqa: PLC0415

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
    from agentic_memory.core.connection import ConnectionManager  # noqa: PLC0415

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
    """Parse CLI arguments and dispatch to the appropriate command handler.

    This is the setuptools entry point registered as ``agentic-memory`` (and the
    legacy alias ``codememory``) in ``pyproject.toml``.  It builds the full
    argparse tree — global flags plus every subcommand — then routes to the
    matching ``cmd_*`` function.

    Top-level global flags (``--prompted``, ``--unprompted``, etc.) support
    telemetry annotation workflows that run *outside* of a subcommand context.
    All subcommands accept ``--repo`` and ``--env-file`` to override the default
    repository root and .env file discovery.

    Typical invocations:
        ``agentic-memory init``            — interactive setup wizard
        ``agentic-memory serve --port 8080`` — start MCP server
        ``agentic-memory index --quiet``   — one-shot indexing (CI-friendly)
        ``agentic-memory search "auth flow"`` — ad hoc code semantic query

    Side effects:
        Calls sys.exit() on unrecoverable errors via _exit_with_error().
        Prints human-readable or JSON output to stdout depending on ``--json``.
    """
    primary_name = PRIMARY_CLI_NAME
    parser = argparse.ArgumentParser(
        description="Agentic Memory: Structural Memory Layer for AI agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Quick Start:
  {primary_name} init              # Initialize in current repo (interactive wizard)
  {primary_name} status            # Show repository status

Commands:
  {primary_name} index             # One-time full index
  {primary_name} watch             # Continuous monitoring
  {primary_name} serve             # Start MCP server
  {primary_name} search <query>    # Test code semantic search
  {primary_name} debug-py-calls    # Inspect Python analyzer output for one file
  {primary_name} debug-ts-calls    # Inspect JS/TS analyzer output for one file
  {primary_name} call-status       # Show CALLS-edge coverage and provenance
  {primary_name} git-init          # Enable git graph integration
  {primary_name} git-sync          # Sync local git history into Neo4j
  {primary_name} git-status        # Show git graph sync status

Legacy alias still supported: codememory
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
        help="Repository root to use for .agentic-memory/config.json resolution",
    )
    serve_parser.add_argument(
        "--env-file",
        type=str,
        help="Optional .env file to load before starting the server",
    )

    # Command: search (test semantic search)
    search_parser = subparsers.add_parser(
        "search",
        help="Test code semantic search (requires the configured code embedding API key)",
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

    # Command: debug-ts-calls (TypeScript analyzer diagnostics)
    debug_py_calls_parser = subparsers.add_parser(
        "debug-py-calls",
        help="Run the Python semantic call analyzer on one file without indexing",
    )
    debug_py_calls_parser.add_argument(
        "path",
        help="Repo-relative path to a .py file",
    )
    debug_py_calls_parser.add_argument(
        "--repo",
        type=str,
        help="Repository root to analyze. Defaults to the detected current repo root.",
    )
    debug_py_calls_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output",
    )

    # Command: debug-ts-calls (TypeScript analyzer diagnostics)
    debug_ts_calls_parser = subparsers.add_parser(
        "debug-ts-calls",
        help="Run the JS/TS semantic call analyzer on one file without indexing",
    )
    debug_ts_calls_parser.add_argument(
        "path",
        help="Repo-relative path to a .js/.jsx/.ts/.tsx file",
    )
    debug_ts_calls_parser.add_argument(
        "--repo",
        type=str,
        help="Repository root to analyze. Defaults to the detected current repo root.",
    )
    debug_ts_calls_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output",
    )

    # Command: call-status (CALLS diagnostics)
    call_status_parser = subparsers.add_parser(
        "call-status",
        help="Show CALLS-edge coverage, provenance, and confidence for one repo",
    )
    call_status_parser.add_argument(
        "--repo",
        type=str,
        help="Repository root path (defaults to detected current repository)",
    )
    call_status_parser.add_argument(
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

    # Product control-plane commands
    product_status_parser = subparsers.add_parser(
        "product-status",
        help="Show local product-state summary for desktop and install loops",
    )
    product_status_parser.add_argument(
        "--repo",
        type=str,
        help="Optional repository path to summarize against product state",
    )
    product_status_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output",
    )

    product_repo_add_parser = subparsers.add_parser(
        "product-repo-add",
        help="Track a repository in the local product state",
    )
    product_repo_add_parser.add_argument("path", help="Repository path to track")
    product_repo_add_parser.add_argument("--label", type=str, help="Optional display label")
    product_repo_add_parser.add_argument(
        "--metadata-json",
        type=str,
        help="Optional JSON object with additional repo metadata",
    )
    product_repo_add_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output",
    )

    product_integration_set_parser = subparsers.add_parser(
        "product-integration-set",
        help="Create or update an integration record in local product state",
    )
    product_integration_set_parser.add_argument("--surface", required=True, help="Integration surface")
    product_integration_set_parser.add_argument("--target", required=True, help="Integration target")
    product_integration_set_parser.add_argument("--status", required=True, help="Integration status")
    product_integration_set_parser.add_argument(
        "--config-json",
        type=str,
        help="Optional JSON object with integration config details",
    )
    product_integration_set_parser.add_argument(
        "--last-error",
        type=str,
        help="Optional last error string",
    )
    product_integration_set_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output",
    )

    product_component_set_parser = subparsers.add_parser(
        "product-component-set",
        help="Update local runtime component health",
    )
    product_component_set_parser.add_argument("--component", required=True, help="Component name")
    product_component_set_parser.add_argument("--status", required=True, help="Component status")
    product_component_set_parser.add_argument(
        "--details-json",
        type=str,
        help="Optional JSON object with component details",
    )
    product_component_set_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output",
    )

    product_event_record_parser = subparsers.add_parser(
        "product-event-record",
        help="Record a product event for install and integration loops",
    )
    product_event_record_parser.add_argument("--event", required=True, help="Event type name")
    product_event_record_parser.add_argument(
        "--status",
        default="ok",
        help="Event status (default: ok)",
    )
    product_event_record_parser.add_argument(
        "--actor",
        default="cli",
        help="Actor responsible for the event (default: cli)",
    )
    product_event_record_parser.add_argument(
        "--details-json",
        type=str,
        help="Optional JSON object with event details",
    )
    product_event_record_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output",
    )

    product_onboarding_parser = subparsers.add_parser(
        "product-onboarding-step",
        help="Update onboarding progress in local product state",
    )
    product_onboarding_parser.add_argument("--step", required=True, help="Onboarding step name")
    product_onboarding_parser.add_argument(
        "--pending",
        action="store_true",
        help="Mark the step as pending instead of completed",
    )
    product_onboarding_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output",
    )

    openclaw_setup_parser = subparsers.add_parser(
        "openclaw-setup",
        help="Generate OpenClaw config and register local product state",
    )
    openclaw_setup_parser.add_argument("--workspace-id", required=True, help="Shared OpenClaw workspace identifier")
    openclaw_setup_parser.add_argument(
        "--device-id",
        help="Current device identifier. Defaults to COMPUTERNAME when omitted.",
    )
    openclaw_setup_parser.add_argument(
        "--agent-id",
        help="OpenClaw agent identifier. Defaults to a username-derived id when omitted.",
    )
    openclaw_setup_parser.add_argument(
        "--session-id",
        type=str,
        help="Optional setup session identifier. Defaults to a deterministic bootstrap id.",
    )
    openclaw_setup_parser.add_argument(
        "--backend-url",
        type=str,
        default="http://127.0.0.1:8765",
        help="Agentic Memory backend URL for the OpenClaw plugin package",
    )
    openclaw_setup_parser.add_argument(
        "--api-key-env",
        type=str,
        default="AGENTIC_MEMORY_API_KEY",
        help="Environment variable name to interpolate into the generated apiKey field",
    )
    openclaw_setup_parser.add_argument(
        "--config-path",
        type=str,
        default=str(Path.home() / ".openclaw" / "agentic-memory.json"),
        help="Where to write the generated OpenClaw config artifact",
    )
    openclaw_setup_parser.add_argument(
        "--enable-context-augmentation",
        action="store_true",
        help="Enable Agentic Memory context augmentation in addition to memory capture",
    )
    openclaw_setup_parser.add_argument(
        "--enable-context-engine",
        action="store_true",
        help="Legacy alias for --enable-context-augmentation",
    )
    openclaw_setup_parser.add_argument(
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
                    f"   Use: {_command_example('--unprompted', '\"check our auth\"')}",
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
    elif args.command == "debug-py-calls":
        cmd_debug_py_calls(args)
    elif args.command == "debug-ts-calls":
        cmd_debug_ts_calls(args)
    elif args.command == "call-status":
        cmd_call_status(args)
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
    elif args.command == "product-status":
        cmd_product_status(args)
    elif args.command == "product-repo-add":
        cmd_product_repo_add(args)
    elif args.command == "product-integration-set":
        cmd_product_integration_set(args)
    elif args.command == "product-component-set":
        cmd_product_component_set(args)
    elif args.command == "product-event-record":
        cmd_product_event_record(args)
    elif args.command == "product-onboarding-step":
        cmd_product_onboarding_step(args)
    elif args.command == "openclaw-setup":
        cmd_openclaw_setup(args)
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
