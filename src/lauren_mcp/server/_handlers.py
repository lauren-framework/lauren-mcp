"""Handler factories that generate async callables for the MCP dispatcher."""

from __future__ import annotations

import json
import re
from typing import Any

from lauren_mcp._types import JsonRpcRequest

from ._meta import McpPromptMeta, McpResourceMeta, McpToolMeta

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def make_tools_list_handler(tools: list[McpToolMeta]):
    """Return an async handler for ``tools/list``."""
    schemas = [
        {
            "name": t.name,
            "description": t.description,
            "inputSchema": t.input_schema,
        }
        for t in tools
    ]

    async def handler(req: JsonRpcRequest) -> dict:
        return {"tools": schemas}

    return handler


def make_tools_call_handler(server_instance: Any, tools: list[McpToolMeta]):
    """Return an async handler for ``tools/call``.

    Dispatches to ``server_instance.<method_name>(**arguments)``.
    """
    tool_map = {t.name: t for t in tools}

    async def handler(req: JsonRpcRequest) -> dict:
        params = req.params or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name not in tool_map:
            raise ValueError(f"Unknown tool: {name!r}")
        meta = tool_map[name]
        method = getattr(server_instance, meta.method_name)
        result = await method(**arguments)
        if isinstance(result, str):
            content = [{"type": "text", "text": result}]
        elif isinstance(result, (dict, list)):
            content = [{"type": "text", "text": json.dumps(result)}]
        else:
            content = [{"type": "text", "text": str(result)}]
        return {"content": content, "isError": False}

    return handler


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


def make_resources_list_handler(resources: list[McpResourceMeta]):
    """Return an async handler for ``resources/list``."""
    schemas = [
        {
            "uri": r.uri_template,
            "name": r.name,
            **({"description": r.description} if r.description is not None else {}),
            **({"mimeType": r.mime_type} if r.mime_type is not None else {}),
        }
        for r in resources
    ]

    async def handler(req: JsonRpcRequest) -> dict:
        return {"resources": schemas}

    return handler


def _compile_uri_pattern(template: str) -> re.Pattern:
    """Compile a URI template like ``/items/{id}`` to a named-group regex."""
    escaped = re.escape(template)
    # re.escape turns { → \{ and } → \} — unescape those, then replace
    escaped = escaped.replace(r"\{", "{").replace(r"\}", "}")
    pattern = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", escaped)
    return re.compile(f"^{pattern}$")


def make_resources_read_handler(server_instance: Any, resources: list[McpResourceMeta]):
    """Return an async handler for ``resources/read``.

    Matches the requested URI against compiled URI-template patterns and
    calls the corresponding method with extracted path variables.
    """
    compiled = [(r, _compile_uri_pattern(r.uri_template)) for r in resources]

    async def handler(req: JsonRpcRequest) -> dict:
        params = req.params or {}
        uri = params.get("uri", "")
        for meta, pattern in compiled:
            m = pattern.match(uri)
            if m:
                kwargs = m.groupdict()
                method = getattr(server_instance, meta.method_name)
                result = await method(**kwargs)
                # Normalise result to a ResourceContent-compatible dict
                if isinstance(result, str):
                    content = {"uri": uri, "text": result}
                    if meta.mime_type:
                        content["mimeType"] = meta.mime_type
                    contents = [content]
                elif isinstance(result, dict):
                    contents = [result]
                elif isinstance(result, list):
                    contents = result
                else:
                    contents = [{"uri": uri, "text": str(result)}]
                return {"contents": contents}
        raise ValueError(f"No resource matches URI: {uri!r}")

    return handler


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


def make_prompts_list_handler(prompts: list[McpPromptMeta]):
    """Return an async handler for ``prompts/list``."""
    schemas = []
    for p in prompts:
        entry: dict = {"name": p.name}
        if p.description is not None:
            entry["description"] = p.description
        if p.arguments:
            entry["arguments"] = p.arguments
        schemas.append(entry)

    async def handler(req: JsonRpcRequest) -> dict:
        return {"prompts": schemas}

    return handler


def make_prompts_get_handler(server_instance: Any, prompts: list[McpPromptMeta]):
    """Return an async handler for ``prompts/get``.

    Dispatches to ``server_instance.<method_name>(**arguments)`` and
    expects the method to return either a string (turned into a single
    user message) or a dict/list matching the MCP GetPromptResult shape.
    """
    prompt_map = {p.name: p for p in prompts}

    async def handler(req: JsonRpcRequest) -> dict:
        params = req.params or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name not in prompt_map:
            raise ValueError(f"Unknown prompt: {name!r}")
        meta = prompt_map[name]
        method = getattr(server_instance, meta.method_name)
        result = await method(**arguments)
        # Normalise to GetPromptResult shape
        if isinstance(result, str):
            return {
                "description": meta.description or name,
                "messages": [{"role": "user", "content": {"type": "text", "text": result}}],
            }
        elif isinstance(result, dict):
            # Already a GetPromptResult-like dict
            return result
        else:
            return {
                "description": meta.description or name,
                "messages": [{"role": "user", "content": {"type": "text", "text": str(result)}}],
            }

    return handler
