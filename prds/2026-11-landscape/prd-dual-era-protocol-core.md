# PRD — Dual-era protocol core

**Status:** Draft  
**Date:** 2026-11-26  
**Scope:** `src/lauren_mcp/_mcp_version.py`, `src/lauren_mcp/_era.py` (new), `src/lauren_mcp/_server/_handshake.py`, `src/lauren_mcp/_server/_dispatcher.py`, `src/lauren_mcp/_server/_streamable.py`, `src/lauren_mcp/server/_module.py`  
**Priority:** P1 — `2026-07-28` makes `server/discover` a MUST (E-21) and removes `initialize` for modern peers, so a fielded modern client cannot complete one request against `lauren-mcp` 1.0.0.  
**Issue:** [#61](https://github.com/lauren-framework/lauren-mcp/issues/61)

---

## 1. Problem Statement

`lauren-mcp` 1.0.0 implements the legacy era completely and the modern era not at all. The
VERSIONS-MATRIX capability delta records `2026-07-28` as **absent**: `server/discover` = 0 hits,
`resultType` = 0, `subscriptions/listen` = 0. That is not a missing feature; it is a closed door,
because the modern era replaces the *entry point* of the protocol rather than adding to it.

### 1.1 A modern host cannot open a conversation

A host built against `2026-07-28` does not send `initialize`. It sends `server/discover`, which the
specification tree makes mandatory (E-21: "The `initialize` handshake is **removed** for modern
peers; `server/discover` is a MUST"). Our dispatcher has no handler for that method, so the request
falls through to the unknown-method branch:

```python
# src/lauren_mcp/_server/_dispatcher.py  lines 115-121
            handler = self._handlers.get(request.method)
            if handler is None:
                return build_error_response(
                    id=request.id,
                    code=McpErrorCode.METHOD_NOT_FOUND,
```

The client receives `-32601` on its very first frame. There is no second frame. Confirming the
absence: `grep -ril 'server/discover' src/ | wc -l` → `0` (E-230). `lauren-mcp` scores zero on the
modern era for a reason unrelated to its tools, resources, and prompts — all complete, all
unreachable.

### 1.2 The version table is a single point of exclusion

One module decides what wire dialect this server speaks:

```python
# src/lauren_mcp/_mcp_version.py  lines 5-7
LATEST = "2025-11-25"
STABLE = "2024-11-05"
SUPPORTED = frozenset({"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"})
```

`SUPPORTED` has no `2026-07-28` (E-226), and `negotiate_version()` falls back to `LATEST`:

```python
# src/lauren_mcp/_server/_handshake.py  lines 14-25
def negotiate_version(client_version: str) -> str:
    """Return the best mutually-supported protocol version.
    ...
    """
    if client_version in SUPPORTED:
        return client_version
    return LATEST
```

A modern client that nonetheless sent `initialize` with `"protocolVersion": "2026-07-28"` would be
answered `"2025-11-25"` — silently downgraded into a dialect it did not ask for, over a handshake the
modern era says must not exist. The downgrade is legal legacy behaviour and simultaneously wrong for
a modern peer.

### 1.3 Sessions are gone, and we demand them

Streamable HTTP in `2026-07-28` **removes** `Mcp-Session-Id` (E-20). We require it on every request
after `initialize`, and mint it in the response:

```python
# src/lauren_mcp/_server/_streamable.py  line 41, line 335
_SESSION_HEADER = "mcp-session-id"
...
    def _require_session(self, request: Request) -> StreamableSession | Response:
```

```python
# src/lauren_mcp/_server/_streamable.py  lines 330-333
            return _json_response(
                response.to_json(),
                headers=[(_SESSION_HEADER, session.session_id), (_PROTOCOL_HEADER, version)],
            )
```

A modern HTTP client that sends a bare `tools/call` with a per-request `_meta` envelope and no session
header is rejected before dispatch — yet the handler needs only the catalog, which is process-wide.

### 1.4 Why one binary

The alternative is a fork — 1.x for legacy hosts, 2.x for modern ones — which doubles the maintenance
surface of a library whose selling point is two runtime dependencies and one dispatch table (E-222),
and strands users who cannot move their host for a year. `SUPPORTED` already proves the intent: this
server was built to answer in more than one dialect. It needs one missing dimension, era, alongside the
revision it tracks.

---

## 2. Goals

1. **One process, two eras.** Answer both `2024-11-05`…`2025-11-25` (legacy) and `2026-07-28`
   (modern) peers with no configuration change beyond extending the supported set.
2. **A mandatory `server/discover`.** Returns supported revisions, server info, capabilities, and
   instructions in one round trip (E-21).
3. **Per-request era detection.** Resolved from the request — the `_meta` envelope's
   `io.modelcontextprotocol/protocolVersion` (E-22) or the `Mcp-Protocol-Version` header — never from
   process-global state. Two clients on one process must not see each other's dialect.
4. **Sessionless modern HTTP.** A modern `tools/call` with no `Mcp-Session-Id` is served (E-20).
5. **Result shaping at the edge.** Modern results carry `resultType` (E-27); list results additionally
   carry `ttlMs` and `cacheScope`. Legacy results do not.
6. **`ping`, `logging/setLevel`, `roots/list_changed` stay absent for modern peers.** They are removed
   in `2026-07-28` (E-24); answering `-32601` to a modern `ping` is correct, and this PRD must not
   "helpfully" keep them alive.
7. **Legacy wire output is byte-identical.** `tests/unit/test_mcp_handshake.py` passes unmodified.
8. **No new runtime dependency** — `anyio`, `McpDispatcher`, and existing controllers only (E-222).

### 2.1 Acceptance criteria

- [ ] `grep -ril 'server/discover' src/ | wc -l` ≥ 1 (currently 0, E-230).
- [ ] `grep -ril 'resultType' src/ | wc -l` ≥ 1 (currently 0, E-232).
- [ ] `python -c "from lauren_mcp._mcp_version import SUPPORTED; assert '2026-07-28' in SUPPORTED"`
      exits 0.
- [ ] `pytest tests/unit/test_era.py tests/unit/test_result_shape.py -q` passes.
- [ ] `pytest tests/unit/test_mcp_handshake.py -q` passes with **zero** edits to that file.
- [ ] `pytest tests/integration/test_dual_era_streamable.py -q` passes: one module, two clients,
      interleaved requests, each receiving its own era's result shape.
- [ ] `negotiate_version("2026-07-28") == "2026-07-28"` and
      `negotiate_version("2019-01-01") == STABLE`.
- [ ] No new entry under `[project.dependencies]` in `pyproject.toml`.

---

## 3. Non-Goals

- **Removing sessions for legacy peers.** `Mcp-Session-Id` stays mandatory for `2024-11-05` …
  `2025-11-25`.
- **`subscriptions/listen`.** The modern replacement for the HTTP GET channel (E-23) needs a
  streaming subscription registry; separate PRD. `_streamable.py` has no GET channel today and this
  PRD does not add one.
- **Tasks and MRTR.** The `io.modelcontextprotocol/tasks` extension (E-25) and `input_required`
  (E-26) stay at zero (E-235, E-236).
- **Renumbering the error enum.** `2026-07-28` renumbers error codes and standardises
  resource-not-found (E-29). Wire-visible, its own compatibility matrix; `McpErrorCode` is untouched.
- **SSE resumability.** Removed in `2026-07-28` (E-28); no `Last-Event-ID` replay in either era.
- **A modern client.** `src/lauren_mcp/_client/` keeps speaking legacy. This PRD makes the *server*
  dual-era.
- **Cancellation.** `$/cancelRequest` is the wrong method name for both eras (E-237) and belongs to
  the sibling cancellation PRD; mixing it in would put two unrelated wire changes in one diff.
- **Configuration beyond one kwarg.** No env vars, no `lmcp` subcommand, no per-tool era flags.

---

## lauren-mcp Advantages

What this repository already has that a "vendor the official SDK" approach would lose.

**The negotiation is already one function.** `negotiate_version()` (`_handshake.py:14`) is 12 lines
and the only place version policy lives. Extending it to two eras is a table edit, not an
architectural change. The TypeScript SDK reaches the same goal through a version-union type, a
generated schema per revision, and a capability layer — which a two-dependency Python package cannot
afford to copy, and does not need, because the policy is already centralised.

**One dispatch table serves four transports.** `_dispatcher.py` routes by method name for WebSocket,
Streamable HTTP, SSE, and stdio alike (`_ws.py:236`, `_streamable.py:315`, `_stdio.py:50`). Era
detection therefore has one place to live: the dispatcher, once per request. A host-per-transport
design would implement the check four times and drift.

**Guard and DI wiring is era-orthogonal.** `@use_guards`, `@use_interceptors`, and the Lauren
`@injectable` graph (`_decorators.py:44`, `:758`) run *behind* dispatch. Modern peers get the same
authorisation and the same injected `State` for free — a property no third-party adapter in the
ecosystem offers, and the main reason a dual-era core belongs here rather than in a shim.

**The supported set is a frozenset, not a version-union type.** Adding a fifth string is a one-line
diff: no generated schema to regenerate, no compile-time exhaustiveness to satisfy. The Rust, Go, and
C# implementations must touch a tagged union to do the same.

**Two dependencies.** `lauren` and `anyio` (E-222). Every candidate library that solves this problem
drags in a JSON-schema validator, an HTTP client, and a schema generator. The design below adds one
~90-line module.

---

## 4. Design

### 4.1 Era as a first-class value — `src/lauren_mcp/_era.py` (new)

Era is coarser than revision, because `2026-07-28` replaces the handshake, session model, and result
shape rather than extending them. It must be a value derived per request.

```python
# src/lauren_mcp/_era.py  (new file, ~90 lines)
"""Protocol era classification for dual-era negotiation."""

from __future__ import annotations

from enum import Enum
from typing import Any, Mapping

from lauren_mcp._mcp_version import MODERN_REVISIONS

META_REVISION_KEY = "io.modelcontextprotocol/protocolVersion"


class ProtocolEra(str, Enum):
    """Wire dialect of one request."""

    LEGACY = "legacy"
    MODERN = "modern"


def era_for_revision(revision: str | None) -> ProtocolEra:
    """Classify *revision*; unknown or absent revisions are legacy.

    Deliberate: a legacy initialize may omit protocolVersion, and legacy is
    the conservative answer for anything unrecognised.
    """
    if revision and revision in MODERN_REVISIONS:
        return ProtocolEra.MODERN
    return ProtocolEra.LEGACY


def era_from_meta(params: Mapping[str, Any] | None) -> ProtocolEra:
    """Read the era from a request's per-request ``_meta`` envelope (E-22)."""
    if not params:
        return ProtocolEra.LEGACY
    meta = params.get("_meta")
    if not isinstance(meta, Mapping):
        return ProtocolEra.LEGACY
    revision = meta.get(META_REVISION_KEY)
    return era_for_revision(revision if isinstance(revision, str) else None)


def era_from_header(value: str | None) -> ProtocolEra:
    """Read the era from the ``Mcp-Protocol-Version`` header."""
    return era_for_revision(value)
```

`_mcp_version.py` grows by two names. `SUPPORTED` (the negotiation claim) and `MODERN_REVISIONS` (the
era claim) stay separate so they cannot drift into tautology:

```python
# src/lauren_mcp/_mcp_version.py  lines 5-9, proposed
LATEST = "2026-07-28"
STABLE = "2024-11-05"
SUPPORTED = frozenset({"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28"})
MODERN = "2026-07-28"
MODERN_REVISIONS = frozenset({MODERN})
LEGACY_REVISIONS = SUPPORTED - MODERN_REVISIONS
```

A revision may be modern but unsupported (era known, not yet served) — which is what lets a future
`2027-xx-xx` be classified before it is implemented.

### 4.2 `server/discover` — the modern entry point

It carries everything the handshake used to carry (E-22). It reuses the composition internals of
`build_initialize_result`, so one place still decides what "this server is" means:

```python
# src/lauren_mcp/_server/_handshake.py  after build_initialize_result (line 43)
def build_discover_result(
    server_info: Implementation,
    capabilities: ServerCapabilities,
    *,
    instructions: str | None = None,
) -> dict[str, Any]:
    """Build the ``server/discover`` result (E-21, E-22).

    No negotiation: the caller has established the peer is modern, and the
    reply is the complete advertisement in a single frame.
    """
    result: dict[str, Any] = {
        "protocolVersions": sorted(SUPPORTED),
        "serverInfo": server_info.model_dump(by_alias=True, exclude_none=True),
        "capabilities": capabilities.model_dump(by_alias=True, exclude_none=True),
        "resultType": RESULT_TYPE_COMPLETE,
    }
    if instructions is not None:
        result["instructions"] = instructions
    return result
```

```python
# src/lauren_mcp/server/_module.py  after line 415
                async def _discover_handler(params: dict[str, Any] | None) -> dict[str, Any]:
                    # Modern peers never call initialize (E-21); the first
                    # frame must be answered with the full advertisement.
                    return build_discover_result(_server_info, _sc)

                dispatcher.register("server/discover", _discover_handler)
```

It is answered for **both** eras: a legacy client sending it is off-spec, but answering is harmless
and lets a probing client detect a dual-era server in one round trip — the same reasoning that keeps
`ping` registered for legacy peers (`_dispatcher.py:83`).

### 4.3 Per-request era in the dispatcher

The dispatcher is the one chokepoint all four transports funnel through, so era resolution belongs
there and nowhere else. A `ContextVar` keeps it per-task without touching handler signatures — which
matters, because handlers are plain `Callable[[dict | None], Awaitable[dict]]` and changing that would
touch every user-written tool.

```python
# src/lauren_mcp/_server/_dispatcher.py  new module-level state
from contextvars import ContextVar

from lauren_mcp._era import ProtocolEra, era_from_meta

_ERA: ContextVar[ProtocolEra] = ContextVar("lauren_mcp_era", default=ProtocolEra.LEGACY)


def current_era() -> ProtocolEra:
    """Era of the request being handled; ``LEGACY`` outside a request."""
    return _ERA.get()
```

```python
# src/lauren_mcp/_server/_dispatcher.py  lines 101-131, proposed
    async def dispatch(self, request: JsonRpcRequest) -> JsonRpcResponse | JsonRpcErrorResponse:
        handler = self._handlers.get(request.method)
        if handler is None:
            return build_error_response(
                id=request.id,
                code=McpErrorCode.METHOD_NOT_FOUND,
            )
        era = era_from_meta(request.params if isinstance(request.params, dict) else None)
        token = _ERA.set(era)
        try:
            result = await handler(request.params)
            return JsonRpcResponse(
                id=request.id,
                result=shape_result(result, era, method=request.method),
            )
        finally:
            _ERA.reset(token)
```

Ordering matters: `server/discover` and `initialize` travel the same path, so a modern peer's
`server/discover` already carries a correct era, and `shape_result()` adds `resultType` a second time
harmlessly (idempotent by construction, 4.5).

### 4.4 Sessionless modern Streamable HTTP

```python
# src/lauren_mcp/_server/_streamable.py  line 335, proposed
    def _require_session(self, request: Request) -> StreamableSession | Response:
        # 2026-07-28 removes Mcp-Session-Id entirely (E-20): a modern peer
        # carries its identity in each request's _meta envelope instead.
        if era_from_header(request.headers.get(_PROTOCOL_HEADER)) is ProtocolEra.MODERN:
            return _STATELESS
        session_id = request.headers.get(_SESSION_HEADER)
```

`_STATELESS` is a frozen `StreamableSession` with `session_id=""`, `protocol_version=MODERN`, and no
capabilities. It never enters the session map and never appears in a response header, so it cannot leak
into a legacy client's world, and the session mutations in `_handle_initialize` (`_streamable.py:322`)
are unreachable for it. The modern path stops echoing `Mcp-Session-Id` but keeps echoing
`Mcp-Protocol-Version`, which is how a client confirms the answered revision when it omitted `_meta`.

### 4.5 Result shaping at the edge

`resultType` is required on every `2026-07-28` result, `ttlMs` and `cacheScope` on cacheable list
results (E-27). Both are result concerns, applied once in the dispatcher, never inside handlers where
11 call sites would each have to remember:

```python
# src/lauren_mcp/_server/_result_shape.py  (new file, ~55 lines)
"""Modern-era result shaping (E-27)."""

from __future__ import annotations

from typing import Any

from lauren_mcp._era import ProtocolEra

RESULT_TYPE_COMPLETE = "complete"

_CACHEABLE = frozenset({"tools/list", "resources/list", "prompts/list", "resources/templates/list"})
_DEFAULT_TTL_MS = 60_000


def shape_result(
    result: dict[str, Any],
    era: ProtocolEra,
    *,
    method: str = "",
    ttl_ms: int = _DEFAULT_TTL_MS,
) -> dict[str, Any]:
    """Add ``2026-07-28`` discriminators; return *result* untouched for legacy.

    ``setdefault`` keeps this idempotent, so a handler that already set
    ``resultType`` (``server/discover``) is not corrupted.
    """
    if era is ProtocolEra.LEGACY or not isinstance(result, dict):
        return result
    shaped = dict(result)
    shaped.setdefault("resultType", RESULT_TYPE_COMPLETE)
    if method in _CACHEABLE:
        shaped.setdefault("ttlMs", ttl_ms)
        shaped.setdefault("cacheScope", "server")
    return shaped
```

Legacy results come back as the *same object*, so no legacy client observes even a key reordering.

### 4.6 Public API — one kwarg

```python
from lauren_mcp import McpServerModule
from lauren_mcp.server import McpServer

server = McpServerModule.for_root(
    McpServer,
    transport="streamable-http",
    protocol_eras=frozenset({"2024-11-05", "2025-11-25", "2026-07-28"}),
)
```

```python
# src/lauren_mcp/server/_module.py  lines 74-75, proposed
        instrument_otel: bool = False,
        protocol_eras: frozenset[str] | None = None,   # NEW
    ) -> type:
```

`None` means "serve everything in `SUPPORTED`" — the dual-era default, so existing call sites become
dual-era without an edit. An explicit frozenset narrows the served set without editing module
constants. A revision absent from `SUPPORTED` raises `ValueError` at construction, not at request
time.

**Scope of the change.** Era changes nothing else: the method namespace (all 11 registered methods already use slashed names
such as `tools/call`, `_module.py:457`), the error enum, and the guard pipeline are untouched. Era is
resolved *before* dispatch and guards run *inside* it, so authorisation is identical in both eras.

---

## 5. Server-side Changes

| File | Change | Risk |
|---|---|---|
| `_mcp_version.py` | Add `MODERN`, `MODERN_REVISIONS`, `LEGACY_REVISIONS`; extend `SUPPORTED` | Low — constants |
| `_era.py` (new) | `ProtocolEra`, `era_for_revision`, `era_from_meta`, `era_from_header` | Low — pure |
| `_result_shape.py` (new) | `shape_result`, `RESULT_TYPE_COMPLETE` | Low — pure |
| `_handshake.py` | Add `build_discover_result`; keep the `LATEST` fallback legacy-bound | Low |
| `_dispatcher.py` | `_ERA` contextvar, `current_era()`, era + shaping in `dispatch()` | Medium — hot path |
| `_streamable.py` | Era-aware `_require_session`; `_STATELESS`; conditional session header | Medium — transport |
| `server/_module.py` | `protocol_eras` kwarg; `_discover_handler` + registration | Medium — public API |

**Not touched:** `_ws.py`, `_stdio.py`, `_sse.py`, `_handlers.py`, `_decorators.py`, `_client/*` — all
inherit dual-era behaviour by calling `McpDispatcher.dispatch()`.

---

## 6. Exact Lines to Change

### 6.1 `src/lauren_mcp/_mcp_version.py` lines 5-7

```python
# current
LATEST = "2025-11-25"
STABLE = "2024-11-05"
SUPPORTED = frozenset({"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"})

# proposed
LATEST = "2026-07-28"
STABLE = "2024-11-05"
SUPPORTED = frozenset({"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25", "2026-07-28"})
MODERN = "2026-07-28"
MODERN_REVISIONS = frozenset({MODERN})
LEGACY_REVISIONS = SUPPORTED - MODERN_REVISIONS
```

`LATEST` moving is the one change with reach, and 6.2 exists so it cannot misfire. See Open Question 5
for the timing caveat: keep `LATEST = "2025-11-25"` until the subscription PRD lands.

### 6.2 `src/lauren_mcp/_server/_handshake.py` lines 23-25

```python
# current
    if client_version in SUPPORTED:
        return client_version
    return LATEST

# proposed
    if client_version in SUPPORTED:
        return client_version
    # An unknown revision is answered in the legacy dialect; never guess
    # "modern" for a peer we cannot classify (E-21).
    return STABLE
```

### 6.3 `src/lauren_mcp/_server/_dispatcher.py` lines 101-131

Replace the head of `dispatch()` with 4.3. The existing `except` clauses (`asyncio.CancelledError`
:134, `McpInvalidParamsError` :142, generic :148) are unchanged, and `_ERA.reset(token)` goes in a
`finally` around them: a leaked contextvar in a reused task would make the next request inherit the
previous client's era.

### 6.4 `src/lauren_mcp/_server/_streamable.py` line 335

Replace the first two statements of `_require_session()` with the era guard in 4.4, and add the
`_STATELESS` sentinel beside `StreamableSession` (line 47).

### 6.5 `src/lauren_mcp/server/_module.py` lines 74-75 and 415

```python
# current, line 74
        instrument_otel: bool = False,
    ) -> type:

# current, line 415
                dispatcher.register("initialize", _initialize_handler)

# proposed: the kwarg from 4.6, then append after line 415
                async def _discover_handler(params: dict[str, Any] | None) -> dict[str, Any]:
                    return build_discover_result(_server_info, _sc)

                dispatcher.register("server/discover", _discover_handler)
```

---

## 7. Backward Compatibility

**Legacy clients see no change.** For a peer in `LEGACY_REVISIONS`, `shape_result()` returns the
original object, `_require_session()` takes the unchanged path, `initialize` is still the entry point,
`Mcp-Session-Id` is still issued and demanded, and `ping` (`_dispatcher.py:83`) still answers `{}`.

**One observable change.** `LATEST` moves to `"2026-07-28"` (6.1). A client sending a revision outside
`SUPPORTED` currently receives `"2025-11-25"`; with 6.2 it receives `"2024-11-05"`. Clients pinned to a
supported revision are unaffected. 6.1 and 6.2 must land together.

**Migration for existing users: none.** Every `for_root()` call site gets `protocol_eras=None`, which
resolves to all of `SUPPORTED`. It is genuinely none because era resolution is per request and defaults
to `ProtocolEra.LEGACY`, so nothing previously served in the legacy dialect stops being served in it.

**Version recommendation:** `1.1.0` — additive constants, additive method, one defaulted kwarg, one
fallback fix. Not a major: no modern *client* exists to break.

**Doc drift to fix in the same commit:** the supported-range table in `README.md` and `docs/` must
gain `2026-07-28`, or the repository will claim less than it does.

---

## 8. Test Plan

### 8.1 Unit tests — `tests/unit/test_era.py`

1. `era_for_revision("2026-07-28") is ProtocolEra.MODERN`.
2. `LEGACY` for `"2025-06-18"`, `"2024-11-05"`, `None`, `""`, `"not-a-version"`, `"2027-01-01"` — an
   unknown future revision must not be guessed modern.
3. `era_from_meta({"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}})` is `MODERN`;
   `era_from_meta({})`, `era_from_meta(None)`, `era_from_meta({"_meta": "nope"})` are `LEGACY`.
4. `era_from_header("2026-07-28")` is `MODERN`; `era_from_header(None)` is `LEGACY`.

### 8.2 Unit tests — `tests/unit/test_result_shape.py`

1. Legacy: the returned object *is* the input object — identity, not equality.
2. Modern generic: gains `resultType == "complete"`.
3. Modern `tools/list`: gains `ttlMs` and `cacheScope`; `tools/call` gains neither.
4. Idempotence: shaping a shaped result changes nothing — what makes the double application to a
   `server/discover` reply safe.

### 8.3 Unit tests — `tests/unit/test_discover.py`

1. `build_discover_result(...)` has `protocolVersions`, `serverInfo`, `capabilities`, `resultType`;
   revisions are sorted and include both `"2024-11-05"` and `"2026-07-28"`.
2. `instructions` absent when `None`, present verbatim otherwise.
3. Via `McpDispatcher`: `server/discover` with a modern `_meta` returns a `resultType`-bearing result;
   with a legacy `_meta` it succeeds and carries no `resultType`.
4. `negotiate_version("2026-07-28") == "2026-07-28"`; `negotiate_version("2019-01-01") == STABLE`.

### 8.4 Regression gate — `tests/unit/test_mcp_handshake.py` (existing, unmodified)

Must pass without a single edit. If era work leaks into the legacy initialize path, this file fails.

### 8.5 Integration tests — `tests/integration/test_dual_era_streamable.py`

Modelled on `tests/integration/test_mcp_streamable_http.py`.

1. **Modern happy path:** `tools/call` with `_meta` revision `2026-07-28`, no `Mcp-Session-Id` → 200,
   result carries `resultType`.
2. **Legacy happy path:** `initialize` → 200 with `Mcp-Session-Id` and `Mcp-Protocol-Version`;
   `tools/list` with the session header → 200, no `resultType`, no `ttlMs`.
3. **Interleaving:** one module, alternating modern and legacy requests on two connections; each
   response's shape matches its own request. This is the contextvar-leak test.
4. **Missing session on legacy:** `tools/call` with no session header and no `_meta` → the existing
   error status, unchanged.
5. **`server/discover` over HTTP** with no session header → 200 with a `protocolVersions` list.

`tests/integration/test_dual_era_ws.py` repeats case 3 over WebSocket (`_ws.py:236`), proving the
dispatcher is the single chokepoint and the design does not depend on HTTP headers.

---

## 9. Open Questions

1. **Does `server/discover` take parameters?** The `2026-07-28` tree names the method and its result
   (E-21, E-22) but this research did not enumerate a parameter schema. The design assumes empty or
   arbitrary `params` and ignores them. Resolve by reading `server/discover.mdx` in full.
2. **Is `Mcp-Protocol-Version` still a response header in the modern era?** E-22 moves the revision
   into `_meta`, implying the header is redundant or removed. The design keeps echoing it, because a
   header a client ignores is harmless and its absence might not be.
3. **What `ttlMs` and `cacheScope` values?** `60_000` / `"server"` are placeholders; the answer depends
   on whether the catalog is hot-reloadable (`_module.py:519`), which this PRD cannot settle.
4. **Is `SUPPORTED` or `protocol_eras` authoritative?** Both exist, the kwarg narrowing the constant.
   One source of truth would mean the constant becomes the kwarg's default.
5. **`LATEST` migration timing.** Advertising `LATEST = "2026-07-28"` overclaims while
   `subscriptions/listen` (E-23) is unimplemented. Recommendation: land 6.1 but hold `LATEST` at
   `"2025-11-25"` until that PRD merges.
6. **Sequencing against the cancellation fix.** `$/cancelRequest` (E-237) is a legacy conformance bug
   *today*; neither fix depends on the other's code, so order them as convenient.

---

## 10. References

**Specification and changelog**

- E-20 — Sessions removed; `Mcp-Session-Id` absent from the `2026-07-28` Streamable HTTP schema.
- E-21 — `initialize` removed for modern peers; `server/discover` is a MUST.
  <https://github.com/modelcontextprotocol/modelcontextprotocol>
- E-22 — Per-request `_meta` carries `protocolVersion`, `clientInfo`, `clientCapabilities`,
  `serverInfo`, `logLevel` (SEP-2567 / SEP-2575).
- E-23 — `subscriptions/listen` replaces the HTTP GET channel.
- E-24 — `ping`, `logging/setLevel`, `roots/list_changed` removed.
- E-25 — Tasks become the `io.modelcontextprotocol/tasks` extension (SEP-2663).
- E-26 — Server-initiated sampling/elicitation/roots replaced by MRTR.
- E-27 — Every result carries `resultType`; cacheable list results carry `ttlMs` + `cacheScope`
  (SEP-2549).
- E-28 — SSE resumability removed (`Last-Event-ID` replay no longer specified).
- E-29 — Error codes renumbered; resource-not-found standardised (SEP-2164).

**Repository (each verified with `grep -n` / `sed -n` at `7778737`)**

- `src/lauren_mcp/_mcp_version.py:5-7` — `LATEST`, `STABLE`, `SUPPORTED` (E-225, E-226).
- `src/lauren_mcp/_server/_handshake.py:14`, `:23-25`, `:28`, `:38` — `negotiate_version`,
  `build_initialize_result`.
- `src/lauren_mcp/_server/_dispatcher.py:80`, `:83`, `:101`, `:118`, `:134`, `:142` — `ping`,
  registration, `dispatch`, `METHOD_NOT_FOUND`.
- `src/lauren_mcp/_server/_streamable.py:41`, `:42`, `:315`, `:332`, `:335` — session and protocol
  headers, `_handle_initialize`, `_require_session`.
- `src/lauren_mcp/_server/_ws.py:38`, `:236` — `notifications/initialized`, `initialize` branch.
- `src/lauren_mcp/_server/_stdio.py:50` — ndjson read loop.
- `src/lauren_mcp/server/_module.py:62-75`, `:367`, `:415`, `:457-458`, `:532-533`, `:544` —
  `for_root` signature, initialize handler, and the 11 registrations.
- `src/lauren_mcp/server/_decorators.py:44`, `:758`, `:874`, `:988`, `:1064` — `@use_guards` reading,
  `mcp_tool`, `mcp_resource`, `mcp_prompt`, `mcp_completion`.

**Internal inputs**

- `prds/2026-11-landscape/EVIDENCE.md` — E-220 (v1.0.0, 2026-06-14), E-222 (two dependencies),
  E-225/E-226 (version constants), E-230 … E-237 (zero-hit absences).
- `prds/2026-11-landscape/VERSIONS-MATRIX.md` §1, §2, §9.1 — revision table, mandatory modern-era
  surface per implementation, capability deltas.
- `prds/2026-11-landscape/_research/lauren-mcp-inventory.md` §1, §2, §3, §6 — package, protocol
  versions, transports, decorators and DI.
