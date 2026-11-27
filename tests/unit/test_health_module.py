"""Tests for optional MCP liveness and readiness support."""

from __future__ import annotations

import pytest

from lauren_mcp.server._health import (
    HealthCheckResult,
    HealthStatus,
    McpHealthModule,
    _overall_status,
    _run_checks,
)


@pytest.mark.asyncio
async def test_readiness_healthy_sync_and_async_checks() -> None:
    async def database() -> bool:
        return True

    results = await _run_checks({"cache": lambda: True, "database": database})

    assert results == {
        "cache": HealthStatus.HEALTHY,
        "database": HealthStatus.HEALTHY,
    }
    assert _overall_status(results) == (HealthStatus.HEALTHY, 200)


@pytest.mark.asyncio
async def test_readiness_degraded_is_still_ready() -> None:
    results = await _run_checks(
        {"upstream": lambda: HealthCheckResult(HealthStatus.DEGRADED)}
    )

    assert results["upstream"] is HealthStatus.DEGRADED
    assert _overall_status(results) == (HealthStatus.DEGRADED, 200)


@pytest.mark.asyncio
async def test_readiness_unhealthy_returns_service_unavailable() -> None:
    results = await _run_checks({"database": lambda: False})

    assert results["database"] is HealthStatus.UNHEALTHY
    assert _overall_status(results) == (HealthStatus.UNHEALTHY, 503)


@pytest.mark.asyncio
async def test_check_exceptions_fail_closed_without_exposing_details() -> None:
    def broken() -> bool:
        raise RuntimeError("password=do-not-leak")

    results = await _run_checks({"database": broken})

    assert results == {"database": HealthStatus.UNHEALTHY}
    assert _overall_status(results) == (HealthStatus.UNHEALTHY, 503)


@pytest.mark.asyncio
async def test_empty_check_set_is_healthy() -> None:
    assert await _run_checks({}) == {}
    assert _overall_status({}) == (HealthStatus.HEALTHY, 200)


def test_health_module_validates_prefix_and_checks() -> None:
    with pytest.raises(ValueError, match="absolute route path"):
        McpHealthModule.for_root(prefix="health")
    with pytest.raises(ValueError, match="must not end"):
        McpHealthModule.for_root(prefix="/health/")
    with pytest.raises(ValueError, match="non-empty"):
        McpHealthModule.for_root(checks={" ": lambda: True})
    with pytest.raises(TypeError, match="must be callable"):
        McpHealthModule.for_root(checks={"database": object()})  # type: ignore[dict-item]


def test_health_module_can_be_disabled() -> None:
    health_module = McpHealthModule.for_root(enabled=False)

    assert health_module is not None
