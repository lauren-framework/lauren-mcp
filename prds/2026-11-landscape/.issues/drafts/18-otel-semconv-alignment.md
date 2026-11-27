**PRD:** [`prd-otel-semconv-alignment.md`](https://github.com/lauren-framework/lauren-mcp/blob/docs/mcp-landscape-2026-11/prds/2026-11-landscape/prd-otel-semconv-alignment.md)
**Priority:** P2 — Traces are emitted, but attribute names predate the current MCP semantic conventions, so our spans do not group with others
**Theme:** Ecosystem
**Key evidence:** E-180, E-181, E-182 — see `EVIDENCE.md` in the same directory.

## Problem

lauren-mcp **already emits OpenTelemetry traces**: `_server/_otel.py` is 138 lines, is wired into
the module factory, and wraps every JSON-RPC dispatch in a span. This PRD does not build
instrumentation — it **renames and reshapes the instrumentation that exists**, and adds the one
signal the published convention defines but the repo never emits.

That is the priority argument, stated plainly: **every other PRD in this directory adds
behaviour, surface area or protocol machinery. This one changes three string literals, one span
name, one span kind, and one absent signal.** For a few hundred lines of diff — most of it tests —
lauren-mcp stops emitting a private telemetry dialect that no MCP-aware backend or collector
rename-processor understands, and starts emitting the one the OpenTelemetry GenAI registry
defines (E-181).

## Goals

- Emit **exactly** the canonical `mcp.*` names of the GenAI registry (E-181); nothing under
  `mcp.` that is not canonical — non-semantic keys get a package namespace.
- Structure spans per `mcp-server-span.md` / `mcp-client-span.md` (E-182): `SERVER`/`CLIENT`
  kinds, operation+target names, server span a child of the client span.
- Emit the client operation-duration metric per `mcp-client-operation-duration-metric.md`
  (E-182) with a stated cardinality budget and an explicit deny-list of labels.
- Propagate `traceparent`/`tracestate` both ways over Streamable HTTP, SSE, WebSocket and stdio.
- Keep existing dashboards working for one minor release (dual emission), then remove the old
  names on a published schedule.

## Acceptance criteria



---

Drafted from the 2026-11 MCP landscape review (evidence retrieved 2026-11-26). Full PRD, evidence register (`EVIDENCE.md`) and `VERSIONS-MATRIX.md` live in `prds/2026-11-landscape/` on branch `docs/mcp-landscape-2026-11`.
