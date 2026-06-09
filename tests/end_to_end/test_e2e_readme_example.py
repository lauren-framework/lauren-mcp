"""End-to-end: CatalogueServer — the README Quick Start example.

Verifies that the exact server code shown in the README works correctly
over stdio, covering @mcp_tool, @mcp_resource, and @mcp_prompt.
Nothing is mocked: decorator metadata, schema generation, JSON serialisation,
subprocess I/O, client parsing, and result typing all run for real.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import textwrap

import pytest

from lauren_mcp import McpServer
from lauren_mcp._client._stdio import McpStdioClient
from lauren_mcp._types import PromptSchema, ResourceSchema, ToolSchema

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Subprocess server script — CatalogueServer (README Quick Start example)
# ---------------------------------------------------------------------------
# This is the exact code from the README, wired to the lower-level handler
# factories so it can serve JSON-RPC over stdin/stdout without a full Lauren
# web server.  The decorator behaviour, schema generation, and tool/resource/
# prompt dispatch are all production code paths.
# Note: inner docstrings use single quotes to avoid terminating the outer """.

_CATALOGUE_SERVER_SCRIPT = textwrap.dedent("""\
    import sys, json, asyncio

    from lauren_mcp.server._decorators import (
        mcp_server, mcp_tool, mcp_resource, mcp_prompt,
    )
    from lauren_mcp.server._meta import (
        MCP_TOOL_META, MCP_RESOURCE_META, MCP_PROMPT_META,
    )
    from lauren_mcp.server._handlers import (
        make_tools_list_handler, make_tools_call_handler,
        make_resources_list_handler, make_resources_read_handler,
        make_prompts_list_handler, make_prompts_get_handler,
    )
    from lauren_mcp._server._dispatcher import McpDispatcher
    from lauren_mcp._types import JsonRpcRequest

    CATALOGUE = [
        {"id": 1, "name": "Widget A", "price": 9.99},
        {"id": 2, "name": "Widget B", "price": 14.99},
        {"id": 3, "name": "Gadget C", "price": 24.99},
    ]

    @mcp_server("/mcp")
    class CatalogueServer:
        @mcp_tool()
        async def search(self, query: str) -> list:
            "Search the catalogue by name."
            return [i for i in CATALOGUE if query.lower() in i["name"].lower()]

        @mcp_tool()
        async def get_item(self, item_id: int) -> dict:
            "Get a single item by ID."
            return next((i for i in CATALOGUE if i["id"] == item_id), None)

        @mcp_resource("/catalogue/{item_id}")
        async def item_resource(self, item_id: str) -> str:
            "Expose a catalogue item as a readable MCP resource."
            item = next(
                (i for i in CATALOGUE if i["id"] == int(item_id)), None
            )
            if item is None:
                return f"Item {item_id} not found."
            return f"{item[\'name\']} -- ${item[\'price\']:.2f}"

        @mcp_prompt()
        async def recommend(self, budget: str) -> str:
            "Generate a recommendation prompt for a given budget."
            affordable = [
                i for i in CATALOGUE if i["price"] <= float(budget)
            ]
            names = ", ".join(i["name"] for i in affordable) or "none"
            return (
                f"Recommend a product to a customer"
                f" with ${budget} budget: {names}"
            )


    async def main():
        dispatcher = McpDispatcher()
        dispatcher._register_builtins()
        server = CatalogueServer()

        tools, resources, prompts = [], [], []
        for attr_name in dir(CatalogueServer):
            try:
                attr = getattr(CatalogueServer, attr_name)
            except AttributeError:
                continue
            if hasattr(attr, MCP_TOOL_META):
                tools.append(getattr(attr, MCP_TOOL_META))
            if hasattr(attr, MCP_RESOURCE_META):
                resources.append(getattr(attr, MCP_RESOURCE_META))
            if hasattr(attr, MCP_PROMPT_META):
                prompts.append(getattr(attr, MCP_PROMPT_META))

        async def _init(params):
            return {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                "serverInfo": {"name": "catalogue-server", "version": "1.0.0"},
            }
        dispatcher.register("initialize", _init)

        tl = make_tools_list_handler(tools)
        tc = make_tools_call_handler(server, tools)
        async def _tl(p): return await tl(JsonRpcRequest(method="tools/list", params=p))
        async def _tc(p): return await tc(JsonRpcRequest(method="tools/call", params=p))
        dispatcher.register("tools/list", _tl)
        dispatcher.register("tools/call", _tc)

        rl = make_resources_list_handler(resources)
        rr = make_resources_read_handler(server, resources)
        async def _rl(p): return await rl(JsonRpcRequest(method="resources/list", params=p))
        async def _rr(p): return await rr(JsonRpcRequest(method="resources/read", params=p))
        dispatcher.register("resources/list", _rl)
        dispatcher.register("resources/read", _rr)

        pl = make_prompts_list_handler(prompts)
        pg = make_prompts_get_handler(server, prompts)
        async def _pl(p): return await pl(JsonRpcRequest(method="prompts/list", params=p))
        async def _pg(p): return await pg(JsonRpcRequest(method="prompts/get", params=p))
        dispatcher.register("prompts/list", _pl)
        dispatcher.register("prompts/get", _pg)

        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        while True:
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=30.0)
            except asyncio.TimeoutError:
                break
            if not line:
                break
            raw = line.decode().strip()
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            id_ = msg.get("id")
            if id_ is None:
                continue
            req = JsonRpcRequest(
                method=msg.get("method", ""), id=id_, params=msg.get("params")
            )
            resp = await dispatcher.dispatch(req)
            print(resp.to_json(), flush=True)


    asyncio.run(main())
""")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def catalogue_server_command():
    """Return argv that launches the CatalogueServer over stdin/stdout."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(_CATALOGUE_SERVER_SCRIPT)
        fname = f.name
    yield [sys.executable, fname]
    os.unlink(fname)


@pytest.fixture
async def catalogue_client(catalogue_server_command):
    """Connected McpStdioClient backed by the CatalogueServer subprocess."""
    client: McpStdioClient = McpServer.stdio(catalogue_server_command)
    await asyncio.wait_for(client.connect(), timeout=10.0)
    yield client
    await client.close()


# ---------------------------------------------------------------------------
# Tool discovery
# ---------------------------------------------------------------------------


class TestToolDiscovery:
    async def test_list_tools_returns_two_tools(self, catalogue_client):
        tools = await asyncio.wait_for(catalogue_client.list_tools(), timeout=5.0)
        assert len(tools) == 2

    async def test_tool_names_are_search_and_get_item(self, catalogue_client):
        tools = await asyncio.wait_for(catalogue_client.list_tools(), timeout=5.0)
        names = {t.name for t in tools}
        assert names == {"search", "get_item"}

    async def test_tools_are_tool_schema_instances(self, catalogue_client):
        tools = await asyncio.wait_for(catalogue_client.list_tools(), timeout=5.0)
        for t in tools:
            assert isinstance(t, ToolSchema)

    async def test_search_input_schema_type_is_object(self, catalogue_client):
        tools = await asyncio.wait_for(catalogue_client.list_tools(), timeout=5.0)
        search = next(t for t in tools if t.name == "search")
        assert search.inputSchema.get("type") == "object"

    async def test_search_schema_has_query_property(self, catalogue_client):
        tools = await asyncio.wait_for(catalogue_client.list_tools(), timeout=5.0)
        search = next(t for t in tools if t.name == "search")
        assert "query" in search.inputSchema.get("properties", {})

    async def test_search_schema_query_is_required(self, catalogue_client):
        tools = await asyncio.wait_for(catalogue_client.list_tools(), timeout=5.0)
        search = next(t for t in tools if t.name == "search")
        assert "query" in search.inputSchema.get("required", [])

    async def test_search_schema_query_type_is_string(self, catalogue_client):
        tools = await asyncio.wait_for(catalogue_client.list_tools(), timeout=5.0)
        search = next(t for t in tools if t.name == "search")
        assert search.inputSchema["properties"]["query"]["type"] == "string"

    async def test_get_item_schema_has_item_id_property(self, catalogue_client):
        tools = await asyncio.wait_for(catalogue_client.list_tools(), timeout=5.0)
        get_item = next(t for t in tools if t.name == "get_item")
        assert "item_id" in get_item.inputSchema.get("properties", {})

    async def test_get_item_schema_item_id_type_is_integer(self, catalogue_client):
        tools = await asyncio.wait_for(catalogue_client.list_tools(), timeout=5.0)
        get_item = next(t for t in tools if t.name == "get_item")
        assert get_item.inputSchema["properties"]["item_id"]["type"] == "integer"

    async def test_get_item_schema_item_id_is_required(self, catalogue_client):
        tools = await asyncio.wait_for(catalogue_client.list_tools(), timeout=5.0)
        get_item = next(t for t in tools if t.name == "get_item")
        assert "item_id" in get_item.inputSchema.get("required", [])

    async def test_tool_descriptions_derived_from_docstrings(self, catalogue_client):
        tools = await asyncio.wait_for(catalogue_client.list_tools(), timeout=5.0)
        search = next(t for t in tools if t.name == "search")
        assert search.description
        assert "Search" in search.description


# ---------------------------------------------------------------------------
# Tool invocation
# ---------------------------------------------------------------------------


class TestToolInvocation:
    async def test_search_widget_returns_two_items(self, catalogue_client):
        result = await asyncio.wait_for(
            catalogue_client.call_tool("search", {"query": "Widget"}), timeout=5.0
        )
        text = next(c["text"] for c in result["content"] if c.get("type") == "text")
        assert len(json.loads(text)) == 2

    async def test_search_gadget_returns_one_item(self, catalogue_client):
        result = await asyncio.wait_for(
            catalogue_client.call_tool("search", {"query": "Gadget"}), timeout=5.0
        )
        text = next(c["text"] for c in result["content"] if c.get("type") == "text")
        data = json.loads(text)
        assert len(data) == 1
        assert data[0]["name"] == "Gadget C"

    async def test_search_case_insensitive(self, catalogue_client):
        r_lower = await asyncio.wait_for(
            catalogue_client.call_tool("search", {"query": "widget"}), timeout=5.0
        )
        r_upper = await asyncio.wait_for(
            catalogue_client.call_tool("search", {"query": "WIDGET"}), timeout=5.0
        )
        t1 = next(c["text"] for c in r_lower["content"] if c.get("type") == "text")
        t2 = next(c["text"] for c in r_upper["content"] if c.get("type") == "text")
        assert json.loads(t1) == json.loads(t2)

    async def test_search_no_match_returns_empty_list(self, catalogue_client):
        result = await asyncio.wait_for(
            catalogue_client.call_tool("search", {"query": "Unicorn"}), timeout=5.0
        )
        text = next(c["text"] for c in result["content"] if c.get("type") == "text")
        assert json.loads(text) == []

    async def test_get_item_id_1_returns_widget_a(self, catalogue_client):
        result = await asyncio.wait_for(
            catalogue_client.call_tool("get_item", {"item_id": 1}), timeout=5.0
        )
        text = next(c["text"] for c in result["content"] if c.get("type") == "text")
        data = json.loads(text)
        assert data["name"] == "Widget A"
        assert data["id"] == 1

    async def test_get_item_id_3_returns_gadget_c_with_price(self, catalogue_client):
        result = await asyncio.wait_for(
            catalogue_client.call_tool("get_item", {"item_id": 3}), timeout=5.0
        )
        text = next(c["text"] for c in result["content"] if c.get("type") == "text")
        data = json.loads(text)
        assert data["name"] == "Gadget C"
        assert data["price"] == 24.99

    async def test_get_item_nonexistent_returns_none_string(self, catalogue_client):
        result = await asyncio.wait_for(
            catalogue_client.call_tool("get_item", {"item_id": 999}), timeout=5.0
        )
        text = next(c["text"] for c in result["content"] if c.get("type") == "text")
        assert text == "None"

    async def test_search_result_is_not_error(self, catalogue_client):
        result = await asyncio.wait_for(
            catalogue_client.call_tool("search", {"query": "Widget"}), timeout=5.0
        )
        assert result.get("isError") is False

    async def test_sequential_calls_return_independent_results(self, catalogue_client):
        r1 = await asyncio.wait_for(
            catalogue_client.call_tool("search", {"query": "Widget"}), timeout=5.0
        )
        r2 = await asyncio.wait_for(
            catalogue_client.call_tool("search", {"query": "Gadget"}), timeout=5.0
        )
        t1 = next(c["text"] for c in r1["content"] if c.get("type") == "text")
        t2 = next(c["text"] for c in r2["content"] if c.get("type") == "text")
        assert len(json.loads(t1)) == 2
        assert len(json.loads(t2)) == 1


# ---------------------------------------------------------------------------
# Resource discovery and reading
# ---------------------------------------------------------------------------


class TestResources:
    async def test_list_resources_returns_one_resource(self, catalogue_client):
        resources = await asyncio.wait_for(catalogue_client.list_resources(), timeout=5.0)
        assert len(resources) == 1

    async def test_resource_is_resource_schema_instance(self, catalogue_client):
        resources = await asyncio.wait_for(catalogue_client.list_resources(), timeout=5.0)
        assert isinstance(resources[0], ResourceSchema)

    async def test_resource_uri_template_contains_catalogue(self, catalogue_client):
        resources = await asyncio.wait_for(catalogue_client.list_resources(), timeout=5.0)
        assert "catalogue" in resources[0].uri

    async def test_read_resource_item_1_contains_widget_a(self, catalogue_client):
        result = await asyncio.wait_for(catalogue_client.read_resource("/catalogue/1"), timeout=5.0)
        text = next(c.get("text", "") for c in result.get("contents", []) if "text" in c)
        assert "Widget A" in text

    async def test_read_resource_item_1_contains_price(self, catalogue_client):
        result = await asyncio.wait_for(catalogue_client.read_resource("/catalogue/1"), timeout=5.0)
        text = next(c.get("text", "") for c in result.get("contents", []) if "text" in c)
        assert "9.99" in text

    async def test_read_resource_item_2_contains_widget_b(self, catalogue_client):
        result = await asyncio.wait_for(catalogue_client.read_resource("/catalogue/2"), timeout=5.0)
        text = next(c.get("text", "") for c in result.get("contents", []) if "text" in c)
        assert "Widget B" in text

    async def test_read_resource_item_3_contains_gadget_c(self, catalogue_client):
        result = await asyncio.wait_for(catalogue_client.read_resource("/catalogue/3"), timeout=5.0)
        text = next(c.get("text", "") for c in result.get("contents", []) if "text" in c)
        assert "Gadget C" in text

    async def test_read_resource_unknown_id_returns_not_found(self, catalogue_client):
        result = await asyncio.wait_for(
            catalogue_client.read_resource("/catalogue/999"), timeout=5.0
        )
        text = next(c.get("text", "") for c in result.get("contents", []) if "text" in c)
        assert "not found" in text.lower()

    async def test_read_resource_different_items_give_different_text(self, catalogue_client):
        r1 = await asyncio.wait_for(catalogue_client.read_resource("/catalogue/1"), timeout=5.0)
        r3 = await asyncio.wait_for(catalogue_client.read_resource("/catalogue/3"), timeout=5.0)
        t1 = next(c.get("text", "") for c in r1.get("contents", []) if "text" in c)
        t3 = next(c.get("text", "") for c in r3.get("contents", []) if "text" in c)
        assert t1 != t3


# ---------------------------------------------------------------------------
# Prompt discovery and retrieval
# ---------------------------------------------------------------------------


class TestPrompt:
    async def test_list_prompts_returns_one_prompt(self, catalogue_client):
        prompts = await asyncio.wait_for(catalogue_client.list_prompts(), timeout=5.0)
        assert len(prompts) == 1

    async def test_prompt_is_prompt_schema_instance(self, catalogue_client):
        prompts = await asyncio.wait_for(catalogue_client.list_prompts(), timeout=5.0)
        assert isinstance(prompts[0], PromptSchema)

    async def test_prompt_name_is_recommend(self, catalogue_client):
        prompts = await asyncio.wait_for(catalogue_client.list_prompts(), timeout=5.0)
        assert prompts[0].name == "recommend"

    async def test_get_prompt_returns_messages_list(self, catalogue_client):
        result = await asyncio.wait_for(
            catalogue_client.get_prompt("recommend", {"budget": "20"}), timeout=5.0
        )
        assert "messages" in result
        assert len(result["messages"]) >= 1

    async def test_get_prompt_message_role_is_user(self, catalogue_client):
        result = await asyncio.wait_for(
            catalogue_client.get_prompt("recommend", {"budget": "20"}), timeout=5.0
        )
        assert result["messages"][0]["role"] == "user"

    async def test_get_prompt_budget_20_includes_widget_a_and_b(self, catalogue_client):
        result = await asyncio.wait_for(
            catalogue_client.get_prompt("recommend", {"budget": "20"}), timeout=5.0
        )
        text = str(result["messages"])
        assert "Widget A" in text
        assert "Widget B" in text

    async def test_get_prompt_budget_20_excludes_gadget_c(self, catalogue_client):
        result = await asyncio.wait_for(
            catalogue_client.get_prompt("recommend", {"budget": "20"}), timeout=5.0
        )
        assert "Gadget C" not in str(result["messages"])

    async def test_get_prompt_budget_30_includes_all_items(self, catalogue_client):
        result = await asyncio.wait_for(
            catalogue_client.get_prompt("recommend", {"budget": "30"}), timeout=5.0
        )
        text = str(result["messages"])
        assert "Widget A" in text
        assert "Widget B" in text
        assert "Gadget C" in text

    async def test_get_prompt_budget_5_returns_none_in_message(self, catalogue_client):
        result = await asyncio.wait_for(
            catalogue_client.get_prompt("recommend", {"budget": "5"}), timeout=5.0
        )
        assert "none" in str(result["messages"]).lower()


# ---------------------------------------------------------------------------
# Ping
# ---------------------------------------------------------------------------


class TestPing:
    async def test_ping_completes_without_error(self, catalogue_client):
        await asyncio.wait_for(catalogue_client.ping(), timeout=5.0)

    async def test_ping_after_tool_and_resource_calls(self, catalogue_client):
        await asyncio.wait_for(
            catalogue_client.call_tool("search", {"query": "Widget"}), timeout=5.0
        )
        await asyncio.wait_for(catalogue_client.read_resource("/catalogue/1"), timeout=5.0)
        await asyncio.wait_for(catalogue_client.ping(), timeout=5.0)
