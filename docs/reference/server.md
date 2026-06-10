# Server API Reference

---

## `mcp_server`

```python
def mcp_server(path: str, *, transport: str = "ws") -> Callable[[type], type]:
```

Class decorator that registers a class as an MCP server endpoint.  Applies
`@injectable(scope=Scope.SINGLETON)` from Lauren so the class participates in
constructor injection.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `path` | `str` | required | URL path prefix (e.g. `"/mcp"`) |
| `transport` | `str` | `"ws"` | `"ws"` \| `"sse"` \| `"streamable"` \| `"both"` \| `"all"` |

**Transport values**

| Value | Mounts |
|---|---|
| `"ws"` | WebSocket at `{path}/ws` |
| `"sse"` | Legacy HTTP+SSE at `{path}` (MCP 2024-11-05) |
| `"streamable"` | Streamable HTTP at `{path}` (MCP 2025-03-26) |
| `"both"` | WebSocket + legacy HTTP+SSE |
| `"all"` | WebSocket + Streamable HTTP |

The transport value on `@mcp_server` is the default; `McpServerModule.for_root(transport=...)` overrides it.

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
    annotations: ToolAnnotations | None = None,
    timeout: float | None = None,
    tags: frozenset[str] | set[str] | None = None,
    meta: dict[str, Any] | None = None,
    output_schema: Any = None,
) -> Callable[[Callable], Callable]:
```

Method decorator that marks an `async def` method as an MCP tool.

JSON Schema is derived automatically from Python type annotations. Docstring
`Args:` sections (Google / Sphinx / NumPy format) supply per-parameter
descriptions. Any parameter annotated with `McpToolContext` (or
`McpToolContext | None`) is injected by the framework and excluded from the
schema.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `name` | `str \| None` | `None` | Override tool name; defaults to method name |
| `description` | `str \| None` | `None` | Override description; defaults to docstring |
| `annotations` | `ToolAnnotations \| None` | `None` | Behavioural hints transmitted to clients |
| `timeout` | `float \| None` | `None` | Per-call deadline in seconds; exceeded calls fail with internal error |
| `tags` | `frozenset[str] \| set[str] \| None` | `None` | Categorical tags in `tools/list` |
| `meta` | `dict[str, Any] \| None` | `None` | Opaque metadata forwarded under `_meta` in `tools/list` |
| `output_schema` | `Any` | `None` | JSON Schema dict, Pydantic model, `msgspec.Struct`, dataclass, or `TypedDict` describing structured output |

**Schema generation rules**

| Python annotation | JSON Schema type |
|---|---|
| `str` | `"string"` |
| `int` | `"integer"` |
| `float` | `"number"` |
| `bool` | `"boolean"` |
| `list` / `list[X]` | `"array"` |
| `dict` | `"object"` |
| Pydantic model / dataclass / `TypedDict` | `"object"` with properties |
| `X \| None` or param with default | optional (omitted from `required`) |
| No default, not `X \| None` | required |

**Return value conventions**

| Return type | Wire encoding |
|---|---|
| `str` | Single `TextContent` block |
| `bytes` | Single `TextContent` block (base-64) |
| `dict` / `list` | JSON-serialised `TextContent` |
| `TextContent` / `ImageContent` / `EmbeddedResource` | Used as-is |
| `list[TextContent \| ...]` | Multiple content blocks |
| `ToolOutput` | Full control — separate `content` and `structured_content` |

**Example**

```python
from lauren_mcp import mcp_tool, McpToolContext, ToolAnnotations

@mcp_tool(
    name="catalogue_search",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False),
    timeout=5.0,
)
async def search(
    self,
    query: str,
    limit: int = 10,
    ctx: McpToolContext | None = None,
) -> list[dict]:
    """Search the product catalogue.

    Args:
        query: Full-text search query.
        limit: Maximum number of results.
    """
    if ctx:
        await ctx.info(f"Searching for {query!r}")
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
) -> Callable[[Callable], Callable]:
```

Method decorator that exposes a URI-addressable resource.

URI template variables (`{item_id}`) are extracted and passed as string
keyword arguments. URI variables are **always strings** — cast inside the
method. Supports `{+param}` / `{param*}` multi-segment placeholders and a
`{?p1,p2}` optional query-parameter suffix.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `uri_template` | `str` | required | URI template (e.g. `"/items/{item_id}"`) |
| `name` | `str \| None` | `None` | Resource name; defaults to method name |
| `description` | `str \| None` | `None` | Description; defaults to docstring |
| `mime_type` | `str \| None` | `None` | MIME type hint (e.g. `"application/json"`) |

**Return value conventions**

| Return type | Wire encoding |
|---|---|
| `str` | `ResourceContent(text=...)` |
| `bytes` | `ResourceContent(blob=base64(data))` |
| `BlobResource` | `ResourceContent(blob=..., mimeType=mime_type)` |
| `ResourceResult` | Multiple `ResourceContent` items |

**Example**

```python
from lauren_mcp import mcp_resource

@mcp_resource("/orders/{order_id}", mime_type="application/json")
async def get_order(self, order_id: str) -> str:
    """Return an order as a JSON string."""
    import json
    return json.dumps({"id": int(order_id), "status": "open"})
```

---

## `mcp_prompt`

```python
def mcp_prompt(
    name: str | None = None,
    *,
    description: str | None = None,
) -> Callable[[Callable], Callable]:
```

Method decorator that exposes a parameterised prompt template.

The method returns a `str` (wrapped into a single `user` message) or a
`list[dict]` of `{"role": ..., "content": {"type": "text", "text": ...}}`
dicts for multi-turn prompts.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `name` | `str \| None` | `None` | Prompt name; defaults to method name |
| `description` | `str \| None` | `None` | Description; defaults to docstring |

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
        "Include: market position, top 3 strengths, top 3 weaknesses."
    )
```

---

## `mcp_lifespan`

```python
def mcp_lifespan(fn: AsyncGeneratorMethod) -> AsyncGeneratorMethod:
```

Method decorator marking an async generator as the server's lifespan hook.
No arguments — used as a bare decorator.

The generator runs **once at server startup**. The dict it yields becomes
`McpToolContext.lifespan_context` for every tool call during that session.
Code after the `yield` (typically in a `finally` block) runs at server
shutdown.

Raises `TypeError` if the decorated function is not an `async def` generator.

**Example**

```python
from lauren_mcp.server import mcp_lifespan

@mcp_server("/api")
class MyServer:
    @mcp_lifespan
    async def lifespan(self):
        db = await create_db_pool()
        try:
            yield {"db": db}
        finally:
            await db.close()

    @mcp_tool()
    async def query(self, sql: str, ctx: McpToolContext) -> list:
        db = ctx.lifespan_context["db"]
        return await db.fetch(sql)
```

---

## `McpToolContext`

```python
@dataclass(frozen=True)
class McpToolContext:
```

Per-call context object injected into `@mcp_tool` methods when a parameter is
annotated with `McpToolContext` (or `McpToolContext | None`).  The object is
frozen; `state` and `extras` are mutable bags.

**Fields**

| Field | Type | Description |
|---|---|---|
| `tool_name` | `str` | Name of the tool being called |
| `tool_use_id` | `str \| int \| None` | JSON-RPC request `id` |
| `headers` | `Headers \| None` | HTTP headers from the transport (WebSocket / SSE) |
| `execution_context` | `ExecutionContext \| None` | Lauren execution context |
| `session_id` | `str \| None` | SSE/Streamable session identifier |
| `metadata` | `dict[str, Any]` | Server-level metadata (from `@set_metadata` on the server class) |
| `state` | `dict[str, Any]` | Mutable per-call scratch space |
| `extras` | `dict[str, Any]` | Extension bag (e.g. `extras["agent_context"]` from `lauren-ai`) |
| `lifespan_context` | `dict[str, Any]` | Dict yielded by `@mcp_lifespan` |

**Methods**

```python
def get_metadata(self, key: str, default=None) -> Any
```
Convenience accessor for `self.metadata`.

```python
async def report_progress(
    self,
    progress: float | int,
    total: float | int | None = None,
) -> None
```
Send `notifications/progress` to the client. No-op when the client sent no
`progressToken` or the transport has no notification channel.

```python
async def log(
    self,
    level: Literal["debug", "info", "warning", "error"],
    message: str,
    data: dict | None = None,
) -> None
```
Send a structured `notifications/message` log entry to the client.  Dropped
when below the server's minimum level (`log_level` in `for_root`) or when the
transport has no notification channel.

```python
async def debug(self, message: str, data: dict | None = None) -> None
async def info(self, message: str, data: dict | None = None) -> None
async def warning(self, message: str, data: dict | None = None) -> None
async def error(self, message: str, data: dict | None = None) -> None
```
Convenience wrappers for `log()` at each level.

```python
async def sample(
    self,
    messages: str | list[SamplingMessage],
    *,
    max_tokens: int = 1024,
    system_prompt: str | None = None,
    temperature: float | None = None,
    stop_sequences: list[str] | None = None,
    model_preferences: dict | None = None,
    include_context: Literal["none", "thisServer", "allServers"] = "none",
    result_type: type | None = None,
) -> CreateMessageResult | Any
```
Ask the connected MCP client to run an LLM call.  Returns
`CreateMessageResult`, or an instance of `result_type` when that is a Pydantic
model class (parsed from the reply text).

Raises `McpSamplingNotAvailable` when the client lacks the `sampling`
capability or the transport cannot deliver server-to-client requests (legacy
SSE).

```python
async def elicit(
    self,
    message: str,
    response_type: Any = None,
) -> ElicitResult
```
Ask the connected MCP client to prompt its user for input.  `response_type`
may be `None` (approval only), a scalar type (`str`, `bool`, `int`, `float`),
a `Literal[...]`, an `Enum` subclass, or a flat Pydantic model / dataclass /
`TypedDict`.

Raises `McpElicitationNotAvailable` when the client lacks the `elicitation`
capability or the transport cannot deliver server-to-client requests.

---

## `ToolAnnotations`

```python
@dataclass(frozen=True)
class ToolAnnotations:
    readOnlyHint: bool = False
    destructiveHint: bool = True    # MCP spec conservative default
    idempotentHint: bool = False
    openWorldHint: bool = True      # MCP spec conservative default
```

Behavioural hints transmitted to clients in `tools/list`.  Defaults follow
the MCP specification's conservative assumptions: a tool is presumed
destructive and open-world unless declared otherwise.

Pass to `@mcp_tool(annotations=...)`:

```python
@mcp_tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
async def search(self, query: str) -> list: ...
```

---

## `ToolStream`

```python
@dataclass
class ToolStream(Generic[T]):
    generator: AsyncGenerator[T, None]
    total: int | None = None
    accumulate: Callable[[list[T]], Any] | None = None
```

Return type for `@mcp_tool` methods that produce incremental results.  Each
value yielded by `generator` is sent to the connected client as a
`notifications/progress` event (when the client supplied a `progressToken`).
When the generator is exhausted, the accumulated value becomes the
`tools/call` response.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `generator` | `AsyncGenerator[T, None]` | required | Async generator that yields chunk values |
| `total` | `int \| None` | `None` | Declared total count; forwarded as `total` in each progress notification |
| `accumulate` | `Callable[[list[T]], Any] \| None` | `None` | Reduces all chunks to the final response value; default: join `str` chunks, or return the last chunk |

**Accumulation defaults**

- `str` chunks — `"".join(chunks)`
- All other types — last chunk, or `None` for an empty generator
- Custom — `accumulate=lambda chunks: sum(chunks)` (or any callable)

**Example**

```python
from lauren_mcp import ToolStream, mcp_tool

@mcp_tool()
async def stream_tokens(self, prompt: str) -> ToolStream[str]:
    """Stream LLM tokens for a prompt.

    Args:
        prompt: The prompt to complete.
    """
    async def gen():
        async for token in llm.stream_complete(prompt):
            yield token

    return ToolStream(gen())
```

Progress notifications require the client to include `_meta.progressToken` in
the `tools/call` request.  Without it the stream still runs and the accumulated
result is returned, but no notifications are sent.

---

## Lauren parameter injection

The following Lauren-framework types can be declared as method parameters on
`@mcp_tool` and `@mcp_resource` methods.  They are **excluded from the tool's
JSON Schema** — the AI client never sees or provides them.

See the **[Lauren Parameter Injection guide](../guides/tool-lauren-params.md)**
for full examples.

### `QueryField` / `PathField`

```python
from lauren import QueryField, PathField
```

Declarative field descriptors that add JSON Schema constraints and enforce them
at call time.  Keywords:

| Keyword | JSON Schema keyword |
|---|---|
| `ge=N` | `"minimum": N` |
| `gt=N` | `"exclusiveMinimum": N` |
| `le=N` | `"maximum": N` |
| `lt=N` | `"exclusiveMaximum": N` |
| `min_length=N` | `"minLength": N` |
| `max_length=N` | `"maxLength": N` |
| `pattern=r"..."` | `"pattern": "..."` |
| `description="..."` | property description |

Constraint violations return `INVALID_PARAMS (-32602)` to the client.

### `@pipe()`

```python
from lauren import pipe
from lauren.extractors import PipeContext
```

Callable transform applied to a parameter value after type coercion.  Declare
with `Annotated[T, my_pipe]` or as a subscript `Query[T, my_pipe]`.  Pipes are
**not** reflected in the JSON Schema.  Raising `ExtractorFieldError` returns
`INVALID_PARAMS (-32602)`.

### `Depends[callable]`

```python
from lauren import Depends
```

Injects the return value of `callable` into the parameter.  The factory is
called once per tool invocation and memoised for that call — two parameters
with the same factory get the same instance.  Supports sync functions, async
functions, async generators (with cleanup), and async context managers.
Parameters are **excluded from the JSON Schema**.

### `Header[T]`

```python
from lauren import Header
```

Extracts a typed value from the transport headers.  The parameter name maps to
a header: `x_user_id` → `"x-user-id"` (underscores to hyphens).  The Python
default is used when the header is absent.  Parameters are **excluded from the
JSON Schema**.  On stdio the default is always used.

### `State[T]`

```python
from lauren import State          # also exported as StateExtractor
```

Provides a fresh `T()` instance scoped to the current call.  Multiple
parameters with the same `State[T]` within one call share the same instance.
Parameters are **excluded from the JSON Schema**.

### `BackgroundTasks`

```python
from lauren import BackgroundTasks
```

Provides a task queue.  Tasks added with `bg.add_task(fn, *args, **kwargs)`
run after the response is sent.  Both sync and async callables are accepted.
Task errors are logged but do not affect the tool result.  Parameters are
**excluded from the JSON Schema**.

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
        providers: list | None = None,
        imports: list | None = None,
        exports: list | None = None,
        log_level: str = "debug",
        mounts: list[tuple[type, str]] | None = None,
        proxies: list[tuple[McpClientProtocol, str]] | None = None,
    ) -> type:
```

Builds a Lauren `@module` that wires `server_cls` into the DI graph and
registers all MCP handler coroutines.  Pass the result to a Lauren `@module`'s
`imports=[...]`.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `server_cls` | `type` | required | Class decorated with `@mcp_server` |
| `transport` | `str` | `"ws"` | `"ws"` \| `"sse"` \| `"streamable"` \| `"both"` \| `"all"` — overrides the transport on `@mcp_server` |
| `server_info` | `Implementation \| None` | `None` | Override name/version in handshake (defaults to `Implementation(name=cls.__name__, version="1.0.0")`) |
| `capabilities` | `ServerCapabilities \| None` | `None` | Override auto-detected capabilities |
| `providers` | `list \| None` | `None` | Extra Lauren providers visible to `server_cls` via constructor injection |
| `imports` | `list \| None` | `None` | Extra `@module` classes whose exports become visible to `server_cls` |
| `exports` | `list \| None` | `None` | Provider types to re-export to the importing module |
| `log_level` | `str` | `"debug"` | Minimum severity for `ctx.log()` client notifications |
| `mounts` | `list[tuple[type, str]] \| None` | `None` | `[(OtherCls, "prefix_"), ...]` — compose another `@mcp_server`'s tools into this server |
| `proxies` | `list[tuple[client, str]] \| None` | `None` | `[(client, "prefix_"), ...]` — forward a remote MCP server's tools through this server |

**Raises**

- `TypeError` — `server_cls` not decorated with `@mcp_server`
- `ValueError` — unknown `transport` value

**Route mounting**

For a server declared at path `"/mcp"`:

| Transport | Path | Protocol |
|---|---|---|
| `"ws"` | `/mcp/ws` | WebSocket (JSON-RPC framing) |
| `"sse"` | `/mcp/sse` (GET) + `/mcp/` (POST) | Legacy HTTP+SSE, MCP 2024-11-05 |
| `"streamable"` | `/mcp/` (POST) | Streamable HTTP, MCP 2025-03-26 |

**Capabilities auto-detection**

When `capabilities=None`, capabilities are inferred from the decorated methods:

| Condition | Result |
|---|---|
| Has any `@mcp_tool` methods | `tools: {"listChanged": True}` |
| Has any `@mcp_resource` methods | `resources: {"listChanged": True}` |
| Has any `@mcp_prompt` methods | `prompts: {"listChanged": True}` |
| Always | `logging: {}` |

**Usage with Lauren**

```python
from lauren import LaurenFactory, module
from lauren_mcp import McpServerModule

@module(imports=[McpServerModule.for_root(CatalogueServer, transport="all")])
class AppModule:
    pass

app = LaurenFactory.create(AppModule)
```

**Composition example**

```python
McpServerModule.for_root(
    MainServer,
    mounts=[
        (SiblingServer, "sibling_"),   # expose SiblingServer's tools with prefix
    ],
    proxies=[
        (McpServer.ws("ws://remote/mcp/ws"), "remote_"),  # proxy remote tools
    ],
)
```

---

## `make_mount_binder`

```python
def make_mount_binder(mounted_cls: type, prefix: str) -> type:
```

Build an `@injectable` provider that registers a sibling `@mcp_server` class's
tools, resources, and prompts through the host server, with all names prefixed.

Add the returned class **and `mounted_cls` itself** to `for_root`'s
`providers=[...]`. Colliding names (after prefixing) raise
`McpToolNameCollision` at startup.

**Parameters**

| Name | Type | Description |
|---|---|---|
| `mounted_cls` | `type` | An `@mcp_server`-decorated class |
| `prefix` | `str` | String prepended to every tool/resource/prompt name |

Raises `TypeError` if `mounted_cls` is not decorated with `@mcp_server`.

**Example**

```python
from lauren_mcp.server import make_mount_binder

McpServerModule.for_root(
    MainServer,
    providers=[SiblingServer, make_mount_binder(SiblingServer, "sib_")],
)
```

Prefer using the `mounts=` shorthand in `for_root` which does this
automatically.

---

## `make_proxy_binder`

```python
def make_proxy_binder(client: McpClientProtocol, prefix: str) -> type:
```

Build an `@injectable` provider that connects a remote MCP server at startup,
fetches its tool catalogue, and registers each tool locally under
`{prefix}{name}`. Calls are forwarded over the client; the connection closes at
shutdown.

Add the returned class to `for_root`'s `providers=[...]`.

**Parameters**

| Name | Type | Description |
|---|---|---|
| `client` | `McpClientProtocol` | Client instance (e.g. from `McpServer.ws(...)`) |
| `prefix` | `str` | String prepended to every proxied tool name |

Prefer using the `proxies=` shorthand in `for_root` which does this
automatically.

---

## `McpToolNameCollision`

```python
class McpToolNameCollision(Exception):
```

Raised at server startup when two composition sources (mounts or proxies)
expose the same tool name after prefix expansion.

```python
from lauren_mcp import McpToolNameCollision

try:
    app = LaurenFactory.create(AppModule)
except McpToolNameCollision as exc:
    print(f"Duplicate tool: {exc}")
```

---

## `build_openapi_server_class`

```python
def build_openapi_server_class(
    spec: dict[str, Any] | str | Path,
    *,
    http_client: Any,
    base_url: str = "",
    server_path: str = "/mcp",
    route_map: list[RouteEntry] | None = None,
    class_name: str = "OpenApiMcpServer",
) -> type:
```

Generate an `@mcp_server` class whose tools wrap an OpenAPI 3.x spec.  Pass
the result to `McpServerModule.for_root()`.

**Parameters**

| Name | Type | Default | Description |
|---|---|---|---|
| `spec` | `dict \| str \| Path` | required | Parsed spec dict or path to `.json` / `.yaml` file |
| `http_client` | `Any` | required | `httpx.AsyncClient` (or compatible) that executes the calls |
| `base_url` | `str` | `""` | Prefix for all request URLs; may be empty if `http_client` has its own `base_url` |
| `server_path` | `str` | `"/mcp"` | Mount path passed to `@mcp_server` |
| `route_map` | `list[RouteEntry] \| None` | `None` | Ordered rules; first match wins; operations with no match are exposed as tools |
| `class_name` | `str` | `"OpenApiMcpServer"` | Name of the generated class |

**Example**

```python
import httpx
from lauren_mcp.server import build_openapi_server_class

client = httpx.AsyncClient(base_url="https://api.example.com")
ServerCls = build_openapi_server_class("openapi.json", http_client=client)
module = McpServerModule.for_root(ServerCls)
```

---

## `RouteEntry`

```python
@dataclass
class RouteEntry:
    pattern: str                                  # regex matched against the path
    method: str | None = None                     # "GET", "POST", … or None for all methods
    expose_as: Literal["tool", "exclude"] = "tool"
    name_override: str | None = None
    description_override: str | None = None
```

One rule controlling how an OpenAPI operation maps to an MCP tool.  Used in
the `route_map` of `build_openapi_server_class`.

| Field | Description |
|---|---|
| `pattern` | Regex matched against the OpenAPI path string |
| `method` | HTTP method to match (`"GET"`, `"POST"`, etc.) or `None` for all |
| `expose_as` | `"tool"` (default) or `"exclude"` to omit the operation |
| `name_override` | Override the auto-generated tool name |
| `description_override` | Override the auto-generated tool description |
