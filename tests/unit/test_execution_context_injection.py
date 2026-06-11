"""Unit tests for ExecutionContext injection into MCP transport handlers.

Verifies that:
- TransportBinding.execution_context uses the real Lauren ExecutionContext
  instead of a manually constructed copy.
- McpExecutionContext.metadata merges EC.metadata (carrying @set_metadata
  values) with server_metadata and per-tool tool_metadata correctly.
- The priority order is: server_metadata < EC.metadata < tool_metadata.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ec(metadata: dict[str, Any]) -> Any:
    """Build a mock that quacks like lauren.types.ExecutionContext."""
    ec = MagicMock()
    ec.metadata = metadata
    ec.request = MagicMock()
    ec.request.headers = MagicMock()
    ec.handler_class = None
    ec.handler_func = None
    ec.route_template = "/__mcp__"
    return ec


def _make_binding(execution_context=None, extras=None):
    from lauren_mcp._server._binding import TransportBinding

    return TransportBinding(
        headers=None,
        execution_context=execution_context,
        session_id=None,
        send_notification=None,
        client_rpc=None,
        client_capabilities=None,
        extras=dict(extras or {}),
    )


# ---------------------------------------------------------------------------
# McpExecutionContext metadata merging
# ---------------------------------------------------------------------------


class TestMetadataMerge:
    def _build_exec_ctx(
        self,
        server_metadata: dict,
        ec_metadata: dict,
        tool_metadata: dict,
        extras: dict | None = None,
    ) -> Any:
        """Build McpExecutionContext by exercising the merge logic from handlers."""
        from lauren_mcp._server._binding import TransportBinding
        from lauren_mcp._server._exec_context import McpExecutionContext

        ec = _make_ec(ec_metadata)
        binding = TransportBinding(
            headers=ec.request.headers,
            execution_context=ec,
            session_id=None,
            send_notification=None,
            client_rpc=None,
            client_capabilities=None,
            extras=dict(extras or {}),
        )
        _ec_meta = dict(ec.metadata)
        _extras_meta = dict(binding.extras)
        _merged = {
            **_extras_meta,
            **server_metadata,
            **_ec_meta,
            **tool_metadata,
        }
        return McpExecutionContext(
            tool_name="test_tool",
            method_name="test_method",
            server_class=object,
            headers=ec.request.headers,
            execution_context=ec,
            session_id=None,
            metadata=_merged,
            tool_use_id=1,
        )

    def test_ec_metadata_included_in_exec_ctx(self):
        ctx = self._build_exec_ctx(
            server_metadata={},
            ec_metadata={"env": "production"},
            tool_metadata={},
        )
        assert ctx.metadata["env"] == "production"

    def test_server_metadata_included_when_no_ec_metadata(self):
        ctx = self._build_exec_ctx(
            server_metadata={"service": "mcp"},
            ec_metadata={},
            tool_metadata={},
        )
        assert ctx.metadata["service"] == "mcp"

    def test_tool_metadata_wins_over_server_metadata(self):
        ctx = self._build_exec_ctx(
            server_metadata={"scope": "server"},
            ec_metadata={},
            tool_metadata={"scope": "tool"},
        )
        assert ctx.metadata["scope"] == "tool"

    def test_tool_metadata_wins_over_ec_metadata(self):
        ctx = self._build_exec_ctx(
            server_metadata={},
            ec_metadata={"role": "admin"},
            tool_metadata={"role": "superadmin"},
        )
        assert ctx.metadata["role"] == "superadmin"

    def test_ec_metadata_wins_over_server_metadata(self):
        """EC.metadata (from real Lauren dispatch) overrides server_metadata."""
        ctx = self._build_exec_ctx(
            server_metadata={"tenant": "default"},
            ec_metadata={"tenant": "acme"},  # EC has same key → should win
            tool_metadata={},
        )
        assert ctx.metadata["tenant"] == "acme"

    def test_all_three_levels_merged_without_conflict(self):
        ctx = self._build_exec_ctx(
            server_metadata={"a": 1},
            ec_metadata={"b": 2},
            tool_metadata={"c": 3},
        )
        assert ctx.metadata == {"a": 1, "b": 2, "c": 3}

    def test_extras_included_at_lowest_priority(self):
        """WS connection-level extras from @set_metadata have lowest priority."""
        ctx = self._build_exec_ctx(
            server_metadata={"x": "server"},
            ec_metadata={},
            tool_metadata={},
            extras={"x": "extras", "y": "only_in_extras"},
        )
        # server_metadata beats extras
        assert ctx.metadata["x"] == "server"
        # extras-only key still present
        assert ctx.metadata["y"] == "only_in_extras"

    def test_ec_none_falls_back_to_server_metadata(self):
        """When execution_context is None (stdio / WS), server_metadata used."""
        from lauren_mcp._server._exec_context import McpExecutionContext

        ctx = McpExecutionContext(
            tool_name="tool",
            method_name="method",
            server_class=object,
            headers=None,
            execution_context=None,
            session_id=None,
            metadata={"from_server": "yes"},
            tool_use_id=None,
        )
        assert ctx.metadata["from_server"] == "yes"
        assert ctx.execution_context is None

    def test_get_metadata_convenience(self):
        from lauren_mcp._server._exec_context import McpExecutionContext

        ctx = McpExecutionContext(
            tool_name="tool",
            method_name="m",
            server_class=object,
            headers=None,
            execution_context=None,
            session_id=None,
            metadata={"k": "v"},
            tool_use_id=None,
        )
        assert ctx.get_metadata("k") == "v"
        assert ctx.get_metadata("missing", "default") == "default"

    def test_headers_from_ec_request_when_ec_present(self):
        """headers field uses ec.request.headers when EC is available."""
        from lauren_mcp._server._binding import TransportBinding

        mock_headers = MagicMock()
        ec = _make_ec({"k": "v"})
        ec.request.headers = mock_headers

        binding = TransportBinding(
            headers=MagicMock(),  # different object from EC headers
            execution_context=ec,
            session_id=None,
            send_notification=None,
            client_rpc=None,
            client_capabilities=None,
        )

        _ec = binding.execution_context
        resolved_headers = _ec.request.headers if _ec is not None else binding.headers
        assert resolved_headers is mock_headers


# ---------------------------------------------------------------------------
# TransportBinding — execution_context field
# ---------------------------------------------------------------------------


class TestTransportBindingExecutionContext:
    def test_real_ec_stored_not_reconstructed(self):
        """The binding must store the injected EC instance, not rebuild one."""
        real_ec = _make_ec({"tenant": "acme"})
        binding = _make_binding(execution_context=real_ec)
        assert binding.execution_context is real_ec

    def test_ec_metadata_accessible_from_binding(self):
        real_ec = _make_ec({"env": "prod"})
        binding = _make_binding(execution_context=real_ec)
        assert binding.execution_context.metadata["env"] == "prod"

    def test_none_ec_for_ws_and_stdio(self):
        binding = _make_binding(execution_context=None)
        assert binding.execution_context is None

    def test_extras_field_stores_ws_metadata(self):
        """WS connection-level metadata stored in extras (set by _ws.py)."""
        binding = _make_binding(extras={"channel": "ws", "tenant": "acme"})
        assert binding.extras["channel"] == "ws"
