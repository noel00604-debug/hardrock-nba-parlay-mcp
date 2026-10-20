# Launch readiness (integration lead, 2026-10-19 evening ET)

Statuses: PASS (exercised by the integration lead tonight), BLOCKED (needs something only the owner can
supply), NOT IMPLEMENTED, NOT TESTED. "Manual" means the user types or confirms the data; "automatic"
means the server fetches it. A fixture-mode or unit-test PASS is never evidence of live access.

Evidence collected tonight
- `uv run pytest -q`: 705 passed; `uv run ruff check src tests scripts`: clean.
- Fixture-mode end-to-end through the official MCP Python client over stdio (`hrnba serve --transport stdio`):
  all 20 tools; coverage, slate (3 games), build (3 MULTI_GAME candidates, one leg per game), correlation,
  select refused before a quote, quote import, refresh, budget, reservation, record (idempotent replay),
  external over-cap wager recorded with BUDGET_BREACH_RECORDED, book settlement, performance, 30-day review,
  export.
- Hosted mode over real HTTP (uvicorn, `HRNBA_AUTH_MODE=builtin_oauth`): unauthenticated `/mcp` returns 401 with
  `WWW-Authenticate ... resource_metadata=...`; protected-resource and authorization-server metadata served
  (`code_challenge_methods_supported: ["S256"]`, `registration_endpoint`); DCR accepted for a loopback redirect
  and rejected for a foreign one; PKCE enforced (wrong verifier -> `invalid_grant`); wrong password -> 401;
  token issued; authenticated MCP initialize / tools/list / tools/call through the SDK client; refresh rotation
  with reuse rejected; revocation -> 401.
- PostgreSQL ledger path on an embedded PostgreSQL (pgserver): 10 concurrent $3 reservations at a $10 cap ->
  exactly 3 succeed; replay; settlement; performance; tenant isolation (other user sees nothing); import.
- Claude Code 2.1.123 (`claude mcp add --scope user ... --transport stdio`, then `claude mcp get`): Status
  "Connected" (Claude Code spawned the server and completed the MCP handshake).
- `claude plugin validate --strict` (Claude Code 2.1.299 embedded in the desktop app): plugin and marketplace
  both "Validation passed". `claude --plugin-dir ./plugin/nba-three-leg-parlays plugin list` on 2.1.123:
  loaded.
- `dist/nba-three-leg-parlays-0.1.0.zip` built (10 files, plugin folder as the single top-level entry).

## Priority A: core day-one workflow

| Feature | Access | Status |
|---|---|---|
| NBA schedule for the date (3 games on 2026-10-20) | automatic via The Odds API `/events` (0 credits); verified tonight from pr.nba.com, nba.com and ESPN | PASS for the verified schedule; the live `/events` call is BLOCKED until the owner's Odds API key exists |
| Hard Rock Florida odds with source timestamps (`hardrockbet_fl`, never substituted) | automatic via The Odds API | BLOCKED: no key on this Mac; adapter tested against documented response shapes only |
| Player props and alternate lines for `hardrockbet_fl` | automatic, per-event endpoint | BLOCKED: whether Hard Rock FL props appear in the feed is unverified; coverage tool reports it |
| Reference prices (Pinnacle, delay caveat; fallback books) | automatic | BLOCKED: same key; skew is measured and reported, never silently loosened |
| Official injury report (PDF, 15-minute slots) | automatic fetch, manual entry fallback | NOT TESTED live (parser tested on a text reconstruction of the Oct 19 7 PM report and a generated PDF) |
| Freshness checks (180 s odds age, 60 s reference skew, started game) | n/a | PASS (unit and fixture flow) |
| Leg analysis with facts, interpretations, data grade, probability state, price value | n/a | PASS (fixture flow) |
| Exactly-three validation, duplicates, contradictions, nested, mutually exclusive | n/a | PASS (unit) |
| Correlation flags; no multiplied same-game joint probability | n/a | PASS (unit; same-game tickets return p_joint unknown) |
| Candidate generation, primary plus up to two alternatives, NO SUITABLE TICKET, WAIT FOR UPDATE | n/a | PASS (fixture flow and unit) |
| MCP connection from Claude Code (local stdio) | automatic | PASS (`claude mcp get` Connected on 2.1.123) |
| MCP connection from claude.ai / Desktop / Cowork (remote HTTPS) | automatic | BLOCKED: no public HTTPS host yet (hosting purchase is the owner's decision) |

## Priority B: price verification, budget, records, results, dashboard

| Feature | Access | Status |
|---|---|---|
| Combined three-leg quote | manual only (typed, screenshot fields confirmed in chat, receipt); no provider sells Hard Rock parlay/SGP prices | PASS (fixture flow: conflicting slip text refused, confirmed quote replaces the indicative product) |
| Revalidation before handoff | automatic re-fetch | PASS (fixture flow; price change returns the ticket to NEEDS_BOOK_QUOTE) |
| $10 daily cap per ET day, reservations, idempotency, breach recorded truthfully, DST boundary | n/a | PASS (unit incl. 2026-11-01; SQLite and PostgreSQL concurrency) |
| Budget display before handoff | n/a | PASS |
| Confirmed-bet recording incl. external wagers | manual | PASS |
| Settlement: book-confirmed authoritative, provisional never overrides, append-only corrections | manual (book); provisional team legs from `/scores` | PASS (unit); live `/scores` BLOCKED on the key |
| Player-prop provisional settlement | would need balldontlie All-Star ($9.99/mo) | NOT IMPLEMENTED (manual from the app) |
| Performance report, 30-day review ($300 max gross) | n/a | PASS |
| Dashboard (`hrnba dashboard`) | n/a | PASS (static HTML written; not styled beyond tables) |

## Priority C

| Feature | Status |
|---|---|
| Extra prop markets gated on live coverage | BLOCKED on the key |
| Validated statistical joint model | NOT IMPLEMENTED (day one is MARKET_BASELINE or INSUFFICIENT_EVIDENCE, labelled) |
| Optional background monitoring | NOT IMPLEMENTED (on-demand refresh only, by design) |
| Installation packaging (bundle, ZIP, marketplace, stamp script) | PASS (files, strict validation, ZIP) |

## Section 13: plugin package and public release

| Requirement | Status |
|---|---|
| 13.A identity and description | PASS |
| 13.A "Create a plugin" editor instructions | BLOCKED: the editor's controls are not in any official doc; the documented route is the ZIP upload (`docs/install.md`) |
| 13.B bundle layout | PASS; `.mcp.json` url is `""` until `scripts/stamp_release.py` stamps the real HTTPS endpoint |
| 13.C operational skill | PASS as text; NOT TESTED in a live chat with real tools |
| 13.D hosted MCP with Streamable HTTP and OAuth, per-user isolation | PASS locally over real HTTP; deployment, TLS and backup restore BLOCKED on hosting |
| 13.E test installation | Claude Code: PASS (validate --strict, --plugin-dir, stdio Connected). claude.ai ZIP upload, Connectors tab, fresh conversation: NOT TESTED (owner's account) |
| 13.F directory submission materials | BLOCKED (owner): public GitHub repo, support contact, privacy policy URL, reviewer test account, use cases ready in `docs/use-cases.md` |
| 13.G direct-install route | PASS (files); commands need the public repository |
| 13.G provider rights for multiple users | documented in `docs/costs.md` and `docs/publication-readiness.md` |
| 13.H two-account isolation | PASS in tests (ASGI OAuth flow with two users; PostgreSQL tenant check); NOT TESTED on a deployed host |
| 13.H clean-environment install | NOT TESTED (needs the public repository) |
| Publication status | NOT SUBMITTED |
