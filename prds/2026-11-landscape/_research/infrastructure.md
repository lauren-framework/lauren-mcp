# MCP Infrastructure, Registry, Auth, Hosting & Security — Landscape Research

**Retrieval date for all facts: 2026-11-26** (network-verified; every number below was read live from
the URL listed in [Sources](#sources) unless explicitly marked *inferred*).
**Scope:** registry, gateways/proxies, auth/identity, hosting/runtime, security, plus the resulting
compliance obligations for this repository (`lauren-mcp`, a Python MCP server **and** client).

> **How this was gathered.** Live HTTP against `registry.modelcontextprotocol.io`, `static.modelcontextprotocol.io`,
> the GitHub REST API, `pypi.org/pypi/<pkg>/json`, `registry.npmjs.org`, `api.osv.dev`, and shallow clones of
> `modelcontextprotocol/registry` and `modelcontextprotocol/modelcontextprotocol` at `main`. Where a claim could
> not be verified it is marked *unverified* rather than asserted.

---

## 0. Headline findings (read this if you read nothing else)

1. **The protocol moved past us.** Current spec revision is **`2026-07-28`**; prior revisions are
   `2025-11-25`, `2025-06-18`, `2025-03-26`, `2024-11-05`. `lauren-mcp` currently declares
   `LATEST = "2025-11-25"` and `SUPPORTED = {2024-11-05, 2025-03-26, 2025-06-18, 2025-11-25}`
   (`src/lauren_mcp/_mcp_version.py:6-7`) — **we are one full revision behind, and that revision is not additive.**
2. **`2026-07-28` deletes protocol-level sessions.** `Mcp-Session-Id` is removed from Streamable HTTP, the
   `initialize`/`notifications/initialized` handshake is removed ("make MCP stateless"; version + capabilities
   move into per-request `_meta`), `server/discover` becomes a **MUST**-implement RPC, and the HTTP GET endpoint
   plus `resources/subscribe` are replaced by `subscriptions/listen`. Our session machinery
   (`src/lauren_mcp/_server/_streamable.py`, `_SESSION_HEADER = "mcp-session-id"`, `secrets.token_urlsafe(16)`
   sessions, event-store replay) is now **legacy-only** and must be gated behind a negotiated version.
3. **DCR is deprecated; CIMD is the path.** Dynamic Client Registration is explicitly marked *Deprecated* as of
   `2026-07-28` (PR #2858) and stays in-spec for ≥12 months; **OAuth Client ID Metadata Documents (CIMD)** is the
   recommended registration mechanism, with `Pre-registration` retained for enterprise. We have neither.
4. **RFC 8707 resource indicators are no longer optional.** The authorization section ties the PKCE verifier
   record to the *canonical URI of the MCP server* as the resource/audience. A server-issued token audience we
   never validate is the single most common real-world MCP auth defect (OWASP MCP07).
5. **The official registry is real, big, and still "preview".** Service `1.8.16` (built 2026-11-23), APIs `v0`
   (legacy, still served) + **`v0.1`** (the only version in the shipped OpenAPI), OpenAPI `3.1.0`, `server.json`
   schema **`2025-12-11`**, **≥20,000 published server-version records** (we hit a 200-page pagination cap with
   `nextCursor` still non-null), read API unauthenticated. Publishing requires reverse-DNS names plus cryptographic
   namespace proof (`dns`, `http`, `github-at`, `github-oidc`) and a second, per-artifact ownership marker.
6. **Gateways are now the security control plane, not just a proxy.** Kong ships `ai-mcp-proxy` *and*
   `ai-mcp-oauth2`; Envoy AI Gateway was renamed **Agent Router** (2026-09-09, Agentic AI Foundation) with an
   explicit MCP Gateway feature set (aggregation, OAuth, tool filtering, API-key injection, rate limiting);
   IBM ContextForge ships virtual servers + federation + 40+ plugins. Any "add a gateway later" argument is weak:
   the gateway is where scope, audit and per-tool policy are actually enforced.
7. **Vulnerability surface is material and measurable.** Live OSV counts (2026-11-26): Python `mcp` **17**
   advisories (7 HIGH), `fastmcp` **16** (incl. 1 CRITICAL), `@modelcontextprotocol/sdk` **9**,
   `mcp-contextforge-gateway` **5**, `@modelcontextprotocol/inspector` **2**, `mcp-remote` **1** (CVE-2025-6514,
   CRITICAL, OS command injection), `supergateway` **0**. A gateway/framework is a *liability accumulator*.

---

## 1. MCP Registry

### 1.1 Service reality (verified live)

| Property | Observed value (2026-11-26) |
|---|---|
| Base URL | `https://registry.modelcontextprotocol.io` |
| Version endpoint | `GET /v0/version` and `GET /v0.1/version` → `{"version":"1.8.16","git_commit":"a21a32bd…","build_time":"2026-11-23T13:54:44Z"}` |
| API versions live | `v0` and **`v0.1`** both respond; the shipped `openapi.yaml` documents **only `v0.1`**, so `v0` is legacy-but-still-served (*inferred from the spec's scope, not from a deprecation notice*) |
| OpenAPI doc | `/openapi.yaml` → OpenAPI **3.1.0**, `info.title = "Official MCP Registry"`, `info.version = 1.0.0` |
| `server.json` schema | `https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json` (22,090 bytes) |
| Read auth | **none** — "The MCP Registry provides an unauthenticated read-only API" (registry-aggregators.mdx) |
| Pagination | `cursor`, `limit` (default 30), `updated_since`, `search`, `version`, `include_deleted` |
| Maturity | **preview** — "Breaking changes or data resets may occur before general availability" |
| Upstream repo | `modelcontextprotocol/registry` — 7,500★, 1,065 forks, releases latest **v1.8.16** (2026-11-23) |
| Scale (measured) | ≥ **20,000** server-version records returned by walking `v0.1/servers?limit=100` to our 200-page cap; `metadata.nextCursor` still non-null → **20k is a floor, not a total** |

The registry is a *metadata* registry only: it stores `server.json` documents. It does not proxy traffic,
does not host images, and does not scan code.

### 1.2 Endpoints (from the shipped OpenAPI)

```
GET  /v0.1/servers                 list (paginated, `search`, `updated_since`, `include_deleted`)
GET  /v0.1/servers/{name}/versions list versions of one server
GET  /v0.1/servers/{name}/versions/{version}
POST /v0.1/publish                 body: ServerJSON (the server.json document)
POST /v0.1/auth/dns                exchange a DNS TXT proof for a short-lived registry JWT
POST /v0.1/auth/github-at          exchange a GitHub access token
POST /v0.1/auth/github-oidc        exchange a GitHub Actions OIDC token (no long-lived secret)
POST /v0.1/auth/http               exchange an HTTP-hosted proof
```

Notably there is **no `securitySchemes`** in the OpenAPI components — publish auth is a bearer JWT obtained from
the `/auth/*` exchange endpoints, and the read paths carry no auth. Rate limiting exists operationally but is not
described in the spec (*unverified*: exact limits).

### 1.3 Metadata that must be published (`server.json`, schema `2025-12-11`)

**Required on every document:** `name`, `description`, `version`. `$schema` and `_meta` are optional but
`$schema` is expected in practice.

| Field | Rule |
|---|---|
| `name` | Reverse-DNS **with exactly one `/`**: `namespace/server`, e.g. `io.github.user/weather`. Exactly one slash — `com.example/foo/bar` is invalid. |
| `version` | Required per published record; each publish creates a new immutable version, and `latest` resolution is separate from `name` (see *Versioning*). |
| `packages[]` | Required for package-delivered servers. `registryType ∈ {npm, pypi, nuget, cargo, oci, mcpb}`; npm limited to the **public** `registry.npmjs.org`; OCI images restricted to an allow-list of registries — Docker Hub (`docker.io`), GitHub (`ghcr.io`), Quay (`quay.io`), Google Artifact Registry (`*.pkg.dev`), Azure Container Registry (`*.azurecr.io`), Microsoft Container Registry (`mcr.microsoft.com`) — per `official-registry-requirements.md`. |
| `remotes[]` | Required for remote-only servers. `StreamableHttpTransport` requires `type` + `url`; optional `headers`. `SseTransport` exists as the legacy variant. URLs support `{curly_brace}` templating for variables. |
| `packages[].transport` | `stdio` / `streamable-http` / `sse`, per-package. |
| `packages[].environmentVariables[]` | `name`, optional `description`, `default`, **`isSecret`**, `choices`, `format` (`string`/`number`/`boolean`/`filepath`), `value`. |
| `packages[].packageArguments[]` | `Argument` schema: `type` (`positional`/`named`), `value`/`valueHint`, `isSecret`, `choices`, `default`, `format`, `variables`. |
| `repository` | `url` + `source` (`github`/`git`), used for provenance display. |
| `_meta` | **Two different `_meta`s.** In `server.json` it is publisher extension metadata (reverse-DNS-keyed, e.g. `io.modelcontextprotocol.registry/publisher-provided`); in API responses `_meta` is *registry-owned* (`io.modelcontextprotocol.registry/official`) and contains `status`, `publishedAt`, `updatedAt`, `isLatest`. Do not conflate them — the official requirements doc calls this out explicitly. |

Validation on publish: schema validation, then registry-specific rules (image/namespace allow-lists, version
monotonicity, official `_meta` presence for "official" servers).

### 1.4 Namespace ownership — this is the real auth model

Publishing is gated on *proving you control the namespace*, not on a user account:

| Login method | Proof of control | Use case |
|---|---|---|
| `mcp-publisher login dns --domain example.com --private-key <hex>` | Ed25519 signature published as a DNS **TXT** record at `_mcp-auth.<domain>` (also supports GCP KMS / cloud signing) | Owning `com.example/*` |
| `login http --domain example.com --private-key <hex>` | Signature file served at `https://<domain>/.well-known/mcp-registry-auth` | No DNS control, but controls the web origin |
| `login github` | GitHub OAuth interactive | `io.github.<user>/*` |
| `login github-oidc` | GitHub Actions OIDC token | CI publishing with **no stored secret** |
| `login github-at --token` | GitHub PAT | Scripted/headless |
| `login anonymous` | none | local/test registry only |

Package-level ownership is verified *separately*, by a marker embedded in the artifact you already control the
release of:
- **npm**: `"mcpName": "<namespace>/<server>"` in `package.json` must equal the `server.json` `name`.
- **PyPI**: the README must contain the literal string `mcp-name: <namespace>/<server>`.
- NuGet / Cargo / OCI / MCPB have equivalent per-ecosystem proofs (see `package-types.mdx`).

**Implication:** a name is a claim about *domain or package ownership*, and it is verified twice (namespace
claim + artifact marker). This is the strongest supply-chain primitive in the whole MCP ecosystem today and it is
what aggregators trust.

### 1.5 Publisher tooling

`mcp-publisher` CLI (Go; release assets include `mcp-publisher_<os>_<arch>.tar.gz` for linux/darwin/windows on
amd64/arm64, plus `checksums.txt`):

```
mcp-publisher init                 # scaffold server.json
mcp-publisher login <method>       # see table above
mcp-publisher publish [--registry=<url>] [PATH]   # validates then POSTs /v0.1/publish
```

`--registry` makes the CLI point at any compatible instance, which is how private/internal registries are built.

### 1.6 Versioning & lifecycle semantics

- Every publish mints an immutable `(name, version)` record; re-publishing the same version is rejected.
- `isLatest` is registry-owned state on the record, not a client-side computation.
- Deletion is **soft** (`include_deleted=true` to see tombstones) so that clients that cached a server do not
  silently resolve a name to different code.
- Registry-side schema versions (`2025-09-29`, `2025-12-11`) are versioned **independently** of protocol
  revisions — pin `$schema` explicitly.

### 1.7 The aggregator/marketplace layer

The registry is explicitly designed to be *consumed* by downstream aggregators ("app store for MCP servers" →
aggregators add curation, ratings, hosting). Measured 2026-11-26:

| Index | Observed | Note |
|---|---|---|
| **Glama** | "131,130 in the Glama Registry" | Largest by count; auto-indexes GitHub repos, adds automated security scoring |
| **mcp.so** | 20,915 servers | Directory-style, SEO-heavy |
| **Docker MCP Catalog** | `docker/mcp-registry` 589★, 327 entries under `servers/`; Docker Hub `mcp/` namespace: 244 repos | Curated, container-signature-based, one-click into Docker Desktop/`docker mcp` |
| **Smithery** | site title: *"Smithery · MCP servers, now part of Arcade"* | Consolidation event; hosting + CLI (`smithery-ai/cli` 847★) |
| **Official registry** | ≥20,000 server-version records, preview | Canonical `server.json` source; everyone else mirrors |

Aggregators differ from the official registry in exactly the ways that matter for trust: they add
**scanning/scoring** (Glama), **container signing** (Docker), **hosted execution** (Smithery, Docker, Cloudflare),
and they *mirror* `server.json` rather than being authoritative for it.

---

## 2. Gateways & proxies

Two distinct products get called "MCP gateway". Conflating them causes architecture mistakes:

- **Type A — transport bridge / multiplexer (dev tool):** turns a local `stdio` server into a URL, or fans one
  endpoint out to many child servers. Stateless-ish, single-user, no policy engine.
- **Type B — policy gateway (production control plane):** terminates auth, enforces per-tool authorization,
  aggregates N upstreams behind one endpoint, emits audit/telemetry, rate-limits, and injects upstream credentials.

### 2.1 Verified inventory (2026-11-26)

| Project | Version / signal | Type | What it actually does |
|---|---|---|---|
| **Docker MCP Gateway** (`docker/mcp-gateway`) | 1,649★, tags to **v0.44.3**; ships as `docker mcp` CLI plugin | A+B | Runs catalog servers in containers, exposes one MCP endpoint to the client (`docker mcp gateway run`), secret injection via Docker secrets, OAuth helper sidecar (`docker/mcp-gateway-oauth-helpers`) |
| **IBM ContextForge** (`IBM/mcp-context-forge`) | PyPI `mcp-contextforge-gateway` **1.1.2** (2026-11-25) | B | "Virtual servers" (named tool subsets), federation of multiple registries/upstreams, REST-to-MCP translation, stdio↔SSE bridging, **40+ plugins**, multi-tenant, admin UI |
| **Kong Gateway** | OSS **3.9.5** (2026-11-19); plugins `ai-mcp-proxy`, `ai-mcp-oauth2` (both listed in Kong Hub) | B | MCP traffic as a first-class Kong route/service via `ai-mcp-proxy`, with `ai-mcp-oauth2` supplying OAuth2 resource-server behaviour; inherits Kong's rate limiting, key-auth, mTLS and observability plugins. Exact proxy surface beyond that not verified from docs |
| **Agent Router** (formerly **Envoy AI Gateway**, renamed **2026-09-09**, Agentic AI Foundation project) | `envoyproxy/ai-gateway` 2,450★, release **v1.3.0** (2026-11-18) | B | MCP Gateway: aggregate many MCP servers into one endpoint, OAuth authentication, fine-grained access control **per tool call**, API-key injection, tool filtering, plus Envoy networking (LB, rate limiting, circuit breaking, tracing). Same `aigateway.envoyproxy.io` API groups and `aigw` CLI; namespace `envoy-ai-gateway-system` unchanged |
| **supergateway** (`supercorp-ai/supergateway`) | 2,984★, **v4.3.0** (2026-11-24), npm `supergateway@4.3.0`, **0 OSV advisories** | A | The "npx one-liner": stdio → SSE / streamable-HTTP / SSE-over-stdio, both directions |
| **mcp-proxy** (`sparfenyuk/mcp-proxy`) | PyPI **0.15.0** (2026-11-09) | A | stdio↔SSE/streamable bridge, client-side and server-side modes |
| **mcpo** (`open-webui/mcpo`) | PyPI **0.0.21** (2026-11-25) | A (translation) | MCP → **OpenAPI/REST** so any OpenAPI-consuming LLM app can use MCP servers. Different direction of translation than everything else here |
| **mcp-remote** (npm) | **0.17.1**; 1 advisory: **CVE-2025-6514** (CRITICAL, published 2025-07-09) | A (client-side) | Lets stdio-only clients reach remote servers via a local bridge; the CVE is OS command injection from an untrusted server's `command` |
| **LiteLLM** (`BerriAI/litellm`) | 63,957★, **v1.111.0** (2026-11-25) | B (LLM-proxy-centric) | MCP client + server registry inside an LLM proxy: per-key/per-team MCP server allow-lists, tool-name prefixing, OAuth passthrough |
| **Vercel MCP Adapter** (`vercel/mcp-adapter`) | 711★, **v2.4.0** (2026-11-12) | A (framework) | Mount an MCP endpoint into Next.js/Nuxt/SvelteKit route handlers |
| **FastMCP** (`jlowin/fastmcp`) | PyPI **4.2.6** (2026-11-25); 16 advisories incl. 1 CRITICAL | Framework | Proxy/mount/compose MCP servers in-process (`FastMCP.as_proxy`, prefixing, multi-server mounting) — the "gateway" here is Python object composition |
| **mcp-use** (`mcp-use`, now "Manufact") | site title *"Open-Source SDK for MCP Apps and Servers \| Manufact"* | Framework | Client/server SDK with first-class **MCP Apps** (UI extension) support |

### 2.2 What actually breaks in gateways

1. **Session identity.** With `2026-07-28` removing `Mcp-Session-Id`, a Type-A bridge that relied on the header for
   upstream affinity has nothing to pin on. Gateways must either keep a legacy-only compatibility path or move to
   stateless per-request routing (which is what makes horizontal scaling work at all).
2. **Tool-name collisions.** Aggregating N servers produces N duplicate `search`/`read`/`list` tools. Every serious
   Type-B gateway namespaces (`server__tool`) or filters. Client-visible tool names must therefore be treated as
   *gateway-derived*, not server-derived, when auditing.
3. **Auth composition.** A gateway terminating OAuth for the client while injecting a *different* credential
   upstream is a scope-confused-deputy generator if it does not also filter tools per caller (OWASP MCP02/MCP07).
4. **Notification fan-out.** With `subscriptions/listen` replacing the GET stream + `resources/subscribe`, a
   multiplexing gateway now has to map one downstream long-lived POST stream to N upstream subscriptions.
5. **Error/telemetry attribution.** Once `mcp.method.name` is an OpenTelemetry span/attribute namespace (§5.5),
   per-tool authorization decisions become auditable — but only if the gateway records the *upstream* server name
   alongside the *exposed* tool name.

---

## 3. Auth & identity

### 3.1 What the spec actually requires now (`2026-07-28`)

Grounded in `docs/specification/2026-07-28/basic/authorization/*`:

| # | Requirement | Level |
|---|---|---|
| 1 | Authorization servers implement **OAuth 2.1** (`draft-ietf-oauth-v2-1-13`), with measures for both confidential and public clients | **MUST** |
| 2 | Support **OAuth Client ID Metadata Documents (CIMD)**; fall back to pre-registration / DCR where unavailable | **SHOULD** |
| 3 | Bearer tokens per **RFC 6750**; `WWW-Authenticate` on 401 | MUST (implied by flow) |
| 4 | Protected Resource Metadata per **RFC 9728** at `/.well-known/oauth-protected-resource` with `authorization_servers`, `resource` | **MUST** for HTTP transports |
| 5 | AS discovery: RFC 8414 `/.well-known/oauth-authorization-server`, **plus** OIDC Discovery 1.0 (added in `2025-11-25`) | **MUST** |
| 6 | **PKCE** with `code_challenge`/`code_verifier`, verifier bound to the per-request state record | **MUST** |
| 7 | **RFC 8707 resource indicator** — the token audience is the *canonical URI of the MCP server*, not the AS; server must reject tokens minted for another resource | **MUST** |
| 8 | **`iss` parameter** in authorization responses, and clients **MUST** compare it against the recorded issuer before redeeming the code (mix-up defence) | SHOULD (AS) / MUST (client) |
| 9 | STDIO transports **SHOULD NOT** use this flow — take credentials from the environment instead | SHOULD NOT |
| 10 | Alternative transports **MUST** apply equivalent security practices | MUST |

**DCR status:** `## Dynamic Client Registration` in `client-registration.mdx` carries a `<Warning>`:
*"Deprecated: Dynamic Client Registration is deprecated as of protocol version `2026-07-28` (PR #2858).
Under the feature lifecycle policy, it remains in the specification for at least twelve months after that
revision's release before it becomes eligible for removal. New implementations should use Client ID Metadata
Documents."* Section order in the doc is now **CIMD → Pre-registration → DCR → Authorization Server Binding**,
which is the priority order in practice.

Why DCR lost: every MCP client registering with every MCP server's AS produces unbounded, orphaned client records
and turns each MCP server into an AS operator — the opposite of the "MCP server is a *resource* server" model.

### 3.2 Client ID Metadata Document (CIMD) — the shape of the successor

- The **client's_own HTTPS URL is the `client_id`**; the AS fetches it to get `client_name`, `redirect_uris`,
  `grant_types`, `token_endpoint_auth_method`, etc. (`### Example Metadata Document`, `### Advertising CIMD Support`).
- Requirements (`### Implementation Requirements`): HTTPS only, `client_id` must equal the document URL,
  redirect URIs must be exact-match and HTTPS (or loopback for native apps), document must be fetchable at
  authorization time, and the AS should cache with an explicit TTL.
- **This is a new SSRF/redirect-URI-validation surface**, and it is the single biggest new hardening job for any
  MCP authorizer: you are now *fetching attacker-nominated URLs* on every authorization.
- `## Authorization Server Binding` exists precisely because with CIMD + RFC 8707 the *binding* between client,
  resource and issuer is the security property — not the client secret.

### 3.3 Token models seen in the wild

| Model | Example | Fit |
|---|---|---|
| **Per-user OAuth (authorization code + PKCE)** | WorkOS AuthKit MCP, Auth0 for AI Agents, Descope MCP, Zitadel (docs URL 404 at time of check — *unverified*) | Human-in-the-loop interactive clients |
| **Client credentials (M2M)** | **`lauren-mcp`'s current token provider**, most CI/batch agents | No user, machine identity. Cannot express per-user consent; must not be presented as user auth |
| **CIMD** | Spec-blessed replacement for DCR | Modern clients, still needs an AS |
| **Static API key / bearer** | Docker MCP secrets, `mcp-remote` headers, `packages[].environmentVariables[].isSecret` | Trusted single-tenant; must be marked `isSecret` in `server.json` |
| **Brokered/ephemeral (gateway-issued)** | Agent Router API-key injection, Kong `ai-mcp-oauth2`, LiteLLM per-key MCP allow-lists, Cloudflare `workers-oauth-provider` 1.4.0 | Production multi-tenant; the gateway owns the token lifecycle |

Verified auth-provider docs live as of 2026-11-26: `https://workos.com/docs/authkit/mcp` (200),
`https://docs.descope.com/mcp` (200). `https://zitadel.com/docs/guides/integrate/mcp` returned **404**.

### 3.4 The gap that matters most for us

`lauren-mcp` publishes `.well-known/oauth-authorization-server` and `.well-known/oauth-protected-resource`
**with no authorization server behind them**, and has **no PKCE, no RFC 8707, no DCR, no CIMD** (0 hits each).
That is the worst of both worlds: clients are told an AS exists (so they will try the interactive flow), but
nothing can issue or validate a token except our client-credentials provider. Two honest end-states:
(a) **resource-server-only** — PRM advertises a *third-party* `authorization_servers`, and we validate
`aud`/`resource`/`iss`; or (b) **full AS** — implement authorization code + PKCE + RFC 8707 + CIMD fetching.
Advertising discovery metadata we cannot service is a correctness bug, not a placeholder.

---

## 4. Hosting & runtime

### 4.1 Verified hosting options (2026-11-26)

| Platform | MCP surface | Transport/runtime model | Auth story |
|---|---|---|---|
| **Cloudflare Workers** | `cloudflare/agents` (6,153★) — `McpAgent` Durable Object, "Build a Remote MCP server" guide (200 OK); `@cloudflare/workers-oauth-provider` **1.4.0** on npm | Stateless HTTP entry → Durable Object per session | OAuth provider library handles AS-side, KV/D1-backed grants, per-user token → upstream provider token exchange |
| **AWS Bedrock AgentCore Gateway** | "Amazon Bedrock AgentCore Gateway: A secure AI gateway for agents, tools, and mod…" (docs page 200 OK) | Managed MCP endpoint in front of Lambda/OpenAPI/Smithy targets | SigV4/IAM + OAuth inbound; AgentCore Identity for outbound |
| **Azure API Center** | "Inventory and Discover MCP Servers in Your API Center" (docs 200 OK) | **Registry**, not runtime: inventory/discovery of MCP servers as API assets | Entra ID |
| **Vercel** | `vercel/mcp-adapter` **v2.4.0** | Next.js/Nuxt/SvelteKit route handler on serverless functions | Bring-your-own AS; pass-through headers |
| **Docker (local/desktop)** | `docker mcp` plugin + Gateway **v0.44.3**, catalog `docker/mcp-registry` | Container per server, gateway multiplexes; secrets via Docker secrets | OAuth helper sidecar |
| **Prefect Horizon / FastMCP Cloud** | FastMCP **4.2.6** | Managed deployment of a FastMCP app | Platform-managed |
| **mcp-use / Manufact** | "Open-Source SDK for MCP Apps and Servers" | Self-hosted SDK, **MCP Apps** (UI) aware | BYO |
| **Kong / Agent Router / ContextForge** | see §2 | Kubernetes ingress / gateway layer, in front of *any* runtime | Policy engine (OAuth, mTLS, tool ACL) |

Google Cloud's Apigee/Gemini Enterprise MCP documentation paths we tried
(`/apigee/docs/api-platform/genai/mcp`, `.../mcp-servers`) returned **404** on 2026-11-26 — the capability is
widely referenced but we could not verify a canonical doc URL, so treat it as *unverified* here.

### 4.2 What "hosting an MCP server" now means

1. **Stateless-first is the default for `2026-07-28`.** Removing `Mcp-Session-Id` + `initialize` means a request
   carries everything needed; serverless runtimes stop needing sticky sessions or a Durable Object keyed on the
   header. Long-lived state moves to explicit `subscriptions/listen` streams.
2. **Two hosting modes, both first-class:** *package* (npm/PyPI/NuGet/Cargo/OCI/MCPB, executed by the client or a
   local gateway like Docker) and *remote-only* (`remotes[]`, published with **no package at all** — an explicitly
   supported registry workflow). Our repo is the Python-package flavour with a remote endpoint bolted on; the
   registry treats those as separate distribution stories.
3. **The Durable-Object/stateful-worker pattern is legacy-shaped now.** Anything that keeps a session map in
   process memory (ours: `StreamableSession` with `token_urlsafe(16)` ids) must survive `2026-07-28` clients that
   never send the header.
4. **Hosted execution is where trust shifts.** If a marketplace runs your server (Smithery/Docker/Cloudflare),
   its signing + scanning becomes part of your supply chain, and its OAuth grants become the user's consent record.

---

## 5. Security

### 5.1 The named threat catalogue — OWASP MCP Top 10 (2025)

Verified from `OWASP/www-project-mcp-top-10` (140★, `2025/` directory), i.e. the canonical list:

| ID | Risk |
|---|---|
| MCP01 | Token Mismanagement & Secret Exposure |
| MCP02 | Privilege Escalation via Scope Creep |
| MCP03 | Tool Poisoning |
| MCP04 | Software Supply Chain Attacks |
| MCP05 | Command Injection & Execution |
| MCP06 | Intent Flow Subversion |
| MCP07 | Insufficient Authentication & Authorization |
| MCP08 | Lack of Audit and Telemetry |
| MCP09 | Shadow MCP Servers |
| MCP10 | Context Injection & Over-Sharing |

The project page (`https://owasp.org/www-project-mcp-top-10/`) is live (200) but its body is roadmap text, not the
list; the list lives in the repo. MCP09 (Shadow MCP) is the one most infrastructure teams underestimate: it is a
*registry/CIMD* problem as much as a network one.

### 5.2 Measured vulnerability surface

Live `POST https://api.osv.dev/v1/query` counts on 2026-11-26:

| Package | Ecosystem | Advisories | Severity mix |
|---|---|---|---|
| `mcp` (official Python SDK) | PyPI | **17** | 7 HIGH, 4 MODERATE, 6 unrated |
| `fastmcp` | PyPI | **16** | 1 CRITICAL, 4 HIGH, 5 MODERATE, 6 unrated |
| `@modelcontextprotocol/sdk` | npm | **9** | — |
| `mcp-contextforge-gateway` | PyPI | **5** | ≥1 CRITICAL, ≥1 HIGH, ≥1 MODERATE |
| `@modelcontextprotocol/inspector` | npm | **2** | — |
| `mcp-remote` | npm | **1** | **CRITICAL** — `GHSA-6xpm-ggf7-wc3p` = **CVE-2025-6514**, "OS command injection via untrusted MCP server connections", published 2025-07-09 |
| `supergateway` | npm | **0** | — |

Reading: **the bridge/SDK layer is where the CVEs are**, and the pattern is uniform — *the client trusts
server-supplied strings* (commands, URLs, tool metadata, HTML). `supergateway`'s zero is a useful control:
a small, purpose-built bridge beats a kitchen-sink framework on this axis.

### 5.3 Transport & origin validation (spec-mandated)

`docs/specification/2026-07-28/basic/transports/streamable-http.mdx`, server requirements:

1. Servers **MUST** validate the `Origin` header on all incoming connections to prevent **DNS rebinding**; if
   `Origin` is present and invalid, reject. (Our `McpTransportSecurityGuard` / `TransportSecuritySettings`
   already implements Host + Origin + Content-Type validation — this is one of the few places we are *ahead*.)
2. Servers **MUST** bind to loopback when running locally and **SHOULD** validate `Host`.
3. One **single MCP endpoint path** supporting POST (GET is gone in `2026-07-28`; `subscriptions/listen`
   is the replacement stream).
4. `Content-Type: application/json` required; `Accept` must include both `application/json` and
   `text/event-stream` for streamed responses.

New validation obligations introduced by the auth changes, all of which are *origin*-flavoured:

| Thing to validate | Against | Consequence if missed |
|---|---|---|
| `Origin` | allow-list | DNS rebinding, local-network SSRF from a browser |
| `Host` | configured public hostname | Host-header injection into discovery URLs (poisons PRM `resource`) |
| `resource` / `aud` in token | canonical MCP URI (RFC 8707) | Token replay across resources — confused deputy |
| `iss` in authorization response | issuer recorded at discovery | Mix-up attack |
| CIMD `client_id` | the document URL itself | Attacker-registered client with stolen redirect |
| CIMD `redirect_uris` | exact-match, HTTPS (loopback excepted) | Code interception |
| `redirect_uri` on authorize | exact match to registered set | Open redirect → code theft |
| Package/OCI namespace | registry allow-list + artifact `mcpName` marker | Typosquat / supply-chain substitution |

### 5.4 Defence-in-depth patterns that are actually implemented somewhere

- **Tool allow-listing at the gateway** (Agent Router tool filtering, Kong `ai-mcp-proxy`, LiteLLM per-key
  allow-lists, ContextForge virtual servers) — the only reliable mitigation for MCP02/MCP03, because the model
  cannot be trusted to ignore a poisoned description.
- **Secret marking, not secret smuggling**: `isSecret: true` on `environmentVariables`/`packageArguments` so
  registries and catalog UIs can redact; Docker secrets for injection.
- **Containerisation per server** (Docker MCP Gateway) — bounds MCP05 blast radius.
- **Human-in-the-loop for destructive tools** — a policy concern, not a protocol one; must be enforced at the
  gateway since a stdio server cannot see the conversation.
- **Pinning**: `(name, version)` records are immutable in the registry — pin them, do not float to `isLatest`.

### 5.5 Observability is now standardised — and it just moved

OpenTelemetry defines an MCP attribute namespace:

```
mcp.method.name        mcp.protocol.version        mcp.resource.uri        mcp.session.id
```

**Important nuance verified 2026-11-26:** all four attributes are marked *Deprecated* in the main
`open-telemetry/semantic-conventions` repo, but not because they are going away — the file
`docs/registry/attributes/mcp.md` is now headed **"MCP Attributes (Moved)"** and redirects to
`open-telemetry/semantic-conventions-genai` (566★), which carries the live definitions plus dedicated
`reference/reports/mcp-client-span.md`, `mcp-server-span.md`, and an MCP client operation-duration metric. So the
convention is: **`mcp.*` attributes are current; the main semconv repo is the wrong place to read them.** Anyone
who greps the main repo and sees "Deprecated" will draw the wrong conclusion (we nearly did).

Practical effect: MCP08 (Lack of Audit and Telemetry) is no longer an excuse. Emit `mcp.method.name` +
`mcp.protocol.version` (+ `mcp.resource.uri`) per request, model client and server spans per the GenAI-semconv
reports, and treat `mcp.session.id` as version-coupled — it is meaningful only on pre-`2026-07-28` connections.

---

## 6. Requirements this imposes on `lauren-mcp` (gap analysis)

Grounded in the repo as of this worktree (`src/lauren_mcp/_mcp_version.py`, `src/lauren_mcp/_server/_streamable.py`).

### 6.1 Protocol versions that must be supported

| Revision | Status today | Action |
|---|---|---|
| `2024-11-05` | supported (`STABLE`) | keep as legacy floor |
| `2025-03-26`, `2025-06-18` | supported | keep (clients are sticky) |
| `2025-11-25` | `LATEST`, supported | becomes **legacy**; keep, but it is no longer "current" |
| **`2026-07-28`** | **not supported** | **must add** — stateless request model, `server/discover`, `subscriptions/listen`, mandatory `ttlMs`/`cacheScope`, DCR-deprecation-aware auth |

The Python SDK reference implementation already runs `2026-07-28` and `2025-11-25` side by side
(`mcp` 2.3.0 release notes, 2026-10-02) — so dual-protocol is the expected shape for a server in 2026, not an
excuse to drop the old revisions.

### 6.2 Metadata that must be published (for registry listing)

`server.json` with `$schema` pinned to `…/schemas/2025-12-11/server.schema.json`, reverse-DNS `name` with exactly
one `/`, `description`, `version`, and **either** `packages[]` (PyPI, `registryType: "pypi"`, `mcp-name:` marker in
the README, `transport: {type: streamable-http|sse|stdio}`) **or** `remotes[]` (`type: streamable-http`, `url`,
optional `headers`) for the hosted endpoint. Mark every credential-ish env var/argument `isSecret: true`.
Declare `repository` for provenance. Note the registry `_meta` ≠ our `_meta`.

### 6.3 Origins that must be validated

Already: `Host`, `Origin`, `Content-Type` (`TransportSecuritySettings` / `McpTransportSecurityGuard`) — keep, and
add the `2026-07-28` §5.3 rows: **`resource`/`aud`**, **`iss`**, **CIMD `client_id`/`redirect_uris`**,
**`redirect_uri` exact match**, **`Accept` negotiation**.

### 6.4 Auth posture

| Item | Today | Required end-state |
|---|---|---|
| `.well-known/oauth-protected-resource` (RFC 9728) | present, points at *us* | must advertise a real `authorization_servers[]` and a correct `resource` |
| `.well-known/oauth-authorization-server` (RFC 8414) | present, **no AS behind it** | remove, or implement (not recommended) |
| PKCE | absent | **MUST** if we ever host an AS; otherwise validate a third-party AS's PKCE-built tokens |
| RFC 8707 resource binding | absent | **MUST** — validate `aud`/`resource` == our canonical URI on every request |
| DCR | absent | **do not add** (deprecated `2026-07-28`) |
| CIMD | absent | **SHOULD** support verification when acting as a resource server that inspects `client_id` |
| Client credentials | only model implemented | keep for M2M, but do not present it as the interactive story |
| `iss` validation | absent | **MUST** on the client path (we are also an MCP *client*) |

### 6.5 Priority order (infrastructure view)

1. **Version negotiation for `2026-07-28`** incl. `server/discover`, stateless `_meta` handling, `ttlMs`/`cacheScope`,
   `subscriptions/listen`; keep session/event-store replay strictly on the legacy path.
2. **Fix the discovery-metadata honesty problem** (§6.4 rows 1–2) — it is the cheapest credibility win and the
   biggest active footgun.
3. **RFC 8707 audience validation** on both server and client paths.
4. **`server.json` + a CI publish path** using `mcp-publisher login github-oidc` (no long-lived secret) so the
   server is discoverable at all.
5. **OTel `mcp.*` instrumentation** (attributes read from
   `open-telemetry/semantic-conventions-genai`, *not* the main semconv repo where they now show as "Moved") to
   close MCP08 before an auditee asks.
6. **Decide gateway-or-library**: if we ship production multi-tenant, per-tool authorization belongs in profile
   with Kong/Agent Router/ContextForge, not in `lauren_mcp` core. If we stay library-only, document that MCP02/03
   mitigation is the deployer's job.

---

## Sources

All retrieved **2026-11-26**. "live" = value read from the running service / package index; "repo" = read from
the named file in a shallow clone of `main` at that date.

| # | Source | URL | What it established | Retrieval |
|---|---|---|---|---|
| 1 | Official MCP Registry — version endpoint (live) | https://registry.modelcontextprotocol.io/v0/version | Service `1.8.16`, git `a21a32b`, build `2026-11-23T13:54:44Z` | 2026-11-26 |
| 2 | Official MCP Registry — OpenAPI spec (live) | https://registry.modelcontextprotocol.io/openapi.yaml | OpenAPI 3.1.0, `v0.1` paths, `/auth/{dns,github-at,github-oidc,http}`, list params, no `securitySchemes` | 2026-11-26 |
| 3 | Official MCP Registry — servers list (live) | https://registry.modelcontextprotocol.io/v0.1/servers?limit=100 | Pagination, `metadata.count`, ≥20,000 records walked | 2026-11-26 |
| 4 | `server.json` JSON Schema `2025-12-11` | https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json | Required `name`/`description`/`version`, reverse-DNS-with-one-slash name, `packages[]`, `remotes[]`, `isSecret`, transports | 2026-11-26 |
| 5 | Registry repo | https://github.com/modelcontextprotocol/registry | 7,500★; releases latest `v1.8.16` (2026-11-23); `mcp-publisher` assets | 2026-11-26 |
| 6 | Official Registry server.json requirements (repo) | https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/server-json/official-registry-requirements.md | OCI/npm allow-lists, MCPB, `_meta` server.json-vs-API distinction, validation rules | 2026-11-26 |
| 7 | Publisher CLI reference (repo) | https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/cli/commands.md | `init`/`login`/`publish`, `dns`/`http`/`github`/`github-oidc`/`github-at`/`anonymous`, KMS signing, `--registry` | 2026-11-26 |
| 8 | Publishing quickstart, incl. "Remote-only servers" (repo) | https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/quickstart.mdx | Remote-only publish without a package | 2026-11-26 |
| 9 | Package types & ownership verification (repo) | https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/package-types.mdx | npm/PyPI/NuGet/Cargo/OCI/MCPB; `mcpName` in `package.json`; `mcp-name: <name>` in PyPI README | 2026-11-26 |
| 10 | Registry aggregators (repo) | https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/registry-aggregators.mdx | "unauthenticated read-only API"; preview status; aggregator model | 2026-11-26 |
| 11 | Versioning published servers (repo) | https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/versioning.mdx | Immutable versions, `isLatest`, registry preview caveat | 2026-11-26 |
| 12 | Spec revision tags | https://github.com/modelcontextprotocol/modelcontextprotocol/tags | `2026-07-28` (current), `2025-11-25`, `2025-06-18`, `2025-03-26`, `2024-11-05` | 2026-11-26 |
| 13 | Spec `2026-07-28` changelog (repo) | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/changelog.mdx | Session/`Mcp-Session-Id` removal, stateless `_meta`, `server/discover`, `subscriptions/listen`, `ttlMs`/`cacheScope`, removal of `ping`/`logging/setLevel`/`roots/list_changed`, `iss` requirement | 2026-11-26 |
| 14 | `2026-07-28` authorization overview (repo) | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/authorization/index.mdx | OAuth 2.1 MUST, CIMD SHOULD, PKCE, RFC 8707 canonical-URI resource, STDIO exemption | 2026-11-26 |
| 15 | `2026-07-28` client registration (repo) | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/authorization/client-registration.mdx | CIMD section; **DCR deprecated as of `2026-07-28` (PR #2858)**, ≥12-month removal window; pre-registration; AS binding | 2026-11-26 |
| 16 | `2026-07-28` Streamable HTTP transport (repo) | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/transports/streamable-http.mdx | `Origin` MUST-validate (DNS rebinding), single POST endpoint, `Host`/`Accept`/`Content-Type` rules | 2026-11-26 |
| 17 | `2025-11-25` changelog (repo) | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/changelog.mdx | OIDC Discovery 1.0 for AS discovery, icons, etc. (baseline we currently implement) | 2026-11-26 |
| 18 | Python SDK releases (repo) | https://github.com/modelcontextprotocol/python-sdk/releases | `v2.3.0` (2026-10-02) runs `2026-07-28` and `2025-11-25` concurrently; `v1.30.0` legacy line | 2026-11-26 |
| 19 | TypeScript SDK releases | https://github.com/modelcontextprotocol/typescript-sdk/releases | latest `v2.4.0` (2026-10-23) | 2026-11-26 |
| 20 | PyPI JSON API (live) | https://pypi.org/pypi/mcp/json | `mcp` 2.3.0 (2026-10-02) | 2026-11-26 |
| 21 | PyPI JSON API (live) | https://pypi.org/pypi/fastmcp/json | `fastmcp` 4.2.6 (2026-11-25) | 2026-11-26 |
| 22 | PyPI JSON API (live) | https://pypi.org/pypi/mcp-contextforge-gateway/json | `mcp-contextforge-gateway` 1.1.2 (2026-11-25) | 2026-11-26 |
| 23 | PyPI JSON API (live) | https://pypi.org/pypi/mcp-proxy/json | `mcp-proxy` 0.15.0 (2026-11-09) | 2026-11-26 |
| 24 | PyPI JSON API (live) | https://pypi.org/pypi/mcpo/json | `mcpo` 0.0.21 (2026-11-25) | 2026-11-26 |
| 25 | npm registry (live) | https://registry.npmjs.org/@modelcontextprotocol/inspector/latest | Inspector 2.16.0 | 2026-11-26 |
| 26 | npm registry (live) | https://registry.npmjs.org/mcp-remote/latest | `mcp-remote` 0.17.1 | 2026-11-26 |
| 27 | npm registry (live) | https://registry.npmjs.org/@cloudflare/workers-oauth-provider/latest | `workers-oauth-provider` 1.4.0 | 2026-11-26 |
| 28 | Docker MCP Gateway | https://github.com/docker/mcp-gateway | 1,649★; tags to `v0.44.3`; `docker mcp` plugin / MCP Gateway | 2026-11-26 |
| 29 | Docker MCP registry/catalog | https://github.com/docker/mcp-registry | 589★; 327 entries under `servers/` | 2026-11-26 |
| 30 | Docker Hub `mcp/` namespace (live) | https://hub.docker.com/v2/repositories/mcp/?page_size=1 | 244 repositories | 2026-11-26 |
| 31 | IBM ContextForge | https://github.com/IBM/mcp-context-forge | Virtual servers, federation, REST-to-MCP, stdio↔SSE, 40+ plugins | 2026-11-26 |
| 32 | Kong Gateway | https://github.com/Kong/kong | OSS latest `3.9.5` (2026-11-19) | 2026-11-26 |
| 33 | Kong AI MCP Proxy plugin | https://developer.konghq.com/plugins/ai-mcp-proxy/ | `ai-mcp-proxy` and `ai-mcp-oauth2` plugins listed in Kong Hub (200) | 2026-11-26 |
| 34 | Agent Router (formerly Envoy AI Gateway) — rename announcement | https://theagentrouter.ai/blog/envoy-ai-gateway-is-now-agent-router | 2026-09-09 rename; Agentic AI Foundation; API groups/CLI unchanged | 2026-11-26 |
| 35 | Agent Router MCP Gateway capability doc | https://theagentrouter.ai/docs/capabilities/mcp/ | Aggregation to one endpoint, OAuth, per-tool-call access control, API-key injection, tool filtering, Envoy LB/rate-limiting/tracing | 2026-11-26 |
| 36 | Envoy AI Gateway repo | https://github.com/envoyproxy/ai-gateway | 2,450★; `v1.3.0` (2026-11-18) | 2026-11-26 |
| 37 | supergateway | https://github.com/supercorp-ai/supergateway | 2,984★; `v4.3.0` (2026-11-24); npm 4.3.0 | 2026-11-26 |
| 38 | LiteLLM | https://github.com/BerriAI/litellm | 63,957★; `v1.111.0` (2026-11-25) | 2026-11-26 |
| 39 | Vercel MCP Adapter | https://github.com/vercel/mcp-adapter | 711★; `v2.4.0` (2026-11-12) | 2026-11-26 |
| 40 | Cloudflare Agents — Remote MCP server guide | https://developers.cloudflare.com/agents/guides/remote-mcp-server/ | Remote MCP hosting on Workers (200); repo 6,153★ | 2026-11-26 |
| 41 | AWS Bedrock AgentCore Gateway | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html | "A secure AI gateway for agents, tools, and models" (200) | 2026-11-26 |
| 42 | Azure API Center — inventory/discover MCP servers | https://learn.microsoft.com/en-us/azure/api-center/register-discover-mcp-server | MCP server inventory as API assets (200) | 2026-11-26 |
| 43 | mcp-use / Manufact | https://www.mcp-use.com | "Open-Source SDK for MCP Apps and Servers" (200) | 2026-11-26 |
| 44 | MCP Apps spec & SDK | https://github.com/modelcontextprotocol/ext-apps | 3,159★; `v2.1.0` (2026-11-10) — UI extension any host/gateway must proxy | 2026-11-26 |
| 45 | OWASP MCP Top 10 — project page | https://owasp.org/www-project-mcp-top-10/ | Project exists (200); roadmap text | 2026-11-26 |
| 46 | OWASP MCP Top 10 — item list | https://github.com/OWASP/www-project-mcp-top-10/tree/main/2025 | MCP01…MCP10 titles as tabulated in §5.1 | 2026-11-26 |
| 47 | OSV API — Python `mcp` (live) | https://api.osv.dev/v1/query | 17 advisories (7 HIGH / 4 MODERATE) | 2026-11-26 |
| 48 | OSV API — `fastmcp` (live) | https://api.osv.dev/v1/query | 16 advisories (1 CRITICAL / 4 HIGH / 5 MODERATE) | 2026-11-26 |
| 49 | OSV API — `@modelcontextprotocol/sdk` (live) | https://api.osv.dev/v1/query | 9 advisories | 2026-11-26 |
| 50 | OSV API — `mcp-contextforge-gateway` (live) | https://api.osv.dev/v1/query | 5 advisories | 2026-11-26 |
| 51 | OSV API — `@modelcontextprotocol/inspector` (live) | https://api.osv.dev/v1/query | 2 advisories | 2026-11-26 |
| 52 | OSV — CVE-2025-6514 / `mcp-remote` | https://api.osv.dev/v1/vulns/GHSA-6xpm-ggf7-wc3p | CRITICAL OS command injection via untrusted MCP server connections, published 2025-07-09 | 2026-11-26 |
| 53 | OSV API — `supergateway` (live) | https://api.osv.dev/v1/query | 0 advisories | 2026-11-26 |
| 54 | OpenTelemetry — MCP attributes (moved notice) | https://github.com/open-telemetry/semantic-conventions/blob/main/docs/registry/attributes/mcp.md | Section "MCP Attributes (Moved)"; `mcp-method-name`, `mcp-protocol-version`, `mcp-resource-uri`, `mcp-session-id` all flagged Deprecated here | 2026-11-26 |
| 54b | OpenTelemetry GenAI semconv — live MCP attributes | https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/registry/attributes/mcp.md | Canonical `mcp.*` attribute definitions; 566★ repo | 2026-11-26 |
| 54c | OTel GenAI semconv — MCP span/metric reports | https://github.com/open-telemetry/semantic-conventions-genai/tree/main/reference/reports | `mcp-client-span.md`, `mcp-server-span.md`, `mcp-client-operation-duration-metric.md` | 2026-11-26 |
| 55 | Glama MCP directory (live) | https://glama.ai/mcp/servers | "131,130 in the Glama Registry" | 2026-11-26 |
| 56 | mcp.so directory (live) | https://mcp.so | "20,915 MCP servers" | 2026-11-26 |
| 57 | Smithery (live) | https://smithery.ai | Title: "Smithery · MCP servers, now part of Arcade"; CLI `smithery-ai/cli` 847★ | 2026-11-26 |
| 58 | WorkOS AuthKit for MCP | https://workos.com/docs/authkit/mcp | Third-party AS for MCP (200) | 2026-11-26 |
| 59 | Descope MCP auth | https://docs.descope.com/mcp | Third-party AS for MCP (200) | 2026-11-26 |
| 60 | Zitadel MCP guide | https://zitadel.com/docs/guides/integrate/mcp | **404** — cited as negative result, not a claim | 2026-11-26 |
| 61 | Google Cloud / Apigee MCP docs | https://cloud.google.com/apigee/docs/api-platform/genai/mcp | **404** — capability marked *unverified* | 2026-11-26 |
| 62 | `lauren-mcp` — supported protocol versions | `src/lauren_mcp/_mcp_version.py:6-7` (this worktree) | `LATEST = "2025-11-25"`, `SUPPORTED = {2024-11-05, 2025-03-26, 2025-06-18, 2025-11-25}` | 2026-11-26 |
| 63 | `lauren-mcp` — session implementation | `src/lauren_mcp/_server/_streamable.py:41,71` (this worktree) | `_SESSION_HEADER = "mcp-session-id"`; `secrets.token_urlsafe(16)` session ids | 2026-11-26 |

### Reproduction commands

```bash
# registry liveness + scale
curl -s https://registry.modelcontextprotocol.io/v0/version
curl -s "https://registry.modelcontextprotocol.io/v0.1/servers?limit=100" | head -c 400
# schema + required fields
curl -s https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json | \
  python3 -c "import json,sys; d=json.load(sys.stdin)['definitions']; print(d['ServerDetail']['required'])"
# vulnerability surface
curl -s https://api.osv.dev/v1/query -H 'Content-Type: application/json' \
  -d '{"package":{"name":"mcp","ecosystem":"PyPI"}}' | python3 -c "import json,sys;print(len(json.load(sys.stdin)['vulns']))"
# spec revisions
gh api repos/modelcontextprotocol/modelcontextprotocol/tags -q '.[].name'
```
