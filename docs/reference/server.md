# Server API Reference

---

## `mcp_server`

```python
def mcp_server(
    path: str,
    *,
    name: str | None = None,
    version: str = "1.0.0",
    description: str | None = None,
) -> Callable[[type], type]:
    ...
```

Class decorator that registers a class as an MCP server mounted at `path`.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `path` | `str` | required | URL path prefix for this server (e.g. `"/mcp"`) |
| `name` | `str \| None` | `None` | Human-readable server name; defaults to the class name |
| `version` | `str` | `"1.0.0"` | Version string reported in the MCP handshake |
| `description` | `str \| None` | `None` | Server description reported in the MCP handshake |

**Returns**: The decorated class, unmodified except for attached MCP metadata.

**Example**

```python
from lauren_mcp import mcp_server, mcp_tool

@mcp_server("/mcp", name="My Service", version="2.0.0")
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
) -> Callable[[Callable], Callable]:
    ...
```

Method decorator that marks an async method as an MCP tool.

The tool's JSON Schema is derived automatically from Python type annotations. Docstring
descriptions (Google format `Args:` section) populate per-parameter descriptions.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `name` | `str \| None` | `None` | Override the tool name; defaults to the method name |
| `description` | `str \| None` | `None` | Override the description; defaults to the method docstring |

**Returns**: The decorated method with attached MCP tool metadata.

**Schema generation rules**

| Python annotation | JSON Schema |
|---|---|
| `str` | `{"type": "string"}` |
| `int` | `{"type": "integer"}` |
| `float` | `{"type": "number"}` |
| `bool` | `{"type": "boolean"}` |
| `list[X]` | `{"type": "array", "items": <X schema>}` |
| `dict` / `dict[str, X]` | `{"type": "object"}` |
| `X \| None` | optional parameter (omitted from `required`) |

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
    uri: str,
    *,
    name: str | None = None,
    description: str | None = None,
    mime_type: str = "text/plain",
) -> Callable[[Callable], Callable]:
    ...
```

Method decorator that exposes a URI-addressable resource.

URI template variables (e.g. `{item_id}`) are extracted and passed as keyword
arguments to the decorated method.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `uri` | `str` | required | URI template string (e.g. `"items://{item_id}"`) |
| `name` | `str \| None` | `None` | Override resource name; defaults to method name |
| `description` | `str \| None` | `None` | Override description; defaults to docstring |
| `mime_type` | `str` | `"text/plain"` | MIME type of the returned content |

**Returns**: The decorated method with attached MCP resource metadata.

**Example**

```python
@mcp_resource("orders://{order_id}", mime_type="application/json")
async def get_order(self, order_id: str) -> str:
    """Return an order as a JSON string.

    Args:
        order_id: The order identifier.
    """
    import json
    order = await db.get_order(order_id)
    return json.dumps(order)
```

---

## `mcp_prompt`

```python
def mcp_prompt(
    *,
    name: str | None = None,
    description: str | None = None,
) -> Callable[[Callable], Callable]:
    ...
```

Method decorator that exposes a parameterised prompt template.

The method must return a `str` (the rendered prompt text). Parameter annotations are
used to build the prompt's argument schema for the `prompts/list` response.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `name` | `str \| None` | `None` | Override prompt name; defaults to method name |
| `description` | `str \| None` | `None` | Override description; defaults to docstring |

**Returns**: The decorated method with attached MCP prompt metadata.

**Example**

```python
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
    @classmethod
    def for_root(
        cls,
        *,
        transports: list[str] = ("ws", "sse"),
        ping_interval: float = 30.0,
        session_timeout: float = 300.0,
    ) -> McpServerModule:
        ...
```

Lauren module that discovers all `@mcp_server`-decorated classes and mounts their
transport handlers.

**`for_root()` parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `transports` | `list[str]` | `["ws", "sse"]` | Which transports to enable: `"ws"`, `"sse"`, or both |
| `ping_interval` | `float` | `30.0` | WebSocket keepalive ping interval in seconds |
| `session_timeout` | `float` | `300.0` | Idle SSE session timeout in seconds |

**Route mounting**

For a server declared at path `/mcp`, `McpServerModule.for_root()` mounts:

| Path | Transport | Description |
|---|---|---|
| `/mcp/ws` | WebSocket | Persistent bidirectional connection |
| `/mcp/sse` | HTTP + SSE | POST for client→server, SSE stream for server→client |
| `/mcp` | — | Redirects to `/mcp/ws` or `/mcp/sse` based on `Upgrade` header |

**Example**

```python
from lauren import Lauren
from lauren_mcp import McpServerModule

app = Lauren()
# Mount with both transports (default)
app.include(McpServerModule.for_root())

# WebSocket only
app.include(McpServerModule.for_root(transports=["ws"]))

# SSE only with custom timeout
app.include(McpServerModule.for_root(transports=["sse"], session_timeout=60.0))
```
