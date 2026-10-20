"""Adversarial review of the data module (providers, normalization, freshness, injury_context).

Every test here that FAILS against the current code reproduces a defect described in the review report.
Tests that pass are kept only because they document a non-obvious behaviour; each is marked with a
``# documents:`` comment. No network: respx intercepts every request.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx
from conftest import NOW, make_event

from hardrock_nba_parlay import freshness as F
from hardrock_nba_parlay import normalization as N
from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.config import FixedClock, Settings
from hardrock_nba_parlay.errors import InvalidInput, ProviderError
from hardrock_nba_parlay.providers import manual
from hardrock_nba_parlay.providers import nba_injury_report as R
from hardrock_nba_parlay.providers.fixtures import load_fixture_slate
from hardrock_nba_parlay.providers.odds_api import OddsApiProvider

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://api.the-odds-api.com/v4"
API_KEY = "FIXTUREKEYabcdef0123456789abcdef01234567"  # fake key; must never appear in any log


def body(name: str):
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert data["data_mode"] == "FIXTURE"
    return data["body"]


def make_settings(tmp_path, **overrides) -> Settings:
    kwargs = {
        "data_dir": tmp_path,
        "database_url": f"sqlite:///{tmp_path / 'review.db'}",
        "allow_fixture_ledger": True,
    }
    kwargs.update(overrides)
    return Settings(**kwargs)


@pytest.fixture
def api():
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        yield router


@pytest.fixture
def provider(settings, clock):
    return OddsApiProvider(API_KEY, settings, clock, http=httpx.Client(), sleep=lambda _s: None)


@pytest.fixture
def http_client_logs_at_info():
    """Put the HTTP client loggers back to NOTSET for one test and restore them afterwards.

    `config.configure_logging` (run by the CLI/web tests earlier in a full session) lowers the global "httpx"
    logger to WARNING, which would silence the very line this file checks; the premise here is a process that
    did NOT go through configure_logging, so the level is reset for the test (the module-level filter must do
    the redaction on its own).
    """
    names = ("httpx", "httpcore")
    saved = {name: logging.getLogger(name).level for name in names}
    for name in names:
        logging.getLogger(name).setLevel(logging.NOTSET)
    try:
        yield
    finally:
        for name, level in saved.items():
            logging.getLogger(name).setLevel(level)


# --------------------------------------------------------------------------------------
# Secrets
# --------------------------------------------------------------------------------------


def test_http_client_request_log_does_not_leak_api_key(api, provider, caplog, http_client_logs_at_info):
    """ARCHITECTURE section 0: "HTTP client logs must strip apiKey".

    httpx logs every request at INFO on the "httpx" logger with the full URL, apiKey included. The adapter
    owns the client (it creates one when http=None) but installs no filter and does not lower that logger, so
    any process whose root logger is at INFO (anything that does not go through config.configure_logging)
    writes the key to its log.
    """
    api.get("/sports/basketball_nba/events").mock(return_value=httpx.Response(200, json=[]))
    with caplog.at_level(logging.INFO):
        provider.list_events("2026-10-20")
    assert "HTTP Request" in caplog.text  # the httpx line was emitted
    assert API_KEY not in caplog.text
    assert "apiKey=" not in caplog.text


# --------------------------------------------------------------------------------------
# Time zone: the local day is America/New_York by contract, not settings.display_tz
# --------------------------------------------------------------------------------------


def test_list_events_day_bounds_are_et_regardless_of_display_tz(api, tmp_path, clock):
    """Brief: commenceTimeFrom/To are "the UTC bounds of the ET day"; ARCHITECTURE section 0 says local dates
    are America/New_York. mcp_server/cli compute date_local with config.local_date (always ET), so a user who
    sets display_tz to another zone gets a slate window that no longer matches their ledger day."""
    settings = make_settings(tmp_path, display_tz="America/Los_Angeles")
    provider = OddsApiProvider(API_KEY, settings, clock, http=httpx.Client(), sleep=lambda _s: None)
    route = api.get("/sports/basketball_nba/events").mock(return_value=httpx.Response(200, json=[]))
    provider.list_events("2026-10-20")
    params = route.calls.last.request.url.params
    assert params["commenceTimeFrom"] == "2026-10-20T04:00:00Z"
    assert params["commenceTimeTo"] == "2026-10-21T03:59:59Z"


def test_credit_guard_day_is_et_regardless_of_display_tz(api, tmp_path):
    """Brief: the guard sums credits "for today's ET date". With display_tz=America/Los_Angeles the day rolls
    at 03:00 ET, so credits spent between 00:00 and 03:00 ET vanish from the guard three hours early."""
    clock = FixedClock(datetime(2026, 10, 21, 5, 30, tzinfo=UTC))  # 01:30 ET Oct 21 == 22:30 PT Oct 20
    settings = make_settings(tmp_path, display_tz="America/Los_Angeles", daily_provider_credit_budget=1)
    provider = OddsApiProvider(API_KEY, settings, clock, http=httpx.Client(), sleep=lambda _s: None)
    api.get("/sports/basketball_nba/odds").mock(
        return_value=httpx.Response(200, json=body("odds_api_featured.json"))
    )
    assert (
        provider.fetch_featured_odds("2026-10-21", ["hardrockbet_fl"], [S.MarketType.MONEYLINE]).credits_cost
        == 1
    )
    clock.advance(2 * 3600)  # 03:30 ET Oct 21: still the same ET day (but a new Pacific day)
    provider.clear_cache()
    assert provider.credits_used_today() == 1
    with pytest.raises(ProviderError) as exc:
        provider.fetch_featured_odds("2026-10-21", ["hardrockbet_fl"], [S.MarketType.SPREAD])
    assert exc.value.reason_codes == ["PROVIDER_CREDIT_GUARD"]


def test_invalid_date_local_raises_invalid_input_not_value_error(provider):
    """schemas.LocalDate only checks the digit pattern, so "2026-13-45" reaches the provider. A raw ValueError
    is not a ServiceError and would surface as an unexpected exception (stack trace) instead of ToolError."""
    with pytest.raises(InvalidInput):
        provider.list_events("2026-13-45")
    with pytest.raises(InvalidInput):
        R.report_slots("2026-13-45", NOW)


# --------------------------------------------------------------------------------------
# Reference pairing: the target book must never benchmark itself
# --------------------------------------------------------------------------------------


def test_pair_reference_never_uses_the_target_book_as_its_own_reference():
    """fetch_featured_odds/fetch_event_props return target and reference books in ONE list, so passing that
    list to pair_reference is the natural call. The pairing never excludes selection.quote.book, so the
    hardrockbet_fl two-way becomes its own "reference" (edge exactly 0) and, when Pinnacle has a different
    line, it masks LINE_MISMATCH instead of reporting it."""
    slate = load_fixture_slate(now=NOW)
    selections = N.build_selections(slate.target_quotes, slate.events)
    brunson = next(
        s
        for s in selections
        if s.player
        and s.player.player_id == "player:jalen-brunson"
        and s.quote.side == S.Side.OVER
        and not s.quote.is_alternate
    )
    ref, reasons = N.pair_reference_with_reasons(brunson, slate.quotes)
    assert ref is not None and reasons == []
    assert ref.book != brunson.quote.book
    assert ref.book == "pinnacle"
    maxey = next(
        s
        for s in selections
        if s.player and s.player.player_id == "player:tyrese-maxey" and s.quote.side == S.Side.OVER
    )
    # Pinnacle has Maxey at 27.5, the target at 26.5: the only "reference" at 26.5 is the target book itself.
    assert N.pair_reference_with_reasons(maxey, slate.quotes, preferred_books=["pinnacle"]) == (
        None,
        ["LINE_MISMATCH"],
    )


# --------------------------------------------------------------------------------------
# Contract drift after the lead applied the data module's own foundation requests
# --------------------------------------------------------------------------------------


def test_manual_team_total_leg_with_team_field_is_accepted(three_game_slate, clock):
    """schemas.ManualSelectionInput now carries `team` (the field this module requested in
    docs/integration-notes/data.md), but selections_from_inputs still rejects every TEAM_TOTAL leg with
    MARKET_NOT_OFFERED and ignores the field."""
    item = S.ManualSelectionInput(
        game="PHI@NYK",
        market=S.MarketType.TEAM_TOTAL,
        side=S.Side.OVER,
        line=Decimal("115.5"),
        team="NYK",
        odds_american=-110,
    )
    (sel,) = manual.selections_from_inputs([item], three_game_slate, clock)
    assert sel.quote.market_type == S.MarketType.TEAM_TOTAL
    assert sel.quote.team_id == "nba:NYK" and sel.team is not None and sel.team.team_id == "nba:NYK"
    assert sel.description == "NYK team total over 115.5 (full game)"
    # a TEAM_TOTAL leg without a team is still rejected, with a code that names the gap
    with pytest.raises(InvalidInput) as exc:
        manual.selections_from_inputs([item.model_copy(update={"team": None})], three_game_slate, clock)
    assert exc.value.reason_codes == ["TEAM_UNMATCHED"]


def test_cancelled_event_reports_game_cancelled():
    """ARCHITECTURE section 7 and schemas.REASON_CODES now include GAME_CANCELLED; freshness still folds a
    CANCELLED event into GAME_POSTPONED (its own comment says to switch once the code exists)."""
    assert "GAME_CANCELLED" in S.REASON_CODES
    cancelled = make_event("BOS", "DET", start=NOW + timedelta(hours=1)).model_copy(
        update={"status": S.EventStatus.CANCELLED}
    )
    assert F.check_event_not_started(cancelled, NOW) == ["GAME_CANCELLED"]
    assert "GAME_CANCELLED" in F.BLOCKING_REASON_CODES


# --------------------------------------------------------------------------------------
# Robustness: one bad record must not discard a whole response or raise the wrong error type
# --------------------------------------------------------------------------------------


def test_one_unusable_prop_outcome_does_not_abort_the_call(api, provider):
    """A player_points outcome whose description normalises to nothing ("-") makes canonical_player raise
    InvalidInput(PLAYER_UNMATCHED) from inside the mapper, so the entire event-props call (all books, all
    markets) is lost instead of the one outcome being skipped with a warning like every other bad row."""
    payload = body("odds_api_event_props.json")
    points = next(m for m in payload["bookmakers"][0]["markets"] if m["key"] == "player_points")
    points["outcomes"].append({"name": "Over", "description": "-", "price": 1.9, "point": 10.5})
    api.get("/sports/basketball_nba/events/2a4b6c8d0e1f3a5b7c9d1e3f5a7b9c0d/odds").mock(
        return_value=httpx.Response(200, json=payload)
    )
    result = provider.fetch_event_props(
        "oddsapi:2a4b6c8d0e1f3a5b7c9d1e3f5a7b9c0d", ["hardrockbet_fl"], [S.MarketType.PLAYER_POINTS], False
    )
    brunson = [q for q in result.data if q.player_id == "player:jalen-brunson"]
    assert len(brunson) == 2
    assert any("skipped" in w for w in result.warnings)


def test_non_list_odds_body_is_provider_error_not_attribute_error(api, provider):
    """A 200 whose JSON body is an object (not the documented list) is iterated as dict keys and crashes
    with AttributeError ('str' has no attribute 'get'); callers expect ProviderError."""
    api.get("/sports/basketball_nba/odds").mock(return_value=httpx.Response(200, json={"message": "oops"}))
    with pytest.raises(ProviderError) as exc:
        provider.fetch_featured_odds("2026-10-20", ["hardrockbet_fl"], [S.MarketType.MONEYLINE])
    assert exc.value.reason_codes == ["PROVIDER_ERROR"]


def test_slip_extraction_unparseable_capture_time_is_unresolved_not_an_error():
    """slip_fields_from_extraction promises to list every ambiguous field in `unresolved` and never raise for
    readable-but-odd text. A screenshot timestamp like "10/20/2026 2:55 PM" raises InvalidInput instead."""
    fields = {
        "legs": [{"game": "BOS@DET", "market": "SPREAD", "side": "HOME", "line": "3.5", "odds": "-110"}],
        "combined_odds": "+650",
        "stake": "10",
        "payout": "75.00",
        "payout_includes_stake": True,
        "captured_at_utc": "10/20/2026 2:55 PM",
    }
    quote, legs, unresolved = manual.slip_fields_from_extraction(fields)
    assert "captured_at_utc" in unresolved
    assert quote.captured_at_utc is None and quote.user_confirmed is False
    assert len(legs) == 1 and legs[0].odds_american == -110


def test_csv_with_utf8_bom_is_accepted(tmp_path):
    """Excel's "CSV UTF-8" export prefixes a BOM; the header check compares the raw first cell ("\\ufeffgame")
    and the file reader uses encoding="utf-8", so both paths reject a valid file."""
    text = (
        "game,market,side,line,player_name,odds_american,odds_decimal,book,observed_at_utc\n"
        "BOS@DET,SPREAD,HOME,3.5,,-110,,,\n"
    )
    inputs = manual.parse_pasted_selections("﻿" + text)
    assert len(inputs) == 1 and inputs[0].odds_american == -110
    path = tmp_path / "legs.csv"
    path.write_text(text, encoding="utf-8-sig")
    assert len(manual.load_csv(path)) == 1


# --------------------------------------------------------------------------------------
# Provenance of cached responses
# --------------------------------------------------------------------------------------


def test_cached_result_reports_zero_credits_and_original_receipt_time(api, provider, clock):
    """A cache hit makes no request, yet the result repeats the documented cost (so a pipeline summing
    credits_cost over-reports spend) and stamps received_at_utc with the hit time, not the time the data was
    actually received; for /events (no source timestamp) that hides the data's real age."""
    api.get("/sports/basketball_nba/odds").mock(
        return_value=httpx.Response(200, json=body("odds_api_featured.json"))
    )
    first = provider.fetch_featured_odds("2026-10-20", ["hardrockbet_fl"], [S.MarketType.MONEYLINE])
    clock.advance(30)
    second = provider.fetch_featured_odds("2026-10-20", ["hardrockbet_fl"], [S.MarketType.MONEYLINE])
    assert second.cached is True
    assert second.credits_cost == 0
    assert second.stamp.received_at_utc == first.stamp.received_at_utc
    assert second.data[0].stamp.received_at_utc == first.data[0].stamp.received_at_utc


# --------------------------------------------------------------------------------------
# Passing tests kept because they document non-obvious behaviour
# --------------------------------------------------------------------------------------


def test_force_bypasses_the_credit_guard_but_not_the_cache(api, tmp_path, clock):
    # documents: force=True only skips the PROVIDER_CREDIT_GUARD check; a fresh cache entry is still served,
    # so a caller that wants a real refetch must call clear_cache() first (the module's tests do exactly that).
    settings = make_settings(tmp_path, daily_provider_credit_budget=1)
    provider = OddsApiProvider(API_KEY, settings, clock, http=httpx.Client(), sleep=lambda _s: None)
    route = api.get("/sports/basketball_nba/odds").mock(
        return_value=httpx.Response(200, json=body("odds_api_featured.json"))
    )
    provider.fetch_featured_odds("2026-10-20", ["hardrockbet_fl"], [S.MarketType.MONEYLINE])
    forced = provider.fetch_featured_odds(
        "2026-10-20", ["hardrockbet_fl"], [S.MarketType.MONEYLINE], force=True
    )
    assert forced.cached is True and route.call_count == 1


def test_json_integer_american_odds_are_taken_as_typed_but_text_requires_a_sign():
    # documents: in the JSON/MCP-argument path an integer 110 is an unambiguous +110 (the structured type
    # carries the sign), while the same digits as text ("110") are rejected with QUOTE_SIGN_AMBIGUOUS.
    (typed,) = manual.parse_pasted_selections(
        '[{"game": "BOS@DET", "market": "SPREAD", "side": "HOME", "line": "3.5", "odds_american": 110}]'
    )
    assert typed.odds_american == 110
    with pytest.raises(InvalidInput) as exc:
        manual.parse_pasted_selections(
            '[{"game": "BOS@DET", "market": "SPREAD", "side": "HOME", "line": "3.5", "odds_american": "110"}]'
        )
    assert exc.value.reason_codes == ["QUOTE_SIGN_AMBIGUOUS"]
