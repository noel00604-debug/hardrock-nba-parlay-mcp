"""Service layer: the single integration point that ``mcp_server.py`` and ``cli.py`` call.

Every public function takes a ``RequestContext`` (user id from verified auth, clock, database, settings,
providers) and returns a ``schemas`` response model. Every user-facing failure is an ``errors.ServiceError``
subclass: ledger errors (``budget.LedgerError`` family, ``db.FixtureLedgerError``) and pydantic validation
errors on inputs become ``InvalidInput``; provider failures arrive as ``errors.ProviderError``.

Tenant scoping: every read and write filters by ``ctx.user_id``; another user's candidate, reservation or bet
is indistinguishable from a missing one (``NotFound``). Data mode is explicit: the registry is LIVE_PROVIDER
or FIXTURE (``settings.data_mode``), and live never falls back to fixture silently (NO_PROVIDER_KEY instead).
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from cryptography.fernet import Fernet, InvalidToken
from pydantic import ValidationError
from sqlalchemy import func, insert, select, update

from hardrock_nba_parlay import (
    actual_bets,
    budget,
    candidate_builder,
    injury_context,
    normalization,
    quote_review,
    reports,
    settlement,
)
from hardrock_nba_parlay import db as dbm
from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.config import (
    DEFAULT_TZ,
    Clock,
    Settings,
    local_date,
    local_day_bounds_utc,
    mask_user_id,
    redact,
    to_display,
)
from hardrock_nba_parlay.db import Database, FixtureLedgerError, dumps, iso, loads, new_id, parse_iso
from hardrock_nba_parlay.errors import InvalidInput, NotFound, ProviderError, ServiceError
from hardrock_nba_parlay.providers import fixtures as fixture_slates
from hardrock_nba_parlay.providers import nba_injury_report, odds_api
from hardrock_nba_parlay.providers.base import ProviderResult, empty_quota

logger = logging.getLogger(__name__)

__all__ = [
    "FixtureOddsProvider",
    "MarketData",
    "ProviderRegistry",
    "RequestContext",
    "add_cost",
    "analyze_leg",
    "analyze_my_parlay",
    "build_providers",
    "build_three_leg_parlays",
    "check_data_coverage",
    "check_parlay_correlation",
    "export_my_data",
    "generate_30_day_review",
    "get_daily_budget",
    "get_injury_context",
    "get_nba_slate",
    "get_performance",
    "get_system_status",
    "get_user_settings",
    "import_hardrock_quote",
    "list_candidate_history",
    "load_candidate",
    "record_actual_bet",
    "reconcile_settlement",
    "refresh_parlay",
    "release_reservation",
    "save_candidate",
    "scrub_export_bundle",
    "select_ticket",
    "set_user_settings",
    "transition",
]

DEFAULT_FIXTURE = "opening_night_2026_10_20"
FEATURED_MARKETS: tuple[S.MarketType, ...] = (S.MarketType.MONEYLINE, S.MarketType.SPREAD, S.MarketType.TOTAL)
PROP_MARKETS: tuple[S.MarketType, ...] = (
    S.MarketType.PLAYER_POINTS,
    S.MarketType.PLAYER_REBOUNDS,
    S.MarketType.PLAYER_ASSISTS,
    S.MarketType.PLAYER_THREES,
)
NO_KEY_HINT = (
    "set HRNBA_ODDS_API_KEY (environment or ~/.hardrock-nba-parlay/.env) or run 'hrnba secret set ODDS_API_KEY'; "
    "for the offline demo slate set HRNBA_DATA_MODE=fixture"
)
FIXTURE_WARNING = "FIXTURE_DATA: offline demo slate with synthetic prices; nothing here is live or bettable"
ONBOARDING_CODE = "NEEDS_ONBOARDING"
ONBOARDING_HINT = "NEEDS_ONBOARDING: confirm the daily cap with set_user_settings(confirm_onboarding=true)"
_TERMINAL_STATES: frozenset[S.CandidateState] = frozenset(
    {S.CandidateState.USER_CONFIRMED_PLACED, S.CandidateState.SETTLED}
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --------------------------------------------------------------------------------------
# Context and providers
# --------------------------------------------------------------------------------------


@dataclass
class RequestContext:
    """What every service call needs. ``user_id`` comes from verified auth, never from a tool argument."""

    user_id: str
    clock: Clock
    db: Database
    settings: Settings
    providers: ProviderRegistry | None = None


@dataclass
class ProviderRegistry:
    """The providers one request may use, with the data mode they produce."""

    odds: Any | None = None
    injury: Any | None = None
    fixture: FixtureOddsProvider | None = None
    data_mode: S.DataMode = S.DataMode.LIVE_PROVIDER
    key_configured: bool = False
    key_source: str | None = None
    warnings: list[str] = field(default_factory=list)


class FixtureOddsProvider:
    """``OddsProvider`` plus ``InjuryProvider`` backed by a packaged FIXTURE slate (offline, zero credits).

    Every stamp is FIXTURE, so the ledger refuses the records and every response shows the mode.
    ``received_at`` pins the slate's receipt time (tests use it to make quotes stale).
    """

    def __init__(
        self,
        settings: Settings,
        clock: Clock,
        *,
        fixture_name: str = DEFAULT_FIXTURE,
        received_at: datetime | None = None,
    ) -> None:
        self.settings = settings
        self.clock = clock
        self.fixture_name = fixture_name
        self.received_at = received_at
        self.name = f"fixture:{fixture_name}"
        self._cache: dict[datetime, fixture_slates.FixtureSlate] = {}

    def _slate(self) -> fixture_slates.FixtureSlate:
        now = self.received_at or self.clock.now_utc()
        slate = self._cache.get(now)
        if slate is None:
            slate = fixture_slates.load_fixture_slate(
                self.fixture_name, now=now, target_book=self.settings.target_book
            )
            self._cache = {now: slate}
        return slate

    def clear_cache(self) -> None:
        self._cache.clear()

    def _stamp(self, source_ts: datetime | None = None) -> S.SourceStamp:
        return S.SourceStamp(
            source=self.name,
            source_url=None,
            source_record_id=None,
            source_timestamp_utc=source_ts,
            received_at_utc=self.received_at or self.clock.now_utc(),
            data_mode=S.DataMode.FIXTURE,
        )

    def _result(self, data: Any, source_ts: datetime | None = None) -> ProviderResult[Any]:
        return ProviderResult(
            data=data,
            stamp=self._stamp(source_ts),
            credits_cost=0,
            quota=empty_quota(),
            warnings=[FIXTURE_WARNING],
            reason_codes=["FIXTURE_DATA"],
        )

    def _events_for_day(self, date_local: str) -> list[S.Event]:
        return [e for e in self._slate().events if local_date(e.commence_time_utc) == date_local]

    def list_events(self, date_local: str) -> ProviderResult[list[S.Event]]:
        return self._result(self._events_for_day(date_local))

    def fetch_featured_odds(
        self, date_local: str, books: list[str], markets: list[S.MarketType]
    ) -> ProviderResult[list[S.MarketQuote]]:
        event_ids = {e.event_id for e in self._events_for_day(date_local)}
        quotes = [
            q
            for q in self._slate().quotes
            if q.event_id in event_ids and q.book in books and q.market_type in markets and not q.is_alternate
        ]
        return self._result(quotes)

    def fetch_event_props(
        self, event_id: str, books: list[str], markets: list[S.MarketType], include_alternates: bool
    ) -> ProviderResult[list[S.MarketQuote]]:
        quotes = [
            q
            for q in self._slate().quotes
            if q.event_id == event_id
            and q.book in books
            and q.market_type in markets
            and (include_alternates or not q.is_alternate)
        ]
        return self._result(quotes)

    def list_event_markets(self, event_id: str, books: list[str]) -> ProviderResult[dict[str, list[str]]]:
        out: dict[str, list[str]] = {}
        for q in self._slate().quotes:
            if q.event_id != event_id or q.book not in books:
                continue
            key = odds_api.FEATURED_MARKET_KEYS.get(q.market_type) or odds_api.PROP_MARKET_KEYS.get(
                q.market_type
            )
            if key is None:
                continue
            if q.is_alternate:
                key = f"{key}_alternate"
            out.setdefault(q.book, [])
            if key not in out[q.book]:
                out[q.book].append(key)
        return self._result(out)

    def fetch_scores(self, days_from: int | None = 1) -> ProviderResult[list[S.GameResult]]:
        return self._result([])

    def probe(self, spend_credits: bool = False) -> S.ProviderProbe:
        return S.ProviderProbe(
            provider=self.name,
            auth_ok=None,
            nba_active=None,
            target_book_present=True,
            reference_books_present={b: True for b in self.settings.reference_books},
            quota=empty_quota(),
            checked_at_utc=self.clock.now_utc(),
            warnings=[FIXTURE_WARNING],
            reason_codes=["FIXTURE_DATA"],
        )

    def fetch_latest_report(
        self, now: datetime, slate: list[S.Event]
    ) -> ProviderResult[list[S.InjuryContext]]:
        wanted = {e.event_id for e in slate} if slate else None
        entries = [i for i in self._slate().injuries if wanted is None or i.event_id in wanted]
        return self._result(entries, injury_context.report_timestamp(entries))


_LIVE_PROVIDERS: dict[tuple[str, str, str, int], odds_api.OddsApiProvider] = {}
_INJURY_HTTP: httpx.Client | None = None


def _fernet(settings: Settings) -> Fernet | None:
    secret = settings.secret_key.get_secret_value() if settings.secret_key is not None else ""
    if not secret:
        return None
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest()))


def _resolve_odds_key(
    settings: Settings, db: Database | None, user_id: str | None, warnings: list[str]
) -> tuple[str | None, str | None]:
    """Per-user encrypted key first, then the server-wide key. Never logs or returns more than the source."""
    if db is not None and user_id:
        with db.engine.connect() as conn:
            row = conn.execute(
                select(dbm.user_settings.c.odds_api_key_encrypted).where(
                    dbm.user_settings.c.user_id == user_id
                )
            ).first()
        encrypted = row[0] if row is not None else None
        if encrypted:
            fernet = _fernet(settings)
            if fernet is None:
                warnings.append(
                    "a per-user odds key is stored but HRNBA_SECRET_KEY is not set; using the server key"
                )
            else:
                try:
                    return fernet.decrypt(encrypted.encode("utf-8")).decode("utf-8"), "user"
                except (InvalidToken, ValueError):
                    warnings.append(
                        "the stored per-user odds key cannot be decrypted with the current HRNBA_SECRET_KEY; set it again"
                    )
    server_key = settings.odds_api_key_value()
    if server_key:
        return server_key, "server"
    return None, None


def _live_odds_provider(
    key: str, settings: Settings, clock: Clock, db: Database | None, user_id: str | None
) -> odds_api.OddsApiProvider:
    fingerprint = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    cache_key = (db.url if db is not None else "", user_id or "", fingerprint, id(clock))
    provider = _LIVE_PROVIDERS.get(cache_key)
    if provider is None or provider.settings is not settings:
        provider = odds_api.OddsApiProvider(key, settings, clock, db=db, user_id=user_id)
        _LIVE_PROVIDERS[cache_key] = provider
    return provider


def _live_injury_provider(clock: Clock) -> nba_injury_report.NbaInjuryReportProvider:
    global _INJURY_HTTP
    if _INJURY_HTTP is None:
        _INJURY_HTTP = httpx.Client(timeout=20.0, follow_redirects=True)
    return nba_injury_report.NbaInjuryReportProvider(_INJURY_HTTP, clock)


def build_providers(
    ctx_or_settings: RequestContext | Settings,
    db: Database | None = None,
    clock: Clock | None = None,
    user_id: str | None = None,
) -> ProviderRegistry:
    """Build the ``ProviderRegistry`` for a request.

    Accepts either a ``RequestContext`` (how ``mcp_server.make_request_context`` calls it) or
    ``(settings, db, clock, user_id=None)``. In fixture mode (``settings.data_mode == "fixture"``) every
    provider is the packaged FIXTURE slate. In live mode the odds provider needs a key (per-user encrypted
    key wins, else the server key); without one ``odds`` is None and the first odds-needing call raises
    NO_PROVIDER_KEY. Live never falls back to fixture silently.
    """
    if isinstance(ctx_or_settings, RequestContext):
        settings = ctx_or_settings.settings
        db = ctx_or_settings.db
        clock = ctx_or_settings.clock
        user_id = ctx_or_settings.user_id
    else:
        settings = ctx_or_settings
    if clock is None:
        raise InvalidInput("build_providers needs a clock")
    warnings: list[str] = []
    key, key_source = _resolve_odds_key(settings, db, user_id, warnings)
    if settings.data_mode == "fixture":
        fixture = FixtureOddsProvider(settings, clock)
        return ProviderRegistry(
            odds=fixture,
            injury=fixture,
            fixture=fixture,
            data_mode=S.DataMode.FIXTURE,
            key_configured=key is not None,
            key_source=key_source,
            warnings=warnings,
        )
    odds = _live_odds_provider(key, settings, clock, db, user_id) if key else None
    injury = _live_injury_provider(clock) if settings.injury_auto_fetch else None
    return ProviderRegistry(
        odds=odds,
        injury=injury,
        fixture=None,
        data_mode=S.DataMode.LIVE_PROVIDER,
        key_configured=key is not None,
        key_source=key_source,
        warnings=warnings,
    )


def _registry(ctx: RequestContext) -> ProviderRegistry:
    if ctx.providers is None:
        ctx.providers = build_providers(ctx)
    return ctx.providers


def _odds(ctx: RequestContext) -> Any:
    reg = _registry(ctx)
    if reg.odds is None:
        raise ServiceError(
            "no odds provider is configured for live mode (The Odds API key missing)",
            ["NO_PROVIDER_KEY"],
            detail=NO_KEY_HINT,
        )
    return reg.odds


# --------------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------------


def _today(ctx: RequestContext) -> str:
    return local_date(ctx.clock.now_utc())


def _validate_date(date_local: str | None) -> str:
    if not date_local or not _DATE_RE.match(date_local):
        raise InvalidInput(f"date_local must be YYYY-MM-DD (America/New_York), got {date_local!r}")
    try:
        date.fromisoformat(date_local)
    except ValueError as exc:
        raise InvalidInput(f"date_local is not a calendar date: {date_local}") from exc
    return date_local


def _money(value: Decimal | int | str, name: str = "stake_usd") -> Decimal:
    if isinstance(value, float | bool):
        raise InvalidInput(f"{name} must be a decimal string, not a float")
    try:
        amount = budget.q_money(Decimal(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InvalidInput(f"{name} is not a money amount: {value!r}") from exc
    # Quantize first: an amount that rounds to 0.00 is zero, and a zero cap or stake is never valid.
    if amount <= 0:
        raise InvalidInput(f"{name} must be positive (at least 0.01)")
    return amount


def _coerce(model: type[S.Model], value: Any, what: str) -> Any:
    if isinstance(value, model):
        return value
    try:
        return model.model_validate(value)
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in err["loc"]) for err in exc.errors()})
        raise InvalidInput(
            f"invalid {what}: {', '.join(fields) or 'unknown field'}", detail=str(exc)[:500]
        ) from exc


def _ledger(fn: Any, *args: Any, **kwargs: Any) -> Any:
    """Call a ledger function and map its exceptions to ``ServiceError`` subclasses."""
    try:
        return fn(*args, **kwargs)
    except budget.NotFoundError as exc:
        raise NotFound(str(exc)) from exc
    except budget.LedgerError as exc:
        raise InvalidInput(str(exc), list(exc.reason_codes)) from exc
    except FixtureLedgerError as exc:
        raise InvalidInput(
            f"{exc}: FIXTURE data never reaches a real ledger", ["INVALID_INPUT", "FIXTURE_DATA"]
        ) from exc
    except ValidationError as exc:
        raise InvalidInput("invalid ledger input", detail=str(exc)[:500]) from exc


def _dedupe(codes: list[str]) -> list[str]:
    return list(dict.fromkeys(codes))


# --------------------------------------------------------------------------------------
# User settings
# --------------------------------------------------------------------------------------


def _settings_from_row(row: Any) -> S.UserSettings:
    created = parse_iso(row.created_at)
    updated = parse_iso(row.updated_at)
    assert created is not None and updated is not None
    cap = dbm.from_cents(row.daily_cap_cents)
    assert cap is not None
    return S.UserSettings(
        user_id=row.user_id,
        daily_cap_usd=cap,
        display_tz=row.display_tz,
        onboarding_complete=bool(row.onboarding_complete),
        has_own_odds_api_key=bool(row.odds_api_key_encrypted),
        created_at_utc=created,
        updated_at_utc=updated,
    )


def get_user_settings(ctx: RequestContext) -> S.UserSettings:
    """The user's settings row, created with defaults (cap, display tz, onboarding incomplete) on first use."""
    now = ctx.clock.now_utc()
    with ctx.db.tx() as conn:
        row = conn.execute(
            select(dbm.user_settings).where(dbm.user_settings.c.user_id == ctx.user_id)
        ).first()
        if row is None:
            if (
                conn.execute(select(dbm.users.c.user_id).where(dbm.users.c.user_id == ctx.user_id)).first()
                is None
            ):
                conn.execute(
                    insert(dbm.users).values(
                        user_id=ctx.user_id, email=None, display_name=None, disabled=0, created_at=iso(now)
                    )
                )
            conn.execute(
                insert(dbm.user_settings).values(
                    user_id=ctx.user_id,
                    daily_cap_cents=dbm.cents(ctx.settings.daily_cap_usd_default),
                    display_tz=ctx.settings.display_tz,
                    onboarding_complete=0,
                    odds_api_key_encrypted=None,
                    created_at=iso(now),
                    updated_at=iso(now),
                )
            )
            row = conn.execute(
                select(dbm.user_settings).where(dbm.user_settings.c.user_id == ctx.user_id)
            ).one()
        return _settings_from_row(row)


def set_user_settings(
    ctx: RequestContext,
    daily_cap_usd: Decimal | None = None,
    display_tz: str | None = None,
    odds_api_key: str | None = None,
    confirm_onboarding: bool = False,
) -> S.UserSettings:
    """Update the cap (> 0), display time zone (valid zoneinfo name), a per-user odds key (Fernet-encrypted
    with a key derived from ``settings.secret_key``; an empty string clears it), or confirm onboarding."""
    get_user_settings(ctx)
    values: dict[str, Any] = {}
    if daily_cap_usd is not None:
        cap = _money(daily_cap_usd, "daily_cap_usd")
        values["daily_cap_cents"] = dbm.cents(cap)
    if display_tz is not None:
        try:
            ZoneInfo(display_tz)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise InvalidInput(f"unknown time zone: {display_tz!r}") from exc
        values["display_tz"] = display_tz
    if odds_api_key is not None:
        key = odds_api_key.strip()
        if key == "":
            values["odds_api_key_encrypted"] = None
        else:
            fernet = _fernet(ctx.settings)
            if fernet is None:
                raise InvalidInput(
                    "per-user odds keys need HRNBA_SECRET_KEY on the server (local mode uses HRNBA_ODDS_API_KEY, "
                    "~/.hardrock-nba-parlay/.env, or the keychain instead)"
                )
            values["odds_api_key_encrypted"] = fernet.encrypt(key.encode("utf-8")).decode("utf-8")
    if confirm_onboarding:
        values["onboarding_complete"] = 1
    now = ctx.clock.now_utc()
    with ctx.db.tx() as conn:
        if values:
            values["updated_at"] = iso(now)
            conn.execute(
                update(dbm.user_settings).where(dbm.user_settings.c.user_id == ctx.user_id).values(**values)
            )
            budget.write_audit(
                conn,
                ctx.user_id,
                "settings.update",
                None,
                {k: ("[set]" if k == "odds_api_key_encrypted" else v) for k, v in values.items()},
                now,
            )
        row = conn.execute(select(dbm.user_settings).where(dbm.user_settings.c.user_id == ctx.user_id)).one()
    return _settings_from_row(row)


def _onboarding_complete(ctx: RequestContext) -> bool:
    return get_user_settings(ctx).onboarding_complete


def _with_onboarding(ctx: RequestContext, obj: Any) -> Any:
    """Add NEEDS_ONBOARDING to the response (never to persisted records) while onboarding is incomplete."""
    if _onboarding_complete(ctx):
        return obj
    if isinstance(obj, S.Candidate | S.LegAnalysis):
        if ONBOARDING_CODE in obj.reason_codes:
            return obj
        return obj.model_copy(update={"reason_codes": [*obj.reason_codes, ONBOARDING_CODE]})
    if isinstance(obj, S.SelectResponse):
        return obj.model_copy(update={"candidate": _with_onboarding(ctx, obj.candidate)})
    if isinstance(obj, S.ReviewReport):
        return obj.model_copy(update={"performance": _with_onboarding(ctx, obj.performance)})
    if isinstance(obj, S.CoverageReport | S.PerformanceReport):
        if ONBOARDING_HINT in obj.notes:
            return obj
        return obj.model_copy(update={"notes": [*obj.notes, ONBOARDING_HINT]})
    warnings = getattr(obj, "warnings", None)
    if isinstance(warnings, list) and ONBOARDING_CODE not in warnings:
        return obj.model_copy(update={"warnings": [*warnings, ONBOARDING_CODE]})
    return obj


# --------------------------------------------------------------------------------------
# Hosted per-user credit quota
# --------------------------------------------------------------------------------------


def _credits_used_today(ctx: RequestContext) -> int:
    start, end = local_day_bounds_utc(_today(ctx))
    with ctx.db.engine.connect() as conn:
        total = conn.execute(
            select(func.coalesce(func.sum(dbm.provider_usage.c.credits_cost), 0)).where(
                dbm.provider_usage.c.user_id == ctx.user_id,
                dbm.provider_usage.c.created_at >= iso(start),
                dbm.provider_usage.c.created_at < iso(end),
            )
        ).scalar_one()
    return int(total or 0)


def _guard_credits(ctx: RequestContext) -> None:
    """Hosted per-user quota on the SERVER-WIDE key only (section 11); a user's own key is never throttled."""
    reg = _registry(ctx)
    if reg.data_mode != S.DataMode.LIVE_PROVIDER or ctx.settings.auth_mode == "none":
        return
    if reg.key_source == "user":
        return
    used = _credits_used_today(ctx)
    quota = ctx.settings.per_user_daily_credit_quota
    if used >= quota:
        raise ServiceError(
            f"your daily provider credit quota is used up ({used} of {quota} credits today, America/New_York day)",
            ["PROVIDER_CREDIT_GUARD"],
            detail="store your own The Odds API key with set_user_settings(odds_api_key=...) or wait for the next day",
        )


def _provider_usage_summary(ctx: RequestContext) -> tuple[datetime | None, dict[str, int | None]]:
    with ctx.db.engine.connect() as conn:
        row = conn.execute(
            select(dbm.provider_usage)
            .where(dbm.provider_usage.c.provider == odds_api.PROVIDER_NAME)
            .order_by(dbm.provider_usage.c.created_at.desc(), dbm.provider_usage.c.id.desc())
            .limit(1)
        ).first()
    if row is None:
        return None, empty_quota()
    quota = empty_quota()
    quota["requests_remaining"] = row.requests_remaining
    quota["requests_used"] = row.requests_used
    return parse_iso(row.created_at), quota


# --------------------------------------------------------------------------------------
# Market data fetch and persistence
# --------------------------------------------------------------------------------------


@dataclass
class MarketData:
    """Everything one research call fetched, with provenance, credits and warnings."""

    date_local: str
    data_mode: S.DataMode
    events: list[S.Event] = field(default_factory=list)
    target_quotes: list[S.MarketQuote] = field(default_factory=list)
    reference_quotes: list[S.MarketQuote] = field(default_factory=list)
    injuries: list[S.InjuryContext] = field(default_factory=list)
    injury_stamp: S.SourceStamp | None = None
    stamps: list[S.SourceStamp] = field(default_factory=list)
    credits_used: int = 0
    quota: dict[str, int | None] = field(default_factory=empty_quota)
    warnings: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    props_fetched_for: list[str] = field(default_factory=list)

    def absorb(self, result: ProviderResult[Any]) -> None:
        self.credits_used += result.credits_cost or 0
        if any(v is not None for v in result.quota.values()):
            self.quota = dict(result.quota)
        for w in result.warnings:
            if w not in self.warnings:
                self.warnings.append(w)
        for c in result.reason_codes:
            if c not in self.reason_codes:
                self.reason_codes.append(c)
        self.stamps.append(result.stamp)


def _featured_books(settings: Settings) -> list[str]:
    return list(dict.fromkeys([settings.target_book, *settings.reference_books]))


def _prop_books(settings: Settings) -> list[str]:
    return list(dict.fromkeys([settings.target_book, *settings.prop_reference_books]))


def _split_quotes(ctx: RequestContext, quotes: list[S.MarketQuote], data: MarketData) -> None:
    for q in quotes:
        (data.target_quotes if q.book == ctx.settings.target_book else data.reference_quotes).append(q)


def _fetch_events(ctx: RequestContext, date_local: str, data: MarketData) -> None:
    result = _odds(ctx).list_events(date_local)
    data.absorb(result)
    data.events = list(result.data)


def _fetch_featured(ctx: RequestContext, date_local: str, data: MarketData) -> None:
    _guard_credits(ctx)
    result = _odds(ctx).fetch_featured_odds(date_local, _featured_books(ctx.settings), list(FEATURED_MARKETS))
    data.absorb(result)
    _split_quotes(ctx, list(result.data), data)


def _fetch_props(ctx: RequestContext, events: list[S.Event], data: MarketData) -> None:
    for event in events:
        if event.event_id in data.props_fetched_for:
            continue
        _guard_credits(ctx)
        result = _odds(ctx).fetch_event_props(
            event.event_id, _prop_books(ctx.settings), list(PROP_MARKETS), True
        )
        data.absorb(result)
        _split_quotes(ctx, list(result.data), data)
        data.props_fetched_for.append(event.event_id)


def _fetch_injuries(ctx: RequestContext, events: list[S.Event], data: MarketData) -> None:
    reg = _registry(ctx)
    if reg.injury is None:
        data.warnings.append(
            "INJURY_REPORT_MISSING: automatic injury-report fetch is disabled (HRNBA_INJURY_AUTO_FETCH=false); "
            "confirm availability from the official report yourself"
        )
        data.reason_codes.append("INJURY_REPORT_MISSING")
        return
    try:
        result = reg.injury.fetch_latest_report(ctx.clock.now_utc(), list(events))
    except ProviderError as exc:
        # An unavailable report is a modelled state (INJURY_REPORT_MISSING, data quality downgraded), not a
        # reason to abandon a slate whose odds credits were already spent.
        why = redact(exc.message)
        logger.warning("injury report fetch failed; continuing without it: %s", why)
        data.warnings.append(
            f"INJURY_REPORT_MISSING: the official injury report could not be fetched ({why}); "
            "confirm availability from the official report yourself"
        )
        if "INJURY_REPORT_MISSING" not in data.reason_codes:
            data.reason_codes.append("INJURY_REPORT_MISSING")
        data.injuries = []
        data.injury_stamp = None
        return
    data.absorb(result)
    data.injuries = list(result.data)
    data.injury_stamp = result.stamp
    if not data.injuries and "INJURY_REPORT_MISSING" not in data.reason_codes:
        data.reason_codes.append("INJURY_REPORT_MISSING")


def _fetch_market_data(ctx: RequestContext, date_local: str, *, include_props: bool) -> MarketData:
    reg = _registry(ctx)
    data = MarketData(date_local=date_local, data_mode=reg.data_mode)
    _fetch_events(ctx, date_local, data)
    if data.events:
        _fetch_featured(ctx, date_local, data)
        if include_props:
            _fetch_props(ctx, data.events, data)
    _fetch_injuries(ctx, data.events, data)
    if data.data_mode == S.DataMode.FIXTURE and FIXTURE_WARNING not in data.warnings:
        data.warnings.append(FIXTURE_WARNING)
    return data


def _upsert_events(conn: Any, events: list[S.Event]) -> None:
    for event in events:
        payload = dumps(event.model_dump(mode="json"))
        received = iso(event.stamp.received_at_utc)
        exists = conn.execute(
            select(dbm.events_cache.c.event_id).where(dbm.events_cache.c.event_id == event.event_id)
        ).first()
        if exists is None:
            conn.execute(
                insert(dbm.events_cache).values(event_id=event.event_id, json=payload, received_at=received)
            )
        else:
            conn.execute(
                update(dbm.events_cache)
                .where(dbm.events_cache.c.event_id == event.event_id)
                .values(json=payload, received_at=received)
            )


def _persist_events(ctx: RequestContext, events: list[S.Event]) -> None:
    with ctx.db.tx() as conn:
        _upsert_events(conn, events)


def _persist_market_data(ctx: RequestContext, data: MarketData) -> None:
    """events_cache upsert plus odds_snapshots / injury_snapshots rows (append-only provenance)."""
    with ctx.db.tx() as conn:
        _upsert_events(conn, data.events)
        for q in [*data.target_quotes, *data.reference_quotes]:
            conn.execute(
                insert(dbm.odds_snapshots).values(
                    snapshot_id=new_id("odds"),
                    user_id=ctx.user_id,
                    event_id=q.event_id,
                    book=q.book,
                    market_type=q.market_type.value,
                    period=q.period.value,
                    is_alternate=1 if q.is_alternate else 0,
                    side=q.side.value,
                    line=None if q.line is None else format(q.line.normalize(), "f"),
                    player_id=q.player_id,
                    odds_decimal=str(q.odds_decimal),
                    source_ts=iso(q.stamp.source_timestamp_utc),
                    received_at=iso(q.stamp.received_at_utc),
                    data_mode=q.stamp.data_mode.value,
                    json=dumps(q.model_dump(mode="json")),
                )
            )
        for entry in data.injuries:
            conn.execute(
                insert(dbm.injury_snapshots).values(
                    snapshot_id=new_id("inj"),
                    report_ts=iso(entry.report_timestamp_utc),
                    event_id=entry.event_id,
                    team_id=entry.team_id,
                    player_id=entry.player_id,
                    designation=entry.designation.value,
                    json=dumps(entry.model_dump(mode="json")),
                    received_at=iso(entry.stamp.received_at_utc),
                )
            )


def _cached_event(ctx: RequestContext, event_id: str) -> S.Event | None:
    with ctx.db.engine.connect() as conn:
        row = conn.execute(select(dbm.events_cache).where(dbm.events_cache.c.event_id == event_id)).first()
    if row is None:
        return None
    try:
        return S.Event.model_validate(loads(row.json))
    except ValidationError:
        return None


# --------------------------------------------------------------------------------------
# Candidate persistence
# --------------------------------------------------------------------------------------


def _candidate_date(candidate: S.Candidate) -> str:
    return local_date(candidate.expires_at_utc)


def _append_history(
    conn: Any,
    ctx: RequestContext,
    candidate_id: str,
    from_state: S.CandidateState | None,
    to_state: S.CandidateState,
    reason: str,
    extra: dict[str, Any] | None,
    now: datetime,
) -> None:
    conn.execute(
        insert(dbm.candidate_history).values(
            candidate_id=candidate_id,
            user_id=ctx.user_id,
            from_state=from_state.value if from_state is not None else None,
            to_state=to_state.value,
            reason=reason,
            json=dumps(extra) if extra else None,
            created_at=iso(now),
        )
    )


def save_candidate(
    ctx: RequestContext,
    candidate: S.Candidate,
    *,
    from_state: S.CandidateState | None = None,
    reason: str | None = None,
    extra: dict[str, Any] | None = None,
    date_local: str | None = None,
) -> None:
    """Insert or update the candidate row for ``ctx.user_id``; with ``reason`` also append a history row."""
    if candidate.user_id != ctx.user_id:
        raise NotFound("candidate not found", detail=candidate.candidate_id)
    now = ctx.clock.now_utc()
    payload = dumps(candidate.model_dump(mode="json"))
    with ctx.db.tx() as conn:
        existing = conn.execute(
            select(dbm.candidates.c.candidate_id).where(
                dbm.candidates.c.candidate_id == candidate.candidate_id,
                dbm.candidates.c.user_id == ctx.user_id,
            )
        ).first()
        values = {
            "state": candidate.state.value,
            "parlay_type": candidate.parlay_type.value,
            "data_mode": candidate.data_mode.value,
            "json": payload,
            "updated_at": iso(candidate.updated_at_utc),
            "expires_at": iso(candidate.expires_at_utc),
        }
        if existing is None:
            conn.execute(
                insert(dbm.candidates).values(
                    candidate_id=candidate.candidate_id,
                    user_id=ctx.user_id,
                    date_local=date_local or _candidate_date(candidate),
                    created_at=iso(candidate.created_at_utc),
                    **values,
                )
            )
        else:
            conn.execute(
                update(dbm.candidates)
                .where(
                    dbm.candidates.c.candidate_id == candidate.candidate_id,
                    dbm.candidates.c.user_id == ctx.user_id,
                )
                .values(**values)
            )
        if reason is not None:
            _append_history(
                conn, ctx, candidate.candidate_id, from_state, candidate.state, reason, extra, now
            )


def load_candidate(ctx: RequestContext, candidate_id: str) -> S.Candidate:
    """The user's candidate; ``NotFound`` for an unknown id or another user's candidate."""
    with ctx.db.engine.connect() as conn:
        row = conn.execute(
            select(dbm.candidates).where(
                dbm.candidates.c.candidate_id == candidate_id, dbm.candidates.c.user_id == ctx.user_id
            )
        ).first()
    if row is None:
        raise NotFound("candidate not found for this user", detail=candidate_id)
    return S.Candidate.model_validate(loads(row.json))


def list_candidate_history(ctx: RequestContext, candidate_id: str) -> list[dict[str, Any]]:
    """Append-only state history of the user's candidate (oldest first)."""
    with ctx.db.engine.connect() as conn:
        rows = (
            conn.execute(
                select(dbm.candidate_history)
                .where(
                    dbm.candidate_history.c.candidate_id == candidate_id,
                    dbm.candidate_history.c.user_id == ctx.user_id,
                )
                .order_by(dbm.candidate_history.c.id)
            )
            .mappings()
            .all()
        )
    return [dict(r) for r in rows]


def transition(
    ctx: RequestContext,
    candidate: S.Candidate,
    to_state: S.CandidateState,
    reason: str,
    extra: dict[str, Any] | None = None,
) -> S.Candidate:
    """Move the candidate to ``to_state`` with an append-only history row; returns the stored candidate."""
    updated = quote_review.rebuild_candidate(candidate, state=to_state, updated_at_utc=ctx.clock.now_utc())
    save_candidate(ctx, updated, from_state=candidate.state, reason=reason, extra=extra)
    return updated


def _save_book_quote(ctx: RequestContext, book_quote: S.BookQuote | None) -> None:
    if book_quote is None:
        return
    with ctx.db.tx() as conn:
        exists = conn.execute(
            select(dbm.book_quotes.c.book_quote_id).where(
                dbm.book_quotes.c.book_quote_id == book_quote.book_quote_id
            )
        ).first()
        if exists is None:
            conn.execute(
                insert(dbm.book_quotes).values(
                    book_quote_id=book_quote.book_quote_id,
                    candidate_id=book_quote.candidate_id,
                    user_id=ctx.user_id,
                    json=dumps(book_quote.model_dump(mode="json")),
                    created_at=iso(ctx.clock.now_utc()),
                )
            )


# --------------------------------------------------------------------------------------
# Status and coverage
# --------------------------------------------------------------------------------------


def get_system_status(ctx: RequestContext) -> S.SystemStatus:
    now = ctx.clock.now_utc()
    reg = _registry(ctx)
    prefs = get_user_settings(ctx)
    last_ok, quota = _provider_usage_summary(ctx)
    modes: list[S.DataMode] = []
    if reg.key_configured:
        modes.append(S.DataMode.LIVE_PROVIDER)
    modes.append(S.DataMode.MANUAL_INPUT)
    if ctx.settings.data_mode == "fixture":
        modes.append(S.DataMode.FIXTURE)
    warnings = list(reg.warnings)
    if ctx.settings.data_mode == "fixture":
        warnings.append(FIXTURE_WARNING + " (HRNBA_DATA_MODE=fixture)")
    elif not reg.key_configured:
        warnings.append(f"NO_PROVIDER_KEY: no The Odds API key resolves; {NO_KEY_HINT}")
    if not ctx.settings.injury_auto_fetch:
        warnings.append("injury-report auto fetch is disabled; availability must be confirmed manually")
    return S.SystemStatus(
        app_version=ctx.settings.version,
        now_utc=now,
        now_display=to_display(now, prefs.display_tz),
        display_tz=prefs.display_tz,
        auth_mode=ctx.settings.auth_mode,
        user_id_masked=mask_user_id(ctx.user_id),
        database_ok=ctx.db.ping(),
        database_kind=ctx.db.kind,
        provider_configured=reg.key_configured,
        provider_last_ok_utc=last_ok,
        provider_quota=quota,
        data_modes_available=modes,
        target_book=ctx.settings.target_book,
        jurisdiction=ctx.settings.target_jurisdiction,
        daily_cap_usd=prefs.daily_cap_usd,
        onboarding_complete=prefs.onboarding_complete,
        warnings=warnings,
    )


def _coverage_item(
    status: S.CoverageStatus, detail: str, codes: list[str] | None = None, stamp: S.SourceStamp | None = None
) -> S.CoverageItem:
    return S.CoverageItem(status=status, detail=detail, reason_codes=_dedupe(codes or []), stamp=stamp)


def _count_status(n: int, total: int) -> S.CoverageStatus:
    if total == 0 or n == 0:
        return S.CoverageStatus.BLOCKED
    return S.CoverageStatus.PASS if n == total else S.CoverageStatus.PARTIAL


def check_data_coverage(ctx: RequestContext, date_local: str, probe_props: bool = False) -> S.CoverageReport:
    """What the tool can and cannot see for the day. ``probe_props`` spends one credit per game (live mode)."""
    _validate_date(date_local)
    now = ctx.clock.now_utc()
    reg = _registry(ctx)
    odds = _odds(ctx)
    data = MarketData(date_local=date_local, data_mode=reg.data_mode)
    _fetch_events(ctx, date_local, data)
    events = data.events
    if events:
        _fetch_featured(ctx, date_local, data)
    markets_by_event: dict[str, dict[str, list[str]]] = {}
    if probe_props:
        for event in events:
            _guard_credits(ctx)
            res = odds.list_event_markets(event.event_id, _prop_books(ctx.settings))
            data.absorb(res)
            markets_by_event[event.event_id] = dict(res.data)
    _fetch_injuries(ctx, events, data)

    target = ctx.settings.target_book
    total_events = len(events)
    odds_stamp = data.stamps[1] if len(data.stamps) > 1 else None
    single_leg: dict[str, S.CoverageItem] = {}
    reference_markets: dict[str, S.CoverageItem] = {}
    selections = normalization.build_selections(data.target_quotes, events)
    skews: list[float] = []
    for market in S.MarketType:
        key = market.value
        if market in FEATURED_MARKETS:
            with_target = {q.event_id for q in data.target_quotes if q.market_type == market}
            n = len(with_target)
            if total_events == 0:
                single_leg[key] = _coverage_item(S.CoverageStatus.UNKNOWN, f"no NBA games on {date_local}")
                reference_markets[key] = _coverage_item(
                    S.CoverageStatus.UNKNOWN, f"no NBA games on {date_local}"
                )
                continue
            codes = ["BOOK_NOT_AVAILABLE"] if "BOOK_NOT_AVAILABLE" in data.reason_codes else []
            if n == 0:
                codes = codes or ["MARKET_NOT_OFFERED"]
            single_leg[key] = _coverage_item(
                _count_status(n, total_events),
                f"{target} {key} seen for {n} of {total_events} games",
                codes,
                odds_stamp,
            )
            legs = [s for s in selections if s.quote.market_type == market]
            matched = 0
            reasons: list[str] = []
            for sel in legs:
                ref, why = normalization.pair_reference_with_reasons(
                    sel, data.reference_quotes, ctx.settings.reference_books
                )
                if ref is None:
                    reasons += why
                    continue
                matched += 1
                t_ts, r_ts = sel.quote.stamp.source_timestamp_utc, ref.stamp.source_timestamp_utc
                if t_ts is not None and r_ts is not None:
                    skews.append(abs((t_ts - r_ts).total_seconds()))
            if not legs:
                reference_markets[key] = _coverage_item(
                    S.CoverageStatus.BLOCKED, f"no {target} {key} legs to benchmark", ["REFERENCE_MISSING"]
                )
            else:
                reference_markets[key] = _coverage_item(
                    _count_status(matched, len(legs)),
                    f"{matched} of {len(legs)} {target} {key} legs have a complete {'/'.join(ctx.settings.reference_books)} two-way at the same line",
                    reasons if matched < len(legs) else [],
                    odds_stamp,
                )
            continue
        # Props and team totals: only a markets probe (or a props fetch) can say.
        if not probe_props:
            single_leg[key] = _coverage_item(
                S.CoverageStatus.UNKNOWN, "not probed (probe_props=false; one credit per game in live mode)"
            )
            reference_markets[key] = _coverage_item(
                S.CoverageStatus.UNKNOWN, "not probed (probe_props=false)"
            )
            continue
        main_key = odds_api.PROP_MARKET_KEYS.get(market) or (
            "team_totals" if market == S.MarketType.TEAM_TOTAL else None
        )
        offered = [
            e
            for e in events
            if main_key
            and any(k.startswith(main_key) for k in markets_by_event.get(e.event_id, {}).get(target, []))
        ]
        ref_offered = [
            e
            for e in events
            if main_key
            and any(
                k.startswith(main_key)
                for b in ctx.settings.prop_reference_books
                for k in markets_by_event.get(e.event_id, {}).get(b, [])
            )
        ]
        single_leg[key] = _coverage_item(
            _count_status(len(offered), total_events),
            f"{target} lists {main_key} for {len(offered)} of {total_events} games",
            [] if offered else ["MARKET_NOT_OFFERED"],
        )
        reference_markets[key] = _coverage_item(
            _count_status(len(ref_offered), total_events),
            f"reference books list {main_key} for {len(ref_offered)} of {total_events} games",
            [] if ref_offered else ["REFERENCE_MISSING"],
        )

    event_ids = {e.event_id for e in events}
    entries = [i for i in data.injuries if i.event_id in event_ids]
    if reg.injury is None:
        injury_item = _coverage_item(
            S.CoverageStatus.PARTIAL,
            "automatic fetch disabled; manual injury entries only",
            ["INJURY_REPORT_MISSING"],
        )
    elif not data.injuries:
        injury_item = _coverage_item(
            S.CoverageStatus.BLOCKED,
            "no official injury report found",
            ["INJURY_REPORT_MISSING"],
            data.injury_stamp,
        )
    else:
        report_ts = injury_context.report_timestamp(data.injuries)
        stale = (
            report_ts is not None
            and (now - report_ts).total_seconds() > ctx.settings.injury_report_max_age_seconds
        )
        when = to_display(report_ts) if report_ts else "unknown time"
        injury_item = _coverage_item(
            S.CoverageStatus.PARTIAL if stale else S.CoverageStatus.PASS,
            f"{len(entries)} entries for {len({i.event_id for i in entries})} of {total_events} games from the {when} report"
            + ("; older than the configured maximum" if stale else ""),
            ["INJURY_REPORT_STALE"] if stale else [],
            data.injury_stamp,
        )

    notes: list[str] = []
    if skews:
        median = statistics.median(skews)
        ok = median <= ctx.settings.max_reference_skew_seconds
        notes.append(
            f"median reference-vs-target last_update skew {median:.0f}s over {len(skews)} matched legs; "
            f"{'within' if ok else 'above'} max_reference_skew_seconds={ctx.settings.max_reference_skew_seconds}"
            + ("" if ok else " (legs above the limit get INSUFFICIENT_EVIDENCE with TIMESTAMP_SKEW)")
        )
    else:
        notes.append("reference skew not measurable: no leg matched a reference two-way")
    notes.append(f"provider credits used by this check: {data.credits_used}")
    if reg.data_mode == S.DataMode.FIXTURE:
        notes.append(FIXTURE_WARNING)
    notes.extend(w for w in data.warnings if w not in notes)

    report = S.CoverageReport(
        date_local=date_local,
        generated_at_utc=now,
        data_mode=reg.data_mode,
        hard_rock_single_leg=single_leg,
        reference_markets=reference_markets,
        injury_information=injury_item,
        three_leg_combinability=_coverage_item(
            S.CoverageStatus.UNKNOWN,
            "whether Hard Rock Bet allows these three legs on one slip is only confirmed by your slip import",
            ["COMBINATION_UNVERIFIED"],
        ),
        combined_payout_verification=_coverage_item(
            S.CoverageStatus.BLOCKED,
            "needs the combined quote shown on your Hard Rock Bet slip (import_hardrock_quote)",
            ["QUOTE_FIELDS_MISSING"],
        ),
        stats_and_settlement_rules=_coverage_item(
            S.CoverageStatus.PARTIAL,
            "team legs can be graded provisionally from final scores; player props are graded manually from box scores; "
            "the book's settlement is authoritative",
            ["PROVISIONAL_RESULT"],
        ),
        provider_quota=data.quota,
        notes=notes,
    )
    return _with_onboarding(ctx, report)


# --------------------------------------------------------------------------------------
# Slate, injuries, single leg
# --------------------------------------------------------------------------------------


def _event_summary(event: S.Event, tz_name: str) -> S.EventSummary:
    return S.EventSummary(
        event_id=event.event_id,
        away=event.away_team.name,
        home=event.home_team.name,
        commence_time_utc=event.commence_time_utc,
        commence_time_display=to_display(event.commence_time_utc, tz_name),
        status=event.status,
        season_stage=event.season_stage,
    )


def get_nba_slate(ctx: RequestContext, date_local: str) -> S.SlateResponse:
    _validate_date(date_local)
    reg = _registry(ctx)
    prefs = get_user_settings(ctx)
    result = _odds(ctx).list_events(date_local)
    events = list(result.data)
    _persist_events(ctx, events)
    warnings = list(result.warnings)
    codes = list(result.reason_codes)
    if reg.data_mode == S.DataMode.FIXTURE and FIXTURE_WARNING not in warnings:
        warnings.append(FIXTURE_WARNING)
    if not events:
        warnings.append(f"no NBA games found for {date_local} (America/New_York)")
    response = S.SlateResponse(
        date_local=date_local,
        events=[_event_summary(e, prefs.display_tz) for e in events],
        data_mode=result.data_mode,
        stamps=[result.stamp],
        warnings=warnings,
        reason_codes=_dedupe(codes),
    )
    return _with_onboarding(ctx, response)


def get_injury_context(ctx: RequestContext, event_id: str) -> S.InjuryResponse:
    event = _cached_event(ctx, event_id)
    if event is None:
        probe = MarketData(date_local=_today(ctx), data_mode=_registry(ctx).data_mode)
        _fetch_events(ctx, probe.date_local, probe)
        event = next((e for e in probe.events if e.event_id == event_id), None)
        if event is None:
            raise NotFound("event not found on the cached or current slate", detail=event_id)
        _persist_events(ctx, probe.events)
    data = MarketData(date_local=local_date(event.commence_time_utc), data_mode=_registry(ctx).data_mode)
    _fetch_events(ctx, data.date_local, data)
    slate = data.events or [event]
    _fetch_injuries(ctx, slate, data)
    team_ids = {event.home_team.team_id, event.away_team.team_id}
    entries = [
        e
        for e in data.injuries
        if e.event_id == event_id or (e.event_id.startswith("unmatched:") and e.team_id in team_ids)
    ]
    report_ts = injury_context.report_timestamp(entries or data.injuries)
    warnings = list(data.warnings)
    codes = list(data.reason_codes)
    if not entries:
        codes.append("INJURY_REPORT_MISSING")
        warnings.append(
            f"no injury-report entries for {event.short_name}; confirm availability from the official report"
        )
    elif (
        report_ts is not None
        and (ctx.clock.now_utc() - report_ts).total_seconds() > ctx.settings.injury_report_max_age_seconds
    ):
        codes.append("INJURY_REPORT_STALE")
        warnings.append(f"the injury report is from {to_display(report_ts)}; a newer one may exist")
    response = S.InjuryResponse(
        event_id=event_id,
        entries=entries,
        report_timestamp_utc=report_ts,
        stamp=data.injury_stamp,
        warnings=warnings,
        reason_codes=_dedupe(codes),
    )
    return _with_onboarding(ctx, response)


def _find_selection(data: MarketData, selection_id: str) -> S.Selection | None:
    selections = normalization.build_selections(data.target_quotes, data.events)
    return next((s for s in selections if s.selection_id == selection_id), None)


def analyze_leg(ctx: RequestContext, selection_id: str, date_local: str | None = None) -> S.LegAnalysis:
    """Analyse one target-book selection. Props are fetched one game at a time, stopping at the first hit,
    because every event-props call costs credits."""
    date_local = _validate_date(date_local or _today(ctx))
    data = _fetch_market_data(ctx, date_local, include_props=False)
    selection = _find_selection(data, selection_id)
    for event in data.events:
        if selection is not None:
            break
        _fetch_props(ctx, [event], data)
        selection = _find_selection(data, selection_id)
    if selection is None:
        raise NotFound(f"selection not on the {date_local} slate", detail=selection_id)
    analysis = candidate_builder.analyze_leg(
        selection, data.reference_quotes, data.injuries, ctx.clock.now_utc(), ctx.settings
    )
    return _with_onboarding(ctx, analysis)


# --------------------------------------------------------------------------------------
# Candidate construction
# --------------------------------------------------------------------------------------


def _stake_for_research(ctx: RequestContext, date_local: str, warnings: list[str]) -> Decimal:
    prefs = get_user_settings(ctx)
    daily = _ledger(
        budget.get_daily_budget, ctx.db, ctx.user_id, date_local, ctx.clock.now_utc(), prefs.daily_cap_usd
    )
    if daily.remaining_usd > 0:
        return min(daily.remaining_usd, prefs.daily_cap_usd)
    warnings.append(
        "BUDGET_EXCEEDED: the day's budget is fully used; payout math is shown at the daily cap for illustration only"
    )
    return prefs.daily_cap_usd


def _no_ticket_reason(
    date_local: str,
    data: MarketData,
    selections: list[S.Selection],
    analyses: dict[str, S.LegAnalysis],
    stats: candidate_builder.SearchStats,
    parlay_type: str,
) -> tuple[str, list[str]]:
    codes = ["NO_SUITABLE_TICKET"]
    if not data.events:
        return f"NO SUITABLE TICKET: no NBA games on {date_local} (America/New_York)", codes
    if not data.target_quotes:
        return (
            f"NO SUITABLE TICKET: no target-book quotes for {date_local}",
            codes
            + (
                ["BOOK_NOT_AVAILABLE"]
                if "BOOK_NOT_AVAILABLE" in data.reason_codes
                else ["MARKET_NOT_OFFERED"]
            ),
        )
    if stats.legs_usable == 0:
        counts: dict[str, int] = {}
        waiting = 0
        for a in analyses.values():
            if a.decision == S.LegDecision.WAIT_FOR_UPDATE:
                waiting += 1
            for c in a.reason_codes:
                if c in (
                    "QUOTE_STALE",
                    "GAME_STARTED",
                    "GAME_POSTPONED",
                    "INJURY_OUT",
                    "INJURY_DOUBTFUL",
                    "INJURY_QUESTIONABLE_MATERIAL",
                    "WAIT_FOR_UPDATE",
                    "PERIOD_UNSUPPORTED",
                    "MARKET_SUSPENDED",
                ):
                    counts[c] = counts.get(c, 0) + 1
        top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        summary = ", ".join(f"{c} x{n}" for c, n in top) or "no usable leg"
        if waiting and waiting == len(analyses):
            codes.append("WAIT_FOR_UPDATE")
        codes += [c for c, _ in top[:3]]
        return (
            f"NO SUITABLE TICKET: none of the {len(selections)} legs is usable right now ({summary})",
            codes,
        )
    if (
        parlay_type in ("auto", "multi_game")
        and stats.events_with_usable_legs < 3
        and parlay_type == "multi_game"
    ):
        return (
            f"NO SUITABLE TICKET: only {stats.events_with_usable_legs} game(s) have usable legs; a multi-game ticket needs three",
            codes,
        )
    if parlay_type == "same_game" and stats.combinations_evaluated == 0:
        return "NO SUITABLE TICKET: no game has three usable legs for a same-game ticket", codes
    return (
        f"NO SUITABLE TICKET: {stats.combinations_evaluated} combination(s) evaluated, "
        f"{stats.combinations_rejected} rejected as not combinable, none left for {stats.mode or parlay_type}",
        codes,
    )


def build_three_leg_parlays(
    ctx: RequestContext,
    date_local: str,
    parlay_type: str = "auto",
    max_candidates: int = 3,
    include_props: bool = True,
) -> S.BuildResponse:
    """Research candidate tickets for the day; persists snapshots and candidate records (NEEDS_BOOK_QUOTE)."""
    _validate_date(date_local)
    if parlay_type not in candidate_builder.PARLAY_TYPE_ARGS:
        raise InvalidInput(f"parlay_type must be one of {candidate_builder.PARLAY_TYPE_ARGS}")
    if not 1 <= int(max_candidates) <= 10:
        raise InvalidInput("max_candidates must be between 1 and 10")
    now = ctx.clock.now_utc()
    data = _fetch_market_data(ctx, date_local, include_props=include_props)
    _persist_market_data(ctx, data)
    selections = normalization.build_selections(data.target_quotes, data.events)
    analyses = {
        s.selection_id: candidate_builder.analyze_leg(
            s, data.reference_quotes, data.injuries, now, ctx.settings
        )
        for s in selections
    }
    warnings = list(data.warnings)
    stake = _stake_for_research(ctx, date_local, warnings)
    stats = candidate_builder.SearchStats()
    candidates = candidate_builder.build_candidates(
        selections,
        data.reference_quotes,
        data.injuries,
        parlay_type,
        int(max_candidates),
        now,
        ctx.settings,
        ctx.user_id,
        stake,
        analyses=analyses,
        stats=stats,
    )
    codes = list(data.reason_codes)
    no_ticket: str | None = None
    if not candidates:
        no_ticket, extra_codes = _no_ticket_reason(date_local, data, selections, analyses, stats, parlay_type)
        codes += extra_codes
    for cand in candidates:
        save_candidate(
            ctx,
            cand,
            from_state=S.CandidateState.RESEARCH_CANDIDATE,
            reason="built by build_three_leg_parlays",
            extra={"parlay_type_arg": parlay_type, "date_local": date_local, "ranking": cand.ranking},
            date_local=date_local,
        )
    usable = sum(1 for a in analyses.values() if a.decision == S.LegDecision.USABLE)
    waiting = sum(1 for a in analyses.values() if a.decision == S.LegDecision.WAIT_FOR_UPDATE)
    with_reference = sum(1 for a in analyses.values() if a.probability.value is not None)
    coverage_summary = {
        "events": str(len(data.events)),
        "target_quotes": str(len(data.target_quotes)),
        "reference_quotes": str(len(data.reference_quotes)),
        "injury_entries": str(len(data.injuries)),
        "legs_usable": f"{usable}/{len(selections)}",
        "legs_waiting": str(waiting),
        "legs_with_reference": f"{with_reference}/{len(selections)}",
        "events_with_usable_legs": str(stats.events_with_usable_legs),
        "search_mode": stats.mode or parlay_type,
        "stake_used_for_payout_math": str(stake),
        "data_mode": data.data_mode.value,
    }
    if waiting:
        codes.append("WAIT_FOR_UPDATE")
    response = S.BuildResponse(
        date_local=date_local,
        candidates=candidates,
        primary_candidate_id=candidates[0].candidate_id if candidates else None,
        no_ticket_reason=no_ticket,
        reason_codes=_dedupe(codes),
        coverage_summary=coverage_summary,
        data_mode=data.data_mode,
        credits_used=data.credits_used,
        legs_considered=stats.legs_considered,
        combinations_evaluated=stats.combinations_evaluated,
        warnings=warnings,
    )
    return _with_onboarding(ctx, response)


def analyze_my_parlay(
    ctx: RequestContext,
    selections: list[S.ManualSelectionInput] | list[dict[str, Any]],
    combined: S.ManualQuoteInput | dict[str, Any] | None = None,
    date_local: str | None = None,
) -> S.Candidate:
    """Analyse the user's own three legs against the slate; creates one candidate record."""
    date_local = _validate_date(date_local or _today(ctx))
    inputs = [_coerce(S.ManualSelectionInput, item, "selection") for item in list(selections)]
    quote = _coerce(S.ManualQuoteInput, combined, "combined quote") if combined is not None else None
    if len(inputs) != 3:
        raise InvalidInput(
            f"a ticket must contain exactly three selections ({len(inputs)} given)", ["NOT_THREE_LEGS"]
        )
    now = ctx.clock.now_utc()
    data = _fetch_market_data(ctx, date_local, include_props=False)
    if not data.events:
        raise InvalidInput(
            f"no NBA games on {date_local} to match the selections against", ["EVENT_UNMATCHED"]
        )
    prop_events: list[S.Event] = []
    for item in inputs:
        if item.market in S.PLAYER_MARKETS or item.is_alternate:
            event = normalization.match_event(item.game, data.events)
            if event not in prop_events:
                prop_events.append(event)
    if prop_events:
        _fetch_props(ctx, prop_events, data)
    _persist_market_data(ctx, data)
    warnings: list[str] = []
    stake = _stake_for_research(ctx, date_local, warnings)
    candidate = quote_review.analyze_user_ticket(
        inputs,
        quote,
        data.events,
        data.reference_quotes,
        data.injuries,
        now,
        ctx.settings,
        ctx.user_id,
        stake,
        clock=ctx.clock,
    )
    save_candidate(
        ctx,
        candidate,
        from_state=S.CandidateState.RESEARCH_CANDIDATE,
        reason="built by analyze_my_parlay",
        extra={"date_local": date_local, "legs": [leg.description for leg in candidate.ticket.legs]},
        date_local=date_local,
    )
    _save_book_quote(ctx, candidate.book_quote)
    return _with_onboarding(ctx, candidate)


def check_parlay_correlation(ctx: RequestContext, candidate_id: str) -> S.CorrelationReport:
    return load_candidate(ctx, candidate_id).correlation


def import_hardrock_quote(
    ctx: RequestContext, candidate_id: str, quote: S.ManualQuoteInput | dict[str, Any]
) -> S.Candidate:
    """Attach the combined quote Hard Rock Bet shows; the book quote replaces the indicative price."""
    quote_input = _coerce(S.ManualQuoteInput, quote, "quote")
    candidate = load_candidate(ctx, candidate_id)
    if candidate.state in _TERMINAL_STATES:
        raise InvalidInput(f"candidate is {candidate.state.value}; its quote can no longer change")
    updated, codes = quote_review.review_book_quote(candidate, quote_input, ctx.clock.now_utc(), ctx.settings)
    if "QUOTE_FIELDS_MISSING" in codes:
        raise InvalidInput("the quote needs combined_decimal or combined_american", ["QUOTE_FIELDS_MISSING"])
    save_candidate(
        ctx,
        updated,
        from_state=candidate.state,
        reason="import_hardrock_quote: " + ", ".join(codes),
        extra={
            "book_quote_id": updated.book_quote.book_quote_id if updated.book_quote else None,
            "combined_decimal": str(updated.book_quote.combined_decimal) if updated.book_quote else None,
            "reason_codes": codes,
        },
    )
    _save_book_quote(ctx, updated.book_quote)
    return _with_onboarding(ctx, updated)


def refresh_parlay(ctx: RequestContext, candidate_id: str) -> S.Candidate:
    """Re-validate a candidate against freshly fetched quotes, references and injuries."""
    candidate = load_candidate(ctx, candidate_id)
    if candidate.state in _TERMINAL_STATES:
        raise InvalidInput(f"candidate is {candidate.state.value}; nothing to refresh")
    now = ctx.clock.now_utc()
    date_local = _candidate_date(candidate)
    event_ids = set(candidate.ticket.event_ids)
    reg = _registry(ctx)
    if reg.fixture is not None:
        reg.fixture.clear_cache()
    elif reg.odds is not None and hasattr(reg.odds, "clear_cache"):
        reg.odds.clear_cache()
    data = _fetch_market_data(ctx, date_local, include_props=False)
    needs_props = any(
        leg.quote.market_type in S.PLAYER_MARKETS or leg.quote.is_alternate for leg in candidate.ticket.legs
    )
    if needs_props:
        _fetch_props(ctx, [e for e in data.events if e.event_id in event_ids], data)
    _persist_market_data(ctx, data)
    fresh = normalization.build_selections(
        [q for q in data.target_quotes if q.event_id in event_ids], data.events
    )
    # quote_review.revalidate keeps a typed (MANUAL_INPUT) leg at the line the user typed unless the feed
    # carries exactly the same bet; it is never rewritten to the feed's main line nor called suspended.
    updated = quote_review.revalidate(
        candidate, fresh, data.reference_quotes, data.injuries, now, ctx.settings
    )
    new_codes = [c for c in updated.reason_codes if c not in candidate.reason_codes]
    save_candidate(
        ctx,
        updated,
        from_state=candidate.state,
        reason="refresh_parlay: " + (", ".join(new_codes) if new_codes else "inputs refreshed"),
        extra={"credits_used": data.credits_used, "data_mode": data.data_mode.value},
    )
    return _with_onboarding(ctx, updated)


# --------------------------------------------------------------------------------------
# Budget and ledger
# --------------------------------------------------------------------------------------


def _not_ready_error(candidate: S.Candidate) -> ServiceError:
    state = candidate.state
    codes: list[str]
    if state == S.CandidateState.NEEDS_BOOK_QUOTE:
        bq = candidate.book_quote
        if bq is None:
            codes, what = (
                ["QUOTE_FIELDS_MISSING"],
                "import the combined quote shown on your slip (import_hardrock_quote)",
            )
        elif "legs_as_shown" in bq.unresolved_fields:
            codes, what = (
                ["QUOTE_CONFLICTS_WITH_LEGS"],
                "the imported slip legs do not match this candidate; re-import",
            )
        elif "combined_odds" in bq.unresolved_fields:
            codes, what = (
                ["QUOTE_SIGN_AMBIGUOUS"],
                "the imported American and decimal combined prices disagree; re-import one consistent price",
            )
        elif "payout_shown_usd" in bq.unresolved_fields:
            codes, what = (
                ["QUOTE_SIGN_AMBIGUOUS"],
                "the imported slip payout contradicts the combined price; re-check the slip and re-import",
            )
        elif "captured_at_utc" in bq.unresolved_fields:
            codes, what = (
                ["QUOTE_STALE"],
                "the imported slip quote was captured too long ago; re-import a current quote",
            )
        elif "price_changed" in bq.unresolved_fields or "QUOTE_STALE" in candidate.reason_codes:
            codes, what = ["QUOTE_STALE"], "run refresh_parlay, then re-import the slip quote"
        elif not bq.confirmed_by_user:
            codes, what = ["QUOTE_UNCONFIRMED"], "re-import the quote with user_confirmed=true"
        elif "WAIT_FOR_UPDATE" in candidate.reason_codes:
            codes, what = ["WAIT_FOR_UPDATE"], "a leg is waiting for an injury update; refresh_parlay later"
        else:
            codes, what = ["QUOTE_FIELDS_MISSING"], "import the combined quote (import_hardrock_quote)"
    elif state == S.CandidateState.EXPIRED:
        codes, what = ["GAME_STARTED"], "the earliest game has started; build a new ticket"
    elif state == S.CandidateState.REJECTED:
        blocking = [
            c
            for c in candidate.reason_codes
            if c in ("GAME_POSTPONED", "MARKET_SUSPENDED", "INJURY_OUT", "INJURY_DOUBTFUL")
        ]
        codes, what = (
            (blocking or ["NO_SUITABLE_TICKET"]),
            "the candidate was rejected on refresh; build a new ticket",
        )
    elif state == S.CandidateState.RESEARCH_CANDIDATE:
        codes, what = ["QUOTE_FIELDS_MISSING"], "import the combined quote first"
    else:
        codes, what = ["INVALID_INPUT"], "this candidate was already placed or settled"
    return ServiceError(
        f"candidate is {state.value}, not READY_FOR_USER_REVIEW: {what}", codes, detail=f"state={state.value}"
    )


def _default_select_key(
    ctx: RequestContext, candidate_id: str, now: datetime
) -> tuple[str, S.BudgetReservation | None]:
    """The idempotency key ``select_ticket`` uses when the caller passes none.

    A live (ACTIVE, unexpired) reservation of this candidate is replayed through its own key. Otherwise a key
    no earlier attempt used is minted (``select:<candidate_id>``, then ``select:<candidate_id>:2`` ...), so a
    released or expired reservation is never replayed as if it still held budget.
    """
    prefix = f"select:{candidate_id}"
    with ctx.db.engine.connect() as conn:
        rows = conn.execute(
            select(dbm.reservations).where(
                dbm.reservations.c.user_id == ctx.user_id, dbm.reservations.c.candidate_id == candidate_id
            )
        ).all()
    rows = [r for r in rows if r.idempotency_key == prefix or r.idempotency_key.startswith(prefix + ":")]
    for row in rows:
        expires = parse_iso(row.expires_at)
        if row.status == S.ReservationStatus.ACTIVE.value and (expires is None or expires > now):
            return row.idempotency_key, budget.reservation_from_row(row)
    taken = {r.idempotency_key for r in rows}
    if prefix not in taken:
        return prefix, None
    attempt = 2
    while f"{prefix}:{attempt}" in taken:
        attempt += 1
    return f"{prefix}:{attempt}", None


def select_ticket(
    ctx: RequestContext, candidate_id: str, stake_usd: Decimal, idempotency_key: str | None = None
) -> S.SelectResponse:
    """Reserve ``stake_usd`` of today's budget for a READY_FOR_USER_REVIEW candidate. Places nothing.

    Without an ``idempotency_key`` the call is idempotent against the candidate's live reservation (same
    stake replays it; a different stake is IDEMPOTENCY_CONFLICT until it is released) and reserves anew once
    that reservation was released or expired. A FIXTURE candidate never reserves real budget.
    """
    stake = _money(stake_usd)
    candidate = load_candidate(ctx, candidate_id)
    now = ctx.clock.now_utc()
    if candidate.state != S.CandidateState.READY_FOR_USER_REVIEW:
        raise _not_ready_error(candidate)
    # reservations is a ledger table: fixture data never reaches a real ledger (ARCHITECTURE section 0).
    _ledger(ctx.db.guard_ledger_mode, candidate.data_mode.value)
    if now >= candidate.expires_at_utc:
        transition(ctx, candidate, S.CandidateState.EXPIRED, "select_ticket: earliest game has started")
        raise ServiceError("candidate EXPIRED: the earliest game has started", ["GAME_STARTED"])
    age = int((now - candidate.inputs_snapshot_utc).total_seconds())
    if age > ctx.settings.max_odds_age_seconds:
        raise ServiceError(
            f"candidate inputs are {age}s old (limit {ctx.settings.max_odds_age_seconds}s): run refresh_parlay first",
            ["QUOTE_STALE"],
        )
    prefs = get_user_settings(ctx)
    date_local = _today(ctx)
    daily = _ledger(budget.get_daily_budget, ctx.db, ctx.user_id, date_local, now, prefs.daily_cap_usd, stake)
    live_reservation: S.BudgetReservation | None = None
    if idempotency_key:
        key = idempotency_key
    else:
        key, live_reservation = _default_select_key(ctx, candidate_id, now)
    if stake > daily.remaining_usd:
        # A replay of an earlier reservation is still allowed; anything else exceeds the budget.
        with ctx.db.engine.connect() as conn:
            existing = conn.execute(
                select(dbm.reservations.c.reservation_id).where(
                    dbm.reservations.c.user_id == ctx.user_id, dbm.reservations.c.idempotency_key == key
                )
            ).first()
        if existing is None:
            raise InvalidInput(
                f"stake {stake} exceeds the remaining budget {daily.remaining_usd} for {date_local}",
                ["BUDGET_EXCEEDED"],
                detail=f"cap {daily.cap_usd}, recorded {daily.recorded_stake_usd}, reserved {daily.reserved_stake_usd}",
            )
    expires_at = min(now + timedelta(seconds=ctx.settings.reservation_ttl_seconds), candidate.expires_at_utc)
    try:
        reservation, replay = _ledger(
            budget.reserve,
            ctx.db,
            ctx.user_id,
            date_local,
            candidate_id,
            stake,
            key,
            now,
            prefs.daily_cap_usd,
            expires_at,
        )
    except InvalidInput as exc:
        if live_reservation is None or "IDEMPOTENCY_CONFLICT" not in exc.reason_codes:
            raise
        raise InvalidInput(
            f"an ACTIVE reservation ({live_reservation.reservation_id}) already holds "
            f"{live_reservation.stake_usd} for this candidate: release it (release_reservation) before "
            f"reserving {stake}, or repeat the same stake to replay it",
            ["IDEMPOTENCY_CONFLICT"],
            detail=f"reservation_id={live_reservation.reservation_id}",
        ) from exc
    ranking = dict(candidate.ranking)
    ranking["reservation_id"] = reservation.reservation_id
    ranking["reservation_stake_usd"] = str(reservation.stake_usd)
    ranking["reservation_expires_at_utc"] = iso(reservation.expires_at_utc) or ""
    updated = quote_review.rebuild_candidate(candidate, ranking=ranking, updated_at_utc=now)
    save_candidate(
        ctx,
        updated,
        from_state=candidate.state,
        reason=f"select_ticket: budget reserved {stake} ({'replay' if replay else 'new reservation'})",
        extra={"reservation_id": reservation.reservation_id, "stake_usd": str(stake), "idempotency_key": key},
    )
    after = _ledger(budget.get_daily_budget, ctx.db, ctx.user_id, date_local, now, prefs.daily_cap_usd)
    after = after.model_copy(update={"proposed_stake_usd": stake})
    return _with_onboarding(
        ctx, S.SelectResponse(candidate=updated, reservation=reservation, budget=after, replay=replay)
    )


def release_reservation(ctx: RequestContext, reservation_id: str, reason: str) -> S.BudgetReservation:
    if not reason or not reason.strip():
        raise InvalidInput("a release reason is required")
    return _ledger(budget.release, ctx.db, ctx.user_id, reservation_id, reason.strip(), ctx.clock.now_utc())


def get_daily_budget(
    ctx: RequestContext, date_local: str | None = None, proposed_stake_usd: Decimal | None = None
) -> S.DailyBudget:
    date_local = _validate_date(date_local or _today(ctx))
    proposed = _money(proposed_stake_usd, "proposed_stake_usd") if proposed_stake_usd is not None else None
    prefs = get_user_settings(ctx)
    return _ledger(
        budget.get_daily_budget,
        ctx.db,
        ctx.user_id,
        date_local,
        ctx.clock.now_utc(),
        prefs.daily_cap_usd,
        proposed,
    )


def _candidate_snapshot(candidate: S.Candidate) -> tuple[dict[str, Any], Decimal]:
    recommended = (
        candidate.book_quote.combined_decimal
        if candidate.book_quote is not None and candidate.book_quote.confirmed_by_user
        else candidate.indicative_multiplied_decimal
    )
    snapshot = {
        "candidate_id": candidate.candidate_id,
        "p_joint": None if candidate.p_joint is None else str(candidate.p_joint),
        "p_joint_method": candidate.p_joint_method,
        "model_state": candidate.model_state.value,
        "parlay_type": candidate.parlay_type.value,
        "market_composition": "+".join(sorted(leg.quote.market_type.value for leg in candidate.ticket.legs)),
        "recommended_combined_decimal": str(recommended),
        "recommended_source": "BOOK_QUOTE"
        if candidate.book_quote is not None and candidate.book_quote.confirmed_by_user
        else "INDICATIVE_MULTIPLIED",
        "ev_per_dollar": None if candidate.ev_per_dollar is None else str(candidate.ev_per_dollar),
        "data_mode": candidate.data_mode.value,
        "inputs_snapshot_utc": iso(candidate.inputs_snapshot_utc),
        "legs": [leg.description for leg in candidate.ticket.legs],
    }
    return snapshot, recommended


def record_actual_bet(
    ctx: RequestContext, ticket: S.ConfirmedTicketInput | dict[str, Any], idempotency_key: str
) -> S.RecordResponse:
    """Record a wager the user confirms they placed. Append-only; replays by idempotency key."""
    confirmed = _coerce(S.ConfirmedTicketInput, ticket, "confirmed ticket")
    if not idempotency_key or not idempotency_key.strip():
        raise InvalidInput("idempotency_key is required")
    now = ctx.clock.now_utc()
    prefs = get_user_settings(ctx)
    candidate: S.Candidate | None = None
    snapshot: dict[str, Any] | None = None
    recommended: Decimal | None = None
    data_mode = S.DataMode.MANUAL_INPUT
    if confirmed.candidate_id:
        candidate = load_candidate(ctx, confirmed.candidate_id)
        snapshot, recommended = _candidate_snapshot(candidate)
        data_mode = candidate.data_mode
    bet, daily, replay = _ledger(
        actual_bets.record_bet,
        ctx.db,
        ctx.user_id,
        confirmed,
        idempotency_key.strip(),
        now,
        prefs.daily_cap_usd,
        DEFAULT_TZ,
        data_mode,
        snapshot,
        recommended,
    )
    if candidate is not None and not replay and candidate.state not in _TERMINAL_STATES:
        transition(
            ctx,
            candidate,
            S.CandidateState.USER_CONFIRMED_PLACED,
            f"record_actual_bet: bet {bet.bet_id} recorded",
            {"bet_id": bet.bet_id, "stake_usd": str(bet.stake_usd), "breach_flags": list(bet.breach_flags)},
        )
    return S.RecordResponse(bet=bet, budget=daily, replay=replay, breach_flags=list(bet.breach_flags))


def reconcile_settlement(
    ctx: RequestContext, bet_id: str, settlement_input: S.SettlementInput | dict[str, Any]
) -> S.SettlementResponse:
    """Append a settlement record; a final BOOK_CONFIRMED result moves the linked candidate to SETTLED."""
    s = _coerce(S.SettlementInput, settlement_input, "settlement")
    now = ctx.clock.now_utc()
    bet, record, replay, warnings = _ledger(settlement.reconcile, ctx.db, ctx.user_id, bet_id, s, now)
    if (
        not replay
        and record.source == S.SettlementSource.BOOK_CONFIRMED
        and bet.status in S.FINAL_BET_STATUSES
        and bet.candidate_id
    ):
        try:
            candidate = load_candidate(ctx, bet.candidate_id)
        except NotFound:
            candidate = None
        if candidate is not None and candidate.state != S.CandidateState.SETTLED:
            transition(
                ctx,
                candidate,
                S.CandidateState.SETTLED,
                f"reconcile_settlement: bet {bet.bet_id} {bet.status.value}",
                {"bet_id": bet.bet_id, "settlement_id": record.settlement_id, "status": bet.status.value},
            )
    response = S.SettlementResponse(bet=bet, settlement=record, replay=replay, warnings=list(warnings))
    return _with_onboarding(ctx, response)


# --------------------------------------------------------------------------------------
# Reports, costs, export
# --------------------------------------------------------------------------------------


def get_performance(ctx: RequestContext, start_date: str, end_date: str) -> S.PerformanceReport:
    _validate_date(start_date)
    _validate_date(end_date)
    report = _ledger(reports.performance, ctx.db, ctx.user_id, start_date, end_date, ctx.clock.now_utc())
    return _with_onboarding(ctx, report)


def generate_30_day_review(ctx: RequestContext) -> S.ReviewReport:
    prefs = get_user_settings(ctx)
    review = _ledger(
        reports.thirty_day_review,
        ctx.db,
        ctx.user_id,
        ctx.settings.review_window_start.isoformat(),
        ctx.settings.review_window_end.isoformat(),
        prefs.daily_cap_usd,
        ctx.clock.now_utc(),
    )
    return _with_onboarding(ctx, review)


def add_cost(ctx: RequestContext, cost: S.CostInput | dict[str, Any]) -> S.CostEntry:
    """Record a cost; a repeat with the same idempotency key returns the stored entry (replay)."""
    cost_input = _coerce(S.CostInput, cost, "cost")
    entry, _replay = _ledger(reports.add_cost, ctx.db, ctx.user_id, cost_input, ctx.clock.now_utc())
    return entry


def scrub_export_bundle(tables: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """Remove secret material from an exported bundle: the user's encrypted Odds API key never leaves the
    server (section 0). ``has_own_odds_api_key`` conveys presence instead."""
    out: dict[str, list[dict[str, Any]]] = {}
    for name, rows in tables.items():
        cleaned: list[dict[str, Any]] = []
        for row in rows:
            record = dict(row)
            if name == "user_settings" or "odds_api_key_encrypted" in record:
                record["has_own_odds_api_key"] = bool(record.get("odds_api_key_encrypted"))
                record["odds_api_key_encrypted"] = None
            cleaned.append(record)
        out[name] = cleaned
    return out


def export_my_data(ctx: RequestContext) -> S.ExportBundle:
    """Every record stored for the user (credentials and OAuth rows excluded by ``db.export_user``; the
    encrypted per-user odds key is blanked by ``scrub_export_bundle``)."""
    return S.ExportBundle(
        user_id_masked=mask_user_id(ctx.user_id),
        exported_at_utc=ctx.clock.now_utc(),
        tables=scrub_export_bundle(ctx.db.export_user(ctx.user_id)),
    )
