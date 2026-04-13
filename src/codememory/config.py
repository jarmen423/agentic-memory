"""Per-repository configuration for CodeMemory (``.codememory/``).

Reads and writes ``.codememory/config.json``, merges user values with
``DEFAULT_CONFIG`` so new keys get safe defaults, and resolves secrets and
connection strings from environment variables when files omit them. Also
manages ``.codememory/.graphignore`` for indexing exclusions.

Typical on-disk layout::

    <repo_root>/.codememory/
        config.json      # Neo4j, embeddings, indexing, git, modules, etc.
        .graphignore     # Optional path patterns excluded from the graph

The ``Config`` class is constructed with a repository root and exposes load/save
plus typed accessors (Neo4j, OpenAI, per-module embedding settings, extraction
LLM, git).

Attributes:
    DEFAULT_CONFIG: Deep dict of factory defaults merged on load; not mutated
        by callers—use ``Config.load`` / ``Config.save`` for I/O.
"""

import os
import json
import copy
from pathlib import Path
from typing import Optional, Dict, Any

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
    },
    "nemotron": {
        "api_key": "",  # Empty means fall back to NVIDIA_API_KEY env var
        "base_url": "https://integrate.api.nvidia.com/v1",
    },
}


class Config:
    """Load, merge, and persist CodeMemory settings for one repository.

    All paths are anchored at ``repo_root``; ``config_file`` is
    ``<repo_root>/.codememory/config.json`` and ``graphignore_file`` is
    ``<repo_root>/.codememory/.graphignore``.

    Attributes:
        repo_root: Absolute or resolved repository root directory.
        config_dir: ``.codememory`` directory under the repo root.
        config_file: JSON configuration path.
        graphignore_file: Ignore patterns file for the indexer.
    """

    def __init__(self, repo_root: Path) -> None:
        """Create a config handle for ``repo_root``.

        Args:
            repo_root: Root of the Git working tree (or project root) that
                contains or will contain ``.codememory/``.
        """
        self.repo_root = repo_root
        self.config_dir = repo_root / ".codememory"
        self.config_file = self.config_dir / "config.json"
        self.graphignore_file = self.config_dir / ".graphignore"

    def exists(self) -> bool:
        """Return True if ``config_file`` is present on disk."""
        return self.config_file.exists()

    def load(self) -> Dict[str, Any]:
        """Load JSON config merged with defaults, or return a deep copy of defaults.

        Returns:
            Merged configuration dict (Neo4j, providers, indexing, git, modules,
            etc.).

        Raises:
            RuntimeError: If the file exists but is not valid JSON or cannot be
                read.
        """
        if not self.exists():
            return copy.deepcopy(DEFAULT_CONFIG)

        try:
            with open(self.config_file, "r") as f:
                config = json.load(f)
                # Merge with defaults to handle missing keys
                return self._merge_defaults(config)
        except (json.JSONDecodeError, IOError) as e:
            raise RuntimeError(f"Failed to load config from {self.config_file}: {e}")

    def save(self, config: Dict[str, Any]) -> None:
        """Persist ``config`` to ``config_file`` with normalized empty API keys.

        Empty string API key fields are written as JSON null so the next load
        falls back to environment variables.

        Args:
            config: Full configuration dict to serialize (typically from
                ``load`` after edits).
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
        """Create ``.graphignore`` with defaults if the file is missing.

        Uses ``ignore_dirs`` if provided; otherwise reads ``indexing.ignore_dirs``
        from the loaded config. Idempotent when the file already exists.

        Args:
            ignore_dirs: Optional directory names to write as ignore patterns;
                trailing slashes are added per line.
        """
        if self.graphignore_file.exists():
            return

        ignore_dirs = ignore_dirs or self.load().get("indexing", {}).get("ignore_dirs", [])
        lines = [
            "# Patterns to exclude from codememory indexing",
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
        """Return active patterns from ``graphignore_file``, skipping blanks and ``#`` comments.

        Returns:
            List of pattern strings, or an empty list if the file is missing.
        """
        if not self.graphignore_file.exists():
            return []
        patterns: list[str] = []
        with open(self.graphignore_file, "r") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                patterns.append(line)
        return patterns

    def _merge_defaults(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Deep-merge ``config`` onto a copy of ``DEFAULT_CONFIG``.

        Args:
            config: User-supplied dict from JSON.

        Returns:
            Merged dict with all default keys present.
        """
        return self._deep_merge_dicts(copy.deepcopy(DEFAULT_CONFIG), config)

    def _deep_merge_dicts(self, base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively merge ``overrides`` into ``base`` (dict values merge, scalars replace).

        Args:
            base: Dict to mutate and return.
            overrides: Shallow or nested overrides from the user file.

        Returns:
            The same ``base`` object after merge.
        """
        for key, value in overrides.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                base[key] = self._deep_merge_dicts(base[key], value)
            else:
                base[key] = value
        return base

    def get_neo4j_config(self) -> Dict[str, str]:
        """Resolve Neo4j Bolt settings from config and environment.

        Environment variables override file values: ``NEO4J_URI``,
        ``NEO4J_USER`` or ``NEO4J_USERNAME``, ``NEO4J_PASSWORD``.

        Returns:
            Dict with keys ``uri``, ``user``, ``password``.
        """
        config = self.load()
        neo4j = config["neo4j"]
        neo4j_user = os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME")
        return {
            "uri": os.getenv("NEO4J_URI", neo4j["uri"]),
            "user": neo4j_user or neo4j["user"],
            "password": os.getenv("NEO4J_PASSWORD", neo4j["password"]),
        }

    def get_openai_key(self) -> Optional[str]:
        """Return OpenAI API key from config, else ``OPENAI_API_KEY`` env.

        Returns:
            Non-empty key string, or None if unset.
        """
        config = self.load()
        # Priority: config file > env var
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
        """Return provider-scoped settings (keys, base URLs) for embedding calls.

        Args:
            provider_name: One of ``openai``, ``gemini``, ``nemotron`` (case
                insensitive); unknown names yield ``{}``.

        Returns:
            A shallow copy of the matching subsection of the loaded config.
        """
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
        """Return the ``indexing`` subsection (ignore lists, extensions, etc.)."""
        return self.load()["indexing"]

    def get_git_config(self) -> Dict[str, Any]:
        """Return the ``git`` subsection (ingestion flags, checkpoint, GitHub)."""
        return self.load()["git"]

    def save_git_config(self, git_config: Dict[str, Any]) -> None:
        """Deep-merge ``git_config`` into stored git settings and save.

        Args:
            git_config: Partial or full git dict to merge over existing config
                and defaults.
        """
        config = self.load()
        merged_git = self._deep_merge_dicts(
            copy.deepcopy(DEFAULT_CONFIG["git"]),
            config.get("git", {}),
        )
        config["git"] = self._deep_merge_dicts(merged_git, git_config)
        self.save(config)


def find_repo_root(start_path: Path = None) -> Optional[Path]:
    """Walk parents from ``start_path`` for ``.codememory``, then ``.git``, else cwd.

    Args:
        start_path: Directory to begin the upward walk; defaults to
            ``Path.cwd()``.

    Returns:
        The nearest ancestor of ``start_path`` that contains ``.codememory``;
        if none, the nearest ancestor that contains ``.git``; if still none,
        ``start_path.resolve()`` as a deterministic fallback.
    """
    start_path = start_path or Path.cwd()
    current = start_path.resolve()

    # Walk up directories looking for .codememory
    while current != current.parent:
        codememory_dir = current / ".codememory"
        if codememory_dir.exists():
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
    """Build a ``Config`` for the current working directory when initialized.

    Uses ``find_repo_root`` and requires ``<repo>/.codememory`` to exist.

    Returns:
        ``Config`` instance when ``.codememory`` is present under the discovered
        root; otherwise ``None``.
    """
    repo_root = find_repo_root()
    codememory_dir = repo_root / ".codememory"

    if not codememory_dir.exists():
        return None

    return Config(repo_root)
