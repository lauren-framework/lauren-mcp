"""Unit tests for BackgroundTasks injection on @mcp_tool methods."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from lauren_mcp._types import JsonRpcRequest
from lauren_mcp.server._decorators import _build_schema
from lauren_mcp.server._handlers import make_tools_call_handler
from lauren_mcp.server._meta import McpToolMeta

# Skip entire module if lauren not installed
lauren = pytest.importorskip("lauren", reason="lauren not installed")
from lauren import BackgroundTasks  # noqa: E402

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_meta(fn: Any) -> McpToolMeta:
    from lauren_mcp.server._decorators import mcp_tool  # noqa: PLC0415

    mcp_tool()(fn)
    return fn.__mcp_tool_meta__


async def _wait_for(condition_list: list, timeout: float = 0.5) -> None:
    """Poll until condition_list is non-empty or timeout expires."""
    elapsed = 0.0
    interval = 0.01
    while elapsed < timeout and not condition_list:
        await asyncio.sleep(interval)
        elapsed += interval


async def _call_tool(server: Any, meta: McpToolMeta, arguments: dict[str, Any]) -> Any:
    from lauren_mcp._server._dispatcher import McpDispatcher  # noqa: PLC0415
    from lauren_mcp._types import JsonRpcRequest as _Req  # noqa: PLC0415

    dispatcher = McpDispatcher()
    dispatcher._register_builtins()
    _inner = make_tools_call_handler(server, [meta])

    async def _tools_call(params: dict | None) -> dict:
        return await _inner(_Req(method="tools/call", params=params))

    dispatcher.register("tools/call", _tools_call)
    req = JsonRpcRequest(
        method="tools/call",
        id=1,
        params={"name": meta.name, "arguments": arguments},
    )
    return await dispatcher.dispatch(req)


# ---------------------------------------------------------------------------
# Schema exclusion tests
# ---------------------------------------------------------------------------


class TestSchemaExclusion:
    def test_bg_tasks_param_excluded_from_input_schema(self) -> None:
        class S:
            async def mytool(self, name: str, tasks: BackgroundTasks) -> str:
                return name

        _, _, schema, _, _, _, bg_tasks_param, _, _, _ = _build_schema(S.mytool)
        assert "tasks" not in schema["properties"]
        assert "tasks" not in schema.get("required", [])

    def test_bg_tasks_meta_field_populated(self) -> None:
        class S:
            async def mytool(self, name: str, tasks: BackgroundTasks) -> str:
                return name

        _, _, _, _, _, _, bg_tasks_param, _, _, _ = _build_schema(S.mytool)
        assert bg_tasks_param == "tasks"

    def test_no_bg_tasks_param_is_none(self) -> None:
        class S:
            async def mytool(self, name: str) -> str:
                return name

        _, _, _, _, _, _, bg_tasks_param, _, _, _ = _build_schema(S.mytool)
        assert bg_tasks_param is None

    def test_other_params_still_present(self) -> None:
        class S:
            async def mytool(self, name: str, qty: int, tasks: BackgroundTasks) -> str:
                return name

        _, _, schema, _, _, _, _, _, _, _ = _build_schema(S.mytool)
        assert "name" in schema["properties"]
        assert "qty" in schema["properties"]
        assert "tasks" not in schema["properties"]


# ---------------------------------------------------------------------------
# Execution tests
# ---------------------------------------------------------------------------


class TestBackgroundTaskExecution:
    async def test_sync_task_runs_after_tool_result(self) -> None:
        side_effects: list[str] = []

        class S:
            async def mytool(self, name: str, tasks: BackgroundTasks) -> str:
                tasks.add_task(lambda: side_effects.append("ran"))
                return f"hello {name}"

        meta = _make_meta(S.mytool)
        server = S()
        resp = await _call_tool(server, meta, {"name": "world"})
        assert hasattr(resp, "result")
        await _wait_for(side_effects)
        assert side_effects == ["ran"]

    async def test_async_task_runs_after_tool_result(self) -> None:
        side_effects: list[str] = []

        async def async_work(msg: str) -> None:
            side_effects.append(msg)

        class S:
            async def mytool(self, tasks: BackgroundTasks) -> str:
                tasks.add_task(async_work, "async_ran")
                return "ok"

        meta = _make_meta(S.mytool)
        server = S()
        resp = await _call_tool(server, meta, {})
        assert hasattr(resp, "result")
        await _wait_for(side_effects)
        assert side_effects == ["async_ran"]

    async def test_multiple_tasks_run_in_order(self) -> None:
        order: list[int] = []

        class S:
            async def mytool(self, tasks: BackgroundTasks) -> str:
                tasks.add_task(lambda: order.append(1))
                tasks.add_task(lambda: order.append(2))
                tasks.add_task(lambda: order.append(3))
                return "ok"

        meta = _make_meta(S.mytool)
        server = S()
        resp = await _call_tool(server, meta, {})
        assert hasattr(resp, "result")
        # Wait for all 3 tasks to complete
        await asyncio.sleep(0.5)
        assert order == [1, 2, 3]

    async def test_task_error_does_not_change_tool_result(self) -> None:
        class S:
            async def mytool(self, tasks: BackgroundTasks) -> str:
                tasks.add_task(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
                return "ok"

        meta = _make_meta(S.mytool)
        server = S()
        resp = await _call_tool(server, meta, {})
        # Tool result is unaffected
        assert hasattr(resp, "result")
        assert "ok" in resp.result["content"][0]["text"]
        # Let background task attempt to run
        await asyncio.sleep(0.05)

    async def test_no_bg_tasks_no_overhead(self) -> None:
        class S:
            async def mytool(self, name: str) -> str:
                return f"hi {name}"

        meta = _make_meta(S.mytool)
        assert meta.bg_tasks_param is None
        server = S()
        resp = await _call_tool(server, meta, {"name": "test"})
        assert hasattr(resp, "result")

    async def test_lambda_task_runs(self) -> None:
        side_effects: list[int] = []

        class S:
            async def mytool(self, tasks: BackgroundTasks) -> str:
                tasks.add_task(lambda: side_effects.append(42))
                return "ok"

        meta = _make_meta(S.mytool)
        server = S()
        await _call_tool(server, meta, {})
        await _wait_for(side_effects)
        assert side_effects == [42]

    async def test_tool_raises_tasks_still_run(self) -> None:
        """Tasks added before a tool raise still execute."""
        side_effects: list[int] = []

        class S:
            async def mytool(self, tasks: BackgroundTasks) -> str:
                tasks.add_task(lambda: side_effects.append(99))
                raise ValueError("tool error")

        meta = _make_meta(S.mytool)
        server = S()
        resp = await _call_tool(server, meta, {})
        # Tool raised → error result from dispatcher
        assert hasattr(resp, "error")
        # Tasks added before raise still run
        await _wait_for(side_effects)
        assert side_effects == [99]

    async def test_no_tasks_added_noop(self) -> None:
        """BackgroundTasks declared but add_task never called — no error."""

        class S:
            async def mytool(self, tasks: BackgroundTasks) -> str:
                return "ok"

        meta = _make_meta(S.mytool)
        assert meta.bg_tasks_param == "tasks"
        server = S()
        resp = await _call_tool(server, meta, {})
        assert hasattr(resp, "result")

    async def test_two_bg_params_same_instance(self) -> None:
        """Two BackgroundTasks params → same object (matches Lauren HTTP behaviour)."""
        ids: list[int] = []

        class S:
            async def mytool(self, t1: BackgroundTasks, t2: BackgroundTasks) -> str:
                ids.append(id(t1))
                ids.append(id(t2))
                return "ok"

        meta = _make_meta(S.mytool)
        server = S()
        resp = await _call_tool(server, meta, {})
        assert hasattr(resp, "result")
        assert ids[0] == ids[1]
