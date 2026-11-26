# PRD — Developer tooling on `lmcp inspect`: transcripts, scenarios, non-interactive runs

**Status:** Draft
**Date:** 2026-11-26
**Scope:** `src/lauren_mcp/cli/_commands.py` (`inspect_cmd`), new `src/lauren_mcp/cli/_inspect/` package, `src/lauren_mcp/_client/` frame sink, `docs/reference/cli.md`
**Priority:** P3
**Issue:** _pending_

---

## 1. Problem Statement

### 1.1 What the evidence establishes, and what it does not

| Claim | Value | Anchor |
|---|---|---|
| Inspector current version | **2.16.0** (`latest` dist-tag) | `E-165` |
| Inspector has known advisories | **2 OSV advisories** | `E-166` |
| Inspector's functional surface at 2.16.0 | **not enumerated** | `U-01` |

```
prds/2026-11-landscape/EVIDENCE.md  line 516
| U-01 | Inspector's full functional surface at 2.16.0 | an "Inspector parity" PRD needs a
  checklist, not a version | read the Inspector README/source at implementation time |
```

The known-gap note above it is explicit that the review established *version and vulnerability count, not
feature surface* (`EVIDENCE.md:277-282`). **This PRD therefore makes no claim about what the Inspector does or
does not do.** Every capability below follows from two verifiable sources: this repository's client surface
(`src/lauren_mcp/_client/`, 13 methods over 4 transports) and the spec's grep-verified method inventory
(`_research/spec.md` §7). Where "parity" would be tempting, the claim is instead: *the protocol gives a
developer this method, and nothing here lets them exercise it.* Acceptance criteria are written against this
repo's own behaviour (exit codes, JSON keys, frames on disk); the one criterion that needs the Inspector
(`AC-14`) is a research task. `E-166` is a reason to *prefer* an in-tree command; its severity was not recorded, so it is
not evidence that the reference tool is unsafe.

### 1.2 What `lmcp inspect` does today

`src/lauren_mcp/cli/_commands.py:71` is the whole command: a positional `file_spec_or_url`, a `transport`
option defaulting to `"ws"` (`:76`), and the docstring *"Connect to an MCP server and list its tools,
resources, and prompts"* (`:78`). It connects over one of four transports (`:85-91`, `_make_remote_client` at
`:170-177`), calls exactly three methods (`list_tools` / `list_resources` / `list_prompts`, `:95-97`), and
prints names only:

```python
# src/lauren_mcp/cli/_commands.py  line 101
            typer.echo(f"  {t.name}: {t.description}")
```

1. **Three methods out of thirteen.** `call_tool`, `read_resource`, `subscribe_resource`,
   `unsubscribe_resource`, `get_prompt`, `ping`, `set_logging_level`, and `complete` are unreachable from
   `inspect` (`_client/_protocol.py:28,37,49,57,83,91,108,126,143,151,176,184,206`).
2. **No schemas.** `ToolSchema.inputSchema` (`_types.py:280`) is dropped and resources/prompts lose fields
   (`_commands.py:104-109`), so a developer cannot tell what to send a tool.
3. **No machine-readable mode.** `grep -n '\-\-json' src/lauren_mcp/cli/_commands.py` → 0 hits; the one
   `json.dumps` (`:165`) belongs to `call`.
4. **No frame visibility.** No JSON-RPC observation seam exists in `src/lauren_mcp/_client/`, so a wire
   transcript cannot be produced at all.

### 1.3 Failure scenario: the bug report that cannot be filed

A user reports *"my tool returns nothing when a host calls it, but it works when I test it."* The operator's
toolchain is `lmcp inspect server.py`, which prints `Tools (2):` / `add: Add two numbers` and nothing else —
a screenshot with no `inputSchema`, no arguments, no raw envelope, no notification. The maintainer must ask
the reporter to install a Node toolchain and reproduce by hand, and none of it is diffable, replayable, or
attachable. The **raw envelope**, the **frame transcript**, and a **recorded scenario that re-runs** would
turn this into a one-message report. The command has none of the three.

### 1.4 Failure scenario: nothing here runs in CI

The only `inspect` test mocks the async layer and asserts `asyncio.run` was called
(`tests/unit/test_cli_commands_coverage.py:391`). "Connect, call `add` with `{a:1,b:2}`, assert
`content[0].text == "3"`, exit non-zero otherwise" is inexpressible — as a test or a shell line — so every
conformance PRD in this set writes its own harness: the same harness, seven times.

### 1.5 The spec surface a developer tool is expected to cover

`_research/spec.md:337` is a grep-verified inventory. For the legacy era — the era this repo implements — the
surfaces a developer needs to exercise are `tools/{list,call}`, `resources/{list,read,templates/list}`,
`prompts/{list,get}`, `completion/complete`, `ping`, `logging/setLevel`, `resources/{subscribe,unsubscribe}`,
`notifications/{cancelled,progress}`, `roots/list`, `sampling/createMessage`, and `elicitation/create`
(`spec.md:344-362`). `lmcp inspect` reaches three of them. Two rows are why the tool must exist before the
server features do:

```
prds/2026-11-landscape/_research/spec.md  line 352
| `server/discover` | — | — | — | — | **10** | **Added**, servers **MUST** |
prds/2026-11-landscape/_research/spec.md  line 255
| 8 | All results now carry a required **`resultType`**: `"complete"` for ordinary results,
  `"input_required"` for MRTR interim responses | SEP-2322 |
```

A tool that can *call* `server/discover` and *print* the result verbatim — `resultType` included — is how the
acceptance tests for `prd-server-discover-request-meta.md` and `prd-result-envelope-caching.md` get written.
Today `lmcp` cannot display a field it has no dataclass for; `grep -rn resultType src/` → 0.

### 1.6 The security problem a local inspection tool creates

`lmcp inspect server.py` is an executor: `_commands.py:90-91` builds a `python -c` script and spawns it.
Correct for a *local file the operator named* — but a hazard once this PRD adds a scenario file (`--script`)
and a recorded session (`--record`). Both arrive from somewhere (an issue attachment, a docs page), and a
naive format would let such a file carry `"command": ["npx", "-y", "@scope/server"]` or
`"file": "../../etc/x.py"`. Replaying a stranger's recording must not, by default, execute what it names.

---

## 2. Goals

1. **Expose every client method** — all 13 in `_protocol.py` reachable from `inspect` (`AC-02`).
2. **Print schemas, not names** — `inputSchema`, resource `uri`/`mimeType`, prompt `arguments` (`AC-03`).
3. **Show the raw envelope** — unknown keys preserved, `resultType` when present, `isError` always (`AC-04`).
4. **A versioned JSON document** (`--json`, logs to stderr) and a **scenario engine** (`--script` with
   assertions and a stable exit-code contract) (`AC-05`…`AC-10`).
5. **Record and replay** — `--record` writes a bundle; `--diff` re-runs and compares (`AC-11`); and
   `--transcript` shows raw frames with direction and relative time, redacted by default (`AC-12`).
6. **Interactive server-initiated requests** — elicitation, sampling, MRTR answers via the factory kwargs at
7. **Fail closed on execution** — nothing spawns without `--allow-exec` (`AC-09`, `AC-10`).

**Priority — P3, and why.** `PRD-BRIEF.md` §4 defines P3 as ergonomics, packaging, and developer tooling.
Nothing here breaks a deployment, no spec MUST is violated by its absence, and the command already connects
over all four transports — incremental surface, not a rescue.

---

## 3. Non-Goals

* **No parity checklist against an unenumerated surface (`U-01`).** §10 Q-1 records the settlement action.
* **No web UI, browser control, or proxy.** Output is text, JSON, or a file; no TUI.
* **No new runtime dependency or extra.** Frame capture is a `Callable`; `E-222` and the `cli` extra (`pyproject.toml:38-45`) hold.
* **No remote script fetching.** `--script https://…` is rejected, not implemented (§4.7).
* **No load testing, fuzzing, or benchmarking**, and **no new server behaviour**: a scenario runs once, in
  order, and §5 is client/CLI only — this PRD is the *instrument* for other PRDs' features.
---

## 4. Design

### 4.1 The capability list, derived from the method inventory

This table *is* the scope; column two is the justification.

| Capability | Justification | Surface |
|---|---|---|
| stdio, WebSocket, HTTP+SSE, Streamable HTTP | `_factory.py:68,105,139,182` | `--transport ws\|sse\|streamable` |
| tools with `inputSchema`; resources + templates; prompts + `arguments` | `spec.md:362`, `_types.py:280,475` | text view, `--json` |
| read resource, get prompt, call tool with JSON args | `_protocol.py:91,151,57` | `:read`, `:get-prompt`, `:call` |
| raw envelope incl. `resultType` | `spec.md:255`, `:314` | `--raw` |
| completion, ping, log level | `spec.md:361,346,347`; `_protocol.py:206,176,184` | `:complete`, `:ping`, `:log-level` |
| subscribe + show notifications | `spec.md:348`; `_protocol.py:108`; `_features.py:132` | `:subscribe` |
| elicitation, sampling, MRTR | `spec.md:355,357,254`; `_factory.py:46-50` | `:elicit`, `:sample`, scripted ops |
| `server/discover` assertion | `spec.md:352` | `{"op":"server_discover"}` |
| transcript; non-interactive scenarios | seam absent (§1.2); §1.4 | `--transcript`, `--record`, `--script` |

Deliberately absent: `tasks/*` is an extension (`spec.md:358`), `subscriptions/listen` (`:353`) replaces
subscribe in the modern era, and `initialize` / `notifications/initialized` (`:344,345`) are removed there. The
tool must *observe* those transitions (for `prd-dual-era-protocol-core.md`), not implement them.

### 4.2 Command shape

Ten flags, all keyword-only so the two positional arguments do not move: `--json`, `--script PATH`,
`--record PATH`, `--diff PATH`, `--transcript`, `--interactive/--no-interactive`, `--allow-exec`,
`--no-redact`, plus the existing `--transport`. All default off, so today's behaviour is byte-identical (§7).

```python
# src/lauren_mcp/cli/_commands.py  NEW — keyword-only additions to the signature at line 71
    as_json: Annotated[bool, typer.Option("--json")] = False,             # one JSON document on stdout
    script: Annotated[Path | None, typer.Option(help="Run a scenario file.")] = None,
    allow_exec: Annotated[bool, typer.Option("--allow-exec")] = False,    # a scenario may spawn a process
```

```bash
lmcp inspect server.py --json | jq '.tools[0].inputSchema'   # plain `lmcp inspect server.py` is unchanged
lmcp inspect ws://127.0.0.1:8000/ws --transcript
lmcp inspect server.py --script scenarios/add.json --json
lmcp inspect server.py --record /tmp/s.lmcp.json --interactive
```

### 4.3 `--json`: one versioned document

stdout carries exactly one JSON object; human-facing notes go to stderr, so `--json | jq` is safe. `target`
never leaks a secret: a URL is emitted with userinfo stripped, a local spec as the spec string (never the
generated `python -c`).

```json
{"schemaVersion": 1, "lmcpVersion": "1.0.0",
 "target": {"kind": "url", "value": "ws://127.0.0.1:8000/ws", "transport": "ws"},
 "negotiated": {"protocolVersion": "2025-11-25", "serverInfo": {"name": "demo", "version": "0.1.0"}},
 "capabilities": {"tools": {"listChanged": true}},
 "tools": [{"name": "add", "inputSchema": {"type": "object", "required": ["a","b"],
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}}}}],
 "resources": [], "resourceTemplates": [], "prompts": [], "steps": [],
 "transcript": {"path": null, "frames": 0}, "errors": []}
```

`negotiated.protocolVersion` reads `_features.py:94` and `capabilities` reads `_features.py:104`, so this
view is mostly a serialiser over data the client already holds — hence P3, not P2.

### 4.4 `--script`: a scenario file with assertions

JSON, not YAML: no new dependency, and `json` is already imported at `_commands.py:332`. Every field is
validated before a connection opens.

```json
{"schemaVersion": 1, "target": {"file": "server.py:DemoServer"}, "transport": "ws",
 "steps": [
   {"id": "lists-tools", "op": "list_tools", "expect": {"tools.0.name": "add"}},
   {"id": "adds", "op": "call_tool", "name": "add", "arguments": {"a": 1, "b": 2},
    "expect": {"content.0.text": "3", "isError": false}},
   {"id": "discovers", "op": "server_discover", "optional": true,
    "expect": {"protocolVersions.$len": {"$gte": 1}}}]}
```

`op` names are the client method names (`_protocol.py:49,57,83,91,108,126,143,151,176,184,206`), except
`server_discover` — which sends `server/discover` (`spec.md:352`), fails `unsupported` on a legacy server, and
is skipped when `optional: true` — and `elicit` / `sample`, which answer a server-initiated request queued by
the preceding step. `expect` maps dotted paths to expectations; a scalar means deep equality, with
`{"$exists": true}` for presence (how a legacy server's *absence* of `resultType` is asserted),
`{"$len": {"$gte": 1}}`, and `{"$matches": "^demo"}`.

**Exit codes** — the contract CI depends on: `0` all steps passed or skipped; `1` assertion failed (step id
printed); `2` usage error, unreadable script, or handshake failure; `3` refused (`--allow-exec` needed);
`4` step raised, timed out, or transport closed. With `--json`, `steps` becomes
`[{"id":"adds","op":"call_tool","ok":true,"result":{…},"durationMs":12}]`.

### 4.5 `--record` / `--diff`: a shareable bug

A bundle is one JSON file holding `schemaVersion`, `createdAt`, `lmcpVersion`, `redactions`, `scenario`,
`frames` (`{"t", "dir", "frame"}` per frame) and `results` keyed by step id.

* **The target is a value, not a command, and `--diff` compares results, not frames.** A `url` bundle
  replays against whatever endpoint the operator names, and it never carries the `python -c` string from
  `_make_stdio_script` (`_commands.py:260`) — that would be executable content in a shareable artefact.
  Comparison is over `results` by step id, because servers legitimately change ids and timings; a mismatch
  prints a unified diff and exits 1, making `--diff` a regression test attachable to a PR.
* **Redaction is default-on.** `authorization`, `cookie`, `mcp-session-id`, and `_meta.authorization` values
  become `"<redacted>"`; keys stay, so the shape of the bug is intact. `--no-redact` warns on stderr.

### 4.6 The frame seam

One inbound funnel, four outbound writers:

```
inbound :  src/lauren_mcp/_client/_base_remote.py  line 171   def _dispatch_message(self, raw: str)
outbound:  src/lauren_mcp/_client/_ws.py           line 118   async def _send_raw(self, obj)
           … same shape in _sse.py:146, _streamable.py:140, _stdio.py:285
stdio in:  src/lauren_mcp/_client/_stdio.py        line 313   self._dispatch(msg)   # read loop (:293)
```

One attribute plus five one-line calls — no signature changes, no dependency:

```python
# src/lauren_mcp/_client/_base_remote.py  NEW, next to _send_raw at line 101
def _emit_frame(self, direction: str, frame: dict[str, Any]) -> None:   # "in" | "out"; None by default
    if self._frame_sink is not None:
        self._frame_sink(direction, frame)   # wrapped in try/except: an observer must not break a transport

# src/lauren_mcp/_client/_ws.py  line 118 — first statement (same in _sse.py:146,
# _streamable.py:140, _stdio.py:285);  _base_remote.py:171 after parse_message(raw)
        self._emit_frame("out", obj)
# src/lauren_mcp/_client/_stdio.py  line 313, before self._dispatch(msg)
        self._emit_frame("in", msg)
```

The sink is a plain callable, so the CLI owns rendering: `--transcript` is `TranscriptRecorder(echo=True,
redact=not no_redact)`, and `--record` is the same recorder with `echo=False` plus a bundle write.

### 4.7 Interactive mode, and execution is opt-in

The factory already accepts both handlers (`_client/_factory.py:46-50`) and advertises the MRTR capability
shape when a sampling handler is present (`:50`). The CLI passes neither, so a server that asks a question
today gets no answer and the call fails opaquely. `--interactive` turns each server-initiated request into a
visible prompt — `! elicitation/create "What is your name?"  answer: {"name":"Ada"}`, then
`! sampling/createMessage (1 message, maxTokens 100)  answer: {…}` — and the tool call then completes with
`{"resultType":"complete","content":[{"type":"text","text":"done"}]}`.

Verbs (`:` never collides with JSON): `:tools`/`:resources`/`:prompts`, `:call <tool> <json>`, `:read <uri>`,
`:get-prompt <name>`, `:subscribe`/`:unsubscribe <uri>` (incoming `notifications/resources/updated` print as
they arrive), `:complete`, `:ping`, `:log-level`, `:discover` (prints "unsupported" on a legacy server),
`:frames on|off`, `:quit`. Scripted runs use the `elicit`/`sample` ops with a queue of canned answers, so the
same behaviour is testable in CI without a human; both paths share one `AnswerQueue`.

**Execution is opt-in.** Enforced in one place, `_inspect/_scenario.py`, before any connection — a file that
`lmcp inspect` is pointed at may describe a target, it may not constitute one:

1. `target` may be `{"url": …}` (any of the four schemes) or `{"file": …}`; a `file` target resolves relative
   to the scenario's directory and must not escape it (`../` → exit 2).
2. A `file` target requires `--allow-exec`, unless the operator also passed the file spec on the command line
   — then the command line wins, with a stderr note. `lmcp inspect server.py --script someone.json` never
   runs *their* file.
3. No other key may name a program: `{"command": […]}` / `{"args": […]}` exit 2 with `scenario may not
   specify a command; pass --allow-exec with an explicit file spec`. This closes the "replay a stranger's
   `npx -y …` line" hole.
4. Scripts come from a local path or stdin only; a scheme in `--script` exits 2 (`refusing to fetch a scenario
   over the network`).
5. `lmcp inspect server.py` still spawns a subprocess — the command's documented purpose (`_commands.py:88-91`,
   `docs/reference/cli.md:50`) — but `--verbose` prints the exact argv.

---

## 5. Client-side Changes

1. `_base_remote.py:89` — `self._frame_sink: Callable[[str, dict[str, Any]], None] | None = None` beside
   `self._pending`; add `_emit_frame`; call it at `:171`.
2. `_ws.py:118`, `_sse.py:146`, `_streamable.py:140`, `_stdio.py:285` — one `self._emit_frame("out", obj)`.
3. `_stdio.py:313` — one `self._emit_frame("in", msg)` before `self._dispatch(msg)`.
5. `cli/_commands.py` — options per §4.2; `_inspect_async` gains keyword-only `options: InspectOptions | None
   = None`, so `tests/unit/test_cli_commands_coverage.py:398` keeps working.
6. New package `src/lauren_mcp/cli/_inspect/` — `_options.py`, `_scenario.py`, `_transcript.py`, `_render.py`,
   `_repl.py`. No third-party imports.

---

## 6. Exact Lines to Change

| File:line | Change |
|---|---|
| `cli/_commands.py:71-77` | add the eight keyword-only options (§4.2) |
| `cli/_commands.py:78` / `:79` | docstring → "inspect a server: list, call, record, replay" / `asyncio.run(…, options=…)` |
| `cli/_commands.py:82-112` | thin adapter over `_inspect/_session.py`; the branch at `:85` and `_make_remote_client` (`:86`, `:170-177`) are untouched. `:99-109` moves to `_render.render_default`, byte-compatible (§7) |
| `cli/_commands.py:165` | unchanged — `call` keeps its JSON dump |
| `_base_remote.py:89` / `:101` / `:171` | `_frame_sink` attribute / `_emit_frame` / `self._emit_frame("in", msg)` |
| `_ws.py:118`, `_sse.py:146`, `_streamable.py:140`, `_stdio.py:285` | first statement of `_send_raw`: `self._emit_frame("out", obj)` |
| `_stdio.py:313` | before `self._dispatch(msg)`: `self._emit_frame("in", msg)` |
| `docs/reference/cli.md:41-68` | document the seven flags, the §4.4 exit codes, one scenario example |

---

## 7. Backward Compatibility

* **`lmcp inspect server.py` output is unchanged** — same `Tools (n):` / `  name: description` lines from
  `_commands.py:99-109`. Schemas print after each description and only when non-empty, so a schema-less tool
  renders exactly as today.
* **`lmcp call` is untouched**, including its `json.dumps` at `:165`.
* **`_inspect_async(file, transport)` still works positionally**; new behaviour arrives via keyword-only
  `options`, so `tests/unit/test_cli_commands_coverage.py:398` passes unmodified.
* **The frame sink is inert when `None`** — no behaviour change, one `None` check on the hot path.
* **Artefact formats are versioned from day one** (`"schemaVersion": 1`); an unknown version exits 2 rather
  than guessing, because bundles outlive the release that wrote them.

---

## 8. Test Plan

**Unit — `tests/unit/test_cli_inspect_options.py`**: `test_json_document_keys_are_stable` (the §4.3 keys,
`inputSchema` verbatim); `test_default_view_matches_legacy_text` (golden string, schema-less server);
`test_script_ops_map_to_protocol_methods`; `test_assertion_operators`; `test_exit_codes` (0/1/2/3/4 via
`typer.testing.CliRunner`, failing step id on stderr); `test_scenario_rejects_command_key`,
`test_scenario_file_target_requires_allow_exec`, `test_scenario_path_escape_rejected`,
`test_script_url_rejected` (§4.7 rules 2-4); `test_redaction`; `test_bundle_roundtrip`;
`test_diff_detects_changed_result`.

**Unit — `tests/unit/test_client_frame_sink.py`**: `test_sink_receives_out_then_in` for all four transports
(direction order; inbound payload is the parsed dict, not the raw string); `test_sink_default_none_is_inert`;
`test_sink_exception_does_not_kill_transport`.

**Integration — `tests/integration/test_inspect_scenarios.py`**: against a real `@mcp_server` class over stdio
and over `--transport ws`: `test_inspect_json_over_stdio` / `test_inspect_json_over_ws`,
`test_script_call_tool_asserts_content`, `test_subscribe_then_receive_notification`,
`test_record_replay_diff_is_clean`, `test_interactive_elicitation_answer`.

---

## 9. Acceptance Criteria

- [ ] **AC-01** — all flags documented: `lmcp inspect --help | grep -c -- '--json\|--script\|--record\|--diff\|--transcript\|--interactive\|--allow-exec'` → `7`
- [ ] **AC-02** — no orphaned client method: all 13 `_protocol.py` names appear in `cli/_inspect/_scenario.py` or `_repl.py` (AC-02 test)
- [ ] **AC-03** — schemas printed: `lmcp inspect examples/demo_server.py | grep -q inputSchema` → exit 0
- [ ] **AC-04** — raw envelope: `lmcp inspect … --call add --args '{"a":1,"b":2}' --raw | jq -e '.content[0].text == "3"'`; a server-sent `resultType` appears unchanged
- [ ] **AC-05** — versioned document: `… --json 2>/dev/null | jq -e '.schemaVersion == 1'` → exit 0
- [ ] **AC-06** — stdout is pure JSON: `… --json 2>/dev/null | python -c 'import json,sys; json.load(sys.stdin)'` → exit 0
- [ ] **AC-07** — passing scenario: `… --script scenarios/add.json; echo $?` → `0`
- [ ] **AC-08** — failing assertion: `… --script scenarios/add-bad.json 2>&1 | grep -q 'adds'` → exit 0, command exit `1`
- [ ] **AC-09** — command-bearing scenario refused: `… --script scenarios/evil.json; echo $?` → `2`, no process spawned
- [ ] **AC-10** — `file` target needs opt-in: `… --script scenarios/other-file.json; echo $?` → `3`; with `--allow-exec` → `0`
- [ ] **AC-11** — record then diff is clean: `… --record /tmp/s.lmcp.json --script scenarios/add.json && … --diff /tmp/s.lmcp.json` → `0`
- [ ] **AC-12** — both directions, redacted: `… --transcript 2>/dev/null | grep -c '"dir": "out"'` ≥ 2 and `… | grep -c '<redacted>'` ≥ 1
- [ ] **AC-13** — interactive answers reach the server: `printf ':call ask_name {}\n{"name":"Ada"}\n:quit\n' | lmcp inspect … --interactive --json | jq -e '.steps != null'`
- [ ] **AC-14** — `U-01` settled: `_research/inspector-surface.md` exists, one row per capability with a source line for Inspector 2.16.0; until then no document here asserts Inspector behaviour
- [ ] **AC-15** — no new dependency: `git diff --stat pyproject.toml` empty; `python -c "import lauren_mcp.cli._inspect"` works with only `[cli]`


---

## 10. Open Questions

| # | Question | Why it matters | How to settle |
|---|---|---|---|
| Q-1 | The Inspector's actual surface at 2.16.0? | `U-01`; §3 forbids assuming it, so no parity claim can be made or refuted | Read the 2.16.0 README and package layout; write `_research/inspector-surface.md`, one row per capability plus a source line (AC-14) |
| Q-2 | Does the client surface `resultType`? | 0 grep hits in `src/`, no field in `_types.py`; this PRD assumes `call_tool`'s untyped `Any` (`_protocol.py:57`) | Confirm at implementation; if `prd-result-envelope-caching.md` types results, `--raw` prints the typed model instead |
| Q-3 | Is `server_discover` `optional: true` by default? | Legacy servers lack `server/discover` (`spec.md:352`), so a mandatory step fails every pre-dual-era scenario | Yes while `prd-dual-era-protocol-core.md` is in flight; flip when the server implements it |


---

## 11. lauren-mcp Advantages

**One command, four transports.** The client speaks stdio, WebSocket, HTTP+SSE, and Streamable HTTP behind a
transport-agnostic protocol surface (`_factory.py:68,105,139,182`; `_protocol.py`), and `_make_remote_client`
(`_commands.py:170-177`) already routes a URL to the right one. So the same document, scenario, and transcript
work against a stdio subprocess, a WebSocket dev server, and a remote Streamable HTTP endpoint —
transport-complete by construction, which is why §4.1's table needs one column, not four.

**Tool and server share types.** `ToolSchema` / `ResourceSchema` / `PromptSchema` (`_types.py:280,406,475`)
are the dataclasses the server uses to publish tools, so the inspector prints the schema the server actually
emitted, with no re-serialisation to drift; when `prd-json-schema-2020-12.md` changes the emitted dialect,
the inspector follows for free. And it is Python: the command runs wherever the package is installed (`cli`
extra, `pyproject.toml:38-45`), including CI images with Python and nothing else, and the frame seam is a
`Callable` plus a `None` check — nothing in §5 adds a dependency, so `E-222` stays true.

Where an advantage is **not** claimed: interactivity quality, visual affordances, integration breadth. `U-01`
is open, so this PRD does not assert that a terminal beats a browser — only that it covers §4.1's workflows.

---

## 12. References

**Evidence (`EVIDENCE.md`)** — `E-165` Inspector **2.16.0** (`latest`, registry URL recorded there); `E-166`
Inspector has **2** OSV advisories (severity/affected ranges not recorded — do not over-read); `E-222` exactly
**two** runtime dependencies (`pyproject.toml:31-34`); `U-01` surface unenumerated (`:516`, known gap `:277`).

**Research** — `_research/spec.md` §7 (`:337-362`); modern-era changes (`:248-255`); `resultType` (`:255`,
`:314`); `server/discover` (`:352`); `subscriptions/listen` (`:353`); elicitation (`:355`); `roots/list`
(`:356`); sampling (`:357`); `tasks/*` (`:358`). `_research/lauren-mcp-inventory.md` §7 client API
(`:311-336`) and §10 CLI table (`:413-424`) — the brief cited "inventory §7" for the CLI; the CLI table is
§10, and both are cited with verified lines.

**This repository** (every line checked with `grep -n` / `sed -n`) — `cli/_commands.py:71,76,78,82,85,86,
89-91,93-97,99-109,110-111,119,165,170-177,260`; `cli/__init__.py:10,18-22`;
`_client/_factory.py:10,33,46-50,68,105,139,182`; `_client/_protocol.py:28,37,49,57,83,91,108,126,143,151,
176,184,206`; `_client/_features.py:94,104,122,132,267`; `_client/_base_remote.py:89,101,154,171`;
`_client/_ws.py:118`; `_client/_sse.py:146`; `_client/_streamable.py:140`; `_client/_stdio.py:285,293,313`;
`_types.py:280,312,406,475`; `pyproject.toml:31-34,38-45`; `docs/reference/cli.md:41-68,50`;
`tests/unit/test_cli_commands_coverage.py:386-398`; `.gitignore:70`.

**Sibling PRDs this one feeds** — `prd-cancellation-conformance.md` §8, `prd-result-envelope-caching.md`,
`prd-server-discover-request-meta.md`, `prd-subscriptions-listen.md`, `prd-mrtr-input-required.md`,
`prd-dual-era-protocol-core.md`, `prd-client-parity.md`.
