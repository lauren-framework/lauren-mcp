"""MCP wire types as dataclasses — full JSON-RPC 2.0 + MCP protocol shapes."""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Generic, Literal, TypeVar

_T = TypeVar("_T")

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
    completions: dict[str, Any] | None = None
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


@dataclass
class AudioContent:
    """A base64-encoded audio content item.

    ``data`` must be base64-encoded audio bytes.  ``mimeType`` should be a
    valid audio MIME type such as ``"audio/wav"``, ``"audio/mpeg"``, or
    ``"audio/ogg"``.
    """

    data: str  # base64-encoded audio bytes
    mimeType: str  # e.g. "audio/wav"
    type: str = "audio"

    @classmethod
    def from_bytes(cls, data: bytes, mime_type: str = "audio/wav") -> AudioContent:
        """Construct from raw audio *data*, base64-encoding it automatically."""
        return cls(data=base64.b64encode(data).decode("ascii"), mimeType=mime_type)


@dataclass
class ResourceLink:
    """A lightweight reference to a resource by URI.

    Unlike :class:`EmbeddedResource`, a ``ResourceLink`` does **not** inline
    the resource's content — it provides only the URI and optional metadata.
    The MCP client may choose to fetch the resource separately via
    ``resources/read`` if needed.
    """

    uri: str
    name: str | None = None
    description: str | None = None
    mimeType: str | None = None
    type: str = "resource_link"


#: Union alias for any content item that can appear in a tool result or message.
AnyContent = TextContent | ImageContent | AudioContent | EmbeddedResource | ResourceLink


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
    title: str | None = None


@dataclass
class ToolCallParams:
    """Parameters for a ``tools/call`` request."""

    name: str
    arguments: dict[str, Any] | None = None


@dataclass
class ToolResult:
    """Result returned from a ``tools/call`` invocation."""

    content: list[
        TextContent
        | ImageContent
        | AudioContent
        | EmbeddedResource
        | ResourceLink
        | ToolUseContent
        | ToolResultContent
    ] = field(default_factory=list)
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


@dataclass
class ToolStream(Generic[_T]):
    """Return type for streaming ``@mcp_tool`` methods.

    Each value yielded by *generator* is sent to the client as a
    ``notifications/progress`` message during the tool call.  When the
    generator is exhausted the accumulated result becomes the ``tools/call``
    response.

    Attributes
    ----------
    generator:
        An async generator producing ``_T`` values.
    total:
        Optional declared item count forwarded as the ``total`` field of each
        progress notification.  Use when the total is known in advance (e.g.
        transcribing a file of known duration).
    accumulate:
        Optional callable ``(chunks: list[_T]) -> Any`` that reduces all chunks
        to a single final value.  Defaults:

        - If all chunks are ``str``: ``"".join(chunks)``
        - Otherwise: the last chunk, or ``None`` for an empty generator.
    """

    generator: AsyncGenerator[_T, None]
    total: int | None = None
    accumulate: Callable[[list[_T]], Any] | None = None


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------

#: Role type alias for MCP audience annotations.
Role = Literal["user", "assistant"]


@dataclass
class ResourceAnnotations:
    """Annotations attached to an MCP resource for UI and routing hints.

    Attributes:
        audience: List of intended readers; omitted means unrestricted.
            Valid values are ``"user"`` and ``"assistant"``.
        priority: Relevance weighting in ``[0.0, 1.0]``.  Higher values
            indicate higher priority.  Omitted when not specified.
    """

    audience: list[Role] | None = None
    priority: float | None = None

    def __post_init__(self) -> None:
        if self.priority is not None and not (0.0 <= self.priority <= 1.0):
            raise ValueError(
                f"ResourceAnnotations.priority must be in [0.0, 1.0], got {self.priority}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialise to the MCP wire representation."""
        out: dict[str, Any] = {}
        if self.audience is not None:
            out["audience"] = list(self.audience)
        if self.priority is not None:
            out["priority"] = self.priority
        return out

    @classmethod
    def from_dict(cls, obj: dict[str, Any]) -> ResourceAnnotations:
        """Deserialise from a wire ``annotations`` dict."""
        return cls(
            audience=obj.get("audience"),
            priority=obj.get("priority"),
        )


@dataclass
class ResourceSchema:
    """Descriptor for a single MCP resource."""

    uri: str
    name: str
    description: str | None = None
    mimeType: str | None = None
    title: str | None = None
    annotations: ResourceAnnotations | None = None


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
    title: str | None = None


@dataclass
class PromptMessage:
    """A single message within a prompt response."""

    role: Literal["user", "assistant"]
    content: TextContent | ImageContent | AudioContent | EmbeddedResource | ResourceLink = field(
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
class ToolUseContent:
    """A tool invocation block inside a sampling message.

    Represents the LLM requesting to call a tool, as returned inside a
    ``sampling/createMessage`` response when the model decides to use a tool.
    Also used when re-sending past assistant turns that contained tool calls.

    Attributes
    ----------
    id:
        Unique opaque identifier for this tool call, supplied by the model.
        Must match the ``tool_use_id`` of the corresponding
        :class:`ToolResultContent`.
    name:
        Name of the tool to call.
    input:
        Tool arguments as a JSON-serialisable dict.  No schema validation is
        performed here — the tool author is responsible.
    type:
        Wire discriminator.  Always ``"tool_use"``; do not override.
    """

    id: str
    name: str
    input: dict[str, Any]
    type: str = "tool_use"

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "id": self.id,
            "name": self.name,
            "input": self.input,
        }

    @classmethod
    def from_dict(cls, obj: dict[str, Any]) -> ToolUseContent:
        return cls(
            id=obj.get("id", ""),
            name=obj.get("name", ""),
            input=obj.get("input") or {},
        )


@dataclass
class ToolResultContent:
    """The result of a prior tool invocation, placed in a user-role message.

    When the tool author has handled the :class:`ToolUseContent` from an
    assistant turn, they create a ``ToolResultContent`` and append it as a
    ``role="user"`` :class:`SamplingMessage` to continue the conversation.

    Attributes
    ----------
    tool_use_id:
        Must match the ``id`` of the :class:`ToolUseContent` this result
        corresponds to.
    content:
        One or more content blocks (text or image) that constitute the tool's
        output.  An empty list is valid (the tool produced no output).
    is_error:
        Set to ``True`` when the tool call failed; the LLM can then decide
        how to proceed.
    type:
        Wire discriminator.  Always ``"tool_result"``; do not override.
    """

    tool_use_id: str
    content: list[TextContent | ImageContent] = field(default_factory=list)
    is_error: bool = False
    type: str = "tool_result"

    def to_dict(self) -> dict[str, Any]:
        content_list: list[dict[str, Any]] = []
        for block in self.content:
            if isinstance(block, TextContent):
                content_list.append({"type": "text", "text": block.text})
            elif isinstance(block, ImageContent):
                content_list.append(
                    {"type": "image", "data": block.data, "mimeType": block.mimeType}
                )
        return {
            "type": self.type,
            "tool_use_id": self.tool_use_id,
            "content": content_list,
            "is_error": self.is_error,
        }

    @classmethod
    def from_dict(cls, obj: dict[str, Any]) -> ToolResultContent:
        raw_content = obj.get("content") or []
        content: list[TextContent | ImageContent] = []
        for block in raw_content:
            if isinstance(block, dict):
                if block.get("type") == "image":
                    content.append(
                        ImageContent(
                            data=block.get("data", ""),
                            mimeType=block.get("mimeType", ""),
                        )
                    )
                else:
                    content.append(TextContent(text=block.get("text", "")))
        return cls(
            tool_use_id=obj.get("tool_use_id", ""),
            content=content,
            is_error=bool(obj.get("is_error", False)),
        )


@dataclass
class SamplingMessage:
    """A single message in a ``sampling/createMessage`` request."""

    role: Literal["user", "assistant"]
    content: TextContent | ImageContent | ToolUseContent | ToolResultContent = field(
        default_factory=lambda: TextContent(text="")
    )

    def to_dict(self) -> dict[str, Any]:
        content_dict: dict[str, Any]
        if isinstance(self.content, (ToolUseContent, ToolResultContent)):
            content_dict = self.content.to_dict()
        elif isinstance(self.content, TextContent):
            content_dict = {"type": "text", "text": self.content.text}
        else:
            content_dict = {
                "type": "image",
                "data": self.content.data,
                "mimeType": self.content.mimeType,
            }
        return {"role": self.role, "content": content_dict}


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
    content: TextContent | ImageContent | ToolUseContent
    model: str
    stopReason: str | None = None

    @property
    def text(self) -> str:
        """The text of the assistant's reply ('' for image or tool_use content)."""
        return self.content.text if isinstance(self.content, TextContent) else ""

    @classmethod
    def from_dict(cls, obj: dict[str, Any]) -> CreateMessageResult:
        raw = obj.get("content") or {}
        content: TextContent | ImageContent | ToolUseContent
        if raw.get("type") == "image":
            content = ImageContent(data=raw.get("data", ""), mimeType=raw.get("mimeType", ""))
        elif raw.get("type") == "tool_use":
            content = ToolUseContent.from_dict(raw)
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


def validate_sampling_messages(messages: list[SamplingMessage]) -> None:
    """Validate that ``ToolResultContent`` blocks are properly paired.

    Raises
    ------
    ValueError
        If a ``ToolResultContent`` appears before a ``ToolUseContent`` with the
        same ``id``, or if a ``ToolUseContent`` is never followed by any
        ``ToolResultContent`` when more messages follow.

    Notes
    -----
    This performs a shallow ordering check only.  It does not validate tool
    input schemas or result content types.  An empty list is valid.
    """
    seen_use_ids: set[str] = set()
    for i, msg in enumerate(messages):
        if isinstance(msg.content, ToolUseContent):
            seen_use_ids.add(msg.content.id)
        elif isinstance(msg.content, ToolResultContent):  # noqa: SIM102
            if msg.content.tool_use_id not in seen_use_ids:
                raise ValueError(
                    f"SamplingMessage[{i}] contains ToolResultContent with "
                    f"tool_use_id={msg.content.tool_use_id!r} but no preceding "
                    f"ToolUseContent with that id was found in the messages list."
                )


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


@dataclass
class UrlElicitResult:
    """Result of a URL-elicitation ``elicitation/create`` request.

    ``action`` values:

    - ``"accept"`` — the user completed the external URL flow successfully.
    - ``"cancel"`` — the user dismissed the dialog or the flow was aborted.

    Note: URL elicitation has no ``"decline"`` state. The only outcomes are
    completion (``"accept"``) or abandonment (``"cancel"``).
    """

    action: Literal["accept", "cancel"]

    @classmethod
    def from_dict(cls, obj: dict[str, Any]) -> UrlElicitResult:
        action = obj.get("action", "cancel")
        if action not in ("accept", "cancel"):
            action = "cancel"
        return cls(action=action)


class McpUrlElicitationNotAvailable(RuntimeError):
    """Raised when ``ctx.elicit_url()`` is called but the connected client did not
    advertise the ``urlElicitation`` sub-capability, the ``elicitation`` capability
    is absent, or the transport cannot carry server-to-client requests."""


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
# Argument completion
# ---------------------------------------------------------------------------


@dataclass
class CompletionResult:
    """Result of a ``completion/complete`` request."""

    values: list[str]
    total: int | None = None
    has_more: bool = False


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
    "AudioContent",
    "ResourceLink",
    "AnyContent",
    "ToolAnnotations",
    "ToolSchema",
    "ToolCallParams",
    "ToolResult",
    "ToolOutput",
    "ToolStream",
    "Role",
    "ResourceAnnotations",
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
    "ToolUseContent",
    "ToolResultContent",
    "SamplingMessage",
    "CreateMessageParams",
    "CreateMessageResult",
    "McpSamplingNotAvailable",
    "validate_sampling_messages",
    "ElicitResult",
    "McpElicitationNotAvailable",
    "UrlElicitResult",
    "McpUrlElicitationNotAvailable",
    "Root",
    "CompletionResult",
    "McpParseError",
    "parse_message",
    "build_error_response",
]
