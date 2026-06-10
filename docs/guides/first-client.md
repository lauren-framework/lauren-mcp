# Your First MCP Client

This guide shows you how to connect to any MCP server, discover what it
offers, call its tools, and receive server notifications.

---

## 1. Choose a transport

`McpServer` has four factory methods — one per transport.  Pick the one that
matches how your server is hosted:

```python
from lauren_mcp import McpServer

# stdio — spawn a local subprocess (no network required)
client = McpServer.stdio(["python", "my_server.py"])

# WebSocket — connect to a running Lauren app
client = McpServer.ws("ws://localhost:8000/mcp/ws")

# Streamable HTTP — MCP 2025-03-26 transport (recommended for HTTP)
client = McpServer.streamable_http("http://localhost:8000/mcp")

# HTTP + SSE — legacy 2024-11-05 transport
client = McpServer.http("http://localhost:8000/mcp")
```

All four return the same `McpClientProtocol` object and share the same API.
For new HTTP deployments prefer `streamable_http`; it uses the current MCP
2025-03-26 transport and supports bidirectional server-to-client requests.

---

## 2. Connect and disconnect

Always call `connect()` before making requests and `close()` when done:

```python
import asyncio
from lauren_mcp import McpServer

async def main():
    client = McpServer.streamable_http("http://localhost:8000/mcp")
    await client.connect()      # initialize handshake
    try:
        tools = await client.list_tools()
        print([t.name for t in tools])
    finally:
        await client.close()    # graceful shutdown

asyncio.run(main())
```

---

## 3. Discover tools

`list_tools()` returns a list of `ToolSchema` objects, each describing one
callable the server exposes:

```python
tools = await client.list_tools()

for tool in tools:
    print(f"{tool.name}: {tool.description}")
    print(f"  schema: {tool.inputSchema}")
    if tool.annotations:
        print(f"  read-only: {tool.annotations.get('readOnlyHint')}")
```

Each `ToolSchema` has:

| Field | Type | Description |
|---|---|---|
| `name` | `str` | Tool identifier used in `call_tool()` |
| `description` | `str` | Human-readable description |
| `inputSchema` | `dict` | JSON Schema for the arguments |
| `outputSchema` | `dict \| None` | JSON Schema for structured output, if declared |
| `annotations` | `dict \| None` | Behavioural hints (`readOnlyHint`, etc.) |

---

## 4. Call a tool

`call_tool(name, arguments)` returns a raw dict with `"content"` and
`"isError"` keys.  The content list contains objects with a `"type"` field
(`"text"`, `"image"`, etc.):

```python
result = await client.call_tool("search", {"query": "design"})

# Check for errors
if result.get("isError"):
    print("Tool error:", result)

# Extract the first text item
content = result.get("content", [])
if content and content[0].get("type") == "text":
    text = content[0]["text"]
    print(text)
```

When the tool returns a Python dict or list the server serialises it to JSON
before placing it in the `"text"` field.  Parse it with `json.loads()`:

```python
import json

result = await client.call_tool("list_books", {})
content = result.get("content", [])
books = json.loads(content[0]["text"]) if content else []
for book in books:
    print(book["title"])
```

Tools that declare an `output_schema` also populate `"structuredContent"`:

```python
result = await client.call_tool("analyse_image", {"path": "cat.png"})
structured = result.get("structuredContent", {})
print(structured.get("label"), structured.get("confidence"))
```

---

## 5. Discover and read resources

`list_resources()` returns a list of `ResourceSchema` objects.  Use
`read_resource(uri)` to fetch the content at a specific URI:

```python
resources = await client.list_resources()

for r in resources:
    print(f"{r.name}: {r.uri}")

# Read a specific resource
result = await client.read_resource("/books/1")
contents = result.get("contents", [])
if contents:
    print(contents[0].get("text", ""))
```

URI templates like `/books/{book_id}` are listed exactly as registered.
Substitute values yourself when calling `read_resource`:

```python
book_id = 2
result = await client.read_resource(f"/books/{book_id}")
```

---

## 6. Discover and render prompts

`list_prompts()` lists available prompt templates.  `get_prompt(name,
arguments)` returns the rendered prompt as a messages list:

```python
prompts = await client.list_prompts()
print([p.name for p in prompts])

result = await client.get_prompt(
    "book_recommendation", {"topic": "software architecture"}
)

messages = result.get("messages", [])
for msg in messages:
    role = msg.get("role", "user")
    text = msg.get("content", {}).get("text", "")
    print(f"[{role}] {text}")
```

---

## 7. Notification callbacks

Pass handler functions at construction time to react to server-pushed
notifications.  Handlers can be sync or async:

```python
from lauren_mcp import McpServer

client = McpServer.ws(
    "ws://localhost:8000/mcp/ws",
    progress_handler=lambda p: print(
        f"Progress: {p['progress']}/{p.get('total', '?')}"
    ),
    log_handler=lambda p: print(
        f"[{p['level']}] {p['data']['message']}"
    ),
    list_changed_handler=lambda kind: print(
        f"{kind} catalog changed"          # kind = "tools" | "resources" | "prompts"
    ),
)
await client.connect()
```

The same callbacks are available on `streamable_http` and `http` clients:

```python
async def on_progress(params):
    pct = int(100 * params["progress"] / params.get("total", 1))
    print(f"  {pct}%")

client = McpServer.streamable_http(
    "http://localhost:8000/mcp",
    progress_handler=on_progress,
)
```

You can also register handlers after construction with `on_progress()`,
`on_log()`, and `on_list_changed()`.  Each returns an unsubscribe callable:

```python
unsubscribe = client.on_log(lambda p: print(p))
# later…
unsubscribe()
```

---

## 8. Expose filesystem roots

Pass a `roots` list to advertise which local paths the client is working with:

```python
from lauren_mcp import McpServer, Root

client = McpServer.ws(
    "ws://localhost:8000/mcp/ws",
    roots=[Root("file:///workspace", name="workspace")],
)
```

Pass a callable to supply roots dynamically; call `notify_roots_changed()`
after the list changes:

```python
current_roots = [Root("file:///workspace")]

client = McpServer.ws(
    "ws://localhost:8000/mcp/ws",
    roots=lambda: current_roots,
)
await client.connect()

# Later, when roots change:
current_roots.append(Root("file:///data"))
await client.notify_roots_changed()
```

---

## 9. Authentication headers (remote transports)

Pass HTTP headers for Bearer token or API key auth:

```python
# Bearer token
client = McpServer.ws(
    "wss://api.example.com/mcp/ws",
    headers={"Authorization": "Bearer eyJ..."},
)

# API key
client = McpServer.streamable_http(
    "https://api.example.com/mcp",
    headers={"X-Api-Key": "sk-..."},
)
```

---

## 10. Retry on disconnect

By default clients restart or reconnect up to three times if the connection
drops unexpectedly.  Adjust with `max_retries`:

```python
# Never retry (fail immediately)
client = McpServer.stdio(["python", "server.py"], max_retries=0)

# Retry up to 5 times
client = McpServer.streamable_http("http://localhost:8000/mcp", max_retries=5)
```

---

## 11. Ping the server

`ping()` checks that the connection is alive.  It raises an exception if the
server does not respond:

```python
await client.ping()     # succeeds silently
```

---

## Full example

```python
import asyncio, json
from lauren_mcp import McpServer, Root

async def main():
    client = McpServer.streamable_http(
        "http://localhost:8000/mcp",
        progress_handler=lambda p: print(f"  progress: {p['progress']}"),
        log_handler=lambda p: print(f"  [{p['level']}] {p['data']['message']}"),
        roots=[Root("file:///workspace")],
    )
    await client.connect()

    # 1. List tools
    tools = await client.list_tools()
    print("Tools:", [t.name for t in tools])

    # 2. Call a tool
    res = await client.call_tool("search", {"query": "clean"})
    books = json.loads(res["content"][0]["text"])
    print("Search results:", books)

    # 3. Read a resource
    res = await client.read_resource("/books/1")
    print("Resource:", res["contents"][0]["text"])

    # 4. Get a prompt
    res = await client.get_prompt("book_recommendation", {"topic": "design"})
    print("Prompt:", res["messages"][0]["content"]["text"])

    await client.close()

asyncio.run(main())
```

---

## Next steps

- **[Decorators in depth](decorators.md)** — full decorator reference
- **[Multiple servers](multiple-servers.md)** — connect several MCP servers at once
- **[Testing your server](testing.md)** — test patterns for MCP code
