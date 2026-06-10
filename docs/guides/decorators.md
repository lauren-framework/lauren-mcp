# Decorators in Depth

Lauren MCP exposes four method-level decorators — `@mcp_tool`, `@mcp_resource`,
`@mcp_prompt`, and `@mcp_lifespan` — and one class-level decorator —
`@mcp_server`.  This guide covers every option each decorator accepts, how
schema generation works, `McpToolContext`, and common patterns.

---

## `@mcp_server`

Marks a class as an MCP server endpoint.  Must appear on the class before any
method decorators.

```python
from lauren_mcp import mcp_server

@mcp_server("/mcp")
class MyServer:
    ...
```

| Argument | Type | Default | Description |
|---|---|---|---|
| `path` | `str` | — | Mount path; WebSocket will be at `{path}/ws` |
| `transport` | `str` | `"ws"` | `"ws"`, `"sse"`, `"streamable"`, `"both"`, or `"all"` |

The decorator also applies `@injectable(scope=Scope.SINGLETON)` so the class
participates in the Lauren DI container — constructor dependencies are resolved
automatically.

=== "WebSocket only (default)"

    ```python
    @mcp_server("/mcp")
    class MyServer: ...
    ```

    Mounts at `ws://host/mcp/ws`.

=== "Streamable HTTP"

    ```python
    @mcp_server("/mcp", transport="streamable")
    class MyServer: ...
    ```

    Mounts the MCP 2025-03-26 Streamable HTTP endpoint at `http://host/mcp`.

=== "Legacy HTTP+SSE"

    ```python
    @mcp_server("/mcp", transport="sse")
    class MyServer: ...
    ```

    Mounts a `GET /mcp/sse` SSE stream and `POST /mcp/` message endpoint.

=== "Both WS and SSE"

    ```python
    @mcp_server("/mcp", transport="both")
    class MyServer: ...
    ```

    Mounts WebSocket and legacy HTTP+SSE together.

=== "All transports"

    ```python
    @mcp_server("/mcp", transport="all")
    class MyServer: ...
    ```

    Mounts WebSocket, Streamable HTTP, and legacy HTTP+SSE together.

---

## `@mcp_tool`

Exposes an `async` method as a callable MCP tool.  The JSON Schema for the
input arguments is generated automatically from type annotations.

### Signature

```python
def mcp_tool(
    *,
    name: str | None = None,
    description: str | None = None,
    annotations: ToolAnnotations | None = None,
    timeout: float | None = None,
    tags: frozenset[str] | set[str] | None = None,
    meta: dict[str, Any] | None = None,
    output_schema: Any = None,
)
```

| Parameter | Description |
|---|---|
| `name` | Override the tool name (defaults to the method name) |
| `description` | Override the description (defaults to the docstring summary) |
| `annotations` | `ToolAnnotations` behavioural hints sent to clients |
| `timeout` | Per-call execution deadline in seconds; exceeding it fails the call |
| `tags` | Categorical tags included in the `tools/list` entry |
| `meta` | Opaque metadata forwarded under `_meta` in `tools/list` |
| `output_schema` | JSON Schema dict, Pydantic model, dataclass, or `TypedDict` describing the structured output |

### Basic usage

```python
from lauren_mcp import mcp_tool

@mcp_tool()
async def greet(self, name: str) -> str:
    """Greet someone by name.

    Args:
        name: The person's name.
    """
    return f"Hello, {name}!"
```

### Override name and description

```python
@mcp_tool(name="catalogue_search", description="Full-text search across all items.")
async def search(self, query: str) -> list[dict]:
    ...
```

### ToolAnnotations

`ToolAnnotations` carries behavioural hints that clients use to decide whether
to confirm an action, cache results, or show a warning:

```python
from lauren_mcp import mcp_tool, ToolAnnotations

@mcp_tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,      # tool does not modify server state
        destructiveHint=False,  # will not delete or overwrite data
        idempotentHint=True,    # repeated calls produce the same result
        openWorldHint=False,    # only reads from the server's own data
    )
)
async def search(self, query: str) -> list[dict]:
    ...
```

| Field | Default | Meaning |
|---|---|---|
| `readOnlyHint` | `False` | Tool does not modify state |
| `destructiveHint` | `True` | Tool may delete or overwrite data |
| `idempotentHint` | `False` | Repeated calls are safe |
| `openWorldHint` | `True` | Tool may access external resources |

Defaults follow the MCP specification's conservative assumptions: a tool is
presumed potentially destructive and open-world unless declared otherwise.

### Timeout

```python
@mcp_tool(timeout=30.0)     # fail after 30 seconds
async def slow_operation(self, data: str) -> str:
    ...
```

### Tags and metadata

```python
@mcp_tool(
    tags={"read", "catalogue"},
    meta={"version": "2.0", "owner": "catalogue-team"},
)
async def search(self, query: str) -> list[dict]:
    ...
```

### Output schema

Declare the structure of the tool's structured output so clients can parse it
programmatically.  Accepts a Pydantic model, a dataclass, a `TypedDict`, or a
raw JSON Schema dict:

```python
from pydantic import BaseModel
from lauren_mcp import mcp_tool

class SearchResult(BaseModel):
    name: str
    score: float
    url: str

@mcp_tool(output_schema=SearchResult)
async def search(self, query: str) -> SearchResult:
    ...
```

The schema is advertised as `outputSchema` in `tools/list` and the result's
`structuredContent` field is populated accordingly.

### All parameters — full example

```python
from lauren_mcp import mcp_tool, ToolAnnotations

@mcp_tool(
    name="search",
    description="Search the catalogue.",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
    timeout=30.0,
    tags={"read", "catalogue"},
    meta={"version": "2.0"},
    output_schema=SearchResult,
)
async def search(self, query: str, limit: int = 10) -> SearchResult:
    ...
```

---

## McpToolContext

Declare a parameter annotated with `McpToolContext` anywhere in the method
signature (after `self`) to receive the per-call context object.  The
parameter is not included in the tool's JSON Schema — it is invisible to MCP
clients.

```python
from lauren_mcp import McpToolContext, mcp_tool

@mcp_tool()
async def search(self, query: str, ctx: McpToolContext) -> list:
    """Search items.

    Args:
        query: Search terms.
    """
    user = ctx.headers.get("x-user-id", "anon")
    await ctx.info("Starting search", {"query": query, "user": user})
    await ctx.report_progress(0, total=100)
    # ... do work ...
    await ctx.report_progress(100, total=100)
    return results
```

### Identity fields

| Field | Type | Description |
|---|---|---|
| `tool_name` | `str` | Name of the current tool |
| `tool_use_id` | `str \| int \| None` | JSON-RPC request ID from the client |
| `session_id` | `str \| None` | Transport session identifier |

### Transport fields

| Field | Type | Description |
|---|---|---|
| `headers` | `dict`-like | HTTP / WebSocket headers from the client connection |
| `execution_context` | `lauren.ExecutionContext \| None` | Lauren request context (DI scope, auth, etc.) |

### Metadata and scratch

| Field | Type | Description |
|---|---|---|
| `metadata` | `dict[str, Any]` | Request-level metadata from the client |
| `state` | `dict[str, Any]` | Mutable per-call scratch space |
| `extras` | `dict[str, Any]` | Extension bag for integrations |
| `lifespan_context` | `dict[str, Any]` | Dict yielded by `@mcp_lifespan` |

### Methods

#### `report_progress(progress, total=None)`

Send a `notifications/progress` notification to the client.  No-op if the
client did not include a `progressToken` in the `tools/call` request.

```python
await ctx.report_progress(0, total=100)
# ... do work ...
await ctx.report_progress(50, total=100)
await ctx.report_progress(100, total=100)
```

#### `log / debug / info / warning / error`

Send a structured `notifications/message` log entry to the client.

```python
await ctx.debug("verbose detail", {"key": "value"})
await ctx.info("Starting operation")
await ctx.warning("Rate limit approaching")
await ctx.error("Operation failed", {"reason": "timeout"})

# Generic form
await ctx.log("info", "message text", {"extra": "data"})
```

#### `sample(messages, *, max_tokens, ...)`

Ask the connected MCP client to run an LLM call on the server's behalf
(requires `sampling` capability).

```python
result = await ctx.sample(
    "Summarise this text: ...",
    max_tokens=512,
    system_prompt="You are a concise summariser.",
)
print(result.text)

# Parse the reply into a Pydantic model
class Summary(BaseModel):
    title: str
    points: list[str]

summary = await ctx.sample(
    messages=[SamplingMessage(role="user", content=TextContent(text="..."))],
    max_tokens=512,
    result_type=Summary,
)
print(summary.title)
```

Raises `McpSamplingNotAvailable` if the client did not advertise sampling
support or the transport cannot carry server-to-client requests.

#### `elicit(message, response_type=None)`

Ask the MCP client to prompt its human user for input (requires `elicitation`
capability).

```python
from lauren_mcp import McpToolContext
from pydantic import BaseModel

class Confirmation(BaseModel):
    confirmed: bool
    reason: str | None = None

result = await ctx.elicit(
    "Are you sure you want to delete all records?",
    response_type=Confirmation,
)
if result.action == "accept":
    data = Confirmation.model_validate(result.content)
    if data.confirmed:
        await do_delete()
elif result.action in ("decline", "cancel"):
    return "Operation cancelled."
```

`response_type` may be `None` (approval-only), a scalar (`str`, `bool`,
`int`, `float`), a `Literal[...]`, an `Enum`, or a flat Pydantic model /
dataclass.  Nested objects and arrays are not permitted by the MCP
specification.

Raises `McpElicitationNotAvailable` if the client did not advertise
elicitation support.

---

## `@mcp_lifespan`

Marks an `async generator` method as the server's lifespan hook.  The
generator runs once at server startup; the dict it yields is available to
every tool as `ctx.lifespan_context`.  Code after the `yield` — typically in
a `finally` block — runs at server shutdown.

```python
from lauren_mcp import mcp_server, mcp_lifespan, mcp_tool, McpToolContext

@mcp_server("/mcp")
class MyServer:
    @mcp_lifespan
    async def lifespan(self):
        db = await connect_database()
        cache = await connect_cache()
        try:
            yield {"db": db, "cache": cache}
        finally:
            await db.close()
            await cache.close()

    @mcp_tool()
    async def search(self, query: str, ctx: McpToolContext) -> list:
        """Search using the shared database connection."""
        db = ctx.lifespan_context["db"]
        return await db.search(query)
```

!!! note
    `@mcp_lifespan` is a bare decorator (no call parentheses):
    `@mcp_lifespan`, not `@mcp_lifespan()`.

!!! warning
    The decorated method must be an async generator — it must contain exactly
    one `yield`.  `@mcp_lifespan` raises `TypeError` on ordinary `async def`
    methods.

---

## `@mcp_resource`

Exposes an `async` method as a readable MCP resource at a given URI template.

### Signature

```python
def mcp_resource(
    uri_template: str,
    *,
    name: str | None = None,
    description: str | None = None,
    mime_type: str | None = None,
)
```

| Parameter | Description |
|---|---|
| `uri_template` | URI template with `{param}` placeholders and optional operators |
| `name` | Resource name (defaults to the method name) |
| `description` | Human-readable description (defaults to docstring) |
| `mime_type` | Optional MIME type hint (e.g. `"text/plain"`, `"application/json"`) |

### Basic usage

```python
from lauren_mcp import mcp_resource

@mcp_resource("/items/{item_id}")
async def item_resource(self, item_id: str) -> str:
    """Return an item's description as plain text.

    Args:
        item_id: Extracted from the URI path.
    """
    item = db.get(item_id)
    return f"{item['name']}: {item['description']}"
```

URI template variables are **always passed as strings** (extracted from the
URI path or query string), regardless of how you annotate them.  Cast inside
the method body:

```python
@mcp_resource("/orders/{order_id}")
async def order_resource(self, order_id: str) -> str:
    order = await db.get_order(int(order_id))   # cast here
    ...
```

### URI template operators

#### Multi-segment path variable `{+param}`

Captures everything after the prefix, including `/` characters:

```python
@mcp_resource("/files/{+path}")
async def file_resource(self, path: str) -> str:
    """Read a file at any depth.

    Args:
        path: Full relative path, e.g. 'docs/api/index.md'.
    """
    # path = "docs/api/index.md" for URI /files/docs/api/index.md
    return read_file(path)
```

#### Query parameters `{?p1,p2}`

A `{?...}` suffix declares optional query parameters:

```python
@mcp_resource("/search/{topic}{?page,size}")
async def search_resource(
    self, topic: str, page: str = "1", size: str = "10"
) -> str:
    """Paginated search resource.

    Args:
        topic: The search topic.
        page: Page number (default 1).
        size: Results per page (default 10).
    """
    # URI: /search/python?page=2&size=20
    return json.dumps(search(topic, int(page), int(size)))
```

### Multiple path segments

```python
@mcp_resource("/catalogue/{category}/{item_id}")
async def item_by_category(self, category: str, item_id: str) -> str:
    ...
```

### MIME type

```python
import json

@mcp_resource("/products/{sku}", mime_type="application/json")
async def product_json(self, sku: str) -> str:
    product = await catalogue.get_product(sku)
    return json.dumps(product)
```

### Binary resources

Return `bytes` directly (the server base64-encodes them automatically) or
return a `BlobResource` to explicitly set the MIME type:

```python
from lauren_mcp import BlobResource

@mcp_resource("/img/{name}", mime_type="image/png")
async def image(self, name: str) -> bytes:
    return read_image(name)

@mcp_resource("/doc/{name}")
async def document(self, name: str) -> BlobResource:
    data = read_file(name)
    return BlobResource(data=data, mime_type="application/pdf")
```

### Not-found handling

Return a descriptive string — the client receives it as the resource content:

```python
@mcp_resource("/items/{item_id}")
async def item_resource(self, item_id: str) -> str:
    item = db.get(item_id)
    if item is None:
        return f"Item '{item_id}' not found."
    return f"{item['name']}: £{item['price']:.2f}"
```

---

## `@mcp_prompt`

Exposes an `async` method as a reusable LLM prompt template.  The method
should return a string or a list of message dicts.

### Signature

```python
def mcp_prompt(name: str | None = None, *, description: str | None = None)
```

| Parameter | Description |
|---|---|
| `name` | Prompt name (defaults to the method name) |
| `description` | Human-readable description (defaults to docstring) |

### Return a plain string

The server wraps a string return value into a single `user` message:

```python
from lauren_mcp import mcp_prompt

@mcp_prompt()
async def summarise(self, topic: str) -> str:
    """Generate a summarisation prompt.

    Args:
        topic: What to summarise.
    """
    return f"Please write a concise summary about: {topic}"
```

Rendered result structure:

```json
{
  "messages": [
    {"role": "user", "content": {"type": "text", "text": "Please write..."}}
  ]
}
```

### Return a message list

For multi-turn prompts return a list of `{"role", "content"}` dicts directly:

```python
@mcp_prompt()
async def code_review(self, language: str, code: str) -> list[dict]:
    """A multi-turn code review prompt.

    Args:
        language: Programming language of the code.
        code: Source code to review.
    """
    return [
        {
            "role": "user",
            "content": {"type": "text", "text": (
                f"Please review this {language} code and list any bugs:\n\n```\n{code}\n```"
            )},
        }
    ]
```

### Optional vs required arguments

Arguments without a default are **required**; those with a default are
**optional** in the prompt's argument list:

```python
@mcp_prompt()
async def email_draft(
    self,
    recipient: str,         # required
    subject: str,           # required
    tone: str = "formal",   # optional
) -> str:
    """Draft a professional email.

    Args:
        recipient: Who the email is addressed to.
        subject: The email subject line.
        tone: Writing tone (default "formal").
    """
    return (
        f"Draft a {tone} email to {recipient} about: {subject}. "
        "Keep it under 200 words."
    )
```

### Override name

```python
@mcp_prompt(name="product_pitch")
async def pitch(self, product: str) -> str:
    ...
```

---

## Rich type annotations in schemas

`@mcp_tool` builds a JSON Schema from all major Python types.  Complex types
generate `$defs` inline in the schema:

```python
import dataclasses
from typing import Literal, Annotated
from pydantic import BaseModel, Field

class SearchResult(BaseModel):
    name: str
    score: float

@dataclasses.dataclass
class Point:
    x: int
    y: int

@mcp_tool()
async def search(
    self,
    query: str,
    mode: Literal["fast", "deep"] = "fast",
    limit: Annotated[int, Field(ge=1, le=50)] = 10,
    location: Point | None = None,
) -> SearchResult:
    ...
```

Supported types:

| Type | JSON Schema |
|---|---|
| `str` | `"string"` |
| `int` | `"integer"` |
| `float` | `"number"` |
| `bool` | `"boolean"` |
| `list[T]` | `"array"` with items schema |
| `dict[K, V]` | `"object"` with `additionalProperties` |
| `tuple[A, B]` | `"array"` with `prefixItems` |
| `set[T]` | `"array"` with `uniqueItems: true` |
| `X \| None` | optional (not in `required`) |
| `Literal["a", "b"]` | `"string"` with `"enum"` |
| `Enum` subclass | `"string"` with `"enum"` from values |
| `Annotated[T, Field(...)]` | schema for `T` merged with Field constraints |
| Pydantic `BaseModel` | `$ref` into `$defs` |
| `msgspec.Struct` | `$ref` into `$defs` |
| `@dataclass` | `$ref` into `$defs` |
| `TypedDict` | `$ref` into `$defs` |
| `UUID` | `"string"` with `"format": "uuid"` |
| `datetime` | `"string"` with `"format": "date-time"` |

### `Annotated` with `Field` constraints

```python
from typing import Annotated
from pydantic import Field

@mcp_tool()
async def paginate(
    self,
    query: str,
    page: Annotated[int, Field(ge=1)] = 1,
    size: Annotated[int, Field(ge=1, le=100, description="Results per page")] = 10,
) -> list[dict]:
    ...
```

---

## Return types — `ToolOutput` and `BlobResource`

### `ToolOutput`

Return `ToolOutput` to control content blocks and structured output
independently:

```python
from lauren_mcp import ToolOutput, TextContent, ImageContent
import base64

@mcp_tool()
async def analyse(self, img_path: str) -> ToolOutput:
    """Analyse an image and return text + structured data."""
    label, confidence = await run_model(img_path)
    image_bytes = open(img_path, "rb").read()
    b64 = base64.b64encode(image_bytes).decode()
    return ToolOutput(
        content=[
            TextContent(text=f"Label: {label} ({confidence:.0%})"),
            ImageContent(data=b64, mimeType="image/jpeg"),
        ],
        structured_content={"label": label, "confidence": confidence},
    )
```

| Field | Type | Description |
|---|---|---|
| `content` | `list[TextContent \| ImageContent \| ...]` | Content blocks shown to the user |
| `structured_content` | `dict[str, Any] \| None` | Machine-readable result |
| `is_error` | `bool` | Whether to mark the result as an error |

### `BlobResource`

Return `BlobResource` from an `@mcp_resource` method to serve binary data
with an explicit MIME type:

```python
from lauren_mcp import BlobResource

@mcp_resource("/export/{name}")
async def export(self, name: str) -> BlobResource:
    data = generate_pdf(name)
    return BlobResource(data=data, mime_type="application/pdf")
```

| Field | Type | Default | Description |
|---|---|---|---|
| `data` | `bytes` | — | Raw binary content |
| `mime_type` | `str` | `"application/octet-stream"` | MIME type for the blob |

---

## Docstring `Args:` section

Place argument descriptions in a Google-style `Args:` section.  The text is
extracted and stored in the tool's parameter descriptions; it also appears in
the JSON Schema `description` fields:

```python
@mcp_tool()
async def translate(self, text: str, target_lang: str = "en") -> str:
    """Translate text to another language.

    Args:
        text: The source text to translate.
        target_lang: BCP-47 language code for the target language.
    """
    ...
```

NumPy and Sphinx docstring styles are also supported.

---

## Putting it all together

A complete server using all decorators:

```python
from __future__ import annotations

import dataclasses
from typing import Annotated, Literal

from pydantic import BaseModel, Field
from lauren import Lauren
from lauren_mcp import (
    BlobResource, McpToolContext, TextContent, ToolAnnotations, ToolOutput,
    mcp_lifespan, mcp_prompt, mcp_resource, mcp_server, mcp_tool,
    McpServerModule,
)

PRODUCTS = [
    {"id": "p1", "name": "Laptop Pro",     "price": 999.00, "category": "electronics"},
    {"id": "p2", "name": "Wireless Mouse", "price":  29.99, "category": "electronics"},
    {"id": "p3", "name": "Notebook",       "price":   4.99, "category": "stationery"},
]


class ProductResult(BaseModel):
    id: str
    name: str
    price: float


@dataclasses.dataclass
class PriceRange:
    min: float = 0.0
    max: float = 9999.0


@mcp_server("/mcp", transport="all")
class ShopServer:

    # ----- lifespan -----

    @mcp_lifespan
    async def lifespan(self):
        catalogue = await build_catalogue(PRODUCTS)
        try:
            yield {"catalogue": catalogue}
        finally:
            await catalogue.close()

    # ----- tools -----

    @mcp_tool(
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
        output_schema=ProductResult,
        tags={"read", "catalogue"},
        timeout=10.0,
    )
    async def search(
        self,
        query: str,
        category: str | None = None,
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
        ctx: McpToolContext | None = None,
    ) -> list[ProductResult]:
        """Search products by name.

        Args:
            query: Search terms matched against the product name.
            category: Optional category filter.
            limit: Maximum number of results to return.
        """
        if ctx:
            await ctx.info("Searching", {"query": query})
        results = [p for p in PRODUCTS if query.lower() in p["name"].lower()]
        if category:
            results = [p for p in results if p["category"] == category]
        return [ProductResult(**p) for p in results[:limit]]

    @mcp_tool()
    async def analyse_price(
        self, product_id: str, range: PriceRange | None = None
    ) -> ToolOutput:
        """Return text + structured pricing data.

        Args:
            product_id: The product identifier.
            range: Optional price range for context.
        """
        p = next((p for p in PRODUCTS if p["id"] == product_id), None)
        if p is None:
            return ToolOutput(
                content=[TextContent(text=f"Product {product_id!r} not found.")],
                is_error=True,
            )
        in_range = range is None or range.min <= p["price"] <= range.max
        return ToolOutput(
            content=[TextContent(text=f"{p['name']}: £{p['price']:.2f}")],
            structured_content={"price": p["price"], "in_range": in_range},
        )

    # ----- resources -----

    @mcp_resource("/products/{product_id}", mime_type="text/plain")
    async def product_card(self, product_id: str) -> str:
        """One-line product card.

        Args:
            product_id: Product identifier extracted from URI.
        """
        p = next((p for p in PRODUCTS if p["id"] == product_id), None)
        if p is None:
            return f"Product {product_id!r} not found."
        return f"{p['name']} — £{p['price']:.2f} ({p['category']})"

    @mcp_resource("/catalogue/export{?format}")
    async def catalogue_export(self, format: str = "json") -> BlobResource:
        """Export the full catalogue as a downloadable file.

        Args:
            format: Output format ('json' or 'csv').
        """
        import json, io
        if format == "csv":
            buf = io.StringIO()
            buf.write("id,name,price,category\n")
            for p in PRODUCTS:
                buf.write(f"{p['id']},{p['name']},{p['price']},{p['category']}\n")
            return BlobResource(data=buf.getvalue().encode(), mime_type="text/csv")
        data = json.dumps(PRODUCTS, indent=2).encode()
        return BlobResource(data=data, mime_type="application/json")

    # ----- prompts -----

    @mcp_prompt()
    async def recommend(
        self,
        budget: str,
        mode: Literal["brief", "detailed"] = "brief",
    ) -> str:
        """Generate a product recommendation prompt.

        Args:
            budget: Customer's maximum budget in GBP.
            mode: Response verbosity.
        """
        affordable = [p for p in PRODUCTS if p["price"] <= float(budget)]
        names = ", ".join(p["name"] for p in affordable) or "none"
        verb = "briefly" if mode == "brief" else "in detail"
        return (
            f"Recommend a product {verb} to a customer with a £{budget} budget. "
            f"Available items: {names}."
        )


app = Lauren()
app.include_module(McpServerModule.for_root(ShopServer))
```

---

---

## Lauren Parameter Injection

`@mcp_tool` and `@mcp_resource` methods can declare Lauren-framework parameters
alongside their normal tool arguments.  These parameters are resolved and
injected by the framework at call time; they are **invisible to MCP clients**
and excluded from the tool's JSON Schema.

See the **[Lauren Parameter Injection guide](tool-lauren-params.md)** for full
examples and transport notes.  Quick-reference table:

| Feature | Lauren type | Schema impact | Use case |
|---|---|---|---|
| Field validation | `QueryField(ge=1)` | Adds constraints to schema | Input validation and client hints |
| Pipe transform | `@pipe()` | None (stripped from schema) | Value transformation and domain validation |
| DI dependency | `Depends[callable]` | Excluded entirely | DB connections, auth tokens, config |
| Header extraction | `Header[T]` | Excluded entirely | User ID, locale, auth headers |
| Request state | `State[T]` | Excluded entirely | Per-call audit logs, accumulators |
| Background tasks | `BackgroundTasks` | Excluded entirely | Fire-and-forget notifications |
| Streaming output | `ToolStream[T]` | Return type only | LLM tokens, incremental progress |

Brief example with all features:

```python
# No 'from __future__ import annotations' when using Depends/Header/State

from typing import Annotated, Optional
from lauren import BackgroundTasks, Depends, Header, QueryField, State
from lauren_mcp import mcp_tool, McpToolContext, ToolStream


async def get_db():
    return await db_pool.acquire()


@mcp_tool()
async def search(
    self,
    query: str,
    limit: Annotated[int, QueryField(ge=1, le=100)] = 10,
    db=Depends[get_db],
    x_user_id: Header[str] = "anonymous",
    bg: BackgroundTasks = None,       # type: ignore[assignment]
    ctx: McpToolContext | None = None,
) -> list:
    """Search items.

    Args:
        query: Search terms.
        limit: Max results (1–100).
    """
    if ctx:
        await ctx.info("searching", {"user": x_user_id})
    results = await db.search(query, limit=limit)
    if bg:
        bg.add_task(log_search, query)
    return results
```

---

## Next steps

- **[Lauren Parameters](tool-lauren-params.md)** — full guide with examples,
  transport tables, and edge cases
- **[Multiple servers](multiple-servers.md)** — tool namespacing across servers
- **[Testing](testing.md)** — test all four decorator types
- **[MCP Server API](mcp-server.md)** — full generated reference
