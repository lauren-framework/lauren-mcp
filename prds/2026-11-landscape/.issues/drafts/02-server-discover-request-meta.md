**PRD:** [`prd-server-discover-request-meta.md`](https://github.com/lauren-framework/lauren-mcp/blob/docs/mcp-landscape-2026-11/prds/2026-11-landscape/prd-server-discover-request-meta.md)
**Priority:** P1 — No `server/discover` and no per-request `_meta` envelope, so a modern peer has nothing to negotiate against
**Theme:** Protocol core
**Key evidence:** E-20, E-21, E-30 — see `EVIDENCE.md` in the same directory.

## Problem

The `2026-07-28` revision deletes the `initialize` / `initialized` handshake for modern peers and replaces
it with a mandatory `server/discover` request (**E-21**). The handshake is not deprecated there — it is
**removed**, one of nine mandatory removals that make that revision breaking rather than additive
(**E-20**, **E-21**, **E-30**). `lauren-mcp` 1.0.0 has no `server/discover` at any layer:

```bash
# run from repo root — the acceptance command for this PRD
$ grep -ril 'server/discover' src/ | wc -l
0
```

## Goals

1. A `2026-07-28` peer sending `server/discover` over any server transport receives a well-formed result with
   `serverInfo`, `capabilities` and `instructions` — no `-32601`, no empty session.
2. `grep -ril 'server/discover' src/ | wc -l` returns ≥ 1 (it returns 0 today — **E-230**).
3. `_mcp_version.py` gains a modern era *beside* the legacy set: `LATEST` stays `"2025-11-25"` and
   `SUPPORTED` stays `{"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}`, so no existing client's
   negotiation changes.
4. Every request's `_meta` envelope is parsed once, in `McpDispatcher.dispatch()`, into an immutable
   `RequestMeta` (**E-22**), reachable from handlers and `McpToolContext` without user code touching
   `params["_meta"]`.
5. A malformed envelope fails fast with `-32602` (`McpErrorCode.INVALID_PARAMS`, `_types.py:117`).
6. Request era is resolved in exactly one function, so the next revision has one place to change.
7. `era_policy="modern"` lets an operator refuse `initialize` with a message naming `server/discover`; the
   default `"dual"` keeps both eras answering.
8. Zero behaviour change for any caller that neither sends `server/discover` nor sends
   `io.modelcontextprotocol/*` keys.

### 2.1 Acceptance criteria

- [ ] `grep -ril 'server/discover' src/ | wc -l` ≥ 1 (was 0 — **E-230**).
- [ ] `grep -rl 'io.modelcontextprotocol/' src/ | wc -l` ≥ 1 (was 0 — **E-22**).
- [ ] `python -c "from lauren_mcp._mcp_version import MODERN_LATEST; print(MODERN_LATEST)"` prints
      `2026-07-28`; the same line with `LATEST` still prints `2025-11-25`.
- [ ] `pytest tests/unit/test_server_discover.py -q` passes, incl. `test_discover_capabilities_match_initialize`.
- [ ] `pytest tests/unit/test_request_meta.py -q` passes, incl.
      `test_malformed_protocol_version_returns_invalid_params`.
- [ ] `pytest tests/integration/test_modern_era_discovery.py -q` passes on STDIO and Streamable HTTP.
- [ ] `pytest tests/unit/test_mcp_handshake.py tests/integration/test_mcp_dispatcher_protocol.py -q` still
      passes, unmodified.

## Acceptance criteria

- [ ] `grep -ril 'server/discover' src/ | wc -l` ≥ 1 (was 0 — **E-230**).
- [ ] `grep -rl 'io.modelcontextprotocol/' src/ | wc -l` ≥ 1 (was 0 — **E-22**).
- [ ] `python -c "from lauren_mcp._mcp_version import MODERN_LATEST; print(MODERN_LATEST)"` prints
      `2026-07-28`; the same line with `LATEST` still prints `2025-11-25`.
- [ ] `pytest tests/unit/test_server_discover.py -q` passes, incl. `test_discover_capabilities_match_initialize`.
- [ ] `pytest tests/unit/test_request_meta.py -q` passes, incl.
      `test_malformed_protocol_version_returns_invalid_params`.
- [ ] `pytest tests/integration/test_modern_era_discovery.py -q` passes on STDIO and Streamable HTTP.
- [ ] `pytest tests/unit/test_mcp_handshake.py tests/integration/test_mcp_dispatcher_protocol.py -q` still
      passes, unmodified.

---

Drafted from the 2026-11 MCP landscape review (evidence retrieved 2026-11-26). Full PRD, evidence register (`EVIDENCE.md`) and `VERSIONS-MATRIX.md` live in `prds/2026-11-landscape/` on branch `docs/mcp-landscape-2026-11`.
