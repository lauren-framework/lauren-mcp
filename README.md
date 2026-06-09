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

**Documentation**: <a href="https://mcp.lauren-py.dev" target="_blank">https://mcp.lauren-py.dev</a>

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
| [`llms-full.txt`](https://raw.githubusercontent.com/lauren-framework/lauren-mcp/refs/heads/main/llms-full.txt) | Complete API reference — all 40+ symbols, signatures, common errors |
| [`AGENTS.md`](https://github.com/lauren-framework/lauren-mcp/blob/main/AGENTS.md) | Agent rules, by-task lookup, file ownership, common errors, definition of done |
| [`CLAUDE.md`](https://github.com/lauren-framework/lauren-mcp/blob/main/CLAUDE.md) | Conventions, commands, golden rules |
| [`skills/`](https://github.com/lauren-framework/lauren-mcp/tree/main/skills/) | Copy-paste skill guides for common tasks |

---

## Features

- `@mcp_server`, `@mcp_tool`, `@mcp_resource`, `@mcp_prompt` decorators with
  automatic JSON Schema generation from Python type annotations
- Three client transports: **stdio subprocess**, **WebSocket**, **HTTP+SSE**
- `McpServerConfig` + `AgentModule.for_root(mcp_servers=[...])` for zero-boilerplate
  agent tool integration
- Tool namespacing (`alias__tool_name`) prevents collisions across multiple MCP servers
- Automatic system prompt injection listing all available MCP tools
- Exponential backoff reconnect for the WebSocket client
- DI-aware tool dispatch — `Depends(...)` parameters excluded from generated JSON Schema
- 100% typed (mypy strict), 418 tests across Python 3.11–3.14

## Installation

| Command | What you get |
|---|---|
| `pip install lauren-mcp` | Core: JSON-RPC types + server decorators + stdio client |
| `pip install "lauren-mcp[ws]"` | + WebSocket client (`websockets`) |
| `pip install "lauren-mcp[http]"` | + HTTP+SSE client (`httpx`, `httpx-sse`) |
| `pip install "lauren-mcp[all]"` | All transports |

## Quick start — Server

```python
from lauren import Lauren
from lauren_mcp import mcp_server, mcp_tool, mcp_resource, mcp_prompt, McpServerModule

CATALOGUE = [
    {"id": 1, "name": "Widget A", "price": 9.99},
    {"id": 2, "name": "Widget B", "price": 14.99},
    {"id": 3, "name": "Gadget C", "price": 24.99},
]

@mcp_server("/mcp")
class CatalogueServer:
    @mcp_tool()
    async def search(self, query: str) -> list[dict]:
        """Search the catalogue by name.

        Args:
            query: Search terms.
        """
        return [i for i in CATALOGUE if query.lower() in i["name"].lower()]

    @mcp_tool()
    async def get_item(self, item_id: int) -> dict | None:
        """Get a single item by ID.

        Args:
            item_id: The numeric item ID.
        """
        return next((i for i in CATALOGUE if i["id"] == item_id), None)

    @mcp_resource("/catalogue/{item_id}")
    async def item_resource(self, item_id: str) -> str:
        """Expose a catalogue item as a readable MCP resource.

        Args:
            item_id: The item ID extracted from the URI path.
        """
        item = next((i for i in CATALOGUE if i["id"] == int(item_id)), None)
        if item is None:
            return f"Item {item_id} not found."
        return f"{item['name']} — ${item['price']:.2f}"

    @mcp_prompt()
    async def recommend(self, budget: str) -> str:
        """Generate a recommendation prompt for a given budget.

        Args:
            budget: Customer's maximum budget (e.g. "20").
        """
        affordable = [i for i in CATALOGUE if i["price"] <= float(budget)]
        names = ", ".join(i["name"] for i in affordable) or "none"
        return f"Recommend a product to a customer with ${budget} budget: {names}"

app = Lauren()
app.include_module(McpServerModule.for_root(CatalogueServer))
```

## Quick start — Client

```python
from lauren_mcp import McpServer, McpServerConfig
from lauren_ai import AgentModule

mcp_servers = [
    McpServerConfig(
        alias="fs",
        client=McpServer.stdio(
            ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        ),
    ),
]

# tools available to agent: fs__read_file, fs__write_file, fs__list_directory, ...
app.include_module(AgentModule.for_root(model="claude-opus-4-5", mcp_servers=mcp_servers))
```

## Documentation

- [Getting Started](https://mcp.lauren-py.dev/getting-started/)
- [MCP Server guide](https://mcp.lauren-py.dev/guides/mcp-server/)
- [MCP Client guide](https://mcp.lauren-py.dev/guides/mcp-client/)
- [Agent Tools guide](https://mcp.lauren-py.dev/guides/mcp-agent-tools/)
- [Testing guide](https://mcp.lauren-py.dev/guides/testing/)
- [API Reference](https://mcp.lauren-py.dev/reference/)
