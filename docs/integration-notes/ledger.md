# Integration notes: ledger module (budget, actual_bets, settlement, reports)

Owner: ledger. Files: `src/hardrock_nba_parlay/{budget,actual_bets,settlement,reports}.py`,
`tests/test_{budget,actual_bets,settlement,reports}.py`. Nothing outside these files was edited.

## Requests for the foundation (none blocking; all worked around locally)

1. `GameResult` carries no team identity (only `event_id`, scores, status). A TEAM_TOTAL leg
   (`AcceptedLeg.team_name`) therefore cannot be attributed to home/away from results alone.
   Workaround: `settlement.provisional_from_results(bet, results, stats, events=None)` takes an
   optional `events: Sequence[Event]` and resolves `team_name` against `Event.home_team/away_team`
   (name, abbreviation, id suffix, or last word of the name). Without it the leg stays PENDING.
   Suggestion: add `home_team_id`/`away_team_id` to `GameResult`.
2. `PlayerGameStat.player_id` is optional and `AcceptedLeg` has only `player_name`, so player legs are
   matched on a normalised `player_name_raw` (lower-case, punctuation stripped) within the same
   `event_id`. A stat for a different name is "missing" and the leg stays PENDING.
   Suggestion: let the pipeline write `player_id` into `AcceptedLeg` via a new optional field.
3. `Database.lock_user_day(conn, user_id, date_local, now)` takes `now` (ARCHITECTURE.md section 4
   shows three arguments). The ledger passes `now`; the doc line could be updated.
4. `CostEntry` has no `idempotency_key` field, so `reports.add_cost` signals a replay only through the
   returned `replay: bool`. The key is stored in `costs.idempotency_key` and is per user.
5. The reason code `IDEMPOTENT_REPLAY` is returned as a warning by `settlement.reconcile` and as the
   `replay` boolean by `budget.reserve` / `actual_bets.record_bet` / `reports.add_cost`; services may
   add the code to tool responses when the boolean is true.
6. **Blocking for one review test.** `schemas._nonneg_money` quantizes every `Money` field with the
   default context rounding (ROUND_HALF_EVEN) while the contract (section 0 / section 5 `q_money`) and
   the ledger (`budget.q_money`, `db.cents`) use ROUND_HALF_UP. Observable through the ledger API:
   `budget.reserve(stake 2.345)` stores 2.35 but `ConfirmedTicketInput(stake_usd=2.345)` reaches
   `record_bet` already rounded to 2.34; `SettlementInput(cash_returned_usd=55.005)` becomes 55.00
   (by hand half-up: 55.01). The ledger cannot see the raw value, so it cannot work around this.
   Request: `return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)` in `_nonneg_money`.
   `tests/test_ledger_review.py::test_money_inputs_round_half_up_like_the_ledger` is marked
   `xfail(strict=True)` and will fail (XPASS) once the fix lands; remove the marker then.

## Behaviour the pipeline/server modules should know

- Exceptions: `budget.LedgerError(ValueError)` is the base; subclasses `NotFoundError` (NOT_FOUND),
  `IdempotencyConflictError` (IDEMPOTENCY_CONFLICT), `ReservationNotActiveError`
  (RESERVATION_NOT_ACTIVE), `BudgetExceeded` (BUDGET_EXCEEDED; `.remaining`). All carry
  `.reason_codes` for mapping to `ToolError`. `db.FixtureLedgerError` propagates unchanged.
- `record_bet` consumes EVERY ACTIVE reservation of the candidate for that user and links the oldest as
  `reservation_id`. Reservation date and bet date may differ (reserve at 23:50 ET, place at 00:05 ET);
  the budget of the placement date is what is charged.
- `record_bet` data_mode: pass the `DataMode` of the data that produced the ticket
  (`MANUAL_INPUT` for user-typed/receipt tickets). FIXTURE is refused on a real ledger.
- `reconcile` defaults apply to BOOK_CONFIRMED records only: VOID -> cash = stake, LOST -> cash =
  0.00. WON without `cash_returned_usd` is stored but has no profit (reports list it under
  `incomplete_data_notes`); the server/skill should ask the user for the cash returned figure rather
  than computing stake x odds. PROVISIONAL_NBA_RESULTS records get no defaults, store only what the
  caller supplied, and `settlement.cash_profit` returns None for them: a provisional result never
  moves net profit.
- `reconcile` replay = payload identical to the bet's LATEST settlement record (same status, source,
  money at 2 dp, odds at 4 dp, leg results, settled_at, notes). A payload identical to an older
  record is a new event and is appended (the book reverting a correction). The stored
  `payload_hash` is `sha256(prev_seq + canonical json)`, so `UNIQUE(bet_id, payload_hash)` holds.
  Consequence: a provisional re-run identical to an older provisional record, after a book record
  intervened, appends a SUPERSEDED_BY_BOOK row rather than replaying.
- `actual_bets.ticket_payload_hash` hashes the values the ledger stores (odds 4 dp, money 2 dp, lines
  without trailing zeros, ISO UTC datetimes, American odds resolved to decimal), so a retry that
  respells a Decimal replays instead of raising IDEMPOTENCY_CONFLICT. Hashes of bets recorded before
  this change will not match a retry (pre-release; no migration).
- The record that governs a bet is `settlement.effective_settlement(records)` (latest BOOK_CONFIRMED,
  else latest) / `settlement.current_effective_settlement(db, user_id, bet_id)`; reports use it.
  `actual_bets.current_settlement` is still "highest seq" (the audit view). Provisional settlements
  never write leg results into the bet record; `settlement.effective_leg_results(bet, record)`
  returns the book-graded legs even when handed a later superseded provisional record.
- `reports.performance` ticket win rate denominator = tickets with a binary result per
  `settlement.ticket_outcome`: WON/LOST status, or CORRECTED resolved by a 0.00 cash return (LOST)
  or by its corrected leg results (any LOST -> LOST, all WON -> WON). CASHED_OUT, REPRICED, VOID,
  PARTIALLY_VOID and unresolved corrections are excluded from the rate but included in net profit
  when the book cash figure is known. Net profit counts book-confirmed cash only.
- `reports.dashboard_html(report, budget_today, costs_list=None)`: the optional third argument itemises
  costs; without it only the window total is shown.
- `budget.list_reservations(db, user_id, date_local, now=None)`: pass `now` to expire stale rows first.

## Verified

- `uv run pytest tests/test_ledger*.py tests/test_budget.py tests/test_actual_bets.py tests/test_settlement.py tests/test_reports.py -q` -> see the fixer report (all pass; one xfail for item 6).
- The threaded reservation test (10 threads x $3 against $10 on the SQLite test DB) passes repeatedly:
  exactly 3 succeed, 7 raise `BudgetExceeded`, total reserved $9.00.
