# Per-Method Cross-Cutting Decorators

## Overview

Lauren's `@use_guards`, `@use_interceptors`, `@use_exception_handlers`, and
`@set_metadata` decorators can be applied to individual `@mcp_tool`,
`@mcp_resource`, and `@mcp_prompt` methods for fine-grained access control and
cross-cutting concerns.

> **Decorator order matters.**
> `@mcp_tool()` must be the **outermost** decorator. Lauren decorators go
> inside (closer to the `async def`). Python applies decorators inside-out,
> so Lauren's attribute-setting decorators must run before `@mcp_tool()` reads them.

```python
# Correct order:
@set_metadata("required_role", "admin")  # innermost
@use_guards(AdminGuard)
@mcp_tool()                              # outermost — reads Lauren attrs
async def delete_all(self) -> dict: ...

# Wrong order (use_guards has no effect):
@mcp_tool()                              # runs before use_guards sets attrs
@use_guards(AdminGuard)
async def delete_all(self) -> dict: ...  # guard NOT read
```

---

## `@use_guards` — Per-Tool Access Control

Guards declared on a method run only for that specific tool call. They receive
`McpExecutionContext` (not `McpToolContext` — guards run before the tool method).

```python
from lauren import injectable, use_guards, set_metadata
from lauren_mcp import mcp_server, mcp_tool, McpExecutionContext

@injectable()
class RoleGuard:
    async def can_activate(self, ctx: McpExecutionContext) -> bool:
        required = ctx.get_metadata("required_role")
        if required is None:
            return True
        role = ctx.headers.get("x-role", "guest") if ctx.headers else "guest"
        return role == required


@mcp_server("/mcp")
class AdminServer:

    @set_metadata("required_role", "admin")
    @use_guards(RoleGuard)
    @mcp_tool()
    async def admin_action(self) -> dict:
        """Perform a privileged admin operation."""
        return {"status": "ok"}

    @mcp_tool()
    async def public_action(self) -> dict:
        """This tool has no guard — anyone can call it."""
        return {"status": "ok"}
```

When a guard returns `False`, the tool call returns `INTERNAL_ERROR` with
`data = {"type": "FORBIDDEN", "guard": "RoleGuard"}`. The WS/SSE connection
stays open — only this call is rejected.

### `McpExecutionContext` fields

| Field | Type | Description |
|---|---|---|
| `headers` | `Headers \| None` | Transport headers (WebSocket upgrade / HTTP request headers) |
| `execution_context` | `ExecutionContext \| None` | Lauren `ExecutionContext` for SSE/Streamable transports; `None` for WS/stdio |
| `session_id` | `str \| None` | SSE/Streamable session identifier |
| `metadata` | `dict[str, Any]` | Merged class- and method-level metadata from `@set_metadata` |

```python
def get_metadata(self, key: str, default: Any = None) -> Any
```

Convenience accessor for `self.metadata`.

---

## `@use_interceptors` — Cross-Cutting Concerns

Interceptors wrap the tool call and can observe or modify the result. The
interceptor's `intercept` method receives `McpExecutionContext` and a
`McpCallHandler` whose `handle()` method calls through to the tool.

```python
from lauren import interceptor, use_interceptors
from lauren_mcp import mcp_server, mcp_tool, McpCallHandler, McpExecutionContext
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
        """Search the catalogue."""
        ...
```

### `McpCallHandler`

```python
class McpCallHandler:
    async def handle(self) -> dict: ...
```

Calling `await call_handler.handle()` invokes the next handler in the chain
(which may be another interceptor or the tool method itself). The return value
is the raw `tools/call` result dict. Interceptors may return a modified copy
or a completely new dict.

---

## `@use_exception_handlers` — Domain Exception Mapping

Map domain-specific exceptions to structured `isError: True` responses instead
of opaque `INTERNAL_ERROR` replies:

```python
from lauren import exception_handler, use_exception_handlers
from lauren_mcp import mcp_server, mcp_tool


@exception_handler(ValueError, TypeError)
class ValidationHandler:
    async def catch(self, exc: Exception, ctx) -> dict:
        return {
            "content": [{"type": "text", "text": f"Invalid input: {exc}"}],
            "isError": True,
        }


@mcp_server("/mcp")
class OrderServer:

    @use_exception_handlers(ValidationHandler)
    @mcp_tool()
    async def create_item(self, name: str, qty: int) -> dict:
        """Create a catalogue item.

        Args:
            name: Item name.
            qty: Initial quantity (must be non-negative).
        """
        if qty < 0:
            raise ValueError("qty must be non-negative")
        return {"name": name, "qty": qty}
```

The handler's return value becomes the `tools/call` response body. Returning a
dict with `"isError": True` signals a tool-level error without closing the
transport connection.

---

## `@set_metadata` — Per-Tool Configuration

Metadata set on a method is merged into `McpExecutionContext.metadata` (and
therefore `McpToolContext.metadata`), with method-level values overriding
class-level values for the same key:

```python
from lauren import set_metadata
from lauren_mcp import mcp_server, mcp_tool, McpToolContext


@mcp_server("/mcp")
@set_metadata("env", "production")   # class-level default
class MyServer:

    @set_metadata("env", "staging")   # overrides class-level for this method
    @set_metadata("team", "platform")
    @mcp_tool()
    async def beta_feature(self, ctx: McpToolContext) -> dict:
        """An experimental feature running in staging."""
        env  = ctx.get_metadata("env")   # "staging"
        team = ctx.get_metadata("team")  # "platform"
        return {"env": env, "team": team}

    @mcp_tool()
    async def stable_feature(self, ctx: McpToolContext) -> dict:
        """A stable production feature."""
        env = ctx.get_metadata("env")    # "production" (class-level)
        return {"env": env}
```

---

## Combining multiple decorators

All four decorator types can be stacked on a single method. Evaluation order
(outermost to innermost at runtime):

1. Guards — check access before anything else
2. Interceptors — wrap the full execution (including exception handlers)
3. Exception handlers — catch errors raised by the tool body
4. Tool method — the actual implementation

```python
from lauren import injectable, interceptor, exception_handler
from lauren import use_guards, use_interceptors, use_exception_handlers, set_metadata
from lauren_mcp import mcp_server, mcp_tool, McpExecutionContext, McpCallHandler


@injectable()
class AuthGuard:
    async def can_activate(self, ctx: McpExecutionContext) -> bool:
        token = ctx.headers.get("authorization", "") if ctx.headers else ""
        return token.startswith("Bearer ")


@interceptor()
class AuditInterceptor:
    async def intercept(
        self, ctx: McpExecutionContext, call_handler: McpCallHandler
    ) -> dict:
        print(f"[audit] calling tool, metadata={ctx.metadata}")
        result = await call_handler.handle()
        print(f"[audit] tool finished, isError={result.get('isError', False)}")
        return result


@exception_handler(PermissionError)
class PermissionHandler:
    async def catch(self, exc: Exception, ctx) -> dict:
        return {
            "content": [{"type": "text", "text": f"Permission denied: {exc}"}],
            "isError": True,
        }


@mcp_server("/mcp")
class SecureServer:

    @set_metadata("sensitivity", "high")
    @use_exception_handlers(PermissionHandler)
    @use_interceptors(AuditInterceptor)
    @use_guards(AuthGuard)
    @mcp_tool()
    async def sensitive_op(self) -> dict:
        """A fully guarded, audited, and exception-mapped tool."""
        return {"result": "success"}
```

---

## Transport availability

Guards and interceptors receive `McpExecutionContext`. The fields available
depend on the active transport:

| Transport | `ctx.headers` | `ctx.execution_context` |
|---|---|---|
| WebSocket | WS upgrade headers | `None` |
| Legacy SSE | HTTP request headers | `ExecutionContext` |
| Streamable HTTP | HTTP request headers | `ExecutionContext` |
| stdio | `None` | `None` |

Guards and interceptors must handle `None` headers gracefully. For example,
deny access on stdio when authentication is required:

```python
@injectable()
class AuthGuard:
    async def can_activate(self, ctx: McpExecutionContext) -> bool:
        if ctx.headers is None:
            return False   # deny stdio callers when auth is required
        token = ctx.headers.get("authorization", "")
        return token.startswith("Bearer ")
```

---

## Guards auto-registered as DI providers

Guard, interceptor, and exception-handler classes are automatically registered
as DI providers when they appear in a `@use_*` decorator on a method of an
`@mcp_server` class. There is no need to add them to
`McpServerModule.for_root(providers=[...])`.

---

## Difference from class-level decorators

Class-level `@use_guards` and `@use_interceptors` on `@mcp_server` apply to
the transport controller (the WebSocket `@on_connect` handler or the HTTP
route handlers). They guard the entire connection or every HTTP request.
Method-level decorators apply to individual tool-call dispatch — they run after
the transport has accepted the connection and received the JSON-RPC message.

| Scope | Applies to | Receives |
|---|---|---|
| Class-level `@use_guards` | Transport connection or HTTP handler | Lauren `ExecutionContext` |
| Method-level `@use_guards` | Individual tool / resource / prompt call | `McpExecutionContext` |
| Class-level `@use_interceptors` | Transport handler | Lauren `ExecutionContext` |
| Method-level `@use_interceptors` | Individual tool call | `McpExecutionContext`, `McpCallHandler` |

Use class-level decorators for transport-wide concerns (TLS cert checks,
IP allowlists) and method-level decorators for per-operation access control
(role checks, rate limits per tool).

---

## See also

- [Decorators in Depth](decorators.md) — full reference for `@mcp_tool`, `@mcp_resource`, `@mcp_prompt`
- [MCP Server Guide](mcp-server.md) — complete server guide including class-level guards
- [Server API Reference](../reference/server.md) — `McpExecutionContext`, `McpForbiddenError`, `McpCallHandler`
