"""MCP server decorator API."""

from __future__ import annotations

from ._builtin_resources import (
    DirectoryResource,
    FileResource,
    HttpResource,
    register_directory_resource,
    register_file_resource,
    register_http_resource,
)
from ._composition import McpToolNameCollision, make_mount_binder, make_proxy_binder
from ._decorators import (
    mcp_completion,
    mcp_lifespan,
    mcp_prompt,
    mcp_resource,
    mcp_server,
    mcp_tool,
)
from ._module import McpServerModule
from ._openapi import RouteEntry, build_openapi_server_class

__all__ = [
    "mcp_server",
    "mcp_tool",
    "mcp_resource",
    "mcp_prompt",
    "mcp_lifespan",
    "mcp_completion",
    "McpServerModule",
    "McpToolNameCollision",
    "make_mount_binder",
    "make_proxy_binder",
    "RouteEntry",
    "build_openapi_server_class",
    "FileResource",
    "HttpResource",
    "DirectoryResource",
    "register_file_resource",
    "register_http_resource",
    "register_directory_resource",
]
