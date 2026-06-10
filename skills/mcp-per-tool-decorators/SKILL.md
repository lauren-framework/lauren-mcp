---
skill: mcp-per-tool-decorators
version: 1.0.0
tags: [mcp, guards, interceptors, exception-handlers, set-metadata, lauren, lauren-mcp]
summary: Apply @use_guards, @use_interceptors, @use_exception_handlers, and @set_metadata to individual @mcp_tool methods for per-tool access control and cross-cutting concerns.
---

# Skill: MCP Per-Tool Decorators

## When to use this skill

Use this skill when you need to:
- Gate individual tools behind role or permission checks
- Add timing, logging, or auditing around specific tools without touching their logic
- Convert domain exceptions (`ValueError`, `PermissionError`, …) to well-formed `isError` responses for specific tools
- Attach metadata to a tool for guards or interceptors to read via `ctx.get_metadata()`

---

## 1. Decorator ordering rule

Lauren decorators (`@use_guards`, `@use_interceptors`, `@use_exception_handlers`,
`@set_metadata`) must be placed **inside** (below) `@mcp_tool()`.
`@mcp_tool()` is the outermost decorator:

```python
@set_metadata("required_role", "admin")   # applied 3rd — outermost
@use_guards(RoleGuard)                     # applied 2nd
@mcp_tool()                                # applied 1st — innermost
async def delete_all(self) -> dict: ...
```

**Why**: Python applies decorators bottom-up (innermost first).  `@mcp_tool()`
calls `_read_method_decorators(fn)` on the raw function, so Lauren must have
already set its attributes on `fn` before `@mcp_tool()` runs.  If `@mcp_tool()`
were innermost, the Lauren attributes would not yet be present and the guards /
interceptors / metadata would be silently ignored.

> **Tip**: think "Lauren decorators dress the method; `@mcp_tool()` reads what
> they wrote."  The reader (`@mcp_tool`) goes outermost.

---

## 2. `@use_guards(GuardClass)` on `@mcp_tool`

Guards are called **before** the tool method is invoked.  A guard returns `bool`:
`True` allows the call; `False` (or any raised exception) rejects it.

```python
from lauren import injectable, use_guards
from lauren_mcp import McpExecutionContext, mcp_server, mcp_tool

@injectable()
class AdminGuard:
    async def can_activate(self, ctx: McpExecutionContext) -> bool:
        role = ctx.get_metadata("required_role")
        # In real code: inspect ctx.headers for a JWT or API key
        return role != "admin"   # placeholder — replace with real auth

@mcp_server("/mcp")
class MyServer:
    @set_metadata("required_role", "admin")
    @use_guards(AdminGuard)
    @mcp_tool()
    async def admin_only(self) -> dict:
        return {"secret": "data"}
```

**Guard receives `McpExecutionContext`** (not `McpToolContext`).
`McpExecutionContext` is available before the tool method is entered; it
contains only dispatch-time information.  `McpToolContext` is injected into
the tool method itself and carries richer runtime capabilities (`sample()`,
`log()`, `report_progress()`).

**Rejection** raises `McpForbiddenError` internally, which the dispatcher
converts to an `INTERNAL_ERROR` JSON-RPC response with
`data.type = "FORBIDDEN"` and `data.guard = "<GuardClassName>"`.  The
WebSocket or SSE session is **not** closed; subsequent calls continue normally.

**`ctx.headers` availability**: populated from the current transport binding.
For WebSocket and Streamable HTTP, `ctx.headers` is a dict of the HTTP headers
from the upgrade / POST request.  For stdio, `ctx.headers` is `None`.

**Guard auto-registration**: you do not need to add guard classes to
`providers=[]` in `McpServerModule.for_root()`.  The module registers them
automatically.

Multiple guards on one method run in order (top to bottom in source order);
the first rejection wins:

```python
@use_guards(AuthGuard, RateLimitGuard)
@mcp_tool()
async def limited_tool(self) -> dict: ...
```

---

## 3. `@use_interceptors(InterceptorClass)` on `@mcp_tool`

Interceptors wrap the tool call.  They receive `(ctx, call_handler)` and must
call `await call_handler.handle()` to advance the chain.  The return value is
the result dict (`{"content": [...], "isError": bool, "structuredContent": ...}`).

```python
from lauren import interceptor, use_interceptors
from lauren_mcp import McpCallHandler, McpExecutionContext

@interceptor()
class AuditInterceptor:
    async def intercept(self, ctx: McpExecutionContext, call_handler: McpCallHandler) -> dict:
        result = await call_handler.handle()
        print(f"[AUDIT] {ctx.tool_name} -> isError={result.get('isError')}")
        return result

@interceptor()
class TimingInterceptor:
    async def intercept(self, ctx: McpExecutionContext, call_handler: McpCallHandler) -> dict:
        import time
        start = time.perf_counter()
        result = await call_handler.handle()
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        sc = result.get("structuredContent")
        if isinstance(sc, dict):
            sc["_elapsed_ms"] = elapsed_ms
        return result
```

**Composition — outside-in ordering**: the first interceptor listed in
`@use_interceptors(A, B)` is outermost (runs first and last); the last is
innermost (closest to the tool method).

```python
@use_interceptors(AuditInterceptor, TimingInterceptor)
@mcp_tool()
async def measured_tool(self) -> dict:
    # call order: AuditInterceptor → TimingInterceptor → method → TimingInterceptor → AuditInterceptor
    return {"value": 42}
```

`McpCallHandler.handle()` returns `dict[str, Any]`, not a `Response` object.
Do not call `.status_code` or `.headers` on it.

Interceptors are auto-registered as DI providers — no explicit `providers=[]`
needed.

---

## 4. `@use_exception_handlers(HandlerClass)` on `@mcp_tool`

Exception handlers catch domain exceptions that escape the tool method (and
any interceptors) and convert them to well-formed `isError` result dicts
instead of `INTERNAL_ERROR` JSON-RPC responses.

Decorate the handler class with `@exception_handler(ExcType, ...)` from Lauren
and implement `catch(exc, ctx) -> dict | None`.  Return `None` to pass to the
next handler; return a dict to stop the chain.

```python
from lauren import exception_handler, use_exception_handlers

@exception_handler(ValueError)
class BadValueHandler:
    async def catch(self, exc: Exception, ctx: object) -> dict:
        return {
            "content": [{"type": "text", "text": f"Invalid input: {exc}"}],
            "isError": True,
            "structuredContent": {"error_type": "ValueError", "message": str(exc)},
        }

@exception_handler(PermissionError)
class PermissionHandler:
    async def catch(self, exc: Exception, ctx: object) -> dict:
        return {
            "content": [{"type": "text", "text": "Permission denied"}],
            "isError": True,
        }

@mcp_server("/mcp")
class MyServer:
    @use_exception_handlers(BadValueHandler, PermissionHandler)
    @mcp_tool()
    async def create_item(self, qty: int) -> dict:
        if qty <= 0:
            raise ValueError("qty must be positive")
        return {"created": qty}
```

**Matching semantics**:
- `catch` is called only when `isinstance(exc, handled_types)` is true (the
  exception types declared in `@exception_handler(...)`).
- Return `None` → no match, try next handler.
- If no handler matches or all return `None`, the exception propagates as an
  `INTERNAL_ERROR` JSON-RPC response.

Multiple handlers are tried in declaration order (left to right in
`@use_exception_handlers(A, B)`):

```python
@use_exception_handlers(PermissionHandler, BadValueHandler)
@mcp_tool()
async def multi_handler_tool(self, mode: str) -> dict: ...
```

---

## 5. `@set_metadata(key, value)` on `@mcp_tool`

Per-method metadata is visible to guards and interceptors via
`ctx.get_metadata(key)`.  Method-level `@set_metadata` wins over class-level
`@set_metadata` for the same key.

```python
from lauren import set_metadata, use_guards
from lauren_mcp import McpExecutionContext

@injectable()
class RoleGuard:
    async def can_activate(self, ctx: McpExecutionContext) -> bool:
        required = ctx.get_metadata("required_role", "user")
        user_role = _resolve_role_from_headers(ctx.headers)  # your auth logic
        return user_role == required

@set_metadata("app", "shop")        # class-level — applies to all tools
@mcp_server("/mcp")
class ShopServer:
    @set_metadata("required_role", "admin")   # method-level — wins for same key
    @use_guards(RoleGuard)
    @mcp_tool()
    async def admin_report(self) -> dict: ...

    @set_metadata("required_role", "user")
    @use_guards(RoleGuard)
    @mcp_tool()
    async def user_report(self) -> dict: ...
```

Both guards receive `ctx.get_metadata("app") == "shop"` (from the class)
**and** the respective `required_role` value from the method.

---

## 6. `@use_middlewares` on `@mcp_tool` raises `TypeError`

Applying `@use_middlewares` to an `@mcp_tool` (or `@mcp_resource` /
`@mcp_prompt`) method raises `TypeError` at decoration time:

```
TypeError: @use_middlewares cannot be applied to 'delete_all' — MCP tool,
resource, and prompt methods have no HTTP request/response lifecycle.
Apply @use_middlewares to the @mcp_server class or a transport controller instead.
```

MCP tool methods do not go through the HTTP middleware stack (they receive
JSON-RPC parameters, not HTTP requests).  Apply `@use_middlewares` to the
`@mcp_server` class to gate the entire transport, or to a transport controller
for HTTP-level concerns.

---

## 7. Complete example — all four decorators on one tool

```python
from __future__ import annotations

from lauren import (
    LaurenFactory,
    exception_handler,
    injectable,
    interceptor,
    module,
    set_metadata,
    use_exception_handlers,
    use_guards,
    use_interceptors,
)
from lauren.testing import TestClient, WsTestClient
from lauren_mcp import (
    McpCallHandler,
    McpExecutionContext,
    McpServerModule,
    mcp_server,
    mcp_tool,
)


@injectable()
class AuthGuard:
    async def can_activate(self, ctx: McpExecutionContext) -> bool:
        return ctx.get_metadata("public", False) is True


@interceptor()
class LogInterceptor:
    async def intercept(self, ctx: McpExecutionContext, ch: McpCallHandler) -> dict:
        print(f"-> {ctx.tool_name}")
        result = await ch.handle()
        print(f"<- {ctx.tool_name} isError={result.get('isError')}")
        return result


@exception_handler(ValueError)
class InputErrorHandler:
    async def catch(self, exc: Exception, ctx: object) -> dict:
        return {
            "content": [{"type": "text", "text": f"Input error: {exc}"}],
            "isError": True,
        }


@mcp_server("/mcp")
class ExampleServer:
    @set_metadata("public", True)
    @use_exception_handlers(InputErrorHandler)
    @use_interceptors(LogInterceptor)
    @use_guards(AuthGuard)
    @mcp_tool()
    async def public_action(self, qty: int) -> dict:
        """Perform a public action.

        Args:
            qty: Must be positive.
        """
        if qty <= 0:
            raise ValueError("qty must be positive")
        return {"done": True, "qty": qty}


@module(imports=[McpServerModule.for_root(ExampleServer)])
class AppModule:
    pass

app = LaurenFactory.create(AppModule)
```

---

## 8. Testing pattern

```python
import asyncio
import pytest
from lauren import LaurenFactory, injectable, module, use_guards
from lauren.testing import TestClient, WsTestClient
from lauren_mcp import McpExecutionContext, McpServerModule, mcp_server, mcp_tool


@injectable()
class DenyGuard:
    async def can_activate(self, ctx: McpExecutionContext) -> bool:
        return False


@mcp_server("/mcp")
class GuardedServer:
    @use_guards(DenyGuard)
    @mcp_tool()
    async def protected(self) -> str:
        return "unreachable"

    @mcp_tool()
    async def open_tool(self) -> str:
        return "hello"


@pytest.fixture(scope="module")
def app():
    @module(imports=[McpServerModule.for_root(GuardedServer)])
    class AppMod:
        pass

    _app = LaurenFactory.create(AppMod)
    TestClient(_app)   # triggers @post_construct — required before WsTestClient
    return _app


async def test_guard_rejection(app):
    async with WsTestClient(app).connect("/mcp/ws") as ws:
        await ws.send_json({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "t", "version": "1"}},
        })
        await asyncio.wait_for(ws.receive_json(), timeout=3.0)
        await ws.send_json({"jsonrpc": "2.0", "method": "notifications/initialized"})

        await ws.send_json({
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "protected", "arguments": {}},
        })
        resp = await asyncio.wait_for(ws.receive_json(), timeout=3.0)

    assert "error" in resp
    assert resp["error"]["code"] == -32603           # INTERNAL_ERROR
    assert resp["error"]["data"]["type"] == "FORBIDDEN"
    assert resp["error"]["data"]["guard"] == "DenyGuard"


async def test_open_tool_unaffected(app):
    """Guard on one tool does not affect other tools."""
    async with WsTestClient(app).connect("/mcp/ws") as ws:
        await ws.send_json({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "t", "version": "1"}},
        })
        await asyncio.wait_for(ws.receive_json(), timeout=3.0)
        await ws.send_json({"jsonrpc": "2.0", "method": "notifications/initialized"})

        await ws.send_json({
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "open_tool", "arguments": {}},
        })
        resp = await asyncio.wait_for(ws.receive_json(), timeout=3.0)

    assert resp["result"]["content"][0]["text"] == "hello"
```

**Key testing notes**:
- Guards declared with `@injectable()` are auto-registered; no `providers=[...]`
  needed in `McpServerModule.for_root()`.
- `TestClient(app)` **must** be called after `LaurenFactory.create(app)` to
  fire `@post_construct` hooks that register MCP handlers.  Omitting this call
  causes `McpCallError: Method not found: 'initialize'`.
- Guard rejection returns `"error"` at the JSON-RPC level (not `"result"` with
  `"isError": True`).  Exception-handler output returns `"result"` with
  `"isError": True`.
