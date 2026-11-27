# MCP Landscape 2026-11 - PRD index

**Status:** Draft
**Date:** 2026-11-26
**Scope:** the 20 PRDs in this directory, read against `lauren-mcp` 1.0.0 on branch `docs/mcp-landscape-2026-11` and against MCP revisions `2024-10-07` through `2026-07-28`. This file is an index: it adds no requirement a PRD does not already state.
**Evidence base:** [`EVIDENCE.md`](./EVIDENCE.md) (177 rows, sections 0-23), [`VERSIONS-MATRIX.md`](./VERSIONS-MATRIX.md) (11 sections, 19 tables), `_research/` (7 files, including [`PRD-BRIEF.md`](./_research/PRD-BRIEF.md)). Single retrieval date: 2026-11-26.

## 1. How the series was produced

Four stages, each written down before the next:

1. **Clusters.** Six research passes, one file each in `_research/`: [`spec.md`](./_research/spec.md) (the revisions), [`python-frameworks.md`](./_research/python-frameworks.md), [`cross-language.md`](./_research/cross-language.md), [`agent-integration.md`](./_research/agent-integration.md), [`infrastructure.md`](./_research/infrastructure.md) and [`lauren-mcp-inventory.md`](./_research/lauren-mcp-inventory.md) (this repository, file by file).
2. **Inventory.** Every claim that survived the clusters became a row with a source, a retrieval method and a date, in `EVIDENCE.md`. The register is the only place external claims originate; a PRD cites an `E-xxx` row but cannot add one.
3. **Version reconciliation.** `VERSIONS-MATRIX.md` turns the revision list into a capability delta, recording per capability whether `lauren-mcp` declares it and whether it conforms. The two-era split (`2024-11-05` … `2025-11-25` against `2026-07-28`) becomes a table here rather than a theme.
4. **PRDs.** One per gap that survived those stages, written against the contract in [`PRD-BRIEF.md`](./_research/PRD-BRIEF.md): status header with `**Priority:**`, a problem statement quoting this repository's own code with file and line, then requirements and references.

The series is **additive only**. The 64 pre-existing `prds/*.md` from June 2026 are untouched and pinned by [`.baseline-sha256.txt`](./.baseline-sha256.txt) (64 hashes). Section 4 maps between the batches.

## 2. Prioritised summary

Priority is the cost of *not* doing the work, not the size of the change. P1: a shipped or expected peer cannot complete a conversation. P2: conformance, parity, reach. P3: differentiators that pay off once P1 and P2 hold.

### 2.1 P1 - a peer cannot complete the conversation

| # | Priority | PRD | Theme | Gap in one line | Key evidence · issue |
|---|---|---|---|---|---|
| 1 | P1 | [`prd-dual-era-protocol-core.md`](./prd-dual-era-protocol-core.md) | Protocol core | Only the legacy era is served: `initialize`-only handshake, closed version list, session-bound state, so a `2026-07-28` peer cannot connect | E-20, E-21, E-22 · [#61](https://github.com/lauren-framework/lauren-mcp/issues/61) |
| 2 | P1 | [`prd-server-discover-request-meta.md`](./prd-server-discover-request-meta.md) | Protocol core | No `server/discover` and no per-request `_meta` envelope, so a modern peer has nothing to negotiate against | E-20, E-21, E-30 · [#62](https://github.com/lauren-framework/lauren-mcp/issues/62) |
| 3 | P1 | [`prd-result-envelope-caching.md`](./prd-result-envelope-caching.md) | Protocol core | No `resultType`, `ttlMs` or `cacheScope` in any result (`grep -ril resultType src/` returns 0, E-232), so hosts cannot cache or date one | E-20, E-21, E-26 · [#63](https://github.com/lauren-framework/lauren-mcp/issues/63) |
| 4 | P1 | [`prd-mrtr-input-required.md`](./prd-mrtr-input-required.md) | Protocol core | `tools/call` is one-shot: a tool needing input mid-call cannot return `input_required` and resume | E-14, E-20, E-21 · [#64](https://github.com/lauren-framework/lauren-mcp/issues/64) |
| 5 | P1 | [`prd-cancellation-conformance.md`](./prd-cancellation-conformance.md) | Transports | `notifications/cancelled` has existed since the first schema, but the read loop is blocked by the call it should cancel, so no handler sees it | E-08, E-09, E-237 · [#65](https://github.com/lauren-framework/lauren-mcp/issues/65) |
| 6 | P1 | [`prd-transport-security-hardening.md`](./prd-transport-security-hardening.md) | Transports | `transport_security` is an opt-in keyword and nothing attaches it to the generated HTTP/SSE controllers | E-169b, E-169, E-160 · [#66](https://github.com/lauren-framework/lauren-mcp/issues/66) |

### 2.2 P2 - conformance, parity and reach

| # | Priority | PRD | Theme | Gap in one line | Key evidence · issue |
|---|---|---|---|---|---|
| 7 | P2 | [`prd-client-parity.md`](./prd-client-parity.md) | Protocol core | Event store, subscriptions and cancellation exist server-side, but the four client transports expose no matching surface | E-81, E-200, E-201 · [#67](https://github.com/lauren-framework/lauren-mcp/issues/67) |
| 8 | P2 | [`prd-deprecation-lifecycle.md`](./prd-deprecation-lifecycle.md) | Protocol core | Five of the six features `2026-07-28` deprecates ship with no signal, no sunset revision, no removal path | E-30, E-41, E-42 · [#68](https://github.com/lauren-framework/lauren-mcp/issues/68) |
| 9 | P2 | [`prd-sessionless-http-transport.md`](./prd-sessionless-http-transport.md) | Transports | Streamable HTTP still mints a session at `initialize`; there is no sessionless shape for deployments that need one | E-20, E-22, E-23 · [#69](https://github.com/lauren-framework/lauren-mcp/issues/69) |
| 10 | P2 | [`prd-oauth-resource-indicators-cimd.md`](./prd-oauth-resource-indicators-cimd.md) | Transports | OAuth is hand-rolled in two places, with no resource indicators and no client-ID metadata | E-170, E-171, E-172 · [#70](https://github.com/lauren-framework/lauren-mcp/issues/70) |
| 11 | P2 | [`prd-subscriptions-listen.md`](./prd-subscriptions-listen.md) | Notifications | The GET stream and `resources/subscribe` are legacy-era; the modern era replaces both with `subscriptions/listen` | E-23, E-28, E-41 · [#71](https://github.com/lauren-framework/lauren-mcp/issues/71) |
| 12 | P2 | [`prd-tasks-extension.md`](./prd-tasks-extension.md) | Notifications | An eight-minute tool runs inside one JSON-RPC request with nowhere to report progress and no task handle | E-25, E-53, E-30 · [#72](https://github.com/lauren-framework/lauren-mcp/issues/72) |
| 13 | P2 | [`prd-json-schema-2020-12.md`](./prd-json-schema-2020-12.md) | Schemas and tools | JSON Schema is built by hand rather than asked of Pydantic, so `2020-12` keywords and `$ref` handling drift from what a host validates | E-13, E-30, E-223 · [#73](https://github.com/lauren-framework/lauren-mcp/issues/73) |
| 14 | P2 | [`prd-tool-presentation-budget.md`](./prd-tool-presentation-budget.md) | Schemas and tools | The host now decides how much tool text exists (deferred search, 16,384-char descriptions, 10,000/25,000-token caps); we have no budget-aware presentation | E-191a, E-191b, E-191c · [#74](https://github.com/lauren-framework/lauren-mcp/issues/74) |
| 15 | P2 | [`prd-conformance-ci.md`](./prd-conformance-ci.md) | Tooling and conformance | No conformance measurement of any kind: every claim about our own protocol behaviour is an assertion with no number attached | E-75, E-76, E-55 · [#75](https://github.com/lauren-framework/lauren-mcp/issues/75) |
| 16 | P2 | [`prd-host-compatibility-profiles.md`](./prd-host-compatibility-profiles.md) | Ecosystem | `lmcp install` writes one config shape for ten hosts, and the server cannot ask what a host cannot do | E-191, E-195, E-198 · [#76](https://github.com/lauren-framework/lauren-mcp/issues/76) |
| 17 | P2 | [`prd-registry-publishing.md`](./prd-registry-publishing.md) | Ecosystem | The registry is live at 1.8.16 and everything consumes one `server.json` shape; we publish none | E-120, E-121, E-122 · [#77](https://github.com/lauren-framework/lauren-mcp/issues/77) |
| 18 | P2 | [`prd-otel-semconv-alignment.md`](./prd-otel-semconv-alignment.md) | Ecosystem | Traces are emitted, but attribute names predate the current MCP semantic conventions, so our spans do not group with others | E-180, E-181, E-182 · [#78](https://github.com/lauren-framework/lauren-mcp/issues/78) |

### 2.3 P3 - differentiators that need P1 and P2 first

| # | Priority | PRD | Theme | Gap in one line | Key evidence · issue |
|---|---|---|---|---|---|
| 19 | P3 | [`prd-packaging-typing-parity.md`](./prd-packaging-typing-parity.md) | Ecosystem | The differentiator is supply chain - two runtime dependencies, a Python floor matching CI, no upstream `mcp` dependency - and our own metadata fails that scrutiny in five places | E-105, E-106, E-109 · [#79](https://github.com/lauren-framework/lauren-mcp/issues/79) |
| 20 | P3 | [`prd-inspector-dev-tooling.md`](./prd-inspector-dev-tooling.md) | Tooling and conformance | `lmcp inspect` is a thin positional command; Inspector is at 2.16.0 with capabilities we neither drive nor test | E-165, E-166, E-222 · [#80](https://github.com/lauren-framework/lauren-mcp/issues/80) |

## 3. Theme to PRD map

The same 20 PRDs by work area. Bracketed numbers are summary-table rows.

### 3.1 Protocol era core and discovery

**1, 2, 3, 4, 7, 8** - dual-era core, `server/discover`, result envelope, MRTR, client parity, deprecation lifecycle. The modern era is a breaking revision: it deletes the `initialize` handshake for modern peers, makes `server/discover` the entry point and moves freshness into the result envelope. So 1 gates 2, 3 and 4 - without an era decision there is no peer to serve. 4 reuses the `_meta` plumbing 2 introduces. 7 is the client half of that surface, scoped only once it exists. 8 spans all of them: a deprecation means nothing until the code knows which era its peer speaks.

### 3.2 Transports and security

**5, 6, 9, 10** - cancellation, transport security, sessionless HTTP, OAuth hardening. 5 and 6 are defects in code that already ships, so neither waits on the era work. 6 and 9 both edit `_streamable.py` and `_sse.py` and must be sequenced. 10 alone adds a server-side capability rather than repairing one.

### 3.3 Notifications, subscriptions and long-running work

**11, 12** - `subscriptions/listen`, tasks extension. 11 folds two mechanisms into one; 12 makes a call that outlives a single request observable. Both depend on 1 for era detection and 2 for capability negotiation; 12's progress reporting partners 4, since both answer "the call did not finish in one round trip".

### 3.4 Schemas, tools and authoring

**13, 14** - JSON Schema 2020-12, tool presentation. 13 changes the schema factory every published `inputSchema` comes from, including the manifest 17 submits. 14 sets budgets on the text 13 generates, so 14 first would mean measuring twice. Neither depends on the era work: the safest cluster if the modern era waits.

### 3.5 Developer tooling and conformance

**15, 20** - conformance CI, inspector tooling. 15 is a P2 to build early: it is the harness that turns 1-6 from claims into numbers. 20 consumes it and the host profiles from 16.

### 3.6 Ecosystem, packaging and distribution

**16, 17, 18, 19** - host profiles, registry publishing, OTel semconv, packaging/typing. 16 and 17 both write host-facing metadata and should settle on one shape. 19 is the supply-chain claim 17 publishes, so it goes first if the listing argues security. 18 stands alone: operator-facing, no wire-format change.

## 4. Relationship to the June-2026 PRDs

The June 2026 batch (64 files in [`prds/`](../)) is the baseline. *Superseded*: the new PRD replaces the requirement. *Extended*: the old requirement holds, the new PRD adds to it. *Unchanged*: the review looked and had nothing to add.

| PRD | Relationship | What changed |
|---|---|---|
| [`prd-protocol-version-negotiation.md`](../prd-protocol-version-negotiation.md) | Extended | Negotiation was a client-side handshake picking the newest version on offer; the list is now an era boundary the server must also satisfy (1). |
| [`prd-sdk-protocol-versions-2025.md`](../prd-sdk-protocol-versions-2025.md) | Extended | The supported table is now two eras with different mandatory surfaces (1, 8). |
| [`prd-streamable-http-transport.md`](../prd-streamable-http-transport.md) | Superseded in part | Built the `2025-03-26` transport with a session minted at `initialize`; both are now optional, so the shape reopens (9). |
| [`prd-sdk-stateless-http-mode.md`](../prd-sdk-stateless-http-mode.md) | Absorbed | Stateless mode was a switch on a sessioned transport; it becomes the modern-era default, not a separate mode (9). |
| [`prd-sdk-sse-event-store-resumability.md`](../prd-sdk-sse-event-store-resumability.md) | Extended, new owner | Event IDs and resume stay valid for legacy peers, but the GET stream they ride is replaced, so resumability needs a second spec (11). |
| [`prd-sdk-dns-rebinding-protection.md`](../prd-sdk-dns-rebinding-protection.md) | Extended, promoted to P1 | The guard was an opt-in keyword; it must now be attached by default, with the rest of the hardening set (6). |
| [`prd-sdk-oauth-discovery-endpoints.md`](../prd-sdk-oauth-discovery-endpoints.md) | Extended | Resource indicators and client-ID metadata change what is discovered and sent (10). |
| [`prd-sdk-oauth-client-provider.md`](../prd-sdk-oauth-client-provider.md) | Extended | Client credentials and PKCE exist client-side only; the ground now covers resource indicators and the server side (10). |
| [`prd-sdk-opentelemetry.md`](../prd-sdk-opentelemetry.md) | Superseded in detail | The wiring stays; attribute names are replaced so spans group with other MCP implementations (18). |
| [`prd-schema-generation.md`](../prd-schema-generation.md) | Extended | Hand-built schema generation stays, but its `$ref` and `2020-12` behaviour must become conformant (13). |
| [`prd-sdk-cli-tooling.md`](../prd-sdk-cli-tooling.md) | Extended | The `lmcp` command grows host profiles (16) and a real inspector (20). |
| [`prd-client-logging.md`](../prd-client-logging.md) | Unchanged | Logging is one of the features `2026-07-28` deprecates; changes surface through the lifecycle PRD (8). |
| [`prd-sampling.md`](../prd-sampling.md) | Extended by adjacency | Sampling is deprecated in the modern era; the round-trip machinery it uses is what MRTR generalises (4, 8). |
| [`prd-elicitation.md`](../prd-elicitation.md) | Extended | Under the modern era an eliciting tool returns `input_required` and is resumed, changing the call shape it sits inside (4). |
| [`prd-client-roots.md`](../prd-client-roots.md) | Unchanged | Roots is deprecated by `2026-07-28`; the feature is untouched here and the sunset belongs to 8. |
| [`prd-list-changed-notifications.md`](../prd-list-changed-notifications.md) | Extended | For modern peers, notifications move onto the `subscriptions/listen` channel (11). |
| [`prd-sdk-resource-subscriptions.md`](../prd-sdk-resource-subscriptions.md) | Superseded in part | `resources/subscribe` and `resources/unsubscribe` become the legacy branch of the single channel 11 describes. |
| [`prd-sdk-cancel-requested-signal.md`](../prd-sdk-cancel-requested-signal.md) | Re-scoped | The handler-facing signal survives; its notification never reaches the dispatcher, so delivery becomes the work (5). |
| [`prd-tool-background-tasks.md`](../prd-tool-background-tasks.md) | Extended | In-process background work keeps its shape; a protocol-level task handle makes a long call observable (12). |
| [`prd-pypi-release-readiness.md`](../prd-pypi-release-readiness.md) | Extended | Parity now covers wheels, typing and metadata against the surveyed frameworks (19). |
| [`prd-tool-annotations.md`](../prd-tool-annotations.md) | Unchanged | 14 governs text volume, not annotation semantics. |
| [`prd-sdk-title-field.md`](../prd-sdk-title-field.md) | Extended by adjacency | `title` is the text the registry manifest (17) and host presentation (14) consume; the field is unchanged. |
| [`python-sdk-gap-analysis.md`](../python-sdk-gap-analysis.md) | Superseded as a source of counts | Re-derived with citations at 2026-11-26; where a count differs, the evidence register wins. |
| [`fastmcp-gap-analysis-prd.md`](../fastmcp-gap-analysis-prd.md) | Referenced, not revised | It informs the tooling and host-compatibility PRDs; no requirement here supersedes it. |

## 5. Reading order

Four tracks, one question each. Numbers are summary-table rows.

**Track A - open a modern-era conversation.** 1, 2, 3, 4, 11, 12, 8 (dual-era core, `server/discover`, result envelope, MRTR, `subscriptions/listen`, tasks extension, deprecation lifecycle). The order the protocol imposes: era, discovery, envelope, call shapes, channels, then the sunset of what it retires.

**Track B - repair the legacy era we already ship.** 5, 6, 9, 10, 13 (cancellation, transport security, sessionless HTTP, OAuth hardening, JSON Schema 2020-12). All five are defects or omissions in `src/lauren_mcp/`, none needs the era work first, and the first two carry the security edge.

**Track C - prove it and say so.** 15, 7, 18, 19 (conformance CI, client parity, OTel semconv, packaging/typing). The harness comes first because it makes the other nineteen measurable; parity, tracing and packaging follow from it.

**Track D - reach the hosts.** 16, 20, 14, 17 (host profiles, inspector tooling, tool presentation, registry publishing). Host configuration, the inspector, the presentation budget and the registry listing are where a developer first meets this package.

## 6. Method and limits

- **One retrieval date.** Everything external was read on 2026-11-26 and is only true as of that day. Registry version, Inspector version, advisory counts and host defaults will move; each row carries its retrieval method so a later pass can re-run it, not re-argue it.
- **Hosts are unverified.** Host behaviour comes from published documentation and configuration defaults, not from executing each host against this server. Where a PRD says a host defers tool definitions or caps a description length, read that as documented behaviour of a version, not a measured result. This is the weakest link; 16 is where it closes.
- **Counts are dated, not given.** Numbers are attributed to `E-xxx` rows and should not be quoted without them. Where a June 2026 gap analysis disagrees, the register wins: it carries the citation.
- **The PRDs are drafts.** All 20 carry `**Status:** Draft`; none is accepted, sequenced or costed.
- **Tracking.** Each PRD has exactly one issue on `lauren-framework/lauren-mcp`, labelled `prd` plus its priority (`p1`/`p2`/`p3`): #61-#80, one per summary row. The PRD header carries the link and section 2 repeats it next to the evidence IDs, so a requirement can be argued here and tracked there.
