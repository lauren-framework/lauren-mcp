# Deployment guide

This guide describes production deployment patterns for `lauren-mcp`. The examples
assume an application module named `myapp.py` that exports a Lauren ASGI app as
`app`. Choose one transport deliberately and expose it only behind an authenticated,
TLS-terminating ingress when it is reachable outside a trusted network.

## Application entry point

```python
# myapp.py
from lauren import LaurenFactory, module
from lauren_mcp import McpServerModule, mcp_server, mcp_tool

@mcp_server("/mcp", transport="streamable")
class ExampleServer:
    @mcp_tool()
    async def health(self) -> dict[str, str]:
        """Return an application-level health response."""
        return {"status": "ok"}

@module(imports=[McpServerModule.for_root(ExampleServer, transport="streamable")])
class AppModule:
    pass

app = LaurenFactory.create(AppModule)
```

Install the HTTP server extra and start the ASGI application:

```bash
pip install "lauren-mcp[cli]"
uvicorn myapp:app --host 0.0.0.0 --port 8000
```

Do not treat an MCP tool named `health` as a platform health endpoint. Configure
liveness and readiness probes against endpoints supplied by your hosting application
or ingress, and keep those endpoints independent of MCP session state.

## Docker

A minimal multi-stage image keeps build tooling out of the runtime image.

```dockerfile
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir ".[cli]"
EXPOSE 8000
USER 10001
CMD ["uvicorn", "myapp:app", "--host", "0.0.0.0", "--port", "8000"]
```

Build and run:

```bash
docker build -t example-mcp:local .
docker run --rm -p 8000:8000 example-mcp:local
```

For production, pin the base image by digest, install from a locked dependency set,
run as a non-root user, provide secrets through the platform secret manager, and
configure CPU/memory limits. Do not bake credentials into the image or pass them
as build arguments.

## Kubernetes

Deploy multiple replicas behind a ClusterIP Service and an ingress that enforces
TLS and your authentication policy. The following is a starting point; replace the
image and adapt probes to endpoints implemented by the hosting application.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: example-mcp
spec:
  replicas: 2
  selector:
    matchLabels:
      app: example-mcp
  template:
    metadata:
      labels:
        app: example-mcp
    spec:
      containers:
        - name: mcp
          image: example-mcp:1.0.0
          ports:
            - name: http
              containerPort: 8000
          resources:
            requests:
              cpu: 100m
              memory: 128Mi
            limits:
              cpu: "1"
              memory: 512Mi
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            runAsNonRoot: true
            runAsUser: 10001
---
apiVersion: v1
kind: Service
metadata:
  name: example-mcp
spec:
  selector:
    app: example-mcp
  ports:
    - name: http
      port: 80
      targetPort: http
```

Use sticky routing only if the selected transport or session store requires it.
For horizontally scaled SSE deployments, session state and message queues must be
shared or requests must be routed consistently to the owning replica. Do not assume
an in-memory session store is cluster-safe. Configure graceful termination so the
process has time to stop accepting new work and close active sessions.

## Serverless and edge platforms

Serverless support depends on the platform's Python runtime, ASGI adapter, WebSocket
support, execution duration, and connection lifetime. A stateless HTTP request/response
adapter is generally a better fit than long-lived stdio or WebSocket processes.
Before deploying, verify that the platform supports the exact Streamable HTTP
semantics required by your MCP clients, including streaming responses if used.

Recommended deployment checklist:

- Use Streamable HTTP where the platform supports it; do not assume WebSocket or SSE
  connections can remain open indefinitely.
- Keep durable state outside the function instance. Treat process memory as ephemeral.
- Set platform request, execution and concurrency limits with headroom for tool calls.
- Authenticate every request and derive tenant identity from verified credentials,
  never from an untrusted request parameter.
- Ensure cancellation and client disconnects propagate to tool execution.
- Test cold starts, concurrent requests, streaming, timeout behaviour and retries on
  the actual target platform.
- If the platform cannot satisfy the transport lifecycle requirements, deploy the
  MCP server as a conventional container service instead.

## Operational security

- Terminate TLS at a trusted ingress and restrict network access to the MCP route.
- Apply authentication and per-tenant authorization before dispatching tools.
- Treat tool arguments, roots, headers and remote server metadata as untrusted input.
- Use outbound network allowlists when tools or clients can contact user-controlled URLs.
- Set bounded request sizes, connection limits, timeouts and concurrency limits at
  both the ingress and application layers.
- Export logs, traces and metrics without recording secrets or raw sensitive arguments.
- Test shutdown behaviour and ensure subprocesses are not orphaned.

This guide is a deployment pattern, not a claim that every hosting platform or
transport combination has been integration-tested by this project.
