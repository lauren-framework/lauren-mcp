"""Decorators: mcp_server, mcp_tool, mcp_resource, mcp_prompt."""

from __future__ import annotations

import inspect
import typing
from collections.abc import Callable
from typing import Any

from ._meta import (
    MCP_PROMPT_META,
    MCP_RESOURCE_META,
    MCP_SERVER_META,
    MCP_TOOL_META,
    McpPromptMeta,
    McpResourceMeta,
    McpServerMeta,
    McpToolMeta,
)

_SENTINEL = object()

# ---------------------------------------------------------------------------
# Type-to-JSON-Schema mapping
# ---------------------------------------------------------------------------

_PY_TO_JSON: dict[Any, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
    type(None): "string",
}


def _json_type(annotation: Any) -> str:
    """Map a Python type annotation to a JSON Schema type string."""
    if annotation is inspect.Parameter.empty:
        return "string"
    # Handle Optional[X] / Union[X, None] by extracting the non-None arg
    origin = getattr(annotation, "__origin__", None)
    if origin is typing.Union:
        args = [a for a in annotation.__args__ if a is not type(None)]
        if args:
            return _json_type(args[0])
        return "string"
    return _PY_TO_JSON.get(annotation, "string")


def _extract_description(fn: Callable) -> str:
    """Return first non-empty line of docstring, stopping before 'Args:' etc."""
    doc = fn.__doc__
    if not doc:
        return ""
    lines = doc.strip().splitlines()
    parts: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith(("args:", "returns:", "raises:", "example")):
            break
        if stripped:
            parts.append(stripped)
        elif parts:
            # blank line after first paragraph — stop
            break
    return " ".join(parts)


def _build_schema(fn: Callable) -> tuple[str, str, dict[str, Any]]:
    """Build ``(name, description, json_schema)`` from a function's signature.

    * Uses ``inspect.signature`` and ``typing.get_type_hints`` (with fallback).
    * Skips ``self``.
    * Parameters without a default are marked as required.
    """
    name = fn.__name__
    description = _extract_description(fn)

    try:
        hints = typing.get_type_hints(fn)
    except Exception:
        hints = {}

    sig = inspect.signature(fn)
    properties: dict[str, Any] = {}
    required: list[str] = []

    for param_name, param in sig.parameters.items():
        if param_name == "self":
            continue
        annotation = hints.get(param_name, param.annotation)
        json_t = _json_type(annotation)
        properties[param_name] = {"type": json_t}
        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required

    return name, description, schema


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------


def mcp_server(path: str, *, transport: str = "ws"):
    """Class decorator that marks a class as an MCP server.

    Applies ``@injectable(scope=Scope.SINGLETON)`` from Lauren so the class
    participates in DI, and attaches :class:`McpServerMeta` as an attribute.

    Args:
        path: The mount path for the MCP server endpoint (e.g. ``"/mcp"``).
        transport: One of ``"ws"``, ``"sse"``, or ``"both"``.
    """

    def decorator(cls: type) -> type:
        from lauren import Scope, injectable

        injectable(scope=Scope.SINGLETON)(cls)
        setattr(cls, MCP_SERVER_META, McpServerMeta(path=path, transport=transport))
        return cls

    return decorator


def mcp_tool(*, name: str | None = None, description: str | None = None):
    """Method decorator that exposes a coroutine as an MCP tool.

    Args:
        name: Override the tool name (defaults to the method name).
        description: Override the tool description (defaults to docstring).
    """

    def decorator(fn: Callable) -> Callable:
        auto_name, auto_desc, schema = _build_schema(fn)
        resolved_name = name if name is not None else auto_name
        resolved_desc = description if description is not None else auto_desc
        meta = McpToolMeta(
            name=resolved_name,
            description=resolved_desc,
            input_schema=schema,
            method_name=fn.__name__,
        )
        setattr(fn, MCP_TOOL_META, meta)
        return fn

    return decorator


def mcp_resource(
    uri_template: str,
    *,
    name: str | None = None,
    description: str | None = None,
    mime_type: str | None = None,
):
    """Method decorator that exposes a coroutine as an MCP resource.

    Args:
        uri_template: A URI template with optional ``{param}`` placeholders.
        name: Resource name (defaults to the method name).
        description: Human-readable description (defaults to docstring).
        mime_type: Optional MIME type hint (e.g. ``"text/plain"``).
    """

    def decorator(fn: Callable) -> Callable:
        resolved_name = name if name is not None else fn.__name__
        resolved_desc = description if description is not None else _extract_description(fn)
        meta = McpResourceMeta(
            uri_template=uri_template,
            name=resolved_name,
            description=resolved_desc,
            mime_type=mime_type,
            method_name=fn.__name__,
        )
        setattr(fn, MCP_RESOURCE_META, meta)
        return fn

    return decorator


def mcp_prompt(name: str | None = None, *, description: str | None = None):
    """Method decorator that exposes a coroutine as an MCP prompt.

    Args:
        name: Prompt name (defaults to the method name).
        description: Human-readable description (defaults to docstring).
    """

    def decorator(fn: Callable) -> Callable:
        resolved_name = name if name is not None else fn.__name__
        resolved_desc = description if description is not None else _extract_description(fn)

        sig = inspect.signature(fn)
        arguments: list[dict] = []
        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue
            arg_entry: dict = {
                "name": param_name,
                "description": None,
                "required": param.default is inspect.Parameter.empty,
            }
            arguments.append(arg_entry)

        meta = McpPromptMeta(
            name=resolved_name,
            description=resolved_desc,
            arguments=arguments,
            method_name=fn.__name__,
        )
        setattr(fn, MCP_PROMPT_META, meta)
        return fn

    return decorator
