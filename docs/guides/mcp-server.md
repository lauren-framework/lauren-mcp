# MCP Server Guide

This is the authoritative reference for everything you can do on the server side of
`lauren-mcp`.  It covers the full decorator API, transport configuration, `McpToolContext`,
rich schema types, server composition, the dynamic catalog, OpenAPI import, and Lauren DI
integration.

---

## Quick start

```python
from lauren import LaurenFactory, module
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
            query: Search terms to match against item names.
        """
        return [i for i in CATALOGUE if query.lower() in i["name"].lower()]


@module(imports=[McpServerModule.for_root(CatalogueServer)])
class AppModule:
    pass

app = LaurenFactory.create(AppModule)
```

```bash
pip install "lauren-mcp[ws]" uvicorn
uvicorn myapp:app --port 8000
```

Clients connect at `ws://localhost:8000/mcp/ws` (WebSocket) or
`http://localhost:8000/mcp` (Streamable HTTP / legacy SSE depending on transport).

---

## Server setup

### `@mcp_server`

Marks a class as an MCP server endpoint and enrolls it in Lauren's DI container as a
Singleton.

```python
from lauren_mcp import mcp_server

@mcp_server("/mcp")                        # WebSocket only (default)
class MyServer: ...

@mcp_server("/mcp", transport="sse")       # Legacy HTTP+SSE only
class MyServer: ...

@mcp_server("/mcp", transport="streamable")  # Streamable HTTP only
class MyServer: ...

@mcp_server("/mcp", transport="both")      # WebSocket + legacy SSE
class MyServer: ...

@mcp_server("/mcp", transport="all")       # WebSocket + Streamable HTTP
class MyServer: ...
```

**Signature**

```python
def mcp_server(path: str, *, transport: str = "ws") -> Callable[[type], type]:
```

| Argument | Type | Default | Description |
|---|---|---|---|
| `path` | `str` | required | URL prefix — WebSocket mounts at `{path}/ws`, HTTP endpoints at `{path}` |
| `transport` | `str` | `"ws"` | `"ws"`, `"sse"`, `"streamable"`, `"both"`, or `"all"` |

`@mcp_server` also applies `@injectable(scope=Scope.SINGLETON)` so the constructor
can declare dependencies that Lauren resolves automatically.

### `McpServerModule.for_root()`

Builds a Lauren `@module` that wires the server class into the DI graph, mounts
transport controllers, and handles the full MCP lifecycle.

```python
from lauren import module
from lauren_mcp import McpServerModule
from lauren_mcp._types import Implementation

@module(imports=[McpServerModule.for_root(
    MyServer,
    transport="all",                            # WS + Streamable HTTP
    server_info=Implementation(name="my-server", version="1.0.0"),
    log_level="info",                           # min level for ctx.log() notifications
)])
class AppModule: ...
```

**Full signature**

```python
McpServerModule.for_root(
    server_cls: type,
    *,
    transport: str = "ws",
    server_info: Implementation | None = None,
    capabilities: ServerCapabilities | None = None,
    providers: list[Any] | None = None,
    imports: list[Any] | None = None,
    exports: list[Any] | None = None,
    log_level: str = "debug",
    mounts: list[tuple[type, str]] | None = None,
    proxies: list[tuple[McpClientProtocol, str]] | None = None,
) -> type
```

| Parameter | Default | Description |
|---|---|---|
| `server_cls` | required | Class decorated with `@mcp_server` |
| `transport` | `"ws"` | One of `"ws"`, `"sse"`, `"streamable"`, `"both"`, `"all"` |
| `server_info` | `None` | Overrides the name/version sent in the `initialize` handshake |
| `capabilities` | `None` | Overrides auto-detected capabilities (tools/resources/prompts/logging) |
| `providers` | `None` | Extra Lauren providers to add — use to inject services into `server_cls` |
| `imports` | `None` | Extra `@module` classes to import |
| `exports` | `None` | Extra types to export from the generated module |
| `log_level` | `"debug"` | Minimum severity for client-bound `notifications/message` events |
| `mounts` | `None` | `[(OtherServer, "prefix_"), ...]` — see [Server composition](#server-composition) |
| `proxies` | `None` | `[(client, "prefix_"), ...]` — see [Server composition](#server-composition) |

!!! note
    `server_info` defaults to `Implementation(name=server_cls.__name__, version="1.0.0")`.
    When `capabilities` is `None`, capabilities are inferred: the `tools`, `resources`, and
    `prompts` keys are populated only when the corresponding decorators are present, always
    with `listChanged: True`.  `logging` is always enabled.

### Transport endpoints

| Transport key | Mounted routes |
|---|---|
| `"ws"` | `{path}/ws` (WebSocket) |
| `"sse"` | `{path}/sse` (GET stream) + `{path}/` (POST messages) |
| `"streamable"` | `{path}` (POST + optional GET) |
| `"both"` | WebSocket + legacy SSE |
| `"all"` | WebSocket + Streamable HTTP |

!!! warning
    Legacy SSE and Streamable HTTP both use `POST {path}/` and cannot be mounted
    together on the same path.  Use `"all"` (WS + Streamable) or `"both"` (WS + SSE)
    but not a combination that includes both SSE and Streamable on one server.

---

## `@mcp_tool`

Marks an `async` method as an MCP tool.  JSON Schema is generated from type
annotations; docstring `Args:` sections provide parameter descriptions.

### Basic example

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

### Full parameter reference

```python
from lauren_mcp import mcp_tool, ToolAnnotations

@mcp_tool(
    name="search",                                    # override method name
    description="Search the catalogue",              # override docstring
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    ),
    timeout=30.0,                                    # per-call deadline in seconds
    tags={"read", "catalogue"},                      # categorical tags
    meta={"version": "2"},                           # opaque _meta forwarded to clients
    output_schema=SearchResult,                      # Pydantic/dataclass/TypedDict or dict
)
async def search(self, query: str, limit: int = 10) -> list:
    ...
```

| Parameter | Type | Description |
|---|---|---|
| `name` | `str \| None` | Tool name; defaults to the method name |
| `description` | `str \| None` | Tool description; defaults to the docstring summary |
| `annotations` | `ToolAnnotations \| None` | Behavioural hints sent in `tools/list` |
| `timeout` | `float \| None` | Execution deadline; exceeding it raises `ValueError` with `isError=True` |
| `tags` | `set[str] \| frozenset[str] \| None` | Categorical tags included in `tools/list` (sorted) |
| `meta` | `dict[str, Any] \| None` | Opaque metadata forwarded under `_meta` in `tools/list` |
| `output_schema` | any | Declares `outputSchema` in `tools/list`; also validates structured output |

### `ToolAnnotations`

```python
from lauren_mcp import ToolAnnotations

ToolAnnotations(
    readOnlyHint=False,     # tool does not modify state (default: False)
    destructiveHint=True,   # tool may irreversibly destroy data (default: True)
    idempotentHint=False,   # repeated identical calls have the same effect (default: False)
    openWorldHint=True,     # tool may contact external systems (default: True)
)
```

Defaults follow the MCP specification's conservative assumptions: unknown tools are
presumed destructive and open-world.

### Return value coercion

The handler normalises any return value into the `tools/call` wire format automatically:

| Return type | `content` block | `structuredContent` |
|---|---|---|
| `str` | `{"type": "text", "text": ...}` | absent |
| `dict` | JSON-serialised text block | the dict itself |
| `list` | JSON-serialised text block | `{"result": [...]}` |
| dataclass or Pydantic model | JSON-serialised text block | `model_dump()` / `dataclasses.asdict()` |
| `msgspec.Struct` | JSON-serialised text block | `msgspec.to_builtins()` |
| `ToolOutput` | `content` list as-is | `structured_content` field |
| `TextContent` / `ImageContent` | the content object | absent |

Use `ToolOutput` when you need independent control over what the user sees versus
what an agent loop parses:

```python
from lauren_mcp import ToolOutput
from lauren_mcp._types import TextContent

@mcp_tool()
async def process(self, data: str) -> ToolOutput:
    result = {"status": "ok", "rows": 42}
    return ToolOutput(
        content=[TextContent(text="Processed 42 rows successfully")],
        structured_content=result,
        is_error=False,
    )
```

### `output_schema` validation

When `output_schema` is set, `for_root` advertises `outputSchema` in `tools/list` and
the handler validates required keys before returning.  The schema may be:

- A plain JSON Schema `dict`
- A Pydantic `BaseModel` class — `model_json_schema()` is called automatically
- A `dataclass`, `TypedDict`, or `msgspec.Struct` — the shared schema builder handles it

```python
from pydantic import BaseModel

class SearchResult(BaseModel):
    items: list[str]
    total: int

@mcp_tool(output_schema=SearchResult)
async def search(self, query: str) -> dict:
    ...
```

---

## `McpToolContext`

Injecting `McpToolContext` into a tool method gives access to transport metadata,
progress reporting, structured logging, LLM sampling, and user elicitation.  The
parameter is automatically excluded from the JSON Schema visible to clients.

```python
from lauren_mcp import McpToolContext

@mcp_tool()
async def my_tool(self, data: str, ctx: McpToolContext) -> str:
    ...
```

The parameter name is arbitrary — any name annotated with `McpToolContext` (or
`McpToolContext | None`) is detected and injected.

### Identity

```python
ctx.tool_name      # str  — the registered tool name
ctx.tool_use_id    # str | int | None — the JSON-RPC request id; None outside agent loops
```

### Transport information

```python
ctx.headers            # lauren Headers (case-insensitive) — HTTP headers for SSE/Streamable
ctx.execution_context  # lauren ExecutionContext | None — SSE/Streamable only; None for WS
ctx.session_id         # str | None — mcp-session-id for SSE/Streamable; None for WS
```

### State and metadata

```python
ctx.metadata        # dict[str, Any] — values from @set_metadata on the @mcp_server class
ctx.state           # dict[str, Any] — mutable scratch space for this call
ctx.extras          # dict[str, Any] — extension bag; lauren-ai stores AgentContext here
ctx.lifespan_context  # dict[str, Any] — dict yielded by @mcp_lifespan

ctx.get_metadata(key, default=None)  # convenience wrapper around ctx.metadata.get(...)
```

### Progress reporting

```python
await ctx.report_progress(50, total=100)   # sends notifications/progress to the client
await ctx.report_progress(75)              # total is optional
```

`report_progress` is a no-op when the client did not include a `progressToken` in the
`tools/call` request, or when the transport has no notification channel.

### Structured logging

```python
await ctx.debug("cache miss", {"key": "item-42"})
await ctx.info("processing started")
await ctx.warning("rate limit approaching", {"remaining": 5})
await ctx.error("upstream timeout", {"url": "https://..."})

# Or directly:
await ctx.log("info", "message", {"extra": "data"})
```

Each call sends a `notifications/message` JSON-RPC notification to the connected client.
Messages below the server's minimum log level are dropped silently.  The level threshold
can be adjusted at runtime via `logging/setLevel` (see [Logging / setLevel](#logging-setlevel)).

Logging is a no-op when there is no notification channel (e.g. in unit tests where
`_send_notification` was not supplied).

### Sampling — ask the client's LLM

`ctx.sample()` sends a `sampling/createMessage` request to the connected client,
asking it to run an LLM call on the server's behalf.

```python
result = await ctx.sample(
    "Summarise this document",
    max_tokens=256,
    system_prompt="Be concise.",
    temperature=0.3,
    stop_sequences=["---"],
    include_context="thisServer",    # "none" | "thisServer" | "allServers"
)
# result is a CreateMessageResult
print(result.text)     # assistant reply text
print(result.model)    # model used
```

Pass `result_type` to parse and validate a structured JSON reply:

```python
from pydantic import BaseModel

class Summary(BaseModel):
    headline: str
    word_count: int

summary = await ctx.sample(
    "Summarise this document as JSON",
    max_tokens=512,
    result_type=Summary,
)
# summary is a validated Summary instance
```

Raises `McpSamplingNotAvailable` when:
- the connected client did not advertise the `sampling` capability, or
- the transport cannot carry server-to-client requests (legacy SSE).

### Elicitation — ask the user

`ctx.elicit()` sends an `elicitation/create` request asking the connected client to
prompt its user for input.

```python
from lauren_mcp import ElicitResult

# Approval only (no schema)
answer = await ctx.elicit("Confirm deletion of 500 records?")
if answer.action == "accept":
    ...  # proceed
elif answer.action == "decline":
    ...  # user said no
# answer.action can be "accept" | "decline" | "cancel"
```

Pass `response_type` to collect a typed value:

```python
# Scalar types
name = await ctx.elicit("Enter your name:", str)
age  = await ctx.elicit("Enter your age:", int)
confirmed = await ctx.elicit("Proceed?", bool)

# Enum / Literal choices
from typing import Literal
choice = await ctx.elicit("Pick format:", Literal["json", "csv", "xml"])

# Flat structured form — Pydantic model, dataclass, TypedDict, or msgspec.Struct
from pydantic import BaseModel

class ConfirmForm(BaseModel):
    reason: str
    notify_team: bool

form = await ctx.elicit("Provide deletion reason:", ConfirmForm)
if form.action == "accept" and form.content:
    reason = form.content["reason"]
```

!!! warning
    MCP elicitation schemas must be **flat** (no nested objects or arrays).  Attempting
    to use a nested structured type raises `ValueError` at call time.

Raises `McpElicitationNotAvailable` when the client does not support the `elicitation`
capability or the transport cannot deliver server-to-client requests.

---

## `@mcp_lifespan`

Runs once at server startup; the `dict` yielded becomes `ctx.lifespan_context` in every
tool call.  Code after the `yield` (typically in a `finally` block) runs at server
shutdown.

```python
from lauren_mcp.server import mcp_lifespan
from lauren_mcp import McpToolContext

@mcp_server("/mcp")
class MyServer:
    @mcp_lifespan
    async def lifespan(self):
        """Initialise shared resources."""
        db = await connect_db()
        cache = await Cache.create()
        try:
            yield {"db": db, "cache": cache}
        finally:
            await db.close()
            await cache.close()

    @mcp_tool()
    async def query(self, sql: str, ctx: McpToolContext) -> list:
        """Run a SQL query."""
        db = ctx.lifespan_context["db"]
        return await db.fetch(sql)
```

Rules:
- The decorated method must be an `async def` with a single `yield` (`async def` with
  `yield` makes it an async generator function).
- Only one `@mcp_lifespan` method is allowed per class; a second raises `TypeError`.
- The yielded value must be a `dict` (or `None`, which becomes `{}`).

---

## `@mcp_resource`

Exposes a URI-addressable resource.  Path template variables are extracted from the URI
and passed as keyword arguments.

### Basic resource

```python
from lauren_mcp import mcp_resource

@mcp_server("/mcp")
class CatalogueServer:
    @mcp_resource("/items/{item_id}", mime_type="application/json")
    async def get_item(self, item_id: str) -> dict:
        """Return a catalogue item.

        Args:
            item_id: The item ID extracted from the URI path.
        """
        item = next((i for i in CATALOGUE if str(i["id"]) == item_id), None)
        return item or {}
```

### Full signature

```python
def mcp_resource(
    uri_template: str,
    *,
    name: str | None = None,
    description: str | None = None,
    mime_type: str | None = None,
) -> Callable:
```

### URI template syntax

`@mcp_resource` supports an RFC 6570 subset:

| Syntax | Matches | Example |
|---|---|---|
| `{param}` | Single path segment (no `/`) | `/items/{id}` |
| `{+param}` | Multi-segment (across `/`) | `/files/{+path}` |
| `{param*}` | Same as `{+param}` | `/files/{path*}` |
| `{?p1,p2}` | Query-string suffix (optional) | `/search/{topic}{?page,size}` |

```python
# Multi-segment path variable
@mcp_resource("/files/{+path}")
async def read_file(self, path: str) -> str:
    with open(path) as f:
        return f.read()

# Query parameters with automatic type coercion
@mcp_resource("/search/{topic}{?page,size}")
async def search(self, topic: str, page: int = 1, size: int = 10) -> list:
    ...
```

Type annotations on query parameters are used to coerce the string URI variable into the
declared Python type (`int`, `float`, `bool`).  Path variables annotated as `int` or
`float` are also coerced.

### Binary and multi-item responses

```python
# bytes → base64-encoded blob + mimeType from decorator or "application/octet-stream"
@mcp_resource("/img/{name}", mime_type="image/png")
async def image(self, name: str) -> bytes:
    return Path(f"static/{name}").read_bytes()

# Explicit BlobResource — lets you set mime_type per-call
from lauren_mcp import BlobResource

@mcp_resource("/doc/{id}")
async def document(self, id: str) -> BlobResource:
    data, mime = fetch_document(id)
    return BlobResource(data=data, mime_type=mime)

# ResourceResult — return multiple content items in one response
from lauren_mcp import ResourceResult

@mcp_resource("/bundle/{name}")
async def bundle(self, name: str) -> ResourceResult:
    return ResourceResult(contents=[
        "text item visible to LLM",
        b"binary attachment",
    ])
```

---

## `@mcp_prompt`

Registers a parameterised prompt template.  Parameter names and docstring `Args:` entries
are forwarded in `prompts/list`.

```python
from lauren_mcp import mcp_prompt

@mcp_server("/mcp")
class CatalogueServer:
    @mcp_prompt(name="catalogue_summary", description="Summarise the catalogue")
    async def catalogue_summary_prompt(self, focus: str = "all") -> str:
        """Generate a catalogue summarisation prompt.

        Args:
            focus: Which category to focus on (default "all").
        """
        return (
            f"Please summarise the current catalogue, focusing on: {focus}. "
            "Include item counts and notable trends."
        )
```

Return a plain `str` (wrapped into a single `user` message) or a `dict` that already
matches the `GetPromptResult` shape for multi-turn prompts:

```python
@mcp_prompt()
async def review_prompt(self, draft: str, tone: str = "formal") -> dict:
    return {
        "description": "Review a text draft",
        "messages": [
            {"role": "user", "content": {"type": "text", "text": f"Draft:\n{draft}"}},
            {"role": "assistant", "content": {"type": "text", "text": "I will review this."}},
            {"role": "user", "content": {"type": "text", "text": f"Tone: {tone}. Please proceed."}},
        ],
    }
```

**Signature**

```python
def mcp_prompt(name: str | None = None, *, description: str | None = None) -> Callable:
```

---

## Rich schema types

`@mcp_tool` generates JSON Schema from Python type annotations.  The following types
are all supported out of the box.

### Primitives and containers

```python
@mcp_tool()
async def example(
    self,
    text: str,                         # {"type": "string"}
    count: int,                        # {"type": "integer"}
    ratio: float,                      # {"type": "number"}
    flag: bool,                        # {"type": "boolean"}
    tags: list[str],                   # {"type": "array", "items": {"type": "string"}}
    ids: set[int],                     # {"type": "array", "uniqueItems": true, ...}
    mapping: dict[str, int],           # {"type": "object", "additionalProperties": {...}}
    pair: tuple[str, int],             # prefixItems tuple (fixed-length)
    optional: str | None = None,       # optional — not in "required"
) -> dict: ...
```

### Literal and Enum

```python
from typing import Literal
import enum

class Format(enum.Enum):
    JSON = "json"
    CSV  = "csv"

@mcp_tool()
async def export(
    self,
    fmt: Literal["json", "csv", "xml"],  # {"type": "string", "enum": [...]}
    style: Format,                        # {"type": "string", "enum": ["json", "csv"]}
) -> str: ...
```

### Annotated with Field constraints

Pydantic `Field` and `annotated_types` constraints (`Ge`, `Le`, `MinLen`, etc.) are
applied to the JSON Schema when the `pydantic` package is installed:

```python
from typing import Annotated
from pydantic import Field

@mcp_tool()
async def create_user(
    self,
    username: Annotated[str, Field(min_length=3, max_length=32, description="Login name")],
    age: Annotated[int, Field(ge=18, le=120)],
    score: Annotated[float, Field(gt=0.0, le=1.0)],
) -> dict: ...
```

### Structured types (Pydantic, dataclass, TypedDict, msgspec)

Structured types are emitted as `$ref` into a shared `$defs` block.

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import TypedDict
from pydantic import BaseModel

class Address(BaseModel):
    street: str
    city: str
    postcode: str

@dataclass
class OrderLine:
    sku: str
    qty: int
    price: float = 0.0

class Filters(TypedDict, total=False):
    category: str
    min_price: float

@mcp_tool()
async def place_order(
    self,
    address: Address,          # Pydantic — requires pydantic installed
    lines: list[OrderLine],    # dataclass — built-in support
    filters: Filters,          # TypedDict — built-in support
) -> dict: ...
```

!!! note
    Pydantic and msgspec are optional dependencies.  Install them as extras:
    `pip install "lauren-mcp[pydantic]"` or `pip install "lauren-mcp[msgspec]"`.
    Without them, those structured types degrade to `{"type": "object"}` and a
    warning is logged.

### Special scalar types

```python
import uuid, datetime, pathlib

@mcp_tool()
async def special(
    self,
    item_id: uuid.UUID,            # {"type": "string", "format": "uuid"}
    created: datetime.datetime,    # {"type": "string", "format": "date-time"}
    date: datetime.date,           # {"type": "string", "format": "date"}
    duration: datetime.timedelta,  # {"type": "string", "format": "duration"}
    path: pathlib.Path,            # {"type": "string", "format": "path"}
    data: bytes,                   # {"type": "string", "format": "byte"}
) -> str: ...
```

---

## Transport configuration

The `transport` parameter to `for_root()` (or `@mcp_server`) controls which transport
controllers are mounted.  The `for_root()` value overrides the `@mcp_server` value.

=== "WebSocket only"

    ```python
    McpServerModule.for_root(MyServer, transport="ws")
    # Mounts: GET/WS {path}/ws
    ```

=== "Streamable HTTP only"

    ```python
    McpServerModule.for_root(MyServer, transport="streamable")
    # Mounts: POST {path}  (optionally GET for SSE streams)
    # Protocol: MCP 2025-03-26
    ```

=== "Both WS and Streamable HTTP"

    ```python
    McpServerModule.for_root(MyServer, transport="all")
    # Mounts: WS at {path}/ws  +  Streamable HTTP at {path}
    ```

=== "Legacy SSE (MCP 2024-11-05)"

    ```python
    McpServerModule.for_root(MyServer, transport="sse")
    # Mounts: GET {path}/sse  (event stream)
    #         POST {path}/    (client → server messages)
    ```

=== "WS + Legacy SSE"

    ```python
    McpServerModule.for_root(MyServer, transport="both")
    ```

!!! tip
    Prefer `"all"` for new deployments — it gives you WebSocket for low-latency
    bidirectional use and Streamable HTTP for clients that cannot use WebSockets.
    Legacy SSE (`"sse"`) cannot deliver server-to-client requests, so `ctx.sample()`
    and `ctx.elicit()` will raise `McpSamplingNotAvailable` / `McpElicitationNotAvailable`
    on that transport.

---

## Guards, interceptors, and metadata

All Lauren `@use_*` decorators placed on the `@mcp_server` class are propagated onto the
generated transport controllers automatically.

### Guards and interceptors

```python
from lauren import use_guards, use_interceptors, set_metadata
from my_app.guards import AuthGuard, RateLimitGuard
from my_app.interceptors import AuditInterceptor

@mcp_server("/mcp")
@use_guards(AuthGuard, RateLimitGuard)
@use_interceptors(AuditInterceptor)
@set_metadata("team", "platform")
@set_metadata("env", "production")
class MyServer:
    @mcp_tool()
    async def sensitive_op(self, ctx: McpToolContext) -> str:
        team = ctx.get_metadata("team")    # "platform"
        env  = ctx.metadata["env"]         # "production"
        ...
```

`set_metadata` values are available inside every tool via `ctx.metadata` /
`ctx.get_metadata()`.  Guards receive these values through Lauren's standard
`ExecutionContext.get_metadata()` mechanism.

### Per-transport behaviour

| Annotation | WebSocket transport | SSE / Streamable transport |
|---|---|---|
| `@use_guards` | Enforced before `@on_connect` | Per-request (Lauren HTTP pipeline) |
| `@use_interceptors` | Wraps `@on_connect` | Wraps every handler call |
| `@use_middlewares` | No-op | Per-request middleware chain |
| `@use_encoder` | No-op | Custom JSON encoder for all routes |
| `@use_exception_handlers` | No-op | Per-controller exception handling |
| `@set_metadata` | Available via `ctx.metadata` | Available via `ctx.metadata` |

---

## Per-Tool Guards and Interceptors

Class-level `@use_guards` and `@use_interceptors` apply to the entire transport
connection or every HTTP handler.  For finer-grained control, the same
decorators can be placed directly on individual `@mcp_tool`, `@mcp_resource`,
or `@mcp_prompt` methods.

!!! important "Decorator order"
    `@mcp_tool()` must be the **outermost** decorator. Lauren decorators go
    **inside** (closer to the `async def`):

    ```python
    # Correct:
    @set_metadata("required_role", "admin")
    @use_guards(AdminGuard)
    @mcp_tool()
    async def admin_op(self) -> dict: ...
    ```

### Per-tool guard example

```python
from lauren import injectable, use_guards, set_metadata
from lauren_mcp import McpExecutionContext

@injectable()
class RoleGuard:
    async def can_activate(self, ctx: McpExecutionContext) -> bool:
        required = ctx.get_metadata("required_role")
        if required is None:
            return True
        role = ctx.headers.get("x-role", "guest") if ctx.headers else "guest"
        return role == required


@mcp_server("/mcp")
class MyServer:

    @set_metadata("required_role", "admin")
    @use_guards(RoleGuard)
    @mcp_tool()
    async def admin_delete(self) -> dict:
        """Delete all records. Requires admin role."""
        ...

    @mcp_tool()
    async def public_search(self, query: str) -> list:
        """Search — accessible to everyone."""
        ...
```

When `RoleGuard.can_activate` returns `False`, the call returns
`INTERNAL_ERROR` with `data = {"type": "FORBIDDEN", "guard": "RoleGuard"}`.
The transport connection remains open; only that specific call is rejected.

### Per-tool interceptor example

```python
from lauren import interceptor, use_interceptors
from lauren_mcp import McpCallHandler, McpExecutionContext
import time

@interceptor()
class TimingInterceptor:
    async def intercept(
        self, ctx: McpExecutionContext, call_handler: McpCallHandler
    ) -> dict:
        start = time.perf_counter()
        result = await call_handler.handle()
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        if isinstance(result.get("structuredContent"), dict):
            result["structuredContent"]["_elapsed_ms"] = elapsed_ms
        return result


@mcp_server("/mcp")
class CatalogueServer:

    @use_interceptors(TimingInterceptor)
    @mcp_tool()
    async def search(self, query: str) -> dict:
        ...
```

### Difference from class-level decorators

| Scope | Applies to | Context type |
|---|---|---|
| Class-level `@use_guards` | Transport connection / HTTP handler | Lauren `ExecutionContext` |
| Method-level `@use_guards` | Individual tool / resource / prompt call | `McpExecutionContext` |
| Class-level `@use_interceptors` | Transport handler | Lauren `ExecutionContext` |
| Method-level `@use_interceptors` | Individual tool call | `McpExecutionContext`, `McpCallHandler` |

Guard and interceptor classes used in method-level decorators are automatically
registered as DI providers — no need to add them to
`McpServerModule.for_root(providers=[...])`.

See **[Per-Method Cross-Cutting Decorators](per-tool-decorators.md)** for a
comprehensive guide including exception handlers, transport availability, and
decorator-stacking rules.

---

## Server composition

### Mount a sibling server

Expose another `@mcp_server` class's tools, resources, and prompts through the primary
server, with a name prefix applied to avoid collisions.

```python
@mcp_server("/orders")
class OrderServer:
    @mcp_tool()
    async def list_orders(self) -> list:
        """List all orders."""
        ...

@mcp_server("/mcp")
class PrimaryServer:
    @mcp_tool()
    async def search(self, query: str) -> list:
        """Search the catalogue."""
        ...

@module(imports=[McpServerModule.for_root(
    PrimaryServer,
    transport="ws",
    mounts=[(OrderServer, "orders_")],   # exposes tool as "orders_list_orders"
    providers=[OrderServer],             # make it resolvable by DI
)])
class AppModule: ...
```

At startup, each tool / resource / prompt from `OrderServer` is cloned with the prefix
applied and registered in the shared catalogue.  Calls to `orders_list_orders` are
forwarded to `OrderServer`'s DI-resolved instance.

`McpToolNameCollision` is raised at startup if the prefixed name collides with an
existing entry.

### Proxy a remote MCP server

Connect to a remote MCP server and re-export its tools locally.

```python
from lauren_mcp import McpServer

remote_client = McpServer.streamable_http("http://remote-service/mcp")

@module(imports=[McpServerModule.for_root(
    LocalServer,
    transport="ws",
    proxies=[(remote_client, "remote_")],
)])
class AppModule: ...
```

At startup the binder:
1. Calls `await remote_client.connect()` and fetches `tools/list`.
2. Registers each remote tool locally under `remote_{name}`.
3. Forwards `tools/call` requests over `remote_client.call_tool()`.
4. At shutdown, unregisters the tools and closes the client.

!!! note
    Only tools are proxied (not resources or prompts).  If the remote server's tool list
    changes after startup, the local catalogue does not update automatically — reconnect
    or restart to refresh.

---

## Dynamic catalog

The `McpCatalogManager` singleton holds the live tool / resource / prompt catalogue.
Mutations after startup automatically fire `notifications/*/list_changed` broadcasts to
all connected clients.

```python
from lauren import injectable, Scope, post_construct
from lauren_mcp._server._catalog import McpCatalogManager
from lauren_mcp.server._meta import McpToolMeta

@injectable(scope=Scope.SINGLETON)
class PluginLoader:
    def __init__(self, catalog: McpCatalogManager) -> None:
        self._catalog = catalog

    @post_construct
    async def load_plugins(self) -> None:
        for plugin in await discover_plugins():
            meta = McpToolMeta(
                name=plugin.name,
                description=plugin.description,
                input_schema=plugin.schema,
                method_name="call",
            )
            # Bind the callable directly on the meta object
            meta._bound_instance = plugin  # type: ignore[attr-defined]
            self._catalog.register_tool(meta)

    async def unload_plugin(self, name: str) -> None:
        self._catalog.unregister_tool(name)
        # Connected clients automatically receive
        # notifications/tools/list_changed
```

Add `PluginLoader` to `for_root(..., providers=[PluginLoader])` so Lauren's DI
instantiates it at startup alongside the MCP handler registrar.

**Catalog API**

```python
catalog.register_tool(meta, on_conflict="replace")   # "replace" | "error"
catalog.unregister_tool(name)                        # returns True if removed
catalog.list_tools()                                 # list[McpToolMeta]

catalog.register_resource(meta)
catalog.unregister_resource(name)
catalog.list_resources()

catalog.register_prompt(meta)
catalog.unregister_prompt(name)
catalog.list_prompts()
```

---

## OpenAPI import

`build_openapi_server_class()` generates a fully-decorated `@mcp_server` class whose
tools proxy an OpenAPI 3.x REST API.

```python
import json
import httpx
from lauren import module
from lauren_mcp import McpServerModule
from lauren_mcp.server import build_openapi_server_class, RouteEntry

with open("openapi.json") as f:
    spec = json.load(f)

ServerCls = build_openapi_server_class(
    spec,
    http_client=httpx.AsyncClient(base_url="https://api.example.com"),
    server_path="/mcp",
    route_map=[
        RouteEntry(r"^/admin", expose_as="exclude"),          # hide admin routes
        RouteEntry(r"^/items", method="GET", name_override="list_items"),
    ],
    class_name="PetStoreServer",
)

@module(imports=[McpServerModule.for_root(ServerCls)])
class AppModule: ...
```

**`build_openapi_server_class()` parameters**

| Parameter | Default | Description |
|---|---|---|
| `spec` | required | Parsed spec `dict`, or a path to a `.json` / `.yaml` file |
| `http_client` | required | `httpx.AsyncClient` (or compatible) used to execute calls |
| `base_url` | `""` | URL prefix for all requests; may be empty if `http_client` already has one |
| `server_path` | `"/mcp"` | Mount path passed to `@mcp_server` |
| `route_map` | `None` | Ordered `RouteEntry` rules — first match wins |
| `class_name` | `"OpenApiMcpServer"` | Name for the generated class |

**`RouteEntry` fields**

```python
@dataclass
class RouteEntry:
    pattern: str               # regex matched against the OpenAPI path
    method: str | None = None  # "GET", "POST", … or None (matches all methods)
    expose_as: Literal["tool", "exclude"] = "tool"
    name_override: str | None = None
    description_override: str | None = None
```

Operations with no matching `RouteEntry` are exposed as tools.  Tool names default to
`operationId` (sanitised) or `{method}{path}`.  Header and cookie parameters are excluded
from the AI-visible schema; only path and query parameters (plus JSON request bodies) are
included.

!!! tip
    OpenAPI-imported tool descriptions are generated from `operationId` or `summary`
    strings, which tend to be terse.  For production use, prefer hand-written tool
    descriptions that explain what the operation does in plain language — they perform
    significantly better with LLMs.

---

## Logging / setLevel

Connected clients can adjust the server's minimum log level at runtime by sending a
`logging/setLevel` request.  The initial level is set via `for_root(log_level=...)`.

```python
McpServerModule.for_root(
    MyServer,
    log_level="info",    # "debug" | "info" | "warning" | "error"
)
```

Accepted levels and their filter behaviour:

| Level | `ctx.debug()` | `ctx.info()` | `ctx.warning()` | `ctx.error()` |
|---|:---:|:---:|:---:|:---:|
| `"debug"` | sent | sent | sent | sent |
| `"info"` | dropped | sent | sent | sent |
| `"warning"` | dropped | dropped | sent | sent |
| `"error"` | dropped | dropped | dropped | sent |

When a client sends `logging/setLevel`, the threshold is updated immediately and applies
to all subsequent tool calls in that server process.  The change is server-wide, not
per-connection.

---

## Testing

### In-process integration test (Lauren DI stack)

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
    TestClient(app)    # triggers @post_construct (registers handlers)
    return app

async def test_tools_list(app):
    async with WsTestClient(app).connect("/mcp/ws") as ws:
        await ws.send_json({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        })
        await ws.receive_json()
        await ws.send_json({"jsonrpc": "2.0", "method": "notifications/initialized"})
        await ws.send_json({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        resp = await asyncio.wait_for(ws.receive_json(), timeout=3.0)
    assert any(t["name"] == "search" for t in resp["result"]["tools"])
```

!!! warning
    Always call `TestClient(app)` after `LaurenFactory.create()`.  This triggers
    `@post_construct` hooks which register all MCP handlers.  Skipping it results in
    `Method not found: 'initialize'` on the first request.

### Unit test (no DI, no network)

Use `make_tools_call_handler` directly for fast handler-level tests:

```python
from lauren_mcp.server._handlers import make_tools_call_handler
from lauren_mcp.server._meta import MCP_TOOL_META
from lauren_mcp._types import JsonRpcRequest

async def test_search_handler():
    meta = getattr(CatalogueServer.search, MCP_TOOL_META)
    handler = make_tools_call_handler(CatalogueServer(), [meta])
    req = JsonRpcRequest(method="tools/call", id=1, params={"name": "search", "arguments": {"query": "widget"}})
    result = await handler(req)
    items = result["structuredContent"]["result"]
    assert len(items) > 0
```

---

## Common errors

| Error | Cause | Fix |
|---|---|---|
| `TypeError: … is not an MCP server class` | `for_root()` called with an un-decorated class | Add `@mcp_server(path)` to the class |
| `Method not found: 'initialize'` | `@post_construct` did not fire | Call `TestClient(app)` after `LaurenFactory.create()` |
| `INVALID_REQUEST` on first call | Request sent before handshake completed | Send `initialize`, receive result, send `notifications/initialized` before any other request |
| `McpToolNameCollision` | Two composition sources expose the same tool name | Add or change the mount prefix |
| `McpSamplingNotAvailable` | `ctx.sample()` on legacy SSE, or client has no `sampling` capability | Use WS or Streamable HTTP; verify client advertises sampling |
| `McpElicitationNotAvailable` | `ctx.elicit()` on legacy SSE, or client has no `elicitation` capability | Use WS or Streamable HTTP; verify client advertises elicitation |
| `ValueError: … timed out` | `timeout=N` exceeded | Increase the timeout or optimise the tool |
| `ValueError: missing required key` | Return value does not satisfy `output_schema` | Fix the tool's return value or update the schema |
| `MissingProviderError: No provider for server_cls` | `from __future__ import annotations` stringifies the annotation and DI cannot resolve it | Already handled internally — do not manually replicate the `_McpHandlerRegistrar` pattern |
