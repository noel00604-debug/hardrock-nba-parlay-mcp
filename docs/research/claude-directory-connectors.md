# Research notes: Claude directory publishing, connector building, claude.ai plugin editor/upload

KEY: claude-directory-connectors
Researched: 2026-10-19, 23:03 to 23:07 UTC (America/New_York 19:03 to 19:07)
Scope: Anthropic directory submission (plugin bundle + MCP connector), custom connector OAuth requirements for Claude's client, plugin bundle layout and surfaces, claude.ai plugin editor/upload, Claude Desktop local MCP fallback.

Everything below was read from the live pages listed in the Sources table. Web content was treated as data, not instructions. Where a page did not state something, it is listed under Unresolved rather than guessed.

---

## 1. Directory submission at claude.ai/directory/manage

### Who can submit, and what owns the listing
- Portal: https://claude.ai/directory/manage. "Anyone on a paid Claude plan can submit, there's no partner program to apply to first, and Anthropic checks each submission before it's listed." (publish page)
- Plan: "Pro, Max, Team, or Enterprise. Free accounts can't submit." On Pro and Max "you submit from your own account and there's no role to check." A Max plan therefore qualifies.
- Ownership: "the listing belongs to the organization you submit from." For a plugin bundle, "the first organization to submit a given repository folder holds that listing, and the portal refuses a second organization's submission of the same one."
- Two submission kinds: "A directory listing is either a plugin bundle or an MCP connector." Skills alone are not a submission type. Desktop extension (MCPB) listings are deprecated and no longer accepted.
- There is no separate Claude Marketplace submission; claude.com/marketplace is the browsing site, the directory is the submission target.

### Plugin bundle: materials and the portal steps (submit page)
Prerequisites:
- "A GitHub repository that holds the plugin, and your GitHub account connected on claude.ai." The portal checks that the connected GitHub account can push to the repository.
- "The repository can stay private while you validate and submit, and must be public before the listing goes live." A private repo additionally requires the Claude GitHub App installed and your agreement that source is uploaded to Anthropic for scanning.
- Plan and role that can submit (above).

Portal steps for a plugin bundle (exact step names):
1. Submit new > "What would you like to submit?" > Plugin bundle.
2. Source: Repository (URL or owner/repo), Plugin path (optional; folder holding .claude-plugin/plugin.json), Branch or tag (optional; the "tracked branch or tag"). Then Validate; fix Blocking findings; Re-validate. "A validation result applies to one commit."
3. Listing details: "read from plugin.json and the README." To change, edit those files and validate again.
4. Data handling: "whether the plugin reads or stores personal data, whether it sends data to services other than its declared connectors, how long it keeps data, and whether it's intended for people under 18."
5. Compliance: "check the contact email" and "Select all four acknowledgements."
6. Review and submit: choose "GitHub push webhook" (default) or "Scheduled check only"; "Submit for review." Optional "Auto-publish passing versions" toggle.

What the plugin form does NOT ask for directly: there is no privacy-policy URL field, screenshot upload, or test-account field on the plugin bundle form. The plugin's listing links come from plugin.json instead: the Claude Code manifest reference states the directory "reads the icon, documentationUrl, supportUrl, privacyPolicyUrl, and termsOfServiceUrl fields from plugin.json for your plugin's listing." Set icon to an image path inside the plugin and each URL field to an https:// URL. claude plugin validate accepts these without warning on Claude Code v2.1.281 or later (earlier versions warn, so --strict fails there).

Validation and scan (pre-submission checklist page), the blocking items that matter for this build:
- Folder must contain .claude-plugin/plugin.json (a skills-only folder without a manifest is listed for Claude Code only).
- README of at least 40 words (code blocks don't count): "README missing", "README too short" block.
- LICENSE file or license field in plugin.json: "License missing" blocks.
- Name: lowercase letters, digits, hyphens, up to 64 chars; not reserved words (claude, anthropic, official, plugin, mcp, test); not another org's name; look-alikes are held for a reviewer.
- .mcp.json must be valid JSON; each remote server needs type http, sse, or ws and an absolute https:// (or wss://) URL. "MCP server URL is not https" blocks.
- No credentials anywhere in files ("Secret in MCP headers" blocks). Ask through userConfig with sensitive: true instead.
- Remove .DS_Store, Thumbs.db, desktop.ini, __MACOSX (blocks).
- Package launchers (npx, uvx, uv run, pipx run) must be pinned to exact versions; even pinned launchers are held for a reviewer. A lockfile install at the plugin root is held.
- File limits: every non-image/font file under 256 KiB, at most 512 files, only text/SVG/PNG/JPEG/GIF/WebP/fonts; other binaries (.pdf, .zip, .ico, executables) are held for review.
- Repository limits: under 50 MiB archived, 256 MiB unpacked, fewer than 10,000 entries, each file in the plugin folder under 5 MiB.
- Results: Blocks (cannot submit), Held for a reviewer (policy hold; can submit; reviewer reads), Warning, Note.
- Security scan runs after submit on each commit: "A first submission that fails the security scan is rejected." Categories such as "Sends data to an undisclosed destination." Describe in the README everything the plugin runs, sends, or fetches; commit readable source.
- Submission limits: "An organization can create up to 10 submissions in any 24-hour period"; one submission per repository+folder.

Review, publication, and timing (publish, submit, submission-status pages):
- "Plugin bundles: every version gets automated validation and a security scan, and a person reviews a new listing before it goes live."
- "Review time isn't fixed."
- Statuses: Draft, Scanning, Needs changes, In review, Approved, Published, Not live yet, Delisted, Withdrawn. "Approved doesn't mean people can install the plugin. A plugin is installable only once its status is Published."
- Publishing: "When the version passes, select Publish on the plugin's page. By default, the portal records this as a request for an Anthropic reviewer, who then publishes the version."
- Updates after first publication: merge to the tracked branch; the directory scans and publishes per the auto-publish setting; "If your plugin.json sets version, raise it with every release."
- Contact: in-portal "Get help"/"Contact Anthropic", or directory@anthropic.com (plugins); mcp-review@anthropic.com (connectors).

### MCP connector: materials and portal steps (submission page)
Pre-submission checklist from the page:
- Server remote and reachable over HTTPS (local servers cannot be submitted alone).
- "Authentication works for Claude's client: OAuth 2.0 if your tools act on a user's account, or no authentication for public data."
- "Every tool has a title and a readOnlyHint or destructiveHint annotation."
- Tested as a custom connector in Claude; "the portal's Test & launch step asks you to confirm this."
- Listing materials: "documentation URL, privacy policy URL, support contact, an icon," plus carousel screenshots only for MCP Apps (3 to 5 PNG, width at least 1000px, no video/GIF).
- "You have a test account for reviewers: credentials for a fully populated account, which you enter in the portal and which only reviewers see."
- "Public documentation: required by your publish date. A blog post or help-center article is sufficient."

Portal steps (exact step names): Connection (paste https URL or choose an existing custom connector; Universal URL / Multiple URLs / URL pattern) > Tools (synced from the server; flags missing titles/annotations) > Listing ("server name up to 100 characters, one-liner up to 200 characters, description up to 2,000 characters, one to five categories, documentation URL, privacy policy URL, support contact, icon, and the URL slug"; slug permanent) > Use cases ("The primary use cases, what users need before they can connect ... and whether the connector reads data, writes data, or both") > Company (company name, website, primary contact) > Authentication (OAuth with DCR, CIMD, or Anthropic-held credentials; custom connection; none; lazy-auth flag) > Data handling (own API vs proxied vs third-party; personal health data; sponsored content) > Test & launch (test-account setup and access instructions "detailed enough for a reviewer to connect to your server and run its tools"; confirm you ran every tool) > Compliance ("Seven policy acknowledgments covering the directory guidelines, first-party API usage, financial transactions, AI media generation, prompt injection, conversation data collection, and public documentation. All seven are required.") > Review and submit.

Review for connectors: "Anthropic scans your submission automatically for policy compliance and, by default, lists it as a Community connector with no action from you. Some submissions also get a review from a person, and those review times vary with queue volume." Verified is an automatic escalation; no application.

Connector review criteria (review-criteria page) that affect tool design:
- No catch-all tool mixing safe and unsafe methods; separate read and write tools.
- Every tool: title plus readOnlyHint: true (read-only) or destructiveHint: true (modifies/deletes). "Read-only tools can run without per-call confirmation, and destructive tools always prompt."
- Tool names 64 characters or fewer.
- Descriptions narrow and accurate; no prompt-injection patterns.
- Functional quality: valid calls succeed; actionable errors; bounded responses; "Don't query Claude's memory, chat history, conversation summaries, or user files."
- API ownership: "Your server must call your own first-party APIs, or APIs you legitimately proxy. The MCP server domain should match your service."
- Unsupported: "Transfer money, cryptocurrency, or other financial assets"; AI image/video/audio generation.

Software Directory Policy (support article 13145358, effective April 15, 2026) items that apply:
- 4A: not allowed to "execute financial transactions on behalf of users" without express written permission.
- 3A privacy policy link covering collection, usage, retention when the software collects data or connects to a remote service.
- 3B verified contact information and support channels.
- 3C documentation of how the software works, purpose, troubleshooting.
- 3D "a standard testing account with sample data for Anthropic to verify full Software functionality."
- 3E "at least three working prompts or use cases."
- 5D remote servers requiring auth "use secure OAuth 2.0 with certificates from recognized authorities."
- Section 5: tool names max 64 chars; annotations (readOnlyHint, destructiveHint, title); remote servers should support Streamable HTTP.
- The policy page does not mention gambling or betting.

### Does a plugin bundle require a public GitHub repo?
Yes for go-live: "The repository can stay private while you validate and submit, and must be public before the listing goes live." The connector submission needs no repository ("The server's URL, with no repository needed").

---

## 2. Connector and plugin: separate submissions, same owner, shared URL

- "If you have a remote MCP server, always submit it as an MCP connector, even when a plugin you're submitting already references it." Benefits: the connector's listing, its own dashboard (health and usage by tool), and pairing.
- Pairing: "when the connector and a plugin bundle that references it are submitted from the same organization, you can pair the two listings."
- Deduplication: "Point the bundle's MCP server configuration at the same URL, so people who have both see one set of tools rather than two." (publish page) and "If your server is already listed in the directory, use the same URL here, so that someone who has both your connector and your plugin sees one set of tools rather than two." (plugins/build)
- The reference lives in .mcp.json at the plugin root:
  {
    "mcpServers": {
      "expenses": { "type": "http", "url": "https://mcp.example.com/mcp" }
    }
  }
  "Don't put API keys or other secrets in this file, because every person who installs the plugin receives its files."
- On claude.ai and Cowork the entry "is listed on the plugin's Connectors tab, where each user adds or connects it and signs in through your server's OAuth flow. Claude Code loads it with the plugin."
- Installing the plugin does not sign anyone in: "Adding a plugin doesn't add a connector to your account or sign you in to anything." Connectors tab states: Connected / Not connected / Not added.
- Claude Code precedence when a server is defined in more than one place: "1. Local scope 2. Project scope 3. User scope 4. Plugin-provided servers 5. claude.ai connectors."

---

## 3. Custom connector requirements for Claude's client (authentication page)

Specification versions: "Claude follows the 2025-03-26, 2025-06-18, and 2025-11-25 authorization specifications."

Supported authentication types (table on the page):
- oauth_dcr: OAuth 2.0 with Dynamic Client Registration (RFC 7591). Supported by default.
- oauth_cimd: OAuth 2.0 with Client ID Metadata Document. Supported by default.
- oauth_anthropic_creds: Anthropic-held client credentials. Contact mcp-review@anthropic.com.
- custom_connection: user-entered URL or client credentials. Contact mcp-review@anthropic.com.
- static_headers: fixed API key/bearer in a header, entered by an org Owner. "Beta, for a limited set of organizations."
- none: authless; combine with lazy authentication to protect some tools.
- "A machine-to-machine client_credentials grant isn't supported."

Client registration:
- DCR: expose a registration_endpoint. "DCR causes Claude to register a new client on every fresh connection"; for high traffic prefer CIMD or Anthropic-held creds.
- CIMD: Claude uses it "only when your authorization server metadata advertises both client_id_metadata_document_supported: true and 'none' in token_endpoint_auth_methods_supported." Otherwise it falls back to DCR.
- PKCE: "Claude includes a PKCE code_challenge with code_challenge_method=S256 on every authorization request, regardless of which registration mechanism it uses. Your authorization server must support S256 PKCE" and advertise "code_challenge_methods_supported": ["S256"].
- Scopes: control via scope parameter in the WWW-Authenticate header on the 401; otherwise Claude requests scopes_supported from protected resource metadata, and appends offline_access if the AS lists it.

Discovery (RFC 9728 protected resource metadata, RFC 8414 or OIDC Discovery for the AS):
- "Return 401 with a resource_metadata pointer": e.g.
  HTTP/1.1 401 Unauthorized
  WWW-Authenticate: Bearer resource_metadata="https://mcp.example.com/.well-known/oauth-protected-resource"
- "The 401 status is required, because Claude doesn't honor a WWW-Authenticate header on a 200 response."
- "Make resource match your MCP server URL exactly" including path.
- "List your primary issuer first": Claude uses only the first entry of authorization_servers.
- Fallback probe if no pointer: /.well-known/oauth-protected-resource/<mcp-path> then /.well-known/oauth-protected-resource on the MCP origin.
- The AS host must be reachable from Anthropic's egress range; "Anthropic's outbound traffic to your server originates from 160.79.104.0/21."
- Discovery metadata is cached globally per server URL for about five minutes.

Redirect URIs (exact):
- Hosted apps (claude.ai web, Desktop, mobile, Cowork): register exactly https://claude.ai/api/mcp/auth_callback
- Claude Code: loopback on any port, e.g. http://localhost:3118/callback. Its Client ID Metadata Document at https://claude.ai/oauth/claude-code-client-metadata declares redirect_uris ["http://localhost/callback", "http://127.0.0.1/callback"], token_endpoint_auth_method "none", grant_types ["authorization_code", "refresh_token"], response_types ["code"]. "match both with the port component ignored."
- The URL https://claude.com/api/mcp/auth_callback does not appear in any official Anthropic page fetched. Third-party vendor docs (Zuora, surfaced by search) list it as an alternative. Treat the claude.ai URL as authoritative; registering the claude.com variant in addition is harmless but unconfirmed as needed.
- Claude Code history: v2.1.229 briefly sent http://127.0.0.1:PORT/callback; v2.1.231 restored localhost. Use --callback-port to pin a port if a server needs an exact pre-registered redirect.

Token endpoint:
- Accept Content-Type: application/x-www-form-urlencoded; DCR /register uses application/json.
- Refresh: reactive on 401 and proactive up to five minutes before expiry; return invalid_grant for dead refresh tokens; rotate refresh tokens for public clients (DCR and CIMD register Claude as a public client).
- Latency: "Claude waits up to 10 seconds for a response from your OAuth discovery, registration, and token endpoints, and up to 30 seconds for refresh token requests."

Transport and limits (connectors/building/index):
- "Use Streamable HTTP ... Claude also supports the legacy HTTP+SSE transport, which is being deprecated."
- Limits table: claude.ai and Desktop max tool result ~150,000 characters, tool call timeout 240 seconds; Claude Code 25,000 tokens (MAX_MCP_OUTPUT_TOKENS) and MCP_TOOL_TIMEOUT.
- Unsupported MCP features: resource subscriptions, sampling, advanced/draft capabilities.
- Exposes tools, prompts, resources; text and image tool results.
- Claude Code: entries with url but no type are read as stdio (configuration error); v2.1.265+ tries HTTP first then falls back to SSE; `_meta["anthropic/maxResultSizeChars"]` can raise a tool's persist-to-disk threshold up to 500,000 chars; `_meta["anthropic/requiresUserInteraction"]: true` forces a prompt on every call (useful for record_actual_bet / select_ticket).

Lazy authentication (useful design pattern for this build):
- Public tools (e.g. get_system_status, get_nba_slate) can run before sign-in; protected tools (budget, bets) trigger sign-in only when called.
- The 401 must be sent from the HTTP handler before the MCP SDK runs: "A 200 with isError: true is an application-level tool failure ... there is no auth prompt."
- Canonical 401:
  WWW-Authenticate: Bearer error="invalid_token", error_description="Authentication required for this tool", resource_metadata="https://example.com/.well-known/oauth-protected-resource/mcp", scope="orders:read"
- Step-up: 403 with WWW-Authenticate: Bearer error="insufficient_scope", scope="...".

Custom connector testing path (testing page, add-unlisted page, support 11175166):
- "You test against the real Claude client, not a staging environment." "Custom connectors use the exact same runtime as directory connectors."
- Pro/Max: Customize > Connectors > "+ Add" > "Add custom connector"; enter name and MCP server URL; Authentication = Sign in now / Sign in when needed / No sign-in; OAuth client = "Use Claude's published identity (Recommended)" (CIMD) / "Register automatically" (DCR) / "Use your own OAuth client" (client ID, secret optional); Request headers (beta); Advanced > Transport (URL ending /sse selects legacy SSE).
- "You can't change authentication settings after you add a connector"; remove and re-add.
- Local server: expose via Cloudflare Tunnel or ngrok; keep auth on; shut the tunnel down after. Claude Code can connect to http://localhost directly: claude mcp add --transport http name http://localhost:3000/mcp, then /mcp to sign in.
- MCP Inspector CLI: npx @modelcontextprotocol/inspector --cli <url> --transport http --method tools/list
- Custom connectors "are available on Claude, Cowork, and Claude Desktop" for all plans; Free is limited to one; "Installing connectors on mobile is currently in beta."
- Install link that prefills the dialog: https://claude.ai/customize/connectors?modal=add-custom-connector&connectorName=NAME&connectorUrl=ENCODED_URL
- Directory listing URL after publication: https://claude.ai/directory/connectors/SLUG (permanent).

---

## 4. claude.ai plugin editor, ZIP upload, Connectors tab, surfaces

### "Create a plugin" editor (create-with-claude page, plugins overview)
- Location: Customize > Plugins > Add. Two items: "Create with Claude" (a conversation; Claude produces a .plugin file card; "Select Save plugin on that card") and "Create a plugin": "fill in a form with the plugin's name and what it helps with, then write its skills, commands, and connectors in an editor. Choose this when you already know what each piece should say."
- "If neither item appears in the Add menu, plugin creation isn't available on your account."
- A plugin made this way "is for you. It lives on your account ... It isn't a directory listing." "Anthropic's directory reads plugins from a GitHub repository, so a plugin that lives only on your account can't be submitted as it is." To submit, get the files as a folder (the docs describe asking Claude for "a plugin folder I can push to GitHub for the directory" in the Create-with-Claude conversation), check .claude-plugin/plugin.json, skills/, README.md, LICENSE, run claude plugin validate, push to a public GitHub repo, then Submit a plugin.
- Not stated in any fetched official page: the exact editor control labels ("Add file", "Save version"), whether the editor seeds a starter skill, how to rename/replace that starter skill, or how to download the editor's files. The user's screenshot is the only source for those labels. Recorded as unresolved.

### Upload plugin ZIP route (plugins/build, plugins/overview, platform-support)
- "In claude.ai, go to Customize > Plugins > Add > Upload plugin and select the zip. The plugin then appears on your own account."
- Accepted: ".zip or .plugin file. Zip either the plugin folder itself or its contents; both work as long as the archive holds one .claude-plugin/plugin.json."
- Error text if wrong: "plugin.json must be at .claude-plugin/plugin.json at the zip root (or inside a single top-level directory)".
- Limits: "Each plugin can contain up to 5,000 files and 200 MB, and 200 MB is also the largest file that Upload plugin accepts."
- Test sequence from the build page: 1 zip, 2 upload, 3 "Open a chat and ask Claude which skills it has from plugins", 4 "Connect the bundled connector from the plugin's Connectors tab", 5 Cowork task for agents.
- Uploaded/self-added plugins are not reviewed by Anthropic.

### Connectors tab and sign-in step
- Open the plugin from Customize > Plugins > Connectors tab. States: Connected; Not connected ("Connect it from this tab"); Not added ("Add it from this tab, then connect it"). On Team/Enterprise an Owner adds it for the org.
- "The plugin's skills load whether or not you connect anything. A skill that uses a connector's service can't reach that service until the connector shows Connected."
- A connector marked "Runs in each session" is local (command) and works only in Claude Code and local Cowork sessions.

### Which surfaces load what (platform-support table)
| Component | Chat (web, desktop, mobile) | Cowork | Claude Code |
| Skills | Loads | Loads | Loads |
| Commands | Loads as a skill | Loads (/plugin:command) | Loads |
| Agents | Ignored | Loads | Loads |
| Hooks | Ignored | Loads | Loads |
| Remote MCP server (http/sse, fixed URL) | Listed on Connectors tab; works once added/connected | Loads; connect from Connectors tab | Loads |
| Local MCP server (command, .mcpb) | Ignored | Loads when the session runs on your computer | Loads |
| MCP server using ${user_config.*} | Ignored when URL contains it | Ignored when option has no default | Loads; prompts |
| bin/ | Can't be installed | Can't be installed | Loads |
| LSP, output styles, themes, settings | Ignored | Ignored | Loads |

- Installs made in claude.ai sync to Claude Code "as a synced plugin at the next session start" (support article: requires Claude Code v2.1.273 or later; not with API-key sign-in or Bedrock). Claude Code installs do not sync back to the account.
- Directory browsing: "Discover in Customize > Plugins, on Pro, Max, Team, and Enterprise plans"; Claude Code: /plugin directory in v2.1.287+.
- Cowork: plugin limits 200 MB uncompressed, 5,000 files; marketplace repo archive 512 MB; 25 marketplaces.

### Plugin bundle layout and manifest (plugins/build, manifest reference, skills/how-to)
- "Put only the manifest inside .claude-plugin/. Everything else goes at the plugin's top level."
- Minimal manifest fields every app and the directory read: name, displayName, version, description, author {name, url}, license. name is permanent; raise version every release.
- Skill: skills/<name>/SKILL.md; frontmatter name "Lowercase letters, numbers, and hyphens only, up to 64 characters. Must match the skill's directory name"; description "Up to 1,024 characters"; "Keep your main SKILL.md under 500 lines"; references/, assets/, scripts/ folders; reference scripts as ${CLAUDE_SKILL_DIR}/scripts/x.py.
- README.md at least 40 words; LICENSE file or license field.
- A CLAUDE.md at the plugin root is not loaded and triggers a validate warning.
- Reserved name patterns rejected by claude plugin validate: starts with claude-, anthropic-, anthropics-, cc-plugin-; equals claude, anthropic, claude-code, claude-mods; "official" beside claude/anthropic. "mcp-for-claude" style names only warn.
- claude plugin validate --strict turns warnings (missing version/description/author, unknown fields) into failures.

### Claude Code direct-install marketplace route (code.claude.com publish page)
- Add .claude-plugin/marketplace.json beside plugin.json:
  { "name": "your-marketplace", "owner": { "name": "Your Name" }, "plugins": [ { "name": "deploy-helper", "source": "./" } ] }
- Users: claude plugin marketplace add owner/repo, then claude plugin install name@your-marketplace (or claude plugin install name --marketplace owner/repo on v2.1.292+).
- "Anthropic's official marketplace, claude-plugins-official, doesn't take submissions through the directory portal."
- Directory-listed plugins reach Claude Code as <name>@synced.
- For one-session dev testing: claude --plugin-dir ./plugin (skills appear as /plugin:skill; /mcp shows server state).

---

## 5. support.claude.com articles found
- 11175166 "Get started with custom connectors using remote MCP": availability on Claude, Cowork, Claude Desktop; Free limited to one; connections originate from Anthropic cloud; Pro/Max steps (Customize > Connectors > + Add > Add custom connector); OAuth client options; editing requires remove and re-add; local servers via claude_desktop_config.json "aren't available in Cowork or claude.ai"; "Advanced research is not currently able to invoke tools from local MCP servers."
- 11176164 "Use connectors to extend Claude's capabilities": web connectors on Claude, Cowork, Desktop, Mobile; mobile install in beta; tool permissions (Always allow / Needs approval / Blocked).
- 13837440 "Use plugins in Claude": "Plugins are available to all paid plans (Pro, Max, Team, Enterprise)"; hooks and sub-agents gray out in chat; Claude Code sync needs v2.1.273+; upload a custom plugin file; mentions a "Plugin Create" helper plugin. Does not describe editor control labels.
- 13837433 "Manage plugins for your organization": org-managed marketplaces (not needed for a personal Max account).
- 10949351 "Getting started with local MCP servers on Claude Desktop": now about desktop extensions (.mcpb): Settings > Extensions > Advanced settings > "Install Extension…"; built-in Node.js; "Plugins and remote connectors go through the developer portal"; it no longer documents claude_desktop_config.json.
- 13145358 Software Directory Policy (effective April 15, 2026): see section 1.
- No support article titled "Create a plugin", "Upload plugin", "Cowork plugins", or "connector directory submission" was found by search; the equivalents are the claude.com docs pages listed in Sources.

---

## 6. Local MCP on Claude Desktop (stdio fallback)
From modelcontextprotocol.io "Connect to local MCP servers":
- Open the Claude menu in the macOS menu bar (not in-window settings) > Settings... > Developer tab > Edit Config.
- File: macOS ~/Library/Application Support/Claude/claude_desktop_config.json; Windows %APPDATA%\Claude\claude_desktop_config.json.
- Structure:
  { "mcpServers": { "filesystem": { "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/Users/username/Desktop"] } } }
  (env block optional per server; use absolute paths.)
- "completely quit Claude Desktop and restart it."
- Logs: ~/Library/Logs/Claude/mcp.log and mcp-server-SERVERNAME.log; tail -n 20 -f ~/Library/Logs/Claude/mcp*.log
- Constraints from Anthropic pages: local servers are desktop-only, not in claude.ai or Cowork cloud sessions; Advanced research can't call them; the directory no longer accepts MCPB; a local server can be shipped inside a plugin bundle (loads in Claude Code and local Cowork sessions; chat ignores it; declare with command and args, run a file in the plugin with plain arguments, not via shell or npm run).

---

## Unresolved
1. Exact "Create a plugin" editor controls (Plugin name, Description, skills folder with SKILL.md, Add file, Save version) and how to replace the starter skill: not documented in any fetched official page; only the existence and purpose of the editor is documented. Confirm in the user's own claude.ai UI.
2. Whether https://claude.com/api/mcp/auth_callback must also be registered: not in official docs; only third-party vendor pages mention it.
3. Whether the plugin bundle portal shows privacy policy, support, and screenshot fields anywhere beyond plugin.json fields: the submit page lists only Source, Listing details, Data handling, Compliance, Review and submit. Screenshots are documented only for MCP App connector listings.
4. Minimum number of use cases for a connector listing: the portal asks for "the primary use cases"; the Policy requires "at least three working prompts or use cases." No field count was stated.
5. Review duration: explicitly not fixed; no SLA found.
6. Policy classification of sports-betting research tools: the Software Directory Policy does not mention gambling or betting; the financial-transaction prohibition (4A) applies to executing transfers, which this product does not do. Anthropic Usage Policy review is a separate research key.
7. Whether the Pro/Max custom-connector dialog in this account shows the one-screen "Advanced settings" layout or the two-step layout: "The layout of the Add custom connector dialog varies by organization."
8. The exact clientInfo name Claude sends (varies: "claude-ai", "Anthropic", "claude-code"); do not gate on it.

## Recommendations for this build
1. Prepare two submissions from the same Max account: MCP connector (server URL) first, then the plugin bundle whose .mcp.json uses the identical https URL, so tools do not duplicate; pair them in the portal.
2. Implement OAuth 2.1-style auth on the Python server: RFC 9728 protected resource metadata (resource equals the exact MCP URL incl. /mcp path), RFC 8414 AS metadata with code_challenge_methods_supported ["S256"], registration_endpoint (DCR) and, preferably, client_id_metadata_document_supported true plus token_endpoint_auth_methods_supported ["none"] (CIMD); return 401 with WWW-Authenticate resource_metadata pointer; accept form-urlencoded token requests; rotate refresh tokens; return invalid_grant; keep every OAuth endpoint under 10 s.
3. Register redirect URIs: https://claude.ai/api/mcp/auth_callback exactly, plus loopback http://localhost/callback and http://127.0.0.1/callback matched with the port ignored.
4. Use Streamable HTTP only; keep tool results under 150,000 characters and 240 s; keep each tool name at or under 64 chars; give every tool a title and readOnlyHint or destructiveHint; split read tools from write tools; mark record_actual_bet and select_ticket with destructiveHint true and consider _meta anthropic/requiresUserInteraction true.
5. Consider lazy auth: public tools (get_system_status, get_nba_slate, check_data_coverage) and protected per-user tools (budget, select_ticket, record_actual_bet, get_performance) gated by a 401 sent before the MCP SDK handles tools/call.
6. Plugin bundle: .claude-plugin/plugin.json with name, displayName, version, description, author, license, and the directory fields icon, documentationUrl, supportUrl, privacyPolicyUrl, termsOfServiceUrl; README.md over 40 words describing what runs, what is sent, and to where; LICENSE; skills/nba-three-leg-parlays/SKILL.md (name matches folder; description under 1,024 chars; body under 500 lines); .mcp.json with type http and the https URL; no bin/, no lockfiles at the root, no binaries, every non-image file under 256 KiB, no .DS_Store.
7. Validate with claude plugin validate --strict on Claude Code 2.1.281 or later (so the directory URL fields do not warn), then the portal's Validate button; expect a reviewer hold if anything is non-shell or a launcher is used.
8. Test order: claude --plugin-dir, then zip (folder as the single top-level entry) and Customize > Plugins > Add > Upload plugin, then the plugin's Connectors tab > Add > Connect, then a fresh chat. For the server itself, add it as a custom connector (Customize > Connectors > + Add > Add custom connector, OAuth client "Use Claude's published identity").
9. Keep the GitHub repo private during validation if desired, but it must be public before Publish; connect GitHub on claude.ai first; expect up to 10 submissions per 24 h.
10. Prepare for the connector form: documentation URL (public by publish date), privacy policy URL, support contact, icon, company name/website, a reviewer test account with fully populated sample data and step-by-step instructions, at least three working use cases, and the seven acknowledgements.
11. Treat "READY TO SUBMIT" as the deliverable; review time is not fixed and Approved is not Published.

---

## Sources
| URL | retrieved_at_utc | what it established |
| --- | --- | --- |
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
