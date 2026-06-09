# MCP Client Guide

This guide covers connecting to remote MCP servers using `lauren-mcp`'s three transport
modes: stdio, WebSocket, and HTTP+SSE.

---

## `McpServer` factory

`McpServer` is the entry point for creating client connections. It exposes three
class-method factories, one per transport:

```python
from lauren_mcp import McpServer

# stdio subprocess
client = McpServer.stdio(["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"])

# WebSocket
client = McpServer.ws("ws://localhost:8000/mcp/ws")

# HTTP + SSE
client = McpServer.http("http://localhost:8000/mcp/sse")
```

All three return an `McpClientProtocol` instance. The connection is not established until
you enter the async context manager (or call `connect()` explicitly).

---

## `McpServer.stdio`

Starts a subprocess and communicates over its stdin/stdout.

```python
McpServer.stdio(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
    timeout: float = 30.0,
) -> McpClientProtocol
```

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `command` | `list[str]` | required | Command + arguments to start the MCP server subprocess |
| `env` | `dict[str, str] \| None` | `None` | Extra environment variables; merged with the current process environment |
| `cwd` | `str \| None` | `None` | Working directory for the subprocess |
| `timeout` | `float` | `30.0` | Seconds to wait for the subprocess to complete the MCP handshake |

**Example**

```python
client = McpServer.stdio(
    ["python", "-m", "my_mcp_server"],
    env={"DEBUG": "1"},
    cwd="/path/to/server",
)
async with client:
    tools = await client.list_tools()
```

No extra dependencies are required for stdio — it is part of the core install.

---

## `McpServer.ws`

Connects to an MCP server over a persistent WebSocket connection.

```python
McpServer.ws(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    ping_interval: float = 20.0,
    reconnect: bool = True,
    reconnect_delay: float = 1.0,
    reconnect_max_delay: float = 30.0,
    timeout: float = 30.0,
) -> McpClientProtocol
```

**Requires**: `pip install "lauren-mcp[ws]"` (the `websockets` package).

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `url` | `str` | required | WebSocket URL, e.g. `ws://host/mcp/ws` or `wss://host/mcp/ws` |
| `headers` | `dict[str, str] \| None` | `None` | Extra HTTP headers sent during the upgrade (use for auth tokens) |
| `ping_interval` | `float` | `20.0` | Seconds between keepalive pings |
| `reconnect` | `bool` | `True` | Automatically reconnect on unexpected disconnection |
| `reconnect_delay` | `float` | `1.0` | Initial delay before first reconnect attempt |
| `reconnect_max_delay` | `float` | `30.0` | Maximum delay between reconnect attempts (exponential backoff) |
| `timeout` | `float` | `30.0` | Seconds to wait for the handshake to complete |

**Example**

```python
client = McpServer.ws(
    "wss://api.example.com/mcp/ws",
    headers={"Authorization": "Bearer my-token"},
)
async with client:
    result = await client.call_tool("search", {"query": "coffee"})
```

---

## `McpServer.http`

Connects to an MCP server over HTTP with Server-Sent Events for server-to-client
messages.

```python
McpServer.http(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
    sse_timeout: float | None = None,
) -> McpClientProtocol
```

**Requires**: `pip install "lauren-mcp[http]"` (the `httpx` and `httpx-sse` packages).

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `url` | `str` | required | Base SSE URL, e.g. `http://host/mcp/sse` |
| `headers` | `dict[str, str] \| None` | `None` | Extra HTTP headers for every request (use for auth tokens) |
| `timeout` | `float` | `30.0` | Per-request timeout in seconds |
| `sse_timeout` | `float \| None` | `None` | SSE stream read timeout; `None` means no timeout |

**Example**

```python
client = McpServer.http(
    "https://api.example.com/mcp/sse",
    headers={"X-Api-Key": "secret"},
)
async with client:
    resources = await client.list_resources()
```

---

## `McpClientProtocol` methods

All three transports return an object that implements `McpClientProtocol`:

### `connect() / disconnect()`

```python
await client.connect()    # establishes connection, runs MCP handshake
await client.disconnect() # gracefully closes connection
```

Both are called automatically when using the async context manager.

### `list_tools() -> list[ToolSchema]`

Returns the server's current tool manifest.

```python
tools = await client.list_tools()
for tool in tools:
    print(tool.name, "—", tool.description)
```

### `call_tool(name: str, arguments: dict) -> list[TextContent | ImageContent | EmbeddedResource]`

Calls a tool and returns its content blocks.

```python
result = await client.call_tool("search", {"query": "blue widgets"})
# result is a list of TextContent or ImageContent objects
text = result[0].text  # for TextContent
```

### `list_resources() -> list[ResourceSchema]`

Returns the server's current resource manifest.

### `read_resource(uri: str) -> ReadResourceResult`

Reads a resource by URI.

```python
res = await client.read_resource("items://42")
print(res.contents[0].text)
```

### `list_prompts() -> list[PromptSchema]`

Returns the server's prompt manifest.

### `get_prompt(name: str, arguments: dict | None = None) -> GetPromptResult`

Retrieves a rendered prompt.

```python
prompt_result = await client.get_prompt("catalogue_summary_prompt", {"focus": "gadgets"})
print(prompt_result.messages[0].content.text)
```

---

## Connection lifecycle

```
McpServer.ws(url) → McpClientProtocol (not yet connected)
    │
    ▼ async with client: (or await client.connect())
    │
    ├─ TCP/TLS connect
    ├─ MCP initialize handshake (capabilities exchange)
    ├─ Ready: list_tools / call_tool / etc.
    │
    ▼ exit context (or await client.disconnect())
    └─ graceful close
```

If `reconnect=True` (WebSocket only), any unexpected disconnection triggers exponential
backoff reconnect attempts in the background. Calls made during a reconnect window will
raise `McpConnectionError` — callers should implement retry logic for production use.

---

## Error handling

| Exception | When raised |
|---|---|
| `McpConnectionError` | Cannot connect to or lost connection to the server |
| `McpHandshakeError` | Protocol version mismatch during initialize |
| `McpToolNotFoundError` | `call_tool` name not in server's tool list |
| `McpToolError` | Server returned an error response for a tool call |
| `McpTimeoutError` | Operation exceeded the configured timeout |

All exceptions derive from `lauren_mcp.McpError`.

---

## Authentication headers

Pass authentication credentials via the `headers` parameter:

```python
# Bearer token
client = McpServer.ws("wss://api.example.com/mcp/ws", headers={"Authorization": "Bearer token"})

# API key
client = McpServer.http("https://api.example.com/mcp/sse", headers={"X-Api-Key": "key"})

# Basic auth (pre-encoded)
import base64
creds = base64.b64encode(b"user:pass").decode()
client = McpServer.ws("wss://api.example.com/mcp/ws", headers={"Authorization": f"Basic {creds}"})
```

For stdio servers, pass credentials via `env`:

```python
client = McpServer.stdio(
    ["python", "-m", "my_server"],
    env={"API_KEY": "secret"},
)
```

---

## Reconnect behaviour (WebSocket)

When `reconnect=True` (default), the WebSocket client uses exponential backoff:

1. Disconnected → wait `reconnect_delay` seconds → attempt reconnect
2. On failure → wait `min(delay * 2, reconnect_max_delay)` → retry
3. On success → reset delay to `reconnect_delay`

The reconnect loop runs until the context manager exits or `disconnect()` is called.
Pending `call_tool` awaits that were in-flight at disconnect time will raise
`McpConnectionError`.
