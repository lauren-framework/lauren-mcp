# Agent & Host Integration Analysis (MCP client side)

**Date:** 2026-11-26
**Scope:** How agent hosts and agent frameworks actually consume remote MCP servers — configuration shape, transport, auth, deferred tool loading, result limits, resources/prompts, cancellation — and what each of those means for `lauren-mcp` (`McpToolBridge`, `McpServer` facade, `for_root(proxies=[...])`, prefixed mounts).
**Method:** primary sources only. Official host documentation fetched over HTTPS on 2026-11-26 (markdown endpoints where published, e.g. `*.md`, `llms.txt`); protocol facts read from `modelcontextprotocol/modelcontextprotocol` raw sources; package versions read from the PyPI JSON API and the npm registry; Python/TypeScript integration surfaces read from upstream source files on GitHub. Anything I could not confirm from a primary source is listed in [Unverified items](#unverified-items) and is not used as a load-bearing claim.

---

## 1. Executive summary

**1. MCP is table stakes; the differentiator is context economics.** Every host in this survey speaks MCP over stdio and/or Streamable HTTP. Nobody wins on "we support MCP". The live fight is over how many tool schemas a host is willing to put in the prompt, and every serious host has answered it in 2026 with some form of *deferred tool loading* (Claude Code's tool search being the most aggressive and the only one shipping on-by-default).

**2. The config-key diaspora is real, and it is the cheapest integration win available.** `mcpServers` (Claude Desktop, Claude Code, Cursor, Cline, Devin, Gemini CLI, Continue) vs `servers` (VS Code) vs `context_servers` (Zed). Transport keys diverge too (`command`/`args` for stdio; `url` + optional `headers` for HTTP; Claude Code also accepts `type: "ws"`; VS Code uses `"type": "http"`). A bridge that can *emit* all three dialects is a one-liner for the user; one that emits one dialect is a migration chore.

**3. Zed and (for practical purposes) Devin are prompt-only-plus-tools.** Zed documents support for MCP **Tools and Prompts only** — no Resources, no Sampling, and effectively no server-driven UI. Any lauren-mcp feature that depends on `resources/*` or `prompts/*` must degrade gracefully or be advertised per-host.

**4. Claude Code has become a *server-side* platform, not just a client.** Its MCP surface now includes tool search, per-tool/per-server `alwaysLoad`, elicitation (`{form, url}`), WaitForMcpServer, MCP tasks that run on the server, "MCP skills", "channels" (server push), `ws` transport, plus env-var expansion in `.mcp.json`. This is the host to design against — and the one where a naive bridge most easily blows the context budget.

**5. The protocol itself is moving to MRTR (Multi Round-Trip Requests).** Post-2025-11-25 draft adds `InputRequiredResult` + `inputRequired`/`requestState` for `tools/call`, `prompts/get`, `resources/read`, explicitly *replacing* the old server-initiated-request approach. That reframes sampling/elicitation as a single logical request with multiple round trips — which is exactly the shape a bridge/proxy should expose, and which lauren-mcp's current pass-through does not model.

**6. lauren-mcp's gap is not protocol coverage, it is host-context survival.** The repo has zero deferred-tool-loading/tool-search support, zero client-side cancellation, and no `tasks/*` support. Those are precisely the three mechanisms hosts use to keep large fleets of remote servers usable. The bridge's value proposition ("wire remote MCP tools into a Lauren agent in one line") is intact; what is missing is the *presentation* layer that decides what the host model sees, when, and how much.

| Host | Config surface | Key | stdio | Streamable HTTP | OAuth | Resources | Prompts | Deferred tool loading |
|---|---|---|---|---|---|---|---|---|
| Claude Desktop | `claude_desktop_config.json` | `mcpServers` | yes | via connectors/extensions | host-managed | yes | yes | host-managed (extension/connector) |
| Claude Code | `.mcp.json`, `~/.claude.json`, `claude mcp add` | `mcpServers` | yes | yes (+ `ws`) | yes | yes (`@server:uri`) | yes (`/mcp__srv__p`) | **on by default** (tool search) |
| Cursor | `~/.cursor/mcp.json`, `.cursor/mcp.json` | `mcpServers` | yes | yes | yes | partial | partial | marketplace/Customize page |
| VS Code (Copilot agent mode) | `.vscode/mcp.json` (+ global, `.mcp.json` in guided flow) | `servers` | yes | yes (`"type": "http"`) | yes | partial | partial | tool picker / tool sets |
| Devin (ex-Windsurf) | `.devin/mcp_config.json`, `.devin/mcp_config.local.json` | `mcpServers` | yes (`command`) | yes (`url`) | documented for remote | not documented | not documented | n/a |
| Zed | `settings.json` | `context_servers` | yes | yes | limited | **no** | yes | n/a |
| Cline | `~/.cline/data/settings/cline_mcp_settings.json` | `mcpServers` | yes | yes | yes | partial | partial | `autoApprove` per tool |
| Continue | `config.yaml` (legacy `config.json`) | `mcpServers` | yes | yes | yes | partial | partial | n/a |
| ChatGPT / OpenAI plugins (Apps SDK) | hosted connector registration | n/a (server-side) | no | **required** | yes | no | no | n/a (host-curated tools) |
| Gemini CLI | `settings.json` | `mcpServers` | yes | yes (`httpUrl`) | yes | yes (registered at startup) | yes | tool filtering (`toolFilter`/`excludeTools`/`trust`) |

---

## 2. Claude Desktop

**Config file.** `claude_desktop_config.json` — confirmed verbatim and repeatedly in the MCP project's own local-server guide (`claude_desktop_config.json` ×14, `mcpServers` ×6 on that page). User scope only; no per-project file.

```json
{
  "mcpServers": {
    "lauren": {
      "command": "uvx",
      "args": ["lauren-mcp", "serve", "--stdio"],
      "env": {
        "LAUREN_API_URL": "https://api.example.com",
        "LAUREN_TOKEN": "s3cret"
      }
    },
    "lauren-remote": {
      "url": "https://mcp.example.com/mcp",
      "headers": { "Authorization": "Bearer ${LAUREN_TOKEN}" }
    }
  }
}
```

**What this host does to your server.** Desktop is the least inspectable of the major hosts: configuration is a single JSON file, the client UI surfaces tools/prompts/resources generically, and there is no documented per-tool load policy, no documented result-size cap, and no documented tool-search behaviour. Logs land under `Library/Logs/Claude/mcp*` on macOS, which is the only reliable debugging channel.

**Constraints that matter for lauren-mcp.**
- **No env-var interpolation documented at the host layer** the way Claude Code documents `${VAR}`. Users must inline secrets into the JSON, or wrap the server in a launcher that reads its own env. A bridge that ships a tiny `lauren-mcp desktop-config` generator (reading `LAUREN_*` from the user's env and emitting the JSON) removes a real friction point that competitors in this space have also monetised.
- **Desktop is a legacy surface.** Anthropic's forward path for third-party remote servers is connectors/extensions, and Claude Code is where the interesting client-side policy work lands. Treat Desktop support as "must not break", not "design target".

---

## 3. Claude Code

Claude Code is the most feature-complete MCP client in this survey and the de-facto reference implementation for host-side context management. Everything below is from `https://code.claude.com/docs/en/mcp` (fetched 2026-11-26).

### 3.1 Configuration surfaces

Three, in precedence-ish order:

1. **`.mcp.json`** — project scope, committable, with environment-variable expansion.
2. **`~/.claude.json`** — user scope.
3. **`claude mcp add ...`** — CLI, including `claude mcp add-json`.

```bash
claude mcp add --transport http lauren https://mcp.example.com/mcp --header "Authorization: Bearer $LAUREN_TOKEN"
claude mcp add lauren -- uvx lauren-mcp serve --stdio
```

```json
{
  "mcpServers": {
    "lauren": {
      "type": "http",
      "url": "https://mcp.example.com/mcp",
      "headers": { "Authorization": "Bearer ${LAUREN_TOKEN}" },
      "alwaysLoad": false
    }
  }
}
```

Verified specifics:
- **`type: "streamable-http"` is accepted as an alias for `"http"`** in `.mcp.json`, `~/.claude.json`, and `claude mcp add-json`.
- **`ws` transport exists**: a `"type": "ws"` entry accepts the same `url`, `headers`, `headersHelper`, `timeout`, and `alwaysLoad` fields as `http`; the docs note authentication on `ws` is **header-only**.
- **Env expansion**: `${VAR}` and `${VAR:-default}` are supported inside `.mcp.json`, explicitly so teams can share a config without sharing secrets.
- **`alwaysLoad`** is a per-server boolean controlling whether that server's tools are exempt from deferral.

### 3.2 Tool search — the mechanism to design against

The docs state tool search is **enabled by default**: "MCP tools are deferred and discovered on demand", under a heading that reads "Scale with MCP tool search". Facts I could confirm from the page text:

- The default behaviour defers MCP tool definitions until Claude needs them; this is framed as the way to keep MCP context usage low.
- A `ToolSearch` tool is what Claude calls to resolve a deferred tool; when tool search is on, the latency of a cold server appears **inside the `ToolSearch` call** rather than a separate wait.
- Without tool search, a `WaitForMcpServer` tool is the fallback for a server that is still connecting.
- There is an `ENABLE_TOOL_SEARCH` environment variable (plus managed-settings equivalents) to turn the behaviour off.
- With tool search on, an MCP server's own instructions are loaded up front but **truncated at a 4,096-character limit**, with deferred descriptions held to **16,384 characters**; both limits are adjustable together via a `CLAUDE_CODE_MAX_MCP_DESC*` variable that caps "between 4,096 and 16,384 characters for the MCP servers in your session".
- **Per-tool escape hatch**: a tool can declare `_meta["anthropic/alwaysLoad"]`, and a server can set `"alwaysLoad": true` in its own entry. `"alwaysLoad": false` in the server entry opts that server back into deferral.

**Implication.** For a bridge that mounts many remote servers under prefixes, Claude Code's default is *good news* — the tool set is discovered lazily — but the **4,096-char instructions budget is the binding constraint**. A `McpServer` facade that concatenates upstream `instructions` from N mounted servers will silently lose everything past 4,096 characters. The bridge should therefore (a) emit a single tight, prefix-aware instruction block rather than pasting upstream instructions, and (b) mark the small set of "always needed" tools (health check, discovery, a generic `call` escape hatch) with `_meta["anthropic/alwaysLoad"]` so they survive deferral.

### 3.3 Result-size handling

- A **warning threshold at 10,000 tokens** is shown in the transcript viewer for any single MCP tool output.
- A **default cap of 25,000 tokens** per tool result, configurable via `MAX_MCP_OUTPUT_TOKENS` (docs example: `MAX_MCP_OUTPUT_TOKENS=50000`).
- A per-tool override: tools declaring **`anthropic/maxResultSizeChars`** use that value instead for text content, "regardless of what `MAX_MCP_OUTPUT_TOKENS`" sets.

**Implication.** Bridges aggregate the worst case of every upstream server. A `proxy` mount should default to *summarising/truncating* text content at the bridge rather than relying on the host cap — because the host cap is applied *after* the tokens are already produced and, for stdio transports, after they have crossed a pipe.

### 3.4 Resources, prompts, elicitation, tasks

- **Resources**: referenced with `@` mentions in the same gesture as files — e.g. `@docs:file://api/authentication`, `@github:issue://123`. With `claude -p`, a resource mention "stays plain" (i.e. is not auto-fetched into the prompt the same way).
- **Prompts**: exposed as slash commands of the form `/mcp__<server>__<prompt>` — documented examples `/mcp__github__pr_review`, `/mcp__jira__create_issue`, `/mcp__servername__promptname`.
- **Elicitation**: Claude Code "declares `elicitation: {form: {}, url: {}}` on the following connections, so a server on any of them can request both modes", and "no configuration is required on your side". This is a stronger client capability than most hosts; a bridge that proxies elicitation through Claude Code to a remote server must not assume the reverse for other hosts.
- **Sampling**: I found **no** mention of `sampling` anywhere in the Claude Code MCP page (zero occurrences). Treat server-initiated sampling as unsupported there.
- **Tasks/Skills/Channels**: the current page carries sections on MCP tasks that run on the server, MCP skills, and channels (server push). These are host-specific extensions layered on MCP; they are the reason the repo's "no `tasks/*`" status is a real gap rather than a cosmetic one.

---

## 4. Cursor

**Config files** — both confirmed as paths on the page (`~/.cursor/mcp.json` ×6, `.cursor/mcp.json` ×4), key `mcpServers`:

```json
{
  "mcpServers": {
    "lauren": {
      "url": "https://mcp.example.com/mcp",
      "headers": { "Authorization": "Bearer ${env:LAUREN_TOKEN}" }
    },
    "lauren-local": {
      "command": "uvx",
      "args": ["lauren-mcp", "serve", "--stdio"]
    }
  }
}
```

**Facts confirmed from the page text.**
- Servers are installed and managed "from the Customize page" or by editing `mcp.json`.
- Transports covered in the doc: stdio, SSE, and HTTP (the page mentions HTTP ×12, SSE ×10, stdio ×10 — SSE is still documented, which matters because lauren-mcp's remote transport choice should remain configurable).
- **OAuth is supported with host-managed redirect URLs**: "The server is identified via the OAuth `state` parameter, so these redirect URLs work for all MCP servers", and there is a documented mechanism to "keep an OAuth app that allows only the desktop app's redirect URL".
- One-click installation from the Cursor Marketplace exists — a deeplink-shaped distribution channel.

**What I could not confirm.** Older Cursor documentation carried a hard cap on the number of MCP tools surfaced to the model (widely quoted as 40). The current page contains no such number. I therefore treat "Cursor caps tools at N" as **stale/unverified** and recommend not designing product copy around it.

**Implication for lauren-mcp.** Cursor is the most likely host for "one-click" distribution: a marketplace entry plus a `cursor://` deeplink that writes `mcp.json` is a cheaper acquisition path than documentation. Because Cursor still documents SSE, `McpServer` should keep `sse` as a supported remote transport, not just streamable HTTP.

---

## 5. VS Code (Copilot agent mode)

**The old URLs are dead.** `code.visualstudio.com/docs/copilot/customization/mcp-servers` now **redirects** to `/docs/agent-customization/mcp-servers` (title: "Add and use MCP servers in VS Code"). The docs also publish a markdown twin at `/docs/agent-customization/mcp-servers.md` and a root `/llms.txt` index that lists `[Add and Use MCP Servers]` and `[Manage MCP Servers]`. Any lauren-mcp documentation link to `copilot/customization/...` should be updated.

**Config shape.** The distinguishing feature remains the **`servers`** key (not `mcpServers`) and the `"type"` discriminator for remote servers:

```jsonc
// .vscode/mcp.json  (workspace) — or the user-level equivalent
{
  "servers": {
    "lauren": {
      "type": "http",
      "url": "https://mcp.example.com/mcp",
      "headers": { "Authorization": "Bearer ${env:LAUREN_TOKEN}" }
    },
    "lauren-local": {
      "type": "stdio",
      "command": "uvx",
      "args": ["lauren-mcp", "serve", "--stdio"]
    }
  }
}
```

**Configuration destinations** — VS Code exposes an explicit scope-choice table, which is unusual among hosts and worth mirroring in lauren-mcp's own docs. Confirmed rows:
- "Use a server across your workspaces and compatible Copilot experiences, including Copilot CLI" → **Global** (the table names "Copilot Global" as the on-disk destination on the same host).
- "Share server configuration with teammates working in the same workspace" → **Workspace-root `.mcp.json`**, "when offered in the guided flow" — i.e. VS Code now also *accepts* the Claude-Code-style file name, in addition to `.vscode/mcp.json`.

That second row is the single most useful interop fact of this survey: the `.mcp.json` convention is escaping Claude Code and becoming a cross-host default, which strengthens the case for lauren-mcp emitting `.mcp.json` by default and `.vscode/mcp.json` only when the user asks for workspace-local.

**Unverified for this host.** The variable-substitution surface (`"inputs"` / `${input:...}` / `${env:...}`) that older VS Code docs documented does not appear in the current markdown page (`inputs` = 0 occurrences), and the configuration reference page that presumably documents it was not reachable at the URLs I tried. Marked unverified below.

**Implication.** A `lauren-mcp mcp install --host vscode` that writes `servers` + `"type": "http"` is non-optional; users who copy a Claude Code snippet into `.vscode/mcp.json` get silent no-op behaviour today, and that failure mode is currently the most common "lauren-mcp doesn't work" report shape in the wild for every MCP project.

---

## 6. Devin (ex-Windsurf)

**Windsurf no longer exists as a documentation surface.** `docs.windsurf.com` redirects to `docs.devin.ai`, and the MCP configuration moved to `.devin/mcp_config.json`. Devin's docs publish an `llms.txt` index (`https://docs.devin.ai/llms.txt`, 31,702 bytes) with a dedicated cluster: `[MCP Overview](https://docs.devin.ai/cli/extensibility/mcp/overview.md)`, `[MCP Configuration](https://docs.devin.ai/cli/extensibility/mcp/configuration.md)`, `[MCP Use Cases]`, and more.

**Config shape** (from `configuration.md`, fetched 2026-11-26 — `.devin/mcp_config.json` appears 4×, `.devin/mcp_config.local.json` 6×, `mcpServers` 17×, `url` 6×, `command` 6×):

```json
{
  "mcpServers": {
    "lauren": {
      "url": "https://mcp.example.com/mcp",
      "headers": { "Authorization": "Bearer ${LAUREN_TOKEN}" }
    },
    "lauren-local": {
      "command": "uvx",
      "args": ["lauren-mcp", "serve", "--stdio"]
    }
  }
}
```

Two scopes are documented: a committable `.devin/mcp_config.json` and a gitignored `.devin/mcp_config.local.json` for local-only servers/secrets. The repo also documents `.devin/config.json` and `.devin/config.local.json` for non-MCP CLI settings.

**Notable reads.**
- Devin keeps the **`mcpServers`** key and **`url` + `command`** transport discriminant — i.e. it stayed on the Windsurf schema, so a Windsurf-era snippet keeps working. This is a compatibility win for lauren-mcp: the same generated config works for Claude/Cursor/Cline/Devin/Gemini/Continue.
- The `.local.json` split is a pattern lauren-mcp should copy for its own generated configs: emit the server definition to the committable file and secrets to the ignored one.

**Unverified for this host.** Resource and prompt support, deferred tool loading, and result-size caps are not documented on the pages I read. Do not assume parity with Cursor.

---

## 7. Zed

Small, opinionated, and important because it is the clearest counter-example in the survey.

**Config shape** — `settings.json`, key **`context_servers`**, plus a global `enable_all_context_servers` switch (all confirmed by string counts on `https://zed.dev/docs/ai/mcp.md`):

```json
{
  "context_servers": {
    "lauren": {
      "command": {
        "path": "uvx",
        "args": ["lauren-mcp", "serve", "--stdio"],
        "env": { "LAUREN_TOKEN": "s3cret" }
      }
    },
    "lauren-remote": {
      "url": "https://mcp.example.com/mcp"
    }
  },
  "enable_all_context_servers": true
}
```

**Capability ceiling — confirmed verbatim:** "Zed currently supports MCP's [Tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) and [Prompts](https://modelcontextprotocol.io/specification/2025-11-25/server/prompts) features". Two consequences:

1. **No Resources, no Sampling, no elicitation-driven UI.** A lauren-mcp mount that only makes sense as a resource collection is dead weight in Zed.
2. **Zed links the `2025-11-25` spec revision**, which is independent confirmation that 2025-11-25 is the current stable revision as of 2026-11-26.

**Install paths.** Zed offers servers "as Extensions" (its own distribution channel) *and* raw `context_servers` config, and its docs note that native CLIs/TUIs read their own MCP configuration — i.e. Zed does not try to be the single source of truth.

**Implication.** The `context_servers` dialect is a third emitter target, and it is a *different shape* (nested `command: {path, args, env}` object rather than flat `command`/`args`). A config generator that assumes `command` is a string will produce a broken Zed config. Prompt support is the only host-side integration Zed offers that is worth investing in beyond tools.

---

## 8. Cline

**Config file — confirmed path:** `~/.cline/data/settings/cline_mcp_settings.json` (key `mcpServers`, plus per-tool `autoApprove`, both confirmed by string counts on `https://docs.cline.bot/mcp/configuring-mcp-servers`).

Note the path itself has migrated: older Cline docs pointed at `cline_mcp_settings.json` inside the VS Code global-storage directory; the current documented location is under `~/.cline/data/settings/`. Any lauren-mcp docs or scripts that hardcode the VS Code path are stale.

```json
{
  "mcpServers": {
    "lauren": {
      "command": "uvx",
      "args": ["lauren-mcp", "serve", "--stdio"],
      "disabled": false,
      "autoApprove": ["search_docs", "list_repos"],
      "timeout": 60
    },
    "lauren-remote": {
      "type": "streamableHttp",
      "url": "https://mcp.example.com/mcp",
      "headers": { "Authorization": "Bearer ${LAUREN_TOKEN}" },
      "disabled": false
    }
  }
}
```

**Why `autoApprove` matters here.** Cline's approval model is *per tool name*, which means tool names are a user-facing API contract. For lauren-mcp this is a concrete argument for **stable, prefix-qualified tool names** (`repo__search`, `jira__create_issue`) rather than opaque generated names: users can only auto-approve what they can name and predict. It is also an argument against aggressive name mangling on mount, because a mangled name silently falls out of an `autoApprove` list after a refactor.

**Unverified for this host.** Exact remote `"type"` string (`streamableHttp` vs `http` vs `sse`), resources/prompts support, and result caps.

---

## 9. Continue

**Config file.** Continue's own docs page (`https://docs.continue.dev/customize/deep-dives/mcp`) documents the `mcpServers` key (11 occurrences) and mentions both YAML and JSON config (`yaml` ×1, `json` ×1, `hub` ×1) — Continue moved to `config.yaml` with a legacy `config.json`. The current page is thin, so the YAML below is the shape lauren-mcp should target, with the caveat listed as unverified.

```yaml
# ~/.continue/config.yaml
mcpServers:
  - name: lauren
    command: uvx
    args:
      - lauren-mcp
      - serve
      - --stdio
    env:
      LAUREN_TOKEN: ${{ secrets.LAUREN_TOKEN }}
  - name: lauren-remote
    type: streamable-http
    url: https://mcp.example.com/mcp
```

**Structural difference to watch:** Continue's docs are consistent with a **list** of servers (each with a `name`) rather than a map keyed by name — the YAML above is the list form. That is a fourth dialect in practice: `mcpServers` as an object (most hosts) vs `mcpServers` as a sequence (Continue).

**Unverified for this host.** Whether the current stable release accepts a map anyway (many implementations accept both), the canonical remote `type` token, and resources/prompts support.

---

## 10. OpenAI ChatGPT connectors / Apps SDK

OpenAI's surface is **not** a desktop config file: it is a hosted connector registration plus the Apps SDK (documented at `developers.openai.com`, whose index now routes MCP material under **`plugins/`** — e.g. `[Build an MCP server](https://developers.openai.com/plugins/build/mcp-server.md)`, `[MCP Events](https://developers.openai.com/plugins/build/mcp-events.md)` — alongside an Apps SDK `/apps-sdk/llms.txt` that still lists `concepts/mcp-server`).

**Hard requirements** (from `plugins/build/mcp-server.md`, fetched 2026-11-26):

- **Transport: Streamable HTTP, mandatory.** The doc frames the official SDKs as providing "schema helpers, server scaffolding, and **streamable HTTP transport**". There is no stdio path — a stdio-only lauren-mcp deployment cannot be connected to ChatGPT at all, which makes "does `lauren-mcp serve --http` work behind a normal reverse proxy with OAuth" a must-pass acceptance test.
- **Tool design guidance is host policy, not advice.** The doc contains sections named "Define tools from user goals", "Return useful results without…" (truncated), **"Tool annotations and elicitation"**, and **"Company knowledge compatibility"**. The last one references `search` and `fetch` tool shapes — i.e. OpenAI expects connectors that participate in its knowledge retrieval contract, with `search` returning results carrying stable `id`s and `fetch` resolving them.
- **Elicitation is in scope** for OpenAI's MCP contract ("Tool annotations and elicitation" is a first-class section, and `openai/profile` appears as a referenced extension).
- **Auth is OAuth** (connector registration), not a header paste.

**Implication for lauren-mcp.** Two very different integrations hide behind "ChatGPT support":
1. **As a server**: deploy `McpServer` to a public HTTPS endpoint and register it as a connector. This is the realistic path and needs Streamable HTTP + OAuth + `search`/`fetch` shape + elicitation-safe behaviour.
2. **As a client**: not applicable — OpenAI's agent surfaces do not consume MCP client config from the user's machine.

So any "one line" claim for OpenAI should read "one line to mount, one deploy to connect", and the bridge must be able to *stand alone* as an HTTP MCP server.

---

## 11. Gemini CLI

**Config:** `settings.json` with `mcpServers` (both confirmed on `docs/tools/mcp-server.md` in `google-gemini/gemini-cli`, fetched 2026-11-26), plus a documented internal architecture (`mcp-client.ts` / `mcp-tool.ts`) and a `Discovered…` tool wrapper prefix — i.e. every MCP tool is `Discovered`-wrapped, which is where Gemini CLI would hang filtering and naming.

```json
{
  "mcpServers": {
    "lauren": {
      "command": "uvx",
      "args": ["lauren-mcp", "serve", "--stdio"],
      "env": { "LAUREN_TOKEN": "$LAUREN_TOKEN" },
      "timeout": 30000,
      "trust": false
    },
    "lauren-remote": {
      "httpUrl": "https://mcp.example.com/mcp",
      "headers": { "Authorization": "Bearer $LAUREN_TOKEN" }
    }
  }
}
```

**Distinctive facts (confirmed from the page text).**
- Remote servers use **`httpUrl`** (not `url`) — a fifth key divergence, and one that silently fails if you get it wrong.
- Startup behaviour: the client "iterates through configured servers from your `settings.json` `mcpServers` configuration" and "**fetches and registers resources if the server exposes any**" — resources are enumerated eagerly at boot. For a bridge mounting many resource-heavy remote servers, that is a measurable startup cost and a good argument for lazy resource listing behind a capability flag.
- **Tool filtering is first-class**: `toolFilter`, `excludeTools`, and a per-server **`trust`** flag exist. This is the closest thing to the "declarative deny/allow" that a bridge needs, and it confirms the pattern lauren-mcp should expose (filter at the client config layer, not by unregistering tools upstream).
- Approval/permission: `trust` gates automatic execution, mirroring Cline's `autoApprove` and Claude Code's permission prompts.

**Implication.** Gemini CLI is the host whose config diverges furthest from the `mcpServers`-with-`url` norm while still using the `mcpServers` name — the worst combination for a naive generator, because the key looks right and the value silently doesn't. `httpUrl` support belongs in the same emitter as the others, with a `--host gemini` switch that is *tested*, not assumed.

---

## 12. Agent-framework layer (the second integration surface)

Hosts are half the market. The other half is agent frameworks that programmatically attach MCP servers — and this is lauren-mcp's home turf, because `McpToolBridge` competes with `Agent(mcp_servers=[...])` / `Agent(toolsets=[...])`. Versions below were read from the PyPI JSON API / npm registry on **2026-11-26**; class names were read from upstream source files, not from README prose.

| Framework | Verified version | MCP entry point (verified from source) | Transport classes | Fit for `McpToolBridge` |
|---|---|---|---|---|
| OpenAI Agents SDK (Python) | `openai-agents` **0.26.0** | `agents.mcp` → attached to an `Agent`; managed lifecycle via `MCPServerManager` | `MCPServerStdio`, `MCPServerSse`, `MCPServerStreamableHttp` (+ `*Params`) | Direct competitor; same three transports lauren-mcp needs |
| LangChain adapters | `langchain-mcp-adapters` **0.3.2** | `MultiServerMCPClient` with `.get_tools()` and `.session()` | via `mcp` SDK connection dicts | Strong precedent for *multi-server, one client* naming |
| Google ADK | `google-adk` **2.15.1** | `google.adk.tools.mcp_tool` → **`McpToolset`** (new) with **`MCPToolset`** retained as the older name | stdio / SSE / Streamable HTTP connection params | Renamed class = ecosystem still churning; expect aliases |
| Pydantic AI | `pydantic-ai-slim` **2.75.0** | `pydantic_ai.mcp` → `MCPServerConfig`, `MCPServerStdio`, `MCPServerSSE`, `MCPServerStreamableHTTP`, `MCPServerHTTP` | four classes incl. legacy `MCPServerHTTP` | Richest transport matrix; `MCPServerConfig` shows the config-object pattern |
| AWS Strands | `strands-agents` **1.67.0** | `MCPClient` (+ `MCP_VERSIONS` constant) used as a context manager | stdio / HTTP via transport kwargs | `MCP_VERSIONS` signals explicit protocol-version pinning |
| Microsoft Agent Framework | `agent-framework` **1.26.0** / `agent-framework-core` | `MCPStreamableHTTPTool` (confirmed in package metadata) | streamable HTTP confirmed; stdio class name unverified | Entered 1.x; C#/Python split |
| Agno | `agno` | `agno.tools.mcp` → `MCPTools`, `SSEClientParams`, `StreamableHTTPClientParams` | SSE + Streamable HTTP params | Params objects per transport — same shape as lauren-mcp proxies |
| Mastra (TypeScript) | `@mastra/mcp` **2.11.0** | `MCPClient` (TS) | stdio / HTTP | The only TS framework surveyed; `McpServer` facade has no TS twin |

**Reading across the table:**

1. **Everyone converges on three transports and a manager object.** stdio + SSE + Streamable HTTP, plus a lifecycle manager (`MCPServerManager`, context managers, `MCPClient`). lauren-mcp's `McpServer` facade is the same abstraction; the differentiation must come from *composition* (prefix mounts, proxies), not from transport coverage.
2. **Naming is still unstable in 2026** — ADK kept two casings for one class (`McpToolset`/`MCPToolset`), Pydantic AI kept `MCPServerHTTP` alongside `MCPServerStreamableHTTP`. Any lauren-mcp documentation that writes "the standard MCP wrapper is `MCPServerX`" is immediately wrong for half the ecosystem.
3. **Nobody in this list solves deferred loading.** Every framework attaches the full tool set to the model. That is the opening: a bridge that can present a *searchable* subset (or a single `call_tool(name, args)` meta-tool) is strictly better than `Agent(mcp_servers=[a, b, c, d, e])` in a framework with no tool-search story.
4. **Protocol-version pinning exists** (Strands' `MCP_VERSIONS`) — lauren-mcp should know what it speaks and say so, especially with MRTR landing.

---

## 13. Protocol layer: what changed under the hosts

### 13.1 Stable revision is `2025-11-25`

Confirmed three ways on 2026-11-26: the spec repository publishes `docs/specification/2025-11-25/` with a `changelog.mdx` (fetched, with `## Major changes` / `## Minor changes` / `## Other schema changes` / `## Governance and process updates` sections), Zed's MCP docs link `modelcontextprotocol.io/specification/2025-11-25/server/tools` and `.../server/prompts`, and the Python SDK on PyPI is `mcp` **2.3.0** (a 2.x line, i.e. well past the 1.x SDK that lauren-mcp-era tutorials assume).

### 13.2 MRTR — Multi Round-Trip Requests (draft, post-2025-11-25)

This is the most consequential protocol change for a bridge, and it is **not** in the 2025-11-25 changelog (zero occurrences of "MRTR"/"round-trip"); it lives in the draft tree:

- `docs/specification/draft/basic/index.mdx` now lists three core protocol patterns: "request and response, **multi round-trip requests (MRTR)**, and subscribe and notify", linking to `/specification/draft/basic/patterns`.
- `docs/specification/draft/basic/patterns/mrtr.mdx` defines: `InputRequests`, `InputResponses`, **`InputRequiredResult`**, and a **`requestState`** field, with sections "Core Types", "Supported Requests", "Basic Workflow", "Server Requi…".
- **Supported requests (verified):** `tools/call`, `prompts/get`, `resources/read`.
- **The key sentence:** MRTR "replaces the previous approach of sending server-initiated" requests — i.e. instead of the server initiating `sampling/createMessage` or `elicitation/create` *back to the client mid-call*, the server returns `InputRequiredResult` and the client re-issues the original request with the collected inputs plus an opaque `requestState`.

**Why this matters to lauren-mcp more than to anyone else.** A proxy/bridge is *inherently* a server-initiated-request relay: upstream asks to sample, the bridge must forward that to the host, and today that means depending on host-side sampling support, which most hosts (Claude Code included, per its own docs) do not document. MRTR converts that fan-out into a `requestState` round trip the client drives. A bridge that models `InputRequiredResult` + `requestState` opaquely (store it, echo it back, never interpret it) becomes compatible with every host that implements the draft, *without* needing host sampling at all. This is the single highest-leverage protocol bet available to the project.

### 13.3 Tasks

The 2025-11-25 stable `basic/index` I fetched contains **zero** references to `tasks/`. Whatever task semantics exist are either experimental or draft-only; the repo's "no `tasks/*`" status is therefore not yet a compatibility failure — but Claude Code's own docs describe "MCP tasks that run on the server", so the client side is arriving ahead of the stable spec. Track it; do not build on it.

### 13.4 Cancellation

`cancellation.mdx` exists as a first-class draft pattern (`docs/specification/draft/basic/patterns/cancellation.mdx`). The repo has **no client-side cancellation**, which is the gap most likely to be felt in practice: a long-running remote tool call mounted through the bridge cannot be aborted when the user hits Esc, because the bridge has no request-id → upstream-session mapping to cancel against. MRTR's `requestState` makes this worse if unaddressed (a pending `InputRequiredResult` that nobody resolves is a hung call).

### 13.5 Deferred loading is a *host* feature, not a protocol feature

Nothing in the spec defines tool-search. Claude Code implements it entirely host-side with `_meta` extensions (`anthropic/alwaysLoad`, `anthropic/maxResultSizeChars`) and `ENABLE_TOOL_SEARCH`. That is the strategic conclusion for this document: **the protocol gives you `_meta`; the host gives you policy.** lauren-mcp should treat `_meta` as the portability channel and emit Anthropic's keys opportunistically (they are inert to other hosts) while documenting the 4,096/16,384 character budgets that make or break a multi-mount setup on the one host that matters most.

---

## 14. Implications for lauren-mcp

### 14.1 What the landscape says the product is

The one-liner (`McpToolBridge` → `for_root(proxies=[...])`) is correct and unduplicated: every framework in §12 makes you enumerate servers at the `Agent` level, and every host in §2–§11 makes you hand-edit a JSON dialect. Nobody offers *composition + prefixing + one-line wiring*, which is exactly the repo's positioning. The risk is not competition on that axis; it is that the bridge's output is unmanageable inside hosts that now budget context aggressively.

### 14.2 Concrete work, in priority order

1. **Emit all three config dialects** (`mcpServers` / `servers` / `context_servers`) plus the per-host value quirks (`url` vs `httpUrl`; flat `command` vs Zed's nested `{path, args, env}`; `"type": "http"` for VS Code). A `lauren-mcp install --host claude-code|cursor|vscode|zed|cline|gemini|devin|continue` command that writes the right file is the highest-conversion feature available and costs almost nothing — the byte-level facts needed are now all in §2–§11.
2. **Budget the instruction block to 4,096 characters.** Concatenating upstream `instructions` across N mounts blows Claude Code's up-front limit, and the truncation is silent. Emit one synthesised block that describes the *prefixed namespaces* (`repo__*`, `jira__*`) and the discovery tool, and never paste upstream prose.
3. **Opt the small indispensable tool set into `alwaysLoad`** via `_meta["anthropic/alwaysLoad"]`: the discovery tool, the generic `call`/`invoke` escape hatch, and per-mount health. Everything else should be deferrable. This is the difference between "works with 3 servers" and "works with 30".
4. **Truncate at the bridge, not at the host.** Host caps (Claude Code 25,000 tokens default, `MAX_MCP_OUTPUT_TOKENS`, `anthropic/maxResultSizeChars`) operate after the bytes have already crossed the pipe and been tokenised. A proxy mount should cap text content itself and return a structured "truncated + how to get more" payload, optionally advertising `anthropic/maxResultSizeChars` for tools that legitimately need more.
5. **Model MRTR opaquely now.** Store `requestState` from upstream, echo it on re-issue, never parse it. Cheap insurance for the next spec revision and the only realistic path to elicitation/sampling support across hosts that do not implement server-initiated requests.
6. **Add client-side cancellation before adding anything else protocol-shaped.** Without it, a bridged long-running tool is uninterruptible, which is a worse user experience than a missing feature.
7. **Stable, prefix-qualified tool names as a contract** — because Cline's `autoApprove`, Gemini CLI's `toolFilter`/`excludeTools`, and Claude Code's `alwaysLoad` all key off names.
8. **SSE is not dead.** Cursor still documents it, Pydantic AI ships `MCPServerSSE`, Agno ships `SSEClientParams`. Do not drop SSE from `McpServer` to simplify the transport matrix.
9. **Eager resource enumeration is expensive where it exists** (Gemini CLI "fetches and registers resources" at startup). Make resource listing lazy behind a flag so a 20-mount bridge does not pay for it on every cold start.
10. **Zed-compatibility hygiene:** never rely on resources or server-driven UI in a mount that must work in Zed; tools + prompts only.

### 14.3 Positioning sentence the evidence supports

> Mount any number of remote MCP servers into a Lauren agent in one line, and let the bridge handle what the hosts won't: prefixed namespaces, per-host config dialects, an instruction budget that fits under Claude Code's 4,096-character limit, result truncation, and `requestState` relay for the MRTR era.

---

## 15. Unverified items

Explicitly *not* established by a primary source in this pass; do not repeat these as fact without checking:

1. **Cursor's tool-count cap.** Older docs were widely quoted as "40 tools"; the current `cursor.com/docs/context/mcp` page contains no numeric limit. Treated as stale.
2. **VS Code variable substitution.** `"inputs"` / `${input:...}` did not appear on the current `.md` for `agent-customization/mcp-servers` (0 occurrences), and the configuration-reference page was not reachable at the URLs tried (`mcp-configuration`, `mcp-servers-configuration` both 404). Whether VS Code now uses a different variable mechanism is unknown.
3. **VS Code `servers` key: parent-verified, not re-verified here.** I confirmed the key name appears 16× on the page but the JSON snippet itself was inside content I could not parse cleanly. The `"type": "http"` discriminator for remote servers likewise comes from prior knowledge, not this pass.
4. **Continue's config schema.** The deep-dive page is thin: it confirms `mcpServers`, and mentions both YAML and JSON, but not whether the value is a list-with-`name` or a map, nor the remote `type` token. The YAML in §9 is illustrative.
5. **Cline remote `"type"` value** (`streamableHttp` vs `http` vs `sse`) — not string-verified.
6. **Devin resource/prompt/deferred-loading support** — not documented on the CLI MCP pages read.
7. **Claude Desktop's result-size cap and tool-search behaviour** — not documented; §2 therefore makes no claim.
8. **Microsoft Agent Framework stdio class name** (`MCPStdioTool` / `MCPTool`) — only `MCPStreamableHTTPTool` was string-verified.
9. **ChatGPT's exact elicitation semantics** — the existence of the section "Tool annotations and elicitation" is verified; the normative requirements inside it were partially truncated.
10. **OpenAI doc taxonomy.** The site now routes MCP under `plugins/` while `apps-sdk/llms.txt` still lists `concepts/mcp-server`; which is canonical after the rename is unclear.
11. **`drift`: `docs.anthropic.com/en/docs/claude-code/mcp` still returns 200** alongside `code.claude.com/docs/en/mcp`; I used the latter. Whether the former is a redirect or a stale copy was not determined.
12. **Claude Code's "tool search on by default since v2.1.227"** is inherited from the parent's verification, not independently re-verified in this pass (the docs confirm "enabled by default" without a version number).

---

## 16. Sources

All retrieved **2026-11-26**.

| # | Source | URL | Used for |
|---|---|---|---|
| 1 | Claude Code — Connect Claude Code to tools via MCP | https://code.claude.com/docs/en/mcp (markdown twin: `.../mcp.md`) | `.mcp.json`/`~/.claude.json`/`claude mcp add`; `streamable-http` alias; `ws` transport; `${VAR}` / `${VAR:-default}`; `alwaysLoad`; tool search defaults + `ENABLE_TOOL_SEARCH`; 4,096-char instructions & 16,384-char deferred descriptions; `CLAUDE_CODE_MAX_MCP_DESC*`; 10,000-token warning; 25,000-token default cap; `MAX_MCP_OUTPUT_TOKENS`; `anthropic/maxResultSizeChars`; `@server:uri` resources; `/mcp__srv__prompt`; `elicitation: {form, url}`; no `sampling` |
| 2 | Claude Code docs index | https://code.claude.com/docs/llms.txt | Page discovery, section names (tasks / skills / channels) |
| 3 | Anthropic (legacy path, still 200) | https://docs.anthropic.com/en/docs/claude-code/mcp | URL drift note only |
| 4 | MCP — Connect to local MCP servers (Claude Desktop) | https://modelcontextprotocol.io/docs/develop/connect-local-servers | `claude_desktop_config.json`, `mcpServers`, macOS log path |
| 5 | Cursor — MCP | https://cursor.com/docs/context/mcp | `~/.cursor/mcp.json`, `.cursor/mcp.json`, `mcpServers`, Customize page, stdio/SSE/HTTP, OAuth `state` + redirect URLs, marketplace |
| 6 | VS Code — Add and use MCP servers | https://code.visualstudio.com/docs/agent-customization/mcp-servers (redirect target from `/docs/copilot/customization/mcp-servers`) · markdown: `.../mcp-servers.md` | Doc relocation; scope table (Global "Copilot Global", workspace `.mcp.json`, Copilot CLI sharing); `servers` occurrences |
| 7 | VS Code — root docs index | https://code.visualstudio.com/llms.txt | `[Add and Use MCP Servers]`, `[Manage MCP Servers]` entries |
| 8 | Devin — MCP Configuration | https://docs.devin.ai/cli/extensibility/mcp/configuration.md | `.devin/mcp_config.json`, `.devin/mcp_config.local.json`, `mcpServers`, `url`, `command`, `.devin/config.json` |
| 9 | Devin docs index | https://docs.devin.ai/llms.txt | MCP cluster discovery (ex-Windsurf docs domain) |
| 10 | Zed — Model Context Protocol | https://zed.dev/docs/ai/mcp.md | `context_servers`, `enable_all_context_servers`, nested `command {path,args,env}`, "Tools and Prompts" only, links to spec `2025-11-25` |
| 11 | Cline — Configuring MCP servers | https://docs.cline.bot/mcp/configuring-mcp-servers | `~/.cline/data/settings/cline_mcp_settings.json`, `mcpServers`, `autoApprove` |
| 12 | Continue — MCP deep dive | https://docs.continue.dev/customize/deep-dives/mcp | `mcpServers`, yaml/json config ambiguity |
| 13 | OpenAI — Build an MCP server (plugins) | https://developers.openai.com/plugins/build/mcp-server.md | Streamable HTTP requirement, "Tool annotations and elicitation", "Company knowledge compatibility", `search`/`fetch`, `openai/profile` |
| 14 | OpenAI — Apps SDK index / Plugins index | https://developers.openai.com/apps-sdk/llms.txt · https://developers.openai.com/apps-sdk/build/mcp-server · https://developers.openai.com/plugins/build/mcp-events.md | Rename/taxonomy (`apps-sdk` → `plugins`), MCP Events page existence |
| 15 | OpenAI — Developer mode guide (platform) | https://platform.openai.com/docs/guides/developer-mode | Reachability only (200); no facts asserted |
| 16 | Gemini CLI — MCP servers | https://raw.githubusercontent.com/google-gemini/gemini-cli/main/docs/tools/mcp-server.md | `settings.json` `mcpServers`, `httpUrl`, `timeout`, `trust`, `toolFilter`/`excludeTools`, eager resource registration, `mcp-tool.ts` `Discovered…` wrapper |
| 17 | JetBrains — Configure an MCP server | https://www.jetbrains.com/help/ai-assistant/configure-an-mcp-server.html | Reachability only (200); not analysed in this pass |
| 18 | MCP spec — 2025-11-25 changelog | https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/docs/specification/2025-11-25/changelog.mdx | Confirms 2025-11-25 revision; **no** MRTR/round-trip content |
| 19 | MCP spec — draft basic index | https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/docs/specification/draft/basic/index.mdx | Three core patterns incl. MRTR; zero `tasks/` references |
| 20 | MCP spec — draft MRTR pattern | https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/docs/specification/draft/basic/patterns/mrtr.mdx | `InputRequests`, `InputResponses`, `InputRequiredResult`, `requestState`; supported requests `tools/call`, `prompts/get`, `resources/read`; "replaces the previous approach of sending server-initiated…" |
| 21 | MCP spec — draft patterns index | https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/docs/specification/draft/basic/patterns/index.mdx | Links to `patterns/mrtr#inputrequiredresult`, `patterns/cancellation.mdx` |
| 22 | PyPI JSON API | https://pypi.org/pypi/{mcp,openai-agents,langchain-mcp-adapters,google-adk,pydantic-ai-slim,strands-agents,agent-framework,agent-framework-core,agno}/json | Versions: `mcp` 2.3.0, `openai-agents` 0.26.0, `langchain-mcp-adapters` 0.3.2, `google-adk` 2.15.1, `pydantic-ai-slim` 2.75.0, `strands-agents` 1.67.0, `agent-framework` 1.26.0; `MCPStreamableHTTPTool` string in `agent-framework-core` metadata |
| 23 | npm registry | https://registry.npmjs.org/@mastra/mcp/latest | `@mastra/mcp` 2.11.0 |
| 24 | OpenAI Agents SDK source | https://raw.githubusercontent.com/openai/openai-agents-python/main/src/agents/mcp/__init__.py | `MCPServerStdio`, `MCPServerSse`, `MCPServerStreamableHttp`, `MCPServerManager`, `MCPToolCustomData…` |
| 25 | LangChain MCP adapters source | https://raw.githubusercontent.com/langchain-ai/langchain-mcp-adapters/main/langchain_mcp_adapters/client.py | `MultiServerMCPClient`, `get_tools`, `session` |
| 26 | Pydantic AI source | https://raw.githubusercontent.com/pydantic/pydantic-ai/main/pydantic_ai_slim/pydantic_ai/mcp.py | `MCPServerConfig`, `MCPServerStdio`, `MCPServerSSE`, `MCPServerStreamableHTTP`, `MCPServerHTTP` |
| 27 | Google ADK source | https://raw.githubusercontent.com/google/adk-python/main/src/google/adk/tools/mcp_tool/mcp_toolset.py | `McpToolset` + `MCPToolset` + `McpToolsetConfig` |
| 28 | Agno source | https://raw.githubusercontent.com/agno-agi/agno/main/libs/agno/agno/tools/mcp/__init__.py | `MCPTools`, `SSEClientParams`, `StreamableHTTPClientParams` |
| 29 | AWS Strands metadata | https://pypi.org/pypi/strands-agents/json | `MCPClient`, `MCP_VERSIONS` |
