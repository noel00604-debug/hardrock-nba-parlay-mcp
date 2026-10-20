"""freshness.py: 180 s / 60 s thresholds (inclusive), unknown timestamps, game state, aggregation."""

from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import NOW, TEAMS, make_event, make_quote, make_reference, make_selection

from hardrock_nba_parlay import freshness as F
from hardrock_nba_parlay import schemas as S


def _quote_at(event, seconds_old: int | None):
    source_ts = None if seconds_old is None else NOW - timedelta(seconds=seconds_old)
    quote = make_quote(event, S.MarketType.TOTAL, S.Side.OVER, "1.91", line="224.5", source_ts=source_ts)
    if seconds_old is None:
        quote = quote.model_copy(
            update={"stamp": quote.stamp.model_copy(update={"source_timestamp_utc": None})}
        )
    return quote


@pytest.mark.parametrize(
    ("age", "expected"), [(0, []), (179, []), (180, []), (181, ["QUOTE_STALE"]), (3600, ["QUOTE_STALE"])]
)
def test_quote_age_threshold_inclusive(three_game_slate, age, expected):
    quote = _quote_at(three_game_slate[1], age)
    assert F.check_quote_age(quote, NOW, 180) == expected


def test_quote_without_source_timestamp_is_unknown_not_fresh(three_game_slate):
    quote = _quote_at(three_game_slate[1], None)
    assert F.check_quote_age(quote, NOW, 180) == ["SOURCE_TIMESTAMP_UNKNOWN"]


def test_quote_age_requires_aware_now(three_game_slate):
    with pytest.raises(ValueError):
        F.check_quote_age(_quote_at(three_game_slate[1], 10), NOW.replace(tzinfo=None), 180)


@pytest.mark.parametrize(
    ("skew", "expected"), [(0, []), (60, []), (61, ["TIMESTAMP_SKEW"]), (-60, []), (-61, ["TIMESTAMP_SKEW"])]
)
def test_reference_skew_threshold_inclusive_both_directions(three_game_slate, skew, expected):
    event = three_game_slate[1]
    target = _quote_at(event, 30)
    ref = make_reference(
        event, S.MarketType.TOTAL, "1.91", "1.91", line="224.5", source_ts=NOW - timedelta(seconds=30 + skew)
    )
    assert F.check_reference_skew(target, ref, 60) == expected


def test_reference_skew_unknown_when_a_timestamp_is_missing(three_game_slate):
    event = three_game_slate[1]
    ref = make_reference(event, S.MarketType.TOTAL, "1.91", "1.91", line="224.5")
    assert F.check_reference_skew(_quote_at(event, None), ref, 60) == ["SOURCE_TIMESTAMP_UNKNOWN"]
    ref_unknown = ref.model_copy(
        update={"stamp": ref.stamp.model_copy(update={"source_timestamp_utc": None})}
    )
    assert F.check_reference_skew(_quote_at(event, 10), ref_unknown, 60) == ["SOURCE_TIMESTAMP_UNKNOWN"]


def test_event_state_codes():
    assert F.check_event_not_started(make_event("BOS", "DET", start=NOW + timedelta(seconds=1)), NOW) == []
    assert F.check_event_not_started(make_event("BOS", "DET", start=NOW), NOW) == ["GAME_STARTED"]
    assert F.check_event_not_started(make_event("BOS", "DET", start=NOW - timedelta(hours=1)), NOW) == [
        "GAME_STARTED"
    ]
    live = make_event("BOS", "DET", start=NOW + timedelta(hours=1)).model_copy(
        update={"status": S.EventStatus.LIVE}
    )
    assert F.check_event_not_started(live, NOW) == ["GAME_STARTED"]
    final = make_event("BOS", "DET", start=NOW + timedelta(hours=1)).model_copy(
        update={"status": S.EventStatus.FINAL}
    )
    assert F.check_event_not_started(final, NOW) == ["GAME_STARTED"]
    postponed = make_event("BOS", "DET", start=NOW + timedelta(hours=1)).model_copy(
        update={"status": S.EventStatus.POSTPONED}
    )
    assert F.check_event_not_started(postponed, NOW) == ["GAME_POSTPONED"]
    cancelled = make_event("BOS", "DET", start=NOW - timedelta(hours=1)).model_copy(
        update={"status": S.EventStatus.CANCELLED}
    )
    # ARCHITECTURE section 7 lists GAME_CANCELLED; a cancelled game is no longer folded into GAME_POSTPONED.
    assert F.check_event_not_started(cancelled, NOW) == ["GAME_CANCELLED"]
    assert "GAME_CANCELLED" in F.BLOCKING_REASON_CODES and "GAME_POSTPONED" in F.BLOCKING_REASON_CODES
    assert F.decision_for(["GAME_CANCELLED"]) == S.LegDecision.UNUSABLE


def test_revalidation_aggregates_and_deduplicates(settings, three_game_slate):
    event = three_game_slate[1]
    stale = make_selection(_quote_at(event, 200), event)
    assert F.revalidation_reasons(stale, None, NOW, settings) == ["QUOTE_STALE", "REFERENCE_MISSING"]
    fresh = make_selection(_quote_at(event, 30), event)
    skewed_ref = make_reference(
        event, S.MarketType.TOTAL, "1.91", "1.91", line="224.5", source_ts=NOW - timedelta(seconds=100)
    )
    assert F.revalidation_reasons(fresh, skewed_ref, NOW, settings) == ["TIMESTAMP_SKEW"]
    stale_ref = make_reference(
        event, S.MarketType.TOTAL, "1.91", "1.91", line="224.5", source_ts=NOW - timedelta(seconds=400)
    )
    assert F.revalidation_reasons(stale, stale_ref, NOW, settings) == ["QUOTE_STALE", "TIMESTAMP_SKEW"]
    ok_ref = make_reference(
        event, S.MarketType.TOTAL, "1.91", "1.91", line="224.5", source_ts=NOW - timedelta(seconds=40)
    )
    assert F.revalidation_reasons(fresh, ok_ref, NOW, settings) == []
    tip = event.commence_time_utc
    at_tip = make_quote(
        event, S.MarketType.TOTAL, S.Side.OVER, "1.91", line="224.5", source_ts=tip - timedelta(seconds=30)
    )
    ref_at_tip = make_reference(
        event, S.MarketType.TOTAL, "1.91", "1.91", line="224.5", source_ts=tip - timedelta(seconds=40)
    )
    assert F.revalidation_reasons(make_selection(at_tip, event), ref_at_tip, tip, settings) == [
        "GAME_STARTED"
    ]


def test_is_usable_and_decision():
    assert F.is_usable([]) is True
    assert F.is_usable(["REFERENCE_MISSING", "SOURCE_TIMESTAMP_UNKNOWN", "TIMESTAMP_SKEW"]) is True
    assert F.is_usable(["QUOTE_STALE"]) is False
    assert F.is_usable(["INJURY_QUESTIONABLE_MATERIAL"]) is False
    assert F.decision_for([]) == S.LegDecision.USABLE
    assert F.decision_for(["INJURY_QUESTIONABLE_MATERIAL"]) == S.LegDecision.WAIT_FOR_UPDATE
    assert F.decision_for(["GAME_STARTED", "INJURY_QUESTIONABLE_MATERIAL"]) == S.LegDecision.UNUSABLE
    assert F.decision_for(["INJURY_OUT"]) == S.LegDecision.UNUSABLE
    assert "QUOTE_STALE" in F.BLOCKING_REASON_CODES and "WAIT_FOR_UPDATE" in F.WAIT_REASON_CODES
    assert TEAMS["BOS"].team_id == "nba:BOS"
