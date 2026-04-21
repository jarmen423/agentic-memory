"""Support ``python -m agentic_memory`` as an alternate CLI entry path.

This module exists so the same ``main()`` routine used by the ``agent-memory``
and ``codememory`` console scripts (defined in ``pyproject.toml``) can be
invoked when Python is asked to run the package as a module. Behavior is
identical to calling ``agentic_memory.cli:main`` directly.

Note:
    Prefer the installed console script in automation and documentation;
    ``python -m`` is useful in editable installs and when the script shim is
    not on ``PATH``.
"""

from agentic_memory.cli import main


# Module execution: delegate to the full argparse tree and subcommand dispatch
# in cli.main() (same entry as setuptools console_scripts).
if __name__ == "__main__":
    main()
