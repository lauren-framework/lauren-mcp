# Error Handling

This guide covers every error type you will encounter when building MCP servers
and clients with `lauren-mcp`, and how to handle each one correctly.

---

## Error types at a glance

| Error | Package | When it occurs |
|---|---|---|
| `McpCallError` | `lauren_mcp` | Server returns a JSON-RPC error response |
| `asyncio.TimeoutError` | stdlib | `connect()` exceeds `startup_timeout` |
| `asyncio.TimeoutError` | stdlib | `@mcp_tool(timeout=...)` deadline exceeded (wrapped as internal error) |
| `ConnectionRefusedError` | stdlib | TCP connection refused (remote transports) |
| `McpSamplingNotAvailable` | `lauren_mcp` | `ctx.sample()` called when client lacks `sampling` capability |
| `McpElicitationNotAvailable` | `lauren_mcp` | `ctx.elicit()` called when client lacks `elicitation` capability |
| `McpToolNameCollision` | `lauren_mcp` | Two composition sources register the same prefixed tool name |
| `ValueError` | stdlib | `output_schema` validation fails; resource/prompt not found |

---

## 1. Connection timeout

The `startup_timeout` parameter controls how long `connect()` waits for the
`initialize` handshake. If the server does not respond in time,
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

## 2. Tool-call errors (`McpCallError`)

When a tool raises an unhandled exception on the server side, the dispatcher
wraps it in a JSON-RPC `INTERNAL_ERROR` response. The client raises `McpCallError`:

```python
from lauren_mcp import McpCallError

try:
    result = await client.call_tool("divide", {"a": 1, "b": 0})
except McpCallError as exc:
    # exc.code is an McpErrorCode int, e.g. -32603 for INTERNAL_ERROR
    print(f"Tool failed (code {exc.code}): {exc}")
```

For expected failure cases — where the tool wants to communicate an error to the
caller without raising — return a payload with `isError: True`:

```python
result = await client.call_tool("process", {"data": bad_data})
if result.get("isError"):
    content = result.get("content", [])
    error_text = content[0].get("text", "") if content else ""
    print("Tool reported error:", error_text)
```

Server-side best practice: raise only for programming errors; use structured
error returns for expected business-logic failures:

```python
from lauren_mcp import mcp_tool, ToolOutput, TextContent

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

---

## 3. Tool timeout

Use `@mcp_tool(timeout=...)` to enforce a per-call deadline in seconds. When the
deadline is exceeded, `asyncio.TimeoutError` is caught by the dispatcher and
returned as an `INTERNAL_ERROR` response with a message containing "timed out":

```python
from lauren_mcp import mcp_tool

@mcp_tool(timeout=10.0)    # fail the call if it takes more than 10 s
async def slow_query(self, q: str) -> list:
    """Run a potentially slow database query."""
    return await db.query(q)
```

On the client side this arrives as a regular `McpCallError`:

```python
try:
    result = await client.call_tool("slow_query", {"q": "complex query"})
except McpCallError as exc:
    if "timed out" in str(exc):
        print("Query took too long — try a simpler query")
```

---

## 4. Output schema validation errors

When `@mcp_tool(output_schema=...)` is declared, the dispatcher validates the
tool's return value against the schema before sending the response. A validation
failure raises `ValueError` which is also wrapped as an `INTERNAL_ERROR`:

```python
from lauren_mcp import mcp_tool

schema = {"type": "object", "required": ["count"], "properties": {"count": {"type": "integer"}}}

@mcp_tool(output_schema=schema)
async def stats(self) -> dict:
    """Return statistics."""
    return {"count": 5, "total": 100}   # valid — "count" is present
```

If the tool returns `{"wrong_key": 1}` the client will receive `McpCallError`
with a message indicating the missing required field.

---

## 5. Sampling and elicitation not available

`ctx.sample()` and `ctx.elicit()` require the client to have advertised the
corresponding capability and the transport to support bidirectional
server-to-client requests (WebSocket or Streamable HTTP only).

```python
from lauren_mcp import mcp_tool, McpToolContext, McpSamplingNotAvailable, McpElicitationNotAvailable

@mcp_tool()
async def smart_summarise(self, text: str, ctx: McpToolContext) -> str:
    """Summarise text using the client's LLM."""
    try:
        result = await ctx.sample(f"Summarise: {text}", max_tokens=256)
        return result.text
    except McpSamplingNotAvailable:
        # Fall back to a simpler local summary
        return text[:200] + "..."
```

```python
@mcp_tool()
async def confirm_delete(self, item_id: int, ctx: McpToolContext) -> str:
    """Delete an item after user confirmation."""
    try:
        response = await ctx.elicit(f"Delete item {item_id}? This cannot be undone.")
    except McpElicitationNotAvailable:
        raise ValueError("This tool requires a client that supports elicitation")

    if response.action != "accept":
        return "Cancelled"
    await db.delete(item_id)
    return "Deleted"
```

> **Transport limitations:** Legacy HTTP+SSE (`McpServer.http`) cannot deliver
> server-initiated requests. Both `McpSamplingNotAvailable` and
> `McpElicitationNotAvailable` will always be raised on that transport, even if
> the client supplies a `sampling_handler` or `elicitation_handler`.

---

## 6. Tool name collisions in composition

When you use `McpServerModule.for_root(..., mounts=[...])` to compose multiple
servers, each mounted server's tools are prefixed. If two sources produce the
same prefixed name, `McpToolNameCollision` is raised at startup:

```python
from lauren_mcp import McpToolNameCollision

# This will fail at DI container startup (post_construct) if two sources
# register a tool called "search_items" after prefixing.
try:
    McpServerModule.for_root(
        PrimaryServer,
        mounts=[
            (CatalogServer, "search_"),   # registers "search_items"
            (InventoryServer, "search_"), # also tries to register "search_items"
        ]
    )
except McpToolNameCollision as exc:
    print(f"Name collision: {exc}")
    # Fix: use distinct prefixes like "cat_" and "inv_"
```

---

## 7. Unknown tool, resource, or prompt

Calling a name the server has not registered returns a `McpCallError` with
`METHOD_NOT_FOUND` or `INTERNAL_ERROR` depending on the transport:

```python
try:
    await client.call_tool("nonexistent_tool", {})
except McpCallError as exc:
    print("No such tool:", exc)
```

Guard against this by checking the catalogue first:

```python
tools = await client.list_tools()
tool_names = {t.name for t in tools}

if "my_tool" in tool_names:
    result = await client.call_tool("my_tool", {"arg": "value"})
else:
    print("Server does not expose 'my_tool'")
```

---

## 8. Subprocess exit and auto-restart

When the stdio subprocess exits unexpectedly, pending futures are failed with
`McpCallError` and the client automatically restarts the subprocess up to
`max_retries` times:

```python
# Disable auto-restart — raise immediately on subprocess exit
client = McpServer.stdio(["python", "server.py"], max_retries=0)

# Retry up to 5 times before giving up
client = McpServer.stdio(["python", "server.py"], max_retries=5)
```

---

## 9. Resource not found

`read_resource()` passes the URI to the server. If no resource template matches,
the server raises `ValueError` which becomes an `INTERNAL_ERROR` response. Some
servers may also return a descriptive text payload rather than an error:

```python
try:
    result = await client.read_resource("/books/9999")
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

## 10. Best-practice pattern

Wrap all client calls in try/except at the call site:

```python
import asyncio
import json
from lauren_mcp import McpCallError

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

    text = content[0].get("text", "[]")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return [{"text": text}]
```

---

## Next steps

- **[Testing](testing.md)** — test error conditions with mock clients
- **[Multiple servers](multiple-servers.md)** — partial failure handling with
  composition
