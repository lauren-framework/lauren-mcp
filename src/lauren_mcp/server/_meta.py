"""Metadata dataclasses attached to MCP-decorated classes and methods."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Attribute names used to store metadata on decorated objects
MCP_SERVER_META   = "__mcp_server_meta__"
MCP_TOOL_META     = "__mcp_tool_meta__"
MCP_RESOURCE_META = "__mcp_resource_meta__"
MCP_PROMPT_META   = "__mcp_prompt_meta__"


@dataclass
class McpServerMeta:
    """Metadata attached to a class decorated with ``@mcp_server``."""

    path: str
    transport: str  # "ws" | "sse" | "both"


@dataclass
class McpToolMeta:
    """Metadata attached to a method decorated with ``@mcp_tool``."""

    name: str
    description: str
    input_schema: dict[str, Any]
    method_name: str


@dataclass
class McpResourceMeta:
    """Metadata attached to a method decorated with ``@mcp_resource``."""

    uri_template: str
    name: str
    description: str | None
    mime_type: str | None
    method_name: str


@dataclass
class McpPromptMeta:
    """Metadata attached to a method decorated with ``@mcp_prompt``."""

    name: str
    description: str | None
    arguments: list[dict]   # [{name, description, required}]
    method_name: str
