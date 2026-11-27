# PRD — Authorization hardening: RFC 8707 resource indicators and CIMD registration

**Status:** Draft
**Date:** 2026-11-26
**Scope:** `_client/_oauth.py`, `_client/_factory.py`, `_client/_cimd.py` (new), `_server/_streamable.py`,
`_server/_auth.py` (new), `_client/__init__.py`, `_server/__init__.py`, `README.md`
**Priority:** P2 — the audience-binding half is a security fix that applies today, but the exposure is conditional
**Issue:** _pending_
on deployment topology and no fielded peer breaks; the CIMD/DCR half is modern-era feature work (§1.4).
**Era split:** one requirement is era-independent (§1.3.1); three are `2026-07-28`-only (§1.3.2).

---

## 1. Problem Statement

`lauren-mcp` speaks OAuth in two places: as a **client**, `ClientCredentialsProvider` fetches a bearer token and
attaches it to every HTTP request (`src/lauren_mcp/_client/_oauth.py:59`, `:156`); as a **server**, two `.well-known`
handlers publish authorization-server and protected-resource metadata (`src/lauren_mcp/_server/_streamable.py:546`,
`:557`). Nothing in between binds a token to a resource.

### 1.1 A token minted for one server is accepted by another

Two servers run behind one authorization server — `https://tools-a.example.com/mcp` and
`https://tools-b.example.com/mcp` — with one confidential client. The token request on the wire is:

```python
# src/lauren_mcp/_client/_oauth.py  line 130-137  (current)
        data: dict[str, str] = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        if self._scopes:
            data["scope"] = " ".join(self._scopes)
        data.update(self._extra_params)
```

No `resource` parameter (RFC 8707). The only audience-shaped key in the client is a docstring example at `_oauth.py:92`
— `extra_params={"audience": "https://api.example.com"}`, an Auth0-ism, not a resource indicator. So the authorization
server mints a token with its default audience: in practice, "everything this client may call".
`grep -ril 'RFC 8707' src/ | wc -l` returns **0** (E-238).

The token handed to A is a valid credential at B. The servers share neither data nor scopes nor authority, but they
share the token, and B validates nothing — `handle_post` parses the body before it knows who sent it
(`_streamable.py:167-173`). One captured `Authorization` header reaches every server that trusts that authorization
server.

### 1.2 The repo advertises a resource it never enforces

`_streamable.py:557-565` publishes `/.well-known/oauth-protected-resource` per RFC 9728 (E-247, one file) — a
document that names a resource. But `grep -rn 'Authorization' src/lauren_mcp/_server/` has no hits: no token is ever
inspected. Validation is implicitly delegated to whatever sits in front of the process (`oauth2-proxy`, a gateway, a
load balancer). Defensible, but *undocumented* — nothing in the README or the published metadata says "this server
does not authenticate callers". A reader who sees RFC 9728 metadata served concludes the opposite.

### 1.3 What is a security fix today, and what is modern-era-only

The repo's auth code is **legacy-shaped, not non-conformant**: `client_credentials` is a valid OAuth grant and this repo
implements it correctly for its era. We do not claim a violation where there is only a missing modern feature.

**§1.3.1 — Era-independent: audience/resource binding (security fix, applies today).** The confused-deputy class is a
property of OAuth, not of MCP `2026-07-28`. A token issued for resource A must not be accepted by resource B, and
enforcing that needs both ends: the client names the resource when requesting the token (RFC 8707 `resource`), the
server checks that the token's `aud`/resource claim names *it*. Neither end exists here, so the exposure exists in the
repo as fielded today, on any multi-resource deployment. It is *conditioned* by §1.2 — the server validates nothing, so
in practice "the proxy decides" — which is why the fix lands as an opt-in verifier hook plus a client that stops asking
for unbound tokens.

**§1.3.2 — Modern-era-only.** (a) *OAuth 2.1 for HTTP, stdio exempt* (E-170): the code is an OAuth 2.0 provider
(`_oauth.py:1`, `:59`) — older than the revision, not broken. (b) *CIMD is the recommended registration path* (E-172):
nothing here registers clients at all, so it is new capability, not repair. (c) *DCR deprecated, ≥12-month window*
(E-173): never implemented, so the requirement is "do not add it" plus a deprecation note (§4.4). (d) *`iss` recommended
in auth responses* (E-175, SEP-2468): meaningful only once a token is inspected, i.e. after §4.1. A legacy deployment
may ignore all four and stay correct for its era; it cannot ignore §4.1 and §4.2 and stay safe.

### 1.4 Why P2

Brief §4's P2 test: *"Standard capability that real hosts/SDKs already ship; absence costs features, not interop."* No
fielded client fails to connect for want of `resource`; no peer is blocked by missing CIMD. A `2026-07-28` authorization
server that *requires* a resource indicator, or one that refuses DCR-only clients, would strand this client — that is
the escalation trigger to P1, and it is not fielded. The security half is real but conditional: the repo server
validates nothing, so §4.1 is *new enforcement*, not the repair of a fielded control, and the deployment that needs it
most can already be protected by the proxy it must be running. P1 here is reserved for "non-conformant today" (see the
sibling `server/discover` PRD).

## lauren-mcp Advantages

* **The OAuth surface is small enough to audit in one sitting.** Twelve lines mint a token (`_oauth.py:130-141`), four
  attach it (`_oauth.py:156-163`), sixteen publish metadata (`_streamable.py:144-147`, `:546-565`). The same change in a
  framework that vendors `authlib` plus a session store plus a registration service is a multi-day audit.
* **The dependency posture keeps the fix in-repo.** Exactly two runtime dependencies — `lauren>=1.7.0`, `anyio>=4.0`
  (`pyproject.toml:28-29`, E-222) — with `httpx` as an extra (`pyproject.toml:34`). A resource-indicator canonicaliser
  and an HS256 claim checker fit in the standard library (`hmac`, `hashlib`, `base64`, `json`): no new runtime
  dependency, no version-range negotiation (§4.1).
* **RFC 9728 metadata is already advertised.** `/.well-known/oauth-protected-resource` is served when
  `oauth_settings.protected_resource_metadata` is set (`_streamable.py:557-565`), RFC 8414 metadata likewise
  (`:546-555`). A conforming client can already *discover* the resource — it is never told to *bind* to it. Half the
  story ships (E-247); this PRD adds the other half, which is why it is cheap here.

## 2. Goals

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

## 3. Non-Goals

* **Becoming an authorization server** — no `/authorize`, `/token`, `/register`, consent UI, or user sessions;
  `lauren-mcp` verifies and requests tokens, it does not mint them.
* **Replacing the reverse proxy** — `oauth2-proxy`/gateway token exchange stays the recommended topology; §4.1 adds an
  in-process enforcement point for deployments that cannot run one and does not deprecate them.
* **Implementing DCR in order to remove it** — no registration client, no `registration_endpoint` handling, no
  migration tool; the ≥12-month window (E-173) is honoured by never shipping the capability.
* **Asymmetric verification as a runtime dependency** — no `pyjwt`, `authlib`, or `cryptography` in the base install
  (§9 Q2).
* **OAuth 2.1 interactive flows** — authorization-code + PKCE, dynamic scopes, refresh rotation, JAR/PAR are out of
  scope; `client_credentials` is the only grant touched, and per-tool scopes stay with the host.
* **Changing the stdio transport**, and **vendor-capability claims** — we do not assert that Zitadel or Google
  Cloud/Apigee support CIMD or resource indicators: both doc URLs 404 (E-177, E-178), unverified and therefore not
  claimed.

## 4. Design

### 4.1 Server-side token validation: resource binding, `aud`, `iss`

New stdlib-only module `src/lauren_mcp/_server/_auth.py`: a `TokenVerifier` Protocol (signature check only), a
`ResourcePolicy`, and `check_claims()`. Resource binding is deliberately *not* the verifier's job.

```python
# src/lauren_mcp/_server/_auth.py  (new)
@dataclass(frozen=True)
class ResourcePolicy:
    canonical_uri: str                  # "https://tools-a.example.com/mcp"
    issuer: str | None = None           # SEP-2468 (E-175); None = do not check
    require_audience: bool = True       # the security fix (§1.3.1)
    required_scopes: tuple[str, ...] = ()
    clock_skew_s: int = 60
    metadata_url: str | None = None     # advertised in WWW-Authenticate


def check_claims(claims, policy: ResourcePolicy, now: float | None = None) -> AuthDecision:
    """`aud` may be a string, a list, or an RFC 8707 `resource` echo (RFC 9068)."""
    aud = {canonicalize_resource(u) for u in _as_list(claims.get("aud")) + _as_list(claims.get("resource"))}
    if policy.require_audience and canonicalize_resource(policy.canonical_uri) not in aud:
        return AuthDecision(False, error="invalid_token", detail="audience does not name this resource")
    if policy.issuer is not None and claims.get("iss") != policy.issuer:
        return AuthDecision(False, error="invalid_token", detail="issuer mismatch")
    ...  # exp/nbf against policy.clock_skew_s, then required_scopes -> "insufficient_scope"
    return AuthDecision(True, claims=claims)
```

`HmacTokenVerifier` is the default: HS256 over `hmac` from the standard library, so `pyproject.toml:28-29` is untouched.
It accepts no `alg` other than HS256 and rejects `alg: none` outright. Wiring is one call site — `oauth_settings` gains
`verifier` and `resource_policy`, read with `getattr(..., None)`, where `None` means no enforcement (§7).

`handle_post` (`_streamable.py:167-176`) calls `_authorize(...)` before `await request.body()`, so an unauthenticated
caller never reaches `parse_message` (`:172-173`); a rejection returns `_challenge()`, which shapes RFC 6750 §3 —
`error`, optional `error_description`, and a `resource_metadata` URL taken from the *policy* (never from an inbound
header, see T5) pointing at the RFC 9728 document already served at `:557`. The same guard goes at `:458` (`@get("/")`)
and `:522` (`@delete("/")`): an unauthenticated caller must not open a stream or tear one down.

### 4.2 Client-side `resource` parameter (RFC 8707)

```python
# src/lauren_mcp/_client/_oauth.py  line 129-141  (new)
    async def _fetch_token(self) -> str:
        data: list[tuple[str, str]] = [
            ("grant_type", "client_credentials"),
            ("client_id", self._client_id),
            ("client_secret", self._client_secret),
        ]
        if self._scopes:
            data.append(("scope", " ".join(self._scopes)))
        # RFC 8707: one `resource` parameter per resource, repeated, never joined.
        for uri in self._resources:
            data.append(("resource", uri))
        data.extend(self._extra_params.items())
        async with httpx.AsyncClient() as client:
            resp = await client.post(self._token_endpoint, data=data)
            resp.raise_for_status()
            body: dict[str, Any] = resp.json()
```

`data` becomes `list[tuple[str, str]]` because RFC 8707 §2 allows repeated parameters and RFC 6749 §3.1 forbids
space-joining them; `httpx` encodes a list of tuples natively, and the single-value case produces today's form body.
`canonicalize_resource()` (new, shared with `_server/_auth.py`) requires an absolute URI with a host, rejects any
fragment or query, lower-cases scheme and host, drops `:443`/`:80`, keeps non-default ports, and maps an empty path to
`"/"`; `_normalize_resources()` applies it at construction time, so a bad URI fails in the caller's `__init__` rather
than on the first token request.

Constructor surface, additive: `resource: str | list[str] | None = None` after `extra_params` (`_oauth.py:95-103`),
`self._resources = _normalize_resources(resource)` after `:114`, and `with_resource()` so the factory can attach a
resource without rebuilding the provider. The `extra_params` docstring at `_oauth.py:90-92` gains one sentence: prefer
`resource` for audience binding — `extra_params` is a vendor escape hatch, not a substitute for an RFC 8707 indicator.

### 4.3 CIMD: the URL is the client id

New `src/lauren_mcp/_client/_cimd.py`: `CimdDocument` (frozen), `CimdError`, `fetch_client_metadata()`. Validation
rules, each a test in §8.2:

| Rule | Why |
|---|---|
| `https` URL (loopback `http://127.0.0.1` allowed), no fragment | the client_id is the only identity proof; plaintext lets a network attacker swap the document |
| redirect chain same-origin, ≤ 2 hops; body ≤ 64 KiB | an `https` client_id that 302s to `http` defeats the rule above; an unbounded fetch is a DoS |
| document `client_id` equals the fetched URL after canonicalisation | otherwise a document can claim another client's identity |
| `redirect_uris` non-empty and `https`/loopback; `token_endpoint_auth_method` not `client_secret_*` | a redirect to nowhere allows hijack; a public client documenting a shared secret is a leaked-secret pattern |

```python
# src/lauren_mcp/_client/_cimd.py  (new)
async def fetch_client_metadata(client_id_url, *, timeout=5.0, ttl=300.0) -> CimdDocument:
    doc = await _cached_fetch(client_id_url, timeout=timeout, ttl=ttl)   # https or loopback only, no fragment
    if canonicalize_resource(str(doc.get("client_id", ""))) != canonicalize_resource(client_id_url):
        raise CimdError("document client_id does not match the URL it was fetched from")
    ...  # redirect_uris https/loopback; reject token_endpoint_auth_method starting "client_secret_"
    return CimdDocument(client_id=client_id_url, redirect_uris=redirects,
                        token_endpoint_auth_method=method, raw=doc)
```

**Why it replaces DCR.** A DCR `client_id` is minted per authorization server, is lost with local state, and leaves
orphaned registrations behind. A CIMD `client_id` is a URL the client already controls: stable across authorization
servers, verifiable by fetch (the AS checks that the document at that URL names itself), revocable by editing the
document, and available before the first authorization request. The cost moves from a registration database to a fetcher
on the AS side and a hosting obligation on the client side. `lauren-mcp` is on the client side, so it ships the fetcher
and exposes `CimdDocument` for hosts that drive an authorization-code flow themselves.

### 4.4 DCR deprecation path

Nothing to remove: no `registration` hits in the three files (§1.3.2) and no `registration_endpoint` is parsed, so the
≥12-month window (E-173) is honoured by policy and documentation rather than migration. **(1) Never add it** —
`registration_endpoint` in `src/` is a review blocker (§2.1). **(2) Mark it deprecated where users look** —
`README.md:138` and the `_oauth.py` class docstring (rendered at `docs/generated-reference/client.md:13`) say that
dynamic registration is deprecated in `2026-07-28` with a ≥12-month removal window and point at CIMD. **(3) Warn on
the config path that implies it** — a client id that is not a URL (a UUID or opaque token, i.e. server-minted) is
exactly the DCR shape, so `__init__` logs one `WARNING` ("client_id %r is not a URL: dynamic client registration is
deprecated in 2026-07-28 (>=12 months to removal). Prefer a Client ID Metadata Document.") at construction, not per
request, so it appears once and cannot pollute a request log.

### 4.5 stdio exemption

E-170 exempts stdio and nothing here touches `_client/_stdio.py` or the stdio server path: `ClientCredentialsProvider`
is an `httpx` auth object attached only through `McpClientFactory.http(..., auth=...)` (`_factory.py:143`), `.stdio()`
has no `auth` parameter, `fetch_client_metadata()` has no URL to derive from, and `ResourcePolicy` lives on
`oauth_settings`, which only the HTTP transports read (`_streamable.py:107`, `:144-147`). A stdio server's authority
boundary is the OS user that spawned it, and there is no third party to confuse.

### 4.6 Threat model: token replay across resources

Assumption: one authorization server issues tokens to `lauren-mcp` as a `client_credentials` client for N ≥ 2 servers;
the attacker replays a token at the wrong resource, or tries to obtain one that works everywhere.

| # | Attack | Precondition today | Control |
|---|---|---|---|
| **T1** | Cross-resource replay: capture the header at A, replay at B | no `resource` at mint (`_oauth.py:130-137`), no `aud` check at B (`_streamable.py:167-172`) | §4.2 binds at mint, §4.1 rejects at B — both ends, or neither holds |
| **T2** | Issuer substitution: a rogue AS mints the same audience | no `iss` inspection anywhere | `ResourcePolicy.issuer` must equal `claims["iss"]` when configured (E-175) |
| **T3** | Replay after expiry, or use before `nbf` | `expires_in` honoured only by the client cache (`_oauth.py:145-146`); the server checks nothing | `exp`/`nbf` with `clock_skew_s=60` |
| **T4** | Identity spoofing, or one shared secret for every server | no client-identity mechanism; the secret is the only identity | CIMD (§4.3) ties `client_id` to a document the presenter controls; one secret per (client, resource) pair (§7) |
| **T5** | Metadata lie: point `resource_metadata` at an attacker document | `_oauth_pr_meta` is operator-supplied (`:147`), served verbatim (`:561`, `:565`) | out of scope here; `_challenge()` uses the policy URL, so an inbound header never steers a client |

Residual risk: an AS that ignores `resource` still mints unbound tokens. The client cannot detect that at mint time, but
§4.1 makes the resource side fail closed, so the deployment learns immediately (`401`, `audience does not name this
resource`) instead of silently accepting replayed tokens. That is the intended failure mode.

## 5. Client-side and Server-side Changes

**Client** — `resource` on the provider, a shared `canonicalize_resource`, a CIMD fetcher, a deprecation warning for
URL-less client ids. Untouched: `_sse.py`, `_ws.py`, `_stdio.py`, `_protocol.py`, `_features.py`. **Server** — an opt-in
verifier hook and resource policy on `oauth_settings`, 401 challenges with `WWW-Authenticate`, applied to `POST /`,
`GET /`, `DELETE /`. Untouched: dispatch, sessions, both `.well-known` bodies, `_bridge.py`, the CLI, the registry.

## 6. Exact Lines to Change

`_client/_oauth.py` — `:1` docstring gains "Implements RFC 8707 resource indicators; see §4.2" (this satisfies
`grep -ril 'RFC 8707' src/`); `:90-93` docstring gains the `resource` entry; `:95-103` `__init__` gains
`resource: str | list[str] | None = None`; `:110-114` sets `self._resources = _normalize_resources(resource)`;
`:129-141` `_fetch_token` builds a list of tuples with `resource` pairs before `extra_params`; `:144-146` and `:153-163`
are unchanged bar one comment that the retried token carries the same `resource`. New: `_normalize_resources()`,
`canonicalize_resource()`, `_looks_like_url()`, `with_resource()`.

`_client/_factory.py` — `:139-147` `http()` and `sse()` gain `resource=` after `auth` (`:143`); `:162-164` docstring
says to pass `resource=` to bind the token (RFC 8707); after `:147` forward to `auth.with_resource(resource)`
(`ValueError` if the auth object is not a provider) and `logger.info` once when the token will be unbound. `stdio()` is
unchanged (E-170).

`_server/_streamable.py` — `:107` type unchanged, settings optionally expose `verifier`/`resource_policy`; `:133-141`
docstring notes enforcement; `:144-147` captures both with `getattr(..., None)`; `:167-176` calls `_authorize` before
`await request.body()` (`:172`), same guard at `:458` and `:522` (401, not 404); `:546-555` and `:557-568` are unchanged
and `_challenge()` links to the latter.

New modules — `_client/_cimd.py` (~140 lines: `CimdDocument`, `CimdError`, `fetch_client_metadata()`, `_cached_fetch()`,
`_redirect_ok()`, `_is_loopback()`); `_server/_auth.py` (~160 lines: `TokenVerifier`, `TokenRejected`, `ResourcePolicy`,
`AuthDecision`, `check_claims()`, `HmacTokenVerifier`, re-export of `canonicalize_resource`). Exports: `_client/__init__.py`
gains `ClientCredentialsProvider` (not currently re-exported), `CimdDocument`, `fetch_client_metadata`;
`_server/__init__.py` gains `ResourcePolicy`, `HmacTokenVerifier`; `README.md:138` gains the RFC 8707 sentence and the
§4.4 note.

## 7. Backward Compatibility

| Surface | Default | Change seen by a `v1.0.0` user |
|---|---|---|
| `ClientCredentialsProvider(...)` | `resource=None` | none — form body identical |
| `McpClientFactory.http(...)` | `resource=None` | none; at most one `INFO` line |
| server transport | no verifier, no policy | none — no header read, no 401, metadata bodies unchanged |
| exports / `pyproject.toml` | superset / unchanged | none — no new runtime dependency |

The one intentional change is the `WARNING` on a URL-less `client_id` (§4.4): a static `"lauren-prod"` now warns once per
construction. **Upgrade notes:** *(1)* if one `client_id`/`client_secret` is shared across servers, mint one client per
resource *and* pass `resource=`; *(2)* enabling `resource_policy` against an AS that ignores `resource` starts returning
401s — canary it and read `error_description`.

## 8. Test Plan

**8.1 Unit — `tests/unit/test_oauth_resource_indicators.py` (new)**, extending the `respx` fixtures in
`tests/unit/test_oauth_client.py` (`:89`, `:103`): `resource` posted once for one URI and twice, in order, for two; the
`v1.0.0` golden body when unset; `canonicalize_resource` rejects fragment/query/relative, lower-cases the host, drops
`:443`, keeps non-default ports, maps `""` to `"/"`; `with_resource()` twice raises and the factory cannot rebind a bound
provider; a URL-less `client_id` logs exactly one `WARNING`; `check_claims` over `aud` as string/list/`resource` echo, a
client-shaped `aud`, a missing `aud` under both `require_audience` values, `iss` mismatch and absence, `exp`/`nbf` with
skew, `insufficient_scope`; `HmacTokenVerifier` accepts HS256 and rejects a tampered payload, `alg: none`, and
`alg: RS256` with a message naming the opt-in extra.

**8.2 Unit — `tests/unit/test_cimd.py` (new):** happy path (HTTPS `client_id` echoed by the document,
`token_endpoint_auth_method="none"`); rejected (`http://` non-loopback, `https` → `http` redirect, three redirects,
65 KiB body, `client_id` mismatch, empty `redirect_uris`, `client_secret_basic`, fragment); TTL cache behaviour; loopback
`http://127.0.0.1:8765/client.json` accepted.

**8.3 Integration — `tests/integration/test_resource_binding.py` (new):** matching `aud` → `200` with a normal MCP
response; foreign `aud` → `401` carrying `error="invalid_token"` and `resource_metadata`; no `aud` → `401` by default,
`200` with `require_audience=False`; `iss` match/mismatch → `200`/`401`; no policy → byte-identical transcript (extend
`tests/integration/test_transport_changes.py`, which already asserts the `.well-known` bodies); `GET /` and `DELETE /`
challenged; in `tests/unit/test_stdio.py`, no `Authorization` header and no `fetch_client_metadata` call.

## 9. Open Questions

**Q1 — one verifier or a chain?** `TokenVerifier` + `ResourcePolicy` covers HS256 today and JWKS later; a chain
(`[introspection, jwt]`) puts an authorization-server round-trip in the request path and deserves its own PRD.

**Q2 — how do RS256 tokens get verified without breaking the two-dependency posture?** (a) in-repo RS256 via an
`auth-rs256` extra — correct, but signature verification is security-critical code; (b) delegate to the proxy and keep
`HmacTokenVerifier` in-process — least code, the current draft; (c) JWKS only via the extra. This PRD adopts (b), so a
deployment using RS256 tokens behind no proxy is not served — a real gap worth calling out in review. Related: RFC 8707
defines `resource` for authorization and token requests, but some authorization servers ignore it, so verify against a
real AS before release (E-176 lists AuthKit for MCP and Descope MCP as candidates; this PRD claims nothing about their
behaviour beyond their existence).

**Q3 — does the CIMD fetch belong in the client or the AS?** SEP-991 has the *authorization server* fetch the document.
`_client/_cimd.py` also serves hosts that drive an authorization-code flow themselves; if reviewers read that as scope
creep, the module drops to a ~60-line validator — the §4.3 rules are the durable content.

## 10. References

**Evidence (`EVIDENCE.md`)** — **E-170** OAuth 2.1 required for HTTP transports, stdio exempt (§1.3.2, §4.5); **E-171**
RFC 8707 resource indicators normative, the canonical URI is the resource (§1.3.1, §4.2); **E-172** CIMD is the
*recommended* registration path, SEP-991 (§4.3); **E-173** DCR deprecated as of `2026-07-28` (PR #2858), ≥12-month
removal window (§4.4); **E-174** Protected Resource Metadata is RFC 9728-aligned, SEP-2467 (§4.1); **E-175** `iss`
recommended as an auth response parameter, SEP-2468 (§4.1, T2); **E-176** third-party MCP authorization servers exist
(§9 Q2); **E-177**, **E-178** Zitadel and Google Cloud/Apigee MCP doc URLs **404** — cited as negatives, so this PRD
makes no capability claim about either (do not claim vendor capability you cannot verify); **E-169** OWASP MCP Top 10
exists, T1 and T4 being the MCP05-class confused-deputy pattern; **E-238** `grep -ril 'RFC 8707' src/ | wc -l` = **0**,
the gap §2.1 turns into ≥ 1; **E-246** `oauth` in **5 files** — provider (`_client/_oauth.py`) and RFC 8414 + RFC 9728
discovery (`_server/_streamable.py:133-138`); *re-verified here* the count is **3** in `src/` (8 across all `*.py` with
tests), so the recorded 5 is stale rather than contradicted; **E-247** `resource_metadata` in **1 file**; **E-222**
exactly two runtime dependencies (`pyproject.toml:28-29`).

**Specifications** — RFC 8707, RFC 9728, RFC 8414, RFC 9068 (`aud`), RFC 6750 §3 (`WWW-Authenticate`), RFC 6749 §3.1
(repeated form parameters), OAuth 2.1 draft, and the MCP `2026-07-28` authorization / client-registration /
protected-resource-metadata pages (sources behind E-170…E-175).

**Companion documents** — `EVIDENCE.md` §11, §12, §22; `_research/PRD-BRIEF.md`; model
`prds/prd-protocol-version-negotiation.md`; sibling `prd-server-discover-request-meta.md` (era-splitting convention);
`prd-dual-era-protocol-core.md`.
