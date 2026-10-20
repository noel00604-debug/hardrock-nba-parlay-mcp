"""Day-one flow in FIXTURE mode against a temp SQLite ledger opened with allow_fixture_ledger=True.

status -> coverage -> slate -> build -> correlation -> import quote (conflict, then confirmed) -> refresh ->
select_ticket -> record_actual_bet (replay, breach) -> reconcile -> performance and the 30-day review.
Nothing here touches the network; every price is synthetic and labelled FIXTURE.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from test_services import FakeOdds, live_events, live_quotes

from hardrock_nba_parlay import config, services
from hardrock_nba_parlay import db as dbm
from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.config import FixedClock, Settings
from hardrock_nba_parlay.db import open_database
from hardrock_nba_parlay.errors import InvalidInput, NotFound, ServiceError

# 11:00 ET on opening day: nothing has tipped off (BOS@DET is at 15:00 ET).
E2E_NOW = datetime(2026, 10, 20, 15, 0, tzinfo=UTC)
DAY = "2026-10-20"


@pytest.fixture(autouse=True)
def _no_real_secrets(monkeypatch):
    monkeypatch.setattr(config, "get_secret", lambda name: None)


@pytest.fixture
def fx_settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'e2e.db'}",
        allow_fixture_ledger=True,
        data_mode="fixture",
        auth_mode="none",
    )


@pytest.fixture
def fx_db(fx_settings):
    database = open_database(fx_settings.effective_database_url, allow_fixture_ledger=True)
    yield database
    database.dispose()


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(E2E_NOW)


def make_ctx(user_id: str, clock: FixedClock, db, settings: Settings) -> services.RequestContext:
    ctx = services.RequestContext(user_id=user_id, clock=clock, db=db, settings=settings)
    ctx.providers = services.build_providers(ctx)
    return ctx


@pytest.fixture
def ctx(fx_settings, fx_db, clock) -> services.RequestContext:
    return make_ctx("local-owner", clock, fx_db, fx_settings)


def legs_payload(candidate: S.Candidate) -> list[dict]:
    return [
        {
            "description": leg.description,
            "event_id": leg.event.event_id,
            "market_type": leg.quote.market_type.value,
            "period": leg.quote.period.value,
            "side": leg.quote.side.value,
            "line": None if leg.quote.line is None else str(leg.quote.line),
            "player_name": leg.quote.player_name_raw,
            "team_name": leg.team.name if leg.team else None,
            "accepted_decimal": str(leg.quote.odds_decimal),
        }
        for leg in candidate.ticket.legs
    ]


def test_day_one_flow(ctx, fx_db, clock):
    # 1. status
    status = services.get_system_status(ctx)
    assert status.data_modes_available == [S.DataMode.MANUAL_INPUT, S.DataMode.FIXTURE]
    assert status.provider_configured is False and status.database_ok is True
    assert status.ai_disclosure == S.AI_DISCLOSURE and status.daily_cap_usd == Decimal("10.00")
    assert any("FIXTURE" in w for w in status.warnings)

    # 2. coverage
    coverage = services.check_data_coverage(ctx, DAY, probe_props=True)
    assert coverage.data_mode == S.DataMode.FIXTURE
    assert coverage.hard_rock_single_leg["MONEYLINE"].status == S.CoverageStatus.PASS
    assert coverage.hard_rock_single_leg["PLAYER_POINTS"].status == S.CoverageStatus.PARTIAL
    assert coverage.reference_markets["TOTAL"].status == S.CoverageStatus.PASS
    assert coverage.injury_information.status == S.CoverageStatus.PARTIAL  # the 7 PM report is 16 h old
    assert coverage.injury_information.reason_codes == ["INJURY_REPORT_STALE"]
    assert coverage.three_leg_combinability.status == S.CoverageStatus.UNKNOWN
    assert coverage.three_leg_combinability.reason_codes == ["COMBINATION_UNVERIFIED"]
    assert coverage.combined_payout_verification.status == S.CoverageStatus.BLOCKED
    assert coverage.stats_and_settlement_rules.status == S.CoverageStatus.PARTIAL
    assert any("nothing here is live" in n for n in coverage.notes)
    assert any("skew" in n for n in coverage.notes)

    # 3. slate
    slate = services.get_nba_slate(ctx, DAY)
    assert [e.event_id for e in slate.events] == ["fixture:BOS@DET", "fixture:PHI@NYK", "fixture:OKC@SAS"]
    assert slate.data_mode == S.DataMode.FIXTURE and "FIXTURE_DATA" in slate.reason_codes
    assert slate.events[0].commence_time_display == "2026-10-20T15:00:00-04:00"
    assert "NEEDS_ONBOARDING" in slate.warnings
    with fx_db.engine.connect() as conn:
        assert len(conn.execute(select(dbm.events_cache)).all()) == 3
    injuries = services.get_injury_context(ctx, "fixture:PHI@NYK")
    assert len(injuries.entries) == 6 and "INJURY_REPORT_STALE" in injuries.reason_codes
    assert injuries.report_timestamp_utc == datetime(2026, 10, 19, 23, 0, tzinfo=UTC)

    # 4. build
    build = services.build_three_leg_parlays(ctx, DAY)
    assert len(build.candidates) == 3 and build.data_mode == S.DataMode.FIXTURE
    assert build.primary_candidate_id == build.candidates[0].candidate_id
    assert build.no_ticket_reason is None and build.credits_used == 0
    assert build.ai_disclosure == S.AI_DISCLOSURE and build.combinations_evaluated <= 2024
    primary = build.candidates[0]
    assert primary.parlay_type == S.ParlayType.MULTI_GAME and len(set(primary.ticket.event_ids)) == 3
    assert primary.state == S.CandidateState.NEEDS_BOOK_QUOTE and primary.data_mode == S.DataMode.FIXTURE
    assert primary.p_joint is not None and primary.model_state == S.ModelState.MARKET_BASELINE
    assert (
        primary.ai_disclosure == S.AI_DISCLOSURE
        and primary.ranking["note"] == "ranking never uses payout size"
    )
    assert all(len(set(c.ticket.event_ids)) == 3 for c in build.candidates)
    with fx_db.engine.connect() as conn:
        assert len(conn.execute(select(dbm.odds_snapshots)).all()) > 0
        assert len(conn.execute(select(dbm.injury_snapshots)).all()) == 16
    history = services.list_candidate_history(ctx, primary.candidate_id)
    assert [(h["from_state"], h["to_state"]) for h in history] == [("RESEARCH_CANDIDATE", "NEEDS_BOOK_QUOTE")]

    # 5. correlation
    report = services.check_parlay_correlation(ctx, primary.candidate_id)
    assert report.joint_numeric_allowed is True and "independence" in report.weakest_assumption

    # 6. quote: conflict first, then confirmed
    cid = primary.candidate_id
    conflict = services.import_hardrock_quote(
        ctx,
        cid,
        {
            "combined_decimal": "7.00",
            "legs_as_shown": ["Lakers -3.5", "Clippers ML", "Celtics over 300.5"],
            "user_confirmed": True,
        },
    )
    assert (
        conflict.state == S.CandidateState.NEEDS_BOOK_QUOTE
        and "QUOTE_CONFLICTS_WITH_LEGS" in conflict.reason_codes
    )
    assert conflict.book_quote is not None and "legs_as_shown" in conflict.book_quote.unresolved_fields
    with pytest.raises(ServiceError) as not_ready:
        services.select_ticket(ctx, cid, Decimal("6"))
    assert not_ready.value.reason_codes == ["QUOTE_CONFLICTS_WITH_LEGS"]
    confirmed = services.import_hardrock_quote(
        ctx,
        cid,
        {
            "combined_decimal": "7.00",
            "stake_shown_usd": "10",
            "payout_shown_usd": "70",
            "payout_includes_stake": True,
            "legs_as_shown": [leg.description for leg in primary.ticket.legs],
            "user_confirmed": True,
        },
    )
    assert confirmed.state == S.CandidateState.READY_FOR_USER_REVIEW
    assert confirmed.payout.combined_source == "BOOK_QUOTE" and confirmed.payout.combined_decimal == Decimal(
        "7.0000"
    )
    assert "QUOTE_REPLACES_INDICATIVE" in confirmed.reason_codes and confirmed.ev_per_dollar is not None
    with fx_db.engine.connect() as conn:
        assert len(conn.execute(select(dbm.book_quotes)).all()) == 2

    # 7. refresh (fixture prices do not move)
    clock.advance(60)
    refreshed = services.refresh_parlay(ctx, cid)
    assert refreshed.state == S.CandidateState.READY_FOR_USER_REVIEW
    assert (
        refreshed.inputs_snapshot_utc == clock.now_utc() and refreshed.payout.combined_source == "BOOK_QUOTE"
    )

    # 8. select_ticket
    selected = services.select_ticket(ctx, cid, Decimal("6"), "select-1")
    assert selected.reservation.status == S.ReservationStatus.ACTIVE and selected.replay is False
    assert selected.budget.reserved_stake_usd == Decimal("6.00") and selected.budget.remaining_usd == Decimal(
        "4.00"
    )
    assert selected.budget.recorded_stake_usd == Decimal(
        "0.00"
    ) and selected.budget.proposed_stake_usd == Decimal("6.00")
    assert selected.candidate.state == S.CandidateState.READY_FOR_USER_REVIEW
    assert selected.candidate.ranking["reservation_id"] == selected.reservation.reservation_id
    assert selected.reservation.expires_at_utc == min(
        clock.now_utc() + timedelta(seconds=ctx.settings.reservation_ttl_seconds), refreshed.expires_at_utc
    )
    assert services.select_ticket(ctx, cid, Decimal("6"), "select-1").replay is True
    other_cid = build.candidates[1].candidate_id
    with pytest.raises(ServiceError) as needs_quote:
        services.select_ticket(ctx, other_cid, Decimal("1"))
    assert (
        needs_quote.value.reason_codes == ["QUOTE_FIELDS_MISSING"]
        and "NEEDS_BOOK_QUOTE" in needs_quote.value.message
    )

    # 9. record_actual_bet: the user placed it in the app
    ticket = {
        "candidate_id": cid,
        "ticket_ref": "HR-123",
        "legs": legs_payload(refreshed),
        "accepted_combined_decimal": "7.00",
        "stake_usd": "6",
        "source": "USER_CONFIRMATION",
    }
    recorded = services.record_actual_bet(ctx, ticket, "bet-1")
    assert recorded.replay is False and recorded.breach_flags == []
    assert (
        recorded.bet.candidate_id == cid
        and recorded.bet.reservation_id == selected.reservation.reservation_id
    )
    assert recorded.bet.recommended_combined_decimal == Decimal("7.0000")
    assert recorded.budget.recorded_stake_usd == Decimal(
        "6.00"
    ) and recorded.budget.reserved_stake_usd == Decimal("0.00")
    assert recorded.budget.remaining_usd == Decimal("4.00")
    assert services.load_candidate(ctx, cid).state == S.CandidateState.USER_CONFIRMED_PLACED
    replay = services.record_actual_bet(ctx, ticket, "bet-1")
    assert replay.replay is True and replay.bet.bet_id == recorded.bet.bet_id
    breach = services.record_actual_bet(
        ctx,
        {
            "legs": [{"description": "external 2-leg parlay"}],
            "stake_usd": "8",
            "external": True,
            "source": "EXTERNAL_REPORT",
        },
        "bet-2",
    )
    assert "BUDGET_BREACH_RECORDED" in breach.breach_flags and breach.budget.raw_remaining_usd == Decimal(
        "-4.00"
    )
    assert (
        breach.budget.remaining_usd == Decimal("0.00") and "BUDGET_BREACH_RECORDED" in breach.budget.breaches
    )

    # 10. reconcile: the book paid
    settled = services.reconcile_settlement(
        ctx,
        recorded.bet.bet_id,
        {"status": "WON", "cash_returned_usd": "42.00", "leg_results": ["WON", "WON", "WON"]},
    )
    assert settled.bet.status == S.BetStatus.WON and settled.settlement.cash_returned_usd == Decimal("42.00")
    assert settled.replay is False and services.load_candidate(ctx, cid).state == S.CandidateState.SETTLED
    again = services.reconcile_settlement(
        ctx,
        recorded.bet.bet_id,
        {"status": "WON", "cash_returned_usd": "42.00", "leg_results": ["WON", "WON", "WON"]},
    )
    assert again.replay is True and "IDEMPOTENT_REPLAY" in again.warnings
    final_history = services.list_candidate_history(ctx, cid)
    assert [h["to_state"] for h in final_history][-3:] == [
        "READY_FOR_USER_REVIEW",
        "USER_CONFIRMED_PLACED",
        "SETTLED",
    ]

    # 11. performance and review
    perf = services.get_performance(ctx, DAY, DAY)
    assert perf.tickets_placed == 2 and perf.settled_tickets == 1
    assert perf.net_profit_usd == Decimal("36.00") and perf.pending_exposure_usd == Decimal("8.00")
    assert perf.ticket_win_rate.numerator == 1 and perf.leg_hit_rate.numerator == 3
    assert perf.calibration and perf.calibration[0].forecast_p_joint == primary.p_joint
    review = services.generate_30_day_review(ctx)
    assert review.window_start == "2026-10-20" and review.window_end == "2026-11-18"
    assert review.days_with_bets == 1 and review.max_possible_gross_stake_usd == Decimal("300.00")
    assert any("not evidence" in line for line in review.evidence_of_skill)


def test_no_suitable_ticket_when_slate_is_empty(ctx):
    build = services.build_three_leg_parlays(ctx, "2026-10-22")
    assert build.candidates == [] and build.primary_candidate_id is None
    assert build.no_ticket_reason == "NO SUITABLE TICKET: no NBA games on 2026-10-22 (America/New_York)"
    assert "NO_SUITABLE_TICKET" in build.reason_codes


def test_no_suitable_ticket_when_every_leg_is_stale(fx_settings, fx_db, clock):
    ctx = services.RequestContext(user_id="local-owner", clock=clock, db=fx_db, settings=fx_settings)
    stale = services.FixtureOddsProvider(fx_settings, clock, received_at=E2E_NOW - timedelta(minutes=20))
    ctx.providers = services.ProviderRegistry(
        odds=stale, injury=stale, fixture=stale, data_mode=S.DataMode.FIXTURE
    )
    build = services.build_three_leg_parlays(ctx, DAY)
    assert build.candidates == []
    assert build.no_ticket_reason is not None and build.no_ticket_reason.startswith("NO SUITABLE TICKET")
    assert {"NO_SUITABLE_TICKET", "QUOTE_STALE"} <= set(build.reason_codes)
    assert build.coverage_summary["legs_usable"] == "0/32"


def test_wait_for_update_for_a_questionable_prop(ctx):
    inputs = [
        {
            "game": "BOS@DET",
            "market": "PLAYER_POINTS",
            "side": "OVER",
            "line": "8.5",
            "player_name": "Taurean Prince",
            "odds_american": -110,
        },
        {"game": "PHI@NYK", "market": "TOTAL", "side": "OVER", "line": "224.5", "odds_american": -110},
        {"game": "OKC@SAS", "market": "MONEYLINE", "side": "AWAY", "odds_american": -150},
    ]
    cand = services.analyze_my_parlay(ctx, inputs, None, DAY)
    prince = cand.leg_analyses[0]
    assert (
        prince.decision == S.LegDecision.WAIT_FOR_UPDATE
        and "INJURY_QUESTIONABLE_MATERIAL" in prince.reason_codes
    )
    assert "Taurean Prince is Questionable" in prince.strongest_reason_against
    # Typed legs matched to the FIXTURE slate and priced against FIXTURE benchmarks are fixture data.
    assert cand.data_mode == S.DataMode.FIXTURE and cand.p_joint is None
    quoted = services.import_hardrock_quote(
        ctx, cand.candidate_id, {"combined_decimal": "6.2", "user_confirmed": True}
    )
    assert quoted.state == S.CandidateState.NEEDS_BOOK_QUOTE and "WAIT_FOR_UPDATE" in quoted.reason_codes
    with pytest.raises(ServiceError) as exc:
        services.select_ticket(ctx, cand.candidate_id, Decimal("5"))
    assert exc.value.reason_codes == ["WAIT_FOR_UPDATE"]


def test_same_game_request_is_qualitative(ctx):
    build = services.build_three_leg_parlays(ctx, DAY, parlay_type="same_game", max_candidates=2)
    assert len(build.candidates) == 2
    for cand in build.candidates:
        assert cand.parlay_type == S.ParlayType.SAME_GAME
        assert cand.p_joint is None and cand.ev_per_dollar is None
        assert cand.model_state == S.ModelState.INSUFFICIENT_EVIDENCE
        assert "not called value" in cand.rationale
        assert {"SAME_GAME_CORRELATION", "JOINT_PROBABILITY_UNAVAILABLE", "EV_UNAVAILABLE"} <= set(
            cand.reason_codes
        )
    quoted = services.import_hardrock_quote(
        ctx, build.primary_candidate_id, {"combined_decimal": "6.0", "user_confirmed": True}
    )
    assert quoted.state == S.CandidateState.READY_FOR_USER_REVIEW and quoted.ev_per_dollar is None


def test_select_ticket_refuses_stale_inputs(ctx, clock):
    build = services.build_three_leg_parlays(ctx, DAY, include_props=False)
    cid = build.primary_candidate_id
    services.import_hardrock_quote(ctx, cid, {"combined_decimal": "7.0", "user_confirmed": True})
    clock.advance(ctx.settings.max_odds_age_seconds + 5)
    with pytest.raises(ServiceError) as exc:
        services.select_ticket(ctx, cid, Decimal("5"))
    assert exc.value.reason_codes == ["QUOTE_STALE"] and "refresh_parlay" in exc.value.message
    services.refresh_parlay(ctx, cid)
    assert services.select_ticket(ctx, cid, Decimal("5")).reservation.status == S.ReservationStatus.ACTIVE


def test_started_game_expires_on_refresh_and_select(ctx, clock):
    build = services.build_three_leg_parlays(ctx, DAY, include_props=False)
    cid = build.primary_candidate_id
    services.import_hardrock_quote(ctx, cid, {"combined_decimal": "7.0", "user_confirmed": True})
    clock.set(datetime(2026, 10, 20, 19, 30, tzinfo=UTC))  # BOS@DET tipped at 19:00Z
    with pytest.raises(ServiceError) as exc:
        services.select_ticket(ctx, cid, Decimal("5"))
    assert exc.value.reason_codes == ["GAME_STARTED"]
    assert services.load_candidate(ctx, cid).state == S.CandidateState.EXPIRED
    assert services.refresh_parlay(ctx, cid).state == S.CandidateState.EXPIRED


def test_tenant_isolation(ctx, fx_db, clock, fx_settings):
    build = services.build_three_leg_parlays(ctx, DAY, include_props=False)
    cid = build.primary_candidate_id
    services.import_hardrock_quote(ctx, cid, {"combined_decimal": "7.0", "user_confirmed": True})
    rsv = services.select_ticket(ctx, cid, Decimal("4")).reservation
    cand = services.load_candidate(ctx, cid)
    bet = services.record_actual_bet(
        ctx, {"candidate_id": cid, "legs": legs_payload(cand), "stake_usd": "4"}, "bet-a"
    ).bet
    other = make_ctx("user-b", clock, fx_db, fx_settings)
    with pytest.raises(NotFound):
        services.check_parlay_correlation(other, cid)
    with pytest.raises(NotFound):
        services.refresh_parlay(other, cid)
    with pytest.raises(NotFound):
        services.release_reservation(other, rsv.reservation_id, "not mine")
    with pytest.raises(NotFound):
        services.reconcile_settlement(other, bet.bet_id, {"status": "WON", "cash_returned_usd": "20"})
    assert services.export_my_data(other).tables["candidates"] == []
    assert services.get_daily_budget(other, DAY).recorded_stake_usd == Decimal("0.00")
    assert services.get_daily_budget(ctx, DAY).recorded_stake_usd == Decimal("4.00")


def test_candidates_survive_db_reopen(ctx, fx_settings, clock):
    build = services.build_three_leg_parlays(ctx, DAY, include_props=False)
    cid = build.primary_candidate_id
    services.import_hardrock_quote(ctx, cid, {"combined_decimal": "7.0", "user_confirmed": True})
    ctx.db.dispose()
    reopened = open_database(fx_settings.effective_database_url, allow_fixture_ledger=True)
    try:
        again = make_ctx("local-owner", clock, reopened, fx_settings)
        loaded = services.load_candidate(again, cid)
        assert loaded.state == S.CandidateState.READY_FOR_USER_REVIEW and loaded.book_quote is not None
        assert loaded.ticket.legs[0].selection_id == build.candidates[0].ticket.legs[0].selection_id
        assert services.select_ticket(again, cid, Decimal("3")).budget.remaining_usd == Decimal("7.00")
    finally:
        reopened.dispose()


def test_real_ledger_refuses_the_fixture_bet(tmp_path, clock):
    strict_settings = Settings(
        data_dir=tmp_path, database_url=f"sqlite:///{tmp_path / 'strict.db'}", data_mode="fixture"
    )
    strict = open_database(strict_settings.effective_database_url, allow_fixture_ledger=False)
    try:
        ctx = make_ctx("local-owner", clock, strict, strict_settings)
        build = services.build_three_leg_parlays(ctx, DAY, include_props=False)
        cid = build.primary_candidate_id
        cand = services.import_hardrock_quote(ctx, cid, {"combined_decimal": "7.0", "user_confirmed": True})
        with pytest.raises(ServiceError) as exc:
            services.record_actual_bet(
                ctx, {"candidate_id": cid, "legs": legs_payload(cand), "stake_usd": "5"}, "bet-fx"
            )
        assert isinstance(exc.value, InvalidInput) and "FIXTURE_DATA" in exc.value.reason_codes
        with strict.engine.connect() as conn:
            assert conn.execute(select(dbm.bets)).all() == []
    finally:
        strict.dispose()


def test_live_mode_without_key_raises_no_provider_key(tmp_path, clock):
    live_settings = Settings(
        data_dir=tmp_path, database_url=f"sqlite:///{tmp_path / 'live.db'}", data_mode="live"
    )
    db = open_database(live_settings.effective_database_url)
    try:
        ctx = make_ctx("local-owner", clock, db, live_settings)
        status = services.get_system_status(ctx)
        assert status.provider_configured is False and S.DataMode.FIXTURE not in status.data_modes_available
        with pytest.raises(ServiceError) as exc:
            services.check_data_coverage(ctx, DAY)
        assert exc.value.reason_codes == ["NO_PROVIDER_KEY"]
        assert "hrnba secret set ODDS_API_KEY" in (exc.value.detail or "")
    finally:
        db.dispose()


def test_hosted_per_user_credit_quota(tmp_path, clock, three_game_slate):
    hosted = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'hosted.db'}",
        data_mode="live",
        auth_mode="builtin_oauth",
        secret_key=config.SecretStr("secret"),
        odds_api_key=config.SecretStr("server-key"),
        per_user_daily_credit_quota=3,
    )
    db = open_database(hosted.effective_database_url)
    try:
        ctx = make_ctx("hosted-user", clock, db, hosted)
        assert ctx.providers is not None and ctx.providers.key_source == "server"
        # Swap the real adapter for a LIVE-stamped fake so no request can leave the process.
        events = live_events(three_game_slate)
        ctx.providers.odds = ctx.providers.injury = FakeOdds(events, live_quotes(events))
        with db.tx() as conn:
            conn.execute(
                dbm.provider_usage.insert().values(
                    user_id="hosted-user",
                    provider="the-odds-api",
                    endpoint="/odds",
                    credits_cost=3,
                    created_at=dbm.iso(clock.now_utc()),
                )
            )
        with pytest.raises(ServiceError) as exc:
            services.check_data_coverage(ctx, DAY)
        assert exc.value.reason_codes == ["PROVIDER_CREDIT_GUARD"]
        assert services.get_system_status(ctx).provider_configured is True
    finally:
        db.dispose()


def test_default_date_is_today_in_et(fx_settings, fx_db):
    late = FixedClock(datetime(2026, 10, 21, 3, 0, tzinfo=UTC))  # 23:00 ET on Oct 20
    ctx = make_ctx("local-owner", late, fx_db, fx_settings)
    assert services.get_daily_budget(ctx).date_local == DAY
    assert config.local_date(late.now_utc()) == DAY
