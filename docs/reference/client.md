# Client API Reference

---

## `McpServer`

Factory class — use the static methods below.  Do not instantiate directly.

### `McpServer.stdio`

```python
@staticmethod
def stdio(
    command: list[str] | tuple[str, ...],
    *,
    max_retries: int = 3,
    startup_timeout: float = 10.0,
) -> McpClientProtocol:
```

Create an MCP client that communicates with a subprocess over stdin/stdout.

**No extra install required** — stdio is part of the core package.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `command` | `list[str] \| tuple[str, ...]` | required | Command + args to launch the subprocess |
| `max_retries` | `int` | `3` | Subprocess restart attempts on unexpected EOF |
| `startup_timeout` | `float` | `10.0` | Seconds to wait for the `initialize` handshake |

**Returns**: `McpClientProtocol` (not yet connected).

**Example**

```python
from lauren_mcp import McpServer

client = McpServer.stdio(
    ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
)
await client.connect()
tools = await client.list_tools()
await client.close()
```

---

### `McpServer.ws`

```python
@staticmethod
def ws(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    max_retries: int = 3,
    startup_timeout: float = 10.0,
) -> McpClientProtocol:
```

Create an MCP client that connects over WebSocket.

**Requires**: `pip install "lauren-mcp[ws]"`

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `url` | `str` | required | WebSocket URL (`ws://` or `wss://`) |
| `headers` | `dict[str, str] \| None` | `None` | Extra HTTP headers for the upgrade request |
| `max_retries` | `int` | `3` | Reconnect attempts after unexpected disconnect |
| `startup_timeout` | `float` | `10.0` | Seconds to wait for the `initialize` handshake |

**Example**

```python
client = McpServer.ws(
    "wss://api.example.com/mcp/ws",
    headers={"Authorization": "Bearer my-token"},
)
await client.connect()
result = await client.call_tool("search", {"query": "coffee"})
await client.close()
```

---

### `McpServer.http`

```python
@staticmethod
def http(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    max_retries: int = 3,
    startup_timeout: float = 10.0,
) -> McpClientProtocol:
```

Create an MCP client using HTTP POST for client→server messages and SSE for
server→client messages.

**Requires**: `pip install "lauren-mcp[http]"`

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `url` | `str` | required | Base URL (`http://` or `https://`) |
| `headers` | `dict[str, str] \| None` | `None` | Extra HTTP headers for every request |
| `max_retries` | `int` | `3` | Reconnect attempts after SSE stream closes |
| `startup_timeout` | `float` | `10.0` | Seconds to wait for the `initialize` handshake |

---

## `McpClientProtocol`

The interface implemented by all three transport clients.

### Connection lifecycle

```python
await client.connect()   # establish transport + MCP handshake
await client.close()     # graceful shutdown
```

### `list_tools() → list[ToolSchema]`

```python
tools = await client.list_tools()
for tool in tools:
    print(tool.name, "—", tool.description)
    print("  inputSchema:", tool.inputSchema)
```

### `call_tool(name, arguments) → dict`

Returns a raw dict with `"content"` and `"isError"` keys.  The `"content"`
list contains dicts with `{"type": "text", "text": "..."}` or image/resource
blocks.

```python
result = await client.call_tool("search", {"query": "blue widgets"})

if result.get("isError"):
    print("Tool error")

content = result.get("content", [])
if content and content[0].get("type") == "text":
    print(content[0]["text"])

# dict/list return values are JSON-encoded in text
import json
items = json.loads(content[0]["text"])
```

**Raises**: `McpCallError` if the server returns a JSON-RPC error response.

### `list_resources() → list[ResourceSchema]`

```python
resources = await client.list_resources()
for r in resources:
    print(r.name, "—", r.uri)
```

### `read_resource(uri) → dict`

Returns a raw dict with a `"contents"` list.

```python
result = await client.read_resource("/items/42")
contents = result.get("contents", [])
if contents:
    print(contents[0].get("text", ""))
```

### `list_prompts() → list[PromptSchema]`

```python
prompts = await client.list_prompts()
print([p.name for p in prompts])
```

### `get_prompt(name, arguments) → dict`

Returns a raw dict with a `"messages"` list.

```python
result = await client.get_prompt("summary_prompt", {"topic": "sales"})
messages = result.get("messages", [])
if messages:
    print(messages[0].get("content", {}).get("text", ""))
```

### `ping() → None`

```python
await client.ping()   # raises McpCallError on failure
```

---

## `McpCallError`

```python
from lauren_mcp import McpCallError

class McpCallError(Exception):
    code: int
    # message is the standard exception message
```

Raised when the server returns a JSON-RPC error response.

```python
from lauren_mcp import McpCallError
import asyncio

try:
    result = await client.call_tool("divide", {"a": 1, "b": 0})
except McpCallError as exc:
    print(f"Server error {exc.code}: {exc}")
except asyncio.TimeoutError:
    print("Request timed out")
```

---

## `McpServerConfig`

```python
from dataclasses import dataclass

@dataclass
class McpServerConfig:
    alias: str
    client: Any   # McpClientProtocol
```

Pairs an alias string with an MCP client for use with `McpToolBridge` and
`lauren_ai.AgentModule.for_root(mcp_servers=[...])`.

**Fields**

| Field | Type | Required | Description |
|---|---|---|---|
| `alias` | `str` | yes | Short identifier; tools are namespaced as `alias__tool_name` |
| `client` | `McpClientProtocol` | yes | Client instance from `McpServer.stdio/ws/http` |

**Example**

```python
from lauren_mcp import McpServerConfig, McpServer

config = McpServerConfig(
    alias="fs",
    client=McpServer.stdio(["python", "-m", "my_mcp_server"]),
)
```

---

## `McpToolBridge`

Manages the lifecycle for a list of `McpServerConfig` entries.  Connects
every server, populates a registry, and disconnects cleanly on teardown.

```python
from lauren_mcp import McpToolBridge, McpServerConfig, McpServer

bridge = McpToolBridge([
    McpServerConfig(alias="alpha", client=McpServer.stdio(["python", "server_a.py"])),
    McpServerConfig(alias="beta",  client=McpServer.stdio(["python", "server_b.py"])),
])

# Optional: attach a registry that implements register_mcp_server()
bridge.set_registry(my_registry)

await bridge.connect_all()     # connect + list_tools + populate registry
await bridge.disconnect_all()  # close all clients
```

### `set_registry(registry) → None`

Attach any object with a `register_mcp_server(alias, tools, client)` method.
Called by `connect_all()` once per server.

### `connect_all() → None`

Connect every configured server, fetch tool lists, and call
`registry.register_mcp_server(alias, tools, client)` for each one.  Failures
on individual servers are logged at ERROR level and do not abort the others.

### `disconnect_all() → None`

Close every client.  Individual close failures are suppressed.
