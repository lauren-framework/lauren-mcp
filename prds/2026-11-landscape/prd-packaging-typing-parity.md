# PRD — Packaging, typing and dependency-advice parity

**Status:** Draft
**Date:** 2026-11-26
**Scope:** `pyproject.toml`, `src/lauren_mcp/py.typed`, `src/lauren_mcp/**` (annotations), `CHANGELOG.md`, `README.md:84-95`, `docs/getting-started/installation.md`, `.github/workflows/tests.yml`, `noxfile.py`, `SECURITY.md` (new)
**Priority:** P3 — nothing here breaks a fielded client or a live handshake, but two extras defects turn a modern-era onboarding step into a dead end, and the competitive claim in §8 stays unverifiable until this ships.

---

## 1. Problem Statement

`lauren-mcp`'s differentiation is not a protocol feature. It is a **supply-chain shape**: two runtime
dependencies, a Python floor that matches the CI matrix exactly, an installed `py.typed`, and extras that
keep the core importable on a machine with no HTTP stack. The research for this series found three of
seven surveyed Python agent frameworks pinned to a superseded `mcp` SDK line, and 17 OSV advisories
against the upstream `mcp` package, 7 HIGH (E-105, E-106, E-109, E-160, E-168). "We do not depend on it"
is therefore both a compatibility claim and a security claim — **but only if our own metadata survives the
same scrutiny.** It does not, in five places, each read off this branch and confirmed with `grep -n`.

### 1.1 The metadata audit

| # | Field | Declared value | Line | Verdict |
|---|---|---|---|---|
| 1 | `requires-python` | `">=3.11"` | `11` | matches `noxfile.py:13` and `tests.yml:23` exactly (§4.4) |
| 2 | `keywords` | `lauren`, `mcp`, `model-context-protocol`, `ai`, `llm` | `13` | `mcp` is present, so PyPI search surfaces us on the same query as the SDK we don't depend on |
| 3 | `classifiers` | 12 entries: Beta (`15`), MIT (`17`), `Python :: 3`…`3.14` (`18`–`22`), two `Topic ::` (`23`–`24`), `Typing :: Typed` (`25`) | `14`–`26` | `Typing :: Typed` is a claim — §1.3 shows it is half-enforced |
| 4 | runtime deps | `lauren>=1.7.0`, `anyio>=4.0` | `27`–`30` | the asset itself (E-222) |
| 5 | extras | `ws`, `http`, `pydantic`, `msgspec`, `all`, `cli` | `32`–`45` | **two extras referenced by shipped code and docs do not exist** (§1.2) |
| 6 | wheel payload | `packages = ["src/lauren_mcp"]` (`61`); `artifacts` names `py.typed`, `llms-full.txt`, **`llms.txt`** (`62`) | | `src/lauren_mcp/llms.txt` does not exist (§1.3) |
| 7 | sdist | `include` (`72`–`75`) names `llms.txt`; `exclude` (`76`–`82`) drops `prds/`, `skills/`, `tests/`, `examples/`, `docs/`, `.github/` | | correct — this PRD is excluded from the shipped artifact |

The shape is right and the count is right. Every defect sits in the seam between what the metadata
promises and what the tree contains.

### 1.2 The extras users are told to install do not exist

`[project.optional-dependencies]` (`pyproject.toml:32`–`45`) declares `ws` (`33`), `http` (`34`),
`pydantic` (`35`), `msgspec` (`36`), `all` (`37`, self-referential: `["lauren-mcp[ws,http,pydantic,msgspec,cli]"]`)
and `cli` (`38`–`45`). There is **no `sse` extra and no `otel` extra**: `grep -rn "lauren-mcp\[sse\]" src/ | wc -l`
→ `12` (in `_factory`, `_sse`, `_oauth`, `_streamable`), `grep -rn "lauren-mcp\[otel\]" src/ | wc -l` → `1`.
The one that matters most is the *modern* transport (`_client/_streamable.py:60`–`62`):
`Install lauren-mcp[sse] to use Streamable HTTP MCP transport: pip install 'lauren-mcp[sse]'`;
`_module.py:558`–`560` adds `instrument_otel=True requires opentelemetry-api; install it with: pip install
'lauren-mcp[otel]'`, and `README.md:94` advertises that extra to every reader. From a clean venv,
`pip install 'lauren-mcp[sse]'` prints `WARNING: lauren-mcp 1.2.2 does not provide the extra 'sse'` and
exits 0; the import then fails with the message above. The install succeeds, the import fails, and the
error repeats the instruction that just silently did nothing — self-consistent, unescapable by following
it. Meanwhile `server/_builtin_resources.py:137` tells agents `pip install 'lauren-mcp[http]'`, the name
that exists, so the tree documents two answers for one transport. This is a **modern-era** problem:
Streamable HTTP is the transport the dual-era roadmap pushes new users toward
(prd-dual-era-protocol-core, prd-client-parity), and it already points at a non-existent extra.

### 1.3 PEP 561 is claimed and half-enforced

`py.typed` exists — verified, not assumed: `ls -la src/lauren_mcp/py.typed` →
`-rw-r--r-- 1 root root 0 Nov 26 19:32 src/lauren_mcp/py.typed`. Zero bytes (correct), listed in
`artifacts` (`pyproject.toml:62`), so it ships, and `Typing :: Typed` (`25`) is accurate. Better than
several peers. Three gaps sit behind it.

**(a) A dangling artifact.** The same `artifacts` list names `src/lauren_mcp/llms.txt`, which does not
exist (`llms-full.txt` does). Hatchling globs unmatched artifact paths away and the only build gate is
`twine check` — metadata, never wheel *contents* (`noxfile.py:278`) — so the wheel
ships without a file the manifest claims and the pipeline stays green.

**(b) The decorators erase the signature they annotate.** All four public decorators are annotated; all
four return `Callable[..., Any]`:

```python
# src/lauren_mcp/server/_decorators.py
736:def mcp_server(path: str, *, transport: str = "ws") -> Callable[[type], type]:
770:) -> Callable[[Callable[..., Any]], Callable[..., Any]]:   # mcp_tool (758)
882:) -> Callable[[Callable[..., Any]], Callable[..., Any]]:   # mcp_resource (874)
993:) -> Callable[[Callable[..., Any]], Callable[..., Any]]:   # mcp_prompt (988)
```

`_decorators.py:10` imports `from typing import TYPE_CHECKING, Any` and nothing else from `typing`;
there is no `TypeVar` (the tree's 33 `ParamSpec` hits are `HeaderParamSpec` and
`lauren.extractors._ParamSpec` identifiers). For a consumer, `reveal_type(add)` on a decorated
`def add(a: int, b: int) -> int` is `Callable[..., Any]`, so `add("x")` type-checks: the annotation covers
the *decorator's arguments* and is discarded for the user's function. A `py.typed` package that erases the
wrapped callable is typed in name only for its most-used API.

### 1.4 Five release tags, one changelog entry

`git tag` lists `v1.0.0 v1.1.0 v1.2.0 v1.2.1 v1.2.2`; `grep -n '^## ' CHANGELOG.md` returns only
`10:## [1.0.0] — 2026-06-14` and `213:## Historical phases`. Four releases have no heading anywhere,
everything after `1.0.0` lives under a development journal rather than a release log, and there is no
`## [Unreleased]`, so an in-flight change has no defined home. Users cannot answer "what changed in the
release I just upgraded to" — the question that matters most as the next `1.x` starts changing
legacy-path behaviour.

---

## 2. Goals

1. **Every install instruction resolves to a real extra**: zero `lauren-mcp[sse]`/`[otel]` in `src/`,
   `README.md`, `docs/`; one canonical name per capability, enforced by a test.
2. **Every optional-import failure is one sentence** naming capability, extra and fix — the existing
   `ws`/`http` pattern (E-223), applied uniformly, with the two missing extras added (§4.3).
3. **PEP 561 is a guarantee**: `py.typed` ships; the four decorators preserve the wrapped signature under
   `mypy --strict`; a consumer fixture in CI proves it (§4.2).
4. **Metadata and payload agree**: no `artifacts` entry naming a missing file; CI asserts wheel contents
   both ways (§4.4).
5. **A written dependency-advice policy** (supported majors, the rule for adding an upper bound, and
   the documented justification for *no* `anyio` upper bound today, §4.1) and a **changelog/versioning
   policy** separating additive modern-era support from legacy-path behaviour changes (§4.5).

### 2.1 Acceptance criteria

Each item is a command with an expected result; together they seed the CI jobs in §4.4.

- [ ] `grep -rn "lauren-mcp\[sse\]\|lauren-mcp\[otel\]" src/ README.md docs/ | wc -l` → `0` (currently `12 + 1 + 1`).
- [ ] `python -c "import tomllib;print(sorted(tomllib.load(open('pyproject.toml','rb'))['project']['optional-dependencies']))"` → `['all','cli','http','msgspec','otel','pydantic','sse','ws']` (`sse` only as a deprecated alias, §4.3).
- [ ] For every extra `X` in that list: `pip install --dry-run "lauren-mcp[$X]"` emits no `does not provide the extra`.
- [ ] `nox -s build` then `python -c "import zipfile,glob;z=zipfile.ZipFile(glob.glob('dist/lauren_mcp-*.whl')[0]);print([n for n in z.namelist() if 'py.typed' in n or 'llms' in n])"` → `lauren_mcp/py.typed` and `lauren_mcp/llms-full.txt`, no `llms.txt`.
- [ ] `grep -c "llms.txt" pyproject.toml` → `1` (sdist `include` only; today `62` and `73`).
- [ ] `mypy --strict tests/typing/test_public_api.py` → exit `0`, and `reveal_type(add)` there shows `def (a: int, b: int) -> int`.
- [ ] `grep -c "TypeVar" src/lauren_mcp/server/_decorators.py` → `≥ 1` (currently `0`).
- [ ] `grep -c '^## \[Unreleased\]' CHANGELOG.md` → `1`; `grep -c '^## \[1\.' CHANGELOG.md` → `5`.
- [ ] `test -f SECURITY.md` and it contains `anyio`, `lauren`, `mcp` and a 90-day disclosure window.
- [ ] `grep -rn "from mcp import\|mcp>=\|mcp==" pyproject.toml src/ | wc -l` → `0` (§4.6).
- [ ] `.github/workflows/tests.yml` has jobs `floor`, `ceiling`, `prerelease`, `extras`, `typing`, `wheel-contents`, all green on the PR branch.
- [ ] `README.md:86`–`95` and `docs/getting-started/installation.md:11`–`18` list the same extras in the same order (asserted by `tests/docs/test_reference_docs.py`).
- [ ] `grep -n 'lauren-mcp Advantages' prds/2026-11-landscape/prd-packaging-typing-parity.md` → hit (§8).

---

## 3. Non-Goals

* **No new runtime dependency.** `lauren` and `anyio` stay the only two; everything here is metadata,
  annotations, or documentation.
* **No optional `mcp` SDK adoption.** E-160 is the reason to stay off it; an extra would inherit the same
  advisories with worse visibility.
* **No upper bound added to `lauren`/`anyio` in this PRD.** §4.1 defines the *rule*; adding one now would
  reproduce mcp-use's failure mode (`mcp<2.0.0`, E-105).
* **No build-backend change** (hatchling + hatch-vcs works; reproducing version derivation is bigger than
  the defect).

---

## 4. Design

### 4.1 Dependency-advice policy

| Dependency | Lower bound | Upper bound today | Why | Verified by |
|---|---|---|---|---|
| `lauren` | `>=1.7.0` (`pyproject.toml:28`) | none | Same-org dependency, breaking changes visible to us first. Import surface is small and enumerable: `lauren`, `lauren.types`, `lauren.sse`, `lauren.decorators`, `lauren.exceptions`, `lauren.extractors`, `lauren.reflect`, plus lazy `lauren.LaurenFactory`/`lauren.module` in the CLI | new `floor` + `ceiling` jobs (§4.4) |
| `anyio` | `>=4.0` (`pyproject.toml:29`) | **none, deliberately** | One call site (below); a major bump can break one expression | `ceiling` + `prerelease` jobs |

**The fact that decides the `anyio` question.** The whole dependency is one lazily-imported call:

```python
# src/lauren_mcp/server/_handlers.py
132:                import anyio.to_thread  # noqa: PLC0415
135:                await anyio.to_thread.run_sync(lambda: _func(*_a, **_kw))  # noqa: B023
```

`grep -rn anyio --include=*.py src/ tests/` returns nothing else. Therefore:

1. **No upper bound is right today.** An `anyio` 5.0 could break one call signature, which one CI run
detects. An `anyio<5` bound protects us from nothing we cannot observe, while punishing users in shared
environments where Starlette, httpx or pytest-anyio require 5.x — the resolver backtracks on us, not on
them. Add it only when (a) 5.0 removes or re-signatures `to_thread.run_sync`, (b) usage grows past ~3 call
sites, or (c) `anyio` goes >12 months without a release while a HIGH advisory is open.
2. **`>=4.0` is stale, not wrong, and `lauren>=1.7.0` is untested.** Nothing at the call site needs 4.0,
but raising a floor narrows users' options, so it is a separate evidence-driven change. Worse: the
`lauren` floor is load-bearing and never exercised — `noxfile.py:30` syncs `--dev` and `noxfile.py:34`
syncs `--extra all`, both resolving *latest* `lauren`. A floor nobody runs is a guess.

**How an upper bound is decided** (verbatim in `docs/reference/compatibility.md`):

> We declare a lower bound on everything and an upper bound only when we cannot observe the dependency's
> next major. An upper bound is added in the same release that documents the reason, and the reason must
> be one of: (i) a known breaking change in the next major we cannot yet adapt to; (ii) the dependency is
> unmaintained and its next release is unknown; (iii) it is a transitive pin we do not control and must
> align with. An upper bound is never added to make a red CI matrix green, and never without a
> `floor`/`ceiling` pair showing which side we actually tested.

### 4.2 PEP 561 guarantees — what "typed" will mean

| Guarantee | Today | After |
|---|---|---|
| `py.typed` in repo | ✅ 0-byte `src/lauren_mcp/py.typed` | unchanged |
| `py.typed` in wheel | ✅ via `packages` (`61`)/`artifacts` (`62`) | asserted by `wheel-contents` job |
| Decorators preserve the wrapped signature | ❌ `Callable[..., Any]` (`770`, `882`, `993`) | ✅ `TypeVar`-bound |
| Consumer type-check of the installed wheel | ❌ nothing | ✅ `tests/typing/`, `mypy --strict` |
| No dangling artifact | ❌ `llms.txt` (`62`) | ✅ removed; repo-root `llms.txt` stays in sdist (`73`) |

Minimal fix, no new dependency:

```python
# src/lauren_mcp/server/_decorators.py
from typing import Any, Callable, TypeVar
_F = TypeVar("_F", bound=Callable[..., Any])

def mcp_tool(...) -> Callable[[_F], _F]:   # was Callable[[Callable[..., Any]], Callable[..., Any]]
```

`TypeVar` suffices because the decorators return `fn` unchanged; `ParamSpec` becomes necessary only if a
decorator starts returning a wrapper. 
### 4.3 Extras matrix — cost, guard, and the exact `ImportError` text

The rule we already follow (E-223): capability behind an extra, plus a one-sentence `ImportError` naming
the extra and the install command. Audit of its application:

| Extra | Direct requires (`pyproject.toml`) | Used by | Guard | Exact text today | Verdict |
|---|---|---|---|---|---|
| `ws` | `websockets>=12` (`33`) | WebSocket transport | `_client/_ws.py:59`–`63` | `Install lauren-mcp[ws] to use WebSocket MCP transport: …` | ✅ model |
| `http` | `httpx>=0.27`, `httpx-sse>=0.4` (`34`) | `HttpResource`; SSE + Streamable clients | `server/_builtin_resources.py:136`–`137` | `HttpResource requires httpx; install it with: pip install 'lauren-mcp[http]'` | ✅ name exists — the clients disagree |
| `sse` | **does not exist** | `_sse`, `_streamable`, `_oauth`, `_factory` | `_sse.py:71`–`73`; `_streamable.py:60`–`62`; `_oauth.py:105`–`107` | `Install lauren-mcp[sse] to use Streamable HTTP MCP transport: …` (full text at §1.2) | ❌ dead end |
| `pydantic` | `pydantic>=2.0` (`35`) | schema generation | `server/_schema.py:156`–`159` | *(none)* `logging.warning("Pydantic is not installed; emitting unconstrained …")` | ⚠️ silent degradation |
| `msgspec` | `msgspec>=0.18` (`36`) | schema generation | `server/_schema.py:39`–`42` | *(none)* flag `_MSGSPEC_AVAILABLE` | same |
| `cli` | 6 requires (`38`–`45`), with `websockets`, `httpx`, `httpx-sse` duplicated by hand | `lmcp` | `cli/_commands.py:210`–`213` | `Warning: python-dotenv not installed; --env-file ignored.` / `Install with: pip install 'lauren-mcp[cli]'` | ⚠️ warning not exception (defensible: the CLI must start) |
| `otel` | **does not exist** | `instrument_otel=True` | `server/_module.py:558`–`560` | `instrument_otel=True requires opentelemetry-api; install it with: pip install 'lauren-mcp[otel]'` | ❌ dead end, advertised at `README.md:94` |
| `all` | `lauren-mcp[ws,http,pydantic,msgspec,cli]` (`37`) | tests/CI (`noxfile.py:34`) | n/a | n/a | self-referential; must gain `otel` |

**Cost, honestly stated.** Cost is the direct-requirement count (column 2) plus resolver-collision
risk: `ws` adds 1 and no shared pins (lowest risk); `http` adds 2 and `httpx` is the most-pinned package
in the whole set, so it is the extra most likely to constrain a user's resolver; `pydantic`/`msgspec` add
1 each, are mutually exclusive in practice, and change only the generated `inputSchema` — neither is
needed to *serve*; `otel` adds 1 and costs nothing when the flag is false; `all` costs the union. `cli`
is the outlier at 6 and duplicates `websockets`/`httpx`/`httpx-sse` *by declaration* (`38`–`45`), so a
`ws` bump must be mirrored by hand — preferred form is `cli = ["lauren-mcp[ws,http]", "typer>=0.12",
"python-dotenv>=1.0", "uvicorn>=0.31"]`.

**Why `sse` is aliased, not added.** Two names already exist for one capability (`http` in metadata
and docs, `sse` in four modules), and a second real extra would make the matrix permanently ambiguous. So
`http` stays canonical; `sse = ["lauren-mcp[http]"]` ships as a **deprecated alias** so every message
`1.2.x` already printed starts working — which is why the fix can be a patch; all 12 message strings plus
the `_client/_streamable.py:45` docstring move to `[http]`; a test asserts `pip install --dry-run
'lauren-mcp[sse]'` emits no warning; and `[sse]` is removed at `2.0.0`, because removing a name users can
type is metadata-visible (§4.5).

**Uniform format**, enforced by a test over every `raise ImportError` in `src/`:
`{Capability} requires {extra}: pip install 'lauren-mcp[{extra}]'`. Outlier: `server/_openapi.py:48`–`49`
— `Reading YAML OpenAPI specs requires pyyaml: pip install pyyaml` — which bypasses extras and tells the
user to install an unpinned, untracked, untriageable dependency. `pyyaml` moves under `http` and the
message names the extra.

### 4.4 Supported versions and the CI matrix

Classifier ↔ `requires-python` ↔ nox ↔ CI all agree today (E-221):

| Python | Classifier | `requires-python` | `noxfile.py:13` | `tests.yml:23` | Runs |
|---|---|---|---|---|---|
| 3.11 | `19` | ✅ floor (`11`) | ✅ | ✅ | `tests_unit` |
| 3.12 | `20` | ✅ | ✅ (primary, `noxfile.py:12`) | ✅ | all jobs |
| 3.13 | `21` | ✅ | ✅ | ✅ | `tests_unit` |
| 3.14 | `22` | ✅ | ✅ | ✅ | `tests_unit` |

A floor that is *tested* on the floor is rarer than it should be, and the docs should say so. What is
missing is the dependency dimension:

| Job (new) | Matrix | Installs | Asserts |
|---|---|---|---|
| `floor` | py3.11 | `lauren==1.7.0`, `anyio==4.0` | unit suite passes → declared floors are real (§4.1) |
| `ceiling` | py3.14 | unpinned latest | unit suite passes → "no upper bound" is a tested claim |

| `prerelease` | py3.13 | `--pre` for both | non-blocking early warning — the substitute for an upper bound |
| `extras` | py3.12 | each extra in isolation + import probe | no `does not provide the extra`; each guard raises when its dep is absent |
| `typing` | py3.12 | wheel + `mypy --strict tests/typing/` | §4.2 holds for a consumer, not just for us |
| `wheel-contents` | py3.12 | `nox -s build` + zipfile assertions | `py.typed`, `llms-full.txt` in; `prds/`, `llms.txt` out |

The `extras` job would have caught §1.2 on the day it landed:

```

### 4.5 Changelog and versioning policy, tied to the protocol-era work

SemVer is claimed at `CHANGELOG.md:6`; it must now be read against the dual-era roadmap, because the next
releases add MCP `2025-11-25` behaviour beside the legacy `2024-11-05`…`2025-06-18` line
(`src/lauren_mcp/_mcp_version.py:5`–`7`).

| Change class | Examples | Bump |
|---|---|---|
| Additive modern-era support | new era value in `SUPPORTED`; optional capability on a negotiated `2025-11-25` session; new transport behind an existing extra | **minor** |
| Additive legacy-path support | decorator argument with a default; new client method; new extra | **minor** |
| Any behaviour change on the legacy path | different default `protocol_version`; changed error code for an existing failure; changed generated-schema *shape*; a legacy request that now negotiates differently | **major** |
| Metadata-visible removal | dropping an extra (`[sse]`), raising `requires-python`, renaming a console script, raising a floor | **major** |
| Packaging bug fix | adding `otel`; removing the dangling `llms.txt` artifact; correcting an install instruction | **patch** |
| Security fix | per §4.6 | **patch** + advisory |

Mechanically: `## [Unreleased]` becomes the first heading, with Keep-a-Changelog subsections (`Added`,
`Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`), empty ones omitted; the four missing release
headings are reconstructed from `git log` once, marked as reconstructed; and `Release`
(`.github/workflows/release.yml:44`–`49`) gains a guard that fails before upload unless the released tag
has a `## [x.y.z]` heading and `[Unreleased]` is empty. The Beta → Stable classifier move
(`pyproject.toml:15`) rides `2.0.0`, with the `[sse]` removal.

### 4.6 Vulnerability-response policy

The repo has no direct `mcp` dependency, so it inherits none of E-160's 17 advisories. That must be
*demonstrable*: `grep -rn "from mcp import\|mcp>=\|mcp==" pyproject.toml src/` → `0` hits outside the
`lauren_mcp` package name and `_mcp_version.py` constants.

A new `SECURITY.md` (~1 page) will state:

1. **Scope and reachability map** — the §4.1 table: `anyio` → `_handlers.py:132,135`; `lauren` → the
   enumerated import surface. In scope if reachable through those paths.
2. **No `mcp` dependency, by design**, citing E-160 (17 advisories, 7 HIGH): a caller who also installs
   `mcp` owns that surface, not us. This is the security half of §8 and belongs in the repo.
3. **Triage SLA** — advisory against `lauren`/`anyio`: triage within 5 business days → reachable? → fixed
   version available? If yes, cut a patch raising the floor; if no, publish a mitigation under
   `CHANGELOG.md` `Security` and add an upper bound **using the §4.1 rule** (a security fix is exactly
   case (i): a known break we cannot absorb).
4. **Disclosure** — private contact → 90 days or a coordinated advisory; CVE via GitHub Security
   Advisories for HIGH and above.

---


## 5. Exact Lines to Change

### 5.1 `pyproject.toml`

| Line(s) | Change |
|---|---|
| `10` | `license = "MIT"` + `license-files = ["LICENSE"]` (PEP 639 form) |
| after `36` | add `otel = ["opentelemetry-api>=1.27"]` and `sse = ["lauren-mcp[http]"]` |
| `37` | `all = ["lauren-mcp[ws,http,pydantic,msgspec,cli,otel]"]` |
| `38`–`45` | `cli = ["lauren-mcp[ws,http]", "typer>=0.12", "python-dotenv>=1.0", "uvicorn>=0.31", "pyyaml>=6"]` |
| `62` | drop `"src/lauren_mcp/llms.txt"` from `artifacts` |
| `119` | keep `ignore_missing_imports = true`; documented limit in §4.2 |

### 5.2 Source

| File:line | Change |
|---|---|
| `server/_decorators.py:10` | `from typing import TYPE_CHECKING, Any, Callable, TypeVar`; add `_F = TypeVar("_F", bound=Callable[..., Any])` |
| `server/_decorators.py:770`, `882`, `993` | return `Callable[[_F], _F]` |
| `_client/_sse.py:71`–`73`; `_streamable.py:43`–`45`, `60`–`62`; `_oauth.py:105`–`107`; `_factory.py:18`–`21` | `[sse]` → `[http]` |
| `server/_module.py:558`–`560` | message already names `[otel]`; only the extra needs adding |

### 5.3 Docs and CI

| File:line | Change |
|---|---|
| `.github/workflows/tests.yml:22`–`23` | keep the 4-version matrix; add the six §4.4 jobs |

| `.github/workflows/release.yml:44`–`49` | add the changelog-heading guard (§4.5) |


---

## 6. Backward Compatibility

**No runtime behaviour changes.** The decorators keep returning `fn`; the `TypeVar` only narrows the
static return type, which *widens* the set of accepted programs. Extras additions are additive metadata,
and the `sse` alias makes previously-broken installs work rather than changing working ones. Removing
`llms.txt` from `artifacts` removes a file that was never in the wheel.

Migration notes for users: **none required.** The only user-visible change lands at `2.0.0`, when `[sse]`
is removed — and the replacement message names `[http]`. For maintainers: `build_check` alone is
insufficient (add `wheel_check`); a release tag now requires a changelog heading; a new extra cannot land
without a guard message and a test.


---

## 7. Test Plan

| File | Cases |
|---|---|
| `tests/packaging/test_extra_names.py` (new) | every `lauren-mcp[...]` in `src/` is a declared extra; `all` covers every non-deprecated extra; `sse` aliases `http` and `all` excludes it |
| `tests/packaging/test_wheel_contents.py` (new) | build once; `py.typed` + `llms-full.txt` present, `llms.txt` absent, no `prds/` or `tests/` paths |
| `tests/packaging/test_metadata.py` (new) | `requires-python` floor == `min(SUPPORTED_PYTHONS)`; classifiers == `SUPPORTED_PYTHONS`; `Typing :: Typed` iff `py.typed` exists |
| `tests/packaging/test_extras_guards.py` (new) | monkeypatch each `_X_AVAILABLE` flag to `False`; the `ImportError` matches `requires .+: pip install 'lauren-mcp\[[a-z]+\]'` |
| `tests/typing/test_public_api.py` (new) | `mypy --strict` consumer fixture; `reveal_type` on all four decorators preserves the wrapped signature |


All of these are metadata, text and static-analysis assertions: no network, no host, cheap in CI.

---


## 8. lauren-mcp Advantages

**Two runtime dependencies, both observable.** `lauren>=1.7.0` and `anyio>=4.0` (`pyproject.toml:27`–`30`),
with the entire `anyio` usage at one call site (`_handlers.py:132,135`) and `lauren` confined to seven
importable modules. The field: **mcp-use** pins `mcp<2.0.0,>=1.24.0` and is stranded on a superseded SDK
line (E-105); **mcp-agent** pins `mcp>=1.20.0` with nothing published since 2025-12-05 (E-106);
**smolagents** leaves `mcp` unpinned and inherits whatever the resolver picks (E-109). All three carry the
upstream advisory surface — 17 OSV advisories, 7 HIGH (E-160) — with CVE-2025-6514 (`mcp-remote`,
CRITICAL, untrusted-server command injection reaching RCE) as the concrete worst case (E-168). We carry
none of it, and §4.6 makes that checkable rather than rhetorical.

**An extras design that keeps the core importable.** A machine with no HTTP stack can `import lauren_mcp`
and serve over stdio; nothing in the core pulls `httpx`, `websockets`, `pydantic`, `msgspec`, `typer` or
`opentelemetry`. The `ws`/`http` guard messages (E-223) are a pattern most frameworks do not bother with;
this PRD makes them uniform and complete rather than abandoning the approach.

**A Python range tested on both ends, and `py.typed` actually shipped.** 3.11–3.14 appears in classifiers
(`19`–`22`), `requires-python` (`11`), `noxfile.py:13` and `tests.yml:23` — four declarations that agree —
and the marker is in the tree *and* the wheel `artifacts` (`62`), so `Typing :: Typed` is honest. §4.2
turns "we ship types" into "we ship types that survive a strict consumer".

Where we are *not* ahead, plainly: no changelog for four of five releases, no `SECURITY.md`, two install
instructions that cannot work, no published bound policy. Each is cheap to fix and none is fixed by adding
a feature — which is why this PRD is P3 in effort, not in value.

## 9. References

* `prds/2026-11-landscape/EVIDENCE.md` — E-105, E-106, E-109 (competitor SDK pins), E-160 (17 OSV
  advisories against Python `mcp`), E-168 (CVE-2025-6514), E-221 (`requires-python`), E-222 (two runtime
  dependencies), E-223 (extras set), E-224 (console script).
  *Anchor drift noted:* E-222 cites `pyproject.toml:31-34` and E-223 cites `36-44`; verified anchors on
  this branch are `27`–`30` and `32`–`45`. E-221 (`:11`) is correct. This PRD uses verified numbers;
  `_research/` is read-only here.
* `prds/prd-protocol-version-negotiation.md` — structural model. Sibling PRDs:
  `prd-dual-era-protocol-core.md`, `prd-client-parity.md`, `prd-cancellation-conformance.md`.
* Specs: PEP 561, PEP 621, PEP 639, PEP 440; Keep a Changelog 1.1.0; Semantic Versioning 2.0.0.
