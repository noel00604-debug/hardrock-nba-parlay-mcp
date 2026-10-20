# Integration notes: pipeline (candidate_builder.py, quote_review.py, services.py)

Owner: pipeline. Files: `src/hardrock_nba_parlay/{candidate_builder,quote_review,services}.py`,
`tests/test_{candidate_builder,quote_review,services,e2e_fixture,pipeline_review}.py`, this note. No foundation
file, research note, or other module was edited. Written 2026-10-19 evening ET; section 0 added later that
evening after the independent review.

## 0. Review fixes applied (2026-10-19, later in the evening)

An independent reviewer reproduced fourteen defects in `tests/test_pipeline_review.py`; all are fixed in the
module code (no reviewer test was weakened). Three of the module's own tests were corrected because they
were wrong against the contract (section 0 of ARCHITECTURE: fixture records never reach a real ledger):
`test_candidate_builder.py::test_candidate_data_mode_prefers_fixture_then_manual`,
`test_quote_review.py::test_user_ticket_multi_game` and
`test_e2e_fixture.py::test_wait_for_update_for_a_questionable_prop` expected a typed ticket matched to the
FIXTURE slate to be labelled `MANUAL_INPUT`; it is `FIXTURE`. Behaviour changes the server/ledger/data owners
should know:

- **`legs_as_shown` must describe the same bet, not merely the same game** (`quote_review.match_legs_as_shown`).
  A spread line must carry the sign the leg was offered at (`DET -3.5` and `Pistons 3.5` both conflict with the
  `DET +3.5` leg); a team market's subject is the team written outside any `X @ Y` / `X at Y` / `X vs Y` matchup
  phrase (`OKC @ SAS: Spurs ML` conflicts with the OKC moneyline leg, `OKC @ SAS: Thunder ML` matches); a slip
  line naming an NBA team that is not playing in the leg's game is another game's bet (`Celtics @ Pistons Over
  224.5` conflicts with the PHI/NYK total). A player's name is excluded from that check (`P.J. Washington`
  is not the Wizards). Ambiguous spellings shared by two clubs (`LA`, `Los Angeles`) never count as a foreign
  team.
- **Book-quote capture age** (`review_book_quote`): a `captured_at_utc` more than `max_odds_age_seconds` from
  `now` is `QUOTE_STALE`; the quote is stored with `captured_at_utc` in `unresolved_fields` and NOT applied
  (payout math stays indicative, state NEEDS_BOOK_QUOTE). `refresh_parlay` never resurrects it: `revalidate`
  restores READY only when the stored quote has no field in `quote_review.BLOCKING_UNRESOLVED_FIELDS`
  (`legs_as_shown`, `combined_odds`, `payout_shown_usd`, `captured_at_utc`, `price_changed`). The remedy is a
  re-import of a current quote (`select_ticket` says so with `QUOTE_STALE`). A quote imported within the limit
  stays valid across refreshes whose leg prices are unchanged (the existing rule).
- **Payout contradiction** (`review_book_quote`): a slip stake and payout that cannot be produced by the combined
  price (either convention is tried when `payout_includes_stake` is unknown) is reported as
  `QUOTE_SIGN_AMBIGUOUS` with `payout_shown_usd` unresolved; the quote is stored but not applied. The section-7
  vocabulary has no closer code: the slip's own figures disagree, so the price reading is ambiguous.
  `select_ticket` names `QUOTE_SIGN_AMBIGUOUS` for both `combined_odds` and `payout_shown_usd` unresolved
  fields instead of sending the caller to import a quote it already imported.
- **Typed legs keep their line on refresh** (`revalidate`): a MANUAL_INPUT leg follows the feed only when the feed
  carries exactly the same bet (same `selection_id`); otherwise it is kept at the typed line and re-analysed
  against the fresh benchmarks (`LINE_MISMATCH` when none exists at that line). It is never rewritten to the
  feed's main line and never reported `MARKET_SUSPENDED`. `services.refresh_parlay` no longer patches the fresh
  list; the rule lives in `revalidate`.
- **A benchmark of unmeasurable age gives no baseline** (`candidate_builder.analyze_leg`): when the benchmark has
  no `source_timestamp_utc` the probability is INSUFFICIENT_EVIDENCE with method and reason code
  `SOURCE_TIMESTAMP_UNKNOWN` (section 11: the skew rule is never silently loosened; an unmeasurable skew cannot
  satisfy it). A typed (MANUAL_INPUT) target without `observed_at_utc` was observed when the user typed it, so
  its skew against the benchmark is measured from `received_at_utc` (its own freshness check still reports
  `SOURCE_TIMESTAMP_UNKNOWN`, grade B at best, as before); a typed leg therefore gets `TIMESTAMP_SKEW` on a
  refresh whose benchmarks are more than `max_reference_skew_seconds` newer than the typing, and the remedy is
  to re-type the slip. A LIVE/FIXTURE target without a source timestamp has an unmeasurable skew.
- **Data mode of a ticket** (`candidate_data_mode(legs, analyses=None)`): FIXTURE when any leg quote, any leg's
  event, or any benchmark behind the leg analyses is fixture data; else MANUAL_INPUT when any leg was typed;
  else LIVE_PROVIDER. In `HRNBA_DATA_MODE=fixture` a typed ticket is therefore FIXTURE and `record_actual_bet`
  is refused on a real ledger (`FIXTURE_DATA`). Injury entries do not set the mode.
- **`select_ticket` guards the ledger mode**: `db.guard_ledger_mode(candidate.data_mode)` runs before any
  reservation (`reservations` is a ledger table), so a FIXTURE candidate never holds real budget
  (`InvalidInput`, `["INVALID_INPUT", "FIXTURE_DATA"]`).
- **`select_ticket` default idempotency key** (`services._default_select_key`): without a caller key the call
  replays the candidate's live (ACTIVE, unexpired) reservation through that reservation's own key (same stake:
  `replay=True`; different stake: `IDEMPOTENCY_CONFLICT` whose message names `release_reservation`). Once that
  reservation was released or expired, a fresh key is minted (`select:<candidate_id>`, then
  `select:<candidate_id>:2`, `:3` ...) so a dead reservation is never replayed as if it held budget. Two
  concurrent default-key calls still cannot double-reserve: the second finds the first's key inside
  `budget.reserve` and replays or conflicts.
- **Injury feed failure degrades, never aborts** (`services._fetch_injuries`): an `errors.ProviderError` from
  `fetch_latest_report` is logged (redacted) and turned into the modelled `INJURY_REPORT_MISSING` state (warning
  plus reason code, no entries); `build_three_leg_parlays` still prices and persists the slate whose odds credits
  were already spent. `get_injury_context` and `check_data_coverage` report the same code.
- **`auto` counts events over ALL usable legs** (`candidate_builder.build_candidates`), and for a MULTI_GAME
  search the 24-leg cut is taken round-robin across events (`_search_legs`: each event keeps its best legs) so
  one game with many strong props cannot hide the other games. Same-game / mixed searches keep the global
  order (depth inside one game). `SearchStats.events_with_usable_legs` now counts all usable legs.
- **Hosted credit quota applies to the server-wide key only** (`services._guard_credits`): a user whose own key
  resolved (`ProviderRegistry.key_source == "user"`) is never refused with `PROVIDER_CREDIT_GUARD`, which is
  what the guard's own hint promises. Their usage rows are still written for accounting.
- **`export_my_data` never returns key material**: `services.scrub_export_bundle` blanks
  `user_settings.odds_api_key_encrypted` (and adds `has_own_odds_api_key`) before the bundle leaves the service.
  Request for the server owner: `web.account_export` calls `db.export_user` directly and still includes the
  ciphertext in the JSON download; route it through `services.export_my_data` or `scrub_export_bundle`.
  `db.import_user` ignores the extra key, so a scrubbed bundle still imports.
- **`analyze_leg` spends props credits one game at a time**: props are fetched per event and the search stops at
  the first event that carries the selection (a featured-market selection fetches no props at all).
- **`set_user_settings(daily_cap_usd)` and every stake are quantized before the `> 0` check**
  (`services._money`): `0.004` is `0.00` and is refused (`INVALID_INPUT`); the message says at least 0.01.

Verified after the fixes (no network): `uv run pytest tests/test_pipeline_review.py tests/test_candidate_builder.py
tests/test_quote_review.py tests/test_services.py tests/test_e2e_fixture.py -q` and the whole suite; see the
fixer report for the exact summary lines.

## 1. Requests for the foundation (worked around locally; none blocking)

1. **`RecordResponse` has no `warnings` field.** The brief asks for `IDEMPOTENT_REPLAY` in warnings on a
   replayed `record_actual_bet`; the model only has `replay: bool` and `breach_flags` (budget flags), and
   `extra="forbid"` blocks an extra field. The replay is reported through `replay=True` only. Request: add
   `warnings: list[str] = []` to `RecordResponse` (and to `SelectResponse`, `DailyBudget` for the same reason).
2. **`add_cost` returns `CostEntry` and drops the replay flag.** `mcp_server.add_cost` is annotated
   `S.CostEntry | S.ToolError`, so the service returns the entry; `reports.add_cost`'s `replay` boolean is
   discarded. Request: a `CostResponse(entry, replay)` or a `replay` field on `CostEntry`.
3. **No tool argument asks for the demo slate explicitly.** The brief allows the fixture slate "when no odds
   key exists and the caller asks for the demo slate explicitly"; no MCP tool or CLI command carries such an
   argument, so the only explicit request today is `HRNBA_DATA_MODE=fixture`. In live mode with no key every
   odds-needing tool raises `NO_PROVIDER_KEY` with the hint (`HRNBA_ODDS_API_KEY`, `hrnba secret set
   ODDS_API_KEY`, or `HRNBA_DATA_MODE=fixture`). Live never falls back to fixture. If a per-call demo switch
   is wanted, add `demo: bool = False` to `get_nba_slate` / `build_three_leg_parlays` and the services will
   honour it through `ProviderRegistry.fixture` (already constructed in fixture mode).
4. **`NEEDS_ONBOARDING` has no slot on several responses.** It is added to `warnings` where the model has one
   (`SlateResponse`, `InjuryResponse`, `BuildResponse`, `SettlementResponse`), to `reason_codes` on the
   returned `Candidate` / `LegAnalysis` (never on the persisted record), and as a note on `CoverageReport` /
   `PerformanceReport` (`ReviewReport.performance.notes`). `DailyBudget`, `BudgetReservation`,
   `RecordResponse`, `CostEntry`, `CorrelationReport` and `UserSettings` cannot carry it. Request: a shared
   `warnings` field on those models.
5. **Candidate state names are not reason codes.** `select_ticket` refuses a non-READY candidate with section-7
   codes and names the state in the message and `detail` (`state=NEEDS_BOOK_QUOTE`): no quote stored ->
   `QUOTE_FIELDS_MISSING`; slip legs mismatched -> `QUOTE_CONFLICTS_WITH_LEGS`; quote stored unconfirmed ->
   `QUOTE_UNCONFIRMED`; price moved since the quote or inputs stale -> `QUOTE_STALE` (run `refresh_parlay`);
   leg waiting on an injury update -> `WAIT_FOR_UPDATE`; EXPIRED -> `GAME_STARTED`; REJECTED -> the blocking
   code that rejected it (else `NO_SUITABLE_TICKET`); placed or settled -> `INVALID_INPUT`.
6. **`FIXTURE_DATA` is used as a reason code.** It is in `schemas.REASON_CODES` but not in ARCHITECTURE section
   7. `db.FixtureLedgerError` maps to `InvalidInput` with `["INVALID_INPUT", "FIXTURE_DATA"]`; fixture
   responses carry `FIXTURE_DATA` in `reason_codes`. Request: add `FIXTURE_DATA` and `MANUAL_DATA` to section 7.
7. **`build_providers` call shape.** The brief says `build_providers(settings, db, clock, user_id=None)`;
   `mcp_server.make_request_context` calls `build_providers(ctx)`. Both are accepted (a `RequestContext` first
   argument wins). The consumer shape is the one exercised by the server.
8. **Contract signature additions.** `build_candidates(..., stake_usd=None, *, analyses=None, stats=None)`,
   `review_book_quote(candidate, quote, now, settings=None, *, max_odds_age_seconds=None)` (the contract's
   three-argument form still works with the 180 s default), `analyze_user_ticket(..., stake_usd=None, *,
   clock=None, analyses=None)`, `transition(ctx, candidate, to_state, reason, extra=None)`,
   `save_candidate(ctx, candidate, *, from_state=None, reason=None, extra=None, date_local=None)`.
9. **`TEAM_TOTAL` is never requested from providers** (`ReferenceTwoWay` cannot name the team and
   `ManualSelectionInput` has no team field; see quant.md item 1 and data.md item 1). Coverage reports it as
   BLOCKED / UNKNOWN; a typed TEAM_TOTAL leg is refused by `providers.manual` with `MARKET_NOT_OFFERED`.

## 2. Decisions other modules should know

- **Freshness composition.** The pipeline does not use `freshness.revalidation_reasons` because it labels a
  stale benchmark `QUOTE_STALE` (blocking). The leg analysis applies `check_event_not_started`,
  `check_quote_age` on the target, and `check_reference_skew`; a stale or skewed benchmark only downgrades the
  probability to INSUFFICIENT_EVIDENCE with method `TIMESTAMP_SKEW` (section 11), it never blocks the leg.
  A benchmark from the target book itself is discarded (`REFERENCE_MISSING`, reason text says so).
- **Benchmark-side mismatches.** `estimate_leg_probability` methods `PLAYER_UNMATCHED` / `EVENT_UNMATCHED`
  describe the benchmark, not the selection; the pipeline records them as `REFERENCE_MISSING` so
  `freshness.decision_for` does not mark the leg UNUSABLE. The selection's own identity is checked separately
  (`identity_matched`; failure adds `PLAYER_UNMATCHED` / `TEAM_UNMATCHED` and grade D).
- **Typed legs without `observed_at_utc`** get `SOURCE_TIMESTAMP_UNKNOWN` (not blocking) from the target
  freshness check and `target_fresh` fails (grade B at best); their skew against the benchmark is measured from
  `received_at_utc` (section 0), so the probability is computed when that skew is within the limit. A
  benchmark without a source timestamp never yields a probability.
- **Data-quality grade**: A = every named check passes (`target_fresh`, `reference_complete`,
  `reference_fresh`, `injury_report_current`, `identity_matched`, `rules_profile_known`), B = one failure,
  C = two, D = three or more, a stale target quote, or an unresolved identity. On opening night the 7:00 PM
  report is older than `injury_report_max_age_seconds` by game time, so every leg is at best B until a newer
  report is fetched.
- **Strongest reason against** (priority): game started / postponed, unsupported period, stale target,
  OUT / DOUBTFUL / QUESTIONABLE prop player, team not yet submitted, no benchmark (or benchmark equals the
  target book, or skew), questionable teammate on a team market, price below the benchmark, alternate line,
  unknown source timestamp, stale injury report, then "benchmark is <book>'s price as relayed by the odds
  feed, which may be delayed".
- **Ranking** (`Candidate.ranking`, all strings): `evidence_tier` (A = three benchmarked legs with a joint
  probability, B = two or three benchmarked legs without one, C = one, D = none), `legs_with_reference`,
  `sum_edge`, `min_grade`, `model_state`, `parlay_type`, `note` = "ranking never uses payout size". Sorted by
  tier, then legs with reference, then sum of edges, then grade. Same-game and mixed candidates carry
  `SAME_GAME_CORRELATION`, `JOINT_PROBABILITY_UNAVAILABLE`, `EV_UNAVAILABLE`, `p_joint=None`, no EV, and a
  rationale that says they are qualitative and not called value.
- **Search bound**: USABLE legs ordered by (has market-baseline probability, edge desc, grade); the 24-leg cut
  is round-robin across events for a MULTI_GAME search and global otherwise (section 0); then
  `itertools.combinations` (at most 2024 evaluated, counted in `BuildResponse.combinations_evaluated`).
  "auto" builds MULTI_GAME only when three or more events have usable legs (over all usable legs); with fewer
  it builds the qualitative SAME_GAME / MIXED set; "multi_game" never falls back.
- **Candidate persistence**: `candidates.json` = `Candidate.model_dump(mode="json")`, `date_local` = ET date
  of the earliest tip-off, every state change appends a `candidate_history` row (build:
  RESEARCH_CANDIDATE -> NEEDS_BOOK_QUOTE). `book_quotes` gets one row per imported quote (conflicting and
  unconfirmed ones included, marked in `unresolved_fields`). Reservations and bets are charged to today's ET
  day (`America/New_York`), never to `display_tz`.
- **`select_ticket` idempotency**: when the caller passes no key the candidate's live reservation is replayed
  (same stake) or defended (`IDEMPOTENCY_CONFLICT` for a different stake until it is released); after a release
  or expiry a new attempt key is minted (section 0). The reservation id is recorded in
  `Candidate.ranking["reservation_id"]`; the candidate stays READY_FOR_USER_REVIEW. The returned `DailyBudget`
  has `proposed_stake_usd` set to the stake after the reservation was taken (so it shows recorded, reserved,
  proposed and remaining without a spurious `BUDGET_EXCEEDED` breach). A FIXTURE candidate is refused before
  any write (`FIXTURE_DATA`).
- **`refresh_parlay`** clears the provider cache first, fetches featured odds (plus props for events with prop
  or alternate legs), persists snapshots, and calls `quote_review.revalidate`. A typed (MANUAL_INPUT) leg is
  kept at the line the user typed unless the feed carries exactly the same bet, and is never reported
  `MARKET_SUSPENDED` (section 0); a typed price is compared with the feed at the schema's American/decimal
  tolerance (0.0105), feed prices exactly. A price or line move of a feed leg keeps the old `BookQuote` on the
  record but marks it unresolved (`price_changed`, `confirmed_by_user` False) and the payout math reverts to
  the indicative product until the slip quote is re-imported.
- **`record_actual_bet`** stores `{candidate_id, p_joint, p_joint_method, model_state, parlay_type,
  market_composition, recommended_combined_decimal, recommended_source, ev_per_dollar, data_mode,
  inputs_snapshot_utc, legs}` as the forecast snapshot; `data_mode` comes from the candidate (MANUAL_INPUT when
  no candidate is linked); the candidate moves to USER_CONFIRMED_PLACED. A final BOOK_CONFIRMED settlement
  moves it to SETTLED.
- **Per-user key**: Fernet with key = urlsafe-base64(sha256(`HRNBA_SECRET_KEY`)). `set_user_settings(
  odds_api_key="")` clears it. A stored key that no longer decrypts (secret rotated) falls back to the server
  key with a warning in `SystemStatus.warnings`; nothing crashes. The decrypted key is never logged, returned,
  or written to the audit log (`settings.update` audit rows record `[set]`).
- **Hosted credit quota**: in `auth_mode != "none"` every credit-spending call (featured odds, event props,
  event markets) on the SERVER-WIDE key first sums `provider_usage.credits_cost` for `ctx.user_id` within the
  current ET day and raises `PROVIDER_CREDIT_GUARD` at `per_user_daily_credit_quota`. A user's own stored key
  (`key_source == "user"`) is never throttled. Free `/events` calls are not guarded.
  The live `OddsApiProvider` is built with `user_id=ctx.user_id` so its usage rows carry the user; it is
  cached per (database url, user id, key fingerprint, clock) so the 60 s response cache survives across tool
  calls.
- **Fixture mode** (`HRNBA_DATA_MODE=fixture`): `services.FixtureOddsProvider` serves events, featured odds,
  event props, event markets and the injury report from the packaged `opening_night_2026_10_20` slate with
  FIXTURE stamps and zero credits; `received_at=` pins the receipt time (tests use it to make every leg
  stale). Every response says FIXTURE in `data_mode`, `reason_codes` (`FIXTURE_DATA`) and warnings; a typed
  ticket analysed in fixture mode is FIXTURE too, and neither `select_ticket` nor `record_actual_bet` writes
  it to a real ledger.
- **Coverage report**: featured markets PASS / PARTIAL / BLOCKED by games with target quotes; props and team
  totals UNKNOWN unless `probe_props=True` (one credit per game live, `list_event_markets`); reference
  markets by complete two-ways at the same line; injury PASS / PARTIAL (stale) / BLOCKED (missing);
  `three_leg_combinability` UNKNOWN `COMBINATION_UNVERIFIED`; `combined_payout_verification` BLOCKED
  `QUOTE_FIELDS_MISSING`; `stats_and_settlement_rules` PARTIAL `PROVISIONAL_RESULT`; notes carry the median
  reference-vs-target `last_update` skew and whether it is within `max_reference_skew_seconds`.

## 3. Verified (2026-10-19 evening ET, no network)

- `uv run ruff check src/hardrock_nba_parlay/{candidate_builder,quote_review,services}.py tests/test_{candidate_builder,quote_review,services,e2e_fixture}.py` -> `All checks passed!`
- `uv run pytest tests/test_candidate_builder.py tests/test_quote_review.py tests/test_services.py tests/test_e2e_fixture.py -q` -> `99 passed in 1.14s`
- `uv run pytest -q` (whole repository) -> `676 passed in 6.86s`
- `HRNBA_DATA_MODE=fixture hrnba --json build --date 2026-10-20 --no-props` through the real CLI and
  `mcp_server.make_request_context(services, ...)` both produce three MULTI_GAME candidates from the fixture
  slate; `hrnba --json status` reports `data_modes_available = [MANUAL_INPUT, FIXTURE]`.
- Not verified: anything against the live Odds API or the live NBA injury PDF (needs a key; the adapter's
  own behaviour is covered by the data module's tests).
