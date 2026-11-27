**PRD:** [`prd-transport-security-hardening.md`](https://github.com/lauren-framework/lauren-mcp/blob/docs/mcp-landscape-2026-11/prds/2026-11-landscape/prd-transport-security-hardening.md)
**Priority:** P1 — `transport_security` is an opt-in keyword and nothing attaches it to the generated HTTP/SSE controllers
**Theme:** Transports
**Key evidence:** E-169b, E-169, E-160 — see `EVIDENCE.md` in the same directory.

## Problem

`transport_security` is an opt-in keyword (`_streamable.py:106`, `_sse.py:55`); `mcp_http_sse_controller` binds it the same way (`_sse.py:256`–`:265`). Attaching it is a three-line block, `_streamable.py:577`–`:579`:

```python
    if transport_security is not None:              # line 577
        _guard = McpTransportSecurityGuard()        # line 578
        _guard.configure(transport_security)        # line 579
```

## Goals

1. **Guard attached by default on every HTTP path.** `for_root` gains `transport_security`, passes it to the streamable and SSE controllers, and defaults to `"auto"` (attached) rather than `None`.
2. **WS validates `Origin`.** `mcp_ws_controller` gains the parameter and rejects a foreign `Origin` before `ws.accept()` (`_ws.py:139`).
3. **`allowed_origins` is authoritative.** The bare-host fallback (`_transport_security.py:72`–`:74`) is skipped when the list is non-empty.
4. **`Content-Type` is parsed, not substring-matched** (`:105` currently accepts `application/jsonp`).
5. **Every advertised tool set has one canonical `sha256` digest**, in `tools/list` `_meta`, `list_changed` params, and a pollable route.
6. **A client can pin that digest**, including trust-on-first-use, and raises on mismatch.
7. **The client survives an untrusted server**: bounded timeout, bounded response, no cross-origin redirect, no interpretation of `instructions`, no URL fetching.
8. **The control is importable** (`from lauren_mcp import TransportSecuritySettings`) and every OWASP MCP Top 10 item is classified in §10.

### 2.1 Acceptance criteria

- [ ] `grep -c transport_security src/lauren_mcp/server/_module.py` returns ≥ 4.
- [ ] `grep -c transport_security src/lauren_mcp/_server/_ws.py` returns ≥ 3.
- [ ] `python -c "from lauren_mcp import TransportSecuritySettings"` exits 0.
- [ ] `grep -n 'timeout=None\|follow_redirects=True' src/lauren_mcp/_client/_streamable.py` returns no match.
- [ ] `grep -rn 'compute_toolset_digest' src/ | wc -l` returns ≥ 3.
- [ ] `pytest tests/unit/test_transport_security.py tests/unit/test_toolset_digest.py tests/integration/test_transport_security_http.py -q` passes.
- [ ] `grep -rn 'icons\|websiteUrl' src/lauren_mcp/ | wc -l` returns 0, or every hit sits behind a documented no-fetch note.
- [ ] A hand-written page under `docs/guides/` names `TransportSecuritySettings`.

## Acceptance criteria

- [ ] `grep -c transport_security src/lauren_mcp/server/_module.py` returns ≥ 4.
- [ ] `grep -c transport_security src/lauren_mcp/_server/_ws.py` returns ≥ 3.
- [ ] `python -c "from lauren_mcp import TransportSecuritySettings"` exits 0.
- [ ] `grep -n 'timeout=None\|follow_redirects=True' src/lauren_mcp/_client/_streamable.py` returns no match.
- [ ] `grep -rn 'compute_toolset_digest' src/ | wc -l` returns ≥ 3.
- [ ] `pytest tests/unit/test_transport_security.py tests/unit/test_toolset_digest.py tests/integration/test_transport_security_http.py -q` passes.
- [ ] `grep -rn 'icons\|websiteUrl' src/lauren_mcp/ | wc -l` returns 0, or every hit sits behind a documented no-fetch note.
- [ ] A hand-written page under `docs/guides/` names `TransportSecuritySettings`.

---

Drafted from the 2026-11 MCP landscape review (evidence retrieved 2026-11-26). Full PRD, evidence register (`EVIDENCE.md`) and `VERSIONS-MATRIX.md` live in `prds/2026-11-landscape/` on branch `docs/mcp-landscape-2026-11`.
