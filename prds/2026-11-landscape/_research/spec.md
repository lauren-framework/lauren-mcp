# MCP Specification Evolution Reference

Complete revision-by-revision record of the Model Context Protocol specification,
`2024-11-05` → `2025-03-26` → `2025-06-18` → `2025-11-25` → `2026-07-28`.

| Field | Value |
| --- | --- |
| Document | `prds/2026-11-landscape/_research/spec.md` |
| Research date (all retrievals) | **2026-11-26** |
| Newest published revision | `2026-07-28` (released 2026-07-28; RC tagged 2026-05-29) |
| Upstream repo | `modelcontextprotocol/modelcontextprotocol` (default branch `main`) |
| Scope | Protocol revisions, SEPs, deprecations, per-side impact |

---

## 0. How this document was built (and how to audit it)

Every claim below is tagged with the evidence class used to establish it:

| Tag | Evidence source | How obtained |
| --- | --- | --- |
| **[C]** | Revision `changelog.mdx` | `raw.githubusercontent.com/.../docs/specification/<rev>/changelog.mdx` |
| **[S]** | Normative TypeScript schema | `raw.githubusercontent.com/.../schema/<rev>/schema.ts`, grepped for string literals |
| **[R]** | GitHub Releases API | `gh api repos/modelcontextprotocol/modelcontextprotocol/releases` |
| **[P]** | SEP markdown frontmatter | `raw.githubusercontent.com/.../seps/<NNNN>-*.md`, fields `Status`/`Type`/`Created` |
| **[D]** | Rendered/raw docs page | `modelcontextprotocol.io/...` and `docs/specification/<rev>/*.mdx` |

Two structural facts frame everything else:

1. **`2024-11-05` has no changelog.** The docs tree contains
   `docs/specification/2024-11-05/{architecture,basic,client,server,index.mdx}` and **no
   `changelog.mdx`**. `https://modelcontextprotocol.io/specification/2024-11-05/changelog`
   returns HTTP **404**. The earliest changelog document in the repository is
   `docs/specification/2025-03-26/changelog.mdx`. **[C][D]** — so the `2024-11-05` → `2025-03-26`
   delta can only be reconstructed *forward* from the `2025-03-26` changelog plus the
   `2024-11-05` schema surface, which is what §2 and §3 do.
2. **Changelog item numbering is per-section and per-revision**, not global. This document
   cites items as `[rev §section #n]` so entries are unambiguous.

### 0.1 Verification hygiene notes

* Issue/PR references in changelogs are *not* automatically SEPs. `SEP-837`
  (client `application_type`) and `SEP-2352` (client credentials bound to issuer) are cited
  by the `2026-07-28` changelog but **no `seps/` file exists for either**, so they are issue/PR
  identifiers, not SEP documents. **[P]**
* Three SEP files carry apparently mistyped `Created` years given their surrounding numbers
  (SEP-2133 `2025-01-21`, SEP-2149 `2025-01-15`, SEP-2575 `2025-06-18` — their neighbours are
  2026-dated). Reported verbatim in §10 and flagged there rather than silently corrected. **[P]**
* Only **one** SEP in `seps/` is not `Final`: **SEP-3398** (`Accepted`, 2026-10-14). See §11. **[P]**

---

## 1. Revision timeline (all dates verified)

| Revision | GitHub tag | Tag published (UTC) | RC tag | RC published (UTC) | Changelog doc exists |
| --- | --- | --- | --- | --- | --- |
| `2024-10-07` | `2024-10-07` | 2024-11-06T10:59:21Z | — | — | no |
| `2024-11-05` | `2024-11-05` | **2025-01-17T20:37:02Z** | — | — | **no** |
| `2024-11-05` (final) | `2024-11-05-final` | 2025-03-26T13:53:30Z | — | — | no |
| `2025-03-26` | `2025-03-26` | **2025-03-26T14:28:27Z** | — | — | yes |
| `2025-06-18` | `2025-06-18` | **2025-06-18T20:09:59Z** | — | — | yes |
| `2025-11-25` | `2025-11-25` | **2025-11-25T21:17:42Z** | `2025-11-25-RC` | 2025-11-15T06:06:55Z | yes |
| `2026-07-28` | `2026-07-28` | **2026-07-28T16:47:49Z** | `2026-07-28-RC` | **2026-05-29T12:51:22Z** | yes |

**[R]** for every timestamp above. Notes:

* The tag named `2024-11-05` was **published 2025-01-17**, i.e. the version label is a
  specification identifier, not a publication date. A second tag, `2024-11-05-final`, was
  published 2025-03-26 — the same day as the `2025-03-26` release — consistent with a
  cleanup/finalisation pass on the prior revision at release time.
* `2024-10-07` was published 2024-11-06, which is why the *next* revision is dated `2024-11-05`.
* RC lead time grew over time: `2025-11-25` had a ~10-day RC window (2025-11-15 → 2025-11-25);
  `2026-07-28` had a **~60-day** RC window (2026-05-29 → 2026-07-28). **[R]**
* Cadence is roughly quarterly for the first three revisions, then ~5 months
  (`2025-06-18` → `2025-11-25`), then ~8 months (`2025-11-25` → `2026-07-28`). As of
  2026-11-26 no `2026-11-*` release or RC tag exists. **[R]**

---

## 2. `2024-11-05` — the origin revision

**Status:** superseded, but still the version string most fielded clients/servers negotiate.

### 2.1 Documented surface (verified from schema and docs, not from a changelog)

* **Transports** (`basic/transports.mdx`): `## stdio`, `## HTTP with SSE`, `## Custom Transports`.
  SSE is the *only* HTTP transport; there is no Streamable HTTP and no session-id header. **[D]**
* **Method strings present in `schema/2024-11-05/schema.ts`** (slash-delimited literals; **[S]**):

  `completion/complete`, `logging/setLevel`, `notifications/cancelled`,
  `notifications/initialized`, `notifications/message`, `notifications/progress`,
  `notifications/resources/updated`, `prompts/get`, `prompts/list`, `ref/prompt`,
  `ref/resource`, `resources/list`, `resources/read`, `resources/subscribe`,
  `resources/templates/list`, `resources/unsubscribe`, `roots/list`,
  `sampling/createMessage`, `tools/call`, `tools/list`.

  Plus the two non-slash methods confirmed by identifier grep: **`initialize`** (4 occurrences)
  and **`ping`** (2 occurrences). **[S]**
* **Not present in this revision:** `tasks/*`, `elicitation/create`, `server/discover`,
  `subscriptions/listen`, structured tool output, resource links, resource indicators,
  JSON Schema 2020-12 dialect, `title`, `_meta` on most types. **[S]**

### 2.2 The one thing that *did* change after `2024-10-07`

The `2024-10-07` → `2024-11-05` step is the version *rename* that established the
`YYYY-MM-DD` revision identifier scheme still in use. Because the `2024-11-05` docs directory
carries no changelog, this reference deliberately makes **no** itemised claim about that
step beyond the tag dates in §1. **[R][D]**

---

## 3. `2025-03-26`

Source: `docs/specification/2025-03-26/changelog.mdx` ("changes … since the previous revision,
2024-11-05"). **[C]**

### 3.1 Major changes

| # | Change | SEP/PR |
| --- | --- | --- |
| 1 | Add a comprehensive **authorization framework** based on **OAuth 2.1** | PR #133 |
| 2 | Replace the **HTTP+SSE** transport with **Streamable HTTP** (single endpoint, POST + optional GET, `Mcp-Session-Id`) | — |
| 3 | Add **tool annotations** for describing tool behaviour (read-only / destructive hints) | PR #185 |

### 3.2 Other schema changes

* Added `message` field to `ProgressNotification` for descriptive status updates. **[C]**
* Added **audio** data support, joining the existing text and image content types. **[C]**

### 3.3 Consequence for later revisions

`2025-03-26` is where HTTP+SSE became **deprecated** in prose. That status persisted
unformally for six revisions' worth of time and was only retroactively formalised in
`2026-07-28` via SEP-2596 (§6.5, §9). **[C]**

---

## 4. `2025-06-18`

Source: `docs/specification/2025-06-18/changelog.mdx` ("since … 2025-03-26"). **[C]**

### 4.1 Major changes

| # | Change | Notes |
| --- | --- | --- |
| 1 | **Remove support for JSON-RPC batching** | Reverses a JSON-RPC 2.0 feature previously allowed |
| 2 | Add support for **structured tool output** | `outputSchema` + `structuredContent` |
| 3 | Classify MCP servers as **OAuth Resource Servers**; add **protected resource metadata** to discover the corresponding Authorization Server | RFC 9728 groundwork |
| 4 | Require MCP clients to implement **Resource Indicators** (RFC 8707) | `resource` parameter on token requests |
| 5 | **Elicitation** — servers can request additional information from users during interactions | First server→user input primitive |
| 6 | Add support for **resource links** in tool call results | `type: "resource_link"` content |
| 7 | Require the negotiated protocol version to be sent via the **`MCP-Protocol-Version`** header on subsequent HTTP requests | Makes per-request versioning explicit |
| 8 | Change **SHOULD** to **MUST** in Lifecycle Operation | Tightens `initialize` flow |

*(Item numbering in 4.1 renumbers the changelog's `1..9` contiguously after the Elicitation
item; the changelog contains 9 major items. The `MCP-Protocol-Version` and
Lifecycle `SHOULD`→`MUST` items are changelog items 8 and 9.)* **[C]**

### 4.2 Other schema changes

* Add `_meta` field to additional interface types and specify proper usage. **[C]**
* Add `context` field to `CompletionRequest`, so completion requests can include
  previously-resolved variables. **[C]**
* Add `title` field for human-friendly display names, so `name` can be used as a stable
  programmatic identifier. **[C]**

### 4.3 Why it matters downstream

Three of these seeds get reaped much later: `_meta` (→ the entire `2026-07-28` stateless
story), `MCP-Protocol-Version` (→ per-request version declaration replacing `initialize`),
and Elicitation (→ folded into MRTR in `2026-07-28`). **[C]**

---

## 5. `2025-11-25`

Source: `docs/specification/2025-11-25/changelog.mdx` ("since … 2025-06-18"). **[C]**
This is the last revision before the stateless/MRTR rewrite, and the revision with the
largest *additive* surface before `2026-07-28`.

### 5.1 Major changes (9 items)

| # | Change | SEP |
| --- | --- | --- |
| 1 | Enhance **authorization server discovery** with **OpenID Connect Discovery 1.0** support | PR #797 |
| 2 | Allow servers to expose **icons** as additional metadata for tools, resources, resource templates and prompts | SEP-973 |
| 3 | Enhance authorization flows with **incremental scope consent** via `WWW-Authenticate` | SEP-835 † |
| 4 | Specify the **format for tool names** | SEP-986 |
| 5 | Update `ElicitResult` and `EnumSchema` to a more standards-based approach; support titled/untitled and single-select/multi-select enums | SEP-1330 |
| 6 | Add support for **URL mode elicitation** (secure out-of-band interactions) | SEP-1036 |
| 7 | Add **tool calling support to sampling** via `tools` and `toolChoice` | SEP-1577 |
| 8 | Add **OAuth Client ID Metadata Documents** as a recommended client registration mechanism | SEP-991 |
| 9 | Add **experimental support for tasks** — durable requests with polling and deferred result retrieval | SEP-1686 |

† No `seps/835-*.md` document exists in the repository; SEP-835 is cited only by number, so its
full text cannot be verified from the SEP corpus. **[P][C]**

### 5.2 Minor changes (10 items)

| # | Change | SEP |
| --- | --- | --- |
| 1 | Clarify that stdio servers may use **stderr for all types of logging**, not just errors | — |
| 2 | Add optional **`description`** field to `Implementation`, aligning with registry `server.json` | — |
| 3 | Clarify servers **MUST return HTTP 403 Forbidden** for invalid `Origin` headers in Streamable HTTP | — |
| 4 | Updated **Security Best Practices** guidance | — |
| 5 | Clarify that **input validation errors** should be **Tool Execution Errors**, not Protocol Errors, to enable model self-correction | SEP-1303 |
| 6 | Support **SSE polling** by allowing servers to disconnect at will | SEP-1699 |
| 7 | Clarify SEP-1699: GET streams support polling; resumption always via GET regardless of stream origin; **event IDs must encode stream identity**; disconnection includes server-initiated closure | SEP-1699 / Issue #1847 |
| 8 | Align **OAuth 2.0 Protected Resource Metadata** discovery with RFC 9728 — `WWW-Authenticate` header optional with `.well-known` fallback | SEP-985 |
| 9 | Support **default values** in all primitive types (string, number, enum) for elicitation schemas | SEP-1034 |
| 10 | Establish **JSON Schema 2020-12** as the default dialect for MCP schema definitions | SEP-1613 |

### 5.3 Other schema changes

* Decouple request payload from RPC method definition — SEP-1319. **[C]**

### 5.4 Governance and process updates

1. Formalize MCP governance structure — SEP-932.
2. Establish shared communication practices and guidelines — SEP-994.
3. Formalize **Working Groups and Interest Groups** — SEP-1302.
4. Establish the **SDK tiering system** with feature-support and maintenance commitments — SEP-1730.

### 5.5 Signature of this revision

`2025-11-25` is where **statefulness is maximised**: sessions, `resources/subscribe`,
`logging/setLevel`, `ping`, `roots/list`, SSE resumability with `Last-Event-ID`, and
experimental tasks all coexist. Six months later, `2026-07-28` removes or relocates almost
every one of them. **[C][S]**

Method-string count in `schema/2025-11-25/schema.ts` peaks at **29** slash-delimited literals,
versus 20 in `2024-11-05` and 22 in `2026-07-28`. **[S]**

---

## 6. `2026-07-28` — the current revision

Source: `docs/specification/2026-07-28/changelog.mdx` ("since … 2025-11-25"). **[C]**
Released 2026-07-28T16:47:49Z; RC tagged 2026-05-29T12:51:22Z. **[R]**

This is the structural break. It converts MCP from a *session-oriented, server-push* protocol
into a **stateless, client-driven, cacheable** one.

### 6.1 Major changes (9 items)

| # | Change | SEP |
| --- | --- | --- |
| 1 | **Remove protocol-level sessions and the `Mcp-Session-Id` header** from Streamable HTTP. List endpoints (`tools/list`, `resources/list`, `prompts/list`) no longer depend on a session | SEP-2567 |
| 2 | **Make MCP stateless**: remove the `initialize`/`notifications/initialized` handshake. Every request carries its protocol version and client capabilities via `_meta` | SEP-2575 |
| 3 | Add **`server/discover`**: servers **MUST** implement this RPC to advertise supported protocol versions, capabilities and identity; clients **MAY** call it | SEP-2575 |
| 4 | Replace the **HTTP GET endpoint** and **`resources/subscribe`/`resources/unsubscribe`** with **`subscriptions/listen`** — a single long-lived POST-response stream | SEP-2575 |
| 5 | Remove **`ping`**, **`logging/setLevel`**, and **`notifications/roots/list_changed`**. Log level is now per-request | SEP-2575 |
| 6 | Move experimental **tasks** out of the core protocol into an official extension **`io.modelcontextprotocol/tasks`**; the redesigned extension replaces the earlier design | SEP-2663 |
| 7 | Introduce **Multi Round-Trip Requests (MRTR)**, replacing the previous approach of sending **server-initiated requests** (`roots/list`, `sampling/createMessage`, `elicitation/create`) | SEP-2322 |
| 8 | All results now carry a required **`resultType`**: `"complete"` for ordinary results, `"input_required"` for MRTR interim responses | SEP-2322 |
| 9 | Remove **SSE stream resumability and message redelivery** (`Last-Event-ID` header and SSE event IDs). A broken response stream must be retried as a new request | SEP-2575 |

### 6.2 Minor changes (12 items)

| # | Change | SEP |
| --- | --- | --- |
| 1 | Add **`extensions`** field to `ClientCapabilities` and `ServerCapabilities` for optional extensions beyond the core protocol | (SEP-2133 lineage) |
| 2 | Document **OpenTelemetry** trace-context propagation conventions for `_meta` keys (`traceparent`, `tracestate`, `baggage`) | SEP-414 |
| 3 | Servers **SHOULD** return tools from `tools/list` in **deterministic order** to enable client-side caching | — |
| 4 | Require standard MCP request headers **`Mcp-Method`**, **`Mcp-Name`** on Streamable HTTP POST requests; add support for custom headers from tool parameters (`x-mcp-header`) | SEP-2243 |
| 5 | Require **`ttlMs`** and **`cacheScope`** on results from `server/discover`, `tools/list`, `prompts/list`, `resources/list`, `resources/read` (cacheable results) | SEP-2549 |
| 6 | Change **resource not found** error code from **`-32002` to `-32602`** (Invalid Params) to align with JSON-RPC | SEP-2164 |
| 7 | Authorization servers **SHOULD** include the **`iss`** parameter in authorization responses per RFC 9207 | SEP-2468 |
| 8 | Require clients to specify an appropriate **`application_type`** during Dynamic Client Registration to avoid OIDC redirect-URI conflicts | SEP-837 |
| 9 | Clarify that **client credentials are bound to the authorization server that issued them**: clients **MUST** key persisted credentials by issuer identity | SEP-2352 |
| 10 | Loosen `inputSchema`/`outputSchema` to allow **any JSON Schema 2020-12 keywords** | SEP-2106 |
| 11 | Remove **`notifications/elicitation/complete`** and the **`elicitationId`** field of URL-mode elicitation, both introduced in `2025-11-25` | — |
| 12 | Define an **error code allocation policy** partitioning the JSON-RPC server-error range | — |

### 6.3 Other schema changes

* `schema.json` now correctly reflects that the TypeScript definitions of
  `minimum`/`maximum`/`default` are `number`s, not only `integer`s. **[C]**

### 6.4 Deprecations introduced by this revision (4 items)

| # | Item | SEP | Notes |
| --- | --- | --- | --- |
| 1 | **Roots, Sampling and Logging** deprecated | SEP-2577 | Remain fully functional during the deprecation window; new implementations should not adopt |
| 2 | **HTTP+SSE** transport (deprecated in prose since `2025-03-26`) **reclassified as Deprecated** under the lifecycle policy | SEP-2596 | Migration target: Streamable HTTP |
| 3 | `includeContext` values `"thisServer"` and `"allServers"` (soft-deprecated since `2025-11-25`) **reclassified as Deprecated** | SEP-2596 | Migration: omit the field or use `"none"` |
| 4 | **OAuth 2.0 Dynamic Client Registration (RFC 7591)** deprecated as a client registration mechanism | PR #2858 | Migration target: Client ID Metadata Documents |

### 6.5 Governance and process updates

1. Adopt a **specification feature lifecycle and deprecation policy** defining the
   **Active**, **Deprecated** and **Removed** states, with a **minimum twelve-month**
   deprecation window — SEP-2596.

### 6.6 Process changes

1. Formalize the **PR-based SEP workflow**: markdown files in `seps/`, PR-derived numbering,
   sponsor responsibilities, and status management via PR — SEP-1850.

### 6.7 Schema-level confirmation of the `2026-07-28` removals

Grepping `schema/2026-07-28/schema.ts` (**[S]**) confirms, in the normative schema itself:

| Token | `2024-11-05` | `2025-11-25` | `2026-07-28` |
| --- | --- | --- | --- |
| `initialize` | 4 | present | **0** |
| `ping` | 2 | present | **0** |
| `logging/setLevel` | present | present | **absent** |
| `notifications/initialized` | present | present | **absent** |
| `resources/subscribe` | present | present | absent as a method — **1 hit only, inside the doc comment** "Replaces the former `resources/subscribe` RPC" |
| `resources/unsubscribe` | present | present | **absent** |
| `server/discover` | 0 | 0 | **10** |
| `subscriptions/listen` | 0 | 0 | **20** |
| `resultType` | 0 | 0 | **2** |
| `ttlMs` / `cacheScope` | 0 / 0 | 0 / 0 | **1 / 1** |
| `-32020` (reserved range) | 0 | 0 | **3** |
| `roots/list`, `sampling/createMessage` | present | present | **still present** (deprecated, not removed) |
| `notifications/cancelled` | present | present | **present** |
| `elicitation/create` | 0 | present | present as the `ElicitRequest` interface (`method: "elicitation/create"`), reached now via MRTR `input_required` rather than a server-initiated request |

**Nuance worth flagging:** item 7 of §6.1 says MRTR "replaces the previous approach of sending
server-initiated requests, such as `roots/list`, `sampling/createMessage`, `elicitation/create`",
yet `schema.ts` still declares `ElicitRequest` with `method: "elicitation/create"` and still
declares `roots/list`/`sampling/createMessage`. The consistent reading is that these are
**no longer server-initiated requests over a bidirectional channel** — the *payload types*
survive because they are now transported inside `resultType: "input_required"` round trips
(and, for Roots/Sampling, because SEP-2577 keeps them functional during the deprecation
window). Treat "server-initiated request removed" as a change in **who initiates and how**,
not as deletion of the schema types. **[C][S]**

`Mcp-Method`/`Mcp-Name` and `Mcp-Session-Id` produce **0** hits in `schema.ts` for every
revision — HTTP header names are normative in the transport docs, not in the TS schema, so
their presence/absence must be evidenced from changelog text (§6.1 #1, §6.2 #4), not by grep. **[S][C]**

---

## 7. Method surface across revisions (grep-verified)

Counts are of match-lines for the literal token in `schema/<rev>/schema.ts`. `—` = 0 hits.
Non-slash methods (`initialize`, `ping`) were confirmed by separate identifier grep. **[S]**

| Surface | 2024-11-05 | 2025-03-26 | 2025-06-18 | 2025-11-25 | 2026-07-28 | Fate |
| --- | --- | --- | --- | --- | --- | --- |
| `initialize` | 4 | ✓ | ✓ | ✓ | **—** | **Removed** (SEP-2575) — replaced by per-request `_meta` |
| `notifications/initialized` | ✓ | ✓ | ✓ | ✓ | **—** | **Removed** (SEP-2575) |
| `ping` | 2 | ✓ | ✓ | ✓ | **—** | **Removed** (SEP-2575) |
| `logging/setLevel` | ✓ | ✓ | ✓ | ✓ | **—** | **Removed** (SEP-2575); log level per-request |
| `resources/subscribe` | ✓ | ✓ | ✓ | ✓ | **—** (doc-comment only) | **Removed** → `subscriptions/listen` |
| `resources/unsubscribe` | ✓ | ✓ | ✓ | ✓ | **—** | **Removed** → `subscriptions/listen` |
| HTTP GET stream | ✓ (SSE) | ✓ | ✓ | ✓ | **—** | **Removed** (SEP-2575) |
| `Last-Event-ID` resumability | ✓ | ✓ | ✓ | ✓ | **—** | **Removed** (SEP-2575) |
| `server/discover` | — | — | — | — | **10** | **Added**, servers **MUST** |
| `subscriptions/listen` | — | — | — | — | **20** | **Added** |
| `notifications/subscriptions/acknowledged` | — | — | — | — | ✓ | **Added** |
| `elicitation/create` | — | — | ✓ | ✓ | ✓ (via MRTR) | **Reshaped** by SEP-2322 |
| `roots/list` | ✓ | ✓ | ✓ | ✓ | ✓ | **Deprecated** (SEP-2577) |
| `sampling/createMessage` | ✓ | ✓ | ✓ | ✓ | ✓ | **Deprecated** (SEP-2577) |
| `tasks/*` (experimental) | — | — | — | ✓ (SEP-1686) | → extension | **Relocated** to `io.modelcontextprotocol/tasks` (SEP-2663) |
| `notifications/cancelled` | ✓ | ✓ | ✓ | ✓ | ✓ | **Unchanged** — survives all five revisions |
| `notifications/progress` | ✓ | ✓ | ✓ | ✓ | ✓ | Unchanged |
| `completion/complete` | ✓ | ✓ | ✓ | ✓ | ✓ | Unchanged |
| `prompts/{list,get}`, `resources/{list,read,templates/list}`, `tools/{list,call}` | ✓ | ✓ | ✓ | ✓ | ✓ | Unchanged |
| Slash-literal total | 20 | 20 | 21 | **29** | 22 | Peaks in `2025-11-25` |

**Correctness note on `notifications/cancelled`:** it is present in the `2024-11-05` schema and
still present in `2026-07-28`; §6.1 does **not** remove it. The only cancellation-adjacent
removal in `2026-07-28` is the *stream* resumability mechanism. Likewise **`$/cancelRequest`
does not exist in any MCP revision** — that is an LSP method and appears nowhere in the MCP
schema or changelogs. **[S][C]**

---

## 8. Cross-cutting evolution tracks

### 8.1 Transport

| Revision | Transports | HTTP details |
| --- | --- | --- |
| `2024-11-05` | stdio, **HTTP with SSE**, custom | Two endpoints (GET SSE + POST); no session header |
| `2025-03-26` | stdio, **Streamable HTTP**, custom | One endpoint; POST + optional GET; `Mcp-Session-Id`; SSE deprecated |
| `2025-06-18` | + required `MCP-Protocol-Version` header | Version declared per HTTP request |
| `2025-11-25` | + SSE polling / server-initiated disconnect (SEP-1699) | Event IDs encode stream identity; resumption via GET |
| `2026-07-28` | stdio, **Streamable HTTP** only ("custom" still allowed) | **No GET endpoint, no session header, no resumability**; `Mcp-Method`/`Mcp-Name` required; `ttlMs`+`cacheScope` on results |

**[C][D][S]** — SSE's retirement story spans three revisions: deprecated in prose at
`2025-03-26`, formally Deprecated under policy at `2026-07-28` (SEP-2596), removable no earlier
than the first revision released on/after **2027-07-28**.

### 8.2 Session and statefulness

`2024-11-05` already had an `initialize` handshake but no HTTP session concept.
`2025-03-26` added `Mcp-Session-Id`. `2026-07-28` removes **both** sessions and the
`initialize` handshake: state is carried per-request (client capabilities + protocol version in
`_meta`), and any durable state becomes an explicit **state handle** (SEP-2567's "sessionless
MCP via explicit state handles") or a task in the tasks extension. **[C]**

### 8.3 Lifecycle and discovery

* `initialize` handshake: `2024-11-05` → `2025-11-25`; `SHOULD`→`MUST` in `2025-06-18`;
  **removed** in `2026-07-28`.
* `server/discover`: **new in `2026-07-28`**, servers **MUST** implement it; clients **MAY** call
  it. It advertises supported protocol versions, capabilities and identity — i.e. it absorbs
  the negotiation role of `initialize` while remaining optional to call. **[C]**

### 8.4 Server-initiated interaction → MRTR

| Revision | How the server asks the client/user for something |
| --- | --- |
| `2024-11-05` | Server→client requests: `roots/list`, `sampling/createMessage` (requires `initialize` + capabilities) |
| `2025-06-18` | + `elicitation/create` |
| `2025-11-25` | + URL-mode elicitation (SEP-1036), sampling with tools (SEP-1577) |
| `2026-07-28` | **MRTR (SEP-2322)**: no server-initiated request channel; every result carries `resultType`, and `"input_required"` means "answer these inputs and retry". `notifications/elicitation/complete` and `elicitationId` are removed |

The consequence is that a *single* logical interaction may now span multiple client requests,
and servers become **stateless between rounds** — the client replays the request with the
requested inputs attached. **[C]**

### 8.5 Subscriptions

`resources/subscribe` + `resources/unsubscribe` + `notifications/resources/updated`
(`2024-11-05` … `2025-11-25`) are replaced by **`subscriptions/listen`**: one long-lived
POST-response stream carrying `notifications/subscriptions/acknowledged` and update
notifications. **[C][S]**

### 8.6 Tasks and extensions

* `2025-11-25`: tasks shipped as **experimental core protocol** (SEP-1686) — durable requests,
  polling, deferred result retrieval.
* `2026-07-28`: tasks **moved out of core** into the extension
  **`io.modelcontextprotocol/tasks`** (SEP-2663), and the core gained an **`extensions`** field on
  `ClientCapabilities`/`ServerCapabilities` plus an extensions overview page
  (`modelcontextprotocol.io/extensions/overview`, HTTP 200 as of 2026-11-26). **[C][S][D]**
* Extension maturity is governed by **SEP-3392 (Extension Lifecycle, Final)**: an extension
  starts **Experimental**, may advance to **Beta**, and then becomes Final or is retired. **[P]**

### 8.7 Authorization (largest *additive* track)

| Revision | Authorization change |
| --- | --- |
| `2024-11-05` | none (no authorization chapter) |
| `2025-03-26` | OAuth 2.1 framework (PR #133) |
| `2025-06-18` | Servers are **OAuth Resource Servers**; protected-resource metadata; clients implement **Resource Indicators** (RFC 8707) |
| `2025-11-25` | **OIDC Discovery 1.0** (PR #797); **Client ID Metadata Documents** (SEP-991); RFC 9728 alignment with `.well-known` fallback (SEP-985); incremental scope consent via `WWW-Authenticate` (SEP-835); 403 on invalid `Origin` |
| `2026-07-28` | `iss` parameter recommended, RFC 9207 (SEP-2468); `application_type` required for DCR (SEP-837); credentials keyed by issuer (SEP-2352); **DCR (RFC 7591) deprecated** in favour of Client ID Metadata Documents (PR #2858) |

So the single biggest functional arc in the protocol is authorization, and its newest phase is
*replacing* dynamic client registration. **[C]**

### 8.8 Result envelopes: `resultType`, `ttlMs`, `cacheScope`

* `resultType` is **required on all results** from `2026-07-28`: `"complete"` |
  `"input_required"` (SEP-2322). Absent in every earlier revision. **[S]**
* `ttlMs` + `cacheScope` are required on `server/discover`, `tools/list`, `prompts/list`,
  `resources/list`, `resources/read` results from `2026-07-28` (SEP-2549) — i.e. **cacheability
  becomes part of the protocol contract**, matched by the `SHOULD`-deterministic tool ordering
  (§6.2 #3). **[C][S]**

### 8.9 Error codes

| Code | `2024-11-05` … `2025-11-25` | `2026-07-28` |
| --- | --- | --- |
| `-32002` | **Resource not found** | **Reassigned** — no longer resource-not-found |
| `-32602` (Invalid Params) | standard JSON-RPC only | **Now also resource not found** (SEP-2164) |
| `-32020`…`-32099` | unallocated | **Reserved** by a new error-code allocation policy |

Grep confirms `-32020` appears only in the `2026-07-28` schema (3 hits), and `-32602` goes from
1 → 2 occurrence. **[S][C]**

### 8.10 Schema dialect

`2025-06-18` added `title`; `2025-11-25` made **JSON Schema 2020-12 the default dialect**
(SEP-1613) and `2026-07-28` loosened `inputSchema`/`outputSchema` to accept **any** 2020-12
keywords (SEP-2106) and fixed `minimum`/`maximum`/`default` to be `number`, not `integer`. **[C]**

### 8.11 Governance and process

| Revision | Governance/process milestone |
| --- | --- |
| `2025-11-25` | Formal governance (SEP-932), communication practices (SEP-994), Working/Interest Groups (SEP-1302), **SDK tiering** (SEP-1730) |
| `2026-07-28` | **Feature lifecycle & deprecation policy** with three states and a ≥12-month window (SEP-2596); **PR-based SEP workflow** with `seps/*.md`, PR-derived numbering (SEP-1850) |

The PR-based SEP workflow is why this document can cite `seps/NNNN-*.md` files at all: the
corpus contains **46** SEP documents, of which **45 are `Final`** and 1 is `Accepted`. **[P]**

---

## 9. Deprecation and removal schedule (SEP-2596 + SEP-2577)

### 9.1 The policy

SEP-2596 (*Specification Feature Lifecycle and Deprecation Policy*, `Final`, `Process`,
created 2026-04-17) introduces **[P]**:

* Three feature states: **Active**, **Deprecated**, **Removed**.
* A **minimum deprecation window**, specified as "the number of months, at least **twelve**".
* Documentation obligations at each transition, plus the documentation produced for a
  deprecation (replacement target, migration path, earliest removal).
* Scope: "protocol messages, capabilities, transports, schema types, and normative behavioral
  requirements." It explicitly does **not** govern non-core material.
* Removal is "a Core Maintainer decision at release preparation, not an automatic event when
  the grace period [ends]".

Rendered policy page: `https://modelcontextprotocol.io/community/feature-lifecycle` (HTTP 200,
2026-11-26). **[D]**

### 9.2 The live registry (`/specification/2026-07-28/deprecated`)

The `2026-07-28` docs add a dedicated registry page whose table columns are
**Feature | Deprecation SEP | Deprecated in | Migration path | Earliest removal**. Verbatim
values (**[D]**):

| Feature | Deprecation SEP | Deprecated in | Migration path | Earliest removal |
| --- | --- | --- | --- | --- |
| **Roots** | SEP-2577 | `2026-07-28` | Pass directories or files via tool parameters | First revision released on or after **2027-07-28** |
| **Sampling** | SEP-2577 | `2026-07-28` | (see SEP-2577) | First revision released on or after **2027-07-28** |
| **Logging** | SEP-2577 | `2026-07-28` | (see SEP-2577) | First revision released on or after **2027-07-28** |
| **Dynamic Client Registration** | PR #2858 | `2026-07-28` | Client ID Metadata Documents | First revision released on or after **2027-07-28** |
| `includeContext: "thisServer"` / `"allServers"` (Sampling) | SEP-2596 | `2025-11-25` | Omit the field or use `"none"` | Follows Sampling (SEP-2577) |

And the `## Removed` section states, verbatim: **"No features have been removed under this
policy yet."** **[D]** — i.e. as of 2026-11-26 nothing has actually been deleted *by this
mechanism*; the `2026-07-28` removals in §6.1 were made directly by revision-level SEPs
(SEP-2575, SEP-2567, SEP-2663, SEP-2322), not through the deprecation window.

### 9.3 SEP-2577 guarantees

SEP-2577 (*Deprecate Roots, Sampling, and Logging*, `Final`, `Standards Track`, created
2026-04-14) states that the deprecated features remain **functional in all specification
versions released within one year** of the deprecating release, and that they are supported for
**one year past their original release date**. **[P]**

Scope of SEP-2577, verbatim from the SEP: **Roots** (`roots/list`,
`notifications/roots/list_changed`), **Sampling** (`sampling/createMessage`,
`ClientCapabilities.tasks.requests.sampling`), **Logging** (`logging/setLevel`, …). **[P]**

### 9.4 Practical timeline as of 2026-11-26

| Item | State | Earliest removal |
| --- | --- | --- |
| Roots, Sampling, Logging | Deprecated | First revision released on/after 2027-07-28 |
| HTTP+SSE transport | Deprecated (formally since `2026-07-28`; in prose since `2025-03-26`) | First revision released on/after 2027-07-28 |
| OAuth DCR (RFC 7591) | Deprecated | First revision released on/after 2027-07-28 |
| `includeContext` `"thisServer"`/`"allServers"` | Deprecated (soft since `2025-11-25`) | Follows Sampling |
| Everything removed in `2026-07-28` (sessions, `initialize`, `ping`, GET stream, resumability, `resources/(un)subscribe`, `logging/setLevel`) | **Already removed** | n/a |

**Bottom line for implementers:** the only *forward* deadline visible today is
**2027-07-28**, and it applies to Roots/Sampling/Logging, HTTP+SSE, and DCR. Any implementation
planning through 2027 can treat those four as "must migrate" and everything else in `2026-07-28`
as "must already have migrated".

---

## 10. SEP index (cited by this document; frontmatter verified)

All rows `Status: Final` unless marked. `Type` and `Created` are verbatim from each SEP's
frontmatter. "First revision" is the revision whose changelog first cites the SEP. **[P][C]**

| SEP | Title | Type | Created | First revision |
| --- | --- | --- | --- | --- |
| 414 | Document OpenTelemetry Trace Context Propagation Conventions | Standards Track | 2025-04-25 | `2026-07-28` |
| 835 | *(no `seps/` file; cited for incremental scope consent)* | — | — | `2025-11-25` |
| 932 | Model Context Protocol Governance | Process | 2025-07-08 | `2025-11-25` |
| 973 | Expose additional metadata for Implementations, Resources, Tools and Prompts | Standards Track | 2025-07-15 | `2025-11-25` |
| 985 | OAuth 2.0 Protected Resource Metadata alignment (RFC 9728) | Standards Track | 2025-07-16 | `2025-11-25` |
| 986 | Specify Format for Tool Names | Standards Track | 2025-07-16 | `2025-11-25` |
| 991 | Enable URL-based Client Registration using OAuth Client ID Metadata Documents | Standards Track | 2025-07-07 | `2025-11-25` |
| 994 | Shared Communication Practices | Process | 2025-07-17 | `2025-11-25` |
| 1034 | Support default values for all primitive types in elicitation schemas | Standards Track | 2025-07-22 | `2025-11-25` |
| 1036 | URL Mode Elicitation for secure out-of-band interactions | Standards Track | 2025-07-22 | `2025-11-25` |
| 1302 | Formalize Working Groups and Interest Groups in MCP Governance | Standards Track | 2025-08-05 | `2025-11-25` |
| 1303 | Input Validation Errors as Tool Execution Errors | Standards Track | 2025-08-05 | `2025-11-25` |
| 1319 | Decouple Request Payload from RPC Methods Definition | Standards Track | 2025-08-08 | `2025-11-25` |
| 1330 | Elicitation Enum Schema Improvements and Standards Compliance | Standards Track | 2025-08-11 | `2025-11-25` |
| 1577 | Sampling With Tools | Standards Track | 2025-09-30 | `2025-11-25` |
| 1613 | Establish JSON Schema 2020-12 as Default Dialect for MCP | Standards Track | 2025-10-06 | `2025-11-25` |
| 1686 | Tasks | Standards Track | 2025-10-20 | `2025-11-25` |
| 1699 | Support SSE polling via server-side disconnect | Standards Track | 2025-10-22 | `2025-11-25` |
| 1730 | SDKs Tiering System | Standards Track | 2025-10-29 | `2025-11-25` |
| 1850 | PR-Based SEP Workflow | Process | 2025-11-20 | `2026-07-28` |
| 2106 | Tools `inputSchema` & `outputSchema` Conform to JSON Schema 2020-12 | Standards Track | 2026-01-06 | `2026-07-28` |
| 2133 | Extensions | Standards Track | **2025-01-21** ⚠ | `2026-07-28` |
| 2164 | Standardize Resource Not Found Error Code | Standards Track | 2026-01-28 | `2026-07-28` |
| 2243 | HTTP Header Standardization for Streamable HTTP Transport | Standards Track | 2026-02-04 | `2026-07-28` |
| 2322 | Multi Round-Trip Requests | Standards Track | 2026-02-03 | `2026-07-28` |
| 2468 | Recommend Issuer (`iss`) Parameter in MCP Auth Responses | Standards Track | 2026-03-25 | `2026-07-28` |
| 2549 | TTL for List Results | Standards Track | 2026-04-09 | `2026-07-28` |
| 2567 | Sessionless MCP via Explicit State Handles | Standards Track | 2026-03-11 | `2026-07-28` |
| 2575 | Make MCP Stateless | Standards Track | **2025-06-18** ⚠ | `2026-07-28` |
| 2577 | Deprecate Roots, Sampling, and Logging | Standards Track | 2026-04-14 | `2026-07-28` |
| 2596 | Specification Feature Lifecycle and Deprecation Policy | Process | 2026-04-17 | `2026-07-28` |
| 2663 | Tasks Extension | Extensions Track | 2026-04-27 | `2026-07-28` |
| 3392 | Extension Lifecycle | Process | 2026-09-25 | **(after `2026-07-28`)** — see §11 |
| 3398 | Release Cycle Updates | Process | 2026-09-17 | **(after `2026-07-28`)** — see §11 |

⚠ = the `Created` year appears mistyped in the SEP file (its numeric neighbours are 2026-dated,
and the `2026-07-28` changelog behaviour is described as new). Reported as-found.

Corpus size: **46** SEP markdown files exist in `seps/`; **45** are `Final` and **1** is
`Accepted` (SEP-3398). Two of the numbers cited by the `2026-07-28` changelog — **SEP-837**
and **SEP-2352** — have **no** SEP file, as does **SEP-835**. **[P]**

---

## 11. Merged but not in any released revision (as of 2026-11-26)

These three SEPs were created **after** the `2026-07-28` release date, so they are not part of
any published specification revision yet: **[P][R]**

| SEP | Title | Status | Type | Created | Notes |
| --- | --- | --- | --- | --- | --- |
| 3392 | Extension Lifecycle | Final | Process | 2026-09-25 | Experimental → Beta → Final/retired lifecycle for extensions. Pairs with the `io.modelcontextprotocol/tasks` extension from `2026-07-28` |
| 3398 | **Release Cycle Updates** | **Accepted** (2026-10-14) | Process | 2026-09-17 | The only non-`Final` SEP in the corpus. Changes the *release cadence/process*, not wire behaviour |
| 3415 | Events Extension | Final | Extensions Track | 2026-10-05 | New extension; not in `2026-07-28` |

**Implication:** the *next* revision (not yet tagged as of 2026-11-26) will be the first to be
produced under the SEP-3398 process and will be the first where an extension beyond *tasks* is
an official, lifecycle-governed artefact. Nothing indicates a `2026-11-*` tag exists yet. **[R]**

---

## 12. Anomalies, gaps and traps

1. **No `2024-11-05` changelog exists** (404 on the site; no `changelog.mdx` in the docs tree).
   Any "2024-11-05 → 2025-03-26 diff" must be reconstructed, never quoted. **[C][D]**
2. **Version label ≠ release date.** Tag `2024-11-05` was published 2025-01-17; tag
   `2024-11-05-final` was published 2025-03-26. **[R]**
3. **"Deprecated" was used informally before `2026-07-28`.** HTTP+SSE was called deprecated in
   prose from `2025-03-26`; `includeContext` values were "soft-deprecated" from `2025-11-25`.
   Neither had a removal guarantee until SEP-2596 codified the 12-month window. **[C]**
4. **Server-initiated requests are gone; their payload types are not.** `roots/list`,
   `sampling/createMessage` and `ElicitRequest`/`elicitation/create` still exist as schema types
   in `2026-07-28`. See §6.7. **[S]**
5. **Header names cannot be grepped from `schema.ts`.** `Mcp-Session-Id`, `Mcp-Method`,
   `Mcp-Name`, `Last-Event-ID` return 0 hits in *every* revision's schema; they are normative in
   transport docs only. **[S]**
6. **`notifications/cancelled` is not the removed thing.** It exists in `2024-11-05` and in
   `2026-07-28`. `$/cancelRequest` has **never** existed in MCP (it is an LSP method). **[S]**
7. **`tasks` moved, and was redesigned.** `2025-11-25` tasks (SEP-1686, experimental core) is
   *not* the same design as the `io.modelcontextprotocol/tasks` extension (SEP-2663). Treat
   `2025-11-25` task implementations as needing rework, not just re-plumbing. **[C]**
8. **`2025-11-25` has the widest method surface** (29 slash literals) — the protocol
   *contracted* in `2026-07-28` (22) while *gaining* caching, discovery, MRTR and extensions. **[S]**
9. **Renumbered error code is a silent break.** A `2025-11-25`-era server returning `-32002`
   for a missing resource will be misinterpreted by a strict `2026-07-28` client, and
   `-32020`…`-32099` is now reserved territory. **[C][S]**

---

## 13. Impact: server-side vs client-side vs both

Legend: **S** = server must change; **C** = client must change; **B** = both; **—** = no
implementation change (documentation/behaviour clarity only).

| Change (revision) | Side | Why |
| --- | --- | --- |
| OAuth 2.1 authorization framework (`2025-03-26`) | **B** | Server becomes an OAuth resource server; client must run the flow |
| Streamable HTTP replaces HTTP+SSE (`2025-03-26`) | **B** | New endpoint/shape on server; new transport on client |
| Remove JSON-RPC batching (`2025-06-18`) | **B** | Neither side may send batched arrays any more |
| Structured tool output (`2025-06-18`) | **B** | Server declares/produces `outputSchema`+`structuredContent`; client parses |
| Server = OAuth Resource Server + protected-resource metadata (`2025-06-18`) | **B** | Server publishes metadata; client discovers AS |
| Resource Indicators, RFC 8707 (`2025-06-18`) | **C** | Client must send `resource` on token requests |
| Elicitation (`2025-06-18`) | **B** | Server requests; client UI must render and answer |
| Resource links in tool results (`2025-06-18`) | **B** | Server emits; client renders |
| `MCP-Protocol-Version` header (`2025-06-18`) | **B** | Client sends; server validates |
| `should`→`must` in lifecycle (`2025-06-18`) | **B** | Conformance tightening |
| OIDC Discovery (`2025-11-25`) | **B** | Client uses OIDC discovery; server/AS advertises it |
| Icons + `Implementation.description` (`2025-11-25`) | **S** | Server-supplied metadata |
| Tool-name format (`2025-11-25`) | **B** | Server names tools; client validates |
| Elicitation enum rework, URL-mode elicitation, primitive defaults (`2025-11-25`) | **B** | New schema + new flow |
| Sampling with tools (`2025-11-25`) | **B** | Server asks with `tools`/`toolChoice`; client honours |
| Client ID Metadata Documents (`2025-11-25`), recommended again in `2026-07-28` | **B** | Client hosts/presents CIMD; server validates |
| Experimental tasks (`2025-11-25`) | **B** | New RPC family both sides; **superseded** in `2026-07-28` |
| Input validation as tool-execution errors (`2025-11-25`) | **B** | Server error shape; client interpretation |
| SSE polling / server disconnect (`2025-11-25`) | **B** | Server may disconnect; client resumes via GET |
| JSON Schema 2020-12 default dialect (`2025-11-25`) | **B** | Schema authoring + validation |
| **Remove `Mcp-Session-Id` + protocol sessions** (`2026-07-28`) | **B** | Server drops session store; client stops sending |
| **Remove `initialize`/`notifications/initialized`** (`2026-07-28`) | **B** | Client sends version+capabilities per request; server parses `_meta` |
| **`server/discover` MUST** (`2026-07-28`) | **S** (MUST) / **C** (MAY) | Server **must** implement; client **may** call |
| **Remove HTTP GET endpoint** (`2026-07-28`) | **B** | Server stops exposing it; client stops using it |
| **`subscriptions/listen` replaces `resources/(un)subscribe`** (`2026-07-28`) | **B** | One long-lived POST stream replaces the subscribe RPCs |
| **Remove `ping`** (`2026-07-28`) | **B** | Liveness must move to transport/HTTP level |
| **Remove `logging/setLevel`** (`2026-07-28`) | **B** | Log level per-request; server no longer stores it |
| **Remove `notifications/roots/list_changed`** (`2026-07-28`) | **B** | Roots are deprecated anyway |
| **Tasks → `io.modelcontextprotocol/tasks` extension** (`2026-07-28`) | **B** | Extension negotiation + new design; `extensions` capability field |
| **MRTR replaces server-initiated requests** (`2026-07-28`) | **B** | Server returns `resultType:"input_required"`; client answers and retries |
| **`resultType` required on all results** (`2026-07-28`) | **B** | Server must stamp every result; client must branch on it |
| **Remove SSE resumability / `Last-Event-ID`** (`2026-07-28`) | **B** | Server cannot replay; client must retry as a new request |
| **`ttlMs` + `cacheScope` required** (`SEP-2549`) | **B** | Server sets them; client caches by them |
| **Deterministic `tools/list` ordering** (`2026-07-28`) | **S** | Server-side ordering discipline |
| **`Mcp-Method`/`Mcp-Name` + `x-mcp-header`** (`2026-07-28`) | **B** | Client sends headers; server validates and routes |
| **`-32002` → `-32602`** for resource-not-found (`2026-07-28`) | **B** | Server emits; client matches |
| **Error-code allocation policy, `-32020`…`-32099` reserved** (`2026-07-28`) | **B** | Neither side may claim reserved codes |
| **`iss` in auth responses, RFC 9207** (`2026-07-28`) | **B** | AS emits; client validates |
| **`application_type` on DCR** (`2026-07-28`) | **C** | Client-side registration parameter |
| **Credentials keyed by issuer** (`2026-07-28`) | **C** | Client credential store |
| **Loosen `inputSchema`/`outputSchema` to any 2020-12 keyword** (`2026-07-28`) | **B** | Server may emit; client must not reject |
| **Remove `notifications/elicitation/complete` + `elicitationId`** (`2026-07-28`) | **B** | Round-trip completion now signalled by MRTR |
| **Deprecate Roots/Sampling/Logging** (`SEP-2577`) | **B** | Functional until ≥2027-07-28, but new work should avoid |
| **Deprecate HTTP+SSE** (`SEP-2596`) | **B** | Must migrate to Streamable HTTP before ≥2027-07-28 |
| **Deprecate OAuth DCR** (`PR #2858`) | **B** | Migrate client registration to Client ID Metadata Documents |
| **Features only *clarified* (security guidance, `Origin` 403, stderr logging, `_meta` usage)** | **—** | No behaviour change required; conformance/expectation only |
| **Governance/process SEPs (932, 994, 1302, 1730, 1850, 2596, 3392, 3398)** | **—** | Ecosystem process only; no wire impact |

### 13.1 Roll-up counts

| Side | Items |
| --- | --- |
| **B (both)** | **39** |
| **S only** | **2** (deterministic `tools/list` ordering; server-supplied icons + `Implementation.description`) |
| **S mandatory / C optional (mixed)** | **1** (`server/discover`: servers **MUST** implement, clients **MAY** call) |
| **C only** | **3** (Resource Indicators RFC 8707, `application_type` on DCR, credentials keyed by issuer) |
| **— (no code change)** | **2** (pure clarifications; governance/process SEPs) |
| **Total rows** | **47** |

**Read:** the protocol's evolution is overwhelmingly **bidirectional**. There is no realistic
path where a `2024-11-05` server can be upgraded without also upgrading, or at minimum
version-gating, the clients — and the `2026-07-28` changes (sessions, `initialize`, MRTR,
`resultType`) are strictly non-negotiable on both sides simultaneously.

---

## Sources

All URLs retrieved **2026-11-26**. `HTTP 200` confirmed for rendered pages at retrieval time.

| # | Source | URL | Used for |
| --- | --- | --- | --- |
| 1 | `2025-03-26` changelog (rendered) | https://modelcontextprotocol.io/specification/2025-03-26/changelog | §3 |
| 2 | `2025-03-26` changelog (raw) | https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/docs/specification/2025-03-26/changelog.mdx | §3 |
| 3 | `2025-06-18` changelog (rendered) | https://modelcontextprotocol.io/specification/2025-06-18/changelog | §4 |
| 4 | `2025-06-18` changelog (raw) | https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/docs/specification/2025-06-18/changelog.mdx | §4 |
| 5 | `2025-11-25` changelog (rendered) | https://modelcontextprotocol.io/specification/2025-11-25/changelog | §5 |
| 6 | `2025-11-25` changelog (raw) | https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/docs/specification/2025-11-25/changelog.mdx | §5, §10 |
| 7 | `2026-07-28` changelog (rendered) | https://modelcontextprotocol.io/specification/2026-07-28/changelog | §6 |
| 8 | `2026-07-28` changelog (raw) | https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/docs/specification/2026-07-28/changelog.mdx | §6, §10 |
| 9 | `2024-11-05` changelog — **does not exist (HTTP 404)** | https://modelcontextprotocol.io/specification/2024-11-05/changelog | §0, §2, §12.1 |
| 10 | `2024-11-05` spec index | https://modelcontextprotocol.io/specification/2024-11-05 | §2 |
| 11 | `2024-11-05` transports doc | https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/docs/specification/2024-11-05/basic/transports.mdx | §2.1, §8.1 |
| 12 | `2024-11-05` schema | https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/schema/2024-11-05/schema.ts | §2.1, §6.7, §7 |
| 13 | `2025-03-26` schema | https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/schema/2025-03-26/schema.ts | §7 |
| 14 | `2025-06-18` schema | https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/schema/2025-06-18/schema.ts | §7 |
| 15 | `2025-11-25` schema | https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/schema/2025-11-25/schema.ts | §6.7, §7 |
| 16 | `2026-07-28` schema | https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/schema/2026-07-28/schema.ts | §6.7, §7, §8.8, §8.9 |
| 17 | Releases / tags API | https://github.com/modelcontextprotocol/modelcontextprotocol/releases | §1 (all publish dates) |
| 18 | SEP corpus (directory) | https://github.com/modelcontextprotocol/modelcontextprotocol/tree/main/seps | §0.1, §10, §11 |
| 19 | SEP-414 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/414-request-meta.md | §6.2 #2 |
| 20 | SEP-932 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/932-model-context-protocol-governance.md | §5.4 |
| 21 | SEP-973 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/973-expose-additional-metadata-for-implementations-res.md | §5.1 #2 |
| 22 | SEP-985 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/985-align-oauth-20-protected-resource-metadata-with-rf.md | §5.2 #8 |
| 23 | SEP-986 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/986-specify-format-for-tool-names.md | §5.1 #4 |
| 24 | SEP-991 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/991-enable-url-based-client-registration-using-oauth-c.md | §5.1 #8 |
| 25 | SEP-994 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/994-shared-communication-practicesguidelines.md | §5.4 |
| 26 | SEP-1034 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/1034--support-default-values-for-all-primitive-types-in.md | §5.2 #9 |
| 27 | SEP-1036 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/1036-url-mode-elicitation-for-secure-out-of-band-intera.md | §5.1 #6 |
| 28 | SEP-1302 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/1302-formalize-working-groups-and-interest-groups-in-mc.md | §5.4 |
| 29 | SEP-1303 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/1303-input-validation-errors-as-tool-execution-errors.md | §5.2 #5 |
| 30 | SEP-1319 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/1319-decouple-request-payload-from-rpc-methods-definiti.md | §5.3 |
| 31 | SEP-1330 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/1330-elicitation-enum-schema-improvements-and-standards.md | §5.1 #5 |
| 32 | SEP-1577 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/1577--sampling-with-tools.md | §5.1 #7 |
| 33 | SEP-1613 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/1613-establish-json-schema-2020-12-as-default-dialect-f.md | §5.2 #10 |
| 34 | SEP-1686 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/1686-tasks.md | §5.1 #9, §8.6 |
| 35 | SEP-1699 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/1699-support-sse-polling-via-server-side-disconnect.md | §5.2 #6–7 |
| 36 | SEP-1730 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/1730-sdks-tiering-system.md | §5.4 |
| 37 | SEP-2106 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2106-json-schema-2020-12.md | §6.2 #10 |
| 38 | SEP-2133 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2133-extensions.md | §6.2 #1 |
| 39 | SEP-2164 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2164-resource-not-found-error.md | §6.2 #6 |
| 40 | SEP-2243 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2243-http-standardization.md | §6.2 #4 |
| 41 | SEP-2322 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2322-MRTR.md | §6.1 #7–8, §8.4 |
| 42 | SEP-2468 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2468-recommend-issuer-claim-for-auth.md | §6.2 #7 |
| 43 | SEP-2549 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2549-TTL-for-list-results.md | §6.2 #5, §8.8 |
| 44 | SEP-2567 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2567-sessionless-mcp.md | §6.1 #1, §8.2 |
| 45 | SEP-2575 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2575-stateless-mcp.md | §6.1 #2–5, #9 |
| 46 | SEP-2577 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2577-deprecate-roots-sampling-and-logging.md | §6.4, §9.3 |
| 47 | SEP-2596 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2596-spec-feature-lifecycle-and-deprecation.md | §6.4–6.5, §9.1 |
| 48 | SEP-2663 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2663-tasks-extension.md | §6.1 #6, §8.6 |
| 49 | SEP-3392 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/3392-extension-lifecycle.md | §8.6, §11 |
| 50 | SEP-3398 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/3398-release-cycle-updates.md | §10, §11 |
| 51 | SEP-3415 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/3415-events-extension.md | §11 |
| 52 | Deprecation registry (`2026-07-28`) | https://modelcontextprotocol.io/specification/2026-07-28/deprecated | §9.2 |
| 53 | Deprecation registry (raw) | https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/docs/specification/2026-07-28/deprecated.mdx | §9.2 |
| 54 | Feature lifecycle policy page | https://modelcontextprotocol.io/community/feature-lifecycle | §9.1 |
| 55 | Extensions overview | https://modelcontextprotocol.io/extensions/overview | §8.6 |
| 56 | MRTR pattern page | https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/mrtr | §8.4 |
| 57 | Subscriptions pattern page | https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/subscriptions | §8.5 |
| 58 | Full-diff links cited by changelogs | https://github.com/modelcontextprotocol/specification/compare/2025-11-25...2026-07-28 | §6 (pointer) |
| 59 | `2026-07-28` `/basic` index (per-request `_meta` semantics) | https://modelcontextprotocol.io/specification/2026-07-28/basic | §8.2 |
| 60 | `2026-07-28` versioning doc | https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/docs/specification/2026-07-28/basic/versioning.mdx | §8.3 |

**Reproduction recipe** (any auditor can re-run these in ~2 minutes):

```bash
R=modelcontextprotocol/modelcontextprotocol
for v in 2025-03-26 2025-06-18 2025-11-25 2026-07-28; do
  curl -sS https://raw.githubusercontent.com/$R/main/docs/specification/$v/changelog.mdx
done
gh api repos/$R/releases --jq '.[]|"\(.tag_name)\t\(.published_at)"'
for v in 2024-11-05 2025-03-26 2025-06-18 2025-11-25 2026-07-28; do
  curl -sS https://raw.githubusercontent.com/$R/main/schema/$v/schema.ts \
    | grep -oE '"[a-z]+/[a-zA-Z/]+"' | sort -u
done
gh api repos/$R/contents/seps --jq '.[]|select(.name|endswith(".md"))|.name'
```
