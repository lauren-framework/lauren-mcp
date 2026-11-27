**PRD:** [`prd-client-parity.md`](https://github.com/lauren-framework/lauren-mcp/blob/docs/mcp-landscape-2026-11/prds/2026-11-landscape/prd-client-parity.md)
**Priority:** P2 — Event store, subscriptions and cancellation exist server-side, but the four client transports expose no matching surface
**Theme:** Protocol core
**Key evidence:** E-81, E-200, E-201 — see `EVIDENCE.md` in the same directory.

## Problem

`lauren-mcp` implements the MCP **legacy era** (`2024-11-05` … `2025-11-25`) completely and has **zero** `2026-07-28` (modern era) surface (`_research/PRD-BRIEF.md:10-12`). That is usually read as a server claim, because the visible work happened in `src/lauren_mcp/_server/`: an event store (`_event_store.py`), a per-URI subscription manager (`_subscriptions.py`), session-aware Streamable HTTP (`_streamable.py`), and cancellation scaffolding (`_dispatcher.py:165` `def cancel(self, request_id: str | int) -> bool`).

The client did not follow. Measured with `grep -rlF`: `notifications/cancelled` appears in **0** files in `src/` (`E-237`) and `_client/` has no cancel API (`N-10`); `mode` appears in **0** client files and the revision is hard-coded at `_features.py:70`; `_meta` appears in **15** server files and **0** client files; `resultType`, `ttlMs` and `cacheScope` appear **nowhere** (`E-232`…`E-234`); `server/discover` is absent everywhere (`E-230`), as are `subscriptions/listen` (`E-231`) and `tasks/*` (`E-235`); `last-event-id` exists in `_server/_streamable.py` and `_server/_event_store.py` only. Every agent framework in the landscape wraps the same three transports behind one client object (`E-200`…`E-207`), and the official Python SDK ships all of it dual-era (`E-81`). A host here gets the server half of the 2026 stack and a 2025 client.

## Goals

1. Publish a **parity matrix** (§4.1) for every MCP method and notification, each column anchored by a verified `path:line`, plus `tests/unit/test_client_parity_matrix.py` so the table fails the build when it rots.
2. Make the client **cancellable**: `client.cancel(request_id)` and task-cancellation propagation that emits `notifications/cancelled`, removes the pending future in `finally`, discards a response that still arrives, and never converts `asyncio.CancelledError` into an `Exception`.
3. Give the client **era selection**: `era` (`"legacy" | "modern" | "auto"`) on all four factories, `SUPPORTED` validation, a defined reaction to a legacy-only server, and a `negotiated_era` property.
4. Add an **envelope reader and in-client cache** honouring `ttlMs`/`cacheScope`, invalidated by the three `list_changed` notifications and `resources/updated`.
5. Support **`server/discover`** as the first frame of an `auto` connection, with a timeout and a clean fallback to `initialize`.
6. Extend **`McpClientProtocol`** and add `tests/unit/test_client_transport_surface.py` so the four transports cannot drift apart.
7. Change **no default observable behaviour** apart from the single probe frame of §4.3.

### 2.1 Acceptance criteria

- [ ] `grep -rlF 'notifications/cancelled' src/ | wc -l` ≥ 2, and ≥ 1 under `src/lauren_mcp/_client`; `python -c "from lauren_mcp._client import McpRequestCancelled, McpEraMismatch"` exits 0.
- [ ] `grep -c 'async def cancel' src/lauren_mcp/_client/_protocol.py` ≥ 1; `grep -c 'CancelledError' src/lauren_mcp/_client/_base_remote.py` ≥ 2.
- [ ] `grep -c 'era' src/lauren_mcp/_client/_features.py` ≥ 6; `grep -rn '\bera=' src/lauren_mcp/_client/_factory.py | wc -l` ≥ 4; `grep -rn 'SUPPORTED' src/lauren_mcp/_client/ | wc -l` ≥ 1.
- [ ] `grep -c 'ttlMs'`, `'cacheScope'` and `'resultType'` over `src/lauren_mcp/_client/_cache.py` each ≥ 1; `grep -rn 'server/discover' src/lauren_mcp/_client/ | wc -l` ≥ 2; `grep -c 'last-event-id' src/lauren_mcp/_client/_streamable.py` ≥ 1.
- [ ] `pytest tests/unit/test_client_parity_matrix.py tests/unit/test_client_transport_surface.py -q` passes and the matrix literal matches §4.1 row for row.
- [ ] `pytest tests/unit/test_client_cancel.py tests/unit/test_client_era.py tests/unit/test_client_cache.py -q` passes.
- [ ] `pytest tests/integration/test_client_cancel_integration.py tests/integration/test_client_discover_integration.py -q` passes.
- [ ] `pytest tests/unit/test_client_transports_coverage.py tests/unit/test_client_changes.py tests/end_to_end/test_client_e2e.py -q` passes unmodified.
- [ ] `git diff --stat src/lauren_mcp/_server/ src/lauren_mcp/server/` is empty; `wc -c prds/2026-11-landscape/prd-client-parity.md` is 18000–30000.

## Acceptance criteria

- [ ] `grep -rlF 'notifications/cancelled' src/ | wc -l` ≥ 2, and ≥ 1 under `src/lauren_mcp/_client`; `python -c "from lauren_mcp._client import McpRequestCancelled, McpEraMismatch"` exits 0.
- [ ] `grep -c 'async def cancel' src/lauren_mcp/_client/_protocol.py` ≥ 1; `grep -c 'CancelledError' src/lauren_mcp/_client/_base_remote.py` ≥ 2.
- [ ] `grep -c 'era' src/lauren_mcp/_client/_features.py` ≥ 6; `grep -rn '\bera=' src/lauren_mcp/_client/_factory.py | wc -l` ≥ 4; `grep -rn 'SUPPORTED' src/lauren_mcp/_client/ | wc -l` ≥ 1.
- [ ] `grep -c 'ttlMs'`, `'cacheScope'` and `'resultType'` over `src/lauren_mcp/_client/_cache.py` each ≥ 1; `grep -rn 'server/discover' src/lauren_mcp/_client/ | wc -l` ≥ 2; `grep -c 'last-event-id' src/lauren_mcp/_client/_streamable.py` ≥ 1.
- [ ] `pytest tests/unit/test_client_parity_matrix.py tests/unit/test_client_transport_surface.py -q` passes and the matrix literal matches §4.1 row for row.
- [ ] `pytest tests/unit/test_client_cancel.py tests/unit/test_client_era.py tests/unit/test_client_cache.py -q` passes.
- [ ] `pytest tests/integration/test_client_cancel_integration.py tests/integration/test_client_discover_integration.py -q` passes.
- [ ] `pytest tests/unit/test_client_transports_coverage.py tests/unit/test_client_changes.py tests/end_to_end/test_client_e2e.py -q` passes unmodified.
- [ ] `git diff --stat src/lauren_mcp/_server/ src/lauren_mcp/server/` is empty; `wc -c prds/2026-11-landscape/prd-client-parity.md` is 18000–30000.

---

Drafted from the 2026-11 MCP landscape review (evidence retrieved 2026-11-26). Full PRD, evidence register (`EVIDENCE.md`) and `VERSIONS-MATRIX.md` live in `prds/2026-11-landscape/` on branch `docs/mcp-landscape-2026-11`.
