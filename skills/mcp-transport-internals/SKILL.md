---
skill: mcp-transport-internals
version: 3.0.0
tags: [mcp, internals, dispatcher, sse, session-store, streamable-http, binding, catalog, registry, subscriptions, security, lauren-mcp]
summary: Understand McpDispatcher routing, CURRENT_BINDING, Streamable HTTP, McpCatalogManager, McpConnectionRegistry, and related transport internals.
---

# Skill: MCP Transport Internals

## When to use this skill

Use this skill when you need to:
- Understand how incoming JSON-RPC messages are routed to handler methods
- Debug per-call context flow (headers, session id, notification channel)
- Understand the Streamable HTTP architecture and SSE resumability
- Work on the WebSocket or SSE transports
- Add a new transport
- Understand the dynamic catalog or connection fan-out architecture

---

## `McpDispatcher` — body-based routing

`McpDispatcher` (`src/lauren_mcp/_server/_dispatcher.py`) is a
`@injectable(Singleton)` — one instance per Lauren app, shared across all
connections.

```python
class McpDispatcher:
    _handlers: dict[str, AsyncHandler]
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

    def cancel(self, request_id: str | int) -> bool:
        task = self._in_flight.pop(request_id, None)
        if task and not task.done():
            task.cancel()
            return True
        return False
```

Routing is body-based (`message.method`), not path-based. All transports
funnel messages through the same dispatcher instance.

---

## `CURRENT_BINDING` contextvar — per-call transport state

Because the dispatcher is a singleton shared by every connection, per-call
state (headers, session id, notification channel, client RPC channel) must
be threaded through without mutating the dispatcher.

`TransportBinding` (`src/lauren_mcp/_server/_binding.py`) is a plain
dataclass:

```python
@dataclass
class TransportBinding:
    headers: Any = None
    execution_context: Any = None   # lauren.ExecutionContext | None
    session_id: str | None = None
    send_notification: SendNotification | None = None  # push notif to client
    client_rpc: ClientRpc | None = None                # server-initiated request
    client_capabilities: ClientCapabilities | None = None
    extras: dict[str, Any] = field(default_factory=dict)

CURRENT_BINDING: ContextVar[TransportBinding | None] = ContextVar(
    "mcp_transport_binding", default=None
)
```

Each transport sets `CURRENT_BINDING` with a `ContextVar.set()` token
**before** calling `dispatcher.dispatch()`. Because `contextvars` propagate
into tasks created from the calling coroutine, the handler task sees the
right binding without any locking:

```python
# inside a transport handler
binding = TransportBinding(
    headers=request.headers,
    session_id=session.session_id,
    send_notification=send_notif,
)
token = CURRENT_BINDING.set(binding)
try:
    response = await self._dispatcher.dispatch(msg)
finally:
    CURRENT_BINDING.reset(token)
```

`McpToolContext` is built from the current binding inside
`make_context_factory()` in `server/_handlers.py`.

In tests, inject a fake binding to simulate transport state without a real
connection (see `mcp-testing` skill Pattern 4).

---

## Streamable HTTP transport (MCP 2025-03-26)

`mcp_streamable_http_controller(base_path)` (`src/lauren_mcp/_server/_streamable.py`)
exposes a single MCP endpoint per the 2025-03-26 spec:

```
POST {base_path}/    — main MCP endpoint; Accept header decides response format
GET  {base_path}/    — optional server-push SSE channel
DELETE {base_path}/  — explicit session teardown
```

**POST semantics:**
- `initialize` — creates a session, returns `mcp-session-id` header
- Requests — dispatch and return either `application/json` (direct) or
  `text/event-stream` (SSE body; notifications stream before the final result)
- Notifications — return `202 Accepted`
- Client responses to server-initiated RPCs — resolve the pending future

**Stateless mode** (`stateless=True`) — no session created or required;
no GET/DELETE endpoints; server-initiated RPCs unavailable.

**SSE body mode** — when the client sends `Accept: text/event-stream` on a
POST, the server streams any notifications generated during the call as SSE
`message` events, then emits the final JSON-RPC response as the last event.

---

## `StreamableSessionStore` — Streamable HTTP session lifecycle

`StreamableSessionStore` (`_server/_streamable.py`) is a `@injectable(Singleton)`.

```python
class StreamableSession:
    session_id: str
    protocol_version: str
    client_capabilities: ClientCapabilities | None
    initialized: bool
    push_queue: asyncio.Queue[str | None]  # feeds the GET push channel
    pending_client_rpcs: dict[str, asyncio.Future[Any]]
    next_srv_id: int
    next_event_id: int   # counter for SSE event IDs when event_store is set

class StreamableSessionStore:
    def create(self, protocol_version: str) -> StreamableSession: ...
    def get(self, session_id: str) -> StreamableSession | None: ...
    def remove(self, session_id: str) -> None: ...
    # remove() drains push_queue (puts None sentinel) and fails pending RPCs
```

---

## `EventStore` / `InMemoryEventStore` — SSE resumability

`EventStore` (`_server/_event_store.py`) is an ABC for persisting SSE events
so that reconnecting clients can replay missed events using `Last-Event-ID`.

```python
class EventStore(ABC):
    async def store_event(self, session_id, event_id, data): ...
    async def replay_events_after(self, session_id, last_event_id, send): ...

class InMemoryEventStore(EventStore):
    def __init__(self, *, max_events: int = 1000): ...
    def evict_session(self, session_id: str) -> None: ...
```

Pass an `EventStore` instance to `mcp_streamable_http_controller`:

```python
from lauren_mcp._server._event_store import InMemoryEventStore
from lauren_mcp._server._streamable import mcp_streamable_http_controller

store = InMemoryEventStore(max_events=500)
controller = mcp_streamable_http_controller("/mcp", event_store=store)
```

When configured, every event emitted on the GET channel receives a
sequential `id:` field (`"{session_id}:{seq}"`). On reconnect the client
sends `Last-Event-ID`; the controller calls `replay_events_after()` to
deliver missed events before resuming the normal queue-drain loop.

---

## WebSocket gateway — `mcp_ws_controller`

`mcp_ws_controller(path)` (`_server/_ws.py`) mounts at `{path}/ws`.

**Lifecycle quirk**: Lauren calls `ws.accept()` only after `@on_connect`
returns. The MCP message loop never returns, so we call `await ws.accept()`
explicitly before entering the loop:

```python
@on_connect
async def handle_connect(self, ws: WebSocket) -> None:
    await ws.accept()           # must be explicit
    await self._message_loop(ws)   # blocks until connection closes
```

Protocol enforcement:
- Requests before `notifications/initialized` → `INVALID_REQUEST (-32600)`
- Unknown methods → `METHOD_NOT_FOUND (-32601)`
- `$/cancelRequest` notification → `dispatcher.cancel(id)`

Each WebSocket connection creates its own `send_notification` closure that
writes JSON frames directly to the socket. The connection key is registered
with `McpConnectionRegistry` on connect and removed on disconnect.

---

## Legacy SSE transport — `mcp_http_sse_controller`

Two endpoints at `base_path`:

```
GET  {base_path}/sse   → opens SSE stream; first event = "endpoint" with session_id
POST {base_path}/      → receives JSON-RPC; "mcp-session-id" header required
```

POST response codes:
- Missing `mcp-session-id` header → 400
- Unknown session_id → 404
- Malformed JSON → 202 (PARSE_ERROR response queued)
- Notification → 202 (no queue write)
- Request → 202 (response JSON queued to SSE stream)

---

## `SseSessionStore` — legacy SSE session registry

`SseSessionStore` (`_server/_session.py`) is a `@injectable(Singleton)`.

```python
class SseSessionStore:
    def create(self, session_id: str) -> asyncio.Queue[str]: ...
    def get(self, session_id: str) -> asyncio.Queue[str] | None: ...
    def remove(self, session_id: str) -> None: ...
```

Sessions created on `GET /sse`, removed in the generator's `finally` block.
In tests: `await app.container.resolve(SseSessionStore)` to create sessions
directly without opening a real SSE stream.

---

## `McpCatalogManager` — dynamic tool/resource/prompt catalog

`McpCatalogManager` (`_server/_catalog.py`) is a `@injectable(Singleton)`.
Holds the live catalog seeded at startup and mutable at runtime.

```python
class McpCatalogManager:
    def register_tool(self, meta, *, on_conflict="replace") -> None: ...
    def unregister_tool(self, name: str) -> bool: ...
    def list_tools(self) -> list[Any]: ...

    def register_resource(self, meta) -> None: ...
    def unregister_resource(self, name: str) -> bool: ...
    def list_resources(self) -> list[Any]: ...

    def register_prompt(self, meta) -> None: ...
    def unregister_prompt(self, name: str) -> bool: ...
    def list_prompts(self) -> list[Any]: ...

    def set_broadcast_fn(self, fn: BroadcastFn | None) -> None: ...
    # Mutations after set_broadcast_fn fire list_changed notifications
```

`_McpHandlerRegistrar` seeds the catalog in `@post_construct`, then calls
`catalog.set_broadcast_fn(registry.broadcast_method)` so subsequent
mutations push `notifications/*/list_changed` to all connections.

---

## `McpConnectionRegistry` — connection fan-out

`McpConnectionRegistry` (`_server/_registry.py`) is a `@injectable(Singleton)`.
Tracks every live connection's send function for broadcast.

```python
class McpConnectionRegistry:
    def register(self, send_fn: SendFn) -> str: ...   # returns opaque key
    def unregister(self, key: str) -> None: ...
    async def broadcast(self, payload: dict[str, Any]) -> None: ...
    async def broadcast_method(self, method: str) -> None: ...
    # broadcast failures on individual connections are logged, not raised
```

---

## `ResourceSubscriptionManager` — per-URI subscriber fan-out

`ResourceSubscriptionManager` (`_server/_subscriptions.py`) is a
`@injectable(Singleton)`.

```python
class ResourceSubscriptionManager:
    def subscribe(self, uri, session_key, send_fn) -> None: ...
    def unsubscribe(self, uri, session_key) -> None: ...
    def unsubscribe_all(self, session_key) -> None: ...   # on disconnect
    def get_subscribers(self, uri) -> dict[str, SendFn]: ...
    async def notify_updated(self, uri: str) -> None: ...
    # broadcasts notifications/resources/updated to all subscribers of uri
```

Trigger update notifications from within your server logic:

```python
from lauren_mcp._server._subscriptions import ResourceSubscriptionManager

@mcp_server("/mcp")
class MyServer:
    def __init__(self, sub_mgr: ResourceSubscriptionManager) -> None:
        self._subs = sub_mgr

    @mcp_tool()
    async def update_config(self, key: str, value: str) -> str:
        # ... do update ...
        await self._subs.notify_updated("config://main")
        return "updated"
```

---

## `TransportSecuritySettings` — DNS-rebinding protection

`TransportSecuritySettings` (`_server/_transport_security.py`) is a frozen
dataclass that configures `McpTransportSecurityGuard`, a Lauren guard applied
to HTTP transports to block DNS-rebinding attacks.

```python
from lauren_mcp._server._transport_security import TransportSecuritySettings

settings = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=["api.example.com", "localhost:8000"],
    allowed_origins=["https://app.example.com"],
)

# Pass to the controller factory
controller = mcp_streamable_http_controller("/mcp", transport_security=settings)
# Or via McpServerModule.for_root — currently no direct kwarg; pass via providers
```

The guard validates:
- `Host` header on every request (all methods)
- `Origin` header on POST requests (cross-origin only)
- `Content-Type: application/json` on POST requests

When `allowed_hosts` is empty, only `localhost` and `127.0.0.1` are allowed.

---

## `_McpBaseRemoteClient` — shared remote client logic

All remote clients (`McpWebSocketClient`, `McpHttpSseClient`,
`McpStreamableHttpClient`) share pending-future request multiplexing:

```python
class _McpBaseRemoteClient(McpClientProtocol, _ClientFeaturesMixin):
    _pending: dict[int, asyncio.Future[Any]]
    _next_id: int

    async def _request(self, method, params=None) -> Any:
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
        elif isinstance(msg, JsonRpcNotification):
            self._route_notification(msg)
        elif isinstance(msg, JsonRpcRequest):
            self._handle_server_request(msg)
```

`McpStdioClient` does **not** inherit from `_McpBaseRemoteClient` — it uses
the same pending-future pattern but reads from subprocess stdout directly.

---

## Adding a new transport

1. Create `src/lauren_mcp/_client/_newtransport.py` extending
   `_McpBaseRemoteClient` (or use the mixin pattern like stdio).
2. Call `self._init_features(**feature_kwargs)` in `__init__`.
3. Implement `connect()` to open the connection and start a read loop that
   calls `self._dispatch_message(raw)` for each received frame.
4. Implement `async def _send_raw(self, obj: dict[str, Any]) -> None` to
   serialise and write.
5. Add `McpServer.newtransport(...)` static method in `_client/_factory.py`.
6. Guard the import: `try: import dep; _AVAIL=True except ImportError: _AVAIL=False`
   and raise informative `ImportError` in `__init__` if unavailable.
7. Add optional extra to `pyproject.toml`.
8. Update `docs/reference/client.md`, `llms-full.txt`, `llms.txt`, and this skill.
