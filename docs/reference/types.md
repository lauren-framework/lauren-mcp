# Wire Types Reference

All types live in `lauren_mcp._types` and are re-exported from `lauren_mcp`.

---

## JSON-RPC 2.0 primitives

### `JsonRpcRequest`

```python
@dataclass
class JsonRpcRequest:
    method: str
    params: dict[str, Any] | list[Any] | None = None
    id: str | int | None = None
    jsonrpc: str = "2.0"

    def to_json(self) -> str: ...
```

A JSON-RPC 2.0 request (has both `method` and `id`).  For notifications (no
reply expected) use `JsonRpcNotification`.

---

### `JsonRpcNotification`

```python
@dataclass
class JsonRpcNotification:
    method: str
    params: dict[str, Any] | list[Any] | None = None
    jsonrpc: str = "2.0"

    def to_json(self) -> str: ...
```

A JSON-RPC 2.0 notification — like a request but with no `id`.  The server
does not send a response to notifications.

---

### `JsonRpcResponse`

```python
@dataclass
class JsonRpcResponse:
    id: str | int | None
    result: Any
    jsonrpc: str = "2.0"

    def to_json(self) -> str: ...
```

Successful JSON-RPC 2.0 response.

---

### `JsonRpcError`

```python
@dataclass
class JsonRpcError:
    code: int
    message: str
    data: Any = None
```

Error object embedded in `JsonRpcErrorResponse`.

---

### `JsonRpcErrorResponse`

```python
@dataclass
class JsonRpcErrorResponse:
    id: str | int | None
    error: JsonRpcError
    jsonrpc: str = "2.0"

    def to_json(self) -> str: ...
```

Error JSON-RPC 2.0 response.  `id` is `None` when the error occurred before
the request `id` could be determined (e.g. parse error).

---

### `McpErrorCode`

```python
from enum import IntEnum

class McpErrorCode(IntEnum):
    # JSON-RPC 2.0 standard codes
    PARSE_ERROR       = -32700
    INVALID_REQUEST   = -32600
    METHOD_NOT_FOUND  = -32601
    INVALID_PARAMS    = -32602
    INTERNAL_ERROR    = -32603
    # MCP extension codes
    REQUEST_CANCELLED = -32800
    CONTENT_TOO_LARGE = -32801
```

Standard JSON-RPC 2.0 error codes plus MCP protocol extensions.

---

### `parse_message`

```python
def parse_message(
    raw: str | bytes,
) -> JsonRpcRequest | JsonRpcNotification | JsonRpcResponse | JsonRpcErrorResponse:
```

Parse a raw JSON string or bytes into the appropriate JSON-RPC message type.

Dispatch rules (per JSON-RPC 2.0 spec):

| Fields present | Returns |
|---|---|
| `method` + `id` | `JsonRpcRequest` |
| `method` only (no `id`) | `JsonRpcNotification` |
| `result` (no `method`) | `JsonRpcResponse` |
| `error` (no `method`) | `JsonRpcErrorResponse` |

Raises `McpParseError` on bad JSON, missing `jsonrpc` field, or an
unrecognised shape.

---

### `build_error_response`

```python
def build_error_response(
    id: str | int | None,
    code: int | McpErrorCode,
    message: str,
    data: Any = None,
) -> JsonRpcErrorResponse:
```

Convenience constructor for error responses.

```python
response = build_error_response(
    id=42,
    code=McpErrorCode.METHOD_NOT_FOUND,
    message="Tool 'foo' is not registered.",
)
```

---

## Handshake types

### `ClientCapabilities`

```python
@dataclass
class ClientCapabilities:
    roots: dict[str, Any] | None = None
    sampling: dict[str, Any] | None = None
    elicitation: dict[str, Any] | None = None
    experimental: dict[str, Any] | None = None
```

Capability flags advertised by the client during the `initialize` handshake.

---

### `ServerCapabilities`

```python
@dataclass
class ServerCapabilities:
    tools: dict[str, Any] | None = None
    resources: dict[str, Any] | None = None
    prompts: dict[str, Any] | None = None
    logging: dict[str, Any] | None = None
    experimental: dict[str, Any] | None = None
```

Capability flags advertised by the server during the `initialize` handshake.

---

### `Implementation`

```python
@dataclass
class Implementation:
    name: str
    version: str
```

Identifies a client or server implementation.  Used in `InitializeParams`,
`InitializeResult`, and `McpServerModule.for_root(server_info=...)`.

---

### `InitializeParams`

```python
@dataclass
class InitializeParams:
    protocolVersion: str
    capabilities: ClientCapabilities
    clientInfo: Implementation
```

Payload sent by the client in the `initialize` request.

---

### `InitializeResult`

```python
@dataclass
class InitializeResult:
    protocolVersion: str
    capabilities: ServerCapabilities
    serverInfo: Implementation
    instructions: str | None = None
```

Payload returned by the server in response to `initialize`.

---

## Content types

### `TextContent`

```python
@dataclass
class TextContent:
    text: str
    type: str = "text"
```

Plain-text content block.  Appears in tool results, prompt messages, and
sampling messages.

---

### `ImageContent`

```python
@dataclass
class ImageContent:
    data: str      # base-64 encoded image bytes
    mimeType: str  # e.g. "image/png"
    type: str = "image"
```

Base-64 encoded image content block.

---

### `EmbeddedResource`

```python
@dataclass
class EmbeddedResource:
    resource: Any  # ResourceContent or similar
    type: str = "resource"
```

An embedded resource returned inside a tool call result.

---

### `AnyContent`

```python
AnyContent = TextContent | ImageContent | EmbeddedResource
```

Union alias for any content item that can appear in a tool result or message.

---

## Tool types

### `ToolAnnotations`

```python
@dataclass(frozen=True)
class ToolAnnotations:
    readOnlyHint: bool = False
    destructiveHint: bool = True    # MCP spec conservative default
    idempotentHint: bool = False
    openWorldHint: bool = True      # MCP spec conservative default
```

Behavioural hints transmitted to clients in `tools/list`.  See
[`mcp_tool`](server.md#mcp_tool).

---

### `ToolSchema`

```python
@dataclass
class ToolSchema:
    name: str
    description: str
    inputSchema: dict[str, Any] = field(default_factory=dict)
    outputSchema: dict[str, Any] | None = None
    annotations: dict[str, Any] | None = None
```

Descriptor for a single MCP tool as returned by `tools/list` and
`McpClientProtocol.list_tools()`.

---

### `ToolCallParams`

```python
@dataclass
class ToolCallParams:
    name: str
    arguments: dict[str, Any] | None = None
```

Parameters for a `tools/call` JSON-RPC request.

---

### `ToolResult`

```python
@dataclass
class ToolResult:
    content: list[TextContent | ImageContent | EmbeddedResource] = field(default_factory=list)
    isError: bool = False
    structuredContent: dict[str, Any] | None = None
```

Full result envelope from a `tools/call` response.

---

### `ToolOutput`

```python
@dataclass
class ToolOutput:
    content: list[Any] | None = None
    structured_content: dict[str, Any] | None = None
    is_error: bool = False
```

Rich return type for `@mcp_tool` methods.  Lets a tool control the display
content (shown to the user) and the structured JSON payload (parsed by the
agent loop) independently.

| Field | Description |
|---|---|
| `content` | List of content blocks (`TextContent`, `ImageContent`, etc.) sent to the client |
| `structured_content` | Structured JSON data; advertised as `structuredContent` in the wire result |
| `is_error` | When `True` sets `isError: true` in the wire result |

---

## Resource types

### `ResourceSchema`

```python
@dataclass
class ResourceSchema:
    uri: str
    name: str
    description: str | None = None
    mimeType: str | None = None
```

Descriptor for a single MCP resource as returned by `resources/list`.

---

### `ResourceContent`

```python
@dataclass
class ResourceContent:
    uri: str
    mimeType: str | None = None
    text: str | None = None
    blob: str | None = None   # base64-encoded binary
```

The content of a read resource.  Exactly one of `text` or `blob` should be
set.

---

### `ReadResourceParams`

```python
@dataclass
class ReadResourceParams:
    uri: str
```

Parameters for a `resources/read` JSON-RPC request.

---

### `ReadResourceResult`

```python
@dataclass
class ReadResourceResult:
    contents: list[ResourceContent] = field(default_factory=list)
```

Result envelope from a `resources/read` response.

---

### `BlobResource`

```python
@dataclass
class BlobResource:
    data: bytes
    mime_type: str = "application/octet-stream"
```

Convenience return type for binary `@mcp_resource` methods.  The server
automatically base-64 encodes `data` and sets `mimeType` in the
`ResourceContent`.

---

### `ResourceResult`

```python
@dataclass
class ResourceResult:
    contents: list[Any] = field(default_factory=list)
```

Multi-item return type for `@mcp_resource` methods when the method produces
more than one `ResourceContent`.

---

## Prompt types

### `PromptArgument`

```python
@dataclass
class PromptArgument:
    name: str
    description: str | None = None
    required: bool = False
```

A single declared argument within a `PromptSchema`.

---

### `PromptSchema`

```python
@dataclass
class PromptSchema:
    name: str
    description: str | None = None
    arguments: list[PromptArgument] = field(default_factory=list)
```

Descriptor for a single MCP prompt as returned by `prompts/list`.

---

### `PromptMessage`

```python
@dataclass
class PromptMessage:
    role: Literal["user", "assistant"]
    content: TextContent | ImageContent | EmbeddedResource
```

A single rendered message within a `GetPromptResult`.

---

### `GetPromptParams`

```python
@dataclass
class GetPromptParams:
    name: str
    arguments: dict[str, str] | None = None
```

Parameters for a `prompts/get` JSON-RPC request.

---

### `GetPromptResult`

```python
@dataclass
class GetPromptResult:
    description: str
    messages: list[PromptMessage] = field(default_factory=list)
```

Result envelope from a `prompts/get` response.

---

## Sampling types

### `SamplingMessage`

```python
@dataclass
class SamplingMessage:
    role: Literal["user", "assistant"]
    content: TextContent | ImageContent

    def to_dict(self) -> dict[str, Any]: ...
```

A single message in a `sampling/createMessage` request.  Used with
`McpToolContext.sample()`.

---

### `CreateMessageParams`

```python
@dataclass
class CreateMessageParams:
    messages: list[SamplingMessage]
    maxTokens: int
    systemPrompt: str | None = None
    includeContext: Literal["none", "thisServer", "allServers"] = "none"
    temperature: float | None = None
    stopSequences: list[str] = field(default_factory=list)
    modelPreferences: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]: ...
```

Parameters for a `sampling/createMessage` request.

---

### `CreateMessageResult`

```python
@dataclass
class CreateMessageResult:
    role: Literal["assistant"]
    content: TextContent | ImageContent
    model: str
    stopReason: str | None = None

    @property
    def text(self) -> str: ...      # "" for image content

    @classmethod
    def from_dict(cls, obj: dict[str, Any]) -> CreateMessageResult: ...
```

Result of a `sampling/createMessage` request.  The `text` property returns the
assistant's reply as a plain string (empty string for image content).

---

## Elicitation types

### `ElicitResult`

```python
@dataclass
class ElicitResult:
    action: Literal["accept", "decline", "cancel"]
    content: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, obj: dict[str, Any]) -> ElicitResult: ...
```

Result of an `elicitation/create` request initiated via `McpToolContext.elicit()`.

| `action` value | Meaning |
|---|---|
| `"accept"` | User filled in the form; `content` contains the submitted data |
| `"decline"` | User explicitly declined the elicitation |
| `"cancel"` | User closed or dismissed without responding |

---

## Roots

### `Root`

```python
@dataclass
class Root:
    uri: str
    name: str | None = None

    def to_dict(self) -> dict[str, Any]: ...
```

A filesystem root exposed by an MCP client to servers.  Supply to
`McpServer.*(..., roots=[Root(uri="file:///home/user/project")])`.

---

## Exceptions

### `McpParseError`

```python
class McpParseError(ValueError):
```

Raised by `parse_message()` when an incoming MCP message cannot be parsed
(invalid JSON, missing `jsonrpc` field, or unrecognised shape).

---

### `McpSamplingNotAvailable`

```python
class McpSamplingNotAvailable(RuntimeError):
```

Raised by `McpToolContext.sample()` when the connected client did not advertise
the `sampling` capability or the transport cannot deliver server-to-client
requests (legacy SSE transport does not support them).

---

### `McpElicitationNotAvailable`

```python
class McpElicitationNotAvailable(RuntimeError):
```

Raised by `McpToolContext.elicit()` when the connected client did not advertise
the `elicitation` capability or the transport cannot deliver server-to-client
requests.

---

## Version constants

```python
from lauren_mcp import LATEST, STABLE, SUPPORTED
```

| Constant | Type | Value | Description |
|---|---|---|---|
| `LATEST` | `str` | `"2025-03-26"` | Latest MCP protocol version supported |
| `STABLE` | `str` | `"2024-11-05"` | Stable MCP protocol version for production |
| `SUPPORTED` | `frozenset[str]` | `{"2025-03-26", "2024-11-05"}` | All handled protocol versions |

Pass `protocol_version=STABLE` to any `McpServer.*` factory to force the older
transport.
