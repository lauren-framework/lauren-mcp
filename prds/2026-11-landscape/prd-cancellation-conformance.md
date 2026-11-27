# PRD — Cancellation Conformance: Accept `notifications/cancelled`

**Status:** Draft
**Date:** 2026-11-26
**Scope:** `lauren-mcp` server transports (`_server/_ws.py`, `_server/_stdio.py`, `_server/_streamable.py`), `_server/_dispatcher.py`, `_server/_context.py`, and `docs/guides/tool-context.md`
**Priority:** P1
**Issue:** [#65](https://github.com/lauren-framework/lauren-mcp/issues/65)

---

## 1. Problem Statement

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

Six files, nine occurrences of the wrong name — four of them executable code paths.

### 1.1 A cancelled tool call keeps running, and its result is written to a dead request

A Lauren application exposes a slow tool — `@mcp_tool(name="reindex")` awaiting `build_index(path)`,
60-90 s of I/O. The client calls it; the user presses Escape; per the specification the client emits:

```json
{"jsonrpc": "2.0", "method": "notifications/cancelled",
 "params": {"requestId": 7, "reason": "user cancelled"}}
```

`lauren-mcp` compares that method against a constant and falls through:

```python
# src/lauren_mcp/_server/_ws.py  lines 39, 288-297
_METHOD_CANCEL = "$/cancelRequest"
...
            if method == _METHOD_CANCEL:
                params = notification.params or {}
                if isinstance(params, dict):
                    request_id = params.get("id")
                    if request_id is not None:
                        self._dispatcher.cancel(request_id)
                return
```

`"notifications/cancelled" != "$/cancelRequest"`, so the notification is dropped as unknown and
`McpDispatcher.cancel()` is never reached. `build_index()` runs to completion and its 90-second result
is serialised to a client that has already forgotten request `7`.

Its result is then written unconditionally (`_ws.py:243-246`: `dispatch(msg)` followed by
`await ws.send_text(response.to_json())`). Depending on the client this surfaces as an `Unknown request id` log line, a dropped frame, or — in
Streamable HTTP, where the `POST` carrying `tools/call` is parked on a `text/event-stream` body — a write
into a stream the client may have closed. The work is not cancelled, and the only party who asked it to
stop is the one party the server does not listen to. The same two lines exist in `_streamable.py:212-215`
(`elif msg.method == "$/cancelRequest" ...`) and `_stdio.py:76-81` (`if message.method !=
"$/cancelRequest": return`), so the defect is uniform.

### 1.2 Renaming the method is not sufficient: the read loop is blocked by the call it should cancel

`McpDispatcher` already does the right thing once it is told to cancel: it wraps every handler in an
`asyncio.Task` (`_dispatcher.py:126-128`), tracks it in `_in_flight`, and `cancel()`
(`_dispatcher.py:165-189`) sets the cooperative `_cancel_event` *before* hard-cancelling the task.

But the two stateful transports never give that machinery a chance: they `await` the dispatch **inside
their frame/line read loop**.

```python
# src/lauren_mcp/_server/_ws.py  line 202
                    await self._handle_frame(
# src/lauren_mcp/_server/_stdio.py  lines 61-63
            if isinstance(message, JsonRpcRequest):
                response = await dispatcher.dispatch(message)
```

While `build_index()` awaits I/O the loop is parked, so `ws.receive_text()` / `reader.readline()` is
not called and the cancel frame sits unread in the transport buffer. When the tool finally returns the
loop reads the stale cancel, calls `dispatcher.cancel(7)`, and `cancel()` returns `False` because
`_in_flight` was already popped in `dispatch`'s `finally` (`_dispatcher.py:161-163`) — a silent no-op,
precisely the failure `notifications/cancelled` exists to prevent. Streamable HTTP escapes this: each
`POST` is a separate ASGI request decoded on its own task (`_streamable.py:277`), so there the method
name alone is the bug.

### 1.3 The tool-facing contract is already built, and is unreachable

`McpToolContext` exposes a lazily-created cooperative event for exactly this feature, and the guide
already documents the spec method — so the docs are right, the middleware is right, and only the wire
name is wrong:

```python
# src/lauren_mcp/_server/_context.py  lines 321-336
    def cancel_requested(self) -> asyncio.Event:
        """An ``asyncio.Event`` set when the client cancels this call.
        ...
        Tools should treat this as a *read-only* hint: check
        ``cancel_requested.is_set()`` between work units and return early for
        graceful shutdown.
```

```
docs/guides/tool-context.md:448
`notifications/cancelled` notification for the current request. Tools should poll
```

Three layers disagree: **the docs name the spec method, the code matches an LSP method, and the
middleware between them is correct but starved of input.** The wrong name is also memorialised in
five docstrings — `_ws.py:74`, `_dispatcher.py:105`, `_context.py:308`, `_context.py:336`,
`server/_handlers.py:757` (C-03) — which §6 corrects.

### 1.4 Secondary: the peer-cancelled request still gets a response frame

```python
# src/lauren_mcp/_server/_dispatcher.py  lines 133-138
        except asyncio.CancelledError:
            return build_error_response(
                id=request.id,
                code=McpErrorCode.REQUEST_CANCELLED,
                message=f"Request {request.id!r} was cancelled",
            )
```

`REQUEST_CANCELLED = -32800` (`_types.py:119`). Keeping the *internal* result is right — `dispatch()`
must return something so the awaiting transport can unwind. Writing it to the wire for a request the
peer explicitly abandoned is not: the client has discarded the id and the writer may be a half-closed
stream. Cancellation is the one case where the correct response is no response.

---

## 2. Goals

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

---

## 3. Non-Goals

* **Client-side cancellation.** `McpClient` never sends a cancellation notification — the only `cancel`
  calls under `src/lauren_mcp/_client/` are `Task.cancel()` on local tasks (`_client/_sse.py:130`,
  `_client/_streamable.py:117`). `McpClient.cancel(request_id)` is a separate PRD (§9, Q3).
* **`2026-07-28` task-augmented cancellation.** The modern era moves long work into tasks (`tasks/…`,
  E-235) with different cancellation semantics; nothing here depends on that era.
* **Server-side timeouts and progress-token cleanup.** A wall-clock deadline that cancels a tool without
  a peer notification is a resource-policy feature; `notifications/cancelled` is peer-driven only, and
  clearing a cancelled request's progress state belongs to the progress PRD.
* **Guaranteeing the tool stops.** Python cannot preempt a synchronous tool: this PRD guarantees
  `cancel_requested` is set and `task.cancel()` is delivered, not that a blocking C call stops.
* **Changing the `-32800` code or its name.** `McpErrorCode.REQUEST_CANCELLED` is public surface; only
  its *emission to the wire* changes. Authorising a cancel is likewise out of scope: it can only arrive
  on the session that owns the request.

---

## 4. Design

Four moving parts: a module that owns the wire contract, three one-line transport call sites, a
dispatcher that remembers *why* a request ended, and a concurrency change in the two loops that are
currently serialised.

### 4.1 One module owns the names

```python
# src/lauren_mcp/_server/_cancel.py   (new)
CANCEL_METHOD = "notifications/cancelled"          # spec method (E-08)
LEGACY_CANCEL_METHOD = "$/cancelRequest"           # LSP name; alias for one minor release
UNCANCELLABLE_METHODS = frozenset({"initialize"})  # the spec forbids cancelling the handshake


def is_cancel_notification(method: str) -> bool:
    return method in (CANCEL_METHOD, LEGACY_CANCEL_METHOD)


def cancel_request_id(params: Any) -> str | int | None:
    """``requestId`` is the spec spelling; ``id`` is the pre-1.1 alias."""
    if not isinstance(params, dict):
        return None
    request_id = params.get("requestId", params.get("id"))
    return request_id if isinstance(request_id, (str, int)) else None


def handle_cancel(dispatcher: "McpDispatcher", method: str, params: Any) -> bool:
    """Apply a cancellation notification.  Never writes to the wire: a
    notification has no response, and the cancelled request's own response is
    suppressed by the transport (PRD §4.5)."""
    if method == LEGACY_CANCEL_METHOD:
        logger.warning("%s is not an MCP method (it is an LSP name); send %s instead.",
                       LEGACY_CANCEL_METHOD, CANCEL_METHOD)
    request_id = cancel_request_id(params)
    if request_id is None:
        return False
    reason = params.get("reason") if isinstance(params, dict) else None
    return dispatcher.cancel(request_id, reason=reason if isinstance(reason, str) else None)
```

### 4.2 The dispatcher remembers why a request ended

```python
# src/lauren_mcp/_server/_dispatcher.py  — replaces lines 165-189
    def cancel(self, request_id: str | int, *, reason: str | None = None) -> bool:
        """Cancel the in-flight task for *request_id*.

        Sets the cooperative ``cancel_requested`` event before hard-cancelling
        the task, then records the id in ``_peer_cancelled`` so the transport
        can drop the response frame.
        """
        task = self._in_flight.get(request_id)
        if task is None or task.done():
            return False
        if self._method_of.get(request_id) in UNCANCELLABLE_METHODS:
            return False
        ctx = self._contexts.get(request_id)
        if ctx is not None:
            cancel_event = getattr(ctx, "_cancel_event", None)
            if cancel_event is not None:
                cancel_event.set()
            object.__setattr__(ctx, "_cancel_reason", reason)
        self._peer_cancelled.add(request_id)
        logger.debug("Cancelling request %r (%s)", request_id, reason or "no reason")
        task.cancel()
        return True

    def was_peer_cancelled(self, request_id: str | int) -> bool:
        return request_id in self._peer_cancelled
```

`_method_of` is populated in `dispatch()` beside `self._in_flight[request_id] = task`
(`_dispatcher.py:128`) and popped with the other two dicts in the same `finally`
(`_dispatcher.py:161-163`). `_peer_cancelled` ids are discarded by the transport when it observes them
(§4.5), so the set cannot grow across a session. `dispatch()` still returns the `-32800` response
(`_dispatcher.py:133-138`); only the transport's decision to write it changes.

### 4.3 Transports: one call, three sites

```python
# src/lauren_mcp/_server/_ws.py  — replaces lines 288-294
            if is_cancel_notification(method):
                handle_cancel(self._dispatcher, method, notification.params)
                return
```

The same call replaces `_streamable.py:212-215` and the whole `_handle_notification` body at
`_stdio.py:76-81`, whose signature is unchanged so no plumbing moves.

### 4.4 Make the two read loops concurrent

This is what makes cancellation *effective* rather than merely *accepted*: a handler must not own the
loop that reads frames. Requests become tasks; notifications stay inline and cheap — an asymmetry that
is exactly what a cancel needs.

```python
# src/lauren_mcp/_server/_ws.py  — inside _serve(), replaces the receive loop at lines 195-206
            while True:
                try:
                    raw: str = await ws.receive_text()
                except Exception:
                    break
                for msg in self._decode_frames(raw):        # existing parse helper
                    if isinstance(msg, JsonRpcRequest):
                        task = asyncio.create_task(self._handle_frame(ws, msg))
                        self._frame_tasks.add(task)
                        task.add_done_callback(self._frame_tasks.discard)
                    else:
                        await self._handle_frame(ws, msg)
```

A new `_send(ws, payload)` helper — `async with self._write_lock: await ws.send_text(payload)` —
replaces the bare `await ws.send_text(...)` at `_ws.py:246`, so two concurrent results cannot interleave
half a frame. stdio mirrors this at `_stdio.py:61-64` with a `pending` task set drained in the
existing `finally` (`_stdio.py:36-70`), so a `SIGTERM` mid-tool does not truncate a response.

### 4.5 Suppress the response for a peer-cancelled request

```python
# src/lauren_mcp/_server/_ws.py  — replaces lines 243-246
                response = await self._dispatcher.dispatch(msg)
                if self._dispatcher.was_peer_cancelled(msg.id):
                    logger.debug("Dropping response for peer-cancelled request %r", msg.id)
                    return
                await self._send(ws, response.to_json())
```

stdio's `_dispatch_and_write` takes the same guard (`if not dispatcher.was_peer_cancelled(message.id)`),
as does the Streamable HTTP writer at `_streamable.py:277-281`; there, when the cancelled request is the
only one on an open `text/event-stream`, the `POST` completes with an empty event stream rather than a
`-32800` payload. Programmatic cancellation is unaffected: `was_peer_cancelled()` is only `True` when `cancel()` was
reached through `handle_cancel`, so `app.shutdown()` still gets the error frame.

### 4.6 The tool-facing contract, now reachable

```python
# user code — the existing API, now actually driven by the wire
@mcp_tool(name="reindex")
async def reindex(ctx: McpToolContext, path: str) -> ReindexReport:
    for batch in chunks(path, 500):
        if ctx.cancel_requested.is_set():
            logger.info("reindex cancelled: %s", ctx.cancel_reason)
            return partial_report()            # graceful stop
        await index_batch(batch)
    return full_report()
```

`ctx.cancel_reason -> str | None` is a new read-only property backed by `_cancel_reason` (§4.2). It is
additive, defaults to `None`, and is safe for the frozen dataclass, which already tolerates
`object.__setattr__` for `_cancel_event` (`_context.py:321-340`).

---

## 5. Server-side Changes

* **`src/lauren_mcp/_server/_cancel.py`** (new, ~85 lines) — method names, params extraction, `handle_cancel()`.
* **`_server/_dispatcher.py`** — `cancel(..., reason=)`, `_method_of`, `_peer_cancelled`,
  `was_peer_cancelled()`, `initialize` guard.
* **`_server/_ws.py`** — cancel branch, per-frame tasks, `_write_lock`/`_send`, response suppression.
* **`_server/_stdio.py`** — `_handle_notification` rewrite, task-per-request, drain on shutdown.
* **`_server/_streamable.py`** — cancel branch, response suppression.
* **`_server/_context.py`**, **`server/_handlers.py`** — docstrings at 308/336/757, `cancel_reason` property.
* **`docs/guides/tool-context.md`** — cancellation section rewritten around `notifications/cancelled`.

No public export is removed: `lauren_mcp._server` is private by convention, and the user-facing surface
(`ctx.cancel_requested`, `McpErrorCode.REQUEST_CANCELLED`) keeps its names.

---

## 6. Exact Lines to Change

Line numbers verified with `grep -n` against `7778737`; each entry names the symbol, not only the number.

**`_server/_ws.py`** — `39` delete `_METHOD_CANCEL = "$/cancelRequest"` (import
`is_cancel_notification`, `handle_cancel`); `74` docstring → "``notifications/cancelled`` (and the legacy
`$/cancelRequest` alias)"; `195-206` per-request `asyncio.create_task`, notifications inline (§4.4);
`243-246` `was_peer_cancelled` guard before `await self._send(...)`; `288-297` the whole branch becomes
`if is_cancel_notification(method): handle_cancel(self._dispatcher, method, notification.params)`, which
also retires the debug string at `296` (`"$/cancelRequest: no in-flight task for request %r"`).

**`src/lauren_mcp/_server/_dispatcher.py`** — `71-74` add `_method_of`, `_peer_cancelled`; `105`
docstring → "``notifications/cancelled`` notification"; `128` also record
`self._method_of[request_id] = request.method`; `161-163` `finally` also pops `_method_of`;
`165-189` `cancel(self, request_id, *, reason=None)` plus `was_peer_cancelled()`.

**`src/lauren_mcp/_server/_stdio.py`** — `61-64` `asyncio.create_task(_dispatch_and_write(...))` on the
read loop; `74-81` replace the whole `_handle_notification` body with one `handle_cancel(...)` call;
new module-level `pending: set[asyncio.Task[None]]` drained before `app.shutdown()`.

**`src/lauren_mcp/_server/_streamable.py`** — `212-215` `elif is_cancel_notification(msg.method):
handle_cancel(self._dispatcher, msg.method, msg.params)`; `277-281` `was_peer_cancelled` guard before the
SSE/JSON write.

**`src/lauren_mcp/_server/_context.py`** — `308` comment → "when notifications/cancelled arrives"; `336`
keep the docstring, add the `cancel_reason` property below it.

**`src/lauren_mcp/server/_handlers.py`** — `757` docstring → "`notifications/cancelled` can set the
cooperative cancel_requested event".

**`docs/guides/tool-context.md`** — 448 already names the spec method; the surrounding section must stop
implying the server *sends* cancellation and show the §4.6 pattern.

---

## 7. Backward Compatibility

| Surface | Impact | Migration |
|---|---|---|
| Wire: `$/cancelRequest` clients | still accepted via the alias in `_cancel.py`, now logged at `WARNING` | none; clients should migrate to `notifications/cancelled`, which is what every real MCP client already sends (E-09) |
| Tool authors using `ctx.cancel_requested` | unchanged, but now fires | none (behaviour change is the point) |
| `McpDispatcher.cancel(request_id)` | keeps working; `reason` is keyword-only and optional | none |
| `McpDispatcher.was_peer_cancelled()` | new method | none |
| `ctx.cancel_reason` | new read-only property returning `None` by default | none |
| Response frames for cancelled requests | a peer-cancelled request no longer produces a frame | clients that counted on `-32800` must ignore unmatched/absent responses — the spec already requires them to |
| `McpErrorCode.REQUEST_CANCELLED` | unchanged value and name | none |

There is no migration for existing users because nothing they import changes name, and the only
observable difference is that cancellation finally works. The single behavioural ## 7. Backward Compatibility

| Surface | Impact | Migration |
|---|---|---|
| Wire: `$/cancelRequest` clients | still accepted via the alias in `_cancel.py`, now logged at `WARNING` | none; clients should send `notifications/cancelled`, which every real MCP client already does (E-09) |
| Tool authors using `ctx.cancel_requested` | unchanged, but now fires | none (the behaviour change is the point) |
| `McpDispatcher.cancel(request_id)` | keeps working; `reason` is keyword-only and optional | none |
| `McpDispatcher.was_peer_cancelled()`, `ctx.cancel_reason` | new | none |
| Response frames for cancelled requests | a peer-cancelled request no longer produces one | clients must ignore unmatched/absent responses — already required of them |

No migration is needed because no imported name changes and the only observable behaviour change is
that cancellation works; the one edge — no `-32800` frame — affects exactly the case the spec already
tells clients to ignore.

---

## 8. Test Plan

### 8.1 Unit tests — `tests/unit/test_server_cancel.py`

Nine cases over `_server/_cancel.py` and `McpDispatcher.cancel`, all with a fake dispatcher:
`is_cancel_notification` accepts both names (and logs a `WARNING` for the alias) and rejects
`notifications/initialized` / `tools/call`; `cancel_request_id` reads `requestId`, falls back to `id`,
and returns `None` for `{}`, `None` and non-scalar ids; `handle_cancel` is a no-op without an id, forwards
`reason="user cancelled"` to `cancel()`, and ignores a cancel whose `_method_of` is `"initialize"`.

### 8.2 Integration tests — `tests/integration/test_notifications_cancelled.py`

Each test starts a real app on one transport and drives it with a raw client, so the notification
crosses a real socket or pipe:

```python
        pending = asyncio.create_task(ws.call("tools/call", {"name": "slow", "arguments": {}}, id=7))
        await started.wait()                        # tool is inside await asyncio.sleep(5)
        await ws.notify("notifications/cancelled", {"requestId": 7, "reason": "test"})
        await asyncio.wait_for(stopped.wait(), timeout=1.0)          # ms, not 5 s
        assert await asyncio.wait_for(pending, timeout=1.0) is None  # no response frame
```

| Test | Transport | Asserts |
|---|---|---|
| `test_ws_cancel_interrupts_in_flight_tool` | WS | tool's `finally` runs within 1 s of the cancel |
| `test_ws_cancelled_request_emits_no_response` | WS | zero text frames for the cancelled id |
| `test_stdio_cancel_interrupts_in_flight_tool` | stdio | the same, over a pipe |
| `test_streamable_cancel_interrupts_in_flight_tool` | HTTP | cancel `POST` on the same `mcp-session-id` unparkes the `tools/call` `POST` |
| `test_cancel_unknown_or_completed_request_is_silent` | WS | no frame, no exception, `cancel()` returns `False` |
| `test_legacy_cancel_request_alias_still_cancels` | WS | `$/cancelRequest` + `{"id": 7}` still stops the tool |
| `test_concurrent_requests_not_serialised` | WS | two 500 ms tools issued together finish in < 900 ms |

`test_mcp_server_ws_frame.py::TestCancelRequest` (149-181) keeps its shape — mocked dispatcher, assert
`cancel()` called — with the method string and key changed to `notifications/cancelled` / `requestId`.

---

## 9. Open Questions

1. **Drop the `id` alias how soon?** This PRD accepts `params.id` for one minor release. Confirm 1.2.0
   as the removal point.
2. **Should the alias `WARNING` be rate-limited, and should `_frame_tasks` be capped?** Per-frame tasks
   are unbounded by design today; back-pressure may belong here or in a follow-up.
3. **Client-side cancel.** `McpClient` has no cancellation method (§3). Does it belong in this release,
   given the client can already `Task.cancel()` its own await?
4. **Tracing.** Should a cancel mark the span `cancelled=true` rather than leave it an error span?
5. **Normative wording and session lifetime.** Re-read the normative strength of "the server must not
   respond to a cancelled request" against the `2025-11-25` revision before §4.5 ships (E-08 covers only
   method *presence* in `2024-11-05`), and decide whether a parked `POST` that returns an empty event
   stream closes the `mcp-session-id` or keeps it. Current lean: keep it.

---

## 10. lauren-mcp Advantages

The cooperative half of cancellation is already built and correctly ordered: `cancel_requested` exi## 10. lauren-mcp Advantages

The cooperative half of cancellation is already built and correctly ordered: `cancel_requested` exists
on `McpToolContext` (`_context.py:321`), the dispatcher sets it before `task.cancel()`
(`_dispatcher.py:176-189`), and tools receive it by dependency injection, not by importing a global. A
"just use the official SDK" rewrite would have to reconstruct that: the SDK hands you a request handle,
not a DI-injected context, so a Lauren tool would lose the `@mcp_tool` + `ctx.cancel_requested` pairing
that makes cancellation a two-line change in application code. The fix is
dependency-free (`asyncio` task tracking and one `asyncio.Lock`, two-dependency posture intact, E-222)
and is a **local** conformance bug confined to six files, with
`test_cancel_signal_integration.py:78` already proving the dispatcher half works. The genuine weakness,
stated plainly: the user-facing surface was designed correctly and then never wired, so for one release
the documentation promised behaviour the server did not have.

---
## 11. References


* **E-08** — `notifications/cancelled` is a literal in `schema/2024-11-05/schema.ts`; the method predates
  every "legacy era" question.
* **E-09** — `$/cancelRequest` has zero occurrences in the `modelcontextprotocol` organisation.
* **E-237** — `grep -ril 'notifications/cancelled' src/ \| wc -l` → **0** (cancellation unimplemented).
* **E-240** — `$/cancelRequest`: 6 files, 9 hits, 4 executable (`_ws.py:39`, `_ws.py:296`,
  `_streamable.py:212`, `_stdio.py:76`).
* **E-222** two-dependency posture (`lauren`, `anyio`), preserved here; **E-235** `tasks/` → 0 hits, so
  task-augmented cancellation is out of scope.
* **N-02** `$/cancelRequest` is not an MCP method, it is an LSP name; **N-09** `lauren-mcp` implements
  `notifications/cancelled` in neither direction.
* **C-01** — `$/cancelRequest` never was an MCP method: a bug-fix PRD, not migration work.
* **C-03** — the citation count was understated to 5 files; five of the nine hits are comments.
* `_research/lauren-mcp-inventory.md` §5.4 and §13; MCP spec, "Cancellation", `2024-11-05`.
