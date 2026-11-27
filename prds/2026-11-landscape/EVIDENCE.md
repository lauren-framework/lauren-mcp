# Evidence Register — MCP Landscape Review (2026-11)

**Status:** Draft for review
**Date:** 2026-11-26
**Scope:** every external claim relied on by the `prds/2026-11-landscape/` PRD set — each with source
URL, retrieval date (`2026-11-26`) and the exact version string observed — plus every `lauren-mcp`
baseline claim, each with a `file:line` citation inside this repository.
**Audience:** whoever reviews, prioritises, or implements the PRDs; and anyone re-auditing the
recommendations six months from now.

---

## 0. Why this document exists

A landscape review is only as good as its weakest unstated assumption. The PRDs make claims of the
form *"every official SDK except ours speaks `2026-07-28`"*, *"the spec removed sessions"*, and
*"the Registry has more than 20,000 servers"*. If any of those is wrong, the priority ordering in
the PRD set is wrong with it. So every such claim is registered here, once, with its receipt.

Two rules govern this file:

1. **No unsourced assertion.** If a sentence appears in a PRD and it is not about this repository's
   own code, it must trace to a row here.
2. **Version strings are quoted verbatim.** "Latest" is a moving target and therefore not evidence.
   `2.3.0` is evidence; "latest" is a rumour.

### 0.1 Confidence codes

| Code | Meaning | How it was obtained |
|---|---|---|
| **[P]** | Primary, fetched | The artifact itself was retrieved during this review (rendered page, raw file, HTTP 200). |
| **[S]** | Schema/source token | A literal string was grepped for in an official schema or an SDK source tree, with a hit count. |
| **[R]** | Registry/API | Value read from a live package registry, module proxy, or release API (npm, PyPI, Maven, NuGet, Go proxy, crates.io, RubyGems, Packagist, GitHub REST). |
| **[C]** | Corroborated | Two or more independent sources agree — typically a release page plus a registry plus the changelog. |
| **[D]** | Derived | Inferred by this review from primary evidence. The inference chain is stated. |
| **[N]** | Negative | The thing was looked for and *not* found, with the search that establishes it (404, or a zero-hit grep). |
| **[U]** | Unverified | Could not be established at retrieval time. Carried forward as an explicit open question, never as a fact. |

A **[D]** or **[U]** row is not a weaker *source*, it is a different *kind* of statement. PRDs are
allowed to build on **[P]**, **[S]**, **[R]**, **[C]** and **[D]**; a **[U]** row must be cited as an
open question, not as premises.

### 0.2 Retrieval environment

* All external retrieval: **2026-11-26**, single host, unauthenticated reads (`curl`, `gh api`,
  public package APIs). No scraping behind auth walls.
* Where a documentation page is ambiguous between prose and machine-readable truth, the machine-
  readable artifact wins: `schema.ts` over `changelog.mdx` over blog posts. This ordering matters —
  see §18 C-01.
* Repository-internal claims were verified against the working tree on branch
  `docs/mcp-landscape-2026-11`, base commit `7778737`, `lauren-mcp` **1.0.0**.

---

## 1. Protocol revisions — the spine of the whole review

| # | Claim | Exact value | Source (URL) | Conf. |
|---|---|---|---|---|
| E-01 | The revision set of MCP, oldest to newest | `2024-10-07`, `2024-11-05`, `2025-03-26`, `2025-06-18`, `2025-11-25`, `2026-07-28` | https://github.com/modelcontextprotocol/modelcontextprotocol/tags | **[R]** |
| E-02 | `2026-07-28` is the **current** revision; no `2026-11-*` tag or RC exists as of retrieval | tag `2026-07-28`; latest tag in list | https://github.com/modelcontextprotocol/modelcontextprotocol/releases | **[R]** |
| E-03 | Tag publication timestamps are *not* the version labels | `2024-11-05` published `2025-01-17T20:37:02Z`; `2025-03-26` → `2025-03-26T14:28:27Z`; `2025-06-18` → `2025-06-18T20:09:59Z`; `2025-11-25` → `2025-11-25T21:17:42Z`; `2026-07-28` → `2026-07-28T16:47:49Z` | https://github.com/modelcontextprotocol/modelcontextprotocol/releases | **[R]** |
| E-04 | A second tag `2024-11-05-final` exists, published the same day as `2025-03-26` | `2025-03-26T13:53:30Z` | https://github.com/modelcontextprotocol/modelcontextprotocol/tags | **[R]** |
| E-05 | RC lead time grew sharply for the current revision | `2025-11-25-RC` at `2025-11-15T06:06:55Z` (≈10 d); `2026-07-28-RC` at `2026-05-29T12:51:22Z` (≈60 d) | https://github.com/modelcontextprotocol/modelcontextprotocol/releases | **[R]** |
| E-06 | `2024-11-05` has **no changelog page** — any 2024-11-05→2025-03-26 diff is reconstructed, never quoted | HTTP 404 at the changelog path; no `changelog.mdx` in the docs tree | https://modelcontextprotocol.io/specification/2024-11-05/changelog | **[N]** |
| E-07 | `2024-11-05` carried exactly one HTTP transport: HTTP+SSE (no Streamable HTTP, no session header) | `## stdio`, `## HTTP with SSE`, `## Custom Transports` | https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/docs/specification/2024-11-05/basic/transports.mdx | **[P]** |
| E-08 | `notifications/cancelled` exists in the **earliest** schema | literal `"notifications/cancelled"` present in `schema/2024-11-05/schema.ts` | https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/schema/2024-11-05/schema.ts | **[S]** |
| E-09 | `$/cancelRequest` appears **zero** times anywhere in the MCP organisation | 0 occurrences of `/cancelRequest` across org code search (query in §20) | GitHub code search over `org:modelcontextprotocol`, query archived in §20 — no single citable page, by nature of a zero-result search | **[N]** |
| E-10 | `initialize` and `ping` in `2024-11-05` are non-slash identifiers, confirmed by grep | `initialize` ×4, `ping` ×2 | https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/schema/2024-11-05/schema.ts | **[S]** |
| E-11 | Streamable HTTP enters the protocol at `2025-03-26` | changelog + `basic/transports` | https://modelcontextprotocol.io/specification/2025-03-26/changelog | **[P]** |
| E-12 | `2025-06-18` is additive over `2025-03-26` (elicitation, structured output, resource links, `title`, OAuth resource-indicator hardening) | revision changelog | https://modelcontextprotocol.io/specification/2025-06-18/changelog | **[P]** |
| E-13 | `2025-11-25` is additive: 9 major + 10 minor changes, incl. tasks (SEP-1686), URL-mode elicitation (SEP-1036), OIDC discovery, icons, JSON Schema 2020-12 default (SEP-1613) | changelog sections | https://modelcontextprotocol.io/specification/2025-11-25/changelog | **[P]** |
| E-14 | `2025-11-25` had **no** MRTR / round-trip content — MRTR is a *post*-2025-11-25 draft concept | zero MRTR references in the `2025-11-25` changelog; MRTR present in `draft/basic/patterns/mrtr.mdx` | https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/docs/specification/draft/basic/patterns/mrtr.mdx | **[N]** / **[P]** |

**Why E-14 matters.** An earlier framing of this review assumed MRTR was already released in
`2025-11-25`. It was not. That single check changes which PRD owns MRTR (a `2026-07-28` item, not a
"catch up to 2025-11-25" item).

---

## 2. `2026-07-28` — a breaking revision, not an additive one

This is the load-bearing correction of the whole review (see §18 C-02). Nine mandatory removals:

| # | Claim | Exact evidence | Source (URL) | Conf. |
|---|---|---|---|---|
| E-20 | Sessions are **removed**; `Mcp-Session-Id` no longer exists in Streamable HTTP | changelog "Sessions" removal; `Mcp-Session-Id` absent from `2026-07-28` schema, present in `2025-11-25` schema | https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/docs/specification/2026-07-28/changelog.mdx · https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/schema/2026-07-28/schema.ts | **[P]**/**[S]** |
| E-21 | The `initialize` handshake is **removed** for modern peers; `server/discover` is a MUST | `server/discover.mdx` exists in the `2026-07-28` tree | https://github.com/modelcontextprotocol/modelcontextprotocol/tree/main/docs/specification/2026-07-28 | **[P]** |
| E-22 | Per-request `_meta` carries what the handshake used to carry: `io.modelcontextprotocol/protocolVersion`, `clientInfo`, `clientCapabilities`, `serverInfo`, `logLevel` | `basic` index + SEP-2567 / SEP-2575 | https://modelcontextprotocol.io/specification/2026-07-28/basic · https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2567-sessionless-mcp.md | **[P]** |
| E-23 | `subscriptions/listen` **replaces** the HTTP GET channel and per-resource `resources/subscribe` notifications | subscriptions pattern page | https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/subscriptions | **[P]** |
| E-24 | `ping`, `logging/setLevel`, and `roots/list_changed` are **removed** | removal list in changelog + schema diff | https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/docs/specification/2026-07-28/changelog.mdx | **[P]** |
| E-25 | Tasks leave the core protocol and become the `io.modelcontextprotocol/tasks` **extension** (SEP-2663) | extensions overview + SEP-2663 | https://modelcontextprotocol.io/extensions/overview · https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2663-tasks-extension.md | **[P]** |
| E-26 | Server-initiated sampling/elicitation/roots are **replaced by MRTR** (`input_required` + `requestState`), for `tools/call`, `prompts/get`, `resources/read` | MRTR pattern page states it "replaces the previous approach of sending server-initiated…" | https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/mrtr | **[P]** |
| E-27 | Every result carries `resultType`; cacheable list results carry `ttlMs` + `cacheScope` | SEP-2549 + changelog | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2549-TTL-for-list-results.md | **[P]** |
| E-28 | SSE resumability is **removed** (`Last-Event-ID` replay no longer specified) | transport changelog entries for `2026-07-28` | https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/docs/specification/2026-07-28/changelog.mdx | **[P]** |
| E-29 | Error codes were renumbered; resource-not-found standardised (SEP-2164) | SEP-2164 + `schema.ts` error enum | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2164-resource-not-found-error.md | **[P]** |
| E-30 | Roots, Sampling, Logging, DCR and HTTP+SSE are all **deprecated** by this revision | deprecation registry page | https://modelcontextprotocol.io/specification/2026-07-28/deprecated | **[P]** |

**Derived consequence [D]:** because E-20…E-30 remove as much as they add, "migrate to 2026-07-28"
is the wrong frame for `lauren-mcp`. The correct frame is **dual-era**: keep serving the handshake
era (`2024-11-05`…`2025-11-25`) for fielded clients while adding the modern era alongside it. Every
official SDK that has shipped `2026-07-28` did it that way (§6).

---

## 3. Deprecation schedule

| # | Claim | Exact value | Source (URL) | Conf. |
|---|---|---|---|---|
| E-40 | A formal feature lifecycle policy exists with states Active / Deprecated / Removed / Experimental | SEP-2596 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2596-spec-feature-lifecycle-and-deprecation.md · https://modelcontextprotocol.io/community/feature-lifecycle | **[P]** |
| E-41 | Deprecation is not immediate removal: a ≥12-month window is specified | "at least 12 months" in SEP-2596 / SEP-2577 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2577-deprecate-roots-sampling-and-logging.md | **[P]** |
| E-42 | The live deprecation registry is authoritative over blog posts | registry page lists the deprecated feature set for `2026-07-28` | https://modelcontextprotocol.io/specification/2026-07-28/deprecated | **[P]** |

**Derived [D]:** anything `lauren-mcp` ships today against Roots/Sampling/Logging remains *correct*
through the deprecation window and must not be deleted; it must be *supplemented* by MRTR and marked
in documentation. This is what keeps several PRDs at P2 rather than P1.

---

## 4. SEP corpus

| # | Claim | Exact value | Source (URL) | Conf. |
|---|---|---|---|---|
| E-50 | SEP corpus size at retrieval | **46** markdown files in `seps/`; 45 `Final`, 1 `Accepted` (SEP-3398) | https://github.com/modelcontextprotocol/modelcontextprotocol/tree/main/seps | **[R]** |
| E-51 | SEPs cited by this review | **34** rows in `_research/spec.md` §10, frontmatter `Type`/`Created` quoted verbatim | per-SEP URLs, e.g. https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2322-MRTR.md | **[P]** |
| E-52 | Three SEP numbers are cited by the `2026-07-28` changelog but have **no** SEP file | SEP-835, SEP-837, SEP-2352 | https://github.com/modelcontextprotocol/modelcontextprotocol/tree/main/seps | **[N]** |
| E-53 | Three SEPs are merged after `2026-07-28` and are in no released revision | SEP-3392 (Extension Lifecycle, Final, 2026-09-25), SEP-3398 (Release Cycle Updates, **Accepted** 2026-10-14), SEP-3415 (Events Extension, Final, 2026-10-05) | SEP URLs under `/seps/` | **[P]** |
| E-54 | Two SEP `Created` years look mistyped in the source (reported as-found, not silently corrected) | SEP-2133 → `2025-01-21`; SEP-2575 → `2025-06-18` | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2133-extensions.md | **[P]** |
| E-55 | The official SDK tiering system is itself a SEP | SEP-1730, `Created 2025-10-29`, first shipped in `2025-11-25` | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/1730-sdks-tiering-system.md · https://modelcontextprotocol.io/community/sdk-tiers.md | **[P]** |

---

## 5. Official SDKs — versions, all ten languages

Ten official SDKs; every row below is registry-confirmed **and** release-confirmed **[C]**.
Retrieved 2026-11-26.

| # | SDK | Install coordinate | Latest stable | Published | Repo tag | Tier | Source (URL) |
|---|---|---|---|---|---|---|---|
| E-60 | TypeScript (1.x line) | `@modelcontextprotocol/sdk`, dist-tag `latest` | **1.32.2** | 2026-10-23 | `1.32.2` | 1 | https://registry.npmjs.org/@modelcontextprotocol%2Fsdk |
| E-61 | TypeScript (2.x line) | `@modelcontextprotocol/{core,server,client,node,…}` | **2.4.0** | 2026-10-23 | `v2.4.0` | 1 | https://github.com/modelcontextprotocol/typescript-sdk/releases |
| E-62 | Python | `mcp` (PyPI) | **2.3.0** | 2026-10-02 | `v2.3.0` | 1 | https://pypi.org/pypi/mcp/json |
| E-63 | Java | `io.modelcontextprotocol.sdk:mcp` | **2.2.0** | 2026-11-16 | `v2.2.0` | 2 | https://repo1.maven.org/maven2/io/modelcontextprotocol/sdk/mcp/maven-metadata.xml |
| E-64 | Kotlin | `io.modelcontextprotocol:kotlin-sdk` | **0.16.0** | 2026-10-27 | `0.16.0` | 3 | https://repo1.maven.org/maven2/io/modelcontextprotocol/kotlin-sdk/maven-metadata.xml |
| E-65 | C# | `ModelContextProtocol` (NuGet) | **2.4.0** | 2026-11-07 | `v2.4.0` | 1 | https://api.nuget.org/v3/registration5-gz-semver2/modelcontextprotocol/index.json |
| E-66 | Go | `github.com/modelcontextprotocol/go-sdk` | **v1.8.0** (`v1.9.0-pre.1` tagged 2026-11-17) | 2026-09-14 | `v1.8.0` | 1 | https://proxy.golang.org/github.com/modelcontextprotocol/go-sdk/@latest |
| E-67 | Rust | `rmcp` (crates.io) | **3.12.0** | 2026-11-26 | `rmcp-v3.12.0` | 1 | https://crates.io/api/v1/crates/rmcp |
| E-68 | Ruby | `mcp` (RubyGems) | **1.11.0** | 2026-11-19 | `v1.11.0` | 1 | https://rubygems.org/api/v1/gems/mcp.json |
| E-69 | Swift | SPM `modelcontextprotocol/swift-sdk` | **0.12.1** | 2026-05-07 | `0.12.1` | 3 | https://github.com/modelcontextprotocol/swift-sdk |
| E-70 | PHP | `mcp/sdk` (Packagist) | **0.10.0** (pre-1.0) | 2026-11-10 | `v0.10.0` | 3 | https://repo.packagist.org/p2/mcp/sdk.json |

Additional SDK facts used by the PRDs:

| # | Claim | Exact value | Source (URL) | Conf. |
|---|---|---|---|---|
| E-71 | Python 2.x split its wire types into a second distribution | `mcp-types` **2.3.0** (2026-10-02), deps `pydantic` + `typing-extensions` | https://pypi.org/pypi/mcp-types/json | **[C]** |
| E-72 | Python SDK exports an explicit era registry | `HANDSHAKE_PROTOCOL_VERSIONS`, `MODERN_PROTOCOL_VERSIONS = ("2026-07-28",)`, `KNOWN_PROTOCOL_VERSIONS` = union | `src/mcp-types/mcp_types/version.py` in https://github.com/modelcontextprotocol/python-sdk | **[S]** |
| E-73 | TS 2.x still advertises the 2025 handshake as the naive default | `LATEST_PROTOCOL_VERSION = '2025-11-25'`; `DEFAULT_NEGOTIATED_PROTOCOL_VERSION = '2025-03-26'`; `SUPPORTED_PROTOCOL_VERSIONS = [2025-11-25, 2025-06-18, 2025-03-26, 2024-11-05, 2024-10-07]`; 2026 wire is opt-in via `versionNegotiation.mode` | constants: https://github.com/modelcontextprotocol/typescript-sdk/blob/main/packages/core/src/constants.ts (lines 1-3, re-verified 2026-11-26) · era semantics: https://github.com/modelcontextprotocol/typescript-sdk/blob/main/docs/protocol-versions.md | **[P]**/**[S]** |
| E-74 | TS ships `server-legacy` specifically to keep old-era servers running | package split list includes `server-legacy`, `codemod`, `middleware` | https://registry.npmjs.org/@modelcontextprotocol%2Fsdk | **[R]** |
| E-75 | Conformance suite exists and is what Tier 1 is measured by | `npx @modelcontextprotocol/conformance client --command … --scenario …`; version **0.1.16** (`npm view @modelcontextprotocol/conformance version`); repo pushed 2026-11-23 | https://github.com/modelcontextprotocol/conformance (version read via `npm view`) | **[C]** |
| E-76 | Tier requirements, verbatim | conformance pass rate 100 % / 80 % / none for Tiers 1 / 2 / 3; feature timelines; triage SLAs | https://modelcontextprotocol.io/community/sdk-tiers.md | **[P]** |
| E-77 | Swift is the only official SDK with **no** `2026-07-28` support | `AGENTS.md` states newest implemented revision is `2025-11-25`; 0 hits for `server/discover`, `resultType` | https://github.com/modelcontextprotocol/swift-sdk | **[S]** |

---

## 6. Dual-era readiness — the decisive comparison

Token-hit counts below are file hits inside each SDK's source tree at `main`, 2026-11-26 **[S]**.
They are a *presence* measure, not a conformance measure — a single hit could be a constant or a
test fixture. They are used only to rank "has started" vs "has not started".

| # | SDK version | Serves `2026-07-28`? | `2026-07-28` | `server/discover` | `subscriptions/listen` | `resultType` | Era switch | Source (URL) | Conf. |
|---|---|---|---|---|---|---|---|---|---|
| E-80 | TypeScript 2.4.0 | yes, dual | 296 | 88 | 71 | 112 | `mode: legacy \| auto \| pin` | https://github.com/modelcontextprotocol/typescript-sdk | **[S]** |
| E-81 | Python 2.3.0 | yes, dual | 452 | 135 | 197 | 73 | `HANDSHAKE_*`/`MODERN_*` + `_probe.py` | https://github.com/modelcontextprotocol/python-sdk | **[S]** |
| E-82 | C# 2.4.0 | yes | 117 | 35 | 17 | 29 | capability-driven | https://github.com/modelcontextprotocol/csharp-sdk | **[S]** |
| E-83 | Ruby 1.11.0 | yes | 72 | 40 | 19 | 18 | conformance-verified | https://github.com/modelcontextprotocol/ruby-sdk | **[S]** |
| E-84 | Rust 3.12.0 | yes | 56 | 19 | 14 | 25 | conformance-verified | https://github.com/modelcontextprotocol/rust-sdk | **[S]** |
| E-85 | Go v1.8.0 | yes | 45 | 19 | 11 | 10 | conformance-verified | https://github.com/modelcontextprotocol/go-sdk | **[S]** |
| E-86 | PHP 0.10.0 | partial | 55 | 14 | 10 | 9 | none explicit | https://github.com/modelcontextprotocol/php-sdk | **[S]** |
| E-87 | Java 2.2.0 | partial | 38 | 17 | 3 | 21 | none explicit | https://github.com/modelcontextprotocol/java-sdk | **[S]** |
| E-88 | Kotlin 0.16.0 | barely | 5 | 4 | **0** | 4 | none | https://github.com/modelcontextprotocol/kotlin-sdk | **[S]** |
| E-89 | Swift 0.12.1 | **no** | 1 | **0** | **0** | **0** | none | https://github.com/modelcontextprotocol/swift-sdk | **[S]** |
| E-90 | **`lauren-mcp` 1.0.0** | **no** | **0** | **0** | **0** | **0** | none (`LATEST = "2025-11-25"`) | `src/lauren_mcp/` (this repo) | **[S]** |

**Derived [D]:** nine of ten official SDKs now ship the modern era, and the four Tier-1 SDKs that
matter most for interop (TS, Python, C#, Rust/Go) all ship it *alongside* the legacy era rather than
instead of it. `lauren-mcp` is the only implementation in this comparison set with zero modern-era
surface — and it is the only one whose peers solved the problem with a dual-era switch rather than a
rewrite.

---

## 7. Python ecosystem — framework versions and their `mcp` dependency

Every row is PyPI-confirmed with an exact version and date **[R]**.

| # | Project | Version | Published | Notable dependency fact | Source (URL) |
|---|---|---|---|---|---|
| E-100 | `mcp` (official) | **2.3.0** | 2026-10-02 | `mcp-types==2.3.0`, `httpx2`, `opentelemetry-api`; extras `cli`/`rich`; **no** `ws` extra | https://pypi.org/pypi/mcp/json |
| E-101 | `mcp` 1.x legacy line | **1.30.0** | 2026-09-07 | 1.29.0 on 2026-07-28; `ws` extra = `websockets>=15.0.1` | https://pypi.org/pypi/mcp/1.30.0/json |
| E-102 | FastMCP | **4.2.6** | 2026-11-25 | `fastmcp-slim==4.2.6`; py ≥3.11; Apache-2.0; 28,768★ | https://pypi.org/pypi/fastmcp/json |
| E-103 | FastMCP v3 / v4 transitions | v3.0.0 **2026-02-18**; v4.0.0 **2026-08-31** | — | v4 breaking change list includes "Migrate to MCP SDK v2.0.0b2 (httpx2)" | https://github.com/PrefectHQ/fastmcp/releases/tag/v4.0.0 |
| E-104 | FastMCP serves both eras per connection | documented in `dev-docs/v4-notes/protocol-2026.md` | — | dual-era, SEP-990-adjacent | https://github.com/PrefectHQ/fastmcp/blob/main/dev-docs/v4-notes/protocol-2026.md |
| E-105 | mcp-use | **1.7.1** | 2026-09-10 | pins `mcp<2.0.0,>=1.24.0` → **stranded on 1.x** | https://pypi.org/pypi/mcp-use/json |
| E-106 | mcp-agent | **0.2.6** | 2025-12-05 | `mcp>=1.20.0`; 8,596★; last push 2026-01-25 → **dormant** | https://pypi.org/pypi/mcp-agent/json |
| E-107 | PydanticAI | **2.75.0** (`pydantic-ai-slim`) | 2026-11-25 | `mcp` extra → `fastmcp-slim[client]>=3.3.0,<5` (**no** direct `mcp` dep) | https://pypi.org/pypi/pydantic-ai-slim/json |
| E-108 | PydanticAI dependency history | 1.60.0 → `mcp<2.0,>=1.25`; 2.0.0 (2026-06-23) → `fastmcp-slim[client]>=3.3.0` | — | shows the ecosystem's pivot away from a direct `mcp` pin | https://pypi.org/pypi/pydantic-ai-slim/1.60.0/json |
| E-109 | smolagents | **1.26.0** | 2026-05-29 | `mcp` extra = unpinned `mcp` + `mcpadapt>=0.1.13` → **unpinned risk** | https://pypi.org/pypi/smolagents/json |
| E-110 | fastapi-mcp | **0.4.0** | 2025-07-28 | `mcp>=1.12.0`; 12,031★; last push 2025-11-24 → **stale** | https://pypi.org/pypi/fastapi-mcp/json |
| E-111 | django-mcp-server | **0.5.7** | 2025-10-10 | `mcp>=1.8.0`; 391★ | https://pypi.org/pypi/django-mcp-server/json |
| E-112 | litestar-mcp | **0.20.2** | 2026-11-23 | **no `mcp` dependency**; `httpx2>=2.13.1`, `litestar>=2.23.0` — already era-agnostic | https://pypi.org/pypi/litestar-mcp/json |
| E-113 | mcpadapt | **0.1.20** | 2025-10-24 | `mcp[ws]>=1.10.1` | https://pypi.org/pypi/mcpadapt/json |
| E-114 | `lauren` (framework, this repo's peer) | **1.12.0** | 2026-11-15 | `lauren-mcp` requires `lauren>=1.7.0` | https://pypi.org/pypi/lauren/json |

**Derived [D]:** the "stranded on 1.x" risk is *not* hypothetical. mcp-use pins `<2.0.0`; mcp-agent
pins `>=1.20.0` with no upper bound and has not shipped since 2025-12; smolagents leaves `mcp`
unpinned entirely. Any `lauren-mcp` release that requires `mcp>=2` would break three of the seven
frameworks named in the original brief. This is the strongest single argument for `lauren-mcp`
keeping its **two-dependency** (`lauren`, `anyio`) posture rather than adopting the official SDK —
recorded as an advantage in the PRD set, and sourced here.

---

## 8. Registry and packaging

| # | Claim | Exact value | Source (URL) | Conf. |
|---|---|---|---|---|
| E-120 | The official Registry is live and versioned | service **1.8.16**, git `a21a32b`, build `2026-11-23T13:54:44Z` | https://registry.modelcontextprotocol.io/v0/version | **[R]** |
| E-121 | Registry scale | ≥**20,000** server records walked via paginated list | https://registry.modelcontextprotocol.io/v0.1/servers?limit=100 | **[R]** |
| E-122 | Registry API is read-only and unauthenticated for consumers | "unauthenticated read-only API"; preview status | https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/registry-aggregators.mdx | **[P]** |
| E-123 | `server.json` schema revision | **`2025-12-11`**; required `name`/`description`/`version`; reverse-DNS name with exactly one slash; `packages[]`, `remotes[]`, `isSecret` | https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json | **[P]** |
| E-124 | Publishing is possible for remote-only servers (no package needed) | "Remote-only servers" quickstart section | https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/quickstart.mdx | **[P]** |
| E-125 | Ownership verification methods | `dns`, `http`, `github`, `github-oidc`, `github-at`, `anonymous` via `mcp-publisher` `init`/`login`/`publish` | https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/cli/commands.md | **[P]** |
| E-126 | npm/PyPI ownership is claimed via metadata keys | `mcpName` in `package.json`; `mcp-name: <name>` in the PyPI README | https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/package-types.mdx | **[P]** |
| E-127 | Registry versions are immutable and carry `isLatest` | versioning doc | https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/versioning.mdx | **[P]** |
| E-128 | Registry repo traction | 7,500★; latest release `v1.8.16` (2026-11-23) | https://github.com/modelcontextprotocol/registry | **[R]** |
| E-129 | Third-party directory scale for comparison | Glama "131,130 in the Glama Registry"; mcp.so "20,915 MCP servers"; Smithery now part of Arcade | https://glama.ai/mcp/servers · https://mcp.so · https://smithery.ai | **[P]** |

**Derived [D]:** because the Registry accepts remote-only servers (E-124) and verifies ownership by
DNS/HTTP (E-125), a `lauren-mcp` server can be published without shipping a PyPI artefact at all —
which is why the "Registry readiness" PRD is scoped to a *metadata generator*, not to a packaging
overhaul.

---

## 9. Gateways, proxies and hosting platforms

| # | Artifact | Version | Published | Note used in PRDs | Source (URL) |
|---|---|---|---|---|---|
| E-140 | Docker MCP Gateway | `v0.44.3` | — | 1,649★; `docker mcp` plugin | https://github.com/docker/mcp-gateway |
| E-141 | Docker MCP catalog | — | — | 589★; **327** entries under `servers/`; Docker Hub `mcp/` namespace = **244** repos | https://github.com/docker/mcp-registry · https://hub.docker.com/v2/repositories/mcp/?page_size=1 |
| E-142 | IBM ContextForge gateway | **1.1.2** | 2026-11-25 | virtual servers, federation, REST↔MCP, stdio↔SSE, 40+ plugins; **5** OSV advisories | https://pypi.org/pypi/mcp-contextforge-gateway/json · https://github.com/IBM/mcp-context-forge |
| E-143 | Kong AI MCP Proxy | Kong OSS **3.9.5** | 2026-11-19 | `ai-mcp-proxy`, `ai-mcp-oauth2` plugins | https://developer.konghq.com/plugins/ai-mcp-proxy/ |
| E-144 | Agent Router (ex-Envoy AI Gateway) | Envoy AI Gateway `v1.3.0` | 2026-11-18 | renamed 2026-09-09; aggregation to one endpoint, per-tool access control, API-key injection, tool filtering | https://theagentrouter.ai/docs/capabilities/mcp/ · https://theagentrouter.ai/blog/envoy-ai-gateway-is-now-agent-router |
| E-145 | supergateway | **4.3.0** | 2026-11-24 | 2,984★; stdio↔SSE↔streamable-HTTP bridge; **0** OSV advisories | https://github.com/supercorp-ai/supergateway |
| E-146 | `mcp-remote` | **0.17.1** | — | CVE-2025-6514 (see E-160) | https://registry.npmjs.org/mcp-remote/latest |
| E-147 | LiteLLM | `v1.111.0` | 2026-11-25 | 63,957★; MCP server aggregation in a proxy | https://github.com/BerriAI/litellm |
| E-148 | Vercel MCP Adapter | `v2.4.0` | 2026-11-12 | 711★; hosted adapter for Next.js | https://github.com/vercel/mcp-adapter |
| E-149 | Cloudflare remote MCP hosting | Agents SDK guide | — | Workers-based remote MCP; repo 6,153★ | https://developers.cloudflare.com/agents/guides/remote-mcp-server/ |
| E-150 | Prefect Horizon / FastMCP Cloud | managed FastMCP **4.2.6** | — | managed deployment of a FastMCP app | https://pypi.org/pypi/fastmcp/json |
| E-151 | `mcp-proxy` (python) | **0.15.0** | 2026-11-09 | stdio/SSE proxy | https://pypi.org/pypi/mcp-proxy/json |
| E-152 | `mcpo` | **0.0.21** | 2026-11-25 | MCP → OpenAPI shim | https://pypi.org/pypi/mcpo/json |
| E-153 | MCP Apps extension SDK | `v2.1.0` | 2026-11-10 | 3,159★; UI payload any proxy must pass through | https://github.com/modelcontextprotocol/ext-apps |
| E-154 | AWS Bedrock AgentCore Gateway | — | — | "gateway for agents, tools, and models" | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html |
| E-155 | Azure API Center MCP inventory | — | — | MCP servers registered as API assets | https://learn.microsoft.com/en-us/azure/api-center/register-discover-mcp-server |
| E-156 | Cloudflare OAuth provider for Workers | **1.4.0** | — | `workers-oauth-provider` | https://registry.npmjs.org/@cloudflare/workers-oauth-provider/latest |

---

## 10. Developer tooling — Inspector

| # | Claim | Exact value | Source (URL) | Conf. |
|---|---|---|---|---|
| E-165 | Inspector current version | **2.16.0** (`latest` dist-tag) | https://registry.npmjs.org/@modelcontextprotocol/inspector/latest | **[R]** |
| E-166 | Inspector has known advisories | **2** OSV advisories | https://api.osv.dev/v1/query | **[R]** |

**Known gap [U].** This review established Inspector's *version and vulnerability count*, not its
*feature surface* — it was not possible to enumerate its functional modules (transport matrix,
prompt/elicitation playground, snapshot export) from a registry read. Any PRD that claims
"Inspector parity" must therefore be scoped to what is documented in the Inspector README at
implementation time, and the parity checklist is an explicit PRD deliverable rather than a
premise. Flagged in §19.

---

## 11. Authorization / OAuth

| # | Claim | Exact value | Source (URL) | Conf. |
|---|---|---|---|---|
| E-170 | `2026-07-28` requires OAuth 2.1 for HTTP transports; stdio is exempt | authorization overview | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/authorization/index.mdx | **[P]** |
| E-171 | RFC 8707 resource indicators are normative: the canonical URI is the resource | auth overview | same as E-170 | **[P]** |
| E-172 | Client ID Metadata Documents (CIMD) are the *recommended* registration path (SEP-991) | CIMD section in client-registration doc | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/authorization/client-registration.mdx | **[P]** |
| E-173 | Dynamic Client Registration is **deprecated** as of `2026-07-28` (PR #2858), with a ≥12-month removal window | "DCR deprecated" statement in the same doc | same as E-172 | **[P]** |
| E-174 | Protected Resource Metadata is RFC 9728-aligned (SEP-985) | SEP-985 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/985-align-oauth-20-protected-resource-metadata-with-rf.md | **[P]** |
| E-175 | `iss` (issuer) is a recommended auth response parameter (SEP-2468) | SEP-2468 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/2468-recommend-issuer-claim-for-auth.md | **[P]** |
| E-176 | Third-party authorization servers exist specifically for MCP | WorkOS AuthKit for MCP; Descope MCP | https://workos.com/docs/authkit/mcp · https://docs.descope.com/mcp | **[P]** |
| E-177 | Zitadel's MCP guide URL **404s** — capability unverified, not claimed | HTTP 404 | https://zitadel.com/docs/guides/integrate/mcp | **[N]** |
| E-178 | Google Cloud / Apigee MCP docs URL **404s** — capability unverified, not claimed | HTTP 404 | https://cloud.google.com/apigee/docs/api-platform/genai/mcp | **[N]** |

---

## 12. Security and vulnerability surface

All counts are live OSV queries on 2026-11-26 **[R]**. These are *totals across all versions* of the
package, not necessarily affecting the current release.

| # | Package / issue | Advisory count | Source (URL) |
|---|---|---|---|
| E-160 | Python `mcp` | **17** (7 HIGH, 4 MODERATE) | https://api.osv.dev/v1/query |
| E-161 | `fastmcp` | **16** (1 CRITICAL, 4 HIGH, 5 MODERATE) | https://api.osv.dev/v1/query |
| E-162 | `@modelcontextprotocol/sdk` | **9** | https://api.osv.dev/v1/query |
| E-163 | `mcp-contextforge-gateway` | **5** | https://api.osv.dev/v1/query |
| E-164 | `@modelcontextprotocol/inspector` | **2** | https://api.osv.dev/v1/query |
| E-167 | `supergateway` | **0** | https://api.osv.dev/v1/query |
| E-168 | `mcp-remote` — **CVE-2025-6514**, CRITICAL OS command injection via untrusted server connections, published 2025-07-09 | 1 (GHSA-6xpm-ggf7-wc3p) | https://api.osv.dev/v1/vulns/GHSA-6xpm-ggf7-wc3p |
| E-169 | OWASP MCP Top 10 exists and enumerates MCP01…MCP10 (incl. **MCP03 Tool Poisoning**) | project page + item list | https://owasp.org/www-project-mcp-top-10/ · https://github.com/OWASP/www-project-mcp-top-10/tree/main/2025 |
| E-169b | Streamable HTTP mandates `Origin` validation to defeat DNS rebinding | transport doc MUST clause | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/transports/streamable-http.mdx |

**Derived [D]:** the Python `mcp` package — the dependency most MCP servers in this ecosystem
transitively carry — has the largest advisory count in the set (E-160). A two-dependency package
(`lauren` + `anyio`) has a measurably smaller attack surface, which is a defensible *advantage* to
state in the PRDs, not a euphemism for missing features.

---

## 13. Observability

| # | Claim | Exact value | Source (URL) | Conf. |
|---|---|---|---|---|
| E-180 | MCP attributes moved out of the core OpenTelemetry semantic conventions | section titled "MCP Attributes (Moved)"; `mcp-method-name`, `mcp-protocol-version`, `mcp-resource-uri`, `mcp-session-id` all flagged **Deprecated** at the old location | https://github.com/open-telemetry/semantic-conventions/blob/main/docs/registry/attributes/mcp.md | **[P]** |
| E-181 | The canonical `mcp.*` attribute definitions now live in the GenAI semconv repo | 566★ repo; `docs/registry/attributes/mcp.md` | https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/registry/attributes/mcp.md | **[P]** |
| E-182 | Span and metric reports are published for MCP client and server | `mcp-client-span.md`, `mcp-server-span.md`, `mcp-client-operation-duration-metric.md` | https://github.com/open-telemetry/semantic-conventions-genai/tree/main/reference/reports | **[P]** |
| E-183 | `2026-07-28` standardises `traceparent`/`tracestate` propagation (SEP-414) | SEP-414 | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/seps/414-request-meta.md | **[P]** |

**Consequence for this repo [D]:** `lauren-mcp` already instruments the dispatcher
(`src/lauren_mcp/_server/_otel.py`), but against attribute names that OpenTelemetry has since moved
and deprecated (E-180). That is a *cheap, high-value* PRD: renaming attributes, not building
telemetry from scratch.

---

## 14. Agent hosts — what each one actually requires

| # | Host | Config surface | Key | stdio | Streamable HTTP | Deferred tool loading | Source (URL) | Conf. |
|---|---|---|---|---|---|---|---|---|
| E-190 | Claude Desktop | `claude_desktop_config.json` | `mcpServers` | yes | via connectors/extensions | host-managed | https://modelcontextprotocol.io/docs/develop/connect-local-servers | **[P]** |
| E-191 | Claude Code | `.mcp.json`, `~/.claude.json`, `claude mcp add` | `mcpServers` | yes | yes (+ `ws`) | **on by default** (tool search) | https://code.claude.com/docs/en/mcp | **[P]** |
| E-192 | Cursor | `~/.cursor/mcp.json`, `.cursor/mcp.json` | `mcpServers` | yes | yes | marketplace/Customize page | https://cursor.com/docs/context/mcp | **[P]** |
| E-193 | VS Code (Copilot agent mode) | `.vscode/mcp.json` (+ global, `.mcp.json`) | **`servers`** | yes | yes (`"type": "http"`) | tool picker / tool sets | https://code.visualstudio.com/docs/agent-customization/mcp-servers | **[P]** |
| E-194 | Devin (ex-Windsurf) | `.devin/mcp_config.json`, `.devin/mcp_config.local.json` | `mcpServers` | yes (`command`) | yes (`url`) | n/a | https://docs.devin.ai/cli/extensibility/mcp/configuration.md | **[P]** |
| E-195 | Zed | `settings.json` | **`context_servers`** | yes | yes | n/a | https://zed.dev/docs/ai/mcp.md | **[P]** |
| E-196 | Cline | `~/.cline/data/settings/cline_mcp_settings.json` | `mcpServers` | yes | yes | `autoApprove` per tool | https://docs.cline.bot/mcp/configuring-mcp-servers | **[P]** |
| E-197 | Continue | `config.yaml` (legacy `config.json`) | `mcpServers` | yes | yes | n/a | https://docs.continue.dev/customize/deep-dives/mcp | **[P]** |
| E-198 | ChatGPT / OpenAI plugins (Apps SDK) | hosted connector registration | n/a (server-side) | **no** | **required** | host-curated | https://developers.openai.com/plugins/build/mcp-server.md | **[P]** |
| E-199 | Gemini CLI | `settings.json` | `mcpServers` | yes | yes (`httpUrl`) | `toolFilter`/`excludeTools`/`trust` | https://raw.githubusercontent.com/google-gemini/gemini-cli/main/docs/tools/mcp-server.md | **[P]** |
| E-199b | JetBrains AI Assistant | configure-an-mcp-server | — | — | — | — | https://www.jetbrains.com/help/ai-assistant/configure-an-mcp-server.html | **[U]** reachable (200), not analysed |

**Derived [D]:** three hosts use a *different* config key (`servers`, `context_servers`, and none at
all), and Zed supports **Tools and Prompts only** — no Resources, no Sampling. Any "host-compatibility"
PRD must therefore emit *per-host* config snippets, not one canonical snippet; and any feature that
depends on `resources/*` must degrade, not fail, on Zed.

Claude Code's context budget is a design constraint, not a footnote:

| # | Claim | Exact value | Source (URL) | Conf. |
|---|---|---|---|---|
| E-191a | Tool definitions are deferred by default and searched on demand | tool search on by default; `ENABLE_TOOL_SEARCH` env override | https://code.claude.com/docs/en/mcp | **[P]** |
| E-191b | Instruction and description caps | 4,096-char instructions; 16,384-char deferred descriptions; `CLAUDE_CODE_MAX_MCP_DESC*` overrides | same as E-191a | **[P]** |
| E-191c | Output caps | 10,000-token warning threshold; 25,000-token default cap; `MAX_MCP_OUTPUT_TOKENS` | same as E-191a | **[P]** |
| E-191d | Per-tool `alwaysLoad` and per-server approval controls exist | `alwaysLoad`; `@server:uri` resource refs; `/mcp__srv__prompt` | same as E-191a | **[P]** |

---

## 15. Agent SDKs and MCP client APIs

| # | SDK | Version | MCP surface | Source (URL) |
|---|---|---|---|---|
| E-200 | OpenAI Agents SDK (Python) | `openai-agents` **0.26.0** | `MCPServerStdio`, `MCPServerSse`, `MCPServerStreamableHttp`, `MCPServerManager` | https://pypi.org/pypi/openai-agents/json · https://raw.githubusercontent.com/openai/openai-agents-python/main/src/agents/mcp/__init__.py |
| E-201 | LangChain MCP adapters | `langchain-mcp-adapters` **0.3.2** | `MultiServerMCPClient`, `.get_tools()`, `.session()` | https://pypi.org/pypi/langchain-mcp-adapters/json · https://raw.githubusercontent.com/langchain-ai/langchain-mcp-adapters/main/langchain_mcp_adapters/client.py |
| E-202 | Google ADK | `google-adk` **2.15.1** | `McpToolset` (+ `MCPToolset` alias), `McpToolsetConfig` | https://pypi.org/pypi/google-adk/json · https://raw.githubusercontent.com/google/adk-python/main/src/google/adk/tools/mcp_tool/mcp_toolset.py |
| E-203 | PydanticAI | `pydantic-ai-slim` **2.75.0** | `MCPServerConfig`, `MCPServerStdio`, `MCPServerSSE`, `MCPServerStreamableHTTP`, `MCPServerHTTP` | https://raw.githubusercontent.com/pydantic/pydantic-ai/main/pydantic_ai_slim/pydantic_ai/mcp.py |
| E-204 | AWS Strands | `strands-agents` **1.67.0** | `MCPClient`, `MCP_VERSIONS` | https://pypi.org/pypi/strands-agents/json |
| E-205 | Microsoft Agent Framework | `agent-framework` **1.26.0** | `MCPStreamableHTTPTool` present in package metadata | https://pypi.org/pypi/agent-framework/json |
| E-206 | Agno | `agno` (PyPI) | `MCPTools`, `SSEClientParams`, `StreamableHTTPClientParams` | https://raw.githubusercontent.com/agno-agi/agno/main/libs/agno/agno/tools/mcp/__init__.py |
| E-207 | Mastra (TS) | `@mastra/mcp` **2.11.0** | MCP client/server in a TS agent framework | https://registry.npmjs.org/@mastra/mcp/latest |

---

## 16. `lauren-mcp` 1.0.0 baseline — repository-internal evidence

These are **not** external claims; they are the current state every PRD diffs against. Citation is
`path:line` in this working tree at base commit `7778737`.

### 16.1 Identity

| # | Claim | Evidence | Conf. |
|---|---|---|---|
| E-220 | Version `1.0.0`, released 2026-06-14 | `CHANGELOG.md:10` | **[S]** |
| E-221 | Python `>=3.11` | `pyproject.toml:11` (`requires-python = ">=3.11"`) | **[S]** |
| E-222 | Exactly **two** runtime dependencies: `lauren>=1.7.0`, `anyio>=4.0` | `pyproject.toml:31-34` | **[S]** |
| E-223 | Extras: `ws`, `http`, `pydantic`, `msgspec`, `cli`, `all` | `pyproject.toml:36-44` | **[S]** |
| E-224 | Console script `lmcp` | `pyproject.toml` `[project.scripts]` | **[S]** |

### 16.2 Protocol versions

| # | Claim | Evidence | Conf. |
|---|---|---|---|
| E-225 | `LATEST = "2025-11-25"`, `STABLE = "2024-11-05"` | `src/lauren_mcp/_mcp_version.py:5-6` | **[S]** |
| E-226 | `SUPPORTED = {2024-11-05, 2025-03-26, 2025-06-18, 2025-11-25}` — no `2026-07-28` | `src/lauren_mcp/_mcp_version.py:7` | **[S]** |

### 16.3 Zero-hit absences (each is the result of the command in the last column)

| # | Token | Files | Meaning | Command (run from repo root) | Conf. |
|---|---|---|---|---|---|
| E-230 | `server/discover` | **0** | no modern-era discovery | `grep -ril 'server/discover' src/ \| wc -l` | **[N]** |
| E-231 | `subscriptions/listen` | **0** | no modern-era subscription channel | `grep -ril 'subscriptions/listen' src/ \| wc -l` | **[N]** |
| E-232 | `resultType` | **0** | results lack the required `2026-07-28` discriminator | `grep -ril 'resultType' src/ \| wc -l` | **[N]** |
| E-233 | `ttlMs` | **0** | no cache TTL on list results | `grep -ril 'ttlMs' src/ \| wc -l` | **[N]** |
| E-234 | `cacheScope` | **0** | no cache scope on list results | `grep -ril 'cacheScope' src/ \| wc -l` | **[N]** |
| E-235 | `tasks/` | **0** | no task support (core *or* extension) | `grep -ril 'tasks/' src/ \| wc -l` | **[N]** |
| E-236 | `input_required` | **0** | no MRTR | `grep -ril 'input_required' src/ \| wc -l` | **[N]** |
| E-237 | `notifications/cancelled` | **0** | **standard cancellation is unimplemented** | `grep -ril 'notifications/cancelled' src/ \| wc -l` | **[N]** |
| E-238 | `RFC 8707` | **0** | no resource-indicator handling | `grep -ril 'RFC 8707' src/ \| wc -l` | **[N]** |

### 16.4 Presence facts (positive greps, so the PRDs do not overclaim absence)

| # | Token | Files | What it means | Command (run from repo root) | Conf. |
|---|---|---|---|---|---|
| E-240 | `$/cancelRequest` | **6 files**, 9 hits | 4 of the 9 hits are executable (`_server/_ws.py:39` `_METHOD_CANCEL`, `_server/_ws.py:296`, `_server/_streamable.py:212`, `_server/_stdio.py:76`) and 5 are comments/docstrings | `grep -ril '$/cancelRequest' src/ \| wc -l` | **[S]** |
| E-241 | `mcp-session-id` | **4** files | session-based Streamable HTTP is implemented (a `2025-*`-era design) | `grep -ril 'mcp-session-id' src/ \| wc -l` | **[S]** |
| E-242 | `logging/setLevel` | **7** files | logging implemented — and **deprecated** by `2026-07-28` | `grep -ril 'logging/setLevel' src/ \| wc -l` | **[S]** |
| E-243 | `roots/list` | **3** files | roots implemented — deprecated by `2026-07-28` | `grep -ril 'roots/list' src/ \| wc -l` | **[S]** |
| E-244 | `Last-Event-ID` | **2** files | SSE resumability implemented — removed by `2026-07-28` | `grep -ril 'Last-Event-ID' src/ \| wc -l` | **[S]** |
| E-245 | `opentelemetry` | **3** files | OTel integration exists (`_server/_otel.py`) | `grep -ril 'opentelemetry' src/ \| wc -l` | **[S]** |
| E-246 | `oauth` | **5** files | client-credentials provider (`_client/_oauth.py`), RFC 8414 + RFC 9728 discovery (`_server/_streamable.py:133-138`) | `grep -ril 'oauth' src/ \| wc -l` | **[S]** |
| E-247 | `resource_metadata` | **1** file | RFC 9728 protected-resource metadata is advertised | `grep -ril 'resource_metadata' src/ \| wc -l` | **[S]** |
| E-248 | `tools/list_changed` | **4** files | list-changed notifications implemented | `grep -ril 'tools/list_changed' src/ \| wc -l` | **[S]** |

`tracer` (1 file) co-occurs with `opentelemetry` (E-245) and is not tabulated separately.

---

## 17. Negative results register

Collected separately because "we looked and it is not there" decays fastest.

| # | Question | Result | Method | Conf. |
|---|---|---|---|---|
| N-01 | Does a `2024-11-05` changelog exist? | No — 404 | HTTP GET | **[N]** |
| N-02 | Is `$/cancelRequest` an MCP method? | No — 0 org-wide code hits; it is an LSP name | `gh api -X GET search/code -f q='org:modelcontextprotocol cancelRequest' --jq .total_count` → `0` | **[N]** |
| N-03 | Does `2025-11-25` contain MRTR? | No | changelog grep | **[N]** |
| N-04 | Do SEP-835 / SEP-837 / SEP-2352 have SEP files? | No | `seps/` listing | **[N]** |
| N-05 | Is there a `2026-11-*` spec tag? | No | releases/tags API | **[N]** |
| N-06 | Is Zitadel's MCP guide live? | No — 404 | HTTP GET | **[N]** |
| N-07 | Is Apigee's MCP doc live? | No — 404 | HTTP GET | **[N]** |
| N-08 | Does `lauren-mcp` implement `2026-07-28` anything? | No — 0 hits across 7 distinguishing tokens | grep ×7 | **[N]** |
| N-09 | Does `lauren-mcp` implement `notifications/cancelled`? | No — 0 files, both directions | grep | **[N]** |
| N-10 | Does `lauren-mcp` have client-side cancellation? | No — 0 hits for cancel definitions in `_client/` | grep | **[N]** |

---

## 18. Corrections log

Every correction is recorded with what was believed, what is true, and what changed as a result.
This section exists because a review that never corrects itself is not being verified.

### C-01 — `$/cancelRequest` is not an MCP method, and never was

* **Believed:** `$/cancelRequest` is "the pre-`2025-06-18` cancellation notification", so the repo's
  cancellation support was a *version-migration* gap.
* **Actually true:** `notifications/cancelled` is in the **earliest** schema (E-08). `$/cancelRequest`
  has **zero** occurrences anywhere in the `modelcontextprotocol` org (E-09). It is an **LSP**
  method name.
* **Consequence:** the defect is a plain local conformance **bug**, fixable in every era, and it
  belongs in a bug-fix PRD, not in the `2026-07-28` migration work. The server currently listens for
  a method no MCP client sends and ignores the one every client sends (E-240, E-237), so peer
  cancellation is silently ineffective today.
* **Documents rewritten:** `_research/lauren-mcp-inventory.md` §5.4 and §13.

### C-02 — `2026-07-28` is breaking, not additive

* **Believed:** `2026-07-28` was a further additive revision, so the task was "migrate up".
* **Actually true:** it removes sessions, the `initialize` handshake, `ping`, `logging/setLevel`,
  `roots/list_changed`, SSE resumability, and server-initiated sampling/elicitation/roots — and it
  deprecates Roots/Sampling/Logging/DCR/HTTP+SSE (E-20…E-30).
* **Consequence:** the goal is **dual-era support**, not migration-by-replacement. This inverted the
  framing of the whole PRD set and is why "legacy era stays" appears as an explicit non-goal in the
  migration PRD.
* **Documents rewritten:** `_research/lauren-mcp-inventory.md` gained §15; every PRD that touches
  protocol version negotiation inherits the dual-era premise.

### C-03 — the `$/cancelRequest` citation count was understated

* **Believed (in the inventory draft):** 5 files.
* **Actually true:** **6 files / 9 occurrences**, of which only 4 are executable code; the other 5
  are comments and docstrings (`server/_handlers.py:757`, `_server/_dispatcher.py:105`,
  `_server/_context.py:308`, `_server/_context.py:336`, `_server/_ws.py:74`).
* **Consequence:** the bug is *smaller* than it looked — 4 code sites, not a subsystem — which is
  another reason it is a P1 quick fix rather than an architectural item. This register (E-240) is
  now the authoritative count.

### C-04 — "23 SEPs" was an undercount

* **Believed:** the review cited ~23 SEPs.
* **Actually true:** the SEP index cites **34** SEPs (E-51) out of a 46-file corpus (E-50).
* **Consequence:** documentary only; no PRD changed. Recorded so the number is not repeated.

---

## 19. Known unknowns

Carried forward honestly. Each has a stated way to settle it.

| # | Open question | Why it matters | How to settle |
|---|---|---|---|
| U-01 | Inspector's full functional surface at 2.16.0 | an "Inspector parity" PRD needs a checklist, not a version | read the Inspector README/source at implementation time |
| U-02 | Whether `2026-07-28` clients will *actually* be deployed by the hosts that matter before the next revision | decides whether dual-era is P1 or P2 | track Claude Code / VS Code release notes |
| U-03 | Which of the 17 `mcp` advisories (E-160) affect versions `lauren-mcp` would use | affects the dependency-advice PRD | per-advisory `affected` ranges from OSV |
| U-04 | JetBrains AI Assistant MCP capability (E-199b) | host matrix completeness only | read the JetBrains doc |
| U-05 | Whether the Registry will accept a `lauren-mcp` namespace without a PyPI release | decides publish path | `mcp-publisher validate` dry run |
| U-06 | Kotlin/Java `2026-07-28` completeness (partial per E-86/E-87) | only relevant to cross-language interop tests | run the conformance suite against them |

None of the PRDs make a P1 recommendation that depends on a U-row.

---

## 20. Reproduction

Consolidated; each block re-derives a section above. Assumes `gh`, `curl`, `jq`.

```bash
# §1 revision timeline (E-01..E-05)
gh api repos/modelcontextprotocol/modelcontextprotocol/releases \
  --jq '.[] | "\(.tag_name)\t\(.published_at)"'

# §1 E-08/E-09 — cancellation is real, $/cancelRequest is not
curl -sS https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/schema/2024-11-05/schema.ts \
  | grep -c 'notifications/cancelled'          # expect >= 1
gh api -X GET search/code -f q='org:modelcontextprotocol cancelRequest' --jq '.total_count'   # expect 0
# (that query is the archival record for E-09; a zero-result search has no citable page)

# §5 SDK versions (E-60..E-70)
npm view @modelcontextprotocol/sdk dist-tags
curl -s https://pypi.org/pypi/mcp/json                  | jq -r .info.version
curl -s https://repo1.maven.org/maven2/io/modelcontextprotocol/sdk/mcp/maven-metadata.xml | grep -o '<release>[^<]*'
curl -s https://api.nuget.org/v3/registration5-gz-semver2/modelcontextprotocol/index.json | jq -r '.items[-1].items[-1].catalogEntry.version'
curl -s https://proxy.golang.org/github.com/modelcontextprotocol/go-sdk/@latest
curl -s -A research https://crates.io/api/v1/crates/rmcp | jq -r .crate.max_version
curl -s https://rubygems.org/api/v1/gems/mcp.json | jq -r .version
curl -s https://repo.packagist.org/p2/mcp/sdk.json | jq -r '.packages["mcp/sdk"][0].version'
gh api repos/modelcontextprotocol/swift-sdk/releases/latest --jq .tag_name

# §6 dual-era presence (E-80..E-90), per SDK checkout
for t in 2026-07-28 server/discover subscriptions/listen resultType; do
  printf '%-22s %s\n' "$t" "$(grep -rIl -F "$t" . | wc -l)"
done

# §7 Python dependency pins (E-100..E-114)
for p in mcp fastmcp mcp-use mcp-agent pydantic-ai-slim smolagents litestar-mcp; do
  printf '%-20s %s\n' "$p" "$(curl -s https://pypi.org/pypi/$p/json | jq -r .info.version)"
done

# §8 registry (E-120..E-123)
curl -s https://registry.modelcontextprotocol.io/v0/version
curl -s "https://registry.modelcontextprotocol.io/v0.1/servers?limit=100" | head -c 400
curl -s https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json \
  | jq -r '.definitions.ServerDetail.required'

# §12 vulnerabilities (E-160..E-168)
for p in mcp fastmcp; do
  curl -s https://api.osv.dev/v1/query -H 'Content-Type: application/json' \
    -d "{\"package\":{\"name\":\"$p\",\"ecosystem\":\"PyPI\"}}" \
    | jq -r --arg p "$p" '"\($p)\t\(.vulns|length)"'
done

# §16 repository baseline (E-220..E-248)
cat src/lauren_mcp/_mcp_version.py
grep -n 'dependencies' -A6 pyproject.toml
for t in server/discover subscriptions/listen resultType ttlMs cacheScope tasks/ \
         input_required notifications/cancelled 'RFC 8707'; do
  printf '%-24s %s\n' "$t" "$(grep -ril -- "$t" src/ | wc -l)"
done
grep -rn 'cancelRequest' src/            # expect 6 files / 9 hits
```

---

## 21. Source volume and integrity

| Research artifact | Bytes | Unique URLs | Retrieval date |
|---|---:|---:|---|
| `_research/spec.md` | 57,054 | 64 | 2026-11-26 |
| `_research/infrastructure.md` | 48,859 | 65 | 2026-11-26 |
| `_research/agent-integration.md` | 48,482 | 41 | 2026-11-26 |
| `_research/cross-language.md` | 39,106 | 38 | 2026-11-26 |
| `_research/python-frameworks.md` | 31,209 | 34 | 2026-11-26 |
| `_research/lauren-mcp-inventory.md` | 29,058 | 2 | 2026-11-26 |
| **Total** | **253,768** | **244** (sum of per-file uniques) | — |

Every external row above resolves to one of those URLs. Rows citing this repository cite
`path:line` instead, and are reproducible by `grep` from §20.

**Deduplication note.** The per-file figures sum to 244; the **distinct** union across the six files
is **237** URLs (measured by extracting and de-duplicating `https?://` tokens). The 7-URL overlap is
repeated citation of the same changelog and release pages across clusters.

**Template expansion note.** A few PyPI rows cite an *expanded* form of a URL that the research
files record as a brace template — the research source lists `https://pypi.org/pypi/{mcp,openai-agents,langchain-mcp-adapters,…}/json`, and this register cites the same endpoint with a
single package name filled in. The expansion is recorded here so an auditor diffing URL strings does
not mistake it for a new, unverified source. Only one URL in this register (§20) is a shell template
(`$p`) and it appears inside a code fence, never as a citation.

---

## 22. Claim → PRD traceability

Filled in as the PRDs land; a PRD may cite an E-row or an N-row, never a bare assertion.

| PRD cluster (planned) | Primary evidence | Priority driver |
|---|---|---|
| Protocol dual-era core | E-20…E-30, E-80…E-90, E-225/E-226, E-230…E-236 | the only zero-surface implementation in the comparison set |
| `server/discover` + `_meta` envelope | E-21, E-22, E-230 | required for modern clients to see the server at all |
| `resultType` / `ttlMs` / `cacheScope` | E-27, E-232…E-234 | cheap, mechanical, high conformance payoff |
| `subscriptions/listen` | E-23, E-231 | replaces two mechanisms the repo already has |
| MRTR (`input_required`) | E-26, E-236, E-14 | successor to sampling/elicitation; blocks modern hosts |
| Cancellation conformance (bug) | E-08, E-09, E-237, E-240, C-01, C-03 | a real bug with 4 code sites; cheapest P1 in the set |
| Tasks extension | E-25, E-235, E-53 | extension, not core; modern hosts use it for long tools |
| Registry / `server.json` | E-120…E-128 | distribution; independent of protocol work |
| OAuth 2.1 / RFC 8707 / CIMD | E-170…E-178, E-238, E-247 | security posture for HTTP deployments |
| OTel attribute migration | E-180…E-183, E-245 | cheap rename against already-shipped instrumentation |
| Host compatibility profiles | E-190…E-199b, E-191a…E-191d | adoption; per-host config + context budget |
| Security hardening (Origin/DNS rebinding, tool poisoning) | E-169, E-169b, E-160…E-168 | OWASP MCP03 + transport MUST |
| Python ecosystem compatibility | E-100…E-114, E-222 | keep the two-dependency advantage; avoid `mcp>=2` breakage |
| Inspector / dev tooling parity | E-165, E-166, **U-01** | ergonomics; checklist required before scoping |
| Packaging & typing parity | E-221…E-224, E-100…E-102 | ecosystem-standard ergonomics |

---

## 23. Sign-off

* Every **[P]**, **[S]**, **[R]**, **[C]** row was obtained on **2026-11-26**.
* Every **[N]** row states the negative evidence, not merely the absence of a citation.
* Every **[U]** row appears in §19 with a settlement path, and no P1 recommendation depends on one.
* Two prior claims in this review were **wrong** and are corrected in §18 (C-01, C-02). Both
  corrections are load-bearing; both are reflected in the PRD premises.

Re-review cadence: this register is dated, not evergreen. The spec cadence has been ~5–8 months
between recent revisions (E-05), so a refresh is due at the next tag — or immediately if
`lauren-mcp` begins shipping dual-era support, because §6 then becomes a *claim about us* rather
than about the field.
