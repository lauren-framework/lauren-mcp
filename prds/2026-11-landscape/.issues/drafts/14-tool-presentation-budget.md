**PRD:** [`prd-tool-presentation-budget.md`](https://github.com/lauren-framework/lauren-mcp/blob/docs/mcp-landscape-2026-11/prds/2026-11-landscape/prd-tool-presentation-budget.md)
**Priority:** P2 — The host now decides how much tool text exists (deferred search, 16,384-char descriptions, 10,000/25,000-token caps); we have no budget-aware presentation
**Theme:** Schemas and tools
**Key evidence:** E-191a, E-191b, E-191c — see `EVIDENCE.md` in the same directory.

## Problem

Claude Code defers tool definitions by default and searches them on demand (`ENABLE_TOOL_SEARCH`, E-191a). That changes what `tools/list` *means*: not "the text the model reads" but "the corpus the host indexes and later quotes". The corpus has hard edges:

| Limit | Value | Anchor |
|---|---|---|
| Server `instructions` | 4,096 chars | E-191b |
| One deferred tool description | 16,384 chars | E-191b |
| Output warning / hard cap | 10,000 / 25,000 tokens | E-191c |
| Overrides | `ENABLE_TOOL_SEARCH`, `CLAUDE_CODE_MAX_MCP_DESC*`, `MAX_MCP_OUTPUT_TOKENS` | E-191a..c |
| Per-tool pinning | `alwaysLoad` | E-191d |

## Goals

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

## Acceptance criteria

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

Drafted from the 2026-11 MCP landscape review (evidence retrieved 2026-11-26). Full PRD, evidence register (`EVIDENCE.md`) and `VERSIONS-MATRIX.md` live in `prds/2026-11-landscape/` on branch `docs/mcp-landscape-2026-11`.
