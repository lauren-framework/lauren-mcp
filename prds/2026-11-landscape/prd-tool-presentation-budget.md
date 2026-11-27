# PRD — Tool presentation and the context budget

**Status:** Draft
**Date:** 2026-11-26
**Scope:** `lauren-mcp` server layer (`server/_presentation.py` (new), `server/_meta.py`, `server/_decorators.py`, `server/_handlers.py`, `server/_module.py`), CLI (`cli/_commands.py`, `cli/__init__.py`), docs (`docs/guides/decorators.md`, `mkdocs.yml`), `llms-full.txt`
**Priority:** P2 — not a conformance blocker. A server shipping today is *correct*; it is simply **invisible** to a host that budgets tool text, and it can hand a host 300 KB of output with no marker saying so. The wire stays byte-identical for existing clients unless a policy is declared, so regression risk is near zero — while the cost of doing nothing is slow and silent: a host-side heuristic summarises our tools for us, or drops them from its searchable set.
**Cross-references:** `prd-host-compatibility-profiles.md` (host identity), `prd-result-envelope-caching.md` (list-result `_meta`), `prd-transport-security-hardening.md` (shares §4.4's digest).

---

## 1. Problem Statement

### 1.1 The host, not the server, now decides how much tool text exists

Claude Code defers tool definitions by default and searches them on demand (`ENABLE_TOOL_SEARCH`, E-191a). That changes what `tools/list` *means*: not "the text the model reads" but "the corpus the host indexes and later quotes". The corpus has hard edges:

| Limit | Value | Anchor |
|---|---|---|
| Server `instructions` | 4,096 chars | E-191b |
| One deferred tool description | 16,384 chars | E-191b |
| Output warning / hard cap | 10,000 / 25,000 tokens | E-191c |
| Overrides | `ENABLE_TOOL_SEARCH`, `CLAUDE_CODE_MAX_MCP_DESC*`, `MAX_MCP_OUTPUT_TOKENS` | E-191a..c |
| Per-tool pinning | `alwaysLoad` | E-191d |

Other hosts expose *selection* rather than *search*: Gemini CLI has `toolFilter`, `excludeTools` and per-server `trust` (E-199); Cursor a Customize-page picker (E-192); VS Code tool pickers and tool sets (E-193). Three shapes of one question — *what should this host see, in what form, how much?* — and this repo answers none of them.

### 1.2 We have the vocabulary; the serialiser ignores it

`@mcp_tool` already accepts `name`, `description`, `title`, `annotations`, `timeout`, `tags`, `meta`, `output_schema`, `structured_output`, `strict` — `src/lauren_mcp/server/_decorators.py:758-769` (`description` `:761`, `title` `:762`, `tags` `:765`, `meta` `:766`), with `tags` documented presentationally: *"Categorical tags included in the tool's ``tools/list`` entry"* (`:782`). The values land in `McpToolMeta` (`src/lauren_mcp/server/_meta.py:46`, fields `:49-62`) and reach the wire in `_tool_list_entry` (`src/lauren_mcp/server/_handlers.py:563`): `name` `:564`, `title` `:565-566`, `description` `:567`, `inputSchema` `:568`, `annotations` `:569-570`, `outputSchema` `:571-572`, `tags` `:573-574`, `_meta` `:575-576`.

What does not exist is **audience**. Every field is emitted unconditionally, in one shape, at one size, to every client. `make_tools_list_handler(tools)` takes the catalogue and nothing else (`_handlers.py:580-582`), and its handler ignores `req.params` entirely (`:591`):

```python
# src/lauren_mcp/server/_handlers.py  line 591
return {"tools": [_tool_list_entry(t) for t in get_tools()]}
```

No policy argument, no request-`_meta`, no budget, no digest, no cursor. (Cursors are out of scope — that is `prd-result-envelope-caching.md`'s list surface; §3.) The tooling is equally blind: `lmcp inspect` prints `f"  {t.name}: {t.description}"` from its own decoded client objects (`cli/_commands.py:95`, `:99-101`) — never bytes, never a size — which is why `docs/guides/decorators.md:87-96` documents a signature that has already drifted from source (it omits `title`, present at `_decorators.py:762`).

### 1.3 Measured: where the bytes actually are

The docstring pipeline already collapses prose to the **first paragraph** and pushes parameter detail into the schema (`parse_docstring` returns `(top_description, {param: description})` — `server/_docstring.py:144`; injected at `server/_schema.py:324-327`). Measured on this worktree with the repo's own code, for one three-parameter tool (`search_docs(query, limit=10, collection=None)` with a three-entry `Args:` block):

| Measurement (compact JSON) | Bytes |
|---|---|
| Whole `tools/list` entry | **544** |
| `inputSchema` alone | **392** (72 %) |
| of which per-parameter `description` strings | **227** (42 %) |
| tool `description` | **77** |
| `title` | **22** |
| hypothetical `{name, description}` only | **99** |

Two further probes: **docstrings lose paragraphs** — a four-paragraph docstring reaches the wire as its first paragraph (60 chars here) with `Args:` promoted into the schema, so a longer *tool* description cannot come from a docstring at all; and **explicit `description=` is unbounded** — `"Explicit long description. " * 40` arrives verbatim at 1,080 chars with no cap, no warning, and no relationship to the 16,384-char host cap (E-191b).

Worst of both worlds: prose authors want kept is dropped silently, prose that survives is unbounded, and 42 % of the record is parameter commentary a deferring host cannot match until the tool is already chosen.

### 1.4 Output is unbounded, and silent about it

`grep -ril 'truncat' src/lauren_mcp --include=*.py | wc -l` → **0**. `_coerce_tool_result` (`_handlers.py:627`) builds `{"content": [...], "isError": ..., "structuredContent": ...}` (`:670-672`) and returns it (`:673`) at whatever size the tool produced. A 2 MB tool result is a 2 MB `tools/call` result; the host either overshoots its 25,000-token cap (E-191c) or clips on its own terms, out of our sight.

Silence is the defect, not size. A host that cuts at 25,000 tokens shows the model a payload that *looks complete*, and a model that cannot tell "the list ends here" from "the list was cut here" answers confidently from a fragment. Blind cutting is no fix either: `image`/`audio`/`resource` blocks are opaque binaries, and an MCP Apps UI payload must pass through intact (E-153, `ext-apps` v2.1.0).

---

## 2. Goals

1. **Per-tool presentation declared where tools are declared**: `@mcp_tool(..., summarise=..., max_tokens=..., verbatim=...)` — no second decorator, no registry.
2. **A server-level `PresentationPolicy`** applied at serialisation time, inside `_tool_list_entry`/`make_tools_list_handler`, never in user code.
3. **A compact mode**: name + one-sentence summary + tags + digest for hosts that defer and search; the full record for hosts that do not.
4. **Deterministic, documented mode selection**: request `_meta` hint > per-host profile > policy default > env override.
5. **Long descriptions cut at a declared cap, with a marker** — never silently, never on a `verbatim=True` tool.
6. **A stable tool-set digest** in the `tools/list` result `_meta`, with per-tool digests for differential invalidation.
7. **`tools/call` output bounded with an explicit marker** and a machine-readable `_meta` record; binary and UI blocks never cut.
8. **`lmcp inspect --presentation`** showing the bytes a chosen host would receive, with byte and estimated-token totals.
9. **Zero new runtime dependencies**, with a documented estimator error band and an injection point.

### Acceptance checklist

- [ ] `grep -c 'class PresentationPolicy' src/lauren_mcp/server/_presentation.py` ≥ `1`.
- [ ] `grep -n 'summarise' src/lauren_mcp/server/_decorators.py` hits inside `mcp_tool` (`:758-769`).
- [ ] `grep -ril 'truncat' src/lauren_mcp --include=*.py | wc -l` ≥ `1` (today: `0`).
- [ ] `grep -c 'toolset' src/lauren_mcp/server/_handlers.py` ≥ `1`.
- [ ] `uv run pytest tests/unit/test_presentation_policy.py -q` passes.
- [ ] `uv run pytest tests/unit/test_presentation_estimator.py -q` passes.
- [ ] `uv run pytest tests/integration/test_presentation_budget.py -q` passes.
- [ ] `uv run lmcp inspect examples/filesystem/server.py:FilesystemServer --presentation --host claude-code` exits 0 and prints both `est_tokens` and `sha256:`.
- [ ] `uv run lmcp inspect examples/filesystem/server.py:FilesystemServer --presentation --json | python -c "import json,sys; d=json.load(sys.stdin); assert d['tools'] and all('bytes' in t for t in d['tools'])"` exits 0.
- [ ] `uv run pytest tests/unit/test_presentation_policy.py -q -k compact_budget` passes (20 tools × 200-char descriptions under 24 KB compact).
- [ ] `uv run python scripts/check_llms_full.py` exits 0.
- [ ] `uv run python -c "import lauren_mcp as m; assert {'PresentationPolicy','PresentationHint'} <= set(dir(m))"` exits 0.

---

## 3. Non-Goals

- **`nextCursor` pagination of `tools/list`.** A different mechanism with a different failure mode; it belongs to `prd-result-envelope-caching.md`. This PRD makes entries smaller, never fewer.
- **A tokenizer.** No `tiktoken`, no `transformers`, no vendored BPE; the posture stays `lauren` + `anyio` (`pyproject.toml:27-30`).
- **Host-side search semantics.** No retrieval, ranking or query rewriting — we emit text that retrieves well.
- **Negotiating presentation on the wire.** No MCP capability means "I defer definitions" (§4.4); we invent none.
- **Runtime LLM summarisation**, and **enforcing** the 25,000-token cap as a hard failure. `summarise=` is author-supplied or deterministic; we clamp our own output and say so.
- **MCP Apps rendering.** E-153 constrains what we must not touch (§4.7), not what we render.

---

## lauren-mcp Advantages

1. **The vocabulary is already authored.** `title`, `annotations`, `tags` and `meta` are on the decorator today (inventory §6.1; `_decorators.py:758-769`, `_meta.py:46-62`) and already reach the wire (`_handlers.py:564-576`). A policy is a *projection* of data users have written, not a competing authoring surface — where most Python MCP frameworks would need a second metadata channel.

2. **One serialisation choke point, one result choke point.** Every tool record comes from `_tool_list_entry` (`_handlers.py:563`), called by one handler (`:591`), registered by one module (`server/_module.py:457`); every call result passes `_coerce_tool_result` (`:627`, returned `:673`) before `_module.py:458` registers it. A policy and a clamp are therefore one call each, total for dynamic-catalogue, `_openapi.py`-generated and hand-decorated tools alike, and not a per-transport rewrite across ws/http/stdio.

3. **Per-request identity is already plumbed.** `TransportBinding` carries `session_id` and `client_capabilities` (`_server/_binding.py:33`, `:36`), reachable via `CURRENT_BINDING` (`:40`; used at `_handlers.py:537`), and `initialize` already parses `clientInfo.name/version` (`server/_module.py:369-380`). Per-host presentation needs one field in `binding.extras` (`_binding.py:37`) and a host-table lookup — no new plumbing layer.

---

## 4. Design

### 4.1 Vocabulary — `PresentationHint`, three new keywords

New module `src/lauren_mcp/server/_presentation.py`, importable without `typer` or `anyio` (mirroring the constraint on `_hosts.py`): one dataclass, three keyword-only decorator parameters after `meta` (`_decorators.py:766`), one defaulted `McpToolMeta` field after `meta` (`_meta.py:59`).

```python
# src/lauren_mcp/server/_presentation.py  (new)
@dataclass(frozen=True, slots=True)
class PresentationHint:
    summary: str | None = None      # one sentence; the deferral stub's body
    max_tokens: int | None = None   # cap for this tool's description prose
    verbatim: bool = False          # never rewrite, never cut (UI payloads)
    always_load: bool = False       # advisory: ask the host to pin (E-191d)

# _decorators.py:766 gains summarise=, max_tokens=, verbatim=
# _meta.py:59       gains presentation: PresentationHint = field(default_factory=PresentationHint)
```

filled at construction (`_decorators.py:843-856`, beside `tags=`/`meta=` at `:852-853`). `summarise=` keeps the issue's spelling; the field is `summary` so `hint.summary` reads well. Three additive rules: `summarise=None` **derives** (first sentence of `description`, cut at a word boundary to `PRESENTATION_SUMMARY_CHARS = 120`); `max_tokens=None` **inherits** `policy.description_max_tokens`; `verbatim=True` is **absolute** — it beats `summarise`, `max_tokens`, compact mode and the output clamp.

### 4.2 `PresentationPolicy` — one server-level value

A frozen dataclass in the same new module, every field defaulted: `mode="full"`, `description_max_tokens=800` (~2.9 KB of prose, far under the 16,384-char host cap), `instructions_max_tokens=900` (~3.2 KB, under 4,096 chars), `output_max_tokens=20_000` (under 25,000, leaving marker room — §4.7), `drop_parameter_descriptions=True` (compact mode only), `estimator=chars_over_four` and `chars_per_token=3.6` (§4.5).

Resolution order, first hit wins, pure and table-testable: **(1)** per-request hint, `params._meta["lauren-mcp/presentation"] ∈ {"full","compact"}` on `tools/list`; **(2)** `presentation_policy = PresentationPolicy(...)` as a class attribute, read as other class-level config is read (`server/_module.py:169-176`); **(3)** host profile from `_hosts.py`, keyed by `clientInfo.name` captured at `_module.py:377-380`; **(4)** `LAUREN_MCP_PRESENTATION=full|compact`, read once behind `resolve_mode()`. (4) is the package's first server-side `os.environ` read: `grep -rn environ src/lauren_mcp --include=*.py | wc -l` → `4`, none under `server/`.

### 4.3 What each mode emits

| Field | `full` | `compact` (deferral stub) | Why |
|---|---|---|---|
| `name` | yes | yes | never rewritten |
| `title` | yes | yes | 22 bytes; cheap disambiguation |
| `description` | capped at `description_max_tokens` | `summary` (≤ 120 chars) | the stub is what a searcher matches |
| `tags` | yes | yes | our native grouping signal; maps onto E-192/E-193 pickers |
| `annotations` | yes | yes | `readOnlyHint` drives host auto-approval; never dropped |
| `inputSchema` types/required/enum/defaults | yes | yes | search hits must still validate |
| `inputSchema.properties[].description` | yes | dropped | 42 % of the record, useless pre-selection |
| `outputSchema` | yes | dropped | only meaningful at call time |
| `_meta` | yes | `{"lauren-mcp/presentation": {...}}` | §4.6 |

The compact record is the same shape minus prose, so **no client can fail on it**: every removed key is one a client must already tolerate as absent.

### 4.4 How the mode is chosen — and the honest gap

**There is no MCP capability meaning "I defer tool definitions."** E-191a is a host *setting*, not a wire advertisement, and nothing in the 2025-11-25 or 2026-07-28 cores supplies a deferral signal (E-191a..d describe client behaviour, not negotiation). So this PRD does not claim to negotiate; it layers §4.2's four deterministic inputs and accepts the consequences: a host ignoring our hint gets `full` (bigger payload, never wrong content), a host recognised by `clientInfo.name` gets its profile's mode, and an application that knows its deployment sets `presentation_policy` and stops guessing. The hint is a namespaced extension inside the spec's `_meta` escape hatch, so peers that do not understand it ignore it (§7).

### 4.5 Budgeting without a tokenizer — approximate, monotone, injectable

The estimator is one line of arithmetic — `ceil(len(text) / chars_per_token)` — and its only contract is monotonicity: if A is longer than B, A never estimates cheaper, which is all the trigger logic needs.

**The error band, stated.** For English prose and minified JSON, `chars/4` under-counts by roughly 0–15 % on prose-heavy text (real ratios near 3.4–3.6) and over-counts on ASCII identifiers, base64 and digit runs. So we (a) default `chars_per_token` to the conservative **3.6** rather than the folklore 4.0, (b) decide truncation against 85 % of the declared cap (`BUDGET_SAFETY = 0.85`), and (c) never print an estimate as a fact — `lmcp inspect --presentation` shows exact `bytes` beside approximate `est_tokens`, with a footnote. `PresentationPolicy.estimator` is `Callable[[str], int]`, so an app owning a tokenizer passes `lambda s: len(enc.encode(s))` and gets exact behaviour with no change to our code; `lmcp inspect --chars-per-token` exposes the same seam.

### 4.6 A stable tool-set digest

`list_changed` tells a host that *membership* moved; content identity is missing.

```python
# src/lauren_mcp/server/_presentation.py  (new)
def toolset_digest(entries: list[dict[str, Any]]) -> str:
    payload = json.dumps(entries, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()
```

Emitted once on the result: `_meta["lauren-mcp/toolset"] = {"digest": "sha256:9c1f…", "count": 12, "bytes": 18422, "estTokens": 5120, "mode": "compact", "policy": "description_max_tokens=800;drop_parameter_descriptions=true"}`, plus `_meta["lauren-mcp/tools"]` mapping each name to its own digest.

Three properties, each a test: **(i) the digest covers post-presentation bytes** — what the host receives, not what the author wrote. A pre-projection digest would stay constant while the compact rendering changed: exactly the substitution an attacker wants. This is the shared hook with `prd-transport-security-hardening.md` — that PRD pins a description hash out-of-band, this one guarantees it is computed over the emitted projection; if the two land with different helper names, `toolset_digest` is canonical. **(ii) Per-tool digests** let a host invalidate one entry without discarding the other 39. **(iii) `policy` is inside the digest input**, so a policy change forces a re-fetch while a no-op redeploy does not.

### 4.7 Truncating output — with a marker, and one class of bytes we never touch

Applied at the single choke point, after `_coerce_tool_result` builds `out` (`_handlers.py:670-673`): `clamp_result(out, meta, policy)` returns `out` unchanged when `meta.presentation.verbatim` is set or `policy.estimator(serialise(out)) <= policy.output_max_tokens * BUDGET_SAFETY`.

**(1)** `verbatim=True` short-circuits everything — MCP Apps tools declare it and an `ext-apps` UI payload must arrive whole (E-153). **(2)** Non-text blocks are never cut: any block whose `type` is not `"text"` (`image`, `audio`, `resource`, future binary) passes through untouched, because cutting base64 is corruption rather than truncation; they still count toward `est_tokens`, so the marker can be honest about overshoot. **(3)** Text blocks are cut at a budget-derived boundary and a marker block appended last:

```json
{"content": [{"type": "text", "text": "...first N chars..."},
  {"type": "text", "text": "[lauren-mcp: output truncated - 412,908 of 1,204,113 bytes shown (34%). Raise with @mcp_tool(max_tokens=...) or LAUREN_MCP_MAX_OUTPUT_TOKENS. Full-payload digest sha256:7d1e...; send _meta.lauren-mcp/full=true to receive it whole.]"}],
 "_meta": {"lauren-mcp/truncated": {"shownBytes": 412908, "totalBytes": 1204113, "estTokens": 17000}}}
```

**(4)** `structuredContent` is clamped only if it alone exceeds the budget, and then by dropping the largest array/object leaves while adding `"_truncated": true` plus the `_meta` record — never invalid JSON, never a valid-looking partial structure without the flag; if it is clamped, the `content[0]` text mirror is marked too, since hosts render one or the other. `output_max_tokens=20_000` × `BUDGET_SAFETY=0.85` → 17,000 estimated tokens, leaving room for a host wrapper and the marker, which is how E-191c's 25,000 cap is respected.

### 4.8 `lmcp inspect --presentation`

Extends the existing command (`cli/_commands.py:71`, registered `cli/__init__.py:20`), rendering from the **raw result dict** it already receives from `list_tools()`:

```
$ lmcp inspect examples/filesystem/server.py:FilesystemServer --presentation --host claude-code
host    claude-code  (from _hosts.py: defers=True, tool search on by default, E-191a)
tool                 bytes  est_tokens  desc_chars  props  dropped
search_docs            312       87          61         3   prop-descriptions
tools/list total     1,204      334   digest sha256:9c1f...  (full mode: 2,681 bytes)
footnote: est_tokens is chars/3.6 - approximate, +/-20% on mixed prose/JSON.
```

`--json` emits the same facts as a document, so CI can assert a budget — which the acceptance checklist does. `--mode full|compact` and `--chars-per-token` let an author diff both renderings of one line of code.

---

## 5. Server-side and CLI-side Changes

- **New** `src/lauren_mcp/server/_presentation.py`: `PresentationHint`, `PresentationPolicy`, `chars_over_four`, `project_entry`, `toolset_digest`, `clamp_result`, `resolve_mode` (stdlib imports only).
- **`server/_meta.py`** one defaulted field (`:46-62`); **`server/_decorators.py`** three keyword-only parameters (`:758-769`), docstring lines beside `tags` (`:782`), `presentation=` at construction (`:843-856`).
- **`server/_handlers.py`** `_tool_list_entry(t, policy=None)` (`:563`); `policy=` on `make_tools_list_handler` (`:580`) plus a `req.params._meta` read; `clamp_result` at the `_coerce_tool_result` return (`:673`).
- **`server/_module.py`** build the policy once near `:158-176`; pass at `:440`/`:441`; stash the negotiated mode in `binding.extras` (`_binding.py:37`) from `_initialize_handler` (`:367-386`); clamp `instructions` at `:409`.
- **`cli/_commands.py`** `--presentation`, `--host`, `--mode`, `--chars-per-token`, `--json` on `inspect_cmd` (`:71-79`), rendering in `_inspect_async` (`:82-111`).
- **Docs**: fix the drifted signature at `docs/guides/decorators.md:87-96` while adding the three keywords; new `docs/guides/presentation.md` (with the estimator band); `mkdocs.yml` nav after `:98`; `llms-full.txt` for the new names (`scripts/check_llms_full.py:3`, `noxfile.py:193`); export both in `src/lauren_mcp/__init__.py:__all__` (`:83`).

## 6. Exact Lines to Change

| `path:line` | Current | Change |
|---|---|---|
| `server/_presentation.py` | absent | new module (§4.1, §4.2, §4.5–§4.7) |
| `server/_meta.py:59` | `meta: dict[str, Any] = field(default_factory=dict)` | add `presentation: PresentationHint = ...` after it |
| `server/_decorators.py:766` | `meta: dict[str, Any] \| None = None,` | add `summarise`, `max_tokens`, `verbatim` after it |
| `server/_decorators.py:782` | `tags:` docstring line | add the three new docstring lines |
| `server/_decorators.py:852` | `tags=frozenset(tags) if tags else frozenset(),` | add `presentation=PresentationHint(...)` to the same call |
| `server/_handlers.py:563` | `def _tool_list_entry(t: McpToolMeta) -> dict[str, Any]:` | add defaulted `policy`; project the entry |
| `server/_handlers.py:580` | `def make_tools_list_handler(tools) -> _Handler:` | add `policy: PresentationPolicy \| None = None` |
| `server/_handlers.py:591` | `return {"tools": [...]}` | project per resolved mode; attach the `_meta` digest |
| `server/_handlers.py:673` | `return out` | `return _presentation.clamp_result(out, meta, policy)` |
| `server/_module.py:409` | `{"instructions": result.instructions}` | clamp to `instructions_max_tokens` |
| `server/_module.py:440` | `_tl_inner = make_tools_list_handler(catalog.list_tools)` | pass `policy=self._presentation` |
| `server/_module.py:377-380` | `client_info = Implementation(name=..., version=...)` | record `clientInfo.name` for host lookup |
| `cli/_commands.py:71-79` | `inspect_cmd(..., transport="ws")` | add the five options |
| `cli/_commands.py:99-101` | `typer.echo(f"  {t.name}: {t.description}")` | presentation table when `--presentation`; unchanged otherwise |
| `src/lauren_mcp/__init__.py:83` | `__all__ = [` | add `"PresentationPolicy"`, `"PresentationHint"` |
| `docs/guides/decorators.md:87-96` | signature block missing `title` | add `title`, `summarise`, `max_tokens`, `verbatim` |
| `mkdocs.yml:98` | last Guides entry (`guides/tool-lauren-params.md`) | add `- Presentation & Budgets: guides/presentation.md` |

## 7. Backward Compatibility

**Wire.** With no `PresentationPolicy` and no new keywords, `resolve_mode()` returns `"full"`, `project_entry()` is the identity, `clamp_result()` returns `out` untouched, and unknown `_meta` keys are inert. `tools/list` and `tools/call` stay byte-identical, key order included (`_handlers.py:564-576`), so result-comparing tests keep passing — and a golden test against `_tool_list_entry` makes that a test rather than a hope.

**API and `_meta`.** One defaulted keyword on `_tool_list_entry`, one on `make_tools_list_handler`, one defaulted field on `McpToolMeta`; `PresentationHint` is frozen with all-default fields, so nothing positional changes. New `_meta` keys are namespaced `lauren-mcp/...` and appear only when a non-`full` mode or a clamp happened; clients that ignore `_meta` are unaffected, which is what `_meta` exists to guarantee.

**Output.** Only payloads over `output_max_tokens × 0.85` change, and visibly: one extra text block plus a `_meta` record. A tool returning 200 KB today and relying on a silent host clip now returns ~17 k estimated tokens plus a marker — strictly more information for the model.

**Migration notes: none** — no import moves, no renamed argument, no default flipped, no environment variable read unless set. `verbatim` exists so that anything which must not change does not.

## 8. Test Plan

- **`tests/unit/test_presentation_policy.py`** — mode resolution over a (hint, class attribute, host profile, env) table; `project_entry` against §4.3 field-by-field; golden test that a default policy reproduces today's `_tool_list_entry` bytes; `compact_budget` (20 tools under 24 KB).
- **`tests/unit/test_presentation_estimator.py`** — CJK/emoji/empty inputs; monotonicity over 1,000 random strings; `BUDGET_SAFETY` arithmetic; the injected estimator is really called (spy); `--chars-per-token` rejects `0`, negative, `nan`.
- **`tests/unit/test_presentation_digest.py`** — key-insertion-order independence; equality across `PYTHONHASHSEED=0/1` subprocesses; digest moves on a description or policy change and not on a repeated `tools/list`; per-tool digests move independently.
- **`tests/unit/test_presentation_truncate.py`** — passthrough under budget; exactly one marker per clamp; a 10 MB `image` block preserved; `verbatim=True` short-circuit; `structuredContent` clamp sets `_truncated`; no path emits invalid JSON.
- **`tests/integration/test_presentation_budget.py`** — stdio fixture: compact `tools/list` under a search-capable hint; digest round-trip (cache, re-list, equal); a 1 MB result returns clamped over the wire; `_meta.lauren-mcp/full=true` returns the full payload.
- **`tests/unit/test_cli_commands_coverage.py`**, **`tests/docs/`** — `--json` document shape; `--host nope` exits 1 listing valid ids; `--presentation` without `--host` defaults to `full`; the decorator guide's fenced signature parses (the `:87-96` drift).

## 9. Open Questions

1. **The error band is unmeasured.** `chars/3.6` is a documented heuristic, not a calibrated constant, and no tokenizer exists in this repo, so I cannot measure it here. Proposal: a CI-only calibration job against a real BPE on our own docs, failing above 15 % median error. Until then §4.5's band is an assertion.
2. **Do hosts read `result._meta`?** E-191a..d do not say. If none does, the digest benefits only `lmcp inspect` — cheap and namespaced, so low-risk to ship, but claiming hosts will *use* it would be unsupported.
3. **Whether a compact stub hurts retrieval.** Dropping parameter prose removes 42 % of the record, and a searching host may match words that appeared only there. §4.3's split (summary + tags carry intent, parameters carry mechanics) is a hypothesis needing measurement against a real host's search.
4. **`structuredContent` clamping and `alwaysLoad`.** Dropping array leaves could delete the one element a model needed, while refusing to clamp violates §1.4's premise — a decision for the result-envelope owner. And we can *advise* per-tool pinning (E-191d) but cannot verify any host honours it.
5. **Digest vs `list_changed` races.** The digest is computed at serialisation so it is always true, but a host caching on the notification holds a stale-to-live window; whether that needs a monotonic counter depends on host behaviour we cannot observe.

## 10. References

**Evidence.** E-191a (tool search on by default, `ENABLE_TOOL_SEARCH`), E-191b (4,096-char instructions, 16,384-char deferred descriptions, `CLAUDE_CODE_MAX_MCP_DESC*`), E-191c (10,000-token warning, 25,000-token cap, `MAX_MCP_OUTPUT_TOKENS`), E-191d (`alwaysLoad`), E-192, E-193, E-199 (Gemini CLI `toolFilter`/`excludeTools`/`trust`), E-153 (`ext-apps` v2.1.0). Rows verified in `EVIDENCE.md`: E-191a..d `:367-370`, E-192 `:348`, E-193 `:349`, E-199 `:355`, E-153 `:263`.

**Inventory and source.** `_research/lauren-mcp-inventory.md` §6.1 (`:221-241`, `mcp_tool` surface `:225-226`). Verified lines: `server/_decorators.py:758-769`, `:782`, `:843-856`; `server/_meta.py:49-62`; `server/_handlers.py:563-577`, `:591`, `:627`, `:670-673`; `server/_docstring.py:144`; `server/_module.py:169-176`, `:367-386`, `:409`, `:440-441`; `_server/_binding.py:33`, `:36`, `:37`, `:40`; `cli/_commands.py:71-79`, `:95`, `:99-101`; `mkdocs.yml:97-98`.

**Siblings.** `prd-host-compatibility-profiles.md`, `prd-result-envelope-caching.md`, `prd-transport-security-hardening.md`. **Measurements** in §1.3 come from `uv run python` against `_decorators.mcp_tool`, `_handlers._tool_list_entry` and `_docstring.parse_docstring` on this worktree (compact JSON, `separators=(",", ":")`).
