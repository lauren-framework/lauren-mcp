---
skill: using-mcp-server
version: 3.0.0
tags: [mcp, server, decorator, lauren, lifespan, structured-output, composition, lauren-mcp]
summary: Expose a Lauren service as an MCP server using @mcp_server, @mcp_tool, @mcp_resource, @mcp_prompt, and @mcp_lifespan.
---

# Skill: Using MCP Server

## When to use this skill

Use this skill when you need to:
- Expose a Lauren service so that AI clients can discover and call its tools
- Add resource, prompt, or completion endpoints to a Lauren application
- Use lifecycle hooks, context injection, structured output, or server composition
- Wire an `@mcp_server` class into a Lauren app with `McpServerModule.for_root()`

## Core decorator signatures

```python
@mcp_server(path, *, transport="ws")
# transport: "ws" | "sse" | "streamable" | "both" | "all"

@mcp_tool(
    *,
    name=None,           # override method name
    description=None,    # override docstring
    title=None,          # human-readable display name for UIs
    annotations=None,    # ToolAnnotations(readOnlyHint=True, destructiveHint=False, ...)
    timeout=None,        # per-call deadline in seconds (float)
    tags=None,           # frozenset[str] | set[str] — categorical tags
    meta=None,           # dict[str, Any] — opaque metadata forwarded under _meta
    output_schema=None,  # Pydantic model / dataclass / TypedDict / JSON Schema dict
    structured_output=None,  # None=auto, True=force, False=disable
)

@mcp_resource(uri_template, *, name=None, description=None, title=None,
              mime_type=None, annotations=None)
# uri_template supports {param}, {+path} multi-segment, {?page,size} query params

@mcp_prompt(name=None, *, description=None, title=None)

@mcp_lifespan   # method decorator — async generator; yields dict → lifespan_context

@mcp_completion(target, argument, *, ref_type="ref/prompt")
# target: prompt name or resource URI template
# argument: argument name within that target
```

## Complete realistic example

```python
# app.py
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Annotated

from pydantic import BaseModel, Field

from lauren import LaurenFactory, module
from lauren_mcp import (
    McpServerModule,
    McpToolContext,
    ResourceAnnotations,
    ToolAnnotations,
    ToolOutput,
    mcp_completion,
    mcp_lifespan,
    mcp_prompt,
    mcp_resource,
    mcp_server,
    mcp_tool,
)


# --- Pydantic model for structured output ---
class SearchResult(BaseModel):
    id: int
    name: str
    price: float
    score: float


ITEMS = [
    {"id": 1, "name": "Widget A", "price": 9.99},
    {"id": 2, "name": "Widget B", "price": 19.99},
    {"id": 3, "name": "Gadget C", "price": 49.99},
]


@mcp_server("/mcp", transport="all")   # WebSocket + Streamable HTTP
class ShopServer:

    # ------------------------------------------------------------------
    # Lifespan: runs at startup; dict yielded → ctx.lifespan_context
    # ------------------------------------------------------------------

    @mcp_lifespan
    async def lifespan(self):
        db = {"connection": "open"}       # stand-in for a real DB connection
        try:
            yield {"db": db, "boot_ts": asyncio.get_event_loop().time()}
        finally:
            db["connection"] = "closed"   # cleanup on shutdown

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    @mcp_tool(
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
        timeout=30.0,
        tags={"read", "search"},
        output_schema=SearchResult,       # structured output advertised to clients
    )
    async def search(
        self,
        query: str,
        limit: Annotated[int, Field(description="Max results", ge=1, le=100)] = 10,
        ctx: McpToolContext | None = None,
    ) -> list[dict]:
        """Search shop items by name.

        Args:
            query: Search terms to match against item names.
            limit: Maximum number of results (default 10).
        """
        if ctx:
            await ctx.info(f"Searching for {query!r}", {"db": str(ctx.lifespan_context.get("db"))})
        q = query.lower()
        results = [i for i in ITEMS if q in i["name"].lower()][:limit]
        # Report progress while working
        if ctx:
            for i, item in enumerate(results, 1):
                await ctx.report_progress(i, len(results), f"Processing {item['name']}")
        return results

    @mcp_tool(
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True),
        meta={"version": "2", "category": "write"},
    )
    async def add_item(self, name: str, price: float) -> dict:
        """Add a new item to the shop.

        Args:
            name: Display name for the new item.
            price: Price in USD.
        """
        item = {"id": len(ITEMS) + 1, "name": name, "price": price}
        ITEMS.append(item)
        return item

    @mcp_tool(structured_output=True)    # auto-wraps primitives in {"result": ...}
    async def item_count(self) -> int:
        """Return total item count."""
        return len(ITEMS)

    # ------------------------------------------------------------------
    # Resources
    # ------------------------------------------------------------------

    @mcp_resource(
        "/items/{item_id}",
        mime_type="application/json",
        title="Shop Item",
        annotations=ResourceAnnotations(audience=["user", "assistant"]),
    )
    async def get_item_resource(self, item_id: str) -> str:
        """Return an item as a JSON resource.

        Args:
            item_id: The item identifier (always a string from the URI).
        """
        import json
        item = next((i for i in ITEMS if i["id"] == int(item_id)), None)
        if item is None:
            return json.dumps({"error": f"Item {item_id} not found"})
        return json.dumps(item)

    # RFC 6570 multi-segment and query-parameter templates
    @mcp_resource("/files/{+path}", mime_type="text/plain")
    async def get_file(self, path: str) -> str:
        """Read a file by path (multi-segment).

        Args:
            path: Full relative path e.g. docs/readme.txt
        """
        return f"Content of {path}"

    @mcp_resource("/products{?page,size}", mime_type="application/json")
    async def list_products(self, page: int = 1, size: int = 20) -> str:
        """List products with pagination (query params auto-coerced to int).

        Args:
            page: Page number (default 1).
            size: Items per page (default 20).
        """
        import json
        start = (page - 1) * size
        return json.dumps(ITEMS[start:start + size])

    # ------------------------------------------------------------------
    # Prompts
    # ------------------------------------------------------------------

    @mcp_prompt(title="Price Analysis")
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

    # ------------------------------------------------------------------
    # Completion — argument autocompletion for clients that support it
    # ------------------------------------------------------------------

    @mcp_completion("price_analysis_prompt", "category")
    async def complete_category(self, partial: str) -> list[str]:
        categories = ["all", "electronics", "furniture", "clothing"]
        return [c for c in categories if c.startswith(partial.lower())]


# Wire into a Lauren @module and create the ASGI app
@module(imports=[McpServerModule.for_root(ShopServer, log_level="info")])
class AppModule:
    pass

app = LaurenFactory.create(AppModule)
```

Run with uvicorn:

```bash
pip install "lauren-mcp[ws,sse]" uvicorn
uvicorn app:app --port 8000
```

## Transport endpoints

For `@mcp_server("/mcp")` with the listed `transport=` values:

| `transport=` | Endpoints |
|---|---|
| `"ws"` (default) | `ws://host/mcp/ws` |
| `"sse"` | `POST http://host/mcp/` + `GET http://host/mcp/sse` |
| `"streamable"` | `POST/GET/DELETE http://host/mcp/` (MCP 2025-03-26) |
| `"both"` | WebSocket + legacy HTTP+SSE |
| `"all"` | WebSocket + Streamable HTTP |

Note: legacy SSE and Streamable HTTP share `POST /`, so `"both"` (WS + SSE)
and `"all"` (WS + Streamable) are the valid combinations; you cannot mount
both SSE and Streamable on the same path.

## `McpServerModule.for_root()` parameters

```python
McpServerModule.for_root(
    server_cls,
    *,
    transport="ws",
    server_info=None,        # Implementation(name=..., version="1.0.0")
    capabilities=None,       # auto-inferred when None
    providers=None,          # extra Lauren DI providers
    imports=None,            # extra Lauren @module imports
    exports=None,
    log_level="debug",       # min level for ctx.log() → client
    mounts=None,             # [(OtherServerCls, "prefix_"), ...]
    proxies=None,            # [(McpClientProtocol, "prefix_"), ...]
    instrument_otel=None,    # auto-detect OpenTelemetry if installed
)
```

## `@mcp_lifespan`

Decorate one async generator method. The dict it yields becomes
`McpToolContext.lifespan_context` for every tool call. Code after
the `yield` (typically in a `finally`) runs at server shutdown.

```python
@mcp_lifespan
async def lifespan(self):
    session = await make_db_session()
    try:
        yield {"db": session}
    finally:
        await session.close()
```

## Rich schema types in tool signatures

All of the following work as `@mcp_tool` parameter types — `SchemaBuilder`
handles them automatically:

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Annotated, Literal, TypedDict
from pydantic import BaseModel, Field

class Address(BaseModel):
    street: str
    city: str

@dataclass
class Point:
    x: float
    y: float

class Config(TypedDict):
    debug: bool
    retries: int

@mcp_tool()
async def complex_types(
    self,
    address: Address,          # Pydantic model → nested object schema
    point: Point,              # dataclass → object schema
    config: Config,            # TypedDict → object schema
    mode: Literal["fast", "slow"],  # Literal → enum
    count: Annotated[int, Field(description="Must be positive", ge=1)] = 5,
) -> str: ...
```

## Structured output

Two ways to declare a structured output schema:

```python
# 1. Explicit output_schema= (wins over auto-detection)
@mcp_tool(output_schema=SearchResult)   # Pydantic, dataclass, TypedDict, or dict
async def search(self, query: str) -> list[dict]: ...

# 2. Auto-detection from return annotation (structured types only)
@mcp_tool()
async def get_item(self, item_id: int) -> SearchResult: ...  # auto-detected

# 3. Force-wrap primitives
@mcp_tool(structured_output=True)
async def count(self) -> int: ...   # → {"result": <integer>}

# Return ToolOutput explicitly for full control
from lauren_mcp import ToolOutput
@mcp_tool(output_schema=SearchResult)
async def search_v2(self, query: str) -> ToolOutput:
    results = [SearchResult(id=1, name="Widget", price=9.99, score=0.9)]
    return ToolOutput(
        content=[{"type": "text", "text": "Found 1 item"}],
        structured_content=results[0].model_dump(),
    )
```

## Binary / blob resources

```python
from lauren_mcp import BlobResource, ResourceResult

@mcp_resource("/images/{name}", mime_type="image/png")
async def get_image(self, name: str) -> bytes:
    """Return raw bytes → transmitted as a blob resource."""
    return Path(f"images/{name}").read_bytes()

# Or return a ResourceResult for multi-item responses
@mcp_resource("/archive/{name}")
async def get_archive(self, name: str) -> ResourceResult:
    return ResourceResult(contents=[
        BlobResource(uri=f"/archive/{name}", blob="<base64>", mimeType="application/zip"),
    ])
```

## Server composition — `mounts=` and `proxies=`

Expose another `@mcp_server`'s catalog (tools/resources/prompts) through
the primary server with a name prefix:

```python
@mcp_server("/mcp")
class InventoryServer:
    @mcp_tool()
    async def check_stock(self, sku: str) -> int: ...

@module(imports=[
    McpServerModule.for_root(
        ShopServer,
        mounts=[(InventoryServer, "inv_")],            # in-process
        proxies=[(McpServer.streamable_http("http://analytics:8080/mcp"), "stats_")],  # remote
    )
])
class AppModule: pass
```

Colliding names after prefixing raise `McpToolNameCollision` at startup.

## Key points

- `@mcp_tool()` — every async method becomes a callable tool. Type annotations
  generate the JSON Schema. Use Google-style `Args:` docstrings for per-parameter
  descriptions. Parameters without defaults are **required**.
- `McpToolContext` is excluded from the tool's JSON Schema. Declare it as
  `ctx: McpToolContext` (any name) in any position.
- `@mcp_resource(uri_template)` — URI template variables are extracted and
  passed as **strings** unless the method has an explicit type annotation, in
  which case they are coerced (e.g. `item_id: int` receives an `int`).
- `@mcp_prompt()` — returns `str` (single user message) or `list[dict]`
  (multi-turn messages).
- Call `TestClient(app)` after `LaurenFactory.create(app)` to trigger
  `@post_construct` hooks that register handlers before tests run.

## Testing

```python
import asyncio, json
from lauren import LaurenFactory, module
from lauren.testing import TestClient, WsTestClient
from lauren_mcp import McpServerModule

@module(imports=[McpServerModule.for_root(ShopServer)])
class AppModule: pass

app = LaurenFactory.create(AppModule)
TestClient(app)   # REQUIRED: triggers @post_construct

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
```
