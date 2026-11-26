# PRD — A conformance harness in CI, so protocol claims are measured rather than argued

**Status:** Draft
**Date:** 2026-11-26
**Scope:** `tests/conformance/` (new), `src/lauren_mcp/conformance/` (new), `src/lauren_mcp/cli/{__init__,_commands}.py`, `noxfile.py`, `.github/workflows/tests.yml`, `pyproject.toml`, `docs/reference/cli.md`
**Priority:** P2
**Issue:** _pending_

---

## 1. Problem Statement

`lauren-mcp` 1.0.0 has no conformance measurement of any kind. Every statement this
repo makes about its own protocol behaviour is an assertion with no number behind it
and no command a reviewer can run.

That is no longer acceptable: the ecosystem publishes a number for everyone else. The official suite exists and is exactly what the official Tier 1/2/3
ratings are computed from: `npx @modelcontextprotocol/conformance client --command …
--scenario …`, version **0.1.16**, repo pushed 2026-11-23 (E-75). The tier rules are
verbatim — **pass rate 100 % / 80 % / none for Tiers 1 / 2 / 3** (E-76) — and the
tiering system is SEP-1730, first shipped in `2025-11-25` (E-55).

Nine of the ten surveyed official SDKs ship the modern era (E-80 … E-89).
`lauren-mcp` 1.0.0 is the tenth row and it reads **`no` — 0, 0** (E-90). We are the
only SDK in the set that cannot say whether it passes a single official scenario,
because we have never run one.

### 1.1 Failure scenario: a host cancels a tool call and we never see it

A host starts a long `tools/call`, the user hits stop, the host sends the spec's
cancellation notification. We do not handle that method name anywhere; we listen for
the LSP spelling instead:

```python
# src/lauren_mcp/_server/_stdio.py  line 76
    if message.method != "$/cancelRequest":
# src/lauren_mcp/_server/_streamable.py  line 212
                elif msg.method == "$/cancelRequest":
# src/lauren_mcp/_server/_dispatcher.py  lines 105-106
        cancelled by a concurrent ``$/cancelRequest`` notification via
```

`grep -rn 'notifications/cancelled' src/` returns nothing. The call runs to
completion, the host has already torn down its UI, and the user sees a spinner that
never resolved — on every host that implements cancellation correctly.

This PRD does not fix that bug; `prd-cancellation-conformance.md` does. The point is
that **nobody here could have known**: no scenario exercised it, no baseline recorded
it, no CI job would have gone red.

### 1.2 Secondary problem: the official suite is client-centric, so "run the suite" is not a plan

The documented entry point is `conformance client --command …` (E-75): the thing under
test is a **client** and the suite supplies the server. A documented server-side mode
at 0.1.16 is not established by our evidence — that is OQ-1, not an assumption.

**We have nothing to hand it.** The only fixture is a hand-rolled `sys.stdin` loop
(`tests/conftest.py:7-51`, exposed as `echo_server_command` at
`tests/conftest.py:52-62`) advertising `"protocolVersion": "2025-03-26"` and four
methods. It is not a Lauren MCP server, so it cannot measure our server code.

**Our HTTP tests never bind a port.** They use the in-process ASGI client:

```python
# tests/integration/test_mcp_streamable_http.py  lines 27-35
    @module(imports=[McpServerModule.for_root(_CalcServer, transport="streamable")])
    class _App:
        pass
    a = LaurenFactory.create(_App)
    TestClient(a)
    return a
```

An external Node process cannot talk to an in-process app, so any "we pass HTTP
conformance" claim needs a fixture that binds a real socket — the adapter below.

### 1.3 Tertiary problem: no baseline, so a regression is invisible

The legacy era is not going away: deprecation is not immediate removal, a **≥12-month**
window is specified ("at least 12 months", SEP-2596 / SEP-2577, E-41). Hosts built
today still negotiate `2024-11-05` … `2025-11-25`, and we advertise all four of those
strings (`src/lauren_mcp/_mcp_version.py:7`, E-226), with `LATEST = "2025-11-25"` and
`STABLE = "2024-11-05"` (`_mcp_version.py:5-6`, E-225).

A legacy regression is therefore *worse* than a modern-era gap: the gap costs
features, the regression breaks fielded hosts. With no baseline, a PR that silently
breaks `initialize` for a `2024-11-05` client merges green.

---

## 2. Goals

1. A repo-local scenario suite, `tests/conformance/`, pinning **legacy behaviour for
   all four advertised versions**, hermetic (no network, no Node).
2. A thin adapter, `tests/conformance/harness.py`, starting a real `lauren-mcp` server
   on **stdio** and on **Streamable HTTP** (ephemeral port) and returning a
   ready-to-run command for the official suite.
3. A checked-in baseline, `tests/conformance/baseline.json`, plus a comparator that
   **fails the build when a passing scenario fails or disappears**.
4. CI separating hermetic from network-gated scenarios via `LMCP_NETWORK_TESTS`,
   mirroring the existing marker machinery (`pyproject.toml:125-129`).
5. `lmcp conformance`, running the same subset locally.
6. A written statement of **what the official suite cannot measure**, with a
   local scenario as a *supplement*, never a replacement.
7. No new runtime dependency: `lauren` + `anyio` stay the whole set
   (`pyproject.toml:27-30`), and Node is a subprocess, never an import.

**Why P2.** Real SDKs ship this and the ratings are public (E-80 … E-90), but its
absence costs credibility and regression safety, not interop: no host refuses us for lack of a harness. That is P2, not P1.

### Acceptance checklist

- [ ] `ls tests/conformance/{harness.py,scenarios.toml,baseline.json}` — all three exist
- [ ] `unshare -rn python -m pytest tests/conformance -q -m 'not network'` passes with no network at all
- [ ] `grep -c 'era = "legacy"' tests/conformance/scenarios.toml` returns ≥ 8
- [ ] `grep -o '20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]' tests/conformance/scenarios.toml | sort -u | wc -l` returns ≥ 4 (all of `src/lauren_mcp/_mcp_version.py:7`)
- [ ] `python -m pytest tests/conformance -q -k harness` starts a target on stdio **and** on a bound port; afterwards `pgrep -f 'tests.conformance._serve' | wc -l` returns 0
- [ ] `python tools/check_conformance_baseline.py --report tests/conformance/report.json --baseline tests/conformance/baseline.json` exits 0 on an unchanged tree
- [ ] Breaking a scenario on purpose (`sed -i 's/"echo"/"echoo"/' tests/conformance/_fixture_server.py`) makes that command exit **1** — the gate is proven, not assumed
- [ ] `python -m pytest tests/unit/test_conformance_baseline.py -q` passes, including the pass→fail case
- [ ] `lmcp conformance --era legacy --transport stdio` exits 0, and 1 when a scenario fails
- [ ] `LMCP_NETWORK_TESTS=1 lmcp conformance --official` runs, or exits **2** naming the missing prerequisite — never 0 by silent skip
- [ ] `grep -rn npx tests/conformance/ | grep -v _official.py` returns nothing
- [ ] `wc -c tests/conformance/baseline.json` returns < 4096

---

## 3. Non-Goals

- **Not fixing any conformance bug.** Cancellation goes to
  `prd-cancellation-conformance.md`, the modern era to `prd-dual-era-protocol-core.md`.
- **Not chasing Tier 1.** 100 % is a Tier 1 requirement (E-76) we will not hit for
  several releases; the baseline makes the number visible and monotone.
- **Not running the official suite on every PR** — it is a Node process that fetches a
  package, and it cannot catch a legacy regression we can catch locally.
- **Not a fuzzer, benchmark or coverage tool.** Scenarios are fixed transcripts;
  latency stays under the existing `benchmark` marker (`pyproject.toml:127`).

---

## 4. Design

### 4.1 What the official suite can and cannot measure — stated honestly

| Capability (our side) | Official suite, client mode (E-75) | Server mode | Local scenario? |
|---|---|---|---|
| `initialize` version negotiation | measures the *client's* offer, not our answer | not established (OQ-1) | **yes**, all four strings |
| `tools/*`, `resources/*`, `prompts/*` | request shape only | not established | **yes** |
| Streamable HTTP sessions (`mcp-session-id`) | idem | not established | **yes** |
| Legacy HTTP+SSE (`2024-11-05`) | idem | not established | **yes** |
| `notifications/cancelled` | not applicable — we do not implement it (§1.1) | not established | **yes**, fails today |
| Sessionless Streamable HTTP | not applicable — sessions are mandatory (`_streamable.py:41`, `:65`) | not established | **yes** |
| `subscriptions/listen`, `tasks/*` | absent: `grep -rn 'subscriptions/listen\|tasks/get\|tasks/list' src/` is empty | not established | no — nothing to pin yet |

We register 11 methods: `initialize`, `logging/setLevel`, `tools/list`, `tools/call`,
`resources/{list,read,subscribe,unsubscribe}`, `prompts/{list,get}`,
`completion/complete` (`src/lauren_mcp/server/_module.py:415-520`). Two conclusions,
both of which CI must print verbatim:

1. **If the suite has no server mode, it measures our client.** Our client is worth
   measuring — `src/lauren_mcp/_client/_stdio.py:236` sends `"protocolVersion":
   self._requested_protocol_version` — but a green official run then says nothing about
   server conformance, and the hermetic suite is the only server-side measurement.
2. **Local scenarios supplement, never replace.** Where we pin behaviour the suite does
   not cover, the scenario records what the repo *does*, with `pins = "current"` and a
   comment naming the PRD that flips it to `pins = "spec"`. A local scenario that
   contradicts the spec is labelled as such; it never launders a bug into "conformant".

### 4.2 The fixture server — one of everything, nothing clever

```python
# tests/conformance/_fixture_server.py
import anyio
from lauren_mcp import mcp_prompt, mcp_resource, mcp_server, mcp_tool


@mcp_server("/mcp")
class ConformanceServer:
    """Fixture target. Tool names are asserted by scenarios; do not rename."""

    @mcp_tool()
    async def echo(self, text: str) -> str:
        return text

    async def slow(self, seconds: float = 30.0) -> str:
        """Sleep, so a cancellation scenario has something to cancel."""
        await anyio.sleep(seconds)
        return "slept"

    @mcp_resource("mem://note/1")
    async def note(self) -> str:
        return "conformance"

    @mcp_prompt()
    async def summarise(self, text: str) -> str:
        return f"Summarise: {text}"
```

`mcp_resource` takes `uri_template` positionally
(`src/lauren_mcp/server/_decorators.py:874-880`); `mcp_server`, `mcp_tool`,
`mcp_prompt` are exported from `__init__.py:76-87`.

### 4.3 The adapter — a command for stdio, a URL for HTTP

```python
# tests/conformance/harness.py
import contextlib
import os
import socket
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import anyio

_ROOT = Path(__file__).parents[2]
_MODULE = "tests.conformance._serve"


@dataclass(frozen=True)
class Target:
    """How to reach a server under test."""

    transport: str                      # "stdio" | "streamable"
    command: list[str] | None = None    # for the suite's --command form
    url: str | None = None              # for the suite's --url form

    def suite_args(self) -> list[str]:
        if self.command is not None:
            return ["--command", " ".join(self.command)]
        assert self.url is not None
        return ["--url", self.url]


@contextlib.asynccontextmanager
async def stdio_target() -> AsyncIterator[Target]:
    yield Target("stdio", [sys.executable, "-m", _MODULE, "--transport", "stdio"])


@contextlib.asynccontextmanager
async def http_target() -> AsyncIterator[Target]:
    """Bind a real TCP port — deliberately not Starlette's in-process TestClient."""
    port = _free_port()
    env = {**os.environ, "PYTHONPATH": str(_ROOT / "src")}
    async with anyio.create_task_group() as tg:
        tg.start_soon(
            anyio.run_process,
            [sys.executable, "-m", _MODULE, "--transport", "streamable",
             "--port", str(port)],
            env, str(_ROOT),
        )
        await _wait_port(port, timeout=20.0)
        try:
            yield Target("streamable", url=f"http://127.0.0.1:{port}/mcp")
        finally:
            tg.cancel_scope.cancel()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def _wait_port(port: int, *, timeout: float) -> None:
    """Poll until *port* accepts a connection; TimeoutError after *timeout*."""
    # elided: sleep-loop over socket.create_connection; raises on timeout
```

```python
# tests/conformance/_serve.py — python -m tests.conformance._serve --transport …
def main() -> None:                          # argparse: --transport, --port
    @module(imports=[McpServerModule.for_root(ConformanceServer, transport=args.transport)])
    class _AppModule:
        pass

    app = LaurenFactory.create(_AppModule)
    if args.transport == "stdio":
        app.run()                            # serves over stdin/stdout
    else:
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
```

It mirrors `lmcp run` (`cli/_commands.py:236-241`): one serving story.

### 4.4 The repo-local scenario list — legacy first

```toml
# tests/conformance/scenarios.toml
[meta]
suite         = "@modelcontextprotocol/conformance"
suite_version = "0.1.16"          # E-75; bump deliberately, never float
era_default   = "legacy"

# ---- legacy era: frozen. A regression here breaks fielded hosts (E-41). ----
[[scenario]]
id = "legacy/initialize-echo-2024-11-05"; era = "legacy"; transport = "stdio"
version = "2024-11-05"; pins = "spec"
assert = "result.protocolVersion == '2024-11-05'"

[[scenario]]
id = "legacy/initialize-echo-2025-03-26"; era = "legacy"; transport = "stdio"
version = "2025-03-26"; pins = "spec"
assert = "result.protocolVersion == '2025-03-26'"

[[scenario]]
id = "legacy/initialize-echo-2025-06-18"; era = "legacy"; transport = "stdio"
version = "2025-06-18"; pins = "spec"
assert = "result.protocolVersion == '2025-06-18'"

[[scenario]]
id = "legacy/initialize-echo-2025-11-25"; era = "legacy"; transport = "stdio"
version = "2025-11-25"; pins = "spec"
assert = "result.protocolVersion == '2025-11-25'"

[[scenario]]
id = "legacy/initialize-unknown-version"; era = "legacy"; transport = "stdio"
version = "1999-01-01"; pins = "spec"
# _server/_handshake.py:23-25 -> not in SUPPORTED -> LATEST (_mcp_version.py:5)
assert = "result.protocolVersion == '2025-11-25'"

[[scenario]]
id = "legacy/tools-list-shape"; era = "legacy"; transport = "stdio"; pins = "spec"
assert = "set(t['name'] for t in result.tools) == {'echo','slow'}"

[[scenario]]
id = "legacy/tools-call-echo"; era = "legacy"; transport = "stdio"; pins = "spec"
assert = "result.content[0].text == 'hello'"

[[scenario]]
id = "legacy/resources-read"; era = "legacy"; transport = "stdio"; pins = "spec"
assert = "result.contents[0].text == 'conformance'"

[[scenario]]
id = "legacy/prompts-get"; era = "legacy"; transport = "stdio"; pins = "spec"
assert = "result.messages[0].content.text.startswith('Summarise:')"

[[scenario]]
id = "legacy/http-session-header"; era = "legacy"; transport = "streamable"
pins = "spec"
assert = "'mcp-session-id' in response_headers"      # _server/_streamable.py:41

[[scenario]]
id = "legacy/http-no-session-rejected"; era = "legacy"; transport = "streamable"
pins = "current"                                    # sessionless mode is OQ-2
assert = "request_without_session.status >= 400"

[[scenario]]
id = "legacy/cancel-request"; era = "legacy"; transport = "streamable"
pins = "current"
# $/cancelRequest is LSP; the spec says notifications/cancelled
# (_server/_streamable.py:212, _server/_stdio.py:76). Flips to pins="spec" when
# prd-cancellation-conformance.md lands.
assert = "notifications_cancelled_has_no_effect"

# ---- modern era: empty until the dual-era PRD lands ----
```

Every `pins = "current"` entry is a debt marker, printed with a `DEBT` flag.

### 4.5 The baseline — a summary, not a transcript

```json
{"schema": 1, "date": "2026-11-26",
 "suite": {"name": "@modelcontextprotocol/conformance", "version": "0.1.16"},
 "server_side": {
   "local": {"total": 12, "pass": 8, "debt": 2, "fail": 2},
   "official": {"available": false, "reason": "client-mode entry point at 0.1.16 (E-75); OQ-1"}},
 "client_side": {"official": {"total": 0, "pass": 0}},
 "era": {"legacy": 12, "modern": 0},
 "scenarios": {"legacy/initialize-echo-2024-11-05": "pass",
               "legacy/cancel-request": "debt"},
 "gate": {"require": ["no_pass_to_fail", "no_scenario_disappears",
                     "no_era_bucket_shrinks"],
          "policy": "legacy is frozen; modern may only grow"}}
```

Written by `lmcp conformance --update-baseline`, reviewed like code, and kept small:
no timings, no transcripts, so it does not churn per platform.

The comparator (`tools/check_conformance_baseline.py`, ~40 lines) walks the baseline,
and for each id compares status: `pass → fail|error|missing` is a violation, a missing id
is a violation, `debt → fail|error` is a violation (debt may not get worse), and any era
bucket that shrinks is a violation. New ids and `fail → pass` are free. Violations print
as `::error::conformance baseline: …` and exit 1.

### 4.6 `lmcp conformance` — the developer command

```python
# src/lauren_mcp/cli/__init__.py  line 17
from lauren_mcp.cli._commands import call, conformance, dev, inspect_cmd, install, run
# after line 22
app.command("conformance")(conformance)
```

```python
# src/lauren_mcp/cli/_commands.py  (append after install(); file is 341 lines)
def conformance(
    scenario: Annotated[list[str], typer.Option(help="Scenario id; repeatable")] = [],
    transport: Annotated[str, typer.Option(help="stdio | streamable | all")] = "all",
    era: Annotated[str, typer.Option(help="legacy | modern | all")] = "legacy",
    official: Annotated[bool, typer.Option("--official/--no-official",
                                          help="Also call npx (needs network + Node)")] = False,
    update_baseline: Annotated[bool, typer.Option("--update-baseline")] = False,
    list_only: Annotated[bool, typer.Option("--list")] = False,
) -> None:
    """Run the repo conformance scenarios and compare against the baseline.

    Exit codes: 0 gate passed, 1 gate failed, 2 environment problem
    (missing Node with --official, unreadable baseline).
    """
    from lauren_mcp.conformance import run_cli  # noqa: PLC0415

    raise typer.Exit(code=run_cli(
        scenarios=scenario, transport=transport, era=era, official=official,
        update_baseline=update_baseline, list_only=list_only,
    ))
```

Runner logic (`load_scenarios`, `run_scenario`, `run_cli`) lives in the new
`src/lauren_mcp/conformance/` package so it is importable from tests. Node is imported
lazily with a clear message, like the optional imports at
`src/lauren_mcp/cli/_commands.py:226-230`.

### 4.7 CI wiring — hermetic by default, official by opt-in

Appended to `.github/workflows/tests.yml` after the `coverage` job (line 77), before
`extras-matrix` (line 124):

```yaml
  conformance-hermetic:                       # every PR; no network, no Node
    name: Conformance (hermetic, legacy era)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install -e '.[all]' && nox -s conformance
      - run: python tools/check_conformance_baseline.py
               --report tests/conformance/report.json
               --baseline tests/conformance/baseline.json
      - uses: actions/upload-artifact@v4
        if: always()
        with: { name: conformance-report, path: tests/conformance/report.json }

  conformance-official:                     # opt-in: label `conformance` or push
    name: Conformance (official suite 0.1.16)
    if: github.event_name == 'push' || contains(github.event.pull_request.labels.*.name, 'conformance')
    runs-on: ubuntu-latest
    env: { LMCP_NETWORK_TESTS: "1" }
    steps:                                # python 3.11 + node 20 + checkout, then:
      - run: nox -s conformance_official -- --transport stdio
      - run: nox -s conformance_official -- --transport streamable
```

The marker and default-skip sit next to the existing ones:

```toml
# pyproject.toml  lines 125-129
addopts      = "-m 'not benchmark and not eval and not network'"
markers      = [
    "benchmark: performance benchmarks, excluded from default run",
    "eval: evaluation tests requiring live MCP servers, excluded from default run",
    "network: needs outbound network or Node; opt in with LMCP_NETWORK_TESTS=1",
]
```

```python
# tests/conformance/conftest.py
needs_net = pytest.mark.skipif(
    os.environ.get("LMCP_NETWORK_TESTS") != "1",
    reason="network-gated; set LMCP_NETWORK_TESTS=1 (see .github/workflows/tests.yml)",
)
```

---

## 5. Server-side Changes

**None.** No protocol behaviour, registration
(`src/lauren_mcp/server/_module.py:415-520`) or transport changes. The two divergences
recorded as `pins = "current"` — `$/cancelRequest` (§1.1) and mandatory sessions
(`src/lauren_mcp/_server/_streamable.py:41`) — are pre-existing and fixed by their own
PRDs. Recording them here is deliberate: an instrument's first job is a truthful reading.
The only `src/` additions are `lauren_mcp/conformance/` and the `lmcp conformance`
wrapper.

---

## 6. Exact Lines to Change

| File | Line | Change |
|---|---|---|
| `pyproject.toml` | 125 | `addopts`: add `and not network` |
| `pyproject.toml` | 126-129 | add the `network` marker |
| `src/lauren_mcp/cli/__init__.py` | 17, 22 | extend the import; append `app.command("conformance")(conformance)` |
| `src/lauren_mcp/cli/_commands.py` | 341 | append `def conformance(...)` per §4.6 |
| `noxfile.py` | 16 | add `"conformance"` to `nox.options.sessions` |
| `noxfile.py` | 71 | add sessions `conformance` (`pytest tests/conformance -m 'not network'`) and `conformance_official` (`lmcp conformance --official --transport {posargs}`) |
| `.github/workflows/tests.yml` | 123 | insert the two jobs from §4.7 |

New files: `tests/conformance/` (`harness.py`, `_serve.py`, `_fixture_server.py`,
`scenarios.toml`, `baseline.json`, `test_scenarios.py`, `conftest.py`, `_official.py`),
`src/lauren_mcp/conformance/` (`runner.py`, `scenarios.py`),
`tools/check_conformance_baseline.py`. Regenerating docs also rewrites `llms-full.txt`
via the existing `llms-full-txt-sync` prek hook (so `nox -s llms_check` must pass in the
same PR); `docs/reference/cli.md:68` gains a `## Conformance` section.

---

## 7. Backward Compatibility

- **Public API:** no new exports from `lauren_mcp`; `lauren_mcp.conformance` is a
  developer surface, documented as such.
- **Existing tests:** the only shared-config edit is `addopts` gaining
  `and not network` (`pyproject.toml:125`). `grep -rn 'mark.network' tests/` returns
  nothing today, so it is behaviour-preserving and only binds new tests.
- **Existing fixtures:** `tests/conftest.py:7-62` is untouched, so the ~100 tests
  depending on `echo_server_command` are unaffected.
- **Coverage:** `tests/conformance/` sits under `tests/`, already omitted
  (`pyproject.toml:135`), so the 88 % gate (`pyproject.toml:139`) does not move.
- **Migration for users:** none — the one kind of change that asks nothing of anyone.

---

## 8. Test Plan

**8.1 `tests/unit/test_conformance_baseline.py`** — `test_diff_clean` (`[]` on
identical input); `test_diff_pass_to_fail`; `test_diff_scenario_disappears`;
`test_diff_debt_to_fail` (debt may not get worse); `test_diff_new_scenario_ok` (`[]`);
`test_diff_era_bucket_shrinks` (`legacy` 12 → 11); `test_exit_code` (1 vs 0).

**8.2 `tests/unit/test_conformance_scenarios.py`** — `test_ids_unique`;
`test_all_versions_pinned` (all four values in `src/lauren_mcp/_mcp_version.py:7`);
`test_era_taxonomy`; `test_pins_taxonomy` (every `current` carries a comment);
`test_legacy_minimum` (≥ 8 legacy scenarios).

**8.3 `tests/integration/test_conformance_harness.py`** — `test_stdio_target_command_shape`
(`suite_args()` yields `["--command", "… -m tests.conformance._serve --transport stdio"]`);
`test_stdio_roundtrip` (`initialize` echoes our version); `test_http_target_binds_port`;
`test_http_initialize` (POST returns `mcp-session-id`); `test_no_orphans` (`pgrep` empty
after both context managers exit); `test_http_timeout` (`_wait_port` raises rather than
hangs).

**8.4 `tests/integration/test_cli_conformance.py`** — `test_list` (exit 0, every id
printed); `test_era_filter` (`--era modern` → "0 scenarios", exit 0);
`test_exit_2_without_node` (exit 2 naming the prerequisite); `test_baseline_gate_fails`
(doctored `report.json` → exit 1 with a `::error::` line).

---

## 9. Open Questions

- **OQ-1 — does 0.1.16 have a server mode?** Resolve with `npx
  @modelcontextprotocol/conformance@0.1.16 --help` and record an `E-…` row before
  implementation; if not, §4.1 conclusion 1 stands.
- **OQ-2 — is sessionless Streamable HTTP in scope?** Sessions are mandatory today
  (`_streamable.py:41`, `:65`); if a modern host may omit them, that is P1 for the
  transport PRD.
- **OQ-3 — recorded or hand-written transcripts?** Proposal: hand-written for
  `pins = "spec"`, recorded for `pins = "current"`.
- **OQ-4 — who may bump the baseline?** Proposal: the PR body carries `CONFORMANCE-BASELINE:`.

---

## 10. lauren-mcp Advantages

1. **Two runtime dependencies make the fixture honest.** `pyproject.toml:27-30` is
   `lauren` + `anyio` (E-222), so `_serve.py` exercises the import path a user gets from
   a bare `pip install lauren-mcp`; SDK harnesses often measure a path that only exists
   with a full optional stack — "green on the suite, broken in production".
2. **Four version strings in one file.** `_mcp_version.py:5-7` advertises `2024-11-05`,
   `2025-03-26`, `2025-06-18`, `2025-11-25` (E-225, E-226) and
   `_server/_handshake.py:14-25` answers each correctly, so legacy conformance is cheap
   to *prove* here: the era is small, closed, implemented in full.
3. **Transport is a constructor argument.** `McpServerModule.for_root(server,
   transport="streamable")` (`tests/integration/test_mcp_streamable_http.py:29`,
   `src/lauren_mcp/cli/_commands.py:236`) serves stdio, SSE, WS and Streamable HTTP from
   one line; our adapter is ~80 lines where per-transport SDKs need a second harness.
4. **The known bug is one line wide.** `$/cancelRequest` (`_server/_stdio.py:76`,
   `_streamable.py:212`) is a string constant, not a design flaw: scenario and fix land
   in the same PR.

---

## 11. References

**Evidence rows.** E-75 (official suite, v0.1.16, pushed 2026-11-23); E-76 (tier pass
rates 100/80/—); E-55 (SEP-1730, shipped `2025-11-25`); E-80 … E-89 (ten SDKs, nine
modern-era); **E-90 (`lauren-mcp` 1.0.0: `no`, 0, 0)**; E-41 (≥12-month deprecation
window, SEP-2596 / SEP-2577 — why the legacy freeze outranks the modern gap); E-222
(two-dependency posture); E-225 (`LATEST`/`STABLE`); E-226 (`SUPPORTED`).

**Repo paths, verified with `grep -n` / `grep -o`.** `pyproject.toml:27-30`, `:32-46`,
`:47-48`, `:123-131`, `:135-139` (`fail_under = 88`), `:142-158`; `cli/__init__.py:17-22`,
`cli/_commands.py:24-33`, `:226-241`, `:341`; `server/_module.py:415-520`;
`_server/_handshake.py:14-25`, `_stdio.py:76`, `_streamable.py:41`, `:212`;
`server/_decorators.py:874-880`; `_mcp_version.py:5-7`; `__init__.py:76-87`;
`tests/conftest.py:7-62`; `tests/integration/test_mcp_streamable_http.py:27-35`;
`noxfile.py:16`, `:42-71`; `.github/workflows/tests.yml:17,47,77,124`;
`docs/reference/cli.md:12,41,68`; `.gitignore:70`.

**Spec / external.** MCP cancellation is `notifications/cancelled` (§1.1); SEP-1730
(tiers); SEP-2596 / SEP-2577 (deprecation window).
`@modelcontextprotocol/conformance` **0.1.16** (E-75), pinned exactly, so a baseline
means something.
