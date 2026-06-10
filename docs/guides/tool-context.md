# McpToolContext — Tool Context Injection

## Overview

When a `@mcp_tool` parameter is annotated as `McpToolContext`, the framework injects
a per-call context object at dispatch time. The parameter is **excluded** from the
JSON schema sent to AI clients, so they never see or attempt to supply it.

This lets tool implementations access transport metadata, send progress notifications,
log messages back to the client, issue server-initiated LLM calls (sampling), request
structured input from the user (elicitation), and check whether the caller has
cancelled the request — all without any special wiring.

```python
from lauren_mcp import mcp_server, mcp_tool, McpToolContext

@mcp_server(path="/tools")
class MyServer:
    @mcp_tool()
    async def do_work(self, query: str, ctx: McpToolContext) -> str:
        await ctx.info("Starting work for query: %s", query)
        await ctx.report_progress(0, 100)
        # ...
        return "done"
```

!!! note "Import path"
    `McpToolContext` is exported from the top-level package:
    `from lauren_mcp import McpToolContext`

---

## Declaring context

The injected parameter may appear anywhere in the signature. Any name is accepted;
the type annotation alone triggers injection.

=== "Positional (typical)"

    ```python
    @mcp_tool()
    async def search(self, query: str, ctx: McpToolContext) -> list[str]:
        ...
    ```

=== "Optional annotation"

    ```python
    from __future__ import annotations
    from lauren_mcp import McpToolContext

    @mcp_tool()
    async def search(
        self,
        query: str,
        ctx: McpToolContext | None = None,
    ) -> list[str]:
        if ctx is not None:
            await ctx.info("search called")
        ...
    ```

=== "Any name"

    ```python
    @mcp_tool()
    async def search(self, query: str, context: McpToolContext) -> list[str]:
        await context.report_progress(0, 1, "Searching…")
        ...
    ```

=== "No context (omit entirely)"

    ```python
    @mcp_tool()
    async def ping(self) -> str:
        return "pong"
    ```

    Tools that do not need the context simply omit it — there is no penalty.

!!! warning "Schema exclusion"
    The `McpToolContext` parameter is stripped from the JSON schema the server
    advertises to clients. Never declare it as the first positional parameter after
    `self` if you also rely on positional argument matching from client calls — put
    it after all real parameters.

---

## Transport fields

`McpToolContext` exposes read-only metadata about the current call:

| Attribute | Type | Description |
|---|---|---|
| `headers` | `dict[str, str]` | HTTP/WebSocket headers from the request, lower-cased |
| `execution_context` | `dict[str, Any]` | Lauren execution context (request-scoped DI values) |
| `session_id` | `str \| None` | SSE session identifier; `None` on WebSocket and Streamable HTTP |
| `metadata` | `dict[str, Any]` | MCP `_meta` dict from the `tools/call` request, if any |
| `state` | `dict[str, Any]` | MCP request-level state bag (populated by some clients) |
| `extras` | `dict[str, Any]` | Any additional fields from the `tools/call` params |
| `lifespan_context` | `dict[str, Any]` | Values yielded by the `@mcp_lifespan` generator |

```python
@mcp_tool()
async def authenticated_action(self, resource: str, ctx: McpToolContext) -> str:
    token = ctx.headers.get("authorization", "")
    if not token.startswith("Bearer "):
        raise PermissionError("Missing bearer token")

    db = ctx.lifespan_context["db"]          # set up in @mcp_lifespan
    return await db.fetch(resource)
```

---

## Progress notifications

Use `ctx.report_progress` to send incremental progress updates to the client. The
client must have included a `progressToken` in the `_meta` of its `tools/call`
request; if no token is present the call is a silent no-op.

```python
ctx.report_progress(progress, total=None, message=None)
```

| Parameter | Type | Description |
|---|---|---|
| `progress` | `float` | Current progress value (any unit) |
| `total` | `float \| None` | Optional total; if supplied the client can show a percentage |
| `message` | `str \| None` | Optional human-readable status string |

```python
@mcp_tool(description="Ingest a large dataset")
async def ingest(self, file_path: str, ctx: McpToolContext) -> str:
    rows = await load_rows(file_path)
    total = len(rows)

    for i, row in enumerate(rows):
        if ctx.cancel_requested.is_set():
            return f"Cancelled after {i} rows"

        await process(row)
        await ctx.report_progress(i + 1, total, f"Row {i + 1}/{total}")

    return f"Ingested {total} rows"
```

!!! tip "Cooperative cancellation"
    Pair `report_progress` with `ctx.cancel_requested` (see
    [Cancellation](#cancellation)) for long-running tools that should be
    interruptible.

---

## Logging to client

`McpToolContext` provides eight logging methods that map to MCP log levels. Log
messages are delivered to the client as `notifications/message` JSON-RPC
notifications in real time.

```python
await ctx.debug(msg, *args)
await ctx.info(msg, *args)
await ctx.notice(msg, *args)
await ctx.warning(msg, *args)
await ctx.error(msg, *args)
await ctx.critical(msg, *args)
```

All methods accept a `printf`-style format string and positional arguments — the
interpolation happens only if the client is listening at that level, so there is no
formatting overhead for suppressed messages.

```python
@mcp_tool(description="Run a database migration")
async def migrate(self, target_revision: str, ctx: McpToolContext) -> str:
    await ctx.info("Starting migration to %s", target_revision)

    try:
        result = await run_alembic(target_revision)
        await ctx.info("Migration complete: %d tables affected", result.tables)
        return result.summary
    except Exception as exc:
        await ctx.error("Migration failed: %s", exc)
        raise
```

### Controlling the client log level

Clients can request a minimum log level via `logging/setLevel`. The server respects
this and suppresses notifications below the requested level. You do not need to check
the level yourself.

```python
# The client sends:
# {"method": "logging/setLevel", "params": {"level": "warning"}}
#
# From that point on, ctx.debug() and ctx.info() calls are no-ops.
```

!!! note "Transport support"
    Log notifications are supported on all transports (WebSocket, Streamable HTTP,
    and SSE). On SSE they are delivered as server-sent events on the open SSE stream.

---

## Sampling (server-initiated LLM calls)

`ctx.sample()` lets the server ask the *client's* LLM to generate a response. This
is MCP's "sampling" capability — the client must advertise `{"sampling": {}}` in its
`ClientCapabilities` during the handshake, otherwise `ctx.sample()` raises
`McpSamplingNotAvailable`.

```python
result = await ctx.sample(
    messages,                      # list[SamplingMessage]
    model_preferences=None,        # ModelPreferences | None
    system_prompt=None,            # str | None
    max_tokens=1024,               # int
)
# result: CreateMessageResult
```

### Basic sampling

```python
from lauren_mcp import mcp_tool, McpToolContext
from lauren_mcp import SamplingMessage, TextContent

@mcp_tool(description="Summarise text using the client's LLM")
async def summarise(self, text: str, ctx: McpToolContext) -> str:
    result = await ctx.sample(
        messages=[
            SamplingMessage(
                role="user",
                content=TextContent(type="text", text=f"Summarise:\n\n{text}"),
            )
        ],
        max_tokens=256,
    )
    # result.content is a TextContent | ImageContent
    return result.content.text
```

### Agentic loops

For multi-step tasks where the LLM may call tools, use the extended form:

```python
result = await ctx.sample(
    messages,
    tools=tool_list,               # list[ToolSchema] — tools the LLM may call
    tool_choice="auto",            # "auto" | "any" | "none" | specific tool name
    max_tool_iterations=10,        # guard against infinite loops (default: 5)
    max_tokens=2048,
)
```

The framework automatically executes tool calls returned by the LLM, appends the
results to the conversation, and re-samples until the model produces a final
non-tool-call response or `max_tool_iterations` is reached.

!!! warning "Transport requirement"
    `ctx.sample()` requires a **bidirectional** transport — WebSocket or
    Streamable HTTP. Calling it on an SSE connection raises
    `McpSamplingNotAvailable` because SSE is server-to-client only; the server
    cannot issue a request to the client.

```python
from lauren_mcp import McpSamplingNotAvailable

@mcp_tool()
async def llm_powered_tool(self, prompt: str, ctx: McpToolContext) -> str:
    try:
        result = await ctx.sample(
            [SamplingMessage(role="user", content=TextContent(type="text", text=prompt))]
        )
        return result.content.text
    except McpSamplingNotAvailable:
        return "Sampling not available on this transport"
```

---

## Elicitation

Elicitation allows the server to pause a tool call and ask the *user* (via the
client) for additional structured input. The client must advertise
`{"elicitation": {}}` in its capabilities; otherwise `ctx.elicit()` raises
`McpElicitationNotAvailable`.

### `ctx.elicit(message, response_type)`

```python
result = await ctx.elicit(message, response_type)
# result: ElicitResult
# result.action: "accept" | "decline" | "cancel"
# result.data: the parsed value, or None if declined/cancelled
```

The `response_type` determines the JSON schema sent to the client and the Python
type of `result.data`.

#### Supported response types

=== "`None` — confirmation only"

    ```python
    result = await ctx.elicit("Are you sure you want to delete all records?")
    if result.action != "accept":
        return "Cancelled"
    ```

=== "`str` — free text"

    ```python
    result = await ctx.elicit("Enter a project name:", str)
    if result.action == "accept":
        project_name = result.data   # str
    ```

=== "`bool` — boolean toggle"

    ```python
    result = await ctx.elicit("Enable verbose logging?", bool)
    verbose = result.action == "accept" and result.data
    ```

=== "`int` — integer input"

    ```python
    result = await ctx.elicit("Maximum number of retries (0–10):", int)
    max_retries = result.data if result.action == "accept" else 3
    ```

=== "`list[str]` — multi-select"

    ```python
    result = await ctx.elicit("Select environments to deploy to:", list[str])
    if result.action == "accept":
        envs: list[str] = result.data
    ```

=== "`Literal` — enum choice"

    ```python
    from typing import Literal

    result = await ctx.elicit(
        "Choose log level:",
        Literal["debug", "info", "warning", "error"],
    )
    level = result.data if result.action == "accept" else "info"
    ```

=== "`dataclass` — structured form"

    ```python
    from dataclasses import dataclass

    @dataclass
    class DeployConfig:
        environment: str
        replicas: int
        dry_run: bool = False

    result = await ctx.elicit("Configure deployment:", DeployConfig)
    if result.action == "accept":
        cfg: DeployConfig = result.data
        await deploy(cfg.environment, cfg.replicas, cfg.dry_run)
    ```

=== "`TypedDict` — typed dict form"

    ```python
    from typing import TypedDict

    class SearchOptions(TypedDict):
        max_results: int
        include_archived: bool

    result = await ctx.elicit("Configure search:", SearchOptions)
    if result.action == "accept":
        opts: SearchOptions = result.data
    ```

=== "`BaseModel` — Pydantic model"

    ```python
    from pydantic import BaseModel, Field

    class BackupOptions(BaseModel):
        destination: str = Field(description="S3 bucket or local path")
        compress: bool = True
        retention_days: int = 30

    result = await ctx.elicit("Configure backup:", BackupOptions)
    if result.action == "accept":
        opts: BackupOptions = result.data
    ```

### `ctx.elicit_url(message, url)` — URL-based elicitation

For OAuth flows or any interaction that requires opening a URL in the user's browser,
use `ctx.elicit_url`. The client presents the URL to the user; the result contains
the response once the user completes the flow.

```python
result = await ctx.elicit_url(
    "Authenticate with GitHub to continue:",
    "https://github.com/login/oauth/authorize?client_id=…&state=…",
)
# result: UrlElicitResult
# result.action: "accept" | "decline" | "cancel"
# result.url: the final redirect URL including query params (code, state, etc.)
```

```python
from lauren_mcp import McpElicitationNotAvailable

@mcp_tool(description="Connect to GitHub")
async def connect_github(self, ctx: McpToolContext) -> str:
    auth_url, state = build_oauth_url()

    try:
        result = await ctx.elicit_url("Authenticate with GitHub:", auth_url)
    except McpElicitationNotAvailable:
        return f"Please open: {auth_url}"

    if result.action != "accept":
        return "Authentication cancelled"

    code = extract_code(result.url)
    token = await exchange_code(code, state)
    return f"Connected! Token stored."
```

!!! note "Elicitation vs sampling"
    - **Elicitation** asks the *human user* for input — the client shows a UI.
    - **Sampling** asks the *LLM* to generate a response — no human in the loop.

---

## Cancellation

`ctx.cancel_requested` is an `asyncio.Event` that is set when the client sends a
`notifications/cancelled` notification for the current request. Tools should poll
it at natural checkpoints to exit cleanly rather than being killed mid-operation.

```python
@mcp_tool(description="Process a large file line by line")
async def process_file(self, path: str, ctx: McpToolContext) -> str:
    lines = await read_lines(path)
    processed = 0

    for line in lines:
        if ctx.cancel_requested.is_set():
            await ctx.warning("Cancelled after %d lines", processed)
            return f"Partial result: processed {processed} lines"

        await process_line(line)
        processed += 1

        if processed % 100 == 0:
            await ctx.report_progress(processed, len(lines))

    return f"Done: {processed} lines"
```

!!! tip "Long-running async operations"
    For tools that `await` long operations, check `cancel_requested` before
    each `await`. You can also use `asyncio.wait` with the event to
    implement a timeout-or-cancel pattern:

    ```python
    import asyncio

    done, _ = await asyncio.wait(
        [asyncio.ensure_future(heavy_operation())],
        return_when=asyncio.FIRST_COMPLETED,
    )
    # If cancel_requested fires before the task, handle it here.
    ```

---

## Lifespan context

`ctx.lifespan_context` is the dictionary yielded by the `@mcp_lifespan` async
generator. It is populated once at server startup and shared across all tool calls.
Use it to share expensive resources like database connections, HTTP sessions, or
ML models.

```python
from contextlib import asynccontextmanager
from lauren_mcp import mcp_server, mcp_tool, mcp_lifespan, McpToolContext

@mcp_server(path="/ml")
class MlServer:

    @mcp_lifespan()
    @asynccontextmanager
    async def lifespan(self):
        # Startup — load the model once
        model = await load_model("bert-base")
        yield {"model": model}
        # Shutdown — release resources
        await model.close()

    @mcp_tool(description="Embed text using BERT")
    async def embed(self, text: str, ctx: McpToolContext) -> list[float]:
        model = ctx.lifespan_context["model"]
        return await model.encode(text)
```

!!! note "Availability"
    `ctx.lifespan_context` is an empty dict `{}` if no `@mcp_lifespan` method is
    defined on the server class.

---

## Full example

The following example combines progress, logging, elicitation, and cancellation
in a single tool:

```python
from dataclasses import dataclass
from lauren_mcp import mcp_server, mcp_tool, McpToolContext

@dataclass
class ExportOptions:
    format: str       # "csv" | "json" | "parquet"
    compress: bool = False
    max_rows: int = 10_000

@mcp_server(path="/data")
class DataServer:

    @mcp_tool(description="Export a table to a file")
    async def export_table(
        self,
        table: str,
        destination: str,
        ctx: McpToolContext,
    ) -> str:
        # 1. Ask the user for export options
        result = await ctx.elicit("Configure export:", ExportOptions)
        if result.action != "accept":
            return "Export cancelled"

        opts: ExportOptions = result.data
        await ctx.info(
            "Exporting %s as %s (compress=%s, max_rows=%d)",
            table, opts.format, opts.compress, opts.max_rows,
        )

        # 2. Fetch rows with cooperative cancellation
        rows = await fetch_rows(table, limit=opts.max_rows)
        total = len(rows)

        for i, batch in enumerate(chunk(rows, size=500)):
            if ctx.cancel_requested.is_set():
                await ctx.warning("Export cancelled at batch %d/%d", i, total // 500)
                return f"Partial export: {i * 500} rows written"

            await write_batch(destination, batch, opts.format, opts.compress)
            await ctx.report_progress(min((i + 1) * 500, total), total)

        await ctx.info("Export complete: %d rows → %s", total, destination)
        return f"Exported {total} rows to {destination}"
```
