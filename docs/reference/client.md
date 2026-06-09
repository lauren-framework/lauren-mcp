# Client API Reference

---

## `McpServer`

Factory class. Do not instantiate directly — use the class methods below.

### `McpServer.stdio`

```python
@classmethod
def stdio(
    cls,
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
    timeout: float = 30.0,
) -> McpClientProtocol:
    ...
```

Create an MCP client that communicates with a subprocess over stdin/stdout.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `command` | `list[str]` | required | Command + args to launch the MCP server subprocess |
| `env` | `dict[str, str] \| None` | `None` | Extra environment variables (merged with current env) |
| `cwd` | `str \| None` | `None` | Working directory for the subprocess |
| `timeout` | `float` | `30.0` | Seconds to wait for the MCP initialize handshake |

**Returns**: `McpClientProtocol` (not yet connected)

**No extra deps required** — stdio is in the core install.

---

### `McpServer.ws`

```python
@classmethod
def ws(
    cls,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    ping_interval: float = 20.0,
    reconnect: bool = True,
    reconnect_delay: float = 1.0,
    reconnect_max_delay: float = 30.0,
    timeout: float = 30.0,
) -> McpClientProtocol:
    ...
```

Create an MCP client that connects over WebSocket.

**Requires**: `pip install "lauren-mcp[ws]"`

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `url` | `str` | required | WebSocket URL (`ws://` or `wss://`) |
| `headers` | `dict[str, str] \| None` | `None` | Extra HTTP headers for the upgrade request |
| `ping_interval` | `float` | `20.0` | Seconds between keepalive pings |
| `reconnect` | `bool` | `True` | Reconnect automatically on unexpected disconnect |
| `reconnect_delay` | `float` | `1.0` | Initial backoff delay in seconds |
| `reconnect_max_delay` | `float` | `30.0` | Maximum backoff delay in seconds |
| `timeout` | `float` | `30.0` | Handshake timeout in seconds |

**Returns**: `McpClientProtocol` (not yet connected)

---

### `McpServer.http`

```python
@classmethod
def http(
    cls,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
    sse_timeout: float | None = None,
) -> McpClientProtocol:
    ...
```

Create an MCP client that uses HTTP POST for client→server messages and SSE for
server→client messages.

**Requires**: `pip install "lauren-mcp[http]"`

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `url` | `str` | required | Base SSE URL (`http://` or `https://`) |
| `headers` | `dict[str, str] \| None` | `None` | Extra HTTP headers for every request |
| `timeout` | `float` | `30.0` | Per-request timeout in seconds |
| `sse_timeout` | `float \| None` | `None` | SSE read timeout; `None` means no timeout |

**Returns**: `McpClientProtocol` (not yet connected)

---

## `McpClientProtocol`

The interface implemented by all transport clients. You normally receive one of these
from `McpServer.stdio/ws/http` — you do not implement this yourself.

### Context manager

```python
async with client:
    # client is connected here
    ...
# client is disconnected here
```

### `connect() / disconnect()`

```python
await client.connect() -> None
await client.disconnect() -> None
```

`connect()` establishes the transport connection and completes the MCP initialize
handshake. `disconnect()` sends a graceful close and tears down the transport.

### `list_tools() -> list[ToolSchema]`

```python
tools: list[ToolSchema] = await client.list_tools()
```

Fetch the server's current tool manifest. Re-call after `notifications/tools/list_changed`
events to refresh.

### `call_tool(name, arguments) -> list[TextContent | ImageContent | EmbeddedResource]`

```python
result = await client.call_tool("search", {"query": "coffee"})
```

**Parameters**

| Name | Type | Description |
|---|---|---|
| `name` | `str` | Exact tool name as returned by `list_tools()` |
| `arguments` | `dict` | Keyword arguments matching the tool's JSON Schema |

**Returns**: List of content blocks. For most tools this is a list with one `TextContent`.

**Raises**: `McpToolError` if the server returns an error response.

### `list_resources() -> list[ResourceSchema]`

```python
resources: list[ResourceSchema] = await client.list_resources()
```

### `read_resource(uri) -> ReadResourceResult`

```python
result = await client.read_resource("items://42")
print(result.contents[0].text)
```

### `list_prompts() -> list[PromptSchema]`

```python
prompts: list[PromptSchema] = await client.list_prompts()
```

### `get_prompt(name, arguments) -> GetPromptResult`

```python
result = await client.get_prompt("summary_prompt", {"topic": "sales"})
print(result.messages[0].content.text)
```

---

## `McpServerConfig`

```python
from dataclasses import dataclass
from lauren_mcp import McpServerConfig, McpServer

@dataclass
class McpServerConfig:
    alias: str
    client: McpClientProtocol
    description: str | None = None
    tool_filter: list[str] | None = None
```

**Fields**

| Field | Type | Required | Description |
|---|---|---|---|
| `alias` | `str` | yes | Short identifier; tools are namespaced as `alias__tool_name` |
| `client` | `McpClientProtocol` | yes | Client instance from `McpServer.stdio/ws/http` |
| `description` | `str \| None` | no | Human description injected into the agent system prompt |
| `tool_filter` | `list[str] \| None` | no | Whitelist of tool names to expose (all tools if `None`) |

**Example**

```python
McpServerConfig(
    alias="fs",
    client=McpServer.stdio(["python", "-m", "my_mcp_server"]),
    description="Internal filesystem tools",
    tool_filter=["read_file", "list_directory"],
)
```

---

## `McpToolBridge`

Wraps an `McpServerConfig` and manages the connection lifecycle, tool registration,
and dispatch for one remote MCP server. Used internally by `AgentModule`; you can also
use it directly for custom integrations.

```python
from lauren_mcp import McpToolBridge, McpServerConfig, McpServer

config = McpServerConfig(alias="svc", client=McpServer.stdio([...]))
bridge = McpToolBridge(config)

async with bridge:
    # bridge is connected
    tool_names: list[str] = bridge.get_tool_names()
    # e.g. ["svc__search", "svc__get_item"]

    result = await bridge.call("svc__search", {"query": "widget"})
```

### `get_tool_names() -> list[str]`

Returns the list of namespaced tool names available from this server.
Must be called after the async context manager is entered.

### `call(namespaced_name, arguments) -> list[TextContent | ImageContent | EmbeddedResource]`

Strips the alias prefix, calls the underlying tool, and returns the result.
Raises `McpToolNotFoundError` if the name is not in this bridge's tool list.

### `get_tool_schemas() -> list[ToolSchema]`

Returns the raw `ToolSchema` objects for all exposed tools (after applying
`tool_filter`). Useful for building a tool catalogue for an agent system prompt.
