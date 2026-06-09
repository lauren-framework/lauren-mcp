---
skill: using-mcp-client
version: 1.0.0
tags: [mcp, client, transport, stdio, websocket, http, sse, lauren-mcp]
summary: Connect to a remote MCP server over stdio, WebSocket, or HTTP+SSE.
---

# Skill: Using MCP Client

## When to use this skill

Use this skill when you need to:
- Connect to an external MCP server from within a Lauren application
- Call MCP tools, read resources, or retrieve prompts from a remote server
- Choose the right transport for your deployment (stdio vs WebSocket vs HTTP+SSE)

## Transport 1: stdio (no extra deps)

Best for local subprocesses and scripts. No install extras required.

```python
from lauren_mcp import McpServer

client = McpServer.stdio(
    ["python", "-m", "my_mcp_server"],
    env={"MY_VAR": "value"},
    cwd="/path/to/server",
    timeout=30.0,
)

async with client:
    # List available tools
    tools = await client.list_tools()
    print([t.name for t in tools])

    # Call a tool
    result = await client.call_tool("search", {"query": "coffee"})
    print(result[0].text)

    # Read a resource
    res = await client.read_resource("items://42")
    print(res.contents[0].text)

    # Get a prompt
    prompt = await client.get_prompt("summary", {"topic": "sales"})
    print(prompt.messages[0].content.text)
```

## Transport 2: WebSocket (`[ws]` extra)

Best for persistent bidirectional connections. Install: `pip install "lauren-mcp[ws]"`

```python
from lauren_mcp import McpServer

client = McpServer.ws(
    "wss://api.example.com/mcp/ws",
    headers={"Authorization": "Bearer my-token"},
    ping_interval=20.0,
    reconnect=True,
    reconnect_delay=1.0,
    reconnect_max_delay=30.0,
    timeout=30.0,
)

async with client:
    tools = await client.list_tools()
    result = await client.call_tool("search", {"query": "widget"})
    print(result[0].text)
```

The WebSocket client reconnects automatically by default (`reconnect=True`).

## Transport 3: HTTP + SSE (`[http]` extra)

Best for stateless or browser-friendly deployments. Install: `pip install "lauren-mcp[http]"`

```python
from lauren_mcp import McpServer

client = McpServer.http(
    "https://api.example.com/mcp/sse",
    headers={"X-Api-Key": "secret"},
    timeout=30.0,
    sse_timeout=None,  # no read timeout on the SSE stream
)

async with client:
    tools = await client.list_tools()
    result = await client.call_tool("add", {"a": 3.0, "b": 4.0})
    print(result[0].text)
```

## Common patterns

### Reusable client fixture (pytest)

```python
import pytest
from lauren_mcp import McpServer

@pytest.fixture
async def mcp_client():
    client = McpServer.stdio(["python", "tests/fixtures/echo_server.py"])
    async with client:
        yield client
```

### Checking for available tools before calling

```python
async with client:
    available = {t.name for t in await client.list_tools()}
    if "search" in available:
        result = await client.call_tool("search", {"query": "test"})
```

### Error handling

```python
from lauren_mcp import McpToolError, McpConnectionError

async with client:
    try:
        result = await client.call_tool("risky_tool", {"input": "data"})
    except McpToolError as e:
        print(f"Tool returned an error: {e}")
    except McpConnectionError as e:
        print(f"Lost connection: {e}")
```
