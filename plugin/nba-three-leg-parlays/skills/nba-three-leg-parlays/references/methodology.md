# Methodology: odds, probabilities, payouts

Every number the connector reports comes from these formulas. Odds, probabilities, and
money are decimal values; nothing here is a prediction.

## 1. Odds conversion

American odds `A` to decimal odds `d`:

- `A > 0`: `d = 1 + A / 100`. Example: +150 -> 2.50.
- `A < 0`: `d = 1 + 100 / |A|`. Example: -110 -> 1.9091.
- `A = 0` and `|A| < 100` are rejected as invalid (except that +100 and -100 both mean 2.00).

Decimal to American: `d >= 2` -> `+(d - 1) * 100`; `d < 2` -> `-100 / (d - 1)`.

Implied probability of one price: `q = 1 / d`. Example: 1.9091 -> 0.5238. This includes
the bookmaker's margin, so it is not a fair probability.

## 2. Proportional no-vig reference

For two exhaustive, no-push outcomes from ONE reference book snapshot (same line, same
period, complementary handicaps for a spread):

```
q1 = 1 / d1
q2 = 1 / d2
p1 = q1 / (q1 + q2)
p2 = 1 - p1
```

Example: -110 / -110 -> q1 = q2 = 0.5238 -> p1 = p2 = 0.50.

These are proportional no-vig benchmark estimates from the reference book (Pinnacle by
default, with the caveat that its public-site prices may be delayed). They are not
proven true probabilities. A reference is only used when the line, period, and
overtime treatment match the Hard Rock leg exactly; otherwise the leg has
`REFERENCE_MISSING` or `LINE_MISMATCH` and no probability.

Price value for a leg: `edge_per_dollar = p_reference * d_target - 1`. Positive edge
means Hard Rock's price pays more than the reference implies; it does not mean the leg
will win.

## 3. Joint probability and the independence baseline

For three legs from three different games the connector may show

```
p_ticket = p1 * p2 * p3     (ASSUMPTION: the three legs are independent)
```

This is a baseline, labelled as an assumption. Different games do not guarantee
independence (shared news, shared rest patterns, late scratches across a slate).

Worked check: three independent legs at 0.70 each give `0.70 ^ 3 = 0.343`, not 0.70.

For two or more legs from the same game the connector does NOT multiply marginals.
Pairwise correlations alone do not identify the probability that all three legs win.
A same-game joint probability is reported as unknown unless a `VALIDATED_MODEL` exists.

## 4. Model states

| State | Meaning |
|---|---|
| `MARKET_BASELINE` | benchmark-derived estimates (no-vig reference prices) |
| `UNVALIDATED_MODEL` | a defined statistical model without holdout evidence |
| `VALIDATED_MODEL` | demonstrated chronological holdout and calibration evidence |
| `INSUFFICIENT_EVIDENCE` | no defensible numerical estimate; probability shown as unknown |

Day-one operation runs on `MARKET_BASELINE` for multi-game tickets and
`INSUFFICIENT_EVIDENCE` for same-game joint probabilities. Nobody should present a
baseline as a validated probability.

## 5. Payout math for a verified combined decimal quote D

Assumes all three legs have action (no void, no push, no repricing).

- Gross return if fully won: `stake * D` (includes the stake).
- Net profit if fully won: `stake * (D - 1)`.
- Maximum loss: `stake`.
- Break-even joint probability: `1 / D`.
- Estimated EV per dollar, only when a defensible `p_joint` exists: `p_joint * D - 1`.

Worked examples:

- `p_joint = 0.20`, `D = 5.50`: `EV = 0.20 * 5.50 - 1 = 0.10`, that is 10 cents per
  dollar, shown as an estimate with its probability source and validation status.
- `stake = $10`, `D = 5.50`: gross return `$55.00` including the stake, net profit
  `$45.00`, maximum loss `$10.00`, break-even probability `1 / 5.50 = 0.1818`.

Do not subtract vig again after using the offered payout odds, and do not apply
exchange-fee formulas. Positive estimated EV does not establish a profitable strategy.

## 6. Indicative product versus the book quote

For an ordinary parlay across different games the product `d1 * d2 * d3` may be shown
as an indicative multiplication, labelled "indicative, not the book price". The actual
Hard Rock combined quote determines the payout and replaces the indicative value as
soon as it is imported (`QUOTE_REPLACES_INDICATIVE`). If the quote and the legs
disagree (`QUOTE_CONFLICTS_WITH_LEGS`), the ticket is not ready.

For a same-game or mixed ticket, the multiplied product is never shown as the price.
Hard Rock does not publish its SGP pricing method; the only price is the app's quote.

## 7. Void, push, and repriced outcomes

Under Hard Rock Florida rules a voided or pushed leg is removed and the ticket stands on
the remaining legs (a three-leg ticket becomes a two-leg parlay; two voids leave a
single). The simple all-win-or-lose formula above is incomplete for those states. When
the settlement treatment of a state is unknown, the corresponding EV is unavailable
(`SETTLEMENT_RULES_UNKNOWN`, `EV_UNAVAILABLE`). Push probabilities are never inferred
from normalized two-way odds.

## 8. Rounding

Odds are kept to four decimals, probabilities to six, money to cents (round half up).
Display values are rounded; stored values are not re-rounded between steps.
