---
skill: mcp-transport-internals
version: 2.0.0
tags: [mcp, internals, dispatcher, sse, session-store, transport, ws, lauren-mcp]
summary: Understand McpDispatcher body-based routing, SseSessionStore, the WS gateway, and _McpBaseRemoteClient.
---

# Skill: MCP Transport Internals

## When to use this skill

Use this skill when you need to:
- Understand how incoming JSON-RPC messages are routed to handler methods
- Debug SSE session lifecycle issues
- Understand the shared base class all remote client transports inherit from
- Work on the WebSocket gateway or SSE controller

---

## `McpDispatcher` — body-based routing

`McpDispatcher` (`src/lauren_mcp/_server/_dispatcher.py`) is the central routing
engine.  It is a `@injectable(scope=Scope.SINGLETON)`.

```python
# Simplified
class McpDispatcher:
    _handlers: dict[str, AsyncHandler]  # method_name → coroutine
    _in_flight: dict[str | int, asyncio.Task[Any]]

    def register(self, method: str, handler: AsyncHandler) -> None: ...

    async def dispatch(self, request: JsonRpcRequest) -> JsonRpcResponse | JsonRpcErrorResponse:
        handler = self._handlers.get(request.method)
        if handler is None:
            return build_error_response(request.id, McpErrorCode.METHOD_NOT_FOUND, ...)
        task = asyncio.create_task(handler(params))
        self._in_flight[request.id] = task
        result = await task
        return JsonRpcResponse(id=request.id, result=result)

    def cancel(self, request_id: str | int) -> bool: ...
```

Handlers are registered by `_McpHandlerRegistrar._register_handlers()` in its
`@post_construct` hook.  That hook runs when `TestClient(app)` or the first real
request triggers the Lauren lifecycle.

**Key**: routing is body-based (`message.method`), not path-based.

---

## WebSocket gateway — `mcp_ws_controller`

`mcp_ws_controller(path)` (`src/lauren_mcp/_server/_ws.py`) returns a Lauren
`@ws_controller` class mounted at `{path}/ws`.

**Lifecycle quirk**: Lauren calls `ws.accept()` only after `@on_connect` returns.
Our message loop never returns, so we call `await ws.accept()` explicitly before
entering the loop:

```python
@on_connect
async def handle_connect(self, ws: WebSocket) -> None:
    await ws.accept()           # must be explicit — Lauren can't do it for us
    await self._message_loop(ws)  # blocks until connection closes

async def _message_loop(self, ws: Any) -> None:
    while True:
        raw: str = await ws.receive_text()   # blocks on each frame
        await self._handle_frame(ws, raw)
```

This also prevents Lauren's built-in event-routing loop from starting (MCP uses
raw JSON-RPC frames, not Lauren's `event`-keyed dispatch format).

Protocol enforcement:
- Requests before `notifications/initialized` → `INVALID_REQUEST` (-32600)
- Unknown methods → `METHOD_NOT_FOUND` (-32601)
- `$/cancelRequest` notification → `dispatcher.cancel(id)`

---

## SSE transport — two-endpoint pattern

`mcp_http_sse_controller(base_path)` (`src/lauren_mcp/_server/_sse.py`) exposes:

```
GET  {base_path}/sse   → opens SSE stream; sends "endpoint" event with session_id
POST {base_path}/      → receives JSON-RPC; identified by "mcp-session-id" header
```

```python
# GET /mcp/sse — first event carries the session_id
yield ServerSentEvent(event="endpoint", data=json.dumps({"session_id": session_id}))
# subsequent events carry JSON-RPC responses from the queue
while True:
    payload = await queue.get()
    yield ServerSentEvent(event="message", data=payload)

# POST /mcp/ — dispatches and pushes response to queue
session_id = request.headers.get("mcp-session-id")   # header, not query param
queue = self._sessions.get(session_id)                # None → 404
response = await self._dispatcher.dispatch(msg)
await queue.put(response.to_json())
return Response(body=b"", status=202)
```

POST responses:
- Missing `mcp-session-id` header → 400
- Unknown session_id → 404
- Malformed JSON → 202 (PARSE_ERROR response queued)
- Notification → 202 (no queue write)
- Request → 202 (response JSON queued)

---

## `SseSessionStore` — session registry

`SseSessionStore` (`src/lauren_mcp/_server/_session.py`) is a `@injectable(Singleton)`.

```python
class SseSessionStore:
    _queues: dict[str, asyncio.Queue[str]]

    def create(self, session_id: str) -> asyncio.Queue[str]: ...
    def get(self, session_id: str) -> asyncio.Queue[str] | None: ...
    def remove(self, session_id: str) -> None: ...
```

Sessions are created in `GET /sse` and removed in the generator's `finally` block.
In tests, resolve the store with `await app.container.resolve(SseSessionStore)` to
create sessions manually without opening an SSE stream.

---

## `_McpBaseRemoteClient` — shared client logic

All remote clients (`McpWebSocketClient`, `McpHttpSseClient`) inherit from
`_McpBaseRemoteClient` (`src/lauren_mcp/_client/_base_remote.py`).

```python
class _McpBaseRemoteClient(McpClientProtocol):
    _pending: dict[int, asyncio.Future[Any]]  # id → future
    _next_id: int

    async def _request(self, method: str, params: Any = None) -> Any:
        req_id = self._next_id; self._next_id += 1
        fut = loop.create_future()
        self._pending[req_id] = fut
        await self._send_raw({"jsonrpc":"2.0","id":req_id,"method":method,"params":params})
        return await fut

    def _dispatch_message(self, raw: str) -> None:
        msg = parse_message(raw)
        if isinstance(msg, (JsonRpcResponse, JsonRpcErrorResponse)):
            fut = self._pending.pop(msg.id, None)
            if fut and not fut.done():
                if isinstance(msg, JsonRpcResponse): fut.set_result(msg.result)
                else: fut.set_exception(McpCallError(msg.error.message, msg.error.code))
```

`list_tools()`, `call_tool()` etc. all call `await self._request(...)`.

`McpStdioClient` is separate and does NOT inherit from `_McpBaseRemoteClient` — it
uses the same pending-future pattern but reads from subprocess stdout directly.

---

## Adding a new transport

1. Create `src/lauren_mcp/_client/_newtransport.py` extending `_McpBaseRemoteClient`.
2. Implement `connect()` to open the connection and start a read loop that calls
   `self._dispatch_message(raw)` for each received frame.
3. Implement `_send_raw(obj: dict[str, Any]) -> None` to serialise and write.
4. Add `McpServer.newtransport(...)` in `_client/_factory.py`.
5. Guard with `try: import ...; _AVAIL=True except ImportError: _AVAIL=False` and
   raise informative `ImportError` in `__init__` if not available.
6. Add optional extra to `pyproject.toml`.
7. Update `docs/reference/client.md`, `llms-full.txt`, `llms.txt`, and this skill.
