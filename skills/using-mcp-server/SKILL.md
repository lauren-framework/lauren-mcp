---
skill: using-mcp-server
version: 2.0.0
tags: [mcp, server, decorator, lauren, lauren-mcp]
summary: Expose a Lauren service as an MCP server using @mcp_server, @mcp_tool, @mcp_resource, and @mcp_prompt.
---

# Skill: Using MCP Server

## When to use this skill

Use this skill when you need to:
- Expose a Lauren service so that AI clients can discover and call its tools
- Add resource or prompt endpoints to an existing Lauren application
- Wire an `@mcp_server` class into a Lauren app with `McpServerModule.for_root()`

## Complete example

```python
# app.py
from __future__ import annotations

from lauren import LaurenFactory, module
from lauren_mcp import mcp_server, mcp_tool, mcp_resource, mcp_prompt, McpServerModule

ITEMS = [
    {"id": 1, "name": "Widget A", "price": 9.99},
    {"id": 2, "name": "Widget B", "price": 19.99},
]


@mcp_server("/mcp")          # transport="ws" by default; use "sse" or "both"
class ShopServer:

    @mcp_tool()
    async def search(self, query: str, limit: int = 10) -> list[dict]:
        """Search shop items by name.

        Args:
            query: Search terms to match against item names.
            limit: Maximum number of results (default 10).
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
        item = {"id": len(ITEMS) + 1, "name": name, "price": price}
        ITEMS.append(item)
        return item

    @mcp_resource("/items/{item_id}", mime_type="application/json")
    async def get_item_resource(self, item_id: str) -> str:
        """Return an item as a JSON resource.

        Args:
            item_id: The item identifier (extracted from URI path as str).
        """
        import json
        item = next((i for i in ITEMS if i["id"] == int(item_id)), None)
        if item is None:
            return json.dumps({"error": f"Item {item_id} not found"})
        return json.dumps(item)

    @mcp_prompt()
    async def price_analysis_prompt(self, category: str = "all") -> str:
        """Generate a price analysis prompt.

        Args:
            category: Product category to focus on (default "all").
        """
        avg = sum(i["price"] for i in ITEMS) / len(ITEMS) if ITEMS else 0
        return (
            f"Analyse the pricing of our {category} products. "
            f"We have {len(ITEMS)} items with an average price of ${avg:.2f}. "
            "Suggest pricing adjustments to maximise revenue."
        )


# Wire into a Lauren @module and create the ASGI app
@module(imports=[McpServerModule.for_root(ShopServer)])
class AppModule:
    pass

app = LaurenFactory.create(AppModule)
```

Run with uvicorn:

```bash
pip install "lauren-mcp[ws]" uvicorn
uvicorn app:app --port 8000
```

## Key points

- `@mcp_server(path, *, transport="ws")` — registers the class; `path` is the URL
  prefix.  `transport` is `"ws"` (default), `"sse"`, or `"both"`.
- `@mcp_tool()` — each async method becomes a callable tool.  Type annotations generate
  the JSON Schema.  Use Google-style `Args:` docstrings for per-parameter descriptions.
  Parameters without defaults are **required**; parameters with defaults are **optional**.
- `@mcp_resource(uri_template)` — URI template variables (e.g. `{item_id}`) are
  extracted and passed as **strings** regardless of annotation; cast inside the method.
- `@mcp_prompt()` — returns a `str` (wrapped into a single `user` message) or
  `list[dict]` for multi-turn prompts.
- `McpServerModule.for_root(server_cls, *, transport="ws")` — builds a Lauren `@module`.
  Pass it to `@module(imports=[...])`.
- Call `TestClient(app)` after `LaurenFactory.create(app)` to trigger `@post_construct`
  hooks that register handlers.

## Transport endpoints

For `@mcp_server("/mcp")`:

| Transport | Endpoint |
|---|---|
| WebSocket (`"ws"`) | `ws://host/mcp/ws` |
| HTTP+SSE (`"sse"`) | `http://host/mcp/` (POST) + `http://host/mcp/sse` (GET SSE stream) |

## Testing with Lauren's WsTestClient

```python
import asyncio, json
from lauren import LaurenFactory, module
from lauren.testing import TestClient, WsTestClient
from lauren_mcp import McpServerModule

@module(imports=[McpServerModule.for_root(ShopServer)])
class AppModule: pass

app = LaurenFactory.create(AppModule)
TestClient(app)   # triggers @post_construct (registers handlers)

async def test_search():
    async with WsTestClient(app).connect("/mcp/ws") as ws:
        await ws.send_json({"jsonrpc":"2.0","id":1,"method":"initialize",
                            "params":{"protocolVersion":"2025-03-26","capabilities":{},
                                      "clientInfo":{"name":"t","version":"1"}}})
        await asyncio.wait_for(ws.receive_json(), timeout=3.0)
        await ws.send_json({"jsonrpc":"2.0","method":"notifications/initialized"})
        await ws.send_json({"jsonrpc":"2.0","id":2,"method":"tools/call",
                            "params":{"name":"search","arguments":{"query":"widget"}}})
        resp = await asyncio.wait_for(ws.receive_json(), timeout=3.0)
        items = json.loads(resp["result"]["content"][0]["text"])
        assert len(items) > 0
