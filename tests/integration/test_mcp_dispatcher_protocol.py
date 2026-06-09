"""Integration tests: McpDispatcher full round-trip at the JSON-RPC level.

These tests instantiate McpDispatcher directly (no Lauren DI container),
call ``_register_builtins()`` manually, then exercise ``dispatch()`` end-to-end.
"""
from __future__ import annotations

import asyncio
import pytest

from lauren_mcp._server._dispatcher import McpDispatcher
from lauren_mcp._types import (
    JsonRpcRequest,
    JsonRpcResponse,
    JsonRpcErrorResponse,
    McpErrorCode,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_dispatcher() -> McpDispatcher:
    d = McpDispatcher()
    d._register_builtins()
    return d


def make_req(method: str, id_=1, params=None) -> JsonRpcRequest:
    return JsonRpcRequest(method=method, id=id_, params=params)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestInitializeHandler:
    async def test_initialize_dispatched_returns_success_response(self):
        """An initialize handler registered on the dispatcher returns a JsonRpcResponse."""
        d = make_dispatcher()

        async def _init(params):
            return {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "test-server", "version": "1.0.0"},
            }

        d.register("initialize", _init)
        req = make_req("initialize", id_=1, params={
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0.0.1"},
        })
        resp = await d.dispatch(req)
        assert isinstance(resp, JsonRpcResponse)
        assert resp.jsonrpc == "2.0"

    async def test_initialize_result_has_protocol_version(self):
        d = make_dispatcher()

        async def _init(params):
            return {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "s", "version": "1.0"}}

        d.register("initialize", _init)
        resp = await d.dispatch(make_req("initialize", id_=2))
        assert isinstance(resp, JsonRpcResponse)
        assert "protocolVersion" in resp.result

    async def test_initialize_result_has_capabilities_key(self):
        d = make_dispatcher()

        async def _init(params):
            return {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "s", "version": "1"}}

        d.register("initialize", _init)
        resp = await d.dispatch(make_req("initialize", id_=3))
        assert isinstance(resp, JsonRpcResponse)
        assert "capabilities" in resp.result

    async def test_initialize_result_has_server_info_key(self):
        d = make_dispatcher()

        async def _init(params):
            return {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "myserver", "version": "2.0"}}

        d.register("initialize", _init)
        resp = await d.dispatch(make_req("initialize", id_=4))
        assert isinstance(resp, JsonRpcResponse)
        assert resp.result["serverInfo"]["name"] == "myserver"


class TestToolsList:
    async def test_tools_list_returns_list_of_schemas(self):
        d = make_dispatcher()
        schemas = [{"name": "echo", "description": "Echo text", "inputSchema": {"type": "object"}}]

        async def _tools_list(params):
            return {"tools": schemas}

        d.register("tools/list", _tools_list)
        resp = await d.dispatch(make_req("tools/list", id_=10))
        assert isinstance(resp, JsonRpcResponse)
        tools = resp.result.get("tools", [])
        assert len(tools) == 1
        assert tools[0]["name"] == "echo"

    async def test_tools_list_empty_returns_empty_list(self):
        d = make_dispatcher()

        async def _tools_list(params):
            return {"tools": []}

        d.register("tools/list", _tools_list)
        resp = await d.dispatch(make_req("tools/list", id_=11))
        assert isinstance(resp, JsonRpcResponse)
        assert resp.result["tools"] == []

    async def test_tools_list_multiple_tools(self):
        d = make_dispatcher()
        schemas = [
            {"name": "add", "description": "Add numbers", "inputSchema": {}},
            {"name": "sub", "description": "Subtract", "inputSchema": {}},
            {"name": "mul", "description": "Multiply", "inputSchema": {}},
        ]

        async def _tools_list(params):
            return {"tools": schemas}

        d.register("tools/list", _tools_list)
        resp = await d.dispatch(make_req("tools/list", id_=12))
        assert isinstance(resp, JsonRpcResponse)
        assert len(resp.result["tools"]) == 3


class TestToolsCall:
    async def test_tools_call_valid_tool_returns_content_list(self):
        d = make_dispatcher()

        async def _tools_call(params):
            name = (params or {}).get("name")
            if name == "add":
                a = (params or {}).get("arguments", {}).get("a", 0)
                b = (params or {}).get("arguments", {}).get("b", 0)
                return {"content": [{"type": "text", "text": str(a + b)}], "isError": False}
            raise ValueError(f"Unknown tool: {name!r}")

        d.register("tools/call", _tools_call)
        resp = await d.dispatch(make_req("tools/call", id_=20, params={"name": "add", "arguments": {"a": 3, "b": 4}}))
        assert isinstance(resp, JsonRpcResponse)
        content = resp.result["content"]
        assert len(content) >= 1
        assert content[0]["type"] == "text"
        assert content[0]["text"] == "7"

    async def test_tools_call_unknown_tool_raises_internal_error(self):
        d = make_dispatcher()

        async def _tools_call(params):
            raise ValueError("Unknown tool: 'nonexistent'")

        d.register("tools/call", _tools_call)
        resp = await d.dispatch(make_req("tools/call", id_=21, params={"name": "nonexistent", "arguments": {}}))
        assert isinstance(resp, JsonRpcErrorResponse)
        assert resp.error.code == McpErrorCode.INTERNAL_ERROR


class TestPing:
    async def test_ping_builtin_returns_empty_result(self):
        d = make_dispatcher()
        resp = await d.dispatch(make_req("ping", id_=30))
        assert isinstance(resp, JsonRpcResponse)
        assert resp.result == {}

    async def test_ping_registered_after_register_builtins(self):
        d = make_dispatcher()
        assert "ping" in d._handlers


class TestMethodNotFound:
    async def test_method_not_found_error_on_unregistered_method(self):
        d = make_dispatcher()
        resp = await d.dispatch(make_req("unknown/method", id_=40))
        assert isinstance(resp, JsonRpcErrorResponse)
        assert resp.error.code == McpErrorCode.METHOD_NOT_FOUND

    async def test_method_not_found_message_contains_method_name(self):
        d = make_dispatcher()
        resp = await d.dispatch(make_req("does/not/exist", id_=41))
        assert isinstance(resp, JsonRpcErrorResponse)
        assert "does/not/exist" in resp.error.message


class TestInternalError:
    async def test_handler_exception_returns_internal_error(self):
        d = make_dispatcher()

        async def _boom(params):
            raise RuntimeError("kaboom")

        d.register("explode", _boom)
        resp = await d.dispatch(make_req("explode", id_=50))
        assert isinstance(resp, JsonRpcErrorResponse)
        assert resp.error.code == McpErrorCode.INTERNAL_ERROR
        assert "kaboom" in resp.error.message

    async def test_internal_error_data_includes_exception_type(self):
        d = make_dispatcher()

        async def _boom(params):
            raise ValueError("bad value")

        d.register("bad", _boom)
        resp = await d.dispatch(make_req("bad", id_=51))
        assert isinstance(resp, JsonRpcErrorResponse)
        assert resp.error.data is not None
        assert resp.error.data.get("type") == "ValueError"


class TestRequestCancelled:
    async def test_cancelled_task_returns_request_cancelled_error(self):
        d = make_dispatcher()
        started = asyncio.Event()

        async def _slow(params):
            started.set()
            await asyncio.sleep(60)
            return {}

        d.register("slow", _slow)
        dispatch_task = asyncio.create_task(d.dispatch(make_req("slow", id_=60)))
        await started.wait()
        d.cancel(60)
        resp = await dispatch_task
        assert isinstance(resp, JsonRpcErrorResponse)
        assert resp.error.code == McpErrorCode.REQUEST_CANCELLED

    async def test_cancel_in_flight_returns_true(self):
        d = make_dispatcher()
        started = asyncio.Event()

        async def _slow(params):
            started.set()
            await asyncio.sleep(60)

        d.register("slow2", _slow)
        task = asyncio.create_task(d.dispatch(make_req("slow2", id_=61)))
        await started.wait()
        result = d.cancel(61)
        assert result is True
        await task

    async def test_cancel_completed_request_returns_false(self):
        d = make_dispatcher()

        async def _fast(params):
            return {}

        d.register("fast", _fast)
        await d.dispatch(make_req("fast", id_=62))
        result = d.cancel(62)
        assert result is False

    async def test_cancel_unknown_id_returns_false(self):
        d = make_dispatcher()
        result = d.cancel(9999)
        assert result is False


class TestConcurrentDispatches:
    async def test_five_concurrent_requests_all_complete(self):
        d = make_dispatcher()
        gates = [asyncio.Event() for _ in range(5)]
        results: list[int] = []

        def make_handler(n: int):
            async def handler(params):
                await gates[n].wait()
                results.append(n)
                return {"index": n}
            return handler

        for i in range(5):
            d.register(f"op_{i}", make_handler(i))

        tasks = [
            asyncio.create_task(d.dispatch(make_req(f"op_{i}", id_=i + 100)))
            for i in range(5)
        ]

        # Release in reverse order
        for i in reversed(range(5)):
            gates[i].set()

        responses = await asyncio.gather(*tasks)
        assert len(responses) == 5
        for i, resp in enumerate(responses):
            assert isinstance(resp, JsonRpcResponse)
            assert resp.result["index"] == i

    async def test_concurrent_responses_have_matching_ids(self):
        d = make_dispatcher()

        async def echo_id(params):
            return {"received_id": (params or {}).get("my_id")}

        d.register("echo_id", echo_id)
        tasks = [
            asyncio.create_task(d.dispatch(make_req("echo_id", id_=i + 200, params={"my_id": i + 200})))
            for i in range(5)
        ]
        responses = await asyncio.gather(*tasks)
        for i, resp in enumerate(responses):
            assert isinstance(resp, JsonRpcResponse)
            assert resp.id == i + 200


class TestHandlerOverwrite:
    async def test_re_registering_handler_overwrites_previous(self):
        d = make_dispatcher()

        async def first(params):
            return "first"

        async def second(params):
            return "second"

        d.register("my/method", first)
        d.register("my/method", second)
        resp = await d.dispatch(make_req("my/method", id_=70))
        assert isinstance(resp, JsonRpcResponse)
        assert resp.result == "second"


class TestRequestIdVariants:
    async def test_string_id_preserved_in_response(self):
        d = make_dispatcher()

        async def handler(params):
            return {"ok": True}

        d.register("method", handler)
        req = JsonRpcRequest(method="method", id="req-abc-123")
        resp = await d.dispatch(req)
        assert isinstance(resp, JsonRpcResponse)
        assert resp.id == "req-abc-123"

    async def test_none_id_preserved_in_response(self):
        d = make_dispatcher()

        async def handler(params):
            return {"ok": True}

        d.register("method_none_id", handler)
        req = JsonRpcRequest(method="method_none_id", id=None)
        resp = await d.dispatch(req)
        assert isinstance(resp, JsonRpcResponse)
        assert resp.id is None


class TestParamsHandling:
    async def test_params_dict_passed_to_handler(self):
        d = make_dispatcher()
        received = []

        async def handler(params):
            received.append(params)
            return {}

        d.register("with_params", handler)
        await d.dispatch(make_req("with_params", id_=80, params={"foo": "bar", "n": 42}))
        assert received == [{"foo": "bar", "n": 42}]

    async def test_none_params_passes_none_to_handler(self):
        d = make_dispatcher()
        received = []

        async def handler(params):
            received.append(params)
            return {}

        d.register("no_params", handler)
        req = JsonRpcRequest(method="no_params", id=90, params=None)
        await d.dispatch(req)
        assert received == [None]


class TestResponseStructure:
    async def test_success_response_has_jsonrpc_field(self):
        d = make_dispatcher()

        async def handler(params):
            return {}

        d.register("ok_method", handler)
        resp = await d.dispatch(make_req("ok_method", id_=100))
        assert isinstance(resp, JsonRpcResponse)
        assert resp.jsonrpc == "2.0"

    async def test_success_response_id_matches_request_id(self):
        d = make_dispatcher()

        async def handler(params):
            return {"done": True}

        d.register("id_check", handler)
        resp = await d.dispatch(make_req("id_check", id_=101))
        assert isinstance(resp, JsonRpcResponse)
        assert resp.id == 101

    async def test_error_response_has_jsonrpc_field(self):
        d = make_dispatcher()
        resp = await d.dispatch(make_req("nonexistent", id_=102))
        assert isinstance(resp, JsonRpcErrorResponse)
        assert resp.jsonrpc == "2.0"

    async def test_error_response_id_matches_request_id(self):
        d = make_dispatcher()
        resp = await d.dispatch(make_req("nonexistent", id_=103))
        assert isinstance(resp, JsonRpcErrorResponse)
        assert resp.id == 103


class TestHandlerTimeout:
    async def test_long_running_handler_can_be_cancelled_mid_flight(self):
        d = make_dispatcher()
        entered = asyncio.Event()

        async def long_op(params):
            entered.set()
            await asyncio.sleep(100)
            return {}

        d.register("long_op", long_op)
        dispatch_task = asyncio.create_task(d.dispatch(make_req("long_op", id_=110)))
        await entered.wait()
        assert d.cancel(110) is True
        resp = await dispatch_task
        assert isinstance(resp, JsonRpcErrorResponse)
        assert resp.error.code == McpErrorCode.REQUEST_CANCELLED


class TestRapidDispatches:
    async def test_rapid_back_to_back_dispatches_no_id_mixing(self):
        d = make_dispatcher()

        async def echo(params):
            return {"echo_id": (params or {}).get("req_id")}

        d.register("rapid", echo)

        # Fire 10 sequential dispatches rapidly
        for i in range(10):
            resp = await d.dispatch(make_req("rapid", id_=i + 200, params={"req_id": i + 200}))
            assert isinstance(resp, JsonRpcResponse)
            assert resp.id == i + 200
            assert resp.result["echo_id"] == i + 200
