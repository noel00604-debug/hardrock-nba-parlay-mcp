# Workflows: the seven day-one prompts mapped to tool calls

Tool names are exact. Arguments in brackets are optional. Every workflow starts with the
AI-involvement disclosure (SKILL.md section 1) and states the data mode.

## Prompt 1: "Review today's NBA slate for a three-leg Hard Rock Florida parlay within my $10 daily cap."

1. `get_system_status()` -> confirm provider state, cap, warnings.
2. `check_data_coverage(date_local)` -> which markets Hard Rock FL carries today, whether
   references and the injury report are current, whether combinability and the combined
   payout can be verified.
3. `get_nba_slate(date_local)` -> games with ET start times (with offset) and status.
4. `build_three_leg_parlays(date_local, parlay_type="auto", max_candidates=3, include_props=true)`.
5. `check_parlay_correlation(candidate_id)` for the primary candidate.
6. `get_daily_budget(date_local, proposed_stake_usd)`.

Expected output: coverage summary (PASS / PARTIAL / BLOCKED per item), the slate, one
primary candidate in the eight-block format, up to two alternatives, and the budget line.
Or NO SUITABLE TICKET with reason codes.

## Prompt 2: "Give me one primary candidate and explain the weakest leg."

Same as prompt 1 with `max_candidates=1`, or reuse today's primary candidate. Then for
the weakest leg call `analyze_leg(selection_id, date_local)` and present its facts (with
sources and timestamps), interpretations, injury entries, data-quality grade (not a win
probability), probability estimate with method and state, price value, and the
strongest reason against. Name the rule used to pick the weakest leg.

## Prompt 3: "Compare a three-game parlay with this same-game parlay without assuming independence."

1. Multi-game: today's primary `MULTI_GAME` candidate from `build_three_leg_parlays`.
2. Same-game: collect the user's three legs as structured fields, then
   `analyze_my_parlay(three_selections, combined_odds)` and
   `check_parlay_correlation(candidate_id)`.
3. Present both in the eight-block format side by side.

Expected output: the multi-game ticket shows an independence baseline labelled as an
assumption and a break-even threshold; the same-game ticket shows `joint_numeric_allowed
= false`, joint probability unknown, the correlation flags, a qualitative review, and
the app's quote if the user supplied it. State that the SGP cannot be ranked above the
multi-game ticket on EV because its EV is unavailable.

## Prompt 4: "Here is my Hard Rock bet-slip screenshot. Verify the three selections and combined payout."

1. Extract fields in chat and list the ambiguous ones (SKILL.md section 10).
2. Ask the user to confirm.
3. `analyze_my_parlay(three_selections, combined_odds)` with
   `combined_odds.source = SCREENSHOT_EXTRACTED` and `user_confirmed = true`.
4. `check_parlay_correlation(candidate_id)`.

Expected output: whether the three selections match the slate (event, market, line,
period, player identity), whether the legs as shown match the structured legs
(`QUOTE_CONFLICTS_WITH_LEGS` if not), the combined quote and whether the shown payout
includes the stake, payout math at the shown stake, the correlation flags, and the
rechecks list. Any unresolved field is named; the ticket is not READY until resolved.

## Prompt 5: "Refresh this ticket using current injuries and prices before I decide."

1. `refresh_parlay(candidate_id)`.
2. If still READY, `get_daily_budget(date_local, proposed_stake_usd)` and, on the user's
   choice, `select_ticket(candidate_id, stake_usd, idempotency_key)`.

Expected output: new state, what changed (price deltas, injury designation changes,
start-time status), the full candidate block if still READY, otherwise `EXPIRED` or
`REJECTED` with reason codes and the preserved history. The budget line shows recorded,
reserved, proposed, and remaining amounts, and the reservation expiry.

## Prompt 6: "I placed this exact ticket for $10 at these accepted odds. Record it."

1. Confirm legs, stake, accepted combined odds, placement time, ticket reference.
2. `record_actual_bet(confirmed_ticket_fields, idempotency_key)` with
   `source = USER_CONFIRMATION` (or `RECEIPT_REVIEW` for a reviewed receipt),
   `candidate_id` when the ticket came from a candidate, `external = true` otherwise.

Expected output: the bet id, the three accepted legs, accepted versus recommended
combined odds and the difference, the reservation consumed (if any), today's budget
after recording, and `BUDGET_BREACH_RECORDED` if the stake exceeded the cap. A replay
of the same idempotency key returns the existing record and `replay = true`.

## Prompt 7: "Show my actual results, costs, and remaining daily budget."

1. `get_daily_budget(date_local)`.
2. `get_performance(start_date, end_date)` (default: 2026-10-20 to today).
3. When asked for the first month: `generate_30_day_review()`.
4. If the user reports a settlement: read the status back, get the user's confirmation,
   then `reconcile_settlement(bet_id, settlement_fields)` first. The status comes from
   the app result the user reports (`BOOK_CONFIRMED`) or from scores the user typed
   (`PROVISIONAL_NBA_RESULTS`); never from results Claude looked up or recalled, since
   no tool returns scores.

Expected output: tickets placed, total stake, cash returned, net profit or loss,
pending exposure, voids, ticket win rate and leg hit rate with denominators, results by
parlay type and market composition, accepted versus recommended odds, data costs and the
after-cost result, every ticket including losses, provisional results marked as such,
and today's remaining budget. No invented balance, no win rate without settled tickets.

## Injury-report deadlines (official NBA schedule, quoted verbatim)

Source: https://official.nba.com/nba-injury-report-2025-26-season/ (retrieved
2026-10-19 23:06 UTC; the 2026-27 URL returned 404 on the same day). These are the only
deadlines this skill may state. Quotes:

1. "NBA teams must report information concerning player injuries, illnesses, other
   medical conditions, or rest for all NBA games."
2. "By 5 p.m. local time the day before a game (other than the second day of a
   back-to-back)," teams "must designate a participation status" and "identify a
   specific injury, illness, other medical condition, or other reason" for "any player
   whose participation in the game may be affected for any reason."
3. "For the second game of a back-to-back, teams must report the above information by
   1 p.m. local time on the day of the game."
4. "teams are required to submit a game-day injury report between 11 a.m. and 1 p.m.
   local time" "(and between 8 and 10 a.m. for tip-offs 5 p.m. or earlier) on game
   days (besides the second game of a back-to-back)."
5. "Reports are updated on a continual basis throughout the day."

The page does not state a fixed ET publication time, a "30 or 60 minutes before
tip-off" rule, or definitions of Out, Doubtful, Questionable, Probable, and Available.
Deadlines are in the team's local time, not ET.

How to state the next deadline for a WAIT FOR UPDATE leg:

- The report time to quote is `report_timestamp_utc` from `get_injury_context` or the
  leg's injury entries, rendered in ET with offset.
- Before game day: the next deadline is 5 p.m. local time the day before the game
  (rule 2), unless the game is the second of a back-to-back, in which case 1 p.m. local
  time on game day (rule 3).
- On game day: between 11 a.m. and 1 p.m. local time, or between 8 and 10 a.m. local
  time for "tip-offs 5 p.m. or earlier" (rule 4; the page does not say which time zone
  the 5 p.m. cutoff uses, and the source note treats the 3:00 PM ET Detroit tip as
  qualifying); second game of a back-to-back: by 1 p.m. local time (rule 3). After
  that window, only rule 5 applies: say that the report can be updated at any time and
  no further fixed deadline exists.
- "Local time" is the home team's time zone. State the deadline in local time as the
  page gives it and convert to ET only when the home team's zone is certain (the source
  note establishes Detroit and New York as ET and San Antonio as CT). Whether a game
  is the second of a back-to-back must come from the slate; if the slate does not show
  the previous day, say so.
- If the tip time, the home team's time zone, or the back-to-back status is unknown
  from the tool responses, say "next report deadline: unknown". Never invent a time.

Worked example for 2026-10-20, from the same source note: the day-before deadline was
5 p.m. local on Oct 19; the game-day report for Boston at Detroit (3:00 PM ET tip, so
"5 p.m. or earlier") is due between 8 and 10 a.m. Detroit time (ET); the 7:00 PM ET
game in New York gets its game-day report between 11 a.m. and 1 p.m. ET; the 9:30 PM
ET game in San Antonio between 11 a.m. and 1 p.m. CT (12 p.m. to 2 p.m. ET).

## Other tools

- `get_injury_context(event_id)`: the official report entries for one game when the user
  asks about a specific player or game.
- `release_reservation(reservation_id, reason)`: the user decided not to bet.
- `set_user_settings(daily_cap_usd, display_tz, odds_api_key, confirm_onboarding)`:
  first-run onboarding and later changes. The provider key is stored encrypted on the
  server for that user only; never echo it.
- `add_cost(date_local, description, amount_usd, category, idempotency_key)`: data or
  software costs so the after-cost result is honest.
- `export_my_data()`: the user's own records as structured data.
