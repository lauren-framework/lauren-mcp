"""E2E tests for docs/reference/server.md, docs/reference/client.md, and
docs/reference/types.md.

Every code example from the three reference pages is exercised end-to-end
so that inaccurate signatures or return types are caught immediately.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import textwrap

import pytest

from lauren_mcp import (
    McpCallError,
    McpClientProtocol,
    McpErrorCode,
    McpServer,
    McpServerConfig,
    McpToolBridge,
    build_error_response,
    mcp_server,
    mcp_tool,
    parse_message,
)
from lauren_mcp._client._stdio import McpStdioClient
from lauren_mcp._types import (
    JsonRpcErrorResponse,
    JsonRpcNotification,
    JsonRpcRequest,
    JsonRpcResponse,
    PromptSchema,
    ResourceSchema,
    ToolSchema,
)

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Inline server used by client reference tests
# ---------------------------------------------------------------------------
# All four decorators — matches the reference/server.md examples.

_REF_SERVER = textwrap.dedent("""\
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

    @mcp_server("/mcp")
    class RefServer:
        @mcp_tool(name="catalogue_search")
        async def search(self, query: str, limit: int = 10,
                         tags: list = None) -> list:
            "Search the product catalogue."
            items = [{"id": 1, "name": "Widget A"}, {"id": 2, "name": "Gadget B"}]
            return [i for i in items if query.lower() in i["name"].lower()]

        @mcp_tool()
        async def ping(self) -> str:
            "Return pong."
            return "pong"

        @mcp_resource("/orders/{order_id}", mime_type="application/json")
        async def get_order(self, order_id: str) -> str:
            "Return an order as a JSON string."
            return json.dumps({"id": int(order_id), "status": "open"})

        @mcp_prompt(name="product_analysis")
        async def product_analysis_prompt(self, category: str,
                                          tone: str = "professional") -> str:
            "Generate a product analysis prompt."
            return (
                f"Analyse the {category} product range in a {tone} tone. "
                "Include: market position, top 3 strengths, top 3 weaknesses, "
                "and a one-paragraph recommendation."
            )

    async def main():
        dispatcher = McpDispatcher()
        dispatcher._register_builtins()
        server = RefServer()
        tools, resources, prompts = [], [], []
        for n in dir(RefServer):
            attr = getattr(RefServer, n, None)
            if attr and hasattr(attr, MCP_TOOL_META):
                tools.append(getattr(attr, MCP_TOOL_META))
            if attr and hasattr(attr, MCP_RESOURCE_META):
                resources.append(getattr(attr, MCP_RESOURCE_META))
            if attr and hasattr(attr, MCP_PROMPT_META):
                prompts.append(getattr(attr, MCP_PROMPT_META))
        async def _init(p):
            return {"protocolVersion":"2025-03-26",
                    "capabilities":{"tools":{},"resources":{},"prompts":{}},
                    "serverInfo":{"name":"ref","version":"1.0.0"}}
        dispatcher.register("initialize", _init)
        tl = make_tools_list_handler(tools)
        tc = make_tools_call_handler(server, tools)
        async def _tl(p): return await tl(JsonRpcRequest(method="tools/list",params=p))
        async def _tc(p): return await tc(JsonRpcRequest(method="tools/call",params=p))
        dispatcher.register("tools/list", _tl)
        dispatcher.register("tools/call", _tc)
        rl = make_resources_list_handler(resources)
        rr = make_resources_read_handler(server, resources)
        async def _rl(p): return await rl(JsonRpcRequest(method="resources/list",params=p))
        async def _rr(p): return await rr(JsonRpcRequest(method="resources/read",params=p))
        dispatcher.register("resources/list", _rl)
        dispatcher.register("resources/read", _rr)
        pl = make_prompts_list_handler(prompts)
        pg = make_prompts_get_handler(server, prompts)
        async def _pl(p): return await pl(JsonRpcRequest(method="prompts/list",params=p))
        async def _pg(p): return await pg(JsonRpcRequest(method="prompts/get",params=p))
        dispatcher.register("prompts/list", _pl)
        dispatcher.register("prompts/get", _pg)
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        while True:
            try: line = await asyncio.wait_for(reader.readline(), timeout=30.0)
            except asyncio.TimeoutError: break
            if not line: break
            raw = line.decode().strip()
            if not raw: continue
            try: msg = json.loads(raw)
            except json.JSONDecodeError: continue
            id_ = msg.get("id")
            if id_ is None: continue
            req = JsonRpcRequest(method=msg.get("method",""), id=id_, params=msg.get("params"))
            resp = await dispatcher.dispatch(req)
            print(resp.to_json(), flush=True)
    asyncio.run(main())
""")


@pytest.fixture
def ref_server_cmd():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(_REF_SERVER)
        fname = f.name
    yield [sys.executable, fname]
    os.unlink(fname)


@pytest.fixture
async def ref_client(ref_server_cmd) -> McpStdioClient:
    c: McpStdioClient = McpServer.stdio(ref_server_cmd, startup_timeout=10.0, max_retries=0)
    await asyncio.wait_for(c.connect(), timeout=10.0)
    yield c
    await c.close()


# ---------------------------------------------------------------------------
# reference/server.md — decorator signatures
# ---------------------------------------------------------------------------


class TestServerReferenceDecorators:
    def test_mcp_server_signature_path_and_transport(self):
        @mcp_server("/test-ref")
        class _S: ...

        from lauren_mcp.server._meta import MCP_SERVER_META

        meta = getattr(_S, MCP_SERVER_META)
        assert meta.path == "/test-ref"
        assert meta.transport == "ws"

    def test_mcp_server_transport_sse(self):
        @mcp_server("/ref", transport="sse")
        class _S: ...

        from lauren_mcp.server._meta import MCP_SERVER_META

        assert getattr(_S, MCP_SERVER_META).transport == "sse"

    def test_mcp_tool_name_override(self):
        @mcp_server("/ref")
        class _S:
            @mcp_tool(name="catalogue_search")
            async def search(self, query: str) -> list:
                "Search. Args: query: q."
                return []

        from lauren_mcp.server._meta import MCP_TOOL_META

        meta = getattr(_S.search, MCP_TOOL_META)
        assert meta.name == "catalogue_search"

    def test_mcp_tool_required_vs_optional_schema(self, ref_client):
        # Verified via actual server: limit has default → not required; query has no default → required
        async def _check():
            tools = await asyncio.wait_for(ref_client.list_tools(), timeout=5.0)
            search = next(t for t in tools if t.name == "catalogue_search")
            required = search.inputSchema.get("required", [])
            assert "query" in required
            assert "limit" not in required

        asyncio.get_event_loop().run_until_complete(_check())

    async def test_mcp_tool_schema_types_in_inputschema(self, ref_client):
        tools = await asyncio.wait_for(ref_client.list_tools(), timeout=5.0)
        search = next(t for t in tools if t.name == "catalogue_search")
        props = search.inputSchema["properties"]
        assert props["query"]["type"] == "string"
        assert props["limit"]["type"] == "integer"

    async def test_mcp_resource_uri_template_registered(self, ref_client):
        resources = await asyncio.wait_for(ref_client.list_resources(), timeout=5.0)
        assert any("orders" in r.uri for r in resources)

    async def test_mcp_prompt_name_override(self, ref_client):
        prompts = await asyncio.wait_for(ref_client.list_prompts(), timeout=5.0)
        assert any(p.name == "product_analysis" for p in prompts)

    async def test_for_root_raises_on_plain_class(self):
        from lauren_mcp import McpServerModule

        class _Plain:
            pass

        with pytest.raises(TypeError):
            McpServerModule.for_root(_Plain)


# ---------------------------------------------------------------------------
# reference/client.md — McpServer factory signatures
# ---------------------------------------------------------------------------


class TestClientReferenceFactory:
    def test_stdio_returns_mcp_client_protocol(self, ref_server_cmd):
        c = McpServer.stdio(ref_server_cmd, max_retries=0, startup_timeout=5.0)
        assert isinstance(c, McpClientProtocol)

    def test_ws_returns_client_or_raises_import_error(self):
        # websockets may or may not be installed; both outcomes are correct.
        try:
            c = McpServer.ws("ws://example.com/mcp/ws", headers={"Authorization": "Bearer tok"})
            assert isinstance(c, McpClientProtocol)
        except ImportError as exc:
            # Documented: requires pip install "lauren-mcp[ws]"
            assert "lauren-mcp" in str(exc).lower() or "websocket" in str(exc).lower()

    def test_http_returns_client_or_raises_import_error(self):
        # httpx/httpx_sse may or may not be installed; both outcomes are correct.
        try:
            c = McpServer.http("http://example.com/mcp", headers={"X-Api-Key": "key"})
            assert isinstance(c, McpClientProtocol)
        except ImportError as exc:
            # Documented: requires pip install "lauren-mcp[http]"
            assert "lauren-mcp" in str(exc).lower() or "httpx" in str(exc).lower()

    def test_stdio_max_retries_zero(self, ref_server_cmd):
        c = McpServer.stdio(ref_server_cmd, max_retries=0, startup_timeout=10.0)
        assert c._max_retries == 0

    def test_stdio_max_retries_five(self, ref_server_cmd):
        c = McpServer.stdio(ref_server_cmd, max_retries=5, startup_timeout=10.0)
        assert c._max_retries == 5


class TestClientReferenceProtocol:
    async def test_list_tools_returns_tool_schema_instances(self, ref_client):
        tools = await asyncio.wait_for(ref_client.list_tools(), timeout=5.0)
        for t in tools:
            assert isinstance(t, ToolSchema)

    async def test_call_tool_returns_dict_with_content_and_is_error(self, ref_client):
        result = await asyncio.wait_for(
            ref_client.call_tool("catalogue_search", {"query": "widget"}), timeout=5.0
        )
        assert isinstance(result, dict)
        assert "content" in result
        assert "isError" in result

    async def test_call_tool_content_is_text_type(self, ref_client):
        result = await asyncio.wait_for(
            ref_client.call_tool("catalogue_search", {"query": "widget"}), timeout=5.0
        )
        content = result.get("content", [])
        assert content[0].get("type") == "text"

    async def test_call_tool_result_json_parseable(self, ref_client):
        result = await asyncio.wait_for(
            ref_client.call_tool("catalogue_search", {"query": "widget"}), timeout=5.0
        )
        text = result["content"][0]["text"]
        items = json.loads(text)
        assert isinstance(items, list)

    async def test_call_tool_is_not_error(self, ref_client):
        result = await asyncio.wait_for(ref_client.call_tool("ping", {}), timeout=5.0)
        assert result.get("isError") is False

    async def test_list_resources_returns_resource_schema_instances(self, ref_client):
        resources = await asyncio.wait_for(ref_client.list_resources(), timeout=5.0)
        for r in resources:
            assert isinstance(r, ResourceSchema)

    async def test_read_resource_returns_dict_with_contents(self, ref_client):
        result = await asyncio.wait_for(ref_client.read_resource("/orders/42"), timeout=5.0)
        assert isinstance(result, dict)
        assert "contents" in result

    async def test_read_resource_contents_has_text(self, ref_client):
        result = await asyncio.wait_for(ref_client.read_resource("/orders/1"), timeout=5.0)
        text = result["contents"][0].get("text", "")
        assert "status" in text  # JSON with "status" key

    async def test_list_prompts_returns_prompt_schema_instances(self, ref_client):
        prompts = await asyncio.wait_for(ref_client.list_prompts(), timeout=5.0)
        for p in prompts:
            assert isinstance(p, PromptSchema)

    async def test_get_prompt_returns_dict_with_messages(self, ref_client):
        result = await asyncio.wait_for(
            ref_client.get_prompt("product_analysis", {"category": "electronics"}),
            timeout=5.0,
        )
        assert isinstance(result, dict)
        assert "messages" in result
        assert len(result["messages"]) >= 1

    async def test_get_prompt_message_content_text_field(self, ref_client):
        result = await asyncio.wait_for(
            ref_client.get_prompt(
                "product_analysis",
                {"category": "electronics", "tone": "casual"},
            ),
            timeout=5.0,
        )
        msg = result["messages"][0]
        assert msg["role"] == "user"
        text = msg.get("content", {}).get("text", "")
        assert "electronics" in text
        assert "casual" in text

    async def test_ping_succeeds(self, ref_client):
        await asyncio.wait_for(ref_client.ping(), timeout=5.0)

    async def test_close_then_call_raises(self, ref_server_cmd):
        c = McpServer.stdio(ref_server_cmd, max_retries=0, startup_timeout=10.0)
        await asyncio.wait_for(c.connect(), timeout=10.0)
        await c.close()
        with pytest.raises(Exception):
            await asyncio.wait_for(c.list_tools(), timeout=2.0)


class TestClientReferenceCallError:
    async def test_mcp_call_error_is_publicly_exported(self):
        from lauren_mcp import McpCallError as _McpCallError

        assert _McpCallError is McpCallError

    async def test_mcp_call_error_has_code_attribute(self, ref_client):
        try:
            await asyncio.wait_for(ref_client.call_tool("nonexistent_tool", {}), timeout=5.0)
        except McpCallError as exc:
            assert hasattr(exc, "code")
            assert isinstance(exc.code, int)

    async def test_unknown_tool_raises_mcp_call_error(self, ref_client):
        with pytest.raises(McpCallError):
            await asyncio.wait_for(ref_client.call_tool("totally_nonexistent", {}), timeout=5.0)


class TestClientReferenceMcpServerConfig:
    def test_config_has_alias_and_client_fields(self, ref_server_cmd):
        client = McpServer.stdio(ref_server_cmd)
        config = McpServerConfig(alias="ref", client=client)
        assert config.alias == "ref"
        assert config.client is client

    def test_config_only_has_alias_and_client(self, ref_server_cmd):
        client = McpServer.stdio(ref_server_cmd)
        config = McpServerConfig(alias="ref", client=client)
        assert not hasattr(config, "description")
        assert not hasattr(config, "tool_filter")


class TestClientReferenceMcpToolBridge:
    async def test_bridge_connect_all_populates_registry(self, ref_server_cmd):

        class _Reg:
            def __init__(self):
                self.calls = []

            def register_mcp_server(self, alias, tools, client):
                self.calls.append((alias, tools, client))

        registry = _Reg()
        bridge = McpToolBridge(
            [McpServerConfig(alias="ref", client=McpServer.stdio(ref_server_cmd, max_retries=0))]
        )
        bridge.set_registry(registry)
        await asyncio.wait_for(bridge.connect_all(), timeout=15.0)
        assert registry.calls[0][0] == "ref"
        await bridge.disconnect_all()

    async def test_bridge_disconnect_all_closes_clients(self, ref_server_cmd):
        client = McpServer.stdio(ref_server_cmd, max_retries=0)
        bridge = McpToolBridge([McpServerConfig(alias="ref", client=client)])
        await asyncio.wait_for(bridge.connect_all(), timeout=15.0)
        await bridge.disconnect_all()
        with pytest.raises(Exception):
            await asyncio.wait_for(client.list_tools(), timeout=2.0)


# ---------------------------------------------------------------------------
# reference/types.md — types and utilities
# ---------------------------------------------------------------------------


class TestTypesReference:
    def test_mcp_error_code_values(self):
        assert McpErrorCode.PARSE_ERROR == -32700
        assert McpErrorCode.INVALID_REQUEST == -32600
        assert McpErrorCode.METHOD_NOT_FOUND == -32601
        assert McpErrorCode.INVALID_PARAMS == -32602
        assert McpErrorCode.INTERNAL_ERROR == -32603
        assert McpErrorCode.REQUEST_CANCELLED == -32800
        assert McpErrorCode.CONTENT_TOO_LARGE == -32801

    def test_mcp_error_code_no_fictional_values(self):
        code_names = {e.name for e in McpErrorCode}
        assert "TOOL_NOT_FOUND" not in code_names
        assert "RESOURCE_NOT_FOUND" not in code_names

    def test_parse_message_request(self):
        raw = '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
        msg = parse_message(raw)
        assert isinstance(msg, JsonRpcRequest)
        assert msg.id == 1
        assert msg.method == "tools/list"

    def test_parse_message_notification(self):
        raw = '{"jsonrpc":"2.0","method":"notifications/initialized"}'
        msg = parse_message(raw)
        assert isinstance(msg, JsonRpcNotification)

    def test_parse_message_response(self):
        raw = '{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}'
        msg = parse_message(raw)
        assert isinstance(msg, JsonRpcResponse)
        assert msg.result == {"tools": []}

    def test_parse_message_error_response(self):
        raw = '{"jsonrpc":"2.0","id":1,"error":{"code":-32601,"message":"Not found"}}'
        msg = parse_message(raw)
        assert isinstance(msg, JsonRpcErrorResponse)
        assert msg.error.code == -32601

    def test_parse_message_raises_on_bad_json(self):
        from lauren_mcp._types import McpParseError

        with pytest.raises((McpParseError, ValueError)):
            parse_message("not json at all")

    def test_build_error_response_signature(self):
        # reference doc uses parameter named 'id', not 'request_id'
        resp = build_error_response(
            id=42,
            code=McpErrorCode.INTERNAL_ERROR,
            message="Something went wrong",
        )
        assert isinstance(resp, JsonRpcErrorResponse)
        assert resp.id == 42
        assert resp.error.code == -32603
        assert resp.error.message == "Something went wrong"

    def test_build_error_response_none_id(self):
        resp = build_error_response(id=None, code=McpErrorCode.PARSE_ERROR, message="bad")
        assert resp.id is None
        assert resp.error.code == -32700

    def test_tool_schema_fields(self):
        t = ToolSchema(name="test", description="A test tool", inputSchema={"type": "object"})
        assert t.name == "test"
        assert t.description == "A test tool"
        assert t.inputSchema == {"type": "object"}

    def test_resource_schema_fields(self):
        r = ResourceSchema(uri="/items/1", name="item_1", description="An item")
        assert r.uri == "/items/1"
        assert r.name == "item_1"

    def test_prompt_schema_fields(self):
        p = PromptSchema(name="summary", description="Summarise")
        assert p.name == "summary"
        assert p.description == "Summarise"
