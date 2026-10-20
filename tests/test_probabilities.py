"""Tests for probabilities.py: exact Decimal odds, probability, payout, leg-estimate, and joint math."""

from __future__ import annotations

from decimal import Decimal

import pytest
from conftest import TEAMS, make_event, make_quote, make_reference, make_selection

from hardrock_nba_parlay import probabilities as P
from hardrock_nba_parlay import schemas as S

D = Decimal


def _report(allowed: bool) -> S.CorrelationReport:
    return S.CorrelationReport(
        flags=[],
        joint_numeric_allowed=allowed,
        weakest_assumption="independence across games is assumed, not demonstrated",
        explanation="test report",
    )


def _estimate(value: str | None) -> S.ProbabilityEstimate:
    if value is None:
        return S.ProbabilityEstimate(
            value=None, state=S.ModelState.INSUFFICIENT_EVIDENCE, method="REFERENCE_MISSING"
        )
    return S.ProbabilityEstimate(
        value=D(value), state=S.ModelState.MARKET_BASELINE, method="proportional_no_vig(test)"
    )


# --------------------------------------------------------------------------------------
# Quantization helpers
# --------------------------------------------------------------------------------------


def test_quantizers_use_the_contract_exponents_and_rounding():
    assert P.q_odds(D("1.90909")) == D("1.9091")
    assert P.q_odds(D("1.90909")).as_tuple().exponent == -4
    assert P.q_prob(D("0.3333333")) == D("0.333333")
    assert P.q_prob(D("0.5")).as_tuple().exponent == -6
    assert P.q_money(D("10.005")) == D("10.01")  # ROUND_HALF_UP for money
    assert P.q_money(D("10.004")) == D("10.00")


def test_floats_and_bools_are_rejected_everywhere():
    with pytest.raises(ValueError, match="INVALID_INPUT"):
        P.q_odds(1.9091)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="INVALID_INPUT"):
        P.implied_probability(2.0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="INVALID_INPUT"):
        P.ev_per_dollar(0.2, D("5.5"))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="INVALID_INPUT"):
        P.american_to_decimal(True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="INVALID_INPUT"):
        P.q_money(D("NaN"))


# --------------------------------------------------------------------------------------
# American <-> decimal
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("american", "decimal"),
    [
        (150, "2.5000"),
        (-110, "1.9091"),
        (-200, "1.5000"),
        (100, "2.0000"),
        (-100, "2.0000"),
        (250, "3.5000"),
        (-105, "1.9524"),
    ],
)
def test_american_to_decimal(american: int, decimal: str):
    out = P.american_to_decimal(american)
    assert out == D(decimal)
    assert out.as_tuple().exponent == -4


@pytest.mark.parametrize("bad", [0, 50, -99, 99, -50, 1, -1])
def test_american_to_decimal_rejects_zero_and_small_magnitudes(bad: int):
    with pytest.raises(ValueError, match="INVALID_INPUT"):
        P.american_to_decimal(bad)


@pytest.mark.parametrize(
    "american", [150, -110, -200, 100, -105, 101, -101, -199, 250, -150, 1000, -1000, 105]
)
def test_decimal_to_american_round_trips(american: int):
    assert P.decimal_to_american(P.american_to_decimal(american)) == american


def test_minus_100_round_trips_to_plus_100_because_both_are_even_money():
    assert P.american_to_decimal(-100) == P.american_to_decimal(100) == D("2.0000")
    assert P.decimal_to_american(D("2.0")) == 100


@pytest.mark.parametrize(
    ("decimal", "american"), [("2.5", 150), ("1.9091", -110), ("1.5", -200), ("2.0", 100), ("3.0", 200)]
)
def test_decimal_to_american_known_values(decimal: str, american: int):
    assert P.decimal_to_american(D(decimal)) == american


@pytest.mark.parametrize("bad", ["1", "1.0", "0.5", "0", "-2"])
def test_decimal_to_american_rejects_non_prices(bad: str):
    with pytest.raises(ValueError, match="INVALID_INPUT"):
        P.decimal_to_american(D(bad))


# --------------------------------------------------------------------------------------
# Implied / no-vig
# --------------------------------------------------------------------------------------


def test_implied_probability():
    assert P.implied_probability(D("2.0")) == D("0.500000")
    assert P.implied_probability(D("4.0")) == D("0.250000")
    assert P.implied_probability(D("1.9091")) == D("0.523807")
    with pytest.raises(ValueError, match="INVALID_INPUT"):
        P.implied_probability(D("1"))


def test_no_vig_symmetric_prices_split_evenly():
    p1, p2 = P.no_vig_two_way(D("1.9091"), D("1.9091"))
    assert (p1, p2) == (D("0.500000"), D("0.500000"))


def test_no_vig_asymmetric_prices_sum_to_one():
    p1, p2 = P.no_vig_two_way(D("1.5"), D("2.8"))
    # proportional: p1 = (1/1.5) / (1/1.5 + 1/2.8) = 2.8 / 4.3
    assert p1 == D("0.651163")
    assert p2 == D("0.348837")
    assert abs((p1 + p2) - D(1)) <= D("0.000001")
    assert p1.as_tuple().exponent == -6 and p2.as_tuple().exponent == -6


@pytest.mark.parametrize(
    ("d1", "d2"), [("1.8696", "1.9524"), ("1.3", "3.6"), ("1.05", "11.0"), ("2.1", "1.75")]
)
def test_no_vig_always_sums_to_one_within_tolerance(d1: str, d2: str):
    p1, p2 = P.no_vig_two_way(D(d1), D(d2))
    assert abs((p1 + p2) - D(1)) <= D("0.000001")
    assert D(0) < p1 < D(1) and D(0) < p2 < D(1)


# --------------------------------------------------------------------------------------
# Products, EV, payout
# --------------------------------------------------------------------------------------


def test_three_independent_seventy_percent_legs():
    assert P.independence_baseline([D("0.70"), D("0.70"), D("0.70")]) == D("0.343000")


def test_independence_baseline_validates_inputs():
    with pytest.raises(ValueError, match="INVALID_INPUT"):
        P.independence_baseline([])
    with pytest.raises(ValueError, match="INVALID_INPUT"):
        P.independence_baseline([D("0.7"), D("1.2")])


def test_indicative_multiplied_decimal():
    assert P.indicative_multiplied_decimal([D("2.0"), D("2.0"), D("1.5")]) == D("6.0000")
    assert P.indicative_multiplied_decimal([D("1.5"), D("1.5"), D("1.5")]) == D("3.3750")
    assert P.indicative_multiplied_decimal([D("1.9091"), D("1.9091"), D("1.6667")]) == D("6.0746")
    with pytest.raises(ValueError, match="INVALID_INPUT"):
        P.indicative_multiplied_decimal([D("2.0"), D("1.0")])
    with pytest.raises(ValueError, match="INVALID_INPUT"):
        P.indicative_multiplied_decimal([])


def test_ev_and_break_even():
    assert P.ev_per_dollar(D("0.20"), D("5.50")) == D("0.100000")
    assert P.ev_per_dollar(D("0.181818"), D("5.50")) == D("-0.000001")  # just under break-even after rounding
    assert P.break_even_probability(D("5.50")) == D("0.181818")
    assert P.break_even_probability(D("2.0")) == D("0.500000")


def test_payout_math_with_book_quote():
    out = P.payout_math(D("10"), D("5.50"), "BOOK_QUOTE")
    assert out.combined_decimal == D("5.5000")
    assert out.combined_source == "BOOK_QUOTE"
    assert out.stake_usd == D("10.00")
    assert out.gross_return_usd == D("55.00")
    assert out.net_profit_usd == D("45.00")
    assert out.max_loss_usd == D("10.00")
    assert out.break_even_probability == D("0.181818")
    assert "all legs have action" in out.assumptions  # contract wording, ARCHITECTURE.md section 3
    assert "push/void/reprice outcomes follow the sportsbook's rules and are not modelled" in out.assumptions


def test_payout_math_indicative_and_rounding():
    out = P.payout_math(D("3.33"), D("1.9091"), "INDICATIVE_MULTIPLIED")
    assert out.combined_source == "INDICATIVE_MULTIPLIED"
    assert out.gross_return_usd == D("6.36")
    assert out.net_profit_usd == D("3.03")
    assert out.gross_return_usd - out.stake_usd == out.net_profit_usd
    assert any("indicative" in a for a in out.assumptions)


def test_payout_math_without_combined_price():
    out = P.payout_math(D("10"), None, "NONE")
    assert out.combined_decimal is None
    assert out.combined_source == "NONE"
    assert out.gross_return_usd is None and out.net_profit_usd is None and out.break_even_probability is None
    assert out.max_loss_usd == D("10.00")
    assert "all legs have action" in out.assumptions  # contract wording, ARCHITECTURE.md section 3
    # a missing price forces NONE even if the caller claims a source
    assert P.payout_math(D("10"), None, "BOOK_QUOTE").combined_source == "NONE"


def test_payout_math_rejects_bad_inputs():
    with pytest.raises(ValueError, match="INVALID_INPUT"):
        P.payout_math(D("10"), D("5.5"), "NONE")
    with pytest.raises(ValueError, match="INVALID_INPUT"):
        P.payout_math(D("10"), D("5.5"), "GUESS")
    with pytest.raises(ValueError, match="INVALID_INPUT"):
        P.payout_math(D("-1"), D("5.5"), "BOOK_QUOTE")
    with pytest.raises(ValueError, match="INVALID_INPUT"):
        P.payout_math(10.0, D("5.5"), "BOOK_QUOTE")  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# Book quote replaces indicative
# --------------------------------------------------------------------------------------


def test_book_quote_replaces_multiplied_price():
    combined, source = P.book_quote_replaces_indicative(D("5.50"), D("5.20"))
    assert (combined, source) == (D("5.2000"), "BOOK_QUOTE")
    assert P.quote_difference(D("5.50"), D("5.20")) == D("-0.3000")
    text = P.describe_combined_odds(D("5.50"), D("5.20"))
    assert "5.2000" in text and "5.5000" in text and "-0.3000" in text


def test_indicative_used_only_without_book_quote():
    combined, source = P.book_quote_replaces_indicative(D("5.50"), None)
    assert (combined, source) == (D("5.5000"), "INDICATIVE_MULTIPLIED")
    assert P.quote_difference(D("5.50"), None) is None
    assert "no book quote" in P.describe_combined_odds(D("5.50"), None)


# --------------------------------------------------------------------------------------
# price_value
# --------------------------------------------------------------------------------------


def test_price_value_with_and_without_reference():
    pv = P.price_value(D("2.2"), D("0.5"), "test")
    assert pv.target_decimal == D("2.2000")
    assert pv.fair_decimal == D("2.0000")
    assert pv.edge_per_dollar == D("0.100000")
    none = P.price_value(D("2.2"), None, "no reference")
    assert none.fair_decimal is None and none.edge_per_dollar is None and none.note == "no reference"
    zero = P.price_value(D("2.2"), D("0"), "zero")
    assert zero.fair_decimal is None and zero.edge_per_dollar == D("-1.000000")


# --------------------------------------------------------------------------------------
# estimate_leg_probability
# --------------------------------------------------------------------------------------


@pytest.fixture
def game() -> S.Event:
    return make_event("BOS", "DET")


def test_reference_missing(game):
    q = make_quote(
        game,
        S.MarketType.PLAYER_POINTS,
        S.Side.OVER,
        "1.9091",
        line="24.5",
        player="Cade Cunningham",
        team=TEAMS["DET"],
    )
    est = P.estimate_leg_probability(make_selection(q, game), None)
    assert est.state == S.ModelState.INSUFFICIENT_EVIDENCE
    assert est.value is None
    assert est.method == "REFERENCE_MISSING"
    assert est.reference_book is None and est.reference_stamp is None


def test_player_prop_market_baseline(game):
    q = make_quote(
        game,
        S.MarketType.PLAYER_POINTS,
        S.Side.OVER,
        "1.9091",
        line="24.5",
        player="Cade Cunningham",
        team=TEAMS["DET"],
    )
    ref = make_reference(
        game, S.MarketType.PLAYER_POINTS, "1.8696", "1.9524", line="24.5", player="Cade Cunningham"
    )
    est = P.estimate_leg_probability(make_selection(q, game), ref)
    assert est.state == S.ModelState.MARKET_BASELINE
    assert est.value == P.no_vig_two_way(D("1.8696"), D("1.9524"))[0]
    assert est.method == "proportional_no_vig(pinnacle PLAYER_POINTS 24.5)"
    assert est.reference_book == "pinnacle"
    assert est.reference_stamp == ref.stamp
    assert est.assumptions == [
        "proportional vig removal",
        "benchmark price treated as efficient; not a true probability",
    ]


def test_under_side_gets_the_complementary_probability(game):
    over = make_quote(
        game,
        S.MarketType.PLAYER_POINTS,
        S.Side.OVER,
        "1.9091",
        line="24.5",
        player="Cade Cunningham",
        team=TEAMS["DET"],
    )
    under = make_quote(
        game,
        S.MarketType.PLAYER_POINTS,
        S.Side.UNDER,
        "1.9091",
        line="24.5",
        player="Cade Cunningham",
        team=TEAMS["DET"],
    )
    ref = make_reference(
        game, S.MarketType.PLAYER_POINTS, "1.8696", "1.9524", line="24.5", player="Cade Cunningham"
    )
    p_over = P.estimate_leg_probability(make_selection(over, game), ref).value
    p_under = P.estimate_leg_probability(make_selection(under, game), ref).value
    assert p_over is not None and p_under is not None
    assert abs((p_over + p_under) - D(1)) <= D("0.000001")
    assert p_over > p_under  # 1.8696 is shorter than 1.9524, so the over is the favourite


def test_line_mismatch_over_24_5_vs_reference_25_5(game):
    q = make_quote(
        game,
        S.MarketType.PLAYER_POINTS,
        S.Side.OVER,
        "1.9091",
        line="24.5",
        player="Cade Cunningham",
        team=TEAMS["DET"],
    )
    ref = make_reference(
        game, S.MarketType.PLAYER_POINTS, "1.8696", "1.9524", line="25.5", player="Cade Cunningham"
    )
    est = P.estimate_leg_probability(make_selection(q, game), ref)
    assert est.state == S.ModelState.INSUFFICIENT_EVIDENCE
    assert est.value is None
    assert est.method == "LINE_MISMATCH"
    assert est.reference_book == "pinnacle"


def test_spread_complementary_handicap_matching(game):
    ref = make_reference(game, S.MarketType.SPREAD, "1.9091", "1.9091", line="3.5")  # HOME +3.5 / AWAY -3.5
    home = make_quote(game, S.MarketType.SPREAD, S.Side.HOME, "1.9091", line="3.5", team=TEAMS["DET"])
    away_ok = make_quote(game, S.MarketType.SPREAD, S.Side.AWAY, "1.9091", line="-3.5", team=TEAMS["BOS"])
    away_bad = make_quote(game, S.MarketType.SPREAD, S.Side.AWAY, "1.9091", line="3.5", team=TEAMS["BOS"])
    est_home = P.estimate_leg_probability(make_selection(home, game), ref)
    est_away = P.estimate_leg_probability(make_selection(away_ok, game), ref)
    est_bad = P.estimate_leg_probability(make_selection(away_bad, game), ref)
    assert est_home.state == S.ModelState.MARKET_BASELINE and est_home.value == D("0.500000")
    assert est_home.method == "proportional_no_vig(pinnacle SPREAD 3.5)"
    assert est_away.state == S.ModelState.MARKET_BASELINE and est_away.value == D("0.500000")
    assert est_away.method == "proportional_no_vig(pinnacle SPREAD -3.5)"
    assert est_bad.state == S.ModelState.INSUFFICIENT_EVIDENCE and est_bad.method == "LINE_MISMATCH"


def test_spread_uses_each_sides_own_no_vig_probability(game):
    ref = make_reference(game, S.MarketType.SPREAD, "1.8696", "1.9524", line="3.5")
    home = make_quote(game, S.MarketType.SPREAD, S.Side.HOME, "1.9091", line="3.5", team=TEAMS["DET"])
    away = make_quote(game, S.MarketType.SPREAD, S.Side.AWAY, "1.9091", line="-3.5", team=TEAMS["BOS"])
    p_home, p_away = P.no_vig_two_way(D("1.8696"), D("1.9524"))
    assert P.estimate_leg_probability(make_selection(home, game), ref).value == p_home
    assert P.estimate_leg_probability(make_selection(away, game), ref).value == p_away


def test_moneyline_reference_without_line(game):
    ref = make_reference(game, S.MarketType.MONEYLINE, "2.10", "1.80")
    away = make_quote(game, S.MarketType.MONEYLINE, S.Side.AWAY, "1.85", team=TEAMS["BOS"])
    est = P.estimate_leg_probability(make_selection(away, game), ref)
    assert est.state == S.ModelState.MARKET_BASELINE
    assert est.value == P.no_vig_two_way(D("1.80"), D("2.10"))[0]
    assert est.method == "proportional_no_vig(pinnacle MONEYLINE)"


def test_total_market_baseline_and_mismatch(game):
    over = make_quote(game, S.MarketType.TOTAL, S.Side.OVER, "1.9091", line="224.5")
    ref = make_reference(game, S.MarketType.TOTAL, "1.9524", "1.8696", line="224.5")
    est = P.estimate_leg_probability(make_selection(over, game), ref)
    assert est.state == S.ModelState.MARKET_BASELINE
    assert est.value == P.no_vig_two_way(D("1.9524"), D("1.8696"))[0]
    wrong_line = make_reference(game, S.MarketType.TOTAL, "1.9524", "1.8696", line="225.5")
    assert P.estimate_leg_probability(make_selection(over, game), wrong_line).method == "LINE_MISMATCH"


def test_reference_for_a_different_event_player_or_market_is_not_used(game):
    other = make_event("PHI", "NYK")
    q = make_quote(
        game,
        S.MarketType.PLAYER_POINTS,
        S.Side.OVER,
        "1.9091",
        line="24.5",
        player="Cade Cunningham",
        team=TEAMS["DET"],
    )
    sel = make_selection(q, game)
    wrong_event = make_reference(
        other, S.MarketType.PLAYER_POINTS, "1.8696", "1.9524", line="24.5", player="Cade Cunningham"
    )
    assert P.estimate_leg_probability(sel, wrong_event).method == "EVENT_UNMATCHED"
    wrong_player = make_reference(
        game, S.MarketType.PLAYER_POINTS, "1.8696", "1.9524", line="24.5", player="Jalen Duren"
    )
    assert P.estimate_leg_probability(sel, wrong_player).method == "PLAYER_UNMATCHED"
    wrong_market = make_reference(
        game, S.MarketType.PLAYER_REBOUNDS, "1.8696", "1.9524", line="24.5", player="Cade Cunningham"
    )
    assert P.estimate_leg_probability(sel, wrong_market).method == "LINE_MISMATCH"
    for est in (
        P.estimate_leg_probability(sel, wrong_event),
        P.estimate_leg_probability(sel, wrong_player),
        P.estimate_leg_probability(sel, wrong_market),
    ):
        assert est.state == S.ModelState.INSUFFICIENT_EVIDENCE and est.value is None


def test_team_total_reference_cannot_be_verified_to_a_team(game):
    q = make_quote(game, S.MarketType.TEAM_TOTAL, S.Side.OVER, "1.9091", line="112.5", team=TEAMS["DET"])
    ref = make_reference(game, S.MarketType.TEAM_TOTAL, "1.9091", "1.9091", line="112.5")
    est = P.estimate_leg_probability(make_selection(q, game), ref)
    assert est.state == S.ModelState.INSUFFICIENT_EVIDENCE and est.method == "REFERENCE_INCOMPLETE"


def test_unsupported_period_is_never_priced(game):
    q = make_quote(game, S.MarketType.TOTAL, S.Side.OVER, "1.9091", line="112.5").model_copy(
        update={"period": S.Period.FIRST_HALF}
    )
    ref = make_reference(game, S.MarketType.TOTAL, "1.9091", "1.9091", line="112.5").model_copy(
        update={"period": S.Period.FIRST_HALF}
    )
    est = P.estimate_leg_probability(make_selection(q, game), ref)
    assert est.state == S.ModelState.INSUFFICIENT_EVIDENCE and est.method == "PERIOD_UNSUPPORTED"


# --------------------------------------------------------------------------------------
# joint_probability
# --------------------------------------------------------------------------------------


def test_joint_probability_multi_game_is_the_plain_product(three_multi_game_legs):
    ticket = S.ThreeLegTicket(legs=three_multi_game_legs)
    legs = [_estimate("0.70"), _estimate("0.70"), _estimate("0.70")]
    p, state, method = P.joint_probability(ticket, legs, _report(True))
    assert p == D("0.343000")
    assert state == S.ModelState.MARKET_BASELINE
    assert method == "p1*p2*p3 assuming independence across different games (assumption, not validated)"


def test_joint_probability_none_when_report_disallows(three_multi_game_legs):
    ticket = S.ThreeLegTicket(legs=three_multi_game_legs)
    legs = [_estimate("0.70"), _estimate("0.70"), _estimate("0.70")]
    p, state, method = P.joint_probability(ticket, legs, _report(False))
    assert p is None and state == S.ModelState.INSUFFICIENT_EVIDENCE
    assert method.startswith("JOINT_PROBABILITY_UNAVAILABLE")


def test_joint_probability_none_when_a_leg_has_no_estimate(three_multi_game_legs):
    ticket = S.ThreeLegTicket(legs=three_multi_game_legs)
    legs = [_estimate("0.70"), _estimate(None), _estimate("0.70")]
    p, state, method = P.joint_probability(ticket, legs, _report(True))
    assert p is None and state == S.ModelState.INSUFFICIENT_EVIDENCE
    assert "leg(s) 2" in method


def test_joint_probability_none_for_same_game_even_if_report_claims_allowed(game):
    q1 = make_quote(game, S.MarketType.SPREAD, S.Side.HOME, "1.9091", line="3.5", team=TEAMS["DET"])
    q2 = make_quote(game, S.MarketType.TOTAL, S.Side.OVER, "1.9091", line="224.5")
    q3 = make_quote(
        game,
        S.MarketType.PLAYER_POINTS,
        S.Side.OVER,
        "1.9091",
        line="24.5",
        player="Cade Cunningham",
        team=TEAMS["DET"],
    )
    ticket = S.ThreeLegTicket(
        legs=[make_selection(q1, game), make_selection(q2, game), make_selection(q3, game)]
    )
    assert ticket.parlay_type == S.ParlayType.SAME_GAME
    legs = [_estimate("0.70"), _estimate("0.70"), _estimate("0.70")]
    p, state, method = P.joint_probability(ticket, legs, _report(True))
    assert p is None and state == S.ModelState.INSUFFICIENT_EVIDENCE
    assert "SAME_GAME_CORRELATION" in method


def test_joint_probability_requires_one_estimate_per_leg(three_multi_game_legs):
    ticket = S.ThreeLegTicket(legs=three_multi_game_legs)
    with pytest.raises(ValueError, match="INVALID_INPUT"):
        P.joint_probability(ticket, [_estimate("0.7"), _estimate("0.7")], _report(True))


# --------------------------------------------------------------------------------------
# Review fixes: contract wording of the payout assumption; joint state is the weakest leg state
# --------------------------------------------------------------------------------------


def test_payout_assumption_constant_is_the_contract_string():
    assert P.PAYOUT_ASSUMPTION_ACTION == "all legs have action"
    for payout in (
        P.payout_math(D("10"), D("5.50"), "BOOK_QUOTE"),
        P.payout_math(D("10"), D("5.50"), "INDICATIVE_MULTIPLIED"),
        P.payout_math(D("10"), None, "NONE"),
    ):
        assert payout.assumptions[0] == "all legs have action"


def test_weakest_model_state_orders_evidence_weakest_first():
    MS = S.ModelState
    assert P.weakest_model_state([MS.MARKET_BASELINE, MS.MARKET_BASELINE]) == MS.MARKET_BASELINE
    assert P.weakest_model_state([MS.VALIDATED_MODEL, MS.MARKET_BASELINE]) == MS.MARKET_BASELINE
    assert P.weakest_model_state([MS.MARKET_BASELINE, MS.UNVALIDATED_MODEL]) == MS.UNVALIDATED_MODEL
    assert P.weakest_model_state([MS.UNVALIDATED_MODEL, MS.INSUFFICIENT_EVIDENCE]) == MS.INSUFFICIENT_EVIDENCE
    with pytest.raises(ValueError, match="INVALID_INPUT"):
        P.weakest_model_state([])


def _estimate_with_state(value: str, state: S.ModelState) -> S.ProbabilityEstimate:
    return S.ProbabilityEstimate(value=D(value), state=state, method=f"test {state.value}")


def test_joint_state_follows_the_weakest_leg_and_names_it(three_multi_game_legs):
    ticket = S.ThreeLegTicket(legs=three_multi_game_legs)
    legs = [
        _estimate_with_state("0.7", S.ModelState.MARKET_BASELINE),
        _estimate_with_state("0.7", S.ModelState.UNVALIDATED_MODEL),
        _estimate_with_state("0.7", S.ModelState.MARKET_BASELINE),
    ]
    p, state, method = P.joint_probability(ticket, legs, _report(True))
    assert p == D("0.343000")  # the number is unchanged; only its label is weaker
    assert state == S.ModelState.UNVALIDATED_MODEL
    assert method.startswith(P.JOINT_INDEPENDENCE_METHOD)
    assert "UNVALIDATED_MODEL" in method and "leg(s) 2" in method


def test_joint_state_stays_market_baseline_when_a_validated_leg_joins_baselines(three_multi_game_legs):
    ticket = S.ThreeLegTicket(legs=three_multi_game_legs)
    legs = [
        _estimate_with_state("0.5", S.ModelState.VALIDATED_MODEL),
        _estimate_with_state("0.5", S.ModelState.MARKET_BASELINE),
        _estimate_with_state("0.5", S.ModelState.MARKET_BASELINE),
    ]
    p, state, method = P.joint_probability(ticket, legs, _report(True))
    assert p == D("0.125000")
    assert state == S.ModelState.MARKET_BASELINE
    assert method == P.JOINT_INDEPENDENCE_METHOD  # the day-one label and method are unchanged
