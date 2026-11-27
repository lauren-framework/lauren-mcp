**PRD:** [`prd-mrtr-input-required.md`](https://github.com/lauren-framework/lauren-mcp/blob/docs/mcp-landscape-2026-11/prds/2026-11-landscape/prd-mrtr-input-required.md)
**Priority:** P1 — `tools/call` is one-shot: a tool needing input mid-call cannot return `input_required` and resume
**Theme:** Protocol core
**Key evidence:** E-14, E-20, E-21 — see `EVIDENCE.md` in the same directory.

## Problem

Today a tool that needs something from the user **blocks inside a single `tools/call`** and issues a
nested server→client JSON-RPC request. The two entry points are `McpToolContext.sample()` and
`McpToolContext.elicit()`, and both refuse to run without a handshake-era capability map:

```python
# src/lauren_mcp/_server/_context.py  lines 486-492
        if self._client_rpc is None:
            raise McpSamplingNotAvailable("This transport cannot deliver server-to-client requests")
        caps = self._client_capabilities
        if caps is None or caps.sampling is None:
            raise McpSamplingNotAvailable(
                "The connected client did not advertise the 'sampling' capability"
            )

## Goals

1. A tool can declare "I need input" and return a protocol-valid `tools/call` result containing
   `resultType: "input_required"`, `inputRequests`, and a non-empty opaque `requestState`, **without
   any server→client request being sent and without a session**.
2. A client can resume the same tool call by re-issuing `tools/call` with the returned
   `requestState`; the server decodes it, re-enters the tool from the top, and `ctx.request_input()`
   returns the supplied answer instead of raising.
3. `requestState` is **self-contained, tamper-evident, tool-bound and time-bound**: HMAC-SHA256
   signed, rejected when presented to a different tool, and expiring after a configurable TTL
   (default 300 s), so a stolen token cannot be replayed forever or redirected.
4. The **legacy** path is preserved bit-for-bit: on a `2024-11-05`…`2025-11-25` peer,
   `ctx.request_input()` delegates to `ctx.elicit()`/`ctx.sample()` and the client sees the same
   `elicitation/create` request it sees today.
5. The **client** side gets a driver that performs the round trips against a user-supplied handler,
   capped by a max-rounds guard, so `await client.call_tool(...)` still returns a plain result.
6. A malformed, expired or forged token produces JSON-RPC `-32602` naming the offending field —
   never `-32603`, and never a silent success.
7. No new runtime dependency; Python 3.11+; `anyio` async.

**Why P1.** P1 means "non-conformant today, or a fielded client cannot talk to us".
`input_required` is a MUST row of `2026-07-28` (`VERSIONS-MATRIX.md` §2) **[E-26]**, we have zero
hits for it, and §1.1 shows a modern host receiving `-32603` for a mandatory success case. That is
the definition, not an interpretation.

### 2.1 Acceptance criteria

- [ ] `grep -rn 'resultType' src/lauren_mcp/ | wc -l` returns ≥ 1.
- [ ] `grep -rn 'input_required' src/lauren_mcp/ | wc -l` returns ≥ 1.
- [ ] `grep -rn 'requestState' src/lauren_mcp/ | wc -l` returns ≥ 1.
- [ ] `pytest tests/unit/test_mrtr.py -q` passes, including `test_codec_rejects_forged_mac`,
      `test_codec_rejects_wrong_tool`, `test_codec_rejects_expired`, and
      `test_request_input_raises_input_required_on_modern_peer`.
- [ ] `pytest tests/integration/test_mrtr_roundtrip.py -q` passes, including
      `test_two_round_trip_resume` and `test_legacy_peer_still_gets_elicitation_create`.
- [ ] A raw `tools/call` over Streamable HTTP returns `resultType == "input_required"` with a
      `requestState` the next `tools/call` accepts (`test_result_shape_matches_schema`).
- [ ] `python -c "from lauren_mcp import McpInputRequired, MrtrStateCodec"` exits 0.
- [ ] `pytest tests/ -q` shows no new failures against the pre-change baseline.

## Acceptance criteria

- [ ] `grep -rn 'resultType' src/lauren_mcp/ | wc -l` returns ≥ 1.
- [ ] `grep -rn 'input_required' src/lauren_mcp/ | wc -l` returns ≥ 1.
- [ ] `grep -rn 'requestState' src/lauren_mcp/ | wc -l` returns ≥ 1.
- [ ] `pytest tests/unit/test_mrtr.py -q` passes, including `test_codec_rejects_forged_mac`,
      `test_codec_rejects_wrong_tool`, `test_codec_rejects_expired`, and
      `test_request_input_raises_input_required_on_modern_peer`.
- [ ] `pytest tests/integration/test_mrtr_roundtrip.py -q` passes, including
      `test_two_round_trip_resume` and `test_legacy_peer_still_gets_elicitation_create`.
- [ ] A raw `tools/call` over Streamable HTTP returns `resultType == "input_required"` with a
      `requestState` the next `tools/call` accepts (`test_result_shape_matches_schema`).
- [ ] `python -c "from lauren_mcp import McpInputRequired, MrtrStateCodec"` exits 0.
- [ ] `pytest tests/ -q` shows no new failures against the pre-change baseline.

---

Drafted from the 2026-11 MCP landscape review (evidence retrieved 2026-11-26). Full PRD, evidence register (`EVIDENCE.md`) and `VERSIONS-MATRIX.md` live in `prds/2026-11-landscape/` on branch `docs/mcp-landscape-2026-11`.
