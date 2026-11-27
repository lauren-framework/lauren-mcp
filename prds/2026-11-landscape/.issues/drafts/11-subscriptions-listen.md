**PRD:** [`prd-subscriptions-listen.md`](https://github.com/lauren-framework/lauren-mcp/blob/docs/mcp-landscape-2026-11/prds/2026-11-landscape/prd-subscriptions-listen.md)
**Priority:** P2 — The GET stream and `resources/subscribe` are legacy-era; the modern era replaces both with `subscriptions/listen`
**Theme:** Notifications
**Key evidence:** E-23, E-28, E-41 — see `EVIDENCE.md` in the same directory.

## Problem

`2026-07-28` replaces **both** push channels we ship today — the Streamable HTTP GET stream and
`resources/subscribe` / `resources/unsubscribe` — with one long-lived POST-response stream opened by
`subscriptions/listen` (E-23, `EVIDENCE.md:89`; MUST, `VERSIONS-MATRIX.md:69`). We implement both
mechanisms it replaces and nothing resembling the replacement: `subscriptions/listen` has **0 file
hits** in this tree (E-231, `EVIDENCE.md:416`).

```python
# src/lauren_mcp/_server/_streamable.py:458-462
        @get("/")
        async def handle_get(self, request: Request) -> Response | EventStream:
            if stateless:
                return Response(
                    body=json.dumps({"error": "GET is not supported in stateless mode"}).encode(),
```

## Goals

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

## Acceptance criteria

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

Drafted from the 2026-11 MCP landscape review (evidence retrieved 2026-11-26). Full PRD, evidence register (`EVIDENCE.md`) and `VERSIONS-MATRIX.md` live in `prds/2026-11-landscape/` on branch `docs/mcp-landscape-2026-11`.
