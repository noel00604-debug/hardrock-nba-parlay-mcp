# Installing, updating, removing, and rolling back the plugin

Status of each surface (filled in by the integration lead after testing):

| Surface | Route | Tested |
|---|---|---|
| Claude Code, development (`--plugin-dir`) | section 1 | TESTED 2026-10-19: bundle loads on 2.1.123; `claude plugin validate --strict` passes on 2.1.299; stdio server registered with `claude mcp add --scope user` shows Connected |
| Claude Code, direct marketplace install | section 3 | NOT TESTED (no public repository yet) |
| claude.ai web, Upload plugin ZIP plus Connectors tab | section 2 | NOT TESTED (needs the owner's account; ZIP built at dist/nba-three-leg-parlays-0.1.0.zip) |
| Claude Desktop (same account plugin as claude.ai) | section 2 | NOT TESTED |
| Cowork | section 2 (plugin syncs from the account; connect from Connectors tab) | NOT TESTED |
| Anthropic directory listing | not submitted | NOT APPLICABLE YET |

The plugin has no local state. Everything it records lives on the hosted server under
your account, so installing, updating, or removing the plugin never deletes records.

## 1. Claude Code, development route (no public endpoint needed)

Load the bundle for one session without installing it:

```
claude --plugin-dir ./plugin/nba-three-leg-parlays
```

The skill appears as `/nba-three-leg-parlays:nba-three-leg-parlays`. Because the
committed `.mcp.json` has an empty `url`, Claude Code drops that server entry; add the
server yourself (local dev server or the hosted one):

```
claude mcp add --transport http nba-three-leg-parlays http://localhost:8000/mcp
claude mcp add --transport http nba-three-leg-parlays https://<host>/mcp --scope user
```

Then run `/mcp` in the session, select the server, and sign in through the browser
(Claude Code 2.1.123 has no `claude mcp login`; newer versions do). After editing skill
files, run `/reload-plugins`. On current builds
`claude --plugin-dir ./plugin/nba-three-leg-parlays plugin details nba-three-leg-parlays`
prints the component inventory without starting a session (documented in the CLI
reference); Claude Code 2.1.123 has no `details` subcommand (verified: it falls through
to the generic `claude plugin` usage), so on that build use
`claude --plugin-dir ./plugin/nba-three-leg-parlays plugin list`, which shows
`nba-three-leg-parlays@inline` with `Status: loaded`.

Validate the bundle: `claude plugin validate ./plugin/nba-three-leg-parlays`. On Claude
Code 2.1.281 or later add `--strict`. On 2.1.123 the validator rejects the documented
`displayName` key (`Unrecognized key: "displayName"`) although the same build loads the
bundle; upgrade Claude Code before treating its output as authoritative. Run the
validator again after `scripts/stamp_release.py` has written the real URL: from 2.1.281
it also checks `.mcp.json` and reports a remote `url` that is not a valid absolute URL,
and whether it accepts the committed `""` placeholder was not tested.

## 2. claude.ai: Upload plugin, then connect

1. Build the archive: `python3 scripts/build_plugin_zip.py` writes
   `dist/nba-three-leg-parlays-<version>.zip` with the plugin folder as the single
   top-level entry.
2. In claude.ai: Customize > Plugins > Add > Upload plugin, select the ZIP. The plugin
   appears on your own account (also in Claude Desktop and Cowork, and in Claude Code
   2.1.273 or later as `nba-three-leg-parlays@synced` when signed in with the same
   account).
3. Open the plugin > Connectors tab. The `nba-three-leg-parlays` connector shows "Not
   added" until the `.mcp.json` URL has been stamped with the real endpoint; add it, then
   Connect and sign in on the server's login page (create an account on its sign-up page
   the first time).
4. Start a fresh chat and ask "Which skills do you have from plugins?" then try a prompt
   from `docs/use-cases.md`.

Until the endpoint exists you can still test the skill text this way; the tools will be
absent and the skill will say so.

Offline demonstration: `config.py` declares `HRNBA_DATA_MODE` (`live`, the default, or
`fixture`); `fixture` is meant to serve an offline demo slate labelled FIXTURE that
never writes to a real ledger (`db.Database` refuses FIXTURE records unless opened with
`allow_fixture_ledger=True`, tests only). The server honours the setting end to end
(verified 2026-10-19 through the MCP client over stdio). Never set `fixture` on the hosted server.

## 3. Claude Code: direct install from the GitHub marketplace

Requires the public repository. Replace noel00604-debug/hardrock-nba-parlay-mcp with the repository coordinates:

```
claude plugin marketplace add noel00604-debug/hardrock-nba-parlay-mcp
claude plugin install nba-three-leg-parlays@hardrock-nba-parlay-marketplace
```

`claude plugin marketplace add` prints `Successfully added marketplace:
hardrock-nba-parlay-marketplace`; the install prints `Successfully installed plugin:
nba-three-leg-parlays@hardrock-nba-parlay-marketplace (scope: user)`. Then `/mcp` to sign
in. On Claude Code 2.1.292 or later the one-shot form is
`claude plugin install nba-three-leg-parlays --marketplace noel00604-debug/hardrock-nba-parlay-mcp`.

This is direct distribution. It is not an Anthropic-reviewed listing and must not be
described as one.

## 4. Updating

- Marketplace install: `claude plugin update nba-three-leg-parlays@hardrock-nba-parlay-marketplace`.
  The plugin updates only when `version` in `plugin.json` changed; the release process
  raises it for every release (and never sets `version` in the marketplace entry as
  well).
- claude.ai upload: upload the new ZIP; the account plugin is replaced.
- Your records are on the server and are unaffected. The server's database schema is
  migrated forward by the server, never by the plugin.

## 5. Uninstalling

- Claude Code: `claude plugin uninstall nba-three-leg-parlays` (add `--keep-data` to keep
  the plugin's local data folder, which this plugin does not use). To forget the
  marketplace: `claude plugin marketplace remove hardrock-nba-parlay-marketplace`. To
  remove a manually added server and its stored OAuth tokens:
  `claude mcp remove nba-three-leg-parlays`.
- claude.ai: Customize > Plugins > the plugin > remove. The connector can be removed
  separately under Customize > Connectors; removing it revokes nothing on the server, so
  also sign out or delete your account there if you want the server to forget you.

## 6. Rollback: reinstalling a tagged version

Releases are tagged `nba-three-leg-parlays--v<version>` with `claude plugin tag`. To
install a specific version:

```
claude plugin marketplace remove hardrock-nba-parlay-marketplace
claude plugin marketplace add noel00604-debug/hardrock-nba-parlay-mcp#nba-three-leg-parlays--v0.1.0
claude plugin install nba-three-leg-parlays@hardrock-nba-parlay-marketplace
```

For claude.ai, upload the ZIP built from that tag (`dist/nba-three-leg-parlays-0.1.0.zip`).
A rollback of the plugin never changes server data; if a server release changed the
schema, the server keeps the newer schema and older plugin versions keep working because
the skill only names tools.

## 7. Exporting and deleting your data

- Export, from any client: the `export_my_data` tool returns your records as structured
  data (candidates, reservations, bets, settlements, costs, settings; never passwords or
  tokens).
- Export and delete, from the server's account page: sign in at `https://<host>/account`,
  choose Export (JSON download) or Delete account (confirmation required; removes your
  user row, settings, encrypted provider key, OAuth tokens, candidates, reservations,
  bets, settlements, costs, and audit rows). Deletion is not exposed as an MCP tool by
  design.
- Owner-side CLI (verified 2026-10-19 evening with `uv run hrnba user --help`):
  `hrnba user export <user_id> --out <file.json>` writes every record of a user to a
  JSON file; `hrnba user delete <user_id> --confirm` deletes every record of that user
  (the `--confirm` flag is required); `hrnba user create <email>` creates a hosted-mode
  user and reads the password without echo. All three need database access
  (`HRNBA_DATABASE_URL`).
- Moving local records to the hosted server: day one runs locally (stdio, user
  `local-owner`, SQLite). The contract provides `db.import_user(user_id, bundle, now)`,
  which keeps primary keys and idempotency keys so nothing is double counted, but as of
  2026-10-19 evening the CLI has no import command for it (`hrnba --help` lists none);
  the request stays open in `docs/integration-notes/release.md`. Backups taken before a
  deletion keep the data for the backup retention period (Railway: 6 days daily, 27
  days weekly); locally, `hrnba db backup <file>` copies the SQLite database after a
  WAL checkpoint (on PostgreSQL it prints the `pg_dump` command).

## 8. Troubleshooting

- "plugin.json must be at .claude-plugin/plugin.json at the zip root": the ZIP was not
  built by `scripts/build_plugin_zip.py` or was re-zipped with extra files beside the
  folder.
- Tools missing in chat: the connector is Not connected; open the plugin's Connectors tab.
- `UNAUTHENTICATED` from a tool: sign in again (`/mcp` in Claude Code; Connectors tab in
  claude.ai). Tokens are refreshed automatically; a revoked account cannot sign in.
- `NO_PROVIDER_KEY`: the server has no The Odds API key for you; store your own with
  `set_user_settings` or ask the owner.
