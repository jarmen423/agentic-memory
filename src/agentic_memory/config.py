"""Repository-scoped configuration and environment resolution for Agentic Memory.

Loads and merges ``config.json`` from the per-repo control directory, deep-merges
with :data:`DEFAULT_CONFIG` so new settings keys do not break older files, and
exposes helpers that resolve secrets and connection parameters with explicit
precedence (on-disk config vs process environment).

Directory conventions:
    * **Primary:** ``.agentic-memory/`` — current layout; new writes target this
      tree.
    * **Legacy:** ``.codememory/`` — read fallback so in-place upgrades do not
      strand existing repositories.

Typical usage is via :class:`Config` after discovering ``repo_root`` with
:func:`find_repo_root` or :func:`load_config_for_current_dir` for the current
working directory.

See Also:
    ``agentic_memory.cli`` for how commands choose ``--repo``, load namespaced
    ``.env`` files, and pass resolved paths into graph and embedding code.
"""

import os
import json
import copy
from pathlib import Path
from typing import Optional, Dict, Any

CONFIG_DIR_NAME = ".agentic-memory"
LEGACY_CONFIG_DIR_NAME = ".codememory"

# Baseline merged into every loaded file so missing keys get stable defaults
# without requiring operators to edit config.json after upgrades.
DEFAULT_CONFIG = {
    "neo4j": {
        "uri": "bolt://localhost:7687",
        "user": "neo4j",
        "password": "password",
    },
    "openai": {
        "api_key": "",  # Empty means will use env var
    },
    "indexing": {
        "ignore_dirs": [
            "node_modules",
            "__pycache__",
            ".git",
            "dist",
            "build",
            ".venv",
            "venv",
            ".pytest_cache",
            ".mypy_cache",
            "target",
            "bin",
            "obj",
        ],
        "ignore_files": [],
        "extensions": [".py", ".js", ".ts", ".tsx", ".jsx"],
    },
    "git": {
        "enabled": False,
        "auto_incremental": True,
        "sync_trigger": "commit",
        "github_enrichment": {
            "enabled": False,
            "repo": None,
        },
        "checkpoint": {
            "last_sha": None,
        },
    },
    "modules": {
        "code": {
            # Code defaults to Gemini so code memory can live in the same
            # embedding family as the rest of the multimodal Agentic Memory
            # system. Operators can still switch code to another text embedding
            # provider when they want a completely separate code-memory lane.
            "embedding_provider": "gemini",
            "embedding_model": "gemini-embedding-2-preview",
            "embedding_dimensions": 3072,
            # Gemini Embedding 2 preview supports custom task instructions for
            # retrieval-oriented embedding quality. Code chunks are stored as the
            # retrievable corpus, while semantic search queries represent the
            # user's intent to retrieve code from that corpus.
            "embedding_document_task_instruction": "title: none | text: {content}",
            "embedding_query_task_instruction": "task: code retrieval | query: {content}",
        },
        "web": {
            "embedding_provider": "gemini",
            "embedding_model": "gemini-embedding-2-preview",
            # Gemini embedding defaults to 3072 dimensions. Keep the repo
            # default aligned with the index schema so new configs do not
            # create query-time/index-time dimension mismatches.
            "embedding_dimensions": 3072,
        },
        "chat": {
            "embedding_provider": "gemini",
            "embedding_model": "gemini-embedding-2-preview",
            # Conversation memory uses the same Gemini embedding default.
            "embedding_dimensions": 3072,
        },
    },
    "extraction_llm": {
        "provider": "groq",
        "model": "llama-3.3-70b-versatile",
        "base_url": "",
        "api_key": "",  # Empty means fall back to GROQ_API_KEY env var
    },
    "entity_types": [
        "project",
        "person",
        "business",
        "technology",
        "concept",
    ],
    "gemini": {
        "api_key": "",  # Empty means fall back to GEMINI_API_KEY env var
        "use_vertexai": False,
        "project": "",
        "location": "global",
        "api_version": "v1",
    },
    "nemotron": {
        "api_key": "",  # Empty means fall back to NVIDIA_API_KEY env var
        "base_url": "https://integrate.api.nvidia.com/v1",
    },
}


class Config:
    """Per-repository view of ``config.json``, graphignore, and env fallbacks.

    Bridges two on-disk layouts (``.agentic-memory`` primary, ``.codememory``
    legacy): reads prefer the primary file when present, otherwise the legacy
    file; :meth:`save` always writes under the primary directory so migrations
    happen naturally when settings are persisted.

    Attributes:
        repo_root: Absolute repository root used for relative paths in config.
        config_dir: Primary control directory (``.agentic-memory``).
        legacy_config_dir: Legacy control directory (``.codememory``).
        config_file: Primary ``config.json`` path.
        legacy_config_file: Legacy ``config.json`` path.
        graphignore_file: Primary ``.graphignore`` path.
        legacy_graphignore_file: Legacy ``.graphignore`` path.
    """

    def __init__(self, repo_root: Path):
        """Attach paths for the given repository root (no I/O until load/save).

        Args:
            repo_root: Filesystem root of the Git working tree (or project root)
                that contains ``.agentic-memory`` or ``.codememory``.
        """
        self.repo_root = repo_root
        self.config_dir = repo_root / CONFIG_DIR_NAME
        self.legacy_config_dir = repo_root / LEGACY_CONFIG_DIR_NAME
        self.config_file = self.config_dir / "config.json"
        self.legacy_config_file = self.legacy_config_dir / "config.json"
        self.graphignore_file = self.config_dir / ".graphignore"
        self.legacy_graphignore_file = self.legacy_config_dir / ".graphignore"

    def exists(self) -> bool:
        """Check if config exists for this repo."""
        return self.config_file.exists() or self.legacy_config_file.exists()

    def has_primary_config(self) -> bool:
        """Return whether the repo already has the new ``.agentic-memory`` config."""
        return self.config_file.exists()

    def has_legacy_config(self) -> bool:
        """Return whether the repo still only has the legacy ``.codememory`` config."""
        return self.legacy_config_file.exists()

    def active_config_file(self) -> Path:
        """Return the config file path this repo currently loads from.

        The current repo convention wins when both folders exist. This lets the
        CLI show operators the exact path that will be used without duplicating
        config-selection logic across commands.
        """
        if self.has_primary_config():
            return self.config_file
        return self.legacy_config_file

    def load(self) -> Dict[str, Any]:
        """Load merged configuration from disk, or a deep copy of defaults.

        Returns:
            Merged dict including all keys from :data:`DEFAULT_CONFIG`.

        Raises:
            RuntimeError: If JSON is invalid or the file cannot be read.
        """
        if not self.exists():
            return copy.deepcopy(DEFAULT_CONFIG)

        try:
            source = self.config_file if self.config_file.exists() else self.legacy_config_file
            with open(source, "r") as f:
                config = json.load(f)
                # Merge with defaults to handle missing keys
                return self._merge_defaults(config)
        except (json.JSONDecodeError, IOError) as e:
            raise RuntimeError(f"Failed to load config from {source}: {e}")

    def save(self, config: Dict[str, Any]) -> None:
        """Persist configuration to the primary ``config.json`` only.

        Empty API key strings are normalized to ``null`` on write so the next
        resolution pass can fall back to environment variables cleanly.

        Args:
            config: Full configuration dict to serialize (usually from :meth:`load`
                after mutation).
        """
        self.config_dir.mkdir(exist_ok=True)
        payload = copy.deepcopy(config)

        # Don't save empty provider keys - let them fall back to env vars.
        if payload.get("openai", {}).get("api_key") == "":
            payload["openai"]["api_key"] = None
        if payload.get("gemini", {}).get("api_key") == "":
            payload["gemini"]["api_key"] = None
        if payload.get("nemotron", {}).get("api_key") == "":
            payload["nemotron"]["api_key"] = None

        with open(self.config_file, "w") as f:
            json.dump(payload, f, indent=2)

    def ensure_graphignore(self, ignore_dirs: Optional[list[str]] = None) -> None:
        """Create .graphignore with sensible defaults if it does not exist."""
        if self.graphignore_file.exists() or self.legacy_graphignore_file.exists():
            return

        ignore_dirs = ignore_dirs or self.load().get("indexing", {}).get("ignore_dirs", [])
        lines = [
            "# Patterns to exclude from Agentic Memory indexing",
            "# Supports simple glob-style patterns.",
            "# Examples: .venv*/, node_modules/, *.min.js",
            "",
        ]
        for d in ignore_dirs:
            # Directory-style ignore
            lines.append(f"{d}/")
        lines.extend(
            [
                ".venv*/",
                "venv*/",
                "__pypackages__/",
                ".env",
                ".env.*",
                "*.env",
            ]
        )
        with open(self.graphignore_file, "w") as f:
            f.write("\n".join(lines).rstrip() + "\n")

    def get_graphignore_patterns(self) -> list[str]:
        """Load non-empty, non-comment patterns from .graphignore."""
        graphignore_path = (
            self.graphignore_file
            if self.graphignore_file.exists()
            else self.legacy_graphignore_file
        )
        if not graphignore_path.exists():
            return []
        patterns: list[str] = []
        with open(graphignore_path, "r") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                patterns.append(line)
        return patterns

    def _merge_defaults(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Merge user config with defaults."""
        return self._deep_merge_dicts(copy.deepcopy(DEFAULT_CONFIG), config)

    def _deep_merge_dicts(self, base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively merge nested dictionaries."""
        for key, value in overrides.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                base[key] = self._deep_merge_dicts(base[key], value)
            else:
                base[key] = value
        return base

    def get_neo4j_config(self) -> Dict[str, str]:
        """Resolve Neo4j Bolt settings: env overrides file for each field.

        Precedence per key: ``NEO4J_URI`` / ``NEO4J_USER`` or ``NEO4J_USERNAME`` /
        ``NEO4J_PASSWORD`` when set, else the value from ``config.json``.

        Returns:
            Dict with keys ``uri``, ``user``, and ``password``.
        """
        config = self.load()
        neo4j = config["neo4j"]
        # Env wins for CI/Docker; file values are the portable default.
        neo4j_user = os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME")
        return {
            "uri": os.getenv("NEO4J_URI", neo4j["uri"]),
            "user": neo4j_user or neo4j["user"],
            "password": os.getenv("NEO4J_PASSWORD", neo4j["password"]),
        }

    def get_openai_key(self) -> Optional[str]:
        """Return OpenAI API key: non-empty file value first, else ``OPENAI_API_KEY``."""
        config = self.load()
        # File wins when set so a single repo can pin a key; env is the shared default.
        key = config["openai"].get("api_key")
        if key:
            return key
        return os.getenv("OPENAI_API_KEY")

    def get_module_config(self, module_name: str) -> Dict[str, Any]:
        """Get per-module configuration (embedding provider, model, dimensions).

        Args:
            module_name: Module name key (e.g. "code", "web", "chat").

        Returns:
            Configuration dict for the requested module.
        """
        return self.load()["modules"][module_name]

    def get_embedding_provider_config(self, provider_name: str) -> Dict[str, Any]:
        """Get provider-level embedding config such as API keys and base URLs."""
        provider = provider_name.strip().lower()
        config = self.load()
        if provider == "openai":
            return dict(config.get("openai", {}))
        if provider == "gemini":
            return dict(config.get("gemini", {}))
        if provider == "nemotron":
            return dict(config.get("nemotron", {}))
        return {}

    def get_extraction_llm_config(self) -> Dict[str, Any]:
        """Get entity extraction LLM config with env var fallback for api_key.

        Returns:
            Extraction LLM configuration dict with api_key resolved.
        """
        config = self.load()
        extraction = dict(config["extraction_llm"])
        extraction["provider"] = os.getenv(
            "EXTRACTION_LLM_PROVIDER",
            extraction.get("provider") or "groq",
        )
        extraction["model"] = os.getenv(
            "EXTRACTION_LLM_MODEL",
            extraction.get("model")
            or (
                os.getenv("GROQ_MODEL")
                if extraction["provider"] == "groq"
                else ""
            ),
        )
        extraction["base_url"] = os.getenv(
            "EXTRACTION_LLM_BASE_URL",
            extraction.get("base_url") or "",
        )
        if not extraction.get("api_key"):
            extraction["api_key"] = os.getenv("EXTRACTION_LLM_API_KEY", "")
        if extraction.get("api_key"):
            return extraction

        provider = extraction["provider"]
        if provider == "gemini":
            extraction["api_key"] = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
        elif provider == "cerebras":
            extraction["api_key"] = os.getenv("CEREBRAS_API_KEY", "")
        elif provider == "openai":
            extraction["api_key"] = os.getenv("OPENAI_API_KEY", "")
        else:
            extraction["api_key"] = os.getenv("GROQ_API_KEY", "")
        return extraction

    def get_gemini_key(self) -> Optional[str]:
        """Get Gemini API key from config, falling back to GEMINI_API_KEY env var.

        Returns:
            Gemini API key string, or None if not configured.
        """
        config = self.load()
        key = config.get("gemini", {}).get("api_key")
        if key:
            return key
        return os.getenv("GEMINI_API_KEY")

    def get_entity_types(self) -> list[str]:
        """Get the list of supported entity types from config.

        Returns:
            List of entity type strings (e.g. ["project", "person", ...]).
        """
        return list(self.load()["entity_types"])

    def get_indexing_config(self) -> Dict[str, Any]:
        """Get indexing configuration."""
        return self.load()["indexing"]

    def get_git_config(self) -> Dict[str, Any]:
        """Get git graph configuration."""
        return self.load()["git"]

    def save_git_config(self, git_config: Dict[str, Any]) -> None:
        """Merge and persist git graph configuration."""
        config = self.load()
        merged_git = self._deep_merge_dicts(
            copy.deepcopy(DEFAULT_CONFIG["git"]),
            config.get("git", {}),
        )
        config["git"] = self._deep_merge_dicts(merged_git, git_config)
        self.save(config)


def find_repo_root(start_path: Path = None) -> Optional[Path]:
    """Walk parents for Agentic Memory dirs, then Git metadata, then cwd.

    Resolution order (first match wins):
        #. Directory containing ``.agentic-memory``
        #. Directory containing ``.codememory``
        #. Directory containing ``.git`` (so uninitialized AM dirs still get a root)
        #. ``start_path`` resolved (fallback)

    Args:
        start_path: Directory to begin walking upward; defaults to :func:`Path.cwd`.

    Returns:
        Resolved :class:`~pathlib.Path` to the chosen root. If no marker directory
        is found, returns ``start_path.resolve()`` (always a concrete path).
    """
    start_path = start_path or Path.cwd()
    current = start_path.resolve()

    # Prefer the renamed Agentic Memory config root, but continue honoring the
    # legacy CodeMemory folder so older repos still resolve correctly.
    while current != current.parent:
        if (current / CONFIG_DIR_NAME).exists():
            return current
        if (current / LEGACY_CONFIG_DIR_NAME).exists():
            return current
        current = current.parent

    # Not found, check if current dir is a git repo
    current = start_path.resolve()
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent

    # Fallback to current directory
    return start_path.resolve()


def load_config_for_current_dir() -> Optional[Config]:
    """Return a :class:`Config` for cwd if either control directory exists.

    Uses :func:`find_repo_root` then checks for ``.agentic-memory`` or
    ``.codememory`` under that root. Commands use this to decide whether the
    operator has run ``init`` in the tree.

    Returns:
        Bound :class:`Config` instance, or ``None`` if no control directory is
        present (repo not initialized for Agentic Memory).
    """
    repo_root = find_repo_root()
    config_dir = repo_root / CONFIG_DIR_NAME
    legacy_dir = repo_root / LEGACY_CONFIG_DIR_NAME

    if not config_dir.exists() and not legacy_dir.exists():
        return None

    return Config(repo_root)
