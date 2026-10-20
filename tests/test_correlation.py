"""Tests for correlation.py: hard rejections before ticket construction and correlation flags on tickets."""

from __future__ import annotations

import pytest
from conftest import TEAMS, make_event, make_quote, make_selection
from pydantic import ValidationError

from hardrock_nba_parlay import correlation as C
from hardrock_nba_parlay import schemas as S

MT, SD = S.MarketType, S.Side


@pytest.fixture
def g1() -> S.Event:
    return make_event("BOS", "DET")


@pytest.fixture
def g2() -> S.Event:
    return make_event("PHI", "NYK")


@pytest.fixture
def g3() -> S.Event:
    return make_event("OKC", "SAS")


def sel(
    event: S.Event,
    market: S.MarketType,
    side: S.Side,
    *,
    line: str | None = None,
    player: str | None = None,
    team: str | None = None,
    odds: str = "1.9091",
    is_alternate: bool = False,
    description: str | None = None,
) -> S.Selection:
    q = make_quote(
        event,
        market,
        side,
        odds,
        line=line,
        player=player,
        team=TEAMS[team] if team else None,
        is_alternate=is_alternate,
    )
    return make_selection(q, event, description)


def flag_types(report: S.CorrelationReport) -> set[S.CorrelationType]:
    return {f.type for f in report.flags}


def flag(report: S.CorrelationReport, kind: S.CorrelationType) -> S.CorrelationFlag:
    matches = [f for f in report.flags if f.type == kind]
    assert matches, f"{kind} not in {[f.type for f in report.flags]}"
    return matches[0]


# --------------------------------------------------------------------------------------
# Shared fixture legs
# --------------------------------------------------------------------------------------


@pytest.fixture
def det_spread(g1) -> S.Selection:
    return sel(g1, MT.SPREAD, SD.HOME, line="3.5", team="DET", description="DET +3.5")


@pytest.fixture
def det_ml(g1) -> S.Selection:
    return sel(g1, MT.MONEYLINE, SD.HOME, team="DET", odds="2.30", description="DET ML")


@pytest.fixture
def g1_total_over(g1) -> S.Selection:
    return sel(g1, MT.TOTAL, SD.OVER, line="224.5", description="BOS/DET over 224.5")


@pytest.fixture
def cade_points_over(g1) -> S.Selection:
    return sel(
        g1,
        MT.PLAYER_POINTS,
        SD.OVER,
        line="24.5",
        player="Cade Cunningham",
        team="DET",
        description="Cunningham over 24.5 pts",
    )


@pytest.fixture
def cade_threes_over(g1) -> S.Selection:
    return sel(
        g1,
        MT.PLAYER_THREES,
        SD.OVER,
        line="2.5",
        player="Cade Cunningham",
        team="DET",
        description="Cunningham over 2.5 threes",
    )


@pytest.fixture
def cade_assists_over(g1) -> S.Selection:
    return sel(
        g1,
        MT.PLAYER_ASSISTS,
        SD.OVER,
        line="6.5",
        player="Cade Cunningham",
        team="DET",
        description="Cunningham over 6.5 ast",
    )


@pytest.fixture
def duren_points_over(g1) -> S.Selection:
    return sel(
        g1,
        MT.PLAYER_POINTS,
        SD.OVER,
        line="14.5",
        player="Jalen Duren",
        team="DET",
        description="Duren over 14.5 pts",
    )


@pytest.fixture
def tatum_points_over(g1) -> S.Selection:
    return sel(
        g1,
        MT.PLAYER_POINTS,
        SD.OVER,
        line="27.5",
        player="Jayson Tatum",
        team="BOS",
        description="Tatum over 27.5 pts",
    )


@pytest.fixture
def g2_total_under(g2) -> S.Selection:
    return sel(g2, MT.TOTAL, SD.UNDER, line="219.5", description="PHI/NYK under 219.5")


@pytest.fixture
def g3_okc_ml(g3) -> S.Selection:
    return sel(g3, MT.MONEYLINE, SD.AWAY, team="OKC", odds="1.6667", description="OKC ML")


# --------------------------------------------------------------------------------------
# hard_rejections: leg count and the schema validator
# --------------------------------------------------------------------------------------


def test_clean_multi_game_legs_have_no_rejections(det_spread, g2_total_under, g3_okc_ml):
    assert C.hard_rejections([det_spread, g2_total_under, g3_okc_ml]) == []
    ticket = S.ThreeLegTicket(legs=[det_spread, g2_total_under, g3_okc_ml])
    assert C.hard_rejections(ticket) == []  # accepts a ticket as well as a list


def test_two_legs_rejected_by_hard_rejections_and_by_the_schema(det_spread, g2_total_under):
    assert C.hard_rejections([det_spread, g2_total_under]) == ["NOT_THREE_LEGS"]
    with pytest.raises(ValidationError, match="NOT_THREE_LEGS"):
        S.ThreeLegTicket(legs=[det_spread, g2_total_under])


def test_four_legs_rejected_by_hard_rejections_and_by_the_schema(
    det_spread, g2_total_under, g3_okc_ml, cade_points_over
):
    legs = [det_spread, g2_total_under, g3_okc_ml, cade_points_over]
    assert C.hard_rejections(legs) == ["NOT_THREE_LEGS"]
    with pytest.raises(ValidationError, match="NOT_THREE_LEGS"):
        S.ThreeLegTicket(legs=legs)


def test_zero_legs():
    assert C.hard_rejections([]) == ["NOT_THREE_LEGS"]


def test_four_legs_with_a_duplicate_report_both_codes(det_spread, g2_total_under, g3_okc_ml):
    codes = C.hard_rejections([det_spread, g2_total_under, g3_okc_ml, det_spread])
    assert codes == ["NOT_THREE_LEGS", "DUPLICATE_SELECTION"]


# --------------------------------------------------------------------------------------
# hard_rejections: duplicate / contradictory / nested / mutually exclusive / period
# --------------------------------------------------------------------------------------


def test_duplicate_same_selection_twice(det_spread, g2_total_under):
    assert "DUPLICATE_SELECTION" in C.hard_rejections([det_spread, det_spread, g2_total_under])
    with pytest.raises(ValidationError, match="DUPLICATE_SELECTION"):
        S.ThreeLegTicket(legs=[det_spread, det_spread, g2_total_under])


def test_duplicate_same_outcome_at_another_book_or_as_alternate(g1, det_spread, g2_total_under):
    other_book = make_selection(
        make_quote(g1, MT.SPREAD, SD.HOME, "1.95", line="3.5", team=TEAMS["DET"], book="draftkings"),
        g1,
        "DET +3.5 (DK)",
    )
    assert other_book.selection_id != det_spread.selection_id
    assert C.hard_rejections([det_spread, other_book, g2_total_under]) == ["DUPLICATE_SELECTION"]
    alternate = sel(
        g1,
        MT.SPREAD,
        SD.HOME,
        line="3.5",
        team="DET",
        is_alternate=True,
        odds="1.95",
        description="DET +3.5 (alt)",
    )
    assert alternate.quote.identity_tuple() != det_spread.quote.identity_tuple()
    assert C.hard_rejections([det_spread, alternate, g2_total_under]) == ["DUPLICATE_SELECTION"]


def test_contradictory_moneyline_home_vs_away(g1, det_ml, g2_total_under):
    bos_ml = sel(g1, MT.MONEYLINE, SD.AWAY, team="BOS", odds="1.65", description="BOS ML")
    assert C.hard_rejections([det_ml, bos_ml, g2_total_under]) == ["CONTRADICTORY_SELECTION"]


def test_contradictory_spread_complementary_handicaps(g1, det_spread, g2_total_under):
    bos_spread = sel(g1, MT.SPREAD, SD.AWAY, line="-3.5", team="BOS", description="BOS -3.5")
    assert C.hard_rejections([det_spread, bos_spread, g2_total_under]) == ["CONTRADICTORY_SELECTION"]


def test_contradictory_total_over_vs_under_same_line(g1, g1_total_over, g2_total_under):
    under = sel(g1, MT.TOTAL, SD.UNDER, line="224.5", description="BOS/DET under 224.5")
    assert C.hard_rejections([g1_total_over, under, g2_total_under]) == ["CONTRADICTORY_SELECTION"]


def test_contradictory_player_prop_over_vs_under_same_line(g1, cade_points_over, g2_total_under):
    under = sel(g1, MT.PLAYER_POINTS, SD.UNDER, line="24.5", player="Cade Cunningham", team="DET")
    assert C.hard_rejections([cade_points_over, under, g2_total_under]) == ["CONTRADICTORY_SELECTION"]


def test_nested_player_points_over_two_lines(g1, cade_points_over, g2_total_under):
    higher = sel(
        g1,
        MT.PLAYER_POINTS,
        SD.OVER,
        line="20.5",
        player="Cade Cunningham",
        team="DET",
        odds="1.40",
        description="Cunningham over 20.5 pts",
    )
    assert C.hard_rejections([cade_points_over, higher, g2_total_under]) == ["NESTED_SELECTION"]


def test_nested_spread_same_team_two_handicaps(g1, det_spread, g2_total_under):
    wider = sel(g1, MT.SPREAD, SD.HOME, line="5.5", team="DET", odds="1.60", description="DET +5.5")
    assert C.hard_rejections([det_spread, wider, g2_total_under]) == ["NESTED_SELECTION"]


def test_mutually_exclusive_over_x_with_under_y_below_x(g1, g2_total_under):
    over = sel(g1, MT.PLAYER_POINTS, SD.OVER, line="25.5", player="Cade Cunningham", team="DET")
    under = sel(g1, MT.PLAYER_POINTS, SD.UNDER, line="24.5", player="Cade Cunningham", team="DET")
    assert C.hard_rejections([over, under, g2_total_under]) == ["MUTUALLY_EXCLUSIVE_SELECTION"]
    # whole-number lines: over 25 and under 26 cannot both win either (26+ vs 25-)
    over_w = sel(g1, MT.PLAYER_POINTS, SD.OVER, line="25", player="Cade Cunningham", team="DET")
    under_w = sel(g1, MT.PLAYER_POINTS, SD.UNDER, line="26", player="Cade Cunningham", team="DET")
    assert C.hard_rejections([over_w, under_w, g2_total_under]) == ["MUTUALLY_EXCLUSIVE_SELECTION"]


def test_a_middle_is_not_mutually_exclusive(g1, g2_total_under):
    over = sel(g1, MT.PLAYER_POINTS, SD.OVER, line="24.5", player="Cade Cunningham", team="DET")
    under = sel(g1, MT.PLAYER_POINTS, SD.UNDER, line="25.5", player="Cade Cunningham", team="DET")
    assert C.hard_rejections([over, under, g2_total_under]) == []  # exactly 25 wins both


def test_mutually_exclusive_spread_sides(g1, det_spread, g2_total_under):
    bos_big = sel(g1, MT.SPREAD, SD.AWAY, line="-5.5", team="BOS", description="BOS -5.5")
    assert C.hard_rejections([det_spread, bos_big, g2_total_under]) == ["MUTUALLY_EXCLUSIVE_SELECTION"]
    bos_small = sel(g1, MT.SPREAD, SD.AWAY, line="-1.5", team="BOS", description="BOS -1.5")
    assert C.hard_rejections([det_spread, bos_small, g2_total_under]) == []  # BOS by 2 or 3 wins both


def test_home_ml_with_away_ml_is_contradictory_not_mutually_exclusive(g1, det_ml, g2_total_under):
    bos_ml = sel(g1, MT.MONEYLINE, SD.AWAY, team="BOS", odds="1.65")
    codes = C.hard_rejections([det_ml, bos_ml, g2_total_under])
    assert codes == ["CONTRADICTORY_SELECTION"]
    assert "MUTUALLY_EXCLUSIVE_SELECTION" not in codes


def test_period_unsupported(g1, det_spread, g2_total_under, g3_okc_ml):
    first_half = make_selection(
        det_spread.quote.model_copy(update={"period": S.Period.FIRST_HALF}), g1, "DET +3.5 (1H)"
    )
    assert C.hard_rejections([first_half, g2_total_under, g3_okc_ml]) == ["PERIOD_UNSUPPORTED"]


def test_different_games_never_trigger_market_rejections(g1, g2, det_spread):
    # same market shape, other game: not a duplicate, not contradictory
    nyk_spread = sel(g2, MT.SPREAD, SD.HOME, line="3.5", team="NYK", description="NYK +3.5")
    phi_spread = sel(g2, MT.SPREAD, SD.AWAY, line="-3.5", team="PHI", description="PHI -3.5")
    assert C.hard_rejections([det_spread, nyk_spread, phi_spread]) == [
        "CONTRADICTORY_SELECTION"
    ]  # only the g2 pair
    other_game_over = sel(g2, MT.TOTAL, SD.OVER, line="224.5")
    assert C.hard_rejections([det_spread, nyk_spread, other_game_over]) == []


# --------------------------------------------------------------------------------------
# check_correlation: multi-game baseline
# --------------------------------------------------------------------------------------


def test_multi_game_ticket_has_no_flags_and_allows_numeric_joint(det_spread, g2_total_under, g3_okc_ml):
    report = C.check_correlation(S.ThreeLegTicket(legs=[det_spread, g2_total_under, g3_okc_ml]))
    assert report.flags == []
    assert report.joint_numeric_allowed is True
    assert report.weakest_assumption == "independence across games is assumed, not demonstrated"
    assert "MULTI_GAME" in report.explanation


def test_same_game_ticket_blocks_numeric_joint(det_spread, g1_total_over, cade_points_over):
    report = C.check_correlation(S.ThreeLegTicket(legs=[det_spread, g1_total_over, cade_points_over]))
    assert report.joint_numeric_allowed is False
    assert report.weakest_assumption == (
        "joint outcome depends on shared game state (pace, minutes, score margin) that no validated model here quantifies"
    )
    f = flag(report, S.CorrelationType.SAME_GAME_UNQUANTIFIED)
    assert f.severity == S.Severity.BLOCKING
    assert f.leg_indexes == [0, 1, 2]
    assert "no validated joint model; marginals cannot be multiplied" in f.explanation
    assert "SAME_GAME" in report.explanation


def test_mixed_ticket_blocks_numeric_joint_and_indexes_the_shared_pair(det_spread, g1_total_over, g3_okc_ml):
    report = C.check_correlation(S.ThreeLegTicket(legs=[g3_okc_ml, det_spread, g1_total_over]))
    assert report.joint_numeric_allowed is False
    assert flag(report, S.CorrelationType.SAME_GAME_UNQUANTIFIED).leg_indexes == [1, 2]
    assert report.weakest_assumption.startswith("joint outcome depends on shared game state")
    assert "MIXED" in report.explanation


# --------------------------------------------------------------------------------------
# check_correlation: each soft flag
# --------------------------------------------------------------------------------------


def test_same_player_points_threes(cade_points_over, cade_threes_over, g3_okc_ml):
    report = C.check_correlation(S.ThreeLegTicket(legs=[cade_points_over, cade_threes_over, g3_okc_ml]))
    f = flag(report, S.CorrelationType.SAME_PLAYER_POINTS_THREES)
    assert f.severity == S.Severity.WARNING and f.leg_indexes == [0, 1]
    assert S.CorrelationType.MULTIPLE_OVERS_SHARED_PACE in flag_types(report)
    assert S.CorrelationType.SHARED_MINUTES_OR_INJURY in flag_types(report)
    assert report.joint_numeric_allowed is False


def test_same_player_points_threes_under_under(g1, g3_okc_ml):
    pts = sel(g1, MT.PLAYER_POINTS, SD.UNDER, line="24.5", player="Cade Cunningham", team="DET")
    threes = sel(g1, MT.PLAYER_THREES, SD.UNDER, line="2.5", player="Cade Cunningham", team="DET")
    report = C.check_correlation(S.ThreeLegTicket(legs=[pts, threes, g3_okc_ml]))
    assert S.CorrelationType.SAME_PLAYER_POINTS_THREES in flag_types(report)
    assert S.CorrelationType.MULTIPLE_OVERS_SHARED_PACE not in flag_types(report)


def test_assists_and_teammate_points(cade_assists_over, duren_points_over, g3_okc_ml):
    report = C.check_correlation(S.ThreeLegTicket(legs=[cade_assists_over, duren_points_over, g3_okc_ml]))
    f = flag(report, S.CorrelationType.ASSISTS_AND_TEAMMATE_POINTS)
    assert f.severity == S.Severity.WARNING and f.leg_indexes == [0, 1]


def test_assists_and_opponent_points_is_not_the_teammate_flag(
    cade_assists_over, tatum_points_over, g3_okc_ml
):
    report = C.check_correlation(S.ThreeLegTicket(legs=[cade_assists_over, tatum_points_over, g3_okc_ml]))
    assert S.CorrelationType.ASSISTS_AND_TEAMMATE_POINTS not in flag_types(report)
    assert S.CorrelationType.SHARED_MINUTES_OR_INJURY not in flag_types(report)  # different teams
    assert S.CorrelationType.MULTIPLE_OVERS_SHARED_PACE in flag_types(report)  # still two overs in one game


def test_team_win_and_spread(det_ml, det_spread, g3_okc_ml):
    report = C.check_correlation(S.ThreeLegTicket(legs=[det_ml, det_spread, g3_okc_ml]))
    f = flag(report, S.CorrelationType.TEAM_WIN_AND_SPREAD)
    assert f.severity == S.Severity.WARNING and f.leg_indexes == [0, 1]
    assert "nested-like" in f.explanation


def test_team_win_with_opponent_spread_is_not_the_nested_like_flag(g1, det_ml, g3_okc_ml):
    bos_spread = sel(g1, MT.SPREAD, SD.AWAY, line="-3.5", team="BOS", description="BOS -3.5")
    report = C.check_correlation(S.ThreeLegTicket(legs=[det_ml, bos_spread, g3_okc_ml]))
    assert S.CorrelationType.TEAM_WIN_AND_SPREAD not in flag_types(report)
    assert S.CorrelationType.SAME_GAME_UNQUANTIFIED in flag_types(report)


def test_player_scoring_and_game_total(cade_points_over, g1_total_over, g3_okc_ml):
    report = C.check_correlation(S.ThreeLegTicket(legs=[cade_points_over, g1_total_over, g3_okc_ml]))
    f = flag(report, S.CorrelationType.PLAYER_SCORING_AND_GAME_TOTAL)
    assert f.severity == S.Severity.WARNING and f.leg_indexes == [0, 1]
    assert S.CorrelationType.MULTIPLE_OVERS_SHARED_PACE in flag_types(report)


def test_player_threes_under_and_total_under(g1, g3_okc_ml):
    threes = sel(g1, MT.PLAYER_THREES, SD.UNDER, line="2.5", player="Cade Cunningham", team="DET")
    total = sel(g1, MT.TOTAL, SD.UNDER, line="224.5")
    report = C.check_correlation(S.ThreeLegTicket(legs=[threes, total, g3_okc_ml]))
    assert S.CorrelationType.PLAYER_SCORING_AND_GAME_TOTAL in flag_types(report)


def test_multiple_overs_shared_pace_lists_every_over(cade_points_over, g1_total_over, tatum_points_over):
    report = C.check_correlation(S.ThreeLegTicket(legs=[cade_points_over, g1_total_over, tatum_points_over]))
    f = flag(report, S.CorrelationType.MULTIPLE_OVERS_SHARED_PACE)
    assert f.severity == S.Severity.WARNING and f.leg_indexes == [0, 1, 2]


def test_shared_minutes_or_injury(cade_points_over, duren_points_over, g3_okc_ml):
    report = C.check_correlation(S.ThreeLegTicket(legs=[cade_points_over, duren_points_over, g3_okc_ml]))
    f = flag(report, S.CorrelationType.SHARED_MINUTES_OR_INJURY)
    assert f.severity == S.Severity.WARNING and f.leg_indexes == [0, 1]
    assert "minutes" in f.explanation.lower() and "injury" in f.explanation.lower()


def test_shared_blowout_sensitivity(cade_points_over, det_spread, g3_okc_ml):
    report = C.check_correlation(S.ThreeLegTicket(legs=[cade_points_over, det_spread, g3_okc_ml]))
    f = flag(report, S.CorrelationType.SHARED_BLOWOUT_SENSITIVITY)
    assert f.severity == S.Severity.INFO and f.leg_indexes == [0, 1]


# --------------------------------------------------------------------------------------
# check_correlation: hard flags surface as BLOCKING on a constructible ticket
# --------------------------------------------------------------------------------------


def test_duplicate_flag_on_ticket(g1, det_spread, g2_total_under):
    alternate = sel(g1, MT.SPREAD, SD.HOME, line="3.5", team="DET", is_alternate=True, odds="1.95")
    report = C.check_correlation(S.ThreeLegTicket(legs=[det_spread, alternate, g2_total_under]))
    assert flag(report, S.CorrelationType.DUPLICATE).severity == S.Severity.BLOCKING
    assert report.joint_numeric_allowed is False


def test_nested_flag_on_ticket(g1, cade_points_over, g2_total_under):
    lower = sel(g1, MT.PLAYER_POINTS, SD.OVER, line="20.5", player="Cade Cunningham", team="DET", odds="1.40")
    report = C.check_correlation(S.ThreeLegTicket(legs=[cade_points_over, lower, g2_total_under]))
    assert flag(report, S.CorrelationType.NESTED).severity == S.Severity.BLOCKING
    assert "NESTED_SELECTION" in report.explanation


def test_contradictory_flag_on_ticket(g1, g1_total_over, g2_total_under):
    under = sel(g1, MT.TOTAL, SD.UNDER, line="224.5")
    report = C.check_correlation(S.ThreeLegTicket(legs=[g1_total_over, under, g2_total_under]))
    assert flag(report, S.CorrelationType.CONTRADICTORY).severity == S.Severity.BLOCKING


def test_mutually_exclusive_flag_on_ticket(g1, g2_total_under):
    over = sel(g1, MT.PLAYER_POINTS, SD.OVER, line="25.5", player="Cade Cunningham", team="DET")
    under = sel(g1, MT.PLAYER_POINTS, SD.UNDER, line="24.5", player="Cade Cunningham", team="DET")
    report = C.check_correlation(S.ThreeLegTicket(legs=[over, under, g2_total_under]))
    assert flag(report, S.CorrelationType.MUTUALLY_EXCLUSIVE).severity == S.Severity.BLOCKING


def test_blocking_flags_are_listed_first(cade_points_over, det_spread, g3_okc_ml):
    report = C.check_correlation(S.ThreeLegTicket(legs=[cade_points_over, det_spread, g3_okc_ml]))
    ranks = [{"BLOCKING": 0, "WARNING": 1, "INFO": 2}[f.severity.value] for f in report.flags]
    assert ranks == sorted(ranks)
    assert report.flags[0].type == S.CorrelationType.SAME_GAME_UNQUANTIFIED


# --------------------------------------------------------------------------------------
# Every CorrelationType is produced by some fixture ticket
# --------------------------------------------------------------------------------------


def test_every_correlation_type_is_produced_by_a_fixture_ticket(
    g1,
    det_spread,
    det_ml,
    g1_total_over,
    cade_points_over,
    cade_threes_over,
    cade_assists_over,
    duren_points_over,
    g2_total_under,
    g3_okc_ml,
):
    tickets = [
        [
            cade_points_over,
            cade_threes_over,
            g3_okc_ml,
        ],  # SAME_PLAYER_POINTS_THREES, MULTIPLE_OVERS, SHARED_MINUTES, SAME_GAME
        [cade_assists_over, duren_points_over, g3_okc_ml],  # ASSISTS_AND_TEAMMATE_POINTS
        [det_ml, det_spread, g3_okc_ml],  # TEAM_WIN_AND_SPREAD
        [cade_points_over, g1_total_over, g3_okc_ml],  # PLAYER_SCORING_AND_GAME_TOTAL
        [cade_points_over, det_spread, g3_okc_ml],  # SHARED_BLOWOUT_SENSITIVITY
        [
            det_spread,
            sel(g1, MT.SPREAD, SD.HOME, line="3.5", team="DET", is_alternate=True, odds="1.95"),
            g2_total_under,
        ],  # DUPLICATE
        [
            cade_points_over,
            sel(
                g1, MT.PLAYER_POINTS, SD.OVER, line="20.5", player="Cade Cunningham", team="DET", odds="1.40"
            ),
            g2_total_under,
        ],  # NESTED
        [g1_total_over, sel(g1, MT.TOTAL, SD.UNDER, line="224.5"), g2_total_under],  # CONTRADICTORY
        [
            sel(g1, MT.PLAYER_POINTS, SD.OVER, line="25.5", player="Cade Cunningham", team="DET"),
            sel(g1, MT.PLAYER_POINTS, SD.UNDER, line="24.5", player="Cade Cunningham", team="DET"),
            g2_total_under,
        ],  # MUTUALLY_EXCLUSIVE
    ]
    produced: set[S.CorrelationType] = set()
    for legs in tickets:
        produced |= flag_types(C.check_correlation(S.ThreeLegTicket(legs=legs)))
    missing = set(S.CorrelationType) - produced
    assert not missing, f"never produced: {sorted(t.value for t in missing)}"


# --------------------------------------------------------------------------------------
# describe_parlay_type
# --------------------------------------------------------------------------------------


def test_describe_parlay_type(det_spread, g1_total_over, cade_points_over, g2_total_under, g3_okc_ml):
    multi = C.describe_parlay_type(S.ThreeLegTicket(legs=[det_spread, g2_total_under, g3_okc_ml]))
    assert (
        multi.startswith("MULTI_GAME")
        and "BOS @ DET" in multi
        and "PHI @ NYK" in multi
        and "OKC @ SAS" in multi
    )
    same = C.describe_parlay_type(S.ThreeLegTicket(legs=[det_spread, g1_total_over, cade_points_over]))
    assert same.startswith("SAME_GAME") and "BOS @ DET" in same
    mixed = C.describe_parlay_type(S.ThreeLegTicket(legs=[det_spread, g1_total_over, g3_okc_ml]))
    assert mixed.startswith("MIXED") and "BOS @ DET" in mixed and "OKC @ SAS" in mixed


# --------------------------------------------------------------------------------------
# Review fixes: moneyline vs the opponent's spread; two event ids for one matchup
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ml_side", "ml_team", "spread_side", "spread_team", "spread_line"),
    [
        (SD.HOME, "DET", SD.AWAY, "BOS", "-3.5"),  # DET wins needs m >= 1; BOS -3.5 needs m <= -4
        (SD.AWAY, "BOS", SD.HOME, "DET", "-3.5"),  # BOS wins needs m <= -1; DET -3.5 needs m >= 4
        (SD.HOME, "DET", SD.AWAY, "BOS", "-0.5"),  # DET wins needs m >= 1; BOS -0.5 needs m <= -1
        (SD.HOME, "DET", SD.AWAY, "BOS", "0.5"),  # BOS +0.5 is BOS to win; DET ML is DET to win
        (SD.HOME, "DET", SD.AWAY, "BOS", "1"),  # DET by exactly 1 pushes BOS +1, it does not win it
        (SD.AWAY, "BOS", SD.HOME, "DET", "1"),  # BOS by exactly 1 pushes DET +1
        (SD.HOME, "DET", SD.AWAY, "BOS", "0"),  # pick'em: BOS +0 covers only when BOS wins
    ],
)
def test_moneyline_with_opponent_spread_that_cannot_both_win(
    g1, g2_total_under, ml_side, ml_team, spread_side, spread_team, spread_line
):
    ml = sel(g1, MT.MONEYLINE, ml_side, team=ml_team, odds="2.30", description=f"{ml_team} ML")
    spread = sel(
        g1,
        MT.SPREAD,
        spread_side,
        line=spread_line,
        team=spread_team,
        description=f"{spread_team} {spread_line}",
    )
    assert C.hard_rejections([ml, spread, g2_total_under]) == ["MUTUALLY_EXCLUSIVE_SELECTION"]
    assert C.hard_rejections([spread, ml, g2_total_under]) == ["MUTUALLY_EXCLUSIVE_SELECTION"]  # order-free
    report = C.check_correlation(S.ThreeLegTicket(legs=[ml, spread, g2_total_under]))
    f = flag(report, S.CorrelationType.MUTUALLY_EXCLUSIVE)
    assert f.severity == S.Severity.BLOCKING and f.leg_indexes == [0, 1]
    assert "MUTUALLY_EXCLUSIVE_SELECTION" in report.explanation
    assert report.joint_numeric_allowed is False


@pytest.mark.parametrize(
    ("ml_side", "ml_team", "spread_side", "spread_team", "spread_line"),
    [
        (SD.HOME, "DET", SD.AWAY, "BOS", "3.5"),  # DET by 1-3 wins both
        (SD.HOME, "DET", SD.AWAY, "BOS", "1.5"),  # DET by exactly 1 wins both
        (SD.HOME, "DET", SD.AWAY, "BOS", "2"),  # DET by exactly 1 wins both (2 would push)
        (SD.AWAY, "BOS", SD.HOME, "DET", "3.5"),  # BOS by 1-3 wins both
        (SD.AWAY, "BOS", SD.HOME, "DET", "2"),  # BOS by exactly 1 wins both
    ],
)
def test_moneyline_with_opponent_spread_that_leaves_a_middle_is_combinable(
    g1, g2_total_under, ml_side, ml_team, spread_side, spread_team, spread_line
):
    ml = sel(g1, MT.MONEYLINE, ml_side, team=ml_team, odds="2.30", description=f"{ml_team} ML")
    spread = sel(
        g1,
        MT.SPREAD,
        spread_side,
        line=spread_line,
        team=spread_team,
        description=f"{spread_team} +{spread_line}",
    )
    assert C.hard_rejections([ml, spread, g2_total_under]) == []
    report = C.check_correlation(S.ThreeLegTicket(legs=[ml, spread, g2_total_under]))
    assert S.CorrelationType.MUTUALLY_EXCLUSIVE not in flag_types(report)
    assert S.CorrelationType.TEAM_WIN_AND_SPREAD not in flag_types(report)  # opposite teams
    assert S.CorrelationType.SAME_GAME_UNQUANTIFIED in flag_types(report)  # still one game


def test_same_team_moneyline_and_spread_is_never_mutually_exclusive(g1, det_ml, g2_total_under):
    for line in ("-3.5", "-12.5", "3.5"):
        det_spread = sel(g1, MT.SPREAD, SD.HOME, line=line, team="DET", description=f"DET {line}")
        assert C.hard_rejections([det_ml, det_spread, g2_total_under]) == []
        report = C.check_correlation(S.ThreeLegTicket(legs=[det_ml, det_spread, g2_total_under]))
        assert S.CorrelationType.MUTUALLY_EXCLUSIVE not in flag_types(report)
        assert S.CorrelationType.TEAM_WIN_AND_SPREAD in flag_types(report)


def test_moneyline_and_opponent_spread_in_different_games_are_not_compared(g1, g2, det_ml, g3_okc_ml):
    phi_spread = sel(g2, MT.SPREAD, SD.AWAY, line="-3.5", team="PHI", description="PHI -3.5")
    assert C.hard_rejections([det_ml, phi_spread, g3_okc_ml]) == []
    report = C.check_correlation(S.ThreeLegTicket(legs=[det_ml, phi_spread, g3_okc_ml]))
    assert report.flags == [] and report.joint_numeric_allowed is True


def test_mixed_ticket_with_two_event_ids_for_one_matchup_returns_a_report():
    provider = make_event("BOS", "DET", event_id="oddsapi:abc123")
    manual = make_event("BOS", "DET", event_id="manual:bos-det")
    a = sel(provider, MT.SPREAD, SD.HOME, line="3.5", team="DET", description="DET +3.5")
    b = sel(provider, MT.TOTAL, SD.OVER, line="224.5", description="BOS/DET over 224.5")
    c = sel(manual, MT.MONEYLINE, SD.HOME, team="DET", odds="2.30", description="DET ML (manual)")
    ticket = S.ThreeLegTicket(legs=[a, b, c])
    assert ticket.parlay_type == S.ParlayType.MIXED

    text = C.describe_parlay_type(ticket)
    assert text.startswith("MIXED") and "oddsapi:abc123" in text and "manual:bos-det" in text
    assert "BOS @ DET" in text

    report = C.check_correlation(ticket)
    assert report.joint_numeric_allowed is False
    assert report.explanation.startswith("MIXED")
    assert report.weakest_assumption == C.WEAKEST_ASSUMPTION_SAME_GAME
    same_game = [f for f in report.flags if f.type == S.CorrelationType.SAME_GAME_UNQUANTIFIED]
    assert [f.leg_indexes for f in same_game] == [[0, 1], [0, 1, 2]]  # per event id, then per matchup
    assert all(f.severity == S.Severity.BLOCKING for f in same_game)
    assert "different event ids" in same_game[1].explanation


def test_multi_game_ticket_with_two_event_ids_for_one_matchup_blocks_numeric_joint(g2):
    provider = make_event("BOS", "DET", event_id="oddsapi:abc123")
    manual = make_event("BOS", "DET", event_id="manual:bos-det")
    a = sel(provider, MT.SPREAD, SD.HOME, line="3.5", team="DET", description="DET +3.5")
    c = sel(manual, MT.MONEYLINE, SD.HOME, team="DET", odds="2.30", description="DET ML (manual)")
    other = sel(g2, MT.TOTAL, SD.UNDER, line="219.5", description="PHI/NYK under 219.5")
    ticket = S.ThreeLegTicket(legs=[a, c, other])
    assert ticket.parlay_type == S.ParlayType.MULTI_GAME  # three distinct event ids

    assert C.hard_rejections(ticket) == []  # combinable, but not independent
    report = C.check_correlation(ticket)
    assert report.joint_numeric_allowed is False
    assert report.weakest_assumption == C.WEAKEST_ASSUMPTION_SAME_GAME
    f = flag(report, S.CorrelationType.SAME_GAME_UNQUANTIFIED)
    assert f.severity == S.Severity.BLOCKING and f.leg_indexes == [0, 1]
    assert report.explanation.startswith("MULTI_GAME by event id")
    assert "oddsapi:abc123" in report.explanation and "manual:bos-det" in report.explanation


def test_distinct_matchups_with_matching_short_names_are_not_confused(
    g1, det_spread, g2_total_under, g3_okc_ml
):
    # Sanity: three distinct matchups keep the multi-game path and the independence assumption.
    report = C.check_correlation(S.ThreeLegTicket(legs=[det_spread, g2_total_under, g3_okc_ml]))
    assert report.joint_numeric_allowed is True
    assert report.weakest_assumption == C.WEAKEST_ASSUMPTION_MULTI_GAME
    assert report.explanation.startswith("MULTI_GAME: three legs from three different games")
