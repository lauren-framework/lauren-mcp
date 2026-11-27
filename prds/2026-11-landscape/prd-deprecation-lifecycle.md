# PRD — Feature deprecation lifecycle registry

**Status:** Draft  
**Date:** 2026-11-26  
**Scope:** new `src/lauren_mcp/lifecycle.py`, `_server/_context.py`, `_server/_sse.py`, `_server/_streamable.py`, `server/_module.py`, `server/_handlers.py`, `_client/_features.py`, `_client/_factory.py`, `cli/_commands.py`, `scripts/generate_deprecation_table.py` (new), `docs/reference/deprecation-lifecycle.md` (generated)  
**Priority:** P2 — no host stops talking to us and no MUST is violated; the cost is that users of `logging`, `roots`, `sampling`, `elicitation` and HTTP+SSE have no clock on their features and learn the `2026-07-28` deprecation from a blog post instead of from us (E-30, E-42).  
**Issue:** [#68](https://github.com/lauren-framework/lauren-mcp/issues/68)

---

## 1. Problem Statement

`lauren-mcp` 1.0.0 implements the whole legacy era (`2024-11-05` … `2025-11-25`). Five of the six
features that `2026-07-28` deprecates are implemented here, on the hot path:

* `logging/setLevel` — 7 files, 11 occurrences (E-242): `server/_module.py:427` (registration),
  `_server/_context.py:60` (state cell), `_server/_context.py:383` (emission).
* `roots/list` — 3 files (E-243): `_client/_stdio.py:372`, `_client/_base_remote.py:201`.
* Sampling — `_server/_context.py:437`; elicitation — `_server/_context.py:547`.
* HTTP+SSE transport — `_server/_sse.py:48` (`mcp_http_sse_controller`), GET stream `:109`, RPC `:140`.
* `Last-Event-ID` resumability — 2 files (E-244): `_server/_streamable.py:476`, `_server/_event_store.py:7`.

The sixth deprecated item, Dynamic Client Registration, is **not** implemented — `_oauth.py` holds only
`TokenStorage` (`:22`), `InMemoryTokenStorage` (`:34`) and `ClientCredentialsProvider` (`:59`), with no
registration endpoint anywhere under `src/`. It is recorded as absent in §4.6, not pretended to be present.

The bug is not that these features exist. It is that **nothing knows they have a clock on them**:

`grep -rniE "deprecat"` returns **0** matches in `src/`, `docs/` and `README.md` alike: no lifecycle type,
no deprecation field on `ServerCapabilities` (`src/lauren_mcp/_types.py:139`), no warning, no doc row.

### 1.1 Failure scenario: the user who finds out last

A team ships a `lauren-mcp` server that logs through `ctx.log(...)`
(`src/lauren_mcp/_server/_context.py:383`) and asks the host a question mid-tool-call through
`ctx.elicit(...)` (`:547`) — the documented, recommended way to do both in 1.0.0, since the docs never
mention deprecation either.

Months later their host upgrades to a `2026-07-28` peer, which drops `logging/setLevel` (E-24) and
answers input-needing tool calls with an `input_required` result instead of servicing
`elicitation/create` (E-26). What the user sees:

1. `logging/setLevel` is a method the peer never advertised — an error or a no-op, and `ctx.log` output
   goes nowhere because no level was set (`src/lauren_mcp/_server/_context.py:391` returns early below the
   configured minimum).
2. `ctx.elicit` has no peer to answer it: the request shape itself is gone for modern peers.
3. Neither failure names a replacement (E-22, E-26).

Invert it: told once at import time — *"`logging/setLevel` is deprecated as of `2026-07-28`; replacement
is per-request `_meta.logLevel`; earliest removal 2027-07-28"* — the team makes a ten-line change on its
own schedule. That sentence is the deliverable.

### 1.2 Secondary problem: a hand-written deprecation table will rot

Pasting a "Deprecated" table into `docs/reference/` fails on its own terms: this repo already generates
reference pages from source (`scripts/generate_api_docs.py:8`, `:65`) and gates prose drift
(`nox -s llms_check`), so a hand-maintained table would be the one doc artifact with no check behind it.
The registry must be **data in the library**, the table **rendered from it**, and a test must fail when
they disagree.

---

## 2. Goals

1. Add `src/lauren_mcp/lifecycle.py` with `LifecycleStatus` (`ACTIVE`/`DEPRECATED`/`REMOVED`),
   `FeatureRecord` (`deprecated_in`, `removed_in`, `replacement`, `see`) and a `FEATURES` mapping covering
   every MCP feature this repo implements, sourced from the spec's deprecation registry (E-42).
2. Emit exactly **one warning per process per deprecated feature**, at registration or first use,
   suppressible by environment variable or standard `warnings` filters.
3. Generate `docs/reference/deprecation-lifecycle.md` from `FEATURES` via a committed script with a
   `--check` mode, plus a test asserting the checked-in page equals the rendered page.
4. Record a keep / keep+alias / remove decision per deprecated feature, with the window arithmetic
   (`2026-07-28` + 12 months = `2027-07-28`) written out.
5. Cross-reference each deprecated feature to its replacement (sampling/elicitation → MRTR, E-26; logging
   → `_meta.logLevel`, E-22; roots → cwd hints; DCR → CIMD, E-172; HTTP+SSE → Streamable HTTP, E-20/E-28),
   and expose it as `lauren_mcp.lifecycle` plus `lmcp inspect --features`.

**Removal is not a goal.** Each of these features is spec-valid, shipping and inside its deprecation
window (E-41); removing one would break existing users — see §3.

## 3. Non-Goals

* **No removals.** Not a method, not a transport, not a capability field: `removed_in` stays `None` for
  all six rows (§4.6). Deleting `ctx.sample()` or `mcp_http_sse_controller()` today would break users of a
  feature the spec permits for at least twelve months (E-41).
* **No wire behaviour change.** No capability stops being advertised, no method stops being answered, no
  `Last-Event-ID` replay (`src/lauren_mcp/_server/_streamable.py:486`).
* **No new runtime dependency** — `enum`, `dataclasses`, `warnings`, `threading` only, so the
  two-dependency posture (`lauren`, `anyio`; inventory §1, §14) survives.
* **No automatic migration of user code,** and no invented dates: `removed_in` is filled only when a
  release that removes the feature exists (E-42).
* **Not the replacement implementations** (`_meta.logLevel`, MRTR, Streamable HTTP, CIMD): those land in
  `prd-server-discover-request-meta.md`, `prd-mrtr-input-required.md`,
  `prd-sessionless-http-transport.md`, `prd-oauth-resource-indicators-cimd.md`. This PRD owns only the
  metadata that points at them.

---

## lauren-mcp Advantages

**Implementing the full deprecated set is an asset, not a liability.** Because 1.0.0 already ships
`logging/setLevel` (7 files, E-242), `roots/list` (3 files, E-243), sampling, elicitation, HTTP+SSE and
`Last-Event-ID` replay (2 files, E-244), the `2026-07-28` work is *additive*: the replacement is a second
path beside a working one, never a rewrite of the only path. A server with only the modern surface must
build `_meta.logLevel` and MRTR from nothing while its users have no legacy answer; here both answers
exist. The inventory also records three transports from one class (§14.2) and native WebSocket, which
neither FastMCP nor the official Python SDK ships (§14.1) — a registry covering only the modern surface
would say nothing about the transports users actually run.

**The warning machinery and the doc pipeline already exist.** `src/lauren_mcp/server/_decorators.py:146`
warns about a discouraged tool name with `stacklevel=4` (`:150`) — the lifecycle warning is the same
shape — and `scripts/generate_api_docs.py` (`:8`, `:65`) plus `nox -s llms_check` already generate and
gate docs, so one renderer with `--check` is a script and a test, not new infrastructure. Nothing new for
users to learn either: `FeatureRecord` is a frozen dataclass, and the registry is data all the way down.

---

## 4. Design

### 4.1 The types: `src/lauren_mcp/lifecycle.py` (new)

```python
"""Lifecycle metadata for every MCP feature lauren-mcp implements (E-42)."""

DEPRECATION_REVISION = "2026-07-28"  # E-30: revision that deprecates the set
MIN_WINDOW_MONTHS = 12               # E-41 / SEP-2596: "at least 12 months"


class LifecycleStatus(enum.Enum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    REMOVED = "removed"


@dataclass(frozen=True, slots=True)
class FeatureRecord:
    """One MCP feature, its lifecycle state, and what replaces it."""

    key: str
    title: str
    status: LifecycleStatus
    spec_revision: str
    deprecated_in: str | None = None
    removed_in: str | None = None
    replacement: str | None = None
    see: tuple[str, ...] = ()      # E-… ids and spec paths
    code: tuple[str, ...] = ()     # grep-able path:line anchors in this repo

    @property
    def is_deprecated(self) -> bool:
        return self.status is LifecycleStatus.DEPRECATED
```

### 4.2 The registry

Rows go through two helpers, so `_dep` cannot omit `deprecated_in` and `_act` cannot set it:

```python
def _dep(key, title, replacement, see, code) -> FeatureRecord:
    return FeatureRecord(
        key=key, title=title, status=LifecycleStatus.DEPRECATED,
        spec_revision=DEPRECATION_REVISION, deprecated_in=DEPRECATION_REVISION,
        removed_in=None, replacement=replacement, see=see, code=code,
    )


def _act(key, title, code, replacement=None, see=()) -> FeatureRecord:
    return FeatureRecord(
        key=key, title=title, status=LifecycleStatus.ACTIVE,
        spec_revision=DEPRECATION_REVISION, replacement=replacement, see=see, code=code,
    )


FEATURES: dict[str, FeatureRecord] = {r.key: r for r in (
    _dep("logging.setLevel", "logging/setLevel + notifications/message",
         "per-request _meta.logLevel", ("E-24", "E-22"),
         ("src/lauren_mcp/server/_module.py:427",
          "src/lauren_mcp/_server/_context.py:383")),
    _dep("roots", "roots/list + notifications/roots/list_changed",
         "client-provided cwd hints", ("E-24", "E-26"),
         ("src/lauren_mcp/_client/_stdio.py:372",
          "src/lauren_mcp/_client/_base_remote.py:201")),
    _dep("sampling", "sampling/createMessage",
         "MRTR (input_required + requestState)", ("E-26",),
         ("src/lauren_mcp/_server/_context.py:437",)),
    _dep("elicitation", "elicitation/create",
         "MRTR (input_required + requestState)", ("E-26",),
         ("src/lauren_mcp/_server/_context.py:547",)),
    _dep("transport.http_sse", "HTTP+SSE transport (GET stream + POST endpoint)",
         "Streamable HTTP", ("E-20", "E-28"), ("src/lauren_mcp/_server/_sse.py:48",)),
    _dep("transport.sse_resumption", "Last-Event-ID resumability",
         "none — resumability is not in Streamable HTTP", ("E-28", "E-23"),
         ("src/lauren_mcp/_server/_streamable.py:476",)),
    # --- active, so the table is the whole picture ---
    _act("tools", "tools/list + tools/call", ("src/lauren_mcp/server/_module.py:457",)),
    _act("resources", "resources/*", ("src/lauren_mcp/server/_module.py:476",),
         "subscriptions/listen for the notification half (E-23)", ("E-23",)),
    _act("prompts", "prompts/*", ("src/lauren_mcp/server/_module.py:522",)),
    _act("completion", "completion/complete", ("src/lauren_mcp/_types.py:146",)),
    _act("transport.streamable_http", "Streamable HTTP transport",
         ("src/lauren_mcp/_server/_streamable.py:476",),
         "sessions removed — see prd-sessionless-http-transport.md", ("E-20",)),
)}


def deprecated_features() -> tuple[FeatureRecord, ...]:
    return tuple(f for f in FEATURES.values() if f.is_deprecated)
```

### 4.3 Runtime warning strategy: once per process, per feature, suppressible

```python
_ENV = "LAUREN_MCP_LIFECYCLE_WARNINGS"   # "0"/"off"/"false"/"no" disables warnings
_WARNED: set[str] = set()
_LOCK = threading.Lock()


class McpFeatureLifecycleWarning(UserWarning):
    """A deprecated MCP feature was registered or used.

    A ``UserWarning`` subclass: ``DeprecationWarning`` is hidden outside ``__main__``.
    """


def warn_feature(key: str, *, stacklevel: int = 3) -> bool:
    """Warn once per process per feature. Returns True if a warning was emitted."""
    record = FEATURES.get(key)
    if record is None or not record.is_deprecated:
        return False
    if os.environ.get(_ENV, "").strip().lower() in {"0", "off", "false", "no"}:
        return False
    with _LOCK:
        if key in _WARNED:
            return False
        _WARNED.add(key)
    warnings.warn(
        f"{record.key} ({record.title}) is deprecated as of MCP {record.deprecated_in}; "
        f"replacement: {record.replacement}; lauren-mcp keeps it until at least "
        f"2027-07-28 (12-month window, E-41). See {', '.join(record.see)}.",
        McpFeatureLifecycleWarning, stacklevel=stacklevel,
    )
    return True
```

Rules not to be relaxed silently:

* **Once per process, not per call.** `_WARNED` is module-global: a server logging ten thousand times
  through `_context.py:383` must not emit ten thousand warnings.
* **`UserWarning`, not `DeprecationWarning`** — the latter is invisible to the audience this exists for.
* **Standard suppression works**, because we go through `warnings.warn`: `warnings.simplefilter("ignore",
  McpFeatureLifecycleWarning)` is honoured, and `LAUREN_MCP_LIFECYCLE_WARNINGS=0` is the coarse switch.
* **`stacklevel` per call site**: `3` in `ctx.log`/`ctx.sample`/`ctx.elicit`, `4` in a decorator, per
  `src/lauren_mcp/server/_decorators.py:150`.

### 4.4 Emission points: registration *or* first use

| Point | Anchor | Emits |
|---|---|---|
| server module build | `src/lauren_mcp/server/_module.py:430` | `logging.setLevel`, `sampling`, `elicitation` |
| SSE transport factory | `src/lauren_mcp/_server/_sse.py:48` | `transport.http_sse` |
| streamable replay branch | `src/lauren_mcp/_server/_streamable.py:486` | `transport.sse_resumption` (only with an `event_store` *and* a `last-event-id` header) |
| `McpToolContext.log` / `.sample` / `.elicit` | `src/lauren_mcp/_server/_context.py:383`, `:437`, `:547` | `logging.setLevel`, `sampling`, `elicitation` |
| client: `set_logging_level` / `roots/list` handler | `_client/_factory.py:57`, `_client/_stdio.py:372` | `logging.setLevel`, `roots` |

Both, not either: registration catches the server author, first use catches whoever inherited the code, and
`warn_feature` de-duplicates. In `ctx.log` the diff is two lines, before the guards — a dropped log entry is
still a use, and the user whose logs vanish at `:391` needs it most:

```python
    async def log(self, level: LogLevel, message: str, data: dict[str, Any] | None = None) -> None:
        warn_feature("logging.setLevel", stacklevel=3)     # new
        if self._send_notification is None:                # :389
            return
        if self._log_level_state is not None and not self._log_level_state.allows(level):  # :391
            return
```

### 4.5 Doc generation hook: the table cannot drift

`scripts/generate_deprecation_table.py` (new), modelled on `scripts/generate_api_docs.py`, renders
`docs/reference/deprecation-lifecycle.md` from `FEATURES` between `<!-- BEGIN GENERATED: lifecycle -->` /
`<!-- END GENERATED: lifecycle -->` markers — one row per record
(`key | status | deprecated_in | removed_in | replacement | evidence`) under a preamble naming
`DEPRECATION_REVISION`, `MIN_WINDOW_MONTHS` and the `2027-07-28` earliest-removal date:

```python
def render() -> str:
    rows = [f"| `{r.key}` | {r.status.value} | {r.deprecated_in or '—'} "
            f"| {r.removed_in or 'not scheduled'} | {r.replacement or '—'} "
            f"| {', '.join(r.see) or '—'} |" for r in sorted(FEATURES.values(), key=lambda r: r.key)]
    return "\n".join([BEGIN, preamble(), HEADER, *rows, END]) + "\n"


def main(argv: list[str]) -> int:
    body = render()
    if "--check" in argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        return 0 if body in current else 1
    OUT.write_text("# Feature lifecycle\n\nGenerated.\n\n" + body, encoding="utf-8")
    return 0
```

`nox -s docs` runs the generator before `mkdocs build`, and the page joins the Reference nav.
`test_checked_in_table_matches_registry` compares `render()` against the committed block, so a stale table
is a red test rather than a review comment — the contract `nox -s llms_check` already enforces for prose.
Only the marked region is script-owned.

### 4.6 Decision table: keep, keep+alias, or remove

Deprecated `2026-07-28` (E-30) with a 12-month minimum window (E-41, SEP-2577/SEP-2596): the **earliest
compliant removal is `2027-07-28`**, and today (`2026-11-26`) about eight months remain. At a
minor-per-quarter cadence the first release that could carry a removal is `2.0.0`, not before
`2027-11-01` — a policy floor, not a scheduled date, so it never enters `removed_in`.

| Feature | Anchor | Decision | Why | Earliest removal | `removed_in` |
|---|---|---|---|---|---|
| `logging/setLevel` + `notifications/message` | `_module.py:427` | **keep** | Legacy peers need it, modern ones must not receive it; removing it before `_meta.logLevel` ships strands both. | 2027-07-28 | `None` |
| `roots/list` | `_stdio.py:372` | **keep** | Server-side roots are gone (E-24), but our *client* still answers a legacy server that asks. | 2027-07-28 | `None` |
| `sampling/createMessage` | `_context.py:437` | **keep** | MRTR (E-26) is a different control flow, not a rename; both must exist while it lands. | 2027-07-28 | `None` |
| `elicitation/create` | `_context.py:547` | **keep** | As sampling; `ctx.elicit()` is the entry point MRTR will eventually express. | 2027-07-28 | `None` |
| HTTP+SSE transport | `_sse.py:48` | **keep** | `transport="all"` mounts WS + SSE + Streamable from one class (inventory §14.2); dropping SSE breaks those users. | 2027-07-28 | `None` |
| `Last-Event-ID` resumability | `_streamable.py:476` | **keep** (no alias) | E-28 removes the *specification* of replay, not the option of honouring the header. Nothing to alias to. | 2027-07-28 | `None` |
| Dynamic Client Registration | *absent* — `_oauth.py:59` is `ClientCredentialsProvider` | **n/a** | Nothing to keep or remove; recorded so nobody adds DCR — the path is CIMD (E-172). | n/a | n/a |

The arithmetic, spelled out so it can be checked rather than trusted:

```
deprecated_at             = 2026-07-28           # E-30, revision that deprecates the set
window_months             = 12                   # E-41 / SEP-2596 "at least 12 months"
earliest_removal          = 2026-07-28 + 12m   = 2027-07-28
policy_floor_for_removal  = 2027-11-01           # earliest_removal + one full minor cycle
forbidden                 = any removal before 2027-07-28    # E-41, this PRD §3
```

### 4.7 Replacement cross-references

| Deprecated here | Replacement | Evidence | Lands in |
|---|---|---|---|
| `sampling/createMessage`, `elicitation/create`, server-side `roots/list` | **MRTR** — `resultType: "input_required"` + `requestState`, retried by the client | E-26 | `prd-mrtr-input-required.md` |
| `logging/setLevel` | **per-request `_meta.logLevel`** — level per request, not per connection | E-22, E-24 | `prd-server-discover-request-meta.md` |
| `roots/list` (server side) | **client-provided cwd hints** in `_meta`; no round-trip | E-24, E-26 | `prd-server-discover-request-meta.md` |
| HTTP+SSE transport | **Streamable HTTP** — one endpoint, POST + SSE, no sessions | E-20, E-28 | `prd-sessionless-http-transport.md` |
| `Last-Event-ID` replay | **nothing**; `subscriptions/listen` for notifications | E-28, E-23 | `prd-subscriptions-listen.md` |
| DCR (absent here) | **CIMD** — Client ID Metadata Documents | E-172 | `prd-oauth-resource-indicators-cimd.md` |

### 4.8 Public surface

```python
from lauren_mcp.lifecycle import FEATURES, FeatureRecord, LifecycleStatus, deprecated_features
```

These names also join `src/lauren_mcp/__init__.py`'s `__all__` (`:83`); the inspect command
(`src/lauren_mcp/cli/_commands.py:71`, `def inspect_cmd(`) gains `--features`, printing
`key / status / deprecated_in / removed_in / replacement` for the eleven §4.2 records.

---

## 5. Server-side Changes (and client-side)

1. `src/lauren_mcp/_server/_context.py` — `warn_feature(...)` in `log` (`:383`), `sample` (`:437`) and
   `elicit` (`:547`), ahead of the guards at `:389`/`:391`; `src/lauren_mcp/server/_module.py` — one
   emission after the context factory is built at `:430`, so `lmcp run` says its piece before the first call.
3. `src/lauren_mcp/_server/_sse.py` — `warn_feature("transport.http_sse", stacklevel=3)` in
   `mcp_http_sse_controller` (`:48`); `src/lauren_mcp/_server/_streamable.py` — emit
   `transport.sse_resumption` only inside the replay branch (`:486`).
4. Client: warn in `set_logging_level` (`_client/_factory.py:57`) and the `roots/list` handlers
   (`_client/_stdio.py:372`, `_client/_base_remote.py:201`).
5. `src/lauren_mcp/server/_handlers.py` — no behaviour change; `make_context_factory` (`:513`,
   `log_level_state` at `:517`) is where the deprecated log-state cell enters the context, so that warning
   belongs on the caller side in `_module.py`.

No capability leaves `ServerCapabilities` (`src/lauren_mcp/_types.py:139`, `logging` at `:145`) or
`ClientCapabilities` (`:129`, `roots`/`sampling`/`elicitation` at `:132`–`:134`).

---

## 6. Exact Lines to Change

### 6.1 `src/lauren_mcp/_server/_context.py`

`:383` `async def log(...)` → first statement `warn_feature("logging.setLevel", stacklevel=3)`; the guards
at `:389` (`if self._send_notification is None:`) and `:391` (`if self._log_level_state is not None …`)
stay unchanged and stay *after* it. `:437` `async def sample(` → `warn_feature("sampling", stacklevel=3)`;
`:547` `async def elicit(` → `warn_feature("elicitation", stacklevel=3)`. `:60` `class LogLevelState:` is
untouched — the deprecated *method* is annotated, not the state cell.

### 6.2 `src/lauren_mcp/server/_module.py`

`:427` `dispatcher.register("logging/setLevel", _set_level)` untouched (the handler keeps working);
`:430` `context_factory = make_context_factory(` → one `warn_feature("logging.setLevel", stacklevel=2)`
after it for the module build.

### 6.3 `src/lauren_mcp/server/_handlers.py`

`:513` `def make_context_factory(` / `:517` `log_level_state` — no change. Listed because this wiring makes
`logging/setLevel` reachable from every context; if a refactor moves the registration, so must the warning.

### 6.4 `src/lauren_mcp/_server/_sse.py`

`:48` `def mcp_http_sse_controller(` → first statement `warn_feature("transport.http_sse", stacklevel=3)`.
`:109` `async def open_stream(...)` is the GET channel `subscriptions/listen` replaces (E-23) — no warning
there, the factory already warned.

### 6.5 `src/lauren_mcp/_server/_streamable.py`

`:476` `last_event_id: str | None = request.headers.get("last-event-id")` — read stays. `:486`
`if event_store is not None and last_event_id is not None:` → warn `transport.sse_resumption` inside this
branch only.

### 6.6 `src/lauren_mcp/_client/` (`_features.py`, `_factory.py`)

`:39`–`:42` `_VALID_LOG_LEVELS` for `logging/setLevel` — unchanged; the client validates as today. `:57` the
`set_logging_level` docstring block → add the `warn_feature("logging.setLevel")` call to the method body
plus a `.. deprecated::` note pointing at `_meta.logLevel`.

### 6.8 `src/lauren_mcp/_types.py`

`:139` `class ServerCapabilities:` / `:145` `logging: dict[str, Any] | None = None` — unchanged; gain
`# deprecated by 2026-07-28 (E-24); see lauren_mcp.lifecycle`. Same comment on `:129`–`:134`
`ClientCapabilities` (`roots`/`sampling`/`elicitation`).

### 6.9 New files

`src/lauren_mcp/lifecycle.py`, `scripts/generate_deprecation_table.py`,
`docs/reference/deprecation-lifecycle.md` (generated), `tests/unit/test_lifecycle_registry.py`,
`tests/integration/test_lifecycle_warnings.py`.

---

## 7. Backward Compatibility

Nothing breaks, by construction:

* **No API removed or renamed:** `ctx.log`, `ctx.sample`, `ctx.elicit`, `mcp_http_sse_controller`,
  `set_logging_level` all keep their signatures.
* **No wire change:** capabilities are advertised as today (`src/lauren_mcp/_types.py:145`),
  `logging/setLevel` is still answered (`src/lauren_mcp/server/_module.py:427`), `Last-Event-ID` is still
  replayed (`src/lauren_mcp/_server/_streamable.py:486`).
* **Warnings are the only new output**, once per feature per process, opt-out from day one
  (`LAUREN_MCP_LIFECYCLE_WARNINGS=0`, or filter `McpFeatureLifecycleWarning`). No dependency change, and
  `removed_in` is `None` everywhere, so no version-gated code path exists yet.

Migration notes for users: **none required**, and that is the point — the only change is that the library
now says which features have a clock on them (E-30, E-41).

---

## 8. Test Plan

### 8.1 Unit tests — `tests/unit/test_lifecycle_registry.py`

| Test | Asserts |
|---|---|
| `test_no_feature_has_removed_in_today` | `removed_in is None` and `replacement` is set for every `DEPRECATED` record (§3 non-goal; fails the day a removal sneaks in) |
| `test_deprecated_in_matches_spec_registry` | the six keys carry `deprecated_in == "2026-07-28"`, and `deprecated_in + MIN_WINDOW_MONTHS == "2027-07-28"` (E-30, E-41, E-42) |
| `test_code_anchors_exist` | each `path:line` exists and is within the file — catches a refactor that moves `ctx.log` and leaves the registry dangling |
| `test_warn_once_per_process` | two `warn_feature("sampling")` calls → exactly one `pytest.warns` hit |
| `test_warning_suppressed_by_env` / `_by_filter` | `LAUREN_MCP_LIFECYCLE_WARNINGS=0` and `simplefilter("ignore", …)` both yield no warning |
| `test_checked_in_table_matches_registry` | `render()` equals the committed block in `docs/reference/deprecation-lifecycle.md` |
| `test_cli_features_output` | `lmcp inspect --features` has one row per `DEPRECATED` key |

### 8.2 Integration tests — `tests/integration/test_lifecycle_warnings.py`

| Test | Asserts |
|---|---|
| `test_server_build_warns_once_for_logging` | `@mcp_server` with one `@mcp_tool`, `ctx.log` twice → one warning, not duplicated at registration |
| `test_streamable_replay_warns_only_with_header` | `event_store` + `last-event-id` header → warns; no header → silent |
| `test_legacy_peer_still_works` | a `2025-11-25` client calling `logging/setLevel` gets `{}` and the warning |
| `test_elicit_still_round_trips` | `ctx.elicit` on the in-process client still returns an `ElicitResult` |

Run with `nox -s tests_unit`, `nox -s tests_integration`, `nox -s coverage`.

---

## 9. Acceptance Criteria

- [ ] public surface present — `python -c "from lauren_mcp.lifecycle import FEATURES, FeatureRecord, LifecycleStatus, deprecated_features, warn_feature; print(len(FEATURES))"`
- [ ] six deprecated keys, none removed, all naming a replacement — `python -c "from lauren_mcp.lifecycle import deprecated_features as d; assert all(f.removed_in is None and f.replacement for f in d()); print(sorted(f.key for f in d()))"`
- [ ] no behaviour removed — `git diff --stat HEAD -- src/lauren_mcp/_server/` shows additive hunks only, and
      `grep -rn "NotImplementedError" src/lauren_mcp/_server/_context.py` is empty
- [ ] warning fires once per process per feature — `pytest tests/unit/test_lifecycle_registry.py -k warn_once`
- [ ] warning suppressible — `LAUREN_MCP_LIFECYCLE_WARNINGS=0 pytest tests/unit/test_lifecycle_registry.py -k suppressed`
- [ ] `ctx.log` still emits `notifications/message` — `pytest tests/integration/test_lifecycle_warnings.py -k legacy_peer`
- [ ] docs table generated, not hand-written — `python scripts/generate_deprecation_table.py && python scripts/generate_deprecation_table.py --check`
- [ ] registry/doc drift fails the build — `pytest tests/unit/test_lifecycle_registry.py -k checked_in_table`
- [ ] CLI surfaces the table — `lmcp inspect --features | grep -c deprecated` ≥ 6
- [ ] no new runtime dependency — `grep -A4 "^dependencies" pyproject.toml` lists only `lauren` and `anyio`
- [ ] gates green — `nox -s tests`, `nox -s lint`, `nox -s typecheck`, `nox -s docs`

---

## 10. Open Questions

1. **Does `ctx.log` warn, or only the `setLevel` registration?** First use is the loudest signal but noise
   for a legacy-only server that never meets a `2026-07-28` peer. Current design: warn once, because the
   deprecation is spec-level, not peer-level.
2. **One global suppression variable or a per-feature list?** `LAUREN_MCP_LIFECYCLE_WARNINGS=0` covers CI;
   a `=off:logging.setLevel` form is a five-line change if users ask.
3. **Is `transport.sse_resumption` its own key** or a sub-note of `transport.http_sse`? Separate here:
   different replacements and anchors (`_sse.py:48` vs `_streamable.py:476`). Deferred: whether `removed_in`
   should later raise or warn-and-no-op, and whether the registry should ride on the wire.

---

## 11. References

**Evidence (`prds/2026-11-landscape/EVIDENCE.md`)** — E-30 (deprecated set), E-41 (≥12-month window,
SEP-2577/SEP-2596) and E-42 (live registry outranks blog posts) give the registry its content and cadence;
E-20/E-24/E-26/E-28 (removals, MRTR), E-22 (`_meta.logLevel`), E-23 (`subscriptions/listen`) and E-172
(CIMD) give every replacement; E-242/E-243/E-244 (7 / 3 / 2 files) are the counts re-verified in §1.

**Specification and repo**

* `https://modelcontextprotocol.io/specification/2026-07-28/deprecations` — the registry (E-42); re-read at
  each release, since it outranks any statement here. SEP-2577 (legacy feature-set deprecation), SEP-2596
  (lifecycle policy, 12-month window).
* `_research/lauren-mcp-inventory.md` §1, §3, §7, §14 — cited in `## lauren-mcp Advantages`;
  `prd-mrtr-input-required.md`, `prd-server-discover-request-meta.md`,
  `prd-sessionless-http-transport.md`, `prd-subscriptions-listen.md`,
  `prd-oauth-resource-indicators-cimd.md`, `prd-dual-era-protocol-core.md` — the replacement work.
* `src/lauren_mcp/server/_decorators.py:146`–`:150` — the `warnings.warn(..., stacklevel=4)` precedent;
  `scripts/generate_api_docs.py:8`, `:65` — the doc-generation pattern the new renderer copies.
