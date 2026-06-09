---
skill: using-mcp-client
version: 2.0.0
tags: [mcp, client, transport, stdio, websocket, http, sse, lauren-mcp]
summary: Connect to a remote MCP server over stdio, WebSocket, or HTTP+SSE and call its tools.
---

# Skill: Using MCP Client

## When to use this skill

Use this skill when you need to:
- Connect to an external MCP server from within a Lauren application
- Call MCP tools, read resources, or retrieve prompts from a remote server
- Choose the right transport for your deployment

## Transport 1: stdio (no extra deps)

Best for local subprocesses. No install extras required.

```python
import asyncio, json
from lauren_mcp import McpServer, McpCallError

async def main():
    client = McpServer.stdio(
        ["python", "-m", "my_mcp_server"],
        max_retries=3,           # restart subprocess on unexpected exit
        startup_timeout=10.0,    # seconds to wait for initialize handshake
    )
    await client.connect()

    # Discover tools
    tools = await client.list_tools()
    print([t.name for t in tools])         # list[ToolSchema]

    # Call a tool — returns raw dict
    result = await client.call_tool("search", {"query": "coffee"})
    content = result.get("content", [])
    if content and content[0].get("type") == "text":
        print(content[0]["text"])

    # dict/list results are JSON-encoded in text
    items = json.loads(content[0]["text"])

    # Read a resource — returns raw dict
    res = await client.read_resource("/items/42")
    print(res.get("contents", [{}])[0].get("text", ""))

    # Get a prompt — returns raw dict
    prompt_result = await client.get_prompt("summary", {"topic": "sales"})
    messages = prompt_result.get("messages", [])
    print(messages[0].get("content", {}).get("text", ""))

    await client.close()

asyncio.run(main())
```

## Transport 2: WebSocket (`[ws]` extra)

```bash
pip install "lauren-mcp[ws]"
```

```python
from lauren_mcp import McpServer

client = McpServer.ws(
    "wss://api.example.com/mcp/ws",
    headers={"Authorization": "Bearer my-token"},
    max_retries=3,
    startup_timeout=10.0,
)
await client.connect()
result = await client.call_tool("search", {"query": "widget"})
await client.close()
```

## Transport 3: HTTP + SSE (`[http]` extra)

```bash
pip install "lauren-mcp[http]"
```

```python
from lauren_mcp import McpServer

client = McpServer.http(
    "https://api.example.com/mcp",
    headers={"X-Api-Key": "secret"},
    max_retries=3,
    startup_timeout=10.0,
)
await client.connect()
tools = await client.list_tools()
await client.close()
```

## Connection lifecycle

```python
client = McpServer.stdio([...])
await client.connect()    # runs initialize handshake
# ... make requests ...
await client.close()      # graceful shutdown
```

There is **no** async context manager (`async with client:`) — always call
`connect()` and `close()` explicitly.

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

## Checking available tools before calling

```python
tools = await client.list_tools()
available = {t.name for t in tools}
if "search" in available:
    result = await client.call_tool("search", {"query": "test"})
```

## pytest fixture

```python
import pytest
from lauren_mcp import McpServer

@pytest.fixture
async def mcp_client(echo_server_command):   # echo_server_command from conftest
    c = McpServer.stdio(echo_server_command, max_retries=0, startup_timeout=10.0)
    await c.connect()
    yield c
    await c.close()
```
