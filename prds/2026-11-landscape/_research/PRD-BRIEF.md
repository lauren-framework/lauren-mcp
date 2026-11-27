# PRD Writing Brief — `prds/2026-11-landscape/`

Read this before writing. It is the contract for every `prd-*.md` in this directory.

---

## 1. Context you must already have

`lauren-mcp` **1.0.0** is a Python MCP server+client for the Lauren framework. It implements the
MCP **legacy era** (`2024-11-05` … `2025-11-25`) completely, has **zero** `2026-07-28` (modern era)
surface, and has one genuine conformance bug (it listens for `$/cancelRequest`, an LSP method name,
instead of `notifications/cancelled`).

Three documents in this directory are your inputs — read the relevant sections before writing:

| File | What it gives you |
|---|---|
| `EVIDENCE.md` | 187 numbered claim rows (`E-…`), each with URL/date/version, plus negative results (`N-…`) and a corrections log. **Cite these IDs.** |
| `VERSIONS-MATRIX.md` | The readable matrices: revisions, mandatory modern-era surface per implementation, SDK/Python/host/infra versions, and the `lauren-mcp` capability delta table (§9). |
| `_research/lauren-mcp-inventory.md` | Source-derived inventory of this repository at `7778737`: transports, methods, decorators, DI, auth, OTel, CLI, doc drift. |

**Never invent a fact about the spec, about a competitor, or about this repository.** Every empirical
claim resolves to an `E-…` row, a `_research/` section, or a `path:line` you verified with `grep`/`sed`
yourself. If you cannot verify something, write it as an explicit open question, not as a premise.

---

## 2. House style — copy it exactly

Model file: `../prd-protocol-version-negotiation.md` (18 KB). Structure:

```
# PRD — <Title in sentence case>

**Status:** Draft
**Date:** 2026-11-26
**Scope:** <one line naming the modules/files affected>
**Priority:** P1 | P2 | P3        <- this set adds this line; older PRDs lack it
**Issue:** (filled in later by the index step — leave the line as `**Issue:** _pending_`)

---

## 1. Problem Statement
### 1.1 <a concrete failure scenario>
### 1.2 <secondary problem>

## 2. Goals            <- numbered list, testable
## 3. Non-Goals        <- bullet list, explicit
## 4. Design
### 4.1 … (each with real code)
## 5. Server-side Changes        (and/or "Client-side Changes")
## 6. Exact Lines to Change      <- path:line, one subsection per file
## 7. Backward Compatibility
## 8. Test Plan
### 8.1 Unit tests — `tests/unit/test_<name>.py`
### 8.2 Integration tests — `tests/integration/test_<name>.py`
## 9. Open Questions
## 10. References        <- E-… IDs, spec URLs, competitor citations
```

Rules that make it read like the house style:

* **Code comments carry the path.** Inside code blocks, prefix with `# src/lauren_mcp/server/_handlers.py  line 757`.
* **Show the current code, then the new code.** Problem Statement quotes the actual existing code; Design shows the replacement. Two fences, not one.
* **Concrete over abstract.** `"2026-07-28"` not "the new version"; `_METHOD_CANCEL = "$/cancelRequest"` not "the cancel constant".
* **No marketing.** No "seamless", "world-class", "cutting-edge", "robust".
* **Acceptance criteria live inside Goals or as a checklist under §2** — measurable, e.g. "`grep -ril 'resultType' src/ | wc -l` returns ≥ 1".
* **Target length 18–30 KB.** Under 15 KB means you skipped a required section; over 40 KB means padding.

---

## 3. Required content per PRD

1. **Status header** — exactly as above including `**Priority:**`.
2. **Current-state evidence with citations** — quote this repo's real code with `path:line`, and cite
   `E-…` for anything external. A PRD that asserts a competitor's behaviour without an `E-…` ID is defective.
3. **`## lauren-mcp Advantages`** — a section the older PRDs lack and this set requires. State what
   this repo already has that a naive "just use the official SDK" approach would lose, citing the
   inventory §1/§6 (e.g. two runtime dependencies, DI injection, `@mcp_tool` surface). If a PRD has no
   genuine advantage, say so honestly in one paragraph rather than inventing one.
4. **Proposed API design with code examples** — importable, typed, showing the *user-facing* surface
   (decorator argument, factory kwarg, config field), then the internal wiring.
5. **Acceptance criteria** — as a `- [ ]` checklist, each with a verifiable command or test name.
6. **Test plan** — named test files and the specific cases.
7. **Migration notes** — what existing users must do; explicitly "none" if none, and *why* it is none.
8. **Explicit P1/P2/P3 priority** in the header, justified in one sentence somewhere in §2 or §3.

---

## 4. Priority semantics (use these, do not invent a new scale)

| Priority | Meaning | Test |
|---|---|---|
| **P1** | Correctness or interop blocker. A fielded client cannot talk to us, or we are non-conformant today, or a mandated security control is absent. | "Does this break a real deployment or the spec's MUST?" |
| **P2** | Standard capability that real hosts/SDKs already ship; absence costs features, not interop. | "Would a modern host silently degrade without it?" |
| **P3** | Ergonomics, packaging, developer tooling, or forward-looking extension work. | "Does nothing break if this slips a release?" |

Only ~6 of 20 PRDs may be P1. If you believe yours is P1, say which MUST or which failing deployment
justifies it.

---

## 5. Hard constraints

* **Additive only.** Write only your assigned files under `prds/2026-11-landscape/`. Do **not** edit
  `EVIDENCE.md`, `VERSIONS-MATRIX.md`, `_research/*`, or any pre-existing `prds/*.md`. Those are
  baseline-checksummed elsewhere.
* **`prds/` is gitignored** (`.gitignore:70`). After writing, run
  `git add -f prds/2026-11-landscape/prd-<yours>.md` and confirm with `git status --short` that the
  file is staged. Unstaged files are lost when a worktree is discarded.
* **Verify your own line numbers.** Any `path:line` you cite must be checked with
  `grep -n <symbol> <path>` before you write it. Wrong line numbers are the most common defect in this
  document class.
* **Python 3.11+**, `anyio` async, no new runtime dependency in any proposed design (the two-dependency
  posture — `lauren`, `anyio` — is a stated competitive asset; see `EVIDENCE.md` E-222 and §7 of EVIDENCE).
* **Optional extras pattern.** New capability that needs a third-party library goes behind an extra
  (`[project.optional-dependencies]`) with a clear `ImportError` message, matching the existing
  `ws`/`http`/`pydantic`/`msgspec`/`cli` pattern.

---

## 6. Self-check before you finish

```bash
F=prds/2026-11-landscape/prd-<yours>.md
wc -c "$F"                                  # expect 18000-30000
grep -c '^## ' "$F"                         # expect >= 9
grep -n 'lauren-mcp Advantages' "$F"        # must hit
grep -n '\*\*Priority:\*\* [P123]' "$F"     # must hit
git add -f "$F" && git status --short | grep "$(basename "$F")"
```

Report the byte count and the `git status` line in your final message.
