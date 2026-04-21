"""``python -m codememory`` entry point.

Runs the same CLI as ``agent-memory`` by delegating to
``agentic_memory.cli.main``. This keeps the historical ``codememory`` package
name usable as a module runner without duplicating argument parsing or commands.

Example:
    From the repository root (with the package installed)::

        python -m codememory --help

Note:
    Configuration, subcommands, and behavior are defined entirely in
    ``agentic_memory.cli``; this module only wires ``__main__`` to that main.
"""

from agentic_memory.cli import main


if __name__ == "__main__":
    main()
