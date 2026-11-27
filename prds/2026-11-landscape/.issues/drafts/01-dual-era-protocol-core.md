**PRD:** [`prd-dual-era-protocol-core.md`](https://github.com/lauren-framework/lauren-mcp/blob/docs/mcp-landscape-2026-11/prds/2026-11-landscape/prd-dual-era-protocol-core.md)
**Priority:** P1 — Only the legacy era is served: `initialize`-only handshake, closed version list, session-bound state, so a `2026-07-28` peer cannot connect
**Theme:** Protocol core
**Key evidence:** E-20, E-21, E-22 — see `EVIDENCE.md` in the same directory.

## Problem

`lauren-mcp` 1.0.0 implements the legacy era completely and the modern era not at all. The
VERSIONS-MATRIX capability delta records `2026-07-28` as **absent**: `server/discover` = 0 hits,
`resultType` = 0, `subscriptions/listen` = 0. That is not a missing feature; it is a closed door,
because the modern era replaces the *entry point* of the protocol rather than adding to it.

A host built against `2026-07-28` does not send `initialize`. It sends `server/discover`, which the
specification tree makes mandatory (E-21: "The `initialize` handshake is **removed** for modern
peers; `server/discover` is a MUST"). Our dispatcher has no handler for that method, so the request
falls through to the unknown-method branch:

## Goals

1. **One process, two eras.** Answer both `2024-11-05`…`2025-11-25` (legacy) and `2026-07-28`
   (modern) peers with no configuration change beyond extending the supported set.
2. **A mandatory `server/discover`.** Returns supported revisions, server info, capabilities, and
   instructions in one round trip (E-21).
3. **Per-request era detection.** Resolved from the request — the `_meta` envelope's
   `io.modelcontextprotocol/protocolVersion` (E-22) or the `Mcp-Protocol-Version` header — never from
   process-global state. Two clients on one process must not see each other's dialect.
4. **Sessionless modern HTTP.** A modern `tools/call` with no `Mcp-Session-Id` is served (E-20).
5. **Result shaping at the edge.** Modern results carry `resultType` (E-27); list results additionally
   carry `ttlMs` and `cacheScope`. Legacy results do not.
6. **`ping`, `logging/setLevel`, `roots/list_changed` stay absent for modern peers.** They are removed
   in `2026-07-28` (E-24); answering `-32601` to a modern `ping` is correct, and this PRD must not
   "helpfully" keep them alive.
7. **Legacy wire output is byte-identical.** `tests/unit/test_mcp_handshake.py` passes unmodified.
8. **No new runtime dependency** — `anyio`, `McpDispatcher`, and existing controllers only (E-222).

### 2.1 Acceptance criteria

- [ ] `grep -ril 'server/discover' src/ | wc -l` ≥ 1 (currently 0, E-230).
- [ ] `grep -ril 'resultType' src/ | wc -l` ≥ 1 (currently 0, E-232).
- [ ] `python -c "from lauren_mcp._mcp_version import SUPPORTED; assert '2026-07-28' in SUPPORTED"`
      exits 0.
- [ ] `pytest tests/unit/test_era.py tests/unit/test_result_shape.py -q` passes.
- [ ] `pytest tests/unit/test_mcp_handshake.py -q` passes with **zero** edits to that file.
- [ ] `pytest tests/integration/test_dual_era_streamable.py -q` passes: one module, two clients,
      interleaved requests, each receiving its own era's result shape.
- [ ] `negotiate_version("2026-07-28") == "2026-07-28"` and
      `negotiate_version("2019-01-01") == STABLE`.
- [ ] No new entry under `[project.dependencies]` in `pyproject.toml`.

## Acceptance criteria

- [ ] `grep -ril 'server/discover' src/ | wc -l` ≥ 1 (currently 0, E-230).
- [ ] `grep -ril 'resultType' src/ | wc -l` ≥ 1 (currently 0, E-232).
- [ ] `python -c "from lauren_mcp._mcp_version import SUPPORTED; assert '2026-07-28' in SUPPORTED"`
      exits 0.
- [ ] `pytest tests/unit/test_era.py tests/unit/test_result_shape.py -q` passes.
- [ ] `pytest tests/unit/test_mcp_handshake.py -q` passes with **zero** edits to that file.
- [ ] `pytest tests/integration/test_dual_era_streamable.py -q` passes: one module, two clients,
      interleaved requests, each receiving its own era's result shape.
- [ ] `negotiate_version("2026-07-28") == "2026-07-28"` and
      `negotiate_version("2019-01-01") == STABLE`.
- [ ] No new entry under `[project.dependencies]` in `pyproject.toml`.

---

Drafted from the 2026-11 MCP landscape review (evidence retrieved 2026-11-26). Full PRD, evidence register (`EVIDENCE.md`) and `VERSIONS-MATRIX.md` live in `prds/2026-11-landscape/` on branch `docs/mcp-landscape-2026-11`.
