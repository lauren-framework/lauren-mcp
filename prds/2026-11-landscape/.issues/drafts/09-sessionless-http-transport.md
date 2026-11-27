**PRD:** [`prd-sessionless-http-transport.md`](https://github.com/lauren-framework/lauren-mcp/blob/docs/mcp-landscape-2026-11/prds/2026-11-landscape/prd-sessionless-http-transport.md)
**Priority:** P2 — Streamable HTTP still mints a session at `initialize`; there is no sessionless shape for deployments that need one
**Theme:** Transports
**Key evidence:** E-20, E-22, E-23 — see `EVIDENCE.md` in the same directory.

## Problem

`lauren-mcp` 1.0.0 implements Streamable HTTP the way `2025-03-26` … `2025-11-25` defined it: a client
calls `initialize`, the server mints a session id, and every later request carries it in `Mcp-Session-Id`.
The `2026-07-28` revision deletes that mechanism — the header is gone from the schema (E-20),
`tools/list`/`resources/list`/`prompts/list` no longer vary per connection, and per-request `_meta` carries
what the handshake used to carry (E-22). The code below still *requires* the header on every POST, so a
modern-era client cannot complete its first request.

This PRD adds a sessionless path for modern-era requests **without touching the legacy path**, because the
spec's own policy keeps the prior revision reachable for at least 12 months (E-41).

## Goals

1. **G1 — Era detection from `_meta`.** A POST whose `params._meta` declares
   `io.modelcontextprotocol/protocolVersion` at `2026-07-28` or later is served with **no session**: no
   `Mcp-Session-Id` read, minted, returned or required (E-20, E-22).
2. **G2 — One pure routing function.** `resolve_request_era(msg, headers) -> "legacy" | "modern"`,
   unit-tested with no HTTP layer involved.
3. **G3 — Legacy path untouched.** Any request carrying `Mcp-Session-Id`, or omitting `_meta`, behaves
   exactly as at `HEAD`: `400` at `:339`, `404` at `:344`, headers at `:332`, GET channel at `:458`,
   DELETE teardown at `:522`.
4. **G4 — Per-request client context.** For modern requests `protocolVersion`, `clientInfo` and
   `clientCapabilities` from `_meta` reach handlers through `TransportBinding`, not through a session.
5. **G5 — GET is era-gated.** Modern `GET /mcp` returns `405` naming `subscriptions/listen` (E-23);
   legacy `GET` still opens the SSE push channel.
6. **G6 — DELETE stays legacy-only.** Modern `DELETE` returns `405`; legacy `DELETE` still tears down and
   drains the push queue (`:82`). No session exists in the modern path, so there is nothing to destroy.
7. **G7 — Honest resumability story.** The removed `Last-Event-ID` replay is documented as a
   spec-mandated loss (E-28), with the concrete failure and the mitigation (§4.5), not silently dropped.
8. **G8 — No new runtime dependency.** `asyncio` and `dataclasses` only; the two-dependency posture
   (`lauren`, `anyio`) holds.

**Why P2:** no fielded host regresses — every real client still negotiates a legacy revision, so nothing
breaks. But sessionless Streamable HTTP is the revision both SDKs ship, and a modern host gets a `400` on
its first request (E-20, E-22). Missing capability that narrows reach, which is exactly the brief's P2
test.

### Acceptance criteria

- [ ] `grep -n 'def resolve_request_era' src/lauren_mcp/_server/_streamable.py` returns exactly one hit.
- [ ] `pytest tests/unit/test_request_era.py -q` passes (no `_meta` → legacy; `2025-11-25` in `_meta` → legacy; `2026-07-28` in `_meta` → modern; `2026-07-28` **plus** `Mcp-Session-Id` → legacy with a warning).
- [ ] `pytest tests/integration/test_sessionless_streamable.py -q` passes (modern `tools/list` with no session header returns `200` and the response carries no `mcp-session-id`).
- [ ] `grep -c 'mcp-session-id' src/lauren_mcp/_server/_streamable.py` is unchanged from `HEAD` — the legacy constant and its call sites survive (E-41).
- [ ] `curl -sD- -o/dev/null -X POST http://127.0.0.1:8000/mcp -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28"}}}'` shows `HTTP/1.1 200` and no `mcp-session-id` header.
- [ ] The same `curl` **without** `_meta` still shows `HTTP/1.1 400` with body `{"error": "Missing 'mcp-session-id' header"}`.
- [ ] `curl -s -o/dev/null -w '%{http_code}' -X GET http://127.0.0.1:8000/mcp -H 'accept: text/event-stream' -H 'mcp-protocol-version: 2026-07-28'` prints `405`.
- [ ] `pytest tests/integration/test_streamable*.py -q` passes unchanged (legacy suite, no regression).

## Acceptance criteria

- [ ] `grep -n 'def resolve_request_era' src/lauren_mcp/_server/_streamable.py` returns exactly one hit.
- [ ] `pytest tests/unit/test_request_era.py -q` passes (no `_meta` → legacy; `2025-11-25` in `_meta` → legacy; `2026-07-28` in `_meta` → modern; `2026-07-28` **plus** `Mcp-Session-Id` → legacy with a warning).
- [ ] `pytest tests/integration/test_sessionless_streamable.py -q` passes (modern `tools/list` with no session header returns `200` and the response carries no `mcp-session-id`).
- [ ] `grep -c 'mcp-session-id' src/lauren_mcp/_server/_streamable.py` is unchanged from `HEAD` — the legacy constant and its call sites survive (E-41).
- [ ] `curl -sD- -o/dev/null -X POST http://127.0.0.1:8000/mcp -H 'content-type: application/json' -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28"}}}'` shows `HTTP/1.1 200` and no `mcp-session-id` header.
- [ ] The same `curl` **without** `_meta` still shows `HTTP/1.1 400` with body `{"error": "Missing 'mcp-session-id' header"}`.
- [ ] `curl -s -o/dev/null -w '%{http_code}' -X GET http://127.0.0.1:8000/mcp -H 'accept: text/event-stream' -H 'mcp-protocol-version: 2026-07-28'` prints `405`.
- [ ] `pytest tests/integration/test_streamable*.py -q` passes unchanged (legacy suite, no regression).

---

Drafted from the 2026-11 MCP landscape review (evidence retrieved 2026-11-26). Full PRD, evidence register (`EVIDENCE.md`) and `VERSIONS-MATRIX.md` live in `prds/2026-11-landscape/` on branch `docs/mcp-landscape-2026-11`.
