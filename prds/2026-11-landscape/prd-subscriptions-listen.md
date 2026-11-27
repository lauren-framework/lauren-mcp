# PRD — Multiplexed change notifications via `subscriptions/listen`

**Status:** Draft  
**Date:** 2026-11-26  
**Scope:** `_server/_subscriptions.py`, `_server/_listen.py` (new), `_server/_streamable.py`, `_server/_dispatcher.py`, `_types.py`, `server/_module.py`, `_client/_base_remote.py`  
**Priority:** P2  
**Issue:** [#71](https://github.com/lauren-framework/lauren-mcp/issues/71)

---

## 1. Problem Statement

`2026-07-28` replaces **both** push channels we ship today — the Streamable HTTP GET stream and
`resources/subscribe` / `resources/unsubscribe` — with one long-lived POST-response stream opened by
`subscriptions/listen` (E-23, `EVIDENCE.md:89`; MUST, `VERSIONS-MATRIX.md:69`). We implement both
mechanisms it replaces and nothing resembling the replacement: `subscriptions/listen` has **0 file
hits** in this tree (E-231, `EVIDENCE.md:416`).

### 1.1 The only push channel a modern peer could use disables itself in modern mode

```python
# src/lauren_mcp/_server/_streamable.py:458-462
        @get("/")
        async def handle_get(self, request: Request) -> Response | EventStream:
            if stateless:
                return Response(
                    body=json.dumps({"error": "GET is not supported in stateless mode"}).encode(),
```

The GET channel is the only way a client learns a resource changed without polling, and it shuts itself
off in stateless mode — the mode `2026-07-28` mandates, because sessions are removed (E-20). The
subscription half is narrower: `resources/subscribe` refuses to register unless the transport supplied a
`send_notification` callable, raising `ValueError("resources/subscribe requires a push-capable
transport")` (`server/_module.py:479-493`). Resource changes, tool-list invalidation and log forwarding
therefore have no single path to open.

### 1.2 Two unconnected push paths, one of them unbounded

`ResourceSubscriptionManager` is a singleton whose `_subscriptions: dict[str, dict[str, SendFn]]` maps a URI
to the connections that asked for it (`_server/_subscriptions.py:28-30`), fanning out with
`asyncio.gather(..., return_exceptions=True)` (`:69-72`). The Streamable transport has a *second*,
independent push path — an **unbounded** per-session queue:

`push_queue: asyncio.Queue[str | None] = field(default_factory=asyncio.Queue)`
(`_streamable.py:54-55`). A client that opens the GET channel and stops reading accumulates every frame
generated for it, forever, with no sequence number to tell it anything was missed. Adding
`subscriptions/listen` naively would make that a **third** push path with a third map of who wants what.

### 1.3 Why P2

A modern host degrades silently without this: it keeps working, by re-reading, and pays in latency and
tokens — the P2 test is *absence costs features, not interop*. Eleven of twelve SDKs measured ship surface
for it (TS 71 file hits, Python 197 — E-80/E-81, `EVIDENCE.md:173-174`), so it becomes interop the day we
advertise `2026-07-28`, which we do not yet do.

---

## 2. Goals

1. `subscriptions/listen` is answered on Streamable HTTP with `Content-Type: text/event-stream`: first a
   frame that is an ordinary JSON-RPC **result** for the request id, then notification frames, then EOF —
   exactly one response object per request id, always.
2. One stream carries many subscriptions — resource URIs, `tools|resources|prompts/list` collection
   changes, log messages — each frame tagged with stream id and a per-stream sequence number.
3. Exactly one in-process registry owns "who listens to what": the legacy notifier and every listen
   stream are **two sinks over one hub**, `notify_updated(uri)` becomes
   `hub.publish(ResourceChanged(uri))`, and today's legacy bytes stay byte-identical.
4. Every listen queue is bounded (`queue_frames`, `queue_bytes`) with a documented drop policy
   (`drop_oldest` default, `close` for content streams), and a client can infer loss from a `seq` gap.
5. Ordering claims are exact: per-`(kind, key)` publish order is preserved; there is no global,
   cross-process, or response-relative order.
6. After `prd-result-envelope-caching.md` lands, a change frame invalidates the matching cached result
   regardless of remaining `ttlMs`, and a `cacheSeq` stamp kills the in-flight-response race.
7. Losing SSE resumability (E-28) costs no correctness: the stream is level-triggered, so resubscribing
   re-emits one synthetic change per accepted subscription. No event ids, no `Last-Event-ID` here.
8. Legacy peers see no change: `resources/subscribe`, the GET channel, `notifications/resources/updated`
   and the event store keep working (E-41, ≥12-month window).

### Acceptance checklist

- [ ] `grep -ril 'subscriptions/listen' src/lauren_mcp --include=*.py | wc -l` ≥ `1` (today `0`, E-231).
- [ ] `grep -c 'text/event-stream' src/lauren_mcp/_server/_listen.py` ≥ `1`.
- [ ] `grep -n 'maxsize' src/lauren_mcp/_server/_listen.py` shows a bounded queue (`_streamable.py:55` is not).
- [ ] `git grep -n 'id=eid' -- src/lauren_mcp/_server/` matches only `_streamable.py:495`;
      `grep -c 'id=' src/lauren_mcp/_server/_listen.py` returns `0`.
- [ ] `pytest tests/unit/test_subscriptions_listen.py tests/integration/test_subscriptions_listen_integration.py -q` passes.
- [ ] `pytest tests/integration/test_resource_subscriptions_integration.py -q` passes with an unchanged
      assertion count (legacy bytes unchanged); `pytest tests/unit/test_event_store.py -q` passes.
- [ ] `python -c "from lauren_mcp._server._listen import ListenConfig as C; assert C().queue_frames==256"` exits 0.
- [ ] `git diff --stat pyproject.toml` is empty (no new runtime dependency).

---

## 3. Non-Goals

- **Removing the legacy mechanisms.** GET channel, `resources/subscribe`,
  `notifications/resources/updated` and `InMemoryEventStore` stay for the window (E-41).
- **Wiring the event store into the listen stream.** Deliberate (§4.8): resumption is replaced by
  re-snapshot, not replay.
- **A cross-process subscription bus.** The hub is in-process, like every other server singleton here.
- **Server→client requests on the stream.** `2026-07-28` moves those to MRTR
  (`prd-mrtr-input-required.md`); this stream is one-directional notifications, and there is no
  `subscriptions/unsubscribe` method — per stream, unsubscribing is ending the stream.
- **New error codes.** We reuse `McpErrorCode` (`_types.py:111-121`); the reserved `-32020` range stays
  unused (`spec.md:316`).

---

## lauren-mcp Advantages

This is a **multiplexer over infrastructure that already exists**, not a new subsystem.

Three expensive parts are already here. (a) A change registry keyed by URI with per-connection send
functions, already tested (`_server/_subscriptions.py`,
`tests/integration/test_resource_subscriptions_integration.py`). (b) A connection registry that fans out to
every live transport — stdio, WS, SSE, Streamable — through one `broadcast` (`_server/_registry.py:32-37`,
`:47`), so a change raised in a tool handler reaches a listener on any transport without the handler
knowing a transport exists. (c) SSE plumbing (`lauren.sse.EventStream`, imported at `_streamable.py:14`)
and a bounded-replay event store (`_event_store.py:61-74`), so framing is a variation on
`_streamable.py:484-513`, not a from-scratch SSE stack.

Concretely: **zero new runtime dependencies** (`asyncio.Queue`, `json`, the `lauren.sse` types we already
import); **one registry, not two**, so the channels cannot drift in content or timing; **DI-native**,
because the hub is a server singleton like `McpDispatcher` and `McpConnectionRegistry`, injected through the
existing context machinery rather than reachable only as a module global.

What we do **not** get free: multiplexing policy (coalescing, drop, `seq` stamping), level-triggered
snapshot semantics and the `ttlMs`/`cacheSeq` interaction — §4, roughly 500 lines.

---

## 4. Design

### 4.1 Wire shape: one POST, one stream, N subscriptions

`subscriptions/listen` is a request (has `id`) posted to the normal MCP endpoint; the response is an SSE
stream that stays open.

```json
{"jsonrpc":"2.0","id":7,"method":"subscriptions/listen","params":{
  "subscriptions":[
    {"type":"resource","uri":"memo://notes/1"},
    {"type":"list","method":"tools/list"},
    {"type":"log","minLevel":"warning"}],
  "snapshot":true,"coalesceMs":0}}
```

`subscriptions` holds 1…`max_subscriptions` (64) entries of `{type, uri|method|minLevel}`; `type` is
`resource` | `list` | `log`, `list` takes one of `tools/list`/`resources/list`/`prompts/list`, `log` takes
`debug|info|warning|error`. Empty or over-long → `-32602`. `snapshot` defaults to `true` (§4.8);
`coalesceMs` defaults to `0` and sets the per-`(type, key)` merge window.

The **first frame** is the response — `{"jsonrpc":"2.0","id":7,"result":{"resultType":"subscriptions_listen",
"streamId":"s-3f2a91","accepted":[0,1,2],"rejected":[],"ttlMs":0,"cacheScope":"private"}}` — so a peer that
only understands request/response gets a sane answer and closes. `accepted`/`rejected` are per entry, so
one bad entry does not kill the stream; if *no* entry is acceptable the first frame is `-32602` with
`data.index` and the stream closes at once. `resultType`, `ttlMs` and `cacheScope` belong to
`prd-result-envelope-caching.md`; this PRD only fixes their values here.

### 4.2 Framing and multiplexing

Every later frame is a JSON-RPC notification on the default SSE event:
`event: message` / `data: {"jsonrpc":"2.0","method":"notifications/resources/updated","params":{"uri":"…",
"_meta":{"lauren/listen":{"streamId":"s-3f2a91","seq":12}}}}`. Three rules make the stream fan-out-able:

1. **Method names are the legacy names.** `resource` → `notifications/resources/updated` with the same
   `params.uri` the legacy notifier emits (`_subscriptions.py:63-68`); `list` →
   `notifications/{tools,resources,prompts}/list_changed`; `log` → `notifications/message`. A client that
   handles the legacy methods needs no new handler, only a new transport.
2. **Stream identity rides in `_meta`** — `params._meta["lauren/listen"] = {"streamId", "seq"}`; additive
   `_meta` is the only channel-neutral place for it.
3. **No `id:` SSE field, ever.** The GET generator emits `id=eid` today (`_streamable.py:495`, `:505-507`);
   listen must not, because `Last-Event-ID` replay is gone (E-28) and an event id a client cannot resume
   from is a lie it will act on (§4.8).

`coalesceMs > 0` merges repeated frames for the same `(type, key)` in the window keeping the highest `seq`.

### 4.3 Termination and cancellation

| Trigger | Client sees |
|---|---|
| Client closes/aborts the POST (generator `finally`, `_streamable.py:509-513`) | EOF |
| `notifications/cancelled` naming the listen id | `event: end` `{"reason":"cancelled"}`, EOF |
| Server shutdown or session delete — same discipline as `push_queue.put_nowait(None)` (`_streamable.py:82`) | `event: end` `{"reason":"server_shutdown"}`, EOF |
| Idle for `listen_idle_timeout_s` (300) | `event: end` `{"reason":"idle_timeout","retryAfterMs":0}`, EOF |
| Overflow under `drop_policy="close"` (§4.4) | `event: end` `{"reason":"overflow","dropped":N}`, EOF |

`event: end` is informational: a client that ignores unknown event names still sees EOF, and EOF is always
end-of-stream. It is the only non-`message` event name here.

### 4.4 Backpressure and slow consumers

```python
# src/lauren_mcp/_server/_listen.py (new)
@dataclass(frozen=True, slots=True)
class ListenConfig:
    queue_frames: int = 256           # frames buffered per stream
    queue_bytes: int = 1_048_576      # hard byte ceiling per stream
    drop_policy: str = "drop_oldest"  # "drop_oldest" | "close"
    max_subscriptions: int = 64
    coalesce_ms: int = 0
    idle_timeout_s: float = 300.0
    snapshot: bool = True
```

Each `_ListenStream` owns `asyncio.Queue(maxsize=config.queue_frames)` plus a byte counter; `offer()`, called
from `publish()` and never awaiting, evicts or closes when either bound would be exceeded and records the
loss in `_dropped`.

**`drop_oldest` (default)** evicts the head and keeps the newest. Safe because `resource` and `list` frames
are hints — the reaction is "re-read the authoritative thing", idempotent and order-insensitive per key, so
dropping an older hint whose newer hint is already queued loses nothing. **`close`** ends the stream
instead, and is forced for `log` subscriptions: a log line is content, not a hint, so silently dropping it
is a correctness bug rather than a policy choice.

**What a client can infer.** `seq` is per-stream and strictly increasing, so a jump from 12 to 20 says
frames 13–19 were coalesced or dropped, and how many; the next delivered frame carries
`_meta["lauren/listen"]["dropped"]` with the cumulative count, distinguishing coalescing from loss, and
`dropped > 0` means "refetch rather than trust local deltas". There is no ack and no retransmission: that
is what resumability would have given, and it is gone (E-28). `push_queue` (`_streamable.py:55`) stays
unbounded here — changing it would change legacy semantics — but listen traffic never touches it.

### 4.5 One registry, two sinks

One `SubscriptionHub` owns every subscription in the process; the legacy notifier and each listen stream
are **sinks** on it.

```python
# src/lauren_mcp/_server/_listen.py (new)

@dataclass(frozen=True, slots=True)
class ChangeEvent:
    kind: str      # "resource" | "list" | "log"
    key: str       # uri, or "tools/list", or logger name
    payload: dict  # notification params, minus _meta

class SubscriptionHub:
    async def publish(self, event: ChangeEvent) -> int:
        async with self._lock:                 # no awaits inside: append order == publish order
            self._seq += 1
            for stream in list(self._streams.values()):
                stream.offer(event, self._seq)
            legacy = self._legacy.get(event.key, {}) if event.kind == "resource" else {}
        if legacy:
            await _fan_out_legacy(legacy, event.payload)   # byte-identical legacy fan-out
        return self._seq
```

`_legacy` is today's `dict[str, dict[str, SendFn]]` moved wholesale from `_subscriptions.py:30`;
`_streams` maps `streamId` to a `_ListenStream`. `ResourceSubscriptionManager` keeps its four public
methods and becomes a thin adapter — `notify_updated` becomes a single
`await self._hub.publish(ChangeEvent(kind="resource", key=uri, payload={"uri": uri}))`
(`_server/_subscriptions.py`, modified, ~30 lines).

Every existing caller is unchanged, but its change now reaches listen streams too: no code path can notify
a legacy subscriber without notifying listen subscribers, and there is no second registry to keep in sync.
The list and log taps are one line each — `McpCatalogManager` mutation points publish `list` events, and
the logging handler behind `notifications/message` publishes `log` events.

### 4.6 Ordering: exactly what we guarantee

| Claim | Status |
|---|---|
| Same `(kind, key)`: publish order | **Guaranteed** — appended inside one lock, no awaits in the critical section. |
| `seq` strictly increasing per stream | **Guaranteed** — assigned under the same lock. |
| Different keys, or global order across tasks | **Not guaranteed** — only lock-acquisition order, and only until `coalesceMs > 0` or a drop occurs. |
| Order vs. concurrent POST responses | **Not guaranteed** — a `resources/read` response can be built before a change and delivered after its frame; §4.7 neutralises this. |
| Cross-process or cross-transport order | **Does not exist / not guaranteed** — the hub is per-process (§9, Q3), and a legacy WS subscriber and an HTTP listener see the same events in their own local order. |

Nothing else is ordered, and nothing else needs to be. Today it is strictly worse: `notify_updated` gathers
over a dict of send functions (`_subscriptions.py:69-72`), so concurrent calls interleave arbitrarily.

### 4.7 `ttlMs` / `cacheScope`: invalidation, and a race

Neither field exists here today (E-233, E-234 — both 0 file hits, `EVIDENCE.md:418-419`). Once
`prd-result-envelope-caching.md` lands, list and read results carry a TTL and a client may serve them
without asking us, which makes the listen stream the **only** thing that can tell a client its cache is
wrong.

The hazard: a `tools/list` request is in flight; the server assembles the list, a tool is registered,
`publish()` writes the frame, then the *older* list response arrives. The client caches stale data and has
already consumed the invalidation, which had a lower `seq`. The fix is a stamp on results, not on frames —
cacheable results gain `_meta["lauren/cacheSeq"] = hub.seq_at_snapshot()` in `_server/_envelope.py` (owned
by the caching PRD). Then:

1. **Invalidation beats TTL** — a change frame invalidates the matching result immediately, whatever
   `ttlMs` says remains. `ttlMs` bounds usefulness, it does not promise currency.
2. **`cacheSeq` is the tie-breaker** — apply an invalidation only if `frame seq > cached.cacheSeq`; an
   invalidation older than the snapshot it would invalidate is a no-op (the case above).
3. **`cacheScope` decides reach** — `"private"` results are invalidated by the owner's own stream,
   `"global"` by any listener's frame. The listen result itself is never cacheable (`ttlMs: 0`).
4. **A `seq` gap forces a refetch** regardless of `ttlMs`, because the client cannot know which keys
   changed.

`seq` is the only ordering token that survives the notification/response race.

### 4.8 Why losing SSE resumability (E-28) does not cost correctness

Today a broken push connection is recoverable: the GET generator reads `last-event-id`
(`_streamable.py:476`), calls `event_store.replay_events_after(session.session_id, last_event_id, ...)` and
re-yields each stored event with its `id` (`:486-495`), backed by `InMemoryEventStore`
(`max_events` 1000, `_event_store.py:61-74`). `2026-07-28` removes that (E-28, `EVIDENCE.md:94`): a listen
stream that breaks loses every frame in the gap, permanently — qualitatively different from today's
channel, which is at-most-once with *detectable* gaps because event ids encode stream identity
(`session.session_id:counter`, `_streamable.py:505-507`).

The design answer is to make the loss irrelevant:

1. **`snapshot: true` by default** — right after the result frame the server emits one synthetic change
   frame per accepted subscription, stamped with the current `seq`. A freshly (re)subscribed client is
   told "everything you asked about may have changed; go look" and need not know what it missed.
2. **Hints, not deltas** — every frame means "re-read key K", so the union of missed frames is
   approximated exactly by "re-read every subscribed key".
3. **No `id:`, no resume header, no writes to `EventStore` on this path** — an event id we cannot honour is
   a protocol lie, and a stream that half-supports resumption is worse than one that claims none.
4. **The cost is bandwidth, not correctness.** `snapshot: false` serves clients that track their own
   freshness, at the price of staleness until the next real change.

E-28 turns a *recovery* problem into a *convergence* problem, and convergence is cheap when the stream is
level-triggered. Modelled as edge-triggered deltas (as the GET channel effectively is), E-28 would make
listen unimplementable for correctness — the trap this design avoids.

### 4.9 Coexistence with legacy per-resource subscriptions

Selection is by negotiated protocol version, not configuration:

| Negotiated version | `resources/subscribe` | GET channel | `subscriptions/listen` |
|---|---|---|---|
| `2024-11-05` … `2025-11-25` | served (`server/_module.py:479-500`) | served (`_streamable.py:458-521`) | `-32601` |
| `2026-07-28` | served during the window (E-41) | 405 `{"error":"GET is not supported for 2026-07-28 peers"}` | served |

Gating lives where the version is decided: `negotiate_version` (`_server/_handshake.py:23-26`) returns the
client's version when supported, else `LATEST`; `LATEST` is `"2025-11-25"` and `SUPPORTED` lacks
`"2026-07-28"` (`_mcp_version.py:5-7`), so this PRD depends on `prd-dual-era-protocol-core.md` and adds no
version logic. The legacy handler stays registered because a mixed fleet exists through the window, and
because a `2026-07-28` peer over WS (`_TRANSPORTS` includes `"ws"`, `server/_module.py:55`) still has a
legacy-style push channel we must not break.

The one thing we must prove is that legacy bytes do not change: today's payload is
`notifications/resources/updated` with `params: {"uri": uri}` (`_subscriptions.py:63-68`), and after this
PRD `_fan_out_legacy` must reproduce it **byte-identically** — no `_meta`, no `seq`.

---

## 5. Server-side and Client-side Changes

**Server.** New `_server/_listen.py` (`ChangeEvent`, `SubscriptionHub`, `ListenConfig`, `_ListenStream`,
`handle_listen`); `_server/_subscriptions.py` becomes an adapter over the hub; `_server/_streamable.py` gains
a POST branch routing `subscriptions/listen` to an SSE `EventStream` plus the `2026-07-28` GET rejection;
`server/_module.py` registers and advertises it; `_types.py` gains `ListenRequest`/`ListenResult` and a
`subscriptions` capability. `_server/_dispatcher.py` needs a second registration kind, because `dispatch`
returns one `JsonRpcResponse | JsonRpcErrorResponse` (`_dispatcher.py:101`) while listen returns a first
response *and* a frame iterator.

**Client.** `_client/_base_remote.py` gains `listen()` (§6.7) returning an async iterator over
`ChangeEvent` with `snapshot`/`coalesce_ms` knobs.

```python
# src/lauren_mcp/_server/_dispatcher.py (modified)
    def register_stream(self, method: str, handler: StreamHandler) -> None:
        """Register *handler* for *method*: one JSON-RPC response, then a frame iterator."""
        self._stream_handlers[method] = handler
```

---

## 6. Exact Lines to Change

### 6.1 `src/lauren_mcp/_server/_subscriptions.py`

| `path:line` | Current | Change |
|---|---|---|
| `_server/_subscriptions.py:19-30` | `class ResourceSubscriptionManager:` owning `self._subscriptions: dict[str, dict[str, SendFn]]` | Takes an optional `SubscriptionHub`; the map moves to `hub._legacy`; the four public methods stay. |
| `_server/_subscriptions.py:32` | `def subscribe(self, uri: str, session_key: str, send_fn: SendFn) -> None:` | Delegates to `hub.subscribe_legacy(...)`. |
| `_server/_subscriptions.py:58-79` | `notify_updated` builds the JSON and gathers over subscribers | One `hub.publish(...)`; the JSON at `:63-68` and the gather at `:69-72` move verbatim into `_fan_out_legacy`. |

### 6.2 `src/lauren_mcp/_server/_streamable.py`

| `path:line` | Current | Change |
|---|---|---|
| `_streamable.py:55` | `push_queue: asyncio.Queue[str \| None] = field(default_factory=asyncio.Queue)` | Unchanged (legacy); comment pointing at the bounded listen queue. |
| `_streamable.py:167-168` | `@post("/")` → `async def handle_post(...)` | Route `subscriptions/listen` from a `2026-07-28` peer to `_listen.handle_listen`. |
| `_streamable.py:458-462` | `@get("/")` rejecting only `stateless` | Also reject `2026-07-28` peers with 405. |
| `_streamable.py:476`, `:495`, `:505-507` | `last_event_id` read; `id=eid`; `eid = f"{session.session_id}:{session.next_event_id}"` | Unchanged — legacy GET only; the listen generator must not copy them. |

### 6.3 `src/lauren_mcp/_server/_event_store.py`

No change. `class InMemoryEventStore(EventStore)` with `max_events: int = 1000` (`:61-74`) stays wired to
the GET channel only; its bound is not reused as the listen queue bound, so the two knobs stay
independently tunable. |

### 6.4 `src/lauren_mcp/_server/_dispatcher.py`

| `path:line` | Change |
|---|---|
| `_dispatcher.py:71` (`self._in_flight`) | Add `self._stream_handlers: dict[str, StreamHandler] = {}` alongside. |
| `_dispatcher.py:93` (`def register(...)`) | Unchanged; new sibling `register_stream` (§5). |
| `_dispatcher.py:101` (`async def dispatch(...)`) | Add `open_stream(...) -> tuple[Response, AsyncIterator[str] \| None]`; the request/response signature stays for every non-stream method. |
| `_dispatcher.py:24` (`McpInvalidParamsError`) | Reused for per-entry rejections; no new exception type. |

### 6.5 `src/lauren_mcp/_types.py`

| `path:line` | Change |
|---|---|
| `_types.py:111-121` (`McpErrorCode`) | Unchanged; listen reuses `INVALID_PARAMS = -32602` and `REQUEST_CANCELLED = -32800`, no reserved-range codes. |
| `_types.py:139-147` (`ServerCapabilities`) | Add `subscriptions: dict[str, Any] \| None = None`, and `ListenRequest`/`ListenResult` after it. |

### 6.6 `src/lauren_mcp/server/_module.py`

| `path:line` | Change |
|---|---|
| `server/_module.py:233-237` (`ServerCapabilities(...)`) | Add `subscriptions={"listen": True}` when `resources` is present — the stream also carries `resources/list_changed`. |
| `server/_module.py:479-500` (`resources/subscribe`/`unsubscribe`) | Unchanged except that the manager they talk to is hub-backed. |
| `server/_module.py:20` (`ResourceSubscriptionManager` import) | Add `_listen` imports and `dispatcher.register_stream("subscriptions/listen", ...)` beside the existing `resources/subscribe` registration. |

### 6.7 `src/lauren_mcp/_client/_base_remote.py`

New method (no existing line to modify):
`def listen(self, *, subscriptions: list[dict], snapshot: bool = True, coalesce_ms: int = 0) -> AsyncIterator[ChangeEvent]`
— POST, parse frame 1 as the result (raise on an error frame), iterate `data:` lines, stop at `event: end`
or EOF, surface `dropped`.

---

## 7. Backward Compatibility

**Legacy peers: nothing changes, byte for byte**, provided they did not negotiate `2026-07-28`. The hub
refactor is invisible on the wire: the same JSON comes out of `ChangeEvent.payload`, and the same
`gather(..., return_exceptions=True)` swallows the same failures.

**One deliberate, version-gated change:** a `2026-07-28` peer calling `GET /` gets `405` with a JSON body
instead of a stream — that peer is the one the revision tells to use `subscriptions/listen`, so the 405 is
how it discovers the channel moved. No existing peer negotiates that version.

**Existing users: no migration.** `@mcp_tool` bodies, resource handlers, `mcp_server(...)` kwargs and
transport choices are untouched. The legacy mechanisms stay for the ≥12-month window (E-41,
`EVIDENCE.md:110`); retiring them is a later PRD's call.

---

## 8. Test Plan

### 8.1 Unit tests — `tests/unit/test_subscriptions_listen.py`

`test_hub_publish_reaches_legacy_and_listen` ·
`test_per_key_order_preserved` · `test_seq_strictly_increasing_per_stream` · `test_queue_bound_drops_oldest` ·
`test_queue_bytes_enforced` · `test_log_subscription_forces_close_policy` ·
`test_rejected_entries_do_not_fail_request` ·
 `test_too_many_subscriptions` ·
`test_snapshot_emits_one_frame_per_subscription` · `test_snapshot_false_emits_nothing` ·
`test_coalesce_ms_merges_same_key` ·
`test_cancel_notification_ends_stream` · `test_idle_timeout_ends_stream` ·
`test_legacy_payload_bytes_unchanged` · `test_no_event_id_fields` ·
`test_listen_config_defaults`.

### 8.2 Integration tests — `tests/integration/test_subscriptions_listen_integration.py`

`test_listen_stream_lifecycle` · `test_two_subscriptions_one_stream` · `test_client_disconnect_unsubscribes` ·
`test_legacy_subscribe_unchanged_alongside_listen` ·
`test_get_rejected_for_modern_peer`, `test_get_still_works_for_legacy_peer`, and
`test_slow_consumer_does_not_grow_memory` · `test_resubscribe_after_break_converges` ·
`test_listen_result_is_not_cacheable`.

---

## 9. Open Questions

1. **Log overflow signalling.** `close` is forced for `log` subscriptions but the client cannot see which
   type forced it; proposal: per-entry `"overflowPolicy":"close"` in the result frame.
2. **In-stream subscription mutation.** Adding a URI means a second stream; a client→server
   `notifications/subscriptions/update` frame would avoid it but is unbacked. Default: do not add it.
3. **Multi-process fan-out.** With `uvicorn --workers 4` each worker has its own `_seq` and streams, so a
   change in worker 1 never reaches a listener on worker 2. Out of scope, but it must be documented in the
   deployment guide or it will be filed as a bug.
4. **`snapshot` default for resource-heavy servers.** `true` is correct but expensive at 200+
   subscriptions; consider making it adaptive once `cacheSeq` exists.
5. **Exact spec field names.** E-23 records the replacement and `VERSIONS-MATRIX.md:69` marks it MUST, but
   the research corpus does not pin the parameter object at field level. The names in §4.1 are **this
   PRD's proposal** and must be verified against the published pattern page before implementation; if the
   page differs, the page wins and §4.1 is amended.

---

## 10. References

Evidence (`prds/2026-11-landscape/EVIDENCE.md`): **E-23** (listen replaces the GET channel and per-resource
subscribe — `:89`) · **E-28** (SSE resumability removed — `:94`) · **E-41** (≥12-month window — `:110`) ·
**E-80/E-81** (TS 2.4.0 71 hits, Python 2.3.0 197 — `:173-174`) · **E-20** (sessions removed — `:86`) ·
**E-231** (0 hits here — `:416`) · **E-233/E-234** (`ttlMs`/`cacheScope` both 0 — `:418-419`) · **E-244**
(`Last-Event-ID`, 2 files, removed by `2026-07-28` — `:433`).

Matrices: `VERSIONS-MATRIX.md:65` (header), `:69` (listen MUST; TS 71, Py 197, …, lauren-mcp **0**) ·
`_research/spec.md:100` (absent from `2025-11-25`), `:251` (break row 4, SEP-2575), `:208` (event ids encode
stream identity, superseded), `:316` (reserved `-32020` unused here).

Repository: `_server/_subscriptions.py:19-30,32,58-79` · `_server/_streamable.py:14,43,54-55,79-82,167-168,
458-462,476,486-495,505-507,509-513` · `_server/_event_store.py:61-74` · `_server/_dispatcher.py:24,71,93,101`
· `_server/_registry.py:32-37,47` · `_server/_handshake.py:23-26` · `_mcp_version.py:5-7` ·
`_types.py:111-121,139-147` · `server/_module.py:20,55,233-237,479-500`.

Upstream: https://modelcontextprotocol.io/specification/2026-07-28/basic/patterns/subscriptions (E-23); the
removal of SSE resumability is in the `2026-07-28` changelog (E-28).
