"""Metadata propagation helper — copies ``@use_*`` annotations from a source
class (typically an ``@mcp_server`` class) onto a generated transport
controller.

Uses :func:`~lauren.propagate_metadata` when available (``lauren>=1.7.0``),
and falls back to per-category application using the APIs that have been
available since ``lauren>=1.6.0``.

Supported categories and their runtime behaviour:
  - ``@use_guards``              → WS: enforced before @on_connect;
                                   SSE: per-request (Lauren HTTP pipeline).
  - ``@use_interceptors``        → WS: wraps @on_connect;
                                   SSE: wraps every handler call.
  - ``@use_middlewares``         → SSE: per-request middleware chain.
  - ``@use_encoder``             → SSE: custom JSON encoder for all routes.
  - ``@use_exception_handlers``  → SSE: per-controller exception handling.
  - ``@set_metadata``            → guards can read via ``ctx.get_metadata()``.
"""

from __future__ import annotations

from typing import Any


def _apply_server_metadata(source: Any, target: Any) -> None:
    """Copy all ``@use_*`` metadata from *source* onto *target*.

    Tries :func:`~lauren.propagate_metadata` first (available in
    ``lauren>=1.7.0``), then falls back to per-category application for
    ``lauren 1.6.x``.
    """
    import lauren  # noqa: PLC0415

    propagate_metadata = getattr(lauren, "propagate_metadata", None)
    if propagate_metadata is not None:
        propagate_metadata(source)(target)
        return

    # --- Fallback for lauren 1.6.x ---
    # reflect_guards/interceptors/middlewares are available since 1.6.0.
    from lauren import use_guards, use_interceptors, use_middlewares  # noqa: PLC0415
    from lauren.reflect import (  # noqa: PLC0415
        reflect_guards,
        reflect_interceptors,
        reflect_middlewares,
    )

    guards = reflect_guards(source)
    if guards:
        use_guards(*guards)(target)

    interceptors = reflect_interceptors(source)
    if interceptors:
        use_interceptors(*interceptors)(target)

    middlewares = reflect_middlewares(source)
    if middlewares:
        use_middlewares(*middlewares)(target)

    # Encoder, exception_handlers, and user metadata require direct __dict__
    # access in 1.6.x (no public reader for these yet).
    _USE_EXCEPTION_HANDLERS = "__lauren_use_exception_handlers__"
    _USE_ENCODER = "__lauren_use_encoder__"
    _SET_METADATA = "__lauren_metadata__"

    exc_handlers = (
        source.__dict__.get(_USE_EXCEPTION_HANDLERS)
        if isinstance(source, type)
        else getattr(source, _USE_EXCEPTION_HANDLERS, None)
    )
    if exc_handlers:
        from lauren import use_exception_handlers  # noqa: PLC0415

        use_exception_handlers(*exc_handlers)(target)

    enc = (
        source.__dict__.get(_USE_ENCODER)
        if isinstance(source, type)
        else getattr(source, _USE_ENCODER, None)
    )
    if enc is not None:
        from lauren import use_encoder  # noqa: PLC0415

        use_encoder(enc)(target)

    meta: dict[str, Any] = (
        dict(source.__dict__.get(_SET_METADATA, {}))
        if isinstance(source, type)
        else dict(getattr(source, _SET_METADATA, {}))
    )
    if meta:
        from lauren import set_metadata  # noqa: PLC0415

        for key, value in meta.items():
            set_metadata(key, value)(target)
