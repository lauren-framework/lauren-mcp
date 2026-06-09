# Wire Types Reference

All wire types live in `lauren_mcp._types` and are re-exported from `lauren_mcp`.

---

## `JsonRpcRequest`

```python
@dataclass
class JsonRpcRequest:
    jsonrpc: str          # always "2.0"
    id: int | str
    method: str
    params: dict | None = None
```

Represents an outgoing or incoming JSON-RPC 2.0 request. The `id` field must be
present; for notifications (no reply expected) use `JsonRpcNotification`.

---

## `JsonRpcNotification`

```python
@dataclass
class JsonRpcNotification:
    jsonrpc: str          # always "2.0"
    method: str
    params: dict | None = None
```

A JSON-RPC 2.0 notification — like a request but with no `id` field. The server does
not send a response to notifications.

---

## `JsonRpcResponse`

```python
@dataclass
class JsonRpcResponse:
    jsonrpc: str          # always "2.0"
    id: int | str
    result: dict | list | str | int | float | bool | None
```

Successful JSON-RPC 2.0 response. The `result` field contains the method-specific
return value.

---

## `JsonRpcErrorResponse`

```python
@dataclass
class JsonRpcErrorResponse:
    jsonrpc: str          # always "2.0"
    id: int | str | None
    error: JsonRpcError
```

Error JSON-RPC 2.0 response. `id` is `None` when the error occurred before the
request `id` could be determined (e.g. parse error).

```python
@dataclass
class JsonRpcError:
    code: int
    message: str
    data: dict | None = None
```

---

## `McpErrorCode`

```python
from enum import IntEnum

class McpErrorCode(IntEnum):
    PARSE_ERROR      = -32700
    INVALID_REQUEST  = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS   = -32602
    INTERNAL_ERROR   = -32603
    # MCP-specific codes
    TOOL_NOT_FOUND   = -32001
    RESOURCE_NOT_FOUND = -32002
    PROMPT_NOT_FOUND   = -32003
    CONNECTION_ERROR   = -32004
```

Standard JSON-RPC 2.0 error codes plus MCP-specific extensions.

---

## `parse_message`

```python
def parse_message(
    data: str | bytes,
) -> JsonRpcRequest | JsonRpcNotification | JsonRpcResponse | JsonRpcErrorResponse:
    ...
```

Parse a raw JSON string or bytes into the appropriate JSON-RPC message type.

**Parameters**

| Name | Type | Description |
|---|---|---|
| `data` | `str \| bytes` | Raw JSON-RPC message |

**Returns**: One of the four JSON-RPC message types.

**Raises**: `JsonRpcParseError` if `data` is not valid JSON or does not conform to
JSON-RPC 2.0 structure.

---

## `build_error_response`

```python
def build_error_response(
    request_id: int | str | None,
    code: McpErrorCode | int,
    message: str,
    data: dict | None = None,
) -> JsonRpcErrorResponse:
    ...
```

Convenience constructor for error responses.

**Example**

```python
response = build_error_response(
    request_id=42,
    code=McpErrorCode.TOOL_NOT_FOUND,
    message="Tool 'foo' is not registered on this server.",
)
```

---

## `ToolSchema`

```python
@dataclass
class ToolSchema:
    name: str
    description: str
    inputSchema: dict   # JSON Schema object
```

Descriptor for a single MCP tool as returned by `tools/list`.

---

## `ResourceSchema`

```python
@dataclass
class ResourceSchema:
    uri: str
    name: str
    description: str | None = None
    mimeType: str = "text/plain"
```

Descriptor for a single MCP resource as returned by `resources/list`.

---

## `PromptSchema`

```python
@dataclass
class PromptSchema:
    name: str
    description: str | None = None
    arguments: list[PromptArgument] = field(default_factory=list)
```

Descriptor for a single MCP prompt as returned by `prompts/list`.

---

## `TextContent`

```python
@dataclass
class TextContent:
    type: Literal["text"]   # always "text"
    text: str
```

A plain-text content block returned in tool call results.

---

## `ImageContent`

```python
@dataclass
class ImageContent:
    type: Literal["image"]   # always "image"
    data: str                # base-64 encoded image bytes
    mimeType: str            # e.g. "image/png"
```

A base-64 encoded image content block returned in tool call results.

---

## `EmbeddedResource`

```python
@dataclass
class EmbeddedResource:
    type: Literal["resource"]   # always "resource"
    resource: TextResourceContents | BlobResourceContents
```

An embedded resource returned inside a tool call result.

---

## `PromptArgument`

```python
@dataclass
class PromptArgument:
    name: str
    description: str | None = None
    required: bool = False
```

A single argument descriptor within a `PromptSchema`.

---

## `PromptMessage`

```python
@dataclass
class PromptMessage:
    role: Literal["user", "assistant"]
    content: TextContent | ImageContent | EmbeddedResource
```

A single rendered message within a `GetPromptResult`.

---

## `InitializeParams`

```python
@dataclass
class InitializeParams:
    protocolVersion: str
    capabilities: ClientCapabilities
    clientInfo: Implementation
```

Payload sent by the client in the MCP `initialize` request.

---

## `InitializeResult`

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

## `ClientCapabilities`

```python
@dataclass
class ClientCapabilities:
    roots: dict | None = None
    sampling: dict | None = None
    experimental: dict | None = None
```

Capability flags advertised by the client during handshake.

---

## `ServerCapabilities`

```python
@dataclass
class ServerCapabilities:
    tools: dict | None = None
    resources: dict | None = None
    prompts: dict | None = None
    logging: dict | None = None
    experimental: dict | None = None
```

Capability flags advertised by the server during handshake.

---

## `Implementation`

```python
@dataclass
class Implementation:
    name: str
    version: str
```

Identifies a client or server implementation in the handshake messages.

---

## `ToolCallParams`

```python
@dataclass
class ToolCallParams:
    name: str
    arguments: dict | None = None
```

Arguments for a `tools/call` JSON-RPC request.

---

## `ToolResult`

```python
@dataclass
class ToolResult:
    content: list[TextContent | ImageContent | EmbeddedResource]
    isError: bool = False
```

Full result envelope from a `tools/call` response.

---

## `ReadResourceParams`

```python
@dataclass
class ReadResourceParams:
    uri: str
```

Arguments for a `resources/read` JSON-RPC request.

---

## `ReadResourceResult`

```python
@dataclass
class ReadResourceResult:
    contents: list[TextResourceContents | BlobResourceContents]
```

Result envelope from a `resources/read` response.

---

## `GetPromptParams`

```python
@dataclass
class GetPromptParams:
    name: str
    arguments: dict[str, str] | None = None
```

Arguments for a `prompts/get` JSON-RPC request.

---

## `GetPromptResult`

```python
@dataclass
class GetPromptResult:
    description: str | None
    messages: list[PromptMessage]
```

Result envelope from a `prompts/get` response.
