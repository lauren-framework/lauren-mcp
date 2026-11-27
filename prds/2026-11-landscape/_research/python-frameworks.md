# Python MCP Frameworks — Landscape & Migration Comparison

**As of:** 2026-11-26 · **Repo context:** `lauren-mcp` (hand-built MCP server + client for the Lauren DI framework)
**Scope:** the official `mcp` SDK 2.x line and its full 1.x → 2.x delta; server frameworks (FastMCP, litestar-mcp, fastapi-mcp, django-mcp-server); client/agent-side consumers (mcp-use, mcp-agent, PydanticAI, smolagents, mcpadapt).
**Method:** every version, date, dependency constraint and licence claim below was read from the PyPI JSON API, the GitHub API (release notes / repo metadata) or the upstream docs on `main`, on 2026-11-26. See [Sources](#sources).

**Evidence key** used in cells: `✓` read directly from a primary source on 2026-11-26 · `~` inferred from a primary source (stated as inference) · `n/v` not verified.

---

## 1. Snapshot: versions, health, dependency posture

| Project | Latest on PyPI | Released | Licence | Python | Declared dependency on the SDK | GH stars | Repo last push |
|---|---|---|---|---|---|---|---|
| **mcp** (official SDK) | **2.3.0** | 2026-10-02 | MIT ✓ | >=3.10 ✓ | — (it *is* the SDK) | 24,980 | 2026-11-17 |
| **mcp** (1.x maintenance) | **1.30.0** | 2026-09-07 | MIT ✓ | >=3.10 ✓ | — | — | line ends here |
| **mcp-types** (split-out wire types) | **2.3.0** | 2026-10-02 | MIT ✓ | >=3.10 ✓ | `pydantic`, `typing-extensions` only ✓ | (same org) | — |
| **fastmcp** (PrefectHQ) | **4.2.6** | 2026-11-25 | Apache-2.0 ✓ | >=3.11 ✓ | **no `mcp` dep** — `fastmcp-slim[client,server]==4.2.6` ✓ | 28,768 | 2026-11-26 |
| **fastmcp-slim** | **4.2.6** | 2026-11-25 | Apache-2.0 ✓ | >=3.11 ✓ | `mcp-types>=2.0,<3.0` ✓ | — | — |
| **mcp-use** | **1.7.1** | 2026-09-10 | MIT ✓ | >=3.11 ✓ | `mcp<2.0.0,>=1.24.0` ✓ | 11,012 | 2026-11-26 |
| **mcp-agent** | **0.2.6** | 2025-12-05 | Apache-2.0 ✓ | >=3.10 ✓ | `mcp>=1.20.0` ✓ (open bound) | 8,596 | 2026-01-25 |
| **pydantic-ai-slim** | **2.75.0** | 2026-11-25 | MIT ✓ | >=3.10 ✓ | `mcp` extra → `fastmcp-slim[client]>=3.3.0,<5` ✓ | 21,411 (pydantic-ai) | 2026-11-26 |
| **smolagents** | **1.26.0** | 2026-05-29 | Apache-2.0 ✓ | >=3.10 ✓ | `mcp` extra → `mcp` (unpinned) + `mcpadapt>=0.1.13` ✓ | 30,547 | 2026-11-26 |
| **fastapi-mcp** | **0.4.0** | 2025-07-28 | MIT ✓ | >=3.10 ✓ | `mcp>=1.12.0` ✓ | 12,031 | 2025-11-24 |
| **django-mcp-server** | **0.5.7** | 2025-10-10 | MIT ✓ | >=3.9 ✓ | `mcp>=1.8.0` ✓ | 391 | 2026-03-10 |
| **litestar-mcp** | **0.20.2** | 2026-11-23 | MIT ✓ | >=3.9 ✓ | **no `mcp` dep** — `anyio`, `httpx2>=2.13.1`, `litestar>=2.23.0`, `pyyaml` ✓ | 13 | 2026-11-26 |
| **mcpadapt** | **0.1.20** | 2025-10-24 | MIT ✓ | >=3.10 ✓ | `mcp[ws]>=1.10.1` ✓ | 425 | 2025-10-24 |
| **lauren-mcp** (this repo) | `0.1.x` | — | — | >=3.11 ✓ | **no `mcp` dep** — `lauren>=1.7.0`, `anyio>=4.0` ✓ | — | — |

Baseline for reference: **lauren 1.12.0**, released **2026-11-15** ✓.

Three structural facts fall out of that table:

1. **The `mcp` package is no longer the mandatory substrate.** FastMCP 4.x, litestar-mcp and lauren-mcp all speak the protocol without depending on it. FastMCP buys only `mcp-types` (wire types); litestar-mcp and lauren-mcp implement the protocol themselves.
2. **`mcp-types` is the real integration point.** Anyone who wants wire-level compatibility without the SDK's transports/auth/CLI pins `mcp-types>=2.0,<3.0`.
3. **The long tail is stranded on 1.x.** Four of the projects surveyed either hard-cap (`mcp<2.0.0`), pin an extra that no longer exists (`mcp[ws]`), or have not shipped in 7–16 months.

---

## 2. Capability matrix

| Project | Server side | Client side | stdio | Streamable HTTP | WebSocket | 2026-07-28 era | Typed tool schemas | DI / resolvers | OTel | In-process test client |
|---|---|---|---|---|---|---|---|---|---|---|
| **mcp 2.3.0** | `MCPServer` + raw `Server` ✓ | `Client` (first-class) ✓ | ✓ | ✓ | **removed** ✓ | ✓ native | Pydantic-native ✓ (`mcp-types` needs `pydantic`) | `Resolve(fn)` param resolvers ✓ | **on by default** ✓ | `create_connected_server_and_client_session()` ✓ |
| **FastMCP 4.2.6** | ✓ | ✓ (`fastmcp-slim[client]`) ✓ | ✓ | ✓ | n/v (v3 had WS; v4 static) | ✓ + handshake eras auto-detected ✓ | Pydantic; accepts dataclass/TypedDict-style annotations ✓ | unified DI system + `Depends`-style ✓ | ✓ own spans + SDK-style propagation | ✓ (`Client(server)`) ✓ |
| **mcp-use 1.7.1** | n/v (agent-first) | ✓ LangChain agents ✓ | ✓ | ✓ | n/v | ✗ (1.x cap) ✓ | Pydantic + Zod-derived (TS-first project) ✓ | n/v | n/v | n/v |
| **mcp-agent 0.2.6** | minimal (exposes agent) ~ | ✓ ✓ | ✓ | ✓ | n/v | ✗ (1.x, stale) ✓ | Pydantic ✓ | workflow/agent composer | n/v | ✓ (`MCPApp`) ~ |
| **PydanticAI 2.75.0** | ✓ via FastMCP ✓ | ✓ via FastMCP ✓ | ✓ | ✓ | n/v | ✓ (because FastMCP ≥3.3) ✓ | Pydantic models first-class ✓ | `RunContext` deps + resolvers ✓ | ✓ instrumentation | ✓ (`TestModel`/`FunctionModel`) ✓ |
| **smolagents 1.26.0** | ✗ | ✓ via `mcpadapt` ✓ | ✓ | ✓ | n/v | **✗** — `mcp[ws]` path | HF `@tool` signature → schema ~ | ✗ | ✗ | n/v |
| **fastapi-mcp 0.4.0** | ✓ (FastAPI → MCP) ✓ | ✗ | ✓ | ✓ | ✗ | ✗ (stale, `mcp>=1.12.0` open) ✓ | from FastAPI type hints ~ | FastAPI `Depends` surface ~ | ✗ | ✗ |
| **django-mcp-server 0.5.7** | ✓ (DRF → MCP) ✓ | ✗ | ✓ | ✓ | ✗ | ✗ (stale) ✓ | DRF serializers ~ | Django DI/auth ~ | ✗ | ✗ |
| **litestar-mcp 0.20.2** | ✓ (Litestar handlers → MCP) ✓ | ✗ | ✗ (HTTP-native) | ✓ (`httpx2`) ✓ | ✗ | ✓ (own protocol impl) ~ | Litestar signature models ✓ | Litestar DI ✓ | n/v | ✓ (Litestar TestClient) ~ |
| **mcpadapt 0.1.20** | ✗ | ✓ (tool adapters) ✓ | ✓ | ✓ | `mcp[ws]` ✓ | ✗ | via wrapped callables ~ | ✗ | ✗ | ✗ |
| **lauren-mcp** | ✓ | ✓ | ✓ | ✓ | **✓ native** | n/v (verify 2026-07-28 parity) | dataclass / TypedDict / msgspec, no Pydantic ✓ | Lauren guards/interceptors + prefixed mounts + remote proxying ✓ | ✓ spans | ✓ |

---

## 3. Official `mcp` SDK — the complete 1.x → 2.0 transition

### 3.1 Release history around the cut

| Date | Release | Note |
|---|---|---|
| 2026-06-30 | 2.0.0b1 | first v2 beta |
| 2026-07-14 | 2.0.0b2 | — (this is the pin FastMCP 4.0.0 migrated onto) ✓ |
| 2026-07-27 | 2.0.0rc1 | — |
| **2026-07-28** | **2.0.0** + **1.29.0** | v2 GA; 1.x gets one more feature release the same day |
| 2026-08-25 | 2.1.1 | — |
| 2026-08-26 | 2.0.1 | — |
| 2026-09-07 | **1.30.0** + **2.2.0** | 1.x maintenance line's **final** release, shipped alongside 2.2.0 |
| **2026-10-02** | **2.3.0** (+ `mcp-types` 2.3.0) | current |

### 3.2 Dependency-level delta

| Aspect | 1.30.0 | 2.3.0 |
|---|---|---|
| Base deps | `anyio`, `httpx`, `httpx-sse`, `pydantic`, `starlette`, `sse-starlette`, `uvicorn`, `python-multipart`, `jsonschema` ~ | `anyio` (>=4.9, or >=4.10 on 3.14), **`httpx2>=2.10.0`**, `jsonschema>=4.20.0`, **`mcp-types==2.3.0`**, **`opentelemetry-api>=1.28.0`** ✓ |
| Extras | `cli`, `rich`, **`ws`** (`websockets>=15.0.1`) ✓ | `cli` (`python-dotenv`, `typer>=0.16.0`), `rich` (`rich>=13.9.4`) — **no `ws`** ✓ |
| Wire types | `mcp.types` inside the wheel | separate `mcp-types` dist (import `mcp_types`), pinned exactly ✓ |
| Console script | `mcp` | **still `mcp`** (`mcp = "mcp.cli:app [cli]"`) ✓ — only the class/module path changed |
| OTel | opt-in | **required dep + enabled by default** ✓ |

> Practical consequence: `pip install "mcp[ws]"` still *resolves* on 2.x (pip tolerates a missing extra) but silently provides nothing, because `2.3.0` declares no `ws` extra. Any package pinning `mcp[ws]` looks healthy and is not.

### 3.3 Breaking-change table (1.x → 2.x)

| # | Area | 1.x | 2.x | First symptom in the wild | Action |
|---|---|---|---|---|---|
| 1 | **Server class** | `from mcp.server.fastmcp import FastMCP` | `from mcp.server.mcpserver import MCPServer` ✓ | `ModuleNotFoundError: No module named 'mcp.server.fastmcp'` ✓ | rename class + import; newer 2.x point at the migration doc |
| 2 | **Default server name** | `FastMCP` | `mcp-server` ✓ | server `name` in `discover`/`initialize` results changes | pass `name=` explicitly |
| 3 | **Exceptions** | `McpError` | `MCPError` ✓ | `ImportError` / `AttributeError` in `except McpError` handlers | drop-in rename, no behaviour change ✓ |
| 4 | **Wire types package** | `mcp.types` (bundled) | standalone **`mcp-types`**, import `mcp_types` ✓ | `mcp.types.Tool` resolves but new types only land in `mcp_types`; duplicate-model `isinstance` failures in mixed trees | prefer `mcp_types`; `mcp.types` stays as a supported alias ✓ |
| 5 | **Field naming** | `camelCase` on the wire models | `snake_case` ✓ | `ValidationError` / silently unset fields when constructing types positionally | drop `alias=` workarounds; check `model_dump(by_alias=True)` sites |
| 6 | **Removed type aliases** | `Cursor`, and other aliases/classes | replaced — `Cursor` → plain `str` ✓; `RequestParams.Meta` → `RequestParamsMeta` TypedDict ✓; `RootModel` unions → `TypeAdapter` validation ✓ | `ImportError`, `AttributeError`, or pydantic union errors | follow the removed-types table in the migration guide ✓ |
| 7 | **Protocol version constants** | `SUPPORTED_PROTOCOL_VERSIONS`, single meaning for `LATEST_PROTOCOL_VERSION` | `SUPPORTED_PROTOCOL_VERSIONS` **deprecated** = union of `HANDSHAKE_PROTOCOL_VERSIONS` + `MODERN_PROTOCOL_VERSIONS`; use `LATEST_HANDSHAKE_VERSION`, `LATEST_MODERN_VERSION`, `OLDEST_SUPPORTED_VERSION` ✓ | version checks silently match the wrong era | branch on the era tuples, never index `SUPPORTED_PROTOCOL_VERSIONS` |
| 8 | **Client handshake** | always `initialize` | `Client` defaults to **`mode='auto'`**: probes `server/discover`, falls back to `initialize` ✓ | assertions on handshake ordering; mocks that only implement `initialize` | pin `mode='handshake'` for legacy peers; `server_capabilities`/`server_info`/`instructions`/`protocol_version` now live on the session ✓ |
| 9 | **Multi-round-trip** | tool could only elicit via server→client request | tool returns **`InputRequiredResult`**; params annotated `Resolve(fn)` are filled server-side ✓ | n/a (new) | register `elicitation_callback` / `sampling_callback` / `list_roots_callback`; `Client` drives the loop, or drive it manually ✓ |
| 10 | **Tasks (SEP-1686)** | experimental task support + `experimental` props on `ClientSession`, `ServerSession`, `Server`, `ServerRequestContext` | **removed from the spec and the SDK**; `Task*` types remain in `mcp-types` for wire compat ✓ | `AttributeError` on `.experimental` | delete task polling; use multi-round-trip instead |
| 11 | **WebSocket transport** | `mcp.client.websocket.websocket_client`, `mcp.server.websocket.websocket_server`, `mcp[ws]` | **all removed** ✓; use streamable HTTP (`streamable_http_client` / `streamable_http_app()`) ✓ | `ImportError`, `ModuleNotFoundError` on the `websockets` stack | port to streamable HTTP, or keep your own WS framing (see §9) |
| 12 | **Streamable-HTTP client name** | `streamablehttp_client` | `streamable_http_client` ✓ | `ImportError: cannot import name 'streamablehttp_client'` ✓ | rename |
| 13 | **HTTP stack** | `httpx` + `httpx-sse` | **`httpx2`** ✓ (types and parameter lists preserved ✓) | `httpx` monkeypatches/`respx` fixtures stop intercepting | port test doubles to `httpx2`; watch for duplicate `httpx`/`httpx2` in the lockfile |
| 14 | **Observability** | opt-in | **OTel on by default** (SEP-414): every server installs tracing middleware; client + server spans recorded with no code change; W3C `traceparent` injected into outbound `_meta` ✓ | unexpected span volume / collector load; `opentelemetry-api` now mandatory | configure a sampler or disable; otherwise just enjoy free traces |
| 15 | **Low-level `Server`** | — | **rebuilt, not renamed** ✓; `request_context` property removed ✓; `Server.run()` no longer takes `stateless` ✓; cancelled requests are no longer answered ✓ | anything touching the JSON-RPC layer breaks wholesale ✓ | if you were on the raw `Server`, budget a real port |
| 16 | **Context** | `Context.client_id` | removed ✓ | `AttributeError` | read the requester from the session/request context |
| 17 | **Auth (additive)** | — | **SEP-990** identity assertion (ID-JAG / on-behalf-of) plus stricter client auth at `/token` and `/revoke` ✓ | none (additive) | none required |
| 18 | **Packaging/CLI** | `uv run --with mcp …` unpinned in spawned envs ✓ | pinned so the spawned env matches ✓ | dev server running a different SDK than the app | none |

### 3.4 What v2 adds that v1 could not express

* **Two protocol eras in one server.** `HANDSHAKE_PROTOCOL_VERSIONS` (session-based `initialize`, up to 2025-11-25) and `MODERN_PROTOCOL_VERSIONS` (sessionless, per-request-negotiated, 2026-07-28) ✓. A v2 server negotiates per connection; `discover` is transport-independent and answered over stdio as well as streamable HTTP ✓.
* **`Resolve(fn)` dependency injection.** A tool parameter annotated `Resolve(fn)` is filled by your function, invisible to the model, and falls back to live elicitation on legacy clients or multi-round-trip on 2026-07-28 — one tool body for both eras ✓. This is the closest thing in the official SDK to a DI framework, and it is the direct competitor to lauren-mcp's resolver story.
* **`InputRequiredResult`** as the explicit "I need more input" return value ✓.
* **First-class `Client`** rather than a bag of transport helpers ✓; it runs the multi-round-trip loop for you ✓.
* **Tracing by default** ✓.

---

## 4. FastMCP (PrefectHQ) 4.2.6 — the independent successor

**Lineage:** v3.0.0 **2026-02-18** ✓, v4.0.0 **2026-08-31** ✓, v4.2.6 **2026-11-25** ✓ (v4.2.7a1 on 2026-11-26, prerelease) ✓. Apache-2.0 ✓. Ships `fastmcp` (meta) + `fastmcp-slim` (the real implementation) ✓.

### 4.1 The decoupling event

`fastmcp-slim` **4.0.0 already depends on `mcp-types<3.0.0,>=2.0.0` and not on `mcp`** ✓ — i.e. FastMCP stopped consuming the official SDK at the 4.0 boundary, while "Migrate to MCP SDK v2.0.0b2 (httpx2)" appears in the 4.0.0 breaking-changes list ✓. Net effect: FastMCP owns its protocol implementation and shares only the wire types with the SDK. That is a genuinely different position from "wrapper around `mcp`", and it is why FastMCP can move on its own cadence (11 releases in the three weeks before 2026-11-26) while PydanticAI can pin `fastmcp-slim[client]>=3.3.0,<5` and never see the SDK at all.

### 4.2 v3.0.0 breaking changes (2026-02-18) ✓

| Change | Impact |
|---|---|
| `VisibilityFilter` for hierarchical enable/disable | new filtering model; replaces ad-hoc enabling |
| Automatic env-var loading removed from auth providers | auth config that "worked" via ambient env now fails loudly |
| `pydocket` made optional; **DI systems unified** | one dependency-injection surface instead of two |
| Session-scoped state persistence | server state survives across a session without custom plumbing |
| `ui=` renamed to `app=`, `ToolUI`/`ResourceUI` consolidated into `AppConfig` | MCP Apps API rename |
| Deprecated `FastMCP()` constructor arguments removed | ctor signature break |

### 4.3 v4.0.0 breaking changes (2026-08-31) ✓

| Change | Impact |
|---|---|
| One `SERVER` span per request; spec-correct error codes | trace shape changes; error codes now spec-aligned |
| **All 3.x deprecated module shims and dead parameters removed** | old import paths hard-fail |
| 3.0-deprecated server methods removed; 3.x deprecated parameters + object-mode decorators removed | decorator/object-mode users must migrate |
| Migrated onto **MCP SDK v2.0.0b2 (httpx2)** | `httpx2` everywhere, incl. test doubles |
| Proxies no longer validate backend results or mutate shared transport state | proxy-layer bugs fixed, but proxy-side validation logic disappears |

### 4.4 Position

FastMCP v4 **serves the sessionless 2026-07-28 era and the session-based handshake eras from a single server, with per-connection auto-detection** ✓ — the same two-era trick as the official SDK, achieved independently. It also carries SEP-990 identity assertion ✓. It is the de-facto standard for Python servers that want batteries (apps, proxies, providers, auth, CLI) and is what PydanticAI now builds on ✓.

**Risk for lauren-mcp:** FastMCP is the incumbent in exactly the "batteries included, but not Pydantic-locked" niche only if you accept its Pydantic centrism — it is Pydantic-first, whereas lauren-mcp's differentiator is dataclass/TypedDict/msgspec-native schemas with no Pydantic requirement.

---

## 5. mcp-use 1.7.1 (2026-09-10)

| Aspect | Value |
|---|---|
| Licence / Python | MIT ✓ / >=3.11 ✓ |
| SDK pin | **`mcp<2.0.0,>=1.24.0`** ✓ — hard cap on 1.x |
| Stack | `langchain>=1.0.0`, `httpx>=0.27.1`, `authlib>=1.0.0`, `pydantic>=2.11,<3`, `jsonschema-pydantic`, `posthog` ✓ |
| Shape | Python port of a TypeScript-first project (Zod-heritage "fully typed" pitch ✓); agent/client-side |
| Repo | 11,012 stars, pushed 2026-11-26 ✓ — actively developed *except* for the SDK pin |

**Read:** mcp-use is the clearest current example of the 1.x ceiling. It is a live, popular project whose `mcp<2.0.0` pin means it will not see `MCPServer`, `mcp-types`, `httpx2` or the 2026-07-28 era until it ships a 2.x-compatible major. If you are choosing a client layer today, ask for its 2026-07-28 story before committing.

---

## 6. mcp-agent 0.2.6 (2025-12-05)

| Aspect | Value |
|---|---|
| Licence / Python | Apache-2.0 ✓ / >=3.10 ✓ |
| SDK pin | `mcp>=1.20.0` ✓ (open) + `fastapi>=0.115.6` |
| Repo | 8,596 stars, **last push 2026-01-25** ✓ |
| Differentiator | agent *patterns* library — durable execution via **Temporal** ✓, workflow composition |

**Read:** open upper bound, so it *installs* against 2.x, but it has not shipped in ~12 months and its last commit predates v2 GA by six months. Treat as unmaintained against the 2.x behavioural changes (`mode='auto'`, removed `stateless`, rebuilt low-level `Server`, `McpError`→`MCPError`) — an open bound is not a compatibility statement.

---

## 7. PydanticAI 2.75.0 (2026-11-25) — the migration that matters

| Version | `mcp` extra resolves to | Date |
|---|---|---|
| 1.60.0 | `mcp<2.0,>=1.25.0` ✓ | — |
| **2.0.0** | **`fastmcp-slim[client]>=3.3.0`** ✓ | **2026-06-23** ✓ |
| 2.20.0 | `fastmcp-slim[client]>=3.3.0,<4` ✓ | — |
| 2.75.0 | `fastmcp-slim[client]>=3.3.0,<5` ✓ | 2026-11-25 ✓ |

**Read:** this is the single most consequential ecosystem datapoint in the survey. PydanticAI — MIT, 21k+ stars, shipped daily — **replaced the official SDK with FastMCP for its MCP support**, before the SDK's own v2 GA and never came back. It means (a) FastMCP is now a peer of the official SDK and not a wrapper, and (b) any framework that assumes "`mcp` is the common denominator" is already wrong.

---

## 8. smolagents 1.26.0 (2026-05-29)

| Aspect | Value |
|---|---|
| Licence / Python | Apache-2.0 ✓ / >=3.10 ✓ |
| `mcp` extra | **`mcp` (unpinned)** + **`mcpadapt>=0.1.13`** ✓ |
| Repo | 30,547 stars, pushed 2026-11-26 ✓ |
| Shape | client-only tool consumption, via adapters |

**Read:** the unpinned `mcp` looks v2-ready and is not — it drags in `mcpadapt`, whose own pin is `mcp[ws]>=1.10.1` (§12). Install it against `mcp` 2.3.0 and you get a resolver that accepts the tree while the WebSocket extra silently evaporates. This is the highest-probability "worked yesterday, broken today" combination in the survey.

---

## 9. Server-side adapters: FastAPI, Django, Litestar

| Project | Latest | SDK dep | Transport story | Verdict |
|---|---|---|---|---|
| **fastapi-mcp** | 0.4.0 (2025-07-28) ✓ | `mcp>=1.12.0` ✓ | auto-exposes FastAPI routes ✓ | **16 months stale**, pushed 2025-11-24 ✓; pre-dates the entire v2 era |
| **django-mcp-server** | 0.5.7 (2025-10-10) ✓ | `mcp>=1.8.0` ✓ | DRF serializers → tools ✓ | 13 months stale; last push 2026-03-10 ✓ |
| **litestar-mcp** | 0.20.2 (2026-11-23) ✓ | **none** — `anyio`, **`httpx2>=2.13.1`**, `litestar>=2.23.0`, `pyyaml` ✓ | HTTP-native, own protocol impl; `a2a` extra (`a2a-sdk>=1.1.4`, `protobuf`) ✓ | **most current of the three**, and architecturally the closest analogue to lauren-mcp |

**The litestar-mcp signal:** a framework adapter that dropped the SDK, moved to `httpx2`, and is pushing daily is the same bet lauren-mcp has made. Note the shared tell — both litestar-mcp and `mcp` 2.3.0 depend on **`httpx2`**, so `httpx2` is now the de-facto HTTP substrate of the 2026 Python MCP ecosystem. Any library still intercepting `httpx` is a test-suite liability.

---

## 10. mcpadapt 0.1.20 (2025-10-24)

| Aspect | Value |
|---|---|
| SDK pin | **`mcp[ws]>=1.10.1`** ✓ |
| Repo | 425 stars, **last push 2025-10-24** ✓ |
| Role | wraps MCP servers as framework tools (smolagents et al.) |

**Two problems, both fatal for 2.x adoption:** the `[ws]` extra **no longer exists** in `mcp` 2.3.0 ✓, and the package itself has not moved in 13 months. Because smolagents references it unpinned, this single stale pin silently caps the MCP capability of a 30k-star project.

---

## 11. lauren-mcp — where this repo sits (baseline column)

| Dimension | lauren-mcp | Nearest competitor | Standing |
|---|---|---|---|
| Hard deps | `lauren>=1.7.0`, `anyio>=4.0` ✓ | FastMCP: 6+ deps incl. `pydantic[email]`, `platformdirs`, `pydantic-settings`, `python-dotenv`, `rich` | **best in class** — 2 deps, no Pydantic, no HTTP client, no CLI framework |
| Schema sources | dataclass / TypedDict / msgspec native ✓ | FastMCP/litestar-mcp: Pydantic-first ✓; SDK: Pydantic required ✓ | **unique** |
| WebSocket transport | **native** ✓ | SDK **removed** WS entirely ✓; FastMCP v4 n/v; adapters none | **unique, and newly so** |
| Guards/interceptors | ✓ (Lauren) | SDK: `Resolve` only ✓; FastMCP: unified DI ✓ | parity-ish; Lauren's is framework-native |
| Composition | prefixed mounts + remote proxying ✓ | FastMCP proxies ✓ (now non-validating, v4) ✓ | parity |
| OpenAPI import | ✓ | fastapi-mcp derives from routes; litestar-mcp from handlers | parity/better |
| In-process test client | ✓ | SDK ✓, FastMCP ✓, PydanticAI ✓ | parity |
| OTel | ✓ spans | SDK: **default-on** ✓; FastMCP ✓ | table stakes now — not a differentiator |
| Protocol 2026-07-28 | **n/v — must confirm** | SDK ✓, FastMCP ✓ (auto-detect) | **gap risk** |
| CLI | `lmcp run/dev/inspect/call/install` ✓ | SDK: `mcp` ✓; FastMCP CLI ✓ | parity |

**Two conclusions for this repo:**

1. **OTel and in-process test clients are no longer differentiators.** The official SDK turned tracing on by default (SEP-414) and now ships a first-class `Client`, which erases two of the previously listed advantages. Keep the features; drop them from the pitch.
2. **`Resolve(fn)` is the real competitive move to answer.** The official SDK now has a resolver-shaped DI primitive that spans both protocol eras automatically. lauren-mcp's guards/interceptors are richer, but the doc-level comparison a buyer will make is "does a tool parameter get filled for me, on legacy *and* modern clients?" Answer that explicitly, and make the WS transport + zero-Pydantic + 2-dep story the headline.
3. **Confirm 2026-07-28 parity.** Both the SDK and FastMCP serve modern (sessionless, per-request-negotiated) and handshake eras from one server. If `lauren-mcp` only speaks the handshake era, that is the single largest gap in the matrix.

---

## 12. Who is stranded, and what it costs

| Project | Pin / state | Consequence | Cost to fix |
|---|---|---|---|
| mcp-use 1.7.1 | `mcp<2.0.0,>=1.24.0` ✓ | no `mcp-types`, no `httpx2`, no 2026-07-28 era, no `MCPServer` | needs a major release; active repo, so plausible |
| mcpadapt 0.1.20 | `mcp[ws]>=1.10.1` ✓ | **`ws` extra no longer exists**; 13 months stale | must drop the extra and adopt v2 transports |
| smolagents 1.26.0 | `mcp` unpinned + mcpadapt ✓ | resolves against 2.3.0 while inheriting mcpadapt's dead `[ws]` pin | pin + migrate upstream |
| mcp-agent 0.2.6 | `mcp>=1.20.0` ✓, last push 2026-01-25 ✓ | open bound ≠ compatibility; untested against rebuilt low-level `Server` and `mode='auto'` | needs a maintainer |
| fastapi-mcp 0.4.0 | `mcp>=1.12.0` ✓, 16 months stale ✓ | pre-v2 entirely | fork or replace |
| django-mcp-server 0.5.7 | `mcp>=1.8.0` ✓, 13 months stale ✓ | pre-v2 entirely | fork or replace |
| **Safe today** | mcp 2.3.0, fastmcp 4.2.6, fastmcp-slim 4.x, litestar-mcp 0.20.2, pydantic-ai ≥2.0 | — | — |

---

## 13. Migration playbook (1.x → 2.x), ordered by blast radius

1. **Pin and branch.** `mcp>=2.3.0,<3` + `mcp-types>=2.3,<3`. Keep 1.30.0 alive in a maintenance branch: it is the last 1.x release, dated 2026-09-07 ✓.
2. **Rename, mechanically.** `FastMCP`→`MCPServer`, `mcp.server.fastmcp`→`mcp.server.mcpserver`, `McpError`→`MCPError`, `streamablehttp_client`→`streamable_http_client`.
3. **Type surface.** Move imports to `mcp_types`; convert `camelCase` field construction to `snake_case`; replace `Cursor` with `str`; replace `RequestParams.Meta` with `RequestParamsMeta`; replace `RootModel` unions with `TypeAdapter`.
4. **HTTP stack.** `httpx`→`httpx2` in app *and* tests (respx-style interception does not cross over).
5. **Transports.** Any `websocket_client`/`websocket_server`/`mcp[ws]` usage: port to streamable HTTP, or keep native WS framing outside the SDK.
6. **Client semantics.** Audit for `mode='auto'` (`discover` probe, no unconditional `initialize`), for the removed `stateless` flag, for `.experimental` task access, and for `Context.client_id`.
7. **Observability.** Decide the sampler before shipping — tracing is now on by default and `opentelemetry-api` is a hard dep.
8. **Optional upside.** Adopt `Resolve(fn)` + `InputRequiredResult` to get elicitation/multi-round-trip on both protocol eras with one tool body.

---

## Sources

All URLs retrieved **2026-11-26**.

| # | Claim(s) supported | URL | Retrieved |
|---|---|---|---|
| 1 | `mcp` 2.3.0 = latest, 2026-10-02, MIT, py>=3.10, deps `httpx2`, `mcp-types==2.3.0`, `opentelemetry-api`, extras `cli`/`rich` (no `ws`) | https://pypi.org/pypi/mcp/json | 2026-11-26 |
| 2 | 1.x line: 1.29.0 (2026-07-28), 1.30.0 (2026-09-07) and its `ws` extra (`websockets>=15.0.1`) | https://pypi.org/pypi/mcp/1.30.0/json | 2026-11-26 |
| 3 | Full release timeline incl. 2.0.0b1/b2/rc1 and 2.2.0 | https://pypi.org/pypi/mcp/json (releases map) · https://github.com/modelcontextprotocol/python-sdk/releases | 2026-11-26 |
| 4 | v2 GA announcement, 2026-07-28 protocol revision | https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.0.0 | 2026-11-26 |
| 5 | `FastMCP`→`MCPServer`, `mcp.server.fastmcp` ModuleNotFoundError, default server name, `McpError`→`MCPError`, `mcp.types`→`mcp-types`, snake_case fields, removed aliases, `SUPPORTED_PROTOCOL_VERSIONS`, `mode='auto'`, `InputRequiredResult`, tasks removal, WS removal, `streamablehttp_client` removal, httpx2, OTel default, low-level `Server` rebuild, `stateless`, `Context.client_id`, SEP-990, packaging/CLI | https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/migration.md | 2026-11-26 |
| 6 | `Resolve(fn)`, first-class `Client` | https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/whats-new.md | 2026-11-26 |
| 7 | Multi-round-trip / `InputRequiredResult` client loop | https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/handlers/multi-round-trip.md | 2026-11-26 |
| 8 | Console script remains `mcp = "mcp.cli:app [cli]"`; `mcp-types` split | https://github.com/modelcontextprotocol/python-sdk/blob/main/pyproject.toml | 2026-11-26 |
| 9 | `mcp-types` 2.3.0, 2026-10-02, deps `pydantic` + `typing-extensions` | https://pypi.org/pypi/mcp-types/json | 2026-11-26 |
| 10 | FastMCP 4.2.6 (2026-11-25), py>=3.11, Apache-2.0, `fastmcp-slim==4.2.6` | https://pypi.org/pypi/fastmcp/json | 2026-11-26 |
| 11 | `fastmcp-slim` 4.0.0 already on `mcp-types<3,>=2` with **no** `mcp` dep; 4.2.6 deps | https://pypi.org/pypi/fastmcp-slim/4.0.0/json · https://pypi.org/pypi/fastmcp-slim/json | 2026-11-26 |
| 12 | FastMCP v3.0.0 2026-02-18 + v3 breaking changes; v4.0.0 2026-08-31 + v4 breaking changes incl. "Migrate to MCP SDK v2.0.0b2 (httpx2)" | https://github.com/PrefectHQ/fastmcp/releases/tag/v3.0.0 · https://github.com/PrefectHQ/fastmcp/releases/tag/v4.0.0 | 2026-11-26 |
| 13 | FastMCP v4 serves 2026-07-28 + handshake eras per connection; SEP-990 | https://github.com/PrefectHQ/fastmcp/blob/main/dev-docs/v4-notes/protocol-2026.md | 2026-11-26 |
| 14 | FastMCP stars/licence/activity (28,768 · Apache-2.0 · push 2026-11-26) | https://api.github.com/repos/PrefectHQ/fastmcp | 2026-11-26 |
| 15 | mcp-use 1.7.1 (2026-09-10), `mcp<2.0.0,>=1.24.0`, langchain/httpx/authlib deps | https://pypi.org/pypi/mcp-use/json | 2026-11-26 |
| 16 | mcp-use stars/push/TS heritage pitch | https://api.github.com/repos/mcp-use/mcp-use · https://github.com/mcp-use/mcp-use/blob/main/README.md | 2026-11-26 |
| 17 | mcp-agent 0.2.6 (2025-12-05), `mcp>=1.20.0`; stars 8,596; push 2026-01-25; Temporal/durable | https://pypi.org/pypi/mcp-agent/json · https://api.github.com/repos/lastmile-ai/mcp-agent · https://github.com/lastmile-ai/mcp-agent/blob/main/README.md | 2026-11-26 |
| 18 | PydanticAI 2.75.0 (2026-11-25) `mcp` extra → `fastmcp-slim[client]>=3.3.0,<5`; 1.60.0 → `mcp<2.0,>=1.25`; 2.0.0 (2026-06-23) → `fastmcp-slim[client]>=3.3.0` | https://pypi.org/pypi/pydantic-ai-slim/json · /1.60.0/json · /2.0.0/json · /2.20.0/json | 2026-11-26 |
| 19 | smolagents 1.26.0 (2026-05-29), `mcp` extra = unpinned `mcp` + `mcpadapt>=0.1.13` | https://pypi.org/pypi/smolagents/json | 2026-11-26 |
| 20 | fastapi-mcp 0.4.0 (2025-07-28), `mcp>=1.12.0`, push 2025-11-24, 12,031 stars | https://pypi.org/pypi/fastapi-mcp/json · https://api.github.com/repos/tadata-org/fastapi_mcp | 2026-11-26 |
| 21 | django-mcp-server 0.5.7 (2025-10-10), `mcp>=1.8.0`, 391 stars, push 2026-03-10 | https://pypi.org/pypi/django-mcp-server/json · https://api.github.com/repos/gts360/django-mcp-server | 2026-11-26 |
| 22 | litestar-mcp 0.20.2 (2026-11-23), no `mcp` dep, `httpx2>=2.13.1`, `litestar>=2.23.0`, `a2a` extra | https://pypi.org/pypi/litestar-mcp/json · https://api.github.com/repos/cofin/litestar-mcp | 2026-11-26 |
| 23 | mcpadapt 0.1.20 (2025-10-24), `mcp[ws]>=1.10.1`, 425 stars, push 2025-10-24 | https://pypi.org/pypi/mcpadapt/json · https://api.github.com/repos/grll/mcpadapt | 2026-11-26 |
| 24 | lauren 1.12.0 released 2026-11-15 | https://pypi.org/pypi/lauren/json | 2026-11-26 |
| 25 | lauren-mcp deps `lauren>=1.7.0`, `anyio>=4.0`, py>=3.11 | `pyproject.toml` in this repository | 2026-11-26 |
| 26 | Official SDK stars/licence/activity (24,980 · MIT · push 2026-11-17) | https://api.github.com/repos/modelcontextprotocol/python-sdk | 2026-11-26 |
