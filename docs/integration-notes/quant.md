# Integration notes: quant (probabilities.py, correlation.py)

Requests for the integration lead, plus decisions other modules should know about. No foundation file was edited.

## Requests against the foundation

1. `ReferenceTwoWay` has no `team_id`. A TEAM_TOTAL benchmark therefore cannot be verified to the right team,
   so `estimate_leg_probability` returns `INSUFFICIENT_EVIDENCE` with method `REFERENCE_INCOMPLETE` for every
   TEAM_TOTAL selection. Adding `team_id: str | None` to `ReferenceTwoWay` (and matching it in
   `normalization.pair_reference`) would unlock team totals.
2. `MarketQuote.identity_tuple()` renders the line with `str(Decimal.normalize())`, which turns whole numbers
   into scientific notation (`Decimal("20")` -> `"2E+1"`). It is still deterministic, so selection ids are
   stable, but it is unreadable in logs. `format(line.normalize(), "f")` gives `"20"`.
3. (Resolved 2026-10-19 by the quant fixer.) `PayoutMath.assumptions` now emits the contract string
   `"all legs have action"` (constant `PAYOUT_ASSUMPTION_ACTION`); the earlier `"all three legs have action"`
   wording from the quant brief is gone. Grep for the constant, not the literal.

## Behaviour other modules depend on

- `hard_rejections(legs)` accepts either a `list[Selection]` (before a `ThreeLegTicket` exists) or a
  `ThreeLegTicket`. It returns reason codes in a fixed order: NOT_THREE_LEGS, DUPLICATE_SELECTION,
  CONTRADICTORY_SELECTION, NESTED_SELECTION, MUTUALLY_EXCLUSIVE_SELECTION, PERIOD_UNSUPPORTED.
  DUPLICATE also fires when the same outcome appears at another book or as an alternate line (the schema
  validator only catches identical identity tuples). MUTUALLY_EXCLUSIVE is integer-aware: over 25 / under 26
  is flagged (no integer satisfies both), over 24.5 / under 25.5 is not (25 wins both). It also covers a
  team's moneyline with the opponent's spread in the same game: DET ML + BOS -3.5 (or BOS -0.5, or BOS +1,
  where a one-point DET win pushes rather than wins) is flagged; DET ML + BOS +3.5 is a legal middle and is
  not. The same team's moneyline and spread are never flagged hard (soft TEAM_WIN_AND_SPREAD only).
- Games are keyed by `event_id`, as `ThreeLegTicket.parlay_type` is. When two different event ids describe
  the same matchup (same away/home `team_id` pair, e.g. the provider's `oddsapi:...` plus a `manual:...` import
  of the same game), `check_correlation` adds a BLOCKING `SAME_GAME_UNQUANTIFIED` flag over those legs, sets
  `joint_numeric_allowed=False`, uses the same-game weakest assumption, and `describe_parlay_type` names both
  ids ("MIXED by event id: ..." / "MULTI_GAME by event id ..."). The ticket's `parlay_type` is unchanged
  (that is derived in the frozen schema). Upstream modules should still dedupe events before building
  tickets; this is a safety net, not the fix.
- `check_correlation` also emits DUPLICATE / NESTED / CONTRADICTORY / MUTUALLY_EXCLUSIVE as BLOCKING flags when
  a constructible ticket contains them. `CorrelationFlag.leg_indexes` are 0-based positions in `ticket.legs`.
  Flags are ordered BLOCKING, WARNING, INFO.
- `joint_probability` refuses to multiply (returns `None`, `INSUFFICIENT_EVIDENCE`) whenever two legs share an
  event, even if a caller passes a `CorrelationReport` with `joint_numeric_allowed=True`. The method string
  for every refusal starts with `JOINT_PROBABILITY_UNAVAILABLE`. When it does multiply, the returned
  `ModelState` is the weakest leg state (`weakest_model_state`: INSUFFICIENT_EVIDENCE < UNVALIDATED_MODEL <
  MARKET_BASELINE < VALIDATED_MODEL). Three MARKET_BASELINE legs give MARKET_BASELINE and the exact method
  `JOINT_INDEPENDENCE_METHOD`; an UNVALIDATED_MODEL leg makes the joint UNVALIDATED_MODEL and the method
  string names the leg(s). `Candidate.model_state` should carry that state through unchanged.
- `estimate_leg_probability` mismatch methods are reason codes verbatim: `REFERENCE_MISSING`,
  `PERIOD_UNSUPPORTED`, `EVENT_UNMATCHED`, `PLAYER_UNMATCHED`, `REFERENCE_INCOMPLETE`, `LINE_MISMATCH`.
  On a mismatch `reference_book` / `reference_stamp` still name the benchmark that was examined.
- Successful leg method: `proportional_no_vig(<book> <MARKET_TYPE> <line>)`, e.g.
  `proportional_no_vig(pinnacle SPREAD -3.5)` (the selection's own signed line) or
  `proportional_no_vig(pinnacle MONEYLINE)`.
- `payout_math(stake, None, <any source>)` always yields `combined_source="NONE"`; a price with source `"NONE"`
  raises `INVALID_INPUT`.
- Extra public names beyond the contract: `price_value`, `book_quote_replaces_indicative`, `quote_difference`,
  `describe_combined_odds`, `weakest_model_state`, `describe_parlay_type`, and the constants
  `JOINT_INDEPENDENCE_METHOD`, `LEG_ESTIMATE_ASSUMPTIONS`, `PAYOUT_ASSUMPTION_ACTION`,
  `PAYOUT_ASSUMPTION_BOOK_RULES`, `WEAKEST_ASSUMPTION_MULTI_GAME`, `WEAKEST_ASSUMPTION_SAME_GAME`,
  `SAME_GAME_UNQUANTIFIED_EXPLANATION`, `MATCHUP_COLLISION_EXPLANATION`.
- Every numeric entry point rejects `float` and `bool` with `ValueError("INVALID_INPUT: ...")`.
