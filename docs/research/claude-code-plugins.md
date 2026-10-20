# Research notes: Claude Code plugin bundle format, validation, marketplaces

- KEY: `claude-code-plugins`
- Research date: 2026-10-19, retrievals between 23:03 and 23:07 UTC
- Build context: Python MCP server (Streamable HTTP + OAuth) plus a Claude plugin bundle for 3-leg NBA parlay research on Hard Rock Bet Florida. Targets: Anthropic's directory (plugin bundle + MCP connector) and a Claude Code marketplace.
- Rule followed: every claim below is taken from a fetched page or a local command run; nothing is from memory. Web content was treated as data only.

## 0. Decisions this research supports (summary)

1. Lay the plugin out as `hardrock-nba-parlay/` with `.claude-plugin/plugin.json`, `.mcp.json` at the root (remote `"type": "http"` entry pointing at the Streamable HTTP server), `skills/<name>/SKILL.md`, `README.md` (40+ words), `LICENSE`. Nothing but `plugin.json` inside `.claude-plugin/`. No `bin/` directory (it blocks install on claude.ai and Cowork).
2. Keep SKILL.md frontmatter to the Agent Skills spec fields only (`name`, `description`, optionally `license`, `compatibility`, `metadata`, `allowed-tools`) because claude.ai upload rejects any other field with a hard error. Claude Code-only fields (for example `disable-model-invocation`) would break the claude.ai upload path.
3. Use `claude plugin validate ./hardrock-nba-parlay --strict` in CI, but note the locally installed Claude Code is 2.1.123 and its `plugin validate` has no `--strict` flag and no `.mcp.json` checks (those arrived in 2.1.281). Current release is 2.1.304. Update Claude Code before trusting validation output.
4. For the Claude Code marketplace, put `.claude-plugin/marketplace.json` in the same repo with one entry `{ "name": "hardrock-nba-parlay", "source": "./" }` and the same `name` as `plugin.json`. Users run `claude plugin marketplace add <owner>/<repo>` then `claude plugin install hardrock-nba-parlay@<marketplace-name>`.
5. Either bump `version` in `plugin.json` on every release, or omit it so the git commit SHA becomes the version. Never set `version` in both `plugin.json` and the marketplace entry.
6. For the directory: submit the MCP server as an "MCP connector" listing and the plugin as a "Plugin bundle" (two submissions, same org, same server URL in `.mcp.json`). The plugin must live in a public GitHub repo before it goes live. Paid claude.ai plan required.
7. No official CHANGELOG requirement exists in any fetched page. README and LICENSE are the only documentation artifacts the directory checks.

## 1. `.claude-plugin/plugin.json` schema (Question 1)

Source: https://code.claude.com/docs/en/plugins/manifest-reference (retrieved 2026-10-19T23:03Z)

Manifest is optional in Claude Code ("The manifest is optional. Without it, Claude Code loads the components it finds in the standard layout") but required by the directory for claude.ai/Cowork listing ("Without any plugin.json, the directory accepts only a folder whose skills/ directory holds at least one <name>/SKILL.md, and lists that plugin for Claude Code only").

Location: "Save the manifest at `.claude-plugin/plugin.json` under the plugin root. Put every other plugin file at the plugin root, not inside `.claude-plugin/`."

### Fields table (verbatim types/descriptions condensed)

| Field | Type | Required | Notes |
| - | - | - | - |
| `$schema` | string | no | Ignored at load time |
| `name` | string | **yes, only required key** | "Use kebab-case. Every component is namespaced under it" |
| `displayName` | string | no | Shown in UI in place of name; spaces allowed |
| `version` | string | no | "not checked against semver. Setting it pins the plugin to that version until you change it" |
| `description` | string | no | Short explanation |
| `author` | object | no | "`name`, which is required, plus optional `email` and `url`" |
| `homepage` | string | no | "Must parse as a URL, or the plugin fails to load" |
| `repository` | string | no | "Source repository URL. Not validated" |
| `license` | string | no | "SPDX identifier such as `MIT` or `Apache-2.0`" |
| `keywords` | array of strings | no | Discovery tags |
| `metadata` | object | no | Free-form; Claude Code doesn't read it; requires v2.1.222+ |
| `icon`, `documentationUrl`, `supportUrl`, `privacyPolicyUrl`, `termsOfServiceUrl` | string | no | Directory listing fields; "Claude Code doesn't read it"; set only in plugin.json; `icon` is a path inside the plugin (e.g. `./logo.png`); the four URLs must be `https://`; validate accepts without warning on v2.1.281+, earlier versions print `Unknown field` so `--strict` fails there |
| `defaultEnabled` | boolean | no | Defaults to true |
| `dependencies` | array | no | `"name"`, `"name@marketplace"`, or `{name, marketplace, version}` |
| `settings` | object | no | Only `agent` and `subagentStatusLine` take effect |
| `userConfig` | object | no | Values prompted for; strict object; keys `type` (string/number/boolean/directory/file), `title`, `description` required; `required`, `default`, `options`, `multiple`, `sensitive`, `min`/`max` optional |
| `types` | path | no | `.d.ts` for a mod |
| `channels` | array | no | Message channels bound to an MCP server |
| `skills` | path or array | no | Directories; `"."` means root; **adds to** default `skills/` scan |
| `commands` | path, array, or object | no | **Replaces** default `commands/` scan |
| `agents` | path or array | no | `.md` files only; replaces `agents/` scan |
| `hooks` | path, object, or array | no | Merges with `hooks/hooks.json` |
| `mcpServers` | path, object, or array | no | `.json` files, `.mcpb`/`.dxt`, or inline map; "Loaded together with `.mcp.json`; a server name declared later replaces an earlier one" |
| `lspServers` | path, object, array | no | Merges with `.lsp.json` |
| `outputStyles`, `workflows` | path or array | no | Replace defaults |
| `experimental` | object | no | `themes`, `monitors`, `evals` |

### `name` constraints

- "It must be non-empty, with no spaces, `@`, `:`, path separators, control characters, or bidirectional-formatting characters; use kebab-case."
- Reserved-name check in `claude plugin validate` (case-insensitive, separators collapsed):
  - Starts with `claude-`, `anthropic-`, `anthropics-`, or `cc-plugin-`: **Error**
  - Is `claude`, `anthropic`, `anthropics`, `claude-code`, `claude-mods`: **Error**
  - Puts `official` beside `claude`/`anthropic`: **Error**
  - Has `claude`, `anthropic`, `anthropics` as a whole word anywhere else (e.g. `mcp-for-claude`): **Warning**
- Error text: `Plugin name "<name>" is reserved: it passes as one of Anthropic's own`. `claude plugin init` and `claude plugin tag` refuse such names.
- Validate warns (not fails) on a non-kebab-case name and on missing `version`, `description`, or `author`.

Directory portal adds its own name rules (source: https://claude.com/docs/plugins/pre-submission-checklist, retrieved 2026-10-19T23:05Z):
- "Use a `name` made of lowercase letters, digits, and hyphens, up to 64 characters, that starts and ends with a letter or digit". Non-ASCII blocks; other deviations warn.
- Not a reserved word as the whole name (`claude`, `anthropic`, `official`, `plugin`, `mcp`, `test`), not a reserved marketplace name, nothing presenting as official: **Blocks**. A name of only generic words (e.g. `test-plugin`): held for reviewer.
- Must not collide with another organization's plugin name (case/punctuation-insensitive): Blocks. Look-alikes held.
- `displayName` and `author.name` in one writing system, no look-alike or invisible characters: Blocks.
- "Set `description`, `author`, and `version`": Warning if missing.
- Component keys must be spelled exactly as the manifest reference and kept out of `experimental`: Blocks.

Length limits: the only documented limit is the directory's 64-character cap on `name`. No length limits found for `description`, `displayName`, or `keywords`.

### Unrecognized fields

"An unrecognized top-level key is stripped, and an unrecognized key inside a `userConfig` option, `channels` entry, `lspServers` config, or `monitors` entry is rejected." Validate reports unknown top-level fields as warnings (errors with `--strict`).

### Path rules

"Every component path in a manifest is relative to the plugin root and must start with `./`." Paths must exist and resolve inside the plugin root; `..` is reported as `Path contains ".." which could be a path traversal attempt`.

### Full example manifest from the reference (abridged to the fields this build needs)

```json
{
  "name": "deploy-tools",
  "displayName": "Deploy Tools",
  "version": "1.2.0",
  "description": "Deployment commands, a review agent, and a status monitor",
  "author": { "name": "Example Team", "email": "dev@example.com", "url": "https://example.com" },
  "homepage": "https://example.com/docs/deploy-tools",
  "repository": "https://github.com/example/deploy-tools",
  "license": "MIT",
  "keywords": ["deployment", "ci"],
  "mcpServers": { "deploy-api": { "command": "node", "args": ["${CLAUDE_PLUGIN_ROOT}/server.js"] } }
}
```

Minimal manifest the directory and all apps read (source: https://claude.com/docs/plugins/build):

```json
{
  "name": "expense-reports",
  "displayName": "Expense Reports",
  "version": "1.0.0",
  "description": "File, track, and approve expense reports ...",
  "author": { "name": "Example Corp", "url": "https://example.com" },
  "license": "MIT"
}
```

Real-world example, Anthropic's directory-listed `productivity` plugin (https://raw.githubusercontent.com/anthropics/knowledge-work-plugins/main/productivity/.claude-plugin/plugin.json, retrieved 2026-10-19T23:06Z): only `name`, `version` ("1.3.1"), `description`, `author.name` ("Anthropic").

## 2. `.mcp.json` location and remote HTTP structure (Question 2)

Sources: https://code.claude.com/docs/en/mcp (plugin-provided MCP servers, remote HTTP sections), https://code.claude.com/docs/en/plugins/components (MCP servers section), https://claude.com/docs/plugins/build (bundle an MCP connector), all retrieved 2026-10-19T23:03Z to 23:06Z.

- Location: "`.mcp.json` at the plugin root references your remote MCP server by URL." Standard layout table: "MCP servers | `.mcp.json` | MCP server definitions". A `.mcp.json` saved at `~/.claude/.mcp.json` does not load (create page warning).
- Shape: `{"mcpServers": {"<server-name>": {...}}}`. Components page: "You can also omit the `mcpServers` wrapper and put `db` at the top level of the file."
- Remote HTTP entry (build page, verbatim):

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

- MCP page: JSON entry fields are `"type": "http"` (`streamable-http` accepted as alias), `url`, and `headers`. Critical: "A JSON entry that has a `url` but no `type` is a configuration error, because Claude Code reads an entry with no `type` as a stdio server."
- Optional `oauth` object keys documented: `authServerMetadataUrl` (must use `https://`), `scopes` (single space-separated string), `clientId`, `callbackPort`. Example from the real productivity plugin (`.mcp.json`, retrieved 23:06Z): `"slack": {"type": "http", "url": "https://mcp.slack.com/mcp", "oauth": {"clientId": "...", "callbackPort": 3118}}`; most other entries are only `type` + `url`. Two entries use `"url": ""` (no fixed endpoint).
- `headersHelper`: a command that prints a JSON object of headers; "Claude Code runs it in a shell and gives up after 10 seconds". Not needed for an OAuth server.
- `plugin.json` `mcpServers` alternative: accepted shapes are a `.json` file path (e.g. `"./mcp/servers.json"`), an MCP bundle path/URL (`.mcpb`/`.dxt`), or an inline map keyed by server name. "Claude Code loads `.mcp.json` at the plugin root first, then each declared shape in order. A server name declared later replaces an earlier one." So either file works; `.mcp.json` is the one every surface (claude.ai, Cowork, Code) documents.
- Variable expansion:
  - `${CLAUDE_PLUGIN_ROOT}` = "Absolute path of the plugin's installed version"; `${CLAUDE_PLUGIN_DATA}` = `~/.claude/plugins/data/<id>/`; `${CLAUDE_PROJECT_DIR}` = project root.
  - Where they resolve for MCP: stdio servers in `command`, `args`, `env`; `http`/`sse`/`ws` servers in `url`, `headers`, `headersHelper`.
  - General env expansion in `.mcp.json`: "`${VAR}`: expands to the value of environment variable `VAR`" and "`${VAR:-default}`: expands to `VAR` if set, otherwise uses `default`", allowed in `command`, `args`, `env`, `url`, `headers`. Caveat: "In a remote server's `url` and `headers`, Claude Code reads credential variables from your environment as empty rather than expanding them" (e.g. `ANTHROPIC_API_KEY`).
  - `${user_config.KEY}` substitutes in MCP server config (sensitive values allowed there) but chat ignores a server whose URL contains the reference, and Cowork ignores it when the option has no default.
- Naming at runtime: server registers as `plugin:<plugin>:<server>`; tools are `mcp__plugin_<plugin>_<server>__<tool>` (use that form in permission rules and hook matchers).
- Secrets: "Don't put API keys or other secrets in this file, because every person who installs the plugin receives its files." Directory check: a literal credential in MCP headers **Blocks** (`Secret in MCP headers`).
- Directory URL rule: "Give each remote MCP server a `type` of `http`, `sse`, or `ws` and a `url` that is an absolute `https://` or `wss://` URL, a `${user_config.KEY}` reference, or `""` when the plugin has no fixed endpoint" (Blocks otherwise, `MCP server URL is not https`). Declare servers "with `command` and `args` or with `url`, not a `.mcpb` or `.dxt` bundle" (held; blocked for a bundle fetched from URL).
- claude.ai/Cowork behaviour: "On claude.ai and in Cowork, that entry is listed on the plugin's **Connectors** tab, where the user adds or connects it and signs in through your server's OAuth flow." "If your server is already listed in the directory, use the same URL here, so that someone who has both your connector and your plugin sees one set of tools rather than two."
- OAuth in Claude Code: after the plugin loads, `/mcp` in a session shows the server and starts the browser login; `claude mcp login <name>` / `claude mcp logout <name>` from the shell. Pre-registered client credentials can be supplied via `oauth.clientId` and `callbackPort` when the server lacks Dynamic Client Registration.
- Validation of `.mcp.json` by `claude plugin validate` (v2.1.281+): errors for an entry Claude Code would drop, an undeclared `${user_config.KEY}` reference, or a remote `url` that isn't a valid absolute URL; warnings for `http://`/`ws://` to a non-loopback host and header values that look like literal credentials.

## 3. Skills layout and frontmatter (Question 3)

Sources: https://agentskills.io/specification, https://code.claude.com/docs/en/skills, https://claude.com/docs/skills/how-to, https://code.claude.com/docs/en/plugins/components (retrieved 2026-10-19T23:04Z to 23:06Z).

Layout: `skills/<name>/SKILL.md`, one directory per skill. Optional sibling folders `scripts/`, `references/`, `assets/`. The spec: "Keep your main `SKILL.md` under 500 lines. Move detailed reference material to separate files." Reference files should be "one level deep from `SKILL.md`".

Agent Skills spec frontmatter (the portable subset):

| Field | Required | Constraint (verbatim) |
| - | - | - |
| `name` | yes | "Max 64 characters. Lowercase letters, numbers, and hyphens only. Must not start or end with a hyphen." Also no consecutive hyphens; "Must match the parent directory name" |
| `description` | yes | "Max 1024 characters. Non-empty." |
| `license` | no | License name or bundled file reference |
| `compatibility` | no | "Max 500 characters" |
| `metadata` | no | string-to-string map |
| `allowed-tools` | no | space-separated, experimental |

Claude Code skills page, critical compatibility statement: "If you include any field the spec doesn't allow, packaging or upload fails with a hard error." Outside Claude Code (claude.ai uploads, the Skills API) only `name`, `description`, `license`, `compatibility`, `metadata`, and `allowed-tools` are allowed.

Claude Code-only frontmatter (all optional, ignored elsewhere or rejected on upload): `when_to_use`, `argument-hint`, `arguments`, `disable-model-invocation`, `user-invocable`, `disallowed-tools`, `model`, `effort`, `context` (`fork`), `agent`, `background`, `hooks`, `paths`, `shell`. "The combined `description` and `when_to_use` text is truncated at 1,536 characters."

Plugin namespacing: `my-plugin/skills/review/SKILL.md` runs as `/my-plugin:review`; a frontmatter `name` replaces the last segment only. Components page: a SKILL.md at the plugin root with no `skills/` loads as a single skill.

Supporting files and scripts: refer to scripts as `${CLAUDE_SKILL_DIR}/scripts/x.py` ("the skill's subdirectory within the plugin, not the plugin root"). In chat on claude.ai "the skill's whole folder, scripts included, is copied into the code execution sandbox, so also keep the path readable relative to `SKILL.md`". Directory check: "Write valid YAML front matter in each skill, command, and agent file, with `description` as a single text value, not a list" (Blocks on unparseable frontmatter; Warning on none).

Substitutions available in the body: `$ARGUMENTS`, `$ARGUMENTS[N]`, `$N`, `${CLAUDE_SKILL_DIR}`, `${CLAUDE_PROJECT_DIR}`, `${CLAUDE_PLUGIN_ROOT}` (plugin skills only), `${CLAUDE_PLUGIN_DATA}`, `${CLAUDE_SESSION_ID}`, `${CLAUDE_EFFORT}`.

`commands/` is "the older form of skills. Use `skills/` for new plugins." A `CLAUDE.md` at the plugin root "isn't loaded as context, and `claude plugin validate` warns when it finds one."

## 4. `claude plugin validate` (Question 4)

Sources: https://code.claude.com/docs/en/plugins/cli-reference, manifest-reference, troubleshooting (retrieved 23:04Z to 23:06Z); local `claude plugin validate --help` (2026-10-19T23:06Z).

Syntax (docs): `claude plugin validate <path> [options]`

| Flag | Description (verbatim) |
| - | - |
| `--strict` | "Treat warnings as errors, so unrecognized fields and missing metadata that the runtime tolerates fail the run" |
| `--json` | "Output the validation report as one JSON object with the same exit codes. Requires Claude Code v2.1.259 or later" |

Exit codes: "`0` on success and `1` on failure. `validate` adds exit `2` for an unexpected error."

Results: `Validation passed`; `Validation passed with warnings` (loads, but e.g. unknown top-level field, non-kebab name, missing `version`/`description`/`author`; `--strict` turns these into failures); `Validation failed` (type mismatch, missing or escaping path, unknown key in a strict object). Successful last line prints `✔ Validation passed`; failure prints `Found N errors` then `✘ Validation failed`.

What it reads: the manifest at `.claude-plugin/plugin.json` (plugin dir) or `.claude-plugin/marketplace.json` (marketplace dir), or both (v2.1.289+); frontmatter of every skill, agent, and command file; `hooks/hooks.json`; `.mcp.json` and manifest `mcpServers` entries (v2.1.281+). For a marketplace it validates each relative-path plugin's own `plugin.json` and prefixes messages with `plugins[N] plugin.json →`.

Error/warning messages table (troubleshooting page): `File not found: <path>`; `No manifest found in directory. Expected .claude-plugin/marketplace.json or .claude-plugin/plugin.json`; `Invalid JSON syntax: <parse error>`; `Path not found: <path>. The runtime loader will report this as a load failure.`; `Path contains ".." which could be a path traversal attempt: <path>`; `Path is a file; skills entries must be directories containing SKILL.md`; `No frontmatter block found` or `YAML frontmatter failed to parse: <error>`; `Plugin name "<name>" is reserved: it passes as one of Anthropic's own`; `Unknown field '<key>'`; warning `CLAUDE.md at the plugin root is not loaded as project context`; warning on unquoted `${CLAUDE_PLUGIN_ROOT}` in shell-form hook commands.

What it does not check (pre-submission checklist): "It doesn't check the directory's requirements, such as whether you have a README and license or whether the name is taken; the portal's **Validate** checks those." Also doesn't catch fetch errors for marketplace sources, or entry `hooks` written as path/array.

Installed CLI observation (local, 2026-10-19T23:06Z): `claude --version` prints `2.1.123 (Claude Code)`. `claude plugin validate --help` on this machine shows only `-h, --help` (no `--strict`, no `--json`). The official CHANGELOG (https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md, retrieved 23:06Z) tops out at 2.1.304; `--json` was added at 2.1.259, MCP checks at 2.1.281 ("Added MCP server checks to `claude plugin validate`: it reports `.mcp.json` entries that would be silently dropped at load, undeclared `${user_config.*}` references, and insecure URLs"). The exact release that introduced `--strict` was not located in the changelog (first mention is 2.1.295, which already treats it as existing); it is somewhere after 2.1.123.

## 5. `claude --plugin-dir` for development (Question 5)

Sources: https://code.claude.com/docs/en/plugins/create and cli-reference (retrieved 23:05Z); local `claude --help` (23:06Z).

- `claude --plugin-dir ./my-first-plugin` loads a plugin for one session without installing. "Repeat the flag to load several plugins: `claude --plugin-dir ./my-first-plugin --plugin-dir ./other-plugin.zip`". Accepts a directory or a `.zip` archive. Local help text (2.1.123): `--plugin-dir <path>  Load plugins from a directory for this session only (repeatable: --plugin-dir A --plugin-dir B)`.
- A folder of plugins (each child with `.claude-plugin/plugin.json`) loads each child (v2.1.265+). Pointing at a marketplace root does not read `marketplace.json` and loads nothing.
- Plugin appears as `<name>@inline`; the `inline` marketplace name is reserved. A `--plugin-dir` plugin replaces a same-named installed plugin for that session.
- After editing files, run `/reload-plugins` in the session. `/mcp` shows the plugin's server as `plugin:<plugin>:<server>` and lets you authenticate. `/plugin` Installed tab shows the component inventory; Errors tab shows load failures.
- `claude --plugin-dir ./my-plugin plugin list` lists session-only plugins; `claude --plugin-dir <dir> plugin details <name>` prints the component inventory without starting a session.
- The `userConfig` dialog does not appear with `--plugin-dir`; run `/plugin configure <plugin-name>`.
- Related: `--plugin-url <url>` fetches a `.zip` for one session (added 2.1.129); `CLAUDE_CODE_PLUGIN_DIRS` env var (v2.1.280+); `claude plugin init <name>` scaffolds under `~/.claude/skills/<name>/` and auto-loads as `<name>@skills-dir` (added 2.1.157); Agent SDK `plugins` option is the equivalent.
- Trust note: "A plugin you install can run code with your user privileges."

## 6. `marketplace.json` schema and commands (Question 6)

Sources: https://code.claude.com/docs/en/plugins/marketplace-reference, create-marketplace (the `/docs/en/plugin-marketplaces` start URL resolved to this page), publish, host-marketplace, cli-reference (retrieved 23:03Z to 23:06Z); local `claude plugin marketplace --help` (23:06Z).

Location: `.claude-plugin/marketplace.json` in the marketplace root. "The directory that contains `.claude-plugin/` is called the marketplace root, and every relative plugin source resolves from it, not from `.claude-plugin/`."

Top-level fields: `name` (required; "letters, digits, `.`, `_`, and `-`, starting with a letter or digit, and no `..`"), `owner` (required; `name` required, `email` and `url` optional), `plugins` (required array), `$schema`, `description` (validate warns when missing), `version`, `metadata.description`, `metadata.version`, `metadata.pluginRoot` (v2.1.239+), `forceRemoveDeletedPlugins`, `allowCrossMarketplaceDependenciesOn`, `renames`.

Reserved marketplace names include the official list (`claude-plugins-official`, `claude-code-plugins`, `knowledge-work-plugins`, ...), community names, `inline`, `builtin`, `skills-dir`, `synced`, `claude-plugin-test`, `npm`, `pip`, `uv`, `cargo`, `github`, `gh`, JS object member names, anything starting `claudeai-`, impersonating spellings, and the `<owner>-<repo>` download folder of a registered GitHub marketplace.

Plugin entry fields: `name` (required; same character rules), `source` (required), `description`, `version` (plugin.json wins; validate warns on mismatch), `category`, `tags`, `strict` (default true), `relevance`, `dependencies`, `defaultEnabled`, `displayName`, `metadata`, `headers`, `headersHelper`, plus any `plugin.json` field except the directory listing fields. With `plugin.json` present, entry `mcpServers`, `lspServers`, `userConfig`, `channels` do not apply; declare them in `plugin.json`.

Source forms (verbatim examples):

- Relative path: `"source": "./plugins/formatter"` (must start with `./`; `"./"` or `"."` is the root; `..` fails; a URL-hosted marketplace cannot use relative paths)
- GitHub: `{"source": "github", "repo": "your-org/formatter", "ref": "v2.0.0", "sha": "<40-hex>"}`
- Git URL: `{"source": "url", "url": "https://gitlab.example.com/your-group/formatter.git", "ref": "main"}`
- Subdirectory: `{"source": "git-subdir", "url": "https://github.com/your-org/monorepo.git", "path": "tools/formatter"}`
- npm: `{"source": "npm", "package": "@your-org/formatter", "version": "^2.0.0", "registry": "https://..."}`
- Archive (v2.1.224+): `{"source": "archive", "url": "https://.../formatter-2.0.0.zip", "sha256": "<64-hex>"}`
- Command (v2.1.229+): `{"source": "command", "command": "my-tool claude-plugin-path", "timeout": 120}`

Minimal single-repo marketplace (publish page, verbatim):

```json
{
  "name": "your-marketplace",
  "owner": { "name": "Your Name" },
  "plugins": [
    { "name": "deploy-helper", "source": "./" }
  ]
}
```

"Give the entry the same `name` as `plugin.json`" because the entry name is the install id and the manifest name is the component prefix; a mismatch yields `Plugin "<manifest-name>" not found in marketplace`.

Commands (docs + local help):

- `claude plugin marketplace add <source> [--scope user|project|local] [--sparse <paths...>] [--claudeai] [--json]`. Source forms: `owner/repo`, `owner/repo#ref`, `owner/repo@ref` (github); `user@host:path.git` or `https://...git` (git); other https URL (url, fetches marketplace.json only); `./path`, `/path`, `~/path` (directory) or path to `.json` (file). Prints `✔ Successfully added marketplace: <name> (declared in user settings)`.
- `claude plugin install <plugin>@<marketplace> [-s user|project|local] [--config k=v] [-y] [--json] [--marketplace <source>]`. `--marketplace` (one-shot add + install) requires v2.1.292+. Prints `✔ Successfully installed plugin: <name>@<marketplace> (scope: user)`.
- `claude plugin update <plugin>@<marketplace>`; prints `<name> is already at the latest version (1.0.0).` when nothing changed.
- `claude plugin uninstall <plugin> [-s scope] [--keep-data] [--prune] [-y]`.
- `claude plugin enable|disable <plugin>`; `claude plugin list [--json]`; `claude plugin details <name>`.
- `claude plugin marketplace list|remove <name>|update [name]`.
- `claude plugin tag [path] [--push] [--dry-run] [-f] [-m <msg>] [--remote <name>]`: "Create an annotated git tag named `<name>--v<version>` for a plugin release. Before tagging, the command checks that the plugin's `plugin.json` and any marketplace entry that lists it agree on the version." Exits 1 if no `version`, tag exists, or working tree dirty. Present in the local 2.1.123 build; added in 2.1.118 per CHANGELOG.
- In-session equivalents: `/plugin marketplace add ...`, `/plugin install name@marketplace`, `/reload-plugins`, `/plugin` panel.

Local CLI (2.1.123) subcommands available: disable, enable, install, list, marketplace (add/list/remove/update), prune, tag, uninstall, update, validate. Local `install` has only `--scope`; no `--marketplace`, `--config`, `--json`.

Auto-update: off by default for third-party marketplaces; users toggle under `/plugin` Marketplaces or admins set `autoUpdate` in managed settings. Runs after the first message with a random delay of up to ten minutes.

## 7. Versioning, releases, CHANGELOG, LICENSE (Question 7)

Sources: publish, loading, host-marketplace, pre-submission-checklist, cli-reference, knowledge-work-plugins listing (retrieved 23:03Z to 23:06Z).

- "A version string, not checked against semver." Computation order: `plugin.json` `version` first, then marketplace entry `version`, then the source type's fallback (12-char commit SHA for github/url/git-subdir; sha256 prefix for archive; `unknown` for npm or non-git local dir).
- "If you set `version` in `plugin.json` and later push commits without changing it, `claude plugin update` prints `<name> is already at the latest version (1.0.0).` and users keep the old copy. Either increment `version` on every release, or omit it in a git-hosted marketplace so Claude Code uses the commit SHA instead."
- "Don't set `version` in both `plugin.json` and the marketplace entry." Validate warns `Entry declares version "<a>" but <path>/plugin.json says "<b>"`.
- Directory: "If your `plugin.json` sets `version`, raise it with every release." The directory follows a tracked branch or tag; each new commit is scanned as a new version; "A tag stays on its commit until you change the tag."
- Tagging: only needed "when other plugins declare a version range on yours, because those ranges resolve against tags. Otherwise you don't need a tag." Tag format `{name}--v{version}` via `claude plugin tag`, `--push` to send to origin.
- Never rename a published plugin; use `displayName` for labels and the marketplace `renames` map for unavoidable renames.
- `${CLAUDE_PLUGIN_ROOT}` changes on each version (cache path `cache/<marketplace>/<plugin>/<version>/`); durable state belongs in `${CLAUDE_PLUGIN_DATA}`.
- CHANGELOG: no fetched page (publish, host-marketplace, pre-submission-checklist, submit, build, manifest-reference) mentions a CHANGELOG file or requirement. Anthropic's own directory-listed `productivity` plugin folder contains `.claude-plugin/`, `skills/`, `.mcp.json`, `CONNECTORS.md`, `LICENSE`, `README.md` and no CHANGELOG. A web search returned only third-party community skills recommending a CHANGELOG; none are authoritative.
- LICENSE: "Add a `LICENSE` file to the plugin folder, or set `license` in `plugin.json`" (Blocks with `License missing`). README: "at least 40 words in the plugin folder, preferably named `README.md`. Words inside code blocks don't count." (Blocks with `README missing` / `README too short`). The README is shown as the directory listing's description; it should "say what the plugin does, how to use it, and what data it sends." 2.1.295 changelog: validate now prints advice when a README has no install line (never changes exit code).

## 8. ZIP layout for claude.ai, and component support by surface (Question 8)

Sources: https://claude.com/docs/plugins/build, https://claude.com/docs/plugins/platform-support, https://claude.com/docs/plugins/overview, https://claude.com/docs/plugins/pre-submission-checklist, https://claude.com/docs/plugins/submit, https://claude.com/docs/directory/publish (retrieved 23:03Z to 23:06Z).

ZIP upload (build page): "Zip the plugin folder. The archive can hold the folder as its single top-level entry or the folder's contents directly. If the upload says `plugin.json must be at .claude-plugin/plugin.json at the zip root (or inside a single top-level directory)`, the manifest is nested more than one folder deep or the archive has other files beside the plugin folder." Upload path: claude.ai **Customize > Plugins > Add > Upload plugin** (accepts `.zip` or `.plugin`). Limits: "Each plugin can contain up to 5,000 files and 200 MB, and 200 MB is also the largest file that **Upload plugin** accepts." Up to 25 self-added marketplaces per account per org. Marketplaces you add yourself on claude.ai: GitHub and GitHub Enterprise, public GitLab and Bitbucket.

Note: a standalone skill ZIP (not a plugin) must instead contain `<skill-name>/SKILL.md` as its top level (skills/how-to page). Skills are not a directory submission type on their own; "Put them in a bundle."

Directory submission is from a GitHub repository, not a ZIP: "The directory reads plugins from repositories on github.com." Repo may be private during validation/review but "must be public before the listing goes live." Portal fields: Repository (URL or `owner/repo`), Plugin path (optional, for a subfolder), Branch or tag (optional). Submit one plugin folder per submission; 10 submissions per org per 24 h; first org to submit a repo folder owns it. Plan: Pro, Max, Team, or Enterprise; on Team/Enterprise an Owner (or Enterprise custom-role Directory permission). Review: automated validation + security scan on every version, a person reviews a new listing; default is a reviewer publishes each version, with optional auto-publish for later versions. Installs from the directory reach Claude Code as `<name>@synced` (terminal sync v2.1.273+, only when signed in with claude.ai, not with an API key).

Directory file rules (held for reviewer unless noted): every non-image/font file under 256 KiB; at most 512 files; only text, SVG, PNG/JPEG/GIF/WebP, fonts (other binaries held); no `.DS_Store`/`Thumbs.db`/`__MACOSX` (Blocks); repository under 50 MiB archived / 256 MiB unpacked / 10,000 entries, every file under 5 MiB (validation stops otherwise); no symlinks, submodules, or LFS for loaded files; package launchers (`npx`, `uvx`, `uv run`) pinned to exact versions (Blocks) and still held; no `.npmrc`/`uv.toml` registry config; readable (not minified) source; `hooks/hooks.json` valid with known events.

Component support table (platform-support page, verbatim values):

| Component | Chat | Cowork | Claude Code |
| - | - | - | - |
| Skills (`skills/<name>/SKILL.md`) | Loads | Loads | Loads |
| Commands (`commands/*.md`) | Loads as a skill | Loads; `/plugin-name:command` | Loads |
| Agents (`agents/*.md`) | Ignored | Loads | Loads |
| Hooks (`hooks/hooks.json`) | Ignored | Loads | Loads |
| Remote MCP server, `http` or `sse` with fixed URL | Listed on Connectors tab; works once added/connected | Loads; connect from Connectors tab | Loads |
| Local MCP server (command, incl. `.mcpb`) | Ignored | Loads when session runs on your computer | Loads |
| MCP server referencing `${user_config.*}` | Ignored when the URL contains the reference | Ignored when option has no default | Loads; prompts |
| Executables in top-level `bin/` | Can't be installed | Can't be installed | Loads |
| LSP servers, output styles, themes, `settings` | Ignored | Ignored | Loads |

"The portal derives the surfaces it supports from these same rules and shows them to you before you submit."

Bundled connectors on claude.ai (overview page): "Adding a plugin doesn't add a connector to your account or sign you in to anything." The Connectors tab shows Connected / Not connected / Not added; on Team and Enterprise an Owner adds the connector for the organization. "The plugin's skills load whether or not you connect anything."

Connector listing pairing (directory/publish): "If you have a remote MCP server, always submit it as an MCP connector, even when a plugin you're submitting already references it." Connector requirements (connectors/building/submission): remote `https://` URL; OAuth 2.0 for authenticated services; every tool has a `title` and `readOnlyHint` or `destructiveHint`; documentation URL, privacy policy URL, support contact, icon; a reviewer test account; MCPB local listings are deprecated. Default outcome is a Community listing after automated scan.

## 9. Suggested layout for this build (derived from the above)

```text
hardrock-nba-parlay/
├── .claude-plugin/
│   ├── plugin.json           # name, displayName, version, description, author, homepage, repository, license, keywords, privacyPolicyUrl, supportUrl
│   └── marketplace.json      # optional, if this repo is also the Claude Code marketplace: plugins: [{name, source: "./"}]
├── .mcp.json                 # {"mcpServers": {"hardrock-nba-parlay": {"type": "http", "url": "https://<host>/mcp"}}}
├── skills/
│   └── <skill-name>/
│       ├── SKILL.md          # spec-only frontmatter: name (== folder), description
│       └── references/       # optional
├── README.md                 # 40+ words; what it does, how to use, what data it sends
└── LICENSE
```

Avoid: `bin/`, `CLAUDE.md` at root, secrets in `.mcp.json`, Claude Code-only SKILL.md frontmatter fields, unpinned launchers, binary files other than images/fonts, a `version` set in both manifest and marketplace entry.

## 10. Unresolved

1. Exact Claude Code release that introduced `plugin validate --strict` (between 2.1.124 and 2.1.294; not found by grep of the official CHANGELOG). Installed 2.1.123 lacks it.
2. The `claude --plugin-dir` zip-archive support and folder-of-plugins behaviour are documented for current versions (2.1.265+ for folders); not verified on the installed 2.1.123.
3. The MCP docs page's "Scale with MCP tool search" section was cut off (the page is 122k characters); not needed for the format questions but not read.
4. No documented maximum length for `plugin.json` `description`, `displayName`, or `keywords`; only the directory's 64-char `name` cap.
5. Whether the directory accepts an `.mcp.json` `oauth` block (`clientId`, `callbackPort`) without a hold: the productivity plugin ships one, and the checklist's MCP rules do not mention `oauth`, but no page states it explicitly.
6. The skills page remainder (offset 100000 onward) and the `/docs/plugins/quickstart` page were not read.
7. No official statement on CHANGELOG conventions exists; absence was confirmed across the publish, checklist, submit, build, and host-marketplace pages and the Anthropic example plugin, but it is an absence, not a stated rule.

## Sources

| URL | retrieved_at_utc | What it established |
| - | - | - |
| https://code.claude.com/docs/en/plugins | 2026-10-19T23:03Z | Plugin definition, components list, install scopes, note that same format installs on claude.ai/Cowork with a different component subset |
| https://code.claude.com/docs/en/plugins/manifest-reference | 2026-10-19T23:03Z | Full plugin.json field table, name rules, reserved names, path rules, mcpServers shapes, env vars, standard layout, validate results |
| https://code.claude.com/docs/en/plugins/publish | 2026-10-19T23:03Z | Distribution routes, pre-release checklist, single-repo marketplace.json, user commands, directory submission steps, plugin tag, renames |
| https://code.claude.com/docs/en/plugin-marketplaces (resolves to create-marketplace) | 2026-10-19T23:03Z | marketplace.json walkthrough, required fields, relative path rules, entry/manifest name must match, validate output |
| https://claude.com/docs/plugins/build | 2026-10-19T23:03Z | claude.ai plugin folder layout, minimal manifest, .mcp.json http example, README/LICENSE needed, ZIP layout and error text, per-surface testing |
| https://code.claude.com/docs/en/plugins/marketplace-reference | 2026-10-19T23:04Z–23:06Z | Top-level and entry fields, reserved names, every source type with JSON, strict mode, validation messages |
| https://code.claude.com/docs/en/plugins/cli-reference | 2026-10-19T23:04Z–23:06Z | validate flags/exit codes, install/uninstall/update/tag/init/marketplace add flags, --plugin-dir/--plugin-url |
| https://code.claude.com/docs/en/plugins/components | 2026-10-19T23:04Z–23:06Z | Skills/commands/agents/hooks/MCP in plugins, server and tool naming, .mcp.json wrapper optional, CLAUDE.md warning |
| https://code.claude.com/docs/en/mcp | 2026-10-19T23:04Z–23:06Z | http entry fields, type required with url, oauth keys, headersHelper, env expansion, OAuth login flow |
| https://code.claude.com/docs/en/skills | 2026-10-19T23:04Z–23:06Z | Full Claude Code frontmatter table, 1,536-char cap, spec-only fields outside Claude Code, substitutions, namespacing |
| https://claude.com/docs/plugins/platform-support | 2026-10-19T23:04Z–23:06Z | Component support table by app, install/sync/admin comparison, size limits |
| https://claude.com/docs/plugins/pre-submission-checklist | 2026-10-19T23:04Z–23:06Z | Every portal validation and scan check with result level and message titles |
| https://claude.com/docs/plugins/submit | 2026-10-19T23:04Z–23:06Z | GitHub-repo submission flow, private repo rules, limits, update/tracked branch, publish settings, delist |
| https://claude.com/docs/directory/publish | 2026-10-19T23:04Z–23:06Z | Who can submit, plugin bundle vs MCP connector, pairing, review process |
| https://code.claude.com/docs/en/plugins/create | 2026-10-19T23:04Z–23:06Z | First-plugin walkthrough, --plugin-dir workflow, /reload-plugins, test and debug, plugin init |
| https://code.claude.com/docs/en/plugins/loading | 2026-10-19T23:04Z–23:06Z | Version computation order, synced plugins, on-disk paths, auto-update timing, name conflicts |
| https://code.claude.com/docs/en/plugins/host-marketplace | 2026-10-19T23:04Z–23:06Z | Hosting options, auto-update, release-a-new-version rules, renames map, archive auth |
| https://code.claude.com/docs/en/plugins/troubleshooting | 2026-10-19T23:04Z–23:06Z | validate error message table, --plugin-dir pitfalls, skills-missing fix |
| https://code.claude.com/docs/en/plugins/security | 2026-10-19T23:04Z–23:06Z | Official marketplace names, trust model, review steps |
| https://agentskills.io/specification | 2026-10-19T23:04Z–23:06Z | SKILL.md spec: name 64 chars/pattern/must match dir, description 1024, optional fields, folders |
| https://claude.com/docs/skills/how-to | 2026-10-19T23:04Z–23:06Z | Resource folders, ${CLAUDE_SKILL_DIR} per app, standalone skill ZIP layout, skills-ref validate |
| https://claude.com/docs/plugins/overview | 2026-10-19T23:06Z | Upload plugin (.zip/.plugin, folder or contents), bundled connector states, surfaces, updates |
| https://claude.com/docs/connectors/building/submission | 2026-10-19T23:06Z | Connector submission requirements, portal steps, Community default |
| https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md | 2026-10-19T23:06Z | Latest 2.1.304; plugin tag 2.1.118; --plugin-url 2.1.129; plugin init 2.1.157; validate --json 2.1.259; MCP checks 2.1.281; install --marketplace 2.1.292 |
| https://raw.githubusercontent.com/anthropics/knowledge-work-plugins/main/productivity/.claude-plugin/plugin.json | 2026-10-19T23:06Z | Real directory-listed manifest: name, version, description, author only |
| https://raw.githubusercontent.com/anthropics/knowledge-work-plugins/main/productivity/.mcp.json | 2026-10-19T23:06Z | Real remote-only .mcp.json with type/url and one oauth block |
| https://github.com/anthropics/knowledge-work-plugins/tree/main/productivity | 2026-10-19T23:06Z | Folder has README.md, LICENSE, CONNECTORS.md, .mcp.json, skills/, .claude-plugin/; no CHANGELOG |
| https://raw.githubusercontent.com/anthropics/knowledge-work-plugins/main/.claude-plugin/marketplace.json | 2026-10-19T23:06Z | 123 entries; name knowledge-work-plugins; owner Anthropic; mix of relative and git-subdir sources |
| local: `claude --version`, `claude plugin ... --help` | 2026-10-19T23:06Z | Installed 2.1.123; validate has no --strict; tag exists with --push/--dry-run/-f/-m/--remote; install has only --scope |
