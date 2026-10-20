# hardrock-nba-parlay-mcp

A Python MCP server, CLI, and Claude plugin bundle for researching exactly three-leg NBA
parlays on Hard Rock Bet Florida: current odds with source timestamps, official injury
context, correlation checks, the user's own combined quote from the app, a daily budget
ledger (default $10 per America/New_York day), and tracking of wagers the user confirms
placing, so that results can be reviewed honestly after 30 days.

The software researches and records. The user places every wager in the Hard Rock app.
There is no tool that places bets, moves money, or touches a sportsbook account.

Owner: Noel Fernandez. License: MIT. Status on 2026-10-19: in build; not deployed, not
published, not submitted to the Anthropic directory. See `docs/launch-readiness.md`.

## Repository layout

| Path | What it is |
|---|---|
| `src/hardrock_nba_parlay/` | the package: `schemas.py`, `config.py`, `db.py`, `errors.py` (foundation); `probabilities.py`, `correlation.py` (quant); `providers/`, `normalization.py`, `freshness.py`, `injury_context.py` (data); `budget.py`, `actual_bets.py`, `settlement.py`, `reports.py` (ledger); `candidate_builder.py`, `quote_review.py`, `services.py` (pipeline); `mcp_server.py`, `auth.py`, `web.py`, `cli.py`, `dashboard.py` (server) |
| `tests/` | pytest suites per module; `conftest.py` fixtures; `tests/fixtures/` offline FIXTURE data |
| `plugin/nba-three-leg-parlays/` | the installable Claude plugin bundle (manifest, `.mcp.json`, skill, references, README, LICENSE, CHANGELOG) |
| `.claude-plugin/marketplace.json` | Claude Code marketplace manifest for direct installs from this repository |
| `scripts/` | `build_plugin_zip.py` (ZIP for claude.ai upload), `stamp_release.py` (write the server URL and repository into the bundle) |
| `deploy/` | Dockerfile, Railway and Fly.io configs, docker-compose for local Postgres, deployment README |
| `docs/ARCHITECTURE.md` | the binding interface contract |
| `docs/research/` | verified facts with source URLs and retrieval times |
| `docs/*.md` | publication readiness, sources, install, costs, privacy policy and terms drafts, support, test account, use cases, launch readiness |
| `CLAUDE.md` | development conventions |
| `.env.example` | every `HRNBA_` variable, no values |

## Day one

See [docs/day-one-runbook.md](docs/day-one-runbook.md) for the exact morning sequence (store the Odds API key, check coverage, build candidates, use the registered MCP server in Claude Code) and [docs/launch-readiness.md](docs/launch-readiness.md) for what was tested tonight and what is still blocked.

## Quick start (local, stdio, your own machine)

Requirements: macOS or Linux, Python 3.12, `uv`, a The Odds API key (free Starter tier
gives 500 credits per month; see `docs/costs.md`).

```
cd hardrock-nba-parlay-mcp
export PATH="/opt/homebrew/bin:$PATH"
uv sync
mkdir -p ~/.hardrock-nba-parlay && cp .env.example ~/.hardrock-nba-parlay/.env && chmod 600 ~/.hardrock-nba-parlay/.env
```

Edit `~/.hardrock-nba-parlay/.env` and set `HRNBA_ODDS_API_KEY` (or store it in the macOS
keychain: `security add-generic-password -s hardrock-nba-parlay -a ODDS_API_KEY -w`).
Leave `HRNBA_AUTH_MODE` blank for local use; records are scoped to `local-owner` in a
SQLite database under `~/.hardrock-nba-parlay/`.

Run the server over stdio for Claude Code:

```
claude mcp add --transport stdio nba-three-leg-parlays -- uv --directory /path/to/hardrock-nba-parlay-mcp run hrnba serve --transport stdio
```

Load the skill for the session with `claude --plugin-dir ./plugin/nba-three-leg-parlays`
and ask "Review today's NBA slate for a three-leg Hard Rock Florida parlay within my $10
daily cap." The CLI (`uv run hrnba --help`) exposes the same services and the dashboard.

The `hrnba` CLI exists (verified 2026-10-19 evening with `uv run hrnba --help`):
`status`, `coverage`, `slate`, `build`, `analyze-leg`, `correlation`, `import-quote`,
`refresh`, `select`, `release`, `budget`, `record-bet`, `settle`, `performance`,
`review-30`, `dashboard`, `import-selections`, `serve --transport {stdio,http} [--host]
[--port]`, `db migrate|backup|restore`, `user create|export|delete`, and `secret`. The
data mode of every response is shown (`LIVE_PROVIDER`, `MANUAL_INPUT`, `FIXTURE`);
fixture runs are demonstrations, not live access. `HRNBA_DATA_MODE` (`live`, the
default, or `fixture`) is declared in `config.py` for an offline demo slate labelled
FIXTURE that never writes to a real ledger; never set `fixture` on a hosted server, and
treat its end-to-end behaviour as PENDING INTEGRATION TEST.

## Running tests and lint

```
uv run pytest -q
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
```

Tests never touch the network. Release checks: `claude plugin validate ./plugin/nba-three-leg-parlays`,
`claude plugin validate .`, `python3 scripts/build_plugin_zip.py --dry-run`,
`uv run pytest tests/test_release.py -q`.

## Hosted deployment and publication

- `deploy/README.md`: first deployment on Railway (primary) or Fly.io plus Neon
  (fallback), environment variables, TLS, backups and restore test, tunnel smoke test.
- `docs/install.md`: Claude Code, claude.ai, and marketplace install routes; update,
  uninstall, rollback, export, delete.
- `docs/publication-readiness.md`: Anthropic Software Directory Policy and Usage Policy
  requirements with their effective dates, what is done, and what the owner must still
  do. The High-risk Finance classification is recorded as unresolved.
- `docs/costs.md`: provider tiers, credit model, hosting estimates for 1, 10, and 100
  users, and the 30-day estimate.
- `docs/sources.md`: every URL consulted with retrieval times and the pinned package
  versions.

## Disclosure

Output from this software is produced with AI assistance and is research, not a
prediction or financial advice. It never guarantees an outcome and never reports a win
rate that was not computed from recorded, settled tickets. Florida sports betting is for
people 21 and older physically in Florida; help is available at 1-833-PLAYWISE. Not
affiliated with or endorsed by the NBA, Hard Rock Bet, the Seminole Tribe of Florida,
The Odds API, or Anthropic.
