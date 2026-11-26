# PRD — Tasks extension and the generic extension negotiation it rides on

**Status:** Draft
**Date:** 2026-11-26
**Scope:** `_types.py` (capability maps), new `_extensions.py`, new `_server/_tasks.py`, `_server/_dispatcher.py`, `_server/_context.py`, `server/_handlers.py`, `server/_module.py`, `server/_decorators.py`
**Priority:** P2
**Issue:** _pending_

---

## 1. Problem Statement

### 1.1 A tool that takes eight minutes has nowhere to report progress

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

The revision's answer is **tasks**: the server may answer `tools/call` with a task handle,
and the client polls `tasks/get` until the task reaches a terminal state. Tasks are no
longer core — SEP-2663 moved them into the extension `io.modelcontextprotocol/tasks`
(`_research/spec.md:253`, `:358`, E-25).

### 1.2 There is no way to negotiate *any* extension

This repo has **0 hits** for `tasks/` (E-235; `grep -ril 'tasks/' src/ | wc -l` → `0`),
but that is a symptom. The defect is structural: neither capability object has an
`extensions` field.

```python
# src/lauren_mcp/_types.py:128-135
@dataclass
class ClientCapabilities:
    roots: dict[str, Any] | None = None
    sampling: dict[str, Any] | None = None
    elicitation: dict[str, Any] | None = None
    experimental: dict[str, Any] | None = None      # no `extensions` anywhere below
```

`ServerCapabilities` has the identical shape (`_types.py:139-147`: `tools` at 142,
`resources`, `prompts`, `logging`, `experimental` at 147).

`2026-07-28` adds an `extensions` map to both (SEP-2133 lineage,
`_research/spec.md:262`). Without it there is no place to say "I speak
`io.modelcontextprotocol/tasks`", no place to read whether the peer does, and the
serialization path drops unknown keys anyway: the `initialize` result is rebuilt
field-by-field into `caps_dict` (`src/lauren_mcp/server/_module.py:388-405`), so a field
that is not explicitly copied never reaches the wire. Shipping tasks without this plumbing
would mean hardcoding a second, private capability channel — exactly what the extension
mechanism exists to prevent.

### 1.3 Why tasks are an extension and not core

Tasks were experimental core in `2025-11-25` (SEP-1686) and are now marked "→ extension"
in the change matrix (`_research/spec.md:358`), governed by the extension lifecycle
(SEP-3392). Both SEP-2663 and SEP-3392 are **merged after the `2026-07-28` release and
appear in no released revision** (E-53), so this PRD treats every extension identifier,
method name and version field as *published-but-unreleased* and pins what we cannot verify
in §9 rather than inventing it silently.

Two consequences shape the design: we must not remove the synchronous `tools/call` path
(deprecation is a ≥12-month window here, E-41, and a `2025-11-25` client keeps calling it
expecting an envelope), and we must not make the extension mandatory (a client that does
not advertise `io.modelcontextprotocol/tasks` gets today's blocking behaviour, unchanged).

---

## 2. Goals

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

## 3. Non-Goals

* **No plugin framework.** The registry is a dict plus five methods: no entry points, no
  dynamic import from the wire, no per-extension config schema.
* **No client-side task support** beyond parsing a handle into a typed object; polling from
  `McpClient` is a follow-up.
* **No persistence layer.** `InMemoryTaskStore` only; a file or SQL store is deferred (§9).
* **No task notifications** and no ride-along on `subscriptions/listen` (§4.8).
* **No resumption of a tool body mid-execution.** A task handles a running coroutine, not a
  checkpointed workflow engine.
* **No change to version negotiation** (`_handshake.py`); the two negotiations are
  orthogonal.

---

## 4. Design

### 4.1 The wire shape: one `extensions` map, tolerant reader

Both capability dataclasses gain one optional mapping, defaulting to `None` so every
existing construction site keeps compiling:

```python
# src/lauren_mcp/_types.py (after line 135 / after line 147)
extensions: dict[str, dict[str, Any]] | None = None
```

Keys are extension identifiers (`io.modelcontextprotocol/tasks`); values are opaque
per-extension maps. We read exactly one key out of them, `version`, and read it
defensively, because the value shape is post-release (E-53). The generic layer is one
small module with no I/O:

```python
# src/lauren_mcp/_extensions.py
TASKS_EXTENSION = "io.modelcontextprotocol/tasks"


@dataclass(frozen=True)
class ExtensionDeclaration:          # normalised view of one map entry
    id: str
    version: str | None = None

    @classmethod
    def from_map(cls, id: str, payload: Any) -> "ExtensionDeclaration":
        """Tolerant reader: peers may send {}, {"version": ...} or a bare bool."""


class ExtensionRegistry:
    """Both halves of negotiation: what *we* declare, what the *peer* declared."""

    def declare(self, extension_id: str, *, version: str | None = None) -> None: ...
    def register_method(self, method: str, extension_id: str, handler: Any) -> None: ...
    def observe_client(self, extensions: dict[str, Any] | None) -> None: ...
    def is_negotiated(self, extension_id: str) -> bool: ...
    def as_map(self) -> dict[str, dict[str, Any]] | None: ...
    def owner_of(self, method: str) -> str | None: ...   # dispatch gate
```

That is the whole generic story: declare, observe, `is_negotiated`, `owner_of`.

### 4.2 Task lifecycle and the four extension methods

A task is a server-side record with an id, a state, a monotonic `revision`, an optional
result and an expiry. States: `working` and `input_required` are
non-terminal; `completed`, `failed`, `cancelled` and `expired` are terminal (`expired` = the
TTL swept it, so `tasks/get` returns not-found).

Methods, namespaced under the extension and **only routable when negotiated**:

* `tasks/get` — `{"taskId": ...}` → the record (`state`, `revision`, timestamps, `result`
  when terminal). This is the poll.
* `tasks/list` — optional filter → tasks visible to this client, newest first, capped.
  Needed because the revision removed sessions (`_research/spec.md:389-396`): after a
  reconnect, enumeration is the only re-discovery path.
* `tasks/cancel` — `{"taskId": ...}` → the record after cancellation. Idempotent:
  cancelling a terminal task returns it unchanged rather than erroring.
* `tasks/result` — `{"taskId": ...}` → the accumulated content blocks once terminal, so a
  client that only wants output need not parse the record.

**Creation is implicit, not a method.** The client calls `tools/call` and the *server*
decides asynchronously: if the tool is task-capable and the extension is negotiated, the
response is a task handle instead of the tool result. It is still a normal tool in `tools/list`, so a task-unaware client
can call it and simply block.

### 4.3 How a long-running `tools/call` returns a handle instead of blocking

Today the tool handler (`server/_handlers.py:773`) executes the bound method and
`server/_handlers.py:670` wraps the outcome:

```python
# src/lauren_mcp/server/_handlers.py:670  (today)
out: dict[str, Any] = {"content": content, "isError": is_error}
```

With tasks, the same handler gains one branch *before* invocation:

```python
if meta.task and task_manager.enabled_for(binding.client_capabilities):
    handle = task_manager.submit(tool_name=meta.name, arguments=args, ctx=ctx)
    return {"task": handle.as_wire()}      # returns immediately, no blocking
result = await _invoke_tool(...)           # today's path, unchanged
```

Two things make this safe. The dispatcher **already runs handlers off the request
path** (`_server/_dispatcher.py:124` starts each as an `asyncio.Task`, kept in
`_in_flight` at `:71`); the manager reuses that mechanism, so a task is an `asyncio.Task`
whose id is externally visible. And the **fallback is literal code reuse**: when
`enabled_for(...)` is false, execution takes today's path — no branch, no allocation, no
change to `isError` semantics.

Client capabilities reach the handler through a channel that already exists:
`server/_handlers.py:551` passes `binding.client_capabilities` into
`McpToolContext._client_capabilities` (`_server/_context.py:304`) — the exact object the
negotiation check needs. No new plumbing through the dispatcher.

### 4.4 The Python surface

Three ways in, deliberately redundant, all typed and importable, no new dependency
(E-222).

**(a) Decorator flag** for tools whose owner knows they are slow:

```python
from lauren_mcp import McpServer, mcp_tool

server = McpServer(name="indexer")

@mcp_tool(task=True, description="Re-index a repository; returns a task handle.")
async def reindex_repository(path: str) -> str: ...
```

`task` is a new keyword-only parameter on the existing signature
(`server/_decorators.py:758`, already keyword-only), defaulting to `False`, stored on the
metadata read at `server/_handlers.py:773`.

**(b) `TaskHandle` return type** for tools that decide at runtime:

```python
from lauren_mcp import TaskHandle, McpToolContext, mcp_tool

@mcp_tool()
async def reindex_repository(path: str, ctx: McpToolContext) -> str | TaskHandle:
    if await _is_small(path):
        return await _index(path)                     # plain result, sync path
    return ctx.task.defer(lambda: _index(path, on_progress=ctx.task.progress))
```

Returning a `TaskHandle` promotes the call even when `task=False`; the handler detects the
type just before building the envelope (`_handlers.py:670`). If the client did not
negotiate the extension, `ctx.task.defer(...)` **runs the coroutine inline and returns its
value** instead of a handle — one code path, correct on both peers.

**(c) `ctx.task` access** for progress, cancellation and cooperative parking:

```python
@mcp_tool(task=True)
async def reindex_repository(path: str, ctx: McpToolContext) -> str:
    files = await _walk(path)
    for i, f in enumerate(files):
        if ctx.task.cancelled:                 # wraps ctx.cancel_requested (line 321)
            raise TaskCancelled()
        await _index(f)
        ctx.task.progress(step=i, total=len(files), message=f.name)
    return f"indexed {len(files)} files"
```

The types live in `_server/_tasks.py` and are re-exported from `lauren_mcp`:
`TaskState` (a `StrEnum` with `.terminal`), `TaskHandle` (frozen dataclass with `id`,
`method`, `state`, `revision`, `as_wire()`), `TaskScope` (`cancelled`, `progress`, `defer`,
`require_input`).

`ctx.task` is a property on the existing frozen context (`_server/_context.py:275`), not
a new injected parameter, so the injection rules there are untouched and tools that
never touch it pay nothing.

### 4.5 Negotiation: what happens when the client does not advertise tasks

Checked once per `initialize`, and again for any request carrying capabilities in
`_meta`:

| Client `capabilities.extensions` | We declare tasks | Behaviour of a `task=True` tool |
|---|---|---|
| absent, or no `extensions` key | yes | synchronous result; no handle; identical to `1.0.0` |
| contains `io.modelcontextprotocol/tasks` | yes | task handle returned |
| contains the id, we declare it | no | impossible — declaring follows from the tool |
| client sends `tasks/get` without declaring | yes | `-32601`, `data.extension` names the id |

Server declaration is automatic: if any registered tool has `task=True`, the `initialize`
result advertises the extension. Mirroring the `_has_completions` precedent
(`server/_module.py:245`), we compute `_has_task_tools` at build time and emit the map
from `caps_dict` (`_module.py:388-405`). An operator can force it with
`extensions=[TASKS_EXTENSION]`.

`LAUREN_MCP_EXTENSIONS_STRICT=1` turns "client did not negotiate" into `-32602` on a
`task=True` tool instead of a silent synchronous call. Default off: silent degradation is
safe (a correct result, just slower); an error would break a good `2025-11-25` client.

### 4.6 Durability: what a single process can honestly promise

`InMemoryTaskStore` holds records in a `dict`. That buys **survival of a transport drop**
(the task id is an explicit state handle, exactly what session removal demands,
`_research/spec.md:393-396` — a client whose stream dies reconnects, calls `tasks/list`,
resumes polling while the work keeps running), **survival of a client restart** within the
server's lifetime, and **a deterministic answer on failure** (a raised exception is caught
and stored as `failed`, so the poller never hangs on a dead `working`).

It does **not** buy:

* **Survival across a server restart.** Process memory is gone; every id is not-found.
  There is no journal, no replay, no checkpoint — a task is a handle to a live coroutine,
  not a restartable unit of work.
* **Exactly-once execution.** If the server dies mid-task, partial side effects persist and
  the client must decide whether to resubmit: *at-most-once execution, at-least-once
  observation*.
* **Unbounded retention.** Records expire after `task_ttl_seconds` (default 900) and are
  swept; holding results forever in memory is a leak with extra steps.

The seam for more is a four-method `TaskStore` protocol (`put`, `get`, `list`, `delete`),
with `InMemoryTaskStore` as the only implementation. A durable store fixes
*observation* durability only — it cannot resurrect the coroutine — so "my task survives a
restart" is never true here, and the docs must say so rather than shipping a
`FileTaskStore` that implies otherwise.

### 4.7 Interaction with MRTR

They compose, and the composition is one state: `input_required`.

1. The tool calls `ctx.task.require_input(prompt)`; state becomes `input_required` and
   the pending future is stored on the record — a poller sees a task that is *asking*,
   not stalling.
2. The server issues the client interaction in MRTR's request/response shape, with the
   task id in `_meta`.
3. The client's next request carries the answer in `_meta`; `TaskScope` resolves the
   future and the task returns to `working`.

Caveat: MRTR is not implemented in this repo yet (a separate PRD in this set), so P2 ships
`input_required` as a state plus a hook, not a working round-trip.

### 4.8 Interaction with `subscriptions/listen`

None, by design. `2026-07-28` replaces the subscribe RPCs with `subscriptions/listen`, one
long-lived stream for change notifications (`_research/spec.md:418-423`). Pushing
`tasks/updated` down it is tempting; we do not, because an extension owns its own
notification namespace, because task state is poll-shaped and the record's `revision` lets
a client skip unchanged entries cheaply, and because it keeps failure modes separate — a
broken poll loop cannot break resource notifications.

### 4.9 Errors

Standard JSON-RPC errors, plus two task codes added to the block at `_types.py:106-126`:

| Code | Name | When |
|---|---|---|
| `-32601` | `METHOD_NOT_FOUND` | method belongs to an extension the client never declared; `data` carries `{"extension": id, "reason": "not_negotiated"}` |
| `-32602` | `INVALID_PARAMS` | malformed `taskId`, unknown filter field |
| `-32010` | `TASK_NOT_FOUND` | unknown, evicted or foreign task id |
| `-32011` | `TASK_NOT_CANCELLABLE` | `tasks/cancel` on a terminal task in strict mode (default: no-op success) |

`TASK_NOT_FOUND` rather than an empty `tasks/get` result matters: a client must tell
"your task vanished" from "your task exists with no result yet", or the poll loop cannot
terminate.

---

## 5. Server-side Changes

| File | Change |
|---|---|
| `new` `_extensions.py` | `TASKS_EXTENSION`, `ExtensionDeclaration`, `ExtensionRegistry` (§4.1) |
| `new` `_server/_tasks.py` | `TaskState`, `TaskRecord`, `TaskHandle`, `TaskScope`, `TaskStore`, `InMemoryTaskStore`, `TaskManager` |
| `_types.py` | two `extensions` fields; two new error codes |
| `_server/_dispatcher.py` | consult the registry before `METHOD_NOT_FOUND`; share `_in_flight` |
| `_server/_context.py` | `task` property on `McpToolContext` |
| `server/_handlers.py` | task branch before invocation; `ctx.task`; store wiring |
| `server/_module.py` | declare/emit server extensions; parse client extensions; register `tasks/*` |
| `server/_decorators.py` | `task: bool = False` on `mcp_tool` |
| `__init__.py` | export `TaskHandle`, `TaskState`, `TaskScope`, `TASKS_EXTENSION` |

---

## 6. Exact Lines to Change

### 6.1 `src/lauren_mcp/_types.py`

* `106-126` — `# MCP error codes` block; add `TASK_NOT_FOUND = -32010` and
  `TASK_NOT_CANCELLABLE = -32011`.
* `128-135` — `ClientCapabilities`; append
  `extensions: dict[str, dict[str, Any]] | None = None` after `experimental` (135).
* `139-147` — `ServerCapabilities`; same append after `experimental` (147).

### 6.2 `src/lauren_mcp/server/_module.py`

* `232-234` — `if capabilities is None:` / `resolved_caps = ServerCapabilities(`; set
  `extensions=` from the registry's `as_map()`.
* `245` — `_has_completions = bool(completions)`; add the parallel
  `_has_task_tools = any(t.task for t in tools)` right after.
* `369-372` — `client_caps_raw = params.get("capabilities") or {}` /
  `client_caps = ClientCapabilities(`; pass `extensions=client_caps_raw.get("extensions")`
  and call `extensions_registry.observe_client(...)`.
* `388-405` — `caps_dict` and the field-by-field copy; add an `extensions` branch beside the
  `_has_completions` branch at `399`. **Without this the dataclass field never reaches the
  wire** — the initialize result is rebuilt by hand, not by `asdict`.

### 6.3 `src/lauren_mcp/_server/_dispatcher.py`

* `71` — `self._in_flight: dict[str | int, asyncio.Task[Any]] = {}`; the manager keys off
  the same map so cancel-on-disconnect and cancel-on-tool-call behave alike.
* `101-112` — dispatch; before the handler lookup, ask `owner_of(request.method)` and, if
  the owner is not negotiated, return `-32601` with
  `data={"extension": owner, "reason": "not_negotiated"}`.
* `115-121` — `if handler is None:` → `METHOD_NOT_FOUND`; the four `tasks/*` handlers are
  registered at build time (`server/_module.py`) so they land here as normal handlers,
  not as a special case inside the dispatcher.
* `124` — `asyncio.create_task(...)`; unchanged, cited because it is what makes returning
  a task handle cheap.

### 6.4 `src/lauren_mcp/_server/_context.py`

* `275` — `class McpToolContext`; add a `task` property returning `TaskScope(self)` (built
  lazily, `None` when no task manager is bound).
* `304` — `_client_capabilities: ClientCapabilities | None = None`; unchanged, and the
  single source for the negotiation check in §4.5.
* `321` — `def cancel_requested(self) -> asyncio.Event:`; `TaskScope.cancelled` reads it,
  so `tasks/cancel` and `notifications/cancelled` share one signal.
* `346` — `async def report_progress(...)`; `TaskScope.progress` delegates here so
  progress is emitted exactly once regardless of path.

### 6.5 `src/lauren_mcp/server/_handlers.py`

* `551` — `_client_capabilities=binding.client_capabilities if binding else None,`; no
  change, cited as the existing capability channel.
* `773` — `async def handler(req: JsonRpcRequest) -> dict[str, Any]:`; insert the task
  branch after argument coercion and context construction, before invocation.
* `670` — `out: dict[str, Any] = {"content": content, "isError": is_error}`; add
  `TaskHandle`-return detection immediately before it.

### 6.6 `src/lauren_mcp/server/_decorators.py`

* `758` — `def mcp_tool(` (parameters are keyword-only from `759`); add
  `task: bool = False` and thread it onto the metadata read at `server/_handlers.py:773`.

### 6.7 `src/lauren_mcp/_server/_handshake.py`

* `14-24` (`negotiate_version`) and `31-41`
  (`build_initialize_result(..., capabilities=...)`): **no change**. Extensions travel
  inside `capabilities`, already passed opaquely; keeping the two negotiations separate is
  a goal (§3).

---

## 7. Backward Compatibility

* **Wire-compatible with `2025-11-25` and earlier.** A client that never sends `extensions`
  sees byte-identical `initialize` results unless it talks to a server with task tools, and
  even then the extra key is ignored.
* **`@mcp_tool` unchanged for existing code.** `task` defaults to `False`; every call site
  and `ToolMeta` consumer compiles untouched.
* **No dependency added** (E-222): the delta is stdlib only — `asyncio`, `dataclasses`,
  `enum`, `typing`, `time`.
* **`McpToolContext` stays frozen.** `ctx.task` is a property over existing fields
  (`_context.py:304`, `:321`, `:346`), not a new injected parameter.
* **The synchronous path is the default and the fallback**, so no flag must be flipped
  before an upgrade.
* **Known test churn:** `_module.py:388-405` gains a key, so tests asserting exact
  `caps_dict` equality need updating.

---

## lauren-mcp Advantages

The advantage is not "we also have tasks". It is that `lauren-mcp` can adopt a
*post-release* extension without a breaking release, because the seams already exist:

1. **Cancellation is already task-shaped.** `_dispatcher.py:71` keeps every in-flight
   handler in `_in_flight` and `_context.py:321` already exposes a cancel event. Most SDKs
   built a second execution model for tasks; here `TaskManager` wraps a dictionary that
   already exists, which is why the diff is ~500 lines instead of a subsystem.
2. **Capability plumbing has a precedent.** `completions` is already a capabilities field
   that is not a core capability (`_module.py:245`, `:399`), so a reviewer reads this change
   as "one more branch like the completions one".
3. **Progress is free.** `TaskScope.progress` delegates to `report_progress`
   (`_context.py:346`), so a tool author writes progress handling once and it works on both
   paths — consistency SDKs with separate task-progress APIs do not give you.
4. **Type-first, dependency-free.** `TaskHandle` and `TaskState` are importable dataclasses,
   and `ctx.task.defer(...)` degrades to an inline await on an old peer: one user code path.

Where we are *not* advantaged, honestly: the TS, Python, Rust and C# reference
implementations already ship task-shaped examples (25 / 9 / 17 / 18 hits, E-80/E-81) and
will land the extension first. Our edge is integration quality inside this framework
(context, cancellation, progress), not being early.

---

## 8. Test Plan

### 8.1 Unit tests — `tests/unit/test_tasks_extension.py`

1. `as_map()` is `None` with nothing declared; `{"io.modelcontextprotocol/tasks": {}}` when
   declared without a version.
2. `observe_client({".../tasks": {"version": "2026-07-28"}})` → `is_negotiated` true,
   `peer_version` returns the string; the tolerant reader reports `version is None` for
   `{"x/y": True}` instead of raising.
3. `ClientCapabilities(extensions={"a/b": {}})` round-trips through the `_module.py:388-405`
   serialiser and appears on the wire — regression test for the field-drop bug.
4. Store lifecycle: submit → `working` → `completed`; `cancel` on a terminal record is a
   no-op returning the same record; an expired record yields `TASK_NOT_FOUND` and is absent
   from `tasks/list`.
5. `TaskScope.cancelled` reflects `ctx.cancel_requested.set()`; `TaskScope.defer` returns
   the awaited value, not a handle, when the extension is not negotiated.
6. Dispatcher gate: `tasks/get` from a client that never declared the extension returns
   `-32601` with `data.extension == TASKS_EXTENSION`.

### 8.2 Integration tests — `tests/integration/test_tasks_roundtrip.py`

1. **Happy path.** In-process streamable-HTTP client initialises with
   `extensions={"io.modelcontextprotocol/tasks": {}}`, calls a `task=True` tool, gets a
   handle with `state == "working"`, polls `tasks/get` to `completed`; the result equals the
   direct synchronous call.
2. **Legacy peer.** Same server, client sends no `extensions`: the tool blocks and returns
   today's envelope with no `task` key and a payload identical to `1.0.0`.
3. **Cancel.** Slow task → `tasks/cancel` → `cancelled`; the tool's `ctx.task.cancelled`
   fired; repeated `tasks/get` is stable.
4. **Reconnect.** Drop the connection mid-task, re-initialise, `tasks/list`, find the id,
   resume polling to completion (`_research/spec.md:389-396`).
5. **Restart honesty.** Fresh `InMemoryTaskStore`; `tasks/get` for the old id returns
   `TASK_NOT_FOUND` — the documented limitation encoded as a test so nobody "fixes" it into
   an accidental promise.
6. **Not-negotiated routing.** `tasks/get` without declaring → `-32601` naming the id.

```bash
pytest tests/unit/test_tasks_extension.py tests/integration/test_tasks_roundtrip.py -q
```

---

## 9. Open Questions

1. **Handle placement.** `{"task": {...}}` at the top level, or under `_meta`? SEP-2663 is
   post-release (E-53) and there is no released schema to pin; the decision is centralised
   in `TaskHandle.as_wire()`.
2. **`tasks/result` existence.** The brief specifies create / `tasks/get` / list / cancel;
   `tasks/result` is proposed for ergonomics and can be dropped.
3. **Version value shape.** `{"version": "..."}`, a bare string, or `{}`. We read all three
   and emit `{}` when we have no version to claim.
4. **Durable `TaskStore`.** Deferred: a file-backed store is ~80 stdlib lines but implies
   restart survival we cannot deliver.
5. **`input_required` TTL.** Should a parked task pause its TTL? Proposal: yes, once MRTR
   lands and we can prove a client is waiting.
6. **Auto-declaration versus opt-in.** We auto-declare when a `task=True` tool exists;
   always-explicit is louder but prevents accidental advertisement. Chosen: auto, with the
   `extensions=[...]` escape hatch.

---

## 10. References

Evidence rows (see `EVIDENCE.md`):

* **E-25** — tasks move to the `io.modelcontextprotocol/tasks` extension (SEP-2663).
* **E-53** — SEP-3392 (Extension Lifecycle, Final, 2026-09-25) and SEP-2663 are merged
  **after** `2026-07-28` and appear in no released revision; hence the §9 open items.
* **E-30** — the registry/overview pages enumerating extensions and deprecations.
* **E-41** — deprecation is not removal; ≥12-month window (SEP-2596 / SEP-2577). Basis for
  keeping the synchronous path indefinitely.
* **E-222** — exactly two runtime dependencies (`lauren`, `anyio`); no new dependency.
* **E-235** — `grep -ril 'tasks/' src/ | wc -l` → `0`; baseline for the checklist.
* **E-80 / E-81** — reference implementations: TS 25 hits, Python 9, Rust 17, C# 18. Peers
  ship this; absence costs features, not interop → P2.

Research: `_research/spec.md:253` (change matrix, SEP-2663), `:262` (`extensions` added to
both capability objects), `:358` (`tasks/*` "→ extension"), `:389-396` (sessions removed;
durable state becomes a state handle), `:418-423` (`subscriptions/listen`), `:425` (§8.6
"Tasks and extensions").

Source: `_types.py:106-126`, `:128-135`, `:139-147`; `_dispatcher.py:71`, `:101-121`,
`:124`; `_context.py:275`, `:304`, `:321`, `:346`; `_handlers.py:551`, `:670`, `:773`;
`_module.py:232-234`, `:245`, `:369-372`, `:388-405`; `_decorators.py:758`;
`_handshake.py:14-24`, `:31-41`.

---

## Acceptance Checklist

- [ ] `wc -c prds/2026-11-landscape/prd-tasks-extension.md` reports 18000–30000 bytes.
- [ ] `grep -c '^## ' prds/2026-11-landscape/prd-tasks-extension.md` ≥ 10 and includes
      `## lauren-mcp Advantages`; `grep -n '\*\*Priority:\*\* P2'` hits.
- [ ] `grep -ril 'tasks/' src/ | wc -l` is `0` before implementation and **≥ 1** after
      (`src/lauren_mcp/_server/_tasks.py` plus the `tasks/get` registrations).
- [ ] `grep -n 'extensions' src/lauren_mcp/_types.py` shows both capability classes.
- [ ] `python -c "from lauren_mcp import TaskHandle, TaskState, TASKS_EXTENSION; print(TaskState.WORKING)"`
      succeeds.
- [ ] `pytest tests/unit/test_tasks_extension.py tests/integration/test_tasks_roundtrip.py -q`
      passes, including the legacy-peer case yielding `{"content": ..., "isError": ...}`.
- [ ] `git add -f prds/2026-11-landscape/prd-tasks-extension.md && git status --short` shows
      the file as staged (`A`), not untracked.
