"""Adversarial review of the quant module (probabilities.py, correlation.py).

Every test marked "DEFECT" reproduced one reviewer finding against the original implementation and is kept
as a regression test now that the finding is fixed. Expected numbers are computed by hand with plain
``Decimal`` arithmetic, never with the module's own helpers. One test is marked "PASSES" and is kept on
purpose: it pins the boundary that the fix for the first defect must not cross (a legal middle is not
mutually exclusive).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from conftest import TEAMS, make_event, make_quote, make_selection

from hardrock_nba_parlay import correlation as C
from hardrock_nba_parlay import probabilities as P
from hardrock_nba_parlay import schemas as S

D = Decimal
MT, SD = S.MarketType, S.Side


def _sel(
    event: S.Event,
    market: S.MarketType,
    side: S.Side,
    *,
    line: str | None = None,
    player: str | None = None,
    team: str | None = None,
    odds: str = "1.9091",
    description: str | None = None,
) -> S.Selection:
    quote = make_quote(
        event, market, side, odds, line=line, player=player, team=TEAMS[team] if team else None
    )
    return make_selection(quote, event, description)


@pytest.fixture
def g1() -> S.Event:
    return make_event("BOS", "DET")


@pytest.fixture
def g2() -> S.Event:
    return make_event("PHI", "NYK")


@pytest.fixture
def g2_under(g2) -> S.Selection:
    return _sel(g2, MT.TOTAL, SD.UNDER, line="219.5", description="PHI/NYK under 219.5")


# --------------------------------------------------------------------------------------
# DEFECT 1 (high): a team's moneyline and the opponent's spread can be jointly impossible, yet the
# pair is never examined because the two legs have different market keys. The ticket passes
# hard_rejections with no code and check_correlation reports only the generic same-game block,
# so a bettor is told the ticket is "combinable, correlated" when it can never pay.
#
# Home margin m is an integer. HOME moneyline wins iff m >= 1; AWAY spread at line a covers iff
# m < a. HOME spread at line h covers iff m > -h; AWAY moneyline wins iff m <= -1.
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ml_side", "ml_team", "spread_side", "spread_team", "spread_line", "why"),
    [
        (SD.HOME, "DET", SD.AWAY, "BOS", "-3.5", "DET wins needs m >= 1; BOS -3.5 needs m <= -4"),
        (SD.AWAY, "BOS", SD.HOME, "DET", "-3.5", "BOS wins needs m <= -1; DET -3.5 needs m >= 4"),
        (SD.HOME, "DET", SD.AWAY, "BOS", "-0.5", "DET wins needs m >= 1; BOS -0.5 needs m <= -1"),
    ],
)
def test_moneyline_and_opponent_spread_that_cannot_both_win_is_mutually_exclusive(
    g1, g2_under, ml_side, ml_team, spread_side, spread_team, spread_line, why
):
    ml = _sel(g1, MT.MONEYLINE, ml_side, team=ml_team, odds="2.30", description=f"{ml_team} ML")
    spread = _sel(
        g1,
        MT.SPREAD,
        spread_side,
        line=spread_line,
        team=spread_team,
        description=f"{spread_team} {spread_line}",
    )
    codes = C.hard_rejections([ml, spread, g2_under])
    assert "MUTUALLY_EXCLUSIVE_SELECTION" in codes, why

    report = C.check_correlation(S.ThreeLegTicket(legs=[ml, spread, g2_under]))
    blocking = {f.type for f in report.flags if f.severity == S.Severity.BLOCKING}
    assert S.CorrelationType.MUTUALLY_EXCLUSIVE in blocking, why


def test_moneyline_with_opponent_underdog_spread_is_a_legal_middle(g1, g2_under):
    # PASSES against the current code. Kept to pin the boundary for the fix above: DET ML + BOS +3.5
    # both win when DET wins by 1, 2, or 3, so this pair must stay free of MUTUALLY_EXCLUSIVE.
    det_ml = _sel(g1, MT.MONEYLINE, SD.HOME, team="DET", odds="2.30", description="DET ML")
    bos_dog = _sel(g1, MT.SPREAD, SD.AWAY, line="3.5", team="BOS", description="BOS +3.5")
    assert "MUTUALLY_EXCLUSIVE_SELECTION" not in C.hard_rejections([det_ml, bos_dog, g2_under])
    report = C.check_correlation(S.ThreeLegTicket(legs=[det_ml, bos_dog, g2_under]))
    assert S.CorrelationType.MUTUALLY_EXCLUSIVE not in {f.type for f in report.flags}


# --------------------------------------------------------------------------------------
# DEFECT 2 (medium): describe_parlay_type dedupes games by short_name but the ticket's parlay type is
# derived from event_id. A MIXED ticket whose two event ids render to the same matchup (the same game
# imported once from the provider and once manually) makes `next(g for g in games if g != shared)`
# raise StopIteration, so check_correlation crashes instead of returning a report.
# --------------------------------------------------------------------------------------


def test_check_correlation_survives_two_event_ids_for_one_matchup():
    provider = make_event("BOS", "DET", event_id="oddsapi:abc123")
    manual = make_event("BOS", "DET", event_id="manual:bos-det")
    a = _sel(provider, MT.SPREAD, SD.HOME, line="3.5", team="DET", description="DET +3.5")
    b = _sel(provider, MT.TOTAL, SD.OVER, line="224.5", description="BOS/DET over 224.5")
    c = _sel(manual, MT.MONEYLINE, SD.HOME, team="DET", odds="2.30", description="DET ML (manual)")
    ticket = S.ThreeLegTicket(legs=[a, b, c])
    assert ticket.parlay_type == S.ParlayType.MIXED

    report = C.check_correlation(ticket)  # raised StopIteration before the fix
    assert report.joint_numeric_allowed is False
    assert report.explanation.startswith("MIXED")


# --------------------------------------------------------------------------------------
# DEFECT 3 (low): ARCHITECTURE.md section 3 says PayoutMath.assumptions "includes 'all legs have
# action'". The module emits only "all three legs have action", so any downstream check written against
# the binding contract misses it.
# --------------------------------------------------------------------------------------


def test_payout_assumptions_carry_the_contract_wording():
    priced = P.payout_math(D("10"), D("5.50"), "BOOK_QUOTE")
    unpriced = P.payout_math(D("10"), None, "NONE")
    assert "all legs have action" in priced.assumptions
    assert "all legs have action" in unpriced.assumptions


# --------------------------------------------------------------------------------------
# DEFECT 4 (low): joint_probability labels the product MARKET_BASELINE regardless of the leg states.
# A joint built from an UNVALIDATED_MODEL leg is presented to the bettor as market-baseline evidence.
# The joint's state must be no stronger than its weakest input.
# --------------------------------------------------------------------------------------


def test_joint_state_is_not_market_baseline_when_a_leg_is_an_unvalidated_model(three_multi_game_legs):
    ticket = S.ThreeLegTicket(legs=three_multi_game_legs)
    report = C.check_correlation(ticket)
    assert report.joint_numeric_allowed is True
    legs = [
        S.ProbabilityEstimate(
            value=D("0.5"), state=S.ModelState.UNVALIDATED_MODEL, method="toy model, not validated"
        ),
        S.ProbabilityEstimate(
            value=D("0.5"),
            state=S.ModelState.MARKET_BASELINE,
            method="proportional_no_vig(pinnacle TOTAL 224.5)",
        ),
        S.ProbabilityEstimate(
            value=D("0.5"),
            state=S.ModelState.MARKET_BASELINE,
            method="proportional_no_vig(pinnacle MONEYLINE)",
        ),
    ]
    p, state, _method = P.joint_probability(ticket, legs, report)
    assert p == D("0.125000")  # 0.5 * 0.5 * 0.5 by hand
    assert state == S.ModelState.UNVALIDATED_MODEL
