**PRD:** [`prd-deprecation-lifecycle.md`](https://github.com/lauren-framework/lauren-mcp/blob/docs/mcp-landscape-2026-11/prds/2026-11-landscape/prd-deprecation-lifecycle.md)
**Priority:** P2 — Five of the six features `2026-07-28` deprecates ship with no signal, no sunset revision, no removal path
**Theme:** Protocol core
**Key evidence:** E-30, E-41, E-42 — see `EVIDENCE.md` in the same directory.

## Problem

`lauren-mcp` 1.0.0 implements the whole legacy era (`2024-11-05` … `2025-11-25`). Five of the six
features that `2026-07-28` deprecates are implemented here, on the hot path:

* `logging/setLevel` — 7 files, 11 occurrences (E-242): `server/_module.py:427` (registration),
  `_server/_context.py:60` (state cell), `_server/_context.py:383` (emission).
* `roots/list` — 3 files (E-243): `_client/_stdio.py:372`, `_client/_base_remote.py:201`.
* Sampling — `_server/_context.py:437`; elicitation — `_server/_context.py:547`.
* HTTP+SSE transport — `_server/_sse.py:48` (`mcp_http_sse_controller`), GET stream `:109`, RPC `:140`.
* `Last-Event-ID` resumability — 2 files (E-244): `_server/_streamable.py:476`, `_server/_event_store.py:7`.

## Goals

1. Add `src/lauren_mcp/lifecycle.py` with `LifecycleStatus` (`ACTIVE`/`DEPRECATED`/`REMOVED`),
   `FeatureRecord` (`deprecated_in`, `removed_in`, `replacement`, `see`) and a `FEATURES` mapping covering
   every MCP feature this repo implements, sourced from the spec's deprecation registry (E-42).
2. Emit exactly **one warning per process per deprecated feature**, at registration or first use,
   suppressible by environment variable or standard `warnings` filters.
3. Generate `docs/reference/deprecation-lifecycle.md` from `FEATURES` via a committed script with a
   `--check` mode, plus a test asserting the checked-in page equals the rendered page.
4. Record a keep / keep+alias / remove decision per deprecated feature, with the window arithmetic
   (`2026-07-28` + 12 months = `2027-07-28`) written out.
5. Cross-reference each deprecated feature to its replacement (sampling/elicitation → MRTR, E-26; logging
   → `_meta.logLevel`, E-22; roots → cwd hints; DCR → CIMD, E-172; HTTP+SSE → Streamable HTTP, E-20/E-28),
   and expose it as `lauren_mcp.lifecycle` plus `lmcp inspect --features`.

**Removal is not a goal.** Each of these features is spec-valid, shipping and inside its deprecation
window (E-41); removing one would break existing users — see §3.

## Acceptance criteria

- [ ] public surface present — `python -c "from lauren_mcp.lifecycle import FEATURES, FeatureRecord, LifecycleStatus, deprecated_features, warn_feature; print(len(FEATURES))"`
- [ ] six deprecated keys, none removed, all naming a replacement — `python -c "from lauren_mcp.lifecycle import deprecated_features as d; assert all(f.removed_in is None and f.replacement for f in d()); print(sorted(f.key for f in d()))"`
- [ ] no behaviour removed — `git diff --stat HEAD -- src/lauren_mcp/_server/` shows additive hunks only, and
      `grep -rn "NotImplementedError" src/lauren_mcp/_server/_context.py` is empty
- [ ] warning fires once per process per feature — `pytest tests/unit/test_lifecycle_registry.py -k warn_once`
- [ ] warning suppressible — `LAUREN_MCP_LIFECYCLE_WARNINGS=0 pytest tests/unit/test_lifecycle_registry.py -k suppressed`
- [ ] `ctx.log` still emits `notifications/message` — `pytest tests/integration/test_lifecycle_warnings.py -k legacy_peer`
- [ ] docs table generated, not hand-written — `python scripts/generate_deprecation_table.py && python scripts/generate_deprecation_table.py --check`
- [ ] registry/doc drift fails the build — `pytest tests/unit/test_lifecycle_registry.py -k checked_in_table`
- [ ] CLI surfaces the table — `lmcp inspect --features | grep -c deprecated` ≥ 6
- [ ] no new runtime dependency — `grep -A4 "^dependencies" pyproject.toml` lists only `lauren` and `anyio`
- [ ] gates green — `nox -s tests`, `nox -s lint`, `nox -s typecheck`, `nox -s docs`

---

Drafted from the 2026-11 MCP landscape review (evidence retrieved 2026-11-26). Full PRD, evidence register (`EVIDENCE.md`) and `VERSIONS-MATRIX.md` live in `prds/2026-11-landscape/` on branch `docs/mcp-landscape-2026-11`.
