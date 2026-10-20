# Integration notes from the release module (2026-10-19)

Requests and observations for the integration lead and the other modules. The release
module did not edit any file outside its ownership; where a dependency is missing, the
release files assume the interface below and say so.

## 1. CLI `serve` signature (server module, `cli.py`): RESOLVED 2026-10-19 evening

`deploy/Dockerfile` runs:

```
hrnba serve --transport http --host 0.0.0.0 --port 8080
```

Verified with `uv run hrnba serve --help`: `--transport` (`stdio` | `http`, default
`stdio`), `--host`, and `--port` exist, so the Dockerfile CMD is satisfied. The help text
adds that with HTTP and `auth_mode` `none` the bind host must be loopback and any other
host needs `builtin_oauth` (refused with `FORBIDDEN` otherwise), which matches the
hosted configuration in `deploy/README.md` section 2. Also verified by reading
`src/hardrock_nba_parlay/web.py` and `auth.py` on 2026-10-19 evening: the hosted app
passes `json_response` from `settings.http_json_response`, derives `allowed_hosts` from
`public_url`, runs uvicorn with `proxy_headers=True` and `forwarded_allow_ips="*"`,
serves `/healthz`, and sets the OAuth resource to `public_url + "/mcp"`. Whether
`/healthz` returns no personal data and whether all of this works behind Railway's edge
remain PENDING INTEGRATION TEST (nothing is deployed).

## 2. Export and delete commands (server module): RESOLVED, one request open

Verified with `uv run hrnba user --help` on 2026-10-19 evening: `hrnba user export
<user_id> --out <file.json>`, `hrnba user delete <user_id> --confirm` (flag required),
and `hrnba user create <email>` (password read without echo). `docs/install.md` section
7 now names them. Still open: there is no CLI command that imports an `export_my_data`
bundle through `db.import_user(user_id, bundle, now)` (ARCHITECTURE section 11 says a
CLI command moves day-one local records into the hosted database without double
counting). Suggested name: `hrnba user import <user_id> --from <file.json>`. Until it
exists, `docs/install.md` says so.

## 3. Test-account seeding (server module, optional): still absent

`docs/test-account.md` describes a manual procedure through the MCP tools. A command
`hrnba seed-test-account --email <addr> --from <samples.json>` that creates the user and
records clearly labelled `MANUAL_INPUT` sample bets, settlements, and a cost would make
the reviewer account reproducible. `hrnba --help` on 2026-10-19 evening lists no such
command. Not required for day one.

## 3a. `HRNBA_DATA_MODE` (lead or data module)

`config.Settings.data_mode` (`live` | `fixture`, added 2026-10-19 at 20:11 ET) is now
listed in `.env.example` and described in README.md and `docs/install.md` as declared.
A grep of `src/` on 2026-10-19 evening found no module reading `settings.data_mode`, so
the documents call its end-to-end behaviour PENDING INTEGRATION TEST and warn never to
set `fixture` on the hosted server. Please confirm which module honours it and whether
the hosted server should refuse to start with `fixture`.

## 4. Server instructions and tool metadata (server module)

- ARCHITECTURE section 11 now says `schemas.AI_DISCLOSURE` is attached to `SystemStatus`,
  `BuildResponse`, and `Candidate` as `ai_disclosure`, and that the server `instructions`
  repeat it. SKILL.md section 1 carries the same facts in its own words; please keep the
  two texts consistent (the skill names the tool, says research not prediction or
  financial advice, says the user decides and places any wager, 21+, 1-833-PLAYWISE).
- Consider `meta={"anthropic/requiresUserInteraction": True}` on `select_ticket` and
  `record_actual_bet` so Claude Code prompts on every call (documented in
  `docs/research/claude-code-client-mcp.md`).
- Every tool needs `title` plus `read_only_hint` or `destructive_hint` (Directory Policy
  5.E); the annotations column in ARCHITECTURE section 6 covers this. Tool names are all
  under 64 characters.
- Keep tool results under roughly 10,000 tokens (Claude Code warns above that and caps at
  25,000 by default).

## 5. Ownership table gap (lead)

ARCHITECTURE section 1 lists `plugin/**`, `deploy/**`, README, LICENSE, CHANGELOG,
CLAUDE.md, `.env.example`, `docs/*.md` for release but not `scripts/`. The release brief
assigned `scripts/build_plugin_zip.py` and `scripts/stamp_release.py`; both were written.
The release module also created `tests/test_release.py` (bundle structure, frontmatter,
reference paths, README word count, ZIP builder, stamp script). No test file was listed
for release in the table; please add it to the ownership table or move it.

## 6. Local environment facts that affect integration

- Claude Code 2.1.123: `claude plugin validate` has no `--strict` and no `.mcp.json`
  checks, and it rejects the `displayName` manifest key (`Unrecognized key:
  "displayName"`) that current docs and the directory support; the bundle still loads
  (`claude --plugin-dir ./plugin/nba-three-leg-parlays plugin list`: `Status: loaded`).
  `claude mcp login` and `claude plugin details` do not exist on this build (use `/mcp`
  in a session). The marketplace manifest validates on 2.1.123 but that build does not
  recurse into the plugin's own manifest.
- Docker and `cloudflared` are not installed on the development Mac; `deploy/Dockerfile`
  and `deploy/docker-compose.yml` have not been built or run here.
- `uv` 0.13.1 is the pinned uv version in the Dockerfile (`ghcr.io/astral-sh/uv:0.13.1`).
- `pyyaml` is not a dependency, so the SKILL.md frontmatter check in
  `tests/test_release.py` parses the three `key: value` lines directly.

## 7. Facts the docs assume about other modules (please confirm or correct)

- Reservation expiry: `min(now + 2 h, earliest leg commence_time)` (ARCHITECTURE section
  5, budget algorithm step 5); SKILL.md says "expires at the earliest tip-off or after two
  hours".
- Per-user The Odds API keys are stored encrypted (`user_settings.odds_api_key_encrypted`)
  and never returned; `set_user_settings(odds_api_key=...)` is the only way in.
- `export_my_data` excludes credentials, OAuth tokens, and codes (`db.export_user` skips
  those tables).
- `/account` page offers Export and Delete with confirmation (ARCHITECTURE section 4:
  "used by CLI and the account web page, never by an MCP tool").
