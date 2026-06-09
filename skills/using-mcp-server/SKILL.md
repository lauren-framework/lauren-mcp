---
skill: using-mcp-server
version: 1.0.0
tags: [mcp, server, decorator, lauren-mcp]
summary: Expose a Lauren service as an MCP server using @mcp_server, @mcp_tool, @mcp_resource, and @mcp_prompt.
---

# Skill: Using MCP Server

## When to use this skill

Use this skill when you need to:
- Expose a Lauren service so that AI clients (Claude, custom agents, etc.) can discover and call its tools
- Add resource or prompt endpoints to an existing Lauren application
- Wire an `@mcp_server` class into the Lauren module system

## Complete example

```python
# app.py
from __future__ import annotations

from lauren import Lauren
from lauren_mcp import mcp_server, mcp_tool, mcp_resource, mcp_prompt, McpServerModule

ITEMS = [
    {"id": "1", "name": "Widget A", "price": 9.99},
    {"id": "2", "name": "Widget B", "price": 19.99},
]


@mcp_server("/mcp", name="Shop Service", version="1.0.0")
class ShopServer:
    """MCP server exposing shop tools, resources, and prompts."""

    # ------------------------------------------------------------------
    # Tools — callable by the AI client
    # ------------------------------------------------------------------

    @mcp_tool()
    async def search(self, query: str, limit: int = 10) -> list[dict]:
        """Search shop items by name.

        Args:
            query: Search terms to match against item names.
            limit: Maximum number of results to return (default 10).
        """
        q = query.lower()
        return [i for i in ITEMS if q in i["name"].lower()][:limit]

    @mcp_tool()
    async def add_item(self, name: str, price: float) -> dict:
        """Add a new item to the shop.

        Args:
            name: Display name for the new item.
            price: Price in USD.
        """
        item = {"id": str(len(ITEMS) + 1), "name": name, "price": price}
        ITEMS.append(item)
        return item

    # ------------------------------------------------------------------
    # Resources — URI-addressable data
    # ------------------------------------------------------------------

    @mcp_resource("shop://items/{item_id}", mime_type="application/json")
    async def get_item_resource(self, item_id: str) -> str:
        """Return an item as a JSON resource.

        Args:
            item_id: The item identifier.
        """
        import json
        item = next((i for i in ITEMS if i["id"] == item_id), None)
        if item is None:
            return json.dumps({"error": f"Item {item_id} not found"})
        return json.dumps(item)

    # ------------------------------------------------------------------
    # Prompts — parameterised prompt templates
    # ------------------------------------------------------------------

    @mcp_prompt()
    async def price_analysis_prompt(self, category: str = "all") -> str:
        """Generate a price analysis prompt for the AI.

        Args:
            category: Product category to focus on (default "all").
        """
        total = sum(i["price"] for i in ITEMS)
        avg = total / len(ITEMS) if ITEMS else 0
        return (
            f"Analyse the pricing of our {category} products. "
            f"We have {len(ITEMS)} items with an average price of ${avg:.2f}. "
            "Suggest pricing adjustments to maximise revenue."
        )


# Wire into the Lauren application
app = Lauren()
app.include(McpServerModule.for_root())

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

## Key points

- `@mcp_server(path)` — registers the class; `path` is the URL prefix.
- `@mcp_tool()` — each async method becomes a callable tool. Type annotations generate
  the JSON Schema automatically. Use Google-style docstrings for per-parameter docs.
- `@mcp_resource(uri)` — URI template variables become keyword arguments.
- `@mcp_prompt()` — async method must return `str`.
- `McpServerModule.for_root()` — call once to mount all `@mcp_server` classes.
- No extra deps needed for the server itself. Clients need `[ws]` or `[http]` extras.

## Transport endpoints

After mounting, the server exposes:

| Endpoint | Transport |
|---|---|
| `GET /mcp/ws` | WebSocket |
| `GET /mcp/sse` | HTTP+SSE (server→client stream) |
| `POST /mcp/sse` | HTTP+SSE (client→server messages) |
