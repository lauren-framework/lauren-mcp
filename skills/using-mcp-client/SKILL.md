---
skill: using-mcp-client
version: 3.0.0
tags: [mcp, client, transport, stdio, websocket, http, sse, streamable, oauth, roots, sampling, elicitation, lauren-mcp]
summary: Connect to a remote MCP server over stdio, WebSocket, HTTP+SSE, or Streamable HTTP and call its tools.
---

# Skill: Using MCP Client

## When to use this skill

Use this skill when you need to:
- Connect to an external MCP server from within a Lauren application
- Call MCP tools, read resources, retrieve prompts, or subscribe to resource updates
- Choose the right transport for your deployment
- Handle progress/log/list-changed notifications from the server
- Use OAuth 2.0 client-credentials auth on HTTP transports

## Transport overview

| Factory | Protocol | Install extra |
|---|---|---|
| `McpServer.stdio(cmd)` | JSON-RPC over stdin/stdout | none |
| `McpServer.ws(url)` | WebSocket | `lauren-mcp[ws]` |
| `McpServer.streamable_http(url)` | **Recommended** HTTP (MCP 2025-03-26) | `lauren-mcp[sse]` |
| `McpServer.http(url)` | Legacy HTTP+SSE (MCP 2024-11-05) | `lauren-mcp[sse]` |

Use `streamable_http` for new deployments. Use `http` only to connect to older
servers that do not support the 2025-03-26 Streamable HTTP transport.

## Transport 1: stdio (no extra deps)

```python
import asyncio, json
from lauren_mcp import McpServer, McpCallError

async def main():
    client = McpServer.stdio(
        ["python", "-m", "my_mcp_server"],
        max_retries=3,           # restart subprocess on unexpected exit
        startup_timeout=10.0,
    )
    await client.connect()
    print(client.protocol_version)   # e.g. "2025-03-26"

    tools = await client.list_tools()
    print([t.name for t in tools])       # list[ToolSchema]

    result = await client.call_tool("search", {"query": "coffee"})
    content = result.get("content", [])
    if content and content[0].get("type") == "text":
        print(content[0]["text"])
    items = json.loads(content[0]["text"])

    res = await client.read_resource("/items/42")
    print(res.get("contents", [{}])[0].get("text", ""))

    prompt_result = await client.get_prompt("summary", {"topic": "sales"})
    print(prompt_result.get("messages", [{}])[0].get("content", {}).get("text", ""))

    await client.close()

asyncio.run(main())
```

## Transport 2: Streamable HTTP (recommended for remote servers)

```bash
pip install "lauren-mcp[sse]"
```

```python
from lauren_mcp import McpServer

client = McpServer.streamable_http(
    "https://api.example.com/mcp",
    headers={"X-Api-Key": "secret"},
    max_retries=3,
    startup_timeout=10.0,
)
await client.connect()
tools = await client.list_tools()
await client.close()
```

## Transport 3: WebSocket

```bash
pip install "lauren-mcp[ws]"
```

```python
from lauren_mcp import McpServer

client = McpServer.ws(
    "wss://api.example.com/mcp/ws",
    headers={"Authorization": "Bearer my-token"},
)
await client.connect()
result = await client.call_tool("search", {"query": "widget"})
await client.close()
```

## Transport 4: Legacy HTTP+SSE

```python
from lauren_mcp import McpServer

client = McpServer.http(
    "https://api.example.com/mcp",
    headers={"X-Api-Key": "secret"},
)
await client.connect()
tools = await client.list_tools()
await client.close()
```

## Connection lifecycle

```python
client = McpServer.stdio([...])
await client.connect()        # runs initialize handshake
# ... make requests ...
await client.close()          # graceful shutdown
```

There is **no** async context manager (`async with client:`) — always call
`connect()` and `close()` explicitly.

## Protocol version

After `connect()`, `client.protocol_version` holds the negotiated version
string (e.g. `"2025-03-26"` or `"2025-11-25"`). Accessing it before
`connect()` raises `RuntimeError`.

```python
await client.connect()
print(client.protocol_version)   # "2025-03-26"
```

To request a specific version pass `protocol_version=` to the factory:

```python
client = McpServer.streamable_http(url, protocol_version="2025-03-26")
```

## Notification handlers (constructor kwargs or dynamic `on_*()`)

```python
# Via constructor
client = McpServer.streamable_http(
    url,
    progress_handler=lambda params: print("progress:", params),
    log_handler=lambda params: print(params["data"]["message"]),
    list_changed_handler=lambda kind: print(f"{kind} list changed"),
    resource_updated_handler=lambda uri: print(f"resource updated: {uri}"),
)

# Or register dynamically after construction (returns unsubscribe callable)
unsub = client.on_log(lambda params: print("log:", params))
unsub()  # remove handler
```

Handler signatures:
- `progress_handler(params: dict)` — called on `notifications/progress`
- `log_handler(params: dict)` — called on `notifications/message`
- `list_changed_handler(kind: str)` — `kind` is `"tools"`, `"resources"`, or `"prompts"`
- `resource_updated_handler(uri: str)` — called when a subscribed resource changes

## Resource subscriptions

```python
# Subscribe to change notifications
await client.subscribe_resource("file:///workspace/config.json")

# Register handler for updates (also set as constructor kwarg)
client.on_resource_updated(lambda uri: print(f"Resource changed: {uri}"))

# Unsubscribe
await client.unsubscribe_resource("file:///workspace/config.json")
```

## Adjust server log level at runtime

```python
await client.set_logging_level("warning")
# levels: "debug", "info", "notice", "warning", "error", "critical", "alert", "emergency"
```

## Argument autocompletion

```python
result = await client.complete(
    {"type": "ref/prompt", "name": "price_analysis_prompt"},
    {"name": "category", "value": "ele"},
)
print(result)  # {"completion": {"values": ["electronics"], "hasMore": False}}
```

## Roots

Advertise the client's workspace roots to the server. Pass a static list or
a callable returning the current roots:

```python
from lauren_mcp import McpServer, Root

client = McpServer.ws(
    url,
    roots=[Root(uri="file:///workspace", name="Workspace")],
)
await client.connect()

# Notify the server that roots changed (for dynamic root providers)
await client.notify_roots_changed()
```

## Sampling handler (server asks client to call an LLM)

```python
async def my_sampling_handler(params: dict) -> dict:
    # params contains messages, maxTokens, systemPrompt, etc.
    # Call your LLM here and return a CreateMessageResult-shaped dict
    return {
        "role": "assistant",
        "content": {"type": "text", "text": "LLM response here"},
        "model": "claude-opus-4-8",
        "stopReason": "end_turn",
    }

client = McpServer.streamable_http(
    url,
    sampling_handler=my_sampling_handler,
    sampling_tools=True,   # advertise tool-use sampling support
)
```

## Elicitation handler (server asks client to prompt its user)

```python
async def my_elicitation_handler(params: dict) -> dict:
    print("Server says:", params.get("message"))
    # Optionally read params["requestedSchema"] to show a form
    # Return {"action": "accept", "content": {...}} or {"action": "cancel"}
    return {"action": "accept", "content": {"value": "user input here"}}

client = McpServer.streamable_http(url, elicitation_handler=my_elicitation_handler)
```

## OAuth 2.0 (client-credentials flow)

Requires `lauren-mcp[sse]`:

```python
from lauren_mcp import McpServer
from lauren_mcp._client._oauth import ClientCredentialsProvider

auth = ClientCredentialsProvider(
    token_endpoint="https://auth.example.com/oauth/token",
    client_id="my-service",
    client_secret="s3cr3t",
    scopes=["mcp.read", "mcp.write"],
    # extra_params={"audience": "https://api.example.com"},  # e.g. for Auth0
)
client = McpServer.streamable_http("https://api.example.com/mcp", auth=auth)
await client.connect()
```

`ClientCredentialsProvider` is an `httpx.AsyncAuth`-compatible provider that
caches the token in-memory, refreshes on expiry, and retries once on `401`.

## Error handling

```python
from lauren_mcp import McpServer, McpCallError
import asyncio

client = McpServer.stdio(["python", "server.py"], max_retries=0)
try:
    await asyncio.wait_for(client.connect(), timeout=10.0)
except asyncio.TimeoutError:
    print("Server did not respond in time")
    return

try:
    result = await client.call_tool("risky_tool", {"input": "data"})
    if result.get("isError"):
        print("Tool reported an error:", result["content"])
except McpCallError as exc:
    print(f"Server error (code {exc.code}): {exc}")
finally:
    await client.close()
```

## pytest fixture

```python
import pytest
from lauren_mcp import McpServer

@pytest.fixture
async def mcp_client(echo_server_command):
    c = McpServer.stdio(echo_server_command, max_retries=0, startup_timeout=10.0)
    await c.connect()
    yield c
    await c.close()
```

Always set `max_retries=0` in test fixtures to prevent 30-second retry hangs
when the subprocess crashes.
