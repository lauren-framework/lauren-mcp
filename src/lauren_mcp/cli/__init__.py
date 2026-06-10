"""Lauren MCP CLI entry point.

Install with ``pip install 'lauren-mcp[cli]'`` then run ``lmcp --help``.
"""

from __future__ import annotations

import typer

app = typer.Typer(
    name="lmcp",
    help="lauren-mcp development CLI.",
    no_args_is_help=True,
)

from lauren_mcp.cli._commands import call, dev, inspect_cmd, install, run  # noqa: E402, F401

app.command("run")(run)
app.command("dev")(dev)
app.command("inspect")(inspect_cmd)
app.command("call")(call)
app.command("install")(install)
