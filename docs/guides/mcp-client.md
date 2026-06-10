# MCP Client Guide

This guide covers connecting to MCP servers using `lauren-mcp`'s four transport
modes: **stdio** (subprocess), **WebSocket**, **HTTP + SSE** (legacy), and
**Streamable HTTP** (recommended for new deployments).

---

## `McpServer` factory

`McpServer` is the entry point for all client connections:

```python
from lauren_mcp import McpServer, Root

# stdio — spawn a local subprocess
client = McpServer.stdio(["python", "-m", "myserver"])

# WebSocket — persistent bidirectional connection
client = McpServer.ws("ws://localhost:8000/mcp/ws", headers={"Authorization": "Bearer token"})

# Legacy HTTP + SSE — MCP 2024-11-05 transport
client = McpServer.http("http://localhost:8000/mcp")

# Streamable HTTP — MCP 2025-03-26 transport (recommended for new deployments)
client = McpServer.streamable_http("http://localhost:8000/mcp")
```

All four return an `McpClientProtocol` object. Call `await client.connect()`
before making requests and `await client.close()` when done.

---

## Protocol version

The default protocol version requested during the `initialize` handshake is
`"2025-03-26"` (the current `LATEST`). You can override it per factory call:

```python
client = McpServer.ws(url, protocol_version="2024-11-05")
```

After `connect()` completes, `client.protocol_version` holds the version the
server actually negotiated. Accessing it before `connect()` raises `RuntimeError`.

```python
await client.connect()
print(client.protocol_version)  # e.g. "2025-03-26"
```

---

## `McpServer.stdio`

Starts a subprocess and communicates over its stdin/stdout.

```python
McpServer.stdio(
    command: list[str],
    *,
    max_retries: int = 3,
    startup_timeout: float = 10.0,
    **feature_kwargs,
) -> McpClientProtocol
```

| Argument | Type | Default | Description |
|---|---|---|---|
| `command` | `list[str]` | required | Command + arguments for the subprocess |
| `max_retries` | `int` | `3` | How many times to restart on unexpected exit |
| `startup_timeout` | `float` | `10.0` | Seconds to wait for the `initialize` handshake |

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

> **Note:** Set `max_retries=0` in tests to prevent 30-second hangs when a
> server script crashes on startup.

---

## `McpServer.ws`

Connects to an MCP server over a persistent WebSocket connection.

**Requires:** `pip install "lauren-mcp[ws]"`

```python
McpServer.ws(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    max_retries: int = 3,
    startup_timeout: float = 10.0,
    **feature_kwargs,
) -> McpClientProtocol
```

| Argument | Type | Default | Description |
|---|---|---|---|
| `url` | `str` | required | WebSocket URL, e.g. `ws://host/mcp/ws` |
| `headers` | `dict[str, str] \| None` | `None` | Extra HTTP headers (e.g. auth tokens) |
| `max_retries` | `int` | `3` | Reconnect attempts on disconnect |
| `startup_timeout` | `float` | `10.0` | Seconds to wait for handshake |

```python
client = McpServer.ws(
    "ws://localhost:8000/mcp/ws",
    headers={"Authorization": "Bearer my-token"},
)
await client.connect()
result = await client.call_tool("search", {"query": "widget"})
await client.close()
```

WebSocket is the only transport that supports **full bidirectional** requests:
sampling and elicitation work over WebSocket connections. See
[Sampling handler](#sampling-handler) and [Elicitation handler](#elicitation-handler).

---

## `McpServer.http`

Connects to an MCP server over HTTP + Server-Sent Events (legacy transport,
MCP protocol version 2024-11-05).

**Requires:** `pip install "lauren-mcp[sse]"`

```python
McpServer.http(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    max_retries: int = 3,
    startup_timeout: float = 10.0,
    **feature_kwargs,
) -> McpClientProtocol
```

> **Warning:** This transport cannot carry server-initiated requests (sampling,
> elicitation). Use `McpServer.ws` or `McpServer.streamable_http` when you need
> those features.

---

## `McpServer.streamable_http`

Connects using the MCP 2025-03-26 Streamable HTTP transport. Each request is an
HTTP POST; the server can respond with plain JSON or an SSE stream for long-running
operations. This is the recommended HTTP transport for new deployments.

**Requires:** `pip install "lauren-mcp[sse]"`

```python
McpServer.streamable_http(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    max_retries: int = 3,
    startup_timeout: float = 10.0,
    **feature_kwargs,
) -> McpClientProtocol
```

```python
client = McpServer.streamable_http(
    "http://localhost:8000/mcp",
    headers={"X-Api-Key": "sk-..."},
)
await client.connect()
tools = await client.list_tools()
await client.close()
```

---

## Notification handlers

The server can push notifications to the client without a prior request.
Register handlers either at construction time or dynamically after `connect()`.

### Constructor callbacks

```python
client = McpServer.ws(
    url,
    progress_handler=lambda p: print(f"Progress {p['progress']}/{p.get('total', '?')}"),
    log_handler=lambda p: print(f"[{p['level']}] {p['data']['message']}"),
    list_changed_handler=lambda kind: reload_cache(kind),  # "tools" | "resources" | "prompts"
)
```

### Dynamic registration

Handlers registered after `connect()` can be removed by calling the returned
unsubscribe function:

```python
unsubscribe = client.on_progress(lambda p: ...)
unsubscribe()  # remove this handler

client.on_log(my_log_handler)
client.on_list_changed(my_cache_invalidator)
```

All handler callbacks may be sync or async. Async callbacks are scheduled as
background tasks; exceptions are logged and swallowed.

---

## Roots (filesystem context for servers)

Roots advertise the filesystem locations relevant to a client session. Some
server tools use them to scope searches or read operations.

### Static roots

```python
from lauren_mcp import McpServer, Root

client = McpServer.ws(url, roots=[
    Root("file:///workspace", name="Workspace"),
    Root("file:///data", name="Data"),
])
```

### Dynamic roots

Pass a callable (sync or async). Call `notify_roots_changed()` when the set
changes so the server knows to re-fetch:

```python
async def get_roots():
    return [Root(f"file://{path}") for path in await discover_paths()]

client = McpServer.ws(url, roots=get_roots)
# ... later, after paths change:
await client.notify_roots_changed()
```

---

## Sampling handler

Sampling lets the server ask the client to run an LLM call on its behalf. The
server sends a `sampling/createMessage` request; the client's handler is
responsible for calling the LLM and returning the result.

> **Note:** Sampling requires WebSocket or Streamable HTTP transport. Legacy SSE
> (`McpServer.http`) cannot deliver server-to-client requests.

```python
async def handle_sampling(params: dict) -> dict:
    # params fields: messages, maxTokens, systemPrompt, modelPreferences, etc.
    response = await my_llm.complete(params["messages"], max_tokens=params["maxTokens"])
    return {
        "role": "assistant",
        "content": {"type": "text", "text": response.text},
        "model": response.model,
    }

client = McpServer.ws(url, sampling_handler=handle_sampling)
```

The handler may be sync or async. The client advertises the `sampling` capability
in its `initialize` payload automatically when a `sampling_handler` is supplied.

---

## Elicitation handler

Elicitation lets the server ask the client to prompt its user for structured
input during a tool call. The server sends an `elicitation/create` request
carrying a message and an optional JSON Schema for the expected response.

> **Note:** Elicitation requires WebSocket or Streamable HTTP transport.

```python
async def handle_elicit(params: dict) -> dict:
    message = params["message"]
    schema = params.get("requestedSchema")   # JSON Schema dict or None
    # Prompt the user in your UI ...
    user_input = await prompt_user(message, schema)
    return {"action": "accept", "content": {"value": user_input}}
    # Return {"action": "decline"} or {"action": "cancel"} to abort.

client = McpServer.ws(url, elicitation_handler=handle_elicit)
```

---

## `McpClientProtocol` methods

All four transports expose the same interface.

### `connect()` / `close()`

```python
await client.connect()   # MCP initialize handshake
await client.close()     # graceful shutdown
```

### `list_tools() → list[ToolSchema]`

Returns the server's tool catalogue. Each `ToolSchema` has `.name`,
`.description`, and `.inputSchema` (a JSON Schema dict). `outputSchema` and
`annotations` are present when the server declares them.

```python
tools = await client.list_tools()
for tool in tools:
    print(tool.name, "—", tool.description)
```

### `call_tool(name, arguments) → dict`

Calls a tool and returns a raw dict with `"content"` and `"isError"` keys.
The `"content"` list contains objects with `{"type": "text", "text": "..."}`.
Structured return values are also available in `"structuredContent"` when the
server sends them.

```python
result = await client.call_tool("search", {"query": "blue widgets"})

if result.get("isError"):
    print("Tool reported an error:", result)

content = result.get("content", [])
if content and content[0].get("type") == "text":
    print(content[0]["text"])

# Structured content (dict/list returned by the tool)
structured = result.get("structuredContent")
```

### `list_resources() → list[ResourceSchema]`

Returns the server's resource catalogue. Each `ResourceSchema` has `.uri`,
`.name`, `.description`, and `.mimeType`.

### `read_resource(uri) → dict`

Reads a resource by URI. Returns a raw dict with a `"contents"` list.

```python
result = await client.read_resource("/items/42")
contents = result.get("contents", [])
if contents:
    print(contents[0].get("text", ""))
```

### `list_prompts() → list[PromptSchema]`

Returns the server's prompt catalogue.

### `get_prompt(name, arguments) → dict`

Retrieves a rendered prompt. Returns a raw dict with a `"messages"` list.

```python
result = await client.get_prompt("catalogue_summary", {"focus": "gadgets"})
messages = result.get("messages", [])
if messages:
    print(messages[0].get("content", {}).get("text", ""))
```

### `ping()`

Verifies the connection is alive. Raises `McpCallError` on failure.

```python
await client.ping()
```

### `notify_roots_changed()`

Sends `notifications/roots/list_changed` to the server. Only meaningful when
dynamic roots (a callable) were supplied.

```python
await client.notify_roots_changed()
```

---

## Error handling

```python
from lauren_mcp import McpCallError
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

> **Note:** `McpCallError` is exported directly from `lauren_mcp`. The old
> import path `lauren_mcp._client._stdio.McpCallError` still works but the
> top-level import is preferred.

---

## Authentication headers

```python
# Bearer token (WebSocket or Streamable HTTP)
client = McpServer.ws(
    "wss://api.example.com/mcp/ws",
    headers={"Authorization": "Bearer eyJ..."},
)

client = McpServer.streamable_http(
    "https://api.example.com/mcp",
    headers={"X-Api-Key": "sk-..."},
)
```

---

## Retry on disconnect

The `max_retries` parameter controls how many times the stdio client restarts
after an unexpected subprocess exit, and how many times remote clients attempt
to reconnect:

```python
# Never retry — raise immediately on exit / disconnect
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
    │     client advertises: roots, sampling, elicitation (if configured)
    │     server responds with: protocolVersion, capabilities, serverInfo
    └── Ready: list_tools / call_tool / etc.

    await client.close()  → graceful shutdown
```

---

## Transport comparison

| Feature | `stdio` | `ws` | `http` (SSE) | `streamable_http` |
|---|---|---|---|---|
| MCP protocol version | any | any | 2024-11-05 | 2025-03-26 |
| Sampling / Elicitation | yes | yes | **no** | yes |
| Roots | yes | yes | yes | yes |
| Progress notifications | yes | yes | yes | yes |
| Extra install | — | `[ws]` | `[sse]` | `[sse]` |
