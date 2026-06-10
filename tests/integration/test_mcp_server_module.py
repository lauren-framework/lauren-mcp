"""Integration tests: McpServerModule.for_root() and handler registration flow.

These tests instantiate McpDispatcher directly and wire up handlers manually
so we can verify the full dispatch round-trip without a Lauren DI container.
"""

from __future__ import annotations

import pytest

from lauren_mcp._server._dispatcher import McpDispatcher
from lauren_mcp._types import (
    JsonRpcErrorResponse,
    JsonRpcRequest,
    JsonRpcResponse,
    McpErrorCode,
)
from lauren_mcp.server._decorators import mcp_prompt, mcp_resource, mcp_server, mcp_tool
from lauren_mcp.server._meta import (
    MCP_SERVER_META,
    McpServerMeta,
)
from lauren_mcp.server._module import McpServerModule

# Only async test methods are individually async; sync tests use no mark.


# ---------------------------------------------------------------------------
# Shared test server classes
# ---------------------------------------------------------------------------


@mcp_server("/mcp")
class CalcServer:
    @mcp_tool()
    async def add(self, a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    @mcp_tool()
    async def multiply(self, x: int, y: int) -> int:
        """Multiply two numbers."""
        return x * y

    @mcp_resource("/files/{path}")
    async def read_file(self, path: str) -> str:
        """Read a file by path."""
        return f"contents of {path}"

    @mcp_prompt()
    async def greet(self, name: str) -> str:
        """Greet someone."""
        return f"Hello {name}"


@mcp_server("/mcp-tools-only")
class ToolsOnlyServer:
    @mcp_tool()
    async def echo(self, text: str) -> str:
        """Echo text back."""
        return text


@mcp_server("/mcp-empty")
class EmptyServer:
    """A server with no tools, resources, or prompts."""

    pass


@mcp_server("/mcp-resources")
class ResourceServer:
    @mcp_resource("/data/{id}")
    async def get_data(self, id: str) -> str:
        """Get data by id."""
        return f"data-{id}"


@mcp_server("/mcp-prompts")
class PromptServer:
    @mcp_prompt()
    async def suggest(self, topic: str) -> str:
        """Suggest something about topic."""
        return f"Suggestion about {topic}"


# ---------------------------------------------------------------------------
# Helper: build a dispatcher wired up by a module's _register_handlers
# ---------------------------------------------------------------------------


async def build_wired_dispatcher(
    server_cls: type, **for_root_kwargs
) -> tuple[McpDispatcher, object]:
    """Create a module, instantiate dispatcher + server directly, call _register_handlers."""
    from lauren_mcp._server._catalog import McpCatalogManager
    from lauren_mcp._server._registry import McpConnectionRegistry

    mod_cls = McpServerModule.for_root(server_cls, **for_root_kwargs)
    dispatcher = McpDispatcher()
    dispatcher._register_builtins()
    server_instance = server_cls()
    # Bypass DI: instantiate the handler registrar directly and call its post_construct.
    # The registrar class is stored on the module by for_root() for exactly this use.
    registrar_cls = mod_cls._handler_registrar_cls  # type: ignore[attr-defined]
    registrar = registrar_cls(
        dispatcher, McpConnectionRegistry(), McpCatalogManager(), server_instance
    )
    await registrar._register_handlers()
    return dispatcher, server_instance


def make_req(method: str, id_=1, params=None) -> JsonRpcRequest:
    return JsonRpcRequest(method=method, id=id_, params=params)


# ---------------------------------------------------------------------------
# Tests: for_root() validation
# ---------------------------------------------------------------------------


class TestForRootValidation:
    def test_raises_type_error_for_undecorated_class(self):
        class Plain:
            pass

        with pytest.raises(TypeError, match="mcp_server"):
            McpServerModule.for_root(Plain)

    def test_returns_a_class_for_valid_server(self):
        mod = McpServerModule.for_root(ToolsOnlyServer)
        assert isinstance(mod, type)

    def test_module_has_lauren_module_meta(self):
        from lauren.decorators import MODULE_META

        mod = McpServerModule.for_root(ToolsOnlyServer)
        assert hasattr(mod, MODULE_META)

    def test_module_providers_include_dispatcher(self):
        from lauren.decorators import MODULE_META

        mod = McpServerModule.for_root(CalcServer)
        meta = getattr(mod, MODULE_META)
        assert McpDispatcher in meta.providers

    def test_module_providers_include_server_class(self):
        from lauren.decorators import MODULE_META

        mod = McpServerModule.for_root(CalcServer)
        meta = getattr(mod, MODULE_META)
        assert CalcServer in meta.providers

    def test_module_has_qualname_with_server_class_name(self):
        mod = McpServerModule.for_root(CalcServer)
        assert "CalcServer" in mod.__qualname__


# ---------------------------------------------------------------------------
# Tests: ServerCapabilities inference
# ---------------------------------------------------------------------------


class TestServerCapabilities:
    async def test_capabilities_include_tools_when_tools_present(self):
        """A server with tools should have tools in auto-inferred capabilities."""
        dispatcher, _ = await build_wired_dispatcher(CalcServer)
        resp = await dispatcher.dispatch(
            make_req(
                "initialize",
                id_=1,
                params={
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "0"},
                },
            )
        )
        assert isinstance(resp, JsonRpcResponse)
        assert "tools" in resp.result.get("capabilities", {})

    async def test_capabilities_include_resources_when_resources_present(self):
        dispatcher, _ = await build_wired_dispatcher(CalcServer)
        resp = await dispatcher.dispatch(
            make_req(
                "initialize",
                id_=2,
                params={
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "0"},
                },
            )
        )
        assert isinstance(resp, JsonRpcResponse)
        assert "resources" in resp.result.get("capabilities", {})

    async def test_capabilities_include_prompts_when_prompts_present(self):
        dispatcher, _ = await build_wired_dispatcher(CalcServer)
        resp = await dispatcher.dispatch(
            make_req(
                "initialize",
                id_=3,
                params={
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "0"},
                },
            )
        )
        assert isinstance(resp, JsonRpcResponse)
        assert "prompts" in resp.result.get("capabilities", {})

    async def test_capabilities_no_tools_when_no_tool_methods(self):
        dispatcher, _ = await build_wired_dispatcher(EmptyServer)
        resp = await dispatcher.dispatch(
            make_req(
                "initialize",
                id_=4,
                params={
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "0"},
                },
            )
        )
        assert isinstance(resp, JsonRpcResponse)
        caps = resp.result.get("capabilities", {})
        assert "tools" not in caps

    async def test_capabilities_no_resources_when_no_resource_methods(self):
        dispatcher, _ = await build_wired_dispatcher(ToolsOnlyServer)
        resp = await dispatcher.dispatch(
            make_req(
                "initialize",
                id_=5,
                params={
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "0"},
                },
            )
        )
        assert isinstance(resp, JsonRpcResponse)
        caps = resp.result.get("capabilities", {})
        assert "resources" not in caps

    async def test_capabilities_no_prompts_when_no_prompt_methods(self):
        dispatcher, _ = await build_wired_dispatcher(ToolsOnlyServer)
        resp = await dispatcher.dispatch(
            make_req(
                "initialize",
                id_=6,
                params={
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "0"},
                },
            )
        )
        assert isinstance(resp, JsonRpcResponse)
        caps = resp.result.get("capabilities", {})
        assert "prompts" not in caps


# ---------------------------------------------------------------------------
# Tests: handler registration on dispatcher
# ---------------------------------------------------------------------------


class TestHandlerRegistration:
    async def test_initialize_handler_registered(self):
        dispatcher, _ = await build_wired_dispatcher(CalcServer)
        assert "initialize" in dispatcher._handlers

    async def test_tools_list_handler_registered_when_tools_present(self):
        dispatcher, _ = await build_wired_dispatcher(CalcServer)
        assert "tools/list" in dispatcher._handlers

    async def test_tools_call_handler_registered_when_tools_present(self):
        dispatcher, _ = await build_wired_dispatcher(CalcServer)
        assert "tools/call" in dispatcher._handlers

    async def test_tools_list_registered_even_when_no_tools(self):
        # Handlers are always registered so dynamically added catalog
        # entries are reachable; an empty server returns an empty list.
        dispatcher, _ = await build_wired_dispatcher(EmptyServer)
        assert "tools/list" in dispatcher._handlers
        resp = await dispatcher.dispatch(make_req("tools/list", id_=90))
        assert isinstance(resp, JsonRpcResponse)
        assert resp.result == {"tools": []}

    async def test_resources_list_handler_registered_when_resources_present(self):
        dispatcher, _ = await build_wired_dispatcher(CalcServer)
        assert "resources/list" in dispatcher._handlers

    async def test_resources_list_empty_when_no_resources(self):
        dispatcher, _ = await build_wired_dispatcher(ToolsOnlyServer)
        resp = await dispatcher.dispatch(make_req("resources/list", id_=91))
        assert isinstance(resp, JsonRpcResponse)
        assert resp.result == {"resources": []}

    async def test_prompts_list_handler_registered_when_prompts_present(self):
        dispatcher, _ = await build_wired_dispatcher(CalcServer)
        assert "prompts/list" in dispatcher._handlers

    async def test_prompts_list_empty_when_no_prompts(self):
        dispatcher, _ = await build_wired_dispatcher(ToolsOnlyServer)
        resp = await dispatcher.dispatch(make_req("prompts/list", id_=92))
        assert isinstance(resp, JsonRpcResponse)
        assert resp.result == {"prompts": []}


# ---------------------------------------------------------------------------
# Tests: actual dispatch round-trips
# ---------------------------------------------------------------------------


class TestDispatchRoundTrips:
    async def test_tools_list_dispatch_returns_tool_names(self):
        dispatcher, _ = await build_wired_dispatcher(CalcServer)
        resp = await dispatcher.dispatch(make_req("tools/list", id_=20))
        assert isinstance(resp, JsonRpcResponse)
        tools = resp.result.get("tools", [])
        names = [t["name"] for t in tools]
        assert "add" in names
        assert "multiply" in names

    async def test_tools_call_add_returns_correct_result(self):
        dispatcher, _ = await build_wired_dispatcher(CalcServer)
        resp = await dispatcher.dispatch(
            make_req(
                "tools/call",
                id_=21,
                params={"name": "add", "arguments": {"a": 5, "b": 3}},
            )
        )
        assert isinstance(resp, JsonRpcResponse)
        content = resp.result.get("content", [])
        assert any("8" in item.get("text", "") for item in content if item.get("type") == "text")

    async def test_tools_call_unknown_tool_returns_internal_error(self):
        dispatcher, _ = await build_wired_dispatcher(CalcServer)
        resp = await dispatcher.dispatch(
            make_req(
                "tools/call",
                id_=22,
                params={"name": "NONEXISTENT", "arguments": {}},
            )
        )
        assert isinstance(resp, JsonRpcErrorResponse)
        assert resp.error.code == McpErrorCode.INTERNAL_ERROR

    async def test_resources_list_dispatch_returns_resource_uris(self):
        dispatcher, _ = await build_wired_dispatcher(CalcServer)
        resp = await dispatcher.dispatch(make_req("resources/list", id_=30))
        assert isinstance(resp, JsonRpcResponse)
        resources = resp.result.get("resources", [])
        assert len(resources) >= 1

    async def test_prompts_list_dispatch_returns_prompt_names(self):
        dispatcher, _ = await build_wired_dispatcher(CalcServer)
        resp = await dispatcher.dispatch(make_req("prompts/list", id_=40))
        assert isinstance(resp, JsonRpcResponse)
        prompts = resp.result.get("prompts", [])
        names = [p["name"] for p in prompts]
        assert "greet" in names


# ---------------------------------------------------------------------------
# Tests: McpServerMeta path
# ---------------------------------------------------------------------------


class TestMcpServerMeta:
    def test_mcp_server_meta_path_stored_on_class(self):
        meta: McpServerMeta = getattr(CalcServer, MCP_SERVER_META)
        assert meta.path == "/mcp"

    def test_mcp_server_meta_transport_default_ws(self):
        meta: McpServerMeta = getattr(CalcServer, MCP_SERVER_META)
        assert meta.transport == "ws"


# ---------------------------------------------------------------------------
# Tests: Transport controller selection
# ---------------------------------------------------------------------------


class TestTransportControllers:
    def test_ws_transport_produces_ws_controller_in_module(self):
        from lauren.decorators import MODULE_META
        from lauren.websockets import WS_CONTROLLER_META

        mod = McpServerModule.for_root(ToolsOnlyServer, transport="ws")
        meta = getattr(mod, MODULE_META)
        # Should have exactly 1 controller (WS only)
        assert len(meta.controllers) == 1
        controller = meta.controllers[0]
        # The WS controller has WS_CONTROLLER_META attached
        ws_meta = getattr(controller, WS_CONTROLLER_META, None)
        assert ws_meta is not None
        assert ws_meta.path.endswith("/ws")

    def test_sse_transport_produces_sse_controller_in_module(self):
        from lauren.decorators import CONTROLLER_META, MODULE_META

        @mcp_server("/mcp-test-sse")
        class SseTestServer:
            @mcp_tool()
            async def ping_tool(self) -> str:
                """Ping."""
                return "pong"

        mod = McpServerModule.for_root(SseTestServer, transport="sse")
        meta = getattr(mod, MODULE_META)
        assert len(meta.controllers) == 1
        controller = meta.controllers[0]
        # SSE controllers use CONTROLLER_META (not WS_CONTROLLER_META)
        ctrl_meta = getattr(controller, CONTROLLER_META, None)
        assert ctrl_meta is not None
        # SSE controller prefix should not end with /ws (it's not a WS controller)
        assert not getattr(ctrl_meta, "prefix", "").endswith("/ws")

    def test_both_transport_produces_two_controllers(self):
        from lauren.decorators import MODULE_META

        @mcp_server("/mcp-test-both")
        class BothTestServer:
            @mcp_tool()
            async def ping_tool(self) -> str:
                """Ping."""
                return "pong"

        mod = McpServerModule.for_root(BothTestServer, transport="both")
        meta = getattr(mod, MODULE_META)
        assert len(meta.controllers) == 2
