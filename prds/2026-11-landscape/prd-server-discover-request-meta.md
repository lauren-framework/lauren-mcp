# PRD — Modern-era discovery: `server/discover` and the per-request `_meta` envelope

**Status:** Draft
**Date:** 2026-11-26
**Scope:** `_mcp_version.py`, `_types.py`, `_server/{_dispatcher,_handshake,_context,_meta_envelope,_discover}.py`, `server/{_module,_handlers}.py`
**Priority:** P1
**Issue:** [#62](https://github.com/lauren-framework/lauren-mcp/issues/62)

---

## 1. Problem Statement

### 1.1 A `2026-07-28` peer cannot see the server at all

The `2026-07-28` revision deletes the `initialize` / `initialized` handshake for modern peers and replaces
it with a mandatory `server/discover` request (**E-21**). The handshake is not deprecated there — it is
**removed**, one of nine mandatory removals that make that revision breaking rather than additive
(**E-20**, **E-21**, **E-30**). `lauren-mcp` 1.0.0 has no `server/discover` at any layer:

```bash
# run from repo root — the acceptance command for this PRD
$ grep -ril 'server/discover' src/ | wc -l
0
```

**E-230** records exactly that zero for this repository. The consequence is an empty session, not a
degraded one: a modern peer opens the transport, sends `server/discover`, receives `-32601`, and holds no
`serverInfo`, no `capabilities`, no `instructions` with which to build a tool list. It cannot fall back,
because it does not implement `initialize` either. Every host in §14 (**E-190** … **E-199**) that graduates
to the modern era loses the whole server, not just its tools. The method dies here:

```python
# src/lauren_mcp/_server/_dispatcher.py  line 114-121
handler = self._handlers.get(request.method)
if handler is None:
    return build_error_response(
        id=request.id,
        code=McpErrorCode.METHOD_NOT_FOUND,
        message=f"Method not found: {request.method}",
    )
```

Correct JSON-RPC, wrong outcome: `-32601` is a *conformance* answer to a request the revision makes
mandatory (**E-21**). A fielded client cannot talk to us — the **P1** definition verbatim. The SDKs that
already answer are counted in §6 (**E-80** … **E-90**); Python 2.3.0 is "yes, dual" with `HANDSHAKE_*` /
`MODERN_*` constants and a `_probe.py` (**E-81**). That is the shape this PRD copies: a second era beside
the first, not instead of it.

### 1.2 The `_meta` envelope is read for one key and discarded

The removed handshake did not remove the information it carried — it moved it into a per-request `_meta`
envelope holding `io.modelcontextprotocol/protocolVersion`, `clientInfo`, `clientCapabilities`,
`serverInfo` and `logLevel` (**E-22**). `lauren-mcp` reads `_meta` in exactly one place:

```python
# src/lauren_mcp/server/_handlers.py  line 816-819
request_meta = params.get("_meta") or {}
progress_token = (
    request_meta.get("progressToken") if isinstance(request_meta, dict) else None
)
```

`progressToken` is picked out; nothing else is inspected, validated or exposed, and
`grep -rl 'io.modelcontextprotocol/' src/ | wc -l` returns `0`. Three bugs follow:

1. **A modern request is indistinguishable from a legacy one** — nothing records the caller's revision, so
   the server cannot shape results per era or refuse a legacy-only request on a modern connection.
2. **A malformed envelope is silently accepted** — `"protocolVersion": 20260728` (an int) or a `clientInfo`
   that is a list produces no `-32602`; the failure surfaces later as a confusing tool error.
3. **Tools cannot see who is calling** — `McpToolContext` (`_server/_context.py:277-299`) carries
   `tool_name`, `tool_use_id`, `headers`, `execution_context`, `session_id`, `metadata`, `state`, and no
   `client_info` or `protocol_version`, so a tool cannot vary its payload by peer revision.

### 1.3 Why P1

**P1** means "correctness or interop blocker: a fielded client cannot talk to us, or we are non-conformant
today". Both clauses hold: `server/discover` is a MUST (**E-21**) and is absent (**E-230**). The P2 test —
"would a modern host silently degrade without it?" — does not apply, because a host on this revision does
not degrade, it fails to connect.

---

## lauren-mcp Advantages

"Adopt the official Python SDK and delete ours" is the obvious alternative. It loses three things this
repository already has, and a discovery handler is small enough that none must be traded away.

1. **Two runtime dependencies.** `lauren>=1.7.0` and `anyio>=4.0` — only two
   (`_research/lauren-mcp-inventory.md` §1). `server/discover` needs none: it builds a dict from values the
   module already resolves (`server/_module.py:250-253`).
2. **DI injection over a hand-rolled registry.** `@mcp_server` classes are resolved through Lauren's
   container (`server/_module.py:62-75`, `providers=` / `imports=` / `mounts=`). Discovery must answer for a
   *composed* server whose tools arrive from mounts and proxies; a framework that owns the module graph can
   answer that, a bare protocol library cannot.
3. **One dispatcher for four transports.** `_server/_stdio.py:62-64`, `_streamable.py`, `_ws.py` and
   `_sse.py` all funnel into `McpDispatcher.dispatch()` (`_server/_dispatcher.py:101`), so the envelope is
   parsed once for all four; SDKs with per-transport handlers repeat the work per transport.

Honest counterweight: upstream Python 2.3.0 is further along on the modern era (**E-81**), `_probe.py`
included. This PRD converges on that behaviour without adopting that dependency; §9 records the one
remaining unknown.

---

## 2. Goals

1. A `2026-07-28` peer sending `server/discover` over any server transport receives a well-formed result with
   `serverInfo`, `capabilities` and `instructions` — no `-32601`, no empty session.
2. `grep -ril 'server/discover' src/ | wc -l` returns ≥ 1 (it returns 0 today — **E-230**).
3. `_mcp_version.py` gains a modern era *beside* the legacy set: `LATEST` stays `"2025-11-25"` and
   `SUPPORTED` stays `{"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}`, so no existing client's
   negotiation changes.
4. Every request's `_meta` envelope is parsed once, in `McpDispatcher.dispatch()`, into an immutable
   `RequestMeta` (**E-22**), reachable from handlers and `McpToolContext` without user code touching
   `params["_meta"]`.
5. A malformed envelope fails fast with `-32602` (`McpErrorCode.INVALID_PARAMS`, `_types.py:117`).
6. Request era is resolved in exactly one function, so the next revision has one place to change.
7. `era_policy="modern"` lets an operator refuse `initialize` with a message naming `server/discover`; the
   default `"dual"` keeps both eras answering.
8. Zero behaviour change for any caller that neither sends `server/discover` nor sends
   `io.modelcontextprotocol/*` keys.

### 2.1 Acceptance criteria

- [ ] `grep -ril 'server/discover' src/ | wc -l` ≥ 1 (was 0 — **E-230**).
- [ ] `grep -rl 'io.modelcontextprotocol/' src/ | wc -l` ≥ 1 (was 0 — **E-22**).
- [ ] `python -c "from lauren_mcp._mcp_version import MODERN_LATEST; print(MODERN_LATEST)"` prints
      `2026-07-28`; the same line with `LATEST` still prints `2025-11-25`.
- [ ] `pytest tests/unit/test_server_discover.py -q` passes, incl. `test_discover_capabilities_match_initialize`.
- [ ] `pytest tests/unit/test_request_meta.py -q` passes, incl.
      `test_malformed_protocol_version_returns_invalid_params`.
- [ ] `pytest tests/integration/test_modern_era_discovery.py -q` passes on STDIO and Streamable HTTP.
- [ ] `pytest tests/unit/test_mcp_handshake.py tests/integration/test_mcp_dispatcher_protocol.py -q` still
      passes, unmodified.

---

## 3. Non-Goals

- **Not** the rest of the `2026-07-28` surface: `resultType` (**E-232**), `ttlMs` (**E-233**), `cacheScope`
  (**E-234**), `subscriptions/listen` (**E-231**), tasks (**E-235**) and MRTR (**E-236**) each get their own
  PRD. This one delivers discovery plus the envelope those PRDs will read.
- **Not** removing `initialize`; that would break every host in §14 (**E-190** … **E-199**) still on
  `2024-11-05` … `2025-11-25`.
- **Not** deprecating roots, sampling, logging, DCR or HTTP+SSE (**E-30**). `logLevel` is parsed from the
  envelope and deliberately not acted on.
- **Not** touching sessions (**E-20**, **E-241**) or `$/cancelRequest` (**E-240**). The parser tolerates a
  request with no `_meta` precisely so session-era transports keep working untouched.
- **Not** changing the client layer (`_client/_base_remote.py` keeps sending `initialize`) or the CLI.

---

## 4. Design

### 4.1 Two eras in `_mcp_version.py`

`_mcp_version.py:5-7` defines one era today — `LATEST = "2025-11-25"`, `STABLE = "2024-11-05"`,
`SUPPORTED = frozenset({"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"})`; `2026-07-28` appears
nowhere. Those three lines stay byte-identical, and the following is appended:

```python
# src/lauren_mcp/_mcp_version.py  after line 7
MODERN_LATEST = "2026-07-28"
MODERN_SUPPORTED = frozenset({MODERN_LATEST})
ALL_SUPPORTED = SUPPORTED | MODERN_SUPPORTED


def is_modern(version: str | None) -> bool:
    """True when *version* names a revision that has no ``initialize`` handshake."""
    return version is not None and version in MODERN_SUPPORTED
```

`LATEST` deliberately does not move: it is what `_client/_base_remote.py` advertises and what
`negotiate_version()` (`_server/_handshake.py:15-27`) falls back to, so bumping it would make legacy servers
reject our handshake. This is the `HANDSHAKE_*` / `MODERN_*` split the Python SDK settled on (**E-81**).

### 4.2 The envelope: `RequestMeta`

```python
# src/lauren_mcp/_server/_meta_envelope.py  (new file)
"""Parse the per-request ``_meta`` envelope of the 2026-07-28 revision (E-22)."""

META_PROTOCOL_VERSION = "io.modelcontextprotocol/protocolVersion"
META_CLIENT_INFO = "io.modelcontextprotocol/clientInfo"
META_CLIENT_CAPABILITIES = "io.modelcontextprotocol/clientCapabilities"
META_LOG_LEVEL = "io.modelcontextprotocol/logLevel"


class RequestMetaError(ValueError):
    """A ``_meta`` envelope was present but not well-formed."""


@dataclass(frozen=True, slots=True)
class RequestMeta:
    """What the removed handshake used to carry (E-22)."""

    protocol_version: str | None = None
    client_info: Implementation | None = None
    client_capabilities: ClientCapabilities | None = None
    log_level: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def era(self) -> str:
        return "modern" if is_modern(self.protocol_version) else "legacy"


EMPTY_META = RequestMeta()
_current_meta: ContextVar[RequestMeta] = ContextVar("lauren_mcp_request_meta", default=EMPTY_META)


def parse_request_meta(params: Mapping[str, Any] | None) -> RequestMeta:
    """Parse once per request, in the dispatcher; absent `_meta` is not an error."""
    if not isinstance(params, Mapping):
        return EMPTY_META
    raw = params.get("_meta")
    if raw is None:
        return EMPTY_META
    if not isinstance(raw, Mapping):
        raise RequestMetaError("_meta must be an object")
    return RequestMeta(..., raw=dict(raw))     # field validation per the table below
```

| Envelope state | Result |
|---|---|
| no `params`, or no `params["_meta"]` | `EMPTY_META`, `era == "legacy"` — legacy requests untouched |
| `_meta` not a mapping | `RequestMetaError("_meta must be an object")` |
| `protocolVersion` absent or a `str` in neither set | kept verbatim, `era == "legacy"` — a peer guessing a revision is not an error |
| `protocolVersion` not a `str`; `clientInfo` not a mapping or missing `name`/`version`; `clientCapabilities` not a mapping; `logLevel` not a `str` | `RequestMetaError`, message names the field |
| unknown keys | preserved in `raw`, never rejected — the envelope is an extension point (**E-22**) |

The contextvar keeps `RequestMeta` out of every handler signature: handlers keep their existing
`(params: dict | None) -> dict` shape (`_server/_dispatcher.py:124`), so `tools/list`, `tools/call`,
`resources/*`, `prompts/*` and `completion/complete` do not change at all.

### 4.3 Era resolution in one function

```python
# src/lauren_mcp/_server/_meta_envelope.py  (continued)
def resolve_era(meta: RequestMeta, *, policy: str = "dual") -> str:
    """``"dual"`` follows the envelope; ``"modern"`` / ``"legacy"`` override it."""
    if policy == "modern":
        return "modern"
    if policy == "legacy":
        return "legacy"
    return meta.era
```

### 4.4 Building the `server/discover` result

```python
# src/lauren_mcp/_server/_discover.py  (new file)
"""``server/discover`` — the modern-era replacement for the initialize handshake (E-21)."""

SERVER_DISCOVER = "server/discover"


def build_discover_result(
    *, server_info: Implementation, capabilities: ServerCapabilities,
    instructions: str | None, meta: RequestMeta,
) -> dict[str, Any]:
    """Mirror ``build_initialize_result`` (``_server/_handshake.py:28-43``) so both eras
    describe the same server with the same values."""
    return {
        "serverInfo": {"name": server_info.name, "version": server_info.version},
        "capabilities": _capabilities_to_dict(capabilities),
        "instructions": instructions,
        "protocolVersions": [MODERN_LATEST, *sorted(ALL_SUPPORTED - MODERN_SUPPORTED)],
    }
```

`_capabilities_to_dict()` is the dict-building loop currently inlined in `_initialize_handler`
(`server/_module.py:380-401`, where `caps_dict["completions"] = {}` is set). It moves into `_discover.py` as
a module-level helper that `_initialize_handler` also calls — one function, two eras, no drift between the
two methods. `protocolVersions` is ordered modern-first so a peer taking the first entry lands on
`2026-07-28`; the exact field name is the one genuine unknown (§9 Q1).

### 4.5 Dispatcher wiring — envelope parsed before any handler runs

Today `_dispatcher.py:122-124` takes `params` and calls `asyncio.create_task(handler(params))`. The
replacement:

```python
# src/lauren_mcp/_server/_dispatcher.py  line 122-136  (new)
params: dict[str, Any] | None = request.params if isinstance(request.params, dict) else None

try:                                        # NEW: one parse, one place, all four transports
    meta = parse_request_meta(params)
except RequestMetaError as exc:
    return build_error_response(
        id=request.id, code=McpErrorCode.INVALID_PARAMS,
        message=f"Invalid _meta envelope: {exc}",
    )

async def _invoke() -> Any:
    token = _current_meta.set(meta)
    try:
        return await handler(params)
    finally:
        _current_meta.reset(token)

task: asyncio.Task[Any] = asyncio.create_task(_invoke())
```

Two details are load-bearing. The `set`/`reset` pair lives **inside** the task: setting the contextvar in
`dispatch()` and creating the task afterwards leaks the envelope into concurrent requests, because
`asyncio.create_task` copies the context at creation time. And `reset` is in a `finally`, so a raising tool
cannot poison the contextvar for the next request on the loop. Error mapping is otherwise unchanged —
`CancelledError` → `REQUEST_CANCELLED`, everything else → `INTERNAL_ERROR` (`_dispatcher.py:108-113`). The
`-32602` path returns before a task exists, so a malformed envelope costs one dict walk.

### 4.6 Exposing the envelope to tools

`McpToolContext` gains four fields between its transport and metadata blocks (`_context.py:292-297`):

```python
# src/lauren_mcp/_server/_context.py  line 292-303  (new)
    session_id: str | None = None

    # ---------- caller identity (2026-07-28 _meta envelope) ----------
    protocol_version: str | None = None
    client_info: Implementation | None = None
    client_capabilities: ClientCapabilities | None = None
    era: str = "legacy"

    # ---------- metadata / scratch ----------
    metadata: dict[str, Any] = field(default_factory=dict)
```

All four default to legacy values, so existing `McpToolContext(...)` sites keep working. They are populated
where the context is already built, after the `progressToken` block at `server/_handlers.py:816-819`:

```python
# src/lauren_mcp/server/_handlers.py  after line 826
_envelope = current_request_meta()          # parsed once, in the dispatcher
ctx = replace(ctx, protocol_version=_envelope.protocol_version,
              client_info=_envelope.client_info,
              client_capabilities=_envelope.client_capabilities, era=_envelope.era)
```

Progress handling is untouched: the parser preserves the raw mapping in `.raw`, and `:816-819` keeps reading
`progressToken` from `params["_meta"]` directly.

### 4.7 `initialize` under a modern peer

`_initialize_handler` (`server/_module.py:367-368`) opens with `params = params or {}`. It gains three lines
immediately after:

```python
# src/lauren_mcp/server/_module.py  line 368-375  (new)
    if resolve_era(current_request_meta(), policy=era_policy) == "modern":
        raise McpDispatchError(
            McpErrorCode.INVALID_REQUEST,
            "initialize is not available for 2026-07-28 peers; call server/discover",
        )
```

`McpDispatchError` is the dispatcher's existing error carrier (`_server/_dispatcher.py:31`, `:52`) and
already converts to a JSON-RPC error response. Under the default `era_policy="dual"` the branch is dead code
for legacy peers and fires only for a request that carried a modern envelope.

---

## 5. Server-side Changes

### 5.1 `McpServerModule.for_root` gains one keyword

The signature ends `proxies: ... | None = None, instrument_otel: bool | None = None, ) -> type:`
(`server/_module.py:62-75`); append one keyword-only parameter:

```python
# src/lauren_mcp/server/_module.py  line 62-77  (new, tail)
    instrument_otel: bool | None = None,
    era_policy: str = "dual",          # NEW: "dual" | "modern" | "legacy"
) -> type:
```

```python
from lauren_mcp.server import mcp_server, McpServerModule

@mcp_server
class CatalogServer: ...

# Default: both eras answer.  An existing 1.0.0 deployment changes nothing.
CatalogServerModule = McpServerModule.for_root(CatalogServer)

# Modern-only room: initialize is refused with a pointer to server/discover.
StrictModule = McpServerModule.for_root(CatalogServer, era_policy="modern")
```

`era_policy` raises `ValueError` at module-build time, so a typo fails process start rather than the first
modern peer.

### 5.2 Registration

```python
# src/lauren_mcp/server/_module.py  line 412-421  (new)
                # --- server/discover (2026-07-28, E-21) ---
                async def _discover_handler(params: dict[str, Any] | None) -> dict[str, Any]:
                    return build_discover_result(
                        server_info=resolved_server_info,
                        capabilities=_resolved_capabilities,
                        instructions=instructions,
                        meta=current_request_meta(),
                    )

                dispatcher.register(SERVER_DISCOVER, _discover_handler)
                dispatcher.register("initialize", _initialize_handler)
```

`server/discover` is registered in all three policies: a legacy peer that never sends it pays nothing, and a
modern peer gets an answer regardless of `era_policy`, because refusing discovery would re-create the §1.1
failure from the other direction. `resolved_server_info` is already computed at `server/_module.py:250-253`
(default `Implementation(name=server_cls.__name__, version="1.0.0")`), which is why both eras report the same
`serverInfo` with no second source of truth.

### 5.3 Error shape for a malformed envelope

```json
{"jsonrpc": "2.0", "id": 7,
 "error": {"code": -32602,
           "message": "Invalid _meta envelope: protocolVersion must be a string"}}
```

`-32602` is `INVALID_PARAMS` (`_types.py:117`). The message names the field and never echoes the received
value — a peer that sent a 2 KB object in `protocolVersion` must not be able to inflate our error frames.

---

## 6. Exact Lines to Change

### 6.1 `src/lauren_mcp/_mcp_version.py`

Line 5-7 unchanged. Immediately after line 7, add `MODERN_LATEST`, `MODERN_SUPPORTED`, `ALL_SUPPORTED` and
`is_modern()` from §4.1.

### 6.2 `src/lauren_mcp/_types.py`

No edits. `JsonRpcRequest` (`:20-26`) gains no `_meta` field — the envelope lives inside `params`;
`INVALID_PARAMS = -32602` (`:117`) is reused; `ServerCapabilities` (`:139-147`) stays the single source for
either era's `capabilities`; `InitializeResult` (`:172-178`) stays and no `ServerDiscoverResult` dataclass is
added, because `_discover.py` returns a plain `dict` per the handler contract at `_dispatcher.py:124`.

### 6.3 `src/lauren_mcp/_server/_meta_envelope.py` (new, ~120 lines)

Lines 1-25 docstring citing **E-22** plus the four `META_*` constants; 26-60 `RequestMetaError` and
`RequestMeta` with its `era` property and `EMPTY_META`; 62-92 `parse_request_meta()` per the §4.2 table;
95-115 `resolve_era()`, `_current_meta` and `current_request_meta()`.

### 6.4 `src/lauren_mcp/_server/_discover.py` (new, ~60 lines)

Lines 1-14 docstring citing **E-21** plus `SERVER_DISCOVER = "server/discover"`; 16-45
`build_discover_result(...)`; 47-60 `_capabilities_to_dict()`, extracted from `server/_module.py:380-401`.

### 6.5 `src/lauren_mcp/_server/_dispatcher.py`

Line 101-120 unchanged (`dispatch()` signature, docstring, the `METHOD_NOT_FOUND` path for genuinely unknown
methods). Line 122-124: replace `asyncio.create_task(handler(params))` with the envelope parse + `_invoke()`
from §4.5. Line 125-135 unchanged — in-flight bookkeeping, cancellation and error mapping keep working.

### 6.6 `src/lauren_mcp/_server/_context.py`

Line 277-284 unchanged (`McpToolContext` docstring, immutability contract). Line 292-297: add
`protocol_version`, `client_info`, `client_capabilities`, `era`. Line 299+ unchanged — `metadata` / `state`
remain the scratch surface.

### 6.7 `src/lauren_mcp/server/_handlers.py`

Line 576 (`entry["_meta"] = t.meta`, tool-level `_meta` on `tools/list`) and line 816-819 (`progressToken`)
unchanged. After line 826, populate the four new `McpToolContext` fields from `current_request_meta()` via
`dataclasses.replace`.

### 6.8 `src/lauren_mcp/server/_module.py`

Line 62-75: add the `era_policy` keyword plus its `ValueError` validation. Line 250-253 unchanged
(`resolved_server_info` is the shared `serverInfo`). Line 367-368: the modern-era guard (§4.7). Line 380-401:
move the capability-dict loop into `_discover._capabilities_to_dict()`. Line 415: register `SERVER_DISCOVER`
immediately **above** the `initialize` registration. The remaining registrations are untouched —
`logging/setLevel` (`:427`), `tools/list` and `tools/call` (`:457-458`), `resources/list` and
`resources/read` (`:476-477`), `resources/subscribe` and `resources/unsubscribe` (`:519-520`), `prompts/list`
and `prompts/get` (`:532-533`), `completion/complete` (`:544`).

---

## 7. Backward Compatibility

Nothing that works today stops working.

| Surface | Behaviour |
|---|---|
| `LATEST` / `SUPPORTED` | Unchanged (`_mcp_version.py:5-7`); `negotiate_version()` (`_server/_handshake.py:15-27`) returns the same answers |
| `initialize` on a legacy request | Byte-identical. No `_meta` → `EMPTY_META` → `era == "legacy"` → the §4.7 guard never fires |
| `for_root(...)`, `McpDispatcher` subclasses | Existing keywords keep their defaults; `dispatch()` keeps its signature and error mapping |
| `McpToolContext(...)`, progress, catalogue, schema generation | Four new fields all have defaults; no decorator, field or annotation change elsewhere; unknown `_meta` keys preserved in `.raw` |

One intentional behaviour change: a request whose `_meta` is present but malformed now returns `-32602`
instead of being served (that is §2 Goal 5) — the only observable difference for a caller that does not use
the modern era, so it belongs in the CHANGELOG line.

**Migration notes: none.** An existing 1.0.0 deployment upgrades and gains `server/discover` automatically,
with `era_policy="dual"` meaning `initialize` still answers every current client. No code change, no
configuration change, no re-deploy ordering.

---

## 8. Test Plan

### 8.1 Unit tests — `tests/unit/test_request_meta.py` (new)

`test_no_params_yields_empty_meta` (no `params` → `EMPTY_META`, `era == "legacy"`);
`test_no_meta_key_yields_empty_meta`; `test_meta_not_object_raises`;
`test_malformed_protocol_version_returns_invalid_params` (int version → `RequestMetaError` naming
`protocolVersion`); `test_modern_version_sets_era` / `test_legacy_version_sets_era`;
`test_unknown_version_kept_verbatim` (`"2099-01-01"` → no raise); `test_client_info_parsed` /
`test_client_info_missing_version_raises`; `test_unknown_keys_preserved_in_raw`; `test_resolve_era_policies`;
`test_contextvar_default_is_empty`.

### 8.2 Unit tests — `tests/unit/test_server_discover.py` (new)

`test_discover_over_stdio_returns_server_info` (drive `run_stdio_server()` with a `server/discover` line;
`result["serverInfo"]["name"]` matches `resolved_server_info`); `test_discover_lists_modern_and_legacy_versions`
(`"2026-07-28"` and `"2025-11-25"` both in `protocolVersions`); `test_discover_capabilities_match_initialize`
(the anti-drift test); `test_discover_registered_for_all_policies` (`dual` / `modern` / `legacy`, never
`-32601`); `test_initialize_refused_under_modern_policy` (`-32600` naming `server/discover`) versus
`test_initialize_served_under_dual_policy` (`protocolVersion == "2025-11-25"`);
`test_invalid_era_policy_raises_at_build_time`.

### 8.3 Unit tests — additions to `tests/unit/test_mcp_handshake.py`

`test_dispatch_rejects_malformed_envelope` (`-32602`, handler `Mock` not called);
`test_dispatch_sets_and_resets_contextvar` (inside a handler `protocol_version == "2026-07-28"`, after
`dispatch()` returns `EMPTY_META`); `test_concurrent_requests_do_not_share_meta` (two
`create_task(dispatcher.dispatch(...))` with different envelopes — the §4.5 leak test);
`test_tool_context_carries_envelope`.

### 8.4 Integration tests — `tests/integration/test_modern_era_discovery.py` (new)

`test_discover_round_trip_stdio` — raw JSON-RPC write/read through `run_stdio_server()`
(`_server/_stdio.py:62-64`), no `initialize` first; `test_discover_round_trip_streamable_http` — the same
request over HTTP; `test_modern_request_with_meta_reaches_tool` — `tools/call` with a `2026-07-28` envelope,
the tool returning the revision it observed; `test_legacy_client_unaffected` — `initialize` → `tools/list` →
`tools/call`, output unchanged; `test_malformed_envelope_over_wire` — `-32602`, connection left open.

### 8.5 Regression gate

`pytest tests/unit/test_mcp_handshake.py tests/unit/test_server_transport_coverage.py
tests/integration/test_mcp_dispatcher_protocol.py tests/integration/test_mcp_stdio_client_integration.py -q`,
plus the full suite (`nox -s tests-3.12`). Any diff in a legacy response body is a failure of this PRD, not a
test to be updated.

---

## 9. Open Questions

**Q1 — the exact `server/discover` result schema.** **E-21** establishes that `server/discover.mdx` exists in
the `2026-07-28` tree and that the request is a MUST; the evidence set does not include the field-by-field
result schema. §4.4 therefore proposes `serverInfo` / `capabilities` / `instructions` / `protocolVersions` by
analogy with `InitializeResult` (`_types.py:172-178`). **Confirm the key names against the `2026-07-28`
schema before writing `_discover.py`.** If the schema names the list differently, `build_discover_result`
changes in one place and no test outside `tests/unit/test_server_discover.py` moves.

**Q2 — does refusing `initialize` break a transitional peer?** A mid-upgrade peer might send `initialize` and
also understand `server/discover`; `"dual"` answers both, so this only matters for operators choosing
`"modern"`, which stays non-default.

**Q3 — should `logLevel` override `logging/setLevel`, and should `server/discover` be advertised in a legacy
capability field?** Both out of scope (§3). Revisit if a host in §14 (**E-190** … **E-199**) probes for either.

---

## 10. References

**Evidence (`EVIDENCE.md`)** — E-20 (breaking revision, nine removals); E-21 (`initialize` removed for modern
peers, `server/discover` is a MUST — core justification); E-22 (`_meta` carries `protocolVersion`,
`clientInfo`, `clientCapabilities`, `serverInfo`, `logLevel`); E-30 (roots, sampling, logging, DCR, HTTP+SSE
deprecated — out of scope); E-80…E-90 (§6 dual-era readiness); E-81 (Python SDK 2.3.0 "yes, dual",
`HANDSHAKE_*` / `MODERN_*` + `_probe.py` — the design model); E-190…E-199 (§14 host constraints — stdio and
Streamable HTTP universal, nothing beyond §4 required); E-230 (`grep -ril 'server/discover' src/ | wc -l` →
**0** — the gap this PRD closes); E-231…E-236 (adjacent zero-hits — deferred); E-240…E-244 (presence facts —
`$/cancelRequest`, `mcp-session-id`, `logging/setLevel`, `roots/list`, `Last-Event-ID` — all preserved).

**Repository evidence** — `_mcp_version.py:5-7`; `_types.py:20-26`, `:111-119`, `:139-147`, `:172-178`;
`_server/_handshake.py:15-27`, `:28-43`; `_server/_dispatcher.py:101-124` and `_server/_stdio.py:62-64`;
`_server/_context.py:277-299`; `server/_handlers.py:576`, `:816-819`; `server/_module.py:62-75`, `:250-253`,
`:367-401`, and the registration block at `:415, 427, 457-458, 476-477, 519-520, 532-533, 544`.

**Companion documents:** `EVIDENCE.md` §2, §6, §14, §16.3, §22; `VERSIONS-MATRIX.md` §2;
`_research/lauren-mcp-inventory.md` §1; model `prds/prd-protocol-version-negotiation.md`; spec
`https://modelcontextprotocol.io/specification/2026-07-28` (`server/discover`, `_meta` envelope).
