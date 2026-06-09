# MCP Client Guide

This guide covers connecting to MCP servers using `lauren-mcp`'s three
transport modes: **stdio** (subprocess), **WebSocket**, and **HTTP + SSE**.

---

## `McpServer` factory

`McpServer` is the entry point for all client connections:

```python
from lauren_mcp import McpServer

# stdio — spawn a local subprocess
client = McpServer.stdio(["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"])

# WebSocket — connect to a running Lauren app
client = McpServer.ws("ws://localhost:8000/mcp/ws")

# HTTP + SSE — connect to a running Lauren app
client = McpServer.http("http://localhost:8000/mcp")
```

All three return an `McpClientProtocol` object.  Call `await client.connect()`
before making requests and `await client.close()` when done.

---

## `McpServer.stdio`

Starts a subprocess and communicates over its stdin/stdout.

```python
McpServer.stdio(
    command: list[str],
    *,
    max_retries: int = 3,
    startup_timeout: float = 10.0,
) -> McpClientProtocol
```

| Argument | Type | Default | Description |
|---|---|---|---|
| `command` | `list[str]` | required | Command + arguments for the subprocess |
| `max_retries` | `int` | `3` | How many times to restart on unexpected exit |
| `startup_timeout` | `float` | `10.0` | Seconds to wait for the `initialize` handshake |

**Example**

```python
import asyncio
from lauren_mcp import McpServer

async def main():
    client = McpServer.stdio(
        ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    )
    await client.connect()
    tools = await client.list_tools()
    print([t.name for t in tools])
    await client.close()

asyncio.run(main())
```

---

## `McpServer.ws`

Connects to an MCP server over a persistent WebSocket connection.

**Requires**: `pip install "lauren-mcp[ws]"`

```python
McpServer.ws(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    max_retries: int = 3,
    startup_timeout: float = 10.0,
) -> McpClientProtocol
```

| Argument | Type | Default | Description |
|---|---|---|---|
| `url` | `str` | required | WebSocket URL, e.g. `ws://host/mcp/ws` |
| `headers` | `dict[str, str] \| None` | `None` | Extra HTTP headers (e.g. auth tokens) |
| `max_retries` | `int` | `3` | Reconnect attempts on disconnect |
| `startup_timeout` | `float` | `10.0` | Seconds to wait for handshake |

**Example**

```python
client = McpServer.ws(
    "ws://localhost:8000/mcp/ws",
    headers={"Authorization": "Bearer my-token"},
)
await client.connect()
result = await client.call_tool("search", {"query": "widget"})
await client.close()
```

---

## `McpServer.http`

Connects to an MCP server over HTTP + Server-Sent Events.

**Requires**: `pip install "lauren-mcp[http]"`

```python
McpServer.http(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    max_retries: int = 3,
    startup_timeout: float = 10.0,
) -> McpClientProtocol
```

---

## `McpClientProtocol` methods

All three transports return the same interface.

### `connect()` / `close()`

```python
await client.connect()   # initialise handshake
await client.close()     # graceful shutdown
```

### `list_tools() → list[ToolSchema]`

Returns the server's tool catalogue.  Each `ToolSchema` has `.name`,
`.description`, and `.inputSchema` (a JSON Schema dict).

```python
tools = await client.list_tools()
for tool in tools:
    print(tool.name, "—", tool.description)
    print("  schema:", tool.inputSchema)
```

### `call_tool(name, arguments) → dict`

Calls a tool and returns a raw dict with `"content"` and `"isError"` keys.
The `"content"` list contains objects with `{"type": "text", "text": "..."}`.

```python
result = await client.call_tool("search", {"query": "blue widgets"})

# Check for tool-level errors
if result.get("isError"):
    print("Tool error:", result)

# Extract the first text item
content = result.get("content", [])
if content and content[0].get("type") == "text":
    print(content[0]["text"])

# When the tool returns a dict/list, it's JSON-encoded in the text field
import json
items = json.loads(content[0]["text"])
```

### `list_resources() → list[ResourceSchema]`

Returns the server's resource catalogue.  Each `ResourceSchema` has `.uri`,
`.name`, `.description`, and `.mimeType`.

```python
resources = await client.list_resources()
for r in resources:
    print(r.name, "—", r.uri)
```

### `read_resource(uri) → dict`

Reads a resource by URI.  Returns a raw dict with `"contents"` list.

```python
result = await client.read_resource("/items/42")
contents = result.get("contents", [])
if contents:
    print(contents[0].get("text", ""))
```

### `list_prompts() → list[PromptSchema]`

Returns the server's prompt catalogue.

### `get_prompt(name, arguments) → dict`

Retrieves a rendered prompt.  Returns a raw dict with `"messages"` list.

```python
result = await client.get_prompt("catalogue_summary", {"focus": "gadgets"})
messages = result.get("messages", [])
if messages:
    text = messages[0].get("content", {}).get("text", "")
    print(text)
```

### `ping()`

Checks that the connection is alive; raises `McpCallError` on failure.

```python
await client.ping()
```

---

## Error handling

```python
from lauren_mcp._client._stdio import McpCallError
import asyncio

try:
    result = await client.call_tool("divide", {"a": 1, "b": 0})
except McpCallError as exc:
    print(f"Tool failed (code {exc.code}): {exc}")
except asyncio.TimeoutError:
    print("Request timed out")
```

`McpCallError` is raised when the server returns a JSON-RPC error response.
`asyncio.TimeoutError` is raised when `startup_timeout` is exceeded during
`connect()`.

---

## Authentication headers

```python
# Bearer token (WebSocket or HTTP)
client = McpServer.ws(
    "wss://api.example.com/mcp/ws",
    headers={"Authorization": "Bearer eyJ..."},
)

client = McpServer.http(
    "https://api.example.com/mcp",
    headers={"X-Api-Key": "sk-..."},
)
```

---

## Retry on disconnect

The `max_retries` parameter controls how many times the stdio client
restarts after an unexpected subprocess exit:

```python
# Never retry — raise immediately on exit
client = McpServer.stdio(["python", "server.py"], max_retries=0)

# Retry up to 5 times
client = McpServer.stdio(["python", "server.py"], max_retries=5)
```

---

## Connection lifecycle

```
McpServer.ws(url) → McpClientProtocol (not yet connected)
    │
    ▼  await client.connect()
    │
    ├── TCP / TLS connect
    ├── MCP initialize handshake (capabilities exchange)
    └── Ready: list_tools / call_tool / etc.

    await client.close()  → graceful shutdown
```
