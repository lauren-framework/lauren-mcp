"""E2E tests for docs/guides/decorators.md.

Validates every code example in the decorators guide: @mcp_server options,
@mcp_tool parameter types (required/optional/default), @mcp_resource URI
templates and MIME types, @mcp_prompt string and list returns, schema
generation, and the combined ShopServer example.
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

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# ShopServer — the "Putting it all together" example from decorators.md
# ---------------------------------------------------------------------------

_SHOP_SERVER = textwrap.dedent("""\
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

    PRODUCTS = [
        {"id": "p1", "name": "Laptop Pro", "price": 999.0, "category": "electronics"},
        {"id": "p2", "name": "Wireless Mouse", "price": 29.99, "category": "electronics"},
        {"id": "p3", "name": "Notebook", "price": 4.99, "category": "stationery"},
    ]

    @mcp_server("/mcp")
    class ShopServer:
        @mcp_tool()
        async def search(self, query: str, category: str = None) -> list:
            "Search products by name."
            results = [p for p in PRODUCTS if query.lower() in p["name"].lower()]
            if category:
                results = [p for p in results if p["category"] == category]
            return results

        @mcp_tool()
        async def get_product(self, product_id: str) -> dict:
            "Fetch a product by its ID."
            return next((p for p in PRODUCTS if p["id"] == product_id), None)

        @mcp_tool()
        async def create_order(self, product_id: str, quantity: int,
                               discount: float = 0.0, notes: str = None) -> dict:
            "Create an order with optional discount and notes."
            return {
                "product_id": product_id,
                "quantity": quantity,
                "discount": discount,
                "notes": notes,
                "status": "created",
            }

        @mcp_resource("/products/{product_id}")
        async def product_card(self, product_id: str) -> str:
            "One-line product card."
            p = next((p for p in PRODUCTS if p["id"] == product_id), None)
            if p is None:
                return f"Product {product_id!r} not found."
            return f"{p[\'name\']} -- ${p[\'price\']:.2f} ({p[\'category\']})"

        @mcp_prompt()
        async def recommend(self, budget: str) -> str:
            "Recommendation prompt."
            affordable = [p for p in PRODUCTS if p["price"] <= float(budget)]
            names = ", ".join(p["name"] for p in affordable) or "none"
            return (
                f"Recommend a product to a customer with a ${budget} budget. "
                f"Available items: {names}."
            )

        @mcp_prompt()
        async def code_review(self, language: str, code: str) -> list:
            "Multi-turn code review prompt."
            text = f"Please review this {language} code: {code}"
            return [{"role": "user", "content": {"type": "text", "text": text}}]


    async def main():
        dispatcher = McpDispatcher()
        dispatcher._register_builtins()
        server = ShopServer()

        tools, resources, prompts = [], [], []
        for attr_name in dir(ShopServer):
            try:
                attr = getattr(ShopServer, attr_name)
            except AttributeError:
                continue
            if hasattr(attr, MCP_TOOL_META):
                tools.append(getattr(attr, MCP_TOOL_META))
            if hasattr(attr, MCP_RESOURCE_META):
                resources.append(getattr(attr, MCP_RESOURCE_META))
            if hasattr(attr, MCP_PROMPT_META):
                prompts.append(getattr(attr, MCP_PROMPT_META))

        async def _init(params):
            return {"protocolVersion": "2025-03-26",
                    "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                    "serverInfo": {"name": "shop", "version": "1.0.0"}}
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


@pytest.fixture
def shop_cmd():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(_SHOP_SERVER)
        fname = f.name
    yield [sys.executable, fname]
    os.unlink(fname)


@pytest.fixture
async def shop_client(shop_cmd):
    c: McpStdioClient = McpServer.stdio(shop_cmd, startup_timeout=10.0, max_retries=0)
    await asyncio.wait_for(c.connect(), timeout=10.0)
    yield c
    await c.close()


# ---------------------------------------------------------------------------
# @mcp_tool — search (required param) and create_order (required + optional)
# ---------------------------------------------------------------------------


class TestMcpTool:
    async def test_search_required_param_present(self, shop_client):
        tools = await asyncio.wait_for(shop_client.list_tools(), timeout=5.0)
        search = next(t for t in tools if t.name == "search")
        assert "query" in search.inputSchema.get("required", [])

    async def test_search_optional_category_not_required(self, shop_client):
        tools = await asyncio.wait_for(shop_client.list_tools(), timeout=5.0)
        search = next(t for t in tools if t.name == "search")
        assert "category" not in search.inputSchema.get("required", [])

    async def test_create_order_required_params(self, shop_client):
        tools = await asyncio.wait_for(shop_client.list_tools(), timeout=5.0)
        create = next(t for t in tools if t.name == "create_order")
        required = create.inputSchema.get("required", [])
        assert "product_id" in required
        assert "quantity" in required

    async def test_create_order_optional_params_not_required(self, shop_client):
        tools = await asyncio.wait_for(shop_client.list_tools(), timeout=5.0)
        create = next(t for t in tools if t.name == "create_order")
        required = create.inputSchema.get("required", [])
        assert "discount" not in required
        assert "notes" not in required

    async def test_search_without_category(self, shop_client):
        result = await asyncio.wait_for(
            shop_client.call_tool("search", {"query": "laptop"}), timeout=5.0
        )
        products = json.loads(result["content"][0]["text"])
        assert len(products) == 1
        assert products[0]["name"] == "Laptop Pro"

    async def test_create_order_with_required_only(self, shop_client):
        result = await asyncio.wait_for(
            shop_client.call_tool("create_order", {"product_id": "p1", "quantity": 2}),
            timeout=5.0,
        )
        order = json.loads(result["content"][0]["text"])
        assert order["product_id"] == "p1"
        assert order["quantity"] == 2
        assert order["discount"] == 0.0
        assert order["notes"] is None

    async def test_create_order_with_all_params(self, shop_client):
        result = await asyncio.wait_for(
            shop_client.call_tool(
                "create_order",
                {"product_id": "p2", "quantity": 1, "discount": 10.0, "notes": "gift"},
            ),
            timeout=5.0,
        )
        order = json.loads(result["content"][0]["text"])
        assert order["discount"] == 10.0
        assert order["notes"] == "gift"

    async def test_get_product_by_id(self, shop_client):
        result = await asyncio.wait_for(
            shop_client.call_tool("get_product", {"product_id": "p1"}),
            timeout=5.0,
        )
        product = json.loads(result["content"][0]["text"])
        assert product["name"] == "Laptop Pro"
        assert product["price"] == 999.0

    async def test_get_product_not_found_returns_none(self, shop_client):
        result = await asyncio.wait_for(
            shop_client.call_tool("get_product", {"product_id": "zzz"}),
            timeout=5.0,
        )
        assert result["content"][0]["text"] == "None"


# ---------------------------------------------------------------------------
# @mcp_resource — URI template, MIME type, not-found handling
# ---------------------------------------------------------------------------


class TestMcpResource:
    async def test_resource_uri_template_registered(self, shop_client):
        resources = await asyncio.wait_for(shop_client.list_resources(), timeout=5.0)
        assert any("products" in r.uri for r in resources)

    async def test_read_resource_p1(self, shop_client):
        result = await asyncio.wait_for(shop_client.read_resource("/products/p1"), timeout=5.0)
        text = result["contents"][0]["text"]
        assert "Laptop Pro" in text
        assert "999.00" in text
        assert "electronics" in text

    async def test_read_resource_p3(self, shop_client):
        result = await asyncio.wait_for(shop_client.read_resource("/products/p3"), timeout=5.0)
        text = result["contents"][0]["text"]
        assert "Notebook" in text
        assert "stationery" in text

    async def test_read_resource_not_found(self, shop_client):
        result = await asyncio.wait_for(shop_client.read_resource("/products/zzz"), timeout=5.0)
        text = result["contents"][0]["text"]
        assert "not found" in text.lower()

    async def test_different_ids_give_different_text(self, shop_client):
        r1 = await asyncio.wait_for(shop_client.read_resource("/products/p1"), timeout=5.0)
        r2 = await asyncio.wait_for(shop_client.read_resource("/products/p2"), timeout=5.0)
        assert r1["contents"][0]["text"] != r2["contents"][0]["text"]


# ---------------------------------------------------------------------------
# @mcp_prompt — string return and list return
# ---------------------------------------------------------------------------


class TestMcpPrompt:
    async def test_recommend_returns_user_message(self, shop_client):
        result = await asyncio.wait_for(
            shop_client.get_prompt("recommend", {"budget": "50"}), timeout=5.0
        )
        assert result["messages"][0]["role"] == "user"

    async def test_recommend_budget_50_includes_mouse_and_notebook(self, shop_client):
        result = await asyncio.wait_for(
            shop_client.get_prompt("recommend", {"budget": "50"}), timeout=5.0
        )
        text = str(result["messages"])
        assert "Mouse" in text
        assert "Notebook" in text

    async def test_recommend_budget_50_excludes_laptop(self, shop_client):
        result = await asyncio.wait_for(
            shop_client.get_prompt("recommend", {"budget": "50"}), timeout=5.0
        )
        text = str(result["messages"])
        assert "Laptop Pro" not in text

    async def test_recommend_budget_1000_includes_all(self, shop_client):
        result = await asyncio.wait_for(
            shop_client.get_prompt("recommend", {"budget": "1000"}), timeout=5.0
        )
        text = str(result["messages"])
        assert "Laptop Pro" in text

    async def test_code_review_multi_turn_list_return(self, shop_client):
        # Guide section: "Return a message list"
        result = await asyncio.wait_for(
            shop_client.get_prompt("code_review", {"language": "Python", "code": "x = 1/0"}),
            timeout=5.0,
        )
        messages = result["messages"]
        assert len(messages) >= 1
        assert messages[0]["role"] == "user"
        text = messages[0]["content"]["text"]
        assert "Python" in text
        assert "x = 1/0" in text


# ---------------------------------------------------------------------------
# Schema generation — type mapping table from the guide
# ---------------------------------------------------------------------------


class TestSchemaTypeMapping:
    async def test_string_type_annotation(self, shop_client):
        tools = await asyncio.wait_for(shop_client.list_tools(), timeout=5.0)
        search = next(t for t in tools if t.name == "search")
        assert search.inputSchema["properties"]["query"]["type"] == "string"

    async def test_string_product_id_type(self, shop_client):
        tools = await asyncio.wait_for(shop_client.list_tools(), timeout=5.0)
        get_p = next(t for t in tools if t.name == "get_product")
        assert get_p.inputSchema["properties"]["product_id"]["type"] == "string"

    async def test_integer_quantity_type(self, shop_client):
        tools = await asyncio.wait_for(shop_client.list_tools(), timeout=5.0)
        create = next(t for t in tools if t.name == "create_order")
        assert create.inputSchema["properties"]["quantity"]["type"] == "integer"

    async def test_number_discount_type(self, shop_client):
        tools = await asyncio.wait_for(shop_client.list_tools(), timeout=5.0)
        create = next(t for t in tools if t.name == "create_order")
        assert create.inputSchema["properties"]["discount"]["type"] == "number"

    async def test_all_tool_schemas_have_object_type(self, shop_client):
        tools = await asyncio.wait_for(shop_client.list_tools(), timeout=5.0)
        for t in tools:
            assert t.inputSchema.get("type") == "object"
