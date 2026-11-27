# PRD — Client-side feature parity across the four transports

**Status:** Draft
**Date:** 2026-11-26
**Scope:** `src/lauren_mcp/_client/` — `_protocol.py`, `_base_remote.py`, `_stdio.py`, `_streamable.py`, `_features.py`, `_factory.py`, plus a new `_cache.py`
**Priority:** P2
**Issue:** _pending_

---

## 1. Problem Statement

`lauren-mcp` implements the MCP **legacy era** (`2024-11-05` … `2025-11-25`) completely and has **zero** `2026-07-28` (modern era) surface (`_research/PRD-BRIEF.md:10-12`). That is usually read as a server claim, because the visible work happened in `src/lauren_mcp/_server/`: an event store (`_event_store.py`), a per-URI subscription manager (`_subscriptions.py`), session-aware Streamable HTTP (`_streamable.py`), and cancellation scaffolding (`_dispatcher.py:165` `def cancel(self, request_id: str | int) -> bool`).

The client did not follow. Measured with `grep -rlF`: `notifications/cancelled` appears in **0** files in `src/` (`E-237`) and `_client/` has no cancel API (`N-10`); `mode` appears in **0** client files and the revision is hard-coded at `_features.py:70`; `_meta` appears in **15** server files and **0** client files; `resultType`, `ttlMs` and `cacheScope` appear **nowhere** (`E-232`…`E-234`); `server/discover` is absent everywhere (`E-230`), as are `subscriptions/listen` (`E-231`) and `tasks/*` (`E-235`); `last-event-id` exists in `_server/_streamable.py` and `_server/_event_store.py` only. Every agent framework in the landscape wraps the same three transports behind one client object (`E-200`…`E-207`), and the official Python SDK ships all of it dual-era (`E-81`). A host here gets the server half of the 2026 stack and a 2025 client.

### 1.1 A host cancels a long tool call and the client keeps waiting

The client's only request path is `src/lauren_mcp/_client/_base_remote.py:154-169`:

```python
    # src/lauren_mcp/_client/_base_remote.py  line 154
    async def _request(self, method: str, params: Any = None) -> Any:
        req_id = self._next_id
        self._next_id += 1
        fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut
        await self._send_raw({"jsonrpc": "2.0", "method": method, "id": req_id, ...})
        return await fut
```

No `try`, no `finally`, no way to say "stop waiting for request 7". `McpStdioClient` has a second copy at `_stdio.py:268`. So:

1. `asyncio.wait_for(client.call_tool("slow", ...), timeout=5)` raises locally while the **server keeps running the tool**: nothing was sent. The server can stop it (`_server/_dispatcher.py:165`) but waits for the wrong name — `$/cancelRequest`, an LSP method, in `_server/_stdio.py:76`, `_server/_ws.py:39`, `_server/_streamable.py:212` and `_server/_context.py:308`. The server half belongs to `prd-cancellation-conformance.md`; the client half is here.
2. On task cancellation, `await fut` raises `asyncio.CancelledError` and `self._pending[req_id]` is **never removed** — it leaks until `_fail_all_pending` (`:205`) runs at `close()`, one dead future per attempt, the late response popped by nobody.
3. No exception means "this request was cancelled", and the package exports four names (`_client/__init__.py:9-14`), so a host cannot tell a user cancel from a transport failure.

### 1.2 A client that cannot say which era it speaks, and a gap nobody can measure

`_features.py:16` imports `LATEST`; `:70` does `self._requested_protocol_version: str = protocol_version or LATEST`. `LATEST` is `"2025-11-25"` (`_mcp_version.py:5`), next to `STABLE` (`:6`) and `SUPPORTED` (`:7`) — which **the client never reads**. `protocol_version` is accepted by every transport (`_stdio.py:78`, forwarded `:97`, sent `:236`) and passed through unvalidated, so `protocol_version="2027-13-01"` reaches the wire silently. There is no way to say "I want the modern era, fail loudly on a legacy-only server" and no way to say "probe first, then decide".

The gap is also unmeasurable from the tree: `EVIDENCE.md` records absences as single numbers (`E-230`…`E-237`), but nothing states *which of the twenty-odd methods and notifications each side implements*, so every PRD re-derives it by hand — and two workers have already conflated `_client/_streamable.py` with `_server/_streamable.py`, which share a filename and nothing else. §4.1 makes the matrix an artifact and a test.

## 2. Goals

1. Publish a **parity matrix** (§4.1) for every MCP method and notification, each column anchored by a verified `path:line`, plus `tests/unit/test_client_parity_matrix.py` so the table fails the build when it rots.
2. Make the client **cancellable**: `client.cancel(request_id)` and task-cancellation propagation that emits `notifications/cancelled`, removes the pending future in `finally`, discards a response that still arrives, and never converts `asyncio.CancelledError` into an `Exception`.
3. Give the client **era selection**: `era` (`"legacy" | "modern" | "auto"`) on all four factories, `SUPPORTED` validation, a defined reaction to a legacy-only server, and a `negotiated_era` property.
4. Add an **envelope reader and in-client cache** honouring `ttlMs`/`cacheScope`, invalidated by the three `list_changed` notifications and `resources/updated`.
5. Support **`server/discover`** as the first frame of an `auto` connection, with a timeout and a clean fallback to `initialize`.
6. Extend **`McpClientProtocol`** and add `tests/unit/test_client_transport_surface.py` so the four transports cannot drift apart.
7. Change **no default observable behaviour** apart from the single probe frame of §4.3.

### 2.1 Acceptance criteria

- [ ] `grep -rlF 'notifications/cancelled' src/ | wc -l` ≥ 2, and ≥ 1 under `src/lauren_mcp/_client`; `python -c "from lauren_mcp._client import McpRequestCancelled, McpEraMismatch"` exits 0.
- [ ] `grep -c 'async def cancel' src/lauren_mcp/_client/_protocol.py` ≥ 1; `grep -c 'CancelledError' src/lauren_mcp/_client/_base_remote.py` ≥ 2.
- [ ] `grep -c 'era' src/lauren_mcp/_client/_features.py` ≥ 6; `grep -rn '\bera=' src/lauren_mcp/_client/_factory.py | wc -l` ≥ 4; `grep -rn 'SUPPORTED' src/lauren_mcp/_client/ | wc -l` ≥ 1.
- [ ] `grep -c 'ttlMs'`, `'cacheScope'` and `'resultType'` over `src/lauren_mcp/_client/_cache.py` each ≥ 1; `grep -rn 'server/discover' src/lauren_mcp/_client/ | wc -l` ≥ 2; `grep -c 'last-event-id' src/lauren_mcp/_client/_streamable.py` ≥ 1.
- [ ] `pytest tests/unit/test_client_parity_matrix.py tests/unit/test_client_transport_surface.py -q` passes and the matrix literal matches §4.1 row for row.
- [ ] `pytest tests/unit/test_client_cancel.py tests/unit/test_client_era.py tests/unit/test_client_cache.py -q` passes.
- [ ] `pytest tests/integration/test_client_cancel_integration.py tests/integration/test_client_discover_integration.py -q` passes.
- [ ] `pytest tests/unit/test_client_transports_coverage.py tests/unit/test_client_changes.py tests/end_to_end/test_client_e2e.py -q` passes unmodified.
- [ ] `git diff --stat src/lauren_mcp/_server/ src/lauren_mcp/server/` is empty; `wc -c prds/2026-11-landscape/prd-client-parity.md` is 18000–30000.

## 3. Non-Goals

* **The server half of cancellation** (`prd-cancellation-conformance.md`, which owns the `$/cancelRequest` fix). No server file changes here.
* **The request-side `_meta` envelope** (`prd-server-discover-request-meta.md`): the client only reads discovery answers and forwards a caller-supplied `meta=` untouched.
* **Emission of `resultType`/`ttlMs`/`cacheScope`** (`prd-result-envelope-caching.md`); the reader is a no-op against today's server.
* **`tasks/*` (`E-235`) and `subscriptions/listen` (`E-231`)** — whole features with their own PRDs; here they are measured `No/No` matrix rows only.
* **A persistent cache**, or **replacing `McpCallError`** (new exceptions subclass it).
* **The TypeScript SDK's `mode: legacy | auto | pin` (`E-80`) verbatim** — same semantics, keyword named `era`.

## 4. Design

### 4.1 The parity matrix — measured, not asserted

Every cell was derived with `grep -rlF '"<method>"'` over both package trees and confirmed with `grep -n`. The loop ships as a test (§8.1) so the table cannot rot:

```bash
# derived by grep, one row per method:
#   S: grep -rlF '"<method>"' src/lauren_mcp/server src/lauren_mcp/_server | wc -l
#   C: grep -rlF '"<method>"' src/lauren_mcp/_client | wc -l
```

Anchors: `M` = `server/_module.py`, `B` = `_client/_base_remote.py`, `S` = `_client/_stdio.py`, `F` = `_client/_features.py`, `T` = `_client/_streamable.py`; `D`/`C`/`X`/`SU` = the like-named `_server/_*.py` module.

| Method / notification | Server | Anchor | Client | Anchor |
|---|---|---|---|---|
| `initialize` | yes | `M:415` | yes | `S:236`, `B:116` |
| `ping` | yes | `D:83` | yes | `B:273` |
| `tools/list` | yes | `M:457` | yes | `B:217`, `S:380` |
| `tools/call` | yes | `M:458` | yes | `B:228`, `S:391` |
| `resources/list` | yes | `M:476` | yes | `B:238` |
| `resources/templates/list` | **no** | — | **no** | — (both) |
| `resources/read` | yes | `M:477` | yes | `B:250` |
| `resources/subscribe` | yes | `M:519` | yes | `B:294` |
| `resources/unsubscribe` | yes | `M:520` | yes | `B:298` |
| `prompts/list` | yes | `M:532` | yes | `B:253` |
| `prompts/get` | yes | `M:533` | yes | `B:263` |
| `logging/setLevel` | yes | `M:427` | yes | `B:276` |
| `completion/complete` | yes | `M:544` | yes | `B:302` |
| `notifications/initialized` | yes | `_server/_streamable.py`, `_server/_ws.py` | yes | `S:230` |
| `notifications/progress` | yes | `X` | yes | `F:173` |
| `notifications/message` | yes | `X` | yes | `F:175` |
| `notifications/tools/list_changed` | yes | `C:68` | yes | `F:45` |
| `notifications/resources/list_changed` | yes | `C` | yes | `F:46` |
| `notifications/prompts/list_changed` | yes | `C` | yes | `F:47` |
| `notifications/resources/updated` | yes | `SU` | yes | `F:179` |
| `sampling/createMessage` | yes | `X` | yes | `F:161` |
| `elicitation/create` | yes | `X` | yes | `F:164` |
| `roots/list` | **no** | — | yes | `F:159` (client ahead) |
| **`notifications/cancelled`** | **no** | matches `$/cancelRequest`: `_server/_stdio.py:76`, `_server/_ws.py:39` | **no** | — (`E-237`, `N-10`) |
| **`server/discover`** | **no** | — (`E-230`) | **no** | — |
| **`subscriptions/listen`** | **no** | — (`E-231`) | **no** | — |
| **`tasks/list|get|cancel|result`** | **no** | — (`E-235`) | **no** | — |
| **`resultType`/`ttlMs`/`cacheScope`** | **no** | — (`E-232`…`E-234`) | **no** | — |
| **`input_required` (MRTR)** | **no** | — (`E-236`) | **no** | — |
| **SSE resumption (`last-event-id`)** | yes | `_server/_streamable.py`, `_server/_event_store.py` | **no** | — |

_Anchors are qualified on purpose: `_client/_streamable.py` is the Streamable HTTP **client** (`class McpStreamableHttpClient` at line 28) and `_server/_streamable.py` is the **server** transport; the two share a filename and nothing else._

Two conclusions set the scope. The **legacy rows are at parity** — 22 of them, anchored on both sides, with `roots/list` the client's single advantage: this is a complete 2025 client, not a stub. The **modern rows are uniformly absent on the client** and mostly absent on the server, so "client parity" cannot mean "catch up": it means build the client halves now, behind capability detection, so the day the sibling PRDs land the client already consumes them, degrading to today's behaviour on `-32601`.

### 4.2 Client-side cancellation

```python
# src/lauren_mcp/_client/_protocol.py  (module constants above class McpClientProtocol)
_METHOD_CANCELLED = "notifications/cancelled"
_METHOD_DISCOVER = "server/discover"

class McpRequestCancelled(McpCallError):
    """Cancelled locally or by the peer; subclasses McpCallError on purpose."""
    def __init__(self, request_id: str | int, reason: str | None = None) -> None:
        super().__init__(f"request {request_id!r} cancelled: {reason or 'no reason'}")
        self.request_id, self.reason = request_id, reason
```

```python
# src/lauren_mcp/_client/_base_remote.py  (replaces 154-169; same change at _stdio.py:268)
    async def _request(self, method: str, params: Any = None) -> Any:
        loop = asyncio.get_running_loop()
        req_id = self._next_id
        self._next_id += 1
        fut: asyncio.Future[Any] = loop.create_future()
        self._pending[req_id] = fut
        try:
            await self._send_raw({"jsonrpc": "2.0", "method": method, "id": req_id,
                                  **({"params": params} if params is not None else {})})
            return await fut
        except asyncio.CancelledError:
            # Caller stopped waiting: tell the server, then let the cancellation
            # continue.  Never convert it into an McpCallError.
            if self._cancel_on_cancel:
                with contextlib.suppress(Exception):
                    await self._send_raw({
                        "jsonrpc": "2.0", "method": _METHOD_CANCELLED,
                        "params": {"requestId": req_id, "reason": "caller cancelled"}})
            raise
        finally:
            # Stops the leak: a late response finds no future and is dropped.
            self._pending.pop(req_id, None)
```

`_dispatch_message` (`:171`) pops with a default and, when the slot is empty or done, logs at debug and returns.

Semantics the tests pin down:

* **Explicit** — `await client.cancel(rid, reason="stop")` writes exactly one `notifications/cancelled` with `params.requestId == rid` and returns `True`; it does not unblock the original caller, because the client cannot fabricate a response.
* **Implicit** — cancelling the awaiting task writes the same frame when `cancel_on_cancel=True` (default) and re-raises `asyncio.CancelledError`, never `McpRequestCancelled`: `CancelledError` is not an `Exception` subclass in 3.11 and must not be converted.
* **Peer, and no leaks** — inbound `notifications/cancelled` for a server-initiated request (`_features.py:197`) cancels that handler task; `_pending` is emptied on every path, `_fail_all_pending` is a backstop, and a second `cancel(rid)` returns `False` writing nothing.

New keyword forwarded by `**feature_kwargs` (`_factory.py:75`) into `_init_features` (`_features.py:57`): `cancel_on_cancel: bool = True`.

### 4.3 Client era selection

```python
# src/lauren_mcp/_client/_features.py  (replaces line 70)
Era = Literal["legacy", "modern", "auto"]
MODERN = "2026-07-28"                      # VERSIONS-MATRIX.md:19

        if protocol_version is not None and protocol_version not in SUPPORTED:
            raise ValueError(f"unsupported protocol_version {protocol_version!r}; "
                             f"choose one of {sorted(SUPPORTED)}")
        self._era: Era = era
        self._requested_protocol_version = protocol_version or (
            MODERN if era == "modern" else LATEST)
        self._negotiated_era: str | None = None
```

| `era` | First frame | Server answers | Result |
|---|---|---|---|
| `"legacy"` (today) | `initialize`, `protocolVersion = protocol_version or LATEST` | anything | unchanged; `negotiated_era = "legacy"` |
| `"auto"` (**default**) | `server/discover` | discovery result | `negotiated_era = "modern"`, no `initialize` |
| `"auto"` | `server/discover` | `-32601` / timeout | falls back to `initialize`; `negotiated_era = "legacy"` |
| `"modern"` | `server/discover` | `-32601` / timeout | `McpEraMismatch` from `connect()`, not from the first `tools/call` |

`McpEraMismatch(McpCallError)` carries `requested` and `observed`. The downgrade in `auto` costs one frame and one bounded wait (`discover_timeout: float = 2.0`), not a reconnect; for stdio the process is already running (`_stdio.py:169`), so a failed probe leaves the pipe usable for the legacy handshake at `connect` (`:123`). `era` reaches all four factories because they already take `**feature_kwargs`: `McpServer.stdio(["srv"], era="legacy")` keeps today's frames, `McpServer.streamable_http(url, era="modern")` fails fast on a 2025 server, and `McpServer.http(url, era="auto", discover_timeout=1.0)` probes first.

### 4.4 The modern result envelope and a cache that honours it

`src/lauren_mcp/_client/_cache.py` (new; no new dependency — `E-222` keeps the budget at `lauren` + `anyio`):

```python
# src/lauren_mcp/_client/_cache.py
class _ResultCache:
    """Per-client TTL cache driven by the result envelope: honours ttlMs (int,
    milliseconds) and cacheScope ("public" | "private" | "shared"), and caches
    nothing when the server omits them.
    """

    def put(self, key: tuple[str, ...], result: dict[str, Any]) -> None:
        if result.get("resultType", "complete") != "complete":
            return                              # "partial" / "input_required"
        ttl_ms = result.get("ttlMs")
        if not isinstance(ttl_ms, int) or ttl_ms <= 0:
            return                              # no hint, no cache
        if result.get("cacheScope", "private") not in ("public", "private", "shared"):
            return                              # unknown scope
        self._entries[key] = (time.monotonic() + ttl_ms / 1000.0, result)
        while len(self._entries) > self._max:
            self._entries.popitem(last=False)   # OrderedDict LRU
```

Wiring lives in `_ClientFeaturesMixin` (`_features.py:51`), so **all four transports inherit it**: `cache: bool = False`, `cache_max_entries: int = 128`, a `_maybe_cached(key, thunk)` helper used by `list_tools`/`list_resources`/`list_prompts` (`_base_remote.py:217,238,253`, `_stdio.py:380,402,418`) with keys `("tools",)`, `("resources",)`, `("prompts",)`. Invalidation reuses `_LIST_CHANGED_METHODS` (`_features.py:44-48`) in `_route_notification` (`:171`): `tools` drops `("tools",)`; `resources` drops `("resources",)` **and every `("resource", uri)`**; `prompts` drops `("prompts",)`; `resources/updated` (`:179`) drops that URI only. `cache_stats()` returns counters.

`cacheScope` honesty: nothing is written to disk and nothing is shared across processes, so `"public"` and `"shared"` mean "cacheable in this process only", and the docstring says so. `cache=False` by default keeps today's request pattern (Goal 7); `prd-result-envelope-caching.md` can flip it once the server emits `ttlMs`.

### 4.5 Probing an unknown server with `server/discover`

```python
# src/lauren_mcp/_client/_base_remote.py  (next to ping, line 273)
    async def discover(self, *, timeout: float | None = None) -> dict[str, Any] | None:
        try:
            return await asyncio.wait_for(
                self._request(_METHOD_DISCOVER), timeout or self._discover_timeout)
        except asyncio.TimeoutError:
            return None          # -32601 and timeouts both mean "assume legacy"
```

It lands beside `ping` in both request implementations — `_McpBaseRemoteClient` (`_base_remote.py:39`, shared by `_ws.py:30`, `_sse.py:31`, `_streamable.py:28`) and `McpStdioClient` (`_stdio.py:40`). `connect()` probes first (only for `era` in `{"auto", "modern"}`), then caches the answer into `_server_capabilities`/`_server_info` (`_features.py:109`) or runs today's `_handshake` (`_stdio.py:230`, `_base_remote.py:116`). Only `versions` and, optionally, `capabilities` are read; every other key stays opaque, so the shape remains owned by `prd-server-discover-request-meta.md`.

### 4.6 `McpClientProtocol` surface additions

Current abstract surface, 13 members (`_protocol.py`): `connect:28`, `close:37`, `list_tools:49`, `call_tool:57`, `list_resources:83`, `read_resource:91`, `subscribe_resource:108`, `unsubscribe_resource:126`, `list_prompts:143`, `get_prompt:151`, `ping:176`, `set_logging_level:184`, `complete:206`. Additions, all **new** members, no existing signature changed:

```python
# src/lauren_mcp/_client/_protocol.py  (after set_logging_level, line 184)
    async def cancel(self, request_id: str | int, *, reason: str | None = None) -> bool: ...
    async def discover(self, *, timeout: float | None = None) -> dict[str, Any] | None: ...
    era: str                       # "legacy" | "modern" | "auto", as requested
    negotiated_era: str | None     # what the server agreed to; None before connect
    cache: Any                     # _ResultCache | None
    def cache_stats(self) -> tuple[int, int, int]: ...
```

`cancel`, `discover` and `cache_stats` are **concrete defaults on the ABC** — `cancel` writes through whatever `_send_raw` the transport provides and returns `False` for an unknown id, `discover` returns `None`, `cache_stats` returns `(0, 0, 0)`. That keeps `McpClientProtocol`, publicly exported at `_client/__init__.py:9-14`, from breaking out-of-tree transports while the in-tree four override everything. `tests/unit/test_client_transport_surface.py` asserts for `McpStdioClient`, `McpWebSocketClient`, `McpHttpSseClient` and `McpStreamableHttpClient` that each is an instance, raises no `NotImplementedError`, and *overrides* `cancel`/`discover`.

One asymmetry: the three remote transports share `_BaseRemoteClient._request` (`:154`), while stdio has its own (`_stdio.py:268`) plus copies of eleven legacy methods (`:380`…`:468`), so cancellation and discovery land twice.

## 5. Client-Side Changes

| File | Change |
|---|---|
| `_protocol.py` | `_METHOD_CANCELLED`, `_METHOD_DISCOVER`, `McpRequestCancelled`, `McpEraMismatch`; six new concrete members |
| `_base_remote.py`, `_stdio.py` | `_request` hardening (`:154-169` / `:268`), late-response discard (`:171` / `:345`), `cancel()`/`discover()` after `ping` (`:273` / `:439`), cached lists, probe-safe `connect:123` |
| `_streamable.py` | `last-event-id` on reconnect (`:184`); `mcp-protocol-version` carries `2026-07-28` when `negotiated_era == "modern"` (`:151`) |
| `_features.py`, `_factory.py`, `__init__.py` | four new keywords (`:57`), `SUPPORTED` validation (`:70`), invalidation (`:171`), inbound cancel (`:197`); factory docstrings; two new exports |
| `_cache.py` | **new**, the only added module — `_ResultCache` (§4.4) |


## 6. Exact Lines to Change

* `_client/_protocol.py` — `:15` constants above the class and the two exceptions below it; `:184` insert the six members after `set_logging_level`; `:206` `complete` stays last.
* `_client/_base_remote.py` — `:154-169` the `try`/`except asyncio.CancelledError`/`finally` `_request`; `:171` pop with a default; `:205` backstop; `:217`, `:238`, `:253` cached lists; `:273` `cancel()`/`discover()`.
* `_client/_stdio.py` — `:268`, `:345` the same two changes; `:123` conditional probe before `_handshake:230`; `:380`, `:402`, `:418` cached lists; `:439` `cancel()`/`discover()` or inherit (§9.3).
* `_client/_streamable.py` — `:184` send `last-event-id` on reconnect, matching `src/lauren_mcp/_server/_streamable.py`; `:151` the negotiated revision.
* `_client/_features.py` — `:16` import `SUPPORTED`; `:44-48` now also the invalidation map; `:57-70` keywords and era-aware default; `:171-183` invalidation; `:197` inbound cancel.
* `_client/_factory.py` — `:68`, `:105`, `:139`, `:182` docstring parameters only; `**feature_kwargs:75` already forwards them.

## 7. Backward Compatibility

* **Wire behaviour.** `era` defaults to `"auto"`, which sends one `server/discover` before the handshake; callers needing byte-identical traffic pass `era="legacy"` (`CHANGELOG.md`, one line). Against a non-modern server the difference is one `-32601`.
* **Exceptions and ABC.** `McpRequestCancelled`/`McpEraMismatch` subclass `McpCallError`, and every new ABC member is concrete, so existing handlers and third-party transports keep working.
* **Defaults.** `cache=False` and `cancel_on_cancel=True`: today's request pattern, plus one notification and one fewer leaked entry on cancellation.

## 8. Test Plan

### 8.1 Unit tests — `tests/unit/`

* `test_client_parity_matrix.py` — holds the §4.1 table as a literal, re-derives it by scanning both package trees, reports the offending row, and asserts the out-of-scope rows stay absent on both sides.
* `test_client_cancel.py` — fake transport records frames: one `notifications/cancelled` per `cancel(rid)` with the right `requestId`; second call returns `False` and writes nothing; task cancellation re-raises `CancelledError` and leaves `_pending == {}`; a late response is dropped without raising.
* `test_client_era.py` — `era="modern"` against a `-32601` stub raises `McpEraMismatch` from `connect()`; `era="auto"` falls back to `initialize` with `negotiated_era == "legacy"`; `era="legacy"` sends no probe; `protocol_version="2027-13-01"` raises `ValueError`.
* `test_client_cache.py` — `ttlMs=50` serves the second call from cache and expires after 60 ms; missing `ttlMs` never caches; `resultType="partial"` never caches; `list_changed` drops `("tools",)`; `resources/updated` drops one URI.
* `test_client_transport_surface.py` — the four-transport conformance test of §4.6; `test_client_transports_coverage.py` and `test_client_changes.py` must pass unmodified.

### 8.2 Integration tests — `tests/integration/`

* `test_client_cancel_integration.py` — in-process server with a 5-second tool: `cancel(rid)` fires the server's `cancel_requested` event (`xfail(strict=False)` with an `E-237` comment until the server PRD lands); a second test cancels the client task and asserts the server stops and `_pending` is empty.
* `test_client_discover_integration.py` — a legacy server under `era="auto"` completes `list_tools` and reports `negotiated_era == "legacy"`. `test_mcp_streamable_http.py` gains a dropped-stream case asserting `last-event-id` on reconnect; `tests/end_to_end/test_client_e2e.py` stays unchanged.

## 9. Open Questions

1. **Should `era="auto"` be the default?** It adds a frame against every 2025 server and `test_client_e2e.py` pins frame order; the alternative is defaulting to `"legacy"` for one release. The matrix is unaffected.
2. **Does `cancel()` unblock the caller?** No — it cannot fabricate a response. A `stop()` that notifies *and* cancels the awaiting task needs a task registry keyed by request id, which is larger than P2.
3. **Fold stdio into `_McpBaseRemoteClient`?** `McpStdioClient` (`_stdio.py:40`) reimplements `_request:268`, `_dispatch:345` and eleven methods. Follow-up: delete those ~250 lines.
4. **Flip `cache=True` when `ttlMs` ships?** Leaning opt-in: a cache that misreads `cacheScope` is worse than none.
5. **Emit `_meta` now?** No — the client only forwards a caller-supplied `meta=`.

## 10. References

**Repository:** every `path:line` above was re-verified with `grep -n` before writing, and the full anchor set is re-derived mechanically by `tests/unit/test_client_parity_matrix.py`. Entry points: `_client/_protocol.py:15,184,206`; `_base_remote.py:154,171,273`; `_stdio.py:40,268,345`; `_streamable.py:24,151,184`; `_features.py:16,44-48,57,70,171,197`; `_factory.py:68,75,105,139,182`; `_client/__init__.py:9-14`; `_mcp_version.py:5-7`; `_server/_dispatcher.py:83,165`; `_server/_stdio.py:76`; `server/_module.py:415,427,457,458,476,477,519,520,532,533,544`.

**Evidence (`EVIDENCE.md`):** `E-81` — Python SDK 2.3.0 ships both eras with `HANDSHAKE_*`/`MODERN_*` and a `_probe.py`, the reference design for §4.3/§4.5. `E-200`, `E-201`, `E-203` — OpenAI Agents SDK, LangChain adapters and PydanticAI each wrap stdio + SSE + Streamable HTTP behind one client object, which is why §4.6 must stay one surface. `E-230`…`E-237` — `server/discover`, `subscriptions/listen`, `resultType`, `ttlMs`, `cacheScope`, `tasks/`, `input_required` and `notifications/cancelled` are all at 0. `E-241` — `mcp-session-id` in 4 files, a 2025-era design. `E-222` — exactly two runtime dependencies (`lauren>=1.7.0`, `anyio>=4.0`); §4.4 adds no third. `E-76` — tier requirements and conformance pass rates. `E-80` — TypeScript SDK `mode: legacy | auto | pin`. `N-10` — no client-side cancellation, 0 hits.

**Sibling PRDs:** `prd-cancellation-conformance.md` (server half of cancellation), `prd-server-discover-request-meta.md` (probe shape and `_meta`), `prd-result-envelope-caching.md` (envelope emission), `prd-subscriptions-listen.md`, `prd-tasks-extension.md`, `prd-dual-era-protocol-core.md`, `prd-sessionless-http-transport.md`, `prd-host-compatibility-profiles.md` and `../prd-protocol-version-negotiation.md` (whose handshake this PRD extends).

**Spec:** MCP `2026-07-28` (modern era) and `2024-11-05` … `2025-11-25` (legacy era), as summarised in `VERSIONS-MATRIX.md:16-21`.

## lauren-mcp Advantages

Four transports behind one abstract surface is more than most SDKs in the landscape offer. `McpServer.stdio` (`_factory.py:68`), `.ws` (`:105`), `.http` (`:139`) and `.streamable_http` (`:182`) all return `McpClientProtocol` (`_protocol.py:15`), so a host swaps Streamable HTTP for a subprocess by changing one line, and the three remote transports already share one request path (`_base_remote.py:154`). The frameworks in `E-200`…`E-207` expose three of the four plus an incompatible client per framework; nothing else in this repo's dependency footprint gives a host WebSocket *and* SSE *and* Streamable HTTP from one import.

The second advantage is the one this PRD must not spend: the client is dependency-free. `E-222` records exactly two runtime dependencies, the transports are hand-rolled (`_stdio.py` over `asyncio` pipes, `_streamable.py:140` over the raw HTTP body), and §4.4's cache uses `time.monotonic()` and `OrderedDict` rather than a third package. Era selection is a string comparison, discovery one frame, cancellation one notification, caching a dict with expiry.

Honest counterweight: the client is behind, not merely different — `notifications/cancelled` at 0 (`E-237`), `server/discover` at 0 (`E-230`), and a server matching `$/cancelRequest`, an LSP name, instead of the spec's method. Transport elegance does not fix a client that cannot say "stop".
