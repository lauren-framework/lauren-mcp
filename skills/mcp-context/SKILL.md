---
skill: mcp-context
version: 1.0.0
tags: [mcp, context, injection, progress, logging, sampling, elicitation, cancellation, lifespan, lauren-mcp]
summary: Use McpToolContext to access transport state, report progress, send logs, call LLMs, and elicit user input in @mcp_tool methods.
---

# Skill: MCP Tool Context

## When to use this skill

Use this skill when you need to:
- Access per-call transport state inside an `@mcp_tool` method
- Report progress or send structured log notifications to the client
- Ask the client's LLM to process a sub-task (sampling)
- Prompt the connected user for input (elicitation)
- Check whether the client has cancelled the current call
- Access resources opened during server startup (lifespan context)
- Read server metadata set with `@set_metadata`

## Declaring the context parameter

Add a parameter annotated with `McpToolContext` to any `@mcp_tool` method.
The name does not matter; the parameter is detected by type and excluded from
the JSON Schema:

```python
from lauren_mcp import McpToolContext, mcp_server, mcp_tool

@mcp_server("/mcp")
class MyServer:
    @mcp_tool()
    async def process(self, data: str, ctx: McpToolContext) -> str:
        await ctx.info("Starting process", {"data": data})
        return data.upper()
```

`McpToolContext` can also be declared optional:

```python
async def process(self, data: str, ctx: McpToolContext | None = None) -> str:
    if ctx:
        await ctx.info("has context")
    ...
```

## Transport identity fields

```python
ctx.tool_name        # str — name of the called tool
ctx.tool_use_id      # str | int | None — MCP tool-use ID from the request
ctx.session_id       # str | None — transport session identifier
ctx.headers          # Headers | None — HTTP/WS headers from the transport
ctx.execution_context  # lauren.ExecutionContext | None
ctx.metadata         # dict[str, Any] — @set_metadata values from the server class
ctx.state            # dict[str, Any] — mutable per-call scratch space
ctx.extras           # dict[str, Any] — integration scratch space
                     # (lauren-ai stores AgentContext under extras["agent_context"])
```

## `ctx.lifespan_context` — accessing startup resources

When `@mcp_lifespan` is declared on the server class, the dict it yields is
available as `ctx.lifespan_context` for every tool call:

```python
@mcp_server("/mcp")
class MyServer:
    @mcp_lifespan
    async def lifespan(self):
        db = await create_db_connection()
        try:
            yield {"db": db}
        finally:
            await db.close()

    @mcp_tool()
    async def query(self, sql: str, ctx: McpToolContext) -> list:
        db = ctx.lifespan_context["db"]
        return await db.execute(sql)
```

## `ctx.get_metadata(key, default=None)` — reading server metadata

`@set_metadata` on the `@mcp_server` class propagates to the controller.
Values are readable from every tool call:

```python
from lauren import set_metadata

@mcp_server("/mcp")
@set_metadata("env", "production")
class MyServer:
    @mcp_tool()
    async def info(self, ctx: McpToolContext) -> str:
        env = ctx.get_metadata("env", "unknown")
        return f"Running in {env}"
```

## Progress reporting

`ctx.report_progress()` sends `notifications/progress` to the client. It is
a no-op when the client did not supply a `progressToken` in the request, or
when the transport has no notification channel (e.g. stateless Streamable HTTP).

```python
@mcp_tool()
async def batch_process(self, items: list[str], ctx: McpToolContext) -> str:
    for i, item in enumerate(items, 1):
        await process_one(item)
        await ctx.report_progress(
            progress=i,
            total=len(items),
            message=f"Processed {item}",
        )
    return f"Done — {len(items)} items"
```

Parameters:
- `progress` — current value (e.g. number of items done)
- `total` — optional upper bound; omit for indeterminate progress
- `message` — optional human-readable status string

## Logging

Send structured `notifications/message` log entries to the client. Entries
below the server's minimum level (set via `log_level=` in `for_root()` or
adjusted at runtime with `logging/setLevel`) are silently dropped.

All eight syslog-aligned MCP log levels are supported:

```python
await ctx.debug("Internal state", {"value": x})
await ctx.info("Operation started")
await ctx.notice("Fallback path used")          # significant but normal
await ctx.warning("Rate limit approaching")
await ctx.error("Sub-task failed", {"reason": str(exc)})
await ctx.critical("Primary DB down; using replica")

# Or use the generic method:
await ctx.log("warning", "Custom message", {"extra": "data"})
```

The client receives these as `notifications/message` payloads. The client can
lower or raise the threshold by calling `client.set_logging_level("warning")`.

## Sampling — asking the client's LLM

`ctx.sample()` sends `sampling/createMessage` to the client. The client runs
the LLM call and returns the result. This is a full round-trip and requires:
1. The client to advertise the `sampling` capability
2. A transport that supports server-to-client requests (WebSocket or Streamable HTTP — not legacy SSE)

```python
from lauren_mcp import CreateMessageResult, McpSamplingNotAvailable

@mcp_tool()
async def summarise(self, text: str, ctx: McpToolContext) -> str:
    try:
        result: CreateMessageResult = await ctx.sample(
            messages=f"Summarise this in one sentence:\n\n{text}",
            max_tokens=200,
            system_prompt="You are a concise summarisation assistant.",
        )
        return result.text
    except McpSamplingNotAvailable as exc:
        return f"Sampling unavailable: {exc}"
```

Full signature:

```python
result = await ctx.sample(
    messages,           # str (single user message) or list[SamplingMessage]
    max_tokens=1024,    # int
    system_prompt=None, # str | None
    temperature=None,   # float | None
    stop_sequences=None,
    model_preferences=None,
    include_context="none",   # "none" | "thisServer" | "allServers"
    result_type=None,   # Pydantic model class — parse JSON reply into it
    tools=None,         # list[ToolSchema | McpToolMeta | dict] — agentic loop
    tool_choice=None,   # dict — forwarded to client as-is
    max_tool_iterations=10,
)
```

**`result_type=`** — when provided, `ctx.sample()` parses the response text
as JSON and validates it against the model, returning a model instance:

```python
from pydantic import BaseModel

class Summary(BaseModel):
    headline: str
    key_points: list[str]

summary: Summary = await ctx.sample(
    "Extract headline and key points from: ...",
    result_type=Summary,
)
print(summary.headline)
```

**Tool-enabled sampling** — when `tools=` is supplied, the LLM may respond
with a `ToolUseContent` block. `ctx.sample()` does **not** execute tools
automatically; the caller drives the agentic loop:

```python
from lauren_mcp import McpSamplingLoopError, ToolUseContent

for _ in range(10):
    result = await ctx.sample(messages, tools=[my_tool_schema])
    if isinstance(result.content, ToolUseContent):
        tool_result = await execute_tool(result.content)
        messages.append(...)
        continue
    return result.text
raise McpSamplingLoopError("Loop exceeded 10 iterations")
```

Raises `McpSamplingNotAvailable` when the client did not advertise the
`sampling` capability, or when the transport does not support
server-to-client requests (legacy HTTP+SSE).

## Elicitation — prompting the user for input

`ctx.elicit()` sends `elicitation/create` to the client, which shows a form
or prompt to the human user. Supported `response_type` values:

```python
from lauren_mcp import ElicitResult, McpElicitationNotAvailable

# Approval-only (no response_type)
result: ElicitResult = await ctx.elicit("Confirm deletion?")
if result.action == "accept":
    delete_item()

# Scalar types
result = await ctx.elicit("Enter your name:", str)
name = result.content.get("value") if result.action == "accept" else None

# Pydantic model (flat — no nested objects)
from pydantic import BaseModel

class UserPrefs(BaseModel):
    theme: str
    notifications: bool

result = await ctx.elicit("Configure preferences:", UserPrefs)
if result.action == "accept":
    prefs = UserPrefs(**result.content)
```

Supported `response_type` values:
- `None` — approval only (no schema sent)
- `str`, `bool`, `int`, `float` — single scalar
- `Literal["a", "b", "c"]` or `Enum` subclass — string enum
- `list[str]` — multi-select string array
- Flat Pydantic model, dataclass, TypedDict, `msgspec.Struct` — object form.
  **All fields must be scalar types** (nested objects/arrays raise `ValueError`).

Raises `McpElicitationNotAvailable` when the client does not support
elicitation, or the transport is legacy SSE.

## `ctx.elicit_url()` — open an external URL

Direct the user to a URL for an out-of-band flow (e.g. OAuth consent):

```python
from lauren_mcp import McpUrlElicitationNotAvailable, UrlElicitResult

@mcp_tool()
async def authorize(self, ctx: McpToolContext) -> str:
    try:
        result: UrlElicitResult = await ctx.elicit_url(
            message="Please authorize access to your account.",
            url="https://auth.example.com/oauth/authorize?client_id=...",
        )
        if result.action == "accept":
            return "Authorization complete"
        return "Cancelled"
    except McpUrlElicitationNotAvailable:
        return "URL elicitation not supported by this client"
```

Requires the client to advertise `{"elicitation": {"urlElicitation": true}}`
in its capabilities.

## Cancellation — cooperative and hard cancel

`ctx.cancel_requested` is an `asyncio.Event` set when the client sends
`$/cancelRequest`. Tools should check it between work units for graceful
early exit. The dispatcher will also hard-cancel the asyncio task shortly
after the event fires.

```python
@mcp_tool()
async def long_task(self, n: int, ctx: McpToolContext) -> str:
    results = []
    for i in range(n):
        if ctx.cancel_requested.is_set():
            return f"Cancelled after {i} steps"
        results.append(await heavy_work(i))
        await asyncio.sleep(0)   # yield to allow cancellation
    return f"Done: {len(results)} results"
```

Notes:
- The event is created lazily on first access (safe; frozen dataclass uses
  `object.__setattr__` internally).
- On legacy HTTP+SSE transport the event is never set (SSE does not carry
  `$/cancelRequest`).

## Full example

```python
from __future__ import annotations
from pydantic import BaseModel
from lauren_mcp import (
    McpElicitationNotAvailable,
    McpSamplingNotAvailable,
    McpToolContext,
    mcp_lifespan,
    mcp_server,
    mcp_tool,
)

class ReviewResult(BaseModel):
    approved: bool
    comments: str

@mcp_server("/mcp", transport="all")
class ReviewServer:

    @mcp_lifespan
    async def lifespan(self):
        yield {"review_queue": []}

    @mcp_tool()
    async def review_document(
        self,
        document: str,
        ctx: McpToolContext,
    ) -> str:
        queue = ctx.lifespan_context["review_queue"]

        # 1. Log start
        await ctx.info("Starting review", {"length": len(document)})

        # 2. Report progress while chunking
        chunks = [document[i:i+200] for i in range(0, len(document), 200)]
        summaries = []
        for idx, chunk in enumerate(chunks):
            if ctx.cancel_requested.is_set():
                return "Review cancelled"
            await ctx.report_progress(idx + 1, len(chunks), f"Chunk {idx+1}/{len(chunks)}")

            # 3. Sample an LLM for a chunk summary
            try:
                result = await ctx.sample(
                    f"Summarise this passage in one sentence:\n{chunk}",
                    max_tokens=100,
                )
                summaries.append(result.text)
            except McpSamplingNotAvailable:
                summaries.append(chunk[:50] + "...")

        combined = " ".join(summaries)

        # 4. Elicit human approval
        try:
            approval = await ctx.elicit(
                f"Approve this summary?\n\n{combined}",
                ReviewResult,
            )
            if approval.action == "accept":
                data = ReviewResult(**approval.content)
                if not data.approved:
                    await ctx.warning("Reviewer rejected document", {"comments": data.comments})
                    return f"Rejected: {data.comments}"
        except McpElicitationNotAvailable:
            pass

        queue.append(combined)
        await ctx.info("Review complete", {"queue_size": len(queue)})
        return combined
```
