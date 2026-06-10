# Client API Reference

---

## `McpServer`

Factory class — use the static methods below.  Do not instantiate directly.

All factory methods return an `McpClientProtocol` instance that is **not yet
connected**.  Call `await client.connect()` before using it.

### Common feature kwargs

All four factories accept these optional keyword arguments in addition to their
own parameters:

| Kwarg | Type | Default | Description |
|---|---|---|---|
| `protocol_version` | `str` | `"2025-03-26"` | Protocol version to request during handshake |
| `roots` | `list[Root] \| Callable[[], list[Root]] \| None` | `None` | Static list of roots or a callable returning the current roots; advertises the `roots` capability |
| `progress_handler` | `Callable[[dict], None \| Awaitable[None]] \| None` | `None` | Called when the server pushes `notifications/progress` |
| `log_handler` | `Callable[[dict], None \| Awaitable[None]] \| None` | `None` | Called when the server pushes `notifications/message` (server logs) |
| `list_changed_handler` | `Callable[[str], None \| Awaitable[None]] \| None` | `None` | Called with `"tools"` / `"resources"` / `"prompts"` when the server's catalogue changes |
| `sampling_handler` | `Callable[[dict], dict \| Awaitable[dict]] \| None` | `None` | Answers server-initiated `sampling/createMessage` requests; advertises `sampling` capability |
| `elicitation_handler` | `Callable[[dict], dict \| Awaitable[dict]] \| None` | `None` | Answers server-initiated `elicitation/create` requests; advertises `elicitation` capability |

---

### `McpServer.stdio`

```python
@staticmethod
def stdio(
    command: list[str] | tuple[str, ...],
    *,
    max_retries: int = 3,
    startup_timeout: float = 10.0,
    **feature_kwargs,
) -> McpClientProtocol:
```

Create an MCP client that communicates with a subprocess over stdin/stdout.
No extra install required.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `command` | `list[str] \| tuple[str, ...]` | required | Argv sequence to launch the subprocess |
| `max_retries` | `int` | `3` | Subprocess restart attempts on unexpected EOF |
| `startup_timeout` | `float` | `10.0` | Seconds to wait for the `initialize` handshake |

**Example**

```python
from lauren_mcp import McpServer

client = McpServer.stdio(
    ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
    max_retries=0,   # disable retries in tests
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
    **feature_kwargs,
) -> McpClientProtocol:
```

Create an MCP client that connects over WebSocket.

Requires: `pip install "lauren-mcp[ws]"`

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
    **feature_kwargs,
) -> McpClientProtocol:
```

Create an MCP client using the legacy HTTP+SSE transport (MCP 2024-11-05).
HTTP POST for client→server messages; SSE stream for server→client messages.

Requires: `pip install "lauren-mcp[http]"`

For servers speaking the 2025-03-26 Streamable HTTP transport use
[`McpServer.streamable_http`](#mcpserverstreamable_http) instead.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `url` | `str` | required | Base URL of the SSE endpoint (`http://` or `https://`) |
| `headers` | `dict[str, str] \| None` | `None` | Extra HTTP headers for every request |
| `max_retries` | `int` | `3` | Reconnect attempts after SSE stream closes unexpectedly |
| `startup_timeout` | `float` | `10.0` | Seconds to wait for the `initialize` handshake |

---

### `McpServer.streamable_http`

```python
@staticmethod
def streamable_http(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    max_retries: int = 3,
    startup_timeout: float = 10.0,
    **feature_kwargs,
) -> McpClientProtocol:
```

Create an MCP client using the Streamable HTTP transport (MCP 2025-03-26).

Requires: `pip install "lauren-mcp[http]"`

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `url` | `str` | required | Base URL of the MCP endpoint (`http://` or `https://`) |
| `headers` | `dict[str, str] \| None` | `None` | Extra HTTP headers for every request |
| `max_retries` | `int` | `3` | Reconnect attempts after the connection drops |
| `startup_timeout` | `float` | `10.0` | Seconds to wait for the `initialize` handshake |

**Example**

```python
client = McpServer.streamable_http("http://localhost:8000/mcp")
await client.connect()
tools = await client.list_tools()
```

---

## `McpClientProtocol`

Abstract interface implemented by all transport clients.  All methods are
`async`.

### Connection lifecycle

```python
async def connect() -> None
```
Establish the transport connection and complete the MCP handshake.  Must be
called before any protocol method.

```python
async def close() -> None
```
Tear down the connection gracefully.  Cancels pending in-flight requests and
closes the underlying socket / pipe.

### Properties

```python
@property
protocol_version: str
```
The protocol version negotiated during the handshake.  Raises `RuntimeError`
before `connect()` completes.

### Tools

```python
async def list_tools() -> list[ToolSchema]
```
Retrieve the server's tool catalogue (`tools/list`).

```python
async def call_tool(name: str, arguments: dict | None = None) -> Any
```
Invoke a tool (`tools/call`).  Returns the raw result value from the server.
Raises `McpCallError` on a JSON-RPC error response.

### Resources

```python
async def list_resources() -> list[ResourceSchema]
```
Retrieve the server's resource catalogue (`resources/list`).

```python
async def read_resource(uri: str) -> Any
```
Read a resource by exact URI (`resources/read`).

### Prompts

```python
async def list_prompts() -> list[PromptSchema]
```
Retrieve the server's prompt catalogue (`prompts/list`).

```python
async def get_prompt(name: str, arguments: dict[str, str] | None = None) -> Any
```
Retrieve a rendered prompt (`prompts/get`).

### Utilities

```python
async def ping() -> None
```
Send a `ping` request and await the empty response.  Raises `McpCallError` on
failure.

### Notification handlers

```python
def on_progress(handler: Callable[[dict], None | Awaitable[None]]) -> Callable[[], None]
def on_log(handler: Callable[[dict], None | Awaitable[None]]) -> Callable[[], None]
def on_list_changed(handler: Callable[[str], None | Awaitable[None]]) -> Callable[[], None]
```

Register handlers for server-pushed notifications.  Each method returns a
zero-argument unsubscribe function.

| Method | Notification | Handler argument |
|---|---|---|
| `on_progress` | `notifications/progress` | `dict` with `progressToken`, `progress`, and optional `total` |
| `on_log` | `notifications/message` | `dict` with `level`, `logger`, `data` |
| `on_list_changed` | `notifications/{tools,resources,prompts}/list_changed` | `"tools"` \| `"resources"` \| `"prompts"` |

```python
unsubscribe = client.on_progress(lambda p: print(p["progress"]))
# later:
unsubscribe()
```

### Roots change notification

```python
async def notify_roots_changed() -> None
```
Send `notifications/roots/list_changed` to the server.  Only meaningful when
dynamic roots (a callable) were supplied at construction time.  Raises
`RuntimeError` if `roots` was not configured.

---

### Full example

```python
from lauren_mcp import McpServer

client = McpServer.ws(
    "ws://localhost:8000/mcp/ws",
    log_handler=lambda p: print("[server log]", p),
    list_changed_handler=lambda kind: print(f"{kind} list changed"),
)

await client.connect()
print("protocol:", client.protocol_version)

for tool in await client.list_tools():
    print(tool.name, "—", tool.description)

result = await client.call_tool("search", {"query": "coffee"})
await client.close()
```

---

## `McpCallError`

```python
from lauren_mcp import McpCallError

class McpCallError(Exception):
    code: int
```

Raised when the server returns a JSON-RPC error response.  `code` is the
integer JSON-RPC error code; `str(exc)` is the server's error message.

```python
from lauren_mcp import McpCallError

try:
    result = await client.call_tool("divide", {"a": 1, "b": 0})
except McpCallError as exc:
    print(f"Server error {exc.code}: {exc}")
```

---

## `McpServerConfig`

```python
from dataclasses import dataclass

@dataclass
class McpServerConfig:
    alias: str
    client: McpClientProtocol
```

Pairs an alias string with an MCP client for use with `McpToolBridge` and
`lauren_ai.AgentModule.for_root(mcp_servers=[...])`.

**Fields**

| Field | Type | Description |
|---|---|---|
| `alias` | `str` | Short identifier; tools are namespaced as `alias__tool_name` |
| `client` | `McpClientProtocol` | Client instance from any `McpServer.*` factory |

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

Lifecycle manager for a list of `McpServerConfig` entries.  Connects every
client, populates an optional registry, and disconnects cleanly on teardown.

```python
from lauren_mcp import McpToolBridge, McpServerConfig, McpServer

bridge = McpToolBridge([
    McpServerConfig(alias="alpha", client=McpServer.stdio(["python", "server_a.py"])),
    McpServerConfig(alias="beta",  client=McpServer.stdio(["python", "server_b.py"])),
])

bridge.set_registry(my_registry)   # optional

await bridge.connect_all()
# ... use tools ...
await bridge.disconnect_all()
```

### `set_registry(registry) -> None`

Attach an object with a `register_mcp_server(alias, tools, client)` method.
Called by `connect_all()` once per server after successful connection.

### `connect_all() -> None`

Connect every configured server, fetch tool lists, and invoke
`registry.register_mcp_server(alias, tools, client)` for each one.  Failures
on individual servers are logged at `ERROR` level and do not abort the others.

### `disconnect_all() -> None`

Close every client.  Individual close failures are suppressed.
