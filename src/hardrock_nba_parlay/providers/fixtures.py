"""Offline fixture slates (docs/ARCHITECTURE.md section 5, "providers/fixtures.py").

A fixture carries the REAL schedule for its date but SYNTHETIC prices that are clearly not quotes anyone
could bet. Every stamp has ``data_mode=FIXTURE`` and ``source="fixture:<name>"`` so the ledger refuses the
records and every response shows the mode. Package data lives in ``hardrock_nba_parlay/fixtures/``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from importlib import resources
from typing import Any, NamedTuple

from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.errors import NotFound
from hardrock_nba_parlay.normalization import canonical_player, canonical_team

__all__ = ["FixtureSlate", "available_fixtures", "load_fixture_slate"]

_PACKAGE = "hardrock_nba_parlay.fixtures"
_DESIGNATIONS = {d.value.lower(): d for d in S.InjuryDesignation}


class FixtureSlate(NamedTuple):
    """Events, target-book quotes, reference quotes and injuries, all stamped FIXTURE."""

    events: list[S.Event]
    target_quotes: list[S.MarketQuote]
    reference_quotes: list[S.MarketQuote]
    injuries: list[S.InjuryContext]

    @property
    def quotes(self) -> list[S.MarketQuote]:
        return [*self.target_quotes, *self.reference_quotes]

    @property
    def events_by_id(self) -> dict[str, S.Event]:
        return {e.event_id: e for e in self.events}


def available_fixtures() -> list[str]:
    """Names of the packaged fixture slates (file stem without ``.json``)."""
    names: list[str] = []
    for entry in resources.files(_PACKAGE).iterdir():
        if entry.name.endswith(".json"):
            names.append(entry.name.removesuffix(".json"))
    return sorted(names)


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _stamp(
    source: str, received_at: datetime, source_ts: datetime | None, record_id: str | None = None
) -> S.SourceStamp:
    return S.SourceStamp(
        source=source,
        source_url=None,
        source_record_id=record_id,
        source_timestamp_utc=source_ts,
        received_at_utc=received_at,
        data_mode=S.DataMode.FIXTURE,
    )


def _quote(
    raw: dict[str, Any], source: str, received_at: datetime, source_ts: datetime, target_book: str
) -> S.MarketQuote:
    market = S.MarketType(raw["market"])
    side = S.Side(raw["side"])
    line = Decimal(str(raw["line"])) if raw.get("line") is not None else None
    team_id = canonical_team(raw["team"]).team_id if raw.get("team") else None
    player_id = None
    player_name = None
    if raw.get("player"):
        player = canonical_player(raw["player"], None)
        player_id, player_name = player.player_id, player.name
    book = raw["book"]
    line_text = format(line.normalize(), "f") if line is not None else ""
    quote_id = f"{source}:{raw['event_id']}:{book}:{market.value}:{side.value}:{line_text}:{player_id or team_id or ''}:{'alt' if raw.get('is_alternate') else 'main'}"
    return S.MarketQuote(
        quote_id=quote_id,
        event_id=raw["event_id"],
        book=book,
        jurisdiction="US-FL" if book == target_book else None,
        market_type=market,
        period=S.Period(raw.get("period", "FULL_GAME")),
        is_alternate=bool(raw.get("is_alternate", False)),
        side=side,
        team_id=team_id,
        player_id=player_id,
        player_name_raw=player_name,
        line=line,
        odds_american=raw.get("odds_american"),
        odds_decimal=Decimal(str(raw["odds_decimal"])),
        stamp=_stamp(source, received_at, source_ts, raw["event_id"]),
    )


def load_fixture_slate(
    name: str = "opening_night_2026_10_20",
    now: datetime | None = None,
    *,
    target_book: str = "hardrockbet_fl",
) -> FixtureSlate:
    """Load a packaged fixture by name.

    ``now`` sets ``received_at_utc`` on every stamp; quote source timestamps are placed 30 s earlier so the slate
    is fresh relative to ``now``. When ``now`` is omitted the file's own ``received_at_utc`` is used. The injury
    report timestamp is always the fixed value in the file (it is a public fact about that report).
    """
    try:
        text = resources.files(_PACKAGE).joinpath(f"{name}.json").read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        raise NotFound(f"fixture {name!r} not found; available: {', '.join(available_fixtures())}") from None
    raw = json.loads(text)
    if raw.get("data_mode") != S.DataMode.FIXTURE.value:
        raise NotFound(f"fixture {name!r} is not labelled FIXTURE")
    source = raw["source"]
    received_at = now.astimezone(UTC) if now is not None else _ts(raw["received_at_utc"])
    source_ts = received_at - timedelta(seconds=int(raw.get("quote_age_seconds", 30)))

    events: list[S.Event] = []
    for e in raw["events"]:
        commence = _ts(e["commence_time_utc"])
        events.append(
            S.Event(
                event_id=e["event_id"],
                season_stage=e.get("season_stage", "REGULAR"),
                home_team=canonical_team(e["home"]),
                away_team=canonical_team(e["away"]),
                commence_time_utc=commence,
                status=S.EventStatus.LIVE if commence <= received_at else S.EventStatus.SCHEDULED,
                stamp=_stamp(source, received_at, None, e["event_id"]),
            )
        )
    event_ids = {e.event_id for e in events}
    target: list[S.MarketQuote] = []
    reference: list[S.MarketQuote] = []
    for q in raw["quotes"]:
        if q["event_id"] not in event_ids:
            raise NotFound(f"fixture quote references unknown event {q['event_id']}")
        quote = _quote(q, source, received_at, source_ts, target_book)
        (target if quote.book == target_book else reference).append(quote)

    report_ts = _ts(raw["injury_report_timestamp_utc"]) if raw.get("injury_report_timestamp_utc") else None
    injuries: list[S.InjuryContext] = []
    for inj in raw.get("injuries", []):
        team_id = canonical_team(inj["team"]).team_id if inj.get("team") else None
        player_name = inj.get("player")
        player_id = None
        if player_name and player_name.upper() != "NOT YET SUBMITTED":
            player_id = canonical_player(player_name, None).player_id
        injuries.append(
            S.InjuryContext(
                event_id=inj["event_id"],
                team_id=team_id,
                player_id=player_id,
                player_name_raw=player_name,
                designation=_DESIGNATIONS[str(inj["status"]).lower()],
                reason=inj.get("reason"),
                report_timestamp_utc=report_ts,
                stamp=_stamp(source, received_at, report_ts, raw.get("injury_report_url")),
                material_to_selection=None,
                note=inj.get("note"),
            )
        )
    return FixtureSlate(events=events, target_quotes=target, reference_quotes=reference, injuries=injuries)
