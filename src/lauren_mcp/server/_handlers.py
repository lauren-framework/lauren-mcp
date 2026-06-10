"""Handler factories that generate async callables for the MCP dispatcher."""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from lauren_mcp._server._binding import CURRENT_BINDING
from lauren_mcp._server._context import LogLevelState, McpToolContext
from lauren_mcp._types import (
    BlobResource,
    EmbeddedResource,
    ImageContent,
    JsonRpcRequest,
    ResourceContent,
    ResourceResult,
    TextContent,
    ToolOutput,
)

from ._meta import McpPromptMeta, McpResourceMeta, McpToolMeta
from ._uri import coerce_params, compile_uri_template, match_uri

_logger = logging.getLogger(__name__)

_Handler = Callable[[JsonRpcRequest], Coroutine[Any, Any, dict[str, Any]]]

#: Builds an McpToolContext for one tool call.
ContextFactory = Callable[[str, str | int | None, str | int | None], McpToolContext]


def make_context_factory(
    metadata: dict[str, Any] | None = None,
    *,
    lifespan_getter: Callable[[], dict[str, Any]] | None = None,
    log_level_state: LogLevelState | None = None,
) -> ContextFactory:
    """Build a :data:`ContextFactory` that merges server-level state with the
    per-call transport binding (:data:`CURRENT_BINDING`)."""

    def factory(
        tool_name: str,
        tool_use_id: str | int | None,
        progress_token: str | int | None,
    ) -> McpToolContext:
        binding = CURRENT_BINDING.get()
        return McpToolContext(
            tool_name=tool_name,
            tool_use_id=tool_use_id,
            headers=binding.headers if binding else None,
            execution_context=binding.execution_context if binding else None,
            session_id=binding.session_id if binding else None,
            metadata=dict(metadata or {}),
            state={},
            extras=dict(binding.extras) if binding else {},
            lifespan_context=lifespan_getter() if lifespan_getter else {},
            _progress_token=progress_token,
            _send_notification=binding.send_notification if binding else None,
            _client_rpc=binding.client_rpc if binding else None,
            _client_capabilities=binding.client_capabilities if binding else None,
            _log_level_state=log_level_state,
        )

    return factory


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def _tool_list_entry(t: McpToolMeta) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "name": t.name,
        "description": t.description,
        "inputSchema": t.input_schema,
    }
    if t.annotations is not None:
        entry["annotations"] = t.annotations.to_dict()
    if t.output_schema is not None:
        entry["outputSchema"] = t.output_schema
    if t.tags:
        entry["tags"] = sorted(t.tags)
    if t.meta:
        entry["_meta"] = t.meta
    return entry


def make_tools_list_handler(
    tools: list[McpToolMeta] | Callable[[], list[McpToolMeta]],
) -> _Handler:
    """Return an async handler for ``tools/list``.

    *tools* may be a static list or a zero-arg callable returning the current
    catalogue (used by the dynamic catalog manager).
    """
    get_tools = tools if callable(tools) else (lambda: tools)

    async def handler(req: JsonRpcRequest) -> dict[str, Any]:
        return {"tools": [_tool_list_entry(t) for t in get_tools()]}

    return handler


def _coerce_content_block(item: Any) -> dict[str, Any]:
    """Normalise one content item to its wire dict."""
    if isinstance(item, dict):
        return item
    if isinstance(item, TextContent):
        return {"type": "text", "text": item.text}
    if isinstance(item, ImageContent):
        return {"type": "image", "data": item.data, "mimeType": item.mimeType}
    if isinstance(item, EmbeddedResource):
        return {"type": "resource", "resource": item.resource}
    return {"type": "text", "text": str(item)}


def _is_msgspec_struct(obj: Any) -> bool:
    if not hasattr(type(obj), "__struct_fields__"):
        return False
    try:
        import msgspec
    except ImportError:
        return False
    return isinstance(obj, msgspec.Struct)


def _model_dump(obj: Any) -> dict[str, Any]:
    if hasattr(obj, "model_dump"):  # pydantic v2
        return dict(obj.model_dump(mode="json"))
    if hasattr(obj, "dict"):  # pydantic v1
        return dict(obj.dict())
    raise TypeError(f"Cannot serialise {type(obj).__name__} to structured content")


def _coerce_tool_result(result: Any, meta: McpToolMeta) -> dict[str, Any]:
    """Coerce a tool's raw return value into the ``tools/call`` result shape."""
    structured: dict[str, Any] | None = None
    is_error = False

    if isinstance(result, ToolOutput):
        content = [_coerce_content_block(c) for c in (result.content or [])]
        structured = result.structured_content
        is_error = result.is_error
        if not content and structured is not None:
            content = [{"type": "text", "text": json.dumps(structured)}]
    elif isinstance(result, (TextContent, ImageContent, EmbeddedResource)):
        content = [_coerce_content_block(result)]
    elif isinstance(result, str):
        content = [{"type": "text", "text": result}]
    elif isinstance(result, dict):
        content = [{"type": "text", "text": json.dumps(result)}]
        structured = result
    elif isinstance(result, list):
        content = [{"type": "text", "text": json.dumps(result)}]
        structured = {"result": result}
    elif dataclasses.is_dataclass(result) and not isinstance(result, type):
        structured = dataclasses.asdict(result)
        content = [{"type": "text", "text": json.dumps(structured)}]
    elif _is_msgspec_struct(result):
        import msgspec

        structured = msgspec.to_builtins(result)
        content = [{"type": "text", "text": json.dumps(structured)}]
    elif hasattr(result, "model_dump") or hasattr(result, "dict"):
        structured = _model_dump(result)
        content = [{"type": "text", "text": json.dumps(structured)}]
    else:
        content = [{"type": "text", "text": str(result)}]

    out: dict[str, Any] = {"content": content, "isError": is_error}
    if structured is not None:
        out["structuredContent"] = structured
    return out


def _validate_output(structured: dict[str, Any] | None, meta: McpToolMeta) -> None:
    """Validate structured content against the declared output schema.

    Only the cheap top-level checks are done in-process (type/object,
    required keys) — full JSON Schema validation would need an extra
    dependency.
    """
    schema = meta.output_schema
    if schema is None or structured is None:
        return
    for key in schema.get("required", []):
        if key not in structured:
            raise ValueError(
                f"Tool {meta.name!r} structured output is missing required "
                f"key {key!r} declared in its outputSchema"
            )


def make_tools_call_handler(
    server_instance: Any,
    tools: list[McpToolMeta] | Callable[[], list[McpToolMeta]],
    *,
    context_factory: ContextFactory | None = None,
) -> _Handler:
    """Return an async handler for ``tools/call``.

    Dispatches to ``server_instance.<method_name>(**arguments)``.  When a tool
    declares a ``McpToolContext`` parameter and *context_factory* is supplied,
    the context is injected under the declared parameter name.
    """
    get_tools = tools if callable(tools) else (lambda: tools)

    async def handler(req: JsonRpcRequest) -> dict[str, Any]:
        params: dict[str, Any] = req.params if isinstance(req.params, dict) else {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        tool_map = {t.name: t for t in get_tools()}
        if name not in tool_map:
            raise ValueError(f"Unknown tool: {name!r}")
        meta = tool_map[name]
        target = getattr(meta, "_bound_instance", None) or server_instance
        method = getattr(target, meta.method_name)
        kwargs = dict(arguments)

        if meta.reads_context and meta.context_param_name and context_factory is not None:
            request_meta = params.get("_meta") or {}
            progress_token = (
                request_meta.get("progressToken") if isinstance(request_meta, dict) else None
            )
            kwargs[meta.context_param_name] = context_factory(meta.name, req.id, progress_token)

        if meta.timeout is not None:
            try:
                result = await asyncio.wait_for(method(**kwargs), timeout=meta.timeout)
            except TimeoutError:
                raise ValueError(
                    f"Tool {meta.name!r} execution timed out after {meta.timeout}s"
                ) from None
        else:
            result = await method(**kwargs)

        out = _coerce_tool_result(result, meta)
        _validate_output(out.get("structuredContent"), meta)
        return out

    return handler


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


def make_resources_list_handler(
    resources: list[McpResourceMeta] | Callable[[], list[McpResourceMeta]],
) -> _Handler:
    """Return an async handler for ``resources/list``."""
    get_resources = resources if callable(resources) else (lambda: resources)

    async def handler(req: JsonRpcRequest) -> dict[str, Any]:
        return {
            "resources": [
                {
                    "uri": r.uri_template,
                    "name": r.name,
                    **({"description": r.description} if r.description is not None else {}),
                    **({"mimeType": r.mime_type} if r.mime_type is not None else {}),
                }
                for r in get_resources()
            ]
        }

    return handler


def _coerce_resource_item(item: Any, uri: str, meta: McpResourceMeta) -> dict[str, Any]:
    """Normalise one resource content item to its wire dict."""
    if isinstance(item, dict):
        return item
    if isinstance(item, ResourceContent):
        out: dict[str, Any] = {"uri": item.uri or uri}
        if item.mimeType is not None:
            out["mimeType"] = item.mimeType
        if item.text is not None:
            out["text"] = item.text
        if item.blob is not None:
            out["blob"] = item.blob
        return out
    if isinstance(item, BlobResource):
        return {
            "uri": uri,
            "mimeType": meta.mime_type or item.mime_type,
            "blob": base64.b64encode(item.data).decode("ascii"),
        }
    if isinstance(item, bytes):
        return {
            "uri": uri,
            "mimeType": meta.mime_type or "application/octet-stream",
            "blob": base64.b64encode(item).decode("ascii"),
        }
    if isinstance(item, str):
        out = {"uri": uri, "text": item}
        if meta.mime_type:
            out["mimeType"] = meta.mime_type
        return out
    return {"uri": uri, "text": json.dumps(item)}


def _coerce_resource_result(result: Any, uri: str, meta: McpResourceMeta) -> list[dict[str, Any]]:
    if isinstance(result, ResourceResult):
        return [_coerce_resource_item(item, uri, meta) for item in result.contents]
    if isinstance(result, list):
        return [_coerce_resource_item(item, uri, meta) for item in result]
    return [_coerce_resource_item(result, uri, meta)]


def make_resources_read_handler(
    server_instance: Any,
    resources: list[McpResourceMeta] | Callable[[], list[McpResourceMeta]],
) -> _Handler:
    """Return an async handler for ``resources/read``.

    Matches the requested URI against compiled URI-template patterns and
    calls the corresponding method with extracted (and type-coerced) path
    and query variables.
    """
    get_resources = resources if callable(resources) else (lambda: resources)

    async def handler(req: JsonRpcRequest) -> dict[str, Any]:
        params: dict[str, Any] = req.params if isinstance(req.params, dict) else {}
        uri = params.get("uri", "")
        for meta in get_resources():
            compiled = compile_uri_template(meta.uri_template)
            variables = match_uri(compiled, uri)
            if variables is None:
                continue
            kwargs = coerce_params(variables, meta.param_type_hints)
            target = getattr(meta, "_bound_instance", None) or server_instance
            method = getattr(target, meta.method_name)
            result = await method(**kwargs)
            return {"contents": _coerce_resource_result(result, uri, meta)}
        raise ValueError(f"No resource matches URI: {uri!r}")

    return handler


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


def make_prompts_list_handler(
    prompts: list[McpPromptMeta] | Callable[[], list[McpPromptMeta]],
) -> _Handler:
    """Return an async handler for ``prompts/list``."""
    get_prompts = prompts if callable(prompts) else (lambda: prompts)

    async def handler(req: JsonRpcRequest) -> dict[str, Any]:
        schemas: list[dict[str, Any]] = []
        for p in get_prompts():
            entry: dict[str, Any] = {"name": p.name}
            if p.description is not None:
                entry["description"] = p.description
            if p.arguments:
                entry["arguments"] = p.arguments
            schemas.append(entry)
        return {"prompts": schemas}

    return handler


def make_prompts_get_handler(
    server_instance: Any,
    prompts: list[McpPromptMeta] | Callable[[], list[McpPromptMeta]],
) -> _Handler:
    """Return an async handler for ``prompts/get``.

    Dispatches to ``server_instance.<method_name>(**arguments)`` and
    expects the method to return either a string (turned into a single
    user message) or a dict/list matching the MCP GetPromptResult shape.
    """
    get_prompts = prompts if callable(prompts) else (lambda: prompts)

    async def handler(req: JsonRpcRequest) -> dict[str, Any]:
        params: dict[str, Any] = req.params if isinstance(req.params, dict) else {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        prompt_map = {p.name: p for p in get_prompts()}
        if name not in prompt_map:
            raise ValueError(f"Unknown prompt: {name!r}")
        meta = prompt_map[name]
        target = getattr(meta, "_bound_instance", None) or server_instance
        method = getattr(target, meta.method_name)
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
