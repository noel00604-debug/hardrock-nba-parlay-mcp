"""Shared test fixtures. Everything here is FIXTURE data; nothing touches the network or a real ledger."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.config import FixedClock, Settings
from hardrock_nba_parlay.db import Database, open_database

# 2026-10-20 15:00 ET == 19:00 UTC (EDT, UTC-4)
NOW = datetime(2026, 10, 20, 19, 0, tzinfo=UTC)

TEAMS = {
    "BOS": S.Team(team_id="nba:BOS", name="Boston Celtics", abbreviation="BOS"),
    "DET": S.Team(team_id="nba:DET", name="Detroit Pistons", abbreviation="DET"),
    "PHI": S.Team(team_id="nba:PHI", name="Philadelphia 76ers", abbreviation="PHI"),
    "NYK": S.Team(team_id="nba:NYK", name="New York Knicks", abbreviation="NYK"),
    "OKC": S.Team(team_id="nba:OKC", name="Oklahoma City Thunder", abbreviation="OKC"),
    "SAS": S.Team(team_id="nba:SAS", name="San Antonio Spurs", abbreviation="SAS"),
}


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture
def settings(tmp_path) -> Settings:
    os.environ.pop("HRNBA_ODDS_API_KEY", None)
    return Settings(
        data_dir=tmp_path, database_url=f"sqlite:///{tmp_path / 'test.db'}", allow_fixture_ledger=True
    )


@pytest.fixture
def db(settings) -> Database:
    database = open_database(settings.effective_database_url, allow_fixture_ledger=True)
    yield database
    database.dispose()


@pytest.fixture
def strict_db(tmp_path) -> Database:
    """A ledger that refuses FIXTURE-mode records, like production."""
    database = open_database(f"sqlite:///{tmp_path / 'strict.db'}", allow_fixture_ledger=False)
    yield database
    database.dispose()


def stamp(
    *,
    source: str = "fixture:test",
    mode: S.DataMode = S.DataMode.FIXTURE,
    at: datetime = NOW,
    source_ts: datetime | None = None,
) -> S.SourceStamp:
    return S.SourceStamp(
        source=source,
        source_url=None,
        source_record_id=None,
        source_timestamp_utc=source_ts if source_ts is not None else at - timedelta(seconds=30),
        received_at_utc=at,
        data_mode=mode,
    )


def make_event(
    away: str, home: str, *, start: datetime | None = None, event_id: str | None = None
) -> S.Event:
    start = start or (NOW + timedelta(hours=4))
    return S.Event(
        event_id=event_id or f"fixture:{away}@{home}",
        season_stage="REGULAR",
        home_team=TEAMS[home],
        away_team=TEAMS[away],
        commence_time_utc=start,
        status=S.EventStatus.SCHEDULED,
        stamp=stamp(),
    )


def make_quote(
    event: S.Event,
    market: S.MarketType,
    side: S.Side,
    odds_decimal: str,
    *,
    line: str | None = None,
    player: str | None = None,
    team: S.Team | None = None,
    book: str = "hardrockbet_fl",
    is_alternate: bool = False,
    at: datetime = NOW,
    source_ts: datetime | None = None,
) -> S.MarketQuote:
    player_id = f"player:{player.lower().replace(' ', '-')}" if player else None
    return S.MarketQuote(
        quote_id=f"q:{book}:{event.event_id}:{market}:{side}:{line}:{player or (team.team_id if team else '')}",
        event_id=event.event_id,
        book=book,
        jurisdiction="US-FL" if book == "hardrockbet_fl" else None,
        market_type=market,
        period=S.Period.FULL_GAME,
        is_alternate=is_alternate,
        side=side,
        team_id=team.team_id if team else None,
        player_id=player_id,
        player_name_raw=player,
        line=Decimal(line) if line is not None else None,
        odds_american=None,
        odds_decimal=Decimal(odds_decimal),
        stamp=stamp(at=at, source_ts=source_ts),
    )


def make_selection(quote: S.MarketQuote, event: S.Event, description: str | None = None) -> S.Selection:
    team = None
    if quote.team_id:
        team = next((t for t in TEAMS.values() if t.team_id == quote.team_id), None)
    player = (
        S.Player(player_id=quote.player_id, name=quote.player_name_raw or "", team_id=quote.team_id)
        if quote.player_id
        else None
    )
    return S.Selection(
        selection_id=S.compute_selection_id(quote),
        quote=quote,
        event=event,
        team=team,
        player=player,
        description=description
        or f"{quote.market_type} {quote.side} {quote.line or ''} {quote.player_name_raw or quote.team_id or ''}".strip(),
    )


def make_reference(
    event: S.Event,
    market: S.MarketType,
    odds_a: str,
    odds_b: str,
    *,
    line: str | None = None,
    player: str | None = None,
    book: str = "pinnacle",
    at: datetime = NOW,
    source_ts: datetime | None = None,
) -> S.ReferenceTwoWay:
    team_market = market in (S.MarketType.MONEYLINE, S.MarketType.SPREAD)
    return S.ReferenceTwoWay(
        book=book,
        event_id=event.event_id,
        market_type=market,
        period=S.Period.FULL_GAME,
        player_id=f"player:{player.lower().replace(' ', '-')}" if player else None,
        line=Decimal(line) if line is not None else None,
        side_a=S.Side.HOME if team_market else S.Side.OVER,
        odds_a=Decimal(odds_a),
        side_b=S.Side.AWAY if team_market else S.Side.UNDER,
        odds_b=Decimal(odds_b),
        stamp=stamp(at=at, source_ts=source_ts),
    )


@pytest.fixture
def three_game_slate() -> list[S.Event]:
    return [
        make_event("BOS", "DET", start=datetime(2026, 10, 20, 19, 0, tzinfo=UTC) + timedelta(hours=4)),
        make_event("PHI", "NYK", start=datetime(2026, 10, 20, 23, 0, tzinfo=UTC) + timedelta(hours=1)),
        make_event("OKC", "SAS", start=datetime(2026, 10, 21, 1, 30, tzinfo=UTC) + timedelta(hours=1)),
    ]


@pytest.fixture
def three_multi_game_legs(three_game_slate) -> list[S.Selection]:
    e1, e2, e3 = three_game_slate
    q1 = make_quote(e1, S.MarketType.SPREAD, S.Side.HOME, "1.9091", line="3.5", team=TEAMS["DET"])
    q2 = make_quote(e2, S.MarketType.TOTAL, S.Side.OVER, "1.9091", line="224.5")
    q3 = make_quote(e3, S.MarketType.MONEYLINE, S.Side.AWAY, "1.6667", team=TEAMS["OKC"])
    return [
        make_selection(q1, e1, "DET +3.5"),
        make_selection(q2, e2, "PHI/NYK over 224.5"),
        make_selection(q3, e3, "OKC ML"),
    ]
