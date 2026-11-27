"""Optional liveness and readiness endpoints for Lauren MCP applications."""

from __future__ import annotations

import inspect
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias

from lauren import controller, get, module
from lauren.types import Headers, Response


class HealthStatus(StrEnum):
    """Possible outcomes for an application health check."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass(frozen=True, slots=True)
class HealthCheckResult:
    """A health-check outcome; details are intentionally excluded from HTTP output."""

    status: HealthStatus


HealthCheck: TypeAlias = Callable[
    [], bool | HealthCheckResult | Awaitable[bool | HealthCheckResult]
]


async def _run_checks(checks: Mapping[str, HealthCheck]) -> dict[str, HealthStatus]:
    """Run checks in declaration order and convert failures to safe statuses."""
    results: dict[str, HealthStatus] = {}
    for name, check in checks.items():
        try:
            outcome = check()
            if inspect.isawaitable(outcome):
                outcome = await outcome
            if isinstance(outcome, HealthCheckResult) and isinstance(
                outcome.status, HealthStatus
            ):
                status = outcome.status
            elif isinstance(outcome, bool):
                status = HealthStatus.HEALTHY if outcome else HealthStatus.UNHEALTHY
            else:
                status = HealthStatus.UNHEALTHY
        except Exception:
            # Exception text can contain credentials; never expose it over HTTP.
            status = HealthStatus.UNHEALTHY
        results[name] = status
    return results


def _overall_status(
    results: Mapping[str, HealthStatus],
) -> tuple[HealthStatus, int]:
    """Return the aggregate readiness state and corresponding HTTP status."""
    statuses = tuple(results.values())
    if HealthStatus.UNHEALTHY in statuses:
        return HealthStatus.UNHEALTHY, 503
    if HealthStatus.DEGRADED in statuses:
        return HealthStatus.DEGRADED, 200
    return HealthStatus.HEALTHY, 200


def _health_response(payload: dict[str, object], *, status: int = 200) -> Response:
    return Response(
        body=json.dumps(payload, separators=(",", ":")).encode(),
        status=status,
        headers=Headers([("content-type", "application/health+json")]),
    )


class McpHealthModule:
    """Factory for opt-in HTTP liveness and readiness routes."""

    @staticmethod
    def for_root(
        *,
        checks: Mapping[str, HealthCheck] | None = None,
        prefix: str = "/health",
        enabled: bool = True,
    ) -> type:
        """Build a module exposing GET {prefix}/live and GET {prefix}/ready.

        Checks may be synchronous or asynchronous. Return True for healthy,
        False for unhealthy, or HealthCheckResult for an explicit status.
        Degraded checks keep readiness HTTP 200; unhealthy checks return 503.
        Set enabled=False to compose an empty module without exposing routes.
        """
        if not isinstance(prefix, str) or not prefix.startswith("/"):
            raise ValueError("prefix must be an absolute route path")
        if prefix != "/" and prefix.endswith("/"):
            raise ValueError("prefix must not end with '/'")

        configured = dict(checks or {})
        for name, check in configured.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("health check names must be non-empty strings")
            if not callable(check):
                raise TypeError(f"health check {name!r} must be callable")

        if not enabled:
            @module()
            class _DisabledMcpHealthModule:
                pass

            return _DisabledMcpHealthModule

        @controller(prefix)
        class McpHealthController:
            @get("/live")
            async def live(self) -> Response:
                """Report process liveness without probing dependencies."""
                return _health_response({"status": HealthStatus.HEALTHY.value})

            @get("/ready")
            async def ready(self) -> Response:
                """Report dependency readiness without leaking check details."""
                results = await _run_checks(configured)
                overall, http_status = _overall_status(results)
                return _health_response(
                    {
                        "status": overall.value,
                        "checks": {name: result.value for name, result in results.items()},
                    },
                    status=http_status,
                )

        @module(controllers=[McpHealthController])
        class _McpHealthModule:
            pass

        return _McpHealthModule
