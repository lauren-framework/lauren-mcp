# Versions Matrix — MCP Landscape as of 2026-11-26

**Status:** Draft for review
**Date:** 2026-11-26
**Companion:** [`EVIDENCE.md`](./EVIDENCE.md) — every cell here carries an `E-…` row ID there with its
URL and confidence code. This file is the *readable* view; EVIDENCE.md is the *auditable* one.
**Purpose:** one table per ecosystem layer, so a version claim can be checked without reading five
research files — and one final table that says exactly what `lauren-mcp` must change.

---

## 0. How to read this

* **"Published"** is the registry/release date, not the version label. MCP version labels are
  identifiers (`2024-11-05` was published 2025-01-17 — E-03), so the two are never conflated here.
* **"Era"** is the useful abstraction, not the version string:
  * **legacy era** = `2024-10-07` … `2025-11-25`: opening `initialize` handshake, sessions,
    `Mcp-Session-Id`, server-initiated sampling/elicitation/roots, HTTP GET push channel.
  * **modern era** = `2026-07-28`: stateless per-request `_meta` envelope, `server/discover`,
    `resultType`/`ttlMs`/`cacheScope`, `subscriptions/listen`, MRTR, no sessions.
* A cell of `—` means *not applicable*; a cell of `0` means *looked for, absent* (a negative result,
  logged in EVIDENCE §17).
* Everything is stamped **2026-11-26**. Nothing here is "latest by convention".

Refresh the whole document with the commands in EVIDENCE.md §20; the short version:

```bash
npm view @modelcontextprotocol/sdk dist-tags
curl -s https://pypi.org/pypi/mcp/json | jq -r .info.version
gh api repos/modelcontextprotocol/modelcontextprotocol/releases --jq '.[0] | "\(.tag_name) \(.published_at)"'
```

---

## 1. Protocol revisions

| Revision | Tag published (UTC) | Change character | Changelog | `lauren-mcp` declares | `lauren-mcp` conforms | Evidence |
|---|---|---|---|---|---|---|
| `2024-10-07` | 2024-11-06 | origin draft | none | ✗ | ✗ | E-01 |
| `2024-11-05` | **2025-01-17** (final tag 2025-03-26) | origin, stdio + HTTP+SSE only | **404 — does not exist** | ✓ (`STABLE`) | ✓ | E-03, E-04, E-06, E-07 |
| `2025-03-26` | 2025-03-26 | adds Streamable HTTP | ✓ | ✓ | ✓ | E-11 |
| `2025-06-18` | 2025-06-18 | additive: elicitation, structured output, OAuth hardening | ✓ | ✓ | **partial** — cancellation bug, no OAuth hardening | E-08, E-12, E-237 |
| `2025-11-25` | 2025-11-25 | additive: tasks, URL elicitation, OIDC, icons, JSON Schema 2020-12 | ✓ | ✓ (`LATEST`) | ✓ | E-13, E-225 |
| `2026-07-28` | 2026-07-28 | **breaking**: sessions, handshake, `ping`, `setLevel`, SSE resumability removed; MRTR replaces server-initiated requests | ✓ | ✗ | ✗ (**0** surface) | E-20…E-30, E-226, E-230…E-236 |
| next revision | — | not tagged | — | — | — | E-02, E-53 |

**Delta that matters:** `lauren-mcp` declares four revisions and conforms to roughly three and a
half. The half is `2025-06-18` cancellation (E-237/E-240). The missing whole is `2026-07-28`.

### 1.1 Revision-to-revision character

| Transition | Additive? | Removed anything? | Migration cost for `lauren-mcp` |
|---|---|---|---|
| `2024-11-05` → `2025-03-26` | yes | no | already done |
| `2025-03-26` → `2025-06-18` | yes | no | one bug (cancellation) |
| `2025-06-18` → `2025-11-25` | yes | no | already done |
| `2025-11-25` → `2026-07-28` | **no** | **yes — 7 mechanisms** | dual-era architecture (§7) |

---

## 2. `2026-07-28` mandatory surface — who has what

Presence counts are file hits in each SDK's `main` tree (E-80…E-90). Ranking only, not conformance.

| Capability | Required by spec | TS 2.4.0 | Py 2.3.0 | C# 2.4.0 | Rust 3.12.0 | Go 1.8.0 | Ruby 1.11.0 | Java 2.2.0 | PHP 0.10.0 | Kotlin 0.16.0 | Swift 0.12.1 | **lauren-mcp 1.0.0** |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| `2026-07-28` revision | — | 296 | 452 | 117 | 56 | 45 | 72 | 38 | 55 | 5 | 1 | **0** |
| `server/discover` | MUST | 88 | 135 | 35 | 19 | 19 | 40 | 17 | 14 | 4 | **0** | **0** |
| `subscriptions/listen` | MUST | 71 | 197 | 17 | 14 | 11 | 19 | 3 | 10 | **0** | **0** | **0** |
| `resultType` | MUST | 112 | 73 | 29 | 25 | 10 | 18 | 21 | 9 | 4 | **0** | **0** |
| `input_required` (MRTR) | MUST | 59 | 59 | 17 | 15 | 5 | 22 | 10 | 4 | 2 | **0** | **0** |
| `tasks/get` | extension | 25 | 9 | 18 | 17 | **0** | **0** | 2 | 1 | 3 | **0** | **0** |
| `ttlMs` + `cacheScope` | MUST for lists | high | high | med | med | med | med | med | low | low | **0** | **0** |
| Era switch mechanism | — | `mode: legacy\|auto\|pin` | `HANDSHAKE_*`/`MODERN_*` | capability-driven | conformance | conformance | conformance | none | none | none | none | **none** |

Sources: E-80…E-90; spec MUSTs at E-21, E-23, E-26, E-27.

---

## 3. Official SDKs

| # | Language | Coordinate | Latest stable | Published | Tier | Language floor | Era support | Evidence |
|---|---|---|---|---:|---|---|---|---|
| 1 | TypeScript (1.x) | `@modelcontextprotocol/sdk` (`latest`) | **1.32.2** | 2026-10-23 | 1 | Node ≥ 20 | legacy | E-60 |
| 1b | TypeScript (2.x) | `@modelcontextprotocol/{core,server,client,node,…}` | **2.4.0** | 2026-10-23 | 1 | Node ≥ 20 | **dual** | E-61, E-73, E-74 |
| 2 | Python | `mcp` (PyPI) | **2.3.0** | 2026-10-02 | 1 | ≥ 3.10 | **dual** | E-62, E-71, E-72 |
| 3 | Java | `io.modelcontextprotocol.sdk:mcp` | **2.2.0** | 2026-11-16 | 2 | Java 17 | partial | E-63, E-87 |
| 4 | Kotlin | `io.modelcontextprotocol:kotlin-sdk` | **0.16.0** | 2026-10-27 | 3 | Kotlin/JVM + KMP | barely | E-64, E-88 |
| 5 | C# | `ModelContextProtocol` (NuGet) | **2.4.0** | 2026-11-07 | 1 | `net10.0;net9.0;net8.0;netstandard2.0` | modern | E-65, E-82 |
| 6 | Go | `github.com/modelcontextprotocol/go-sdk` | **v1.8.0** (`v1.9.0-pre.1` 2026-11-17) | 2026-09-14 | 1 | Go 1.26.0 | modern | E-66, E-85 |
| 7 | Rust | `rmcp` (crates.io) | **3.12.0** | 2026-11-26 | 1 | rustc 1.88 | modern | E-67, E-84 |
| 8 | Ruby | `mcp` (RubyGems) | **1.11.0** | 2026-11-19 | 1 | Ruby ≥ 2.7 | modern | E-68, E-83 |
| 9 | Swift | SPM `modelcontextprotocol/swift-sdk` | **0.12.1** | 2026-05-07 | 3 | swift-tools 6.1 | **legacy only** | E-69, E-77, E-89 |
| 10 | PHP | `mcp/sdk` (Packagist) | **0.10.0** (pre-1.0) | 2026-11-10 | 3 | PHP ^8.2 | partial | E-70, E-86 |
| — | **Python (this repo)** | `lauren-mcp` (PyPI, VCS-versioned) | **1.0.0** | 2026-06-14 | — | ≥ 3.11 | **legacy only** | E-220, E-221 |

**Reading the tier column.** Tier 1 requires a 100 % conformance pass rate; Tier 2 80 %; Tier 3 none
(E-76). Nine of ten SDKs are published; Swift lags at `2025-11-25` and is the only official SDK in the
same position as `lauren-mcp` (E-77).

### 3.1 Conformance tooling

| Artifact | Version | Date | Use | Evidence |
|---|---|---|---|---|
| `@modelcontextprotocol/conformance` | **0.1.16** | repo pushed 2026-11-23 | `npx … client --command … --scenario …`; the instrument Tier 1 is measured with | E-75 |

**Actionable:** this is the cheapest way to *measure* `lauren-mcp` rather than argue about it. Any
conformance PRD should name a baseline score before and after.

---

## 4. Python ecosystem

| Project | Version | Published | Pins `mcp` how? | Era risk | Evidence |
|---|---|---|---|---:|---|
| `mcp` (official) | **2.3.0** | 2026-10-02 | — | dual | E-100 |
| `mcp` 1.x legacy line | **1.30.0** | 2026-09-07 | — | legacy | E-101 |
| `mcp-types` | **2.3.0** | 2026-10-02 | — | dual | E-71 |
| FastMCP | **4.2.6** | 2026-11-25 | `fastmcp-slim==4.2.6` | dual | E-102, E-104 |
| mcp-use | **1.7.1** | 2026-09-10 | `mcp<2.0.0,>=1.24.0` | **stranded on 1.x** | E-105 |
| mcp-agent | **0.2.6** | 2025-12-05 | `mcp>=1.20.0` (no upper bound) | **dormant since 2026-01** | E-106 |
| PydanticAI | **2.75.0** | 2026-11-25 | `fastmcp-slim[client]>=3.3.0,<5` (**no** direct dep) | dual | E-107 |
| smolagents | **1.26.0** | 2026-05-29 | unpinned `mcp` + `mcpadapt>=0.1.13` | **unpinned** | E-109 |
| fastapi-mcp | **0.4.0** | 2025-07-28 | `mcp>=1.12.0` | stale | E-110 |
| django-mcp-server | **0.5.7** | 2025-10-10 | `mcp>=1.8.0` | stale | E-111 |
| litestar-mcp | **0.20.2** | 2026-11-23 | **no `mcp` dependency** | era-agnostic | E-112 |
| mcpadapt | **0.1.20** | 2025-10-24 | `mcp[ws]>=1.10.1` | legacy | E-113 |
| `lauren` | **1.12.0** | 2026-11-15 | — | — | E-114 |

### 4.1 Dependency-risk table — what `lauren-mcp` must not break

| If `lauren-mcp` required… | Breaks | Because |
|---|---|---|
| `mcp>=2` | FastMCP 4.x users are fine; **mcp-use**, **mcp-agent**, **smolagents** users are not | mcp-use pins `<2.0.0` (E-105); mcp-agent pins `>=1.20.0` with no 2.x release (E-106); smolagents leaves it unpinned (E-109) |
| a `pydantic` hard dependency | FastMCP users fine; **litestar-mcp** users get a duplicate tree | litestar-mcp deliberately has no `mcp` dep (E-112) |
| nothing at all (status quo: `lauren` + `anyio`) | nobody | E-222 |

**Conclusion for the PRDs:** the two-dependency posture is a *competitive asset* in a Python
ecosystem where three of seven agent frameworks are pinned to a superseded SDK line. This is why the
dual-era PRD proposes an internal wire layer rather than adopting `mcp` 2.x.

---

## 5. Agent SDKs (MCP client side)

| SDK | Package | Version | MCP entry point | Evidence |
|---|---|---:|---|---|
| OpenAI Agents SDK | `openai-agents` | **0.26.0** | `MCPServerStdio`, `MCPServerSse`, `MCPServerStreamableHttp`, `MCPServerManager` | E-200 |
| LangChain adapters | `langchain-mcp-adapters` | **0.3.2** | `MultiServerMCPClient`, `.get_tools()`, `.session()` | E-201 |
| Google ADK | `google-adk` | **2.15.1** | `McpToolset`, `McpToolsetConfig` | E-202 |
| PydanticAI | `pydantic-ai-slim` | **2.75.0** | `MCPServerStdio/SSE/StreamableHTTP/HTTP` | E-203 |
| AWS Strands | `strands-agents` | **1.67.0** | `MCPClient`, `MCP_VERSIONS` | E-204 |
| MS Agent Framework | `agent-framework` | **1.26.0** | `MCPStreamableHTTPTool` | E-205 |
| Agno | `agno` | PyPI tip | `MCPTools`, `SSEClientParams`, `StreamableHTTPClientParams` | E-206 |
| Mastra (TS) | `@mastra/mcp` | **2.11.0** | MCP client/server | E-207 |

**Common denominator:** every one of these exposes **stdio + SSE + Streamable HTTP** as the three
transports. That is exactly the transport set `lauren-mcp` already has (E-241), which is why transport
work is *not* on the critical path. Nothing in this table demands `ws`.

---

## 6. Agent hosts

| Host | Config file | Top-level key | stdio | Streamable HTTP | OAuth | Resources | Prompts | Deferred loading | Evidence |
|---|---|---|---|---|---|---|---|---|---|
| Claude Desktop | `claude_desktop_config.json` | `mcpServers` | ✓ | via connectors | host-managed | ✓ | ✓ | host-managed | E-190 |
| Claude Code | `.mcp.json`, `~/.claude.json`, `claude mcp add` | `mcpServers` | ✓ | ✓ (+ `ws`) | ✓ | ✓ (`@server:uri`) | ✓ (`/mcp__srv__p`) | **default on** | E-191 |
| Cursor | `~/.cursor/mcp.json`, `.cursor/mcp.json` | `mcpServers` | ✓ | ✓ | ✓ | partial | partial | marketplace | E-192 |
| VS Code (Copilot) | `.vscode/mcp.json` | **`servers`** | ✓ | ✓ (`"type": "http"`) | ✓ | partial | partial | tool picker | E-193 |
| Devin (ex-Windsurf) | `.devin/mcp_config.json` | `mcpServers` | ✓ (`command`) | ✓ (`url`) | documented | not doc'd | not doc'd | n/a | E-194 |
| Zed | `settings.json` | **`context_servers`** | ✓ | ✓ | limited | **✗** | ✓ | n/a | E-195 |
| Cline | `~/.cline/data/settings/cline_mcp_settings.json` | `mcpServers` | ✓ | ✓ | ✓ | partial | partial | `autoApprove` | E-196 |
| Continue | `config.yaml` | `mcpServers` | ✓ | ✓ | ✓ | partial | partial | n/a | E-197 |
| ChatGPT / OpenAI plugins | hosted connector | — (server-side) | **✗** | **required** | ✓ | ✗ | ✗ | host-curated | E-198 |
| Gemini CLI | `settings.json` | `mcpServers` | ✓ | ✓ (`httpUrl`) | ✓ | ✓ | ✓ | `toolFilter` | E-199 |
| JetBrains AI Assistant | — | — | ? | ? | ? | ? | ? | ? | **U** (E-199b) |

### 6.1 Claude Code context budget — hard numbers to design against

| Limit | Value | Evidence |
|---|---|---|
| Instructions field | 4,096 chars | E-191b |
| Deferred tool description | 16,384 chars | E-191b |
| Output warning threshold | 10,000 tokens | E-191c |
| Default output cap | 25,000 tokens | E-191c |
| Overrides | `ENABLE_TOOL_SEARCH`, `CLAUDE_CODE_MAX_MCP_DESC*`, `MAX_MCP_OUTPUT_TOKENS` | E-191a, E-191b, E-191c |

**Implication:** a server with 300 tools and verbose descriptions is unusable in Claude Code unless
it either supports tool search/deferral or emits terse descriptions. This is the argument for the
"presentation layer" PRD, and it is a *host* constraint, not an MCP one.

---

## 7. Infrastructure

### 7.1 Registry and packaging

| Artifact | Version | Date | Scale / note | Evidence |
|---|---|---|---|---|
| Official Registry service | **1.8.16** | build 2026-11-23 | git `a21a32b` | E-120 |
| Registry records | — | 2026-11-26 | ≥ **20,000** | E-121 |
| `server.json` schema | **2025-12-11** | — | required `name`/`description`/`version`; `packages[]`, `remotes[]`, `isSecret` | E-123 |
| `mcp-publisher` auth methods | — | — | `dns`, `http`, `github`, `github-oidc`, `github-at`, `anonymous` | E-125 |
| Registry repo | `v1.8.16` | 2026-11-23 | 7,500★ | E-128 |
| Glama directory | — | 2026-11-26 | 131,130 servers | E-129 |
| mcp.so | — | 2026-11-26 | 20,915 servers | E-129 |

### 7.2 Gateways and proxies

| Artifact | Version | Date | Role | Evidence |
|---|---|---|---|---|
| Docker MCP Gateway | **v0.44.3** | — | gateway + `docker mcp` plugin; catalog = 327 entries, 244 Hub repos | E-140, E-141 |
| IBM ContextForge | **1.1.2** | 2026-11-25 | federation, REST↔MCP, stdio↔SSE, 40+ plugins | E-142 |
| Kong AI MCP Proxy | Kong **3.9.5** | 2026-11-19 | `ai-mcp-proxy`, `ai-mcp-oauth2` | E-143 |
| Agent Router (ex-Envoy AI GW) | **v1.3.0** | 2026-11-18 | aggregation, per-tool ACL, key injection, tool filtering; renamed 2026-09-09 | E-144 |
| supergateway | **4.3.0** | 2026-11-24 | stdio↔SSE↔HTTP one-liner | E-145 |
| `mcp-remote` | **0.17.1** | — | carries CVE-2025-6514 | E-146, E-168 |
| LiteLLM | **v1.111.0** | 2026-11-25 | proxy + MCP aggregation | E-147 |
| Vercel MCP Adapter | **v2.4.0** | 2026-11-12 | hosted adapter | E-148 |
| `mcp-proxy` (py) | **0.15.0** | 2026-11-09 | stdio/SSE proxy | E-151 |
| `mcpo` | **0.0.21** | 2026-11-25 | MCP → OpenAPI | E-152 |
| MCP Apps SDK | **v2.1.0** | 2026-11-10 | UI payload extension | E-153 |

### 7.3 Hosting platforms

| Platform | Version / status | Note | Evidence |
|---|---|---|---|
| Cloudflare (Workers + Agents SDK) | current guide | remote MCP hosting; repo 6,153★ | E-149 |
| Cloudflare OAuth provider | **1.4.0** | `workers-oauth-provider` | E-156 |
| Prefect Horizon / FastMCP Cloud | FastMCP **4.2.6** | managed FastMCP deployment | E-150 |
| AWS Bedrock AgentCore Gateway | — | gateway for agents/tools/models | E-154 |
| Azure API Center | — | MCP servers as API assets | E-155 |

### 7.4 Developer tooling

| Artifact | Version | Advisories | Note | Evidence |
|---|---|---:|---|---|
| `@modelcontextprotocol/inspector` | **2.16.0** | 2 | feature surface **not enumerated** — see U-01 | E-165, E-166 |

---

## 8. Observability and auth versions

| Item | Current value | Status | Evidence |
|---|---|---|---|
| OTel `mcp.*` attributes (old location) | `mcp-method-name`, `mcp-protocol-version`, `mcp-resource-uri`, `mcp-session-id` | **Deprecated / moved** | E-180 |
| OTel GenAI semconv repo | canonical location | live | E-181 |
| MCP span/metric reports | `mcp-client-span`, `mcp-server-span`, `mcp-client-operation-duration-metric` | published | E-182 |
| Trace context propagation | SEP-414, standardised in `2026-07-28` | required | E-183 |
| OAuth version baseline | OAuth **2.1** for HTTP transports | required | E-170 |
| Resource indicators | **RFC 8707** | required | E-171 |
| Protected Resource Metadata | **RFC 9728** (SEP-985) | required | E-174 |
| Client registration | **CIMD** recommended (SEP-991); **DCR deprecated** | deprecated ≥12 mo | E-172, E-173 |
| `iss` parameter | SEP-2468 | recommended | E-175 |

---

## 9. `lauren-mcp` 1.0.0 — the row that matters

| Attribute | Value | Evidence |
|---|---|---|
| Package | `lauren-mcp` **1.0.0**, released 2026-06-14 | E-220 |
| Python | ≥ 3.11 | E-221 |
| Runtime deps | **2**: `lauren>=1.7.0`, `anyio>=4.0` | E-222 |
| Extras | `ws`, `http`, `pydantic`, `msgspec`, `cli`, `all` | E-223 |
| CLI | `lmcp` | E-224 |
| `LATEST` | `2025-11-25` | E-225 |
| `SUPPORTED` | `2024-11-05`, `2025-03-26`, `2025-06-18`, `2025-11-25` | E-226 |
| Transports | stdio, WebSocket, Streamable HTTP, HTTP+SSE | E-241, E-244 |
| Modern-era surface | **0** across 7 distinguishing tokens | E-230…E-236 |
| Cancellation | listens for `$/cancelRequest` (LSP name); `notifications/cancelled` absent | E-237, E-240 |
| Observability | OTel present in `_server/_otel.py`; uses moved/deprecated attribute names | E-245, E-180 |
| Auth | OAuth client-credentials; RFC 8414 + RFC 9728 discovery; **no** RFC 8707 | E-246, E-247, E-238 |

### 9.1 Capability deltas — current → target

| Capability | `lauren-mcp` today | Ecosystem target | Delta class |
|---|---|---|---|
| `2026-07-28` revision | absent | 9 / 10 official SDKs ship it | architecture |
| `server/discover` | absent | TS 88, Py 135 hits | new method + router |
| per-request `_meta` | absent | modern-era envelope | architecture |
| `resultType` | absent | universal | mechanical |
| `ttlMs` / `cacheScope` | absent | SEP-2549 | mechanical |
| `subscriptions/listen` | absent (has GET channel + `resources/subscribe`) | SEP-replacement | replaces two mechanisms |
| MRTR `input_required` | absent | TS/Py both 59 hits | new pattern; supersedes sampling/elicitation |
| tasks | absent (`tasks/` = 0) | TS 25, Rust 17, C# 18 | extension |
| cancellation | **wrong method name** | `notifications/cancelled` since 2024-11-05 | **bug** |
| OTel attributes | present, old names | moved to GenAI semconv | rename |
| RFC 8707 | absent | required for HTTP | additive |
| CIMD | absent | recommended over DCR | additive |
| Registry metadata | absent | `server.json` 2025-12-11 | new artefact |
| Tool-search/deferral hints | absent | Claude Code default-on | presentation layer |

### 9.2 What `lauren-mcp` should be able to claim *after* the PRD set

| Claim | Enabled by |
|---|---|
| `SUPPORTED = {2024-11-05 … 2025-11-25, 2026-07-28}` | dual-era PRD |
| "Dual-era, like the TS and Python SDKs" | era-switch mechanism |
| "Cancellation-conformant" | cancellation bug PRD |
| "Publishable to the official Registry" | `server.json` generator |
| "OTel GenAI-semconv compatible" | attribute migration |
| "OAuth 2.1 + RFC 8707 + CIMD" | auth PRD |
| "Works in Claude Code without blowing the context budget" | presentation-layer PRD |

Each row maps to an `E-…` cluster in EVIDENCE.md §22, so the claim set is auditable rather than
aspirational.

---

## 10. Change log of this matrix

| Date | Change |
|---|---|
| 2026-11-26 | Initial matrix. Ten official SDKs, 13 Python projects, 11 hosts, 12 infra artefacts, `lauren-mcp` baseline. |
| 2026-11-26 | Corrected two premises before publication: `$/cancelRequest` is not an MCP method (E-08/E-09); `2026-07-28` is breaking, not additive (E-20…E-30). Both changed the "Era support" column for `lauren-mcp` from "migration pending" to "modern era absent — dual-era required". |

**Maintenance rule:** this matrix is dated. When a new spec revision is tagged, or when any Tier-1 SDK
ships a major, re-run EVIDENCE.md §20 and bump §10. Do not edit a cell without adding its `E-…` row
first — an unsourced cell here is exactly the failure mode this document exists to prevent.
