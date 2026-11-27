**PRD:** [`prd-oauth-resource-indicators-cimd.md`](https://github.com/lauren-framework/lauren-mcp/blob/docs/mcp-landscape-2026-11/prds/2026-11-landscape/prd-oauth-resource-indicators-cimd.md)
**Priority:** P2 — OAuth is hand-rolled in two places, with no resource indicators and no client-ID metadata
**Theme:** Transports
**Key evidence:** E-170, E-171, E-172 — see `EVIDENCE.md` in the same directory.

## Problem

`lauren-mcp` speaks OAuth in two places: as a **client**, `ClientCredentialsProvider` fetches a bearer token and
attaches it to every HTTP request (`src/lauren_mcp/_client/_oauth.py:59`, `:156`); as a **server**, two `.well-known`
handlers publish authorization-server and protected-resource metadata (`src/lauren_mcp/_server/_streamable.py:546`,
`:557`). Nothing in between binds a token to a resource.

Two servers run behind one authorization server — `https://tools-a.example.com/mcp` and
`https://tools-b.example.com/mcp` — with one confidential client. The token request on the wire is:

## Goals

**Priority P2** (§1.4): absence costs features, not interop — no fielded peer breaks, and the security half is
opt-in enforcement rather than a repair of a fielded control.

1. **Client sends a resource indicator** — `resource=` (one URI or a list) on `ClientCredentialsProvider`, sent as
   `resource` in the token request body per RFC 8707.
2. **Server can bind tokens to its canonical URI** — an opt-in verifier rejects a token whose `aud`/resource claim does
   not name this server: `401` with `WWW-Authenticate: Bearer error="invalid_token"` plus `resource_metadata`.
3. **`iss` is checked when configured** — mismatch rejected; absent `iss` passes only when no issuer is configured
   (SEP-2468, E-175).
4. **CIMD client identity is usable** — `_client/_cimd.py` fetches and validates a Client ID Metadata Document over
   HTTPS; the URL *is* the `client_id`.
5. **CIMD precedes static config; DCR is never introduced** — resolution order CIMD → static `client_id`, and any
   DCR-implying configuration warns.
6. **stdio is untouched and provably exempt** (E-170); **the threat model is written down** (§4.6); **documentation
   tells the truth about who validates** (`README.md:138`); **auditability is preserved** — no new runtime dependency
   (`pyproject.toml:28-29`).

### 2.1 Acceptance criteria

- [ ] `ClientCredentialsProvider(..., resource="https://tools-a.example.com/mcp")` posts one `resource` field, asserted
      against the exact form encoding in `tests/unit/test_oauth_client.py`.
- [ ] `resource` is canonicalised (fragment/query rejected, host lower-cased, default port dropped) and multiple
      resources produce repeated parameters, never one space-joined value; with no `resource=` and no `extra_params` the
      posted form is byte-identical to `v1.0.0`.
- [ ] With `oauth_settings.resource_policy`, a foreign-audience token gets `401` + `WWW-Authenticate` and a matching one
      gets `200`; with no policy the server behaves exactly as `v1.0.0`.
- [ ] A token with no `aud`/resource claim is rejected at `require_audience=True` (default) and accepted at
      `require_audience=False`; `iss` mismatch rejected, absent `iss` rejected only when an issuer is configured.
- [ ] `fetch_client_metadata()` rejects non-HTTPS, cross-origin redirect, body > 64 KiB, `client_id` ≠ URL, and
      `token_endpoint_auth_method` starting `client_secret_`; accepts `none` with a matching URL.
- [ ] `grep -ril 'RFC 8707' src/ | wc -l` becomes **≥ 1** (currently **0**, E-238) — the same command E-238 used.
- [ ] `grep -rn 'registration_endpoint' src/` stays empty; `pyproject.toml:28-29` still lists exactly `lauren` and
      `anyio`; `tests/unit/test_stdio.py` asserts no `Authorization` header and no CIMD fetch on stdio; `README.md`
      states the server-side default (no token validation unless a verifier is configured).

## Acceptance criteria

- [ ] `ClientCredentialsProvider(..., resource="https://tools-a.example.com/mcp")` posts one `resource` field, asserted
      against the exact form encoding in `tests/unit/test_oauth_client.py`.
- [ ] `resource` is canonicalised (fragment/query rejected, host lower-cased, default port dropped) and multiple
      resources produce repeated parameters, never one space-joined value; with no `resource=` and no `extra_params` the
      posted form is byte-identical to `v1.0.0`.
- [ ] With `oauth_settings.resource_policy`, a foreign-audience token gets `401` + `WWW-Authenticate` and a matching one
      gets `200`; with no policy the server behaves exactly as `v1.0.0`.
- [ ] A token with no `aud`/resource claim is rejected at `require_audience=True` (default) and accepted at
      `require_audience=False`; `iss` mismatch rejected, absent `iss` rejected only when an issuer is configured.
- [ ] `fetch_client_metadata()` rejects non-HTTPS, cross-origin redirect, body > 64 KiB, `client_id` ≠ URL, and
      `token_endpoint_auth_method` starting `client_secret_`; accepts `none` with a matching URL.
- [ ] `grep -ril 'RFC 8707' src/ | wc -l` becomes **≥ 1** (currently **0**, E-238) — the same command E-238 used.
- [ ] `grep -rn 'registration_endpoint' src/` stays empty; `pyproject.toml:28-29` still lists exactly `lauren` and
      `anyio`; `tests/unit/test_stdio.py` asserts no `Authorization` header and no CIMD fetch on stdio; `README.md`
      states the server-side default (no token validation unless a verifier is configured).

---

Drafted from the 2026-11 MCP landscape review (evidence retrieved 2026-11-26). Full PRD, evidence register (`EVIDENCE.md`) and `VERSIONS-MATRIX.md` live in `prds/2026-11-landscape/` on branch `docs/mcp-landscape-2026-11`.
