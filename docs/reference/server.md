# Server API Reference

---

## `mcp_server`

```python
def mcp_server(path: str, *, transport: str = "ws") -> Callable[[type], type]:
    ...
```

Class decorator that registers a class as an MCP server endpoint.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `path` | `str` | required | URL path prefix (e.g. `"/mcp"`); WebSocket mounts at `{path}/ws` |
| `transport` | `str` | `"ws"` | `"ws"`, `"sse"`, or `"both"` |

**Returns**: The decorated class with MCP metadata attached and
`@injectable(scope=Scope.SINGLETON)` applied so DI resolves constructor
dependencies automatically.

**Example**

```python
from lauren_mcp import mcp_server, mcp_tool

@mcp_server("/mcp")
class MyService:
    @mcp_tool()
    async def ping(self) -> str:
        """Return pong."""
        return "pong"
```

---

## `mcp_tool`

```python
def mcp_tool(
    *,
    name: str | None = None,
    description: str | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    ...
```

Method decorator that marks an async method as an MCP tool.

The tool's JSON Schema is derived automatically from Python type
annotations.  Docstring `Args:` sections (Google format) supply
per-parameter descriptions.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `name` | `str \| None` | `None` | Override tool name; defaults to the method name |
| `description` | `str \| None` | `None` | Override description; defaults to the docstring |

**Schema generation rules**

| Python annotation | JSON Schema type |
|---|---|
| `str` | `"string"` |
| `int` | `"integer"` |
| `float` | `"number"` |
| `bool` | `"boolean"` |
| `list` / `list[X]` | `"array"` |
| `dict` | `"object"` |
| `X \| None` or param with default | optional (omitted from `required`) |
| No default, not `X \| None` | required |

**Example**

```python
@mcp_tool(name="catalogue_search")
async def search(
    self,
    query: str,
    limit: int = 10,
    tags: list[str] | None = None,
) -> list[dict]:
    """Search the product catalogue.

    Args:
        query: Full-text search query.
        limit: Maximum number of results (default 10).
        tags: Optional tag filter list.
    """
    ...
```

---

## `mcp_resource`

```python
def mcp_resource(
    uri_template: str,
    *,
    name: str | None = None,
    description: str | None = None,
    mime_type: str | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    ...
```

Method decorator that exposes a URI-addressable resource.

URI template variables (e.g. `{item_id}`) are extracted and passed as
string keyword arguments to the decorated method.  URI variables are
**always strings** regardless of annotation — cast inside the method.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `uri_template` | `str` | required | URI template (e.g. `"/items/{item_id}"`) |
| `name` | `str \| None` | `None` | Override resource name; defaults to method name |
| `description` | `str \| None` | `None` | Override description; defaults to docstring |
| `mime_type` | `str \| None` | `None` | MIME type hint (e.g. `"application/json"`) |

**Example**

```python
from lauren_mcp import mcp_resource

@mcp_resource("/orders/{order_id}", mime_type="application/json")
async def get_order(self, order_id: str) -> str:
    """Return an order as a JSON string.

    Args:
        order_id: The order identifier.
    """
    import json
    order = {"id": int(order_id), "status": "open"}
    return json.dumps(order)
```

---

## `mcp_prompt`

```python
def mcp_prompt(
    name: str | None = None,
    *,
    description: str | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    ...
```

Method decorator that exposes a parameterised prompt template.

The method returns either a plain `str` (wrapped into a single `user`
message) or a `list[dict]` of `{"role": ..., "content": {"type": "text",
"text": ...}}` dicts for multi-turn prompts.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `name` | `str \| None` | `None` | Override prompt name; defaults to method name |
| `description` | `str \| None` | `None` | Override description; defaults to docstring |

**Example**

```python
from lauren_mcp import mcp_prompt

@mcp_prompt(name="product_analysis")
async def product_analysis_prompt(
    self,
    category: str,
    tone: str = "professional",
) -> str:
    """Generate a product analysis prompt.

    Args:
        category: Product category to focus on.
        tone: Writing tone (default "professional").
    """
    return (
        f"Analyse the {category} product range in a {tone} tone. "
        "Include: market position, top 3 strengths, top 3 weaknesses, "
        "and a one-paragraph recommendation."
    )
```

---

## `McpServerModule`

```python
class McpServerModule:
    @staticmethod
    def for_root(
        server_cls: type,
        *,
        transport: str = "ws",
        server_info: Implementation | None = None,
        capabilities: ServerCapabilities | None = None,
    ) -> type:
        ...
```

Builds a Lauren `@module` that mounts *server_cls* in the DI graph and
registers all MCP handler coroutines.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `server_cls` | `type` | required | Class decorated with `@mcp_server` |
| `transport` | `str` | `"ws"` | `"ws"`, `"sse"`, or `"both"` |
| `server_info` | `Implementation \| None` | `None` | Override name/version in handshake |
| `capabilities` | `ServerCapabilities \| None` | `None` | Override auto-detected capabilities |

**Raises**: `TypeError` if *server_cls* is not decorated with `@mcp_server`.

**Route mounting**

For a server declared at path `"/mcp"`:

| Transport | Path | Protocol |
|---|---|---|
| `"ws"` (default) | `/mcp/ws` | WebSocket |
| `"sse"` | `/mcp` | HTTP POST + SSE stream |

**Usage with Lauren**

```python
from lauren import LaurenFactory, module
from lauren_mcp import McpServerModule

@module(imports=[McpServerModule.for_root(CatalogueServer)])
class AppModule:
    pass

app = LaurenFactory.create(AppModule)
```

Run with uvicorn:

```bash
pip install "lauren-mcp[ws]" uvicorn
uvicorn myapp:app --port 8000
```

Clients connect at `ws://localhost:8000/mcp/ws`.
