"""File-spec resolution for the ``lmcp`` CLI.

A "file spec" is ``path/to/server.py`` or ``path/to/server.py:ClassName``.
:func:`resolve_server_class` imports the module and returns the
``@mcp_server``-decorated class, raising a helpful error when things go wrong.
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path
from typing import Any

from lauren_mcp.server._meta import MCP_SERVER_META


def resolve_server_class(spec: str) -> type:
    """Import *spec* and return the ``@mcp_server``-decorated class.

    *spec* may be:

    - ``"server.py"``           — find the first (and only) ``@mcp_server`` class
    - ``"server.py:MyServer"``  — use the named class

    Raises :class:`typer.BadParameter` (via :func:`_die`) with a helpful message
    on failure.
    """
    if ":" in spec:
        file_part, class_name = spec.rsplit(":", 1)
    else:
        file_part, class_name = spec, None

    path = Path(file_part).resolve()
    if not path.exists():
        _die(f"File not found: {path}")

    # Add the parent directory to sys.path so relative imports work.
    parent = str(path.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)

    module_name = path.stem
    spec_obj = importlib.util.spec_from_file_location(module_name, path)
    if spec_obj is None or spec_obj.loader is None:
        _die(f"Cannot import {path}")

    assert spec_obj is not None  # guarded above
    module = importlib.util.module_from_spec(spec_obj)
    sys.modules[module_name] = module
    spec_obj.loader.exec_module(module)  # type: ignore[union-attr]

    if class_name is not None:
        cls: Any = getattr(module, class_name, None)
        if cls is None:
            _die(f"No attribute {class_name!r} in {path}")
        if not hasattr(cls, MCP_SERVER_META):
            _die(f"{class_name!r} is not decorated with @mcp_server")
        return type(cls)  # type: ignore[return-value]
        return cls

    # Auto-discover: find all @mcp_server classes in module.
    candidates = [
        obj
        for obj in vars(module).values()
        if inspect.isclass(obj) and hasattr(obj, MCP_SERVER_META)
    ]
    if len(candidates) == 0:
        _die(f"No @mcp_server class found in {path}")
    if len(candidates) > 1:
        names = ", ".join(c.__name__ for c in candidates)
        _die(
            f"Multiple @mcp_server classes found in {path}: {names}\n"
            "Specify which one with 'file.py:ClassName'."
        )
    return candidates[0]


def _die(msg: str) -> None:
    import typer  # noqa: PLC0415

    raise typer.BadParameter(msg)
