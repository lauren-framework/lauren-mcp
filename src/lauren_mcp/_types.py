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
    elicitation: dict[str, Any] | None = None
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


@dataclass(frozen=True)
class ToolAnnotations:
    """Behavioural hints for a tool, transmitted to clients in ``tools/list``.

    Field defaults follow the MCP specification's conservative assumptions:
    a tool is presumed destructive and open-world unless declared otherwise.
    """

    readOnlyHint: bool = False
    destructiveHint: bool = True
    idempotentHint: bool = False
    openWorldHint: bool = True

    def to_dict(self) -> dict[str, bool]:
        return {
            "readOnlyHint": self.readOnlyHint,
            "destructiveHint": self.destructiveHint,
            "idempotentHint": self.idempotentHint,
            "openWorldHint": self.openWorldHint,
        }


@dataclass
class ToolSchema:
    """Descriptor for a single MCP tool."""

    name: str
    description: str
    inputSchema: dict[str, Any] = field(default_factory=dict)
    outputSchema: dict[str, Any] | None = None
    annotations: dict[str, Any] | None = None


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
    structuredContent: dict[str, Any] | None = None


@dataclass
class ToolOutput:
    """Rich return type for ``@mcp_tool`` methods.

    Lets a tool control the content blocks (shown to the user) and the
    structured JSON payload (parsed by the agent loop) independently.
    """

    content: list[Any] | None = None
    structured_content: dict[str, Any] | None = None
    is_error: bool = False


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


@dataclass
class BlobResource:
    """Convenience return type for binary ``@mcp_resource`` methods.

    Equivalent to returning ``bytes`` with an explicit MIME type — the
    handler base64-encodes ``data`` into ``ResourceContent.blob``.
    """

    data: bytes
    mime_type: str = "application/octet-stream"


@dataclass
class ResourceResult:
    """Multi-item return type for ``@mcp_resource`` methods."""

    contents: list[Any] = field(default_factory=list)


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
# Progress
# ---------------------------------------------------------------------------


@dataclass
class ProgressNotification(JsonRpcNotification):
    """Notification reporting incremental progress for an in-flight request."""

    method: str = "notifications/progress"
    params: dict[str, Any] | list[Any] | None = None
    jsonrpc: str = "2.0"


# ---------------------------------------------------------------------------
# Sampling (server-initiated LLM calls)
# ---------------------------------------------------------------------------


@dataclass
class SamplingMessage:
    """A single message in a ``sampling/createMessage`` request."""

    role: Literal["user", "assistant"]
    content: TextContent | ImageContent = field(default_factory=lambda: TextContent(text=""))

    def to_dict(self) -> dict[str, Any]:
        if isinstance(self.content, TextContent):
            content: dict[str, Any] = {"type": "text", "text": self.content.text}
        else:
            content = {
                "type": "image",
                "data": self.content.data,
                "mimeType": self.content.mimeType,
            }
        return {"role": self.role, "content": content}


@dataclass
class CreateMessageParams:
    """Parameters for a ``sampling/createMessage`` request."""

    messages: list[SamplingMessage]
    maxTokens: int
    systemPrompt: str | None = None
    includeContext: Literal["none", "thisServer", "allServers"] = "none"
    temperature: float | None = None
    stopSequences: list[str] = field(default_factory=list)
    modelPreferences: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        obj: dict[str, Any] = {
            "messages": [m.to_dict() for m in self.messages],
            "maxTokens": self.maxTokens,
            "includeContext": self.includeContext,
        }
        if self.systemPrompt is not None:
            obj["systemPrompt"] = self.systemPrompt
        if self.temperature is not None:
            obj["temperature"] = self.temperature
        if self.stopSequences:
            obj["stopSequences"] = self.stopSequences
        if self.modelPreferences is not None:
            obj["modelPreferences"] = self.modelPreferences
        if self.metadata is not None:
            obj["metadata"] = self.metadata
        return obj


@dataclass
class CreateMessageResult:
    """Result of a ``sampling/createMessage`` request."""

    role: Literal["assistant"]
    content: TextContent | ImageContent
    model: str
    stopReason: str | None = None

    @property
    def text(self) -> str:
        """The text of the assistant's reply ('' for image content)."""
        return self.content.text if isinstance(self.content, TextContent) else ""

    @classmethod
    def from_dict(cls, obj: dict[str, Any]) -> CreateMessageResult:
        raw = obj.get("content") or {}
        content: TextContent | ImageContent
        if raw.get("type") == "image":
            content = ImageContent(data=raw.get("data", ""), mimeType=raw.get("mimeType", ""))
        else:
            content = TextContent(text=raw.get("text", ""))
        return cls(
            role=obj.get("role", "assistant"),
            content=content,
            model=obj.get("model", ""),
            stopReason=obj.get("stopReason"),
        )


class McpSamplingNotAvailable(RuntimeError):
    """Raised when ``ctx.sample()`` is called but the connected client did not
    advertise the ``sampling`` capability (or the transport cannot deliver
    server-to-client requests)."""


# ---------------------------------------------------------------------------
# Elicitation (server asks client for user input)
# ---------------------------------------------------------------------------


@dataclass
class ElicitResult:
    """Result of an ``elicitation/create`` request."""

    action: Literal["accept", "decline", "cancel"]
    content: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, obj: dict[str, Any]) -> ElicitResult:
        return cls(action=obj.get("action", "cancel"), content=obj.get("content"))


class McpElicitationNotAvailable(RuntimeError):
    """Raised when ``ctx.elicit()`` is called but the connected client did not
    advertise the ``elicitation`` capability (or the transport cannot deliver
    server-to-client requests)."""


# ---------------------------------------------------------------------------
# Roots (client-exposed filesystem roots)
# ---------------------------------------------------------------------------


@dataclass
class Root:
    """A filesystem root exposed by an MCP client to servers."""

    uri: str
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        obj: dict[str, Any] = {"uri": self.uri}
        if self.name is not None:
            obj["name"] = self.name
        return obj


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
    "ToolAnnotations",
    "ToolSchema",
    "ToolCallParams",
    "ToolResult",
    "ToolOutput",
    "ResourceSchema",
    "ResourceContent",
    "ReadResourceParams",
    "ReadResourceResult",
    "BlobResource",
    "ResourceResult",
    "PromptArgument",
    "PromptSchema",
    "PromptMessage",
    "GetPromptParams",
    "GetPromptResult",
    "ToolListChangedNotification",
    "ResourceListChangedNotification",
    "PromptListChangedNotification",
    "LoggingMessageNotification",
    "ProgressNotification",
    "SamplingMessage",
    "CreateMessageParams",
    "CreateMessageResult",
    "McpSamplingNotAvailable",
    "ElicitResult",
    "McpElicitationNotAvailable",
    "Root",
    "McpParseError",
    "parse_message",
    "build_error_response",
]
