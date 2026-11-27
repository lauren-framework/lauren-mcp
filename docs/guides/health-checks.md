# Health checks

Lauren MCP applications can expose optional HTTP liveness and readiness endpoints.
The endpoints are ordinary Lauren routes and are composed alongside the MCP transport module.

## Configure the module

```python
from lauren import LaurenFactory, module
from lauren_mcp import HealthCheckResult, HealthStatus, McpHealthModule, McpServerModule

async def database_ready() -> bool:
    return await database.ping()

def upstream_health() -> HealthCheckResult:
    if upstream_is_slow():
        return HealthCheckResult(HealthStatus.DEGRADED)
    return HealthCheckResult(HealthStatus.HEALTHY)

mcp_module = McpServerModule.for_root(MyMcpServer, transport="streamable")
health_module = McpHealthModule.for_root(
    checks={
        "database": database_ready,
        "upstream": upstream_health,
    },
)

@module(imports=[mcp_module, health_module])
class AppModule:
    pass

app = LaurenFactory.create(AppModule)
```

By default the module exposes:

- `GET /health/live` — process liveness only; it never calls dependency checks.
- `GET /health/ready` — runs the configured checks and reports aggregate readiness.

Pass `prefix="/_internal/health"` to change the route prefix. Pass `enabled=False` to
compose an empty module when health routes are managed elsewhere. Health routes are opt-in:
they are not added by `McpServerModule.for_root()` automatically.

## Check outcomes

A check can be synchronous or asynchronous and may return:

- `True`: healthy.
- `False`: unhealthy; readiness returns HTTP 503.
- `HealthCheckResult(HealthStatus.DEGRADED)`: degraded but still ready; HTTP 200.
- `HealthCheckResult(HealthStatus.HEALTHY)`: healthy; HTTP 200.
- `HealthCheckResult(HealthStatus.UNHEALTHY)`: unhealthy; HTTP 503.

An exception or unsupported return value fails closed as unhealthy. The response includes
only each check's name and status; exception messages and arbitrary check details are never
returned. Use stable, non-sensitive check names.

## Deployment probes

For Kubernetes, use the endpoints as separate probes:

```yaml
livenessProbe:
  httpGet:
    path: /health/live
    port: 8000
  initialDelaySeconds: 5
  periodSeconds: 10
readinessProbe:
  httpGet:
    path: /health/ready
    port: 8000
  periodSeconds: 5
```

Container platforms with HTTP health checks can use `/health/live` for process liveness.
Use `/health/ready` when traffic should stop reaching an instance whose dependencies are
not ready. Keep these routes on a private network or protect them with the same ingress
policy as other operational endpoints when their availability should not be public.
