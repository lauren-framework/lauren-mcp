# PRD — Align lauren-mcp's OpenTelemetry Output with the Current MCP Semantic Conventions

**Status:** Draft
**Date:** 2026-11-26
**Priority:** **P2**
**Scope:** `src/lauren_mcp/_server/_otel.py` (whole module), `instrument_otel` in
`src/lauren_mcp/server/_module.py`, the four server transports, the three remote clients
under `src/lauren_mcp/_client/`, and the missing `otel` extra in `pyproject.toml`.

---

## 1. Problem Statement

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

The problem is not that lauren-mcp forgot to instrument. It is that it instrumented a **third
dialect**.

### 1.1 What the module emits today — every attribute string, verified

`grep -n 'set_attribute' src/lauren_mcp/_server/_otel.py` returns exactly three lines:

```python
# src/lauren_mcp/_server/_otel.py  line 103
        span_name = f"mcp.{request.method}"
```

```python
# src/lauren_mcp/_server/_otel.py  line 109-116
            with tracer.start_as_current_span(span_name) as span:
                span.set_attribute("mcp.method", request.method)
                if request.id is not None:
                    span.set_attribute("mcp.request_id", str(request.id))
                if request.method == "tools/call" and isinstance(params_dict, dict):
                    tool_name = params_dict.get("name")
                    if tool_name:
                        span.set_attribute("mcp.tool_name", str(tool_name))
```

| | Status | Where |
|---|---|---|
| `mcp.method`, `mcp.request_id`, `mcp.tool_name` | **private dialect** — never published anywhere | `_otel.py:110,112,116` |
| `mcp-method-name`, `mcp-protocol-version`, `mcp-resource-uri`, `mcp-session-id` | **Deprecated**, under a heading titled *"MCP Attributes (Moved)"* | old core page (E-180) |
| `mcp.method.name`, `mcp.protocol.version`, `mcp.resource.uri`, `mcp.session.id`, `mcp.tool.name` | **Canonical** | GenAI registry `docs/registry/attributes/mcp.md` (E-181) |

The current strings match *neither* the deprecated names *nor* the canonical ones, so no
dashboard queries them and no collector rewrites them - real telemetry that every consumer built for
the convention cannot read.

### 1.2 Three defects beyond the names

1. **No span kind.** `start_as_current_span(span_name)` at `_otel.py:109` passes no `kind=`, so every
   span is `SpanKind.INTERNAL`. A span handling an inbound MCP request is `SERVER`; backends keying
   service maps or RED metrics off `span.kind` do not see lauren-mcp at all.
2. **The instrumentation scope reports the protocol version as the library version.**
   `_otel.py:14` imports `LATEST as __version__` from `_mcp_version.py` (value `"2025-11-25"`) and
   `_otel.py:37` returns `trace.get_tracer("lauren-mcp", __version__)`. The semconv revision
   belongs in the tracer's **`schema_url`**, which the call does not pass — exactly why a registry
   bump should change one constant, not every attribute string.
3. **No metric.** `grep -rn 'get_meter' src/` returns nothing: a tracer (`_otel.py:33`) and no meter,
   so the operation-duration metric of E-182 does not exist in the output at all.

And a packaging defect that blocks adoption — `_module.py:559-562` raises with *"install it with:
pip install 'lauren-mcp[otel]'"*, but `pyproject.toml:32-46` declares only `ws`, `http`,
`pydantic`, `msgspec`, `cli` and `all` (`pyproject.toml:37`). **There is no `otel` extra and no
`opentelemetry` dependency anywhere in the file**, so the documented install path cannot work.

### 1.3 Why now

The attributes were **moved out of** the core semantic conventions: the old page still answers
the URL every dashboard links to, but says "Moved", and its four `mcp-*` attributes carry a
**Deprecated** badge (E-180). The live definitions are in the GenAI repo (E-181), which publishes
the three reports this PRD implements against (E-182).

So the cost is **monotonically increasing**: dual-emitting both spellings is a complete answer only
while the deprecated names are still documented. Once they are deleted from the old page the §7
window is gone, and users must cut from `mcp.method` to `mcp.method.name` with no overlap.

---

## 2. Goals

- Emit **exactly** the canonical `mcp.*` names of the GenAI registry (E-181); nothing under
  `mcp.` that is not canonical — non-semantic keys get a package namespace.
- Structure spans per `mcp-server-span.md` / `mcp-client-span.md` (E-182): `SERVER`/`CLIENT`
  kinds, operation+target names, server span a child of the client span.
- Emit the client operation-duration metric per `mcp-client-operation-duration-metric.md`
  (E-182) with a stated cardinality budget and an explicit deny-list of labels.
- Propagate `traceparent`/`tracestate` both ways over Streamable HTTP, SSE, WebSocket and stdio.
- Keep existing dashboards working for one minor release (dual emission), then remove the old
  names on a published schedule.

## 3. Non-Goals

- **Changing what is traced.** `instrument_dispatcher` still wraps `dispatcher.dispatch` and
  nothing else (`_otel.py:60-91`).
- **Sampling, exporters, SDK configuration.** lauren-mcp stays `opentelemetry-api`-only; the
  "silent no-op when absent" contract (`_otel.py:3-4`) is preserved.
- **Logs / trace-log correlation.**
- **A canonical server-side duration metric** — none is published (§4.3).
- **`mcp.prompt.name` for `prompts/get`** — new extraction rather than alignment (§9.2).

---

## lauren-mcp Advantages

- **Nothing has to be built.** The instrumentation exists, is wired into `module()`, is
  idempotent (`_otel.py:88-89`), and degrades to a no-op without the SDK.
- **The carrier plumbing is half-there.** `_extract_context` (`_otel.py:40-57`) already builds a W3C
  carrier and calls `extract()`; the wrapper already reads `params._meta` (`_otel.py:99`) and attaches
  parent context (`_otel.py:105-106`). This adds a carrier source, not a propagation system.
- **stdio gets propagation for free**, because the carrier is keyed on `params._meta` — the
  mechanism that serves HTTP headers also serves pipes.
- **One switch, whole-fleet fix.** Every span goes through one wrapper (`_otel.py:94`), so dual
  emission is one `if` in one function.
- **The cardinality hazards are already absent** — no session id, no request-id metric label —
  so §4.3's deny-list is preventative, not remedial.
---

## 4. Design

### 4.1 The renamed attribute surface — name by name

| # | Today (`path:line`) | Deprecated (E-180) | Canonical (E-181) | Type | Cardinality |
|---|---|---|---|---|---|
| 1 | `mcp.method` — `_otel.py:110` | `mcp-method-name` | **`mcp.method.name`** | string enum | low (~20) |
| 2 | `mcp.tool_name` — `_otel.py:116` | *(none published)* | **`mcp.tool.name`** | string | low (tool count) |
| 3 | `mcp.request_id` — `_otel.py:112` | *(none; never a convention attribute)* | **`lauren_mcp.request.id`** (package-namespaced) | string | **unbounded — span only** |
| 4 | not emitted | `mcp-protocol-version` | **`mcp.protocol.version`** | string enum | low (4, `_mcp_version.py:7`) |
| 5 | not emitted | `mcp-resource-uri` | **`mcp.resource.uri`** | string URI | **unbounded — span only** |
| 6 | not emitted | `mcp-session-id` | **`mcp.session.id`** | string | **never emitted (§4.6)** |

Row 3 is namespaced because OTel requires non-registry keys to carry the emitter's namespace
(`<company>.<key>`), and `mcp.request_id` claims `mcp.` while being in no registry; the value -
linking a span to the request id users quote in bug reports - is kept. Row 4 is a four-value enum
(`_mcp_version.py:7`), safe on spans *and* metrics. Row 5 reads the `params["uri"]` already in scope
(`_otel.py:99,114`). Row 6 is never emitted (§4.6).

```python
# src/lauren_mcp/_server/_otel.py  (replaces lines 103-116)
        target = _span_target(request.method, params_dict)
        span_name = f"{request.method} {target}" if target else request.method
        attrs = {"mcp.method.name": request.method,
                 "mcp.protocol.version": protocol_version}
        if target:
            attrs[_TARGET_ATTR[request.method]] = target
        if request.id is not None:
            attrs["lauren_mcp.request.id"] = str(request.id)

        with tracer.start_as_current_span(span_name, kind=span_kind, attributes=attrs) as span:
            ...
```

where `_TARGET_ATTR` maps `tools/call` → `mcp.tool.name`, `resources/read` →
`mcp.resource.uri` and `prompts/get` → `mcp.prompt.name`, `_span_target` reads the matching
`params` field (`name` / `uri` / `name`), and the `prompts/get` entry is the §9.2 decision.

### 4.2 Span naming and structure

One span per dispatch, because the wrapper replaces `Dispatcher.dispatch` itself
(`_dispatcher.py:101`, called from `_streamable.py:277`, `_sse.py:222`, `_ws.py:243` and
`_stdio.py:63`), so no per-method plumbing exists or is needed.

The published span reports (E-182) define one span per MCP operation per side, named after the
operation and its target, target omitted when there is none. That replaces
`f"mcp.{request.method}"` (`_otel.py:103`), which embeds the JSON-RPC method verbatim, carries the
vendor namespace into the span *name*, and gives every `tools/call` in the process the same name —
so no backend can break latency down by tool without reading an attribute.

| | Today | Target |
|---|---|---|
| Server span name | `mcp.tools/call` | `tools/call get_weather` |
| Server span kind | `INTERNAL` (default, `_otel.py:109`) | `SERVER` |
| Client span name / kind | — (no client spans exist) | `tools/call get_weather` / `CLIENT` |
| Parent/child | — | server span child of the client span via §4.4 |

Kind is a one-word diff that changes what the data means (`SERVER`: "this process received the
request"; `INTERNAL`: "a step inside some other operation"), and it is a parameter because the wrapper
also serves the embedded/bridge path. Error mapping is unchanged (`_otel.py:122`, `_otel.py:130`,
`_otel.py:79`) except for `error.type` on the metric path. The signature becomes `instrument_dispatcher(dispatcher, *,
semconv=SemconvMode.DUAL, span_kind=SpanKind.SERVER)`.

### 4.3 The operation-duration metric

No meter exists today — `_get_tracer` (`_otel.py:33-37`) is the only instrument factory. This adds
one, on the **client** side, because that is the metric the registry publishes (E-182).

| Field | Value |
|---|---|
| Name | `mcp.client.operation.duration` |
| Instrument | Histogram |
| Unit | `s` — seconds, not milliseconds, not nanoseconds |
| Buckets | SDK defaults; no custom boundaries |
| Emitted from | the three remote clients, once at the transport-call boundary |

**Attribute allow-list (the whole set):** `mcp.method.name`, `mcp.tool.name`,
`mcp.protocol.version`, `error.type`, `server.address`, `server.port`.

**Attributes that must NOT be metric labels** — a histogram label is forever:

| Attribute | Why not | Consequence |
|---|---|---|
| `lauren_mcp.request.id` | unique per request | one series per request → collector OOM; the metric becomes a slow trace |
| `mcp.session.id` | unique per session *and* ceases to exist (§4.6) | same, and deprecated twice over |
| `mcp.resource.uri` | user-controlled, id-bearing (`file:///tmp/…/a7f3`) | unbounded; a URI is an identifier, not a dimension |
| `error.message` | unbounded free text, may leak handler internals | series explosion plus an exfiltration channel into metric storage |
| `client.address` | client-specific | multiplies series by client count |

Enforced in code, not prose: `_metric_attributes()` in `_client/_otel_client.py` filters the dict
against `_METRIC_ATTR_ALLOWLIST` and drops unknown keys rather than passing them through.

**Cardinality budget.** `20` methods × `N` tools × `4` versions x `2` error types = `160·N` series;
with `N = 50`, 8,000 series for one histogram - bounded by the tool catalogue, not by traffic. Without
the allow-list, 10 rps yields 864,000 samples/hour into a metric whose entire value is a percentile.

**Server side.** No canonical server metric exists, so lauren-mcp emits none under an `mcp.` name;
operators derive server duration from the `SERVER` spans of §4.2 (§9.3 offers a namespaced fallback).

### 4.4 `traceparent` / `tracestate`: extraction and injection per transport

The `2026-07-28` revision standardises W3C trace context propagation via SEP-414 (E-183).
lauren-mcp has the harder half and is missing the other one.

**Exists** — extraction from one carrier only, the JSON-RPC `params._meta`: `_extract_context`
(`_otel.py:40-57`) reads `traceparent`/`tracestate` from the dict, builds a two-key carrier and
calls `opentelemetry.propagate.extract(carrier)`. It is invoked from `_otel.py:101` with
`meta = params_dict.get("_meta")` (`_otel.py:99-100`) and attached around the span at
`_otel.py:105-106`.

**Missing** — `grep -rn 'propagate.inject' src/` returns **nothing**, so client calls are never
children of the caller's span and server spans are always roots.

**Design** — one carrier abstraction, three sources, one injection point:

```python
# src/lauren_mcp/_server/_otel.py  (new)
_CARRIER: ContextVar[dict[str, str] | None] = ContextVar("lauren_mcp_otel_carrier", default=None)


@contextmanager
def use_carrier(carrier: Mapping[str, str] | None):
    token = _CARRIER.set(dict(carrier) if carrier else None)
    try:
        yield
    finally:
        _CARRIER.reset(token)
```

`_extract_context` becomes a two-source lookup: `_meta` first (unchanged behaviour), then the
contextvar as the transport channel.

| Transport | Carrier source | Hook |
|---|---|---|
| Streamable HTTP (server) | request headers | wrap `await self._dispatcher.dispatch(msg)` — `_streamable.py:277` |
| SSE (server) | headers on the `POST /messages` leg | wrap dispatch — `_sse.py:222` |
| WebSocket (server) | handshake headers, once per connection | wrap dispatch — `_ws.py:243` |
| stdio (server) | `params._meta` per message | `_otel.py:47` — already works |
| all remote clients | outgoing headers / outgoing `_meta` | `inject(carrier)` before each request |

Both HTTP transports already hold the `Request` (`_streamable.py:318` reads the protocol-version
header from it), so each hook is four lines: build the two-key carrier from `request.headers`, then
`with use_carrier(carrier):` around the existing `await self._dispatcher.dispatch(msg)`. The client
side is one `inject(headers)` before each send (`inject(params["_meta"])` for `_client/_stdio.py`).

**Why stdio needs a different carrier.** There is no header channel at all: stdio is a
length-prefixed JSON-RPC stream over a pipe (`_stdio.py:63` is the dispatch call), where SEP-414's
header propagation is not expressible. The JSON-RPC envelope is the only out-of-band place a pipe
has, so context rides in `params._meta` — exactly what `_extract_context` already reads, so the
server needs no change and only the *client* must start writing `_meta["traceparent"]`. Two
consequences to document: `_meta` context survives a subprocess boundary but is **per-request**
(stdio has no connection-level context), and it is visible to the server process — a trace id is
not a credential, but say so in `docs/guides/observability.md`.

### 4.5 The switch: one public knob for the whole migration

Two behaviours must coexist (§7), so they get one user-visible control beside the existing
`instrument_otel` parameter (`_module.py:74`):

The new kwarg sits after `instrument_otel` in `module()`: `otel_semconv: Literal["legacy", "dual",
"stable"] | None = None` (`_module.py:74`).

`None` resolves from the environment so containers can flip without a code change (mirroring
`_module.py:552-554`): `effective = otel_semconv or
os.environ.get("LAUREN_MCP_OTEL_SEMCONV", "dual")`. The mode threads into the wrapper, the only
place that touches attribute names, where `SemconvMode.STABLE` skips the three legacy keys and
`SemconvMode.LEGACY` skips `_canonical_attributes(...)`.

| Mode | Emits | Use |
|---|---|---|
| `legacy` | only today's three names, name `mcp.tools/call`, no metric, no injection | escape hatch for one release |
| `dual` *(default in 1.1.0)* | both name sets, canonical span name, metric emitted **once** | migration window |
| `stable` *(default from 1.2.0)* | canonical only | steady state |

Metrics are **never** dual-emitted: a duplicated metric is double-counted by every query, unlike a
duplicate attribute. It appears once, under its canonical name.

### 4.6 Convergence: `mcp-session-id` disappears for two independent reasons

The one attribute in the table that is not a rename, and the only one changed for two independent reasons:

1. **The convention deprecated it** (E-180) — flagged alongside `mcp-method-name`,
   `mcp-protocol-version`, `mcp-resource-uri`.
2. **The protocol removed the thing it describes** (E-20) — sessions are gone in `2026-07-28`;
   `Mcp-Session-Id` no longer exists in Streamable HTTP.

The tempting reading - emit `mcp.session.id` for legacy transports, drop it for modern ones - yields
an attribute whose presence is a function of the negotiated protocol version, a dimension nobody can
query reliably. The convergent answer is simpler: **lauren-mcp never emits a session attribute, in
any mode.**

Not a sacrifice, and not even a change: `grep -n 'session' src/lauren_mcp/_server/_otel.py` is
empty. The identifier exists only where the protocol puts it — `_SESSION_HEADER = "mcp-session-id"`
at `_server/_streamable.py:41`, `_server/_sse.py:45`, `_client/_streamable.py:24` and
`_client/_sse.py:28` — and it is echoed on the wire (`_streamable.py:332` builds the response
header), a transport concern owned by `prd-sessionless-http-transport.md`. Telemetry stays out of
it.

Two side effects: the deny-list in §4.3 is future-proof by construction (the highest-cardinality
attribute an MCP server could add is the one this PRD forbids emitting anywhere), and the
convergence is a citable decision rather than an omission - there will be no dashboard to fix and no
attribute to migrate.

---

## 5. Server-side Changes

```python
app_module = module(McpServer, instrument_otel=True, otel_semconv="dual")
```

`otel_semconv` lands after `instrument_otel` in `module()`'s signature (`_module.py:74`) and in the
same docstring block (`_module.py:122-127`); `LAUREN_MCP_OTEL_SEMCONV` is the env equivalent and the
kwarg wins. It is not an error with `instrument_otel=False` — the mode is simply unused — and
`instrument_otel=None` keeps auto-detect (`_module.py:552-554`), so nothing changes for existing users
except the names on their spans. The internal wiring is exactly the §6 table.

---

## 6. Exact Lines to Change

| File | Lines | Change |
|---|---|---|
| `_server/_otel.py` | 14, 33-37 | package version instead of protocol `LATEST`; `_get_meter()`; `schema_url=` |
| | 40-57 | `_extract_context` falls back to `_CARRIER` when `_meta` has no `traceparent` |
| | 60-61 | `instrument_dispatcher(dispatcher, *, semconv=…, span_kind=…)` |
| | 66, 70-74 | docstring span naming and attribute list → §4.1 / §4.2 |
| | 103, 109-116 | span name, `kind=`, dual-mode `attrs` (keep `_otel_instrumented`, 88-89) |
| | 128-130 | also record `error.type` for the metric |
| `server/_module.py` | 74, 122-127 | new `otel_semconv` parameter and its docs |
| | 552-554, 560, 564 | resolve from env (default `"dual"`); truthful `[otel]` message; pass `semconv=` |
| `_server/_streamable.py`, `_sse.py`, `_ws.py` | 277, 222, 243 | wrap dispatch in `use_carrier(carrier)` |
| `_server/_stdio.py` | 63 | no change — the `_meta` path already works |
| `_client/_streamable.py`, `_sse.py`, `_stdio.py` | per request | `inject(headers)` / `inject(params["_meta"])` |
| `pyproject.toml` | 32-46 | add `otel` extra; extend `all` (line 37) |
| `tests/unit/test_otel.py`, `docs/guides/observability.md` | — | extend tests (§8); new docs page |

## 7. Backward Compatibility

Telemetry is a contract with people's dashboards even though it is not in the type system; a
silent rename break is worse than the conformance problem this PRD solves.

**1.1.0 — dual emission, on by default.** Both spellings of all three attributes: old dashboards keep
working, new ones can target canonical names. The CHANGELOG leads with the §4.1 table plus *"the old
attribute names are deprecated and will be removed in 1.3.0"*. Honest cost: wider spans, and a query
counting `mcp.*` keys sees both.

**1.2.0 — `stable` becomes the default.** `otel_semconv` stays; unmigrated users set
`LAUREN_MCP_OTEL_SEMCONV=dual` (or `legacy`). Nothing is removed.

**1.3.0 — `legacy` and `dual` removed.** Only `"stable"` is accepted; anything else raises
`ValueError` pointing at §4.1, and
`grep -rn 'mcp\.method"\|mcp\.request_id"\|mcp\.tool_name"' src/` must return nothing — a CI gate
(§8), not a review instruction.

| If you | Action | When |
|---|---|---|
| have dashboards on `mcp.method` | rename to `mcp.method.name` | before 1.3.0 |
| filter spans by name `mcp.tools/call` | use `span.name LIKE 'tools/call %'` | on upgrade to 1.1.0 |
| built panels from `span.kind=INTERNAL` | re-target `SERVER` — they were counting the wrong thing | on upgrade to 1.1.0 |

Span names cannot be dual-emitted — one span has one name. That single breaking change lands in
1.1.0 rather than 1.3.0, so the release note must carry the `span.name LIKE 'tools/call %'`
replacement in the same paragraph.

---

## 8. Test Plan

`tests/unit/test_otel.py` is 71 lines of four tests and **not one asserts an attribute name** — they
check availability, the no-op path, idempotence and that `dispatch` was wrapped. That is why the wrong
names survived this long. Every key-set assertion below is exact, never `in`: a superset is a failure.

| File | Tests |
|---|---|
| `test_otel.py` (extend) | `…kind_is_server`; `…span_name_includes_tool_target` (`{"name": "get_weather"}` → `tools/call get_weather`, no params → `tools/call`); `…legacy_mode_emits_only_old_names`; `…dual_mode_emits_both_name_sets`; `…stable_mode_emits_only_canonical_names`; `…resource_read_sets_resource_uri`; `…no_session_attribute_ever`; `…scope_has_schema_url` |
| `test_otel_client.py` (new) | `…client_span_kind_is_client`; `…duration_histogram_recorded_once` (unit `s`, within wall time); `…metric_attributes_are_allowlisted` (a polluted dict never reaches the datapoint); `…client_injects_traceparent_header`; `…stdio_client_injects_meta` |
| `test_otel_propagation.py` (new) | `…server_extracts_from_http_headers` (same `trace_id`, matching `parent_span_id`); `…server_extracts_from_meta_fallback` (the `_otel.py:47` path still works); `…no_context_yields_root_span` |

Harness: `InMemorySpanExporter` + `InMemoryMetricReader` fixtures, patching `_get_tracer` /
`_get_meter` as the existing tests do (`tests/unit/test_otel.py:60-70`); `opentelemetry-sdk` goes in
**test** deps only. CI gates:

```
pytest tests/unit/test_otel.py tests/unit/test_otel_client.py tests/unit/test_otel_propagation.py -q
grep -rn 'mcp\.method"\|mcp\.request_id"\|mcp\.tool_name"' src/ && exit 1
```

---

## 9. Open Questions

1. **Exact canonical spellings.** The *hyphenated* names are verbatim from E-180; the dotted forms
   used here are implied by the move and by the registry file named in E-181, and must be
   transcribed from `docs/registry/attributes/mcp.md` before the first line of code — §4.1 is checked
   against that file by a reviewer with it open.
2. **`mcp.prompt.name`.** `prompts/get` has the same shape as `tools/call` and the registry defines
   it, but lauren-mcp emits no prompt target today. §4.1 includes it; strike it if this is a
   follow-up.
3. **A server-side duration metric.** Derive from `SERVER` spans (this PRD) or emit namespaced
   `lauren_mcp.server.operation.duration`? Revisit when the registry publishes a server report.
4. **`error.type` value space.** Numeric `McpErrorCode` value, its name, or the exception class?
   `_otel.py:129` has the codes; low-cardinality string is the OTel precedent.
5. **WS carrier lifetime.** Handshake headers are read once per connection but MCP over WS
   multiplexes requests. Leaning: support both, `_meta` first (§4.4 already orders it that way).
6. **How long is `legacy` free?** §7 says 1.3.0; if the deprecated names leave the old page before
   then, the flag maintains a spelling nobody documents.

---

## 10. References

- **E-180** — MCP attributes moved out of the core OTel semantic conventions; the old page has a
  section titled *"MCP Attributes (Moved)"* and flags `mcp-method-name`, `mcp-protocol-version`,
  `mcp-resource-uri`, `mcp-session-id` as **Deprecated**.
- **E-181** — canonical `mcp.*` definitions now live in the GenAI semconv repo,
  `docs/registry/attributes/mcp.md`.
- **E-182** — `mcp-client-span.md`, `mcp-server-span.md`,
  `mcp-client-operation-duration-metric.md` in `semantic-conventions-genai/reference/reports`.
- **E-183** — `2026-07-28` standardises `traceparent`/`tracestate` propagation (SEP-414).
- **E-20** — sessions removed; `Mcp-Session-Id` absent from the `2026-07-28` schema.
- **E-245** — `opentelemetry` in 3 files; the integration lives in `_server/_otel.py`.
- Companions: `prd-dual-era-protocol-core.md`, `prd-sessionless-http-transport.md` (§4.6).

---

## Acceptance Checklist

**Attributes and spans**

- [ ] `grep -n 'set_attribute' src/lauren_mcp/_server/_otel.py` shows only canonical names or
      `lauren_mcp.request.id`; `grep -c '"mcp\.method"\|"mcp\.request_id"\|"mcp\.tool_name"'` = `0`.
- [ ] `grep -c 'mcp\.session\.id' …/_otel.py` = `0`; `mcp\.protocol\.version` and
      `mcp\.resource\.uri` each ≥1.
- [ ] `grep -c 'SpanKind.SERVER' …/_otel.py` ≥1; `grep -c 'f"mcp\.{request\.method}"'` = 0.
- [ ] `grep -c 'schema_url' …/_otel.py` ≥1; `grep -c 'LATEST as __version__'` = 0.
- [ ] `pytest tests/unit/test_otel.py -q` passes (kind, span name, three modes).

**Metric**

- [ ] `grep -rc 'get_meter' src/` ≥1; `grep -rc 'mcp\.client\.operation\.duration' src/` ≥1.
- [ ] `grep -rn 'unit="s"' src/lauren_mcp/_client/` returns ≥1 line.
- [ ] `pytest tests/unit/test_otel_client.py -q` passes, including the allow-list test.

**Propagation**

- [ ] `grep -rn 'propagate.inject' src/` returns ≥1 line.
- [ ] `grep -rln 'use_carrier' src/lauren_mcp/_server/` lists `_streamable.py`, `_sse.py`, `_ws.py`.
- [ ] `pytest tests/unit/test_otel_propagation.py -q` passes, `_meta` fallback included.
- [ ] Manual `curl -H 'traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01'`
      against a local Streamable HTTP server yields a span with that `trace_id`.

**Compatibility, packaging, docs**

- [ ] `grep -c 'LAUREN_MCP_OTEL_SEMCONV' src/lauren_mcp/server/_module.py` ≥1;
      `LAUREN_MCP_OTEL_SEMCONV=legacy pytest tests/unit/test_otel.py -q -k legacy` passes;
      `pytest tests/unit/test_otel.py -q -k dual` passes.
- [ ] `git grep -c 'otel_semconv' docs/` ≥1; `git grep -c '1\.3\.0' CHANGELOG.md` ≥1.
- [ ] `pip install -e '.[otel]'` succeeds, so the message at `_module.py:560` is truthful.
- [ ] `docs/guides/observability.md` covers the attribute table, env var, metric name/unit and the
      stdio `_meta` caveat.
