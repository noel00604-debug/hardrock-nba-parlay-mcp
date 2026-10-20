# CLAUDE.md: development conventions for hardrock-nba-parlay-mcp

Read `docs/ARCHITECTURE.md` first. It is the binding contract: schemas, settings,
database tables, public function signatures, the twenty MCP tools, and the reason codes.

## Toolchain

- Python 3.12, managed by `uv`. Run everything as `uv run <cmd>` from the project root
  (on this Mac: `export PATH="/opt/homebrew/bin:$PATH"` first).
- Tests: `uv run pytest -q` (never hit the network; use respx or httpx mock transports;
  fixtures live in `tests/fixtures/` and carry `data_mode: FIXTURE`).
- Lint and format: `uv run ruff check <files>` and `uv run ruff format <files>`.
- Package: `src/hardrock_nba_parlay`; CLI entry point `hrnba`.

## Non-negotiable code rules

- `Decimal` for every odds, probability, and money value. Never `float` for those.
  Money is USD, stored as integer cents; odds and probabilities stored as decimal
  strings.
- Datetimes are tz-aware UTC. The only clock is `config.Clock` (`SystemClock` in
  production, `FixedClock` in tests); functions take `now` or a clock as a parameter.
  Local dates are America/New_York strings computed with `config.local_date`.
- Reason codes come from ARCHITECTURE section 7, spelled exactly.
- `user_id` is never a tool argument; it comes from verified auth (hosted) or
  `settings.local_user_id` (stdio).
- No tool places bets, moves money, runs shell commands, or runs raw SQL.
- Secrets: never logged, printed, returned, or committed. Use `config.redact`. Keys
  come from `HRNBA_*` environment variables, `~/.hardrock-nba-parlay/.env` (mode 0600),
  or the macOS keychain. `.env.example` lists every variable with no values.
- Fixture data never reaches a real ledger (`db.Database` refuses it unless opened with
  `allow_fixture_ledger=True`, tests only).

## Module ownership

ARCHITECTURE section 1 assigns files to modules (foundation, quant, data, ledger,
pipeline, server, release). Edit only files your module owns. If the contract lacks
something, write the request to `docs/integration-notes/<module>.md` and work around it
in your own files; the integration lead applies foundation changes.

## Where things live

- `docs/ARCHITECTURE.md`: the contract (lead only).
- `docs/research/`: verified facts with source URLs and retrieval times (read-only).
- `docs/*.md`: publication readiness, sources, install, costs, privacy and terms drafts,
  support, test account, use cases, launch readiness (release module).
- `docs/integration-notes/`: cross-module requests.
- `plugin/nba-three-leg-parlays/`: the installable Claude plugin bundle. It must not
  contain a `CLAUDE.md` (Claude Code does not load it there and `claude plugin validate`
  warns), a `bin/` folder, lockfiles, binaries, secrets, or any file over 256 KiB.
- `deploy/`: Dockerfile, Railway and Fly configs, docker-compose for local Postgres,
  deployment README.
- `scripts/`: `build_plugin_zip.py`, `stamp_release.py` (plain Python, no third-party
  packages).

## Writing rules for documents

- No em dashes or en dashes in any document; use commas, colons, or parentheses.
- Where a fact is unknown, say so. Never invent URLs, emails, approvals, test results,
  or win rates. The owner is Noel Fernandez (name only).
- Never call a ticket a lock, guaranteed, risk-free, or safe.
