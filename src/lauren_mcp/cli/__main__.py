"""Allow ``python -m lauren_mcp.cli`` to invoke the ``lmcp`` CLI."""

from __future__ import annotations

from . import app

if __name__ == "__main__":
    app()
