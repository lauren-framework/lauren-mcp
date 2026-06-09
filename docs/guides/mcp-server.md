# MCP Server Guide

This guide explains how to expose a Lauren service as an MCP server using
`@mcp_server`, `@mcp_tool`, `@mcp_resource`, and `@mcp_prompt`.

---

## Using with Lauren

The standard pattern mounts an MCP server inside a Lauren ASGI application:

```python
from lauren import Lauren, LaurenFactory, module
from lauren_mcp import mcp_server, mcp_tool, McpServerModule

CATALOGUE = [
    {"id": 1, "name": "Widget A", "price": 9.99},
    {"id": 2, "name": "Widget B", "price": 14.99},
]

@mcp_server("/mcp")
class CatalogueServer:
    @mcp_tool()
    async def search(self, query: str) -> list[dict]:
        """Search the catalogue by name.

        Args:
            query: Search terms.
        """
        return [i for i in CATALOGUE if query.lower() in i["name"].lower()]


# Wire into a Lauren @module and create the ASGI app
@module(imports=[McpServerModule.for_root(CatalogueServer)])
class AppModule:
    pass

app = LaurenFactory.create(AppModule)
```

Run with any ASGI server:

```bash
pip install "lauren-mcp[ws]" uvicorn
uvicorn myapp:app --port 8000
```

Clients connect at `ws://localhost:8000/mcp/ws` (WebSocket) or
`http://localhost:8000/mcp` (HTTP + SSE).

---

## `@mcp_server`

The class decorator that registers a class as an MCP server endpoint.

```python
from lauren_mcp import mcp_server

@mcp_server("/mcp")               # WebSocket transport (default)
class MyServer: ...

@mcp_server("/mcp", transport="sse")   # HTTP + SSE only
class MyServer: ...

@mcp_server("/mcp", transport="both")  # Both transports
class MyServer: ...
```

**Signature**

```python
def mcp_server(path: str, *, transport: str = "ws") -> Callable[[type], type]:
```

| Argument | Type | Default | Description |
|---|---|---|---|
| `path` | `str` | required | URL prefix; WebSocket mounts at `{path}/ws` |
| `transport` | `str` | `"ws"` | `"ws"`, `"sse"`, or `"both"` |

The decorator also applies `@injectable(scope=Scope.SINGLETON)` so the class
participates in Lauren's DI container — constructor dependencies are resolved
automatically.

---

## `@mcp_tool`

Marks an `async` method as an MCP tool. The JSON Schema is generated from type
annotations; `Args:` docstring sections supply parameter descriptions.

```python
from lauren_mcp import mcp_tool

@mcp_server("/mcp")
class CatalogueServer:
    @mcp_tool()
    async def add_item(
        self,
        name: str,
        quantity: int = 1,
        tags: list[str] | None = None,
    ) -> dict:
        """Add an item to the catalogue.

        Args:
            name: Human-readable item name.
            quantity: How many units to add (default 1).
            tags: Optional list of string tags.
        """
        item = {"name": name, "quantity": quantity, "tags": tags or []}
        CATALOGUE.append(item)
        return item
```

**Signature**

```python
def mcp_tool(*, name: str | None = None, description: str | None = None)
```

**Schema generation rules**

| Python | JSON Schema |
|---|---|
| `str` | `"string"` |
| `int` | `"integer"` |
| `float` | `"number"` |
| `bool` | `"boolean"` |
| `list[X]` | `{"type": "array"}` |
| `dict` | `{"type": "object"}` |
| `X \| None` or default present | optional (not in `required`) |
| No default | required |

---

## `@mcp_resource`

Exposes a URI-addressable resource. Template variables (`{name}`) are
extracted from the URI path and passed as string keyword arguments.

```python
from lauren_mcp import mcp_resource

@mcp_server("/mcp")
class CatalogueServer:
    @mcp_resource("/items/{item_id}")
    async def item_resource(self, item_id: str) -> str:
        """Return a catalogue item as plain text.

        Args:
            item_id: The item ID extracted from the URI path.
        """
        item = next((i for i in CATALOGUE if str(i["id"]) == item_id), None)
        if item is None:
            return f"Item {item_id} not found."
        return f"{item['name']}: £{item['price']:.2f}"
```

**Signature**

```python
def mcp_resource(
    uri_template: str,
    *,
    name: str | None = None,
    description: str | None = None,
    mime_type: str | None = None,
)
```

URI template variables are **always passed as strings** regardless of how they
are annotated.  Cast inside the method body when you need a different type.

---

## `@mcp_prompt`

Registers a parameterised prompt template.

```python
from lauren_mcp import mcp_prompt

@mcp_server("/mcp")
class CatalogueServer:
    @mcp_prompt()
    async def catalogue_summary(self, focus: str = "all") -> str:
        """Generate a catalogue summarisation prompt.

        Args:
            focus: Which category to focus on (default "all").
        """
        return (
            f"Please summarise the current catalogue, focusing on: {focus}. "
            "Include item counts and any notable trends."
        )
```

Return a plain `str` (wrapped into a single `user` message) or a list of
`{"role": ..., "content": {"type": "text", "text": ...}}` dicts for multi-turn
prompts.

**Signature**

```python
def mcp_prompt(name: str | None = None, *, description: str | None = None)
```

---

## `McpServerModule.for_root()`

Builds a Lauren `@module` that mounts the server in the DI graph.

```python
from lauren_mcp import McpServerModule

module = McpServerModule.for_root(CatalogueServer)

# Override transport
module = McpServerModule.for_root(CatalogueServer, transport="sse")

# Override server metadata sent during handshake
from lauren_mcp._types import Implementation
module = McpServerModule.for_root(
    CatalogueServer,
    server_info=Implementation(name="My Catalogue", version="2.0.0"),
)
```

**Signature**

```python
def for_root(
    server_cls: type,
    *,
    transport: str = "ws",
    server_info: Implementation | None = None,
    capabilities: ServerCapabilities | None = None,
) -> type:
```

| Argument | Type | Default | Description |
|---|---|---|---|
| `server_cls` | `type` | required | Class decorated with `@mcp_server` |
| `transport` | `str` | `"ws"` | `"ws"`, `"sse"`, or `"both"` |
| `server_info` | `Implementation \| None` | `None` | Overrides name/version in handshake |
| `capabilities` | `ServerCapabilities \| None` | `None` | Overrides auto-detected capabilities |

Raises `TypeError` if `server_cls` is not decorated with `@mcp_server`.

---

## Transport endpoints

| Transport | Mounted path |
|---|---|
| WebSocket | `{path}/ws` (e.g. `/mcp/ws`) |
| HTTP + SSE | `{path}` (e.g. `/mcp`) |

---

## Testing your server

The recommended test approach uses a subprocess stdio server (no Lauren app
needed for unit / integration tests):

```python
# tests/test_catalogue.py
import asyncio, json, pytest
from lauren_mcp import McpServer

@pytest.fixture
async def client(catalogue_server_cmd):  # see Testing guide for the fixture
    c = McpServer.stdio(catalogue_server_cmd, startup_timeout=10.0, max_retries=0)
    await c.connect()
    yield c
    await c.close()

async def test_search_returns_results(client):
    result = await client.call_tool("search", {"query": "widget"})
    items = json.loads(result["content"][0]["text"])
    assert len(items) > 0
```

For full Lauren DI integration tests (verifying the module/DI stack), use
`LaurenFactory.create()` + `WsTestClient`:

```python
import asyncio, json, pytest
from lauren import LaurenFactory, module
from lauren.testing import TestClient, WsTestClient
from lauren_mcp import McpServerModule

@pytest.fixture(scope="module")
def app():
    @module(imports=[McpServerModule.for_root(CatalogueServer)])
    class AppModule: pass
    app = LaurenFactory.create(AppModule)
    TestClient(app)           # triggers @post_construct (registers handlers)
    return app

async def test_tools_list(app):
    async with WsTestClient(app).connect("/mcp/ws") as ws:
        await ws.send_json({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26",
                       "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}},
        })
        await ws.receive_json()
        await ws.send_json({"jsonrpc": "2.0", "method": "notifications/initialized"})
        await ws.send_json({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        resp = await asyncio.wait_for(ws.receive_json(), timeout=3.0)
        assert any(t["name"] == "search" for t in resp["result"]["tools"])
```

See the [Testing guide](testing.md) for the full echo server pattern and fixture setup.

---

## Common errors

| Error | Cause | Fix |
|---|---|---|
| `TypeError: … is not an MCP server class` | `McpServerModule.for_root()` called with an un-decorated class | Add `@mcp_server(path)` to the class |
| `Method not found: 'initialize'` | `@post_construct` didn't fire | Call `TestClient(app)` after `LaurenFactory.create()` to trigger hooks |
| `INVALID_REQUEST` on first call | Client sent a request before `notifications/initialized` | Complete the handshake: send `initialize`, receive result, send `notifications/initialized` |
