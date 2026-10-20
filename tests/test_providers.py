"""providers: The Odds API adapter (respx-mocked), manual import, packaged fixtures. No network."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx
from conftest import NOW, TEAMS, make_event
from sqlalchemy import select

from hardrock_nba_parlay import normalization as N
from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.config import FixedClock, Settings
from hardrock_nba_parlay.db import provider_usage
from hardrock_nba_parlay.errors import InvalidInput, NotFound, ProviderError
from hardrock_nba_parlay.providers import base, manual
from hardrock_nba_parlay.providers.fixtures import FixtureSlate, available_fixtures, load_fixture_slate
from hardrock_nba_parlay.providers.odds_api import OddsApiProvider, credits_for_books

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://api.the-odds-api.com/v4"
API_KEY = "FIXTUREKEYabcdef0123456789abcdef01234567"  # fake; must never appear in logs or stamps
QUOTA = {"x-requests-remaining": "480", "x-requests-used": "20", "x-requests-last": "3"}


def body(name: str):
    data = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert data["data_mode"] == "FIXTURE"
    return data["body"]


def make_settings(tmp_path, **overrides) -> Settings:
    kwargs = {
        "data_dir": tmp_path,
        "database_url": f"sqlite:///{tmp_path / 't.db'}",
        "allow_fixture_ledger": True,
    }
    kwargs.update(overrides)
    return Settings(**kwargs)


@pytest.fixture
def api():
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        yield router


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def provider(settings, clock, sleeps):
    return OddsApiProvider(API_KEY, settings, clock, http=httpx.Client(), sleep=sleeps.append)


def ok(payload, headers=None):
    return httpx.Response(200, json=payload, headers=headers or QUOTA)


# --------------------------------------------------------------------------------------
# Events and ET day bounds
# --------------------------------------------------------------------------------------


def test_list_events_maps_and_uses_et_day_bounds(api, provider):
    route = api.get("/sports/basketball_nba/events").mock(return_value=ok(body("odds_api_events.json")))
    result = provider.list_events("2026-10-20")
    params = route.calls.last.request.url.params
    assert params["commenceTimeFrom"] == "2026-10-20T04:00:00Z"
    assert params["commenceTimeTo"] == "2026-10-21T03:59:59Z"
    assert params["apiKey"] == API_KEY  # sent to the API, never anywhere else
    assert result.credits_cost == 0
    assert result.quota == {"requests_remaining": 480, "requests_used": 20, "requests_last": 3}
    assert result.stamp.data_mode == S.DataMode.LIVE_PROVIDER and "apiKey" not in (
        result.stamp.source_url or ""
    )
    assert [e.event_id for e in result.data] == [
        "oddsapi:1f3a0c4e6b8d2a5c7e9f1b3d5a7c9e0b",
        "oddsapi:2a4b6c8d0e1f3a5b7c9d1e3f5a7b9c0d",
        "oddsapi:3b5c7d9e1f2a4b6c8d0e2f4a6b8c0d1e",
    ]
    first = result.data[0]
    assert first.home_team == TEAMS["DET"] and first.away_team == TEAMS["BOS"]
    assert first.season_stage == "REGULAR"
    assert first.commence_time_utc == datetime(2026, 10, 20, 19, 0, tzinfo=UTC)
    assert first.status == S.EventStatus.LIVE  # clock is exactly tip-off
    assert result.data[1].status == S.EventStatus.SCHEDULED
    assert first.stamp.source == "the-odds-api"
    assert first.stamp.source_record_id == "1f3a0c4e6b8d2a5c7e9f1b3d5a7c9e0b"
    assert first.stamp.source_timestamp_utc is None  # the events endpoint has no update time
    assert first.stamp.received_at_utc == NOW


def test_list_events_dst_end_day_is_25_hours(api, provider):
    route = api.get("/sports/basketball_nba/events").mock(return_value=ok([]))
    provider.list_events("2026-11-01")
    params = route.calls.last.request.url.params
    assert params["commenceTimeFrom"] == "2026-11-01T04:00:00Z"
    assert params["commenceTimeTo"] == "2026-11-02T04:59:59Z"


def test_list_events_skips_other_sports_and_unknown_teams(api, provider):
    events = body("odds_api_events.json")
    events[0]["sport_key"] = "basketball_nba_preseason"
    events[1]["home_team"] = "Harlem Globetrotters"
    api.get("/sports/basketball_nba/events").mock(return_value=ok(events))
    result = provider.list_events("2026-10-20")
    assert [e.event_id for e in result.data] == ["oddsapi:3b5c7d9e1f2a4b6c8d0e2f4a6b8c0d1e"]
    assert any(w.startswith("WRONG_LEAGUE") for w in result.warnings)
    assert any(w.startswith("TEAM_UNMATCHED") for w in result.warnings)


def test_never_requests_preseason_sport_key(api, provider):
    api.get("/sports/basketball_nba/events").mock(return_value=ok([]))
    api.get("/sports/basketball_nba/odds").mock(return_value=ok([]))
    provider.list_events("2026-10-20")
    provider.fetch_featured_odds("2026-10-20", ["hardrockbet_fl"], [S.MarketType.MONEYLINE])
    for call in api.calls:
        assert "/sports/basketball_nba/" in call.request.url.path
        assert "preseason" not in call.request.url.path


# --------------------------------------------------------------------------------------
# Featured odds mapping
# --------------------------------------------------------------------------------------


def test_featured_odds_mapping_sides_lines_and_books(api, provider):
    route = api.get("/sports/basketball_nba/odds").mock(return_value=ok(body("odds_api_featured.json")))
    books = ["hardrockbet_fl", "hardrockbet", "pinnacle"]
    result = provider.fetch_featured_odds(
        "2026-10-20", books, [S.MarketType.MONEYLINE, S.MarketType.SPREAD, S.MarketType.TOTAL]
    )
    params = route.calls.last.request.url.params
    assert params["bookmakers"] == "hardrockbet_fl,hardrockbet,pinnacle"
    assert params["markets"] == "h2h,spreads,totals"
    assert params["oddsFormat"] == "decimal" and params["dateFormat"] == "iso"
    assert result.credits_cost == 3 == credits_for_books(3, 3)
    assert result.reason_codes == []
    quotes = result.data
    assert {q.book for q in quotes} == {"hardrockbet_fl", "hardrockbet", "pinnacle"}
    assert all(q.period == S.Period.FULL_GAME and not q.is_alternate for q in quotes)
    assert all(q.odds_american is None for q in quotes)
    hr = [
        q
        for q in quotes
        if q.book == "hardrockbet_fl" and q.event_id == "oddsapi:1f3a0c4e6b8d2a5c7e9f1b3d5a7c9e0b"
    ]
    assert all(q.jurisdiction == "US-FL" for q in hr)
    assert all(q.jurisdiction is None for q in quotes if q.book != "hardrockbet_fl")
    ml = {q.side: q for q in hr if q.market_type == S.MarketType.MONEYLINE}
    assert (
        ml[S.Side.HOME].team_id == "nba:DET"
        and ml[S.Side.HOME].odds_decimal == Decimal("2.70")
        and ml[S.Side.HOME].line is None
    )
    assert ml[S.Side.AWAY].team_id == "nba:BOS" and ml[S.Side.AWAY].odds_decimal == Decimal("1.48")
    sp = {q.side: q for q in hr if q.market_type == S.MarketType.SPREAD}
    assert sp[S.Side.HOME].line == Decimal("4.5") and sp[S.Side.HOME].team_id == "nba:DET"
    assert sp[S.Side.AWAY].line == Decimal("-4.5") and sp[S.Side.AWAY].team_id == "nba:BOS"
    tot = {q.side: q for q in hr if q.market_type == S.MarketType.TOTAL}
    assert tot[S.Side.OVER].line == tot[S.Side.UNDER].line == Decimal("221.5")
    assert tot[S.Side.OVER].team_id is None
    # market-level last_update is the source timestamp; record id is the event id; url carries no key
    assert ml[S.Side.HOME].stamp.source_timestamp_utc == datetime(2026, 10, 20, 18, 59, 30, tzinfo=UTC)
    assert sp[S.Side.HOME].stamp.source_timestamp_utc == datetime(2026, 10, 20, 18, 59, 31, tzinfo=UTC)
    assert ml[S.Side.HOME].stamp.source_record_id == "1f3a0c4e6b8d2a5c7e9f1b3d5a7c9e0b"
    assert ml[S.Side.HOME].stamp.source_url is not None and "apiKey" not in ml[S.Side.HOME].stamp.source_url
    assert "bookmakers=hardrockbet_fl" in ml[S.Side.HOME].stamp.source_url
    # the Indiana feed keeps its own key and is never relabelled
    indiana = [q for q in quotes if q.book == "hardrockbet"]
    assert indiana and all(q.jurisdiction is None for q in indiana)
    assert {q.line for q in indiana if q.market_type == S.MarketType.SPREAD} == {
        Decimal("4.0"),
        Decimal("-4.0"),
    }
    # ids are deterministic and unique
    assert len({q.quote_id for q in quotes}) == len(quotes)
    assert len({S.compute_selection_id(q) for q in quotes}) == len(quotes)


def test_featured_odds_target_book_absent_is_not_substituted(api, provider):
    events = body("odds_api_featured.json")
    for ev in events:
        ev["bookmakers"] = [b for b in ev["bookmakers"] if b["key"] != "hardrockbet_fl"]
    api.get("/sports/basketball_nba/odds").mock(return_value=ok(events))
    result = provider.fetch_featured_odds(
        "2026-10-20", ["hardrockbet_fl", "hardrockbet", "pinnacle"], [S.MarketType.MONEYLINE]
    )
    assert [q for q in result.data if q.book == "hardrockbet_fl"] == []
    assert result.reason_codes == ["BOOK_NOT_AVAILABLE"]
    assert any(w.startswith("BOOK_NOT_AVAILABLE") and "hardrockbet_fl" in w for w in result.warnings)
    # other REQUESTED books that came back are still keyed by their exact key (reference use only)
    assert {q.book for q in result.data} == {"hardrockbet", "pinnacle"}


def test_featured_odds_ignores_unrequested_books_and_markets(api, provider):
    # The vendor returns only what was requested; if a body carried more, nothing unrequested is mapped (no
    # substitution, no stray market keys) and each ignored bookmaker/market key is named once in the warnings.
    api.get("/sports/basketball_nba/odds").mock(return_value=ok(body("odds_api_featured.json")))
    result = provider.fetch_featured_odds("2026-10-20", ["hardrockbet_fl"], [S.MarketType.MONEYLINE])
    assert {q.book for q in result.data} == {"hardrockbet_fl"}
    assert {q.market_type for q in result.data} == {S.MarketType.MONEYLINE}
    assert result.reason_codes == [] and result.credits_cost == 1
    assert sum("bookmaker 'hardrockbet'" in w and "not requested" in w for w in result.warnings) == 1
    assert sum("bookmaker 'pinnacle'" in w for w in result.warnings) == 1
    assert any("'spreads' from hardrockbet_fl" in w and "not requested" in w for w in result.warnings)


def test_featured_odds_empty_response_costs_nothing(api, provider):
    api.get("/sports/basketball_nba/odds").mock(return_value=ok([]))
    result = provider.fetch_featured_odds(
        "2026-10-20", ["hardrockbet_fl", "pinnacle"], [S.MarketType.SPREAD, S.MarketType.TOTAL]
    )
    assert result.data == [] and result.credits_cost == 0
    assert result.reason_codes == ["BOOK_NOT_AVAILABLE"]


def test_featured_odds_rejects_bad_arguments(provider):
    with pytest.raises(InvalidInput):
        provider.fetch_featured_odds("2026-10-20", [], [S.MarketType.MONEYLINE])
    with pytest.raises(InvalidInput):
        provider.fetch_featured_odds("2026-10-20", ["hardrockbet_fl"], [S.MarketType.PLAYER_POINTS])


def test_credits_rule_from_docs():
    # "cost = markets x regions"; "every group of 10 bookmakers is the equivalent of 1 region"
    assert credits_for_books(3, 1) == 3
    assert credits_for_books(3, 10) == 3
    assert credits_for_books(3, 11) == 6
    assert credits_for_books(1, 20) == 2
    assert credits_for_books(0, 5) == 0


# --------------------------------------------------------------------------------------
# Event props
# --------------------------------------------------------------------------------------


def test_event_props_mapping_alternates_team_totals_and_cost(api, provider):
    route = api.get("/sports/basketball_nba/events/2a4b6c8d0e1f3a5b7c9d1e3f5a7b9c0d/odds").mock(
        return_value=ok(body("odds_api_event_props.json"))
    )
    result = provider.fetch_event_props(
        "oddsapi:2a4b6c8d0e1f3a5b7c9d1e3f5a7b9c0d",
        ["hardrockbet_fl", "pinnacle"],
        [
            S.MarketType.PLAYER_POINTS,
            S.MarketType.PLAYER_ASSISTS,
            S.MarketType.PLAYER_REBOUNDS,
            S.MarketType.TEAM_TOTAL,
        ],
        include_alternates=True,
    )
    params = route.calls.last.request.url.params
    assert params["markets"] == (
        "player_points,player_points_alternate,player_assists,player_assists_alternate,"
        "player_rebounds,player_rebounds_alternate,team_totals,alternate_team_totals"
    )
    # unique markets returned (player_points, player_points_alternate, player_assists, team_totals) x 1 region
    assert result.credits_cost == 4
    assert result.reason_codes == []
    quotes = result.data
    hr = [q for q in quotes if q.book == "hardrockbet_fl"]
    brunson = [
        q for q in hr if q.player_id == "player:jalen-brunson" and q.market_type == S.MarketType.PLAYER_POINTS
    ]
    main = [q for q in brunson if not q.is_alternate]
    alts = [q for q in brunson if q.is_alternate]
    assert {(q.side, q.line) for q in main} == {
        (S.Side.OVER, Decimal("24.5")),
        (S.Side.UNDER, Decimal("24.5")),
    }
    assert {(q.side, q.line) for q in alts} == {
        (S.Side.OVER, Decimal("29.5")),
        (S.Side.OVER, Decimal("19.5")),
    }
    assert all(q.player_name_raw == "Jalen Brunson" and q.team_id is None for q in brunson)
    assert all(q.jurisdiction == "US-FL" for q in hr)
    assert main[0].stamp.source_timestamp_utc == datetime(2026, 10, 20, 18, 59, 20, tzinfo=UTC)
    assists = [q for q in hr if q.market_type == S.MarketType.PLAYER_ASSISTS]
    assert len(assists) == 2 and all(q.line == Decimal("6.5") for q in assists)
    team_totals = [q for q in hr if q.market_type == S.MarketType.TEAM_TOTAL]
    assert {(q.team_id, q.side, q.line) for q in team_totals} == {
        ("nba:NYK", S.Side.OVER, Decimal("115.5")),
        ("nba:NYK", S.Side.UNDER, Decimal("115.5")),
        ("nba:PHI", S.Side.OVER, Decimal("109.5")),
        ("nba:PHI", S.Side.UNDER, Decimal("109.5")),
    }
    pin = [q for q in quotes if q.book == "pinnacle"]
    assert {q.line for q in pin if q.player_id == "player:tyrese-maxey"} == {Decimal("27.5")}
    assert len({q.quote_id for q in quotes}) == len(quotes)


def test_event_props_without_alternates_and_market_key_mapping(api, provider):
    route = api.get("/sports/basketball_nba/events/2a4b6c8d0e1f3a5b7c9d1e3f5a7b9c0d/odds").mock(
        return_value=ok(body("odds_api_event_props.json"))
    )
    provider.fetch_event_props(
        "2a4b6c8d0e1f3a5b7c9d1e3f5a7b9c0d",
        ["hardrockbet_fl"],
        [
            S.MarketType.PLAYER_POINTS,
            S.MarketType.PLAYER_THREES,
            S.MarketType.SPREAD,
            S.MarketType.TOTAL,
            S.MarketType.MONEYLINE,
        ],
        include_alternates=False,
    )
    assert route.calls.last.request.url.params["markets"] == "player_points,player_threes"
    provider.clear_cache()
    provider.fetch_event_props(
        "2a4b6c8d0e1f3a5b7c9d1e3f5a7b9c0d",
        ["hardrockbet_fl"],
        [S.MarketType.SPREAD, S.MarketType.TOTAL],
        True,
    )
    assert route.calls.last.request.url.params["markets"] == "alternate_spreads,alternate_totals"


def test_event_props_unknown_team_total_mapping_is_a_warning(api, provider):
    payload = body("odds_api_event_props.json")
    tt = next(m for m in payload["bookmakers"][0]["markets"] if m["key"] == "team_totals")
    tt["outcomes"] = [{"name": "Over", "description": "Knickerbockers?", "price": 1.9, "point": 115.5}]
    api.get("/sports/basketball_nba/events/2a4b6c8d0e1f3a5b7c9d1e3f5a7b9c0d/odds").mock(
        return_value=ok(payload)
    )
    result = provider.fetch_event_props(
        "2a4b6c8d0e1f3a5b7c9d1e3f5a7b9c0d", ["hardrockbet_fl"], [S.MarketType.TEAM_TOTAL], False
    )
    assert [q for q in result.data if q.market_type == S.MarketType.TEAM_TOTAL] == []
    assert any(w.startswith("UNKNOWN_TEAM_TOTAL_MAPPING") for w in result.warnings)


def test_event_props_404_is_not_found(api, provider):
    api.get("/sports/basketball_nba/events/deadbeef/odds").mock(
        return_value=httpx.Response(404, text="event expired")
    )
    with pytest.raises(ProviderError) as exc:
        provider.fetch_event_props(
            "oddsapi:deadbeef", ["hardrockbet_fl"], [S.MarketType.PLAYER_POINTS], False
        )
    assert exc.value.reason_codes == ["NOT_FOUND"] and exc.value.status_code == 404


def test_list_event_markets(api, provider):
    payload = {
        "id": "2a4b6c8d0e1f3a5b7c9d1e3f5a7b9c0d",
        "bookmakers": [
            {
                "key": "hardrockbet_fl",
                "markets": [
                    {"key": "h2h", "last_update": "2026-10-20T18:59:00Z"},
                    {"key": "player_points", "last_update": "2026-10-20T18:59:00Z"},
                ],
            },
            {"key": "pinnacle", "markets": [{"key": "h2h", "last_update": "2026-10-20T18:59:00Z"}]},
        ],
    }
    api.get("/sports/basketball_nba/events/2a4b6c8d0e1f3a5b7c9d1e3f5a7b9c0d/markets").mock(
        return_value=ok(payload)
    )
    result = provider.list_event_markets(
        "oddsapi:2a4b6c8d0e1f3a5b7c9d1e3f5a7b9c0d", ["hardrockbet_fl", "pinnacle", "draftkings"]
    )
    assert result.data == {"hardrockbet_fl": ["h2h", "player_points"], "pinnacle": ["h2h"]}
    assert result.credits_cost == 1 and result.reason_codes == []


# --------------------------------------------------------------------------------------
# Scores and probe
# --------------------------------------------------------------------------------------


def test_fetch_scores(api, provider):
    route = api.get("/sports/basketball_nba/scores").mock(return_value=ok(body("odds_api_scores.json")))
    result = provider.fetch_scores(1)
    assert route.calls.last.request.url.params["daysFrom"] == "1"
    assert result.credits_cost == 2
    done, pending = result.data
    assert done.event_id == "oddsapi:1f3a0c4e6b8d2a5c7e9f1b3d5a7c9e0b"
    assert done.completed and done.status == S.EventStatus.FINAL
    assert done.home_score == 108 and done.away_score == 112
    assert done.stamp.source_timestamp_utc == datetime(2026, 10, 20, 21, 40, 11, tzinfo=UTC)
    assert not pending.completed and pending.status == S.EventStatus.SCHEDULED
    assert pending.home_score is None and pending.stamp.source_timestamp_utc is None
    provider.clear_cache()
    assert provider.fetch_scores(None).credits_cost == 1
    with pytest.raises(InvalidInput):
        provider.fetch_scores(4)


def test_probe_free_call_and_optional_book_check(api, provider):
    sports = api.get("/sports").mock(
        return_value=ok(
            [{"key": "basketball_nba", "active": True}, {"key": "basketball_nba_preseason", "active": False}]
        )
    )
    probe = provider.probe()
    assert probe.auth_ok is True and probe.nba_active is True
    assert probe.target_book_present is None and probe.reference_books_present == {}
    assert probe.quota["requests_remaining"] == 480
    assert "apiKey" not in sports.calls.last.request.url.path
    api.get("/sports/basketball_nba/odds").mock(return_value=ok(body("odds_api_featured.json")))
    probe = provider.probe(spend_credits=True)
    assert probe.target_book_present is True
    assert probe.reference_books_present == {"pinnacle": True}


def test_probe_auth_failure_does_not_raise(api, provider):
    api.get("/sports").mock(return_value=httpx.Response(401, text="Invalid API key"))
    probe = provider.probe()
    assert probe.auth_ok is False and probe.nba_active is None
    assert probe.reason_codes == ["PROVIDER_AUTH_FAILED"]
    assert API_KEY not in " ".join(probe.warnings)


# --------------------------------------------------------------------------------------
# Errors, retries, backoff
# --------------------------------------------------------------------------------------


def test_401_auth_and_401_usage_limit(api, provider):
    api.get("/sports/basketball_nba/events").mock(
        return_value=httpx.Response(401, text="Unauthorized: invalid key")
    )
    with pytest.raises(ProviderError) as exc:
        provider.list_events("2026-10-20")
    assert exc.value.reason_codes == ["PROVIDER_AUTH_FAILED"]
    api.get("/sports/basketball_nba/events").mock(
        return_value=httpx.Response(401, text="Usage limit exceeded for this key")
    )
    with pytest.raises(ProviderError) as exc:
        provider.list_events("2026-10-20")
    assert exc.value.reason_codes == ["PROVIDER_QUOTA_EXHAUSTED"]


def test_422_is_invalid_input(api, provider):
    api.get("/sports/basketball_nba/odds").mock(
        return_value=httpx.Response(422, text="markets contains an invalid value")
    )
    with pytest.raises(InvalidInput) as exc:
        provider.fetch_featured_odds("2026-10-20", ["hardrockbet_fl"], [S.MarketType.MONEYLINE])
    assert exc.value.reason_codes == ["INVALID_INPUT"] and "invalid value" in (exc.value.detail or "")


def test_429_backoff_then_success(api, provider, sleeps):
    route = api.get("/sports/basketball_nba/events")
    route.side_effect = [httpx.Response(429), httpx.Response(429), ok(body("odds_api_events.json"))]
    result = provider.list_events("2026-10-20")
    assert len(result.data) == 3
    assert route.call_count == 3
    assert sleeps == [0.5, 1.0]


def test_429_exhausted_after_bounded_retries(api, provider, sleeps):
    route = api.get("/sports/basketball_nba/events").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "2"})
    )
    with pytest.raises(ProviderError) as exc:
        provider.list_events("2026-10-20")
    assert exc.value.reason_codes == ["PROVIDER_RATE_LIMITED"]
    assert exc.value.retry_after == 2.0
    assert route.call_count == 4  # 1 + http_max_retries (3)
    assert sleeps == [2.0, 2.0, 2.0]  # Retry-After honoured


def test_5xx_retry_then_provider_error(api, provider, sleeps):
    route = api.get("/sports/basketball_nba/events").mock(return_value=httpx.Response(503, text="down"))
    with pytest.raises(ProviderError) as exc:
        provider.list_events("2026-10-20")
    assert exc.value.reason_codes == ["PROVIDER_ERROR"] and exc.value.status_code == 503
    assert route.call_count == 4
    assert sleeps == [0.5, 1.0, 2.0]


def test_network_error_retries_and_redacts_key(api, provider, sleeps):
    route = api.get("/sports/basketball_nba/events").mock(
        side_effect=httpx.ConnectError(f"boom {BASE}/x?apiKey={API_KEY}")
    )
    with pytest.raises(ProviderError) as exc:
        provider.list_events("2026-10-20")
    assert exc.value.reason_codes == ["PROVIDER_ERROR"]
    assert API_KEY not in exc.value.message
    assert route.call_count == 4 and sleeps == [0.5, 1.0, 2.0]


def test_zero_retries_setting(api, tmp_path, clock, sleeps):
    settings = make_settings(tmp_path, http_max_retries=0)
    provider = OddsApiProvider(API_KEY, settings, clock, http=httpx.Client(), sleep=sleeps.append)
    route = api.get("/sports/basketball_nba/events").mock(return_value=httpx.Response(500))
    with pytest.raises(ProviderError):
        provider.list_events("2026-10-20")
    assert route.call_count == 1 and sleeps == []


# --------------------------------------------------------------------------------------
# Cache, pacing, credit guard, usage rows, redaction
# --------------------------------------------------------------------------------------


def test_cache_hit_avoids_second_request_until_ttl(api, provider, clock):
    route = api.get("/sports/basketball_nba/events").mock(return_value=ok(body("odds_api_events.json")))
    first = provider.list_events("2026-10-20")
    second = provider.list_events("2026-10-20")
    assert route.call_count == 1
    assert first.cached is False and second.cached is True
    assert [e.event_id for e in second.data] == [e.event_id for e in first.data]
    provider.list_events("2026-10-21")  # different params -> different key
    assert route.call_count == 2
    clock.advance(601)  # /events TTL is 600 s per the vendor's caching advice
    provider.list_events("2026-10-20")
    assert route.call_count == 3


def test_cache_key_ignores_api_key_and_uses_odds_ttl(api, tmp_path, clock):
    settings = make_settings(tmp_path, provider_cache_ttl_seconds=60)
    provider = OddsApiProvider(API_KEY, settings, clock, http=httpx.Client(), sleep=lambda _s: None)
    route = api.get("/sports/basketball_nba/odds").mock(return_value=ok(body("odds_api_featured.json")))
    provider.fetch_featured_odds("2026-10-20", ["hardrockbet_fl"], [S.MarketType.MONEYLINE])
    provider.fetch_featured_odds("2026-10-20", ["hardrockbet_fl"], [S.MarketType.MONEYLINE])
    assert route.call_count == 1
    clock.advance(61)
    provider.fetch_featured_odds("2026-10-20", ["hardrockbet_fl"], [S.MarketType.MONEYLINE])
    assert route.call_count == 2


def test_client_side_pacing_five_per_second(api, settings, clock, sleeps):
    ticks = iter([100.0] * 20)
    provider = OddsApiProvider(
        API_KEY, settings, clock, http=httpx.Client(), sleep=sleeps.append, monotonic=lambda: next(ticks)
    )
    api.get("/sports/basketball_nba/events").mock(return_value=ok([]))
    for day in range(1, 8):
        provider.list_events(f"2026-10-{20 + day:02d}")
    assert len(sleeps) >= 1
    assert all(abs(s - 1.0) < 1e-9 for s in sleeps)


def test_credit_guard_blocks_at_budget_and_force_bypasses(api, tmp_path, clock, db):
    settings = make_settings(tmp_path, daily_provider_credit_budget=3)
    provider = OddsApiProvider(API_KEY, settings, clock, http=httpx.Client(), db=db, sleep=lambda _s: None)
    api.get("/sports/basketball_nba/odds").mock(return_value=ok(body("odds_api_featured.json")))
    markets = [S.MarketType.MONEYLINE, S.MarketType.SPREAD, S.MarketType.TOTAL]
    first = provider.fetch_featured_odds("2026-10-20", ["hardrockbet_fl"], markets)
    assert first.credits_cost == 3
    assert provider.credits_used_today() == 3
    provider.clear_cache()
    with pytest.raises(ProviderError) as exc:
        provider.fetch_featured_odds("2026-10-20", ["hardrockbet_fl"], markets)
    assert exc.value.reason_codes == ["PROVIDER_CREDIT_GUARD"]
    forced = provider.fetch_featured_odds("2026-10-20", ["hardrockbet_fl"], markets, force=True)
    assert forced.credits_cost == 3
    assert provider.credits_used_today() == 6
    # free endpoints are never blocked by the guard
    api.get("/sports/basketball_nba/events").mock(return_value=ok([]))
    assert provider.list_events("2026-10-20").credits_cost == 0
    with db.engine.connect() as conn:
        rows = conn.execute(select(provider_usage).order_by(provider_usage.c.id)).mappings().all()
    assert [r["credits_cost"] for r in rows] == [3, 3, 0]
    assert rows[0]["provider"] == "the-odds-api" and rows[0]["endpoint"] == "/sports/basketball_nba/odds"
    assert rows[0]["requests_remaining"] == 480 and rows[0]["requests_used"] == 20
    assert rows[0]["created_at"].endswith("Z")


def test_credit_guard_counts_et_day(api, tmp_path, db):
    # 23:30 ET on Oct 20 is 03:30Z Oct 21; a spend then must count for Oct 20, not Oct 21
    clock = FixedClock(datetime(2026, 10, 21, 3, 30, tzinfo=UTC))
    settings = make_settings(tmp_path, daily_provider_credit_budget=1)
    provider = OddsApiProvider(API_KEY, settings, clock, http=httpx.Client(), db=db, sleep=lambda _s: None)
    api.get("/sports/basketball_nba/odds").mock(return_value=ok(body("odds_api_featured.json")))
    provider.fetch_featured_odds("2026-10-20", ["hardrockbet_fl"], [S.MarketType.MONEYLINE])
    assert provider.credits_used_today() == 1
    provider.clear_cache()
    with pytest.raises(ProviderError):
        provider.fetch_featured_odds("2026-10-21", ["hardrockbet_fl"], [S.MarketType.MONEYLINE])
    clock.advance(3600)  # 00:30 ET on Oct 21: a new ET day
    assert provider.credits_used_today() == 0
    assert (
        provider.fetch_featured_odds("2026-10-21", ["hardrockbet_fl"], [S.MarketType.MONEYLINE]).credits_cost
        == 1
    )


def test_credit_guard_without_db_uses_memory(api, tmp_path, clock):
    settings = make_settings(tmp_path, daily_provider_credit_budget=2)
    provider = OddsApiProvider(API_KEY, settings, clock, http=httpx.Client(), sleep=lambda _s: None)
    api.get("/sports/basketball_nba/scores").mock(return_value=ok(body("odds_api_scores.json")))
    provider.fetch_scores(1)
    provider.clear_cache()
    with pytest.raises(ProviderError) as exc:
        provider.fetch_scores(1)
    assert exc.value.reason_codes == ["PROVIDER_CREDIT_GUARD"]


def test_api_key_never_in_logs_or_stamps(api, provider, caplog):
    api.get("/sports/basketball_nba/events").mock(return_value=ok(body("odds_api_events.json")))
    api.get("/sports/basketball_nba/odds").mock(
        return_value=httpx.Response(500, text=f"echo apiKey={API_KEY}")
    )
    with caplog.at_level(logging.DEBUG, logger="hardrock_nba_parlay.providers.odds_api"):
        result = provider.list_events("2026-10-20")
        with pytest.raises(ProviderError) as exc:
            provider.fetch_featured_odds("2026-10-20", ["hardrockbet_fl"], [S.MarketType.MONEYLINE])
    assert caplog.text  # something was logged
    assert API_KEY not in caplog.text
    assert "apiKey" not in caplog.text
    assert API_KEY not in (exc.value.detail or "") and API_KEY not in exc.value.message
    for event in result.data:
        assert API_KEY not in (event.stamp.source_url or "")
    assert API_KEY not in (result.stamp.source_url or "")
    assert API_KEY not in repr(result.stamp)


def test_provider_requires_key_and_satisfies_protocols(settings, clock):
    with pytest.raises(ProviderError) as exc:
        OddsApiProvider("", settings, clock, http=httpx.Client())
    assert exc.value.reason_codes == ["NO_PROVIDER_KEY"]
    provider = OddsApiProvider(API_KEY, settings, clock, http=httpx.Client())
    assert isinstance(provider, base.OddsProvider)
    assert isinstance(provider, base.GameResultsProvider)
    assert provider.name == "the-odds-api"
    assert base.ProviderError is ProviderError
    assert base.empty_quota() == {"requests_remaining": None, "requests_used": None, "requests_last": None}


# --------------------------------------------------------------------------------------
# Manual import
# --------------------------------------------------------------------------------------

PIPE_TEXT = """# legs copied from the app
BOS@DET | SPREAD | HOME | 3.5 | | -110
PHI@NYK | PLAYER_POINTS | OVER | 24.5 | Jalen Brunson | -115
Thunder @ Spurs | ML | AWAY | | | 1.60
"""

CSV_TEXT = """game,market,side,line,player_name,odds_american,odds_decimal,book,observed_at_utc
BOS@DET,SPREAD,HOME,3.5,,-110,,hardrockbet_fl,2026-10-20T18:55:00Z
PHI@NYK,PLAYER_POINTS,OVER,24.5,Jalen Brunson,-115,,hardrockbet_fl,
OKC@SAS,MONEYLINE,AWAY,,,,1.60,,
"""

JSON_TEXT = json.dumps(
    [
        {"game": "BOS@DET", "market": "SPREAD", "side": "HOME", "line": "3.5", "odds_american": -110},
        {
            "game": "PHI@NYK",
            "market": "PLAYER_POINTS",
            "side": "OVER",
            "line": "24.5",
            "player_name": "Jalen Brunson",
            "odds_american": -115,
        },
        {"game": "OKC@SAS", "market": "MONEYLINE", "side": "AWAY", "odds_decimal": "1.60"},
    ]
)


def _check_three(inputs):
    assert [i.market for i in inputs] == [
        S.MarketType.SPREAD,
        S.MarketType.PLAYER_POINTS,
        S.MarketType.MONEYLINE,
    ]
    assert (
        inputs[0].odds_american == -110 and inputs[0].line == Decimal("3.5") and inputs[0].player_name is None
    )
    assert inputs[1].odds_american == -115 and inputs[1].player_name == "Jalen Brunson"
    assert (
        inputs[2].odds_decimal == Decimal("1.60")
        and inputs[2].odds_american is None
        and inputs[2].line is None
    )
    assert all(i.book == "hardrockbet_fl" and i.period == S.Period.FULL_GAME for i in inputs)


def test_parse_pasted_three_formats(tmp_path):
    _check_three(manual.parse_pasted_selections(PIPE_TEXT))
    csv_inputs = manual.parse_pasted_selections(CSV_TEXT)
    _check_three(csv_inputs)
    assert csv_inputs[0].observed_at_utc == datetime(2026, 10, 20, 18, 55, tzinfo=UTC)
    _check_three(manual.parse_pasted_selections(JSON_TEXT))
    path = tmp_path / "legs.csv"
    path.write_text(CSV_TEXT, encoding="utf-8")
    _check_three(manual.load_csv(str(path)))
    _check_three(manual.load_csv(CSV_TEXT))
    jpath = tmp_path / "legs.json"
    jpath.write_text(JSON_TEXT, encoding="utf-8")
    _check_three(manual.load_json(jpath))
    _check_three(manual.load_json(json.dumps({"selections": json.loads(JSON_TEXT)})))


def test_parse_pasted_rejections():
    with pytest.raises(InvalidInput) as exc:
        manual.parse_pasted_selections("BOS@DET | SPREAD | HOME | 3.5 | | 110")
    assert exc.value.reason_codes == ["QUOTE_SIGN_AMBIGUOUS"]
    with pytest.raises(InvalidInput) as exc:
        manual.parse_pasted_selections(
            "game,market,side,line,player_name,odds_american,odds_decimal,book,observed_at_utc\nBOS@DET,SPREAD,HOME,3.5,,150,,,"
        )
    assert exc.value.reason_codes == ["QUOTE_SIGN_AMBIGUOUS"]
    with pytest.raises(InvalidInput) as exc:
        manual.parse_pasted_selections("BOS@DET | SPREAD | HOME | 3.5 |")
    assert exc.value.reason_codes == ["INVALID_INPUT"]
    with pytest.raises(InvalidInput) as exc:
        manual.parse_pasted_selections("BOS@DET | SPREAD | HOME | 3.5 | | ")
    assert exc.value.reason_codes == ["QUOTE_FIELDS_MISSING"]
    with pytest.raises(InvalidInput) as exc:
        manual.parse_pasted_selections(
            '[{"game": "BOS@DET", "market": "SPREAD", "side": "HOME", "line": "3.5"}]'
        )
    assert exc.value.reason_codes == ["QUOTE_FIELDS_MISSING"]
    with pytest.raises(InvalidInput) as exc:
        manual.parse_pasted_selections(
            '[{"game": "BOS@DET", "market": "SPREAD", "side": "HOME", "line": "3.5", "odds_american": -110, "odds_decimal": "2.50"}]'
        )
    assert exc.value.reason_codes == ["QUOTE_SIGN_AMBIGUOUS"]
    with pytest.raises(InvalidInput):
        manual.parse_pasted_selections("")
    with pytest.raises(InvalidInput):
        manual.parse_pasted_selections("BOS@DET | HALFTIME_SPREAD | HOME | 3.5 | | -110")
    with pytest.raises(InvalidInput):
        manual.parse_pasted_selections("[not json")


def test_selections_from_inputs_builds_manual_selections(three_game_slate, clock):
    inputs = manual.parse_pasted_selections(CSV_TEXT)
    selections = manual.selections_from_inputs(inputs, three_game_slate, clock)
    assert [s.description for s in selections] == [
        "DET +3.5 (full game)",
        "Jalen Brunson over 24.5 points",
        "OKC moneyline (full game)",
    ]
    for sel in selections:
        assert sel.quote.stamp.data_mode == S.DataMode.MANUAL_INPUT
        assert sel.quote.stamp.source == "user" and sel.quote.stamp.received_at_utc == NOW
        assert sel.quote.book == "hardrockbet_fl" and sel.quote.jurisdiction == "US-FL"
        assert sel.selection_id == S.compute_selection_id(sel.quote)
    assert selections[0].quote.stamp.source_timestamp_utc == datetime(2026, 10, 20, 18, 55, tzinfo=UTC)
    assert selections[1].quote.stamp.source_timestamp_utc is None
    assert selections[0].quote.odds_decimal == Decimal("1.9091") and selections[0].quote.odds_american == -110
    assert selections[0].team == TEAMS["DET"] and selections[0].quote.team_id == "nba:DET"
    assert selections[1].player is not None and selections[1].player.player_id == "player:jalen-brunson"
    assert selections[2].quote.odds_decimal == Decimal("1.60") and selections[2].quote.team_id == "nba:OKC"


@pytest.mark.parametrize(
    ("item", "code"),
    [
        (
            {"game": "MIA@ORL", "market": "SPREAD", "side": "HOME", "line": "3.5", "odds_american": -110},
            "EVENT_UNMATCHED",
        ),
        (
            {
                "game": "PHI@NYK",
                "market": "PLAYER_POINTS",
                "side": "OVER",
                "line": "24.5",
                "odds_american": -115,
            },
            "PLAYER_UNMATCHED",
        ),
        (
            {
                "game": "BOS@DET",
                "market": "SPREAD",
                "side": "HOME",
                "line": "3.5",
                "odds_american": -110,
                "book": "hardrockbet",
            },
            "WRONG_BOOK",
        ),
        (
            {
                "game": "BOS@DET",
                "market": "SPREAD",
                "side": "HOME",
                "line": "3.5",
                "odds_american": -110,
                "book": "draftkings",
            },
            "WRONG_BOOK",
        ),
        (
            {
                "game": "BOS@DET",
                "market": "SPREAD",
                "side": "HOME",
                "line": "3.5",
                "odds_american": -110,
                "period": "FIRST_HALF",
            },
            "PERIOD_UNSUPPORTED",
        ),
        (
            {"game": "BOS@DET", "market": "SPREAD", "side": "HOME", "odds_american": -110},
            "QUOTE_FIELDS_MISSING",
        ),
        (
            {"game": "BOS@DET", "market": "TOTAL", "side": "HOME", "line": "221.5", "odds_american": -110},
            "INVALID_INPUT",
        ),
    ],
)
def test_selections_from_inputs_rejections(three_game_slate, clock, item, code):
    inputs = [S.ManualSelectionInput.model_validate(item)]
    with pytest.raises(InvalidInput) as exc:
        manual.selections_from_inputs(inputs, three_game_slate, clock)
    assert exc.value.reason_codes == [code]


def test_selections_from_inputs_sign_ambiguity_from_text(three_game_slate, clock):
    with pytest.raises(InvalidInput) as exc:
        manual.selections_from_inputs(
            manual.parse_pasted_selections("BOS@DET | SPREAD | HOME | 3.5 | | 110"), three_game_slate, clock
        )
    assert exc.value.reason_codes == ["QUOTE_SIGN_AMBIGUOUS"]


def test_slip_fields_from_extraction_lists_every_ambiguity():
    fields = {
        "legs": [
            {
                "game": "BOS@DET",
                "market": "SPREAD",
                "side": "HOME",
                "line": "3.5",
                "odds": "110",
                "text": "Pistons +3.5 110",
            },
            {
                "game": "PHI@NYK",
                "market": "PLAYER_POINTS",
                "side": "OVER",
                "line": "",
                "player": "",
                "odds": "-115",
            },
            {
                "game": "OKC@SAS",
                "market": "MONEYLINE",
                "side": "AWAY",
                "odds": "1.60",
                "text": "Thunder ML 1.60",
            },
        ],
        "combined_odds": "650",
        "stake": "",
        "payout": "$75.00",
        "payout_includes_stake": None,
        "captured_at_utc": "2026-10-20T18:55:00Z",
    }
    quote, legs, unresolved = manual.slip_fields_from_extraction(fields)
    assert unresolved == [
        "legs[0].odds_sign",
        "legs[1].line",
        "legs[1].player",
        "combined_odds",
        "stake",
        "payout_includes_stake",
    ]
    assert quote.user_confirmed is False
    assert quote.source == S.QuoteSource.SCREENSHOT_EXTRACTED
    assert quote.combined_decimal is None and quote.combined_american is None
    assert quote.payout_shown_usd == Decimal("75.00") and quote.stake_shown_usd is None
    assert quote.legs_as_shown == [
        "Pistons +3.5 110",
        "PHI@NYK | PLAYER_POINTS | OVER | -115",
        "Thunder ML 1.60",
    ]
    assert quote.captured_at_utc == datetime(2026, 10, 20, 18, 55, tzinfo=UTC)
    assert len(legs) == 1 and legs[0].game == "OKC@SAS" and legs[0].odds_decimal == Decimal("1.60")
    clean = {
        "legs": [{"game": "BOS@DET", "market": "SPREAD", "side": "HOME", "line": "3.5", "odds": "-110"}],
        "combined_odds": "+650",
        "stake": "10",
        "payout": "75.00",
        "payout_includes_stake": True,
        "source": "RECEIPT",
    }
    quote, legs, unresolved = manual.slip_fields_from_extraction(clean)
    assert unresolved == [] and quote.combined_american == 650 and quote.source == S.QuoteSource.RECEIPT
    assert quote.user_confirmed is False and len(legs) == 1 and legs[0].odds_american == -110


# --------------------------------------------------------------------------------------
# Packaged fixture slate
# --------------------------------------------------------------------------------------


def test_fixture_slate_real_schedule_synthetic_prices():
    assert "opening_night_2026_10_20" in available_fixtures()
    slate = load_fixture_slate("opening_night_2026_10_20")
    assert isinstance(slate, FixtureSlate)
    events, target, reference, injuries = slate  # tuple unpacking per the contract
    assert [(e.event_id, e.commence_time_utc) for e in events] == [
        ("fixture:BOS@DET", datetime(2026, 10, 20, 19, 0, tzinfo=UTC)),
        ("fixture:PHI@NYK", datetime(2026, 10, 20, 23, 0, tzinfo=UTC)),
        ("fixture:OKC@SAS", datetime(2026, 10, 21, 1, 30, tzinfo=UTC)),
    ]
    assert all(e.status == S.EventStatus.SCHEDULED and e.season_stage == "REGULAR" for e in events)
    stamps = [e.stamp for e in events] + [q.stamp for q in target + reference] + [i.stamp for i in injuries]
    assert all(
        s.data_mode == S.DataMode.FIXTURE and s.source == "fixture:opening-night-2026-10-20" for s in stamps
    )
    assert {q.book for q in target} == {"hardrockbet_fl"} and all(q.jurisdiction == "US-FL" for q in target)
    assert {q.book for q in reference} == {"pinnacle"}
    for event in events:
        for market in (S.MarketType.MONEYLINE, S.MarketType.SPREAD, S.MarketType.TOTAL):
            for quotes in (target, reference):
                sides = {q.side for q in quotes if q.event_id == event.event_id and q.market_type == market}
                assert sides == (
                    {S.Side.HOME, S.Side.AWAY}
                    if market != S.MarketType.TOTAL
                    else {S.Side.OVER, S.Side.UNDER}
                ), (event.event_id, market)
    assert any(q.is_alternate for q in target)
    assert len(injuries) == 16
    assert all(i.report_timestamp_utc == datetime(2026, 10, 19, 23, 0, tzinfo=UTC) for i in injuries)
    assert sum(1 for i in injuries if i.designation == S.InjuryDesignation.OUT) == 11
    assert sum(1 for i in injuries if i.designation == S.InjuryDesignation.QUESTIONABLE) == 5
    assert slate.events_by_id["fixture:PHI@NYK"].home_team == TEAMS["NYK"]
    assert len(slate.quotes) == len(target) + len(reference)
    with pytest.raises(NotFound):
        load_fixture_slate("no_such_fixture")


def test_fixture_slate_received_at_follows_now_and_pairs_references():
    now = NOW - timedelta(hours=5)
    slate = load_fixture_slate(now=now)
    assert all(
        q.stamp.received_at_utc == now and q.stamp.source_timestamp_utc == now - timedelta(seconds=30)
        for q in slate.quotes
    )
    selections = N.build_selections(slate.target_quotes, slate.events)
    brunson = next(
        s
        for s in selections
        if s.player
        and s.player.player_id == "player:jalen-brunson"
        and s.quote.side == S.Side.OVER
        and not s.quote.is_alternate
    )
    ref, reasons = N.pair_reference_with_reasons(brunson, slate.reference_quotes)
    assert reasons == [] and ref is not None and ref.book == "pinnacle" and ref.line == Decimal("24.5")
    maxey = next(
        s
        for s in selections
        if s.player and s.player.player_id == "player:tyrese-maxey" and s.quote.side == S.Side.OVER
    )
    assert N.pair_reference_with_reasons(maxey, slate.reference_quotes) == (None, ["LINE_MISMATCH"])
    spread_away = next(
        s
        for s in selections
        if s.quote.market_type == S.MarketType.SPREAD
        and s.quote.side == S.Side.AWAY
        and s.event.event_id == "fixture:BOS@DET"
    )
    ref = N.pair_reference(spread_away, slate.reference_quotes)
    assert ref is not None and ref.line == Decimal("4.5") and ref.odds_for(S.Side.AWAY) == Decimal("1.89")
    for sel in selections:
        if sel.quote.market_type in (S.MarketType.MONEYLINE, S.MarketType.SPREAD, S.MarketType.TOTAL):
            assert N.pair_reference(sel, slate.reference_quotes) is not None, sel.description


def test_fixture_events_match_manual_game_text():
    slate = load_fixture_slate()
    assert N.match_event("Celtics @ Pistons", slate.events).event_id == "fixture:BOS@DET"
    assert make_event("BOS", "DET").home_team == slate.events[0].home_team


# --------------------------------------------------------------------------------------
# Manual TEAM_TOTAL legs (ManualSelectionInput.team) and slip-extraction team totals
# --------------------------------------------------------------------------------------


def test_manual_team_total_from_pipe_and_csv(three_game_slate, clock):
    # pipe: the subject column names the team for a team-total leg; CSV: optional `team` column
    (pipe,) = manual.parse_pasted_selections("PHI@NYK | TEAM_TOTAL | OVER | 115.5 | Knicks | -110")
    assert pipe.team == "Knicks" and pipe.player_name is None
    (csv_row,) = manual.parse_pasted_selections(
        "game,market,side,line,player_name,team,odds_american\nPHI@NYK,TEAM_TOTAL,UNDER,109.5,,PHI,-115\n"
    )
    assert csv_row.team == "PHI"
    sels = manual.selections_from_inputs([pipe, csv_row], three_game_slate, clock)
    assert [s.description for s in sels] == [
        "NYK team total over 115.5 (full game)",
        "PHI team total under 109.5 (full game)",
    ]
    assert [s.quote.team_id for s in sels] == ["nba:NYK", "nba:PHI"]
    assert all(s.team is not None and s.team.team_id == s.quote.team_id for s in sels)
    # a team that is not playing in the matched game is rejected, never guessed
    wrong = pipe.model_copy(update={"team": "BOS"})
    with pytest.raises(InvalidInput) as exc:
        manual.selections_from_inputs([wrong], three_game_slate, clock)
    assert exc.value.reason_codes == ["TEAM_UNMATCHED"]
    # an unknown team name is TEAM_UNMATCHED too
    unknown = pipe.model_copy(update={"team": "Knickerbockers"})
    with pytest.raises(InvalidInput) as exc:
        manual.selections_from_inputs([unknown], three_game_slate, clock)
    assert exc.value.reason_codes == ["TEAM_UNMATCHED"]


def test_slip_extraction_team_total_needs_a_team():
    fields = {
        "legs": [
            {"game": "PHI@NYK", "market": "TEAM_TOTAL", "side": "OVER", "line": "115.5", "odds": "-110"}
        ],
        "combined_odds": "+120",
        "stake": "10",
        "payout": "22.00",
        "payout_includes_stake": True,
    }
    quote, legs, unresolved = manual.slip_fields_from_extraction(fields)
    assert legs == [] and unresolved == ["legs[0].team"]
    fields["legs"][0]["team"] = "NYK"
    quote, legs, unresolved = manual.slip_fields_from_extraction(fields)
    assert unresolved == [] and len(legs) == 1 and legs[0].team == "NYK"
