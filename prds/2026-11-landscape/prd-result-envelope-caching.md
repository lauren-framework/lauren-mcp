# PRD — Result envelope and list-result caching for `2026-07-28`

**Status:** Draft  
**Date:** 2026-11-26  
**Scope:** `_types.py`, `_server/_dispatcher.py`, `_server/_envelope.py` (new), `server/_decorators.py`, `server/_meta.py`, `server/_module.py`, `_client/_cache.py` (new), `_client/_base_remote.py`, `_client/_stdio.py`, `_client/_protocol.py`  
**Priority:** P1 — `resultType` is a MUST on every `2026-07-28` result (E-27, E-232; VERSIONS-MATRIX §2 row `resultType`), so a modern client reads a key we never emit. That is the P1 test in the brief §4 — "we are non-conformant today" — not a missing nicety.  
**Issue:** [#63](https://github.com/lauren-framework/lauren-mcp/issues/63)

---

## 1. Problem Statement

`lauren-mcp` implements the legacy era completely and has **zero** `2026-07-28` surface (EVIDENCE §2; `grep -ril 'resultType' src/` → `0`, E-232). Two failures follow from this repository's own code.

### 1.1 A modern client cannot tell a complete result from a deferred one

Every result is an undecorated JSON object. `tools/list` ends here:

```python
# src/lauren_mcp/server/_handlers.py:591
        return {"tools": [_tool_list_entry(t) for t in get_tools()]}
```

`tools/call` ends here:

```python
# src/lauren_mcp/server/_handlers.py:670-673
    out: dict[str, Any] = {"content": content, "isError": is_error}
    if structured is not None:
        out["structuredContent"] = structured
    return out
```

The dispatcher wraps that dict verbatim, and `to_json` dumps it with no schema awareness:

```python
# src/lauren_mcp/_server/_dispatcher.py:130-132
        try:
            result = await task
            return JsonRpcResponse(id=request.id, result=result)

# src/lauren_mcp/_types.py:65-71
    def to_json(self) -> str:
        obj: dict[str, Any] = {
            "jsonrpc": self.jsonrpc,
            "id": self.id,
            "result": self.result,
        }
        return json.dumps(obj)
```

A `2026-07-28` peer expects `resultType` on **every** result (E-27). Our results carry `content`/`isError`/`structuredContent` (`_types.py:312-313`) and one of three list keys — `{"tools": …}` at `_handlers.py:591`, `{"resources": …}` at `:1056`, `{"prompts": …}` at `:1304` — and nothing else. A host that switches on `resultType` gets `undefined` on all of them. Because the modern era also removes `initialize` in favour of per-request `_meta` (E-21, E-22), the host has no negotiated state to fall back on; the field is simply missing on the result it is holding.

### 1.2 Every list is refetched, forever, by every client

`ttlMs` and `cacheScope` do not exist anywhere in this tree (E-233, E-234 — both `0` file hits). Nothing advertises freshness, so no client can cache, and our own client does not even try:

```python
# src/lauren_mcp/_client/_base_remote.py:217-226
    async def list_tools(self) -> list[ToolSchema]:
        result = await self._request("tools/list")
        return [
            ToolSchema(
                name=t["name"],
                description=t.get("description", ""),
                inputSchema=t.get("inputSchema", {}),
            )
            for t in result.get("tools", [])
        ]
```

`result.get("tools", [])` discards the entire envelope. The same shape repeats in `list_resources` (`:238`), `list_prompts` (`:253`), and again for stdio in `_client/_stdio.py:380`. An agent loop that asks for the tool list once per turn pays a round trip per turn *and* makes the server rebuild the comprehension at `_handlers.py:591` per turn. There is no `nextCursor` either (`grep -rn 'nextCursor' src/lauren_mcp --include=*.py` → no hits), which is why the cache key in §4.6 is method-only, with a documented cursor slot for the pagination PRD.

## 2. Goals

1. Every successful result returned to a peer identifying as `2026-07-28` carries `resultType`. Legacy peers receive byte-identical output.
2. `tools/list`, `resources/list`, `prompts/list` results carry `ttlMs` and `cacheScope` for modern peers only.
3. Cache policy is declarative at registration time — one server-level value, no handler signature change.
4. Our clients honour `ttlMs`/`cacheScope`; `force_refresh=True` bypasses the cache on every list method.
5. The client cache invalidates on `list_changed` and on `connect()`.
6. Zero new runtime dependencies: `time.monotonic` and `anyio` only (E-222).

### Acceptance checklist

- [ ] `grep -ril 'resultType' src/lauren_mcp --include=*.py | wc -l` ≥ `1` (today: `0`, E-232).
- [ ] `grep -ril 'ttlMs' src/lauren_mcp --include=*.py | wc -l` ≥ `1` (today: `0`, E-233).
- [ ] `grep -ril 'cacheScope' src/lauren_mcp --include=*.py | wc -l` ≥ `1` (today: `0`, E-234).
- [ ] `uv run pytest tests/unit/test_result_envelope.py -q` passes.
- [ ] `uv run pytest tests/unit/test_list_cache.py -q` passes.
- [ ] `uv run pytest tests/integration/test_result_envelope_caching.py -q` passes.
- [ ] `uv run pytest tests/unit/test_result_envelope.py -q -k legacy` passes (§7 byte test).
- [ ] `uv run pytest tests/unit -q` shows no new failures (CI baseline: `.github/workflows/tests.yml:155`).
- [ ] `grep -n '^import \|^from ' src/lauren_mcp/_client/_cache.py` lists only `__future__`, `time`, `dataclasses`, `typing`.
- [ ] `python -c "from lauren_mcp.server import mcp_server; import inspect; print('cache' in inspect.signature(mcp_server).parameters)"` prints `True`.

## 3. Non-Goals

- **MRTR / `input_required`.** This PRD emits `resultType: "complete"` and reserves the field (E-26). Deferred-result bodies belong to the MRTR PRD.
- **`server/discover` and version negotiation.** Era detection reads per-request `_meta` (E-22); discovery itself is out of scope (E-21). If the negotiation PRD lands first and adds `"2026-07-28"` to `SUPPORTED` (`_mcp_version.py:7`), the two compose without conflict.
- **Cursor pagination.** Not implemented today, and caching a partial page is meaningless; the cache key reserves a cursor slot (§4.6).
- **Server-side memoisation.** `ttlMs` is advertised, not consumed: the server keeps recomputing `get_tools()` at `_handlers.py:591`.
- **`Cache-Control` headers on the Streamable HTTP transport.** The fields are payload-level (E-27); whether the HTTP layer must mirror them is §9 Q4.
- **`subscriptions/listen` (E-23).** Separate PRD. §4.7 hooks the legacy `list_changed` notifications this repo already forwards (`_base_remote.py:64`, `:81`).
- **Persistence.** Client cache is in-memory only.

## lauren-mcp Advantages

Four structural facts make this cheaper here than in a hand-rolled SDK integration.

1. **One dispatch choke point.** Every transport funnels through `McpDispatcher.dispatch` (`_server/_dispatcher.py:101`) before the response is built at `:132`. Stamping there is ~6 lines and cannot be missed by a handler added later. SDKs that construct envelopes per method or per transport repeat the discipline per path (E-80…E-90: `resultType` presence counts range 4–112 across implementations).
2. **The wire types are ours.** `JsonRpcResponse` (`_types.py:57`) and `ToolResult` (`:300`) are dataclasses in this package, so the envelope is a field, not a schema-generation problem — and the optional-Pydantic/msgspec posture (inventory §1) means no regeneration step is triggered.
3. **Typed surface at registration time.** `@mcp_server` already carries `McpServerMeta` (`_meta.py:38`) and `@mcp_tool` already takes `meta` (`_decorators.py:766`), so a cache policy is one defaulted field on an existing DI injection point.
4. **Three client transports, one base class.** `McpStreamableHttpClient` (`_streamable.py:28`) and `McpWebSocketClient` (`_ws.py:30`) extend `_McpBaseRemoteClient`; `McpStdioClient` (`_stdio.py:40`) implements the same `McpClientProtocol` (`_protocol.py:15`), whose abstract `list_tools` at `:49` is where the new keyword gets documented.

Honest caveat: every SDK that ships `2026-07-28` ships these fields. The advantage is cost and blast radius, not capability.

## 4. Design

### 4.1 The envelope, on the wire

| Field | Type | Appears on | Legacy peers |
|---|---|---|---|
| `resultType` | `"complete"` (this PRD) | every successful result | absent |
| `ttlMs` | `int` (milliseconds) | the three list results | absent |
| `cacheScope` | `"private"` \| `"public"` | the three list results | absent |

Before, `tools/list`:

```json
{"jsonrpc":"2.0","id":7,"result":{"tools":[{"name":"search","inputSchema":{}}]}}
```

After, for a request whose `_meta` says `2026-07-28`:

```json
{"jsonrpc":"2.0","id":7,"result":{
  "tools":[{"name":"search","inputSchema":{}}],
  "resultType":"complete","ttlMs":60000,"cacheScope":"private"}}
```

`tools/call`, `resources/read`, `prompts/get` and `initialize` results get `resultType` and nothing else. JSON-RPC **errors** are not results and are never stamped (`JsonRpcError`, `_types.py:75`, is untouched).

### 4.2 Era detection reads per-request `_meta`

The modern era removed `initialize` (E-21); the revision travels in `params._meta["io.modelcontextprotocol/protocolVersion"]` on every request (E-22). That is the only sound detector and it needs no session state — which matters because sessions are being removed (E-20) while this repo still keeps `SseSessionStore`/`StreamableSessionStore` (`_module.py:638-639`).

```python
# src/lauren_mcp/_server/_envelope.py  (new module)
"""`2026-07-28` result-envelope helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

MODERN: Final = "2026-07-28"   # first revision requiring `resultType` (E-27)
META_VERSION_KEY: Final = "io.modelcontextprotocol/protocolVersion"  # E-22

CacheScope = Literal["private", "public"]      # E-234
Era = Literal["legacy", "modern"]


def request_era(params: dict[str, Any] | None) -> Era:
    """Return the era of the peer that sent this request.

    A missing `_meta`, a non-dict `_meta`, and every revision in
    `_mcp_version.SUPPORTED` (`src/lauren_mcp/_mcp_version.py:7`) are
    legacy, so the pre-2026 wire shape is preserved byte for byte.
    """
    if not isinstance(params, dict):
        return "legacy"
    meta = params.get("_meta")
    if not isinstance(meta, dict):
        return "legacy"
    return "modern" if meta.get(META_VERSION_KEY) == MODERN else "legacy"


@dataclass(frozen=True, slots=True)
class CachePolicy:
    """Advertised freshness for one cacheable list method."""

    ttl_ms: int = 0                 # 0 == do not cache (see §9 Q2)
    scope: CacheScope = "private"

    def as_result_fields(self) -> dict[str, Any]:
        return {"ttlMs": int(self.ttl_ms), "cacheScope": self.scope}


@dataclass(frozen=True, slots=True)
class EnvelopePolicy:
    lists: dict[str, CachePolicy] = None  # type: ignore[assignment]

    def policy_for(self, method: str) -> CachePolicy | None:
        return (self.lists or {}).get(method)


def stamp_result(result: Any, params: dict[str, Any] | None,
                 cache: CachePolicy | None = None) -> Any:
    """Return `result` with the `2026-07-28` envelope applied.

    Copied, not mutated: handlers may hand back a dict they keep a
    reference to (a catalog snapshot), and stamping must not touch it.
    """
    if not isinstance(result, dict):
        return result                    # errors, None, scalars
    if request_era(params) != "modern":
        return result                    # legacy peers: old bytes
    out = dict(result)
    out.setdefault("resultType", "complete")   # a handler may set it first
    if cache is not None:
        out.update(cache.as_result_fields())
    return out
```

`setdefault` keeps the door open for MRTR without editing this module.

### 4.3 Server: stamp once, in the dispatcher

`dispatch` already holds both the request params and the raw result:

```python
# src/lauren_mcp/_server/_dispatcher.py:122-132  (current)
        params: dict[str, Any] | None = request.params if isinstance(request.params, dict) else None
        task: asyncio.Task[Any] = asyncio.create_task(handler(**…))
        try:
            result = await task
            return JsonRpcResponse(id=request.id, result=result)
```

The change is one call plus the policy lookup:

```python
# src/lauren_mcp/_server/_dispatcher.py  (new)
        try:
            result = await task
            result = stamp_result(
                result, params,
                self.envelope.policy_for(request.method) if self.envelope else None,
            )
            return JsonRpcResponse(id=request.id, result=result)
```

with `self.envelope: EnvelopePolicy | None = None` added to `McpDispatcher.__init__` (`_dispatcher.py:58`) so existing constructions keep working.

Why the dispatcher and not each handler: the three list handlers return three shapes (`_handlers.py:591`, `:1056`, `:1304`) and `tools/call` a fourth (`:670`). Stamping per handler is four edits a fifth handler can forget; stamping in `dispatch` covers every method registered at `_module.py:415`, `:457`, `:476`, `:532` and anything user code registers through the public `register` (`_dispatcher.py:101`).

### 4.4 Server: declaring the policy

```python
# src/lauren_mcp/server/_decorators.py  (new signature)
def mcp_server(
    path: str,
    *,
    transport: str = "ws",
    cache: "CachePolicy | None" = None,
) -> Callable[[type], type]:
```

One defaulted field on `McpServerMeta` (`_meta.py:38`), so the existing `McpServerMeta(path=…, transport=…)` construction at `_decorators.py:752` stays valid:

```python
# src/lauren_mcp/server/_meta.py  (new field)
    cache: "CachePolicy | None" = None
```

Usage:

```python
from lauren_mcp.server import mcp_server, mcp_tool
from lauren_mcp._server._envelope import CachePolicy

@mcp_server("/mcp", transport="streamable", cache=CachePolicy(ttl_ms=60_000, scope="public"))
class CatalogServer:
    """Tool list is stable for a minute and identical for every caller."""

    @mcp_tool(name="search")
    async def search(self, q: str) -> dict: ...
```

`scope="public"` says a shared intermediary may reuse the list; `"private"` (default) says it may not. The server does not enforce the distinction — it advertises it (§3, non-goal on memoisation).

### 4.5 Wiring, without touching any handler

The registrar that wires coroutines onto the dispatcher (`_module.py:293`) copies the declarative policy onto the injectable dispatcher, just before the list methods are registered at `_module.py:457`:

```python
# src/lauren_mcp/server/_module.py  (new lines in _McpHandlerRegistrar.__init__)
            from lauren_mcp._server._envelope import CachePolicy, EnvelopePolicy

            _cache = meta.cache or CachePolicy()
            dispatcher.envelope = EnvelopePolicy(
                lists={"tools/list": _cache, "resources/list": _cache,
                       "prompts/list": _cache}
            )
```

A per-method override is a dict entry; this PRD ships one policy for all three lists and keeps per-tool granularity out of scope.

### 4.6 Client: a cache that reads the hints

```python
# src/lauren_mcp/_client/_cache.py  (new)
"""Client-side honouring of `ttlMs` / `cacheScope` (E-27)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class CachedList(Generic[T]):
    items: list[T]
    ttl_ms: int
    scope: str
    stored_at: float


@dataclass
class ListCache:
    """In-memory cache keyed by list method name.

    Method-only key: `nextCursor` is not implemented in this repo yet, and
    the pagination PRD widens the key to (method, cursor) without changing
    this API.
    """

    _entries: dict[str, CachedList[Any]] = field(default_factory=dict)
    clock: Callable[[], float] = time.monotonic

    def get(self, method: str) -> list[Any] | None:
        entry = self._entries.get(method)
        if entry is None or entry.ttl_ms <= 0:
            return None
        if (self.clock() - entry.stored_at) * 1000 >= entry.ttl_ms:
            del self._entries[method]
            return None
        return entry.items

    def put(self, method: str, items: list[Any], result: dict[str, Any]) -> None:
        ttl_ms = int(result.get("ttlMs") or 0)
        if ttl_ms <= 0:
            self._entries.pop(method, None)      # server retracted freshness
            return
        self._entries[method] = CachedList(
            items=items, ttl_ms=ttl_ms,
            scope=str(result.get("cacheScope") or "private"),
            stored_at=self.clock(),
        )

    def invalidate(self, method: str | None = None) -> None:
        self._entries.clear() if method is None else self._entries.pop(method, None)
```

The injected `clock` is the only test seam — no sleeping (§8.2).

### 4.7 Client: list methods honour it

`list_tools` keeps its return type and gains one keyword-only parameter:

```python
# src/lauren_mcp/_client/_base_remote.py:217  (new)
    async def list_tools(self, *, force_refresh: bool = False) -> list[ToolSchema]:
        if not force_refresh:
            cached = self._list_cache.get("tools/list")
            if cached is not None:
                return cached
        result = await self._request("tools/list")
        tools = [
            ToolSchema(
                name=t["name"],
                description=t.get("description", ""),
                inputSchema=t.get("inputSchema", {}),
            )
            for t in result.get("tools", [])
        ]
        self._list_cache.put("tools/list", tools, result)
        return tools
```

`self._list_cache = ListCache()` goes in `__init__` (`_base_remote.py:53`); the identical pattern applies at `:238` (`resources/list`), `:253` (`prompts/list`), and `_stdio.py:380` for stdio.

Invalidation hangs off the handler this repo already forwards (`_base_remote.py:64`, `:81`):

```python
# src/lauren_mcp/_client/_base_remote.py  (new, inside __init__)
        _inner = list_changed_handler

        def _on_list_changed(kind: str) -> None:
            self._list_cache.invalidate(
                {"tools": "tools/list", "resources": "resources/list",
                 "prompts": "prompts/list"}.get(kind))
            if _inner is not None:
                _inner(kind)
```

`connect()` calls `self._list_cache.invalidate()` so a reconnect never serves a list from a dead connection.

## 5. Server-side and Client-side Changes

Server, in order: add `_server/_envelope.py` (§4.2); add `envelope` to `McpDispatcher.__init__` and one `stamp_result` call in `dispatch` (§4.3); add `cache` to `McpServerMeta`; add `cache=` to `mcp_server` and forward it at `_decorators.py:752`; have the registrar set `dispatcher.envelope` before `register("tools/list", …)` at `_module.py:457`; add `result_type` to `ToolResult` (`_types.py:300`) so the dataclass matches the wire; add `MODERN_REVISION = "2026-07-28"` to `_mcp_version.py`, imported by `_envelope.MODERN` rather than a second literal.

Client, in order: add `_client/_cache.py`; add the cache to `_McpBaseRemoteClient.__init__` (`:53`) and `force_refresh` to `list_tools` (`:217`), `list_resources` (`:238`), `list_prompts` (`:253`) plus the `list_changed` wrapper; mirror it on `McpStdioClient.__init__` (`_stdio.py:40`) and `list_tools` (`:380`); add `force_refresh` to the abstract list methods at `_protocol.py:49`, defaulted so third-party subclasses keep compiling.

No change to any handler body, and none at all to `server/_handlers.py` — that is the point of §4.3.

## 6. Exact Lines to Change

### 6.1 Server: dispatcher, envelope module, versions

| `path:line` | Current | Change |
|---|---|---|
| `_server/_dispatcher.py:58` | `class McpDispatcher:` | add `envelope: EnvelopePolicy \| None = None` to `__init__` |
| `_server/_dispatcher.py:122` | `params: … if isinstance(request.params, dict) else None` | unchanged — the era source |
| `_server/_dispatcher.py:132` | `return JsonRpcResponse(id=request.id, result=result)` | insert `result = stamp_result(result, params, …)` one line before |
| `_server/_envelope.py` | file absent | new, §4.2 verbatim (~70 lines) |
| `_mcp_version.py:5` | `LATEST = "2025-11-25"` | unchanged (legacy latest, via `negotiate_version`, `_server/_handshake.py:14`) |
| `_mcp_version.py:7` | `SUPPORTED = frozenset({…})` | unchanged here — negotiation PRD owns it; append `MODERN_REVISION = "2026-07-28"` below |
| `_types.py:313` | `structuredContent: dict[str, Any] \| None = None` | add `result_type: str \| None = None` after it |
| `_types.py:57` | `class JsonRpcResponse:` | unchanged — the envelope lives in `result`, not the JSON-RPC frame |

### 6.2 Server: decorator, metadata, wiring

| `path:line` | Current | Change |
|---|---|---|
| `server/_meta.py:42` | `transport: str  # "ws" \| "sse" \| "streamable" \| "both"` | add `cache: "CachePolicy \| None" = None` (`TYPE_CHECKING` import, avoids a cycle) |
| `server/_decorators.py:736` | `def mcp_server(path: str, *, transport: str = "ws") -> Callable[[type], type]:` | add `cache: "CachePolicy \| None" = None` |
| `server/_decorators.py:741-743` | `Args:` entries for `path`, `transport` | add a `cache:` entry |
| `server/_decorators.py:752` | `McpServerMeta(path=path, transport=transport)` | `…, cache=cache)` |
| `server/_module.py:294-298` | `_McpHandlerRegistrar.__init__(… dispatcher: McpDispatcher …)` | set `dispatcher.envelope = EnvelopePolicy(lists={…})` per §4.5 |
| `server/_module.py:457`, `:476`, `:532` | `register("tools/list"…)`, `("resources/list"…)`, `("prompts/list"…)` | unchanged — policy is set before these run |

### 6.3 Client

| `path:line` | Current | Change |
|---|---|---|
| `_client/_cache.py` | file absent | new, §4.6 verbatim (~60 lines) |
| `_client/_base_remote.py:53` | `def __init__(` | add `self._list_cache = ListCache()` |
| `_client/_base_remote.py:64`, `:81` | `list_changed_handler: … =` / `list_changed_handler=list_changed_handler,` | unchanged signature; wrap per §4.7 |
| `_client/_base_remote.py:217` | `async def list_tools(self) -> list[ToolSchema]:` | add `*, force_refresh: bool = False`; read/write cache |
| `_client/_base_remote.py:238` | `async def list_resources(self) -> list[ResourceSchema]:` | same, key `"resources/list"` |
| `_client/_base_remote.py:253` | `async def list_prompts(self) -> list[PromptSchema]:` | same, key `"prompts/list"` |
| `_client/_stdio.py:380` | `async def list_tools(self) ->` | add `*, force_refresh: bool = False`; read/write cache |
| `_client/_protocol.py:49` | `async def list_tools(self)` | add `*, force_refresh: bool = False` to the abstract signature |

## 7. Backward Compatibility

- **Legacy peers see the old bytes.** The stamp is gated on `request_era` (§4.2). A request with no `_meta`, or with any `SUPPORTED` revision (`_mcp_version.py:7`), gets the handler's dict untouched — no copy, no extra keys. §8.1 asserts `json.dumps(…, sort_keys=True)` equality against a literal captured from today's behaviour.
- **Existing server code compiles unchanged.** `mcp_server(path, transport=…)` still works: `cache` is keyword-only and defaulted, and `McpServerMeta.cache` is defaulted, so `_decorators.py:752`'s own construction remains valid.
- **Existing client code compiles and behaves unchanged.** `force_refresh` is keyword-only, default `False`, and `list_tools` still returns `list[ToolSchema]`. Caching happens only if the server advertises `ttlMs > 0`, and §4.4's default is `ttl_ms=0` — so lauren-mcp-to-lauren-mcp behaviour is identical to today.
- **`ttlMs: 0` means "do not cache".** `ListCache.put` deletes the entry; a server that retracts freshness is honoured.
- **JSON-RPC errors untouched.** `JsonRpcError` (`_types.py:75`) and the error paths in `dispatch` (`_dispatcher.py:133-136`) never reach `stamp_result`. No new dependency either: `_client/_cache.py` imports `time` and `dataclasses` only (E-222).

### 7.1 Migration notes

**None**, and structurally so: both new keywords are keyword-only with defaults, the wire change is gated on a `_meta` value no current lauren-mcp client sends (our `_meta` use at `_handlers.py:816` is progress tokens only), and the advertised default TTL is `0`, which every published implementation reads as "no caching". Opting in is `cache=CachePolicy(ttl_ms=…)` on the server and nothing on the client.

## 8. Test Plan

### 8.1 Unit tests — `tests/unit/test_result_envelope.py`

Fake params, no network.

1. `test_modern_request_gets_result_type` — `_meta` with `"2026-07-28"` yields `resultType == "complete"`.
2. `test_legacy_request_untouched` — `json.dumps(stamp_result(payload, {}), sort_keys=True)` equals the pre-change literal.
3. `test_2025_11_25_meta_untouched` — a `SUPPORTED` revision takes the legacy path (guards a truthiness bug).
4. `test_non_dict_params_and_meta_are_legacy` — `None`, `[]`, and a string `params`; `_meta` as a string.
5. `test_cache_fields_only_when_policy_given` — `cache=None` emits neither `ttlMs` nor `cacheScope`; `CachePolicy(ttl_ms=1500, scope="public")` → `ttlMs == 1500`, `cacheScope == "public"`.
6. `test_handler_result_not_mutated` — the input dict still lacks `resultType` after a modern stamp.
7. `test_existing_result_type_wins` — a handler-set `"input_required"` survives (`setdefault`).
8. `test_error_object_not_stamped` — `JsonRpcError(...)` passes through unchanged.
9. `test_dispatch_stamps_tools_list` — stub handler returns `{"tools": []}`; `await dispatch(...)` with modern params → `result["resultType"]`.
10. `test_dispatch_legacy_shape_unchanged` — same dispatcher, no `_meta` → `set(result) == {"tools"}`.

### 8.2 Unit tests — `tests/unit/test_list_cache.py`

1. `test_miss_then_hit`.
2. `test_expiry_uses_injected_clock` — advance past `ttl_ms`, `get` returns `None`.
3. `test_zero_ttl_never_stores` — `put` with `{"ttlMs": 0}` leaves no entry; `test_missing_ttl_never_stores` covers `{}`.
4. `test_positive_then_zero_revokes` — a later `ttlMs: 0` clears a live entry.
5. `test_invalidate_one_and_all`, `test_scope_defaults_private`.
6. `test_list_tools_uses_cache` — counting fake `_request`: two `list_tools()` calls, one request.
7. `test_force_refresh_bypasses_cache` — `force_refresh=True` issues a second request and refreshes.

### 8.3 Integration tests — `tests/integration/test_result_envelope_caching.py`

1. `test_streamable_roundtrip_modern` — POST `tools/list` with the `_meta` key; assert all three fields in the JSON body.
2. `test_streamable_roundtrip_legacy` — no `_meta`; assert the three keys are absent.
3. `test_ws_roundtrip_modern` — same assertion over the WebSocket transport, proving the stamp is transport-independent.
4. `test_second_list_served_from_cache` — recording request hook observes zero `tools/list` calls on the second read.
5. `test_list_changed_invalidates_client_cache` — after `notifications/tools/list_changed`, the next `list_tools()` hits the server.

### 8.4 End-to-end — `tests/end_to_end/test_e2e_result_envelope.py`

1. `test_decorated_server_advertises_cache` — `@mcp_server(cache=CachePolicy(ttl_ms=60_000))` driven by `McpStdioClient` sees `ttlMs == 60000`.
2. `test_default_server_is_inert` — default config: `ttlMs == 0` for modern peers, no keys for legacy peers.

## 9. Open Questions

1. **Exact `resultType` vocabulary.** E-27 says every result carries it; the value set for non-MRTR results is not quoted in the evidence. This PRD emits only `"complete"` and never validates input, so a different spelling is a one-constant change. Resolve against the `2026-07-28` schema's `Result` union.
2. **Meaning of `ttlMs: 0`.** Unverified here. This PRD treats `0` and absent as "no caching" — the conservative reading; if the spec says "immediately stale but valid", only `ListCache.get`/`put` change.
3. **`cacheScope` when `ttlMs > 0` but the field is missing.** Server defaults to `"private"`, client reads absent as `"private"`. If the spec mandates the field whenever `ttlMs` is present, `CachePolicy.as_result_fields` already emits both.
4. **Whether `initialize`/`server/discover` results may carry `ttlMs`.** Not emitted; `stamp_result` would pass a policy through, so this is policy, not code.
5. **`Cache-Control` on the Streamable HTTP response.** Whether the transport must mirror the fields in headers is not stated in the evidence available here; if required, it belongs to a follow-up owning `_server/_streamable.py`.

## 10. References

Evidence (`prds/2026-11-landscape/EVIDENCE.md`): **E-20** (sessions removed — motivates per-request detection), **E-21** (`initialize` removed, `server/discover` MUST), **E-22** (per-request `_meta` carries `io.modelcontextprotocol/protocolVersion` — the detector), **E-26** (MRTR `input_required`, reserved), **E-27** (every result carries `resultType`; cacheable list results carry `ttlMs` + `cacheScope` — the requirement), **E-232**, **E-233**, **E-234** (`resultType`/`ttlMs`/`cacheScope` hits in `src/`: **0**), **E-222** (two-dependency posture), **E-80…E-90** (per-SDK presence counts).

Matrices: `VERSIONS-MATRIX.md` §2 rows `resultType` (MUST) and `ttlMs` + `cacheScope` (MUST for lists) · `_research/lauren-mcp-inventory.md` §1 (distribution, 13,330 source lines, optional extras) and §6.1 (`@mcp_server`/`@mcp_tool` at `_decorators.py:736`, `:758`).

Spec: SEP-2549, *TTL for list results* — https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2549-TTL-for-list-results.md

House style model: `prds/prd-protocol-version-negotiation.md`
