# Use cases: working prompts and their tool sequences

The Anthropic Software Directory Policy (3.E) requires at least three working examples
of prompts or use cases. Five are listed; each names the expected tool sequence and the
expected output. "Working" is a claim about the live server, so every row carries a
status to be filled by the integration lead after running it against the deployed
server with a real The Odds API key.

| # | Prompt | Verified against live server |
|---|---|---|
| 1 | Review today's NBA slate for a three-leg Hard Rock Florida parlay within my $10 daily cap. | PENDING INTEGRATION TEST |
| 2 | Here is my Hard Rock bet-slip: Celtics -2.5 at -110, 76ers/Knicks over 224.5 at -110, Thunder ML at -150. Verify the three selections and combined payout of +507. | PENDING INTEGRATION TEST |
| 3 | I placed this exact ticket for $10 at +507. Record it. | PENDING INTEGRATION TEST |
| 4 | Show my actual results, costs, and remaining daily budget. | PENDING INTEGRATION TEST |
| 5 | Compare a three-game parlay with this same-game parlay without assuming independence. | PENDING INTEGRATION TEST |

The odds in prompts 2 and 3 are illustrative examples of the input format, not real
quotes. +507 is the product of the three leg prices (1.9091 x 1.9091 x 1.6667 = 6.0744
decimal), so the indicative product and the quoted price agree in the example; a real
Hard Rock quote may differ, and the app's combined odds govern.

## Use case 1: daily research within the cap

Tools: `get_system_status` -> `check_data_coverage(date_local)` ->
`get_nba_slate(date_local)` -> `build_three_leg_parlays(date_local)` ->
`check_parlay_correlation(candidate_id)` -> `get_daily_budget(date_local, proposed_stake_usd)`.

Expected: the AI disclosure; the slate with ET times; a coverage summary; one primary
candidate in the eight-block format (three-row table, reasons against, correlation
flags, NEEDS BOOK QUOTE or quote, model state and break-even, stake and payout,
rechecks); up to two alternatives; the budget line. On an inadequate day: NO SUITABLE
TICKET with reason codes. Reads data only; creates candidate records.

## Use case 2: verify a user's ticket and payout

Tools: `analyze_my_parlay(three_selections, combined_odds)` ->
`check_parlay_correlation(candidate_id)`.

Expected: each leg matched to the slate (or `EVENT_UNMATCHED`, `PLAYER_UNMATCHED`,
`LINE_MISMATCH`); the correlation flags; the combined quote accepted as the book price
(or `QUOTE_CONFLICTS_WITH_LEGS` if the legs shown do not match); payout math at the
stated stake; rechecks. For a screenshot the fields are extracted and confirmed in chat
first. Creates one candidate record.

## Use case 3: record a placed wager

Tools: `record_actual_bet(confirmed_ticket_fields, idempotency_key)`.

Expected: a bet id, the three accepted legs, accepted versus recommended odds, the
updated daily budget, and `BUDGET_BREACH_RECORDED` if over the cap. Repeating the same
request returns the same bet with `replay=true`. Appends to the ledger; never places a
bet.

## Use case 4: results, costs, remaining budget

Tools: `get_daily_budget(date_local)` -> `get_performance(start_date, end_date)` (and
`generate_30_day_review()` for the first month).

Expected: tickets, stakes, cash returned, net, pending exposure, voids, ticket win rate
and leg hit rate with denominators, per-type breakdowns, accepted versus recommended
odds, data costs and after-cost net, every bet including losses, provisional results
marked. Reads only.

## Use case 5: multi-game versus same-game comparison

Tools: today's `MULTI_GAME` candidate from `build_three_leg_parlays` plus
`analyze_my_parlay` for the user's same-game legs, then `check_parlay_correlation` on
both.

Expected: the multi-game ticket shows an independence baseline labelled as an
assumption; the same-game ticket shows `joint_numeric_allowed=false`, joint probability
unknown, qualitative correlation review, and the app's quote if provided; the output
states that the same-game ticket cannot be ranked on EV.
