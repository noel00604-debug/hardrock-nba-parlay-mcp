# Independent review of the release module (plugin bundle, deploy kit, docs)

Reviewer: release reviewer agent, 2026-10-19 evening ET. Scope: every file listed in the
release module's report, checked against docs/ARCHITECTURE.md (re-read after it changed on
disk), src/hardrock_nba_parlay/{schemas,config,db,errors}.py, tests/conftest.py, and the ten
research notes under docs/research/. No file outside this one was edited.

Verdict: the bundle is structurally sound and the documents are unusually careful about
saying what is unknown. Nothing invented was found among URLs, emails, approvals, or test
results. The defects below are real but small; the two that matter most are instructions
in SKILL.md that could make Claude state a settlement or an injury-report deadline it has no
source for.

## 1. Commands run, verbatim results

| Command | Result |
|---|---|
| `claude --version` | `2.1.123 (Claude Code)` |
| `claude plugin validate ./plugin/nba-three-leg-parlays` | `Validating plugin manifest: .../plugin/nba-three-leg-parlays/.claude-plugin/plugin.json` / `✘ Found 1 error:` / `❯ root: Unrecognized key: "displayName"` / `✘ Validation failed` (exit 1) |
| `claude plugin validate .` | `Validating marketplace manifest: .../.claude-plugin/marketplace.json` / `✔ Validation passed` (exit 0) |
| `claude plugin validate --help` | only `-h, --help`; no `--strict` on this build |
| `claude plugin validate <temp copy without displayName>` | `✔ Validation passed` (exit 0) |
| `claude --plugin-dir ./plugin/nba-three-leg-parlays plugin list` | `nba-three-leg-parlays@inline` / `Version: 0.1.0` / `Status: ✔ loaded` |
| `claude plugin details --help` | falls through to the generic `claude plugin` usage; `details` is not a subcommand on 2.1.123 |
| `python3 -I scripts/build_plugin_zip.py --dry-run` | 10 files, `45.2 KiB uncompressed`, `dry run: would write .../dist/nba-three-leg-parlays-0.1.0.zip` (exit 0); no `dist/` created |
| `python3 -I scripts/stamp_release.py --dry-run --server-url https://example.invalid/mcp --repo-url https://github.com/example/example` | `would update .mcp.json: url -> https://example.invalid/mcp` / `would update .claude-plugin/plugin.json: repository -> https://github.com/example/example, homepage -> https://github.com/example/example` / `would update README.md: 2 occurrence(s) of OWNER/REPO -> example/example` (exit 0). See defect 3. |
| same with `--server-url https://example.com/mcp` | `error: --server-url points at a placeholder host: example.com` (exit 1) |
| `uv run pytest tests/test_release.py -q` (first run, 33-field config) | `50 passed, 1 skipped in 0.07s` |
| `uv run pytest tests/test_release.py -q` (re-run after config.py changed at 20:11 ET) | `FAILED tests/test_release.py::test_env_example_lists_every_setting_without_values` / `1 failed, 49 passed, 1 skipped in 0.08s` (see D12) |
| `uv run ruff check scripts/build_plugin_zip.py scripts/stamp_release.py tests/test_release.py` | `All checks passed!` |
| `uv run ruff format --check` (same files) | `3 files already formatted` |
| `uv --version` / `uv run python --version` | `uv 0.13.1` / `Python 3.12.15` (matches Dockerfile pin and sources.md) |
| `uv pip list` | mcp 2.3.0, pydantic 2.14.1, sqlalchemy 2.1.5, httpx 0.28.1, uvicorn 0.54.0, starlette 1.9.0, psycopg 3.3.6 (all match docs/sources.md) |
| `sysctl` / `uname -r` | Apple M5, 17179869184 bytes (16 GiB), Darwin 27.0.0 (match sources.md) |
| `which docker`, `which cloudflared` | both absent (matches deploy/README.md and sources.md) |
| `uv run hrnba --help`, `hrnba serve --help`, `hrnba user --help`, `hrnba db --help` | `hrnba` imports and runs; `serve --transport {stdio,http} --host --port`, `user create|export|delete`, `db migrate|backup|restore` exist. See defect 11. |

Python checks (stdlib only): SKILL.md frontmatter keys are exactly `description`, `license`,
`name`; `name` equals the folder name; description is 647 characters; body is 278 lines. All
20 tool names from ARCHITECTURE section 6 appear in SKILL.md and no other tool-like name
does. Longest tool name is `check_parlay_correlation` (24); the longest full Claude Code
name `mcp__plugin_nba-three-leg-parlays_nba-three-leg-parlays__check_parlay_correlation` is
81 characters. Plugin README has 934 words outside code blocks. The plugin folder holds 10
text files, none over 16.5 KiB, no `.DS_Store`, `__MACOSX`, `Thumbs.db`, `.pyc`, symlink,
`bin/`, `CLAUDE.md`, or lockfile; only `plugin.json` is inside `.claude-plugin/`. A dash scan
(U+2014, U+2013) over every release-owned file found dashes only in docs/sources.md (defect
5). Every URL in the research notes' Sources tables appears in docs/sources.md (350 rows
checked). No secret-like strings in the plugin, deploy, docs, or .env.example.

## 2. Verified defects (quoted file and line)

### D1 (medium) SKILL.md lets Claude submit a provisional settlement with no stated source

`plugin/nba-three-leg-parlays/skills/nba-three-leg-parlays/SKILL.md` lines 132 to 134:

> `reconcile_settlement(bet_id, settlement_fields)` with the book's result when the user
> has it (`source=BOOK_CONFIRMED`), or a provisional result from NBA scores
> (`source=PROVISIONAL_NBA_RESULTS`) that never overrides a book-confirmed record.

No MCP tool returns scores (ARCHITECTURE section 6; `settlement.provisional_from_results`
at `src/hardrock_nba_parlay/settlement.py:454` is server-side and not exposed), and
`reconcile_settlement` stores whatever status and leg results the caller supplies
(`src/hardrock_nba_parlay/mcp_server.py:390-404`). As written, the skill invites Claude to
supply a WON/LOST status "from NBA scores" it has no tool for, which is a fabrication path.
The `anthropic/requiresUserInteraction` meta forces a prompt only in Claude Code
(docs/research/claude-code-client-mcp.md line 161), not in claude.ai. `references/workflows.md`
line 85 ("If the user reports a settlement") is the safer wording. Fix: in 6.D say that a
settlement is recorded only from what the user reports (the app's result, or scores the
user supplies for a provisional record), that Claude never looks up or recalls scores
itself, and that the user confirms the status before the call.

### D2 (medium) SKILL.md asks Claude to state injury-report deadlines the bundle never gives it

SKILL.md line 101 to 102: "say so and name the unresolved player and the next injury-report
window." Line 252 to 253: "Name the player, the report time, and when the next report is
due." A grep over the whole `skills/` folder for `11 a.m`, `1 p.m`, `5 p.m`, `8 a.m`,
`local time`, `report window`, `report is due` matches only those two instruction lines. The
deadlines are known (docs/research/nba-schedule-injuries.md section 3b: 5 p.m. local the day
before; game-day 11 a.m. to 1 p.m. local, 8 to 10 a.m. for tips at 5 p.m. or earlier;
second night of a back-to-back 1 p.m. local; "updated on a continual basis") but were not
copied into any reference, so Claude would have to invent them. Fix: add the verbatim
deadlines with the source URL to `references/workflows.md` or a new reference, and tell
Claude to say "unknown" when the next slot cannot be derived.

### D3 (medium) stamp_release.py accepts reserved-TLD and "example" placeholders

`scripts/stamp_release.py` lines 24 to 25 promise refusal of "example.com, localhost, TODO,
CHANGEME, angle brackets, and similar", and `PLACEHOLDER_HOSTS` (line 44) lists
`example.com/.org/.net`, `localhost`, loopback addresses. The run above with
`https://example.invalid/mcp` and `https://github.com/example/example` exited 0 and would
have written both into the bundle. `.invalid`, `.test`, `.example`, and `.localhost` are the
RFC 2606 reserved TLDs, and `example` is the standard documentation owner on GitHub. Fix:
reject hosts whose last label is one of the reserved TLDs, and reject `example` (and
`owner`, `repo`, `user`, `org`) as a GitHub owner or repository name.

### D4 (low) Stamping leaves a nonsensical sentence in the shipped README

`scripts/stamp_release.py` lines 168 to 171 replace every literal `OWNER/REPO`. Plugin
`README.md` line 82 reads "Once the public repository exists, replace OWNER/REPO with its
coordinates:". After stamping a temporary copy the line became "Once the public repository
exists, replace example/example with its coordinates:" (verified). Fix: delete that sentence
from the README (the commands below it carry the token) or have the script rewrite the
whole line.

### D5 (low) docs/sources.md contains en and em dashes

The brief says no em dashes anywhere in the documents written. `docs/sources.md` lines 72 to
87 contain U+2013 (en dash) between the two times in the retrieval-time column
("2026-10-19T23:04Z" to "23:06Z"), and line 384 contains U+2014 (em dash) between "The Odds
API v4" and "research notes" in the copied note title. `tests/test_release.py` lines 245 to
246 exempt the file deliberately. Neither case needs the dash: "23:04Z to 23:06Z" and
"The Odds API v4: research notes" change no fact. Fix the file and drop the test exemption.

### D6 (low) Wrong "longest tool name" in publication-readiness.md

`docs/publication-readiness.md` line 106: "5.C | ... | DONE: longest is
`generate_30_day_review` (22)". The longest names are `check_parlay_correlation` (24) and
`build_three_leg_parlays` (23). The conclusion (all under 64) still holds.

### D7 (low) launch-readiness.md contradicts itself about PASS

`docs/launch-readiness.md` lines 5 to 6: "Nothing is marked PASS here because the release
module did not run the integrated workflow". Lines 58, 60, 65, 66, 67, 76, 77, 78, 79 mark
items "PASS". Either reword the preamble ("PASS appears only for file-level checks the
release module ran itself") or change those rows.

### D8 (low) install.md recommends a command that does not exist on the installed build

`docs/install.md` lines 36 to 37: "`claude --plugin-dir ./plugin/nba-three-leg-parlays plugin
details nba-three-leg-parlays` prints the component inventory without starting a session."
On 2.1.123 `details` is not a subcommand (verified above), and the module's own note
`docs/integration-notes/release.md` lines 78 to 79 says so. Line 35 caveats `claude mcp
login` the same way; line 36 needs the same caveat.

### D9 (low) Misattributed Hard Rock quotation

`plugin/.../references/hard-rock-rules.md` lines 30 to 31: "the push explainer says odds are
'recalculated as if the pushed leg was not on the wager.'" The research note
(docs/research/hard-rock-house-rules.md line 37) attributes that sentence to the parlay
explainer (`/sportsbook/parlay/`); the push explainer (line 35) says "The odds get
recalculated based on your remaining selections." Swap the attribution.

### D10 (low) use-cases.md example quote does not match its own legs

`docs/use-cases.md` line 12 pairs "-110, -110, -150" with "combined payout of +596". The
product of those prices is decimal 6.0744, that is +507; +596 is decimal 6.96. Line 17
labels the odds illustrative, but this is listed as a working reviewer prompt, and the tool
will show the indicative product next to the quote. Use +507 or write "at the combined odds
the app shows".

### D11 (low) Documents are now stale about cli.py

Root `README.md` lines 58 to 59: "Note: `cli.py` is being written by the server module;
until it lands, `hrnba` is not importable." `docs/install.md` lines 128 to 131 and
`docs/integration-notes/release.md` sections 1 and 2 say the serve signature and the
export/delete names are unconfirmed. In the current tree `uv run hrnba --help` works and
provides `hrnba serve --transport {stdio,http} --host --port` (so the Dockerfile CMD is
satisfied), `hrnba user export <user_id> --out FILE`, `hrnba user delete <user_id>
--confirm`, `hrnba user create`, and `hrnba db migrate|backup|restore` (`db backup` prints
the pg_dump command on PostgreSQL). Still absent: an import command for `db.import_user`
and `seed-test-account`. Update the three documents; deploy/README.md section 5 can name
`hrnba db backup`.

### D12 (low) .env.example no longer lists every Settings field; its own test now fails

`src/hardrock_nba_parlay/config.py` (modified 20:11 ET, after `.env.example` at 19:57)
added `Settings.data_mode` (default `"live"`; description: "fixture = offline demo slate
clearly labelled FIXTURE; never writes to a real ledger"). `.env.example` has no
`HRNBA_DATA_MODE=` line, so `tests/test_release.py::test_env_example_lists_every_setting_without_values`
fails with `AssertionError: data_mode` (verified; the release report's "50 passed, 1
skipped" was true against the earlier 33-field config). Fix: add a commented, blank
`HRNBA_DATA_MODE=` line (values `live` or `fixture`; never `fixture` in production) under
"identity and storage", and mention the variable in README.md and docs/install.md where
fixture runs are described.

## 3. Concerns not reproduced (unverified, or outside what could be tested here)

1. `docs/install.md` lines 26 to 27 state that Claude Code drops the `.mcp.json` entry whose
   `url` is `""`. Not tested (needs an interactive session). Related and more important:
   on Claude Code 2.1.281 or later `claude plugin validate` errors on "a remote url that
   isn't a valid absolute URL" (docs/research/claude-code-plugins.md line 151), so the
   unstamped bundle will very likely fail the validator the docs tell the owner to use
   (install.md lines 39 to 42, publication-readiness.md line 134). The docs should say
   "run validate after stamping".
2. `deploy/fly.toml` lines 27 to 32 use `[http_service.checks]` with a named
   `[http_service.checks.healthz]` table; Fly's documented form for HTTP service checks is
   the array `[[http_service.checks]]` as far as this reviewer recalls, and the research
   did not fetch the fly.toml reference (hosting-options.md unresolved list). Unlike
   railway.toml, the file header does not say its key names are unverified. Also
   `fly deploy --config deploy/fly.toml --dockerfile deploy/Dockerfile` (deploy/README.md
   line 163) uses flags that no research note confirms.
3. `deploy/README.md` line 56: the Railway `${{Postgres.PGUSER}}` reference-variable syntax
   is not in any research note; it carries only a partial caveat.
4. `deploy/README.md` lines 82 to 85: "forward plain HTTP to the container" and "the
   platform certificate satisfies this [Directory Policy 5.D]" are general-knowledge and
   interpretive statements not drawn from the research notes; label the second as
   interpretation.
5. SKILL.md line 11 says "NBA regular season only". `schemas.Event.season_stage` allows
   `CUP`, and the Emirates NBA Cup group-play nights (Oct 30, Nov 6, 13 inside the review
   window) are labelled "EMIRATES NBA CUP" on nba.com; whether they count as regular-season
   games is inference (nba-schedule-injuries.md section 4a). If the slate tags them `CUP`
   the wording could make Claude refuse them. Suggest "regular season including NBA Cup
   group play; playoffs out of scope day one" or whatever the pipeline module decides.
6. `tests/test_release.py` lines 341 to 347, 384 to 386, 397 to 404 use
   `https://parlays.noelfernandez.dev/mcp` and
   `https://github.com/noelfernandez/hardrock-nba-parlay-mcp` as inputs. `.dev` is a live
   TLD and the repository path does not exist; the brief says never to invent URLs. They
   never leave temporary copies and the report disclosed them, but a value that cannot be
   mistaken for a real endpoint would be better (after D3 is fixed, pick one the stricter
   validator still accepts, for example a host under a domain the owner controls).
7. SKILL.md line 104 ("The primary candidate is the first in the response") and lines 105
   to 106 (the weakest-leg rule) are conventions not stated in ARCHITECTURE; confirm with
   the pipeline module that `BuildResponse.candidates` is ranked.
8. `docs/costs.md` lines 55 to 56 describe what the server does when a credit guard is hit
   ("serves cached or null data"); only the reason code `PROVIDER_CREDIT_GUARD` is in the
   contract. Confirm with the data module.
9. Plugin README lines 49 and 119 to 121 send users to `docs/privacy-policy.md` and
   `docs/support.md`, which are not inside the ZIP a claude.ai user receives; after stamping,
   `privacyPolicyUrl` and `supportUrl` will exist but the README text will still name
   repository files.
10. `references/hard-rock-rules.md` lines 95 to 96 cite "the 2021 Compact (Terms 1.3)";
    per the research, Terms 1.3 says "Class III Gaming Compact" without a year and the
    2021 date comes from House Rules 1.9 and 1.12. Minor citation conflation.
11. `docs/launch-readiness.md` line 33 says "verified absence" of any provider with Hard
    Rock parlay or SGP prices; the research checked The Odds API, balldontlie, and one
    vendor page. "Not found in the sources checked" is the accurate wording.
12. The Dockerfile and docker-compose.yml have not been built (Docker absent). The
    `uv sync --frozen --no-dev` layer with hatchling and `readme = "README.md"` looks
    correct but is unexercised.
13. ARCHITECTURE section 1 (re-read after the on-disk change) still lists neither
    `scripts/` nor `tests/test_release.py` under release; the module's integration note
    already asks the lead to add them.
14. The release report's per-note row counts for sources.md (29, 39, 26) differ from the
    file's own counts (30, 47, 27); the file is internally consistent and complete, so this
    is a reporting slip, not a file defect.

## 4. Checked and found correct

- Plugin manifest fields match the brief exactly (name, displayName, version, description,
  author name only, license, keywords; no homepage/repository/supportUrl/privacyPolicyUrl/
  documentationUrl/icon). `.mcp.json` is `{"mcpServers": {"nba-three-leg-parlays": {"type":
  "http", "url": ""}}}`. Marketplace manifest has name, owner, description, one entry with
  relative source and no version.
- SKILL.md frontmatter is spec-only; the body covers the seven prompts, disclosure at
  session start and under every candidate, required inputs, the tool sequence in the
  brief's order, the eight-block output format with the three-row table, freshness rules
  (180 s, 60 s, 6 h), correlation limits, budget rules, the seven candidate states, NO
  SUITABLE TICKET and WAIT FOR UPDATE, screenshot handling with confirmation before any
  call, the banned words inside a prohibition only, the not-connected instructions, and the
  references pointer. The screenshot section requires user confirmation and sends only
  structured fields. Section 15 forbids fabricating a slate, odds, or results.
- All Hard Rock quotations, section numbers, page "Updated" dates, the Google Doc ids, the
  21+ and physical-presence rules, GeoComply, 1-833-PLAYWISE, Bonus Bet terms, and the NBA
  Injury Insurance window match docs/research/hard-rock-house-rules.md.
- Policy dates (April 15, 2026; March 16, 2026; September 15, 2025; November 12, 2026;
  Oct 8, 2026), the verbatim 4.A clause, both Finance definitions, the Exclusions, the
  3.A to 3.H and 5.A to 5.G list, the four plugin and seven connector acknowledgements,
  the submission states, and the Max-plan eligibility match docs/research/anthropic-policies.md
  and claude-directory-connectors.md. The Finance classification and the NBA Terms of Use
  question are recorded as UNRESOLVED, not decided. No text claims Anthropic review,
  approval, or endorsement; status is NOT SUBMITTED everywhere.
- Hosting prices and facts (Railway Hobby $5 with $5 usage, us-east4, Serverless toggle,
  502 on wake, backups 6/27/89 days, post-paid card, hard limit minimum $10; Fly $3.69 and
  31-day note, no free tier, iad, always-on settings; Neon Free limits; Render $7 + $6;
  Cloudflare Quick Tunnel quotes; Anthropic egress 160.79.104.0/21) match hosting-options.md.
- The Odds API tiers, credit rules, worked model (29 and 41 credits), free-tier arithmetic,
  and terms summary match the-odds-api.md; balldontlie tiers match stats-results-reference.md.
- Methodology arithmetic: 1/1.9091 = 0.5238; 0.70^3 = 0.343; 0.20 x 5.50 - 1 = 0.10;
  $10 x 5.50 = $55.00 gross, $45.00 net; 1/5.50 = 0.1818; rounding rules match the
  quantization helpers in ARCHITECTURE. Review window Oct 20 to Nov 18 inclusive is 30 days;
  $300 maximum gross at the cap; DST ends 2026-11-01.
- `.env.example` lists all 33 `Settings` fields with blank values (test passes against
  `Settings.model_fields`); `.gitignore` excludes `.env`, databases, receipts, dist, zips.
- `web.py` derives `allowed_hosts` from `public_url`, passes `json_response` from
  `settings.http_json_response`, runs uvicorn with `proxy_headers=True`, and `auth.py` sets
  `resource = public_url + "/mcp"`, so deploy/README.md lines 32 and 86 to 92 describe the
  code as it now stands. The server `INSTRUCTIONS` and SKILL.md section 1 carry the same
  three disclosure facts.
- `scripts/build_plugin_zip.py` excludes `.DS_Store`, `__MACOSX`, `Thumbs.db`, `desktop.ini`,
  `__pycache__`, `.pyc`, `.zip`, `.git`, symlinks; blocks `bin/`, `CLAUDE.md`, lockfiles,
  extra files in `.claude-plugin/`, missing README or LICENSE, more than 512 files, text
  files over 256 KiB; the real build in the test produced a ZIP whose only top-level entry
  is `nba-three-leg-parlays/`.
