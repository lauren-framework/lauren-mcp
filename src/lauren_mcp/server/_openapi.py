"""OpenAPI import — generate an MCP server module from an OpenAPI 3.x spec.

The generated tools call the backing REST API over an ``httpx.AsyncClient``;
this is intended for prototyping — hand-written tool descriptions perform
better with LLMs than auto-converted ``operationId`` strings.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

_logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30.0


@dataclass
class RouteEntry:
    """One rule controlling how an OpenAPI operation maps to MCP."""

    pattern: str  # regex matched against the path
    method: str | None = None  # "GET", "POST", … or None for all methods
    expose_as: Literal["tool", "exclude"] = "tool"
    name_override: str | None = None
    description_override: str | None = None

    def matches(self, path: str, method: str) -> bool:
        if self.method is not None and self.method.upper() != method.upper():
            return False
        return re.search(self.pattern, path) is not None


def _load_spec(spec: dict[str, Any] | str | Path) -> dict[str, Any]:
    if isinstance(spec, dict):
        return spec
    text = Path(spec).read_text()
    try:
        return dict(json.loads(text))
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:
            raise ImportError(
                "Reading YAML OpenAPI specs requires pyyaml: pip install pyyaml"
            ) from exc
        return dict(yaml.safe_load(text))


def _resolve_ref(spec: dict[str, Any], ref: str) -> dict[str, Any]:
    """Resolve a local ``#/components/schemas/...`` reference."""
    if not ref.startswith("#/"):
        return {}
    node: Any = spec
    for part in ref[2:].split("/"):
        if not isinstance(node, dict):
            return {}
        node = node.get(part)
    return node if isinstance(node, dict) else {}


def _deref(spec: dict[str, Any], schema: dict[str, Any], depth: int = 0) -> dict[str, Any]:
    """Inline local $refs (shallow, cycle-guarded by depth)."""
    if depth > 8 or not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        return _deref(spec, _resolve_ref(spec, schema["$ref"]), depth + 1)
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if isinstance(value, dict):
            out[key] = _deref(spec, value, depth + 1)
        elif isinstance(value, list):
            out[key] = [_deref(spec, v, depth + 1) if isinstance(v, dict) else v for v in value]
        else:
            out[key] = value
    return out


def _operation_schema(
    spec: dict[str, Any], operation: dict[str, Any], path_item: dict[str, Any]
) -> tuple[dict[str, Any], list[str], list[str], bool]:
    """Build ``(input_schema, path_params, query_params, has_body)``."""
    properties: dict[str, Any] = {}
    required: list[str] = []
    path_params: list[str] = []
    query_params: list[str] = []

    all_params = [*(path_item.get("parameters") or []), *(operation.get("parameters") or [])]
    for param in all_params:
        param = _deref(spec, param)
        name = param.get("name")
        if not name:
            continue
        schema = _deref(spec, param.get("schema") or {"type": "string"})
        if param.get("description") and "description" not in schema:
            schema["description"] = param["description"]
        location = param.get("in")
        if location == "path":
            path_params.append(name)
            properties[name] = schema
            required.append(name)
        elif location == "query":
            query_params.append(name)
            properties[name] = schema
            if param.get("required"):
                required.append(name)
        # header/cookie params are transport details — excluded from the
        # AI-visible schema.

    has_body = False
    body = operation.get("requestBody")
    if body:
        body = _deref(spec, body)
        content = body.get("content") or {}
        json_content = content.get("application/json") or {}
        body_schema = _deref(spec, json_content.get("schema") or {})
        if body_schema.get("type") == "object":
            has_body = True
            for prop_name, prop_schema in (body_schema.get("properties") or {}).items():
                properties[prop_name] = prop_schema
            for req in body_schema.get("required") or []:
                if req not in required:
                    required.append(req)

    schema_out: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema_out["required"] = required
    return schema_out, path_params, query_params, has_body


def _make_operation_method(
    http_client: Any,
    base_url: str,
    path: str,
    method: str,
    path_params: list[str],
    query_params: list[str],
    has_body: bool,
) -> Any:
    """Build the async method that executes one REST operation."""

    async def call(self: Any, **kwargs: Any) -> Any:  # noqa: ARG001
        url_path = path
        for name in path_params:
            url_path = url_path.replace("{" + name + "}", str(kwargs.pop(name, "")))
        params = {k: kwargs.pop(k) for k in list(kwargs) if k in query_params}
        body = kwargs if has_body and kwargs else None
        resp = await http_client.request(
            method,
            f"{base_url}{url_path}",
            params=params or None,
            json=body,
            timeout=_DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "application/json" in content_type:
            return resp.json()
        return resp.text

    return call


_DEFAULT_NAME_RE = re.compile(r"[^a-zA-Z0-9_]+")


def _default_name(operation: dict[str, Any], method: str, path: str) -> str:
    op_id = operation.get("operationId")
    if op_id:
        return _DEFAULT_NAME_RE.sub("_", op_id).strip("_")
    return _DEFAULT_NAME_RE.sub("_", f"{method.lower()}{path}").strip("_")


def build_openapi_server_class(
    spec: dict[str, Any] | str | Path,
    *,
    http_client: Any,
    base_url: str = "",
    server_path: str = "/mcp",
    route_map: list[RouteEntry] | None = None,
    class_name: str = "OpenApiMcpServer",
) -> type:
    """Build an ``@mcp_server`` class whose tools wrap an OpenAPI spec.

    Parameters
    ----------
    spec:
        Parsed spec dict, or a path to a ``.json`` / ``.yaml`` file.
    http_client:
        ``httpx.AsyncClient`` (or compatible) used to execute the calls.
    base_url:
        Prefix for all request URLs (e.g. ``"https://api.example.com"``).
        May be empty when *http_client* already has a ``base_url``.
    server_path:
        Mount path passed to ``@mcp_server``.
    route_map:
        Ordered :class:`RouteEntry` rules; the first match wins.  Operations
        with no matching entry are exposed as tools.
    class_name:
        Name for the generated class.

    Pass the result to :meth:`McpServerModule.for_root` like any hand-written
    server class.
    """
    from ._decorators import mcp_server
    from ._meta import MCP_TOOL_META, McpToolMeta

    resolved = _load_spec(spec)
    rules = route_map or []
    namespace: dict[str, Any] = {}
    count = 0

    for path, path_item in (resolved.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        for method in ("get", "post", "put", "patch", "delete"):
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue

            rule = next((r for r in rules if r.matches(path, method)), None)
            if rule is not None and rule.expose_as == "exclude":
                continue

            name = (rule.name_override if rule else None) or _default_name(operation, method, path)
            description = (rule.description_override if rule else None) or (
                operation.get("description") or operation.get("summary") or name
            )

            input_schema, path_params, query_params, has_body = _operation_schema(
                resolved, operation, path_item
            )
            fn = _make_operation_method(
                http_client,
                base_url,
                path,
                method.upper(),
                path_params,
                query_params,
                has_body,
            )
            fn.__name__ = name
            fn.__doc__ = description
            setattr(
                fn,
                MCP_TOOL_META,
                McpToolMeta(
                    name=name,
                    description=description,
                    input_schema=input_schema,
                    method_name=name,
                ),
            )
            namespace[name] = fn
            count += 1

    if not count:
        _logger.warning("OpenAPI import: no operations found in spec")

    cls = type(class_name, (), namespace)
    return mcp_server(server_path)(cls)


__all__ = ["RouteEntry", "build_openapi_server_class"]
