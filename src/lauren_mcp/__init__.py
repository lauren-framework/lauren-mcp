"""lauren-mcp — Model Context Protocol server and client for Lauren applications."""
from __future__ import annotations

from importlib.metadata import version, PackageNotFoundError

from .server import mcp_server, mcp_tool, mcp_resource, mcp_prompt, McpServerModule
from ._client._factory import McpServer
from ._client._protocol import McpClientProtocol
from ._bridge import McpServerConfig, McpToolBridge
from ._types import (
    JsonRpcRequest,
    JsonRpcNotification,
    JsonRpcResponse,
    JsonRpcError,
    JsonRpcErrorResponse,
    McpErrorCode,
    McpParseError,
    ClientCapabilities,
    ServerCapabilities,
    Implementation,
    InitializeParams,
    InitializeResult,
    TextContent,
    ImageContent,
    EmbeddedResource,
    ToolSchema,
    ToolCallParams,
    ToolResult,
    ResourceSchema,
    ResourceContent,
    ReadResourceParams,
    ReadResourceResult,
    PromptArgument,
    PromptSchema,
    PromptMessage,
    GetPromptParams,
    GetPromptResult,
    parse_message,
    build_error_response,
)
from ._version import LATEST, STABLE, SUPPORTED

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
