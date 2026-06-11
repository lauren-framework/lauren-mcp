"""Unit tests to improve coverage of _propagate.py and _otel.py."""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Pre-import the module under test so patching lauren mid-test works.
# _propagate only does `import lauren` inside the function body (lazy),
# so we can freely replace `lauren` in sys.modules before each call.
from lauren_mcp._server._propagate import _apply_server_metadata  # noqa: E402

# ---------------------------------------------------------------------------
# _propagate.py — both code paths
# ---------------------------------------------------------------------------


class _FakeTarget:
    """Bare object used as propagation target."""


class _FakeSource:
    """Source class with attribute dicts for 1.6.x fallback path."""


def _build_fake_lauren_with_propagate(applied_to: list[Any]) -> MagicMock:
    """Return a fake lauren module that has propagate_metadata (>=1.7.0 path)."""
    import lauren as real_lauren  # noqa: PLC0415

    fake = MagicMock(spec=real_lauren)

    def _fake_propagate(src: Any):
        def _inner(tgt: Any) -> None:
            applied_to.append((src, tgt))

        return _inner

    fake.propagate_metadata = _fake_propagate
    return fake


def _build_fake_lauren_no_propagate(
    *,
    guards: list[Any] | None = None,
    interceptors: list[Any] | None = None,
    middlewares: list[Any] | None = None,
    exc_handlers_call: list[Any] | None = None,
    encoders_call: list[Any] | None = None,
    metadata_call: list[tuple[str, Any]] | None = None,
) -> tuple[MagicMock, MagicMock]:
    """Return (fake_lauren, fake_reflect) for the 1.6.x fallback path."""
    import lauren as real_lauren  # noqa: PLC0415
    import lauren.reflect as real_reflect  # noqa: PLC0415

    fake = MagicMock(spec=real_lauren)
    # Remove propagate_metadata to force fallback path
    del fake.propagate_metadata

    def _use_guards(*args: Any):
        if guards is not None:
            guards.extend(args)
        return lambda t: None

    def _use_interceptors(*args: Any):
        if interceptors is not None:
            interceptors.extend(args)
        return lambda t: None

    def _use_middlewares(*args: Any):
        if middlewares is not None:
            middlewares.extend(args)
        return lambda t: None

    def _use_exception_handlers(*args: Any):
        if exc_handlers_call is not None:
            exc_handlers_call.extend(args)
        return lambda t: None

    def _use_encoder(enc: Any):
        if encoders_call is not None:
            encoders_call.append(enc)
        return lambda t: None

    def _set_metadata(key: str, value: Any):
        if metadata_call is not None:
            metadata_call.append((key, value))
        return lambda t: None

    fake.use_guards = _use_guards
    fake.use_interceptors = _use_interceptors
    fake.use_middlewares = _use_middlewares
    fake.use_exception_handlers = _use_exception_handlers
    fake.use_encoder = _use_encoder
    fake.set_metadata = _set_metadata

    fake_reflect = MagicMock(spec=real_reflect)
    return fake, fake_reflect


def test_propagate_new_path_calls_propagate_metadata() -> None:
    """When lauren.propagate_metadata exists, it is called as propagate_metadata(source)(target)."""
    source = _FakeSource()
    target = _FakeTarget()
    applied_to: list[Any] = []

    fake_lauren = _build_fake_lauren_with_propagate(applied_to)

    with patch.dict("sys.modules", {"lauren": fake_lauren}):
        _apply_server_metadata(source, target)

    assert len(applied_to) == 1
    assert applied_to[0] == (source, target)


def test_propagate_fallback_path_with_guards() -> None:
    """Fallback path (lauren 1.6.x) — reflect_guards returns values, use_guards called."""

    class _FakeGuard:
        pass

    source = _FakeSource()
    target = _FakeTarget()
    applied_guards: list[Any] = []

    fake_lauren, fake_reflect = _build_fake_lauren_no_propagate(guards=applied_guards)
    fake_reflect.reflect_guards = lambda src: [_FakeGuard]
    fake_reflect.reflect_interceptors = lambda src: []
    fake_reflect.reflect_middlewares = lambda src: []

    with patch.dict("sys.modules", {"lauren": fake_lauren, "lauren.reflect": fake_reflect}):
        _apply_server_metadata(source, target)

    assert _FakeGuard in applied_guards


def test_propagate_fallback_interceptors() -> None:
    """Fallback path — reflect_interceptors returns values, use_interceptors called."""

    class _FakeInterceptor:
        pass

    source = _FakeSource()
    target = _FakeTarget()
    applied_interceptors: list[Any] = []

    fake_lauren, fake_reflect = _build_fake_lauren_no_propagate(interceptors=applied_interceptors)
    fake_reflect.reflect_guards = lambda src: []
    fake_reflect.reflect_interceptors = lambda src: [_FakeInterceptor]
    fake_reflect.reflect_middlewares = lambda src: []

    with patch.dict("sys.modules", {"lauren": fake_lauren, "lauren.reflect": fake_reflect}):
        _apply_server_metadata(source, target)

    assert _FakeInterceptor in applied_interceptors


def test_propagate_fallback_middlewares() -> None:
    """Fallback path — reflect_middlewares returns values, use_middlewares called."""

    class _FakeMiddleware:
        pass

    source = _FakeSource()
    target = _FakeTarget()
    applied_middlewares: list[Any] = []

    fake_lauren, fake_reflect = _build_fake_lauren_no_propagate(middlewares=applied_middlewares)
    fake_reflect.reflect_guards = lambda src: []
    fake_reflect.reflect_interceptors = lambda src: []
    fake_reflect.reflect_middlewares = lambda src: [_FakeMiddleware]

    with patch.dict("sys.modules", {"lauren": fake_lauren, "lauren.reflect": fake_reflect}):
        _apply_server_metadata(source, target)

    assert _FakeMiddleware in applied_middlewares


def test_propagate_fallback_no_guards_when_empty() -> None:
    """Fallback path — if all reflect_* return empty, no use_* calls are made."""
    source = _FakeSource()
    target = _FakeTarget()
    guards: list[Any] = []
    interceptors: list[Any] = []
    middlewares: list[Any] = []

    fake_lauren, fake_reflect = _build_fake_lauren_no_propagate(
        guards=guards, interceptors=interceptors, middlewares=middlewares
    )
    fake_reflect.reflect_guards = lambda src: []
    fake_reflect.reflect_interceptors = lambda src: []
    fake_reflect.reflect_middlewares = lambda src: []

    with patch.dict("sys.modules", {"lauren": fake_lauren, "lauren.reflect": fake_reflect}):
        _apply_server_metadata(source, target)

    assert not guards
    assert not interceptors
    assert not middlewares


def test_propagate_fallback_exception_handlers_on_type() -> None:
    """Fallback path — __lauren_use_exception_handlers__ on a class triggers use_exception_handlers."""
    exc_calls: list[Any] = []
    fake_lauren, fake_reflect = _build_fake_lauren_no_propagate(exc_handlers_call=exc_calls)
    fake_reflect.reflect_guards = lambda src: []
    fake_reflect.reflect_interceptors = lambda src: []
    fake_reflect.reflect_middlewares = lambda src: []

    # Use a *type* (class) as source so __dict__.get branch runs.
    source = type("_Src", (), {"__lauren_use_exception_handlers__": ["FakeHandler"]})
    target = _FakeTarget()

    with patch.dict("sys.modules", {"lauren": fake_lauren, "lauren.reflect": fake_reflect}):
        _apply_server_metadata(source, target)

    assert "FakeHandler" in exc_calls


def test_propagate_fallback_exception_handlers_on_instance() -> None:
    """Fallback path — __lauren_use_exception_handlers__ on an instance triggers use_exception_handlers."""
    exc_calls: list[Any] = []
    fake_lauren, fake_reflect = _build_fake_lauren_no_propagate(exc_handlers_call=exc_calls)
    fake_reflect.reflect_guards = lambda src: []
    fake_reflect.reflect_interceptors = lambda src: []
    fake_reflect.reflect_middlewares = lambda src: []

    class _Inst:
        pass

    source = _Inst()
    source.__lauren_use_exception_handlers__ = ["InstanceHandler"]  # type: ignore[attr-defined]
    target = _FakeTarget()

    with patch.dict("sys.modules", {"lauren": fake_lauren, "lauren.reflect": fake_reflect}):
        _apply_server_metadata(source, target)

    assert "InstanceHandler" in exc_calls


def test_propagate_fallback_encoder_on_type() -> None:
    """Fallback path — __lauren_use_encoder__ on a class triggers use_encoder."""
    sentinel = object()
    encoders: list[Any] = []
    fake_lauren, fake_reflect = _build_fake_lauren_no_propagate(encoders_call=encoders)
    fake_reflect.reflect_guards = lambda src: []
    fake_reflect.reflect_interceptors = lambda src: []
    fake_reflect.reflect_middlewares = lambda src: []

    source = type("_Src", (), {"__lauren_use_encoder__": sentinel})
    target = _FakeTarget()

    with patch.dict("sys.modules", {"lauren": fake_lauren, "lauren.reflect": fake_reflect}):
        _apply_server_metadata(source, target)

    assert sentinel in encoders


def test_propagate_fallback_encoder_on_instance() -> None:
    """Fallback path — __lauren_use_encoder__ on an instance triggers use_encoder."""
    sentinel = object()
    encoders: list[Any] = []
    fake_lauren, fake_reflect = _build_fake_lauren_no_propagate(encoders_call=encoders)
    fake_reflect.reflect_guards = lambda src: []
    fake_reflect.reflect_interceptors = lambda src: []
    fake_reflect.reflect_middlewares = lambda src: []

    class _Inst:
        pass

    source = _Inst()
    source.__lauren_use_encoder__ = sentinel  # type: ignore[attr-defined]
    target = _FakeTarget()

    with patch.dict("sys.modules", {"lauren": fake_lauren, "lauren.reflect": fake_reflect}):
        _apply_server_metadata(source, target)

    assert sentinel in encoders


def test_propagate_fallback_set_metadata_on_type() -> None:
    """Fallback path — __lauren_metadata__ on a class triggers set_metadata per key."""
    meta_calls: list[tuple[str, Any]] = []
    fake_lauren, fake_reflect = _build_fake_lauren_no_propagate(metadata_call=meta_calls)
    fake_reflect.reflect_guards = lambda src: []
    fake_reflect.reflect_interceptors = lambda src: []
    fake_reflect.reflect_middlewares = lambda src: []

    source = type("_Src", (), {"__lauren_metadata__": {"role": "admin", "tier": "gold"}})
    target = _FakeTarget()

    with patch.dict("sys.modules", {"lauren": fake_lauren, "lauren.reflect": fake_reflect}):
        _apply_server_metadata(source, target)

    keys = {k for k, _ in meta_calls}
    assert "role" in keys
    assert "tier" in keys


def test_propagate_fallback_set_metadata_on_instance() -> None:
    """Fallback path — __lauren_metadata__ on an instance triggers set_metadata per key."""
    meta_calls: list[tuple[str, Any]] = []
    fake_lauren, fake_reflect = _build_fake_lauren_no_propagate(metadata_call=meta_calls)
    fake_reflect.reflect_guards = lambda src: []
    fake_reflect.reflect_interceptors = lambda src: []
    fake_reflect.reflect_middlewares = lambda src: []

    class _Inst:
        pass

    source = _Inst()
    source.__lauren_metadata__ = {"foo": "bar"}  # type: ignore[attr-defined]
    target = _FakeTarget()

    with patch.dict("sys.modules", {"lauren": fake_lauren, "lauren.reflect": fake_reflect}):
        _apply_server_metadata(source, target)

    assert ("foo", "bar") in meta_calls


# ---------------------------------------------------------------------------
# _otel.py — instrumentation logic using mocked opentelemetry
# ---------------------------------------------------------------------------


class _OtelRequest:
    """Fake JSON-RPC request for OTel tests."""

    def __init__(
        self,
        method: str,
        params: Any = None,
        req_id: int | str | None = 1,
    ) -> None:
        self.method = method
        self.params = params
        self.id = req_id


class _OtelDispatcher:
    """Minimal dispatcher stub for OTel tests."""

    def __init__(self, response: Any = None, side_effect: Exception | None = None) -> None:
        self._response = response or MagicMock()
        self._side_effect = side_effect
        self.dispatch_calls: list[Any] = []

    async def dispatch(self, request: Any) -> Any:
        self.dispatch_calls.append(request)
        if self._side_effect is not None:
            raise self._side_effect
        return self._response


def _build_otel_mocks() -> tuple[MagicMock, MagicMock, MagicMock, list[Any]]:
    """Build mock opentelemetry context, trace, and span objects.

    Returns (otel_context_mock, trace_mock, span_mock, finished_spans_list).
    """
    finished_spans: list[Any] = []

    span = MagicMock()
    span.__enter__ = MagicMock(return_value=span)
    span.__exit__ = MagicMock(return_value=False)

    tracer = MagicMock()
    tracer.start_as_current_span = MagicMock(return_value=span)

    trace_mod = MagicMock()
    trace_mod.get_tracer = MagicMock(return_value=tracer)

    # StatusCode-like enum
    from enum import Enum

    class _FakeStatusCode(Enum):
        OK = "OK"
        ERROR = "ERROR"
        UNSET = "UNSET"

    trace_mod.StatusCode = _FakeStatusCode

    otel_context = MagicMock()
    token = MagicMock()
    otel_context.attach = MagicMock(return_value=token)
    otel_context.detach = MagicMock()

    propagate_mod = MagicMock()
    propagate_mod.extract = MagicMock(return_value={"ctx": "fake"})

    return otel_context, trace_mod, tracer, span, propagate_mod, _FakeStatusCode


def _patch_otel_module(
    otel_context: Any,
    trace_mod: Any,
    status_code_cls: Any,
    propagate_mod: Any,
) -> Any:
    """Patch sys.modules with fake otel modules and return a context manager."""
    import sys

    class _PatchCtx:
        def __enter__(self) -> Any:
            import importlib

            # Install fake modules into sys.modules
            fake_otel_pkg = MagicMock()
            fake_otel_pkg.context = otel_context
            fake_otel_pkg.trace = trace_mod

            sys.modules.setdefault("opentelemetry", fake_otel_pkg)
            sys.modules["opentelemetry.context"] = otel_context
            sys.modules["opentelemetry.trace"] = trace_mod
            sys.modules["opentelemetry.propagate"] = propagate_mod

            # Force reload of the otel module so _OTEL_AVAILABLE is re-evaluated
            import lauren_mcp._server._otel as otel_mod

            self._otel_mod = otel_mod
            self._orig_avail = otel_mod._OTEL_AVAILABLE
            self._orig_trace = getattr(otel_mod, "trace", None)
            self._orig_ctx = getattr(otel_mod, "otel_context", None)
            self._orig_sc = getattr(otel_mod, "StatusCode", None)

            # Directly patch the module-level names that were bound at import
            otel_mod._OTEL_AVAILABLE = True
            otel_mod.trace = trace_mod
            otel_mod.otel_context = otel_context
            otel_mod.StatusCode = status_code_cls
            return otel_mod

        def __exit__(self, *args: Any) -> None:
            self._otel_mod._OTEL_AVAILABLE = self._orig_avail
            if self._orig_trace is not None:
                self._otel_mod.trace = self._orig_trace
            if self._orig_ctx is not None:
                self._otel_mod.otel_context = self._orig_ctx
            if self._orig_sc is not None:
                self._otel_mod.StatusCode = self._orig_sc

    return _PatchCtx()


def test_otel_get_tracer_returns_none_when_unavailable() -> None:
    import lauren_mcp._server._otel as otel_mod

    orig = otel_mod._OTEL_AVAILABLE
    try:
        otel_mod._OTEL_AVAILABLE = False
        result = otel_mod._get_tracer()
        assert result is None
    finally:
        otel_mod._OTEL_AVAILABLE = orig


def test_otel_get_tracer_returns_tracer_when_available() -> None:
    otel_context, trace_mod, tracer, span, propagate_mod, StatusCode = _build_otel_mocks()
    with _patch_otel_module(otel_context, trace_mod, StatusCode, propagate_mod) as otel_mod:
        result = otel_mod._get_tracer()
    assert result is not None


def test_otel_extract_context_none_when_unavailable() -> None:
    import lauren_mcp._server._otel as otel_mod

    orig = otel_mod._OTEL_AVAILABLE
    try:
        otel_mod._OTEL_AVAILABLE = False
        result = otel_mod._extract_context({"traceparent": "00-abc123-def456-01"})
        assert result is None
    finally:
        otel_mod._OTEL_AVAILABLE = orig


def test_otel_extract_context_none_when_no_meta() -> None:
    otel_context, trace_mod, tracer, span, propagate_mod, StatusCode = _build_otel_mocks()
    with _patch_otel_module(otel_context, trace_mod, StatusCode, propagate_mod) as otel_mod:
        result = otel_mod._extract_context(None)
    assert result is None


def test_otel_extract_context_none_when_no_traceparent() -> None:
    otel_context, trace_mod, tracer, span, propagate_mod, StatusCode = _build_otel_mocks()
    with _patch_otel_module(otel_context, trace_mod, StatusCode, propagate_mod) as otel_mod:
        result = otel_mod._extract_context({"tracestate": "some-state"})
    assert result is None


def test_otel_extract_context_with_traceparent() -> None:
    otel_context, trace_mod, tracer, span, propagate_mod, StatusCode = _build_otel_mocks()
    with _patch_otel_module(otel_context, trace_mod, StatusCode, propagate_mod) as otel_mod:
        result = otel_mod._extract_context(
            {"traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"}
        )
    # propagate.extract was called → returns the fake context dict
    assert result is not None


def test_otel_extract_context_with_tracestate() -> None:
    otel_context, trace_mod, tracer, span, propagate_mod, StatusCode = _build_otel_mocks()
    with _patch_otel_module(otel_context, trace_mod, StatusCode, propagate_mod) as otel_mod:
        result = otel_mod._extract_context(
            {
                "traceparent": "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
                "tracestate": "vendor=value",
            }
        )
    assert result is not None


async def test_otel_instrument_dispatcher_runs_dispatch() -> None:
    """Instrumented dispatcher calls through to the original dispatch."""
    otel_context, trace_mod, tracer, span, propagate_mod, StatusCode = _build_otel_mocks()
    fake_response = MagicMock()

    d = _OtelDispatcher(response=fake_response)
    with _patch_otel_module(otel_context, trace_mod, StatusCode, propagate_mod) as otel_mod:
        otel_mod.instrument_dispatcher(d)
        req = _OtelRequest("tools/list", params={}, req_id=42)
        result = await d.dispatch(req)

    assert result is fake_response
    assert len(d.dispatch_calls) == 1


async def test_otel_instrument_dispatcher_sets_method_attribute() -> None:
    """Span receives mcp.method attribute."""
    otel_context, trace_mod, tracer, span, propagate_mod, StatusCode = _build_otel_mocks()
    fake_response = MagicMock()

    d = _OtelDispatcher(response=fake_response)
    with _patch_otel_module(otel_context, trace_mod, StatusCode, propagate_mod) as otel_mod:
        otel_mod.instrument_dispatcher(d)
        req = _OtelRequest("tools/list", params={}, req_id=5)
        await d.dispatch(req)

    span.set_attribute.assert_any_call("mcp.method", "tools/list")


async def test_otel_instrument_dispatcher_sets_request_id() -> None:
    """Span receives mcp.request_id attribute when id is not None."""
    otel_context, trace_mod, tracer, span, propagate_mod, StatusCode = _build_otel_mocks()
    fake_response = MagicMock()

    d = _OtelDispatcher(response=fake_response)
    with _patch_otel_module(otel_context, trace_mod, StatusCode, propagate_mod) as otel_mod:
        otel_mod.instrument_dispatcher(d)
        req = _OtelRequest("tools/list", params={}, req_id=99)
        await d.dispatch(req)

    span.set_attribute.assert_any_call("mcp.request_id", "99")


async def test_otel_instrument_dispatcher_sets_tool_name_for_tools_call() -> None:
    """tools/call sets the mcp.tool_name span attribute."""
    otel_context, trace_mod, tracer, span, propagate_mod, StatusCode = _build_otel_mocks()
    fake_response = MagicMock()

    d = _OtelDispatcher(response=fake_response)
    with _patch_otel_module(otel_context, trace_mod, StatusCode, propagate_mod) as otel_mod:
        otel_mod.instrument_dispatcher(d)
        req = _OtelRequest("tools/call", params={"name": "my_tool"}, req_id=7)
        await d.dispatch(req)

    span.set_attribute.assert_any_call("mcp.tool_name", "my_tool")


async def test_otel_instrument_dispatcher_no_tool_name_when_missing() -> None:
    """tools/call without name param does not set mcp.tool_name."""
    otel_context, trace_mod, tracer, span, propagate_mod, StatusCode = _build_otel_mocks()
    fake_response = MagicMock()

    d = _OtelDispatcher(response=fake_response)
    with _patch_otel_module(otel_context, trace_mod, StatusCode, propagate_mod) as otel_mod:
        otel_mod.instrument_dispatcher(d)
        req = _OtelRequest("tools/call", params={}, req_id=8)
        await d.dispatch(req)

    calls = [c[0][0] for c in span.set_attribute.call_args_list]
    assert "mcp.tool_name" not in calls


async def test_otel_instrument_dispatcher_no_id_skips_request_id() -> None:
    """request.id = None → mcp.request_id not set."""
    otel_context, trace_mod, tracer, span, propagate_mod, StatusCode = _build_otel_mocks()
    fake_response = MagicMock()

    d = _OtelDispatcher(response=fake_response)
    with _patch_otel_module(otel_context, trace_mod, StatusCode, propagate_mod) as otel_mod:
        otel_mod.instrument_dispatcher(d)
        req = _OtelRequest("notifications/initialized", params=None, req_id=None)
        await d.dispatch(req)

    calls = [c[0][0] for c in span.set_attribute.call_args_list]
    assert "mcp.request_id" not in calls


async def test_otel_instrument_dispatcher_records_exception() -> None:
    """Exceptions from dispatch are recorded on the span and re-raised."""
    otel_context, trace_mod, tracer, span, propagate_mod, StatusCode = _build_otel_mocks()
    boom = RuntimeError("boom")

    d = _OtelDispatcher(side_effect=boom)
    with _patch_otel_module(otel_context, trace_mod, StatusCode, propagate_mod) as otel_mod:
        otel_mod.instrument_dispatcher(d)
        req = _OtelRequest("tools/call", params={"name": "bad"}, req_id=3)
        with pytest.raises(RuntimeError, match="boom"):
            await d.dispatch(req)

    span.record_exception.assert_called_once_with(boom)
    span.set_status.assert_called()


async def test_otel_instrument_dispatcher_internal_error_sets_span_error() -> None:
    """JsonRpcErrorResponse with INTERNAL_ERROR sets span status to ERROR."""
    from lauren_mcp._types import JsonRpcError, JsonRpcErrorResponse, McpErrorCode

    otel_context, trace_mod, tracer, span, propagate_mod, StatusCode = _build_otel_mocks()

    error_response = JsonRpcErrorResponse(
        id=1,
        error=JsonRpcError(code=McpErrorCode.INTERNAL_ERROR, message="Internal failure"),
    )
    d = _OtelDispatcher(response=error_response)

    with _patch_otel_module(otel_context, trace_mod, StatusCode, propagate_mod) as otel_mod:
        otel_mod.instrument_dispatcher(d)
        req = _OtelRequest("tools/call", params={}, req_id=1)
        result = await d.dispatch(req)

    assert result is error_response
    span.set_status.assert_called()


async def test_otel_instrument_dispatcher_attaches_parent_context() -> None:
    """When traceparent is in _meta, otel_context.attach is called."""
    otel_context, trace_mod, tracer, span, propagate_mod, StatusCode = _build_otel_mocks()
    fake_response = MagicMock()

    d = _OtelDispatcher(response=fake_response)
    traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    with _patch_otel_module(otel_context, trace_mod, StatusCode, propagate_mod) as otel_mod:
        otel_mod.instrument_dispatcher(d)
        req = _OtelRequest(
            "tools/list",
            params={"_meta": {"traceparent": traceparent}},
            req_id=10,
        )
        await d.dispatch(req)

    otel_context.attach.assert_called_once()
    otel_context.detach.assert_called_once()


async def test_otel_instrument_dispatcher_idempotent() -> None:
    """Calling instrument_dispatcher twice does not double-wrap."""
    otel_context, trace_mod, tracer, span, propagate_mod, StatusCode = _build_otel_mocks()
    fake_response = MagicMock()

    d = _OtelDispatcher(response=fake_response)
    with _patch_otel_module(otel_context, trace_mod, StatusCode, propagate_mod) as otel_mod:
        otel_mod.instrument_dispatcher(d)
        first = d.dispatch
        otel_mod.instrument_dispatcher(d)
        assert d.dispatch is first
