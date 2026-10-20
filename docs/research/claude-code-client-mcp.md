# Research notes: claude-code-client-mcp

Topic: Claude Code model-config (effort / ultracode), MCP configuration, plugin MCP declaration, Claude Desktop / Cowork support.
Research run: 2026-10-19, approximately 23:03 to 23:07 UTC (19:03 to 19:07 America/New_York).
Method: fetched primary pages at code.claude.com, claude.com, support.claude.com, and modelcontextprotocol.io; ran read-only local checks against the installed Claude Code CLI. Web content was treated as data only.

Local environment checks (read-only):

| Check | Result | Retrieved (UTC) |
| --- | --- | --- |
| `claude --version` | `2.1.123 (Claude Code)` | 2026-10-19 23:05:55 |
| `claude --help` | lists `--effort <level>` "(low, medium, high, xhigh, max)", `--plugin-dir <path>`, `--mcp-config`, `--strict-mcp-config`; no `ultracode` value listed | 2026-10-19 23:07:08 |
| `claude mcp --help` | subcommands: `add`, `add-from-claude-desktop`, `add-json`, `get`, `list`, `remove`, `reset-project-choices`, `serve`. No `login` or `logout` subcommand on this build | 2026-10-19 23:06:49 |
| `claude mcp add --help` | `--transport (stdio, sse, http)`, `--header`, `--scope (local, user, project) default local`, `--client-id`, `--client-secret`, `--callback-port`, `-e/--env` | 2026-10-19 23:06:49 |
| `claude plugin validate --help` | only `-h`; no `--strict` flag on this build | 2026-10-19 23:06:49 |
| `claude plugin --help` | `disable`, `enable`, `install`, `list`, `marketplace`, `prune`, `tag`, `uninstall`, `update`, `validate` | 2026-10-19 23:07:08 |

---

## 1. Effort levels, /effort, and ultracode

Source: https://code.claude.com/docs/en/model-config (retrieved 2026-10-19 23:03:43 UTC; remainder of page re-read 23:05:55 UTC).

### Level names by model

Quote: "Fable 5.1 and Fable 5 | `low`, `medium`, `high`, `xhigh`, `max`". Opus 4.6 / Sonnet 4.6 lack `xhigh`. "Models not listed here do not support effort."

Quote: "If you set a level the active model does not support, Claude Code falls back to the highest supported level at or below the one you set."

### Resolution order and defaults

1. Explicit: `CLAUDE_CODE_EFFORT_LEVEL` env var, `--effort` at launch, or `/effort` in session.
2. Settings: a saved per-model level or an `effortLevel` key.
3. Model default: "`high` on every model that supports effort", except Opus 5.5 / Sonnet 5.5 / Haiku 5.5 default `medium`, Opus 4.7 defaults `xhigh`.

### The /effort command

- `/effort` with no argument opens an interactive slider.
- `/effort <level>` sets a level directly; `/effort auto` clears the saved level for the active model.
- Quote: "In the session, run `/effort status` to see the level in effect."
- Quote: "The current effort level is also shown in the session header next to the model name".
- `Enter` in the slider or a level typed after `/effort` saves it as the default; `s` applies it to this session only ("Requires Claude Code v2.1.257 or later").
- Quote: "`max` is the deepest reasoning level. Unless you set it through the `CLAUDE_CODE_EFFORT_LEVEL` environment variable, Claude Code applies `max` to the current session only."
- Settings: `modelSettings` or `effortLevel` accept `low`/`medium`/`high`/`xhigh`; quote: "`max` isn't accepted as a level in either key, and `ultracode` has its own `ultracode` key."

### What ultracode is

Quote: "Ultracode is a Claude Code setting rather than a model effort level: with it on, Claude orchestrates dynamic workflows for substantive tasks, at whichever effort level the session runs at."

Ways to turn it on: `/effort ultracode` (off with `/effort ultracode off`); `Tab` in the `/effort` slider then `Enter`; `claude --effort ultracode`; `"ultracode": true` in settings; Agent SDK `effortLevel: "ultracode"`.

### Does ultracode change effort to xhigh?

- Quote: "Turning ultracode on or off with `/effort` or the `ultracode` setting leaves the effort level unchanged."
- Quote: "The `--effort ultracode` flag and the Agent SDK `effortLevel: "ultracode"` value turn it on and also set the level to `xhigh`."
- Quote: "Picking a level in the `/effort` slider or the `/model` picker leaves ultracode as it was."
- The page does not directly address running `/effort max` and then `/effort ultracode`; the closest statements are the three above.

### Version requirements (exact)

- Quote: "The `/effort ultracode off` form, the slider toggle, and keeping ultracode on at effort levels other than `xhigh` require Claude Code v2.1.284 or later."
- Quote: "Before v2.1.284, turning on ultracode set the session to `xhigh` effort, picking another level turned it off, and an effort cap below `xhigh` made it unavailable."
- Quote: "Passing `ultracode` to the `--effort` flag or the Agent SDK `effortLevel` value requires Claude Code v2.1.203 or later. Before v2.1.203, `--effort ultracode` printed `Unknown --effort value 'ultracode'`".
- Quote: "The persisted `effortLevel` setting and the `CLAUDE_CODE_EFFORT_LEVEL` environment variable don't accept `ultracode`."
- Ultracode is unavailable when "Workflows are turned off" or "The model doesn't support `xhigh` effort"; then `--effort ultracode` "starts the session with ultracode off, at the highest effort level the model and any cap allow, up to `xhigh`."

### Comparison with the user's belief and the installed client

- User belief ("v2.1.284+ lets /effort max then /effort ultracode enable both; older clients make ultracode switch to xhigh"): consistent with the docs. On v2.1.284+, `/effort ultracode` leaves the level unchanged, so a session at `max` stays at `max` with ultracode on. Before v2.1.284 turning ultracode on sets `xhigh`, and picking another level turns ultracode off.
- Installed CLI: 2.1.123, below both 2.1.203 and 2.1.284. `claude --help` on this build lists `--effort` values `low, medium, high, xhigh, max` only. The docs do not state the minimum version at which the in-session `/effort ultracode` (on) form first appeared, so whether 2.1.123 accepts it is unresolved.
- Model alias note: the page's version history says "v2.1.257 | `fable` resolves to Fable 5.1". On 2.1.123 the `fable` alias resolves to Fable 5 per the "Earlier" row. The user's screenshot showing Fable 5.1 may come from a different (newer) embedded client than the CLI binary on PATH; unresolved.

---

## 2. Claude Code MCP configuration

Source: https://code.claude.com/docs/en/mcp (retrieved 2026-10-19 23:03:43 UTC; second half 23:05:55 UTC; plugin and OAuth sections re-read 23:06:49 UTC).

### Adding a remote HTTP server

```bash
claude mcp add --transport http <name> <url>
claude mcp add --transport http notion https://mcp.notion.com/mcp
claude mcp add --transport http secure-api https://api.example.com/mcp --header "Authorization: Bearer your-token"
```

Quote: HTTP is "the recommended option for connecting to remote MCP servers." Quote: "The SSE (Server-Sent Events) transport is deprecated. Use HTTP servers instead, where available."

Confirmed on installed 2.1.123: `claude mcp add --help` prints the same `--transport http sentry https://mcp.sentry.dev/mcp` example and `--header` example.

Other commands documented: `claude mcp add-json <name> '<json>'`, `claude mcp list`, `claude mcp get <name>`, `claude mcp remove <name> [--scope]`, `claude mcp reset-project-choices`, `claude mcp serve`, `claude mcp add-from-claude-desktop` ("only works on macOS and Windows Subsystem for Linux"), `claude mcp login <name>` / `claude mcp logout <name>`. Note: on 2.1.123, `claude mcp --help` does not list `login` or `logout`; `add-json` help text reads "(stdio or SSE)".

### Scopes

| Scope | Loads in | Shared | Stored in |
| --- | --- | --- | --- |
| Local (default) | Current project only | No | `~/.claude.json` |
| Project | Current project only | Yes, via version control | `.mcp.json` in project root |
| User | All your projects | No | `~/.claude.json` |

Precedence (first wins): "1. Local scope 2. Project scope 3. User scope 4. Plugin-provided servers 5. claude.ai connectors." Quote: "The entire server entry from that source is used; fields are not merged across scopes." `managedMcpServers` ranks above all (v2.1.259+).

### Project .mcp.json with type http

```json
{
  "mcpServers": {
    "shared-server": {
      "type": "http",
      "url": "https://example.com/mcp"
    }
  }
}
```

Claude Code prompts for approval before using project-scoped servers in interactive sessions; `claude mcp reset-project-choices` resets the choices.

### OAuth for remote servers

- Quote: "Claude Code marks a remote server as needing authentication when the server responds with `401 Unauthorized` or `403 Forbidden`."
- Flow: add the server, run `/mcp`, "follow the steps in your browser to log in."
- Quote: "Authentication tokens are stored securely and refreshed automatically." "Clear authentication" in the `/mcp` menu revokes.
- On a 401 for a server already signed in, Claude Code refreshes the token, reconnects, retries once.
- `claude -p` / Agent SDK runs have no `/mcp` panel; sign in first from an interactive session or with `claude mcp login <name>` (`--no-browser` forces URL prompt). Not available on 2.1.123 per local help.
- Quote: "If you configured `headers.Authorization` for the server and the server rejects that header, Claude Code reports the connection as failed instead of falling back to OAuth."
- Pre-configured OAuth client: `--client-id`, `--client-secret` (masked prompt or `MCP_CLIENT_SECRET`), `--callback-port` (redirect URI `http://localhost:PORT/callback`). Secret goes to the system keychain (macOS) or credentials file, never into the config. `.mcp.json` `oauth` object fields: `clientId`, `callbackPort`, `authServerMetadataUrl` (must be `https://`), `scopes` (space-separated string; overrides discovery).
- Removing a remote server "also deletes the OAuth tokens and client registration it stored for that server."

### Headers

`--header` / `-H` on add; `"headers": {...}` in JSON; `headersHelper` runs a command that prints a JSON object of headers (10-second limit).

### Environment variable expansion

- `${VAR}` and `${VAR:-default}`.
- Expands in `command`, `args`, `env`, `url`, `headers`.
- Missing value with no default: warning, server loads with `${VAR}` unexpanded.
- In remote `url`/`headers`, `ANTHROPIC_API_KEY` and `ANTHROPIC_AUTH_TOKEN` read as empty "so a project can't exfiltrate them."
- Plugin configs may use `${CLAUDE_PLUGIN_ROOT}`, `${CLAUDE_PLUGIN_DATA}`, `${CLAUDE_PROJECT_DIR}`.

### Timeouts

- `MCP_TIMEOUT`: startup timeout in ms (example `MCP_TIMEOUT=10000 claude`); default not stated on the page.
- `MCP_TOOL_TIMEOUT`: "about 28 hours when that variable is unset"; per-server `"timeout"` (ms) overrides; values below 1000 ignored.
- Idle timeout: five minutes for HTTP/SSE/WebSocket/connectors, 30 minutes for stdio (`CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT`).
- Calls running past two minutes move to a background task (`CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS`).
- `alwaysLoad: true` makes startup wait, "capped at the standard 5-second connect timeout".

### Output limits

- Quote: "Claude Code displays a warning when MCP tool output exceeds 10,000 tokens and limits output to 25,000 tokens by default." Raise with `MAX_MCP_OUTPUT_TOKENS=50000`; the warning threshold is fixed.
- Text results over 50,000 characters are persisted to disk and replaced with a file reference unless the tool sets `_meta["anthropic/maxResultSizeChars"]` (hard ceiling 500,000).
- HTTP/SSE responses and WebSocket messages over 16 MiB fail.
- Tool description limits: server instructions and upfront tool descriptions 4,096 characters; deferred (tool-search) descriptions 16,384 characters (`CLAUDE_CODE_MAX_MCP_DESCRIPTION_LENGTH`, v2.1.280+).

### Tool naming and permissions

- Full tool name form `mcp__<server>__<tool>` (shown in `/mcp`); tools whose full name exceeds 128 characters are left out of what is sent to Claude.
- Plugin servers: `mcp__plugin_<plugin-name>_<server-name>__<tool-name>`, "where any character outside `A-Z`, `a-z`, `0-9`, `_`, and `-` is replaced with `_`"; server registers as `plugin:<plugin-name>:<server-name>`.
- Use these names in permission rules, skill `allowed-tools`, subagent `tools`, hook matchers. "A hook matcher written against the bare server key ... never fires for a plugin-bundled server."
- `_meta["anthropic/requiresUserInteraction"]: true` on a tool forces a permission prompt on every call, even in `acceptEdits`, `auto`, `bypassPermissions`; denied in `dontAsk`.
- `_meta["anthropic/alwaysLoad"]` controls deferral per tool; server-level `"alwaysLoad": true/false`.
- Tool search is on by default: only tool names and server instructions load at session start.
- Schema rules: top-level property names 1 to 64 chars ASCII letters/digits/`_`/`.`/`-`; JSON Schema draft 2020-12; root-level `anyOf`/`oneOf`/`allOf` are flattened.

### claude.ai connectors in Claude Code

Quote: "MCP servers you've added in claude.ai, known as connectors, are automatically available in Claude Code" when the active auth is a claude.ai subscription login. Disable with `"disableClaudeAiConnectors": true` or `ENABLE_CLAUDEAI_MCP_SERVERS=false`; block individual ones via `deniedMcpServers`.

---

## 3. Plugins and MCP servers

Sources: https://code.claude.com/docs/en/plugins (23:03:43 UTC), https://code.claude.com/docs/en/plugins/components (23:05:55 UTC), https://code.claude.com/docs/en/plugins/manifest-reference (23:05:55 UTC), https://code.claude.com/docs/en/plugins/create (23:05:55 UTC), https://code.claude.com/docs/en/plugins/install (23:06:49 UTC), https://code.claude.com/docs/en/mcp "Plugin-provided MCP servers" (23:06:49 UTC).

### Where a plugin declares MCP servers

- Quote (mcp page): "Plugins define MCP servers in `.mcp.json` at the plugin root or inline in `plugin.json`".
- Quote (components): "Declare it in `.mcp.json` at the plugin root, in the same shape as a project `.mcp.json`". "You can also omit the `mcpServers` wrapper and put `db` at the top level of the file."
- Manifest `mcpServers` field: "`.json` MCP config files, `.mcpb` or `.dxt` bundles, or inline server configs keyed by name. Loaded together with `.mcp.json`; a server name declared later replaces an earlier one." Shapes: `.json` file path, bundle path, bundle `https://` URL, inline map, or array of these.
- Quote (manifest): "Claude Code loads `.mcp.json` at the plugin root first, then each declared shape in order."
- Standard layout: manifest at `.claude-plugin/plugin.json`, MCP servers at `.mcp.json` (plugin root), skills at `skills/<name>/SKILL.md`. Quote: "Put every other plugin file at the plugin root, not inside `.claude-plugin/`."
- `name` is the only required manifest key; kebab-case; names starting with `claude-`, `anthropic-`, `anthropics-`, `cc-plugin-` are rejected by validate.
- Directory listing fields `icon`, `documentationUrl`, `supportUrl`, `privacyPolicyUrl`, `termsOfServiceUrl` are read by Anthropic's directory; "`claude plugin validate` accepts these fields without a warning on Claude Code v2.1.281 or later. Earlier versions print an `Unknown field` warning for each one, so a `--strict` run fails on those versions."
- A `CLAUDE.md` at plugin root isn't loaded and triggers a validate warning.
- A top-level `bin/` directory: "claude.ai and Cowork don't install a plugin that has this directory".

### Lifecycle

Quote: "When you enable a plugin, Claude Code starts its MCP servers automatically". Quote: "At session startup, Claude Code connects the servers for enabled plugins automatically." Enabling/disabling mid-session connects/disconnects "when the change applies"; in non-interactive sessions `/reload-plugins` doesn't connect plugin servers until the next session. A remote plugin server used before may show `cached` and connect on first tool call (discovery cache, v2.1.221+, off by default unless rolled out; `MCP_DISCOVERY_CACHE=1`). Plugin servers are added/removed by installing/uninstalling the plugin, not `/mcp`; they can be toggled off in `/mcp`. On `/reload-plugins`, unchanged servers keep their connection.

### Remote servers in plugins and OAuth

- Quote: "Multiple transport types: support for stdio, SSE, HTTP, and WebSocket transports". `${CLAUDE_PLUGIN_ROOT}` etc. substitute in `url`, `headers`, `headersHelper` for `http`/`sse`/`ws`.
- Quote (components): "To reach users there too, reference a remote server by its `https://` URL, which claude.ai and Cowork offer to the user as a connector".
- The Claude Code docs do not state explicitly that a plugin-bundled remote server triggers the OAuth prompt; the general rule (401/403 marks the server in `/mcp` for OAuth) and "Plugin servers appear in `/mcp` with indicators showing they come from plugins" together imply the same `/mcp` login path. Treat as medium confidence until tested.
- `claude plugin validate` MCP checks (v2.1.281+): errors for an entry Claude Code would drop, a `${user_config.KEY}` reference to an undeclared option, and "a remote `url` that isn't a valid absolute URL"; warnings for `http://`/`ws://` to non-loopback hosts and header values that look like literal credentials.

### Development and validation

- `claude plugin validate ./my-plugin` prints `Validation passed` / `passed with warnings` / `failed`; "Pass `--strict` to turn warnings into failures in CI". Not present on 2.1.123 (`validate --help` shows only `-h`).
- `claude --plugin-dir ./my-plugin` (repeatable; accepts a `.zip`); `/reload-plugins` applies edits; `/mcp` shows the plugin server's status; `/plugin` Installed and Errors tabs.
- `--plugin-url https://.../plugin.zip`; `CLAUDE_CODE_PLUGIN_DIRS` (v2.1.280+); `claude plugin init`.
- Install scopes: user (`enabledPlugins` in `~/.claude/settings.json`), project (`.claude/settings.json`), local (`.claude/settings.local.json`); local overrides project overrides user.
- Synced plugins: plugins enabled on the claude.ai account arrive in Claude Code as `<name>@synced` (terminal sessions need v2.1.273+); CLI-installed plugins don't go to the account. Cloud sessions (claude.ai/code) don't load local plugins.

---

## 4. claude.ai, Cowork, and Claude Desktop

### Component support table

Source: https://claude.com/docs/plugins/platform-support (23:05:55 UTC).

| Component | Chat | Cowork | Claude Code |
| --- | --- | --- | --- |
| Skills | Loads | Loads | Loads |
| Commands | Loads as a skill | Loads (`/plugin-name:command`) | Loads |
| Agents | Ignored | Loads | Loads |
| Hooks | Ignored | Loads | Loads |
| Remote MCP server (`http`/`sse`, fixed URL) | "Listed on the plugin's Connectors tab; works once you add or connect it there" | "Loads; connect it from the plugin's Connectors tab" | Loads |
| Local MCP server (command, incl. `.mcpb`) | Ignored | "Loads when the Cowork session runs on your computer" | Loads |
| MCP server referencing `${user_config.*}` | Ignored when the URL contains the reference | Ignored when a referenced option has no default; Cowork doesn't prompt | Loads; prompts |
| Top-level `bin/` | Can't be installed | Can't be installed | Loads |
| LSP, output styles, themes, `settings` | Ignored | Ignored | Loads |

Limits for chat/Cowork: up to 25 self-added marketplaces; each plugin up to 5,000 files and 200 MB; **Upload plugin** accepts up to 200 MB. Directory browsing on Pro, Max, Team, Enterprise; `/plugin directory` in Claude Code v2.1.287+.

### Bundling a connector in a plugin

Source: https://claude.com/docs/plugins/build (23:06:49 UTC).

```json
{
  "mcpServers": {
    "expenses": {
      "type": "http",
      "url": "https://mcp.example.com/mcp"
    }
  }
}
```

Quote: "On claude.ai and in Cowork, that entry is listed on the plugin's Connectors tab, where the user adds or connects it and signs in through your server's OAuth flow." Quote: "Don't put API keys or other secrets in this file, because every person who installs the plugin receives its files." Quote: "If your server is already listed in the directory, use the same URL here". Testing: zip the folder, **Customize > Plugins > Add > Upload plugin**; error text if nested wrong: `plugin.json must be at .claude-plugin/plugin.json at the zip root (or inside a single top-level directory)`. README of at least 40 words and a license are required to publish.

Source: https://claude.com/docs/plugins/overview (23:05:55 UTC). Quote: "Adding a plugin doesn't add a connector to your account or sign you in to anything." Connector states on the Connectors tab: Connected / Not connected / Not added. "The plugin's skills load whether or not you connect anything."

### Cowork

- Source: https://claude.com/docs/cowork/guide/plugins (23:06:49 UTC). "A plugin you install is saved to your account, so its skills and connectors are also available in chat and in Claude Code." "Installing doesn't add or sign you in to any connector. If the plugin includes connectors, open its Connectors tab afterward". Components: Skills, Connectors, Agents, Hooks. Limits: 200 MB uncompressed, 5,000 files, 25 marketplaces.
- Source: https://support.claude.com/en/articles/13837440-use-plugins-in-cowork (23:06:49 UTC). "Plugins are available to all paid plans (Pro, Max, Team, Enterprise)." "Plugins you add in Claude on the web or in Claude Desktop are saved to your account, not to your computer". "A plugin's local MCP server runs in Cowork and Claude Code, not in chat." In Cowork, "connectors reach external services through Anthropic's cloud, not through your local network."
- Source: https://support.claude.com/en/articles/11175166 "Get started with custom connectors using remote MCP" (23:06:49 UTC). Custom connectors available on "Claude, Cowork, and Claude Desktop" on Free, Pro, Max, Team, Enterprise (Free limited to one). "Claude connects to your remote MCP server from Anthropic's cloud infrastructure"; "your MCP server must be reachable over the public internet from Anthropic's IP ranges." Quote: "Local MCP servers configured in Claude Desktop via `claude_desktop_config.json` are a separate mechanism and do use your local network, but those aren't available in Cowork or claude.ai." OAuth client options: "Use Claude's published identity (Recommended)", "Register automatically", "Use your own OAuth client".
- Source: https://claude.com/docs/connectors/custom/add-unlisted (23:06:49 UTC). Pro/Max: **Customize > Connectors > Add custom connector**, enter the HTTPS MCP URL (`https://mcp.example.com/mcp`), optional OAuth client ID/secret under **Advanced settings**. Authentication modes: Sign in now / Sign in when needed / No sign-in. "A URL ending in `/sse` selects the older SSE transport." Authentication settings can't be changed after adding; remove and re-add.

### Claude Desktop local MCP

- Source: https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop (23:03:43 UTC, re-read 23:05:55 UTC). The article now documents desktop extensions (`.mcpb`): Settings > Extensions, "Advanced settings", Extension Developer section, "Install Extension…". "Claude Desktop includes a built-in Node.js environment, so Node.js installation isn't required." It contains no `claude_desktop_config.json` JSON block and no Cowork content (page shows "Updated over 3 weeks ago").
- Source: https://claude.com/docs/connectors/custom/add-unlisted (23:06:49 UTC). "Install a local connector in the desktop app": Settings > Extensions, drag the `.mcpb` file, Install. Also no `claude_desktop_config.json` structure.
- Source: https://modelcontextprotocol.io/quickstart/user (23:05:55 UTC; MCP project documentation, not an Anthropic support page). Config path macOS `~/Library/Application Support/Claude/claude_desktop_config.json`; Windows `%APPDATA%\Claude\claude_desktop_config.json`; opened via Claude menu > Settings... > Developer > Edit Config. Structure:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/Users/username/Desktop"]
    }
  }
}
```

An `env` map per server is also shown (Windows `APPDATA` example). Restart Claude Desktop fully; verify via the "Add files, connectors, and more" control > Connectors > Manage connectors. Logs at `~/Library/Logs/Claude/mcp.log` and `mcp-server-SERVERNAME.log`. The page does not show a `type`/`url` remote entry for this file.
- Claude Code can import these entries: `claude mcp add-from-claude-desktop` (present on 2.1.123).

---

## Implications for this build (nba-three-leg-parlays plugin + hosted MCP)

1. Client version: 2.1.123 is below the documented thresholds for `--effort ultracode` (2.1.203) and for ultracode coexisting with `max` (2.1.284). Upgrade before relying on either; verify with `claude --version` afterward. Effort/ultracode are build-session settings only and do not affect the shipped MCP server.
2. Plugin bundle: `.claude-plugin/plugin.json` (name, displayName, version, description, author, license) plus `.mcp.json` at the plugin root with one `type: "http"` entry pointing at the HTTPS endpoint, no headers or secrets, and the same URL as the directory connector submission. Skills under `skills/nba-three-leg-parlays/SKILL.md`. No top-level `bin/`, no `${user_config.*}` in the URL, no stdio server as the primary path.
3. Tool names: the full Claude Code name is `mcp__plugin_nba-three-leg-parlays_<server-key>__<tool>` and must stay under 128 characters; use a short server key.
4. Server behavior: respond 401/403 with standard OAuth discovery so Claude Code flags the server in `/mcp`; support dynamic client registration or Claude's published client identity for claude.ai custom connectors; be reachable from Anthropic's cloud IP ranges over HTTPS.
5. Output sizing: keep tool results under roughly 10,000 tokens; server instructions and upfront tool descriptions under 4,096 characters with key terms first; consider `_meta["anthropic/requiresUserInteraction"]: true` on `select_ticket` and `record_actual_bet`.
6. Validation: `claude plugin validate ./plugin` works on 2.1.123 but without `--strict` and without the v2.1.281 MCP-entry checks or warning-free directory listing fields; re-run after upgrading.
7. Personal testing path in Claude Code: `claude mcp add --transport http nba-parlays https://<host>/mcp --scope user`, then `/mcp` to sign in (no `claude mcp login` on 2.1.123). For claude.ai: Customize > Plugins > Add > Upload plugin (zip), then the plugin's Connectors tab.
8. Cowork support statement: skills and the remote connector load in Cowork from the account; connect via the Connectors tab; connections originate from Anthropic's cloud; local servers only in sessions that run on the user's computer; no `userConfig` prompting in Cowork.
9. Claude Desktop: for the hosted backend, use the custom-connector URL path (shared with claude.ai); `claude_desktop_config.json` is a local stdio mechanism that does not reach claude.ai or Cowork and is not needed for this product.

---

## Unresolved

- Minimum version for the in-session `/effort ultracode` (on) form is not stated; only `--effort ultracode` (v2.1.203) and the off/slider/non-xhigh behaviors (v2.1.284) carry explicit versions. Whether 2.1.123 accepts `/effort ultracode` at all is untested.
- `/effort status` existence on 2.1.123 not verified (needs an interactive session).
- The docs do not spell out `/effort max` followed by `/effort ultracode`; the inference that `max` persists on v2.1.284+ comes from "leaves the effort level unchanged."
- Version history says `fable` resolves to Fable 5.1 from v2.1.257, yet the user's client shows Fable 5.1 on a 2.1.123 CLI; the desktop app may embed a different build. Not resolved here.
- `MCP_TIMEOUT` default value is not stated on the page.
- Explicit statement that plugin-bundled remote HTTP servers trigger the `/mcp` OAuth prompt in Claude Code was not found.
- No Anthropic-owned page fetched documents the current `claude_desktop_config.json` structure; the structure above comes from modelcontextprotocol.io. Whether that file accepts a `type: "http"` / `url` remote entry is undocumented in the pages fetched.
- On 2.1.123, `claude mcp add-json --help` text says "(stdio or SSE)" and `--header` says "WebSocket headers"; whether `add-json` with `type: "http"` and `--header` on HTTP behave per the current docs on this build is untested.
- What determines whether a Cowork session "runs on your computer" versus elsewhere was not found in the fetched pages.
- The managed-MCP page (`/docs/en/managed-mcp`) was not fetched; not needed for a personal/Max-plan build.

---

## Sources

| URL | retrieved_at_utc | What it established |
| --- | --- | --- |
| https://code.claude.com/docs/en/model-config | 2026-10-19T23:03:43Z (and 23:05:55Z for offset 100000) | Effort level names per model, `/effort` forms incl. `/effort status`, `max` session-only rule, ultracode definition, v2.1.203 and v2.1.284 requirements, xhigh behavior, version history of `fable` alias |
| https://code.claude.com/docs/en/mcp | 2026-10-19T23:03:43Z (23:05:55Z offset; 23:06:49Z plugin/OAuth sections) | `claude mcp add --transport http`, scopes and precedence, `.mcp.json` http format, OAuth 401/403 flow, `claude mcp login`, oauth fields, env expansion, timeouts, 10,000/25,000 token output limits, 50,000-char persist threshold, tool naming, tool search limits, plugin-provided server lifecycle, claude.ai connectors |
| https://code.claude.com/docs/en/plugins | 2026-10-19T23:03:43Z | Plugin definition, `.mcp.json` as MCP component, install scopes, cloud sessions don't load local plugins, pointer to claude.com platform-support |
| https://code.claude.com/docs/en/plugins/components | 2026-10-19T23:05:55Z | `.mcp.json` at plugin root (wrapper optional), manifest `mcpServers` replaces same-name, `plugin:<plugin>:<server>` and `mcp__plugin_<plugin>_<server>__<tool>`, local stdio not on claude.ai, MCPB bundles, validate MCP checks v2.1.281+ |
| https://code.claude.com/docs/en/plugins/manifest-reference | 2026-10-19T23:05:55Z | Manifest fields, `name` only required, `mcpServers` shapes and load order, directory listing fields and v2.1.281 warning behavior, `claude plugin validate` results and `--strict`, standard layout, `bin/` blocks claude.ai/Cowork install, env variables table |
| https://code.claude.com/docs/en/plugins/create | 2026-10-19T23:05:55Z | `claude plugin validate ./dir`, `--plugin-dir` (repeatable, zip), `--plugin-url`, `/reload-plugins`, `/mcp` to check plugin server, only `plugin.json` inside `.claude-plugin/` |
| https://code.claude.com/docs/en/plugins/install | 2026-10-19T23:06:49Z | Install scopes and settings files, synced plugins `<name>@synced` (v2.1.273+), cloud sessions, desktop app Code tab install, `claude plugin install/enable/disable/uninstall` |
| https://claude.com/docs/plugins/platform-support | 2026-10-19T23:05:55Z | Component support table for Chat / Cowork / Claude Code, remote vs local MCP behavior, `${user_config.*}` handling, size limits, directory availability |
| https://claude.com/docs/plugins/build | 2026-10-19T23:06:49Z | `.mcp.json` http example for bundles, Connectors tab + OAuth sign-in on claude.ai/Cowork, same-URL-as-directory advice, upload zip rules, README/license requirements |
| https://claude.com/docs/plugins/overview | 2026-10-19T23:05:55Z | Customize > Plugins install paths, "Adding a plugin doesn't add a connector", connector states, plan availability |
| https://claude.com/docs/cowork/guide/plugins | 2026-10-19T23:06:49Z | Cowork plugin components, account sync, Connectors tab after install, limits |
| https://claude.com/docs/connectors/custom/add-unlisted | 2026-10-19T23:06:49Z | Custom connector add steps, auth modes, OAuth client options, SSE via `/sse` URL, `.mcpb` install in desktop app |
| https://support.claude.com/en/articles/13837440-use-plugins-in-cowork | 2026-10-19T23:06:49Z | Cowork plugins on all paid plans, account-saved plugins, local MCP in Cowork/Claude Code not chat, connectors via Anthropic's cloud |
| https://support.claude.com/en/articles/11175166 | 2026-10-19T23:06:49Z | Custom connectors on Claude, Cowork, Claude Desktop; public-internet reachability from Anthropic IP ranges; `claude_desktop_config.json` servers not available in Cowork or claude.ai; OAuth client options |
| https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop | 2026-10-19T23:03:43Z (re-read 23:05:55Z) | Article now covers `.mcpb` desktop extensions; no config JSON; built-in Node.js; no Cowork content |
| https://modelcontextprotocol.io/quickstart/user | 2026-10-19T23:05:55Z | `claude_desktop_config.json` structure (`mcpServers` > `command`/`args`/`env`), file paths, Settings > Developer > Edit Config, restart, log locations |
| WebSearch `site:support.claude.com Cowork plugins` | 2026-10-19T23:05:55Z | Located article 13837440 and 13345190 |
| WebSearch `site:support.claude.com Cowork MCP connectors` | 2026-10-19T23:05:55Z | Located article 11175166 |
| Local: `claude --version` | 2026-10-19T23:05:55Z | 2.1.123 |
| Local: `claude mcp --help`, `claude mcp add --help`, `claude plugin validate --help` | 2026-10-19T23:06:49Z | Flags available on 2.1.123; no `mcp login`; no `validate --strict` |
| Local: `claude --help`, `claude plugin --help` | 2026-10-19T23:07:08Z | `--effort` values (no ultracode), `--plugin-dir`, `--mcp-config`; plugin subcommands |
