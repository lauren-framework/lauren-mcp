**PRD:** [`prd-cancellation-conformance.md`](https://github.com/lauren-framework/lauren-mcp/blob/docs/mcp-landscape-2026-11/prds/2026-11-landscape/prd-cancellation-conformance.md)
**Priority:** P1 — `notifications/cancelled` has existed since the first schema, but the read loop is blocked by the call it should cancel, so no handler sees it
**Theme:** Transports
**Key evidence:** E-08, E-09, E-237 — see `EVIDENCE.md` in the same directory.

## Problem

The MCP cancellation notification has been in the specification since the **earliest** schema:
`notifications/cancelled` is a literal in `schema/2024-11-05/schema.ts` (E-08). `lauren-mcp` 1.0.0 does
not implement it. All three server transports match on `$/cancelRequest` instead — a name with **zero**
occurrences anywhere in the `modelcontextprotocol` organisation (E-09) and an **LSP** method name
(N-02). The server listens for a method no MCP client sends and ignores the one every client sends
(E-240, E-237):

```
$ grep -ril 'notifications/cancelled' src/ | wc -l
0
$ grep -rn 'cancelRequest' src/ | wc -l
9
```

## Goals

1. **Accept the spec method on all three server transports.** `notifications/cancelled` with
   `params.requestId` cancels the matching in-flight request on WebSocket, stdio and Streamable HTTP.
2. **Deliver the cancel while the call is still running.** WebSocket and stdio decode frames
   independently of handler execution, so a cancel arriving 200 ms into a 5 000 ms tool is observed at
   ~200 ms.
3. **Set the cooperative flag before the hard cancel**, in one `cancel()` call, in that order (already
   the behaviour at `_dispatcher.py:176-189`; this PRD pins it with a test instead of a comment).
4. **Stop writing a response frame for a peer-cancelled request.** The transport drops the `-32800`
   frame; `dispatch()` still returns it internally so its return type stays total.
5. **Reject cancellation of `initialize`** (the spec forbids it): the request runs to completion and
   the cancel for its id is ignored at debug level.
6. **Keep the legacy name working for one minor release** — `$/cancelRequest` with `params.id` still
   cancels, matched in exactly one alias shim.
7. **Make documentation, docstrings and code agree.** The five docstrings in §1.3 and
   `docs/guides/tool-context.md` name the spec method; only the shim may mention the alias.
8. **Ship no new runtime dependency.** Everything is `asyncio` plus existing `anyio` usage; the
   two-dependency posture (`lauren`, `anyio`, E-222) is untouched.

**Why P1.** `lauren-mcp` is non-conformant *today*, in every era, on every server transport: the one
cancellation mechanism the spec defines is unimplemented and the name it implements does not exist in the
spec (E-08, E-09, C-01). A fielded client cannot stop a running tool — a correctness and cost problem
(billed tokens, pinned CPU, held database connections), not a feature request — and the fix is
era-independent, so it must not wait for `2026-07-28` migration work.

### Acceptance checklist

- [ ] `grep -ril 'notifications/cancelled' src/ | wc -l` ≥ 5 (currently `0`).
- [ ] `grep -rn '\$/cancelRequest' src/ | wc -l` ≤ 4, all inside the alias shim (currently `9`).
- [ ] `tests/unit/test_server_cancel.py` — 9 tests, and `tests/integration/test_notifications_cancelled.py` — 8 tests, both passing (notably `test_ws_cancel_interrupts_in_flight_tool`: the tool's `finally` runs within 1 s of the cancel).
- [ ] `test_cancel_signal_integration.py::test_dispatcher_can_cancel_in_flight_request` (line 78) still passes, and `test_mcp_server_ws_frame.py::TestCancelRequest` (149-181) is updated to the spec name and green.
- [ ] `grep -rn 'cancelRequest' src/lauren_mcp/_server/_context.py src/lauren_mcp/server/_handlers.py` empty.
- [ ] `pytest tests/ -q` shows no new failures against the pre-change baseline.

## Acceptance criteria

- [ ] `grep -ril 'notifications/cancelled' src/ | wc -l` ≥ 5 (currently `0`).
- [ ] `grep -rn '\$/cancelRequest' src/ | wc -l` ≤ 4, all inside the alias shim (currently `9`).
- [ ] `tests/unit/test_server_cancel.py` — 9 tests, and `tests/integration/test_notifications_cancelled.py` — 8 tests, both passing (notably `test_ws_cancel_interrupts_in_flight_tool`: the tool's `finally` runs within 1 s of the cancel).
- [ ] `test_cancel_signal_integration.py::test_dispatcher_can_cancel_in_flight_request` (line 78) still passes, and `test_mcp_server_ws_frame.py::TestCancelRequest` (149-181) is updated to the spec name and green.
- [ ] `grep -rn 'cancelRequest' src/lauren_mcp/_server/_context.py src/lauren_mcp/server/_handlers.py` empty.
- [ ] `pytest tests/ -q` shows no new failures against the pre-change baseline.

---

Drafted from the 2026-11 MCP landscape review (evidence retrieved 2026-11-26). Full PRD, evidence register (`EVIDENCE.md`) and `VERSIONS-MATRIX.md` live in `prds/2026-11-landscape/` on branch `docs/mcp-landscape-2026-11`.
