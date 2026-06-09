"""MCP server decorator API."""

from __future__ import annotations

from ._decorators import mcp_prompt, mcp_resource, mcp_server, mcp_tool
from ._module import McpServerModule

__all__ = [
    "mcp_server",
    "mcp_tool",
    "mcp_resource",
    "mcp_prompt",
    "McpServerModule",
]
