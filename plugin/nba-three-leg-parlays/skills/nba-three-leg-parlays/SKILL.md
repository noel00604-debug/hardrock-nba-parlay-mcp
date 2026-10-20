---
name: nba-three-leg-parlays
description: Research exactly three-leg NBA parlays on Hard Rock Bet Florida through the nba-three-leg-parlays connector. Covers the day's slate, Hard Rock FL odds with source timestamps, official injury context, correlation checks, a user-entered combined quote, a daily budget ledger (default $10 per America/New_York day), and tracking of wagers the user confirms placing. Use when the user asks for a three-leg NBA parlay, wants a Hard Rock bet-slip screenshot verified, wants a ticket refreshed before deciding, wants a placed ticket recorded, or asks for results, costs, or remaining daily budget. The connector never places bets, deposits, or withdraws.
license: MIT
---

# NBA Three-Leg Parlay Analyst

This skill drives the `nba-three-leg-parlays` connector. The connector researches and
records; the user places every wager in the Hard Rock Bet app. Exactly three legs per
ticket, NBA regular season only (preseason, Summer League, WNBA, and college are out of
scope), Hard Rock Bet Florida is the only target book.

## 1. Disclosure to show first

At the start of every session that uses this skill, and again under every candidate
ticket, show this text (wording may be shortened but the three facts stay):

> AI involvement: this analysis was produced with AI assistance (Claude plus the
> nba-three-leg-parlays server). It is research, not a prediction of a win and not
> financial advice. You decide whether to bet, and you place any wager yourself.
> Florida sports betting is 21+. Help: 1-833-PLAYWISE.

## 2. When to use this skill (the seven day-one prompts)

1. "Review today's NBA slate for a three-leg Hard Rock Florida parlay within my $10 daily cap."
2. "Give me one primary candidate and explain the weakest leg."
3. "Compare a three-game parlay with this same-game parlay without assuming independence."
4. "Here is my Hard Rock bet-slip screenshot. Verify the three selections and combined payout."
5. "Refresh this ticket using current injuries and prices before I decide."
6. "I placed this exact ticket for $10 at these accepted odds. Record it."
7. "Show my actual results, costs, and remaining daily budget."

Each prompt maps to a tool sequence in section 6 and, in more detail, in
`references/workflows.md`.

## 3. Required inputs

- `date_local`: the America/New_York calendar date, `YYYY-MM-DD`. Default to today in
  ET. Never assume games are at night; the slate tool returns start times.
- Optional stake in USD. Default: up to the remaining daily limit, never above it.
- For a user ticket: three selections, each with game, market, side, line (if any),
  player name (for props), and the Hard Rock odds as shown.
- For recording: stake, accepted combined odds, placement time, ticket reference if the
  user has one.

Ask only for what the current action needs. Never ask for the user's Hard Rock login,
payment details, or location.

## 4. Tools (exact names)

In claude.ai and Cowork the tools appear under the connector name. In Claude Code the
plugin prefixes them as `mcp__plugin_nba-three-leg-parlays_nba-three-leg-parlays__<tool>`.

| Tool | Purpose | Mutates |
|---|---|---|
| `get_system_status` | version, clock, data modes, provider state, daily cap, warnings | no |
| `check_data_coverage(date_local, probe_props=false)` | what Hard Rock FL, references, injuries, and settlement rules cover today | provider credits only |
| `get_nba_slate(date_local)` | the day's NBA games with ET times and status | no |
| `get_injury_context(event_id)` | official injury report entries for one game | no |
| `analyze_leg(selection_id, date_local?)` | facts, interpretations, data quality, probability estimate, price value for one leg | no |
| `build_three_leg_parlays(date_local, parlay_type="auto", max_candidates=3, include_props=true)` | generate ranked candidates or NO SUITABLE TICKET | creates candidates |
| `analyze_my_parlay(three_selections, combined_odds?)` | evaluate a user-supplied three-leg ticket | creates one candidate |
| `check_parlay_correlation(candidate_id)` | correlation flags, whether a numeric joint estimate is allowed | no |
| `import_hardrock_quote(candidate_id, quote_fields)` | attach the book's combined quote (typed, screenshot, receipt) | updates candidate |
| `refresh_parlay(candidate_id)` | revalidate prices, injuries, start times; may expire or reject | updates candidate |
| `select_ticket(candidate_id, stake_usd, idempotency_key?)` | reserve budget for the ticket the user chose | budget reservation |
| `release_reservation(reservation_id, reason)` | release a reservation the user will not use | reservation |
| `get_daily_budget(date_local?, proposed_stake_usd?)` | recorded, reserved, proposed, remaining | no |
| `record_actual_bet(confirmed_ticket_fields, idempotency_key)` | record a wager the user confirms placing | ledger (append) |
| `reconcile_settlement(bet_id, settlement_fields)` | record the settlement the user reports: the app's result, or user-supplied scores as a provisional record | ledger (append) |
| `get_performance(start_date, end_date)` | tickets, stakes, returns, P/L, costs, pending exposure | no |
| `generate_30_day_review()` | the review for 2026-10-20 to 2026-11-18 | no |
| `set_user_settings(...)` | daily cap, display time zone, own provider key, onboarding | settings |
| `add_cost(...)` | record a data or software cost | ledger |
| `export_my_data()` | the user's own records | no |

There is no tool that places a bet, moves money, or deletes records. Do not describe one.

## 5. Session start

1. Call `get_system_status`. Read `data_modes_available`, `provider_configured`,
   `onboarding_complete`, `daily_cap_usd`, and `warnings`.
2. If `onboarding_complete` is false, explain the default $10 cap and ask whether to
   keep it, then call `set_user_settings(confirm_onboarding=true)` with any change.
3. Show the disclosure from section 1 (the response's `ai_disclosure` field carries the
   same text when present; either wording is fine).
4. State the data mode of everything that follows: `LIVE_PROVIDER`, `MANUAL_INPUT`, or
   `FIXTURE`. Fixture data is for demonstration only and must never be presented as a
   live price or recorded as a bet.

## 6. Tool sequences

### A. Daily research (prompts 1 and 2)

`get_system_status` -> `check_data_coverage(date_local)` -> `get_nba_slate(date_local)` ->
`build_three_leg_parlays(date_local)` -> for the primary candidate
`check_parlay_correlation(candidate_id)` -> present candidates in the section 7 format.

If the response has `no_ticket_reason`, say NO SUITABLE TICKET and give the reason codes.
Do not substitute a weaker ticket. If a leg carries `WAIT_FOR_UPDATE`, say so and name
the unresolved player, the report time from the tool response, and the next
injury-report deadline derived from the official reporting schedule copied in
`references/workflows.md` (section "Injury-report deadlines"). When the deadline cannot
be derived from that schedule, say "unknown"; never invent a time.

The primary candidate is the first in the response. Alternatives are choices, not
instructions to bet on each. The weakest leg is the one with the lowest data-quality
grade or the strongest reason against; say which rule you applied.

### B. Book quote and handoff (continues A)

The user opens the three legs in the Hard Rock app and reads the combined odds back
(typed or screenshot, section 10). Then:
`import_hardrock_quote(candidate_id, quote_fields)` -> `refresh_parlay(candidate_id)` ->
`get_daily_budget(date_local, proposed_stake_usd)` -> if the user chooses the ticket,
`select_ticket(candidate_id, stake_usd, idempotency_key)`.

Before the user places the bet, show: today's recorded stake, reserved stake, proposed
stake, remaining under the cap, and the rechecks list. The user places the wager in the
app. A reservation expires at the earliest tip-off or after two hours; say that.

### C. Record a placed ticket (prompt 6)

Confirm the exact three legs, stake, accepted combined odds, placement time, and ticket
reference. Then `record_actual_bet(confirmed_ticket_fields, idempotency_key)`. Use a
stable idempotency key such as `bet:<ticket_ref>` or `bet:<date_local>:<candidate_id>`
so a repeated request cannot record the ticket twice (a replay returns `replay=true`).
If the stake exceeds the remaining cap the tool still records it and returns
`BUDGET_BREACH_RECORDED`; report the breach plainly. If the user reports a wager this
tool did not prepare, record it with `external=true`.

### D. Settle and report (prompt 7)

A settlement is recorded only from what the user reports. No tool returns scores or
results, so never look up, recall, or infer a result yourself; a status that did not
come from the user is a fabrication. Two cases:

- The user reports the result shown in the Hard Rock app. Read back the status
  (`WON`, `LOST`, `VOID`, `PARTIALLY_VOID`, `REPRICED`, `CASHED_OUT`, `DISPUTED`,
  `CORRECTED`), the cash returned, and any bonus credited; after the user confirms,
  call `reconcile_settlement(bet_id, settlement_fields)` with `source=BOOK_CONFIRMED`.
- The user supplies final scores or player stats before the app has graded the
  ticket. Derive each leg's result only from the figures the user typed (a leg the
  figures do not settle stays `PENDING`), show the per-leg results and the status they
  imply, and only after the user confirms call `reconcile_settlement` with
  `source=PROVISIONAL_NBA_RESULTS`. Say that the record is provisional; it never
  overrides a book-confirmed record, and the app's grading replaces it later.

Then `get_performance(start_date, end_date)` and, when asked for the first month,
`generate_30_day_review()`. Returns include the stake; net = cash returned minus stake.

### E. User ticket review (prompts 3 and 4)

Collect the three legs as structured fields, then
`analyze_my_parlay(three_selections, combined_odds)` ->
`check_parlay_correlation(candidate_id)`. For a same-game or mixed ticket the joint
probability is unknown unless `model_state` is `VALIDATED_MODEL`; say so and do not rank
it above a multi-game ticket on EV. For a comparison, present both candidates with the
section 7 blocks side by side and state that only the multi-game ticket has an
assumption-based baseline.

### F. Refresh before deciding (prompt 5)

`refresh_parlay(candidate_id)`. Report the new state. `EXPIRED` or `REJECTED` means the
earlier analysis no longer applies; show the reason codes and, if the user still wants a
ticket, run sequence A again. A user-supplied quote establishes the payout but does not
revalidate old inputs; both are refreshed.

## 7. Output format for every candidate

Use exactly these blocks, in this order.

1. **Header**: `Candidate <candidate_id>`, parlay type (`MULTI_GAME`, `SAME_GAME`, or
   `MIXED`), state, data mode, and the disclosure line (the candidate's `ai_disclosure`
   field or section 1).
2. **Legs table** (three rows):

   | # | Game (ET, with offset) | Player or team | Market and line | Selection | Hard Rock FL odds | Source and update time |

   Odds in American and decimal. The update time is the source's publication time; if
   only the received time is known, label it as such.
3. **Per leg**: one-line rationale and the strongest reason against, from
   `leg_analyses[i].strongest_reason_against`. Facts and interpretations stay separate.
4. **Correlation**: the flags with severity, the explanation, and the weakest assumption.
5. **Combined quote**: `D = <decimal> (Hard Rock quote, <source>, <captured time>)` or
   `NEEDS BOOK QUOTE`. When no quote exists, the multiplied product may be shown only as
   "indicative product of the three leg prices, not the book price", and never for a
   same-game ticket.
6. **Probability and value**: model status (`MARKET_BASELINE`, `UNVALIDATED_MODEL`,
   `VALIDATED_MODEL`, `INSUFFICIENT_EVIDENCE`); joint probability or "unknown"; the method
   string; break-even probability `1/D`; estimated EV per dollar `p * D - 1` only when
   both a supported `p_joint` and a quote exist, otherwise "EV unavailable".
7. **Stake and payout**: proposed stake (at most the remaining daily limit), potential
   gross return `stake * D`, potential net profit `stake * (D - 1)`, maximum loss = stake.
8. **Rechecks before placement**: the `rechecks_required` list, at minimum current
   injury status of every named player, quote age, that no game has started, and that
   the app still accepts all three legs as one ticket.

Numbers come from the tool response. Do not recompute probabilities in chat.

## 8. Freshness rules

- Quotes older than 180 seconds (source timestamp to now) are stale: `QUOTE_STALE`.
- Reference and target timestamps more than 60 seconds apart: `TIMESTAMP_SKEW`.
- Injury report older than 6 hours: `INJURY_REPORT_STALE`.
- Retrieval time is not publication time; upstream delay can be unknown even when the
  received time is recent. Say which one you are showing.
- Always `refresh_parlay` right before handoff. A started game, a material injury
  change, a suspended market, or a changed combination invalidates the earlier analysis;
  keep the history and ask for fresh inputs.

## 9. Correlation limits

- Never multiply three same-game marginal probabilities. For a same-game or mixed
  ticket, `joint_numeric_allowed` is false and the joint probability is unknown unless a
  `VALIDATED_MODEL` exists on the server.
- For three different games, `p1 * p2 * p3` is shown only as an independence baseline
  and is labelled as an assumption. Different games do not guarantee independence.
- Report every flag: same player points and threes, assists and a teammate's points,
  team win and its spread, player scoring and the game total, multiple overs sharing
  pace or overtime, shared minutes or injury or blowout assumptions, and duplicate,
  nested, contradictory, or mutually exclusive legs. The last four are rejections.
- Two legs from one game must be placed as a Same Game Parlay in the app; the SGP price
  is the app's quote, not a product of leg prices.

## 10. Screenshots and receipts

When the user supplies a Hard Rock bet slip or receipt image:

1. Extract in chat: each leg's game, market, line, selection, odds sign and value;
   stake; combined odds; payout and whether it includes the stake; ticket reference;
   placement time.
2. List every ambiguous item: a minus sign that could be a dash, a line such as 24.5 vs
   25.5, a player name, the stake, whether the payout shown is gross or net.
3. Ask the user to confirm or correct the list. Never infer a missing minus sign, never
   assume the image is current, never treat the image as authenticated sportsbook data.
4. Send only the confirmed structured fields: `analyze_my_parlay` for a review,
   `import_hardrock_quote` with `source=SCREENSHOT_EXTRACTED` or `RECEIPT` and
   `user_confirmed=true` for a quote, `record_actual_bet` with `source=RECEIPT_REVIEW`
   for a placed ticket. The image itself is never sent to the server.

## 11. Budget rules

- Default cap: $10 total gross stake per America/New_York calendar day (the app's
  ledger, not a sportsbook limit). The user can change it with `set_user_settings`.
- Recommendations do not spend money. Budget is reserved only by `select_ticket` for
  the ticket the user chose, and consumed by `record_actual_bet`.
- Winnings, refunds, and cash-outs do not replenish the day's cap.
- Several smaller wagers must fit the same cap. Other wagers the user reports are
  recorded as external so the ledger stays truthful.
- A reported wager above the cap is recorded and flagged, never refused or hidden.
- No stake increases after wins or losses, no loss-recovery targets, no invented balance.

## 12. Candidate states

`RESEARCH_CANDIDATE` -> `NEEDS_BOOK_QUOTE` -> `READY_FOR_USER_REVIEW` ->
`USER_CONFIRMED_PLACED` -> `SETTLED`, with `EXPIRED` and `REJECTED` as exits.
`READY_FOR_USER_REVIEW` means the stated checks passed; it is not a prediction.

## 13. NO SUITABLE TICKET and WAIT FOR UPDATE

- NO SUITABLE TICKET: coverage, pricing, eligibility, or evidence is inadequate. Report
  the reason codes (for example `BOOK_NOT_AVAILABLE`, `MARKET_NOT_OFFERED`,
  `REFERENCE_MISSING`, `QUOTE_STALE`, `GAME_STARTED`). Do not force a daily parlay.
- WAIT FOR UPDATE: a leg depends on an unresolved availability question (Questionable or
  Doubtful player, minutes restriction). Name the player, the report time
  (`report_timestamp_utc` from the tool response, rendered in ET), and when the next
  report is due under the official NBA reporting schedule copied verbatim in
  `references/workflows.md`. Those deadlines are in the home team's local time and
  depend on the tip time and whether the game is the second of a back-to-back; when
  any of that is not known from the tool responses, say "unknown" rather than guess.
  Team markets are not excluded merely because someone is questionable; say whether
  the uncertainty is material to that selection.

## 14. Language rules

Never call a ticket a lock, guaranteed, risk-free, safe, or a sure thing. Never state a
win rate that was not computed from the user's recorded, settled tickets. Positive
estimated EV is not a profitable strategy. Data quality is not win probability.
Describe the product as research with manual placement; it is not endorsed by the NBA,
Hard Rock Bet, or Anthropic.

## 15. When the connector is not connected

If the tools are missing or a call returns `UNAUTHENTICATED`:

- claude.ai or Cowork: open Customize > Plugins > NBA Three-Leg Parlay Analyst >
  Connectors tab, add the `nba-three-leg-parlays` connector, and sign in. The skill
  loads without it, but no prices, injuries, or ledger are available until it shows
  Connected.
- Claude Code: the plugin's server appears in `/mcp`; select it to sign in. For a
  development server use `claude mcp add --transport http nba-three-leg-parlays <https URL>/mcp`
  then `/mcp`.
- Say that nothing can be researched or recorded until the connection exists. Do not
  fabricate a slate, odds, or results.

## 16. References

- `references/methodology.md`: odds conversion, no-vig, baseline, payout and EV math.
- `references/hard-rock-rules.md`: Florida house rules that affect settlement.
- `references/workflows.md`: each prompt mapped to tool calls and expected output, plus
  the official NBA injury-report deadlines.
- `references/settlement-and-review.md`: settlement states and the 30-day review.
