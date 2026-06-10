# Your First MCP Server

This guide walks you from nothing to a working, testable MCP server in under
five minutes.  You will write a **BookServer** that exposes tools, a resource,
a prompt, a context-aware tool, and a lifespan hook — then deploy it over
WebSocket and Streamable HTTP.

---

## 1. Minimal working server

The smallest possible MCP server has one class decorated with `@mcp_server`
and at least one method decorated with `@mcp_tool`.

```python
# book_server.py
from __future__ import annotations

from lauren import Lauren
from lauren_mcp import mcp_server, mcp_tool, McpServerModule

BOOKS = [
    {"id": 1, "title": "Clean Code", "author": "Martin", "year": 2008},
    {"id": 2, "title": "The Pragmatic Programmer", "author": "Thomas", "year": 1999},
    {"id": 3, "title": "Design Patterns", "author": "GoF", "year": 1994},
]


@mcp_server("/mcp")
class BookServer:
    @mcp_tool()
    async def search(self, query: str) -> list[dict]:
        """Search books by title or author.

        Args:
            query: Search terms matched against title and author.
        """
        q = query.lower()
        return [b for b in BOOKS if q in b["title"].lower() or q in b["author"].lower()]


app = Lauren()
app.include_module(McpServerModule.for_root(BookServer))
```

Run it with uvicorn:

```bash
pip install "lauren-mcp[ws]" uvicorn
uvicorn book_server:app --port 8000
```

---

## 2. Add more tools

Real servers expose multiple tools.  Add `get_book` for direct lookup and
`list_books` to enumerate the full catalogue:

```python
@mcp_server("/mcp")
class BookServer:
    @mcp_tool()
    async def search(self, query: str) -> list[dict]:
        """Search books by title or author.

        Args:
            query: Search terms matched against title and author.
        """
        q = query.lower()
        return [b for b in BOOKS if q in b["title"].lower() or q in b["author"].lower()]

    @mcp_tool()
    async def get_book(self, book_id: int) -> dict | None:
        """Fetch a single book by its numeric ID.

        Args:
            book_id: The book's numeric identifier.
        """
        return next((b for b in BOOKS if b["id"] == book_id), None)

    @mcp_tool()
    async def list_books(self) -> list[dict]:
        """Return the full book catalogue."""
        return BOOKS
```

---

## 3. Inject tool context

Declare a parameter annotated with `McpToolContext` to receive per-call
metadata, report progress, and send log messages back to the client:

```python
from lauren_mcp import McpToolContext, mcp_tool

@mcp_tool()
async def search(self, query: str, ctx: McpToolContext) -> list[dict]:
    """Search books by title or author.

    Args:
        query: Search terms matched against title and author.
    """
    await ctx.info("Starting search", {"query": query})
    await ctx.report_progress(0, total=100)

    q = query.lower()
    results = [b for b in BOOKS if q in b["title"].lower() or q in b["author"].lower()]

    await ctx.report_progress(100, total=100)
    await ctx.info("Search complete", {"hits": len(results)})
    return results
```

The `ctx` parameter is never included in the tool's JSON Schema — it is
injected at call time and invisible to MCP clients.

---

## 4. Add a resource

Resources expose read-only data at stable URIs.  Use `{param}` placeholders
to capture parts of the URI path:

```python
from lauren_mcp import mcp_resource

@mcp_server("/mcp")
class BookServer:
    # ... tools above ...

    @mcp_resource("/books/{book_id}")
    async def book_resource(self, book_id: str) -> str:
        """Expose a book as a readable MCP resource.

        Args:
            book_id: The book's numeric ID extracted from the URI.
        """
        book = next((b for b in BOOKS if b["id"] == int(book_id)), None)
        if book is None:
            return f"Book {book_id} not found."
        return f"{book['title']} by {book['author']} ({book['year']})"
```

---

## 5. Add a prompt

Prompts generate structured LLM messages from arguments:

```python
from lauren_mcp import mcp_prompt

@mcp_server("/mcp")
class BookServer:
    # ... tools and resource above ...

    @mcp_prompt()
    async def book_recommendation(self, topic: str) -> str:
        """Generate a reading-list prompt for a given topic.

        Args:
            topic: The subject area to focus on (e.g. "software design").
        """
        titles = ", ".join(b["title"] for b in BOOKS)
        return (
            f"From this reading list: {titles} — "
            f"recommend the best books about '{topic}' and explain why."
        )
```

---

## 6. Add a lifespan hook

Use `@mcp_lifespan` to run setup and teardown logic around the server's
lifetime.  The dict yielded by the generator is available to every tool as
`ctx.lifespan_context`:

```python
from lauren_mcp import mcp_lifespan

@mcp_server("/mcp")
class BookServer:
    @mcp_lifespan
    async def lifespan(self):
        # Runs once at server startup
        db = await connect_database()
        try:
            yield {"db": db}   # accessible as ctx.lifespan_context["db"]
        finally:
            # Runs at server shutdown
            await db.close()

    @mcp_tool()
    async def search(self, query: str, ctx: McpToolContext) -> list[dict]:
        """Search books via the shared database connection."""
        db = ctx.lifespan_context["db"]
        return await db.search(query)
```

---

## 7. Register and run

Pass your server class to `McpServerModule.for_root()`:

```python
from lauren import Lauren
from lauren_mcp import McpServerModule

app = Lauren()
app.include_module(McpServerModule.for_root(BookServer))
```

By default the module mounts a WebSocket endpoint at `/mcp/ws`.  Use the
`transport` argument to also serve Streamable HTTP or the legacy HTTP+SSE
transport:

=== "WebSocket only (default)"

    ```python
    @mcp_server("/mcp")                   # transport="ws"
    class BookServer: ...
    ```

    | Transport | URL |
    |---|---|
    | WebSocket | `ws://localhost:8000/mcp/ws` |

=== "Streamable HTTP"

    ```python
    @mcp_server("/mcp", transport="streamable")
    class BookServer: ...
    ```

    | Transport | URL |
    |---|---|
    | Streamable HTTP | `http://localhost:8000/mcp` |

=== "All transports"

    ```python
    @mcp_server("/mcp", transport="all")
    class BookServer: ...
    ```

    | Transport | URL |
    |---|---|
    | WebSocket | `ws://localhost:8000/mcp/ws` |
    | Streamable HTTP | `http://localhost:8000/mcp` |
    | HTTP + SSE (legacy) | `http://localhost:8000/mcp` (SSE endpoint) |

---

## 8. Connect a client and call your tools

While the server is running, open a second terminal:

```python
import asyncio
from lauren_mcp import McpServer

async def main():
    client = McpServer.ws("ws://localhost:8000/mcp/ws")
    await client.connect()

    # Discover tools
    tools = await client.list_tools()
    print([t.name for t in tools])
    # → ['search', 'get_book', 'list_books', 'book_recommendation']

    # Call a tool — result dict has "content" and "isError" keys
    result = await client.call_tool("search", {"query": "clean"})
    content = result.get("content", [])
    print(content[0].get("text", ""))   # JSON list of matching books

    # Read a resource
    resource_result = await client.read_resource("/books/1")
    print(resource_result.get("contents", [{}])[0].get("text", ""))

    # Get a prompt
    prompt_result = await client.get_prompt("book_recommendation", {"topic": "design"})
    print(prompt_result.get("messages", [{}])[0].get("content", {}).get("text", ""))

    await client.close()

asyncio.run(main())
```

---

## 9. Schema generation

`@mcp_tool` generates a JSON Schema from type annotations automatically.
Every Python type maps to its JSON Schema equivalent:

| Python type | JSON Schema type |
|---|---|
| `str` | `"string"` |
| `int` | `"integer"` |
| `float` | `"number"` |
| `bool` | `"boolean"` |
| `list[X]` | `"array"` |
| `dict` | `"object"` |
| `Literal["a", "b"]` | `"string"` with `"enum"` |
| `X \| None` | optional (not required) |
| Pydantic `BaseModel` | `"object"` with `$defs` |
| `@dataclass` | `"object"` with `$defs` |

Parameters without a default value are **required** in the schema.
Parameters with a default are **optional**.

```python
from typing import Annotated, Literal
from pydantic import BaseModel, Field

class BookFilter(BaseModel):
    min_year: int = 1900
    max_year: int = 2100

@mcp_tool()
async def create_book(
    self,
    title: str,          # required — no default
    author: str,         # required — no default
    year: int = 2025,    # optional — has default
    tags: list[str] | None = None,   # optional
    mode: Literal["fast", "deep"] = "fast",
    limit: Annotated[int, Field(ge=1, le=50)] = 10,
    filter: BookFilter | None = None,
) -> dict:
    """Add a book to the catalogue."""
    ...
```

---

## 10. Deploying with Lauren

In production, mount your server inside a Lauren ASGI application and serve
it with uvicorn:

```python
# app.py
from lauren import LaurenFactory, module
from lauren_mcp import McpServerModule
# ... BookServer defined above ...

@module(imports=[McpServerModule.for_root(BookServer)])
class AppModule:
    pass

app = LaurenFactory.create(AppModule)
```

```bash
pip install "lauren-mcp[ws]" uvicorn
uvicorn app:app --port 8000
```

For in-process testing (no subprocess, no network), use Lauren's
`WsTestClient`:

```python
import asyncio
from lauren import LaurenFactory, module
from lauren.testing import TestClient, WsTestClient
from lauren_mcp import McpServerModule

@module(imports=[McpServerModule.for_root(BookServer)])
class AppModule: pass

app = LaurenFactory.create(AppModule)
TestClient(app)          # triggers @post_construct (registers handlers)

async def test_via_ws():
    async with WsTestClient(app).connect("/mcp/ws") as ws:
        await ws.send_json({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                            "params": {"protocolVersion": "2025-03-26",
                                       "capabilities": {},
                                       "clientInfo": {"name": "t", "version": "1"}}})
        resp = await asyncio.wait_for(ws.receive_json(), timeout=3.0)
        assert "result" in resp
        await ws.send_json({"jsonrpc": "2.0", "method": "notifications/initialized"})
        await ws.send_json({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        resp = await asyncio.wait_for(ws.receive_json(), timeout=3.0)
        print([t["name"] for t in resp["result"]["tools"]])
```

!!! warning "Always call `TestClient(app)` first"
    `@post_construct` hooks — which register tool handlers — only fire when
    the Lauren DI container starts.  Call `TestClient(app)` after
    `LaurenFactory.create()` to trigger them before connecting via
    `WsTestClient`.

---

## Next steps

- **[Your First MCP Client](first-client.md)** — connect to any server
- **[Decorators in depth](decorators.md)** — all options for `@mcp_tool`, `@mcp_resource`, `@mcp_prompt`, and `@mcp_lifespan`
- **[Testing your server](testing.md)** — unit and integration test patterns
- **[MCP Server guide](mcp-server.md)** — full API reference for the server decorators
