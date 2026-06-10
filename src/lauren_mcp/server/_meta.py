"""Metadata dataclasses attached to MCP-decorated classes and methods."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from lauren_mcp._types import ToolAnnotations

# Attribute names used to store metadata on decorated objects
MCP_SERVER_META = "__mcp_server_meta__"
MCP_TOOL_META = "__mcp_tool_meta__"
MCP_RESOURCE_META = "__mcp_resource_meta__"
MCP_PROMPT_META = "__mcp_prompt_meta__"
MCP_LIFESPAN_META = "__mcp_lifespan_meta__"


@dataclass
class McpServerMeta:
    """Metadata attached to a class decorated with ``@mcp_server``."""

    path: str
    transport: str  # "ws" | "sse" | "streamable" | "both" | "all"


@dataclass
class McpToolMeta:
    """Metadata attached to a method decorated with ``@mcp_tool``."""

    name: str
    description: str
    input_schema: dict[str, Any]
    method_name: str
    context_param_name: str | None = None
    reads_context: bool = False
    annotations: ToolAnnotations | None = None
    output_schema: dict[str, Any] | None = None
    timeout: float | None = None
    tags: frozenset[str] = field(default_factory=frozenset)
    meta: dict[str, Any] = field(default_factory=dict)
    param_descriptions: dict[str, str] = field(default_factory=dict)


@dataclass
class McpResourceMeta:
    """Metadata attached to a method decorated with ``@mcp_resource``."""

    uri_template: str
    name: str
    description: str | None
    mime_type: str | None
    method_name: str
    query_params: list[str] = field(default_factory=list)
    param_type_hints: dict[str, Any] = field(default_factory=dict)


@dataclass
class McpPromptMeta:
    """Metadata attached to a method decorated with ``@mcp_prompt``."""

    name: str
    description: str | None
    arguments: list[dict[str, Any]]  # [{name, description, required}]
    method_name: str


@dataclass
class McpLifespanMeta:
    """Metadata attached to a method decorated with ``@mcp_lifespan``."""

    method_name: str
