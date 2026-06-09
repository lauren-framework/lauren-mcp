---
skill: mcp-transport-internals
version: 1.0.0
tags: [mcp, internals, dispatcher, sse, session-store, transport, lauren-mcp]
summary: Understand McpDispatcher body-based routing, SseSessionStore, and _McpBaseRemoteClient internals.
---

# Skill: MCP Transport Internals

## When to use this skill

Use this skill when you need to:
- Understand how incoming JSON-RPC messages are routed to handler methods
- Implement a custom transport or extend an existing one
- Debug SSE session lifecycle issues
- Understand the shared base class all three client transports inherit from

---

## `McpDispatcher` — body-based routing

`McpDispatcher` (in `src/lauren_mcp/_server/_dispatcher.py`) is the central routing
engine for the server side. It receives a raw JSON-RPC message (already parsed from the
wire) and dispatches it to the right handler method based on `method`.

```
Incoming message (WebSocket frame / HTTP POST body / stdin line)
    │
    ▼
parse_message(data) → JsonRpcRequest | JsonRpcNotification
    │
    ▼
McpDispatcher.dispatch(message, session)
    │
    ├─ "initialize"         → _handle_initialize()
    ├─ "tools/list"         → _handle_tools_list()
    ├─ "tools/call"         → _handle_tool_call()
    ├─ "resources/list"     → _handle_resources_list()
    ├─ "resources/read"     → _handle_resource_read()
    ├─ "prompts/list"       → _handle_prompts_list()
    ├─ "prompts/get"        → _handle_prompt_get()
    └─ unknown method       → build_error_response(METHOD_NOT_FOUND)
```

### Key design decision: body-based routing

The dispatcher inspects `message.method` — a field in the JSON-RPC body — not the
HTTP path or WebSocket subprotocol. This makes all three transports share the same
dispatcher code with zero duplication.

```python
# src/lauren_mcp/_server/_dispatcher.py (simplified)
class McpDispatcher:
    async def dispatch(
        self,
        message: JsonRpcRequest | JsonRpcNotification,
        session: McpSession,
    ) -> JsonRpcResponse | JsonRpcErrorResponse | None:
        handler = self._handlers.get(message.method)
        if handler is None:
            if isinstance(message, JsonRpcNotification):
                return None  # notifications are fire-and-forget
            return build_error_response(
                message.id,
                McpErrorCode.METHOD_NOT_FOUND,
                f"Method not found: {message.method!r}",
            )
        return await handler(message, session)
```

---

## `SseSessionStore` — HTTP+SSE session management

SSE transport uses a two-request pattern:
1. `GET /mcp/sse` — client opens an SSE stream; the server assigns a `session_id`.
2. `POST /mcp/sse` — client sends JSON-RPC messages with `?session_id=...` in the query.

`SseSessionStore` (in `src/lauren_mcp/_server/_session.py`) maintains the mapping
between session IDs and open SSE response queues.

```
GET /mcp/sse
    │
    ▼
SseSessionStore.create_session()
    │ returns session_id
    ▼
Client stores session_id; server holds an asyncio.Queue for this session

POST /mcp/sse?session_id=abc
    │
    ▼
SseSessionStore.get_queue(session_id)  →  Queue
    │
    ▼
McpDispatcher.dispatch(message, session)
    │
    ▼
response placed in Queue → SSE event written to GET stream
```

Sessions are automatically removed after `session_timeout` seconds of inactivity
(configurable in `McpServerModule.for_root(session_timeout=300.0)`).

---

## `_McpBaseRemoteClient` — shared client base

All three transport clients (`_StdioClient`, `_WsClient`, `_HttpSseClient`) inherit
from `_McpBaseRemoteClient` (in `src/lauren_mcp/_client/`).

The base class provides:
- The MCP handshake sequence (`initialize` → `initialized` notification)
- A pending-request registry: maps `id` → `asyncio.Future`
- `_send(request)` / `_receive(response)` hooks called by subclasses
- `list_tools`, `call_tool`, `list_resources`, `read_resource`, `list_prompts`,
  `get_prompt` implementations that call `_send` and await the future

```python
# Pseudocode — base class skeleton
class _McpBaseRemoteClient:
    _pending: dict[int | str, asyncio.Future]

    async def _send(self, request: JsonRpcRequest) -> None:
        """Implemented by subclass — writes to the transport."""
        raise NotImplementedError

    def _receive(self, data: str | bytes) -> None:
        """Called by subclass when a message arrives from the server."""
        msg = parse_message(data)
        if isinstance(msg, JsonRpcResponse | JsonRpcErrorResponse):
            future = self._pending.pop(msg.id, None)
            if future:
                future.set_result(msg)

    async def call_tool(self, name: str, arguments: dict) -> list[...]:
        future = asyncio.get_event_loop().create_future()
        req_id = self._next_id()
        self._pending[req_id] = future
        await self._send(JsonRpcRequest(
            jsonrpc="2.0", id=req_id,
            method="tools/call",
            params={"name": name, "arguments": arguments},
        ))
        response = await asyncio.wait_for(future, timeout=self._timeout)
        if isinstance(response, JsonRpcErrorResponse):
            raise McpToolError(response.error.message)
        return _parse_tool_result(response.result)
```

### Subclass responsibilities

| Subclass | Transport | `connect()` | `_send()` |
|---|---|---|---|
| `_StdioClient` | subprocess stdin/stdout | `asyncio.create_subprocess_exec` | write to `proc.stdin` |
| `_WsClient` | WebSocket | `websockets.connect()` | `ws.send()` |
| `_HttpSseClient` | HTTP + SSE | `httpx.AsyncClient` + SSE stream | `httpx.post()` |

---

## Adding a new transport

To implement a fourth transport (e.g. Unix socket):

1. Create `src/lauren_mcp/_client/_unix.py` with a class inheriting `_McpBaseRemoteClient`.
2. Override `connect()` to open the Unix socket and start a read loop that calls `_receive()`.
3. Override `_send()` to write JSON-RPC messages to the socket.
4. Add a `McpServer.unix(path)` class method that returns an instance of your new class.
5. Guard the import with a try/except if it depends on a platform-specific module.
6. Add a `unix` extra to `pyproject.toml` if needed.
7. Write unit tests mocking the socket and integration tests against a real server.
