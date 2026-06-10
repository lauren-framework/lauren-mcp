"""Integration tests for decorator/handler changes:
- titled tools and annotated resources visible via WS transport
- invalid tool name raises ValueError at decoration time (not @post_construct)
"""

from __future__ import annotations

import pytest
from lauren import LaurenFactory, module
from lauren.testing import TestClient, WsTestClient

from lauren_mcp import McpServerModule
from lauren_mcp.server._decorators import mcp_prompt, mcp_resource, mcp_server, mcp_tool

# ---------------------------------------------------------------------------
# Optional: ResourceAnnotations (types agent)
# ---------------------------------------------------------------------------

try:
    from lauren_mcp._types import ResourceAnnotations

    _RA_AVAILABLE = True
except ImportError:
    ResourceAnnotations = None  # type: ignore[assignment,misc]
    _RA_AVAILABLE = False

# ---------------------------------------------------------------------------
# Helpers: WS handshake
# ---------------------------------------------------------------------------

_INIT_MSG = {
    "jsonrpc": "2.0",
    "method": "initialize",
    "id": 1,
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
_INITIALIZED_MSG = {"jsonrpc": "2.0", "method": "notifications/initialized"}


async def _ws_rpc(app: object, path: str, method: str, req_id: int = 2) -> dict:  # type: ignore[type-arg]
    """Perform MCP handshake then send one RPC call; return its result."""
    ws = WsTestClient(app)  # type: ignore[arg-type]
    async with ws.connect(path) as conn:
        await conn.send_json(_INIT_MSG)
        await conn.receive_json()  # initialize response
        await conn.send_json(_INITIALIZED_MSG)
        await conn.send_json({"jsonrpc": "2.0", "method": method, "id": req_id, "params": {}})
        return await conn.receive_json()  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# App with titled tools and (optionally) annotated resources
# ---------------------------------------------------------------------------


def _build_titled_app() -> object:
    """Build a Lauren app with titled tool, titled prompt, and (if RA available) annotated resource."""  # noqa: E501

    @mcp_server("/mcp")
    class TitledServer:
        @mcp_tool(name="search", title="Search Items", description="Search across items.")
        async def search(self, query: str) -> str:
            return "results"

        @mcp_tool(name="ping")
        async def ping(self) -> str:
            return "pong"

        @mcp_prompt(title="Review Code")
        async def review_code(self, code: str) -> str:
            return f"Please review: {code}"

        if _RA_AVAILABLE:

            @mcp_resource(  # type: ignore[misc]
                "items://{id}",
                title="Item Resource",
                annotations=ResourceAnnotations(audience=["user"], priority=0.9),  # type: ignore[call-arg]
            )
            async def get_item(self, id: str) -> str:
                return f"item-{id}"

        else:

            @mcp_resource("items://{id}", title="Item Resource")  # type: ignore[misc]
            async def get_item(self, id: str) -> str:
                return f"item-{id}"

    @module(imports=[McpServerModule.for_root(TitledServer)])
    class AppModule:
        pass

    app = LaurenFactory.create(AppModule)
    TestClient(app)  # trigger @post_construct
    return app


@pytest.fixture(scope="module")
def titled_app() -> object:
    return _build_titled_app()


# ---------------------------------------------------------------------------
# tools/list — title present and absent
# ---------------------------------------------------------------------------


async def test_titled_tool_has_title_in_list(titled_app: object) -> None:
    resp = await _ws_rpc(titled_app, "/mcp/ws", "tools/list")
    tool_map = {t["name"]: t for t in resp["result"]["tools"]}
    assert tool_map["search"]["title"] == "Search Items"
    assert "title" not in tool_map["ping"]


# ---------------------------------------------------------------------------
# prompts/list — title present
# ---------------------------------------------------------------------------


async def test_titled_prompt_has_title_in_list(titled_app: object) -> None:
    resp = await _ws_rpc(titled_app, "/mcp/ws", "prompts/list")
    prompt_map = {p["name"]: p for p in resp["result"]["prompts"]}
    assert prompt_map["review_code"]["title"] == "Review Code"


# ---------------------------------------------------------------------------
# resources/list — title present; annotations if RA available
# ---------------------------------------------------------------------------


async def test_titled_resource_has_title_in_list(titled_app: object) -> None:
    resp = await _ws_rpc(titled_app, "/mcp/ws", "resources/list")
    resource_map = {r["name"]: r for r in resp["result"]["resources"]}
    assert resource_map["get_item"]["title"] == "Item Resource"


@pytest.mark.skipif(not _RA_AVAILABLE, reason="ResourceAnnotations not yet in _types.py")
async def test_annotated_resource_has_annotations_in_list(titled_app: object) -> None:
    resp = await _ws_rpc(titled_app, "/mcp/ws", "resources/list")
    resource_map = {r["name"]: r for r in resp["result"]["resources"]}
    ann = resource_map["get_item"].get("annotations")
    assert ann is not None
    assert ann["audience"] == ["user"]
    assert ann["priority"] == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# Invalid tool name raises ValueError at decoration time (not @post_construct)
# ---------------------------------------------------------------------------


def test_invalid_tool_name_raises_at_decoration_time() -> None:
    with pytest.raises(ValueError, match="invalid characters"):

        @mcp_server("/mcp2")
        class BadServer:
            @mcp_tool(name="bad name with spaces")
            async def bad_tool(self) -> str:
                return "ok"
