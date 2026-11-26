# Cross-Language MCP SDK Landscape — November 2026

> **Retrieval date for every claim below: 2026-11-26.**
> Scope: the 10 official MCP SDKs (TypeScript, Python, Java, Kotlin, C#, Go, Rust, Ruby, Swift, PHP) plus four
> notable community ecosystems (Elixir, Dart, Zig, C++).
> Purpose: (a) establish what other-language SDKs ship that `lauren-mcp` does not, and (b) separate
> ecosystem-standard features from one-off features.
> Research artifact for `prds/2026-11-landscape/`. Not a public doc.

---

## 0. TL;DR

1. **The ecosystem has split into two protocol eras and every Tier-1 SDK now ships both.** A `2026-07-28` revision
   exists next to the `2024-10-07 … 2025-11-25` "handshake" family. SDKs serve the legacy `initialize` handshake
   *and* the new stateless per-request envelope, negotiated with `server/discover`. TypeScript names these eras
   `legacy` / `modern` (`@modelcontextprotocol/server` 2.4.0, `docs/protocol-versions.md`).
2. **`lauren-mcp` is single-era and pinned to the old family.** `src/lauren_mcp/_mcp_version.py` declares
   `LATEST = "2025-11-25"` and `SUPPORTED = {2024-11-05, 2025-03-26, 2025-06-18, 2025-11-25}`. It contains **zero**
   occurrences of `2026-07-28`, `server/discover`, `subscriptions/listen`, `resultType`, `ttlMs`, `cacheScope`,
   `tasks/get`, or `input_required`/MRTR.
3. **The official docs now rank SDKs in tiers.** Tier 1 = TypeScript, Python, C#, Go, Rust, Ruby. Tier 2 = Java.
   Tier 3 = Swift, PHP, Kotlin. Tier is a *support-commitment* contract (100% / 80% / no-minimum conformance pass
   rate, "new protocol features before spec release" / "within 6 months" / "no commitment"), not popularity.
4. **A cross-language conformance suite is the new gate.** `modelcontextprotocol/conformance`
   (`npx @modelcontextprotocol/conformance` 0.1.16) starts a reference peer and drives a real SDK binary through
   scenarios. Go, Java, Kotlin, Ruby and Rust all vendor a `conformance/` directory; Swift vendors
   `conformance-baseline.yml`. Python, TypeScript, C# and PHP do not vendor it.
5. **"Extensions" is now a first-class protocol concept.** The `2026-07-28` revision adds an `extensions` field to
   `ClientCapabilities`/`ServerCapabilities`, and the spec ships official extensions: `apps`, `auth`, `events`,
   `skills`, `tasks`. C# is the only SDK that publishes extensions as separate NuGet packages
   (`ModelContextProtocol.Extensions.Apps`, `.Skills`, `.Tasks`).
6. **Rust (`rmcp` 3.12.0, released today) and C# (`2.4.0`) are the fastest-moving; Swift is 6+ months stale** — its
   last release is `0.12.1` on 2026-05-07 and its own `AGENTS.md` says the newest revision it implements is
   `2025-11-25`.
7. **Server framework integration is a per-language table stake**, not an SDK feature: ASP.NET Core for C#,
   Starlette/FastAPI-style ASGI for Python, Ktor for Kotlin, tower/axum for Rust, express/fastify/hono adapters for
   TypeScript, Rack/Metal for Ruby. Java delegates to Spring AI; its own repo has no Spring module.
8. **Everyone agrees on the boring parts**: stdio + SSE + Streamable HTTP in all 10, tools/resources/prompts,
   sampling, elicitation, completions, progress, cancellation, OAuth 2.1 + protected-resource metadata.
9. **Tasks are the clearest "standard feature with uneven adoption": 6 of 10 SDKs have `tasks/*`** (TypeScript,
   Python, C#, Rust solid; Java and Kotlin partial), while Go, Ruby, Swift and PHP do not. `lauren-mcp` does not
   either.
10. **What only one SDK has is mostly packaging/tooling, not protocol**: TS's `codemod` (1.x→2.x migration) and
    `middleware` packages, C#'s Roslyn `Analyzers`, Go's standalone `oauthex` module, Kotlin's real WebSocket
    *server* transport, Python's `FastMCP` + Skills extension + OTel module, Rust's `rmcp-macros` proc macros,
    PHP's `#[McpTool]` attributes.

---

## 1. Method & evidence quality

Three independent sources were used, all hit live on 2026-11-26:

1. **Package registries** for the "what users actually install" version: npm dist-tags, PyPI JSON, Maven Central
   `maven-metadata.xml`, NuGet registration index, Go module proxy, crates.io, RubyGems, Packagist, Hex, pub.dev.
2. **GitHub REST API** for releases, `published_at`, stars, and `pushed_at` (tags and release dates diverge —
   e.g. Go's `v1.8.0` tag is 2026-09-04 but the release is 2026-09-14).
3. **Source trees**: `main` tarballs of all 10 official repos downloaded and grepped locally. Feature-presence
   columns in this document are **file-hit counts** for a literal token (e.g. how many files mention
   `subscriptions/listen`). They are a *breadth proxy*, not a correctness proof: a count of 0 is strong evidence
   of absence; a large count is strong evidence of presence; 2–5 hits is "partial / type-only / test-only" and is
   called out as such.

Spec-side facts come from `modelcontextprotocol/modelcontextprotocol` (`docs/specification/2026-07-28/`,
`docs/extensions/`, `docs/community/sdk-tiers.md`, `docs/community/feature-lifecycle.md`) fetched as raw markdown
via the published `.md` endpoints.

Known limits: no SDK was executed; conformance *pass rates* are not published per SDK in a single scrapeable
artifact, so tier membership is the reported proxy. Community SDKs were checked for protocol-version tokens via
GitHub code search rather than full tarball grep.

---

## 2. Official SDKs — snapshot

Registry coordinates are the real install target; "repo tag" is the release that corresponds to it.

| # | SDK | Install coordinate | Latest stable | Published | Repo tag | Tier | Stars | Language floor |
|---|---|---|---:|---|---|---:|---:|---|
| 1 | TypeScript | `@modelcontextprotocol/sdk` (dist-tag `latest` = **1.32.2**) | 1.32.2 | 2026-10-23 | `1.32.2` | 1 | 13,824 | Node ≥ 20 |
| 1b | TypeScript (2.x) | `@modelcontextprotocol/{core,server,client,node,…}` | **2.4.0** | 2026-10-23 | `v2.4.0` | 1 | — | Node ≥ 20 |
| 2 | Python | `mcp` (PyPI) | **2.3.0** | 2026-10-02 | `v2.3.0` | 1 | 24,980 | Python ≥ 3.10 |
| 3 | Java | `io.modelcontextprotocol.sdk:mcp` | **2.2.0** | 2026-11-16 | `v2.2.0` | 2 | 3,778 | Java 17 (`maven.compiler.release`) |
| 4 | Kotlin | `io.modelcontextprotocol:kotlin-sdk` | **0.16.0** | 2026-10-27 | `0.16.0` | 3 | 1,492 | Kotlin/JVM + KMP |
| 5 | C# | `ModelContextProtocol` (NuGet) | **2.4.0** | 2026-11-07 | `v2.4.0` | 1 | 4,656 | `net10.0;net9.0;net8.0;netstandard2.0` |
| 6 | Go | `github.com/modelcontextprotocol/go-sdk` | **v1.8.0** (v1.9.0-pre.1 on 2026-11-17) | 2026-09-14 | `v1.8.0` | 1 | 5,396 | `go 1.26.0` (go.mod) |
| 7 | Rust | `rmcp` (crates.io) | **3.12.0** | 2026-11-26 | `rmcp-v3.12.0` | 1 | 4,148 | `rust-version = 1.88` |
| 8 | Ruby | `mcp` (RubyGems) | **1.11.0** | 2026-11-19 | `v1.11.0` | 1 | 957 | `required_ruby_version >= 2.7.0` |
| 9 | Swift | SPM `modelcontextprotocol/swift-sdk` | **0.12.1** | 2026-05-07 | `0.12.1` | 3 | 1,585 | swift-tools-version 6.1 |
| 10 | PHP | `mcp/sdk` (Packagist) | **0.10.0** (pre-1.0) | 2026-11-10 | `v0.10.0` | 3 | 1,684 | `"php": "^8.2"` |

Structural notes that matter for a Python-side reader:

* **TypeScript is two products at once.** `1.32.2` is still the `latest` dist-tag on `@modelcontextprotocol/sdk`;
  `2.4.0` ships as a *package split* (`core`, `core-internal`, `server`, `server-legacy`, `client`, `middleware`,
  `codemod`, plus express/fastify/hono adapters). `server-legacy` exists precisely to keep old-era servers running.
* **Python 2.x split its wire types out** into a separate `mcp-types` package: `src/mcp` (runtime) +
  `src/mcp-types/mcp_types/version.py` (protocol registry).
* **Java publishes a module family**: `mcp`, `mcp-core`, `mcp-bom`, `mcp-json-jackson2`, `mcp-json-jackson3`,
  `mcp-test`, `conformance-tests`. The Jackson 2/3 split is a Java-only concern.
* **Kotlin and PHP are still 0.x**, and Kotlin is Tier 3 despite being more modern than Java in one respect
  (WebSocket server transport, see §6).
* **Go tags faster than it releases**: `v1.9.0-pre.1` (2026-11-17) is published but `@latest` still resolves to
  `v1.8.0`.

---

## 3. Official SDK profiles

Each profile lists: era status, transports, headline differentiators, and anything it has that nobody else has
(cross-referenced with §6).

### 3.1 TypeScript — 2.4.0 (Tier 1)
* **Dual-era by design.** `packages/core-internal/src/wire/rev2026-07-28` and `rev2025-11-25` are *separate codecs*;
  a server picks one per connection. `docs/protocol-versions.md` defines era = behavior family, not version string,
  with `mode: 'legacy' | 'auto' | { pin: '2026-07-28' }`.
* `LATEST_PROTOCOL_VERSION` is still `'2025-11-25'` and `SUPPORTED_PROTOCOL_VERSIONS` is
  `['2025-11-25', '2025-06-18', '2025-03-26', '2024-11-05', '2024-10-07']` (`DEFAULT_NEGOTIATED_PROTOCOL_VERSION`
  is `'2025-03-26'`) — i.e. **2.x ships the 2026 wire while advertising the 2025 handshake as the naive default.**
  The 2026 era is opt-in via `versionNegotiation.mode`.
* Modern server entry is `createMcpHandler` (`legacy: 'stateless'` also serves 2025); stdio is `serveStdio(factory)`
  from `@modelcontextprotocol/server/stdio`, one factory per connection.
* Tool surface: zod schema driven; `listenRouter.ts` implements `subscriptions/listen` with per-connection
  multiplexing; `legacyInputRequiredShim` upgrades old-era clients to MRTR.
* Unique: `codemod` package (automated 1.x→2.x migration), `middleware` package, spec-type generation scripts
  (`scripts/fetch-spec-types.ts` / `fetch-spec-examples.ts` pull the JSON schema and examples from the spec repo).
* File-hit evidence: `2026-07-28` 296 files, `server/discover` 88, `subscriptions/listen` 71, `resultType` 112,
  `ttlMs` 73, `cacheScope` 75, `input_required` 59, `tasks/get` 25.

### 3.2 Python — 2.3.0 (Tier 1)
* **Dual-era, with an explicit registry**: `HANDSHAKE_PROTOCOL_VERSIONS = (2024-11-05, 2025-03-26, 2025-06-18,
  2025-11-25)`, `MODERN_PROTOCOL_VERSIONS = ("2026-07-28",)` — "revisions that use the stateless per-request
  envelope". `KNOWN_PROTOCOL_VERSIONS` is the union.
* Layout shows the era split plainly: `mcp/server/lowlevel`, `mcp/server/mcpserver`, `mcp/server/fastmcp.py`,
  `mcp/server/apps.py`, `mcp/server/extension.py`, `mcp/server/caching.py`, `mcp/server/_streamable_http_modern.py`;
  client side has `_probe.py` (discovery), `_input_required.py` (MRTR), `session_group.py`, `extensions/`.
* Highest raw breadth of any SDK: `2026-07-28` 452 files, `server/discover` 135, `subscriptions/listen` 197,
  `input_required` 59, MRTR mentions 241.
* Unique: `FastMCP` convenience server (single-file servers), a **Skills extension** implementation
  (`mcp/shared/skills.py`, "SEP-2640 conformance checks for the Skills extension"), and an OpenTelemetry module
  (`_otel.py` present in both `server/` and `client/`).
* Client-ID-Metadata (CIMD) handling is the most complete here (33 files).

### 3.3 Java — 2.2.0 (Tier 2)
* Single-era-first but modern-capable: `2026-07-28` 38 files, `server/discover` 17, `subscriptions/listen` 3,
  `resultType` 21, `input_required` 10, `tasks/get` 2.
* **Annotation-free core API** — no `@Tool`/`@McpTool` in the repo; tool registration is builder/lambda based.
  Annotation-driven ergonomics live in Spring AI's MCP layer, *not* here.
* Ships `mcp-test` (test harness) and a real `conformance-tests/` module wired into Maven.
* Jackson 2 vs Jackson 3 serializers are first-class alternates (`mcp-json-jackson2`, `mcp-json-jackson3`).
* Tier 2 (not 1) despite being Java: the tier contract is conformance pass rate + feature timelines, and Java is
  visibly behind Rust/C# on `subscriptions/listen` breadth (3 files vs 17).

### 3.4 Kotlin — 0.16.0 (Tier 3)
* Pre-1.0 (`0.16.0`), KMP (jvm/js/native) with `kotlin-sdk-core`, `kotlin-sdk-client`, `kotlin-sdk-server`.
* **Weakest modern support among non-Swift SDKs**: `2026-07-28` in only 5 files (a `request.kt` comment, a
  `DiscoveryTest.kt`, `README.md`, `SKILL.md`), `subscriptions/listen` **absent**.
* What it does have, uniquely: a real **WebSocket server transport** (`WebSocketMcpServerTransport`) usable from
  Ktor — no other official SDK ships WS server-side.
* Has a `conformance-test/` directory (Gradle), and 4 WebSocket-related transport classes.

### 3.5 C# — 2.4.0 (Tier 1)
* The most "packaged" SDK: 7 projects — `ModelContextProtocol`, `.Core`, `.AspNetCore`, `.Analyzers`,
  `.Extensions.Apps`, `.Extensions.Skills`, `.Extensions.Tasks`.
* Strongest modern coverage after Python: `2026-07-28` 117 files, `server/discover` 35, `subscriptions/listen` 17,
  `resultType` 29, `ttlMs` 35, `cacheScope` 31, `input_required` 17, MRTR mentions 52, `tasks/get` 18.
* Attribute-based registration (`[McpServerTool]`, `[McpServerToolType]`, 98 references) **plus a Roslyn analyzer
  package** — compile-time diagnostics for MCP usage. No other SDK ships analyzers.
* Unique: extensions are *separate NuGet packages* (Apps/Skills/Tasks), which is the cleanest model for
  protocol-extension distribution found in any SDK.

### 3.6 Go — v1.8.0 (Tier 1)
* Idiomatic split: `mcp/` (public), `jsonrpc/`, `auth/`, `oauthex/`, `internal/`, `conformance/`, `examples/`,
  `docs/`, `design/`.
* Modern coverage is mid-pack: `2026-07-28` 45 files, `server/discover` 19, `subscriptions/listen` 11,
  `resultType` 10, `input_required` 5. **No tasks** (`tasks/get` = 0) — the only Tier-1 SDK without them.
* Generic `AddTool` registration (`mcp.AddTool(srv, &mcp.Tool{...}, handler)`) — no reflection, no tags, no macros.
* Unique: **`oauthex` as a standalone, importable OAuth extension module** rather than auth buried in the SDK.
* Vendors `conformance/` and runs the suite in CI.

### 3.7 Rust — `rmcp` 3.12.0 (Tier 1)
* Workspace: `crates/rmcp` + `crates/rmcp-macros`. Released *today* (2026-11-26T14:58Z) — fastest cadence measured.
* Modern coverage: `2026-07-28` 56 files, `server/discover` 19, `subscriptions/listen` 14, `tasks/get` 17,
  `input_required` 15, MRTR mentions 18.
* Unique: **proc-macro tool registration** (`#[tool]`, `#[tool_router]`, `#[tool_handler]` — 60 occurrences), and
  deep tower integration (`transport/streamable_http_server/tower.rs`), making it the only SDK that is a first-class
  axum/tower citizen.
* Has `conformance/`, `client-metadata.json`, `release-plz.toml` (automated semantic releases).

### 3.8 Ruby — 1.11.0 (Tier 1)
* Smallest codebase in the ecosystem (`lib/mcp`, `lib/json_rpc_handler.rb`) yet **Tier 1**: it vendors
  `conformance/` and passes the suite at ≥100%.
* Modern coverage is surprisingly strong for its size: `2026-07-28` 72 files, `server/discover` 40,
  `subscriptions/listen` 19, `resultType` 18, CIMD 9. **No tasks** (`tasks/get` = 0).
* DSL-style registration (`tool`, `resource`, `prompt` blocks). No macros, no attributes.
* Evidence that tier ≈ discipline, not size: 957 stars, Tier 1.

### 3.9 Swift — 0.12.1 (Tier 3)
* **The laggard.** Last release 2026-05-07. `AGENTS.md` states the newest revision implemented is `2025-11-25`;
  `2026-07-28` appears in exactly one file (`AGENTS.md`, as a pointer to upstream spec work).
* Zero occurrences of `server/discover`, `subscriptions/listen`, `resultType`, `ttlMs`, `cacheScope`, `tasks/get`,
  `input_required`. This is a pure 2025-era SDK.
* Has `conformance-baseline.yml` — a *pinned* baseline rather than a live conformance run, consistent with Tier 3.
* Transports: stdio, SSE, Streamable HTTP (low file counts: 6 / 42 / 5 — a thin, docking-style surface).
* No Swift macros for tools; registration is closure/`CallTool` based.

### 3.10 PHP — 0.10.0 (Tier 3)
* Pre-1.0 but **more modern than its tier suggests**: `2026-07-28` 55 files, `server/discover` 14,
  `subscriptions/listen` 10, `resultType` 9, CIMD 0 (the only SDK with no CIMD handling at all).
* **Attribute-based** registration: `#[McpTool]` (PHP 8 attributes). `tasks/get` = 1 (type-only, not a working
  surface) — treat tasks as absent.
* Ships UI/apps support (`UiResourceCsp.php`, 8 files referencing MCP Apps, 2 `ui://` hits) — PHP punches above its
  weight on the Apps extension.
* No vendored conformance directory.

---

## 4. Community SDKs

| Ecosystem | Package | Latest | Published | Repo (stars) | 2026-07-28 token hits | Read |
|---|---|---:|---|---|---:|---|
| Elixir | `ex_mcp` (Hex) | **1.8.1** | 2026-10-31 | `trust-arbor/arbor_mcp` (33) | 204 | Most active non-official SDK measured; MCP **and** ACP |
| Elixir | `anubis_mcp` (Hex) | **2.2.0** | 2026-10-19 | `zoedsoupe/anubis-mcp` (184) | 41 | Popular, mid-modern |
| Elixir | `hermes_mcp` (Hex) | 0.14.1 | **2025-08-14** | `cloudwalk/hermes-mcp` → **404** | n/a | **Stalled ~15 months**, repo gone |
| Dart | `mcp_dart` (pub.dev) | **2.4.4** | 2026-11-16 | `leehack/mcp_dart` (116) | 113 | Most modern community SDK; client+server+host |
| Dart | `dart_mcp` / `dart_mcp_server` (pub.dev) | 0.5.2 / **1.2.2** | 2026-06-29 / 2026-10-27 | `dart-lang/ai` (302) | 52 | Dart-team-owned, **not** an official MCP SDK |
| Zig | `mcp.zig` | — (no registry) | 2026-10-31 | `muhammad-fiaz/mcp.zig` (43) | ~41 | Active hobby-grade; also `blue-blaze/mcp-zig-sdk` (3★), `justrach/mcp-zig` (17★) |
| C++ | header-only | — (no registry) | 2026-10-21 | `hkr04/cpp-mcp` (349) | **0** | Most-used C++ SDK, **2025-era only**, no 2026 support |

Takeaways:

* **Elixir has fragmented rather than standardised**: three packages, one dead. `ex_mcp` renamed/pivoted to
  `arbor_mcp` and is the only community SDK that rivals Tier-1 SDKs on 2026-era breadth (204 token hits).
* **Dart is the "unofficial official"**: Google's own `dart-lang/ai` monorepo ships `dart_mcp`, but Dart is absent
  from the official SDK list and tiers, while the community `mcp_dart` already tracks `2.4.x`.
* **C++ and Zig are firmly 2025-era** (C++: zero 2026 tokens). If cross-language reach matters, C++ support means
  "can talk to old-era servers", nothing more.
* No community SDK measures up to Tier-1 conformance practice; none vendors the conformance suite.

---

## 5. Feature matrix — what the ecosystem actually ships

Legend: **✓** present and broad · **~** present but partial/type-only/test-only · **·** absent
Counts in `ERA`-block are file-hit counts from the `main` tarball on 2026-11-26.

| Capability | TS | Py | Java | Kt | C# | Go | Rust | Ruby | Swift | PHP |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| stdio transport | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| SSE (legacy HTTP) transport | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Streamable HTTP transport | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| WebSocket **server** transport | · | · | · | **✓** | · | · | ~ | · | · | · |
| Server SDK | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Client SDK | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Sampling (server→client) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ~ | ✓ |
| Elicitation | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ~ | ✓ |
| Completions | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Structured output (`outputSchema`) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ~ | ✓ |
| OAuth 2.1 / PRM | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| CIMD (client-id metadata doc) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | **·** |
| **Tasks** | ✓ | ✓ | ~ | ~ | ✓ | **·** | ✓ | **·** | **·** | **·** |
| **MRTR** (`input_required`) | ✓ | ✓ | ✓ | ~ | ✓ | ✓ | ✓ | ✓ | **·** | ~ |
| **`server/discover`** | ✓ | ✓ | ✓ | ~ | ✓ | ✓ | ✓ | ✓ | **·** | ✓ |
| **`subscriptions/listen`** | ✓ | ✓ | ~ | **·** | ✓ | ✓ | ✓ | ✓ | **·** | ✓ |
| **`resultType`/`ttlMs`/`cacheScope`** | ✓ | ✓ | ✓ | ~ | ✓ | ✓ | ✓ | ✓ | **·** | ~ |
| Extensions mechanism | ✓ | ✓ | ~ | ~ | **✓** | ~ | ✓ | ~ | **·** | ~ |
| MCP Apps (`ui://`) | ✓ | ✓ | ~ | ~ | ✓ | **·** | ~ | ✓ | · | ✓ |
| Skills extension | ~ | **✓** | · | ~ | ✓ | **·** | ~ | ~ | · | · |
| Vendored conformance suite | · | · | ✓ | ✓ | · | ✓ | ✓ | ✓ | ~ (baseline) | · |
| OpenTelemetry module | ~ | **✓** | · | · | ~ | · | ~ | · | · | · |
| Codegen / analyzers / codemod | **✓** | · | · | · | ✓ | · | ✓ | · | · | · |
| Macro/attribute tool registration | · | decorators | · | · | **✓** | generics | **✓** | DSL | · | **✓** |
| Vendored spec JSON schema | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ~ | ✓ |

Reading the matrix:

* **The left half (transports, sampling, elicitation, OAuth, structured output) is settled.** There is no
  differentiation left there; a new SDK that lacks any of these is simply non-conforming.
* **The right/centre columns (tasks, MRTR, `server/discover`, `subscriptions/listen`, `resultType`) are the live
  frontier.** They are the `2026-07-28` era. Swift is 0-for-5 on them; Kotlin and PHP are partial; Go lacks tasks.
* **`lauren-mcp` sits in "left half only"** — it has the settled columns and none of the frontier ones.

---

## 6. Features present in only one SDK

These are genuine singletons in the official-10, verified by absence in the other nine trees.

| Feature | Only in | Why it exists | Portable? |
|---|---|---|---|
| `codemod` package (automated 1.x→2.x source migration) | **TS** | 2.x was a breaking package split; migrations are mandatory | No — Python 2.x also broke, and `lauren-mcp` would face the same on a 2.0 |
| `middleware` package (composable request middleware) | **TS** | Express-style ergonomics | Partially — a WSGI/ASGI-middleware analogue exists in lauren's domain already |
| Roslyn `Analyzers` package (compile-time MCP diagnostics) | **C#** | Catch invalid `[McpServerTool]` usage at build time | Yes in spirit: ruff/mypy plugin or `pytest` fixture equivalents |
| Extensions as separate distributable packages (`.Extensions.Apps/.Skills/.Tasks`) | **C#** | Let extension support version independently of core | **Yes — this is the most copyable idea in the survey** |
| Standalone `oauthex` module | **Go** | Auth usable outside the SDK | Yes: `lauren_mcp.auth` as an importable extra |
| WebSocket **server** transport | **Kotlin** | Ktor-native WS | Already relevant here: `lauren-mcp` has a WS *client* (`_client/_ws.py`) but no WS server |
| `FastMCP` in-tree single-file server | **Python** | Lowest-friction server authoring | Not applicable (lauren already has a binding layer) |
| Skills extension implementation w/ SEP-2640 conformance checks | **Python** | Official extension, early adopter | Spec-level, not language-level |
| `#[tool]`/`#[tool_router]`/`#[tool_handler]` proc macros | **Rust** | Zero-boilerplate registration | Python analogue = decorators (already standard here) |
| `#[McpTool]` PHP attributes | **PHP** | Idiomatic PHP 8 | Analogous to C# attributes |
| `conformance-baseline.yml` (pinned rather than live conformance) | **Swift** | Documents a *frozen* support level | Anti-pattern worth naming |
| Jackson-2 **and** Jackson-3 serializer modules | **Java** | JVM dependency matrix | Not applicable |
| `release-plz.toml` / automated semantic release | **Rust** | Release discipline | Process, not feature |

### 6.1 Honourable mentions: features in only *two* SDKs

* **OpenTelemetry trace propagation module**: Python (`_otel.py`, both sides) and partial in TS/C#/Rust. The
  `2026-07-28` spec now documents `traceparent`/`tracestate` propagation in `_meta`, so this is on its way to being
  standard.
* **MCP Apps (`ui://` resources + CSP)**: C# (23 hits), Python (69). Everyone else is ~ or ·.
* **In-memory / test transports**: Python (`client/_memory.py`), TS, Go — the rest rely on process spawning.

---

## 7. Dual-era readiness (`2026-07-28`) — the decisive table

`legacy era` = `2024-10-07 … 2025-11-25` (opening `initialize` handshake, sessions, `Mcp-Session-Id`).
`modern era` = `2026-07-28` (stateless per-request envelope: `_meta.io.modelcontextprotocol/protocolVersion`,
`clientInfo`, `clientCapabilities`; `server/discover` instead of `initialize`; `resultType`, `ttlMs`, `cacheScope`;
no sessions).

| SDK | Serves 2026-07-28? | `2026-07-28` | `server/discover` | `subscriptions/listen` | `resultType` | `input_required` | `tasks/get` | Era switch mechanism | Tier |
|---|---|--:|--:|--:|--:|--:|--:|---|---|
| TypeScript 2.4.0 | **Yes, dual** | 296 | 88 | 71 | 112 | 59 | 25 | `versionNegotiation.mode: legacy \| auto \| pin`, per-revision codecs | 1 |
| Python 2.3.0 | **Yes, dual** | 452 | 135 | 197 | 73 | 59 | 9 | `HANDSHAKE_*` / `MODERN_*` registries, `_probe.py` discovery | 1 |
| C# 2.4.0 | **Yes** | 117 | 35 | 17 | 29 | 17 | 18 | capability-driven; extension packages | 1 |
| Ruby 1.11.0 | **Yes** | 72 | 40 | 19 | 18 | 22 | 0 | conformance-verified | 1 |
| Rust 3.12.0 | **Yes** | 56 | 19 | 14 | 25 | 15 | 17 | conformance-verified | 1 |
| Go v1.8.0 | **Yes** | 45 | 19 | 11 | 10 | 5 | 0 | conformance-verified; `v1.9.0-pre.1` active | 1 |
| PHP 0.10.0 | **Yes (partial)** | 55 | 14 | 10 | 9 | 4 | 1 | no explicit switch; pre-1.0 | 3 |
| Java 2.2.0 | **Yes (partial)** | 38 | 17 | 3 | 21 | 10 | 2 | no explicit switch | 2 |
| Kotlin 0.16.0 | **Barely** | 5 | 4 | **0** | 4 | 2 | 3 | none; `SKILL.md`/`README` notes only | 3 |
| **Swift 0.12.1** | **No** | 1 | **0** | **0** | **0** | **0** | **0** | none; `AGENTS.md` says it targets `2025-11-25` | 3 |
| **`lauren-mcp` (this repo)** | **No** | **0** | **0** | **0** | **0** | **0** | **0** | none; `LATEST = "2025-11-25"` | n/a |

**What the `2026-07-28` revision actually mandates** (from `docs/specification/2026-07-28/changelog.mdx`, verified
for each token on 2026-11-26):

1. **Sessions are gone.** `Mcp-Session-Id` removed from Streamable HTTP; `tools/list`, `resources/list`,
   `prompts/list` no longer vary per connection.
2. **`server/discover`** replaces `initialize` for modern clients (`docs/specification/2026-07-28/server/discover.mdx`).
3. **Per-request `_meta` envelope**: `io.modelcontextprotocol/protocolVersion`, `clientInfo`, `clientCapabilities`,
   `serverInfo`, `logLevel` travel with every request instead of being negotiated once.
4. **`resultType`** on every result; **`ttlMs`** + **`cacheScope`** (`public`/`private`/`none`/`allServers`/
   `thisServer`) for cacheable list results; **`x-mcp-header`** for HTTP-level hints.
5. **`subscriptions/listen`** replaces the ad-hoc per-resource subscription notifications.
6. **MRTR** — `input_required` in a result, with the client resuming in a later request (no server→client
   request/response reversal needed).
7. **`extensions` field** on `ClientCapabilities` and `ServerCapabilities` — the extension system itself.
8. **OpenTelemetry** `traceparent`/`tracestate` propagation conventions.
9. JSON Schema 2020-12 semantics tightened (`$ref` composition-keyword resource bounds); `notifications/elicitation/
   complete` and `elicitationId` removed.

---

## 8. What is "ecosystem-standard"? (graded)

**Tier A — non-negotiable, every official SDK has it.** Not having it means you are not an MCP SDK.
stdio + SSE + Streamable HTTP; tools/resources/prompts; sampling; elicitation; completions; logging; progress;
cancellation; roots; `outputSchema`/`structuredContent`; OAuth 2.1 + Protected Resource Metadata; JSON-schema-driven
tool input validation; both client and server roles; a vendored copy of the spec schema.

**Tier B — standard by consensus, uneven execution (the migration surface of 2026).**
`server/discover` + per-request `_meta` envelope (8/10, Kotlin partial), `subscriptions/listen` (8/10),
`resultType`/`ttlMs`/`cacheScope` (8/10), MRTR `input_required` (9/10), tasks (6/10, two of them partial), CIMD (9/10),
extensions capability (most of the modern-era SDKs).

**Tier C — standard *process*, not code (and now the bar for being taken seriously).**
The **conformance suite** (`@modelcontextprotocol/conformance` 0.1.16, driven as
`npx @modelcontextprotocol/conformance client --command "<your binary>" --scenario <name>`), the **tier system**
(100% / 80% / no-minimum pass rate; feature timelines "before release" / "6 months" / "none"; issue triage in
2 business days / 1 month / none; critical bug fix in 7 days / 2 weeks / none), **feature lifecycle states**
(Active / Deprecated / Removed / Experimental) and **dual-era support windows**.

**Tier D — normalised packaging idioms per language.** ASP.NET Core / ASGI / Ktor / tower / express / Rack host
integration; attribute-or-macro registration where the language has them; a test harness module (`mcp-test`,
`in-memory` transports); source generation from the spec schema.

**Tier E — fringe / experimental.** WebSocket transports (only Kotlin, server-side), MCP Apps (`ui://`), Skills,
ACP interop (Elixir `ex_mcp`), analyzers/codemods, Jackson-2/3 duality.

Practical rule extracted from this survey: **a 2026-era SDK is "standard" if it passes the conformance suite and
ships `server/discover` + `_meta` envelope + `resultType` + `subscriptions/listen`.** Everything else is either
settled (Tier A) or optional (Tier E).

---

## 9. Gap analysis for `lauren-mcp` (what other-language SDKs ship that this repo does not)

Priority is set by "cost to add" × "interop risk if absent".

### P0 — correctness/interop blockers in a 2026 market

1. **No `2026-07-28` support.** `_mcp_version.py` caps at `2025-11-25`. Eight of ten official SDKs are already
   dual-era; a lauren-mcp server will fall back or fail against a modern-only client. Minimum viable: accept
   `2026-07-28` in negotiation, implement `server/discover`, accept and emit the per-request `_meta` envelope.
2. **No `server/discover`.** Cheapest single interop win; TS/Python treat it as the era selector.
3. **No `resultType` / `ttlMs` / `cacheScope`.** Modern clients will mis-handle or ignore lauren's list results;
   Python devotes 73/49/48 files to these three tokens.
4. **No MRTR (`input_required`).** Every other SDK except Swift has it (0 files here, 59 in Python, 52 in C#).
   This is the sanctioned replacement for lauren's current reverse-request elicitation/sampling flow.
5. **No `subscriptions/listen`.** lauren has `resources/subscribe` only — the removed-era mechanism.
6. **No conformance-suite integration.** No `conformance/` directory, no scenario runner. Ruby proves that a
   ~1-file-per-module library can be Tier 1 purely by passing the suite.

### P1 — standard features with real clients waiting

7. **Tasks** (`tasks/get|list|result|update`) — absent here; present in 6/10 official SDKs (TS, Python, C#, Rust
   fully; Java and Kotlin partially).
8. **Extensions capability field** (`capabilities.extensions`) and at least one extension, so third parties can
   opt in without core changes. Copy C#'s *separate distribution units* model — the single most portable idea found.
9. **CIMD / client-id metadata document** — present in 9/10 SDKs, 0 in PHP, 0 here.
10. **OpenTelemetry propagation** (`traceparent`/`tracestate` in `_meta`) — spec'd in 2026-07-28, implemented in
    Python (`_otel.py`); lauren has 2 files mentioning opentelemetry and 1 mentioning `traceparent`.

### P2 — packaging/ergonomics parity

11. **Spec-schema codegen.** TS (`scripts/fetch-spec-types.ts`), and 9/10 SDKs vendor the spec JSON schema. This
    is the cheapest way to stop hand-maintaining wire types.
12. **Importable `auth` extra** (Go's `oauthex` model; `lauren_mcp._client._oauth` currently ties OAuth to the
    client role).
13. **Client-side discovery probe** (Python `client/_probe.py`, TS `mode: 'auto'`) so lauren's client can talk to
    modern-only servers.
14. **A WebSocket *server* transport.** lauren ships `_client/_ws.py` (WS client) but no server counterpart; only
    Kotlin ships WS server-side, so this is a cheap differentiator rather than a catch-up item.
15. **Static analysis / lint hooks** for tool signatures (C#'s Analyzers analogue: a ruff rule set or mypy plugin).

### Explicitly *not* gaps (already at parity)

stdio/SSE/Streamable HTTP; elicitation; sampling; completions; logging; resource subscribe; roots;
`outputSchema`/`structuredContent`; OAuth client flow; in-memory test transports.

---

## Sources

All URLs retrieved **2026-11-26**. "Registry API" rows were queried directly (npm/PyPI/Maven/NuGet/Go proxy/
crates.io/RubyGems/Packagist/Hex/pub.dev).

| # | Source | URL | What it established |
|---|---|---|---|
| 1 | MCP docs — SDKs & tiers | https://modelcontextprotocol.io/docs/2026-07-28/sdk.md | The 10 official SDKs + Tier 1/2/3 assignment (`.md` endpoint; canonical page `/docs/sdk`) |
| 2 | MCP docs — SDK Tiering System | https://modelcontextprotocol.io/community/sdk-tiers.md | Tier requirements: conformance pass rate 100/80/none, feature timelines, triage SLAs |
| 3 | MCP docs — Feature lifecycle | https://modelcontextprotocol.io/community/feature-lifecycle.md | Active / Deprecated / Removed / Experimental states |
| 4 | MCP docs — Extensions overview | https://modelcontextprotocol.io/extensions/overview | Extensions as a protocol concept |
| 5 | Spec `2026-07-28` changelog | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/changelog.mdx | Sessions removed, `server/discover`, `_meta`, `resultType`, tasks, MRTR, OTel |
| 6 | Spec `2026-07-28` tree | https://github.com/modelcontextprotocol/modelcontextprotocol/tree/main/docs/specification/2026-07-28 | `server/discover.mdx`, `basic/transports`, `basic/versioning.mdx` |
| 7 | Conformance suite repo | https://github.com/modelcontextprotocol/conformance | Suite exists, `SDK_INTEGRATION.md`, pushed 2026-11-23 |
| 8 | Conformance suite README + npm | https://github.com/modelcontextprotocol/conformance/blob/main/README.md · `npm view @modelcontextprotocol/conformance` | Invocation: `npx @modelcontextprotocol/conformance client --command … --scenario …`; version 0.1.16 |
| 9 | TS SDK repo | https://github.com/modelcontextprotocol/typescript-sdk | `v2.4.0` (2026-10-23), package split, 13,824★ |
| 10 | TS SDK era doc | https://github.com/modelcontextprotocol/typescript-sdk/blob/main/docs/protocol-versions.md | `legacy`/`modern` eras, `mode: legacy\|auto\|pin`, `createMcpHandler`, `serveStdio(factory)` |
| 11 | npm registry | https://registry.npmjs.org/@modelcontextprotocol%2Fsdk (dist-tags) | `latest` = 1.32.2; `core`/`server`/`client`/`node` = 2.4.0 |
| 12 | Python SDK repo | https://github.com/modelcontextprotocol/python-sdk | `v2.3.0` (2026-10-02), 24,980★ |
| 13 | Python protocol registry | `src/mcp-types/mcp_types/version.py` in [12] | `HANDSHAKE_PROTOCOL_VERSIONS`, `MODERN_PROTOCOL_VERSIONS = ("2026-07-28",)` |
| 14 | PyPI | https://pypi.org/pypi/mcp/json | `mcp` 2.3.0, `requires_python >=3.10`, release timeline |
| 15 | Java SDK repo | https://github.com/modelcontextprotocol/java-sdk | `v2.2.0` (2026-11-16), modules incl. `mcp-bom`, `mcp-test`, `conformance-tests` |
| 16 | Maven Central metadata | https://repo1.maven.org/maven2/io/modelcontextprotocol/sdk/mcp/maven-metadata.xml | `release` 2.2.0, `lastUpdated` 20261113 |
| 17 | Kotlin SDK repo | https://github.com/modelcontextprotocol/kotlin-sdk | `0.16.0` (2026-10-27); `WebSocketMcpServerTransport` |
| 18 | Maven — Kotlin | https://repo1.maven.org/maven2/io/modelcontextprotocol/kotlin-sdk/maven-metadata.xml | `release` 0.16.0 |
| 19 | C# SDK repo | https://github.com/modelcontextprotocol/csharp-sdk | `v2.4.0`; `Extensions.Apps/.Skills/.Tasks`, `Analyzers`, `AspNetCore` |
| 20 | NuGet | https://api.nuget.org/v3/registration5-gz-semver2/modelcontextprotocol/index.json | `ModelContextProtocol` 2.4.0 published 2026-11-07 |
| 21 | Go SDK repo | https://github.com/modelcontextprotocol/go-sdk | `v1.8.0`, `oauthex/`, `conformance/` |
| 22 | Go module proxy | https://proxy.golang.org/github.com/modelcontextprotocol/go-sdk/@latest | `@latest` = v1.8.0 (2026-09-04 tag); list includes `v1.9.0-pre.1` |
| 23 | Rust SDK repo | https://github.com/modelcontextprotocol/rust-sdk | `rmcp-v3.12.0` (2026-11-26); `rmcp-macros`, tower transport |
| 24 | crates.io | https://crates.io/api/v1/crates/rmcp | `rmcp` max version 3.12.0 |
| 25 | Ruby SDK repo | https://github.com/modelcontextprotocol/ruby-sdk | `v1.11.0` (2026-11-19), `conformance/` |
| 26 | RubyGems | https://rubygems.org/api/v1/gems/mcp.json | `mcp` 1.11.0 |
| 27 | Swift SDK repo | https://github.com/modelcontextprotocol/swift-sdk | `0.12.1` (2026-05-07); `AGENTS.md` says newest implemented revision is `2025-11-25` |
| 28 | PHP SDK repo | https://github.com/modelcontextprotocol/php-sdk | `v0.10.0` (2026-11-10); `#[McpTool]` attributes |
| 29 | Packagist | https://repo.packagist.org/p2/mcp/sdk.json | `mcp/sdk` 0.10.0 |
| 30 | Hex — `ex_mcp` | https://hex.pm/api/packages/ex_mcp | 1.8.1, 2026-10-31; repo `trust-arbor/arbor_mcp` |
| 31 | Hex — `anubis_mcp` | https://hex.pm/api/packages/anubis_mcp | 2.2.0, 2026-10-19 |
| 32 | Hex — `hermes_mcp` | https://hex.pm/api/packages/hermes_mcp | 0.14.1, last published **2025-08-14**; declared repo 404s |
| 33 | pub.dev — `mcp_dart` | https://pub.dev/api/packages/mcp_dart | 2.4.4, 2026-11-16, repo `leehack/mcp_dart` |
| 34 | pub.dev — `dart_mcp` / `dart_mcp_server` | https://pub.dev/api/packages/dart_mcp · `/dart_mcp_server` | 0.5.2 (2026-06-29) / 1.2.2 (2026-10-27), repo `dart-lang/ai` |
| 35 | Zig community SDKs | https://github.com/muhammad-fiaz/mcp.zig · https://github.com/blue-blaze/mcp-zig-sdk · https://github.com/justrach/mcp-zig | 43★/3★/17★; latest pushes 2026-10-31 / 2026-08-14 / 2026-08-02 |
| 36 | C++ community SDK | https://github.com/hkr04/cpp-mcp | 349★, pushed 2026-10-21, **0** hits for `2026-07-28` |
| 37 | GitHub REST API | `repos/modelcontextprotocol/{sdk}/releases/latest`, `repos/{owner}/{repo}` | Every tag/date/star count in §2 and §4 |
| 38 | Source tarballs (all 10 official repos, `main`) | `https://codeload.github.com/modelcontextprotocol/<sdk>/tar.gz/refs/heads/main` | All feature-presence counts in §5–§7 |
| 39 | `lauren-mcp` (this repo) | `src/lauren_mcp/_mcp_version.py` | `LATEST = "2025-11-25"`, `SUPPORTED = {2024-11-05 … 2025-11-25}` — the baseline for §9 |

### Reproduce

```bash
# versions
npm view @modelcontextprotocol/sdk dist-tags
curl -s https://pypi.org/pypi/mcp/json | jq -r .info.version
curl -s https://repo1.maven.org/maven2/io/modelcontextprotocol/sdk/mcp/maven-metadata.xml | grep release
curl -s https://proxy.golang.org/github.com/modelcontextprotocol/go-sdk/@latest
curl -s -A research https://crates.io/api/v1/crates/rmcp | jq -r .crate.max_version
curl -s https://rubygems.org/api/v1/gems/mcp.json | jq -r .version
curl -s https://repo.packagist.org/p2/mcp/sdk.json | jq -r '.packages["mcp/sdk"][0].version'
gh api repos/modelcontextprotocol/swift-sdk/releases/latest --jq .tag_name

# era / feature presence (per SDK, from the tarball)
for t in 2026-07-28 server/discover subscriptions/listen resultType ttlMs cacheScope \
         input_required tasks/get; do
  printf '%-24s %s\n' "$t" "$(grep -rIl -F "$t" <sdk-dir> | wc -l)"
done
```
