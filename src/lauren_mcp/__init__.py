"""lauren-mcp — Model Context Protocol server and client for Lauren applications."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from ._bridge import McpServerConfig, McpToolBridge
from ._client._factory import McpServer
from ._client._protocol import McpClientProtocol
from ._mcp_version import LATEST, STABLE, SUPPORTED
from ._types import (
    AnyContent,
    ClientCapabilities,
    EmbeddedResource,
    GetPromptParams,
    GetPromptResult,
    ImageContent,
    Implementation,
    InitializeParams,
    InitializeResult,
    JsonRpcError,
    JsonRpcErrorResponse,
    JsonRpcNotification,
    JsonRpcRequest,
    JsonRpcResponse,
    McpErrorCode,
    McpParseError,
    PromptArgument,
    PromptMessage,
    PromptSchema,
    ReadResourceParams,
    ReadResourceResult,
    ResourceContent,
    ResourceSchema,
    ServerCapabilities,
    TextContent,
    ToolCallParams,
    ToolResult,
    ToolSchema,
    build_error_response,
    parse_message,
)
from .server import McpServerModule, mcp_prompt, mcp_resource, mcp_server, mcp_tool

__all__ = [
    "mcp_server",
    "mcp_tool",
    "mcp_resource",
    "mcp_prompt",
    "McpServerModule",
    "McpServer",
    "McpClientProtocol",
    "McpServerConfig",
    "McpToolBridge",
    "JsonRpcRequest",
    "JsonRpcNotification",
    "JsonRpcResponse",
    "JsonRpcError",
    "JsonRpcErrorResponse",
    "McpErrorCode",
    "McpParseError",
    "ClientCapabilities",
    "ServerCapabilities",
    "Implementation",
    "InitializeParams",
    "InitializeResult",
    "TextContent",
    "ImageContent",
    "EmbeddedResource",
    "AnyContent",
    "ToolSchema",
    "ToolCallParams",
    "ToolResult",
    "ResourceSchema",
    "ResourceContent",
    "ReadResourceParams",
    "ReadResourceResult",
    "PromptArgument",
    "PromptSchema",
    "PromptMessage",
    "GetPromptParams",
    "GetPromptResult",
    "parse_message",
    "build_error_response",
    "LATEST",
    "STABLE",
    "SUPPORTED",
]

try:
    __version__: str = version("lauren-mcp")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"
