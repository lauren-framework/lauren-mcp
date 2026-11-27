**PRD:** [`prd-result-envelope-caching.md`](https://github.com/lauren-framework/lauren-mcp/blob/docs/mcp-landscape-2026-11/prds/2026-11-landscape/prd-result-envelope-caching.md)
**Priority:** P1 — No `resultType`, `ttlMs` or `cacheScope` in any result (`grep -ril resultType src/` returns 0, E-232), so hosts cannot cache or date one
**Theme:** Protocol core
**Key evidence:** E-20, E-21, E-26 — see `EVIDENCE.md` in the same directory.

## Problem

`lauren-mcp` implements the legacy era completely and has **zero** `2026-07-28` surface (EVIDENCE §2; `grep -ril 'resultType' src/` → `0`, E-232). Two failures follow from this repository's own code.

Every result is an undecorated JSON object. `tools/list` ends here:

## Goals

1. Every successful result returned to a peer identifying as `2026-07-28` carries `resultType`. Legacy peers receive byte-identical output.
2. `tools/list`, `resources/list`, `prompts/list` results carry `ttlMs` and `cacheScope` for modern peers only.
3. Cache policy is declarative at registration time — one server-level value, no handler signature change.
4. Our clients honour `ttlMs`/`cacheScope`; `force_refresh=True` bypasses the cache on every list method.
5. The client cache invalidates on `list_changed` and on `connect()`.
6. Zero new runtime dependencies: `time.monotonic` and `anyio` only (E-222).

### Acceptance checklist

- [ ] `grep -ril 'resultType' src/lauren_mcp --include=*.py | wc -l` ≥ `1` (today: `0`, E-232).
- [ ] `grep -ril 'ttlMs' src/lauren_mcp --include=*.py | wc -l` ≥ `1` (today: `0`, E-233).
- [ ] `grep -ril 'cacheScope' src/lauren_mcp --include=*.py | wc -l` ≥ `1` (today: `0`, E-234).
- [ ] `uv run pytest tests/unit/test_result_envelope.py -q` passes.
- [ ] `uv run pytest tests/unit/test_list_cache.py -q` passes.
- [ ] `uv run pytest tests/integration/test_result_envelope_caching.py -q` passes.
- [ ] `uv run pytest tests/unit/test_result_envelope.py -q -k legacy` passes (§7 byte test).
- [ ] `uv run pytest tests/unit -q` shows no new failures (CI baseline: `.github/workflows/tests.yml:155`).
- [ ] `grep -n '^import \|^from ' src/lauren_mcp/_client/_cache.py` lists only `__future__`, `time`, `dataclasses`, `typing`.
- [ ] `python -c "from lauren_mcp.server import mcp_server; import inspect; print('cache' in inspect.signature(mcp_server).parameters)"` prints `True`.

## Acceptance criteria

- [ ] `grep -ril 'resultType' src/lauren_mcp --include=*.py | wc -l` ≥ `1` (today: `0`, E-232).
- [ ] `grep -ril 'ttlMs' src/lauren_mcp --include=*.py | wc -l` ≥ `1` (today: `0`, E-233).
- [ ] `grep -ril 'cacheScope' src/lauren_mcp --include=*.py | wc -l` ≥ `1` (today: `0`, E-234).
- [ ] `uv run pytest tests/unit/test_result_envelope.py -q` passes.
- [ ] `uv run pytest tests/unit/test_list_cache.py -q` passes.
- [ ] `uv run pytest tests/integration/test_result_envelope_caching.py -q` passes.
- [ ] `uv run pytest tests/unit/test_result_envelope.py -q -k legacy` passes (§7 byte test).
- [ ] `uv run pytest tests/unit -q` shows no new failures (CI baseline: `.github/workflows/tests.yml:155`).
- [ ] `grep -n '^import \|^from ' src/lauren_mcp/_client/_cache.py` lists only `__future__`, `time`, `dataclasses`, `typing`.
- [ ] `python -c "from lauren_mcp.server import mcp_server; import inspect; print('cache' in inspect.signature(mcp_server).parameters)"` prints `True`.

---

Drafted from the 2026-11 MCP landscape review (evidence retrieved 2026-11-26). Full PRD, evidence register (`EVIDENCE.md`) and `VERSIONS-MATRIX.md` live in `prds/2026-11-landscape/` on branch `docs/mcp-landscape-2026-11`.
