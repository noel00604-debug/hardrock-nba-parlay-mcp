# Settlement states and the first 30-day review

## 1. Bet statuses

`PENDING`, `WON`, `LOST`, `VOID`, `PARTIALLY_VOID`, `REPRICED`, `CASHED_OUT`,
`DISPUTED`, `CORRECTED`. Leg results: `PENDING`, `WON`, `LOST`, `VOID`.

- `PARTIALLY_VOID` and `REPRICED`: one leg voided or pushed and the ticket settled on
  the remaining legs (Hard Rock Florida rule 1.15); record the cash actually returned and
  the repriced combined decimal when shown in the app.
- `CASHED_OUT`: cash returned is the cash-out amount, whatever the final outcome.
- `DISPUTED`: the user has raised a grading question with the book; stays open.
- `CORRECTED`: the book changed an earlier grading; a new settlement record is appended.

## 2. Provisional versus book-confirmed

Every settlement record has a source:

- `BOOK_CONFIRMED`: what the Hard Rock app shows. Authoritative for money.
- `PROVISIONAL_NBA_RESULTS`: derived from NBA scores or player stats that the user
  supplies in chat before the app has graded the ticket. No tool returns scores, and
  Claude never looks up or recalls results itself; the user confirms the implied status
  before the call. It creates a provisional outcome for display and never overwrites an
  existing book-confirmed record (`SUPERSEDED_BY_BOOK`, `PROVISIONAL_RESULT`).

Settlement records are append-only with a sequence number; an identical repeated
settlement is a replay and creates no new row, so repeated reconciliation never double
counts. Cash profit for a settled ticket = confirmed cash returned minus the original
cash stake; returns include the stake. Bonus credits are tracked separately from cash.

## 3. What the 30-day review covers

Window: 2026-10-20 through 2026-11-18 inclusive (30 America/New_York calendar days).
Daylight saving time ends 2026-11-01 inside the window; days are computed in
America/New_York, not with a fixed offset.

At the $10 default cap the maximum gross stake in the window is $300 if a ticket is
placed every day. There is no requirement to bet daily; NO SUITABLE TICKET days are
expected and are reported as such.

The review (`generate_30_day_review`) reports:

- tickets placed, stakes, returns, net profit or loss, pending exposure, voids;
- results by parlay type and market composition;
- accepted versus recommended odds;
- missing or incomplete data and late injury changes;
- data and software costs and the after-cost result;
- every recommendation and every user-selected bet, including losses;
- probability calibration only where a pre-placement numerical forecast existed;
- shared-leg and shared-game dependence and small-sample notes.

## 4. What 30 days can and cannot show

Thirty daily three-leg tickets are a small sample of a high-variance bet. Observed
results (money won or lost) are facts. Evidence of predictive skill is a different
question: at this sample size a positive or negative result is usually consistent with
luck, and tickets sharing legs or games are not independent trials. The review separates
"observed results" from "evidence of skill" and will say "inconclusive" when that is
the honest reading. Leg hit rate is not parlay win rate; both are shown with their
denominators.

After the review, normal operation continues unless the user stops it. The daily cap is
never raised by the tool.
