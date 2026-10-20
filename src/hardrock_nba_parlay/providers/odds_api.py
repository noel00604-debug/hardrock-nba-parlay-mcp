"""The Odds API v4 adapter (docs/ARCHITECTURE.md section 5; docs/research/the-odds-api.md).

Facts this adapter is built on (all from the vendor docs quoted in the research note):

- Host ``https://api.the-odds-api.com/v4``; the key goes in the ``apiKey`` query parameter. The key is never
  logged and never stored in a stamp: every ``source_url`` is built without it and every exception string
  passes through ``config.redact``.
- Sport key ``basketball_nba`` only. ``basketball_nba_preseason`` is never requested.
- Credit cost rules: ``/sports`` and ``/sports/{sport}/events`` are free; ``/odds`` costs
  ``markets x regions`` where "every group of 10 bookmakers is the equivalent of 1 region" (so
  ``len(markets) * ceil(len(books) / 10)``) and "if no events are returned, the request will not count";
  ``/events/{id}/odds`` costs ``unique markets returned x regions`` ("responses with empty data do not count");
  ``/events/{id}/markets`` costs 1; ``/scores`` costs 2 with ``daysFrom`` and 1 without.
- Quota headers on every call: ``x-requests-remaining``, ``x-requests-used``, ``x-requests-last``.
- Market-level ``last_update`` is the recency field ("the bookmaker-level last_update field is deprecated").
- ``/events`` carries no update time, so event stamps have ``source_timestamp_utc=None``.
- 401 means missing/invalid key OR "at its usage limit"; 404 on event endpoints means the event expired;
  422 means bad query params; 429 means throttled ("consider retrying the request after a couple of seconds").
- Vendor caching advice: ``/sports`` for an hour, ``/events`` for 10 minutes.

Quotes are keyed by the exact bookmaker key the API returns. ``hardrockbet`` (Indiana), ``hardrockbet_az`` and
``hardrockbet_oh`` are never substituted for ``hardrockbet_fl``.

Conventions that are easy to get wrong:

- The slate day and the daily credit guard are America/New_York days (``config.DEFAULT_TZ``), the same calendar
  the ledger uses for ``date_local``; ``settings.display_tz`` only affects display strings elsewhere.
- A cache hit makes no request, so the result reports ``credits_cost=0`` and every stamp keeps the
  ``received_at_utc`` of the request that actually fetched the data (``ProviderResult.cached`` says which).
- The ``httpx`` request log line carries the full URL; ``providers.base.install_http_log_redaction`` strips the
  ``apiKey`` parameter from those records at construction time.
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import func, insert, select

from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.config import DEFAULT_TZ, Clock, Settings, local_day_bounds_utc, redact, today_local
from hardrock_nba_parlay.db import Database, iso, provider_usage
from hardrock_nba_parlay.errors import InvalidInput, ProviderError
from hardrock_nba_parlay.normalization import canonical_player, try_canonical_team
from hardrock_nba_parlay.providers.base import (
    ProviderResult,
    empty_quota,
    install_http_log_redaction,
    validate_local_date,
)

__all__ = [
    "FEATURED_MARKET_KEYS",
    "KEY_TO_MARKET",
    "MAX_REQUESTS_PER_SECOND",
    "OddsApiProvider",
    "PROP_MARKET_KEYS",
    "SPORT_KEY",
    "credits_for_books",
]

logger = logging.getLogger(__name__)

SPORT_KEY = "basketball_nba"
_ONE_SECOND = timedelta(seconds=1)
PROVIDER_NAME = "the-odds-api"
MAX_REQUESTS_PER_SECOND = 5
BACKOFF_INITIAL_SECONDS = 0.5
CACHE_TTL_SPORTS = 3600
CACHE_TTL_EVENTS = 600

FEATURED_MARKET_KEYS: dict[S.MarketType, str] = {
    S.MarketType.MONEYLINE: "h2h",
    S.MarketType.SPREAD: "spreads",
    S.MarketType.TOTAL: "totals",
}
PROP_MARKET_KEYS: dict[S.MarketType, str] = {
    S.MarketType.PLAYER_POINTS: "player_points",
    S.MarketType.PLAYER_REBOUNDS: "player_rebounds",
    S.MarketType.PLAYER_ASSISTS: "player_assists",
    S.MarketType.PLAYER_THREES: "player_threes",
}
# market key -> (market type, is_alternate)
KEY_TO_MARKET: dict[str, tuple[S.MarketType, bool]] = {
    "h2h": (S.MarketType.MONEYLINE, False),
    "spreads": (S.MarketType.SPREAD, False),
    "totals": (S.MarketType.TOTAL, False),
    "alternate_spreads": (S.MarketType.SPREAD, True),
    "alternate_totals": (S.MarketType.TOTAL, True),
    "team_totals": (S.MarketType.TEAM_TOTAL, False),
    "alternate_team_totals": (S.MarketType.TEAM_TOTAL, True),
    **{key: (mt, False) for mt, key in PROP_MARKET_KEYS.items()},
    **{f"{key}_alternate": (mt, True) for mt, key in PROP_MARKET_KEYS.items()},
}


def credits_for_books(markets: int, books: int) -> int:
    """Documented cost: markets x regions, where every group of up to 10 bookmakers equals one region."""
    if markets <= 0 or books <= 0:
        return 0
    return markets * math.ceil(books / 10)


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value), tz=UTC)
    text = str(value).replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _int_header(headers: httpx.Headers, name: str) -> int | None:
    raw = headers.get(name)
    if raw is None:
        return None
    try:
        return int(float(raw))
    except ValueError:
        return None


def _strip_event_prefix(event_id: str) -> str:
    return event_id.removeprefix("oddsapi:")


@dataclass(slots=True)
class _Response:
    data: Any
    headers: httpx.Headers
    url: str  # without apiKey
    cached: bool
    received_at: datetime  # when the data was actually fetched (the original request time on a cache hit)


@dataclass(slots=True)
class _CacheEntry:
    expires_at: datetime
    data: Any
    headers: httpx.Headers
    url: str
    received_at: datetime


@dataclass(slots=True)
class _Mapped:
    """Accumulator for one response: only quotes for the requested bookmakers and market keys are emitted.

    The vendor returns exactly what was requested; anything else in a body is reported in ``warnings`` and
    never mapped, so an unrequested bookmaker (another state's Hard Rock feed, say) can never leak into the
    quotes and ``market_keys_seen`` (the credit estimate) counts requested markets only.
    """

    requested_books: frozenset[str]
    requested_keys: frozenset[str]
    quotes: list[S.MarketQuote] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    books_seen: set[str] = field(default_factory=set)
    market_keys_seen: set[str] = field(default_factory=set)
    ignored: set[str] = field(default_factory=set)

    def ignore(self, label: str, message: str) -> None:
        """Record one warning per ignored bookmaker/market key."""
        if label not in self.ignored:
            self.ignored.add(label)
            self.warnings.append(message)


class OddsApiProvider:
    """Odds, events and scores from The Odds API v4 for ``basketball_nba``."""

    name = PROVIDER_NAME

    def __init__(
        self,
        api_key: str,
        settings: Settings,
        clock: Clock,
        http: httpx.Client | None = None,
        db: Database | None = None,
        *,
        sleep: Callable[[float], None] | None = None,
        monotonic: Callable[[], float] | None = None,
        user_id: str | None = None,
    ) -> None:
        if not api_key:
            raise ProviderError("The Odds API key is not configured", ["NO_PROVIDER_KEY"])
        self._api_key = api_key
        self.settings = settings
        self.clock = clock
        self.http = http or httpx.Client(timeout=settings.http_timeout_seconds)
        # httpx logs "HTTP Request: GET <url>" at INFO with the apiKey parameter in the URL; strip it there.
        install_http_log_redaction(api_key)
        self.db = db
        self.user_id = user_id
        self._sleep = sleep or time.sleep
        self._monotonic = monotonic or time.monotonic
        self._cache: dict[tuple[str, tuple[tuple[str, str], ...]], _CacheEntry] = {}
        self._recent: deque[float] = deque()
        self._memory_credits: dict[str, int] = {}
        self.last_quota: dict[str, int | None] = empty_quota()
        self.last_ok_utc: datetime | None = None

    # ------------------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------------------

    def list_events(self, date_local: str, *, force: bool = False) -> ProviderResult[list[S.Event]]:
        """NBA events whose commence time falls inside the ET calendar day ``date_local`` (free; cached 600 s)."""
        start, end = local_day_bounds_utc(validate_local_date(date_local), DEFAULT_TZ)
        params = {
            "commenceTimeFrom": _iso_z(start),
            "commenceTimeTo": _iso_z(end.replace(microsecond=0) - _ONE_SECOND),
            "dateFormat": "iso",
        }
        resp = self._get(
            f"/sports/{SPORT_KEY}/events", params, estimated_cost=0, ttl=CACHE_TTL_EVENTS, force=force
        )
        now = self.clock.now_utc()
        events: list[S.Event] = []
        warnings: list[str] = []
        for raw in resp.data:
            event = self._map_event(raw, now, resp.received_at, resp.url, warnings)
            if event is not None:
                events.append(event)
        credits = 0
        if not resp.cached:
            self._record_usage(f"/sports/{SPORT_KEY}/events", credits)
        return ProviderResult(
            data=events,
            stamp=self._stamp(resp.url, None, None, resp.received_at),
            credits_cost=credits,
            quota=dict(self.last_quota),
            warnings=warnings,
            cached=resp.cached,
        )

    def fetch_featured_odds(
        self,
        date_local: str,
        books: list[str],
        markets: list[S.MarketType],
        *,
        force: bool = False,
    ) -> ProviderResult[list[S.MarketQuote]]:
        """h2h/spreads/totals for the ET day at the given bookmaker keys (cost ``markets x ceil(books/10)``)."""
        if not books:
            raise InvalidInput("at least one bookmaker key is required", ["INVALID_INPUT"])
        keys: list[str] = []
        warnings: list[str] = []
        for market in markets:
            key = FEATURED_MARKET_KEYS.get(market)
            if key is None:
                warnings.append(
                    f"MARKET_NOT_OFFERED: {market.value} is not a featured market; use fetch_event_props"
                )
            elif key not in keys:
                keys.append(key)
        if not keys:
            raise InvalidInput("no featured markets requested (MONEYLINE/SPREAD/TOTAL)", ["INVALID_INPUT"])
        start, end = local_day_bounds_utc(validate_local_date(date_local), DEFAULT_TZ)
        params = {
            "bookmakers": ",".join(books),
            "markets": ",".join(keys),
            "oddsFormat": "decimal",
            "dateFormat": "iso",
            "commenceTimeFrom": _iso_z(start),
            "commenceTimeTo": _iso_z(end.replace(microsecond=0) - _ONE_SECOND),
        }
        estimated = credits_for_books(len(keys), len(books))
        path = f"/sports/{SPORT_KEY}/odds"
        resp = self._get(
            path, params, estimated_cost=estimated, ttl=self.settings.provider_cache_ttl_seconds, force=force
        )
        mapped = _Mapped(requested_books=frozenset(books), requested_keys=frozenset(keys))
        for raw in resp.data:
            self._map_bookmakers(raw, resp.received_at, resp.url, mapped)
        warnings.extend(mapped.warnings)
        reason_codes: list[str] = []
        if not resp.data:
            warnings.append(
                f"no NBA events returned for {date_local}; the call is free per the vendor's cost rule"
            )
        self._target_book_check(books, mapped.books_seen, warnings, reason_codes)
        # "If no events are returned, the request will not count against the usage quota."
        credits = estimated if resp.data else 0
        if resp.cached:
            credits = 0  # no request was made
        else:
            self._record_usage(path, credits)
        return ProviderResult(
            data=mapped.quotes,
            stamp=self._stamp(resp.url, None, None, resp.received_at),
            credits_cost=credits,
            quota=dict(self.last_quota),
            warnings=warnings,
            reason_codes=reason_codes,
            cached=resp.cached,
        )

    def fetch_event_props(
        self,
        event_id: str,
        books: list[str],
        markets: list[S.MarketType],
        include_alternates: bool,
        *,
        force: bool = False,
    ) -> ProviderResult[list[S.MarketQuote]]:
        """Player props (and alternates/team totals) for one event via ``/events/{id}/odds``.

        Market mapping: PLAYER_* -> ``player_*`` (plus ``player_*_alternate`` when ``include_alternates``);
        SPREAD/TOTAL -> ``alternate_spreads``/``alternate_totals`` only when ``include_alternates`` (the main
        lines come from ``fetch_featured_odds``); TEAM_TOTAL -> ``team_totals`` (plus ``alternate_team_totals``).
        Cost is ``unique markets returned x ceil(books/10)``; a 404 means the event expired.
        """
        if not books:
            raise InvalidInput("at least one bookmaker key is required", ["INVALID_INPUT"])
        keys: list[str] = []
        warnings: list[str] = []
        for market in markets:
            if market in PROP_MARKET_KEYS:
                keys.append(PROP_MARKET_KEYS[market])
                if include_alternates:
                    keys.append(PROP_MARKET_KEYS[market] + "_alternate")
            elif market == S.MarketType.SPREAD:
                if include_alternates:
                    keys.append("alternate_spreads")
            elif market == S.MarketType.TOTAL:
                if include_alternates:
                    keys.append("alternate_totals")
            elif market == S.MarketType.TEAM_TOTAL:
                keys.append("team_totals")
                if include_alternates:
                    keys.append("alternate_team_totals")
            else:
                warnings.append(
                    f"MARKET_NOT_OFFERED: {market.value} main line comes from fetch_featured_odds"
                )
        keys = list(dict.fromkeys(keys))
        if not keys:
            raise InvalidInput("no event markets to request", ["INVALID_INPUT"])
        raw_id = _strip_event_prefix(event_id)
        params = {
            "bookmakers": ",".join(books),
            "markets": ",".join(keys),
            "oddsFormat": "decimal",
            "dateFormat": "iso",
        }
        path = f"/sports/{SPORT_KEY}/events/{raw_id}/odds"
        resp = self._get(
            path,
            params,
            estimated_cost=credits_for_books(len(keys), len(books)),
            ttl=self.settings.provider_cache_ttl_seconds,
            force=force,
            event_endpoint=True,
        )
        mapped = _Mapped(requested_books=frozenset(books), requested_keys=frozenset(keys))
        if resp.data:
            self._map_bookmakers(resp.data, resp.received_at, resp.url, mapped)
        warnings.extend(mapped.warnings)
        reason_codes: list[str] = []
        self._target_book_check(books, mapped.books_seen, warnings, reason_codes)
        credits = credits_for_books(len(mapped.market_keys_seen), len(books))
        if resp.cached:
            credits = 0  # no request was made
        else:
            self._record_usage(path, credits)
        return ProviderResult(
            data=mapped.quotes,
            stamp=self._stamp(resp.url, raw_id, None, resp.received_at),
            credits_cost=credits,
            quota=dict(self.last_quota),
            warnings=warnings,
            reason_codes=reason_codes,
            cached=resp.cached,
        )

    def list_event_markets(
        self, event_id: str, books: list[str], *, force: bool = False
    ) -> ProviderResult[dict[str, list[str]]]:
        """Recently seen market keys per bookmaker for one event (1 credit). Used by the coverage report."""
        if not books:
            raise InvalidInput("at least one bookmaker key is required", ["INVALID_INPUT"])
        raw_id = _strip_event_prefix(event_id)
        path = f"/sports/{SPORT_KEY}/events/{raw_id}/markets"
        resp = self._get(
            path,
            {"bookmakers": ",".join(books), "dateFormat": "iso"},
            estimated_cost=1,
            ttl=self.settings.provider_cache_ttl_seconds,
            force=force,
            event_endpoint=True,
        )
        out: dict[str, list[str]] = {}
        for bm in resp.data.get("bookmakers", []) or []:
            key = bm.get("key")
            if key:
                out[key] = [m.get("key") for m in bm.get("markets", []) if m.get("key")]
        warnings: list[str] = []
        reason_codes: list[str] = []
        self._target_book_check(books, set(out), warnings, reason_codes)
        credits = 0 if resp.cached else 1
        if not resp.cached:
            self._record_usage(path, credits)
        return ProviderResult(
            data=out,
            stamp=self._stamp(resp.url, raw_id, None, resp.received_at),
            credits_cost=credits,
            quota=dict(self.last_quota),
            warnings=warnings,
            reason_codes=reason_codes,
            cached=resp.cached,
        )

    def fetch_scores(
        self, days_from: int | None = 1, *, force: bool = False
    ) -> ProviderResult[list[S.GameResult]]:
        """Completed/live NBA scores (2 credits with ``daysFrom``, 1 without). Team scores only, no player stats."""
        params: dict[str, str] = {"dateFormat": "iso"}
        if days_from is not None:
            if not 1 <= days_from <= 3:
                raise InvalidInput("daysFrom must be between 1 and 3", ["INVALID_INPUT"])
            params["daysFrom"] = str(days_from)
        path = f"/sports/{SPORT_KEY}/scores"
        estimated = 2 if days_from is not None else 1
        resp = self._get(
            path, params, estimated_cost=estimated, ttl=self.settings.provider_cache_ttl_seconds, force=force
        )
        now = self.clock.now_utc()
        results: list[S.GameResult] = []
        warnings: list[str] = []
        for raw in resp.data:
            result = self._map_score(raw, now, resp.received_at, resp.url, warnings)
            if result is not None:
                results.append(result)
        credits = 0 if resp.cached else estimated
        if not resp.cached:
            self._record_usage(path, credits)
        return ProviderResult(
            data=results,
            stamp=self._stamp(resp.url, None, None, resp.received_at),
            credits_cost=credits,
            quota=dict(self.last_quota),
            warnings=warnings,
            cached=resp.cached,
        )

    def probe(self, spend_credits: bool = False) -> S.ProviderProbe:
        """Check the key and NBA availability via the free ``/sports`` call; optionally spend 1 credit to check books."""
        now = self.clock.now_utc()
        warnings: list[str] = []
        reason_codes: list[str] = []
        auth_ok: bool | None
        nba_active: bool | None = None
        try:
            resp = self._get("/sports", {}, estimated_cost=0, ttl=CACHE_TTL_SPORTS)
            auth_ok = True
            sports = [s for s in resp.data if isinstance(s, dict)]
            nba_active = any(s.get("key") == SPORT_KEY and bool(s.get("active")) for s in sports)
            if not nba_active:
                warnings.append(f"{SPORT_KEY} is not listed as active by the provider")
            if not resp.cached:
                self._record_usage("/sports", 0)
        except ProviderError as exc:
            auth_ok = (
                False
                if "PROVIDER_AUTH_FAILED" in exc.reason_codes
                or "PROVIDER_QUOTA_EXHAUSTED" in exc.reason_codes
                else None
            )
            reason_codes.extend(exc.reason_codes)
            warnings.append(redact(exc.message, [self._api_key]))
        target_present: bool | None = None
        refs_present: dict[str, bool] = {}
        if spend_credits and auth_ok:
            books = [
                self.settings.target_book,
                *[b for b in self.settings.reference_books if b != self.settings.target_book],
            ]
            try:
                odds = self.fetch_featured_odds(
                    today_local(self.clock, DEFAULT_TZ), books, [S.MarketType.MONEYLINE]
                )
                seen = {q.book for q in odds.data}
                if odds.data:
                    target_present = self.settings.target_book in seen
                    refs_present = {b: b in seen for b in self.settings.reference_books}
                else:
                    warnings.append("no events today, so bookmaker presence could not be checked")
                warnings.extend(odds.warnings)
                reason_codes.extend(odds.reason_codes)
            except ProviderError as exc:
                reason_codes.extend(exc.reason_codes)
                warnings.append(redact(exc.message, [self._api_key]))
        return S.ProviderProbe(
            provider=self.name,
            auth_ok=auth_ok,
            nba_active=nba_active,
            target_book_present=target_present,
            reference_books_present=refs_present,
            quota=dict(self.last_quota),
            checked_at_utc=now,
            warnings=warnings,
            reason_codes=list(dict.fromkeys(reason_codes)),
        )

    def clear_cache(self) -> None:
        """Drop the in-process response cache (tests and explicit refreshes)."""
        self._cache.clear()

    def credits_used_today(self) -> int:
        """Credits recorded for the current ET day (database when available, otherwise this process).

        The day is America/New_York regardless of ``settings.display_tz`` so the guard rolls over with the
        ledger's ``date_local``.
        """
        date_local = today_local(self.clock, DEFAULT_TZ)
        if self.db is None:
            return self._memory_credits.get(date_local, 0)
        start, end = local_day_bounds_utc(date_local, DEFAULT_TZ)
        with self.db.engine.connect() as conn:
            total = conn.execute(
                select(func.coalesce(func.sum(provider_usage.c.credits_cost), 0)).where(
                    provider_usage.c.provider == self.name,
                    provider_usage.c.created_at >= iso(start),
                    provider_usage.c.created_at < iso(end),
                )
            ).scalar_one()
        return int(total or 0)

    # ------------------------------------------------------------------------------
    # Mapping
    # ------------------------------------------------------------------------------

    def _stamp(
        self, url: str, record_id: str | None, source_ts: datetime | None, now: datetime
    ) -> S.SourceStamp:
        return S.SourceStamp(
            source=self.name,
            source_url=url,
            source_record_id=record_id,
            source_timestamp_utc=source_ts,
            received_at_utc=now,
            data_mode=S.DataMode.LIVE_PROVIDER,
        )

    def _map_event(
        self, raw: dict[str, Any], now: datetime, received_at: datetime, url: str, warnings: list[str]
    ) -> S.Event | None:
        """Map one raw event; ``now`` decides LIVE/SCHEDULED, ``received_at`` goes on the stamp."""
        if not isinstance(raw, dict):
            warnings.append(f"skipped a non-object event record ({type(raw).__name__})")
            return None
        sport_key = raw.get("sport_key")
        if sport_key and sport_key != SPORT_KEY:
            warnings.append(f"WRONG_LEAGUE: skipped event {raw.get('id')} with sport_key {sport_key}")
            return None
        home = try_canonical_team(raw.get("home_team") or "")
        away = try_canonical_team(raw.get("away_team") or "")
        commence = _parse_ts(raw.get("commence_time"))
        if home is None or away is None or commence is None or not raw.get("id"):
            warnings.append(
                f"TEAM_UNMATCHED: skipped event {raw.get('id')} ({raw.get('away_team')} @ {raw.get('home_team')})"
            )
            return None
        status = S.EventStatus.LIVE if commence <= now else S.EventStatus.SCHEDULED
        return S.Event(
            event_id=f"oddsapi:{raw['id']}",
            season_stage="REGULAR",
            home_team=home,
            away_team=away,
            commence_time_utc=commence,
            status=status,
            stamp=self._stamp(url, str(raw["id"]), None, received_at),
        )

    def _map_bookmakers(self, raw_event: Any, received_at: datetime, url: str, mapped: _Mapped) -> None:
        """Map every bookmaker/market/outcome of one raw event into quotes stamped ``received_at``."""
        if not isinstance(raw_event, dict):
            mapped.warnings.append(f"skipped a non-object event record ({type(raw_event).__name__})")
            return
        raw_id = raw_event.get("id")
        if not raw_id:
            mapped.warnings.append("skipped an event without an id")
            return
        event_id = f"oddsapi:{raw_id}"
        home_name = raw_event.get("home_team") or ""
        away_name = raw_event.get("away_team") or ""
        home = try_canonical_team(home_name)
        away = try_canonical_team(away_name)
        if home is None or away is None:
            mapped.warnings.append(f"TEAM_UNMATCHED: skipped quotes for {raw_id} ({away_name} @ {home_name})")
            return
        for bm in raw_event.get("bookmakers", []) or []:
            if not isinstance(bm, dict):
                continue
            book = bm.get("key")
            if not book:
                continue
            mapped.books_seen.add(book)
            if book not in mapped.requested_books:
                mapped.ignore(
                    f"book:{book}",
                    f"ignored quotes from bookmaker {book!r}: it was not requested (no substitution)",
                )
                continue
            jurisdiction = self.settings.target_jurisdiction if book == self.settings.target_book else None
            for market in bm.get("markets", []) or []:
                if not isinstance(market, dict):
                    continue
                mkey = market.get("key")
                if mkey not in mapped.requested_keys:
                    mapped.ignore(
                        f"market:{book}:{mkey}",
                        f"ignored market key {mkey!r} from {book}: it was not requested",
                    )
                    continue
                mapping = KEY_TO_MARKET.get(mkey or "")
                if mapping is None:
                    mapped.warnings.append(
                        f"MARKET_NOT_OFFERED: unsupported market key {mkey!r} from {book} ignored"
                    )
                    continue
                mapped.market_keys_seen.add(mkey)
                market_type, is_alt = mapping
                source_ts = _parse_ts(market.get("last_update"))
                stamp = self._stamp(url, str(raw_id), source_ts, received_at)
                for outcome in market.get("outcomes", []) or []:
                    quote = self._map_outcome(
                        outcome,
                        event_id,
                        book,
                        jurisdiction,
                        market_type,
                        is_alt,
                        mkey,
                        home,
                        away,
                        home_name,
                        away_name,
                        stamp,
                        mapped,
                    )
                    if quote is not None:
                        mapped.quotes.append(quote)

    def _map_outcome(
        self,
        outcome: dict[str, Any],
        event_id: str,
        book: str,
        jurisdiction: str | None,
        market_type: S.MarketType,
        is_alt: bool,
        market_key: str,
        home: S.Team,
        away: S.Team,
        home_name: str,
        away_name: str,
        stamp: S.SourceStamp,
        mapped: _Mapped,
    ) -> S.MarketQuote | None:
        name = str(outcome.get("name") or "")
        price = _dec(outcome.get("price"))
        point = _dec(outcome.get("point"))
        description = outcome.get("description")
        if price is None or price <= 1:
            mapped.warnings.append(
                f"skipped {market_key} outcome {name!r} at {book}: unusable price {outcome.get('price')!r}"
            )
            return None
        side: S.Side | None = None
        team_id: str | None = None
        player_id: str | None = None
        player_name: str | None = None
        line: Decimal | None = None
        subject = ""
        if market_type in (S.MarketType.MONEYLINE, S.MarketType.SPREAD):
            team = self._team_side(name, home, away, home_name, away_name)
            if team is None:
                mapped.warnings.append(
                    f"UNKNOWN_SIDE: {market_key} outcome {name!r} at {book} matches neither team; skipped"
                )
                return None
            side = S.Side.HOME if team.team_id == home.team_id else S.Side.AWAY
            team_id = team.team_id
            subject = team_id
            if market_type == S.MarketType.SPREAD:
                if point is None:
                    mapped.warnings.append(f"skipped spread outcome {name!r} at {book}: no point")
                    return None
                line = point
        elif market_type == S.MarketType.TOTAL:
            side = _over_under(name)
            if side is None or point is None:
                mapped.warnings.append(f"skipped totals outcome {name!r} at {book}: side/point missing")
                return None
            line = point
        elif market_type == S.MarketType.TEAM_TOTAL:
            # Documented shape for team_totals: outcome.name is "Over"/"Under" and outcome.description names the
            # team. Some feeds invert the two fields; both are accepted, anything else is a warning, never a guess.
            side = _over_under(name)
            team_text = str(description or "")
            if side is None:
                side = _over_under(str(description or ""))
                team_text = name
            team = self._team_side(team_text, home, away, home_name, away_name) if side is not None else None
            if side is None or team is None or point is None:
                mapped.warnings.append(
                    f"UNKNOWN_TEAM_TOTAL_MAPPING: {book} team_totals outcome name={name!r} description={description!r} skipped"
                )
                return None
            team_id = team.team_id
            line = point
            subject = team_id
        else:  # player props
            side = _over_under(name)
            if side is None or point is None or not description:
                mapped.warnings.append(
                    f"skipped {market_key} outcome name={name!r} description={description!r} at {book}"
                )
                return None
            player_name = str(description)
            try:
                player_id = canonical_player(player_name, None).player_id
            except InvalidInput:
                # A description that normalises to nothing ("-", ".", whitespace). Provider data, not caller
                # input: skip this one outcome with a warning instead of failing the whole response.
                mapped.warnings.append(
                    f"skipped {market_key} outcome description={description!r} at {book}: PLAYER_UNMATCHED"
                )
                return None
            line = point
            subject = player_id
        quote_id = f"oddsapi:{_strip_event_prefix(event_id)}:{book}:{market_key}:{side.value}:{format(line.normalize(), 'f') if line is not None else ''}:{subject}"
        return S.MarketQuote(
            quote_id=quote_id,
            event_id=event_id,
            book=book,
            jurisdiction=jurisdiction,
            market_type=market_type,
            period=S.Period.FULL_GAME,
            is_alternate=is_alt,
            side=side,
            team_id=team_id,
            player_id=player_id,
            player_name_raw=player_name,
            line=line,
            odds_american=None,
            odds_decimal=price,
            stamp=stamp,
        )

    @staticmethod
    def _team_side(name: str, home: S.Team, away: S.Team, home_name: str, away_name: str) -> S.Team | None:
        if name == home_name:
            return home
        if name == away_name:
            return away
        team = try_canonical_team(name)
        if team is None:
            return None
        if team.team_id == home.team_id:
            return home
        if team.team_id == away.team_id:
            return away
        return None

    def _map_score(
        self, raw: dict[str, Any], now: datetime, received_at: datetime, url: str, warnings: list[str]
    ) -> S.GameResult | None:
        """Map one raw score record; ``now`` decides LIVE/SCHEDULED, ``received_at`` goes on the stamp."""
        if not isinstance(raw, dict):
            warnings.append(f"skipped a non-object score record ({type(raw).__name__})")
            return None
        raw_id = raw.get("id")
        if not raw_id:
            return None
        home_name = raw.get("home_team") or ""
        away_name = raw.get("away_team") or ""
        completed = bool(raw.get("completed"))
        commence = _parse_ts(raw.get("commence_time"))
        home_score: int | None = None
        away_score: int | None = None
        for entry in raw.get("scores") or []:
            team_name = entry.get("name")
            try:
                value = int(str(entry.get("score")))
            except (TypeError, ValueError):
                continue
            if team_name == home_name:
                home_score = value
            elif team_name == away_name:
                away_score = value
            else:
                warnings.append(f"score entry {team_name!r} for {raw_id} matches neither team")
        if completed:
            status = S.EventStatus.FINAL
        elif raw.get("scores") or (commence is not None and commence <= now):
            status = S.EventStatus.LIVE
        else:
            status = S.EventStatus.SCHEDULED
        return S.GameResult(
            event_id=f"oddsapi:{raw_id}",
            home_score=home_score,
            away_score=away_score,
            completed=completed,
            status=status,
            stamp=self._stamp(url, str(raw_id), _parse_ts(raw.get("last_update")), received_at),
        )

    def _target_book_check(
        self, requested: list[str], seen: set[str], warnings: list[str], reason_codes: list[str]
    ) -> None:
        target = self.settings.target_book
        if target in requested and target not in seen:
            reason_codes.append("BOOK_NOT_AVAILABLE")
            present = ", ".join(sorted(seen)) or "none"
            warnings.append(
                f"BOOK_NOT_AVAILABLE: {target} absent from the response (bookmakers present: {present}); no substitute used"
            )

    # ------------------------------------------------------------------------------
    # HTTP plumbing: cache, credit guard, pacing, retries, error mapping, usage rows
    # ------------------------------------------------------------------------------

    def _get(
        self,
        path: str,
        params: dict[str, str],
        *,
        estimated_cost: int,
        ttl: int,
        force: bool = False,
        event_endpoint: bool = False,
    ) -> _Response:
        """GET ``path`` with the cache, credit guard, pacing, bounded retries and error mapping applied.

        Event endpoints (``/events/{id}/...``) document a JSON object body; every other endpoint documents a
        list. A 200 whose body has another shape is a ``ProviderError`` (PROVIDER_ERROR), never a crash later.
        """
        expected: type = dict if event_endpoint else list
        now = self.clock.now_utc()
        cache_key = (path, tuple(sorted((k, str(v)) for k, v in params.items() if k != "apiKey")))
        entry = self._cache.get(cache_key)
        if entry is not None and entry.expires_at > now:
            return _Response(entry.data, entry.headers, entry.url, cached=True, received_at=entry.received_at)
        if estimated_cost > 0 and not force:
            used = self.credits_used_today()
            budget = self.settings.daily_provider_credit_budget
            if used >= budget:
                raise ProviderError(
                    f"daily provider credit guard reached ({used} of {budget} credits used today); pass force=True to override",
                    ["PROVIDER_CREDIT_GUARD"],
                )
        base = self.settings.odds_api_base_url.rstrip("/")
        safe_url = f"{base}{path}" + (f"?{urlencode(sorted(params.items()))}" if params else "")
        full_params = {**params, "apiKey": self._api_key}
        retries = max(0, int(self.settings.http_max_retries))
        delay = BACKOFF_INITIAL_SECONDS
        for attempt in range(retries + 1):
            self._pace()
            logger.info("GET %s (attempt %d)", safe_url, attempt + 1)
            try:
                response = self.http.get(
                    f"{base}{path}", params=full_params, headers={"Accept": "application/json"}
                )
            except httpx.HTTPError as exc:
                message = redact(f"{type(exc).__name__}: {exc}", [self._api_key])
                logger.warning("network error on %s: %s", safe_url, message)
                if attempt < retries:
                    self._sleep(delay)
                    delay *= 2
                    continue
                raise ProviderError(
                    f"network error calling The Odds API: {message}", ["PROVIDER_ERROR"]
                ) from None
            status = response.status_code
            self._read_quota(response.headers)
            if status == 200:
                try:
                    data = response.json()
                except ValueError:
                    raise ProviderError(
                        "The Odds API returned a non-JSON body", ["PROVIDER_ERROR"], status_code=200
                    ) from None
                if not isinstance(data, expected):
                    raise ProviderError(
                        f"The Odds API returned a JSON {type(data).__name__} where a {expected.__name__} was expected",
                        ["PROVIDER_ERROR"],
                        detail=redact(response.text[:500], [self._api_key]),
                        status_code=200,
                    )
                received_at = self.clock.now_utc()
                self.last_ok_utc = received_at
                if ttl > 0:
                    self._cache[cache_key] = _CacheEntry(
                        now + timedelta(seconds=ttl), data, response.headers, safe_url, received_at
                    )
                return _Response(data, response.headers, safe_url, cached=False, received_at=received_at)
            body = redact(response.text[:500], [self._api_key])
            if status == 401:
                lowered = body.lower()
                if ("usage" in lowered and "limit" in lowered) or "quota" in lowered:
                    raise ProviderError(
                        "The Odds API usage limit reached for this key",
                        ["PROVIDER_QUOTA_EXHAUSTED"],
                        detail=body,
                        status_code=401,
                    )
                raise ProviderError(
                    "The Odds API rejected the key (401)",
                    ["PROVIDER_AUTH_FAILED"],
                    detail=body,
                    status_code=401,
                )
            if status == 404 and event_endpoint:
                raise ProviderError(
                    "event expired or unknown (404)", ["NOT_FOUND"], detail=body, status_code=404
                )
            if status == 422:
                raise InvalidInput(
                    "The Odds API rejected the query parameters (422)", ["INVALID_INPUT"], detail=body
                )
            if status == 429:
                retry_after = _retry_after(response.headers)
                if attempt < retries:
                    self._sleep(retry_after if retry_after is not None else delay)
                    delay *= 2
                    continue
                raise ProviderError(
                    "The Odds API rate limit (429) persisted after retries",
                    ["PROVIDER_RATE_LIMITED"],
                    detail=body,
                    retry_after=retry_after if retry_after is not None else delay,
                    status_code=429,
                )
            if status >= 500:
                logger.warning("The Odds API %s on %s", status, safe_url)
                if attempt < retries:
                    self._sleep(delay)
                    delay *= 2
                    continue
                raise ProviderError(
                    f"The Odds API server error ({status}) persisted after retries",
                    ["PROVIDER_ERROR"],
                    detail=body,
                    status_code=status,
                )
            raise ProviderError(
                f"unexpected status {status} from The Odds API",
                ["PROVIDER_ERROR"],
                detail=body,
                status_code=status,
            )
        raise ProviderError(
            "The Odds API request failed", ["PROVIDER_ERROR"]
        )  # pragma: no cover - loop always returns/raises

    def _pace(self) -> None:
        """Client-side pacing: never more than MAX_REQUESTS_PER_SECOND requests in any rolling second."""
        now_m = self._monotonic()
        while self._recent and now_m - self._recent[0] >= 1.0:
            self._recent.popleft()
        if len(self._recent) >= MAX_REQUESTS_PER_SECOND:
            wait = self._recent[0] + 1.0 - now_m
            if wait > 0:
                self._sleep(wait)
                now_m = self._monotonic()
            while self._recent and now_m - self._recent[0] >= 1.0:
                self._recent.popleft()
        self._recent.append(now_m)

    def _read_quota(self, headers: httpx.Headers) -> None:
        remaining = _int_header(headers, "x-requests-remaining")
        used = _int_header(headers, "x-requests-used")
        last = _int_header(headers, "x-requests-last")
        if remaining is not None or used is not None or last is not None:
            self.last_quota = {"requests_remaining": remaining, "requests_used": used, "requests_last": last}

    def _record_usage(self, endpoint: str, credits: int) -> None:
        now = self.clock.now_utc()
        date_local = today_local(self.clock, DEFAULT_TZ)
        self._memory_credits[date_local] = self._memory_credits.get(date_local, 0) + credits
        if self.db is None:
            return
        with self.db.tx() as conn:
            conn.execute(
                insert(provider_usage).values(
                    user_id=self.user_id,
                    provider=self.name,
                    endpoint=endpoint,
                    credits_cost=credits,
                    requests_remaining=self.last_quota.get("requests_remaining"),
                    requests_used=self.last_quota.get("requests_used"),
                    created_at=iso(now),
                )
            )


def _over_under(name: str) -> S.Side | None:
    lowered = name.strip().lower()
    if lowered == "over":
        return S.Side.OVER
    if lowered == "under":
        return S.Side.UNDER
    return None


def _retry_after(headers: httpx.Headers) -> float | None:
    raw = headers.get("retry-after")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None
