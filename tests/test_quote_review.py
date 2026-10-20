"""Unit tests for quote_review: book-quote review, revalidation, and user-ticket analysis (FIXTURE data)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from conftest import NOW, TEAMS, make_event, make_quote, make_selection, stamp
from test_candidate_builder import injury, ref_quotes

from hardrock_nba_parlay import candidate_builder as CB
from hardrock_nba_parlay import correlation
from hardrock_nba_parlay import quote_review as QR
from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.config import Settings
from hardrock_nba_parlay.errors import InvalidInput


@pytest.fixture
def cfg(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path, database_url=f"sqlite:///{tmp_path / 'qr.db'}")


def three_refs(slate: list[S.Event]) -> list[S.MarketQuote]:
    e1, e2, e3 = slate
    refs: list[S.MarketQuote] = []
    refs += ref_quotes(e1, S.MarketType.SPREAD, "1.93", "1.89", line="3.5")
    refs += ref_quotes(e2, S.MarketType.TOTAL, "1.92", "1.90", line="224.5")
    refs += ref_quotes(e3, S.MarketType.MONEYLINE, "2.45", "1.62")
    return refs


def build(cfg, legs: list[S.Selection], refs, injuries=(), *, now=NOW) -> S.Candidate:
    analyses = {s.selection_id: CB.analyze_leg(s, refs, list(injuries), now, cfg) for s in legs}
    ticket = S.ThreeLegTicket(legs=legs)
    report = correlation.check_correlation(ticket)
    return CB.make_candidate(ticket, analyses, report, now, cfg, "u1", Decimal("10"))


@pytest.fixture
def candidate(cfg, three_game_slate, three_multi_game_legs) -> S.Candidate:
    return build(cfg, three_multi_game_legs, three_refs(three_game_slate))


def quote(**kw) -> S.ManualQuoteInput:
    base = {"combined_decimal": Decimal("5.50"), "user_confirmed": True}
    base.update(kw)
    return S.ManualQuoteInput(**base)


# --------------------------------------------------------------------------------------
# review_book_quote
# --------------------------------------------------------------------------------------


def test_missing_combined_price(candidate):
    out, codes = QR.review_book_quote(candidate, S.ManualQuoteInput(user_confirmed=True), NOW)
    assert codes == ["QUOTE_FIELDS_MISSING"] and out is candidate


def test_unconfirmed_quote_is_stored_but_not_applied(candidate, cfg):
    out, codes = QR.review_book_quote(candidate, quote(user_confirmed=False), NOW, cfg)
    assert "QUOTE_UNCONFIRMED" in codes
    assert out.state == S.CandidateState.NEEDS_BOOK_QUOTE
    assert out.book_quote is not None and out.book_quote.confirmed_by_user is False
    assert out.payout.combined_source == "INDICATIVE_MULTIPLIED"
    assert "QUOTE_UNCONFIRMED" in out.reason_codes


def test_conflicting_slip_legs(candidate, cfg):
    shown = ["Lakers -3.5", "Clippers ML", "Celtics over 300.5"]
    out, codes = QR.review_book_quote(candidate, quote(legs_as_shown=shown), NOW, cfg)
    assert "QUOTE_CONFLICTS_WITH_LEGS" in codes
    assert out.state == S.CandidateState.NEEDS_BOOK_QUOTE
    assert out.book_quote is not None and "legs_as_shown" in out.book_quote.unresolved_fields
    assert out.book_quote.legs_as_shown == shown
    assert out.payout.combined_source == "INDICATIVE_MULTIPLIED"


def test_slip_legs_match_tolerant_formatting(candidate, cfg):
    shown = ["Pistons +3.5 (-110)", "PHI @ NYK Over 224.5 Total Points", "Thunder ML"]
    indexes, conflicts = QR.match_legs_as_shown(shown, candidate.ticket)
    assert conflicts == [] and indexes == [0, 1, 2]
    out, codes = QR.review_book_quote(candidate, quote(legs_as_shown=shown), NOW, cfg)
    assert out.state == S.CandidateState.READY_FOR_USER_REVIEW and "QUOTE_REPLACES_INDICATIVE" in codes


def test_wrong_leg_count_on_slip_conflicts(candidate):
    _indexes, conflicts = QR.match_legs_as_shown(["Pistons +3.5", "Thunder ML"], candidate.ticket)
    assert conflicts


def test_confirmed_quote_replaces_indicative_and_recomputes_ev(candidate, cfg):
    assert candidate.p_joint is not None
    out, codes = QR.review_book_quote(
        candidate,
        quote(stake_shown_usd=Decimal("10"), payout_shown_usd=Decimal("55"), payout_includes_stake=True),
        NOW,
        cfg,
    )
    assert codes == ["QUOTE_REPLACES_INDICATIVE"]
    assert out.state == S.CandidateState.READY_FOR_USER_REVIEW
    assert out.payout.combined_source == "BOOK_QUOTE" and out.payout.combined_decimal == Decimal("5.5000")
    assert out.payout.gross_return_usd == Decimal("55.00") and out.payout.net_profit_usd == Decimal("45.00")
    assert out.ev_per_dollar == (candidate.p_joint * Decimal("5.5") - 1).quantize(Decimal("0.000001"))
    assert out.book_quote is not None and out.book_quote.unresolved_fields == []
    assert "QUOTE_REPLACES_INDICATIVE" in out.reason_codes
    assert "replaces" in out.rationale
    assert (
        out.updated_at_utc == NOW and candidate.state == S.CandidateState.NEEDS_BOOK_QUOTE
    )  # input untouched


def test_american_only_quote_is_converted(candidate, cfg):
    out, codes = QR.review_book_quote(
        candidate, quote(combined_decimal=None, combined_american=450), NOW, cfg
    )
    assert out.book_quote is not None and out.book_quote.combined_decimal == Decimal("5.5000")
    assert "QUOTE_REPLACES_INDICATIVE" in codes


def test_disagreeing_american_and_decimal_is_ambiguous(candidate, cfg):
    out, codes = QR.review_book_quote(candidate, quote(combined_american=-300), NOW, cfg)
    assert "QUOTE_SIGN_AMBIGUOUS" in codes and out.state == S.CandidateState.NEEDS_BOOK_QUOTE
    assert out.book_quote is not None and "combined_odds" in out.book_quote.unresolved_fields


def test_payout_convention_unknown_is_an_unresolved_field(candidate, cfg):
    out, _ = QR.review_book_quote(candidate, quote(payout_includes_stake=None), NOW, cfg)
    assert out.book_quote is not None and "payout_includes_stake" in out.book_quote.unresolved_fields
    assert out.state == S.CandidateState.READY_FOR_USER_REVIEW


def test_inconsistent_payout_is_flagged(candidate, cfg):
    out, _ = QR.review_book_quote(
        candidate,
        quote(stake_shown_usd=Decimal("10"), payout_shown_usd=Decimal("99"), payout_includes_stake=True),
        NOW,
        cfg,
    )
    assert out.book_quote is not None and "payout_shown_usd" in out.book_quote.unresolved_fields


def test_stale_inputs_keep_needs_book_quote(candidate, cfg):
    later = NOW + timedelta(seconds=cfg.max_odds_age_seconds + 1)
    out, codes = QR.review_book_quote(candidate, quote(), later, cfg)
    assert "QUOTE_STALE" in codes and out.state == S.CandidateState.NEEDS_BOOK_QUOTE
    assert "refresh_parlay" in out.rationale
    assert out.payout.combined_source == "BOOK_QUOTE"


def test_started_candidate_expires_on_import(candidate, cfg):
    at_tip = candidate.expires_at_utc
    out, codes = QR.review_book_quote(candidate, quote(), at_tip, cfg, max_odds_age_seconds=10**9)
    assert out.state == S.CandidateState.EXPIRED and "GAME_STARTED" in codes


def test_waiting_leg_blocks_ready(cfg, three_game_slate):
    e1, e2, e3 = three_game_slate
    prop = make_quote(
        e2, S.MarketType.PLAYER_POINTS, S.Side.OVER, "1.87", line="24.5", player="Jalen Brunson"
    )
    legs = [
        make_selection(
            make_quote(e1, S.MarketType.SPREAD, S.Side.HOME, "1.9091", line="3.5", team=TEAMS["DET"]), e1
        ),
        make_selection(prop, e2),
        make_selection(make_quote(e3, S.MarketType.MONEYLINE, S.Side.AWAY, "1.6667", team=TEAMS["OKC"]), e3),
    ]
    cand = build(
        cfg,
        legs,
        three_refs(three_game_slate),
        [injury(e2, "Jalen Brunson", S.InjuryDesignation.QUESTIONABLE, "NYK")],
    )
    assert cand.leg_analyses[1].decision == S.LegDecision.WAIT_FOR_UPDATE
    out, codes = QR.review_book_quote(cand, quote(), NOW, cfg)
    assert out.state == S.CandidateState.NEEDS_BOOK_QUOTE and "WAIT_FOR_UPDATE" in codes


# --------------------------------------------------------------------------------------
# revalidate
# --------------------------------------------------------------------------------------


def ready(candidate, cfg) -> S.Candidate:
    out, _ = QR.review_book_quote(candidate, quote(), NOW, cfg)
    assert out.state == S.CandidateState.READY_FOR_USER_REVIEW
    return out


def test_revalidate_unchanged_keeps_ready_and_refreshes_snapshot(
    candidate, cfg, three_game_slate, three_multi_game_legs
):
    cand = ready(candidate, cfg)
    cand = QR.rebuild_candidate(cand, ranking={**cand.ranking, "reservation_id": "rsv_x"})
    later = NOW + timedelta(seconds=90)
    fresh = [
        make_selection(leg.quote.model_copy(update={"stamp": stamp(at=later)}), leg.event, leg.description)
        for leg in three_multi_game_legs
    ]
    fresh_refs = [q.model_copy(update={"stamp": stamp(at=later)}) for q in three_refs(three_game_slate)]
    out = QR.revalidate(cand, fresh, fresh_refs, [], later, cfg)
    assert out.state == S.CandidateState.READY_FOR_USER_REVIEW
    assert out.inputs_snapshot_utc == later and out.created_at_utc == NOW
    assert out.payout.combined_source == "BOOK_QUOTE" and out.ev_per_dollar is not None
    assert out.ranking["reservation_id"] == "rsv_x"
    assert out.book_quote is not None and out.book_quote.confirmed_by_user is True
    assert "Revalidated" in out.rationale


def test_revalidate_restores_ready_after_stale_import(
    candidate, cfg, three_game_slate, three_multi_game_legs
):
    later = NOW + timedelta(seconds=400)
    stale, codes = QR.review_book_quote(candidate, quote(), later, cfg)
    assert stale.state == S.CandidateState.NEEDS_BOOK_QUOTE and "QUOTE_STALE" in codes
    fresh = [
        make_selection(leg.quote.model_copy(update={"stamp": stamp(at=later)}), leg.event, leg.description)
        for leg in three_multi_game_legs
    ]
    fresh_refs = [q.model_copy(update={"stamp": stamp(at=later)}) for q in three_refs(three_game_slate)]
    out = QR.revalidate(stale, fresh, fresh_refs, [], later, cfg)
    assert out.state == S.CandidateState.READY_FOR_USER_REVIEW
    assert "QUOTE_STALE" not in out.reason_codes


def test_revalidate_price_change_requires_new_quote(candidate, cfg, three_game_slate, three_multi_game_legs):
    cand = ready(candidate, cfg)
    fresh = list(three_multi_game_legs)
    moved = fresh[2].quote.model_copy(update={"odds_decimal": Decimal("1.75"), "stamp": stamp()})
    fresh[2] = make_selection(moved, fresh[2].event, fresh[2].description)
    out = QR.revalidate(cand, fresh, three_refs(three_game_slate), [], NOW, cfg)
    assert out.state == S.CandidateState.NEEDS_BOOK_QUOTE
    assert QR.PRICE_CHANGED_REASON in out.rationale
    assert out.book_quote is not None
    assert out.book_quote.confirmed_by_user is False and "price_changed" in out.book_quote.unresolved_fields
    assert out.ticket.legs[2].quote.odds_decimal == Decimal("1.75")
    assert out.payout.combined_source == "INDICATIVE_MULTIPLIED"


def test_revalidate_line_move_is_a_change(candidate, cfg, three_game_slate, three_multi_game_legs):
    cand = ready(candidate, cfg)
    fresh = list(three_multi_game_legs)
    moved = fresh[0].quote.model_copy(update={"line": Decimal("4.5"), "stamp": stamp()})
    fresh[0] = make_selection(moved, fresh[0].event)
    out = QR.revalidate(cand, fresh, three_refs(three_game_slate), [], NOW, cfg)
    assert out.state == S.CandidateState.NEEDS_BOOK_QUOTE and QR.PRICE_CHANGED_REASON in out.rationale
    assert out.ticket.legs[0].quote.line == Decimal("4.5")


def test_revalidate_missing_quote_rejects_market_suspended(
    candidate, cfg, three_game_slate, three_multi_game_legs
):
    cand = ready(candidate, cfg)
    out = QR.revalidate(cand, three_multi_game_legs[:2], three_refs(three_game_slate), [], NOW, cfg)
    assert out.state == S.CandidateState.REJECTED and "MARKET_SUSPENDED" in out.reason_codes


def test_revalidate_started_game_expires(candidate, cfg, three_game_slate, three_multi_game_legs):
    cand = ready(candidate, cfg)
    tip = three_game_slate[0].commence_time_utc + timedelta(seconds=1)
    fresh = [
        make_selection(leg.quote.model_copy(update={"stamp": stamp(at=tip)}), leg.event, leg.description)
        for leg in three_multi_game_legs
    ]
    out = QR.revalidate(cand, fresh, [], [], tip, cfg)
    assert out.state == S.CandidateState.EXPIRED and "GAME_STARTED" in out.reason_codes


def test_revalidate_postponed_game_rejects(candidate, cfg, three_multi_game_legs):
    cand = ready(candidate, cfg)
    postponed = three_multi_game_legs[0].event.model_copy(update={"status": S.EventStatus.POSTPONED})
    fresh = list(three_multi_game_legs)
    fresh[0] = make_selection(fresh[0].quote, postponed, fresh[0].description)
    out = QR.revalidate(cand, fresh, [], [], NOW, cfg)
    assert out.state == S.CandidateState.REJECTED and "GAME_POSTPONED" in out.reason_codes


def test_revalidate_injury_out_rejects_and_questionable_waits(cfg, three_game_slate):
    e1, e2, e3 = three_game_slate
    prop = make_quote(
        e2, S.MarketType.PLAYER_POINTS, S.Side.OVER, "1.87", line="24.5", player="Jalen Brunson"
    )
    legs = [
        make_selection(
            make_quote(e1, S.MarketType.SPREAD, S.Side.HOME, "1.9091", line="3.5", team=TEAMS["DET"]), e1
        ),
        make_selection(prop, e2),
        make_selection(make_quote(e3, S.MarketType.MONEYLINE, S.Side.AWAY, "1.6667", team=TEAMS["OKC"]), e3),
    ]
    refs = three_refs(three_game_slate)
    cand = ready(build(cfg, legs, refs), cfg)
    out = QR.revalidate(
        cand, legs, refs, [injury(e2, "Jalen Brunson", S.InjuryDesignation.OUT, "NYK")], NOW, cfg
    )
    assert out.state == S.CandidateState.REJECTED and "INJURY_OUT" in out.reason_codes
    waiting = QR.revalidate(
        cand, legs, refs, [injury(e2, "Jalen Brunson", S.InjuryDesignation.QUESTIONABLE, "NYK")], NOW, cfg
    )
    assert waiting.state == S.CandidateState.NEEDS_BOOK_QUOTE
    assert {"WAIT_FOR_UPDATE", "INJURY_QUESTIONABLE_MATERIAL"} <= set(waiting.reason_codes)
    assert waiting.book_quote is not None and waiting.book_quote.confirmed_by_user is True


def test_revalidate_leaves_placed_candidate_alone(candidate, cfg, three_multi_game_legs):
    placed = QR.rebuild_candidate(candidate, state=S.CandidateState.USER_CONFIRMED_PLACED)
    assert QR.revalidate(placed, [], [], [], NOW, cfg) is placed


# --------------------------------------------------------------------------------------
# analyze_user_ticket
# --------------------------------------------------------------------------------------


def manual(
    game: str,
    market: S.MarketType,
    side: S.Side,
    odds: int,
    line: str | None = None,
    player: str | None = None,
    **kw,
):
    return S.ManualSelectionInput(
        game=game,
        market=market,
        side=side,
        line=Decimal(line) if line else None,
        player_name=player,
        odds_american=odds,
        **kw,
    )


def as_live(items):
    """Re-stamp conftest (FIXTURE) events or quotes as LIVE_PROVIDER data."""
    return [
        item.model_copy(
            update={"stamp": item.stamp.model_copy(update={"data_mode": S.DataMode.LIVE_PROVIDER})}
        )
        for item in items
    ]


def test_user_ticket_multi_game(cfg, three_game_slate):
    """Typed legs matched to a LIVE slate and priced against LIVE benchmarks are MANUAL_INPUT; the same typed
    legs matched to the FIXTURE slate are FIXTURE data (the conftest slate is fixture-stamped)."""
    inputs = [
        manual("BOS@DET", S.MarketType.SPREAD, S.Side.HOME, -110, "3.5"),
        manual("PHI@NYK", S.MarketType.TOTAL, S.Side.OVER, -110, "224.5"),
        manual("OKC@SAS", S.MarketType.MONEYLINE, S.Side.AWAY, -150),
    ]
    slate, refs = as_live(three_game_slate), as_live(three_refs(three_game_slate))
    cand = QR.analyze_user_ticket(inputs, None, slate, refs, [], NOW, cfg, "u1")
    assert cand.parlay_type == S.ParlayType.MULTI_GAME and cand.data_mode == S.DataMode.MANUAL_INPUT
    assert cand.p_joint is not None and cand.state == S.CandidateState.NEEDS_BOOK_QUOTE
    assert all(a.decision == S.LegDecision.USABLE for a in cand.leg_analyses)
    assert all("SOURCE_TIMESTAMP_UNKNOWN" in a.reason_codes for a in cand.leg_analyses)
    on_fixture = QR.analyze_user_ticket(
        inputs, None, three_game_slate, three_refs(three_game_slate), [], NOW, cfg, "u1"
    )
    assert on_fixture.data_mode == S.DataMode.FIXTURE and on_fixture.p_joint is not None


def test_user_ticket_same_game_is_qualitative(cfg, three_game_slate):
    inputs = [
        manual("BOS@DET", S.MarketType.SPREAD, S.Side.HOME, -110, "3.5"),
        manual("BOS@DET", S.MarketType.TOTAL, S.Side.OVER, -110, "221.5"),
        manual("BOS@DET", S.MarketType.PLAYER_ASSISTS, S.Side.OVER, -110, "8.5", "Cade Cunningham"),
    ]
    cand = QR.analyze_user_ticket(inputs, None, three_game_slate, [], [], NOW, cfg, "u1")
    assert cand.parlay_type == S.ParlayType.SAME_GAME
    assert cand.p_joint is None and cand.ev_per_dollar is None
    assert cand.model_state == S.ModelState.INSUFFICIENT_EVIDENCE
    assert "not called value" in cand.rationale and "not multiplied" in cand.rationale
    assert "JOINT_PROBABILITY_UNAVAILABLE" in cand.reason_codes
    assert cand.correlation.joint_numeric_allowed is False


def test_user_ticket_with_combined_quote(cfg, three_game_slate):
    inputs = [
        manual("BOS@DET", S.MarketType.SPREAD, S.Side.HOME, -110, "3.5"),
        manual("PHI@NYK", S.MarketType.TOTAL, S.Side.OVER, -110, "224.5"),
        manual("OKC@SAS", S.MarketType.MONEYLINE, S.Side.AWAY, -150),
    ]
    cand = QR.analyze_user_ticket(
        inputs,
        quote(combined_decimal=Decimal("6.10")),
        three_game_slate,
        three_refs(three_game_slate),
        [],
        NOW,
        cfg,
        "u1",
    )
    assert cand.book_quote is not None and cand.payout.combined_source == "BOOK_QUOTE"
    assert cand.state == S.CandidateState.READY_FOR_USER_REVIEW
    with pytest.raises(InvalidInput) as exc:
        QR.analyze_user_ticket(
            inputs, S.ManualQuoteInput(user_confirmed=True), three_game_slate, [], [], NOW, cfg, "u1"
        )
    assert exc.value.reason_codes == ["QUOTE_FIELDS_MISSING"]


@pytest.mark.parametrize(
    ("inputs", "code"),
    [
        (
            [
                manual("BOS@DET", S.MarketType.SPREAD, S.Side.HOME, -110, "3.5"),
                manual("PHI@NYK", S.MarketType.TOTAL, S.Side.OVER, -110, "224.5"),
            ],
            "NOT_THREE_LEGS",
        ),
        (
            [
                manual("BOS@DET", S.MarketType.SPREAD, S.Side.HOME, -110, "3.5"),
                manual("BOS@DET", S.MarketType.SPREAD, S.Side.HOME, -110, "3.5"),
                manual("OKC@SAS", S.MarketType.MONEYLINE, S.Side.AWAY, -150),
            ],
            "DUPLICATE_SELECTION",
        ),
        (
            [
                manual("BOS@DET", S.MarketType.TOTAL, S.Side.OVER, -110, "221.5"),
                manual("BOS@DET", S.MarketType.TOTAL, S.Side.UNDER, -110, "221.5"),
                manual("OKC@SAS", S.MarketType.MONEYLINE, S.Side.AWAY, -150),
            ],
            "CONTRADICTORY_SELECTION",
        ),
        (
            [
                manual("BOS@DET", S.MarketType.SPREAD, S.Side.HOME, -110, "3.5", book="draftkings"),
                manual("PHI@NYK", S.MarketType.TOTAL, S.Side.OVER, -110, "224.5"),
                manual("OKC@SAS", S.MarketType.MONEYLINE, S.Side.AWAY, -150),
            ],
            "WRONG_BOOK",
        ),
        (
            [
                manual("MIA@ORL", S.MarketType.SPREAD, S.Side.HOME, -110, "3.5"),
                manual("PHI@NYK", S.MarketType.TOTAL, S.Side.OVER, -110, "224.5"),
                manual("OKC@SAS", S.MarketType.MONEYLINE, S.Side.AWAY, -150),
            ],
            "EVENT_UNMATCHED",
        ),
    ],
)
def test_user_ticket_rejections(cfg, three_game_slate, inputs, code):
    with pytest.raises(InvalidInput) as exc:
        QR.analyze_user_ticket(inputs, None, three_game_slate, [], [], NOW, cfg, "u1")
    assert code in exc.value.reason_codes


def test_user_ticket_questionable_prop_waits(cfg, three_game_slate):
    e1 = three_game_slate[0]
    inputs = [
        manual("BOS@DET", S.MarketType.PLAYER_POINTS, S.Side.OVER, -110, "8.5", "Taurean Prince"),
        manual("PHI@NYK", S.MarketType.TOTAL, S.Side.OVER, -110, "224.5"),
        manual("OKC@SAS", S.MarketType.MONEYLINE, S.Side.AWAY, -150),
    ]
    report = [injury(e1, "Taurean Prince", S.InjuryDesignation.QUESTIONABLE, "DET")]
    cand = QR.analyze_user_ticket(inputs, None, three_game_slate, [], report, NOW, cfg, "u1")
    assert cand.leg_analyses[0].decision == S.LegDecision.WAIT_FOR_UPDATE
    assert "INJURY_QUESTIONABLE_MATERIAL" in cand.reason_codes


def test_rebuild_candidate_validates(candidate):
    with pytest.raises(ValueError):
        QR.rebuild_candidate(candidate, p_joint=None, ev_per_dollar=Decimal("0.1"))
    out = QR.rebuild_candidate(candidate, state=S.CandidateState.REJECTED)
    assert out.state == S.CandidateState.REJECTED and candidate.state == S.CandidateState.NEEDS_BOOK_QUOTE


def test_matching_with_event_built_from_other_source(cfg):
    # A manual event id for the same matchup still matches by team names.
    e = make_event("BOS", "DET", event_id="manual:bos-det")
    legs = [
        make_selection(
            make_quote(e, S.MarketType.SPREAD, S.Side.HOME, "1.9091", line="3.5", team=TEAMS["DET"]), e
        ),
        make_selection(make_quote(e, S.MarketType.TOTAL, S.Side.OVER, "1.91", line="221.5"), e),
        make_selection(
            make_quote(
                e, S.MarketType.PLAYER_ASSISTS, S.Side.OVER, "1.91", line="8.5", player="Cade Cunningham"
            ),
            e,
        ),
    ]
    ticket = S.ThreeLegTicket(legs=legs)
    indexes, conflicts = QR.match_legs_as_shown(["Detroit +3.5", "Over 221.5", "Cunningham o8.5 ast"], ticket)
    assert conflicts == [] and indexes == [0, 1, 2]


# --------------------------------------------------------------------------------------
# Review fixes (2026-10-19): the slip must describe the same bet; quote capture age; payout contradiction;
# typed legs keep their own line on revalidation
# --------------------------------------------------------------------------------------


def test_slip_with_matchup_prefix_and_our_team_as_subject_matches(candidate):
    shown = [
        "Boston Celtics @ Detroit Pistons: Pistons +3.5",
        "PHI @ NYK Over 224.5",
        "Oklahoma City Thunder @ San Antonio Spurs: Thunder ML",
    ]
    indexes, conflicts = QR.match_legs_as_shown(shown, candidate.ticket)
    assert conflicts == [] and indexes == [0, 1, 2]


def test_unsigned_spread_on_the_slip_is_a_conflict(candidate):
    _indexes, conflicts = QR.match_legs_as_shown(
        ["Pistons 3.5", "PHI/NYK over 224.5", "OKC ML"], candidate.ticket
    )
    assert conflicts and "Pistons 3.5" in conflicts[0]


def test_slip_naming_a_team_from_another_game_is_a_conflict(candidate):
    shown = ["Pistons +3.5", "Knicks vs Lakers over 224.5", "OKC ML"]
    _indexes, conflicts = QR.match_legs_as_shown(shown, candidate.ticket)
    assert conflicts and "Knicks vs Lakers over 224.5" in conflicts[0]


def test_player_name_containing_a_city_is_not_another_game():
    dal = S.Team(team_id="nba:DAL", name="Dallas Mavericks", abbreviation="DAL")
    e = S.Event(
        event_id="fixture:BOS@DAL",
        season_stage="REGULAR",
        home_team=dal,
        away_team=TEAMS["BOS"],
        commence_time_utc=NOW + timedelta(hours=4),
        status=S.EventStatus.SCHEDULED,
        stamp=stamp(),
    )
    legs = [
        make_selection(
            make_quote(
                e, S.MarketType.PLAYER_POINTS, S.Side.OVER, "1.91", line="18.5", player="P.J. Washington"
            ),
            e,
        ),
        make_selection(make_quote(e, S.MarketType.TOTAL, S.Side.OVER, "1.91", line="221.5"), e),
        make_selection(make_quote(e, S.MarketType.MONEYLINE, S.Side.HOME, "1.80", team=dal), e),
    ]
    ticket = S.ThreeLegTicket(legs=legs)
    indexes, conflicts = QR.match_legs_as_shown(
        ["P.J. Washington over 18.5 points", "Over 221.5", "Mavericks ML"], ticket
    )
    assert conflicts == [] and indexes == [0, 1, 2]
    _indexes, conflicts = QR.match_legs_as_shown(
        ["P.J. Washington over 18.5 points", "Wizards over 221.5", "Mavericks ML"], ticket
    )
    assert conflicts
    _indexes, conflicts = QR.match_legs_as_shown(
        ["P.J. Washington over 18.5 points", "Over 221.5", "Celtics ML"], ticket
    )
    assert conflicts


def test_quote_captured_too_long_ago_is_stored_but_not_applied(
    candidate, cfg, three_game_slate, three_multi_game_legs
):
    out, codes = QR.review_book_quote(candidate, quote(captured_at_utc=NOW - timedelta(hours=2)), NOW, cfg)
    assert "QUOTE_STALE" in codes and out.state == S.CandidateState.NEEDS_BOOK_QUOTE
    assert out.book_quote is not None and "captured_at_utc" in out.book_quote.unresolved_fields
    assert (
        out.payout.combined_source == "INDICATIVE_MULTIPLIED"
        and QR.QUOTE_CAPTURE_STALE_REASON in out.rationale
    )
    # a refresh with unchanged prices does not resurrect the old quote; it must be re-imported
    again = QR.revalidate(out, three_multi_game_legs, three_refs(three_game_slate), [], NOW, cfg)
    assert (
        again.state == S.CandidateState.NEEDS_BOOK_QUOTE
        and again.payout.combined_source == "INDICATIVE_MULTIPLIED"
    )
    fresh, fresh_codes = QR.review_book_quote(
        candidate, quote(captured_at_utc=NOW - timedelta(seconds=120)), NOW, cfg
    )
    assert fresh.state == S.CandidateState.READY_FOR_USER_REVIEW and "QUOTE_STALE" not in fresh_codes


def test_payout_contradicting_the_combined_price_blocks(candidate, cfg):
    out, codes = QR.review_book_quote(
        candidate,
        quote(stake_shown_usd=Decimal("10"), payout_shown_usd=Decimal("100"), payout_includes_stake=True),
        NOW,
        cfg,
    )
    assert "QUOTE_SIGN_AMBIGUOUS" in codes and out.state == S.CandidateState.NEEDS_BOOK_QUOTE
    assert out.book_quote is not None and "payout_shown_usd" in out.book_quote.unresolved_fields
    assert (
        out.payout.combined_source == "INDICATIVE_MULTIPLIED"
        and QR.PAYOUT_CONTRADICTS_REASON in out.rationale
    )
    # unknown convention: a payout that fits either reading is fine, one that fits neither is not
    ok, _ = QR.review_book_quote(
        candidate,
        quote(stake_shown_usd=Decimal("10"), payout_shown_usd=Decimal("45"), payout_includes_stake=None),
        NOW,
        cfg,
    )
    assert ok.state == S.CandidateState.READY_FOR_USER_REVIEW
    assert ok.book_quote is not None and "payout_shown_usd" not in ok.book_quote.unresolved_fields
    _bad, bad_codes = QR.review_book_quote(
        candidate,
        quote(stake_shown_usd=Decimal("10"), payout_shown_usd=Decimal("100"), payout_includes_stake=None),
        NOW,
        cfg,
    )
    assert "QUOTE_SIGN_AMBIGUOUS" in bad_codes


def test_revalidate_keeps_a_typed_leg_at_its_own_line(cfg, three_game_slate, three_multi_game_legs):
    e2 = three_game_slate[1]
    typed_stamp = S.SourceStamp(
        source="user",
        source_url=None,
        source_record_id=None,
        source_timestamp_utc=None,
        received_at_utc=NOW,
        data_mode=S.DataMode.MANUAL_INPUT,
    )
    typed = make_quote(e2, S.MarketType.TOTAL, S.Side.OVER, "1.9091", line="226.5").model_copy(
        update={"stamp": typed_stamp}
    )
    legs = [
        three_multi_game_legs[0],
        make_selection(typed, e2, "PHI/NYK over 226.5"),
        three_multi_game_legs[2],
    ]
    refs = three_refs(three_game_slate)  # the benchmark total is at 224.5 only
    cand = ready(build(cfg, legs, refs), cfg)
    assert "LINE_MISMATCH" in cand.leg_analyses[1].reason_codes
    # the feed now carries PHI/NYK over 224.5 (the main line); the user's 226.5 is not rewritten
    out = QR.revalidate(cand, three_multi_game_legs, refs, [], NOW, cfg)
    assert out.ticket.legs[1].quote.line == Decimal("226.5")
    assert out.ticket.legs[1].quote.stamp.data_mode == S.DataMode.MANUAL_INPUT
    assert out.state == S.CandidateState.READY_FOR_USER_REVIEW
    assert "MARKET_SUSPENDED" not in out.reason_codes and QR.PRICE_CHANGED_REASON not in out.rationale
    assert "LINE_MISMATCH" in out.leg_analyses[1].reason_codes
