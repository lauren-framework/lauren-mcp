"""Unit tests for Phase 1: per-tool @use_guards / @use_interceptors /
@use_exception_handlers / @set_metadata reading and storage.

Tests cover:
  Group A: @set_metadata storage on McpToolMeta, McpResourceMeta, McpPromptMeta
  Group B: guard, interceptor, exception_handler storage
  Group C: @use_middlewares rejection (TypeError at decoration time)
  Group D: Lauren not installed (ImportError mock) → empty defaults, no crash
  Group E: McpToolContext.metadata merge semantics via make_context_factory
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import patch

import pytest

from lauren_mcp.server._decorators import mcp_prompt, mcp_resource, mcp_tool
from lauren_mcp.server._handlers import make_context_factory
from lauren_mcp.server._meta import (
    MCP_PROMPT_META,
    MCP_RESOURCE_META,
    MCP_TOOL_META,
    McpPromptMeta,
    McpResourceMeta,
    McpToolMeta,
)

# ---------------------------------------------------------------------------
# Dummy guard / interceptor / exception handler classes
# ---------------------------------------------------------------------------


class SomeGuard:
    async def can_activate(self, ctx: Any) -> bool:
        return True


class AnotherGuard:
    async def can_activate(self, ctx: Any) -> bool:
        return True


class SomeInterceptor:
    async def intercept(self, ctx: Any, call_next: Any) -> Any:
        return await call_next(ctx)


class SomeHandler:
    async def handle(self, exc: Exception) -> Any:
        raise exc


class SomeMw:
    pass


# ---------------------------------------------------------------------------
# Helpers to apply Lauren decorator attributes manually (simulates what
# Lauren's decorators do) without requiring the exact Lauren API.
# ---------------------------------------------------------------------------


def _apply_set_metadata(fn: Any, key: str, value: Any) -> None:
    """Simulate @set_metadata(key, value) applying its attribute to fn."""
    from lauren.decorators import SET_METADATA  # noqa: PLC0415

    existing: dict = getattr(fn, SET_METADATA, {})
    existing[key] = value
    object.__setattr__(fn, SET_METADATA, existing) if False else setattr(fn, SET_METADATA, existing)


def _apply_use_guards(fn: Any, *guard_classes: type) -> None:
    """Simulate @use_guards(*guard_classes) applying its attribute to fn."""
    from lauren.decorators import USE_GUARDS  # noqa: PLC0415

    existing: list = getattr(fn, USE_GUARDS, [])
    existing = list(existing) + list(guard_classes)
    setattr(fn, USE_GUARDS, existing)


def _apply_use_interceptors(fn: Any, *interceptor_classes: type) -> None:
    """Simulate @use_interceptors(*interceptor_classes) applying its attribute to fn."""
    from lauren.decorators import USE_INTERCEPTORS  # noqa: PLC0415

    existing: list = getattr(fn, USE_INTERCEPTORS, [])
    existing = list(existing) + list(interceptor_classes)
    setattr(fn, USE_INTERCEPTORS, existing)


def _apply_use_exception_handlers(fn: Any, *handler_classes: type) -> None:
    """Simulate @use_exception_handlers(*handler_classes) applying its attribute to fn."""
    from lauren.decorators import USE_EXCEPTION_HANDLERS  # noqa: PLC0415

    existing: list = getattr(fn, USE_EXCEPTION_HANDLERS, [])
    existing = list(existing) + list(handler_classes)
    setattr(fn, USE_EXCEPTION_HANDLERS, existing)


def _apply_use_middlewares(fn: Any, *mw_classes: type) -> None:
    """Simulate @use_middlewares(*mw_classes) applying its attribute to fn."""
    from lauren.decorators import USE_MIDDLEWARES  # noqa: PLC0415

    existing: list = getattr(fn, USE_MIDDLEWARES, [])
    existing = list(existing) + list(mw_classes)
    setattr(fn, USE_MIDDLEWARES, existing)


# ---------------------------------------------------------------------------
# Group A: @set_metadata storage
# ---------------------------------------------------------------------------


class TestSetMetadataStorage:
    def test_a1_set_metadata_on_tool(self):
        """A1: @set_metadata('role', 'admin') @mcp_tool() → meta.tool_metadata == {'role': 'admin'}"""  # noqa: E501

        async def my_tool(self) -> str:  # type: ignore[misc]
            return "ok"

        _apply_set_metadata(my_tool, "role", "admin")
        decorated = mcp_tool()(my_tool)
        meta: McpToolMeta = getattr(decorated, MCP_TOOL_META)
        assert meta.tool_metadata == {"role": "admin"}

    def test_a2_multiple_set_metadata_calls_accumulate(self):
        """A2: multiple @set_metadata calls accumulate both keys in dict."""

        async def my_tool(self) -> str:  # type: ignore[misc]
            return "ok"

        _apply_set_metadata(my_tool, "a", 1)
        _apply_set_metadata(my_tool, "b", 2)
        decorated = mcp_tool()(my_tool)
        meta: McpToolMeta = getattr(decorated, MCP_TOOL_META)
        assert meta.tool_metadata == {"a": 1, "b": 2}

    def test_a3_no_set_metadata_gives_empty_dict(self):
        """A3: @mcp_tool() with no @set_metadata → meta.tool_metadata == {}"""

        async def my_tool(self) -> str:  # type: ignore[misc]
            return "ok"

        decorated = mcp_tool()(my_tool)
        meta: McpToolMeta = getattr(decorated, MCP_TOOL_META)
        assert meta.tool_metadata == {}

    def test_a4_set_metadata_on_resource(self):
        """A4: @set_metadata('role', 'admin') @mcp_resource() → meta.tool_metadata == {'role': 'admin'}"""  # noqa: E501

        async def my_resource(self, resource_id: str) -> str:  # type: ignore[misc]
            return resource_id

        _apply_set_metadata(my_resource, "role", "admin")
        decorated = mcp_resource("/things/{resource_id}")(my_resource)
        meta: McpResourceMeta = getattr(decorated, MCP_RESOURCE_META)
        assert meta.tool_metadata == {"role": "admin"}

    def test_a5_set_metadata_on_prompt(self):
        """A5: @set_metadata('role', 'admin') @mcp_prompt() → meta.tool_metadata == {'role': 'admin'}"""  # noqa: E501

        async def my_prompt(self, topic: str) -> str:  # type: ignore[misc]
            return topic

        _apply_set_metadata(my_prompt, "role", "admin")
        decorated = mcp_prompt()(my_prompt)
        meta: McpPromptMeta = getattr(decorated, MCP_PROMPT_META)
        assert meta.tool_metadata == {"role": "admin"}


# ---------------------------------------------------------------------------
# Group B: guard / interceptor / exception_handler storage
# ---------------------------------------------------------------------------


class TestGuardInterceptorStorage:
    def test_b1_use_guards_single_class(self):
        """B1: @use_guards(SomeGuard) @mcp_tool() → meta.guards == (SomeGuard,)"""

        async def my_tool(self) -> str:  # type: ignore[misc]
            return "ok"

        _apply_use_guards(my_tool, SomeGuard)
        decorated = mcp_tool()(my_tool)
        meta: McpToolMeta = getattr(decorated, MCP_TOOL_META)
        assert meta.guards == (SomeGuard,)

    def test_b2_use_guards_multiple_classes(self):
        """B2: @use_guards(G1, G2) → meta.guards == (G1, G2)"""

        async def my_tool(self) -> str:  # type: ignore[misc]
            return "ok"

        _apply_use_guards(my_tool, SomeGuard, AnotherGuard)
        decorated = mcp_tool()(my_tool)
        meta: McpToolMeta = getattr(decorated, MCP_TOOL_META)
        assert meta.guards == (SomeGuard, AnotherGuard)

    def test_b3_stacked_use_guards_accumulate(self):
        """B3: @use_guards(G2) @use_guards(G1) @mcp_tool() → meta.guards == (G1, G2)"""

        async def my_tool(self) -> str:  # type: ignore[misc]
            return "ok"

        # Lauren applies bottom-up; G1 is added first, G2 second
        _apply_use_guards(my_tool, SomeGuard)
        _apply_use_guards(my_tool, AnotherGuard)
        decorated = mcp_tool()(my_tool)
        meta: McpToolMeta = getattr(decorated, MCP_TOOL_META)
        assert meta.guards == (SomeGuard, AnotherGuard)

    def test_b4_use_interceptors(self):
        """B4: @use_interceptors(I1) @mcp_tool() → meta.interceptors == (I1,)"""

        async def my_tool(self) -> str:  # type: ignore[misc]
            return "ok"

        _apply_use_interceptors(my_tool, SomeInterceptor)
        decorated = mcp_tool()(my_tool)
        meta: McpToolMeta = getattr(decorated, MCP_TOOL_META)
        assert meta.interceptors == (SomeInterceptor,)

    def test_b5_use_exception_handlers(self):
        """B5: @use_exception_handlers(H1) @mcp_tool() → meta.exception_handlers == (H1,)"""

        async def my_tool(self) -> str:  # type: ignore[misc]
            return "ok"

        _apply_use_exception_handlers(my_tool, SomeHandler)
        decorated = mcp_tool()(my_tool)
        meta: McpToolMeta = getattr(decorated, MCP_TOOL_META)
        assert meta.exception_handlers == (SomeHandler,)

    def test_b6_none_applied_gives_empty_tuples(self):
        """B6: @mcp_tool() with no guards/interceptors/exception_handlers → all ()"""

        async def my_tool(self) -> str:  # type: ignore[misc]
            return "ok"

        decorated = mcp_tool()(my_tool)
        meta: McpToolMeta = getattr(decorated, MCP_TOOL_META)
        assert meta.guards == ()
        assert meta.interceptors == ()
        assert meta.exception_handlers == ()

    def test_b7_guards_on_resource_and_prompt(self):
        """B7: guards/interceptors also stored on @mcp_resource and @mcp_prompt."""

        async def my_resource(self, item_id: str) -> str:  # type: ignore[misc]
            return item_id

        async def my_prompt(self, topic: str) -> str:  # type: ignore[misc]
            return topic

        _apply_use_guards(my_resource, SomeGuard)
        _apply_use_interceptors(my_resource, SomeInterceptor)
        _apply_use_guards(my_prompt, AnotherGuard)

        dec_resource = mcp_resource("/items/{item_id}")(my_resource)
        dec_prompt = mcp_prompt()(my_prompt)

        r_meta: McpResourceMeta = getattr(dec_resource, MCP_RESOURCE_META)
        p_meta: McpPromptMeta = getattr(dec_prompt, MCP_PROMPT_META)

        assert r_meta.guards == (SomeGuard,)
        assert r_meta.interceptors == (SomeInterceptor,)
        assert p_meta.guards == (AnotherGuard,)

    def test_both_guards_and_metadata_stored(self):
        """Method with both @use_guards and @set_metadata → both stored correctly."""

        async def my_tool(self) -> str:  # type: ignore[misc]
            return "ok"

        _apply_set_metadata(my_tool, "role", "admin")
        _apply_use_guards(my_tool, SomeGuard)
        decorated = mcp_tool()(my_tool)
        meta: McpToolMeta = getattr(decorated, MCP_TOOL_META)
        assert meta.guards == (SomeGuard,)
        assert meta.tool_metadata == {"role": "admin"}


# ---------------------------------------------------------------------------
# Group C: @use_middlewares rejection
# ---------------------------------------------------------------------------


class TestUseMiddlewaresRejection:
    def test_c1_use_middlewares_on_tool_raises_type_error(self):
        """C1: @use_middlewares @mcp_tool() → TypeError at decoration time."""

        async def bad_tool(self) -> str:  # type: ignore[misc]
            return "ok"

        _apply_use_middlewares(bad_tool, SomeMw)
        with pytest.raises(TypeError):
            mcp_tool()(bad_tool)

    def test_c2_type_error_message_contains_method_name(self):
        """C2: TypeError message contains the offending method name."""

        async def delete_all(self) -> str:  # type: ignore[misc]
            return "ok"

        _apply_use_middlewares(delete_all, SomeMw)
        with pytest.raises(TypeError, match="delete_all"):
            mcp_tool()(delete_all)

    def test_c3_use_middlewares_on_resource_raises_type_error(self):
        """C3: @use_middlewares @mcp_resource() → TypeError."""

        async def my_resource(self, item_id: str) -> str:  # type: ignore[misc]
            return item_id

        _apply_use_middlewares(my_resource, SomeMw)
        with pytest.raises(TypeError):
            mcp_resource("/items/{item_id}")(my_resource)

    def test_c4_use_middlewares_on_prompt_raises_type_error(self):
        """C4: @use_middlewares @mcp_prompt() → TypeError."""

        async def my_prompt(self, topic: str) -> str:  # type: ignore[misc]
            return topic

        _apply_use_middlewares(my_prompt, SomeMw)
        with pytest.raises(TypeError):
            mcp_prompt()(my_prompt)


# ---------------------------------------------------------------------------
# Group D: Lauren not installed (ImportError mock)
# ---------------------------------------------------------------------------


class TestLaurenNotInstalled:
    def _make_import_error_patcher(self):
        """Return a context manager that makes 'lauren.decorators' unimportable."""
        real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__  # type: ignore[attr-defined]  # noqa: F841

        import builtins

        original_import = builtins.__import__

        def patched_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "lauren.decorators":
                raise ImportError("lauren not installed")
            return original_import(name, *args, **kwargs)

        return patch("builtins.__import__", side_effect=patched_import)

    def test_d1_import_error_returns_empty_defaults(self):
        """D1: When lauren.decorators ImportError → _read_method_decorators returns empty defaults."""  # noqa: E501
        from lauren_mcp.server._decorators import _read_method_decorators  # noqa: PLC0415

        with self._make_import_error_patcher():
            # Remove cached module so our mock takes effect
            saved = sys.modules.pop("lauren.decorators", None)
            try:
                result = _read_method_decorators(lambda: None)  # type: ignore[arg-type]
            finally:
                if saved is not None:
                    sys.modules["lauren.decorators"] = saved

        assert result["guards"] == ()
        assert result["interceptors"] == ()
        assert result["exception_handlers"] == ()
        assert result["tool_metadata"] == {}

    def test_d2_no_crash_when_lauren_not_installed(self):
        """D2: @mcp_tool() doesn't crash even when lauren.decorators is unavailable."""
        from lauren_mcp.server._decorators import _read_method_decorators  # noqa: PLC0415

        with self._make_import_error_patcher():
            saved = sys.modules.pop("lauren.decorators", None)
            try:
                result = _read_method_decorators(lambda: None)  # type: ignore[arg-type]
            finally:
                if saved is not None:
                    sys.modules["lauren.decorators"] = saved

        # No exception; defaults are clean
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Group E: McpToolContext.metadata merge semantics
# ---------------------------------------------------------------------------


class TestContextMetadataMerge:
    """Tests for make_context_factory tool_metadata kwarg merging."""

    def _build_ctx(
        self,
        server_metadata: dict[str, Any] | None,
        tool_metadata: dict[str, Any] | None,
    ) -> Any:
        """Build a McpToolContext via make_context_factory with given metadata."""
        factory = make_context_factory(server_metadata)
        return factory("test_tool", "req-1", None, tool_metadata=tool_metadata)

    def test_e1_tool_metadata_overrides_server_metadata(self):
        """E1: tool_metadata key overrides same key from server metadata."""
        ctx = self._build_ctx(
            server_metadata={"env": "prod", "team": "core"},
            tool_metadata={"env": "staging"},
        )
        assert ctx.metadata == {"env": "staging", "team": "core"}

    def test_e2_no_tool_metadata_preserves_server_metadata(self):
        """E2: no tool_metadata → server metadata unchanged."""
        ctx = self._build_ctx(
            server_metadata={"env": "prod"},
            tool_metadata={},
        )
        assert ctx.metadata == {"env": "prod"}

    def test_e3_no_server_metadata_uses_tool_metadata_only(self):
        """E3: empty server metadata + tool_metadata → only tool_metadata in context."""
        ctx = self._build_ctx(
            server_metadata={},
            tool_metadata={"env": "staging"},
        )
        assert ctx.metadata == {"env": "staging"}

    def test_e4_get_metadata_returns_overridden_value(self):
        """E4: ctx.get_metadata('env') returns 'staging' after E1 merge."""
        ctx = self._build_ctx(
            server_metadata={"env": "prod", "team": "core"},
            tool_metadata={"env": "staging"},
        )
        assert ctx.get_metadata("env") == "staging"

    def test_e5_get_metadata_returns_default_for_missing_key(self):
        """E5: ctx.get_metadata('missing', 'default') == 'default'."""
        ctx = self._build_ctx(
            server_metadata={"env": "prod"},
            tool_metadata={},
        )
        assert ctx.get_metadata("missing", "default") == "default"

    def test_e_none_tool_metadata_treated_as_empty(self):
        """None tool_metadata kwarg is safe and equivalent to empty dict."""
        ctx = self._build_ctx(
            server_metadata={"key": "val"},
            tool_metadata=None,
        )
        assert ctx.get_metadata("key") == "val"

    def test_e_no_tool_metadata_kwarg_backwards_compat(self):
        """Calling factory with 3 positional args (no tool_metadata) still works."""
        factory = make_context_factory({"env": "prod"})
        ctx = factory("test_tool", "req-1", None)
        assert ctx.get_metadata("env") == "prod"
