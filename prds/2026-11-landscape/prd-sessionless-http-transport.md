# PRD — Sessionless Streamable HTTP transport

**Status:** Draft
**Date:** 2026-11-26
**Scope:** `src/lauren_mcp/_server/_streamable.py`, `src/lauren_mcp/_server/_dispatcher.py`, `src/lauren_mcp/_server/_handshake.py`, `src/lauren_mcp/server/_module.py`, `src/lauren_mcp/_server/_event_store.py`
**Priority:** P2
**Issue:** _pending_

---

## 1. Problem Statement

`lauren-mcp` 1.0.0 implements Streamable HTTP the way `2025-03-26` … `2025-11-25` defined it: a client
calls `initialize`, the server mints a session id, and every later request carries it in `Mcp-Session-Id`.
The `2026-07-28` revision deletes that mechanism — the header is gone from the schema (E-20),
`tools/list`/`resources/list`/`prompts/list` no longer vary per connection, and per-request `_meta` carries
what the handshake used to carry (E-22). The code below still *requires* the header on every POST, so a
modern-era client cannot complete its first request.

This PRD adds a sessionless path for modern-era requests **without touching the legacy path**, because the
spec's own policy keeps the prior revision reachable for at least 12 months (E-41).

### 1.1 A modern client's first `tools/list` is answered with `400 Missing 'mcp-session-id' header`

The session requirement is a hard gate in the POST handler, ahead of any method dispatch:

```python
# src/lauren_mcp/_server/_streamable.py  lines 335-344
        def _require_session(self, request: Request) -> StreamableSession | Response:
            session_id = request.headers.get(_SESSION_HEADER)
            if not session_id:
                return _json_response(
                    json.dumps({"error": f"Missing '{_SESSION_HEADER}' header"}), status=400
                )
            session = self._sessions.get(session_id)
            if session is None:
                return _json_response(
                    json.dumps({"error": f"Unknown session: {session_id!r}"}), status=404
                )
```

with `_SESSION_HEADER = "mcp-session-id"` (`_streamable.py:41`). A modern host sends
`{"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}}}`
and no session header — and there is no value it *could* send, because the field was removed from the
schema (E-20). Guessing an id only changes the failure to `404 Unknown session` (line 344). The assumption
is not a single string: `mcp-session-id` appears in **4** source files (E-241), because the client
transport (`_client/_streamable.py`, `_client/_sse.py`) and the legacy SSE server transport
(`_server/_sse.py`) share it.

### 1.2 Client capabilities only exist inside the session object

The handshake is where `protocolVersion` and `capabilities` enter the process, once, into a per-session
object:

```python
# src/lauren_mcp/_server/_streamable.py  lines 315-322
        async def _handle_initialize(self, request: Request, msg: JsonRpcRequest) -> Response:
            params = msg.params if isinstance(msg.params, dict) else {}
            client_version = params.get("protocolVersion") or (
                request.headers.get(_PROTOCOL_HEADER) or ""
            )
            version = negotiate_version(client_version)
            session = self._sessions.create(version)
            raw_caps = params.get("capabilities") or {}
```

`StreamableSession` (`:47-60`) then carries `session_id`, `protocol_version`, `client_capabilities`,
`initialized`, `push_queue`, `pending_client_rpcs`, `next_srv_id` and `next_event_id`. Modern requests
carry the same three facts in `params._meta` instead (E-22) — and with no session there is nowhere to keep
them, because the request type has no `_meta` field at all:

```python
# src/lauren_mcp/_types.py  lines 20-26
class JsonRpcRequest:
    """A JSON-RPC 2.0 request (has both method and id)."""

    method: str
    params: dict[str, Any] | list[Any] | None = None
    id: str | int | None = None
    jsonrpc: str = "2.0"
```

`_meta` therefore survives only as an untyped key inside `params`, and nothing reads it. A sessionless
handler must bind request scope from `params["_meta"]` at the transport boundary and hand it down.

### 1.3 The GET channel and `Last-Event-ID` bake a session into the wire protocol

The push channel exists to serve one session, and both the queue and the event ids are keyed by it:

```python
# src/lauren_mcp/_server/_streamable.py  lines 458, 476-477, 505-506
        @get("/")
        ...
            last_event_id: str | None = request.headers.get("last-event-id")
            queue = session.push_queue
        ...
                            eid = f"{session.session_id}-{session.next_event_id}"
                            session.next_event_id += 1
```

The replay store is keyed the same way — `store_event(session_id, …)` at `_event_store.py:25`,
`replay_events_after(session_id, last_event_id)` at `:39`, `InMemoryEventStore(max_events=100)` at `:74`.
`2026-07-28` removes SSE resumability (E-28) and replaces the GET channel with the `subscriptions/listen`
request (E-23). `Last-Event-ID` appears in **2** source files today (E-244).

### 1.4 Sessions make every multi-replica deployment sticky

`StreamableSessionStore` is a process-local dict (`self._sessions: dict[str, StreamableSession] = {}`,
`:68`) filled with locally minted ids (`session_id = secrets.token_urlsafe(16)`, `:71`). An id minted by
replica A is unknown to replica B, so a deployment behind a load balancer must pin each client to one pod —
sticky sessions that break on rollout and autoscaling. Details in §4.6.

## 2. Goals

1. **G1 — Era detection from `_meta`.** A POST whose `params._meta` declares
   `io.modelcontextprotocol/protocolVersion` at `2026-07-28` or later is served with **no session**: no
   `Mcp-Session-Id` read, minted, returned or required (E-20, E-22).
2. **G2 — One pure routing function.** `resolve_request_era(msg, headers) -> "legacy" | "modern"`,
   unit-tested with no HTTP layer involved.
3. **G3 — Legacy path untouched.** Any request carrying `Mcp-Session-Id`, or omitting `_meta`, behaves
   exactly as at `HEAD`: `400` at `:339`, `404` at `:344`, headers at `:332`, GET channel at `:458`,
   DELETE teardown at `:522`.
4. **G4 — Per-request client context.** For modern requests `protocolVersion`, `clientInfo` and
   `clientCapabilities` from `_meta` reach handlers through `TransportBinding`, not through a session.
5. **G5 — GET is era-gated.** Modern `GET /mcp` returns `405` naming `subscriptions/listen` (E-23);
   legacy `GET` still opens the SSE push channel.
6. **G6 — DELETE stays legacy-only.** Modern `DELETE` returns `405`; legacy `DELETE` still tears down and
   drains the push queue (`:82`). No session exists in the modern path, so there is nothing to destroy.
7. **G7 — Honest resumability story.** The removed `Last-Event-ID` replay is documented as a
   spec-mandated loss (E-28), with the concrete failure and the mitigation (§4.5), not silently dropped.
8. **G8 — No new runtime dependency.** `asyncio` and `dataclasses` only; the two-dependency posture
   (`lauren`, `anyio`) holds.

**Why P2:** no fielded host regresses — every real client still negotiates a legacy revision, so nothing
breaks. But sessionless Streamable HTTP is the revision both SDKs ship, and a modern host gets a `400` on
its first request (E-20, E-22). Missing capability that narrows reach, which is exactly the brief's P2
test.

### Acceptance criteria

- [ ] `grep -n 'def resolve_request_era' src/lauren_mcp/_server/_streamable.py` returns exactly one hit.
- [ ] `pytest tests/unit/test_request_era.py -q` passes (no `_meta` → legacy; `2025-11-25` in `_meta` → legacy; `2026-07-28` in `_meta` → modern; `2026-07-28` **plus** `Mcp-Session-Id` → legacy with a warning).
- [ ] `pytest tests/integration/test_sessionless_streamable.py -q` passes (modern `tools/list` with no session header returns `200` and the response carries no `mcp-session-id`).
- [ ] `grep -c 'mcp-session-id' src/lauren_mcp/_server/_streamable.py` is unchanged from `HEAD` — the legacy constant and its call sites survive (E-41).
- [ ] `curl -sD- -o/dev/null -X POST http://127.0.0.1:8000/mcp -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28"}}}'` shows `HTTP/1.1 200` and no `mcp-session-id` header.
- [ ] The same `curl` **without** `_meta` still shows `HTTP/1.1 400` with body `{"error": "Missing 'mcp-session-id' header"}`.
- [ ] `curl -s -o/dev/null -w '%{http_code}' -X GET http://127.0.0.1:8000/mcp -H 'accept: text/event-stream' -H 'mcp-protocol-version: 2026-07-28'` prints `405`.
- [ ] `pytest tests/integration/test_streamable*.py -q` passes unchanged (legacy suite, no regression).

## 3. Non-Goals

- **Deleting the legacy path.** Not here and not in this release train: the prior revision stays supported
  for ≥12 months (E-41). `_SESSION_HEADER`, `StreamableSession`, `StreamableSessionStore`, the GET channel
  and DELETE teardown all stay.
- **Implementing `subscriptions/listen`.** E-23 makes it the replacement for the GET channel, but capability
  advertisement, filters and notification envelope belong to the result-envelope work. This PRD reserves
  the method name, answers it with a clear error while unimplemented, and states the transport contract.
- **Changing the client transports.** `_client/_streamable.py` keeps speaking the legacy era; a
  sessionless *client* mode is a separate PRD.
- **Reshaping `EventStore`.** It stays keyed by `session_id` while legacy traffic exists.
- **Dispatch or DI changes.** `tools/call` routing and handler registration are untouched.
- **A second route.** One `/mcp` endpoint serves both eras; no `/mcp/modern`.
- **New dependencies or extras.** No `[project.optional-dependencies]` entry.

## lauren-mcp Advantages

Three things here are already modern-shaped, so the sessionless path is a delta rather than a rewrite.

**1. One POST endpoint, already.** `mcp_streamable_http_controller` mounts `@post("/")`, `@get("/")` and
`@delete("/")` on a single path (`_streamable.py:167`, `:458`, `:522`), and `_module.py` appends exactly
one controller for the streamable transport:

```python
# src/lauren_mcp/server/_module.py  lines 270-271
        if effective_transport in ("streamable", "all"):
            controllers.append(mcp_streamable_http_controller(path, source=server_cls))
```

The `2026-07-28` transport also keeps one endpoint for all traffic: no route has to move, and the era
branch lives inside one handler instead of behind a second URL — which an SDK-per-revision approach would
have to rebuild on every bump.

**2. `TransportSecuritySettings` is already wired, and it is the spec's own MUST.** `Origin` validation to
defeat DNS rebinding is mandated by Streamable HTTP (E-169b) and already implemented as an opt-in guard:

```python
# src/lauren_mcp/_server/_streamable.py  lines 576-579
    # Apply transport security guard if configured.
    if transport_security is not None:
        _guard = McpTransportSecurityGuard()
        _guard.configure(...)
```

`transport_security: TransportSecuritySettings | None = None` is a factory kwarg (`:106`). For the
sessionless path this stops being optional: with no session tying a request to a prior handshake, every
modern request is gated by its headers alone (§4.7).

**3. A session-free execution path already exists.** The controller takes `stateless: bool = False`
(`:104`) and can dispatch to a handler that runs with no session:

```python
# src/lauren_mcp/_server/_streamable.py  lines 263-267
            binding = TransportBinding(
                headers=request.headers,
                execution_context=execution_context or ExecutionContext(request=request),
                session_id=None,
                send_notification=_send_notification,
```

with server-to-client RPCs raising explicitly instead of hanging (`:257-261`). The dispatcher underneath is
equally session-blind — `async def dispatch(self, request: JsonRpcRequest)` takes only the message
(`_dispatcher.py:101`), which is precisely why `tools/list` can be era-invariant. What is missing for the
modern era is not a session-free path but a **per-request capability carrier** and an **era switch** in
front of it: both small and local.

**Honest note.** The session machinery is not gratuitous debt to be praised away: for the legacy era it is
load-bearing, because server-initiated sampling and elicitation depend on `pending_client_rpcs`
(`:57`). The advantage is that both eras share one endpoint, one security guard and one dispatcher.

## 4. Design

### 4.1 Era detection — one pure function in front of the POST handler

The only modern-only input is `params._meta` (E-22), so era resolution is a pure function of the parsed
message plus the raw headers. The tie-break is deliberate: **a present `Mcp-Session-Id` always means
legacy**, even when `_meta` claims a modern revision — a client sending both is mid-migration and the
2025 semantics it already has are the safe interpretation.

```python
# src/lauren_mcp/_server/_streamable.py  (new, immediately after line 43)
MODERN_MIN_REVISION = "2026-07-28"
_META_PROTOCOL_VERSION = "io.modelcontextprotocol/protocolVersion"
_META_CLIENT_INFO = "io.modelcontextprotocol/clientInfo"
_META_CLIENT_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
_METHOD_SUBSCRIPTIONS_LISTEN = "subscriptions/listen"


@dataclass(frozen=True)
class RequestMeta:
    """Per-request replacement for the initialize handshake (2026-07-28, E-22)."""

    protocol_version: str
    client_info: Mapping[str, Any]
    client_capabilities: Mapping[str, Any]
    era: str  # "legacy" | "modern"


def resolve_request_era(msg: JsonRpcRequest, headers: Mapping[str, str]) -> str:
    """Return "modern" when the request declares a >= 2026-07-28 revision in params._meta.

    A request carrying Mcp-Session-Id is always legacy: session ids do not exist in the
    modern revision (E-20), so a client sending both must keep the 2025 semantics it has.
    """
    if headers.get(_SESSION_HEADER):
        return "legacy"
    params = msg.params if isinstance(msg.params, dict) else {}
    meta = params.get("_meta")
    if not isinstance(meta, dict):
        return "legacy"
    declared = meta.get(_META_PROTOCOL_VERSION)
    if not isinstance(declared, str):
        return "legacy"
    return "modern" if declared >= MODERN_MIN_REVISION else "legacy"
```

`parse_request_meta(msg)` reads the same dict and returns a frozen
`RequestMeta(protocol_version, client_info, client_capabilities, era="modern")`, or `None` when `_meta` is
absent (the caller is then on the legacy path and never asks for it).

String comparison is safe here because MCP revisions are zero-padded `YYYY-MM-DD` literals — the same
assumption `_mcp_version.SUPPORTED` already makes (`LATEST = "2025-11-25"` at `_mcp_version.py:5`, the
supported set at `:7`; `2026-07-28` is absent from it, which is the gap this PRD closes). Unknown `_meta`
keys are ignored, not rejected: the modern schema adds keys over time and a transport must not fail a
`tools/call` because a host sent a hint it does not understand.

### 4.2 The sessionless request path reuses the existing stateless handler

`handle_post` gains one branch ahead of the session lookup, beside the existing one at `:183`:

```python
# src/lauren_mcp/_server/_streamable.py  (new sibling of lines 183-184)
            if resolve_request_era(msg, request.headers) == "modern":
                return await _handle_modern(request, msg)
```

`_handle_modern` is a thin wrapper over the existing stateless body (`:232`), which already builds a
`TransportBinding` with `session_id=None` (`:266`):

```python
        async def _handle_modern(self, request: Request, msg: JsonRpcRequest) -> Response | EventStream:
            meta = parse_request_meta(msg)   # never None here: era == "modern" implies _meta
            if msg.method == "initialize":
                # initialize was removed in 2026-07-28; answering it would recreate a session
                return _json_response(
                    build_error_response(
                        None, McpErrorCode.METHOD_NOT_FOUND, "initialize was removed in 2026-07-28"
                    ),
                    status=404,
                )
            return await _handle_stateless(request, msg, request_meta=meta)
```

`_handle_stateless` gains a keyword-only `request_meta` and forwards it onto the binding as one extra
field next to `session_id=None`:

```python
# src/lauren_mcp/_server/_streamable.py  lines 263-267 (existing call, one field added)
            binding = TransportBinding(
                headers=request.headers,
                execution_context=...,
                session_id=None,
                request_meta=meta,   # NEW: replaces the session's protocol_version/client_capabilities
                send_notification=_send_notification,
```

Two invariants follow, and they are the point of the revision: **no `Mcp-Session-Id` is ever emitted on
the modern path** (the header is set only in `_handle_initialize` at `:332`, which the modern path never
reaches), and **every replica answers identically**, because `Dispatcher.dispatch` (`_dispatcher.py:101`)
depends on neither session nor connection.

### 4.3 The fate of the GET push channel

**Legacy:** unchanged — `@get("/")` at `:458` opens the stream fed by `session.push_queue` (`:477`),
notifications are queued at `:375`, and a reconnect with `Last-Event-ID` (`:476`) replays from
`EventStore.replay_events_after` (`_event_store.py:39`).

**Modern:** refused, because the channel it replaced no longer exists (E-23). The existing stateless branch
already returns the right shape:

```python
# src/lauren_mcp/_server/_streamable.py  lines 460-463
            if stateless:
                return Response(
                    body=json.dumps({"error": "GET is not supported in stateless mode"}).encode(),
                    status=405,
                )
```

The modern branch mirrors it with a body that names the replacement:
`{"error": "GET push channel was removed in 2026-07-28; use the 'subscriptions/listen' request (E-23)"}`.
`subscriptions/listen` is a **POST** whose response is a long-lived `text/event-stream` — that is why the
GET channel is unnecessary in the modern transport: the notification channel becomes a request like any
other and needs no session to address it. This PRD reserves `_METHOD_SUBSCRIPTIONS_LISTEN` (§4.1) and, until
the follow-up lands, `_handle_modern` answers it with `METHOD_NOT_FOUND` plus the sibling PRD reference
rather than silently closing a stream. Capability advertisement belongs to
`prd-dual-era-protocol-core.md`; the notification envelope belongs to `prd-result-envelope-caching.md`.

### 4.4 `DELETE` teardown stays a legacy operation

```python
# src/lauren_mcp/_server/_streamable.py  lines 522-538
        @delete("/")
        async def handle_delete(self, request: Request) -> Response:
            ...
            session_id = request.headers.get(_SESSION_HEADER)
            if not session_id:
                return _json_response(...)          # status=400
            self._sessions.delete(session_id)
```

`DELETE` exists to release a server-side session. The modern era creates none (G1), so there is nothing to
release: the modern branch answers `405`, the legacy branch keeps its current behaviour including the `400`
for a missing header and the queue drain at `:82` (`session.push_queue.put_nowait(None)`), which unblocks
any open GET stream before the session drops.

### 4.5 What losing `Last-Event-ID` resumability actually costs

Be precise, because "a feature was removed" is not the same as "the spec removed a guarantee":

- Legacy reconnect with `Last-Event-ID` replays the missed SSE frames (`:476`, `_event_store.py:39`);
  after `2026-07-28` replay is unspecified (E-28) and a server must not emit resumable ids.
- Legacy ids are namespaced per session — `f"{session.session_id}-{n}"` (`:505`); with no session there is
  no namespace, so ids are simply not emitted.
- `InMemoryEventStore(max_events=100)` (`:74`) stops bounding anything for modern traffic, lowering memory
  pressure; the buffer keeps serving legacy sessions until E-41's window closes.

The honest framing: **this is a spec-mandated regression in delivery across a dropped connection** (E-28),
not a `lauren-mcp` defect, and not something to patch with a proprietary `Last-Event-ID` extension that a
modern host would never implement. The mitigation is at the application layer and already available: tool
calls must be idempotent or carry a client-chosen dedupe key in `_meta`, so re-issuing a `tools/call` after
a dropped stream is safe. That requirement belongs in the tools guide.

What is *not* lost: server-initiated requests inside a tool call. In the legacy era they travel over the GET
channel and block in `pending_client_rpcs` (`:57`); in the modern era they travel inside the response stream
of the request that caused them (MRTR, `prd-mrtr-input-required.md`), which never depends on a second
connection.

### 4.6 Multi-instance deployment

Today: replica-local dict (`:68`) plus locally minted ids (`:71`) ⇒ sticky routing or a shared session store,
i.e. rollout churn and a correctness cliff when an autoscaler removes the pod holding a session.

After this PRD, for modern traffic: no shared state, no stickiness, no rollout churn. Client capabilities and
the negotiated revision are per-request, hence consistent by construction across replicas; any replica can
serve any `tools/call`, including one that never saw the client's earlier requests; blue/green and canary
rollouts can split traffic per request instead of per client. Legacy clients keep their requirements, so a
deployment runs both modes side by side and shrinks the sticky pool as clients migrate — the shape E-41's
12-month window implies.

### 4.7 Configuration surface

```python
# src/lauren_mcp/server/_module.py  (new fields on the server settings object, not a new class)
modern_era: bool = True                              # serve 2026-07-28 requests without a session
require_transport_security_for_modern: bool = True   # refuse modern traffic with no Origin guard
```

Both are threaded into the append at `_module.py:271`. `transport_security` itself stays `None` (off) for
legacy traffic so existing deployments do not change behaviour, but the modern path refuses to serve without
a guard: a sessionless endpoint has no per-client state to fall back on, so an `Origin`-less rebinding
request is indistinguishable from a legitimate one (E-169b).

### 4.8 Failure modes

Unchanged: no `_meta` or a bogus `Mcp-Session-Id` still yields `400` (`:339`) or `404` (`:344`). Changed:
modern `_meta` without a session yields `200` with no `mcp-session-id` header; `initialize` with modern
`_meta` yields `404 METHOD_NOT_FOUND`; `GET`/`DELETE` with modern `_meta` yield `405`; and a request carrying
both modern `_meta` and a valid session id is served as legacy (§4.1 tie-break).

## 5. Server-side Changes

1. `_streamable.py`: add `MODERN_MIN_REVISION`, the `_META_*` keys, `_METHOD_SUBSCRIPTIONS_LISTEN`,
   `RequestMeta`, `resolve_request_era`, `parse_request_meta`; add a `modern_era` factory kwarg beside
   `stateless` (`:104`).
2. `_streamable.py`: add the era branch beside `:183`, add `_handle_modern`, add the `request_meta` keyword to
   `_handle_stateless` (`:232`) and pass it into `TransportBinding` (`:263`).
3. `_streamable.py`: gate `handle_get` (`:458`) and `handle_delete` (`:522`) on the era, reusing the existing
   stateless `405` shapes at `:460-462` and `:524-529`.
4. `_streamable.py`: log a `WARNING` the first time a request carries both a session id and modern `_meta`, so
   the transitional population is measurable.
5. `_module.py`: thread `modern_era` and `transport_security` into the controller append at `:271`.
6. `_event_store.py`: docstring only (`:3`) — modern traffic never reaches it (E-28).

## 6. Exact Lines to Change

**`src/lauren_mcp/_server/_streamable.py`** — `_SESSION_HEADER` (`:41`) and `_PROTOCOL_HEADER` (`:42`) stay
untouched; new constants go after `_CLIENT_RPC_TIMEOUT = 120.0` (`:43`). `StreamableSession` (`:47-60`),
`StreamableSessionStore` (`:64-90`) and `_handle_initialize` (`:315-332`) are not modified. The era branch is
inserted before the `stateless` branch at `:183`; `_handle_modern` sits next to `_handle_stateless` (`:232`);
`handle_get` (`:458`) and `handle_delete` (`:522`) each get a two-line era guard above their `if stateless:`
test; the guard at `:576-579` becomes required when `modern_era` is on.

**`src/lauren_mcp/_server/_dispatcher.py`** — no signature change: `dispatch` (`:101`) stays
`async def dispatch(self, request: JsonRpcRequest)`. Per-request metadata reaches handlers through the
execution context `TransportBinding` already carries, never through a new dispatcher argument — threading an
era through dispatch would make every handler transport-aware.

**`src/lauren_mcp/_server/_handshake.py`** — `negotiate_version` (`:14`) keeps serving the legacy handshake
only; the modern path never calls it, because there is no handshake to negotiate. Note in
`build_initialize_result` (`:28`) that its result is legacy-era only (E-20).

**`src/lauren_mcp/server/_module.py`** — the append at `:270-271` gains the two kwargs; nothing else in the
`controllers` list changes.

**`src/lauren_mcp/_server/_event_store.py`** — docstring only (`:3`). `store_event` (`:25`),
`replay_events_after` (`:39`) and `InMemoryEventStore` (`:74`) stay session-keyed and stay the legacy replay
mechanism.

## 7. Backward Compatibility

The legacy path is byte-for-byte unchanged: same constant (`:41`), same `400` (`:339`) and `404` (`:344`),
same response headers (`:332`), same GET channel (`:458-516`), same DELETE teardown (`:522-538`).
`grep -c 'mcp-session-id' src/lauren_mcp/_server/_streamable.py` must not decrease — that is the acceptance
test for E-41's ≥12-month window, not an aspiration.

**Migration notes — none**, and the reason is structural rather than generous: every request that worked
before carries either a session id or no `_meta`, and both resolve to legacy (§4.1). The new behaviour only
triggers for messages that today fail with `400`, so no client can regress. Operators who never enable
`modern_era` see no change.

## 8. Test Plan

### 8.1 Unit tests — `tests/unit/test_request_era.py`

`test_no_meta_is_legacy`, `test_legacy_revision_in_meta_is_legacy`, `test_modern_revision_in_meta_is_modern`,
`test_session_header_beats_modern_meta` (tie-break plus warning), `test_meta_not_a_dict_is_legacy`,
`test_protocol_version_not_a_string_is_legacy`, `test_revision_after_2026_07_28_is_modern`,
`test_parse_request_meta_round_trips_capabilities`.

### 8.2 Integration tests — `tests/integration/test_sessionless_streamable.py`

`test_modern_tools_list_without_session_returns_200_and_no_session_header` (the acceptance `curl`,
in-process), `test_modern_initialize_is_method_not_found` (and `_sessions` is still empty, proving no session
was minted), `test_modern_get_returns_405_naming_subscriptions_listen`,
`test_modern_delete_returns_405`, `test_legacy_flow_unchanged` (`initialize` → `tools/list` → `DELETE` with
`Mcp-Session-Id`, same status codes and headers as `HEAD`), `test_two_controller_instances_answer_identically`.

## 9. Open Questions

1. Should `subscriptions/listen` answer with an immediately-closing empty SSE stream until implemented, or
   with `METHOD_NOT_FOUND`? This PRD chooses the error; a silently empty stream is harder for a host to
   diagnose.
2. Will `require_transport_security_for_modern=True` break the localhost `curl` in the acceptance list (no
   `Origin` header)? Probably; the guard should allow `Origin`-less requests and reject only mismatches.
   Check `McpTransportSecurityGuard` before implementing.
3. Is "session id plus modern `_meta`" a metric only, or a hard `400` after a deprecation window? Measuring
   first is cheap; forbidding later is not reversible.

## 10. References

- E-20 — sessions removed; `Mcp-Session-Id` absent from the `2026-07-28` schema.
- E-22 — per-request `_meta` carries `protocolVersion`, `clientInfo`, `clientCapabilities`.
- E-23 — `subscriptions/listen` replaces the HTTP GET channel.
- E-28 — SSE resumability removed; no `Last-Event-ID` replay.
- E-41 — deprecation is not removal; ≥12-month support window.
- E-169b — Streamable HTTP mandates `Origin` validation (DNS rebinding).
- E-241 — `mcp-session-id` in 4 source files; E-244 — `Last-Event-ID` in 2.
- Siblings: `prd-dual-era-protocol-core.md`, `prd-server-discover-request-meta.md`,
  `prd-mrtr-input-required.md`, `prd-result-envelope-caching.md`.
