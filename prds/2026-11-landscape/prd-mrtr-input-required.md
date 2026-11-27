# PRD — Multi Round-Trip Requests (`input_required`) for `tools/call`

**Status:** Draft
**Date:** 2026-11-26
**Scope:** `src/lauren_mcp/_server/_mrtr.py` (new), `_server/_context.py`, `_server/_binding.py`, `_server/_dispatcher.py`, `server/_handlers.py`, `_client/_factory.py`, `__init__.py`
**Priority:** P1
**Issue:** [#64](https://github.com/lauren-framework/lauren-mcp/issues/64)

---

## Context

`lauren-mcp` 1.0.0 implements the MCP **legacy era** (`2024-11-05` … `2025-11-25`) completely and
has **zero** `2026-07-28` (modern era) surface. The modern era does not add to the legacy
round-trip model — it **replaces** it: *"Server-initiated sampling/elicitation/roots are replaced
by MRTR (`input_required` + `requestState`), for `tools/call`, `prompts/get`, `resources/read`"*
**[E-26]**. `input_required` is a **MUST** row of `VERSIONS-MATRIX.md` §2 (TS 59, Python 59 file
hits; two trailing SDKs at 0). MRTR is a *post*-`2025-11-25` draft concept **[E-14]**, which is why
every round trip here is built on the older model and nothing in `src/` names the new one:

```bash
$ grep -rn 'resultType\|input_required\|inputRequired\|requestState' src/ | wc -l
0
$ sed -n '5p' src/lauren_mcp/_mcp_version.py
LATEST = "2025-11-25"
```

---

## 1. Problem Statement

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

# src/lauren_mcp/_server/_context.py  lines 567-571
        caps = self._client_capabilities
        if caps is None or caps.elicitation is None:
            raise McpElicitationNotAvailable(
                "The connected client did not advertise the 'elicitation' capability"
            )
```

The wire traffic is one long-lived request whose handler reaches *back* into the client —
`_client_rpc("sampling/createMessage", ...)` (`_context.py:531`) and
`_client_rpc("elicitation/create", ...)` (`_context.py:577`) — where `_client_rpc` is transport
plumbing that exists only while a bidirectional channel is open:

```python
# src/lauren_mcp/_server/_streamable.py  line 363
            async def _client_rpc(method: str, params: dict[str, Any]) -> Any:
                req_id = f"srv-{session.next_srv_id}"
                session.next_srv_id += 1
```

Three assumptions are baked in: a **session** to hang `pending_client_rpcs` on
(`_streamable.py:57`), a **capability map** captured once during `initialize`, and a channel that
stays open for the whole tool execution. The modern era removes all three — sessions are removed and
`Mcp-Session-Id` no longer exists in Streamable HTTP **[E-20]**, and the `initialize` handshake is
removed for modern peers **[E-21]**.

### 1.1 Failure scenario — a modern host calls an eliciting tool

A `2026-07-28` client connects and calls `book_flight`, a tool that confirms with `ctx.elicit(...)`:

1. The modern peer never sends `initialize`, so no client capabilities are recorded. The
   `McpToolContext` is built unconditionally at `server/_handlers.py:538` with
   `_client_rpc=binding.client_rpc if binding else None` (`server/_handlers.py:550`) and
   `_client_capabilities` of `None`.
2. `book_flight` reaches `ctx.elicit(...)`; line 568 sees `caps is None` and raises
   `McpElicitationNotAvailable` (a `RuntimeError` subclass, `_types.py:769`).
3. Nothing in the tools/call path knows that exception means "ask the user". It unwinds through
   `base()` (`server/_handlers.py:364`), past `_coerce_tool_result` (`server/_handlers.py:627`),
   into the dispatcher's catch-all at `_server/_dispatcher.py:153`, which answers every unexpected
   exception with `McpErrorCode.INTERNAL_ERROR`.

4. The client receives JSON-RPC `-32603` where the protocol mandates a successful `tools/call`
   result carrying `resultType: "input_required"`. With no retry path and no `requestState`, the
   *only* correct outcome for a modern peer is the one this server cannot produce.

The same shape occurs on the legacy path against hosts that do not hold the Streamable HTTP stream
open — `_client_rpc` parks a future in `pending_client_rpcs` and the tool hangs until timeout. MRTR
removes the hang: the tool call *returns*, and the client drives the next round.

### 1.2 Secondary problem — round trips are invisible and untestable

Because the round trip is nested, it is invisible to everything outside the connection: the host's
UI, its retry/telemetry layer, an OTel span boundary (`_server/_otel.py`), and our own tests, which
must stand up a live bidirectional channel to exercise one confirmation. It is unrepresentable in a
validator, because there is no field to look for. A `resultType`-carrying result makes "this call
needs input" a *value* — inspectable and assertable with a plain JSON assertion — instead of a side
effect of an open socket.

---

## lauren-mcp Advantages

**The `McpToolContext` seam is already the right shape.** `server/_handlers.py:538` builds one
immutable per-call context and injects it through `@mcp_tool`; `request_input()` is a new method on
an existing object, not a new programming model. An SDK consumer would have to reach into a
request/response loop they do not own; here the protocol layer is ours (`_dispatcher.py`,
`_streamable.py`, `_sse.py`, `_stdio.py` are hand-written).

**The two-dependency posture (`lauren`, `anyio`) is preservable.** MRTR state needs HMAC, zlib,
base64 and JSON — all stdlib. A signed `requestState` is ~60 lines with no new dependency, keeping
a stated competitive asset instead of trading it for a token library.

**Statelessness is already half-built, which MRTR requires.** Sessions are gone in the modern era
**[E-20]**, so resumption state cannot live in a session object; the repo carries
`_server/_event_store.py` and a thread-local `TransportBinding` (`_server/_binding.py:28`) instead.
A signed opaque token *extends* that architecture rather than re-architecting it.

**Honest limitation.** None of this is beyond an SDK-authoring effort, and the Python SDK already
shows 59 `input_required` file hits *(presence, not conformance)*. The advantage is shipping the
modern era without adopting, vendoring, or forking an implementation that does not fit the DI
model.

---

## 2. Goals

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

---

## 3. Non-Goals

- **Not** implementing the rest of the modern era (`server/discover`, `subscriptions/listen`,
  `resultType` on every result, `tasks/*`). This PRD adds MRTR vocabulary only where one round trip
  needs it; the era-wide switch is a separate PRD.
- **Not** removing `ctx.sample()`, `ctx.elicit()`, `ctx.elicit_url()` or the
  `pending_client_rpcs` machinery. They remain the legacy delivery path and are what
  `request_input()` compiles down to on old peers.
- **Not** batching several input requests into one round trip: the shape is a map and permits it,
  but this PRD emits exactly one entry per round trip (§9 Q2).
- **Not** a durable job store: `requestState` is a bounded token (≤ 4 KB of JSON before encoding),
  not a workflow engine; larger state fails with `-32602`.
- **Not** touching `prompts/get` or `resources/read`: E-26 names all three and the codec is
  reusable, but only `tools/call` is wired.
- **Not** a UI: no form rendering and no CLI prompt loop — the driver calls a user-supplied
  async callback.

---

## 4. Design

### 4.1 Wire shape

A modern round trip is two ordinary `tools/call` requests. First response:

```json
{"content": [], "isError": false, "resultType": "input_required",
 "inputRequests": {"confirm_booking": {
   "method": "elicitation/create",
   "message": "Confirm booking to LIS for 2026-12-04?",
   "requestedSchema": {"type": "object",
     "properties": {"confirm": {"type": "boolean"}}, "required": ["confirm"]}}},
 "requestState": "v1.eJytVAVT...9fQc.Zm9vYmFy..."}
```

The second request repeats `name`/`arguments` and adds `requestState` plus `inputResponses`, a map
keyed like `inputRequests` whose values are `{"action": "accept", "content": {...}}`.

`resultType`, `input_required` and `requestState` are the names E-26 pins down. The nested keys
(`inputRequests`, `inputResponses`, `method`) are this PRD's proposal and are Q1 in §9 — isolated in
one function (`build_input_required_result`) so a rename is a one-line change plus a test edit.

### 4.2 `McpInputRequired` — a control-flow signal, not an error

The tool body must be able to *stop* mid-way. The cheapest mechanism that keeps tool code linear is
an exception, deliberately inheriting `BaseException` so that neither `except Exception` in tool
bodies nor third-party middleware can turn a resumption point into a 500:

```python
# src/lauren_mcp/_server/_mrtr.py  (new file)
class McpInputRequired(BaseException):
    """Raised by ``ctx.request_input()`` to yield a round trip to the peer.

    Inherits ``BaseException`` (like ``StopAsyncIteration``) so a resumption
    point is not swallowed by ``except Exception``; the tools/call handler
    converts it to a ``resultType: "input_required"`` result.
    """

    def __init__(self, request: InputRequest) -> None:
        super().__init__(request.key)
        self.request = request
```

Because the tool is re-entered from the top on resume (§4.4), no stack container is needed:
replaying the function is the semantics we want, and it keeps the token small.

### 4.3 Stateless, signed `requestState`

```python
# src/lauren_mcp/_server/_mrtr.py  (new file)
_STATE_VERSION: Final = "v1"
DEFAULT_MAX_AGE: Final = 300.0
MAX_STATE_BYTES: Final = 4096


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass(frozen=True, slots=True)
class MrtrStateCodec:
    """Encodes/decodes the opaque ``requestState`` token."""

    secret: bytes
    max_age: float = DEFAULT_MAX_AGE

    @classmethod
    def from_env(cls, max_age: float = DEFAULT_MAX_AGE) -> "MrtrStateCodec":
        raw = os.environ.get("LAUREN_MCP_MRTR_SECRET")
        # A per-process random secret is correct for one process and degrades
        # safely (tokens stop working after a restart) rather than silently
        # accepting anything under a shared default.
        return cls(secret=raw.encode() if raw else os.urandom(32), max_age=max_age)

    def encode(self, *, tool: str, pending: dict[str, Any], data: dict[str, Any]) -> str:
        body = json.dumps(
            {"t": tool, "p": pending, "d": data, "iat": int(time.time())},
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        if len(body) > MAX_STATE_BYTES:
            raise McpInvalidParamsError(
                "arguments",
                f"MRTR state exceeds {MAX_STATE_BYTES} bytes; pass less data in "
                "ctx.request_input(data=...) and re-read it instead",
            )
        raw = zlib.compress(body, 9)
        mac = hmac.new(self.secret, raw, hashlib.sha256).digest()[:16]
        return f"{_STATE_VERSION}.{_b64(raw)}.{_b64(mac)}"

    def decode(self, token: str, *, tool: str) -> tuple[dict[str, Any], dict[str, Any]]:
        version, _, rest = token.partition(".")
        payload, _, mac_text = rest.partition(".")
        if version != _STATE_VERSION or not payload or not mac_text:
            raise McpInvalidParamsError("requestState", "malformed requestState token")
        raw = _unb64(payload)
        expected = hmac.new(self.secret, raw, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(expected, _unb64(mac_text)):
            raise McpInvalidParamsError("requestState", "requestState signature mismatch")
        body = json.loads(zlib.decompress(raw))
        if body.get("t") != tool:
            raise McpInvalidParamsError(
                "requestState", f"requestState was issued for tool {body.get('t')!r}"
            )
        if time.time() - body["iat"] > self.max_age:
            raise McpInvalidParamsError("requestState", "requestState has expired")
        return body["p"], body["d"]
```

Four properties, all asserted in §8.1: **self-contained** (no session lookup, satisfying E-20),
**tamper-evident** (`compare_digest`), **tool-bound** (a token for `book_flight` is rejected by
`delete_account`), **time-bound** (`max_age`).

### 4.4 `McpToolContext.request_input()` — one call site, two eras

```python
# src/lauren_mcp/_server/_context.py  (new method, after elicit_url)
    async def request_input(
        self,
        *,
        key: str,
        message: str,
        schema: dict[str, Any],
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Ask the peer for input and return the accepted content.

        Modern peers: raises ``McpInputRequired`` so the call returns
        ``resultType: "input_required"``; on resume this returns the answer.
        Legacy peers: falls back to ``elicit()`` and returns now.
        """
        answer = self._mrtr_answers.get(key)
        if answer is not None:
            return answer                       # resumed round trip
        request = InputRequest(
            key=key,
            payload={
                "method": "elicitation/create",
                "message": message,
                "requestedSchema": schema,
            },
        )
        if self._mrtr_supported:
            self._mrtr_pending = request
            raise McpInputRequired(request)
        result = await self.elicit(message=message, requested_schema=schema)
        if result.action != "accept":
            raise McpToolError(f"input {key!r} was {result.action}")
        return dict(result.content or {})
```

`_mrtr_supported` is decided once per call in the context factory (§5.1); `_mrtr_answers`,
`_mrtr_resume_data` and `_mrtr_pending` are new fields on the same `McpToolContext` object
(`server/_handlers.py:538`). Nothing else about the object changes.

### 4.5 Wiring into the tools/call result

The single point where a tool's return value becomes a `tools/call` result is `_coerce_tool_result`
(`server/_handlers.py:627`), reached from `base()` (`server/_handlers.py:364`). The exception must be
caught one frame up, around the invocation, because the coercion function never sees it:

Current code (`server/_handlers.py:364-371`) calls the tool straight through:
`result = await method(**kwargs)` at line 365, then either drains a `ToolStream` or returns
`_coerce_tool_result(result, meta)`. Replacement:

```python
# src/lauren_mcp/server/_handlers.py  lines 364-374 — after
    async def base() -> dict[str, Any]:
        try:
            result = await method(**kwargs)
        except McpInputRequired as pending:
            ctx_obj = (
                kwargs.get(meta.context_param_name) if meta.context_param_name else None
            ) or tool_ctx
            return build_input_required_result(pending, ctx=ctx_obj, tool=meta.name)
        if isinstance(result, ToolStream):
            ...
```

and the envelope builder — the one place that knows the field names:

```python
# src/lauren_mcp/_server/_mrtr.py  (new file)
def build_input_required_result(
    pending: McpInputRequired,
    *,
    ctx: McpToolContext,
    tool: str,
    codec: MrtrStateCodec | None = None,
) -> dict[str, Any]:
    """Render a ``resultType: "input_required"`` tools/call result."""
    state = (codec or MrtrStateCodec.from_env()).encode(
        tool=tool,
        pending={pending.request.key: pending.request.payload},
        data=ctx.mrtr_resume_data(),
    )
    return {
        "content": [],
        "isError": False,
        "resultType": "input_required",
        "inputRequests": {pending.request.key: pending.request.payload},
        "requestState": state,
    }
```

It deliberately does **not** reuse `out = {"content": content, "isError": is_error}`
(`server/_handlers.py:670`): the coercion path is for *finished* results, and routing a resumption
through it would drag every future `resultType` change into the coercion function.

### 4.6 Consuming `requestState` on the way in

`make_tools_call_handler` (`server/_handlers.py:773`) reads `params` before dispatch. Two lines are
added there to unpack a resumed call:

```python
# src/lauren_mcp/server/_handlers.py  lines 776-778 — after
        params: dict[str, Any] = req.params if isinstance(req.params, dict) else {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        request_state = params.get("requestState")
        input_responses = params.get("inputResponses") or {}
```

and the context factory (`server/_handlers.py:536-552`) decodes it before building the object:

```python
        if request_state:
            pending, resume_data = MrtrStateCodec.from_env().decode(request_state, tool=tool_name)
            mrtr_answers = _accepted(input_responses, pending)
        else:
            resume_data, mrtr_answers = {}, {}
        return McpToolContext(..., _mrtr_supported=_mrtr_supported(binding),
                              _mrtr_answers=mrtr_answers, _mrtr_resume_data=resume_data)
```

`_mrtr_supported(binding)` is a three-line predicate: false when the binding carries no capability
map on a modern `_meta` protocol version, false when `caps.elicitation is None` on a legacy peer
(preserving §1's behaviour exactly), true otherwise. Keeping the decision in one function is what
makes `test_legacy_peer_keeps_elicitation` a one-liner.

### 4.7 Client-side driver

The client half must not leak the loop into user code:

```python
# src/lauren_mcp/_client/_factory.py  (new helper, exported)
async def call_tool_with_mrtr(
    client: McpServer,
    name: str,
    arguments: dict[str, Any],
    *,
    on_input: Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]],
    max_rounds: int = 4,
) -> dict[str, Any]:
    """Drive MRTR until the server returns a final result."""
    for _ in range(max_rounds):
        result = await client.call_tool(name, arguments)
        if result.get("resultType") != "input_required":
            return result
        answers = {}
        for key, request in result["inputRequests"].items():
            answers[key] = {"action": "accept", "content": await on_input(key, request)}
        arguments = {
            **arguments,
            "requestState": result["requestState"],
            "inputResponses": answers,
        }
    raise McpMrtrRoundLimit(f"{name} exceeded max_rounds={max_rounds}")
```

`max_rounds` is a hard stop: an unbounded MRTR loop with a buggy handler is a liveness bug.

---

## 5. Server-Side and Client-Side Changes

### 5.1 Server

- New `src/lauren_mcp/_server/_mrtr.py`: `InputRequest`, `McpInputRequired`, `MrtrStateCodec`,
  `build_input_required_result`, `_accepted`, `_mrtr_supported` (§4.2, §4.3, §4.5).
- `_server/_context.py`: four private fields (`_mrtr_supported`, `_mrtr_answers`,
  `_mrtr_resume_data`, `_mrtr_pending`), `request_input()` (§4.4) and `mrtr_resume_data()`
  returning `{"tool": self.tool_name, "tool_use_id": self.tool_use_id}`. `McpToolContext` stays
  `frozen`; all four are set at construction, never mutated after.
- `server/_handlers.py`: the try/except at `base()` (§4.5) and the unpacking lines in the tools/call
  handler (§4.6).
- `_types.py`: nothing removed; `McpInputRequired` re-exported for convenience only.
- `_server/_dispatcher.py`: **no change**. `McpInputRequired` never reaches `dispatch()` because
  `base()` converts it; if a tool is invoked outside the handler it does, and line 153's catch-all
  returns `-32603` — the correct "you bypassed the handler" signal.

### 5.2 Client

- `_client/_factory.py`: export `call_tool_with_mrtr` and `McpMrtrRoundLimit` (§4.7).
  `_client/_features.py` gains nothing — the driver sits above the feature matrix.
- The existing `sampling`/`elicitation` callbacks (`_client/_factory.py:47`) keep working; on a
  legacy connection the server still sends `elicitation/create` and the callback answers it.
- No change to `_client/_stdio.py`: MRTR needs no channel, which is the point.

---

## 6. Exact Lines to Change

| File | Line(s) | Change |
|---|---|---|
| `_server/_mrtr.py` (new) | — | §4.2, §4.3, §4.5; ~150 lines; stdlib imports only (`base64`, `hashlib`, `hmac`, `json`, `os`, `time`, `zlib`) plus `McpInvalidParamsError` from `_server/_dispatcher.py:24` |
| `_server/_context.py` | after `303`, after `649` | add `_mrtr_supported: bool = False`, `_mrtr_answers`, `_mrtr_resume_data`, `_mrtr_pending` after `_client_rpc: ClientRpc \| None = None`; insert `request_input()` and `mrtr_resume_data()` after the end of `elicit_url` |
| `server/_handlers.py` | `365` (`result = await method(**kwargs)`) | wrap in `try/except McpInputRequired` per §4.5 |
| `server/_handlers.py` | `536-552`, `776-778` | decode `requestState`, pass three new fields into `McpToolContext(...)`; read `requestState`/`inputResponses` from `params` |
| `server/_handlers.py` | `627`, `670` | **no change** — `_coerce_tool_result` and the `out` dict stay as they are |
| `server/_handlers.py` | `774` | import `McpInputRequired`, `build_input_required_result` |
| `_server/_binding.py` | after `40`, class at `28` | add `client_capabilities: Any = None` to `TransportBinding` so `_mrtr_supported` does not reach through private fields |
| `_client/_factory.py` | — | add `call_tool_with_mrtr`, `McpMrtrRoundLimit`; extend `__all__` |
| `__init__.py` | `79-85` | export `McpInputRequired`, `MrtrStateCodec`, `call_tool_with_mrtr` |

---

## 7. Backward Compatibility

**Behaviour on legacy peers is unchanged, byte for byte.** `_mrtr_supported` is false when
`caps.elicitation is None` or when no capability map was captured, so `ctx.elicit()` still raises
`McpElicitationNotAvailable` with the identical message and `request_input()` degrades to `elicit()`.
Every existing test asserting those messages keeps passing untouched.

**No existing signature changes.** `McpToolContext` gains defaulted fields; `_coerce_tool_result` and
`dispatch()` are untouched. **New result shapes appear only where there was an error before**: a tool
that never calls `request_input()` cannot emit `resultType`, so a client that knows only
`{content, structuredContent, isError}` sees exactly what it sees today.

**Migration notes — none for library users.** A user who never called `ctx.elicit()` has nothing to
do; one who did has a drop-in spelling in `request_input()` and needs it only when claiming the
modern era.

**One operational requirement.** Set `LAUREN_MCP_MRTR_SECRET` when running more than one process:
otherwise each process generates its own secret and a round trip landing on another worker fails with
`-32602` and "signature mismatch" — loud, correct and confusing, hence this paragraph.

---

## 8. Test Plan

### 8.1 Unit tests — `tests/unit/test_mrtr.py`

| Test | Asserts |
|---|---|
| `test_codec_rejects_forged_mac` | flipping one character of the MAC raises `McpInvalidParamsError(field="requestState")` |
| `test_codec_rejects_wrong_tool` | token issued for `book_flight`, presented to `delete_account`, raises |
| `test_codec_rejects_expired` | `max_age=0.01`, `anyio.sleep(0.05)`, raises "expired" |
| `test_request_input_raises_input_required_on_modern_peer` | `_mrtr_supported=True` → `McpInputRequired` with `request.key` set |
| `test_request_input_legacy_falls_back_to_elicit` | `_mrtr_supported=False` → `elicit` called once, content returned |
| `test_mrtr_not_swallowed_by_except_exception` | `try: raise McpInputRequired(...) except Exception: pytest.fail` |

### 8.2 Integration tests — `tests/integration/test_mrtr_roundtrip.py`

| Test | Scenario |
|---|---|
| `test_two_round_trip_resume` | in-memory transport; tool asks twice; second call resumes and returns final content |
| `test_result_shape_matches_schema` | raw JSON of the first response asserted field-by-field against §4.1 |
| `test_legacy_peer_still_gets_elicitation_create` | `2025-06-18` peer with `elicitation` capability sees exactly one `elicitation/create` |
| `test_expired_state_is_minus_32602` | sleep past TTL, re-issue, assert code and `data.field == "requestState"` |

Must stay green: `tests/unit/test_tool_context.py`, the sampling/elicitation integration tests, and
anything asserting the `McpElicitationNotAvailable` message.

---

## 9. Open Questions

1. **Exact nested field names.** E-26 fixes `resultType`, `input_required` and `requestState` but
   does not pin the request/response maps. Are they `inputRequests`/`inputResponses`, and is the
   per-entry discriminator `method`? Isolated in `build_input_required_result()` so the answer is a
   one-line change.
2. **Batching.** Should one round trip carry several `inputRequests`? Raising on the first miss means
   a tool asking twice needs two round trips — correct but chattier.
3. **Where does `requestState` live in the retry?** In `params` (proposed) or in per-request `_meta`?
   `_meta` is already the modern carrier for protocol version **[E-22]**, which argues for `_meta`; a
   top-level key is easier for hand-written clients.
4. **Secret distribution.** Should a multi-worker start-up without `LAUREN_MCP_MRTR_SECRET` refuse to
   boot (strict, safest) or warn (friendlier)?
5. **Cancellation.** Cancelling round 2 leaves round 1's token live until TTL (the repo also listens
   for `$/cancelRequest` instead of `notifications/cancelled`). Shorter TTL, or `state/abandon`?
6. **Token-only retries.** If a host retries with `requestState` and no `arguments`, the arguments
   must move into `d` — a size risk against `MAX_STATE_BYTES`.

---

## 10. References

- **E-14** — MRTR is *post*-`2025-11-25`; `2025-11-25` has no round-trip content: why nothing here
  implements it.
- **E-20** — Sessions removed in `2026-07-28`, `Mcp-Session-Id` gone → `requestState` must be
  self-contained (§4.3).
- **E-21** — `initialize` removed for modern peers → capability map absent → §1.1 failure.
- **E-22** — Per-request `_meta` carries protocol version and client info → Q3.
- **E-26** — Sampling/elicitation/roots replaced by MRTR (`input_required` + `requestState`) for
  `tools/call`, `prompts/get`, `resources/read` — the load-bearing citation.
- `VERSIONS-MATRIX.md` §2 — `input_required` is a MUST row; TS 59 / Python 59 file hits, trailing
  SDKs 0 *(presence, not conformance)*.
- `_research/lauren-mcp-inventory.md` §5 — `sampling/createMessage`, `elicitation/create`,
  `roots/list` are the handshake-era round trips we ship.
- `_server/_context.py:437,547,580`, `_server/_streamable.py:363`, `_mcp_version.py:5` — the code
  this PRD replaces or extends. Style model: `prds/prd-protocol-version-negotiation.md`.
