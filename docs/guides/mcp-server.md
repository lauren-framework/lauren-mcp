# MCP Server Guide

This guide covers everything you need to expose a Lauren service as a Model Context
Protocol server.

---

## `@mcp_server`

The `@mcp_server` decorator registers a class as an MCP server mounted at a given URL
path. The class becomes a Lauren route group; every `@mcp_tool`, `@mcp_resource`, and
`@mcp_prompt` method on it is discovered automatically.

```python
from lauren_mcp import mcp_server, mcp_tool

@mcp_server("/mcp")
class MyServer:
    @mcp_tool()
    async def greet(self, name: str) -> str:
        """Greet a person by name.

        Args:
            name: The name of the person to greet.
        """
        return f"Hello, {name}!"
```

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `path` | `str` | required | The URL path prefix for this MCP server |
| `name` | `str \| None` | `None` | Human-readable server name (defaults to class name) |
| `version` | `str` | `"1.0.0"` | Server version reported during handshake |
| `description` | `str \| None` | `None` | Server description reported during handshake |

---

## `@mcp_tool`

Marks an async method as an MCP tool. The parameter schema is derived automatically
from Python type annotations using the same logic as Lauren's built-in request
validation. Docstrings (Google style) supply the human-readable description and
per-parameter descriptions.

```python
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

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `name` | `str \| None` | `None` | Override the tool name (defaults to method name) |
| `description` | `str \| None` | `None` | Override the description (defaults to docstring) |

**Schema generation rules**

- `str`, `int`, `float`, `bool` → JSON Schema primitives
- `list[X]` → `{"type": "array", "items": <X schema>}`
- `dict` / `dict[str, X]` → `{"type": "object"}`
- `X | None` → parameter is optional (not in `required`)
- Parameters with defaults are optional; all others are required

---

## `@mcp_resource`

Exposes a URI-addressable resource. The URI template uses `{variable}` syntax and the
matching variables are passed as keyword arguments.

```python
from lauren_mcp import mcp_resource

@mcp_server("/mcp")
class CatalogueServer:
    @mcp_resource("items://{item_id}")
    async def get_item_resource(self, item_id: str) -> str:
        """Return a catalogue item as a text resource.

        Args:
            item_id: The ID of the item to retrieve.
        """
        item = next((i for i in CATALOGUE if str(i["id"]) == item_id), None)
        if item is None:
            return f"Item {item_id} not found."
        return f"Item: {item['name']}, Quantity: {item['quantity']}"
```

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `uri` | `str` | required | URI template (e.g. `"items://{id}"`) |
| `name` | `str \| None` | `None` | Override resource name |
| `description` | `str \| None` | `None` | Override description |
| `mime_type` | `str` | `"text/plain"` | MIME type of the returned content |

---

## `@mcp_prompt`

Registers a parameterised prompt template that AI clients can retrieve and render.

```python
from lauren_mcp import mcp_prompt

@mcp_server("/mcp")
class CatalogueServer:
    @mcp_prompt()
    async def catalogue_summary_prompt(self, focus: str = "all") -> str:
        """Build a prompt asking an AI to summarise the catalogue.

        Args:
            focus: Which part of the catalogue to focus on (default "all").
        """
        return (
            f"Please summarise the current catalogue, focusing on: {focus}. "
            "Include item counts and any notable trends."
        )
```

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `name` | `str \| None` | `None` | Override prompt name |
| `description` | `str \| None` | `None` | Override description |

---

## `McpServerModule.for_root()`

Wire all `@mcp_server` classes into the Lauren application:

```python
from lauren import Lauren
from lauren_mcp import McpServerModule

app = Lauren()
app.include(McpServerModule.for_root())
```

`for_root()` scans all registered `@mcp_server` classes and mounts their WebSocket
and/or SSE handlers at the declared paths.

**Optional keyword arguments**

| Name | Type | Default | Description |
|---|---|---|---|
| `transports` | `list[str]` | `["ws", "sse"]` | Which transports to enable (`"ws"`, `"sse"`, or both) |
| `ping_interval` | `float` | `30.0` | WebSocket keepalive ping interval in seconds |
| `session_timeout` | `float` | `300.0` | Idle SSE session timeout in seconds |

---

## Transport selection

By default `McpServerModule.for_root()` enables both WebSocket and HTTP+SSE. You can
restrict to a single transport:

```python
# WebSocket only
McpServerModule.for_root(transports=["ws"])

# HTTP+SSE only
McpServerModule.for_root(transports=["sse"])
```

The WebSocket handler is mounted at `{path}/ws` and the SSE handler at `{path}/sse`.
The standard MCP path (e.g. `/mcp`) redirects to the appropriate handler based on the
`Upgrade` header.

---

## Dependency injection integration

`@mcp_tool` methods participate in Lauren's DI system. Any parameter that is not part
of the MCP call arguments and is annotated with a type that has a registered provider
will be resolved automatically:

```python
from lauren import Depends

def get_db() -> Database:
    return Database(dsn=settings.DATABASE_URL)

@mcp_server("/mcp")
class SearchServer:
    @mcp_tool()
    async def search(
        self,
        query: str,
        db: Database = Depends(get_db),
    ) -> list[dict]:
        """Search using the injected database connection."""
        return await db.query(query)
```

DI parameters are excluded from the generated JSON Schema — only the parameters that
the AI caller provides appear in `tools/list`.

---

## Testing with McpStdioClient

The fastest way to test an MCP server locally is to run your application as a subprocess
and connect to it with `McpServer.stdio`:

```python
import pytest
from lauren_mcp import McpServer

@pytest.mark.asyncio
async def test_search_tool():
    client = McpServer.stdio(["python", "app.py", "--stdio"])
    async with client:
        result = await client.call_tool("search", {"query": "widget"})
        assert len(result) > 0
        assert all("Widget" in item["name"] for item in result)
```

See the [Testing guide](testing.md) for the full echo server pattern and mocking approach.

---

## Common errors

| Error | Cause | Fix |
|---|---|---|
| `McpHandshakeError` | Client sent wrong protocol version | Ensure the client supports MCP 2024-11-05 or later |
| `ToolNotFoundError` | Tool name mismatch | Check that the method name matches what the client calls; use the `name=` parameter to override |
| `SchemaValidationError` | Argument does not match generated schema | Add type annotations to all tool parameters |
| `ImportError: websockets` | ws extra not installed | `pip install "lauren-mcp[ws]"` |
| `ImportError: httpx` | http extra not installed | `pip install "lauren-mcp[http]"` |
