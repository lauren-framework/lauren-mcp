"""MCP wire types as dataclasses — full JSON-RPC 2.0 + MCP protocol shapes."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Literal

# ---------------------------------------------------------------------------
# JSON-RPC 2.0 primitives
# ---------------------------------------------------------------------------


@dataclass
class JsonRpcRequest:
    """A JSON-RPC 2.0 request (has both method and id)."""

    method: str
    params: dict[str, Any] | list[Any] | None = None
    id: str | int | None = None
    jsonrpc: str = "2.0"

    def to_json(self) -> str:
        obj: dict[str, Any] = {
            "jsonrpc": self.jsonrpc,
            "method": self.method,
            "id": self.id,
        }
        if self.params is not None:
            obj["params"] = self.params
        return json.dumps(obj)


@dataclass
class JsonRpcNotification:
    """A JSON-RPC 2.0 notification (has method but no id)."""

    method: str
    params: dict[str, Any] | list[Any] | None = None
    jsonrpc: str = "2.0"

    def to_json(self) -> str:
        obj: dict[str, Any] = {
            "jsonrpc": self.jsonrpc,
            "method": self.method,
        }
        if self.params is not None:
            obj["params"] = self.params
        return json.dumps(obj)


@dataclass
class JsonRpcResponse:
    """A JSON-RPC 2.0 success response."""

    id: str | int | None
    result: Any
    jsonrpc: str = "2.0"

    def to_json(self) -> str:
        obj: dict[str, Any] = {
            "jsonrpc": self.jsonrpc,
            "id": self.id,
            "result": self.result,
        }
        return json.dumps(obj)


@dataclass
class JsonRpcError:
    """A JSON-RPC 2.0 error object (embedded in JsonRpcErrorResponse)."""

    code: int
    message: str
    data: Any = None


@dataclass
class JsonRpcErrorResponse:
    """A JSON-RPC 2.0 error response."""

    id: str | int | None
    error: JsonRpcError
    jsonrpc: str = "2.0"

    def to_json(self) -> str:
        err: dict[str, Any] = {
            "code": self.error.code,
            "message": self.error.message,
        }
        if self.error.data is not None:
            err["data"] = self.error.data
        obj: dict[str, Any] = {
            "jsonrpc": self.jsonrpc,
            "id": self.id,
            "error": err,
        }
        return json.dumps(obj)


# ---------------------------------------------------------------------------
# MCP error codes
# ---------------------------------------------------------------------------


class McpErrorCode(IntEnum):
    """Standard JSON-RPC and MCP-extension error codes."""

    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603
    REQUEST_CANCELLED = -32800
    CONTENT_TOO_LARGE = -32801


# ---------------------------------------------------------------------------
# Capability types
# ---------------------------------------------------------------------------


@dataclass
class ClientCapabilities:
    """Capabilities advertised by an MCP client during initialization."""

    roots: dict[str, Any] | None = None
    sampling: dict[str, Any] | None = None
    experimental: dict[str, Any] | None = None


@dataclass
class ServerCapabilities:
    """Capabilities advertised by an MCP server during initialization."""

    tools: dict[str, Any] | None = None
    resources: dict[str, Any] | None = None
    prompts: dict[str, Any] | None = None
    logging: dict[str, Any] | None = None
    experimental: dict[str, Any] | None = None


@dataclass
class Implementation:
    """Name/version pair identifying a software implementation."""

    name: str
    version: str


# ---------------------------------------------------------------------------
# Initialize handshake
# ---------------------------------------------------------------------------


@dataclass
class InitializeParams:
    """Parameters sent by the client in the ``initialize`` request."""

    protocolVersion: str
    capabilities: ClientCapabilities
    clientInfo: Implementation


@dataclass
class InitializeResult:
    """Result returned by the server for the ``initialize`` request."""

    protocolVersion: str
    capabilities: ServerCapabilities
    serverInfo: Implementation
    instructions: str | None = None


# ---------------------------------------------------------------------------
# Content types
# ---------------------------------------------------------------------------


@dataclass
class TextContent:
    """A plain-text content item."""

    text: str
    type: str = "text"


@dataclass
class ImageContent:
    """A base64-encoded image content item."""

    data: str
    mimeType: str
    type: str = "image"


@dataclass
class EmbeddedResource:
    """A resource embedded inline inside a message."""

    resource: Any  # ResourceContent or similar — forward ref ok
    type: str = "resource"


#: Union alias for any content item that can appear in a tool result or message.
AnyContent = TextContent | ImageContent | EmbeddedResource


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@dataclass
class ToolSchema:
    """Descriptor for a single MCP tool."""

    name: str
    description: str
    inputSchema: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCallParams:
    """Parameters for a ``tools/call`` request."""

    name: str
    arguments: dict[str, Any] | None = None


@dataclass
class ToolResult:
    """Result returned from a ``tools/call`` invocation."""

    content: list[TextContent | ImageContent | EmbeddedResource] = field(default_factory=list)
    isError: bool = False


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@dataclass
class ResourceSchema:
    """Descriptor for a single MCP resource."""

    uri: str
    name: str
    description: str | None = None
    mimeType: str | None = None


@dataclass
class ResourceContent:
    """The content of a read resource."""

    uri: str
    mimeType: str | None = None
    text: str | None = None
    blob: str | None = None  # base64-encoded binary


@dataclass
class ReadResourceParams:
    """Parameters for a ``resources/read`` request."""

    uri: str


@dataclass
class ReadResourceResult:
    """Result returned from a ``resources/read`` invocation."""

    contents: list[ResourceContent] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


@dataclass
class PromptArgument:
    """A single declared argument for an MCP prompt."""

    name: str
    description: str | None = None
    required: bool = False


@dataclass
class PromptSchema:
    """Descriptor for a single MCP prompt."""

    name: str
    description: str | None = None
    arguments: list[PromptArgument] = field(default_factory=list)


@dataclass
class PromptMessage:
    """A single message within a prompt response."""

    role: Literal["user", "assistant"]
    content: TextContent | ImageContent | EmbeddedResource = field(
        default_factory=lambda: TextContent(text="")
    )


@dataclass
class GetPromptParams:
    """Parameters for a ``prompts/get`` request."""

    name: str
    arguments: dict[str, str] | None = None


@dataclass
class GetPromptResult:
    """Result returned from a ``prompts/get`` invocation."""

    description: str
    messages: list[PromptMessage] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Server-to-client notifications
# ---------------------------------------------------------------------------


@dataclass
class ToolListChangedNotification(JsonRpcNotification):
    """Notification sent when the server's tool list changes."""

    method: str = "notifications/tools/list_changed"
    params: dict[str, Any] | list[Any] | None = None
    jsonrpc: str = "2.0"


@dataclass
class ResourceListChangedNotification(JsonRpcNotification):
    """Notification sent when the server's resource list changes."""

    method: str = "notifications/resources/list_changed"
    params: dict[str, Any] | list[Any] | None = None
    jsonrpc: str = "2.0"


@dataclass
class PromptListChangedNotification(JsonRpcNotification):
    """Notification sent when the server's prompt list changes."""

    method: str = "notifications/prompts/list_changed"
    params: dict[str, Any] | list[Any] | None = None
    jsonrpc: str = "2.0"


@dataclass
class LoggingMessageNotification(JsonRpcNotification):
    """Notification carrying a log message from server to client."""

    method: str = "notifications/message"
    params: dict[str, Any] | list[Any] | None = None
    jsonrpc: str = "2.0"


# ---------------------------------------------------------------------------
# Parse errors and helpers
# ---------------------------------------------------------------------------


class McpParseError(ValueError):
    """Raised when an incoming MCP message cannot be parsed."""


def parse_message(
    raw: str | bytes,
) -> JsonRpcRequest | JsonRpcNotification | JsonRpcResponse | JsonRpcErrorResponse:
    """Parse a raw JSON string or bytes into the appropriate JSON-RPC type.

    Dispatch rules (per JSON-RPC 2.0 spec):

    * Has both ``method`` **and** ``id``          → :class:`JsonRpcRequest`
    * Has ``method`` but **no** ``id``            → :class:`JsonRpcNotification`
    * Has ``result`` (no ``method``)              → :class:`JsonRpcResponse`
    * Has ``error``  (no ``method``)              → :class:`JsonRpcErrorResponse`

    Raises :class:`McpParseError` on bad JSON, missing ``jsonrpc`` field,
    or a shape that matches none of the above.
    """
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")

    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise McpParseError(f"Invalid JSON: {exc}") from exc

    if not isinstance(obj, dict):
        raise McpParseError(f"Expected a JSON object, got {type(obj).__name__}")

    jsonrpc = obj.get("jsonrpc")
    if jsonrpc != "2.0":
        raise McpParseError(f"Missing or invalid 'jsonrpc' field: {jsonrpc!r} (expected '2.0')")

    has_method = "method" in obj
    has_id = "id" in obj
    has_result = "result" in obj
    has_error = "error" in obj

    if has_method and has_id:
        # JSON-RPC request
        return JsonRpcRequest(
            method=obj["method"],
            params=obj.get("params"),
            id=obj["id"],
            jsonrpc=jsonrpc,
        )

    if has_method and not has_id:
        # JSON-RPC notification
        return JsonRpcNotification(
            method=obj["method"],
            params=obj.get("params"),
            jsonrpc=jsonrpc,
        )

    if has_result and not has_method:
        # JSON-RPC success response
        return JsonRpcResponse(
            id=obj.get("id"),
            result=obj["result"],
            jsonrpc=jsonrpc,
        )

    if has_error and not has_method:
        # JSON-RPC error response
        err_obj = obj.get("error", {})
        if not isinstance(err_obj, dict):
            raise McpParseError(f"'error' field must be an object, got {type(err_obj).__name__}")
        error = JsonRpcError(
            code=err_obj.get("code", McpErrorCode.INTERNAL_ERROR),
            message=err_obj.get("message", ""),
            data=err_obj.get("data"),
        )
        return JsonRpcErrorResponse(
            id=obj.get("id"),
            error=error,
            jsonrpc=jsonrpc,
        )

    raise McpParseError(f"Cannot determine JSON-RPC message type from fields: {list(obj.keys())}")


def build_error_response(
    id: str | int | None,
    code: int | McpErrorCode,
    message: str,
    data: Any = None,
) -> JsonRpcErrorResponse:
    """Construct a :class:`JsonRpcErrorResponse` from primitive parts."""
    return JsonRpcErrorResponse(
        id=id,
        error=JsonRpcError(code=int(code), message=message, data=data),
    )


__all__ = [
    "JsonRpcRequest",
    "JsonRpcNotification",
    "JsonRpcResponse",
    "JsonRpcError",
    "JsonRpcErrorResponse",
    "McpErrorCode",
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
    "ToolListChangedNotification",
    "ResourceListChangedNotification",
    "PromptListChangedNotification",
    "LoggingMessageNotification",
    "McpParseError",
    "parse_message",
    "build_error_response",
]
