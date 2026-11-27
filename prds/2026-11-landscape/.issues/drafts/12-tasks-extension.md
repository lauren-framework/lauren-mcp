**PRD:** [`prd-tasks-extension.md`](https://github.com/lauren-framework/lauren-mcp/blob/docs/mcp-landscape-2026-11/prds/2026-11-landscape/prd-tasks-extension.md)
**Priority:** P2 — An eight-minute tool runs inside one JSON-RPC request with nowhere to report progress and no task handle
**Theme:** Notifications
**Key evidence:** E-25, E-53, E-30 — see `EVIDENCE.md` in the same directory.

## Problem

`lauren-mcp` executes a `tools/call` inside one JSON-RPC request. The handler runs on the
event loop as an `asyncio.Task` and the request stays open until it returns
(`src/lauren_mcp/_server/_dispatcher.py:124`), then the tool layer builds the single
response envelope `{"content": ..., "isError": ...}`
(`src/lauren_mcp/server/_handlers.py:670`). That is the entire long-running-call story
here: block, stream progress notifications if the client asked for them
(`src/lauren_mcp/_server/_context.py:346`), hope the transport survives.

A `reindex_repository` tool scanning 40k files therefore dies twice: the transport times
out and the `asyncio.Task` keeps running in `_in_flight` (`_dispatcher.py:71`) where no
client will ever read its result; then the client reconnects and calls the tool again,
starting a second full scan, because `2026-07-28` removed sessions and the server cannot
correlate the retry with the in-flight work (`_research/spec.md:389-396`: state is
per-request, and *any durable state becomes an explicit state handle*).

## Goals

1. Add `extensions` to both capability objects and serialise it on the parse path
   (`_module.py:369-372`) and the emit path (`_module.py:388-405`), so a declared extension
   actually reaches the wire.
2. Add a minimal registry: declare local extensions, record peer declarations, answer
   `is_negotiated(id)`, and say which extension owns a method.
3. Implement `io.modelcontextprotocol/tasks` server-side: `tasks/get`, `tasks/list`,
   `tasks/cancel`, plus creation via `tools/call`.
4. Let a tool be task-capable via `@mcp_tool(task=True)` or by returning a `TaskHandle`;
   no new runtime dependency (E-222).
5. Degrade to today's synchronous response when the client did not negotiate, with no
   behavioural change and no broken envelope.
6. State the durability promise honestly, and expose the `TaskStore` seam that lets an
   operator buy more.
7. Answer unnegotiated extension methods with an error that tells "not supported" from
   "typo".

## Acceptance criteria



---

Drafted from the 2026-11 MCP landscape review (evidence retrieved 2026-11-26). Full PRD, evidence register (`EVIDENCE.md`) and `VERSIONS-MATRIX.md` live in `prds/2026-11-landscape/` on branch `docs/mcp-landscape-2026-11`.
