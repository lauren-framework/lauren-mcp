# Your First MCP Server

This guide walks you from nothing to a working, testable MCP server in under
five minutes.  You will write a **BookServer** that exposes three tools, one
resource, and one prompt, then connect a client and call them all.

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

## 3. Add a resource

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

## 4. Add a prompt

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

## 5. Register and run

Pass your server class to `McpServerModule.for_root()`:

```python
from lauren import Lauren
from lauren_mcp import McpServerModule

app = Lauren()
app.include_module(McpServerModule.for_root(BookServer))
```

By default the module mounts a WebSocket endpoint at `/mcp/ws` and an
HTTP+SSE endpoint at `/mcp`.  Clients can connect with either transport.

---

## 6. Connect a client and call your tools

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

## 7. Schema generation

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
| `X \| None` | optional (not required) |

Parameters without a default value are **required** in the schema.
Parameters with a default are **optional**.

```python
@mcp_tool()
async def create_book(
    self,
    title: str,          # required — no default
    author: str,         # required — no default
    year: int = 2025,    # optional — has default
    tags: list[str] | None = None,  # optional — has default
) -> dict:
    """Add a book to the catalogue."""
    ...
```

---

## Next steps

- **[Your First MCP Client](first-client.md)** — connect to any server
- **[Decorators in depth](decorators.md)** — all options for `@mcp_tool`, `@mcp_resource`, `@mcp_prompt`
- **[Testing your server](testing.md)** — unit and integration test patterns
