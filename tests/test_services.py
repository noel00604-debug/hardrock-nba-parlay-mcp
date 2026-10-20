"""services.py with a fake provider registry (LIVE-stamped fake, no network) and the packaged fixture slate."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from conftest import NOW, TEAMS, make_quote, stamp
from sqlalchemy import insert, select
from test_candidate_builder import injury, ref_quotes

from hardrock_nba_parlay import config, services
from hardrock_nba_parlay import db as dbm
from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.config import FixedClock, Settings, local_date
from hardrock_nba_parlay.db import iso, open_database
from hardrock_nba_parlay.errors import InvalidInput, NotFound, ServiceError
from hardrock_nba_parlay.providers.base import ProviderResult


@pytest.fixture(autouse=True)
def _no_real_secrets(monkeypatch):
    """Never let a real key from the keychain or a dotenv file reach these tests."""
    monkeypatch.setattr(config, "get_secret", lambda name: None)


# --------------------------------------------------------------------------------------
# Fake live provider
# --------------------------------------------------------------------------------------


class FakeOdds:
    """An ``OddsProvider`` + ``InjuryProvider`` stub with LIVE_PROVIDER stamps and credit accounting."""

    name = "fake-live"

    def __init__(
        self,
        events: list[S.Event],
        quotes: list[S.MarketQuote],
        injuries: list[S.InjuryContext] | None = None,
        *,
        mode: S.DataMode = S.DataMode.LIVE_PROVIDER,
        featured_cost: int = 3,
        props_cost: int = 4,
        db=None,
        user_id: str | None = None,
    ) -> None:
        self.events = events
        self.quotes = quotes
        self.injuries = injuries or []
        self.mode = mode
        self.featured_cost = featured_cost
        self.props_cost = props_cost
        self.calls: list[tuple[str, Any]] = []
        self.db = db
        self.user_id = user_id
        self.cleared = 0

    def _result(self, data: Any, credits: int, source_ts: datetime | None = None) -> ProviderResult[Any]:
        if credits and self.db is not None:
            with self.db.tx() as conn:
                conn.execute(
                    insert(dbm.provider_usage).values(
                        user_id=self.user_id,
                        provider="the-odds-api",
                        endpoint="fake",
                        credits_cost=credits,
                        requests_remaining=400,
                        requests_used=100,
                        created_at=iso(NOW),
                    )
                )
        return ProviderResult(
            data=data,
            stamp=stamp(source=self.name, mode=self.mode, source_ts=source_ts),
            credits_cost=credits,
            quota={"requests_remaining": 400, "requests_used": 100, "requests_last": credits},
        )

    def list_events(self, date_local: str) -> ProviderResult[list[S.Event]]:
        self.calls.append(("events", date_local))
        return self._result([e for e in self.events if local_date(e.commence_time_utc) == date_local], 0)

    def fetch_featured_odds(self, date_local, books, markets) -> ProviderResult[list[S.MarketQuote]]:
        self.calls.append(("featured", (date_local, tuple(books), tuple(markets))))
        ids = {e.event_id for e in self.list_events(date_local).data}
        data = [
            q
            for q in self.quotes
            if q.event_id in ids and q.book in books and q.market_type in markets and not q.is_alternate
        ]
        return self._result(data, self.featured_cost if data else 0)

    def fetch_event_props(
        self, event_id, books, markets, include_alternates
    ) -> ProviderResult[list[S.MarketQuote]]:
        self.calls.append(("props", (event_id, tuple(books), include_alternates)))
        data = [
            q
            for q in self.quotes
            if q.event_id == event_id
            and q.book in books
            and q.market_type in markets
            and (include_alternates or not q.is_alternate)
        ]
        return self._result(data, self.props_cost if data else 0)

    def list_event_markets(self, event_id, books) -> ProviderResult[dict[str, list[str]]]:
        self.calls.append(("markets", event_id))
        out: dict[str, list[str]] = {}
        for q in self.quotes:
            if q.event_id == event_id and q.book in books:
                out.setdefault(q.book, []).append(q.market_type.value.lower())
        return self._result(out, 1)

    def fetch_scores(self, days_from=1) -> ProviderResult[list[S.GameResult]]:
        return self._result([], 2)

    def probe(self, spend_credits: bool = False) -> S.ProviderProbe:
        return S.ProviderProbe(
            provider=self.name, auth_ok=True, nba_active=True, target_book_present=True, checked_at_utc=NOW
        )

    def fetch_latest_report(self, now, slate) -> ProviderResult[list[S.InjuryContext]]:
        self.calls.append(("injuries", len(slate)))
        ts = max((i.report_timestamp_utc for i in self.injuries if i.report_timestamp_utc), default=None)
        return self._result(list(self.injuries), 0, ts)

    def clear_cache(self) -> None:
        self.cleared += 1


def live_quotes(events: list[S.Event], *, source_ts=None) -> list[S.MarketQuote]:
    quotes: list[S.MarketQuote] = []
    for i, e in enumerate(events):
        home = next(t for t in TEAMS.values() if t.team_id == e.home_team.team_id)
        away = next(t for t in TEAMS.values() if t.team_id == e.away_team.team_id)
        line, total = str(Decimal("3.5") + i), str(Decimal("220.5") + i)
        quotes += [
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
        quotes += ref_quotes(e, S.MarketType.MONEYLINE, "2.78", "1.49", source_ts=source_ts)
        quotes += ref_quotes(e, S.MarketType.SPREAD, "1.93", "1.89", line=line, source_ts=source_ts)
        quotes += ref_quotes(e, S.MarketType.TOTAL, "1.92", "1.90", line=total, source_ts=source_ts)
    # one prop at the target book with a pinnacle benchmark, on PHI@NYK
    e2 = events[1]
    quotes += [
        make_quote(
            e2,
            S.MarketType.PLAYER_POINTS,
            S.Side.OVER,
            "1.87",
            line="24.5",
            player="Jalen Brunson",
            source_ts=source_ts,
        ),
        make_quote(
            e2,
            S.MarketType.PLAYER_POINTS,
            S.Side.UNDER,
            "1.95",
            line="24.5",
            player="Jalen Brunson",
            source_ts=source_ts,
        ),
    ]
    quotes += ref_quotes(
        e2,
        S.MarketType.PLAYER_POINTS,
        "1.90",
        "1.92",
        line="24.5",
        player="Jalen Brunson",
        source_ts=source_ts,
    )
    return [
        q.model_copy(update={"stamp": q.stamp.model_copy(update={"data_mode": S.DataMode.LIVE_PROVIDER})})
        for q in quotes
    ]


def live_events(events: list[S.Event]) -> list[S.Event]:
    return [
        e.model_copy(update={"stamp": e.stamp.model_copy(update={"data_mode": S.DataMode.LIVE_PROVIDER})})
        for e in events
    ]


def registry_for(fake: FakeOdds) -> services.ProviderRegistry:
    return services.ProviderRegistry(
        odds=fake,
        injury=fake,
        fixture=None,
        data_mode=S.DataMode.LIVE_PROVIDER,
        key_configured=True,
        key_source="server",
    )


@pytest.fixture
def live(three_game_slate, db):
    events = live_events(three_game_slate)
    fake = FakeOdds(
        events,
        live_quotes(events),
        [injury(events[0], "Taurean Prince", S.InjuryDesignation.QUESTIONABLE, "DET")],
        db=db,
        user_id="local-owner",
    )
    return fake


@pytest.fixture
def ctx(settings, db, clock, live) -> services.RequestContext:
    return services.RequestContext(
        user_id="local-owner", clock=clock, db=db, settings=settings, providers=registry_for(live)
    )


def ctx_for(user_id: str, base: services.RequestContext) -> services.RequestContext:
    return services.RequestContext(
        user_id=user_id, clock=base.clock, db=base.db, settings=base.settings, providers=base.providers
    )


# --------------------------------------------------------------------------------------
# Providers and keys
# --------------------------------------------------------------------------------------


def test_build_providers_fixture_mode(settings, db, clock):
    fx = settings.model_copy(update={"data_mode": "fixture"})
    ctx = services.RequestContext(user_id="u", clock=clock, db=db, settings=fx)
    reg = services.build_providers(ctx)
    assert reg.data_mode == S.DataMode.FIXTURE and isinstance(reg.odds, services.FixtureOddsProvider)
    assert reg.injury is reg.odds and reg.key_configured is False
    same = services.build_providers(fx, db, clock, "u")
    assert same.data_mode == S.DataMode.FIXTURE


def test_live_mode_without_key_raises_no_provider_key_only_when_needed(settings, db, clock):
    ctx = services.RequestContext(user_id="u", clock=clock, db=db, settings=settings)
    reg = services.build_providers(ctx)
    assert reg.odds is None and reg.data_mode == S.DataMode.LIVE_PROVIDER and reg.key_configured is False
    ctx.providers = reg
    status = services.get_system_status(ctx)
    assert status.provider_configured is False and S.DataMode.FIXTURE not in status.data_modes_available
    assert status.data_modes_available == [S.DataMode.MANUAL_INPUT]
    assert any(w.startswith("NO_PROVIDER_KEY") for w in status.warnings)
    with pytest.raises(ServiceError) as exc:
        services.get_nba_slate(ctx, "2026-10-20")
    assert exc.value.reason_codes == ["NO_PROVIDER_KEY"] and "HRNBA_ODDS_API_KEY" in (exc.value.detail or "")
    with pytest.raises(ServiceError) as exc2:
        services.build_three_leg_parlays(ctx, "2026-10-20")
    assert exc2.value.reason_codes == ["NO_PROVIDER_KEY"]


def test_server_key_builds_live_provider(settings, db, clock):
    keyed = settings.model_copy(update={"odds_api_key": config.SecretStr("server-key-123")})
    ctx = services.RequestContext(user_id="u", clock=clock, db=db, settings=keyed)
    reg = services.build_providers(ctx)
    assert reg.key_configured and reg.key_source == "server" and reg.odds is not None
    assert reg.odds.name == "the-odds-api" and reg.odds.user_id == "u"
    assert services.build_providers(ctx).odds is reg.odds  # cached per (db, user, key, clock)


def test_per_user_key_requires_secret_and_wins_over_server_key(settings, db, clock):
    ctx = services.RequestContext(user_id="hosted-user", clock=clock, db=db, settings=settings)
    with pytest.raises(InvalidInput) as exc:
        services.set_user_settings(ctx, odds_api_key="user-key-456")
    assert "HRNBA_SECRET_KEY" in exc.value.message
    hosted = settings.model_copy(
        update={
            "auth_mode": "builtin_oauth",
            "secret_key": config.SecretStr("s3cret"),
            "odds_api_key": config.SecretStr("server-key"),
        }
    )
    ctx = services.RequestContext(user_id="hosted-user", clock=clock, db=db, settings=hosted)
    prefs = services.set_user_settings(ctx, odds_api_key="user-key-456")
    assert prefs.has_own_odds_api_key is True
    with db.engine.connect() as conn:
        stored = conn.execute(
            select(dbm.user_settings.c.odds_api_key_encrypted).where(
                dbm.user_settings.c.user_id == "hosted-user"
            )
        ).scalar_one()
    assert stored and "user-key-456" not in stored
    reg = services.build_providers(ctx)
    assert reg.key_source == "user" and reg.odds._api_key == "user-key-456"
    # wrong secret: fall back to the server key with a warning, never crash
    other = hosted.model_copy(update={"secret_key": config.SecretStr("different")})
    reg2 = services.build_providers(
        services.RequestContext(user_id="hosted-user", clock=clock, db=db, settings=other)
    )
    assert reg2.key_source == "server" and any("cannot be decrypted" in w for w in reg2.warnings)
    cleared = services.set_user_settings(ctx, odds_api_key="")
    assert cleared.has_own_odds_api_key is False


# --------------------------------------------------------------------------------------
# User settings and onboarding
# --------------------------------------------------------------------------------------


def test_user_settings_defaults_and_validation(ctx):
    prefs = services.get_user_settings(ctx)
    assert prefs.daily_cap_usd == Decimal("10.00") and prefs.onboarding_complete is False
    assert prefs.display_tz == "America/New_York" and prefs.has_own_odds_api_key is False
    with pytest.raises(InvalidInput):
        services.set_user_settings(ctx, daily_cap_usd=Decimal("0"))
    with pytest.raises(InvalidInput):
        services.set_user_settings(ctx, display_tz="Mars/Olympus")
    updated = services.set_user_settings(
        ctx, daily_cap_usd=Decimal("7.5"), display_tz="America/Chicago", confirm_onboarding=True
    )
    assert updated.daily_cap_usd == Decimal("7.50") and updated.display_tz == "America/Chicago"
    assert updated.onboarding_complete is True
    status = services.get_system_status(ctx)
    assert status.daily_cap_usd == Decimal("7.50") and status.now_display.endswith("-05:00")


def test_needs_onboarding_warning_until_confirmed(ctx):
    slate = services.get_nba_slate(ctx, "2026-10-20")
    assert "NEEDS_ONBOARDING" in slate.warnings
    coverage = services.check_data_coverage(ctx, "2026-10-20")
    assert any(n.startswith("NEEDS_ONBOARDING") for n in coverage.notes)
    assert "NEEDS_ONBOARDING" not in services.get_system_status(ctx).warnings
    services.set_user_settings(ctx, confirm_onboarding=True)
    assert "NEEDS_ONBOARDING" not in services.get_nba_slate(ctx, "2026-10-20").warnings


# --------------------------------------------------------------------------------------
# Status, coverage, slate, injuries, single leg
# --------------------------------------------------------------------------------------


def test_system_status_reports_provider_usage(ctx, live):
    assert services.get_system_status(ctx).provider_last_ok_utc is None
    services.get_nba_slate(ctx, "2026-10-20")
    services.build_three_leg_parlays(ctx, "2026-10-20", include_props=False)
    status = services.get_system_status(ctx)
    assert status.provider_last_ok_utc == NOW and status.provider_quota["requests_remaining"] == 400
    assert status.database_ok and status.database_kind == "sqlite" and status.auth_mode == "none"
    assert status.ai_disclosure == S.AI_DISCLOSURE and status.user_id_masked != "local-owner"


def test_coverage_report_shape(ctx, live):
    report = services.check_data_coverage(ctx, "2026-10-20", probe_props=True)
    assert report.data_mode == S.DataMode.LIVE_PROVIDER
    assert set(report.hard_rock_single_leg) == {m.value for m in S.MarketType}
    assert report.hard_rock_single_leg["MONEYLINE"].status == S.CoverageStatus.PASS
    assert report.hard_rock_single_leg["PLAYER_POINTS"].status == S.CoverageStatus.PARTIAL
    assert report.hard_rock_single_leg["TEAM_TOTAL"].status == S.CoverageStatus.BLOCKED
    assert report.reference_markets["SPREAD"].status == S.CoverageStatus.PASS
    assert report.injury_information.status == S.CoverageStatus.PASS
    assert report.three_leg_combinability.status == S.CoverageStatus.UNKNOWN
    assert report.three_leg_combinability.reason_codes == ["COMBINATION_UNVERIFIED"]
    assert report.combined_payout_verification.status == S.CoverageStatus.BLOCKED
    assert report.stats_and_settlement_rules.status == S.CoverageStatus.PARTIAL
    assert report.provider_quota["requests_remaining"] == 400
    assert any("skew" in n and "within" in n for n in report.notes)
    assert sum(1 for c in live.calls if c[0] == "markets") == 3
    unprobed = services.check_data_coverage(ctx, "2026-10-20")
    assert unprobed.hard_rock_single_leg["PLAYER_POINTS"].status == S.CoverageStatus.UNKNOWN


def test_coverage_measures_skew_above_limit(ctx, live, three_game_slate):
    events = live_events(three_game_slate)
    live.quotes = [
        q
        if q.book == "hardrockbet_fl"
        else q.model_copy(
            update={
                "stamp": q.stamp.model_copy(update={"source_timestamp_utc": NOW - timedelta(seconds=150)})
            }
        )
        for q in live.quotes
    ]
    live.events = events
    report = services.check_data_coverage(ctx, "2026-10-20")
    assert any("above max_reference_skew_seconds" in n for n in report.notes)
    build = services.build_three_leg_parlays(ctx, "2026-10-20", include_props=False)
    assert build.candidates and all(c.p_joint is None for c in build.candidates)
    assert all("TIMESTAMP_SKEW" in c.reason_codes for c in build.candidates)


def test_slate_and_injury_context(ctx, live, three_game_slate):
    slate = services.get_nba_slate(ctx, "2026-10-20")
    assert [e.event_id for e in slate.events] == [e.event_id for e in three_game_slate]
    assert slate.data_mode == S.DataMode.LIVE_PROVIDER and slate.events[0].commence_time_display.endswith(
        "-04:00"
    )
    with ctx.db.engine.connect() as conn:
        assert (
            conn.execute(select(dbm.events_cache)).rowcount != 0
            or len(conn.execute(select(dbm.events_cache)).all()) == 3
        )
    injuries = services.get_injury_context(ctx, three_game_slate[0].event_id)
    assert [e.player_name_raw for e in injuries.entries] == ["Taurean Prince"]
    assert injuries.report_timestamp_utc == NOW - timedelta(hours=1)
    empty = services.get_injury_context(ctx, three_game_slate[2].event_id)
    assert empty.entries == [] and "INJURY_REPORT_MISSING" in empty.reason_codes
    with pytest.raises(NotFound):
        services.get_injury_context(ctx, "oddsapi:nope")
    assert services.get_nba_slate(ctx, "2026-10-22").events == []


def test_analyze_leg_finds_featured_and_props(ctx, live):
    target = [q for q in live.quotes if q.book == "hardrockbet_fl"]
    featured = next(q for q in target if q.market_type == S.MarketType.SPREAD)
    prop = next(q for q in target if q.market_type == S.MarketType.PLAYER_POINTS)
    a = services.analyze_leg(ctx, S.compute_selection_id(featured))
    assert a.probability.state == S.ModelState.MARKET_BASELINE and "NEEDS_ONBOARDING" in a.reason_codes
    b = services.analyze_leg(ctx, S.compute_selection_id(prop), "2026-10-20")
    assert b.selection_id == S.compute_selection_id(prop) and b.probability.value is not None
    with pytest.raises(NotFound):
        services.analyze_leg(ctx, "sel_nope")
    with pytest.raises(InvalidInput):
        services.analyze_leg(ctx, "sel_x", "20261020")


# --------------------------------------------------------------------------------------
# Build and no-ticket reasons
# --------------------------------------------------------------------------------------


def test_build_persists_snapshots_and_candidates(ctx, live):
    build = services.build_three_leg_parlays(ctx, "2026-10-20")
    assert len(build.candidates) == 3 and build.primary_candidate_id == build.candidates[0].candidate_id
    assert build.data_mode == S.DataMode.LIVE_PROVIDER and build.credits_used == 3 + 4
    assert build.legs_considered == 20 and build.combinations_evaluated > 0
    assert build.coverage_summary["events"] == "3" and build.ai_disclosure == S.AI_DISCLOSURE
    assert "NEEDS_ONBOARDING" in build.warnings
    with ctx.db.engine.connect() as conn:
        assert len(conn.execute(select(dbm.odds_snapshots)).all()) == len(live.quotes)
        assert len(conn.execute(select(dbm.injury_snapshots)).all()) == 1
        rows = conn.execute(select(dbm.candidates)).all()
    assert {r.state for r in rows} == {"NEEDS_BOOK_QUOTE"} and {r.user_id for r in rows} == {"local-owner"}
    for cand in build.candidates:
        history = services.list_candidate_history(ctx, cand.candidate_id)
        assert [(h["from_state"], h["to_state"]) for h in history] == [
            ("RESEARCH_CANDIDATE", "NEEDS_BOOK_QUOTE")
        ]
        loaded = services.load_candidate(ctx, cand.candidate_id)
        assert loaded.candidate_id == cand.candidate_id and "NEEDS_ONBOARDING" not in loaded.reason_codes


def test_no_suitable_ticket_when_every_leg_is_stale(ctx, live, three_game_slate):
    events = live_events(three_game_slate)
    live.quotes = live_quotes(events, source_ts=NOW - timedelta(seconds=900))
    build = services.build_three_leg_parlays(ctx, "2026-10-20")
    assert build.candidates == [] and build.primary_candidate_id is None
    assert build.no_ticket_reason is not None and build.no_ticket_reason.startswith("NO SUITABLE TICKET")
    assert {"NO_SUITABLE_TICKET", "QUOTE_STALE"} <= set(build.reason_codes)


def test_no_suitable_ticket_when_slate_is_empty(ctx):
    build = services.build_three_leg_parlays(ctx, "2026-10-22")
    assert build.candidates == [] and "no NBA games" in (build.no_ticket_reason or "")
    assert "NO_SUITABLE_TICKET" in build.reason_codes and build.credits_used == 0


def test_build_rejects_bad_arguments(ctx):
    with pytest.raises(InvalidInput):
        services.build_three_leg_parlays(ctx, "2026-10-20", parlay_type="teaser")
    with pytest.raises(InvalidInput):
        services.build_three_leg_parlays(ctx, "2026-10-20", max_candidates=0)
    with pytest.raises(InvalidInput):
        services.build_three_leg_parlays(ctx, "yesterday")


def test_hosted_credit_quota_guard(settings, db, clock, three_game_slate):
    hosted = settings.model_copy(
        update={
            "auth_mode": "builtin_oauth",
            "secret_key": config.SecretStr("s"),
            "per_user_daily_credit_quota": 5,
        }
    )
    events = live_events(three_game_slate)
    fake = FakeOdds(events, live_quotes(events), db=db, user_id="hosted-a")
    ctx_a = services.RequestContext(
        user_id="hosted-a", clock=clock, db=db, settings=hosted, providers=registry_for(fake)
    )
    first = services.build_three_leg_parlays(ctx_a, "2026-10-20", include_props=False)
    assert first.credits_used == 3
    fake.user_id = "hosted-a"
    with pytest.raises(ServiceError) as exc:
        services.build_three_leg_parlays(ctx_a, "2026-10-20")  # 3 already used; props would push past 5
    assert "PROVIDER_CREDIT_GUARD" in exc.value.reason_codes
    # another user on the same server key is not affected by user A's usage
    fake.user_id = "hosted-b"
    ctx_b = services.RequestContext(
        user_id="hosted-b", clock=clock, db=db, settings=hosted, providers=registry_for(fake)
    )
    assert services.check_data_coverage(ctx_b, "2026-10-20").data_mode == S.DataMode.LIVE_PROVIDER


# --------------------------------------------------------------------------------------
# analyze_my_parlay, quotes, refresh
# --------------------------------------------------------------------------------------


def manual_inputs() -> list[dict[str, Any]]:
    return [
        {"game": "BOS@DET", "market": "SPREAD", "side": "HOME", "line": "3.5", "odds_american": -110},
        {"game": "PHI@NYK", "market": "TOTAL", "side": "OVER", "line": "221.5", "odds_american": -110},
        {"game": "OKC@SAS", "market": "MONEYLINE", "side": "AWAY", "odds_american": -150},
    ]


def test_analyze_my_parlay_from_dicts(ctx):
    cand = services.analyze_my_parlay(ctx, manual_inputs(), None, "2026-10-20")
    assert cand.data_mode == S.DataMode.MANUAL_INPUT and cand.parlay_type == S.ParlayType.MULTI_GAME
    assert cand.p_joint is not None  # pinnacle references at the same lines
    assert services.load_candidate(ctx, cand.candidate_id).state == S.CandidateState.NEEDS_BOOK_QUOTE
    with pytest.raises(InvalidInput) as exc:
        services.analyze_my_parlay(ctx, manual_inputs()[:2], None, "2026-10-20")
    assert exc.value.reason_codes == ["NOT_THREE_LEGS"]
    with pytest.raises(InvalidInput) as bad:
        services.analyze_my_parlay(ctx, [{"game": "BOS@DET", "market": "SPREAD"}] * 3, None, "2026-10-20")
    assert bad.value.reason_codes == ["INVALID_INPUT"]


def test_analyze_my_parlay_prop_fetch_and_same_game(ctx, live):
    inputs = [
        {
            "game": "PHI@NYK",
            "market": "PLAYER_POINTS",
            "side": "OVER",
            "line": "24.5",
            "player_name": "Jalen Brunson",
            "odds_american": -115,
        },
        {"game": "PHI@NYK", "market": "TOTAL", "side": "OVER", "line": "221.5", "odds_american": -110},
        {"game": "PHI@NYK", "market": "SPREAD", "side": "HOME", "line": "-4.5", "odds_american": -110},
    ]
    cand = services.analyze_my_parlay(
        ctx, inputs, {"combined_decimal": "6.5", "user_confirmed": True}, "2026-10-20"
    )
    assert cand.parlay_type == S.ParlayType.SAME_GAME and cand.p_joint is None and cand.ev_per_dollar is None
    assert cand.leg_analyses[0].probability.value is not None  # prop benchmark fetched for that event only
    assert sum(1 for c in live.calls if c[0] == "props") == 1
    assert cand.book_quote is not None and cand.state == S.CandidateState.READY_FOR_USER_REVIEW
    with ctx.db.engine.connect() as conn:
        assert len(conn.execute(select(dbm.book_quotes)).all()) == 1


def test_import_quote_persists_and_transitions(ctx):
    build = services.build_three_leg_parlays(ctx, "2026-10-20", include_props=False)
    cid = build.primary_candidate_id
    assert cid is not None
    with pytest.raises(NotFound):
        services.import_hardrock_quote(ctx, "cand_missing", {"combined_decimal": "7"})
    with pytest.raises(InvalidInput) as exc:
        services.import_hardrock_quote(ctx, cid, {"user_confirmed": True})
    assert exc.value.reason_codes == ["QUOTE_FIELDS_MISSING"]
    unconfirmed = services.import_hardrock_quote(ctx, cid, {"combined_decimal": "7.0"})
    assert (
        unconfirmed.state == S.CandidateState.NEEDS_BOOK_QUOTE
        and "QUOTE_UNCONFIRMED" in unconfirmed.reason_codes
    )
    confirmed = services.import_hardrock_quote(ctx, cid, {"combined_decimal": "7.0", "user_confirmed": True})
    assert confirmed.state == S.CandidateState.READY_FOR_USER_REVIEW
    history = services.list_candidate_history(ctx, cid)
    assert (
        history[-1]["to_state"] == "READY_FOR_USER_REVIEW"
        and "QUOTE_REPLACES_INDICATIVE" in history[-1]["reason"]
    )
    with ctx.db.engine.connect() as conn:
        assert len(conn.execute(select(dbm.book_quotes)).all()) == 2
    assert services.check_parlay_correlation(ctx, cid).joint_numeric_allowed is True


def test_refresh_keeps_ready_then_rejects_when_market_gone(ctx, live):
    build = services.build_three_leg_parlays(ctx, "2026-10-20", include_props=False)
    cid = build.primary_candidate_id
    services.import_hardrock_quote(ctx, cid, {"combined_decimal": "7.0", "user_confirmed": True})
    ctx.clock.advance(100)
    refreshed = services.refresh_parlay(ctx, cid)
    assert (
        refreshed.state == S.CandidateState.READY_FOR_USER_REVIEW
        and refreshed.inputs_snapshot_utc == ctx.clock.now_utc()
    )
    assert live.cleared >= 1
    gone_leg = refreshed.ticket.legs[0]
    live.quotes = [q for q in live.quotes if S.compute_selection_id(q) != gone_leg.selection_id]
    rejected = services.refresh_parlay(ctx, cid)
    assert rejected.state == S.CandidateState.REJECTED and "MARKET_SUSPENDED" in rejected.reason_codes
    history = services.list_candidate_history(ctx, cid)
    assert history[-1]["from_state"] == "READY_FOR_USER_REVIEW" and history[-1]["to_state"] == "REJECTED"
    with pytest.raises(ServiceError) as exc:
        services.select_ticket(ctx, cid, Decimal("5"))
    assert "MARKET_SUSPENDED" in exc.value.reason_codes


def test_refresh_keeps_manual_legs_the_feed_never_carried(ctx):
    inputs = manual_inputs()
    inputs[1] = {
        "game": "PHI@NYK",
        "market": "PLAYER_REBOUNDS",
        "side": "OVER",
        "line": "9.5",
        "player_name": "Karl-Anthony Towns",
        "odds_american": -110,
    }
    inputs[2] = {
        "game": "OKC@SAS",
        "market": "MONEYLINE",
        "side": "AWAY",
        "odds_decimal": "1.48",
    }  # same as the feed
    cand = services.analyze_my_parlay(
        ctx, inputs, {"combined_decimal": "6.0", "user_confirmed": True}, "2026-10-20"
    )
    assert cand.state == S.CandidateState.READY_FOR_USER_REVIEW
    refreshed = services.refresh_parlay(ctx, cand.candidate_id)
    assert refreshed.state == S.CandidateState.READY_FOR_USER_REVIEW
    assert refreshed.ticket.legs[1].quote.player_name_raw == "Karl-Anthony Towns"


# --------------------------------------------------------------------------------------
# select_ticket, budget, ledger mapping
# --------------------------------------------------------------------------------------


def ready_candidate(ctx) -> str:
    build = services.build_three_leg_parlays(ctx, "2026-10-20", include_props=False)
    cid = build.primary_candidate_id
    services.import_hardrock_quote(ctx, cid, {"combined_decimal": "7.0", "user_confirmed": True})
    return cid


def test_select_ticket_refusals(ctx):
    build = services.build_three_leg_parlays(ctx, "2026-10-20", include_props=False)
    cid = build.candidates[1].candidate_id
    with pytest.raises(ServiceError) as exc:
        services.select_ticket(ctx, cid, Decimal("5"))
    assert exc.value.reason_codes == ["QUOTE_FIELDS_MISSING"] and "NEEDS_BOOK_QUOTE" in exc.value.message
    services.import_hardrock_quote(
        ctx,
        cid,
        {"combined_decimal": "7.0", "legs_as_shown": ["Lakers", "Suns", "Jazz"], "user_confirmed": True},
    )
    with pytest.raises(ServiceError) as conflict:
        services.select_ticket(ctx, cid, Decimal("5"))
    assert conflict.value.reason_codes == ["QUOTE_CONFLICTS_WITH_LEGS"]
    ready = ready_candidate(ctx)
    ctx.clock.advance(ctx.settings.max_odds_age_seconds + 1)
    with pytest.raises(ServiceError) as stale:
        services.select_ticket(ctx, ready, Decimal("5"))
    assert stale.value.reason_codes == ["QUOTE_STALE"] and "refresh_parlay" in stale.value.message
    with pytest.raises(InvalidInput):
        services.select_ticket(ctx, ready, Decimal("0"))
    with pytest.raises(NotFound):
        services.select_ticket(ctx, "cand_nope", Decimal("5"))


def test_select_ticket_reserves_and_replays(ctx):
    cid = ready_candidate(ctx)
    with pytest.raises(InvalidInput) as too_much:
        services.select_ticket(ctx, cid, Decimal("10.01"))
    assert too_much.value.reason_codes == ["BUDGET_EXCEEDED"]
    out = services.select_ticket(ctx, cid, Decimal("6"), "key-1")
    assert out.replay is False and out.reservation.status == S.ReservationStatus.ACTIVE
    assert out.budget.reserved_stake_usd == Decimal("6.00") and out.budget.remaining_usd == Decimal("4.00")
    assert out.budget.proposed_stake_usd == Decimal("6.00") and out.budget.recorded_stake_usd == Decimal(
        "0.00"
    )
    assert out.candidate.state == S.CandidateState.READY_FOR_USER_REVIEW
    assert out.candidate.ranking["reservation_id"] == out.reservation.reservation_id
    earliest = min(leg.event.commence_time_utc for leg in out.candidate.ticket.legs)
    assert out.reservation.expires_at_utc == min(
        NOW + timedelta(seconds=ctx.settings.reservation_ttl_seconds), earliest
    )
    again = services.select_ticket(ctx, cid, Decimal("6"), "key-1")
    assert again.replay is True and again.reservation.reservation_id == out.reservation.reservation_id
    with pytest.raises(InvalidInput) as conflict:
        services.select_ticket(ctx, cid, Decimal("5"), "key-1")
    assert conflict.value.reason_codes == ["IDEMPOTENCY_CONFLICT"]
    with pytest.raises(InvalidInput) as exceeded:
        services.select_ticket(ctx, cid, Decimal("5"), "key-2")
    assert exceeded.value.reason_codes == ["BUDGET_EXCEEDED"]
    released = services.release_reservation(ctx, out.reservation.reservation_id, "changed my mind")
    assert released.status == S.ReservationStatus.RELEASED
    with pytest.raises(InvalidInput) as not_active:
        services.release_reservation(ctx, out.reservation.reservation_id, "again")
    assert not_active.value.reason_codes == ["RESERVATION_NOT_ACTIVE"]
    assert services.get_daily_budget(ctx).remaining_usd == Decimal("10.00")
    assert services.get_daily_budget(ctx, None, Decimal("11")).breaches == ["BUDGET_EXCEEDED"]


def test_record_bet_links_candidate_and_maps_ledger_errors(ctx):
    cid = ready_candidate(ctx)
    cand = services.load_candidate(ctx, cid)
    services.select_ticket(ctx, cid, Decimal("6"))
    ticket = {
        "candidate_id": cid,
        "legs": [
            {
                "description": leg.description,
                "event_id": leg.event.event_id,
                "market_type": leg.quote.market_type.value,
            }
            for leg in cand.ticket.legs
        ],
        "accepted_combined_decimal": "6.9",
        "stake_usd": "6",
    }
    rec = services.record_actual_bet(ctx, ticket, "bet-1")
    assert rec.replay is False and rec.bet.candidate_id == cid and rec.bet.reservation_id is not None
    assert rec.bet.recommended_combined_decimal == Decimal("7.0000")
    assert rec.budget.recorded_stake_usd == Decimal("6.00") and rec.budget.reserved_stake_usd == Decimal(
        "0.00"
    )
    assert services.load_candidate(ctx, cid).state == S.CandidateState.USER_CONFIRMED_PLACED
    assert services.record_actual_bet(ctx, ticket, "bet-1").replay is True
    with pytest.raises(InvalidInput) as conflict:
        services.record_actual_bet(ctx, {**ticket, "stake_usd": "5"}, "bet-1")
    assert conflict.value.reason_codes == ["IDEMPOTENCY_CONFLICT"]
    with pytest.raises(InvalidInput):
        services.record_actual_bet(ctx, ticket, "")
    with pytest.raises(InvalidInput) as refused:
        services.import_hardrock_quote(ctx, cid, {"combined_decimal": "7.5", "user_confirmed": True})
    assert "USER_CONFIRMED_PLACED" in refused.value.message
    with pytest.raises(InvalidInput):
        services.refresh_parlay(ctx, cid)


def test_reconcile_settles_candidate_and_reports(ctx):
    cid = ready_candidate(ctx)
    cand = services.load_candidate(ctx, cid)
    ticket = {
        "candidate_id": cid,
        "legs": [
            {
                "description": leg.description,
                "event_id": leg.event.event_id,
                "market_type": leg.quote.market_type.value,
            }
            for leg in cand.ticket.legs
        ],
        "accepted_combined_decimal": "7",
        "stake_usd": "5",
    }
    bet = services.record_actual_bet(ctx, ticket, "bet-1").bet
    out = services.reconcile_settlement(ctx, bet.bet_id, {"status": "LOST"})
    assert out.bet.status == S.BetStatus.LOST and out.settlement.cash_returned_usd == Decimal("0.00")
    assert services.load_candidate(ctx, cid).state == S.CandidateState.SETTLED
    again = services.reconcile_settlement(ctx, bet.bet_id, {"status": "LOST"})
    assert again.replay is True and "IDEMPOTENT_REPLAY" in again.warnings
    with pytest.raises(NotFound):
        services.reconcile_settlement(ctx, "bet_nope", {"status": "WON"})
    perf = services.get_performance(ctx, "2026-10-20", "2026-10-20")
    assert perf.tickets_placed == 1 and perf.net_profit_usd == Decimal("-5.00")
    review = services.generate_30_day_review(ctx)
    assert review.window_start == "2026-10-20" and review.performance.tickets_placed == 1
    with pytest.raises(InvalidInput):
        services.get_performance(ctx, "2026-10-21", "2026-10-20")


def test_add_cost_and_export(ctx):
    entry = services.add_cost(
        ctx,
        {"date_local": "2026-10-20", "description": "odds api", "amount_usd": "4.5", "idempotency_key": "c1"},
    )
    assert entry.amount_usd == Decimal("4.50") and entry.category == "DATA"
    assert (
        services.add_cost(
            ctx,
            {
                "date_local": "2026-10-20",
                "description": "odds api",
                "amount_usd": "4.50",
                "idempotency_key": "c1",
            },
        ).cost_id
        == entry.cost_id
    )
    with pytest.raises(InvalidInput):
        services.add_cost(
            ctx,
            {"date_local": "2026-10-20", "description": "other", "amount_usd": "1", "idempotency_key": "c1"},
        )
    bundle = services.export_my_data(ctx)
    assert isinstance(bundle, S.ExportBundle) and bundle.user_id_masked != "local-owner"
    assert len(bundle.tables["costs"]) == 1 and "credentials" not in bundle.tables
    assert bundle.model_dump(mode="json")["tables"]["costs"][0]["amount_cents"] == 450


def test_tenant_isolation(ctx):
    cid = ready_candidate(ctx)
    rsv = services.select_ticket(ctx, cid, Decimal("4")).reservation
    cand = services.load_candidate(ctx, cid)
    legs = [
        {
            "description": leg.description,
            "event_id": leg.event.event_id,
            "market_type": leg.quote.market_type.value,
        }
        for leg in cand.ticket.legs
    ]
    bet = services.record_actual_bet(ctx, {"candidate_id": cid, "legs": legs, "stake_usd": "4"}, "bet-1").bet
    other = ctx_for("user-b", ctx)
    with pytest.raises(NotFound):
        services.check_parlay_correlation(other, cid)
    with pytest.raises(NotFound):
        services.import_hardrock_quote(other, cid, {"combined_decimal": "7", "user_confirmed": True})
    with pytest.raises(NotFound):
        services.release_reservation(other, rsv.reservation_id, "not mine")
    with pytest.raises(NotFound):
        services.reconcile_settlement(other, bet.bet_id, {"status": "WON", "cash_returned_usd": "30"})
    with pytest.raises(NotFound):
        services.record_actual_bet(other, {"candidate_id": cid, "legs": legs, "stake_usd": "4"}, "bet-2")
    assert services.export_my_data(other).tables["bets"] == []
    assert services.get_daily_budget(other).recorded_stake_usd == Decimal("0.00")


def test_default_date_is_today_in_et(settings, db, live):
    late = FixedClock(datetime(2026, 10, 21, 2, 0, tzinfo=UTC))  # 22:00 ET on Oct 20
    ctx = services.RequestContext(
        user_id="u", clock=late, db=db, settings=settings, providers=registry_for(live)
    )
    assert services.get_daily_budget(ctx).date_local == "2026-10-20"
    assert services.analyze_my_parlay(ctx, manual_inputs()).ticket.legs[0].event.event_id.endswith("BOS@DET")


def test_candidates_survive_reopen(ctx, settings):
    cid = ready_candidate(ctx)
    ctx.db.dispose()
    reopened = open_database(settings.effective_database_url, allow_fixture_ledger=True)
    try:
        again = services.RequestContext(
            user_id="local-owner", clock=ctx.clock, db=reopened, settings=settings
        )
        loaded = services.load_candidate(again, cid)
        assert loaded.state == S.CandidateState.READY_FOR_USER_REVIEW and loaded.book_quote is not None
    finally:
        reopened.dispose()


def test_real_ledger_refuses_fixture_candidate(tmp_path, strict_db, clock):
    fx = Settings(data_dir=tmp_path, database_url=f"sqlite:///{tmp_path / 'strict.db'}", data_mode="fixture")
    early = FixedClock(datetime(2026, 10, 20, 15, 0, tzinfo=UTC))
    ctx = services.RequestContext(user_id="local-owner", clock=early, db=strict_db, settings=fx)
    ctx.providers = services.build_providers(ctx)
    build = services.build_three_leg_parlays(ctx, "2026-10-20", include_props=False)
    cid = build.primary_candidate_id
    cand = services.import_hardrock_quote(ctx, cid, {"combined_decimal": "7.0", "user_confirmed": True})
    assert cand.data_mode == S.DataMode.FIXTURE
    legs = [{"description": leg.description, "event_id": leg.event.event_id} for leg in cand.ticket.legs]
    with pytest.raises(InvalidInput) as exc:
        services.record_actual_bet(ctx, {"candidate_id": cid, "legs": legs, "stake_usd": "5"}, "bet-fx")
    assert "FIXTURE_DATA" in exc.value.reason_codes
    assert services.load_candidate(ctx, cid).state == S.CandidateState.READY_FOR_USER_REVIEW
    with strict_db.engine.connect() as conn:
        assert conn.execute(select(dbm.bets)).all() == []


# --------------------------------------------------------------------------------------
# Review fixes (2026-10-19): default idempotency key lifecycle, credit-aware analyze_leg, export scrubbing
# --------------------------------------------------------------------------------------


def test_select_ticket_without_key_replays_live_reservation_then_reserves_again_after_expiry(
    ctx, live, three_game_slate
):
    cid = ready_candidate(ctx)
    first = services.select_ticket(ctx, cid, Decimal("6"))
    assert first.replay is False and first.reservation.idempotency_key == f"select:{cid}"
    assert services.select_ticket(ctx, cid, Decimal("6")).replay is True
    with pytest.raises(InvalidInput) as conflict:
        services.select_ticket(ctx, cid, Decimal("4"))
    assert (
        conflict.value.reason_codes == ["IDEMPOTENCY_CONFLICT"]
        and "release_reservation" in conflict.value.message
    )
    # the TTL passes: the reservation is dead; current prices plus a new select reserve again under a new key
    ctx.clock.advance(ctx.settings.reservation_ttl_seconds + 1)
    events = live_events(three_game_slate)
    live.quotes = live_quotes(events, source_ts=ctx.clock.now_utc() - timedelta(seconds=30))
    assert services.refresh_parlay(ctx, cid).state == S.CandidateState.READY_FOR_USER_REVIEW
    again = services.select_ticket(ctx, cid, Decimal("4"))
    assert again.replay is False and again.reservation.status == S.ReservationStatus.ACTIVE
    assert (
        again.reservation.stake_usd == Decimal("4.00")
        and again.reservation.reservation_id != first.reservation.reservation_id
    )
    assert again.reservation.idempotency_key == f"select:{cid}:2"
    assert again.budget.reserved_stake_usd == Decimal("4.00")
    assert services.load_candidate(ctx, cid).ranking["reservation_id"] == again.reservation.reservation_id


def test_analyze_leg_for_a_featured_market_fetches_no_props(ctx, live):
    featured = next(
        q for q in live.quotes if q.book == "hardrockbet_fl" and q.market_type == S.MarketType.SPREAD
    )
    services.analyze_leg(ctx, S.compute_selection_id(featured), "2026-10-20")
    assert not [c for c in live.calls if c[0] == "props"]


def test_export_reports_key_presence_without_the_ciphertext(settings, db, clock):
    hosted = settings.model_copy(
        update={"auth_mode": "builtin_oauth", "secret_key": config.SecretStr("s3cret")}
    )
    ctx = services.RequestContext(user_id="hosted-user", clock=clock, db=db, settings=hosted)
    services.set_user_settings(ctx, odds_api_key="user-key-456")
    rows = services.export_my_data(ctx).tables["user_settings"]
    assert (
        len(rows) == 1
        and rows[0]["has_own_odds_api_key"] is True
        and rows[0]["odds_api_key_encrypted"] is None
    )
