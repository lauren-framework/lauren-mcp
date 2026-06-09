# Error Handling

This guide covers the errors you will encounter when building MCP servers and
clients, and how to handle them correctly.

---

## Error types

| Error | When it occurs |
|---|---|
| `asyncio.TimeoutError` | `connect()` exceeds `startup_timeout` |
| `McpCallError` | Server returns a JSON-RPC error response |
| `ConnectionRefusedError` | TCP connection refused (remote transports) |
| `ValueError` | Tool / resource / prompt not found on the server |

---

## 1. Connection timeout

The `startup_timeout` parameter controls how long `connect()` waits for the
`initialize` handshake.  If the server does not respond in time,
`asyncio.TimeoutError` is raised:

```python
from lauren_mcp import McpServer
import asyncio

client = McpServer.stdio(
    ["python", "slow_server.py"],
    startup_timeout=5.0,   # raise TimeoutError after 5 s
)

try:
    await client.connect()
except asyncio.TimeoutError:
    print("Server did not respond in time — is it running?")
```

---

## 2. Tool-call errors

When a tool raises an exception on the server side, the dispatcher wraps it in
a JSON-RPC `INTERNAL_ERROR` response.  The client raises `McpCallError`:

```python
from lauren_mcp._client._stdio import McpCallError

try:
    result = await client.call_tool("divide", {"a": 1, "b": 0})
except McpCallError as exc:
    print(f"Tool failed (code {exc.code}): {exc}")
```

Check `isError` in the result dict for non-exception tool failures (tools that
return error payloads intentionally):

```python
result = await client.call_tool("process", {"data": bad_data})
if result.get("isError"):
    content = result.get("content", [])
    error_text = content[0].get("text", "") if content else ""
    print("Tool reported error:", error_text)
```

---

## 3. Unknown tool / resource / prompt

Calling a name that the server has not registered raises `McpCallError` with
`METHOD_NOT_FOUND` or `INTERNAL_ERROR`:

```python
try:
    await client.call_tool("nonexistent_tool", {})
except McpCallError as exc:
    print("No such tool:", exc)
```

Always call `list_tools()` first when you are unsure what a server exposes:

```python
tools = await client.list_tools()
tool_names = {t.name for t in tools}

if "my_tool" in tool_names:
    result = await client.call_tool("my_tool", {"arg": "value"})
else:
    print("Server does not expose 'my_tool'")
```

---

## 4. Subprocess exit and auto-restart

When the subprocess exits unexpectedly (non-zero exit code, OS kill, etc.) the
stdio client fails all pending futures with `McpCallError` and then
automatically restarts the subprocess up to `max_retries` times:

```python
# Disable auto-restart (raise immediately on subprocess exit)
client = McpServer.stdio(["python", "server.py"], max_retries=0)

# Retry up to 5 times before giving up
client = McpServer.stdio(["python", "server.py"], max_retries=5)
```

---

## 5. Resource not found

`read_resource()` passes the URI to the server.  If no resource matches the
URI template the server raises a `ValueError` which becomes an `INTERNAL_ERROR`
response:

```python
try:
    result = await client.read_resource("/books/9999")
    # Server may return "not found" text instead of raising
    content = result.get("contents", [])
    text = content[0].get("text", "") if content else ""
    if "not found" in text.lower():
        print("Resource does not exist")
    else:
        print(text)
except McpCallError as exc:
    print("Server error reading resource:", exc)
```

---

## 6. Best-practice pattern

Wrap all client calls in try/except at the call site:

```python
from lauren_mcp._client._stdio import McpCallError

async def safe_search(client, query: str) -> list:
    try:
        result = await client.call_tool("search", {"query": query})
    except McpCallError as exc:
        print(f"search failed: {exc}")
        return []
    except asyncio.TimeoutError:
        print("search timed out")
        return []

    content = result.get("content", [])
    if not content or result.get("isError"):
        return []

    import json
    text = content[0].get("text", "[]")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return [{"text": text}]
```

---

## 7. Server-side error responses

On the server, exceptions raised inside `@mcp_tool` methods are caught by the
dispatcher and returned as `INTERNAL_ERROR` responses.  Return a structured
error payload instead for expected failure cases:

```python
from lauren_mcp import mcp_tool

@mcp_tool()
async def divide(self, a: float, b: float) -> float:
    """Divide two numbers.

    Args:
        a: Numerator.
        b: Denominator (must not be zero).
    """
    if b == 0:
        raise ValueError("Division by zero")
    return a / b
```

The client receives a `McpCallError` with `INTERNAL_ERROR (-32603)`.

---

## Next steps

- **[Testing](testing.md)** — test error conditions with mock clients
- **[Multiple servers](multiple-servers.md)** — partial failure handling
