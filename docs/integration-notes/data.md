# Integration notes: data module (providers, normalization, freshness, injury_context)

Owner: data. Written 2026-10-19 evening ET. Everything below is either a request for the integration lead
(foundation files are frozen; I did not edit them) or a fact the pipeline/server modules need to know when
they call this module.

## 0. Review fixes applied (2026-10-19, later in the evening)

An independent reviewer reproduced ten defects in `tests/test_data_review.py`; all are fixed in the module
code (no test was weakened). One of the module's own tests was corrected because it was wrong against the
contract: `tests/test_freshness.py` expected a CANCELLED event to report `GAME_POSTPONED`; section 7 now lists
`GAME_CANCELLED`, so the test expects that code. Behaviour changes the pipeline/server should know:

- `OddsApiProvider` installs `providers.base.install_http_log_redaction` on the `httpx`/`httpcore` loggers at
  construction: the `HTTP Request: GET <url>` line is still emitted at INFO but the `apiKey` parameter is
  removed and the key value masked. Nothing else about logging changed (`config.configure_logging` still
  lowers those loggers to WARNING when the CLI/web entry points call it).
- Slate day bounds (`commenceTimeFrom/To`) and the daily credit guard use `config.DEFAULT_TZ`
  (America/New_York) regardless of `settings.display_tz`, matching `date_local` in the ledger.
- A cache hit now reports `credits_cost=0` (no request was made) and keeps the `received_at_utc` of the
  request that actually fetched the data on the result stamp and on every quote/event stamp; `cached=True`
  says which. Summing `credits_cost` over calls therefore equals real spend.
- `normalization.pair_reference[_with_reasons]` ignores quotes whose `book` equals the selection's own book,
  so passing the providers' combined target-plus-reference list is safe; a target-only line now yields
  `LINE_MISMATCH` instead of a self-reference with edge 0.
- `providers/manual`: `TEAM_TOTAL` legs are accepted when `ManualSelectionInput.team` names one of the
  event's teams (`TEAM_UNMATCHED` otherwise, also when the field is missing); in pipe text the subject
  column is the team for a team-total leg, and CSV accepts an optional `team` column (`CSV_HEADER` now
  lists it). A UTF-8 BOM is tolerated in pasted text and files (`utf-8-sig`).
  `slip_fields_from_extraction` never raises for readable text: an unparseable `captured_at_utc` is listed
  in `unresolved` (and `captured_at_utc` stays None); a team-total leg without a team lists `legs[i].team`.
- `freshness.check_event_not_started` returns `GAME_CANCELLED` for CANCELLED events; it is in
  `BLOCKING_REASON_CODES`.
- `date_local` arguments are validated with `date.fromisoformat` in `list_events`, `fetch_featured_odds`,
  `report_slots` and `fetch_injury_report`; a malformed value raises `InvalidInput` (INVALID_INPUT), never
  a bare `ValueError`.
- One unusable player-prop outcome (description that normalises to nothing) is skipped with a
  `skipped ... PLAYER_UNMATCHED` warning instead of aborting the call. A 200 whose JSON body is not the
  documented shape (list for `/odds`, `/events`, `/scores`, `/sports`; object for event endpoints) raises
  `ProviderError` (PROVIDER_ERROR). `fetch_featured_odds`/`fetch_event_props` only emit quotes for the
  bookmakers and market keys that were requested; anything else in a response is reported in `warnings`
  and the credit estimate counts only requested markets that came back.

## 1. Requests for the foundation

1. **Applied by the lead:** `ManualSelectionInput.team` (name or abbreviation, resolved with
   `normalization.canonical_team`, required for `TEAM_TOTAL`). `providers/manual` now uses it (see section 0).
2. **Applied by the lead:** `GAME_CANCELLED` is in section 7 and `schemas.REASON_CODES`; `freshness.py` uses it.
3. **Contract signature drift (section 5) that the brief overrode.** Implemented per the brief, listed here so
   the pipeline codes against what exists:
   - `providers/nba_injury_report.parse_injury_report_pdf(pdf_bytes, now, slate=None, source_url=None)`
     (contract said `(bytes, report_ts)`; the report timestamp is read from the PDF header instead).
   - `OddsApiProvider.probe(spend_credits: bool = False)` (contract: `probe()`).
   - `fetch_scores(days_from: int | None = 1)` accepts `None` (1-credit live/upcoming call).
   - `providers/fixtures.load_fixture_slate(name, now=None, *, target_book="hardrockbet_fl")` returns a
     `FixtureSlate` NamedTuple; tuple unpacking `(events, quotes, references, injuries)` still works.
   - `providers/base.ProviderResult` has two extra fields beyond the contract: `reason_codes: list[str]`
     (machine-readable, e.g. `BOOK_NOT_AVAILABLE`) and `cached: bool`.
4. **`Settings.daily_provider_credit_budget` (now 25) is enforced as "used >= budget blocks the next paid
   call"**, per the brief, not "used + estimated > budget". With the default 25 and a 3-credit featured call plus
   per-event prop calls, the guard trips mid-slate on a busy night; the lead may want the per-user quota and
   the app-wide budget reconciled in `services.py` (pass `force=True` deliberately, never by default).

## 2. Behaviour the pipeline must know

- **Target book is never substituted.** `fetch_featured_odds` / `fetch_event_props` key every quote by the exact
  bookmaker key returned. When `hardrockbet_fl` was requested and is absent, the target-book quotes are an
  empty list, `reason_codes` contains `BOOK_NOT_AVAILABLE`, and other requested books (e.g. `pinnacle`) are
  still returned for reference use. `hardrockbet` (Indiana), `hardrockbet_az`, `hardrockbet_oh` are ordinary
  reference keys with `jurisdiction=None`.
- **Credits.** `credits_cost` is the documented formula (featured: `markets x ceil(books/10)`, zero when no
  events came back; event odds: `unique requested markets returned x ceil(books/10)`; event markets: 1;
  scores: 2 with `daysFrom` else 1; `/sports` and `/events`: 0) and **0 on a cache hit**. The vendor's own
  `x-requests-last` header is in `quota`. Every non-cached call inserts a `provider_usage` row when a `db` is
  given (user_id from the constructor).
- **Cache.** In-process, keyed by path plus sorted params without the key. TTLs: `/sports` 3600 s, `/events`
  600 s, everything else `settings.provider_cache_ttl_seconds` (60 s). `result.cached` tells you when no
  request was made; the stamps then carry the original receipt time, not the hit time. `provider.clear_cache()`
  forces a refetch (use before the final revalidation; `force=True` only bypasses the credit guard).
- **Source timestamps.** Odds quotes carry the market-level `last_update`; events carry `None` (the events
  endpoint has none) so `check_quote_age` on an *event* stamp is meaningless; use quotes.
- **Player identity is a slug claim.** `player:jalen-brunson` is derived from the bookmaker's name string.
  Settlement must confirm it against a roster-bearing stats source before grading a prop.
- **Injury report team attribution is positional.** The parser carries the printed team label forward to the
  rows below it (that is how the PDF is laid out). In the Oct 19 7:00 PM text extraction no "New York Knicks"
  label appeared in the PHI@NYK block, so rows after "Barlow, Dominick" were attributed to the 76ers by
  carry-forward; the packaged fixture leaves their `team_id` null with a note instead. Treat `team_id` on
  injury rows as "as printed", and treat a prop whose team cannot be matched conservatively (the
  `injury_for_selection` NOT-YET-SUBMITTED rule already does this when the player's team is unknown).
- **Injury decisions** (`injury_context.injury_for_selection`): player markets OUT/DOUBTFUL -> UNUSABLE;
  QUESTIONABLE -> WAIT_FOR_UPDATE (`INJURY_QUESTIONABLE_MATERIAL`); team markets never auto-reject
  (`INJURY_QUESTIONABLE_IMMATERIAL`, `material_to_selection=None`, note tells the user to judge). Stale report
  (`INJURY_REPORT_STALE`) and empty report (`INJURY_REPORT_MISSING`) do not change the decision by themselves;
  the pipeline should downgrade `DataQuality` on those codes.
- **Freshness codes that block vs. warn.** `freshness.BLOCKING_REASON_CODES` and `WAIT_REASON_CODES` are the
  authoritative lists; `is_usable(codes)` and `decision_for(codes)` wrap them. `SOURCE_TIMESTAMP_UNKNOWN`,
  `TIMESTAMP_SKEW`, `REFERENCE_*` and `LINE_MISMATCH` are warnings (the ARCHITECTURE section 11 rule that
  `TIMESTAMP_SKEW` makes the probability state `INSUFFICIENT_EVIDENCE` lives in the quant/pipeline modules).
- **Manual odds text requires a sign.** `110` in pipe/CSV text raises `QUOTE_SIGN_AMBIGUOUS`; JSON integers in
  `odds_american` are taken as typed (they come from the structured MCP argument). Screenshot extraction
  (`slip_fields_from_extraction`) never infers a sign, line, player, stake, combined price or payout
  convention; each missing or ambiguous field is named in `unresolved` and `user_confirmed` stays False.
- **Fixture slate** `opening_night_2026_10_20`: real schedule (19:00Z, 23:00Z, 01:30Z+1), synthetic prices,
  injuries from the Oct 19 7:00 PM report, report timestamp 2026-10-19T23:00:00Z. Pass `now=` to make the
  quotes fresh relative to the test clock (source timestamps are `now - 30 s`); without it the file's
  11:00 AM ET game-day timestamp is used.

## 3. Verified facts the adapter relies on (sources in docs/research/)

- The Odds API: bookmaker keys `hardrockbet_fl` / `hardrockbet` / `hardrockbet_az` / `hardrockbet_oh`;
  `basketball_nba` sport key; cost rules and quota headers; market-level `last_update`; 401 doubles as
  "usage limit"; 404 = expired event on event endpoints (the-odds-api.md sections 1 to 5).
- NBA injury report: URL pattern with 15-minute slots on a zero-padded 12-hour clock, 403 for missing slots,
  header `Injury Report: MM/DD/YY HH:MM AM/PM`, column layout, label carry-forward, wrapped reasons,
  `NOT YET SUBMITTED`, vocabulary Out/Doubtful/Questionable/Probable/Available (nba-schedule-injuries.md
  section 3).
- House rules used only for descriptions: full-game markets include overtime; player props need the player
  to be dressed and see court time (hard-rock-house-rules.md section 6).

## 4. Not verified (needs a live key, not done here)

- Whether `hardrockbet_fl` returns NBA player props / alternates through The Odds API, and whether Pinnacle
  returns props at all. `list_event_markets` (1 credit) is the documented way to find out.
- The exact 401 body text at quota exhaustion; the adapter matches "usage" + "limit" or "quota".
- pypdf layout extraction of the real PDF: tested against a hand-built PDF and the pdftotext-style text
  fixture, not against the live file (no network in tests). If the live file extracts with single spaces
  between columns, `parse_injury_report_text` will not split columns; the fix is to extract with
  `extraction_mode="layout"` (already used) or fall back to `pdftotext -layout` if installed.
