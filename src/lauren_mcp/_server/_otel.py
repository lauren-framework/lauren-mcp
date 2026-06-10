"""OpenTelemetry integration for the MCP dispatcher.

When ``opentelemetry-api`` is not installed, every function in this module is
a silent no-op.  Import costs are zero when OTel is absent — no monkey-patching,
no startup cost, no span overhead.
"""

from __future__ import annotations

import functools
import logging
from typing import Any

from lauren_mcp._mcp_version import LATEST as __version__

_logger = logging.getLogger(__name__)

try:
    from opentelemetry import context as otel_context
    from opentelemetry import trace
    from opentelemetry.trace import StatusCode

    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False


def is_otel_available() -> bool:
    """Return ``True`` when ``opentelemetry-api`` is installed."""
    return _OTEL_AVAILABLE


def _get_tracer() -> Any:
    """Return the OTel tracer for ``lauren-mcp``, or ``None``."""
    if not _OTEL_AVAILABLE:
        return None
    return trace.get_tracer("lauren-mcp", __version__)


def _extract_context(meta: dict[str, Any] | None) -> Any | None:
    """Extract W3C trace context from the JSON-RPC ``_meta`` field.

    Returns an OTel ``Context`` if ``traceparent`` is present and OTel is
    available; returns ``None`` otherwise.
    """
    if not _OTEL_AVAILABLE or not meta:
        return None
    traceparent = meta.get("traceparent")
    tracestate = meta.get("tracestate")
    if traceparent is None:
        return None
    carrier: dict[str, str] = {"traceparent": traceparent}
    if tracestate:
        carrier["tracestate"] = tracestate
    from opentelemetry.propagate import extract  # noqa: PLC0415

    return extract(carrier)


def instrument_dispatcher(dispatcher: Any) -> None:
    """Wrap *dispatcher*.dispatch() with an OTel span per MCP request.

    This function is idempotent: calling it twice on the same dispatcher
    instance is a no-op (the wrapper detects the ``_otel_instrumented`` flag).

    Span naming: ``mcp.<method>`` (e.g. ``"mcp.tools/call"``).

    Attributes set on every span:

    - ``mcp.method``      — JSON-RPC method name
    - ``mcp.request_id``  — JSON-RPC request id (string coercion)

    Attributes set for ``tools/call`` only:

    - ``mcp.tool_name``   — the ``params.name`` field

    Error handling:

    - On ``asyncio.CancelledError`` the span ends without error status.
    - On any other exception the span records the exception and sets
      ``StatusCode.ERROR``.
    - When the dispatcher returns a ``JsonRpcErrorResponse`` with code
      ``INTERNAL_ERROR`` the span sets ``StatusCode.ERROR`` with the error
      message.
    """
    if not _OTEL_AVAILABLE:
        return
    if getattr(dispatcher, "_otel_instrumented", False):
        return

    original_dispatch = dispatcher.dispatch

    @functools.wraps(original_dispatch)
    async def _instrumented_dispatch(request: Any) -> Any:
        tracer = _get_tracer()
        if tracer is None:
            return await original_dispatch(request)

        params_dict = request.params if isinstance(request.params, dict) else {}
        meta = params_dict.get("_meta") if isinstance(params_dict, dict) else None
        parent_ctx = _extract_context(meta if isinstance(meta, dict) else None)

        span_name = f"mcp.{request.method}"
        ctx_token = None
        if parent_ctx is not None:
            ctx_token = otel_context.attach(parent_ctx)

        try:
            with tracer.start_as_current_span(span_name) as span:
                span.set_attribute("mcp.method", request.method)
                if request.id is not None:
                    span.set_attribute("mcp.request_id", str(request.id))
                if request.method == "tools/call" and isinstance(params_dict, dict):
                    tool_name = params_dict.get("name")
                    if tool_name:
                        span.set_attribute("mcp.tool_name", str(tool_name))

                try:
                    response = await original_dispatch(request)
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_status(StatusCode.ERROR, str(exc))
                    raise

                # Check for INTERNAL_ERROR in the response
                from lauren_mcp._types import JsonRpcErrorResponse, McpErrorCode  # noqa: PLC0415

                if isinstance(response, JsonRpcErrorResponse):  # noqa: SIM102
                    if response.error.code == McpErrorCode.INTERNAL_ERROR:
                        span.set_status(StatusCode.ERROR, response.error.message)

                return response
        finally:
            if ctx_token is not None:
                otel_context.detach(ctx_token)

    dispatcher.dispatch = _instrumented_dispatch  # type: ignore[method-assign]
    dispatcher._otel_instrumented = True  # type: ignore[attr-defined]
