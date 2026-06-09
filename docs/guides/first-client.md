# Your First MCP Client

This guide shows you how to connect to any MCP server, discover what it
offers, and call its tools, resources, and prompts.

---

## 1. Choose a transport

`McpServer` has three factory methods — one per transport.  Pick the one that
matches how your server is hosted:

```python
from lauren_mcp import McpServer

# stdio — spawn a local subprocess (no network required)
client = McpServer.stdio(["python", "my_server.py"])

# WebSocket — connect to a running Lauren app
client = McpServer.ws("ws://localhost:8000/mcp/ws")

# HTTP + SSE — connect to a running Lauren app via SSE
client = McpServer.http("http://localhost:8000/mcp")
```

All three return the same `McpClientProtocol` object and share the same API.
Examples in this guide use stdio because it needs no running server.

---

## 2. Connect and disconnect

Always call `connect()` before making requests and `close()` when done:

```python
import asyncio
from lauren_mcp import McpServer

async def main():
    client = McpServer.stdio(["python", "book_server.py"])
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
```

Each `ToolSchema` has:

| Field | Type | Description |
|---|---|---|
| `name` | `str` | Tool identifier used in `call_tool()` |
| `description` | `str` | Human-readable description |
| `inputSchema` | `dict` | JSON Schema for the arguments |

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

## 7. Ping the server

`ping()` checks that the connection is alive.  It raises an exception if the
server does not respond:

```python
await client.ping()     # succeeds silently
```

---

## 8. Retry on disconnect

By default the stdio client restarts the subprocess up to three times if it
exits unexpectedly.  Adjust with `max_retries`:

```python
# Never retry (fail immediately on subprocess exit)
client = McpServer.stdio(["python", "server.py"], max_retries=0)

# Retry up to 5 times
client = McpServer.stdio(["python", "server.py"], max_retries=5)
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
client = McpServer.http(
    "https://api.example.com/mcp",
    headers={"X-Api-Key": "sk-..."},
)
```

---

## Full example

```python
import asyncio, json
from lauren_mcp import McpServer

async def main():
    client = McpServer.stdio(["python", "book_server.py"])
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
