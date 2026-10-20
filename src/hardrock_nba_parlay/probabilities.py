"""Odds, probability, and payout arithmetic (docs/ARCHITECTURE.md section 5, ``probabilities.py``).

Rules enforced here
- Exact ``Decimal`` arithmetic only. A ``float`` (or ``bool``) anywhere is rejected with ``INVALID_INPUT``.
- Quantization: odds 4 dp and probabilities 6 dp (ROUND_HALF_EVEN); money 2 dp (ROUND_HALF_UP).
- The only probability source on day one is a benchmark two-way price with the vig removed
  proportionally. That is a ``MARKET_BASELINE``, never a validated model, and each estimate says so.
- A joint probability is only ever the plain product of marginals across *different* games. No
  haircut, no guessed correlation. When any two legs share a game the answer is ``None``. Its
  ``ModelState`` is the weakest of the leg states (a product that depends on an UNVALIDATED_MODEL leg is
  not market-baseline evidence); the independence assumption itself is carried in the method string.
- Nothing here reads a clock or the network.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Literal

from hardrock_nba_parlay import schemas as S

CombinedSource = Literal["BOOK_QUOTE", "INDICATIVE_MULTIPLIED", "NONE"]
COMBINED_SOURCES: tuple[CombinedSource, ...] = ("BOOK_QUOTE", "INDICATIVE_MULTIPLIED", "NONE")

ODDS_EXPONENT = Decimal("0.0001")
PROBABILITY_EXPONENT = Decimal("0.000001")
MONEY_EXPONENT = Decimal("0.01")

PAYOUT_ASSUMPTION_ACTION = "all legs have action"  # contract wording (docs/ARCHITECTURE.md section 3)
PAYOUT_ASSUMPTION_BOOK_RULES = "push/void/reprice outcomes follow the sportsbook's rules and are not modelled"
LEG_ESTIMATE_ASSUMPTIONS: tuple[str, str] = (
    "proportional vig removal",
    "benchmark price treated as efficient; not a true probability",
)
JOINT_INDEPENDENCE_METHOD = (
    "p1*p2*p3 assuming independence across different games (assumption, not validated)"
)

_ZERO = Decimal(0)
_ONE = Decimal(1)
_TWO = Decimal(2)
_HUNDRED = Decimal(100)

# Evidence strength, weakest first. A joint estimate is never labelled stronger than its weakest input.
_EVIDENCE_RANK: dict[S.ModelState, int] = {
    S.ModelState.INSUFFICIENT_EVIDENCE: 0,
    S.ModelState.UNVALIDATED_MODEL: 1,
    S.ModelState.MARKET_BASELINE: 2,
    S.ModelState.VALIDATED_MODEL: 3,
}


# --------------------------------------------------------------------------------------
# Input coercion (exact numbers only)
# --------------------------------------------------------------------------------------


def _dec(value: object, name: str) -> Decimal:
    """Coerce an exact numeric input (Decimal, int, numeric str) to Decimal.

    Floats and bools are refused so that binary rounding never leaks into odds, probabilities, or money.
    """
    if isinstance(value, bool | float):
        raise ValueError(f"INVALID_INPUT: {name} must be a Decimal, not {type(value).__name__}")
    if isinstance(value, Decimal):
        out = value
    elif isinstance(value, int | str):
        try:
            out = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"INVALID_INPUT: {name} is not a valid decimal: {value!r}") from exc
    else:
        raise ValueError(f"INVALID_INPUT: {name} must be a Decimal, not {type(value).__name__}")
    if not out.is_finite():
        raise ValueError(f"INVALID_INPUT: {name} must be finite")
    return out


def _odds(value: object, name: str = "decimal odds") -> Decimal:
    d = _dec(value, name)
    if d <= _ONE:
        raise ValueError(f"INVALID_INPUT: {name} must be > 1 (got {d})")
    return d


def _prob(value: object, name: str = "probability") -> Decimal:
    p = _dec(value, name)
    if p < _ZERO or p > _ONE:
        raise ValueError(f"INVALID_INPUT: {name} must be within [0, 1] (got {p})")
    return p


def _money(value: object, name: str = "stake") -> Decimal:
    m = _dec(value, name)
    if m < _ZERO:
        raise ValueError(f"INVALID_INPUT: {name} must be >= 0 (got {m})")
    return m


# --------------------------------------------------------------------------------------
# Quantization helpers (the "Q" helpers of the contract)
# --------------------------------------------------------------------------------------


def q_odds(d: Decimal) -> Decimal:
    """Quantize decimal odds to 4 dp (ROUND_HALF_EVEN)."""
    return _dec(d, "odds").quantize(ODDS_EXPONENT, rounding=ROUND_HALF_EVEN)


def q_prob(p: Decimal) -> Decimal:
    """Quantize a probability (or a probability-scale quantity such as EV per dollar) to 6 dp (ROUND_HALF_EVEN)."""
    return _dec(p, "probability").quantize(PROBABILITY_EXPONENT, rounding=ROUND_HALF_EVEN)


def q_money(m: Decimal) -> Decimal:
    """Quantize a USD amount to 2 dp (ROUND_HALF_UP)."""
    return _dec(m, "money").quantize(MONEY_EXPONENT, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------------------
# Odds conversions
# --------------------------------------------------------------------------------------


def american_to_decimal(a: int) -> Decimal:
    """Convert American odds to decimal odds, quantized to 4 dp.

    ``+a`` -> ``1 + a/100``; ``-a`` -> ``1 + 100/|a|``. Zero and any magnitude below 100 are invalid and raise
    ``ValueError("INVALID_INPUT: ...")``. Both +100 and -100 map to 2.0000.
    """
    if isinstance(a, bool) or not isinstance(a, int):
        raise ValueError(f"INVALID_INPUT: american odds must be an int, not {type(a).__name__}")
    if a == 0 or abs(a) < 100:
        raise ValueError(f"INVALID_INPUT: american odds must be <= -100 or >= +100 (got {a})")
    if a > 0:
        d = _ONE + Decimal(a) / _HUNDRED
    else:
        d = _ONE + _HUNDRED / Decimal(abs(a))
    return q_odds(d)


def decimal_to_american(d: Decimal) -> int:
    """Convert decimal odds to the nearest American price (``d >= 2`` -> positive, ``1 < d < 2`` -> negative).

    Rejects ``d <= 1`` with ``ValueError("INVALID_INPUT: ...")``. Rounds to the nearest whole number
    (ROUND_HALF_UP, away from zero on ties).
    """
    dd = _odds(d)
    if dd >= _TWO:
        value = (dd - _ONE) * _HUNDRED
    else:
        value = -(_HUNDRED / (dd - _ONE))
    return int(value.to_integral_value(rounding=ROUND_HALF_UP))


def implied_probability(d: Decimal) -> Decimal:
    """Vig-inclusive implied probability ``1/d`` (6 dp). This is a price, not a true probability."""
    return q_prob(_ONE / _odds(d))


def no_vig_two_way(d1: Decimal, d2: Decimal) -> tuple[Decimal, Decimal]:
    """Proportional (multiplicative) vig removal for a two-way market.

    ``q_i = 1/d_i``; returns ``(q1/(q1+q2), q2/(q1+q2))`` each quantized to 6 dp. The pair sums to 1 within 1e-6.
    """
    q1 = _ONE / _odds(d1, "decimal odds (side 1)")
    q2 = _ONE / _odds(d2, "decimal odds (side 2)")
    total = q1 + q2
    return q_prob(q1 / total), q_prob(q2 / total)


# --------------------------------------------------------------------------------------
# Products and payout math
# --------------------------------------------------------------------------------------


def independence_baseline(ps: Sequence[Decimal]) -> Decimal:
    """Product of marginal probabilities (6 dp). The caller must label the independence assumption."""
    if len(ps) == 0:
        raise ValueError("INVALID_INPUT: at least one probability is required")
    product = _ONE
    for i, p in enumerate(ps):
        product *= _prob(p, f"probability[{i}]")
    return q_prob(product)


def indicative_multiplied_decimal(ds: Sequence[Decimal]) -> Decimal:
    """Product of leg decimal odds (4 dp): an *indicative* combined price. The sportsbook's quote governs."""
    if len(ds) == 0:
        raise ValueError("INVALID_INPUT: at least one decimal price is required")
    product = _ONE
    for i, d in enumerate(ds):
        product *= _odds(d, f"decimal odds[{i}]")
    return q_odds(product)


def payout_math(stake: Decimal, combined_decimal: Decimal | None, source: str) -> S.PayoutMath:
    """Gross/net/max-loss/break-even for a stake at a combined decimal price.

    ``gross = stake * D``, ``net = stake * (D - 1)``, ``max_loss = stake``, ``break_even = 1/D``.
    When ``combined_decimal`` is None the gross, net, and break-even fields are None and the source is ``NONE``.
    ``source`` must be one of BOOK_QUOTE, INDICATIVE_MULTIPLIED, NONE; a price with source NONE is invalid.
    """
    if source not in COMBINED_SOURCES:
        raise ValueError(f"INVALID_INPUT: combined source must be one of {COMBINED_SOURCES} (got {source!r})")
    stake_d = q_money(_money(stake))
    assumptions = [PAYOUT_ASSUMPTION_ACTION, PAYOUT_ASSUMPTION_BOOK_RULES]
    if combined_decimal is None:
        assumptions.append("no combined price available; payout cannot be computed")
        return S.PayoutMath(
            combined_decimal=None,
            combined_source="NONE",
            stake_usd=stake_d,
            gross_return_usd=None,
            net_profit_usd=None,
            max_loss_usd=stake_d,
            break_even_probability=None,
            assumptions=assumptions,
        )
    if source == "NONE":
        raise ValueError(
            "INVALID_INPUT: a combined price requires source BOOK_QUOTE or INDICATIVE_MULTIPLIED"
        )
    d = q_odds(_odds(combined_decimal, "combined decimal"))
    if source == "BOOK_QUOTE":
        assumptions.append("combined price is the sportsbook's quote as supplied by the user")
    else:
        assumptions.append(
            "combined price is the product of the leg prices (indicative); the sportsbook's quote governs and replaces it"
        )
    return S.PayoutMath(
        combined_decimal=d,
        combined_source=source,  # type: ignore[arg-type]
        stake_usd=stake_d,
        gross_return_usd=q_money(stake_d * d),
        net_profit_usd=q_money(stake_d * (d - _ONE)),
        max_loss_usd=stake_d,
        break_even_probability=q_prob(_ONE / d),
        assumptions=assumptions,
    )


def break_even_probability(d: Decimal) -> Decimal:
    """Joint probability at which a ticket priced at ``d`` has zero expected value: ``1/d`` (6 dp)."""
    return q_prob(_ONE / _odds(d))


def ev_per_dollar(p_joint: Decimal, d: Decimal) -> Decimal:
    """Expected profit per dollar staked: ``p * d - 1`` (6 dp)."""
    return q_prob(_prob(p_joint, "p_joint") * _odds(d) - _ONE)


# --------------------------------------------------------------------------------------
# Leg and joint estimates
# --------------------------------------------------------------------------------------


def _insufficient(method: str, ref: S.ReferenceTwoWay | None = None) -> S.ProbabilityEstimate:
    return S.ProbabilityEstimate(
        value=None,
        state=S.ModelState.INSUFFICIENT_EVIDENCE,
        method=method,
        reference_book=ref.book if ref is not None else None,
        reference_stamp=ref.stamp if ref is not None else None,
        assumptions=[],
    )


def _line_matches(quote: S.MarketQuote, ref: S.ReferenceTwoWay) -> bool:
    """Exact line match. For SPREAD the reference line is the HOME handicap; AWAY must equal its negation."""
    if quote.market_type == S.MarketType.MONEYLINE:
        return True
    if quote.line is None or ref.line is None:
        return False
    if quote.market_type == S.MarketType.SPREAD:
        expected = ref.line if quote.side == S.Side.HOME else -ref.line
        return quote.line == expected
    return quote.line == ref.line


def _fmt_line(line: Decimal | None) -> str:
    return "" if line is None else format(line.normalize(), "f")


def estimate_leg_probability(selection: S.Selection, ref: S.ReferenceTwoWay | None) -> S.ProbabilityEstimate:
    """Market-baseline probability for one selection from a matching two-way benchmark.

    The reference must match the selection exactly: same event_id, market_type, period, player (for props),
    and line (SPREAD: HOME line == ref.line, AWAY line == -ref.line). Any mismatch, a missing reference, an
    unsupported period, or a TEAM_TOTAL (the reference model cannot name the team) yields
    ``INSUFFICIENT_EVIDENCE`` with ``value=None`` and the reason code as ``method``:
    REFERENCE_MISSING, PERIOD_UNSUPPORTED, EVENT_UNMATCHED, PLAYER_UNMATCHED, REFERENCE_INCOMPLETE, LINE_MISMATCH.

    On a match the value is the proportional no-vig probability of ``selection.quote.side`` with state
    ``MARKET_BASELINE`` and method ``proportional_no_vig(<book> <market> <line>)``.
    """
    quote = selection.quote
    if ref is None:
        return _insufficient("REFERENCE_MISSING")
    if quote.period not in S.SUPPORTED_PERIODS:
        return _insufficient("PERIOD_UNSUPPORTED", ref)
    if ref.event_id != quote.event_id:
        return _insufficient("EVENT_UNMATCHED", ref)
    if ref.market_type != quote.market_type or ref.period != quote.period:
        return _insufficient("LINE_MISMATCH", ref)
    if quote.market_type == S.MarketType.TEAM_TOTAL:
        # ReferenceTwoWay carries no team_id, so a team-total benchmark cannot be verified to the right team.
        return _insufficient("REFERENCE_INCOMPLETE", ref)
    if quote.market_type in S.PLAYER_MARKETS:
        player_id = quote.player_id or (selection.player.player_id if selection.player is not None else None)
        if not player_id or ref.player_id != player_id:
            return _insufficient("PLAYER_UNMATCHED", ref)
    elif ref.player_id is not None:
        return _insufficient("LINE_MISMATCH", ref)
    if not _line_matches(quote, ref):
        return _insufficient("LINE_MISMATCH", ref)
    try:
        own = ref.odds_for(quote.side)
        other = ref.odds_for(ref.opposite(quote.side))
    except KeyError:
        return _insufficient("LINE_MISMATCH", ref)
    p_own, _ = no_vig_two_way(own, other)
    line_part = f" {_fmt_line(quote.line)}" if quote.line is not None else ""
    return S.ProbabilityEstimate(
        value=p_own,
        state=S.ModelState.MARKET_BASELINE,
        method=f"proportional_no_vig({ref.book} {quote.market_type.value}{line_part})",
        reference_book=ref.book,
        reference_stamp=ref.stamp,
        assumptions=list(LEG_ESTIMATE_ASSUMPTIONS),
    )


def price_value(target_decimal: Decimal, p_reference: Decimal | None, note: str) -> S.PriceValue:
    """Compare the target book's price with a reference probability.

    ``fair_decimal = 1/p`` (4 dp) and ``edge_per_dollar = p * target - 1`` (6 dp); both None when ``p`` is None.
    A reference probability of exactly 0 has no finite fair price (None) and an edge of -1.
    """
    d = q_odds(_odds(target_decimal, "target decimal"))
    if p_reference is None:
        return S.PriceValue(target_decimal=d, fair_decimal=None, edge_per_dollar=None, note=note)
    p = _prob(p_reference, "p_reference")
    fair = q_odds(_ONE / p) if p > _ZERO else None
    return S.PriceValue(target_decimal=d, fair_decimal=fair, edge_per_dollar=q_prob(p * d - _ONE), note=note)


def weakest_model_state(states: Iterable[S.ModelState]) -> S.ModelState:
    """The weakest evidence state among ``states``: INSUFFICIENT_EVIDENCE < UNVALIDATED_MODEL < MARKET_BASELINE < VALIDATED_MODEL.

    Used to label a joint estimate: a product is no stronger than its weakest input.
    """
    items = list(states)
    if not items:
        raise ValueError("INVALID_INPUT: at least one model state is required")
    return min(items, key=lambda st: _EVIDENCE_RANK[st])


def joint_probability(
    ticket: S.ThreeLegTicket, legs: Sequence[S.ProbabilityEstimate], correlation: S.CorrelationReport
) -> tuple[Decimal | None, S.ModelState, str]:
    """Joint probability for a ticket: the product of marginals across three different games, or nothing.

    Returns ``(None, INSUFFICIENT_EVIDENCE, reason)`` when the correlation report disallows a numeric joint
    estimate, when any two legs share an event (checked here again regardless of the report), or when any leg
    has no value. Otherwise ``(p1*p2*p3, <weakest leg state>, method)``: with three MARKET_BASELINE legs the
    state is MARKET_BASELINE and the method is exactly ``JOINT_INDEPENDENCE_METHOD``; when a leg is weaker
    (UNVALIDATED_MODEL) the joint carries that weaker state and the method names the leg(s) responsible.
    Never applies a haircut or a guessed correlation.
    """
    if len(legs) != len(ticket.legs):
        raise ValueError(f"INVALID_INPUT: expected {len(ticket.legs)} leg estimates, got {len(legs)}")
    shares_event = len(set(ticket.event_ids)) < len(ticket.legs)
    if shares_event or ticket.parlay_type != S.ParlayType.MULTI_GAME:
        return (
            None,
            S.ModelState.INSUFFICIENT_EVIDENCE,
            "JOINT_PROBABILITY_UNAVAILABLE: SAME_GAME_CORRELATION; no validated joint model, marginals cannot be multiplied",
        )
    if not correlation.joint_numeric_allowed:
        return (
            None,
            S.ModelState.INSUFFICIENT_EVIDENCE,
            f"JOINT_PROBABILITY_UNAVAILABLE: correlation report disallows a numeric joint estimate ({correlation.weakest_assumption})",
        )
    missing = [
        str(i + 1)
        for i, leg in enumerate(legs)
        if leg.value is None or leg.state == S.ModelState.INSUFFICIENT_EVIDENCE
    ]
    if missing:
        return (
            None,
            S.ModelState.INSUFFICIENT_EVIDENCE,
            f"JOINT_PROBABILITY_UNAVAILABLE: leg(s) {', '.join(missing)} have no probability estimate",
        )
    values = [leg.value for leg in legs if leg.value is not None]
    state = weakest_model_state(leg.state for leg in legs)
    method = JOINT_INDEPENDENCE_METHOD
    if state != S.ModelState.MARKET_BASELINE:
        weakest_legs = ", ".join(str(i + 1) for i, leg in enumerate(legs) if leg.state == state)
        method = (
            f"{JOINT_INDEPENDENCE_METHOD}; joint state {state.value} follows the weakest leg estimate "
            f"(leg(s) {weakest_legs})"
        )
    return independence_baseline(values), state, method


# --------------------------------------------------------------------------------------
# Book quote vs indicative product
# --------------------------------------------------------------------------------------


def book_quote_replaces_indicative(
    indicative: Decimal, book_quote: Decimal | None
) -> tuple[Decimal, CombinedSource]:
    """The sportsbook's combined quote always wins over the multiplied indicative price.

    Returns ``(book_quote, "BOOK_QUOTE")`` whenever a quote is present, else ``(indicative, "INDICATIVE_MULTIPLIED")``.
    Use :func:`quote_difference` / :func:`describe_combined_odds` to show the gap between the two.
    """
    ind = q_odds(_odds(indicative, "indicative decimal"))
    if book_quote is None:
        return ind, "INDICATIVE_MULTIPLIED"
    return q_odds(_odds(book_quote, "book quote")), "BOOK_QUOTE"


def quote_difference(indicative: Decimal, book_quote: Decimal | None) -> Decimal | None:
    """``book_quote - indicative`` (4 dp), or None without a book quote. Negative means the book pays less."""
    ind = q_odds(_odds(indicative, "indicative decimal"))
    if book_quote is None:
        return None
    return q_odds(q_odds(_odds(book_quote, "book quote")) - ind)


def describe_combined_odds(indicative: Decimal, book_quote: Decimal | None) -> str:
    """One line for display: which combined price is in force and how it compares with the multiplied price."""
    combined, source = book_quote_replaces_indicative(indicative, book_quote)
    diff = quote_difference(indicative, book_quote)
    if source == "BOOK_QUOTE" and diff is not None:
        sign = "+" if diff >= _ZERO else ""
        return (
            f"Book quote {combined} replaces the multiplied indicative price {q_odds(_odds(indicative))} "
            f"({sign}{diff}); the sportsbook's quote governs the payout."
        )
    return (
        f"Indicative multiplied price {combined} (no book quote yet); the sportsbook's quote will replace it."
    )


__all__ = [
    "COMBINED_SOURCES",
    "JOINT_INDEPENDENCE_METHOD",
    "LEG_ESTIMATE_ASSUMPTIONS",
    "PAYOUT_ASSUMPTION_ACTION",
    "PAYOUT_ASSUMPTION_BOOK_RULES",
    "CombinedSource",
    "american_to_decimal",
    "book_quote_replaces_indicative",
    "break_even_probability",
    "decimal_to_american",
    "describe_combined_odds",
    "estimate_leg_probability",
    "ev_per_dollar",
    "implied_probability",
    "independence_baseline",
    "indicative_multiplied_decimal",
    "joint_probability",
    "no_vig_two_way",
    "payout_math",
    "price_value",
    "q_money",
    "q_odds",
    "q_prob",
    "quote_difference",
    "weakest_model_state",
]
