<p align="center">
  <img src="https://raw.githubusercontent.com/lauren-framework/lauren-assets/refs/heads/main/framework/lauren-logo-only.png" width=40%></img>
</p>
<div align="center">
  <h1><i>lauren-mcp</i></h1>
</div>
<p align="center">
    <em>Model Context Protocol server and client for Lauren applications — expose any Lauren service as an MCP tool endpoint, and wire remote MCP tools into a Lauren AI agent in a single line.</em>
</p>
<p align="center">
<a href="https://github.com/lauren-framework/lauren-mcp/actions/workflows/tests.yml?query=branch%3Amain+event%3Apush">
    <img src="https://github.com/lauren-framework/lauren-mcp/actions/workflows/tests.yml/badge.svg?branch=main&event=push" alt="Test">
</a>
<a href="https://github.com/lauren-framework/lauren-mcp/actions/workflows/lint.yml?query=branch%3Amain+event%3Apush">
    <img src="https://github.com/lauren-framework/lauren-mcp/actions/workflows/lint.yml/badge.svg?branch=main&event=push" alt="Lint">
</a>
<a href="https://github.com/lauren-framework/lauren-mcp/actions/workflows/codeql.yml?query=branch%3Amain">
    <img src="https://github.com/lauren-framework/lauren-mcp/actions/workflows/codeql.yml/badge.svg?branch=main" alt="CodeQL">
</a>
<a href="https://codecov.io/gh/lauren-framework/lauren-mcp">
    <img src="https://img.shields.io/codecov/c/github/lauren-framework/lauren-mcp?color=%2334D058&label=coverage" alt="Coverage">
</a>
<a href="https://pypi.org/project/lauren-mcp">
    <img src="https://img.shields.io/pypi/v/lauren-mcp?color=%2334D058&label=pypi%20package" alt="Package version">
</a>
<a href="https://pypi.org/project/lauren-mcp">
    <img src="https://img.shields.io/pypi/pyversions/lauren-mcp.svg?color=%2334D058" alt="Supported Python versions">
</a>
<a href="https://pypi.org/project/lauren-mcp">
    <img src="https://img.shields.io/pypi/dm/lauren-mcp.svg?color=%2334D058&label=downloads" alt="Downloads">
</a>
<a href="https://github.com/lauren-framework/lauren-mcp/blob/main/LICENSE">
    <img src="https://img.shields.io/github/license/lauren-framework/lauren-mcp.svg?color=%2334D058" alt="License">
</a>
<a href="https://github.com/astral-sh/ruff">
    <img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json" alt="Ruff">
</a>
<a href="https://mypy.readthedocs.io/en/stable/">
    <img src="https://img.shields.io/badge/types-mypy-blue.svg" alt="Checked with mypy">
</a>
<a href="https://github.com/j178/prek">
    <img src="https://img.shields.io/badge/pre--commit-prek-FAB040.svg?logo=pre-commit&logoColor=white" alt="prek">
</a>
<a href="https://github.com/lauren-framework/lauren-mcp/discussions">
    <img src="https://img.shields.io/github/discussions/lauren-framework/lauren-mcp?color=%2334D058&label=discussions" alt="Discussions">
</a>
<a href="https://github.com/lauren-framework/lauren-mcp/stargazers">
    <img src="https://img.shields.io/github/stars/lauren-framework/lauren-mcp.svg?style=social&label=Star" alt="GitHub Stars">
</a>
</p>

---

**Documentation**: <a href="https://lauren-framework.github.io/lauren-mcp/" target="_blank">https://lauren-framework.github.io/lauren-mcp/</a>

**Source Code**: <a href="https://github.com/lauren-framework/lauren-mcp" target="_blank">https://github.com/lauren-framework/lauren-mcp</a>

---

## For AI Agents & Coding Assistants

### Install all skills in one command

```bash
# Claude Code, Cursor, Copilot, Continue, Codex CLI — auto-detected
npx skills add lauren-framework/lauren-mcp
```

This copies all SKILL.md context packs into your agent's global skills
directory (`~/.claude/skills/`, `~/.cursor/skills/`, etc.).  The next time your
agent opens a Lauren project it has pre-loaded expertise on wiring MCP servers,
consuming remote MCP tools, schema generation, transport configuration, and more.

| Resource | What it contains |
|---|---|
| [`llms.txt`](https://raw.githubusercontent.com/lauren-framework/lauren-mcp/refs/heads/main/llms.txt) | 2 KB package overview — start here |
| [`llms-full.txt`](https://raw.githubusercontent.com/lauren-framework/lauren-mcp/refs/heads/main/llms-full.txt) | Complete API reference — all 60+ symbols, signatures, common errors |
| [`AGENTS.md`](https://github.com/lauren-framework/lauren-mcp/blob/main/AGENTS.md) | Agent rules, by-task lookup, file ownership, common errors, definition of done |
| [`CLAUDE.md`](https://github.com/lauren-framework/lauren-mcp/blob/main/CLAUDE.md) | Conventions, commands, golden rules |
| [`skills/`](https://github.com/lauren-framework/lauren-mcp/tree/main/skills/) | Copy-paste skill guides for common tasks |

---

## Installation

| Command | What you get |
|---|---|
| `pip install lauren-mcp` | Core: wire types + server decorators + stdio client |
| `pip install "lauren-mcp[ws]"` | + WebSocket client (`websockets`) |
| `pip install "lauren-mcp[http]"` | + HTTP+SSE client (`httpx` + `httpx-sse`) |
| `pip install "lauren-mcp[pydantic]"` | + Pydantic model schemas (`pydantic>=2`) |
| `pip install "lauren-mcp[msgspec]"` | + msgspec.Struct schemas (`msgspec`) |
| `pip install "lauren-mcp[cli]"` | + `lmcp` CLI (`typer` + `uvicorn`) |
| `pip install "lauren-mcp[otel]"` | + OpenTelemetry tracing (`opentelemetry-api`) |
| `pip install "lauren-mcp[all]"` | Everything |

## MCP protocol versions

| Version | Transport | Status |
|---|---|---|
| 2024-11-05 | Legacy SSE | Supported |
| 2025-03-26 | Streamable HTTP | Supported |
| 2025-06-18 | Streamable HTTP | Supported |
| 2025-11-25 | Streamable HTTP | Supported (default) |

## Server features

- `@mcp_server(path, transport="ws")` — transport options: `"ws"`, `"sse"`, `"streamable"`, `"both"`, `"all"`
- `@mcp_tool(title=, annotations=ToolAnnotations(...), timeout=30.0, tags={"search"}, output_schema=MyModel, structured_output=True)`
- `@mcp_resource(uri_template, mime_type=...)` with RFC 6570 extensions (`{+path}`, `{?page,size}`)
- `@mcp_prompt(title=)`, `@mcp_completion(target, argument)`, `@mcp_lifespan`
- `McpToolContext` injection — `ctx.report_progress()`, `ctx.log/debug/info/warning/error()`, `ctx.sample()`, `ctx.elicit()`, `ctx.elicit_url()`, `ctx.cancel_requested`
- Rich schema generation: Pydantic, msgspec.Struct, `@dataclass`, TypedDict, Literal, `Annotated+Field`
- Binary resources: `bytes` return → auto base64 blob; `BlobResource`, `ResourceResult`
- Dynamic catalog: `listChanged: True`, auto `notifications/tools/list_changed`
- Server composition: `mounts=[(OtherCls, "prefix_")]`, `proxies=[(client, "prefix_")]`
- OpenAPI import: `build_openapi_server_class(spec, http_client=...)`
- Built-in resource types: `FileResource`, `HttpResource`, `DirectoryResource`
- Per-tool `@use_guards(G)` for method-level access control (e.g. admin-only tools)
- Per-tool `@use_interceptors(I)` for cross-cutting concerns (audit, caching, timing)
- Per-tool `@use_exception_handlers(H)` to map domain exceptions to `isError: True`
- `@set_metadata(key, value)` per tool for guard-readable configuration
- Class-level guards, interceptors, and middleware via Lauren pipeline — `@use_guards`, `@use_interceptors`
- DNS rebinding protection: `TransportSecuritySettings`
- SSE event store: `InMemoryEventStore` for resumable connections
- OpenTelemetry tracing: `instrument_otel=True` on `for_root()`
- CLI: `lmcp run`, `lmcp dev`, `lmcp inspect`, `lmcp call`, `lmcp install`

## Client features

- `McpServer.stdio()`, `McpServer.ws()`, `McpServer.http()` (legacy SSE), `McpServer.streamable_http()` (MCP 2025-03-26+)
- All factories accept: `protocol_version=`, `roots=`, `progress_handler=`, `log_handler=`, `list_changed_handler=`, `sampling_handler=`, `elicitation_handler=`, `resource_updated_handler=`
- `client.protocol_version` property after `connect()`
- `client.on_progress/on_log/on_list_changed/on_resource_updated()` return an unsubscribe callable
- `client.subscribe_resource(uri)`, `client.unsubscribe_resource(uri)`
- `client.set_logging_level(level)` — 8 severity levels
- `client.complete(ref, argument)`
- `ClientCredentialsProvider` for OAuth client credentials flow

## Per-tool decorators

Lauren's guard, interceptor, and exception-handler decorators can be applied to
individual `@mcp_tool` / `@mcp_resource` / `@mcp_prompt` methods.
`@mcp_tool()` must be the **outermost** decorator; Lauren decorators go **inside**
(closer to `async def`):

```python
from lauren import use_guards, use_interceptors, use_exception_handlers, set_metadata
from lauren import injectable
from lauren_mcp import mcp_server, mcp_tool, McpToolContext, McpExecutionContext

@injectable()
class AdminGuard:
    async def can_activate(self, ctx: McpExecutionContext) -> bool:
        return ctx.headers.get("x-role") == "admin" if ctx.headers else False

@mcp_server("/mcp")
class AdminServer:
    @set_metadata("required_role", "admin")
    @use_guards(AdminGuard)
    @mcp_tool()
    async def purge_cache(self, ctx: McpToolContext) -> dict:
        """Purge the application cache (admin only)."""
        return {"purged": True}
```

Calling `purge_cache` without the `x-role: admin` header returns
`INTERNAL_ERROR` with `data.type="FORBIDDEN"`. Use `McpForbiddenError` and
`McpExecutionContext` (both in `lauren_mcp`) to inspect guard rejections.

## Quick start — Server

```python
from lauren_mcp import (
    mcp_server, mcp_tool, McpToolContext, McpToolNameCollision,
    McpServerModule, ToolAnnotations, BlobResource,
)
from lauren_mcp.server import mcp_lifespan
from lauren import LaurenFactory, module


@mcp_server("/mcp")
class CatalogueServer:
    @mcp_lifespan
    async def lifespan(self):
        db = await connect_db()
        try:
            yield {"db": db}
        finally:
            await db.close()

    @mcp_tool(
        annotations=ToolAnnotations(readOnlyHint=True),
        timeout=30.0,
        tags={"search"},
    )
    async def search(self, query: str, limit: int = 10, ctx: McpToolContext = ...) -> list:
        """Search items.

        Args:
            query: Search terms.
            limit: Max results.
        """
        await ctx.report_progress(0, total=100, message="Starting search")
        db = ctx.lifespan_context["db"]
        results = await db.search(query, limit)
        await ctx.info("Search complete", {"count": len(results)})
        return results

    @mcp_resource("/img/{name}", mime_type="image/png")
    async def image(self, name: str) -> bytes:
        return open(f"images/{name}.png", "rb").read()


@module(imports=[McpServerModule.for_root(CatalogueServer, transport="all")])
class App:
    pass


app = LaurenFactory.create(App)
# WebSocket:        ws://localhost:8000/mcp/ws
# Streamable HTTP:  http://localhost:8000/mcp/
```

## Quick start — Client

```python
from lauren_mcp import McpServer

client = McpServer.streamable_http(
    "http://localhost:8000/mcp",
    progress_handler=lambda p: print(f"Progress: {p['progress']} — {p.get('message', '')}"),
    log_handler=lambda p: print(f"[{p['level']}] {p['data']['message']}"),
)
await client.connect()
print(f"Protocol: {client.protocol_version}")  # "2025-11-25"
tools = await client.list_tools()
result = await client.call_tool("search", {"query": "coffee", "limit": 5})
```

### Stdio subprocess client

```python
from lauren_mcp import McpServer, McpServerConfig

config = McpServerConfig(
    alias="fs",
    client=McpServer.stdio(
        ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    ),
)
# Tools available as: fs__read_file, fs__write_file, fs__list_directory, ...
```

## Examples

The [`examples/filesystem/`](https://github.com/lauren-framework/lauren-mcp/tree/main/examples/filesystem/) directory contains a fully-working end-to-end example:

| File | Description |
|---|---|
| `server.py` | Lauren-based Filesystem MCP server (Streamable HTTP) |
| `client.py` | Interactive CLI client powered by the Poolside inference backend (OpenAI-compatible), with Rich UI for pretty-printing tool calls and results |
| `pyproject.toml` | Self-contained project with `[client]` and `[deploy]` optional extras |
| `.env.example` | Environment variable reference (`OPENAI_API_KEY`, `OPENAI_API_BASE_URL`, `MCP_SERVER_URL`, etc.) |

```bash
# 1. Start the server
MCP_FS_ROOT=/tmp/sandbox uv run python examples/filesystem/server.py

# 2. Run the interactive client (separate terminal)
OPENAI_API_KEY=<key> uv run --extra client python examples/filesystem/client.py
```

## Documentation

- [Getting Started](https://lauren-framework.github.io/lauren-mcp/getting-started/)
- [MCP Server guide](https://lauren-framework.github.io/lauren-mcp/guides/mcp-server/)
- [MCP Client guide](https://lauren-framework.github.io/lauren-mcp/guides/mcp-client/)
- [Agent Tools guide](https://lauren-framework.github.io/lauren-mcp/guides/mcp-agent-tools/)
- [Testing guide](https://lauren-framework.github.io/lauren-mcp/guides/testing/)
- [API Reference](https://lauren-framework.github.io/lauren-mcp/reference/)

## API summary

```
# Decorators
mcp_server(path, transport="ws", name=, version=, description=)
mcp_tool(title=, annotations=, timeout=, tags=, meta=, output_schema=, structured_output=)
mcp_resource(uri_template, mime_type=, title=, annotations=)
mcp_prompt(title=)
mcp_lifespan
mcp_completion(target, argument)

# Module
McpServerModule.for_root(
    server_cls,
    transport="ws",          # "ws" | "sse" | "streamable" | "both" | "all"
    log_level=,
    mounts=,                 # [(OtherServerCls, "prefix_")]
    proxies=,                # [(McpClientProtocol, "prefix_")]
    instrument_otel=False,
    event_store=,
    stateless_http=False,
)

# Client factories (all accept protocol_version=, roots=, progress_handler=,
#   log_handler=, list_changed_handler=, sampling_handler=,
#   elicitation_handler=, resource_updated_handler=)
McpServer.stdio(command, env=, max_retries=)
McpServer.ws(url, ...)
McpServer.http(url, ...)           # legacy SSE (MCP 2024-11-05)
McpServer.streamable_http(url, ...) # MCP 2025-03-26+

# Client methods
client.connect() / client.close()
client.protocol_version            # property, set after connect()
client.list_tools() / list_resources() / list_prompts()
client.call_tool(name, arguments)
client.read_resource(uri)
client.get_prompt(name, arguments)
client.complete(ref, argument)
client.set_logging_level(level)
client.subscribe_resource(uri) / unsubscribe_resource(uri)
client.on_progress(handler) / on_log(handler)
client.on_list_changed(handler) / on_resource_updated(handler)
client.notify_roots_changed()

# Context (injected into @mcp_tool via ctx: McpToolContext parameter)
ctx.report_progress(progress, total=, message=)
ctx.log/debug/info/notice/warning/error/critical(message, data=)
ctx.sample(messages, model_preferences=, tools=, tool_choice=, max_tool_iterations=)
ctx.elicit(schema, message=)
ctx.elicit_url(url, message=)
ctx.cancel_requested               # asyncio.Event
ctx.lifespan_context               # dict yielded by @mcp_lifespan

# Wire types (selection)
ToolSchema, ToolAnnotations, ToolCallParams, ToolResult, ToolOutput
ResourceSchema, ResourceAnnotations, BlobResource, ResourceResult
PromptSchema, PromptMessage, PromptArgument
TextContent, ImageContent, AudioContent, EmbeddedResource
ResourceLink, ToolUseContent, ToolResultContent
SamplingMessage, CreateMessageParams, CreateMessageResult
ElicitResult, UrlElicitResult
CompletionResult, Root, Role
McpCallError, McpToolNameCollision
McpSamplingNotAvailable, McpElicitationNotAvailable, McpUrlElicitationNotAvailable
LATEST, STABLE, SUPPORTED

# OpenAPI import
build_openapi_server_class(spec, http_client=, route_entries=)
RouteEntry
```
