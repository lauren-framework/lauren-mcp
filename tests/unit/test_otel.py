"""Unit tests for OTel instrumentation helpers."""

from __future__ import annotations

import pytest

from lauren_mcp._server._otel import instrument_dispatcher, is_otel_available


class _FakeDispatcher:
    """Minimal dispatcher stub for OTel tests."""

    def __init__(self) -> None:
        self.dispatch_calls: list[str] = []

    async def dispatch(self, request):
        self.dispatch_calls.append(request.method)
        return object()  # fake response


def test_is_otel_available_returns_bool() -> None:
    result = is_otel_available()
    assert isinstance(result, bool)


def test_instrument_dispatcher_when_otel_absent_is_noop() -> None:
    """When OTel is not installed, instrument_dispatcher should be a no-op."""
    import lauren_mcp._server._otel as otel_mod

    original_flag = otel_mod._OTEL_AVAILABLE
    try:
        # Simulate OTel absent
        otel_mod._OTEL_AVAILABLE = False
        d = _FakeDispatcher()
        # The dispatch attribute is NOT replaced (no __dict__ entry added)
        dispatch_before = d.__dict__.get("dispatch")  # Should be None (not in instance dict)
        instrument_dispatcher(d)
        dispatch_after = d.__dict__.get("dispatch")  # Should still be None
        assert dispatch_before is None
        assert dispatch_after is None
        assert not getattr(d, "_otel_instrumented", False)
    finally:
        otel_mod._OTEL_AVAILABLE = original_flag


def test_instrument_dispatcher_idempotent() -> None:
    """Calling instrument_dispatcher twice should not double-wrap."""
    import lauren_mcp._server._otel as otel_mod

    if not otel_mod._OTEL_AVAILABLE:
        pytest.skip("opentelemetry-api not installed")

    d = _FakeDispatcher()
    instrument_dispatcher(d)
    first_patched = d.dispatch
    instrument_dispatcher(d)  # second call
    assert d.dispatch is first_patched  # not re-wrapped


async def test_instrument_dispatcher_wraps_dispatch() -> None:
    """When OTel is available, dispatch is replaced by a wrapper."""
    import lauren_mcp._server._otel as otel_mod

    if not otel_mod._OTEL_AVAILABLE:
        pytest.skip("opentelemetry-api not installed")

    d = _FakeDispatcher()
    original = d.dispatch
    instrument_dispatcher(d)
    assert d.dispatch is not original
    assert getattr(d, "_otel_instrumented", False) is True
