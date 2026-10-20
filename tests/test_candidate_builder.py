"""Unit tests for candidate_builder: leg analysis and the bounded candidate search (FIXTURE data only)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from conftest import NOW, TEAMS, make_event, make_quote, make_selection, stamp

from hardrock_nba_parlay import candidate_builder as CB
from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.config import Settings


@pytest.fixture
def cfg(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path, database_url=f"sqlite:///{tmp_path / 'cb.db'}")


def ref_quotes(
    event: S.Event,
    market: S.MarketType,
    odds_a: str,
    odds_b: str,
    *,
    line: str | None = None,
    player: str | None = None,
    book: str = "pinnacle",
    source_ts=None,
) -> list[S.MarketQuote]:
    """Both sides of one market at one reference book (one snapshot)."""
    team_market = market in (S.MarketType.MONEYLINE, S.MarketType.SPREAD)
    side_a, side_b = (S.Side.HOME, S.Side.AWAY) if team_market else (S.Side.OVER, S.Side.UNDER)
    home, away = None, None
    if team_market:
        home = next(t for t in TEAMS.values() if t.team_id == event.home_team.team_id)
        away = next(t for t in TEAMS.values() if t.team_id == event.away_team.team_id)
    line_b = None
    if line is not None:
        line_b = str(-Decimal(line)) if market == S.MarketType.SPREAD else line
    return [
        make_quote(
            event, market, side_a, odds_a, line=line, player=player, team=home, book=book, source_ts=source_ts
        ),
        make_quote(
            event,
            market,
            side_b,
            odds_b,
            line=line_b,
            player=player,
            team=away,
            book=book,
            source_ts=source_ts,
        ),
    ]


def injury(
    event: S.Event, player: str, designation: S.InjuryDesignation, team: str | None = None
) -> S.InjuryContext:
    return S.InjuryContext(
        event_id=event.event_id,
        team_id=TEAMS[team].team_id if team else None,
        player_id=f"player:{player.lower().replace(' ', '-')}",
        player_name_raw=player,
        designation=designation,
        reason="Injury/Illness",
        report_timestamp_utc=NOW - timedelta(hours=1),
        stamp=stamp(source_ts=NOW - timedelta(hours=1)),
    )


# --------------------------------------------------------------------------------------
# analyze_leg
# --------------------------------------------------------------------------------------


def test_market_baseline_leg_is_usable_with_facts_and_interpretations(cfg, three_game_slate):
    e1 = three_game_slate[0]
    quote = make_quote(e1, S.MarketType.SPREAD, S.Side.HOME, "1.9091", line="3.5", team=TEAMS["DET"])
    sel = make_selection(quote, e1, "DET +3.5")
    refs = ref_quotes(e1, S.MarketType.SPREAD, "1.95", "1.87", line="3.5")
    analysis = CB.analyze_leg(sel, refs, [], NOW, cfg)
    assert analysis.decision == S.LegDecision.USABLE
    assert analysis.probability.state == S.ModelState.MARKET_BASELINE
    assert analysis.probability.value is not None and analysis.probability.reference_book == "pinnacle"
    assert analysis.price_value.edge_per_dollar is not None
    assert analysis.price_value.fair_decimal is not None
    # facts carry stamps; interpretations are plain text and kept apart
    assert len(analysis.facts) == 2 and all(f.stamp.data_mode == S.DataMode.FIXTURE for f in analysis.facts)
    assert any("edge" in text for text in analysis.interpretations)
    assert analysis.data_quality.checks["reference_complete"] is True
    assert analysis.data_quality.checks["injury_report_current"] is False  # no report supplied
    assert "INJURY_REPORT_MISSING" in analysis.reason_codes
    assert analysis.data_quality.grade == "B"
    assert analysis.analyzed_at_utc == NOW
    assert analysis.strongest_reason_against


def test_no_reference_means_value_unknown(cfg, three_game_slate):
    e1 = three_game_slate[0]
    sel = make_selection(make_quote(e1, S.MarketType.TOTAL, S.Side.OVER, "1.91", line="221.5"), e1)
    analysis = CB.analyze_leg(sel, [], [], NOW, cfg)
    assert analysis.decision == S.LegDecision.USABLE
    assert analysis.probability.state == S.ModelState.INSUFFICIENT_EVIDENCE
    assert analysis.probability.method == "REFERENCE_MISSING"
    assert "REFERENCE_MISSING" in analysis.reason_codes
    assert analysis.price_value.edge_per_dollar is None
    assert analysis.strongest_reason_against == "no benchmark for this line: value unknown"
    assert analysis.data_quality.checks["reference_complete"] is False


def test_line_mismatch_reference_gives_insufficient_evidence(cfg, three_game_slate):
    e1 = three_game_slate[0]
    sel = make_selection(make_quote(e1, S.MarketType.TOTAL, S.Side.OVER, "1.91", line="221.5"), e1)
    refs = ref_quotes(e1, S.MarketType.TOTAL, "1.91", "1.91", line="222.5")
    analysis = CB.analyze_leg(sel, refs, [], NOW, cfg)
    assert analysis.probability.value is None
    assert "LINE_MISMATCH" in analysis.reason_codes
    assert analysis.decision == S.LegDecision.USABLE


def test_reference_skew_downgrades_probability_but_not_decision(cfg, three_game_slate):
    e1 = three_game_slate[0]
    sel = make_selection(make_quote(e1, S.MarketType.MONEYLINE, S.Side.AWAY, "1.6667", team=TEAMS["BOS"]), e1)
    refs = ref_quotes(e1, S.MarketType.MONEYLINE, "2.60", "1.55", source_ts=NOW - timedelta(seconds=200))
    analysis = CB.analyze_leg(sel, refs, [], NOW, cfg)
    assert analysis.probability.state == S.ModelState.INSUFFICIENT_EVIDENCE
    assert analysis.probability.method == "TIMESTAMP_SKEW"
    assert analysis.probability.reference_book == "pinnacle"
    assert "TIMESTAMP_SKEW" in analysis.reason_codes
    assert analysis.decision == S.LegDecision.USABLE
    assert "not reliable" in analysis.strongest_reason_against
    assert analysis.data_quality.checks["reference_fresh"] is False


def test_reference_from_the_target_book_is_not_a_benchmark(cfg, three_game_slate):
    e1 = three_game_slate[0]
    sel = make_selection(make_quote(e1, S.MarketType.MONEYLINE, S.Side.AWAY, "1.6667", team=TEAMS["BOS"]), e1)
    refs = ref_quotes(e1, S.MarketType.MONEYLINE, "2.60", "1.55", book="hardrockbet_fl")
    analysis = CB.analyze_leg(sel, refs, [], NOW, cfg)
    assert analysis.probability.value is None
    assert analysis.probability.method == "REFERENCE_MISSING"
    assert "target book" in analysis.strongest_reason_against


def test_stale_quote_is_unusable_and_grade_d(cfg, three_game_slate):
    e1 = three_game_slate[0]
    quote = make_quote(
        e1,
        S.MarketType.MONEYLINE,
        S.Side.AWAY,
        "1.6667",
        team=TEAMS["BOS"],
        source_ts=NOW - timedelta(seconds=400),
    )
    sel = make_selection(quote, e1)
    analysis = CB.analyze_leg(sel, ref_quotes(e1, S.MarketType.MONEYLINE, "2.60", "1.55"), [], NOW, cfg)
    assert analysis.decision == S.LegDecision.UNUSABLE
    assert "QUOTE_STALE" in analysis.reason_codes
    assert analysis.data_quality.grade == "D"
    assert "old" in analysis.strongest_reason_against


def test_started_game_is_unusable(cfg):
    started = make_event("BOS", "DET", start=NOW - timedelta(minutes=5))
    sel = make_selection(make_quote(started, S.MarketType.TOTAL, S.Side.OVER, "1.91", line="221.5"), started)
    analysis = CB.analyze_leg(sel, [], [], NOW, cfg)
    assert analysis.decision == S.LegDecision.UNUSABLE
    assert "GAME_STARTED" in analysis.reason_codes
    assert "already started" in analysis.strongest_reason_against


def test_questionable_prop_player_waits_for_update(cfg, three_game_slate):
    e2 = three_game_slate[1]
    quote = make_quote(
        e2, S.MarketType.PLAYER_POINTS, S.Side.OVER, "1.87", line="24.5", player="Jalen Brunson"
    )
    sel = make_selection(quote, e2, "Jalen Brunson over 24.5 points")
    report = [injury(e2, "Jalen Brunson", S.InjuryDesignation.QUESTIONABLE, "NYK")]
    analysis = CB.analyze_leg(sel, [], report, NOW, cfg)
    assert analysis.decision == S.LegDecision.WAIT_FOR_UPDATE
    assert "INJURY_QUESTIONABLE_MATERIAL" in analysis.reason_codes
    assert "Jalen Brunson is Questionable" in analysis.strongest_reason_against
    assert analysis.injury and analysis.injury[0].material_to_selection is True
    assert any("injury report" in f.text for f in analysis.facts)


def test_out_prop_player_is_unusable(cfg, three_game_slate):
    e2 = three_game_slate[1]
    quote = make_quote(
        e2, S.MarketType.PLAYER_POINTS, S.Side.OVER, "1.87", line="24.5", player="Jalen Brunson"
    )
    sel = make_selection(quote, e2)
    analysis = CB.analyze_leg(
        sel, [], [injury(e2, "Jalen Brunson", S.InjuryDesignation.OUT, "NYK")], NOW, cfg
    )
    assert analysis.decision == S.LegDecision.UNUSABLE
    assert "INJURY_OUT" in analysis.reason_codes


def test_team_market_names_questionable_teammate_but_stays_usable(cfg, three_game_slate):
    e1 = three_game_slate[0]
    sel = make_selection(
        make_quote(e1, S.MarketType.SPREAD, S.Side.HOME, "1.9091", line="3.5", team=TEAMS["DET"]), e1
    )
    refs = ref_quotes(e1, S.MarketType.SPREAD, "1.91", "1.91", line="3.5")
    analysis = CB.analyze_leg(
        sel, refs, [injury(e1, "Cade Cunningham", S.InjuryDesignation.QUESTIONABLE, "DET")], NOW, cfg
    )
    assert analysis.decision == S.LegDecision.USABLE
    assert "INJURY_QUESTIONABLE_IMMATERIAL" in analysis.reason_codes
    assert analysis.strongest_reason_against.startswith("teammate Cade Cunningham is Questionable")


def test_negative_edge_is_the_strongest_reason_against(cfg, three_game_slate):
    e1 = three_game_slate[0]
    sel = make_selection(make_quote(e1, S.MarketType.TOTAL, S.Side.OVER, "1.80", line="221.5"), e1)
    refs = ref_quotes(e1, S.MarketType.TOTAL, "1.91", "1.91", line="221.5")
    analysis = CB.analyze_leg(
        sel, refs, [injury(e1, "Someone Else", S.InjuryDesignation.AVAILABLE, "DET")], NOW, cfg
    )
    assert analysis.price_value.edge_per_dollar is not None and analysis.price_value.edge_per_dollar < 0
    assert "below the benchmark" in analysis.strongest_reason_against


def test_alternate_line_reason_when_nothing_else_is_wrong(cfg, three_game_slate):
    e2 = three_game_slate[1]
    quote = make_quote(
        e2,
        S.MarketType.PLAYER_POINTS,
        S.Side.OVER,
        "3.00",
        line="29.5",
        player="Jalen Brunson",
        is_alternate=True,
    )
    sel = make_selection(quote, e2)
    refs = ref_quotes(e2, S.MarketType.PLAYER_POINTS, "3.20", "1.35", line="29.5", player="Jalen Brunson")
    analysis = CB.analyze_leg(
        sel, refs, [injury(e2, "Other Guy", S.InjuryDesignation.AVAILABLE, "NYK")], NOW, cfg
    )
    assert analysis.price_value.edge_per_dollar is not None
    if analysis.price_value.edge_per_dollar >= 0:
        assert "alternate line" in analysis.strongest_reason_against


def test_unsupported_period_is_blocking(cfg, three_game_slate):
    e1 = three_game_slate[0]
    quote = make_quote(e1, S.MarketType.TOTAL, S.Side.OVER, "1.91", line="110.5").model_copy(
        update={"period": S.Period.FIRST_HALF}
    )
    sel = S.Selection(
        selection_id=S.compute_selection_id(quote), quote=quote, event=e1, description="1H over"
    )
    analysis = CB.analyze_leg(sel, [], [], NOW, cfg)
    assert analysis.decision == S.LegDecision.UNUSABLE
    assert "PERIOD_UNSUPPORTED" in analysis.reason_codes
    assert analysis.data_quality.checks["rules_profile_known"] is False


# --------------------------------------------------------------------------------------
# build_candidates
# --------------------------------------------------------------------------------------


def slate_legs(events: list[S.Event], *, source_ts=None) -> tuple[list[S.Selection], list[S.MarketQuote]]:
    """Six team legs per event at hardrockbet_fl plus pinnacle references at the same lines."""
    selections: list[S.Selection] = []
    refs: list[S.MarketQuote] = []
    for i, e in enumerate(events):
        home = next(t for t in TEAMS.values() if t.team_id == e.home_team.team_id)
        away = next(t for t in TEAMS.values() if t.team_id == e.away_team.team_id)
        line = str(Decimal("3.5") + i)
        total = str(Decimal("220.5") + i)
        quotes = [
            make_quote(e, S.MarketType.MONEYLINE, S.Side.HOME, "2.70", team=home, source_ts=source_ts),
            make_quote(e, S.MarketType.MONEYLINE, S.Side.AWAY, "1.48", team=away, source_ts=source_ts),
            make_quote(
                e, S.MarketType.SPREAD, S.Side.HOME, "1.91", line=line, team=home, source_ts=source_ts
            ),
            make_quote(
                e,
                S.MarketType.SPREAD,
                S.Side.AWAY,
                "1.91",
                line=str(-Decimal(line)),
                team=away,
                source_ts=source_ts,
            ),
            make_quote(e, S.MarketType.TOTAL, S.Side.OVER, "1.91", line=total, source_ts=source_ts),
            make_quote(e, S.MarketType.TOTAL, S.Side.UNDER, "1.91", line=total, source_ts=source_ts),
        ]
        selections += [make_selection(q, e) for q in quotes]
        refs += ref_quotes(e, S.MarketType.MONEYLINE, "2.78", "1.49")
        refs += ref_quotes(e, S.MarketType.SPREAD, "1.93", "1.89", line=line)
        refs += ref_quotes(e, S.MarketType.TOTAL, "1.92", "1.90", line=total)
    return selections, refs


def test_auto_builds_multi_game_candidates_one_leg_per_game(cfg, three_game_slate):
    selections, refs = slate_legs(three_game_slate)
    stats = CB.SearchStats()
    cands = CB.build_candidates(selections, refs, [], "auto", 3, NOW, cfg, "u1", Decimal("10"), stats=stats)
    assert len(cands) == 3
    for c in cands:
        assert c.parlay_type == S.ParlayType.MULTI_GAME
        assert len(set(c.ticket.event_ids)) == 3
        assert c.state == S.CandidateState.NEEDS_BOOK_QUOTE
        assert c.p_joint is not None and c.model_state == S.ModelState.MARKET_BASELINE
        assert c.ev_per_dollar is not None
        assert c.payout.combined_source == "INDICATIVE_MULTIPLIED"
        assert c.expires_at_utc == min(leg.event.commence_time_utc for leg in c.ticket.legs)
        assert c.ranking["note"] == CB.RANKING_NOTE and c.ranking["evidence_tier"] == "A"
        assert len(c.rechecks_required) == 4
        assert "indicative" in c.rationale
        assert c.data_mode == S.DataMode.FIXTURE
        assert c.user_id == "u1" and c.ai_disclosure == S.AI_DISCLOSURE
    assert (
        stats.mode == "MULTI_GAME"
        and stats.legs_usable == 18
        and stats.combinations_evaluated <= CB.MAX_COMBINATIONS
    )
    # best first: sum_edge never increases down the list
    edges = [Decimal(c.ranking["sum_edge"]) for c in cands]
    assert edges == sorted(edges, reverse=True)


def test_stale_legs_produce_no_candidates(cfg, three_game_slate):
    selections, refs = slate_legs(three_game_slate, source_ts=NOW - timedelta(seconds=600))
    stats = CB.SearchStats()
    assert CB.build_candidates(selections, refs, [], "auto", 3, NOW, cfg, "u1", stats=stats) == []
    assert stats.legs_usable == 0


def test_auto_with_two_games_gives_qualitative_tickets_only(cfg, three_game_slate):
    selections, refs = slate_legs(three_game_slate[:2])
    stats = CB.SearchStats()
    cands = CB.build_candidates(selections, refs, [], "auto", 3, NOW, cfg, "u1", stats=stats)
    assert cands and stats.mode == "MIXED/SAME_GAME"
    for c in cands:
        assert c.parlay_type in (S.ParlayType.MIXED, S.ParlayType.SAME_GAME)
        assert c.p_joint is None and c.ev_per_dollar is None
        assert c.model_state == S.ModelState.INSUFFICIENT_EVIDENCE
        assert {"SAME_GAME_CORRELATION", "JOINT_PROBABILITY_UNAVAILABLE", "EV_UNAVAILABLE"} <= set(
            c.reason_codes
        )
        assert any(f.type == S.CorrelationType.SAME_GAME_UNQUANTIFIED for f in c.correlation.flags)
        assert c.correlation.joint_numeric_allowed is False
        assert "not called value" in c.rationale


def test_multi_game_request_never_falls_back(cfg, three_game_slate):
    selections, refs = slate_legs(three_game_slate[:2])
    assert CB.build_candidates(selections, refs, [], "multi_game", 3, NOW, cfg, "u1") == []


def test_same_game_request(cfg, three_game_slate):
    selections, refs = slate_legs(three_game_slate)
    cands = CB.build_candidates(selections, refs, [], "same_game", 2, NOW, cfg, "u1")
    assert len(cands) == 2 and all(c.parlay_type == S.ParlayType.SAME_GAME for c in cands)
    assert all(c.p_joint is None for c in cands)


def test_without_references_candidates_say_value_unknown(cfg, three_game_slate):
    selections, _ = slate_legs(three_game_slate)
    cands = CB.build_candidates(selections, [], [], "auto", 2, NOW, cfg, "u1")
    assert len(cands) == 2
    for c in cands:
        assert c.p_joint is None and c.model_state == S.ModelState.INSUFFICIENT_EVIDENCE
        assert c.ranking["evidence_tier"] == "D" and c.ranking["legs_with_reference"] == "0"
        assert "unknown" in c.rationale


def test_hard_rejections_are_filtered(cfg, three_game_slate):
    # Only one game with both sides of one total: the single same-game combo is contradictory.
    e1 = three_game_slate[0]
    quotes = [
        make_quote(e1, S.MarketType.TOTAL, S.Side.OVER, "1.91", line="221.5"),
        make_quote(e1, S.MarketType.TOTAL, S.Side.UNDER, "1.91", line="221.5"),
        make_quote(e1, S.MarketType.MONEYLINE, S.Side.HOME, "2.70", team=TEAMS["DET"]),
    ]
    selections = [make_selection(q, e1) for q in quotes]
    stats = CB.SearchStats()
    assert CB.build_candidates(selections, [], [], "same_game", 3, NOW, cfg, "u1", stats=stats) == []
    assert stats.combinations_rejected == 1


def test_search_is_bounded_to_24_legs(cfg, three_game_slate):
    selections, refs = slate_legs(three_game_slate)
    extra: list[S.Selection] = []
    for e in three_game_slate:
        for j in range(4):
            line = str(Decimal("200.5") + j)
            extra.append(
                make_selection(
                    make_quote(e, S.MarketType.TOTAL, S.Side.OVER, "2.10", line=line, is_alternate=True), e
                )
            )
    stats = CB.SearchStats()
    cands = CB.build_candidates(selections + extra, refs, [], "auto", 3, NOW, cfg, "u1", stats=stats)
    assert stats.legs_usable == 30 and stats.legs_searched == CB.MAX_LEGS_SEARCHED
    assert stats.combinations_evaluated <= CB.MAX_COMBINATIONS
    assert len(cands) == 3


def test_invalid_parlay_type_rejected(cfg, three_game_slate):
    selections, refs = slate_legs(three_game_slate)
    with pytest.raises(ValueError, match="INVALID_INPUT"):
        CB.build_candidates(selections, refs, [], "teaser", 3, NOW, cfg, "u1")


def test_candidate_data_mode_prefers_fixture_then_manual(cfg, three_game_slate):
    """FIXTURE beats MANUAL_INPUT beats LIVE_PROVIDER over the leg quotes. The slate and the benchmarks count
    too: a quote on a fixture event, or priced against a fixture benchmark, is fixture data (it never reaches
    a real ledger). The conftest events are FIXTURE-stamped, so the live case needs a live-stamped event."""
    e1 = three_game_slate[0].model_copy(update={"stamp": stamp(mode=S.DataMode.LIVE_PROVIDER)})
    live = make_quote(e1, S.MarketType.TOTAL, S.Side.OVER, "1.91", line="221.5").model_copy(
        update={"stamp": stamp(mode=S.DataMode.LIVE_PROVIDER)}
    )
    manual = make_quote(e1, S.MarketType.TOTAL, S.Side.UNDER, "1.91", line="221.5").model_copy(
        update={"stamp": stamp(source="user", mode=S.DataMode.MANUAL_INPUT)}
    )
    fixture = make_quote(e1, S.MarketType.MONEYLINE, S.Side.HOME, "2.70", team=TEAMS["DET"])
    legs = [make_selection(q, e1) for q in (live, manual, fixture)]
    assert CB.candidate_data_mode(legs) == S.DataMode.FIXTURE
    assert CB.candidate_data_mode(legs[:2]) == S.DataMode.MANUAL_INPUT
    assert CB.candidate_data_mode(legs[:1]) == S.DataMode.LIVE_PROVIDER
    # the same live quote matched to the FIXTURE slate is fixture data
    assert CB.candidate_data_mode([make_selection(live, three_game_slate[0])]) == S.DataMode.FIXTURE
    # a live quote on a live event priced against a FIXTURE benchmark is fixture data too
    refs = ref_quotes(e1, S.MarketType.TOTAL, "1.91", "1.91", line="221.5")
    analysis = CB.analyze_leg(legs[0], refs, [], NOW, cfg)
    assert analysis.probability.reference_stamp is not None
    assert analysis.probability.reference_stamp.data_mode == S.DataMode.FIXTURE
    assert CB.candidate_data_mode(legs[:1], [analysis]) == S.DataMode.FIXTURE
    assert CB.candidate_data_mode(legs[:1], {analysis.selection_id: analysis}) == S.DataMode.FIXTURE
