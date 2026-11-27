# `lauren-mcp` v1.0.0 — Capability Inventory (source-derived)

**Status:** Internal working artifact — input to EVIDENCE.md and the PRD set
**Date:** 2026-11-26
**Scope:** every claim below is derived from the working tree at
`docs/mcp-landscape-2026-11` (base commit `7778737`), not from marketing docs.

> **Method.** Capabilities were extracted by reading `src/lauren_mcp/` directly
> (`grep`/`sed` over the actual declarations) and cross-checked against
> `CHANGELOG.md`. Where the documentation and the source disagree, **the source
> is treated as truth** and the discrepancy is recorded in §12 (Doc Drift).
> Absences were established by exhaustive `grep -ril` over `src/`, with the
> hit count recorded so "absent" means "zero textual occurrences", not
> "I did not look".

---

## 1. Package and distribution

| Attribute | Value | Evidence |
|---|---|---|
| Distribution name | `lauren-mcp` | `pyproject.toml` |
| Version in tree | `1.0.0` (released 2026-06-14), VCS-derived via `hatch-vcs` | `CHANGELOG.md:10`, `pyproject.toml [tool.hatch.version]` |
| Python support | `>=3.11`; classifiers 3.11–3.14 | `pyproject.toml` |
| Runtime dependencies | `lauren>=1.7.0`, `anyio>=4.0` — **only two** | `pyproject.toml [project.dependencies]` |
| Optional extras | `ws`, `http`, `pydantic`, `msgspec`, `cli`, `all` | `pyproject.toml [project.optional-dependencies]` |
| Console script | `lmcp = lauren_mcp.cli:app` | `pyproject.toml [project.scripts]` |
| Build excludes | `prds/`, `skills/`, `tests/`, `docs/`, `examples/` from sdist | `pyproject.toml [tool.hatch.build.targets.sdist]` |
| Source size | 13,330 lines across `src/lauren_mcp/**/*.py` | `wc -l` |

**Design consequence:** because Pydantic is optional, the schema path is
hand-rolled (`server/_schema.py`, 352 lines) rather than delegated to
`pydantic.TypeAdapter`. This is the structural difference from FastMCP and the
official Python SDK, and it is load-bearing for several PRDs.

Largest modules, which is where the complexity lives:

| Lines | Module | Role |
|---:|---|---|
| 1,513 | `server/_handlers.py` | tool/resource/prompt call handling, DI, validation |
| 1,143 | `server/_decorators.py` | `@mcp_tool` / `@mcp_resource` / `@mcp_prompt` registration + schema building |
| 1,047 | `_types.py` | all wire types |
| 668 | `server/_module.py` | `McpServerModule.for_root()` — DI wiring and transport mounting |
| 649 | `_server/_context.py` | `McpToolContext` (progress, logging, sampling, elicitation) |
| 588 | `_server/_streamable.py` | Streamable HTTP server transport |

---

## 2. Protocol version support

`src/lauren_mcp/_mcp_version.py` — the single source of truth:

```python
LATEST = "2025-11-25"
STABLE = "2024-11-05"
SUPPORTED = frozenset({"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"})
```

| Version | Supported | Notes |
|---|---|---|
| `2024-11-05` | ✅ | `STABLE`; legacy HTTP+SSE |
| `2025-03-26` | ✅ | Streamable HTTP introduced |
| `2025-06-18` | ✅ | In `SUPPORTED`, but see §3 — the newer cancellation and auth methods are **not** implemented |
| `2025-11-25` | ✅ | Declared `LATEST` |
| `2026-07-28` | ❌ | **Newest published revision** (see EVIDENCE.md) — entirely absent |

**Important nuance.** Listing a version in `SUPPORTED` is a *negotiation*
claim, not a *conformance* claim. `2025-06-18` is accepted at `initialize`
time, but the repo still uses the pre-`2025-06-18` `$/cancelRequest`
notification rather than `notifications/cancelled` (§5.4), and implements no
part of the `2025-06-18` OAuth hardening (§8). So the version set is
optimistic relative to actual behaviour.

---

## 3. Transports

### 3.1 Server side

`server/_module.py:55`:

```python
_TRANSPORTS = ("ws", "sse", "streamable", "both", "all")
```

| Transport | Status | Implementation |
|---|---|---|
| WebSocket | ✅ native, **default** (`transport="ws"`) | `_server/_ws.py` (336 lines) |
| HTTP+SSE (legacy `2024-11-05`) | ✅ | `_server/_sse.py` (267 lines) |
| Streamable HTTP (`2025-03-26`) | ✅ | `_server/_streamable.py` (588 lines) |
| stdio | ✅ | `_server/_stdio.py` (88 lines); CLI `--stdio` |
| Dual/multi mount | ✅ `"both"` = WS+SSE, `"all"` = WS+SSE+Streamable | `server/_module.py:266-270` |

**Streamable HTTP feature detail** (`_server/_streamable.py`):

- `POST <path>` single endpoint, JSON or SSE response negotiated by `Accept`
- `mcp-session-id` header session management (`_SESSION_HEADER`, line 41)
- `GET <path>` push channel for server-initiated messages
- `DELETE <path>/` explicit session teardown
- `stateless=True` mode (line 104) — no session created; `GET`/`DELETE` return `405`
- `event_store: EventStore` (line 105) — SSE `id:` assignment and `Last-Event-ID` replay
- `transport_security: TransportSecuritySettings` (line 106)
- `.well-known/oauth-authorization-server` (line 133) and `.well-known/oauth-protected-resource` (line 138) discovery documents

**This is a genuine strength:** the repo is one of very few MCP implementations
with native WebSocket, and it can mount three transports from a single class.

### 3.2 Client side

`_client/_factory.py` — `McpServer` static factory:

| Factory method | Transport | Line |
|---|---|---|
| `McpServer.stdio(...)` | stdio subprocess | 68 |
| `McpServer.ws(...)` | WebSocket | 105 |
| `McpServer.http(...)` | HTTP+SSE legacy | 139 |
| `McpServer.streamable_http(...)` | Streamable HTTP | 182 |

All remote clients share `_client/_base_remote.py` (304 lines) + `_client/_features.py` (276 lines).

---

## 4. Content and wire types (`_types.py`)

Confirmed present — including the ones that the *old* June-2026 gap analysis
listed as missing:

| Type | Present | Line |
|---|---|---|
| `TextContent` | ✅ | 188 |
| `ImageContent` | ✅ | 196 |
| `EmbeddedResource` | ✅ | 205 |
| `AudioContent` | ✅ | 213 |
| `ResourceLink` | ✅ | 232 |
| `ToolAnnotations` | ✅ | 258 |
| `ToolSchema` (with `outputSchema`) | ✅ | 280 |
| `ToolResult` / `ToolOutput` | ✅ | 300 / 317 |
| `ToolStream(Generic[_T])` | ✅ | 330 |
| `ResourceAnnotations` | ✅ | 368 |
| `ResourceSchema` / `ResourceContent` / `ReadResourceResult` | ✅ | 406 / 418 / 435 |
| `BlobResource` | ✅ | 442 |
| `PromptArgument` / `PromptSchema` / `PromptMessage` | ✅ | 466 / 475 / 485 |
| `ToolListChangedNotification` / `ResourceListChangedNotification` / `PromptListChangedNotification` | ✅ | 516 / 525 / 534 |
| `LoggingMessageNotification` | ✅ | 543 |
| `ProgressNotification` | ✅ | 557 |
| `ToolUseContent` / `ToolResultContent` | ✅ | 571 / 616 |
| `SamplingMessage` / `CreateMessageParams` / `CreateMessageResult` | ✅ | 682 / 706 / 738 |
| `ElicitResult` / `UrlElicitResult` | ✅ | 809 / 827 |
| `Root` | ✅ | 861 |
| `CompletionResult` | ✅ | 880 |

**Error codes** (`McpErrorCode`, line 111): `PARSE_ERROR -32700`,
`INVALID_REQUEST -32600`, `METHOD_NOT_FOUND -32601`, `INVALID_PARAMS -32602`,
`INTERNAL_ERROR -32603`, `REQUEST_CANCELLED -32800`, `CONTENT_TOO_LARGE -32801`.

**Server capabilities advertised** (`ServerCapabilities`, line 139): `tools`,
`resources`, `prompts`, `logging`, `completions`, `experimental`. There is
**no `tasks` field** and no per-primitive `subscribe` sub-capability — relevant
to PRDs on tasks and on capability honesty.

---

## 5. Implemented MCP methods

Registered in `server/_module.py` (`_register_handlers`, line 315) plus
`_session`, `_subscriptions`, `_catalog`.

| Method | Direction | Status |
|---|---|---|
| `initialize` | client→server | ✅ line 367 |
| `ping` | both | ✅ `_dispatcher.py:80` |
| `logging/setLevel` | client→server | ✅ line 420 |
| `tools/list` | client→server | ✅ line 451 |
| `tools/call` | client→server | ✅ line 454 |
| `resources/list` | client→server | ✅ line 470 |
| `resources/read` | client→server | ✅ line 473 |
| `resources/subscribe` | client→server | ✅ line 480 |
| `resources/unsubscribe` | client→server | ✅ line 505 |
| `prompts/list` | client→server | ✅ line 526 |
| `prompts/get` | client→server | ✅ line 529 |
| `completion/complete` | client→server | ✅ line 539 |
| `notifications/tools/list_changed` | server→client | ✅ |
| `notifications/resources/list_changed` | server→client | ✅ |
| `notifications/prompts/list_changed` | server→client | ✅ |
| `notifications/resources/updated` | server→client | ✅ `_subscriptions.py` |
| `notifications/progress` | server→client | ✅ `ctx.report_progress()` |
| `notifications/message` | server→client | ✅ `ctx.log()` |
| `sampling/createMessage` | server→client | ✅ `ctx.sample()` |
| `elicitation/create` | server→client | ✅ `ctx.elicit()` / `ctx.elicit_url()` |
| `roots/list` | server→client | ✅ client `_resolve_roots()` |
| `$/cancelRequest` | client→server | ✅ **legacy** — see §5.4 |
| `notifications/cancelled` | client→server | ❌ **0 hits in `src/`** |
| `tasks/*` | either | ❌ **0 hits in `src/`** |
| `subscriptions/listen` | client→server | ❌ **0 hits in `src/`** |

### 5.4 Cancellation: `$/cancelRequest` is **not an MCP method at all**

`grep -ril "notifications/cancelled" src/` → **0 files**.
`grep -rn "\\$/cancelRequest" src/` → 5 files (`_ws.py:39`, `_server/_streamable.py:212`,
`_server/_stdio.py:76`, `_dispatcher.py:105`, `_server/_context.py:336`).

**Correction (verified 2026-11-26).** An earlier draft of this inventory described
`$/cancelRequest` as "the pre-`2025-06-18` cancellation method". That was wrong.
`notifications/cancelled` is present in the **earliest** published schema —
`curl https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/schema/2024-11-05/schema.ts`
contains `"notifications/cancelled"` — and a code search across the whole
`modelcontextprotocol` org returns **0** occurrences of `/cancelRequest`.
`$/cancelRequest` is an **LSP** method name; it has never existed in any MCP
revision.

So this is **not a spec-version gap and not a migration task** — it is a plain
local conformance bug: the server emits and listens for a method no MCP client
will ever send, and it ignores the method every client actually sends. Any peer
attempting to cancel a `lauren-mcp` call is silently ineffective. Re-scoped
accordingly (it belongs with bug-fix work, not with the `2026-07-28` migration).

---

## 6. Server API surface

### 6.1 Decorators (`server/_decorators.py`)

```python
mcp_server(path: str, *, transport: str = "ws")                        # line 736
mcp_tool(*, name, description, title, annotations, timeout, tags,
         meta, output_schema, structured_output, strict) -> ...        # line 758
mcp_resource(uri_template: str, *, name, description, title,
             mime_type, annotations) -> ...                            # line 874
mcp_prompt(name=None, *, description, title) -> ...                    # line 988
mcp_lifespan(fn)                                                       # line 1039
mcp_completion(target: str, argument: str, *, ref_type="ref/prompt")   # line 1064
```

`@mcp_tool` parameter surface is notably rich: `title`, `annotations`,
`timeout`, `tags`, `meta`, `output_schema`, `structured_output` tri-state
(`None` = auto-detect, `True` = force, `False` = disable), and `strict`
(tool-name validation per SEP-986, `_validate_tool_name`, line 112).

`@mcp_resource` supports RFC 6570 **subset**: `{param}`, `{+param}`,
`{param*}`, and `{?p1,p2}` query suffix (`server/_uri.py`, 104 lines).

### 6.2 Dependency injection into tool signatures

`_decorators.py` resolves these annotations out of the generated JSON Schema
and injects them at call time:

| Annotation | Purpose | Line |
|---|---|---|
| `McpToolContext` / `ctx` | progress, logging, sampling, elicitation | 278 |
| `Depends[X]` | Lauren DI | 310 |
| `Header[T]` | HTTP header binding + pipe chains | 368 |
| `State[T]` | request state | 446 |
| `BackgroundTasks` | fire-and-forget after response | 256 |
| pipe chains | param validation → `INVALID_PARAMS` | (`McpInvalidParamsError`) |

Per-tool cross-cutting behaviour is provided by **Lauren's own decorators**,
not exported by this package: `@use_guards`, `@use_interceptors`,
`@use_exception_handlers`, `@exception_handler`, `@interceptor`, `@set_metadata`
(see `docs/guides/per-tool-decorators.md`). They do not appear in
`lauren_mcp.__all__`.

### 6.3 `McpToolContext` (`_server/_context.py`)

```python
def allows(self, level: str) -> bool                 # 70   level filtering
def get_metadata(self, key, default=None)            # 313  session metadata
def cancel_requested(self) -> asyncio.Event          # 321  cooperative cancel
async def report_progress(progress, total, message)  # 346
async def log(level, message, data=None)             # 383
# debug/info/notice/warning/error/critical            404-424
async def sample(...)                                # 437  sampling/createMessage
async def elicit(...)                                # 547  elicitation/create
async def elicit_url(...)                            # 580  URL elicitation
```

Notably absent versus FastMCP: no `ctx.get_state()` / session-scoped
mutable state object (only read-only `get_metadata`).

### 6.4 Composition, proxying, OpenAPI, built-ins

| Feature | API | Evidence |
|---|---|---|
| Mount sub-servers with prefix | `for_root(mounts=[(Cls, "prefix")])` | `_module.py`, `_composition.py:53` |
| Proxy a remote MCP server's tools | `for_root(proxies=[(client, "prefix")])` | `_composition.py:114` |
| Collision detection | `McpToolNameCollision` | `_composition.py:25` |
| OpenAPI → MCP server class | `build_openapi_server_class()` | `server/_openapi.py` (268 lines) |
| Built-in resources | `FileResource`, `HttpResource`, `DirectoryResource` + `register_*` + MIME sniffing | `server/_builtin_resources.py` |
| Dynamic catalogue | `McpCatalogManager` SINGLETON, auto `list_changed` | `_server/_catalog.py` |
| Resource subscriptions | `ResourceSubscriptionManager` SINGLETON | `_server/_subscriptions.py` |
| Demo server | `LaurenMcpMemoryServer` | `server/_memory_server.py` |

**This composition + proxying layer is a real differentiator.** FastMCP has
`mount()`/`create_proxy()`; the official Python SDK has neither, so a
`lauren-mcp` deployment can aggregate heterogeneous MCP servers behind one
endpoint.

### 6.5 Schema generation (`server/_schema.py`, 352 lines)

Supported input types: Pydantic `BaseModel`, `msgspec.Struct`, `@dataclass`,
`TypedDict`, `Literal[...]`, `Annotated[T, Field(...)]`, `list[T]`,
`dict[K, V]`, `UUID`, `datetime`, and standard scalars.
Per-parameter descriptions are extracted from **Google, Sphinx and NumPy**
docstrings (`server/_docstring.py`, 191 lines). Output schemas auto-detect
from return annotations (`_auto_output_schema`, `_decorators.py:687`).

The "no Pydantic required" path is the repo's main schema-level advantage over
both FastMCP and the official SDK.

---

## 7. Client API surface

`McpClientProtocol` (`_client/_protocol.py`) — 222 lines, 13 methods:

```python
connect() / close()                              # 28 / 37
list_tools() / call_tool()                       # 49 / 57
list_resources() / read_resource(uri)            # 83 / 91
subscribe_resource(uri) / unsubscribe_resource(uri)  # 108 / 126
list_prompts() / get_prompt()                    # 143 / 151
ping() / set_logging_level(level)                # 176 / 184
complete(ref, argument)                          # 206
```

`_client/_features.py` — notification/handler surface shared by all transports:

```python
protocol_version        # 94   negotiated version
capabilities            # 104  server capabilities
server_info             # 109
on_progress(handler)    # 117  → Unsubscribe
on_log(handler)         # 122
on_list_changed(handler)# 127
on_resource_updated(handler)  # 132
notify_roots_changed()  # 267
```

Plus `sampling_handler=`, `elicitation_handler=`, `roots=[Root(...)]` at
construction (`_features.py:_build_client_capabilities`, line 157), and
`_client/_stdio.py:205 stderr_tail()` for subprocess diagnostics.

**Reconnect/backoff — present (verified).** `ws()` exposes
`reconnect: bool = True`, `reconnect_delay: float = 1.0`,
`reconnect_max_delay: float = 30.0` (`_factory.py:124`, documented in
`src/lauren_mcp/llms-full.txt:381-383`); `streamable_http()` and `http()`
accept reconnect attempts (`_factory.py:166`, `_factory.py:205`); the SSE
client implements bounded retry (`_client/_sse.py:223-228`). So the earlier
assumption "no backoff" is **false** — the capability exists, though it is
per-transport and not unified into one policy object.

**Absent (verified by grep):**
- `grep -rniE "def cancel|cancel_request|cancelRequest" src/lauren_mcp/_client/`
  → **0 hits**. The client has **no way to cancel an in-flight request at
  all**, which is a notable asymmetry given the server accepts
  `$/cancelRequest`.
- no `notifications/cancelled` support either direction (§5.4)
- no `tasks/*`
- no client-side tool-search / deferred loading

---

## 8. Authentication

| Capability | Status | Evidence |
|---|---|---|
| Server `.well-known/oauth-authorization-server` | ✅ discovery doc only | `_server/_streamable.py:133` |
| Server `.well-known/oauth-protected-resource` | ✅ discovery doc only | `_server/_streamable.py:138` |
| OAuth 2.1 authorization-server implementation | ❌ | no AS endpoints (`/authorize`, `/token`, `/register`) |
| OAuth **client-credentials** token provider | ✅ | `_client/_oauth.py` (163 lines), `TokenStorage` protocol |
| PKCE | ❌ `grep -ril PKCE src/` → 0 | — |
| RFC 8707 resource indicators | ❌ `grep -ril RFC8707 src/` → 0 | — |
| Dynamic Client Registration | ❌ | — |
| CIMD / client metadata documents | ❌ | — |
| DNS-rebinding protection | ✅ | `_server/_transport_security.py` (108 lines) |
| Host/Origin/Content-Type validation | ✅ | `TransportSecuritySettings`, `McpTransportSecurityGuard` |
| Lauren guard/interceptor auth pipeline | ✅ | framework-level |

**Assessment:** the repo has *discovery documents without a server behind
them*, and a *client that only does client-credentials*. That is a coherent
"terminate auth at a gateway" stance, but it is not OAuth 2.1 MCP auth, and the
discovery endpoints will mislead a spec-compliant client that then tries
`/authorize`. This deserves a dedicated PRD with an explicit decision
(implement, or stop advertising).

`TransportSecuritySettings` is solid and matches the DNS-rebinding guidance
closely: wildcard-port host entries (`"example.com:*"`), implicit
localhost/127.0.0.1/::1 when empty, same-origin default for `Origin`, and
`application/json` content-type enforcement on POST.

---

## 9. Observability

`_server/_otel.py` (138 lines):

- no-op when `opentelemetry-api` is absent — zero import cost
- `instrument_dispatcher(dispatcher)` wraps `dispatch()` once (idempotent via `_otel_instrumented`)
- span name `mcp.<method>`; attributes `mcp.method`, `mcp.request_id`, `mcp.tool_name`
- W3C `traceparent`/`tracestate` extracted from JSON-RPC `_meta` (`_extract_context`)
- `StatusCode.ERROR` on exception or `INTERNAL_ERROR` response
- enabled via `for_root(instrument_otel=True)`

Also available: `notifications/message` structured logging with
`logging/setLevel` filtering, `notifications/progress`, and
`_server/_propagate.py` (95 lines) for execution-context propagation.

**Absent:** metrics (no counters/histograms for tool calls, latency, error
rates), no `mcp.session_id` or `mcp.protocol_version` span attributes, no
log-to-OTel bridge, no sampling/elicitation spans, no cost/token accounting.

---

## 10. CLI (`cli/_commands.py`, 341 lines; `lmcp`)

| Command | Purpose |
|---|---|
| `lmcp run` | serve; `--transport ws\|sse\|streamable\|all`, `--host`, `--port`, `--env-file`, `--stdio` |
| `lmcp dev` | dev server variant |
| `lmcp inspect` | list tools/resources/prompts of a server |
| `lmcp call` | invoke a tool with `--arg KEY=VALUE` (repeatable) |
| `lmcp install` | write `mcpServers` config for `--client claude\|cursor` |

`--reload` is declared but documented as *"Hot-reload (not yet implemented)"*
(`_commands.py:30`) — a visible loose end.

**Absent:** no `lmcp init`/scaffold, no `lmcp publish` (registry), no
`lmcp test`/conformance runner, no `lmcp doctor`, no `lmcp inspect --web`
(MCP Inspector integration), no `lmcp auth` helper.

---

## 11. Testing infrastructure

| Aspect | Detail |
|---|---|
| Test layout | `tests/` with unit/integration split |
| In-process clients | `WsTestClient`, `TestClient` — no subprocess needed |
| Echo server fixture | `tests/fixtures/echo_server.py` |
| Markers | `benchmark`, `eval` (both excluded from default `pytest`) |
| Coverage gate | `fail_under = 88`; `[all]` extras reach 94%+ |
| Benchmarks | `.benchmarks/` present (pytest-benchmark) |

**Absent:** no MCP **conformance** suite (`grep -ril conformance src/` → 0),
no cross-implementation interoperability tests against the official SDK or
FastMCP, no property-based testing of the JSON Schema builder, no fuzzing of
the JSON-RPC parser.

---

## 12. Doc drift — the docs are behind the source

`docs/comparisons.md` still tells users these are missing, while the source
implements them:

| `docs/comparisons.md` claims | Reality | Source |
|---|---|---|
| "OAuth 2.1 auth ❌", no drop-in OAuth provider | partially true (client-credentials + discovery docs exist) | `_client/_oauth.py` |
| "CLI tools ❌" | `lmcp run/dev/inspect/call/install` exist | `cli/_commands.py` |
| "OpenTelemetry ❌" | `_server/_otel.py` implemented | `_server/_otel.py` |
| "Per-resource subscriptions ❌ (missing on both sides)" | `ResourceSubscriptionManager` + client `subscribe_resource()` exist | `_server/_subscriptions.py`, `_protocol.py:108` |
| "Argument autocompletion ❌ not implemented by either library" | `@mcp_completion` + `completion/complete` exist | `_decorators.py:1064`, `_module.py:539` |
| "Session state ❌ `ctx.get_state()`" | only `ctx.get_metadata()` (read-only) — genuinely partial | `_context.py:313` |
| "Background tasks ❌ Docket integration" | `BackgroundTasks` **injection** exists; no external job queue | `_decorators.py:256` |

Similarly, the June-2026 `prds/python-sdk-gap-analysis.md` lists
`AudioContent`, `ResourceLink`, `ToolUseContent`, `ToolResultContent`,
resource subscriptions, argument completion, OTel and CLI as absent — all of
which now exist. **Any PRD in this set must therefore be based on this
inventory, not on the June-2026 documents.** These discrepancies are recorded
here so the new README can cross-reference (and not contradict) the old PRDs
without editing them.

---

## 13. Consolidated gap list (input to PRD selection)

Absences confirmed by exhaustive `grep -ril` over `src/` (hit counts in
parentheses for the near-misses):

**Protocol / spec**
1. `2026-07-28` revision unsupported entirely (§2) — and it is a *breaking* revision, not an additive one: see the migration note in §15
2. `notifications/cancelled` unimplemented; server listens for the non-existent `$/cancelRequest` instead (LSP name) — a conformance **bug**, not a version gap (§5.4)
3. `tasks/*` long-running task primitive absent (`tasks/get` 0, `TaskStore` 0) (§5)
4. `subscriptions/listen` absent (0) (§5)
5. Capability advertisement is coarse — no per-primitive `subscribe` flag, no `tasks`, no `extensions` (§4)

**Auth / security**
6. No OAuth 2.1 AS; no PKCE (0), no RFC 8707 (0), no DCR, no CIMD (§8)
7. Discovery documents advertised without an authorization server behind them (§8)
8. No token-passthrough / confused-deputy guidance or enforcement (§8)

**Client / agent integration**
9. No deferred tool loading / tool-search (0 hits) — breaks at large tool counts (§7)
10. No session-scoped writable state (read-only `get_metadata` only) (§6.3)
11. No client-side cancellation at all (0 hits in `_client/`); server only accepts legacy `$/cancelRequest` (§5.4, §7)
12. No client `tasks/*` support (§7)

**Ecosystem / packaging**
13. No `server.json` / MCP Registry publishing (0 hits) (§1, §10)
14. No conformance test suite (0) (§11)
15. No MCP Inspector integration; `lmcp inspect` is homegrown (0) (§10)
16. No `lmcp init` / `lmcp doctor` / `lmcp publish` (§10)

**Observability**
17. No metrics; no session/protocol span attributes; no sampling/elicitation spans (§9)

**Docs**
18. `docs/comparisons.md` materially stale (§12)

---

## 14. What this repo genuinely does better than its competitors

Recorded so the PRDs do not erode these advantages:

1. **Native WebSocket transport** — neither FastMCP nor the official Python SDK ships it.
2. **Three transports from one class** — `transport="all"` mounts WS + SSE + Streamable HTTP from a single `@mcp_server` class.
3. **Zero-required-Pydantic schema path** — `@dataclass`, `TypedDict`, `msgspec.Struct` all first-class; only two hard runtime dependencies.
4. **Lauren DI / guards / interceptors / middleware** — per-tool guards, interceptors, exception handlers and metadata come from the framework's pipeline, not a bespoke `Depends`.
5. **Server composition with prefixed mounts *and* remote proxying** — the official SDK has neither; aggregating heterogeneous MCP servers behind one endpoint is a differentiator.
6. **OpenAPI import** — `build_openapi_server_class()`.
7. **In-process test clients** — no subprocess needed for the WS/SSE path.

---

## 15. Critical reframing: `2026-07-28` is a *breaking* revision, not an additive one

Verified directly from `https://modelcontextprotocol.io/specification/2026-07-28/changelog`
on 2026-11-26. This materially changes how every gap must be framed, so it is
recorded here as inventory context.

The `2026-07-28` revision **removes the architecture this repo is built on**:

| Change | Effect on `lauren-mcp` |
|---|---|
| Protocol-level **sessions removed**; `Mcp-Session-Id` header dropped | `StreamableSessionStore`, the `mcp-session-id` header path and `DELETE` teardown become legacy-only |
| **`initialize` / `notifications/initialized` handshake removed**; version + capabilities move into per-request `_meta` | the entire `_handshake.py` flow is legacy-only |
| **`server/discover` added — servers MUST implement** | wholly absent; every new-era client will probe it first |
| **`subscriptions/listen`** replaces the HTTP GET endpoint and `resources/subscribe` / `resources/unsubscribe` | `ResourceSubscriptionManager` + GET push channel become legacy-only |
| **`ping`, `logging/setLevel`, `notifications/roots/list_changed` removed** | three implemented features are dead in the new era |
| **Tasks moved out of core** into the `io.modelcontextprotocol/tasks` extension (`tasks/get`, `tasks/update`; `tasks/result` and `tasks/list` removed) | repo has no tasks support in either era |
| **MRTR** (`resultType: "input_required"`, `inputRequests`/`inputResponses`) **replaces server-initiated requests** — i.e. `sampling/createMessage`, `elicitation/create`, `roots/list` | `ctx.sample()`, `ctx.elicit()`, `ctx.elicit_url()` are legacy-only; a new mechanism is required |
| **`resultType` now required on every result** | all result builders need it; clients MUST treat missing as `"complete"` |
| **SSE resumability removed** — `Last-Event-ID` and SSE event IDs gone; broken streams must be re-issued with a new request ID | the entire `EventStore` / `InMemoryEventStore` replay subsystem becomes legacy-only |
| **`ttlMs` + `cacheScope` required** on list/read results (`CacheableResult`) | absent |
| **`extensions` field** added to `ClientCapabilities`/`ServerCapabilities` | absent |
| `Mcp-Method` / `Mcp-Name` headers + `x-mcp-header` | absent |
| Resource-not-found error code `-32002` → `-32602`; MCP-reserved error range `-32020`…`-32099` | `McpErrorCode` has no `-32002` and no reserved range |
| **Roots, Sampling, Logging deprecated** (SEP-2577); HTTP+SSE deprecated (SEP-2596); **DCR deprecated** in favour of CIMD (PR #2858), ≥12-month removal window | the repo's newest features target capabilities now on a deprecation clock |

**Consequence for the PRD set.** The correct strategic goal is **dual-era
support**, not migration-by-replacement: the ecosystem still runs
`2025-11-25`/`2025-06-18` in production, and `2026-07-28` peers will not
speak the session/handshake protocol at all. So the repo needs
(a) a version-negotiated behaviour split, (b) a new-era path implementing
`server/discover` + `subscriptions/listen` + MRTR + `resultType`/`ttlMs`, and
(c) explicit retention of the legacy path. Any PRD proposing to *replace*
the session model outright would break every current user.

Two further notes for PRD authors:

- The repo's `STABLE = "2024-11-05"` is misleading — that revision predates
  Streamable HTTP and is now the most-deprecated era. "Stable" there means
  "oldest", and should be reconsidered.
- `notifications/cancelled` has existed since `2024-11-05` (§5.4), so
  cancellation is fixable **today, in every supported era**, independently of
  any `2026-07-28` work. It is the cheapest correctness win available.
