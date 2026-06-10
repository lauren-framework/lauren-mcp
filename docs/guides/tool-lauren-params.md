# Lauren Parameter Injection in MCP Tools

`@mcp_tool` and `@mcp_resource` methods can receive more than just the
arguments an MCP client sends.  Lauren's parameter injection system lets you
declare dependencies directly in the method signature, and the framework
resolves and delivers them before your code runs — without exposing them to
AI clients or requiring any changes on the client side.

This guide covers all six injection features: field validation, pipe
transforms, `Depends`, `Header`, `State`, `BackgroundTasks`, and `ToolStream`.

!!! note "No `from __future__ import annotations`"
    Files that use `Depends[callable]`, `Header[T]`, or `State[T]` must **not**
    have `from __future__ import annotations` at the top.  That import stringifies
    all annotations at parse time, which prevents the runtime inspection that
    resolves these subscript forms.  The other features (`QueryField`, `@pipe`,
    `BackgroundTasks`, `ToolStream`) work fine either way.

---

## 1. Field validation and pipe transforms

### What it is

Lauren's `QueryField` / `PathField` descriptor and the `@pipe()` decorator give
you two complementary ways to validate and transform incoming tool arguments
before they reach your method body.

- **`QueryField` / `PathField`** — declarative constraints (`ge`, `le`,
  `min_length`, `max_length`, `pattern`, `description`) that are both enforced
  at runtime **and** reflected in the tool's JSON Schema so AI clients can see
  them before calling the tool.

- **`@pipe()`** — a callable transform applied to the value after type coercion
  and field validation.  Pipes can validate, mutate, or completely replace the
  value.  They are *not* reflected in the schema.

Both forms are declared with `typing.Annotated`.

### When to use it

Use `QueryField` constraints whenever you want the AI client to see limits in
the schema — minimum values, maximum lengths, allowed patterns.  Use `@pipe()`
whenever you need custom transformation or domain-level validation logic that
cannot be expressed as a simple JSON Schema keyword.

### Code example

```python
from __future__ import annotations

from typing import Annotated

from lauren import QueryField, pipe
from lauren.extractors import PipeContext
from lauren.exceptions import ExtractorFieldError

from lauren_mcp import mcp_server, mcp_tool


# Declarative constraints — reflected in JSON Schema
@mcp_server("/mcp")
class OrderServer:
    @mcp_tool()
    async def create_order(
        self,
        product_id: str,
        quantity: Annotated[int, QueryField(ge=1, le=1000, description="Order quantity")],
        name: Annotated[str, QueryField(min_length=1, max_length=100, pattern=r"^[A-Za-z ]+$")],
    ) -> dict:
        """Create a new order.

        Args:
            product_id: The product identifier.
            quantity: How many to order (1–1000).
            name: Customer name (letters and spaces only).
        """
        return {"product_id": product_id, "quantity": quantity, "name": name}
```

```python
# Custom transformation pipe — not reflected in schema, but runs at call time
@pipe()
async def resolve_user(user_id: str) -> dict:
    """Look up a user dict by ID, raising if not found."""
    user = await fetch_user(user_id)
    if not user:
        raise ExtractorFieldError(f"User '{user_id}' not found")
    return user


@mcp_server("/mcp")
class TaskServer:
    @mcp_tool()
    async def assign_task(
        self,
        user_id: Annotated[str, resolve_user],  # arrives as dict after pipe runs
        task_name: str,
    ) -> dict:
        """Assign a task to a user.

        Args:
            user_id: User identifier — transformed to user dict before call.
            task_name: Name of the task to assign.
        """
        return {"user": user_id, "task": task_name}
```

### Three annotation forms

All three forms work and can be mixed freely within the same server class:

```python
from lauren import QueryField, pipe

# 1. Annotated — most explicit, multiple metadata items allowed
quantity: Annotated[int, QueryField(ge=1), ensure_positive]

# 2. Subscript — concise when combining type + pipes
#    (requires a subscriptable extractor type, e.g. Path, Query)
from lauren import Query
quantity: Query[int, ensure_positive]

# 3. Default value (pipe only) — pipe assigned as default
quantity: int = pipe(ensure_positive)
```

### JSON Schema impact of field constraints

`QueryField` keywords translate directly to JSON Schema keywords in
`tools/list`, so AI clients can validate arguments before sending them:

| `QueryField` keyword | JSON Schema keyword |
|---|---|
| `ge=N` | `"minimum": N` |
| `gt=N` | `"exclusiveMinimum": N` |
| `le=N` | `"maximum": N` |
| `lt=N` | `"exclusiveMaximum": N` |
| `min_length=N` | `"minLength": N` |
| `max_length=N` | `"maxLength": N` |
| `pattern=r"..."` | `"pattern": "..."` |
| `description="..."` | added to the property's `"description"` field |

Pipes are **invisible in the schema** — the `user_id` parameter still appears
as `"string"` even though it is transformed to a user object before the tool
body receives it.

### Validation failure

When a `QueryField` constraint or a `@pipe()` raises `ExtractorFieldError`, the
framework returns a JSON-RPC error with code `INVALID_PARAMS` (`-32602`) to the
client.  The tool body is never entered.

### All transports

Field validation and pipe transforms work identically on WebSocket,
Streamable HTTP, legacy HTTP+SSE, and stdio transports.

---

## 2. `Depends[callable]`

### What it is

`Depends[callable]` injects the return value of `callable` into the parameter.
The callable is called once per tool invocation and its result is memoized for
that call — if two parameters declare `Depends[same_factory]`, the factory runs
only once and both parameters receive the same object.

### When to use it

Use `Depends` for anything you would normally pass through a dependency
injection layer: database connections, configuration dicts, authentication
tokens, caches, and other request-scoped or singleton services.

### Code example

```python
# No 'from __future__ import annotations'

from lauren import Depends
from lauren_mcp import mcp_server, mcp_tool, McpToolContext


# Sync factory
def get_config() -> dict:
    return {"timeout": 30, "retries": 3}


# Async factory
async def get_db_connection():
    return await connection_pool.acquire()


# Async generator factory — cleanup runs after the tool finishes
async def get_transaction():
    async with db.transaction() as tx:
        yield tx  # tool body executes here; commit/rollback happens in finally


@mcp_server("/mcp")
class UserServer:
    @mcp_tool()
    async def query_users(
        self,
        limit: int = 20,
        db=Depends[get_db_connection],       # excluded from JSON Schema
        config=Depends[get_config],          # excluded from JSON Schema
        ctx: McpToolContext | None = None,
    ) -> list:
        """Return a list of users.

        Args:
            limit: Maximum number of results.
        """
        if ctx:
            await ctx.info("Querying users", {"limit": limit})
        return await db.fetch_users(limit, timeout=config["timeout"])
```

### JSON Schema impact

`Depends[...]` parameters are **excluded entirely** from `inputSchema` — the
AI client never sees them and must not supply them.  The tool above exposes only
`limit` to the client.

### Memoisation within a call

The factory identity is used as the memoisation key.  Given:

```python
async def db_tool(
    self,
    a=Depends[get_db],
    b=Depends[get_db],
) -> dict:
    return {"same": a is b}  # always True
```

`get_db` runs once, and both `a` and `b` receive the same object.

### Cleanup

- Sync functions — no cleanup.
- Async functions — no cleanup.
- Async generators — the `finally` block (or code after `yield`) runs
  **after** the tool method returns, whether it succeeded or raised.
- Async context managers (`async with`) are also supported.

### All transports

`Depends` works on all transports: WebSocket, Streamable HTTP, legacy HTTP+SSE,
and stdio.

---

## 3. `Header[T]`

### What it is

`Header[T]` extracts a value from the HTTP or WebSocket upgrade headers and
delivers it as a typed parameter.  The parameter name maps to a header name by
converting underscores to hyphens: `x_user_id` → `"x-user-id"`.

### When to use it

Use `Header[T]` to read per-request metadata that the client transmits in
transport headers rather than in the tool arguments: user identity, locale,
auth tokens, API versions.

### Code example

```python
# No 'from __future__ import annotations'

from typing import Optional

from lauren import Header
from lauren_mcp import mcp_server, mcp_tool


@mcp_server("/mcp")
class SearchServer:
    @mcp_tool()
    async def search(
        self,
        query: str,
        x_user_id: Header[str] = "anonymous",       # "x-user-id" → default "anonymous"
        accept_language: Header[str] = "en",         # "accept-language" → default "en"
        x_token: Optional[Header[str]] = None,       # optional; None if absent
    ) -> list:
        """Search items.

        Args:
            query: Search terms.
        """
        return await do_search(query, user=x_user_id, lang=accept_language)
```

### Name mapping

| Parameter name | Header looked up |
|---|---|
| `x_user_id` | `x-user-id` |
| `accept_language` | `accept-language` |
| `x_request_id` | `x-request-id` |

### JSON Schema impact

`Header[T]` parameters are **excluded entirely** from `inputSchema`.  Only
`query` appears in the tool's schema.

### Default values

When the header is absent the Python default expression is used.  For
`Optional[Header[str]] = None` the value is `None`; for `Header[str] = "en"`
the value is `"en"`.

### Pipe chains

You can chain a pipe after the type parameter to transform the raw header
string before it reaches your method:

```python
from lauren import pipe, Header

@pipe()
def to_upper(v: str) -> str:
    return v.upper()

accept_language: Header[str, to_upper] = "EN"
```

### Transport availability

| Transport | Header source |
|---|---|
| WebSocket | HTTP upgrade request headers |
| Streamable HTTP | HTTP request headers |
| Legacy HTTP+SSE (`tools/call` POST) | HTTP request headers |
| stdio | Always uses the parameter default |

---

## 4. `State[T]`

### What it is

`State[T]` provides a fresh instance of `T` (created by calling `T()` with no
arguments) that is scoped to the current tool call.  All parameters that declare
`State[T]` for the same `T` within one call receive the same instance.

### When to use it

Use `State[T]` when you need a mutable scratch object that lives for exactly one
tool invocation: audit logs, per-call counters, result collectors, or any data
you want to accumulate across multiple operations that happen within a single
`tools/call`.

### Code example

```python
# No 'from __future__ import annotations'

from dataclasses import dataclass, field

from lauren import State
from lauren_mcp import mcp_server, mcp_tool


@dataclass
class AuditLog:
    entries: list[str] = field(default_factory=list)


@mcp_server("/mcp")
class OrderServer:
    @mcp_tool()
    async def multi_step_operation(
        self,
        data: str,
        audit: State[AuditLog],   # excluded from schema; T() called once per call
    ) -> dict:
        """Run a multi-step operation with audit logging.

        Args:
            data: Input data to process.
        """
        audit.entries.append(f"Started: {data}")
        result = await process(data)
        audit.entries.append("Completed")
        return {"result": result, "audit": audit.entries}
```

### Sharing state within a call

Two parameters with `State[T]` for the same `T` in the same call receive the
same instance — mutations are visible across both references:

```python
async def two_writers(
    self,
    a: State[AuditLog],
    b: State[AuditLog],
) -> dict:
    a.entries.append("via_a")
    return {"same": a is b, "b_entries": b.entries}
    # {"same": True, "b_entries": ["via_a"]}
```

### Fresh instance per call

Every tool call gets its own `T()`.  There is no sharing between successive
calls, and no state leaks between concurrent calls from different clients.

### JSON Schema impact

`State[T]` parameters are **excluded entirely** from `inputSchema`.

### Using `StateExtractor` (alias)

`State` is also exported as `StateExtractor` from `lauren` — both names refer
to the same type and work identically.  `State` is the recommended short form.

### All transports

`State[T]` works identically on all transports.

---

## 5. `BackgroundTasks`

### What it is

`BackgroundTasks` gives a tool method a task queue.  Tasks added to the queue
with `bg.add_task(fn, *args, **kwargs)` run **after** the tool response has
been sent to the client.  Both sync and async callables are accepted.

### When to use it

Use `BackgroundTasks` for fire-and-forget work that should not delay the
response: sending notifications, updating analytics, writing audit events to
a slow datastore, invalidating caches.

### Code example

```python
from __future__ import annotations

from lauren import BackgroundTasks
from lauren_mcp import mcp_server, mcp_tool


async def send_notification(user_id: str, event: str) -> None:
    await email_client.send(user_id, event)


async def update_analytics(order_id: str) -> None:
    await analytics.record("order_created", order_id)


@mcp_server("/mcp")
class OrderServer:
    @mcp_tool(timeout=30.0)
    async def submit_order(
        self,
        order_data: dict,
        bg: BackgroundTasks,   # excluded from JSON Schema
    ) -> dict:
        """Submit a new order.

        Args:
            order_data: Order payload.
        """
        order = await create_order(order_data)
        bg.add_task(send_notification, order["user_id"], "order_created")
        bg.add_task(update_analytics, order["id"])
        return {"order_id": order["id"], "status": "submitted"}
```

`@mcp_resource` methods also accept `BackgroundTasks`:

```python
@mcp_resource("/orders/{order_id}")
async def order_resource(
    self,
    order_id: str,
    bg: BackgroundTasks,
) -> str:
    bg.add_task(log_access, order_id)
    return await load_order(order_id)
```

### `add_task` signature

```python
bg.add_task(fn, *args, **kwargs) -> TaskHandle
```

`fn` may be a sync function, an async function, or any callable.  The returned
`TaskHandle` has a `task_id` string and a `status` field (`"pending"`,
`"done"`, or `"failed"`) that you can inspect after the request completes
(useful in tests).

### Timing and error handling

- Tasks run after the tool response is sent; the client does not wait for them.
- Task errors are logged but do **not** affect the tool result or the response
  sent to the client.
- If the tool method itself raises before returning, tasks that were added
  **before** the exception still run.  Tasks never added (unreachable code after
  the exception) do not run.
- If `BackgroundTasks` is declared twice in one handler, both parameters receive
  the same instance.

### JSON Schema impact

`BackgroundTasks` parameters are **excluded entirely** from `inputSchema`.

### All transports

`BackgroundTasks` works identically on all transports.

---

## 6. `ToolStream[T]`

### What it is

`ToolStream[T]` is a return type that makes an `@mcp_tool` method stream
incremental results.  Each value yielded by the async generator is sent to the
client as a `notifications/progress` event; when the generator is exhausted the
accumulated final value becomes the `tools/call` response.

### When to use it

Use `ToolStream` when your tool produces results incrementally and the client
benefits from seeing them live: LLM token streaming, file processing progress,
multi-step pipelines where partial results are useful.

### Code example

```python
from __future__ import annotations

from typing import AsyncGenerator

from lauren_mcp import ToolStream, mcp_server, mcp_tool, McpToolContext


@mcp_server("/mcp")
class LlmServer:
    @mcp_tool()
    async def stream_tokens(
        self,
        prompt: str,
        ctx: McpToolContext | None = None,
    ) -> ToolStream[str]:
        """Stream LLM tokens incrementally.

        Args:
            prompt: The prompt to complete.
        """
        async def generate() -> AsyncGenerator[str, None]:
            async for token in llm.stream_complete(prompt):
                yield token

        return ToolStream(generate())
```

### `ToolStream` constructor

```python
ToolStream(
    generator: AsyncGenerator[T, None],
    total: int | None = None,
    accumulate: Callable[[list[T]], Any] | None = None,
)
```

| Parameter | Description |
|---|---|
| `generator` | Async generator producing chunk values |
| `total` | Optional total count; forwarded as the `total` field in each progress notification, enabling percentage display |
| `accumulate` | Optional `(chunks: list[T]) -> Any` that reduces all chunks to the final response value |

### Accumulation defaults

- **`str` chunks** — joined with `""` (empty separator): `"".join(chunks)`
- **All other types** — the last yielded chunk, or `None` for an empty generator
- **Custom** — provide `accumulate=lambda chunks: ...` for any other reduction

```python
# Numbers: sum all chunks
return ToolStream(
    generate(),
    accumulate=lambda chunks: sum(chunks),
)
```

### Progress token requirement

The client must include a `progressToken` in `_meta.params` of the
`tools/call` request for `notifications/progress` events to be delivered:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "stream_tokens",
    "arguments": {"prompt": "Hello!"},
    "_meta": {"progressToken": "my-token-123"}
  }
}
```

If no `progressToken` is provided, the stream still runs to completion and the
accumulated result is returned normally — progress notifications are silently
suppressed.

### Using `ToolStream` from a client

```python
from lauren_mcp import McpServer

tokens_received = []

client = McpServer.streamable_http(
    "http://localhost:8000/mcp",
    progress_handler=lambda p: tokens_received.append(p.get("message", "")),
)
await client.connect()
result = await client.call_tool(
    "stream_tokens",
    {"prompt": "Hello!"},
    progress_token="tok-1",
)
# tokens_received has all incremental chunks
# result["content"][0]["text"] has the full accumulated text
```

### JSON Schema impact

`ToolStream` is the **return type** only — it has no impact on the input schema.
Normal `@mcp_tool` parameters (`prompt` above) appear in the schema as usual.

### All transports

`ToolStream` works on WebSocket, Streamable HTTP, and legacy HTTP+SSE.  On
transports that support bidirectional messaging (WebSocket, Streamable HTTP)
progress notifications arrive in real time.  On legacy SSE the notifications
are pushed as SSE events during the call.

---

## Complete example combining all features

The following server demonstrates all six features together:

```python
# No 'from __future__ import annotations' — required for Depends/Header/State

from dataclasses import dataclass, field
from typing import Optional, AsyncGenerator

from lauren import BackgroundTasks, Depends, Header, QueryField, State, pipe
from lauren.exceptions import ExtractorFieldError
from lauren.extractors import PipeContext

from lauren_mcp import (
    McpServerModule, McpToolContext, ToolStream,
    mcp_server, mcp_tool,
)


# ---------------------------------------------------------------------------
# Pipes
# ---------------------------------------------------------------------------

@pipe()
def ensure_positive(v: int, ctx: PipeContext) -> int:
    if v <= 0:
        raise ExtractorFieldError(f"{ctx.name} must be positive")
    return v


# ---------------------------------------------------------------------------
# Depends factories
# ---------------------------------------------------------------------------

async def get_db():
    return await db_pool.acquire()


def get_config() -> dict:
    return {"max_results": 100}


# ---------------------------------------------------------------------------
# State type
# ---------------------------------------------------------------------------

@dataclass
class CallLog:
    steps: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Side-effect function (runs in background)
# ---------------------------------------------------------------------------

async def record_search(query: str) -> None:
    await analytics.record("search", query)


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

@mcp_server("/mcp")
class FullServer:

    @mcp_tool()
    async def search(
        self,
        # Field validation: constraints in schema + runtime check
        query: str,
        limit: int = QueryField(ge=1, le=100, description="Max results"),  # type: ignore[assignment]

        # Depends: injected DB connection, excluded from schema
        db=Depends[get_db],
        config=Depends[get_config],

        # Header: caller's user ID from transport headers
        x_user_id: Header[str] = "anonymous",

        # State: per-call audit accumulator
        log: State[CallLog] = None,  # type: ignore[assignment]

        # BackgroundTasks: fire-and-forget analytics
        bg: BackgroundTasks = None,  # type: ignore[assignment]

        # McpToolContext: progress + logging (not in schema)
        ctx: McpToolContext | None = None,
    ) -> list:
        """Search the catalogue.

        Args:
            query: Search terms.
            limit: Maximum number of results (1–100).
        """
        if log:
            log.steps.append(f"search started by {x_user_id}")
        if ctx:
            await ctx.info("Searching", {"query": query, "user": x_user_id})

        max_r = min(limit, config["max_results"])
        results = await db.search(query, limit=max_r)

        if bg:
            bg.add_task(record_search, query)

        if log:
            log.steps.append(f"found {len(results)} results")
        return results

    @mcp_tool()
    async def stream_search(
        self,
        query: str,
        ctx: McpToolContext | None = None,
    ) -> ToolStream[str]:
        """Stream search result names one by one.

        Args:
            query: Search terms.
        """
        async def gen() -> AsyncGenerator[str, None]:
            async for item in db.stream_search(query):
                yield item["name"]

        return ToolStream(gen())
```

---

## Summary table

| Feature | Import | Schema impact | Transport |
|---|---|---|---|
| `QueryField` constraints | `from lauren import QueryField` | Adds `minimum`, `maximum`, etc. | All |
| `@pipe()` transform | `from lauren import pipe` | None (stripped) | All |
| `Depends[callable]` | `from lauren import Depends` | Excluded entirely | All |
| `Header[T]` | `from lauren import Header` | Excluded entirely | WS / HTTP (default on stdio) |
| `State[T]` | `from lauren import State` | Excluded entirely | All |
| `BackgroundTasks` | `from lauren import BackgroundTasks` | Excluded entirely | All |
| `ToolStream[T]` | `from lauren_mcp import ToolStream` | Return type only | All |

---

## Next steps

- **[Decorators in Depth](decorators.md)** — full reference for `@mcp_tool`,
  `@mcp_resource`, `@mcp_prompt`, and `@mcp_lifespan`
- **[Tool Context](tool-context.md)** — `McpToolContext` fields and methods
  (`report_progress`, `log`, `sample`, `elicit`)
- **[Testing](testing.md)** — how to test tools that use Lauren parameter
  injection with `WsTestClient`
