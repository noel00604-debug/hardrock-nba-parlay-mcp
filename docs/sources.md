# Sources: every URL consulted, retrieval times, package versions

Compiled 2026-10-19 (America/New_York evening) by the release module from the Sources tables in
`docs/research/*.md`. Rows are copied verbatim from each note; the retrieval time column is the
note's own (UTC). Web content was read as data. Where a note recorded a probe result (HTTP 403,
timeout, 404), that is what the row says; nothing here was re-fetched when this file was compiled.

Local tool versions on the development Mac at compile time: Claude Code 2.1.123, uv 0.13.1,
Python 3.12.15 (project venv), macOS Darwin 27.0.0, Apple M5, 16 GiB RAM. Docker and cloudflared
are not installed.

## anthropic-policies.md

Note title: Anthropic policies as applied to sports-betting research software

| Source | Retrieved (UTC) | What it established |
|---|---|---|
| https://support.claude.com/en/articles/13145358-anthropic-software-directory-policy | 2026-10-19T23:04:22Z | Directory Policy text; page date April 15, 2026; sections 1 to 5 incl. 4.A financial-transactions clause; silent on gambling/age |
| https://support.claude.com/en/articles/13145338-anthropic-software-directory-terms | 2026-10-19T23:04:22Z | Directory Terms text; page date March 16, 2026; warranties, privacy policy duty, indemnity, removal, security reporting, no endorsement |
| https://www.anthropic.com/legal/aup | 2026-10-19T23:04:23Z | Usage Policy labeled "Effective November 12, 2026"; new High-risk wording, Finance definition, Exclusions, disclosure, directory cross-reference; "Previous Version" link |
| https://www.anthropic.com/legal/archive/22742366-2ef0-4c7a-a833-6523f10d3944 | 2026-10-19T23:05:07Z | Usage Policy "Effective September 15, 2025" (in force today); High-Risk Finance definition, qualified-professional review, disclosure; "replaced" banner |
| https://www.anthropic.com/news/2026-usage-policy-update | 2026-10-19T23:04:23Z | Post dated Oct 8, 2026; "takes effect on November 12"; high-risk requirements unchanged but rewritten to list covered/uncovered recommendations |
| https://support.claude.com/en/articles/11697096-anthropic-mcp-directory-policy | 2026-10-19T23:06:42Z | Prior MCP Directory Policy is a stub: consolidated into the Software Directory Policy |
| https://support.claude.com/en/articles/12005017-using-agents-according-to-our-usage-policy | 2026-10-19T23:07:00Z | Agents article (March 16, 2026): prohibits agents engaging in unauthorized/illegal/fraudulent financial transactions or payment processing |
| https://support.claude.com/en/articles/9307344-responsible-use-of-anthropic-s-models-guidelines-for-organizations-serving-minors | 2026-10-19T23:07:01Z | Minors guidance (March 16, 2026): age verification listed as a measure for products serving minors; no gambling text |
| https://www.anthropic.com/legal/consumer-terms | 2026-10-19T23:07:02Z | Consumer Terms "Effective October 8, 2025": minimum age 18 or local age of consent, whichever is higher |

9 rows.

## claude-code-client-mcp.md

Note title: Research notes: claude-code-client-mcp

| Source | Retrieved (UTC) | What it established |
|---|---|---|
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

21 rows.

## claude-code-plugins.md

Note title: Research notes: Claude Code plugin bundle format, validation, marketplaces

| Source | Retrieved (UTC) | What it established |
|---|---|---|
| - | - | - |
| https://code.claude.com/docs/en/plugins | 2026-10-19T23:03Z | Plugin definition, components list, install scopes, note that same format installs on claude.ai/Cowork with a different component subset |
| https://code.claude.com/docs/en/plugins/manifest-reference | 2026-10-19T23:03Z | Full plugin.json field table, name rules, reserved names, path rules, mcpServers shapes, env vars, standard layout, validate results |
| https://code.claude.com/docs/en/plugins/publish | 2026-10-19T23:03Z | Distribution routes, pre-release checklist, single-repo marketplace.json, user commands, directory submission steps, plugin tag, renames |
| https://code.claude.com/docs/en/plugin-marketplaces (resolves to create-marketplace) | 2026-10-19T23:03Z | marketplace.json walkthrough, required fields, relative path rules, entry/manifest name must match, validate output |
| https://claude.com/docs/plugins/build | 2026-10-19T23:03Z | claude.ai plugin folder layout, minimal manifest, .mcp.json http example, README/LICENSE needed, ZIP layout and error text, per-surface testing |
| https://code.claude.com/docs/en/plugins/marketplace-reference | 2026-10-19T23:04Z to 23:06Z | Top-level and entry fields, reserved names, every source type with JSON, strict mode, validation messages |
| https://code.claude.com/docs/en/plugins/cli-reference | 2026-10-19T23:04Z to 23:06Z | validate flags/exit codes, install/uninstall/update/tag/init/marketplace add flags, --plugin-dir/--plugin-url |
| https://code.claude.com/docs/en/plugins/components | 2026-10-19T23:04Z to 23:06Z | Skills/commands/agents/hooks/MCP in plugins, server and tool naming, .mcp.json wrapper optional, CLAUDE.md warning |
| https://code.claude.com/docs/en/mcp | 2026-10-19T23:04Z to 23:06Z | http entry fields, type required with url, oauth keys, headersHelper, env expansion, OAuth login flow |
| https://code.claude.com/docs/en/skills | 2026-10-19T23:04Z to 23:06Z | Full Claude Code frontmatter table, 1,536-char cap, spec-only fields outside Claude Code, substitutions, namespacing |
| https://claude.com/docs/plugins/platform-support | 2026-10-19T23:04Z to 23:06Z | Component support table by app, install/sync/admin comparison, size limits |
| https://claude.com/docs/plugins/pre-submission-checklist | 2026-10-19T23:04Z to 23:06Z | Every portal validation and scan check with result level and message titles |
| https://claude.com/docs/plugins/submit | 2026-10-19T23:04Z to 23:06Z | GitHub-repo submission flow, private repo rules, limits, update/tracked branch, publish settings, delist |
| https://claude.com/docs/directory/publish | 2026-10-19T23:04Z to 23:06Z | Who can submit, plugin bundle vs MCP connector, pairing, review process |
| https://code.claude.com/docs/en/plugins/create | 2026-10-19T23:04Z to 23:06Z | First-plugin walkthrough, --plugin-dir workflow, /reload-plugins, test and debug, plugin init |
| https://code.claude.com/docs/en/plugins/loading | 2026-10-19T23:04Z to 23:06Z | Version computation order, synced plugins, on-disk paths, auto-update timing, name conflicts |
| https://code.claude.com/docs/en/plugins/host-marketplace | 2026-10-19T23:04Z to 23:06Z | Hosting options, auto-update, release-a-new-version rules, renames map, archive auth |
| https://code.claude.com/docs/en/plugins/troubleshooting | 2026-10-19T23:04Z to 23:06Z | validate error message table, --plugin-dir pitfalls, skills-missing fix |
| https://code.claude.com/docs/en/plugins/security | 2026-10-19T23:04Z to 23:06Z | Official marketplace names, trust model, review steps |
| https://agentskills.io/specification | 2026-10-19T23:04Z to 23:06Z | SKILL.md spec: name 64 chars/pattern/must match dir, description 1024, optional fields, folders |
| https://claude.com/docs/skills/how-to | 2026-10-19T23:04Z to 23:06Z | Resource folders, ${CLAUDE_SKILL_DIR} per app, standalone skill ZIP layout, skills-ref validate |
| https://claude.com/docs/plugins/overview | 2026-10-19T23:06Z | Upload plugin (.zip/.plugin, folder or contents), bundled connector states, surfaces, updates |
| https://claude.com/docs/connectors/building/submission | 2026-10-19T23:06Z | Connector submission requirements, portal steps, Community default |
| https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md | 2026-10-19T23:06Z | Latest 2.1.304; plugin tag 2.1.118; --plugin-url 2.1.129; plugin init 2.1.157; validate --json 2.1.259; MCP checks 2.1.281; install --marketplace 2.1.292 |
| https://raw.githubusercontent.com/anthropics/knowledge-work-plugins/main/productivity/.claude-plugin/plugin.json | 2026-10-19T23:06Z | Real directory-listed manifest: name, version, description, author only |
| https://raw.githubusercontent.com/anthropics/knowledge-work-plugins/main/productivity/.mcp.json | 2026-10-19T23:06Z | Real remote-only .mcp.json with type/url and one oauth block |
| https://github.com/anthropics/knowledge-work-plugins/tree/main/productivity | 2026-10-19T23:06Z | Folder has README.md, LICENSE, CONNECTORS.md, .mcp.json, skills/, .claude-plugin/; no CHANGELOG |
| https://raw.githubusercontent.com/anthropics/knowledge-work-plugins/main/.claude-plugin/marketplace.json | 2026-10-19T23:06Z | 123 entries; name knowledge-work-plugins; owner Anthropic; mix of relative and git-subdir sources |
| local: `claude --version`, `claude plugin ... --help` | 2026-10-19T23:06Z | Installed 2.1.123; validate has no --strict; tag exists with --push/--dry-run/-f/-m/--remote; install has only --scope |

30 rows.

## claude-directory-connectors.md

Note title: Research notes: Claude directory publishing, connector building, claude.ai plugin editor/upload

| Source | Retrieved (UTC) | What it established |
|---|---|---|
| https://claude.com/docs/directory/publish | 2026-10-19T23:03Z | Two submission kinds; who can submit (Pro/Max from own account); plugin from GitHub public before go-live; submit server as connector too; pairing; same URL dedupes tools; review overview; "Review time isn't fixed"; MCPB deprecated |
| https://claude.com/docs/connectors/building/index | 2026-10-19T23:03Z | Streamable HTTP recommended, SSE legacy; OAuth spec versions; DCR; callback URL; limits table (150k chars, 240 s; 25k tokens); unsupported MCP features; distribution options |
| https://claude.com/docs/build/overview | 2026-10-19T23:03Z | Plugin = connector + skills (+ apps, commands, agents); build/publish step order; tooling (claude plugin validate, --plugin-dir, plugin eval, mcp-server-dev) |
| https://claude.com/docs/plugins/build | 2026-10-19T23:03Z | Folder layout; manifest fields; .mcp.json example; Connectors tab; what each app loads; ZIP upload steps and error text; test on each surface |
| https://support.claude.com/en/articles/10949351-getting-started-with-local-mcp-servers-on-claude-desktop | 2026-10-19T23:03Z | Article now covers MCPB desktop extensions (Settings > Extensions > Advanced > Install Extension…); not claude_desktop_config.json |
| https://claude.com/docs/plugins/pre-submission-checklist | 2026-10-19T23:04Z | Validation results (Blocks/Held/Warning/Note); README 40 words; license; name rules; file limits; launcher pinning; secrets; .mcp.json schema; security scan |
| https://claude.com/docs/plugins/submit | 2026-10-19T23:04Z | Portal steps (Source, Listing details, Data handling, Compliance, Review and submit); GitHub connection; private repo rules; 10 submissions/24 h; publish settings; update/withdraw/delist |
| https://claude.com/docs/connectors/building/review-criteria | 2026-10-19T23:04Z | Read/write split; title + readOnlyHint/destructiveHint; 64-char names; prompt-injection rules; API ownership; unsupported use cases (money transfer, AI media); test credentials; public docs |
| https://claude.com/docs/connectors/building/submission | 2026-10-19T23:04Z | Connector portal steps and field limits; listing materials; test account; seven acknowledgements; Community default; screenshots only for MCP Apps; mcp-review@anthropic.com |
| https://claude.com/docs/connectors/building/authentication | 2026-10-19T23:04Z | Auth types table; DCR/CIMD rules; PKCE S256; discovery via 401 + resource_metadata; redirect URIs; token endpoint and latency rules; egress 160.79.104.0/21 |
| https://claude.com/docs/plugins/platform-support | 2026-10-19T23:04Z | Component support table by Chat/Cowork/Claude Code; sync direction; upload limits (5,000 files, 200 MB); Discover availability |
| https://claude.com/docs/plugins/create-with-claude | 2026-10-19T23:04Z | Add menu: Create with Claude vs Create a plugin (form + editor); account-only plugins can't be submitted as-is; export to GitHub to submit |
| https://claude.com/docs/plugins/overview | 2026-10-19T23:04Z | Install paths; Bundled connectors states (Connected/Not connected/Not added); surfaces; Upload plugin accepts .zip or .plugin |
| https://claude.com/docs/directory/submission-status | 2026-10-19T23:04Z | Plugin and connector status tables; "Approved doesn't mean people can install"; contact channels |
| https://claude.com/docs/connectors/building/testing | 2026-10-19T23:04Z | Test as custom connector in production; tunnel for local; MCP Inspector CLI; test credentials must be fully populated; debug causes |
| https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp | 2026-10-19T23:04Z | Availability (Claude, Cowork, Desktop; Free = 1); Pro/Max add steps; OAuth client options; local servers not in Cowork/claude.ai; Advanced research can't call local MCP |
| https://claude.com/docs/connectors/building/directory-vs-custom | 2026-10-19T23:04Z | Same runtime; install link format; listing URL format; MCP Registry does not surface in Claude |
| https://claude.com/docs/connectors/custom/add-unlisted | 2026-10-19T23:05Z | Add-by-URL steps per plan; Authentication and OAuth client settings; request headers (beta); transport; can't edit auth after add; .mcpb install |
| https://claude.com/docs/connectors/verification | 2026-10-19T23:05Z | Verified vs Community vs Custom labels; escalation automatic |
| https://claude.com/docs/connectors/building/lazy-authentication | 2026-10-19T23:05Z | 401-before-SDK gate; canonical header; PRM/AS metadata examples; CIMD values; loopback port-agnostic matching; 403 step-up; discovery cache ~5 min; Claude Code localhost testing |
| https://claude.ai/oauth/claude-code-client-metadata | 2026-10-19T23:05Z | Claude Code CIMD JSON: redirect_uris localhost/127.0.0.1 /callback; token_endpoint_auth_method none |
| https://code.claude.com/docs/en/mcp | 2026-10-19T23:05Z | claude mcp add --transport http; .mcp.json types; scopes and precedence; /mcp OAuth; --callback-port; env expansion; MAX_MCP_OUTPUT_TOKENS; maxResultSizeChars; requiresUserInteraction |
| https://code.claude.com/docs/en/plugins/manifest-reference | 2026-10-19T23:05Z | Full plugin.json fields incl. directory listing fields (icon, documentationUrl, supportUrl, privacyPolicyUrl, termsOfServiceUrl); reserved names; userConfig; standard layout |
| https://claude.com/docs/cowork/guide/plugins | 2026-10-19T23:05Z | Cowork install/upload; Connectors tab after install; limits table |
| https://claude.com/docs/plugins/quickstart | 2026-10-19T23:05Z | End-to-end example incl. git push and submit; system files to remove |
| https://claude.com/docs/connectors/building/after-publishing | 2026-10-19T23:05Z | Update by pushing to tracked branch; listing URL permanent; Usage tab; delist |
| https://support.claude.com/en/articles/13145358-anthropic-software-directory-policy | 2026-10-19T23:05Z | Effective 2026-04-15; 4A financial transactions; 3A to 3H developer requirements (privacy policy, support, docs, test account, three use cases); 5D OAuth 2.0; annotations; no gambling mention |
| https://support.claude.com/en/articles/13837440-use-plugins-in-claude | 2026-10-19T23:06Z | Plugins on all paid plans; surfaces; Claude Code sync v2.1.273+; upload custom plugin file; no editor control labels |
| https://claude.com/docs/plugins/share | 2026-10-19T23:06Z | Account-plugin distribution options; .plugin file upload route; Team/Enterprise sharing |
| https://claude.com/docs/skills/how-to | 2026-10-19T23:06Z | SKILL.md frontmatter rules (name 64 chars, description 1,024 chars), 500-line guidance, folders, ${CLAUDE_SKILL_DIR}, skills-ref validate |
| https://code.claude.com/docs/en/plugins/publish | 2026-10-19T23:06Z | Own marketplace (marketplace.json), install commands, claude-plugins-official not via portal, synced plugins |
| https://claude.com/docs/connectors/building/managing-your-listing | 2026-10-19T23:06Z | Connector dashboard, health badge, editable fields, slug locked |
| https://modelcontextprotocol.io/docs/develop/connect-local-servers | 2026-10-19T23:06Z | claude_desktop_config.json path, Developer > Edit Config, JSON shape, restart, logs |
| https://support.claude.com/en/articles/11176164-use-connectors-to-extend-claude-s-capabilities | 2026-10-19T23:06Z | Connector availability incl. mobile beta; tool permissions |
| https://claude.com/docs/skills/overview | 2026-10-19T23:07Z | Skills on paid plans; code execution required; Customize > Skills |
| https://claude.com/docs/extend/overview | 2026-10-19T23:07Z | Customize page overview; availability across chat/desktop/mobile/Cowork/Claude Code |
| WebSearch (claude.com/api/mcp/auth_callback) | 2026-10-19T23:06Z | Only third-party vendor docs mention the claude.com variant; official docs give claude.ai only |

37 rows.

## hard-rock-house-rules.md

Note title: Hard Rock Bet (Florida) House Rules: parlays, SGP, OT, DNP, voids, repricing, cash-out

| Source | Retrieved (UTC) | What it established |
|---|---|---|
| https://www.hardrock.bet/all-house-rules/ | 2026-10-19T23:04Z | Index page only; links state pages incl. `/fl/house-rules/`; "sport-specific rules ... take precedence over the General Rules" |
| https://www.hardrock.bet/fl/house-rules/ | 2026-10-19T23:06Z | WordPress wrapper; static HTML shows "Content loading…"; `data-doc-id="1LohHmj-8bnU9wnJO8yMsi6Ttvee_EZf3RWg4bfUul7s"`; JSON-LD dateModified 2025-12-26 |
| https://www.hardrock.bet/wp-content/cache/min/1/wp-content/themes/salient-child/footer-scripts/google-legal-scripts.js | 2026-10-19T23:07Z | Loader fetches `https://docs.google.com/document/d/${docId}/export?format=html` into `.legal-doc-content` |
| https://docs.google.com/document/d/1LohHmj-8bnU9wnJO8yMsi6Ttvee_EZf3RWg4bfUul7s/export?format=txt | 2026-10-19T23:07:18Z | Full Florida house rules text ("Seminole Gaming House Rules: Mobile and Online Sports Betting"); Parts A-D; all rule quotes above; no version/effective date in doc; no Last-Modified header |
| https://www.hardrock.bet/t-cs/ | 2026-10-19T23:05Z | T&Cs landing; links `/t-cs/florida`; "operated and controlled by Hard Rock Digital" (generic text) |
| https://www.hardrock.bet/t-cs/florida/ | 2026-10-19T23:07Z | Wrapper page; `data-doc-id="1TIC_NVrfOURrYrJhJYeNZFVRXtivwRn5tiktKtM8Xnw"`; Cloudflare blocks bare curl |
| https://docs.google.com/document/d/1TIC_NVrfOURrYrJhJYeNZFVRXtivwRn5tiktKtM8Xnw/export?format=txt | 2026-10-19T23:07:49Z | Florida Terms of Service; Seminole Tribe of Florida d/b/a Seminole Gaming; STGC/Compact; 21+; physical presence; GeoComply; §1.6 precedence; §19 Errors; "Effective September 8, 2026" |
| https://www.hardrock.bet/sportsbook/same-game-parlay/ | 2026-10-19T23:04Z and 23:08Z | "Updated: Dec 15, 2025 2:36 PM EST"; min 2 / max 20 bets; push leg removed and odds recalculated; cash out at discretion; no pricing-method statement |
| https://www.hardrock.bet/sportsbook/parlay/ | 2026-10-19T23:05Z | "Updated: Jul 30, 2026 5:02 PM EDT"; minimum two bets; pushed leg removed, odds recalculated; no max/payout cap stated; bets cannot be cancelled; Parlay Insurance example |
| https://www.hardrock.bet/sportsbook/push/ | 2026-10-19T23:05Z | "Updated: Sep 25, 2026 9:00 AM EDT"; push = leg "removed (voided)", odds recalculated; multiple pushes same; NBA cannot tie; example text/table inconsistency |
| https://www.hardrock.bet/news/introducing-same-game-parlay-max/ | 2026-10-19T23:05Z | "Updated: Jan 5, 2026 8:24 PM EST"; SGP Max up to 20 bets across app; play-by-play markets "can't be included in SGPs"; 21+ |
| https://www.hardrock.bet/florida/ | 2026-10-19T23:04Z | "Page updated: September 23, 2026"; "Offered by the Seminole Tribe of Florida in FL"; 21+; GeoComply on desktop; Bonus Bets expire 7 days, stake excluded; promos exclude Bonus Bets/Boosts/Round Robins/Early Cash Out; 1-833-PLAYWISE |
| https://www.hardrock.bet/sportsbook/player-injury-insurance/ | 2026-10-19T23:06Z | "Updated: Sep 23, 2026 10:43 AM EDT"; NBA period 10/1/2026-8/1/2027; 1st-half injury, no return; only losing leg; settles as loser + Bonus Bet refund within 48h; excludes unders, cash out, boosts, round robins; FL by Seminole Tribe |
| https://www.hardrock.bet/sportsbook/prop-bet/ | 2026-10-19T23:06Z | "Updated: Sep 25, 2026 9:01 AM EDT"; explainer only; no DNP/OT/minutes rules |
| https://www.hardrock.bet/help-center/ | 2026-10-19T23:05Z | Navigation only; no cash-out, void, or settlement articles found |
| https://www.hardrock.bet/nj/house-rules/ | 2026-10-19T23:06Z | Same "Content loading…" pattern (not read further; out of scope) |

16 rows.

## hosting-options.md

Note title: Hosting options for the hosted MCP server (research notes)

| Source | Retrieved (UTC) | What it established |
|---|---|---|
| https://fly.io/docs/about/pricing/ | 2026-10-19 23:12 | 301 redirect to https://docs.fly.io/about/pricing |
| https://docs.fly.io/about/pricing | 2026-10-19 23:13 and 23:15 | shared-cpu-1x 256MB $2.19, 512MB $3.69, 1GB $6.70 (iad); no free tier; trial 2 h / 7 days; MPG from $38; volumes $0.15/GB; egress $0.02/GB NA; certs first 10 free then $0.10; dedicated IPv4 $2; unmanaged PG about $2; support tiers |
| https://docs.fly.io/launch/autostop-autostart/ | 2026-10-19 23:15 | fly launch defaults auto_stop "stop", min_machines_running 0; how to keep always-on; stopped rootfs billing |
| https://docs.fly.io/about/free-trial | 2026-10-19 23:15 | trial contents; payment method needed to continue; apps stop at trial end |
| https://docs.fly.io/postgres | 2026-10-19 23:15 | MPG plans Basic $38 (1 GB) to Performance $1,922; storage $0.28/GB; HA, backups, pooling included |
| https://docs.fly.io/reference/regions | 2026-10-19 23:15 and 23:17 | 17 regions; US: iad, ewr, ord, dfw, lax, sjc; no mia/atl; MPG regions |
| https://docs.fly.io/networking/custom-domain/ | 2026-10-19 23:15 | fly certs add; automatic Let's Encrypt certs; fly.dev subdomain |
| https://docs.fly.io/postgres/getting-started/what-you-should-know/ | 2026-10-19 23:18 | unmanaged Fly Postgres archived/unsupported; daily snapshots; single-node data-loss warning |
| https://docs.fly.io/volumes/overview/ | 2026-10-19 23:18 | volume on one server; two volumes recommended; daily snapshots kept 5 days (1 to 60) |
| https://railway.com/pricing | 2026-10-19 23:12 | plans Free/Hobby/Pro and credits; per-second rates for memory, CPU, volumes; egress $0.05/GB; per-plan limits |
| https://docs.railway.com/reference/pricing/plans | 2026-10-19 23:13 | included usage semantics; overage billed as delta; post-paid card required; per-plan RAM/vCPU caps |
| https://docs.railway.com/reference/app-sleeping | 2026-10-19 23:13 | Serverless sleep after about 5 min inactivity; 502 on first wake |
| https://docs.railway.com/pricing/cost-control | 2026-10-19 23:15 | Serverless is a toggle under Deploy; hard/soft usage limits (hard min $10) |
| https://docs.railway.com/pricing/faqs | 2026-10-19 23:15 | usage billed in arrears; Hobby $5 includes $5 usage, excess charged |
| https://docs.railway.com/pricing/free-trial | 2026-10-19 23:17 | $5 one-time trial, then Free plan with $1/month; trial volumes deleted 30 days after credits expire |
| https://docs.railway.com/reference/regions | 2026-10-19 23:13 | us-east4-eqdc4a Virginia and other regions |
| https://docs.railway.com/reference/databases | 2026-10-19 23:13 | Postgres template; data persisted via attached Volume |
| https://docs.railway.com/databases/postgresql | 2026-10-19 23:15 | single node Railway maintains; private DATABASE_URL; HA optional; backups + PITR available |
| https://docs.railway.com/reference/backups | 2026-10-19 23:13 | daily/weekly/monthly schedules and retention; incremental billing at volume rate; restore steps |
| https://docs.railway.com/networking/public-networking | 2026-10-19 23:15 | free auto-renewed SSL; .railway.app domain; custom domain CNAME + TXT |
| https://docs.railway.com/builds/dockerfiles | 2026-10-19 23:15 | Dockerfile auto-detected at root; RAILWAY_DOCKERFILE_PATH |
| https://docs.railway.com/deployments/github-autodeploys | 2026-10-19 23:20 | auto-deploy on push to connected branch |
| https://docs.railway.com/networking/specs-limits | 2026-10-19 23:20 | 404 (request timeout limits not confirmed) |
| https://render.com/pricing | 2026-10-19 23:13 | page is JS-rendered; headings only |
| https://render.com/pricing.md | 2026-10-19 23:15 | workspace plans; 0.5c-512mb $7; Postgres 0.1c-256mb $6 with 1 GB included, $0.30/GB extra; disk $0.25/GB; bandwidth overage $0.15/GB |
| https://render.com/docs/free | 2026-10-19 23:13 | free web service spin-down after 15 min, about 1 min cold start; free Postgres expires after 30 days; not for production |
| https://render.com/docs/postgresql-backups | 2026-10-19 23:15 | PITR 3 days (Hobby) / 7 days (Pro) for paid DBs; logical backups 7 days; Free has none |
| https://render.com/docs/custom-domains | 2026-10-19 23:15 | automatic TLS incl. wildcard; 2 custom domains on Hobby; $0.25/month extra |
| https://render.com/docs/docker | 2026-10-19 23:15 | Dockerfile builds from repo; prebuilt images |
| https://render.com/docs/regions | 2026-10-19 23:13 | Oregon, Ohio, Virginia, Frankfurt, Singapore |
| https://neon.com/pricing | 2026-10-19 23:12 | Free/Launch/Scale details, rates, history windows, no card for Free, no minimum on paid |
| https://neon.com/docs/introduction/plans | 2026-10-19 23:13 | CU definition (~4 GB RAM), 0.25 CU minimum, scale-to-zero rules per plan |
| https://neon.com/docs/introduction/scale-to-zero | 2026-10-19 23:15 | 5-minute default; restart within a few hundred milliseconds; Free cannot disable |
| https://neon.com/docs/introduction/regions | 2026-10-19 23:13 | aws-us-east-1, aws-us-east-2 etc.; Azure deprecated; region fixed per project |
| https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/ | 2026-10-19 23:12 and 23:13 | quick tunnel: no account/domain; 200 in-flight; no SSE; no uptime guarantee; hostname changes; canonical URL now /tunnel/get-started/quick-tunnels/ |
| https://try.cloudflare.com/ | 2026-10-19 23:17 | "Automatic HTTPS"; example https://quiet-marble-otter.trycloudflare.com; "Ends with the process" |
| https://developers.cloudflare.com/tunnel/get-started/ | 2026-10-19 23:13 | named tunnel prerequisites: Cloudflare account, domain on Cloudflare; public hostname routing; port 7844 |
| https://developers.cloudflare.com/tunnel/ | 2026-10-19 23:15 | "Available on all plans" |
| https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/ | 2026-10-19 23:17 | Cloudflare One tunnel docs (private networking focus); no pricing statement |
| https://www.cloudflare.com/plans/free/ | 2026-10-19 23:15 | Free plan exists ("Sign Up Free"); no tunnel mention |
| https://www.cloudflare.com/plans/zero-trust-services/ | 2026-10-19 23:13 | page content not rendered; no numbers obtained |
| https://www.cloudflare.com/products/registrar/ | 2026-10-19 23:17 | "does not mark up domain prices at all"; no per-TLD prices listed |
| https://www.cloudflare.com/tld-policies/ | 2026-10-19 23:17 | registry operators only; no prices |
| https://blog.cloudflare.com/a-free-argo-tunnel-for-your-next-project/ | 2026-10-19 23:15 | 2019 post: free tunnels for testing/development, not production |
| https://raw.githubusercontent.com/cloudflare/cloudflared/master/README.md | 2026-10-19 23:17 | TryCloudflare mentioned; no example URL |
| https://ngrok.com/pricing | 2026-10-19 23:17 | Free: 3 endpoints, 1 dev domain, 1 GB, 20k requests, interstitial; Hobbyist $10/month |
| https://support.claude.com/en/articles/11175166-getting-started-with-custom-connectors-using-remote-mcp | 2026-10-19 23:13 | custom connectors on all plans (Free limited to one); connections come from Anthropic's cloud; must be publicly reachable |
| https://claude.com/docs/connectors/building/index | 2026-10-19 23:15 | remote server hosted by you; Streamable HTTP; 150k char result limit; 240 s tool timeout; redirect URI https://claude.ai/api/mcp/auth_callback |
| https://claude.com/docs/connectors/building/testing | 2026-10-19 23:17 | tunnel with Cloudflare Tunnel or ngrok; keep auth on; Inspector CLI; connection-failure causes |
| https://modelcontextprotocol.io/specification/2025-06-18/basic/transports | 2026-10-19 23:13 | server may answer POST with JSON or SSE; client must support both; GET stream optional; Origin validation |
| https://py.sdk.modelcontextprotocol.io/ and /llms.txt | 2026-10-19 23:17 | v2 is current stable line; docs index |
| https://py.sdk.modelcontextprotocol.io/run/ | 2026-10-19 23:17 | run(transport="streamable-http"), json_response=True (single JSON body instead of SSE), stateless_http, limits |
| https://py.sdk.modelcontextprotocol.io/run/deploy/ | 2026-10-19 23:18 | DNS-rebinding default rejects requests behind a real hostname; allowed_hosts; proxy headers; sessionless modern protocol (page labels it 2026-07-28) |
| https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/main/README.md | 2026-10-19 23:15 | README defers to py.sdk.modelcontextprotocol.io; `mcp run server.py --transport streamable-http` |
| WebSearch (render pricing; cloudflare free plan) | 2026-10-19 23:13 and 23:17 | located render.com/pricing.md; third-party claims about Zero Trust "50 users" not used as findings |

55 rows.

## mcp-python-sdk-auth.md

Note title: Research notes: MCP Python SDK (version, Streamable HTTP, OAuth AS/RS, annotations, structured output)

| Source | Retrieved (UTC) | What it established |
|---|---|---|
| https://py.sdk.modelcontextprotocol.io/ | 2026-10-19T23:04Z | v2 is the current stable line; `MCPServer` quickstart; Python 3.11+; doc section map |
| https://pypi.org/project/mcp/ | 2026-10-19T23:04Z | mcp 2.3.0 released Oct 2, 2026; `cli` extra; links |
| https://pypi.org/pypi/mcp/json (curl) | 2026-10-19T23:05Z | version 2.3.0, `requires_python >=3.10`, full `requires_dist`, upload timestamps for 1.23.2 through 2.3.0 |
| https://github.com/modelcontextprotocol/python-sdk | 2026-10-19T23:04Z | README uses `MCPServer`; MIT license; doc links |
| https://github.com/modelcontextprotocol/python-sdk/tree/main/examples/servers/simple-auth | 2026-10-19T23:04Z | AS/RS split example overview, ports, `--oauth-strict`, legacy mode |
| https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/main/examples/servers/simple-auth/{README.md,pyproject.toml,mcp_simple_auth/server.py,auth_server.py,token_verifier.py,simple_auth_provider.py,legacy_as_server.py} | 2026-10-19T23:05Z | Exact example code: credential-based AS (not GitHub), `/introspect`, `IntrospectionTokenVerifier`, RS `AuthSettings` usage, legacy combined server |
| https://modelcontextprotocol.io/specification/latest/basic/authorization | 2026-10-19T23:04Z | Resolves to 2026-07-28; OAuth 2.1 draft-13 basis; MUST/SHOULD list; RFC 8707 `resource`; token handling; 401/403/400; scope strategy |
| https://modelcontextprotocol.io/specification/latest/basic/authorization/authorization-server-discovery | 2026-10-19T23:05Z | PRM MUST; `WWW-Authenticate` or well-known paths; RFC 8414/OIDC discovery order; issuer validation |
| https://modelcontextprotocol.io/specification/latest/basic/authorization/client-registration | 2026-10-19T23:05Z | CIMD SHOULD; DCR deprecated/MAY; priority order; `application_type`; AS binding |
| https://modelcontextprotocol.io/specification/latest/basic/authorization/security-considerations | 2026-10-19T23:05Z | PKCE S256 MUST; `code_challenge_methods_supported` check; audience validation; no passthrough; HTTPS; redirect rules |
| https://modelcontextprotocol.io/specification/latest/server/tools | 2026-10-19T23:04Z | Tool fields, `outputSchema`, `structuredContent`, annotations untrusted, naming, errors, security MUSTs |
| https://modelcontextprotocol.io/specification/2026-07-28/changelog | 2026-10-19T23:05Z | Full list of 2026-07-28 major/minor changes and deprecations (incl. DCR deprecated) |
| https://modelcontextprotocol.io/specification/versioning | 2026-10-19T23:08Z | "The current protocol version is 2026-07-28"; per-request negotiation |
| https://modelcontextprotocol.io/specification/latest/basic/transports/streamable-http | 2026-10-19T23:08Z | Required headers, no sessions/GET, Origin validation, backward-compat rules |
| https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/schema/2026-07-28/schema.ts | 2026-10-19T23:08Z | `ToolAnnotations` defaults (false/true/false/true), `Tool`, `CallToolResult`, `LATEST_PROTOCOL_VERSION` |
| https://py.sdk.modelcontextprotocol.io/whats-new/ | 2026-10-19T23:05Z | Complete v2 change tour: renames, config to `run()`, removals, auth, protocol support |
| https://py.sdk.modelcontextprotocol.io/migration/ (offsets 0, 100000, 150000, 200000) | 2026-10-19T23:05Z to 23:08Z | Before/after code for renames, settings, `streamable_http_app`, lifespan, `Context.client_id`, auth carry-overs, `/token` `invalid_client`, public clients |
| https://py.sdk.modelcontextprotocol.io/run/authorization/ | 2026-10-19T23:05Z | RS setup, `TokenVerifier`, `AuthSettings` fields, discovery endpoint, 401 header, `get_access_token`, embedded AS discouraged, stdio skips auth |
| https://py.sdk.modelcontextprotocol.io/servers/tools/ | 2026-10-19T23:05Z | `@mcp.tool()` usage, `ToolAnnotations` snake_case example, validation errors |
| https://py.sdk.modelcontextprotocol.io/servers/structured-output/ | 2026-10-19T23:05Z | Return-type -> schema rules, wrapping, validation, opt-out |
| https://py.sdk.modelcontextprotocol.io/handlers/context/ | 2026-10-19T23:05Z | `Context` injection and members; headers not identity |
| https://py.sdk.modelcontextprotocol.io/handlers/lifespan/ | 2026-10-19T23:05Z | Typed lifespan example; `ctx.request_context.lifespan_context` |
| https://py.sdk.modelcontextprotocol.io/run/ | 2026-10-19T23:05Z | `run()` transports and options; CLI; `__main__` guard |
| https://py.sdk.modelcontextprotocol.io/run/asgi/ | 2026-10-19T23:05Z | Mounting, `session_manager.run()`, custom routes unauthenticated, CORS |
| https://py.sdk.modelcontextprotocol.io/run/deploy/ | 2026-10-19T23:05Z | 421 without `transport_security`; proxy headers; stateless vs stateful; workers; `RequestStateSecurity` |
| https://py.sdk.modelcontextprotocol.io/run/legacy-clients/ | 2026-10-19T23:05Z | One app serves both eras; session limits; `stateless_http` scope |
| https://py.sdk.modelcontextprotocol.io/protocol-versions/ | 2026-10-19T23:05Z | Pinnable set `["2026-07-28"]`; auto fallback |
| https://py.sdk.modelcontextprotocol.io/deprecated/ | 2026-10-19T23:05Z | SEP-2577 deprecations; `validate_token_resource` warning; 3.0 defaults; `MCPDeprecationWarning` |
| https://py.sdk.modelcontextprotocol.io/get-started/installation/ | 2026-10-19T23:05Z | Python 3.11+; extras; pin `mcp>=1.28,<2` if staying on v1 |
| https://py.sdk.modelcontextprotocol.io/get-started/real-host/ | 2026-10-19T23:06Z | Host registration commands; stdio for local hosts |
| https://py.sdk.modelcontextprotocol.io/servers/handling-errors/ | 2026-10-19T23:08Z | `ToolError` vs `MCPError` vs crash behaviour |
| https://github.com/modelcontextprotocol/python-sdk/releases | 2026-10-19T23:05Z | Release list and headline changes (no years shown) |
| https://api.github.com/repos/modelcontextprotocol/python-sdk/releases?per_page=12 | 2026-10-19T23:06Z / 23:08Z | `published_at` dates; full release bodies for v2.0.0, v2.0.1, v2.1.0, v2.2.0, v2.3.0 |
| https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/main/pyproject.toml and .../v2.3.0/pyproject.toml | 2026-10-19T23:06Z | `requires-python` `>=3.11` on main vs `>=3.10` at v2.3.0 |
| https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/main/src/mcp/server/auth/settings.py | 2026-10-19T23:06Z | Exact `AuthSettings`, `ClientRegistrationOptions`, `RevocationOptions` fields and validator |
| .../src/mcp/server/auth/provider.py | 2026-10-19T23:07Z | `TokenVerifier`, `AccessToken`, `OAuthAuthorizationServerProvider` methods, `ProviderTokenVerifier` |
| .../src/mcp/server/auth/middleware/auth_context.py | 2026-10-19T23:06Z | `get_access_token()` implementation via contextvar |
| .../src/mcp/server/auth/middleware/bearer_auth.py | 2026-10-19T23:07Z | `BearerAuthBackend` resource check; `RequireAuthMiddleware` 401/403 bodies and `WWW-Authenticate` format |
| .../src/mcp/server/auth/routes.py | 2026-10-19T23:07Z | `create_auth_routes`, `build_metadata`, `build_resource_metadata_url`, `create_protected_resource_routes`, issuer HTTPS rule |
| .../src/mcp/server/mcpserver/server.py | 2026-10-19T23:06Z | `MCPServer.__init__`, `run()` overloads, `streamable_http_app()`, `tool()` signature, auth constructor rules |
| .../src/mcp/server/lowlevel/server.py | 2026-10-19T23:08Z | HTTP app auth wiring: middleware stack, `RequireAuthMiddleware` on `/mcp`, PRM route, localhost DNS-rebinding defaults |
| .../src/mcp/server/mcpserver/{__init__.py,context.py} | 2026-10-19T23:09Z | Public exports; `Context` members; no `client_id` |
| .../src/mcp-types/mcp_types/_v2026_07_28/__init__.py | 2026-10-19T23:09Z | Python `ToolAnnotations` (snake_case, aliases, `None` defaults) and `Tool` fields |
| https://pypi.org/project/fastmcp/ and https://pypi.org/pypi/fastmcp/json | 2026-10-19T23:05Z / 23:06Z | fastmcp 4.1.1 (2026-10-18), jlowin project, separate from official SDK |
| https://pypi.org/project/mcp-types/ and https://pypi.org/pypi/mcp-types/json | 2026-10-19T23:06Z | mcp-types 2.3.0 wire-types package re-exported by `mcp` |
| https://claude.com/docs/connectors/building/index | 2026-10-19T23:08Z | Claude follows 2025-03-26/06-18/11-25 auth specs; DCR; callback URL; limits; unsupported features |
| https://claude.com/docs/connectors/building/authentication | 2026-10-19T23:09Z | Auth types table; DCR vs CIMD selection rule; 401 required; PKCE S256; redirect URIs; refresh rules; latency; egress range |

47 rows.

## mcp-sdk-v2-installed-api.md

Note title: MCP Python SDK: installed API facts (direct inspection, mcp==2.3.0)

No Sources table in this note (it records direct inspection of the installed package, not web pages).

## nba-schedule-injuries.md

Note title: NBA games on 2026-10-20 and the official injury report process

| Source | Retrieved (UTC) | What it established |
|---|---|---|
| https://pr.nba.com/2026-27-nba-regular-season-schedule | 23:04 (between 23:03:43 and 23:05:37), re-fetched ~23:05:40 | Oct 20 tripleheader, times, NBC/Peacock, Frost Bank Center, Tip-Off wording, Oct 21-22 "second and third days", NBA Cup dates, season end Apr 11 2027, 8 p.m. PT note |
| https://www.nba.com/schedule (WebFetch raw HTML) | ~23:04 | Page is JS-rendered; no games in HTML |
| https://www.nba.com/schedule (built-in browser, rendered) | between 23:07:53 and 23:10:31 | "Week 1 (Oct 20 - Oct 25)", 3 games Oct 20 at 3:00/7:00/9:30 PM ET; 11 games Oct 21; Cup labels from Oct 30; NBC/Peacock nodes; Florida local broadcasters |
| https://www.nba.com/schedule?pd=false&season=Preseason (browser) | ~23:10 | Last preseason heading "Friday, October 16 (Preseason)"; none for Oct 17-19 |
| https://official.nba.com/ | ~23:04 | Dated Oct 19 2026; nav "Team Injury Reports" -> 2025-26 URL; footer -> 2022-23 URL; rulebook PDF URL; Today's Officials showed a WNBA game |
| https://official.nba.com/nba-injury-report-2026-27-season/ | ~23:04 | HTTP 404 |
| https://official.nba.com/nba-injury-report-2025-26-season/ | ~23:05 and ~23:06 | Verbatim reporting deadlines; "updated on a continual basis"; Oct 19 2026 PDF links 12:00 a.m. to 7:00 p.m. ET at 15-min labels; no designation definitions |
| https://official.nba.com/nba-injury-report-2024-25-season/ | ~23:08 | Resolves to the 2025-26-titled page with Oct 19 2026 links |
| https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-10-19_07_00PM.pdf | 23:05:37 | Most recent report; header "Injury Report: 10/19/26 07:00 PM"; Oct 20 rows; column layout |
| https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-10-19_12_00AM.pdf and _06_45PM.pdf | 23:07:53 (HEAD) | HTTP 200: slots exist |
| ..._2026-10-19_07_15PM.pdf, ..._2026-10-18_05_00PM.pdf, ..._2026-10-18_12_00AM.pdf, ..._2026-10-20_12_00AM.pdf | 23:07:53 (HEAD) | HTTP 403 for future/absent slots |
| https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-03-26_08_00PM.pdf | 23:07:53 | Vocabulary counts: Available, Probable, Questionable, Doubtful, Out, NOT YET SUBMITTED |
| https://official.nba.com/referee-assignments/ | ~23:06 | "posted at approximately 9:00am ET each game day"; Oct 19 WNBA-only listing |
| https://www.nba.com/news/key-dates | ~23:06 | Preseason Oct 3; Oct 15-16 preseason action; Oct 19 rosters set 5 p.m. ET; Oct 20 regular season opens; Cup Oct 30-Nov 27; Dec knockout dates; Apr 11 2027; All-Star Feb 19-21 |
| https://www.nba.com/news/2026-nba-cup-group-play-schedule-announced | ~23:06 | 60 Group Play games; dates Oct 30, Nov 6, 13, 20, 24, 25, 27; knockout and championship dates/venue |
| https://www.nba.com/nba-cup/2026 | ~23:08 | "Group Play action ... tips off Friday, Oct. 30"; no standings-count statement |
| https://www.nba.com/kings/blog/injury-kings-clippers (browser) | ~23:09 | Team-blog Participation Status Key (Jan 5 2017): 75/50/25/Out |
| https://www.espn.com/nba/story/_/id/26784014/reliable-injury-info-hard-come-by (search snippet only) | ~23:09 | 2019 report: teams announce probable/questionable/doubtful/out by 5 p.m. day before |
| ESPN session tool espn_scoreboard, basketball/nba, 20261020 | ~23:05 | 3 games, times EDT, venues, eventIds 401909088-090 |
| ESPN espn_scoreboard 20261019, 20261021 | ~23:06 | No games Oct 19; 11 games Oct 21 |
| ESPN espn_scoreboard 20261016/17/18 (seasonType=1) | ~23:08 | 12 preseason finals Oct 16; none Oct 17-18 |
| https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json | 23:05:38 and 23:06:32 | HTTP 403 Access Denied |
| https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json | 23:07:53 | HTTP 403 |
| https://stats.nba.com/stats/scheduleleaguev2?Season=2026-27&LeagueID=00 | 23:07:53 | Timed out (30 s) |
| https://www.nist.gov/pml/time-and-frequency-division/popular-links/daylight-saving-time-dst | 23:10:31 | DST ends "November 1 at 2 a.m. (local time)" 2026; first Sunday of November rule |
| https://www.timeanddate.com/time/change/usa/new-york?year=2026 | ~23:10 | HTTP 403 (not used) |
| Local Python zoneinfo check (America/New_York) | 23:06 | EDT -04:00 through 2026-11-01 02:00, then EST -05:00 |

27 rows.

## stats-results-reference.md

Note title: Research notes: stats/results sources for settlement, Pinnacle reference, parlay-quote availability

| Source | Retrieved (UTC) | What it established |
|---|---|---|
| https://github.com/swar/nba_api | 2026-10-19 23:12 | Unofficial MIT client; NBA.com ToU applies; no endpoint change notices |
| https://raw.githubusercontent.com/swar/nba_api/master/README.md | 2026-10-19 23:13 | Proxy/headers/timeout options; static data; license |
| https://pypi.org/project/nba_api/ | 2026-10-19 23:14 | v1.11.4, Feb 20 2026, Python >=3.10 |
| https://raw.githubusercontent.com/swar/nba_api/master/docs/nba_api/stats/endpoints/boxscoretraditionalv3.md | 2026-10-19 23:15 | Endpoint URL, GameID format, player_stats columns |
| https://raw.githubusercontent.com/swar/nba_api/master/docs/nba_api/stats/static/players.md | 2026-10-19 23:15 | Static player lookup functions and fields |
| https://raw.githubusercontent.com/swar/nba_api/master/docs/table_of_contents.md | 2026-10-19 23:15 | Doc layout; http.md files; no live boxscore doc |
| https://raw.githubusercontent.com/swar/nba_api/master/docs/nba_api/stats/library/http.md | 2026-10-19 23:16 | STATS_HEADERS described; no rate-limit guidance |
| https://raw.githubusercontent.com/swar/nba_api/master/src/nba_api/live/nba/endpoints/boxscore.py | 2026-10-19 23:16 | Live boxscore path template, timeout=30 default |
| https://raw.githubusercontent.com/swar/nba_api/master/src/nba_api/stats/library/http.py | 2026-10-19 23:18 | base_url stats.nba.com/stats/{endpoint}; browser-mimic headers |
| https://github.com/swar/nba_api/issues?q=is%3Aissue+timeout+cloud | 2026-10-19 23:16 | Issues #176, #320 (open), #472, #505 on timeouts |
| https://github.com/bttmly/nba | 2026-10-19 23:15 | Cloud IP blacklisting, hanging requests, proxy workaround |
| Direct probe: https://stats.nba.com/stats/boxscoretraditionalv3?GameID=0022500001... | 2026-10-19 23:16 to 23:17 | curl 15 s no response; urllib 20 s timeout |
| Direct probe: https://cdn.nba.com/static/json/liveData/boxscore/boxscore_0022500001.json | 2026-10-19 23:16 | HTTP 403 Access Denied |
| https://www.balldontlie.io/ | 2026-10-19 23:12 (text grep 23:14) | Tier prices and rate limits; 48h trial; terms link |
| https://nba.balldontlie.io/ | 2026-10-19 23:13, 23:14, 23:15 | Endpoint tier table; /stats fields; players, injuries, odds vendors; auth |
| https://www.balldontlie.io/terms.html | 2026-10-19 23:15 | Terms (Sep 17 2026): commercial use OK, no key sharing, no raw resale, unlawful gambling prohibited |
| https://www.nba.com/stats | 2026-10-19 23:12 | No terms/licensing text on the stats landing page |
| https://www.nba.com/termsofuse | 2026-10-19 23:13 (grep 23:14) | Section 9 NBA Statistics restrictions incl. gambling; last updated July 13 2026 |
| https://pr.nba.com/nba-sportradar-genius-sports-group-partnerships | 2026-10-19 23:15 | Official betting data distributed to licensed operators via Sportradar/Genius |
| https://the-odds-api.com/liveapi/guides/v4/index.html | 2026-10-19 23:12, 23:13, 23:14, 23:16 | /scores, /participants, description field, quota, bookmakers param, 429; no parlay text |
| https://the-odds-api.com/sports-odds-data/bookmaker-apis.html | 2026-10-19 23:13 (parsed 23:14) | pinnacle eu + delay note; hardrockbet_fl us2; betonlineag/lowvig; paid-only list; no circa |
| https://the-odds-api.com/sports-odds-data/betting-markets.html | 2026-10-19 23:13 | NBA player prop market keys; event-odds endpoint; US coverage note |
| https://the-odds-api.com/sports-odds-data/sports-apis.html | 2026-10-19 23:17 | basketball_nba has Scores & Results |
| https://the-odds-api.com/ | 2026-10-19 23:13 (grep 23:17) | Plans: Starter free 500 credits "Most bookmakers"; $30/$59/$119/$249 |
| https://the-odds-api.com/terms-and-conditions.html | 2026-10-19 23:18 | T&C (Aug 31 2026): user-facing apps OK, no standalone redistribution, verify accuracy, termination |
| https://www.pinnacle.com/en/ | 2026-10-19 23:12 | JS page; nothing extractable |
| https://github.com/pinnacleapi/pinnacleapi-documentation | 2026-10-19 23:14 | API closed to public since July 23 2025; funded account; api@pinnacle.com |
| https://www.pinnacle.com/en/corporate/licenses | 2026-10-19 23:18 | No bets from USA-based gamers; licences list |
| https://dev.to/zuplo/unlocking-espns-hidden-api-a-developers-guide-1pp7 | 2026-10-19 23:15 | ESPN API unofficial/undocumented, no stability guarantee |
| https://gist.github.com/akeaswaran/b48b02f1c94f873c6655e7129910fc3b | 2026-10-19 23:16 | Community list of ESPN NBA scoreboard/teams URLs |
| Direct probe: https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20260419 | 2026-10-19 23:16 | Final events with team scores |
| Direct probe: https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=401869191 | 2026-10-19 23:17 | Per-player box score with athlete.id; 3PT as made-attempted string |
| https://disneytermsofuse.com/english/ | 2026-10-19 23:15 | 2.B(x) automated access prohibited; 2.B(viii) commercial use prohibited |
| https://sharpapi.io/sportsbooks/hardrock-odds-api | 2026-10-19 23:16 | Vendor: no public Hard Rock Bet API; no parlay product |
| https://sportsgameodds.com/hard-rock-bet-odds-api/ | 2026-10-19 23:15 | 404 |
| WebSearch "Hard Rock Bet same game parlay odds API feed developer" | 2026-10-19 23:14 | Kambi Odds Feed+ B2B integration (LSR); SGP Max press; no developer API |
| WebSearch "Pinnacle API access requirements" | 2026-10-19 23:13 | Pointed to pinnacleapi docs; npm note on US IPs (unverified) |
| WebSearch "ESPN hidden API ..." | 2026-10-19 23:13 | Community guides; unofficial status |
| WebSearch "nba_api stats.nba.com blocked cloud IP ..." | 2026-10-19 23:14 | bttmly/nba README; HN reports of datacenter IP drops (anecdotal) |
| WebSearch "NBA official data distributor Sportradar Genius ..." | 2026-10-19 23:14 | 2018 deals and 2020 renewal; no 2024/25 release found |
| WebSearch Pinnacle restricted territories (pinnacle.com) | 2026-10-19 23:17 | Licenses page and support article URLs |

41 rows.

## the-odds-api.md

Note title: The Odds API v4: research notes (KEY: the-odds-api)

| Source | Retrieved (UTC) | What it established |
|---|---|---|
| https://the-odds-api.com/liveapi/guides/v4/index.html | 2026-10-19T23:04Z (WebFetch), 2026-10-19T23:05:48Z (curl text) | all endpoints, params, cost formulas, quota headers, response notes, 429 text |
| https://the-odds-api.com/api-reference/v4/ | 2026-10-19T23:07:35Z | Scalar reference UI; points to schema.yml |
| https://the-odds-api.com/api-reference/v4/schema.yml | 2026-10-19T23:07:52Z | OpenAPI 3.0.1 (dated 2025-11-05): regions enum, param descriptions, 401/404/422/429 texts, Outcome/Score schemas, 11 paths |
| https://the-odds-api.com/sports-odds-data/bookmaker-apis.html | 2026-10-19T23:04Z (WebFetch), 2026-10-19T23:05:49Z (curl) | hardrockbet, hardrockbet_az, hardrockbet_fl, hardrockbet_oh in us2; pinnacle in eu with delay note; paid-only keys |
| https://the-odds-api.com/sports-odds-data/betting-markets.html | 2026-10-19T23:04Z (WebFetch), 2026-10-19T23:05:49Z (curl) | featured vs additional markets; NBA prop and alternate keys; coverage caveats; no parlay |
| https://the-odds-api.com/ | 2026-10-19T23:04Z (WebFetch), 2026-10-19T23:07:02Z (curl) | pricing tiers, 500 free credits, "Most bookmakers" vs "All bookmakers", billing, link map |
| https://the-odds-api.com/liveapi/guides/v4/samples.html | 2026-10-19T23:04Z | code-sample landing page only; no response shapes |
| https://the-odds-api.com/terms-and-conditions.html | 2026-10-19T23:05Z (WebFetch), 2026-10-19T23:05:48Z (curl) | restrictions, permitted uses, attribution, liability, responsible gambling, governing law |
| https://the-odds-api.com/manage/faqs.html | 2026-10-19T23:05Z (WebFetch), 2026-10-19T23:07:02Z (curl) | credit definition, monthly reset on the 1st, billing/cancel; no overage or rate-limit text |
| https://the-odds-api.com/sports-odds-data/update-intervals.html | 2026-10-19T23:05Z | 60s/40s featured, 60s/60s additional, 6-hour ramp |
| https://the-odds-api.com/historical-odds-data/ | 2026-10-19T23:05Z | paid-only historical; 10x multipliers; NBA start 2020-06-27; props from 2023-05-03 |
| https://the-odds-api.com/sports-odds-data/sports-apis.html | 2026-10-19T23:05Z | basketball_nba and related keys; NBA scores covered |
| https://the-odds-api.com/sports-odds-data/nba-odds.html | 2026-10-19T23:06Z | NBA props "limited to US and AU bookmakers"; Hard Rock not named; example URL |
| https://the-odds-api.com/guide/rate-limit.html | 2026-10-19T23:07Z (WebFetch), 2026-10-19T23:07:53Z (curl) | 30 req/s on paid plans; 429 handling; caching advice |
| https://the-odds-api.com/sports-odds-data/bets-api.html | 2026-10-19T23:07Z | marketing page; featured markets only; no parlay/SGP |
| https://the-odds-api.com/releases/deep-links.html | 2026-10-19T23:07Z | includeLinks/includeSids semantics; link/sid fields; supported books not listed |
| https://the-odds-api.com/sports-odds-data/live-sports-odds.html | 2026-10-19T23:07Z | marketing page; in-play "approx. every 30 seconds"; no Hard Rock mention |
| https://github.com/the-odds-api/samples-python/blob/master/README.md | 2026-10-19T23:05Z | sample script description only |
| https://raw.githubusercontent.com/the-odds-api/samples-python/master/odds.py | 2026-10-19T23:06Z | reads headers x-requests-remaining / x-requests-used; params regions, markets, oddsFormat, dateFormat |

19 rows.

## docs/research/sdk-examples/

Reference copies of the official MCP Python SDK example `examples/servers/simple-auth` (MIT), fetched from
https://github.com/modelcontextprotocol/python-sdk on 2026-10-19 for study only; not part of the shipped package.

## Installed package versions (uv pip list, run 2026-10-19 evening ET in the project venv)

| Package | Version |
|---|---|
| annotated-doc | 0.0.5 |
| annotated-types | 0.8.0 |
| anyio | 4.15.1 |
| argon2-cffi | 25.1.0 |
| argon2-cffi-bindings | 26.1.0 |
| attrs | 26.1.0 |
| certifi | 2026.10.18 |
| cffi | 2.1.1 |
| click | 8.5.0 |
| cryptography | 50.0.2 |
| h11 | 0.16.0 |
| hardrock-nba-parlay-mcp | 0.1.0 |
| httpcore | 1.0.9 |
| httpcore2 | 2.15.1 |
| httpx | 0.28.1 |
| httpx2 | 2.15.1 |
| idna | 3.20 |
| iniconfig | 2.3.1 |
| itsdangerous | 2.2.0 |
| jsonschema | 4.26.0 |
| jsonschema-specifications | 2025.9.1 |
| markdown-it-py | 4.2.0 |
| mcp | 2.3.0 |
| mcp-types | 2.3.0 |
| mdurl | 0.1.2 |
| opentelemetry-api | 1.45.1 |
| packaging | 26.3 |
| pluggy | 1.7.0 |
| psycopg | 3.3.6 |
| psycopg-binary | 3.3.6 |
| pycparser | 3.11 |
| pydantic | 2.14.1 |
| pydantic-core | 2.50.1 |
| pydantic-settings | 2.16.0 |
| pygments | 2.21.0 |
| pyjwt | 2.15.1 |
| pypdf | 6.21.1 |
| pytest | 9.1.1 |
| pytest-asyncio | 1.4.0 |
| python-dotenv | 1.2.4 |
| python-multipart | 0.0.32 |
| referencing | 0.37.0 |
| respx | 0.23.1 |
| rich | 15.0.0 |
| rpds-py | 2026.9.1 |
| ruff | 0.17.1 |
| shellingham | 1.5.4 |
| sqlalchemy | 2.1.5 |
| sse-starlette | 3.5.0 |
| starlette | 1.9.0 |
| truststore | 0.10.5 |
| typer | 0.27.3 |
| typing-extensions | 4.16.0 |
| typing-inspection | 0.4.4 |
| uvicorn | 0.54.0 |

The lockfile `uv.lock` pins these; the Docker image installs exactly them with `uv sync --frozen --no-dev`
(dev-only packages such as pytest, ruff, respx are excluded from the image).
