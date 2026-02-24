"""
Configuration management for Agentic Memory.

Handles per-repository configuration stored in .codememory/ directory.
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
}


class Config:
    """Manages Agentic Memory configuration for a repository."""

    def __init__(self, repo_root: Path):
        """
        Initialize config for a repository.

        Args:
            repo_root: Path to the repository root
        """
        self.repo_root = repo_root
        self.config_dir = repo_root / ".codememory"
        self.config_file = self.config_dir / "config.json"
        self.graphignore_file = self.config_dir / ".graphignore"

    def exists(self) -> bool:
        """Check if config exists for this repo."""
        return self.config_file.exists()

    def load(self) -> Dict[str, Any]:
        """Load config from file, or return defaults if not exists."""
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
        """Save config to file."""
        self.config_dir.mkdir(exist_ok=True)
        payload = copy.deepcopy(config)

        # Don't save empty api_key - let it fall back to env var
        if payload.get("openai", {}).get("api_key") == "":
            payload["openai"]["api_key"] = None

        with open(self.config_file, "w") as f:
            json.dump(payload, f, indent=2)

    def ensure_graphignore(self, ignore_dirs: Optional[list[str]] = None) -> None:
        """Create .graphignore with sensible defaults if it does not exist."""
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
        """Load non-empty, non-comment patterns from .graphignore."""
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
        """Get Neo4j connection config, with env var fallbacks."""
        config = self.load()
        neo4j = config["neo4j"]
        return {
            "uri": os.getenv("NEO4J_URI", neo4j["uri"]),
            "user": os.getenv("NEO4J_USER", neo4j["user"]),
            "password": os.getenv("NEO4J_PASSWORD", neo4j["password"]),
        }

    def get_openai_key(self) -> Optional[str]:
        """Get OpenAI API key, with env var fallback."""
        config = self.load()
        # Priority: config file > env var
        key = config["openai"].get("api_key")
        if key:
            return key
        return os.getenv("OPENAI_API_KEY")

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
    """
    Find the repository root by looking for .codememory directory.

    Args:
        start_path: Path to start searching from (defaults to cwd)

    Returns:
        Path to repo root, or None if not found
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
    """
    Load config for the current directory.

    Returns:
        Config object, or None if not in a codememory-initialized repo
    """
    repo_root = find_repo_root()
    codememory_dir = repo_root / ".codememory"

    if not codememory_dir.exists():
        return None

    return Config(repo_root)
