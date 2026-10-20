"""Independent adversarial review of the pipeline module (candidate_builder, quote_review, services).

Every test here was written to FAIL against the implementation under review; each failure is a reproduced
defect described in the test docstring. Tests marked "documented behaviour" pass and are kept only because
they pin down a non-obvious consumer contract. FIXTURE data and fakes only; nothing touches the network.
"""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from conftest import NOW, TEAMS, make_event, make_quote, make_selection
from mcp.client import Client
from sqlalchemy import insert, select
from test_candidate_builder import ref_quotes
from test_services import FakeOdds, live_events, live_quotes, ready_candidate, registry_for

from hardrock_nba_parlay import candidate_builder as CB
from hardrock_nba_parlay import config, quote_review, services
from hardrock_nba_parlay import db as dbm
from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.config import FixedClock, Settings
from hardrock_nba_parlay.db import iso, open_database
from hardrock_nba_parlay.errors import InvalidInput, ProviderError, ServiceError
from hardrock_nba_parlay.mcp_server import TOOL_NAMES, build_server

DAY = "2026-10-20"


@pytest.fixture(autouse=True)
def _no_real_secrets(monkeypatch):
    monkeypatch.setattr(config, "get_secret", lambda name: None)


@pytest.fixture
def live(three_game_slate, db):
    events = live_events(three_game_slate)
    return FakeOdds(events, live_quotes(events), [], db=db, user_id="local-owner")


@pytest.fixture
def ctx(settings, db, clock, live) -> services.RequestContext:
    return services.RequestContext(
        user_id="local-owner", clock=clock, db=db, settings=settings, providers=registry_for(live)
    )


def fixture_ctx(tmp_path, clock, *, allow_fixture_ledger: bool, user_id: str = "local-owner"):
    cfg = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'fx.db'}",
        allow_fixture_ledger=allow_fixture_ledger,
        data_mode="fixture",
        auth_mode="none",
    )
    database = open_database(cfg.effective_database_url, allow_fixture_ledger=allow_fixture_ledger)
    ctx = services.RequestContext(user_id=user_id, clock=clock, db=database, settings=cfg)
    ctx.providers = services.build_providers(ctx)
    return ctx


# --------------------------------------------------------------------------------------
# quote_review: legs_as_shown accepts slips that describe a different bet
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "slip",
    [
        # the sign of a spread is stripped by normalisation: DET -3.5 is accepted for the DET +3.5 leg
        ["DET -3.5", "PHI/NYK over 224.5", "OKC ML"],
        # the slip names the matchup and the OPPONENT's moneyline; the candidate team's alias in the matchup
        # text is enough for the OKC ML leg to "match"
        ["DET +3.5", "PHI/NYK over 224.5", "Oklahoma City Thunder @ San Antonio Spurs: San Antonio Spurs ML"],
        # a game total from ANOTHER game at the same number is accepted for the PHI/NYK total
        ["DET +3.5", "Celtics @ Pistons Over 224.5", "OKC ML"],
    ],
)
def test_legs_as_shown_must_reject_a_slip_that_describes_a_different_bet(three_multi_game_legs, slip):
    """DEFECT: match_legs_as_shown reports no conflict for slip lines that describe a different wager
    (opposite handicap sign, the opponent's moneyline, or another game's total), so review_book_quote
    accepts the quote and the candidate can reach READY_FOR_USER_REVIEW with legs that are not on the slip."""
    ticket = S.ThreeLegTicket(legs=three_multi_game_legs)
    _indexes, conflicts = quote_review.match_legs_as_shown(slip, ticket)
    assert conflicts, f"slip {slip!r} was accepted as matching {[leg.description for leg in ticket.legs]}"


def test_quote_contradicted_by_the_slip_payout_is_not_ready(ctx):
    """DEFECT: stake 10 at combined 7.00 cannot pay 100 (stake included). The payout field is marked
    unresolved but the candidate still becomes READY_FOR_USER_REVIEW with payout math at the contradicted
    price; the user-confirmed quote fields disagree with each other and nothing blocks."""
    build = services.build_three_leg_parlays(ctx, DAY, include_props=False)
    cid = build.primary_candidate_id
    updated = services.import_hardrock_quote(
        ctx,
        cid,
        {
            "combined_decimal": "7.00",
            "stake_shown_usd": "10",
            "payout_shown_usd": "100",
            "payout_includes_stake": True,
            "user_confirmed": True,
        },
    )
    assert updated.book_quote is not None and "payout_shown_usd" in updated.book_quote.unresolved_fields
    assert updated.state != S.CandidateState.READY_FOR_USER_REVIEW


def test_quote_captured_hours_ago_is_not_ready(ctx):
    """DEFECT: a slip quote captured two hours ago (older than max_odds_age_seconds) is accepted as the
    current book price: the candidate becomes READY_FOR_USER_REVIEW with no QUOTE_STALE code, although every
    other price in the system is held to the 180 s limit."""
    build = services.build_three_leg_parlays(ctx, DAY, include_props=False)
    cid = build.primary_candidate_id
    old = ctx.clock.now_utc() - timedelta(hours=2)
    updated = services.import_hardrock_quote(
        ctx, cid, {"combined_decimal": "7.00", "captured_at_utc": old.isoformat(), "user_confirmed": True}
    )
    assert updated.state != S.CandidateState.READY_FOR_USER_REVIEW or "QUOTE_STALE" in updated.reason_codes, (
        "a two-hour-old book quote made the candidate READY_FOR_USER_REVIEW"
    )


def test_select_ticket_names_sign_ambiguity_as_the_reason(ctx):
    """DEFECT (minor): a confirmed quote whose american and decimal prices disagree is stored with
    unresolved 'combined_odds', but select_ticket then reports QUOTE_FIELDS_MISSING instead of the code that
    actually blocks it (QUOTE_SIGN_AMBIGUOUS), so the caller is told to import a quote it already imported."""
    build = services.build_three_leg_parlays(ctx, DAY, include_props=False)
    cid = build.primary_candidate_id
    updated = services.import_hardrock_quote(
        ctx, cid, {"combined_decimal": "7.00", "combined_american": 500, "user_confirmed": True}
    )
    assert "QUOTE_SIGN_AMBIGUOUS" in updated.reason_codes
    with pytest.raises(ServiceError) as exc:
        services.select_ticket(ctx, cid, Decimal("5"))
    assert "QUOTE_SIGN_AMBIGUOUS" in exc.value.reason_codes


# --------------------------------------------------------------------------------------
# services.select_ticket: the default idempotency key outlives the reservation
# --------------------------------------------------------------------------------------


def test_select_ticket_after_release_reserves_again(ctx):
    """DEFECT: without an explicit key select_ticket uses 'select:<candidate_id>'. After the reservation is
    released (or expires), the same call "replays" the dead reservation: replay=True, status RELEASED,
    nothing reserved, and a different stake raises IDEMPOTENCY_CONFLICT. The user cannot re-reserve budget
    for the candidate through the tool's default path."""
    cid = ready_candidate(ctx)
    first = services.select_ticket(ctx, cid, Decimal("6"))
    services.release_reservation(ctx, first.reservation.reservation_id, "changed my mind")
    assert services.get_daily_budget(ctx).reserved_stake_usd == Decimal("0.00")
    again = services.select_ticket(ctx, cid, Decimal("6"))
    assert again.reservation.status == S.ReservationStatus.ACTIVE
    assert again.replay is False
    assert again.budget.reserved_stake_usd == Decimal("6.00")


def test_select_ticket_after_release_accepts_a_new_stake(ctx):
    """DEFECT (same root cause): after releasing, selecting the same candidate with a different stake and no
    key raises IDEMPOTENCY_CONFLICT instead of reserving."""
    cid = ready_candidate(ctx)
    first = services.select_ticket(ctx, cid, Decimal("6"))
    services.release_reservation(ctx, first.reservation.reservation_id, "changed my mind")
    out = services.select_ticket(ctx, cid, Decimal("4"))
    assert out.reservation.status == S.ReservationStatus.ACTIVE and out.reservation.stake_usd == Decimal(
        "4.00"
    )


# --------------------------------------------------------------------------------------
# services: secrets, settings validation, credits
# --------------------------------------------------------------------------------------


def test_export_my_data_does_not_return_the_encrypted_odds_key(settings, db, clock):
    """DEFECT: export_my_data returns the user_settings row verbatim, including odds_api_key_encrypted (the
    Fernet ciphertext of the user's The Odds API key). Key material leaves the server in a tool response."""
    hosted = settings.model_copy(
        update={"auth_mode": "builtin_oauth", "secret_key": config.SecretStr("s3cret")}
    )
    ctx = services.RequestContext(user_id="hosted-user", clock=clock, db=db, settings=hosted)
    services.set_user_settings(ctx, odds_api_key="user-key-456")
    with db.engine.connect() as conn:
        stored = conn.execute(
            select(dbm.user_settings.c.odds_api_key_encrypted).where(
                dbm.user_settings.c.user_id == "hosted-user"
            )
        ).scalar_one()
    assert stored
    bundle = services.export_my_data(ctx)
    rows = bundle.tables.get("user_settings", [])
    assert all(not row.get("odds_api_key_encrypted") for row in rows)
    assert stored not in json.dumps(bundle.model_dump(mode="json"), default=str)


def test_daily_cap_that_rounds_to_zero_is_rejected(ctx):
    """DEFECT: the cap is checked for > 0 BEFORE it is quantized to cents, so 0.004 passes the check and is
    stored as 0.00: a zero daily cap, which the contract forbids (cap > 0)."""
    with pytest.raises(InvalidInput):
        services.set_user_settings(ctx, daily_cap_usd=Decimal("0.004"))
    assert services.get_user_settings(ctx).daily_cap_usd > 0


def test_analyze_leg_stops_fetching_props_once_the_selection_is_found(ctx, live, three_game_slate):
    """DEFECT: analyze_leg fetches event props for EVERY game on the slate before looking for the selection,
    instead of stopping at the game that carries it. On a ten-game night that is one credited call per game
    for a single leg analysis (the app-wide budget is 25 credits per day)."""
    e2 = three_game_slate[1]
    brunson = next(
        q
        for q in live.quotes
        if q.market_type == S.MarketType.PLAYER_POINTS
        and q.book == "hardrockbet_fl"
        and q.side == S.Side.OVER
    )
    assert brunson.event_id == e2.event_id
    sel_id = S.compute_selection_id(brunson)
    analysis = services.analyze_leg(ctx, sel_id, DAY)
    assert analysis.selection_id == sel_id
    props_calls = [c for c in live.calls if c[0] == "props"]
    assert len(props_calls) < len(three_game_slate), [c[1][0] for c in props_calls]


def test_credit_guard_does_not_throttle_a_user_with_their_own_key(settings, db, clock, three_game_slate):
    """DEFECT: the hosted per-user quota is meant for the server-wide key (ARCHITECTURE section 11) and the
    guard's own hint says "store your own The Odds API key"; but _guard_credits ignores key_source, so a user
    who did store their own key is still refused with PROVIDER_CREDIT_GUARD."""
    hosted = settings.model_copy(
        update={
            "auth_mode": "builtin_oauth",
            "secret_key": config.SecretStr("s3cret"),
            "per_user_daily_credit_quota": 5,
        }
    )
    events = live_events(three_game_slate)
    fake = FakeOdds(events, live_quotes(events), [], db=db, user_id="hosted-user")
    ctx = services.RequestContext(user_id="hosted-user", clock=clock, db=db, settings=hosted)
    services.set_user_settings(ctx, odds_api_key="user-key-456")
    assert services.build_providers(ctx).key_source == "user"
    ctx.providers = services.ProviderRegistry(
        odds=fake, injury=fake, data_mode=S.DataMode.LIVE_PROVIDER, key_configured=True, key_source="user"
    )
    with db.tx() as conn:
        conn.execute(
            insert(dbm.provider_usage).values(
                user_id="hosted-user",
                provider="the-odds-api",
                endpoint="/odds",
                credits_cost=5,
                requests_remaining=None,
                requests_used=None,
                created_at=iso(NOW),
            )
        )
    build = services.build_three_leg_parlays(ctx, DAY, include_props=False)
    assert build.candidates


# --------------------------------------------------------------------------------------
# candidate_builder: the bounded search and benchmarks of unknown age
# --------------------------------------------------------------------------------------


def test_auto_search_still_builds_multi_game_when_a_third_game_falls_outside_the_top_24(settings):
    """DEFECT: "auto" decides between MULTI_GAME and the qualitative same-game set from the events present in
    the top-24 legs, not from all usable legs. When one game has 24 strong-edge props and the other two games
    have one weaker usable leg each, every event has usable legs and a quantified MULTI_GAME ticket exists,
    yet the search returns only qualitative SAME_GAME candidates (p_joint None)."""
    a = make_event("BOS", "DET", event_id="fixture:A")
    b = make_event("PHI", "NYK", start=NOW + timedelta(hours=5), event_id="fixture:B")
    c = make_event("OKC", "SAS", start=NOW + timedelta(hours=6), event_id="fixture:C")
    selections: list[S.Selection] = []
    refs: list[S.MarketQuote] = []
    for i in range(24):
        player = f"Player Number{i}"
        q = make_quote(a, S.MarketType.PLAYER_POINTS, S.Side.OVER, "2.10", line="20.5", player=player)
        selections.append(make_selection(q, a))
        refs += ref_quotes(a, S.MarketType.PLAYER_POINTS, "1.90", "1.90", line="20.5", player=player)
    for event, home in ((b, "NYK"), (c, "SAS")):
        q = make_quote(event, S.MarketType.SPREAD, S.Side.HOME, "1.85", line="3.5", team=TEAMS[home])
        selections.append(make_selection(q, event))
        refs += ref_quotes(event, S.MarketType.SPREAD, "1.91", "1.91", line="3.5")
    analyses = {s.selection_id: CB.analyze_leg(s, refs, [], NOW, settings) for s in selections}
    assert all(x.decision == S.LegDecision.USABLE for x in analyses.values())
    assert len({s.event.event_id for s in selections}) == 3
    out = CB.build_candidates(selections, refs, [], "auto", 3, NOW, settings, "u", analyses=analyses)
    assert out, "no candidate at all"
    assert any(cand.parlay_type == S.ParlayType.MULTI_GAME for cand in out), [c.parlay_type for c in out]


def test_benchmark_without_a_source_timestamp_gives_no_market_baseline(settings, three_game_slate):
    """DEFECT: when the benchmark carries no source timestamp the reference skew cannot be measured, but the
    leg still gets a MARKET_BASELINE probability and an edge, and three such legs give a candidate a joint
    probability and an EV. Section 11 says a benchmark beyond the skew limit is INSUFFICIENT_EVIDENCE and the
    rule is "never silently loosened"; an unmeasurable skew cannot satisfy the limit."""
    selections: list[S.Selection] = []
    refs: list[S.MarketQuote] = []
    for event in three_game_slate:
        home = next(t for t in TEAMS.values() if t.team_id == event.home_team.team_id)
        q = make_quote(event, S.MarketType.SPREAD, S.Side.HOME, "1.95", line="3.5", team=home)
        selections.append(make_selection(q, event))
        for r in ref_quotes(event, S.MarketType.SPREAD, "1.91", "1.91", line="3.5"):
            refs.append(
                r.model_copy(update={"stamp": r.stamp.model_copy(update={"source_timestamp_utc": None})})
            )
    analysis = CB.analyze_leg(selections[0], refs, [], NOW, settings)
    assert "SOURCE_TIMESTAMP_UNKNOWN" in analysis.reason_codes
    assert analysis.probability.state == S.ModelState.INSUFFICIENT_EVIDENCE
    assert analysis.price_value.edge_per_dollar is None
    out = CB.build_candidates(selections, refs, [], "multi_game", 1, NOW, settings, "u")
    assert out and out[0].p_joint is None and out[0].ev_per_dollar is None


# --------------------------------------------------------------------------------------
# services in FIXTURE mode: typed tickets and refresh
# --------------------------------------------------------------------------------------


TYPED_MULTI_GAME = [
    {"game": "BOS@DET", "market": "MONEYLINE", "side": "AWAY", "odds_american": -150},
    {"game": "PHI@NYK", "market": "TOTAL", "side": "OVER", "line": "224.5", "odds_american": -110},
    {"game": "OKC@SAS", "market": "MONEYLINE", "side": "AWAY", "odds_american": -160},
]


def test_fixture_mode_typed_ticket_never_reaches_a_real_ledger(tmp_path, clock):
    """DEFECT: in HRNBA_DATA_MODE=fixture a typed ticket is matched to the FIXTURE slate and priced against
    the FIXTURE benchmarks, but the candidate is labelled MANUAL_INPUT (only the typed leg stamps are
    inspected). record_actual_bet then writes it, with its synthetic p_joint forecast and fixture event ids,
    into a ledger opened with allow_fixture_ledger=False: fixture-derived records reach a real ledger."""
    ctx = fixture_ctx(tmp_path, clock, allow_fixture_ledger=False)
    cand = services.analyze_my_parlay(ctx, TYPED_MULTI_GAME, None, DAY)
    assert cand.p_joint is not None  # priced from fixture benchmarks
    assert all(leg.event.stamp.data_mode == S.DataMode.FIXTURE for leg in cand.ticket.legs)
    ticket = {
        "candidate_id": cand.candidate_id,
        "legs": [
            {"description": leg.description, "event_id": leg.event.event_id} for leg in cand.ticket.legs
        ],
        "stake_usd": "5",
        "source": "USER_CONFIRMATION",
    }
    with pytest.raises(InvalidInput) as exc:
        services.record_actual_bet(ctx, ticket, "bet-fixture-typed")
    assert "FIXTURE_DATA" in exc.value.reason_codes
    ctx.db.dispose()


def test_refresh_keeps_the_line_the_user_typed(tmp_path, clock):
    """DEFECT: refresh_parlay replaces a typed (MANUAL_INPUT) leg with the feed's current main line whenever
    the feed carries the same market at a different line. The user's own ticket (over 226.5) is rewritten to
    the feed's over 224.5 and reported as "price changed", although nothing about the user's slip changed."""
    ctx = fixture_ctx(tmp_path, clock, allow_fixture_ledger=True)
    typed = [
        {"game": "BOS@DET", "market": "MONEYLINE", "side": "AWAY", "odds_american": -150},
        {"game": "PHI@NYK", "market": "TOTAL", "side": "OVER", "line": "226.5", "odds_american": -110},
        {"game": "OKC@SAS", "market": "MONEYLINE", "side": "AWAY", "odds_american": -160},
    ]
    cand = services.analyze_my_parlay(ctx, typed, None, DAY)
    assert cand.ticket.legs[1].quote.line == Decimal("226.5")
    clock.advance(30)
    refreshed = services.refresh_parlay(ctx, cand.candidate_id)
    lines = [leg.quote.line for leg in refreshed.ticket.legs]
    assert lines[1] == Decimal("226.5"), f"typed line rewritten to {lines[1]}"
    ctx.db.dispose()


def test_select_ticket_never_reserves_fixture_budget_on_a_real_ledger(tmp_path, clock):
    """DEFECT: reservations are a ledger table (db.LEDGER_TABLES), but select_ticket never calls
    db.guard_ledger_mode for the candidate's data_mode. In fixture mode against a real ledger
    (allow_fixture_ledger=False) the FIXTURE candidate's reservation is written and counts against the real
    daily budget until it expires, while record_actual_bet for the same candidate is (correctly) refused."""
    ctx = fixture_ctx(tmp_path, clock, allow_fixture_ledger=False)
    build = services.build_three_leg_parlays(ctx, DAY, include_props=False)
    cid = build.primary_candidate_id
    quoted = services.import_hardrock_quote(ctx, cid, {"combined_decimal": "7.0", "user_confirmed": True})
    assert quoted.state == S.CandidateState.READY_FOR_USER_REVIEW and quoted.data_mode == S.DataMode.FIXTURE
    with pytest.raises(InvalidInput) as exc:
        services.select_ticket(ctx, cid, Decimal("5"), "fixture-select")
    assert "FIXTURE_DATA" in exc.value.reason_codes
    assert services.get_daily_budget(ctx, DAY).reserved_stake_usd == Decimal("0.00")
    ctx.db.dispose()


class _InjuryFeedDown:
    name = "nba-official-injury-report"

    def fetch_latest_report(self, now, slate):
        raise ProviderError("injury report host answered 503", ["PROVIDER_ERROR"], status_code=503)


def test_build_degrades_when_the_injury_feed_fails(ctx, live):
    """DEFECT: _fetch_injuries lets a ProviderError from the injury feed (network error, 429, 5xx in
    providers.nba_injury_report.fetch_latest_report) propagate, so build_three_leg_parlays aborts AFTER the
    odds credits were spent and persists nothing. An unavailable injury report is a documented state
    (INJURY_REPORT_MISSING, data quality downgraded); it should not turn a priced slate into a tool error."""
    ctx.providers = services.ProviderRegistry(
        odds=live,
        injury=_InjuryFeedDown(),
        data_mode=S.DataMode.LIVE_PROVIDER,
        key_configured=True,
        key_source="server",
    )
    build = services.build_three_leg_parlays(ctx, DAY, include_props=False)
    assert build.candidates
    assert "INJURY_REPORT_MISSING" in build.reason_codes
    assert any("injury" in w.lower() for w in build.warnings)


# --------------------------------------------------------------------------------------
# Documented behaviour: every MCP tool wrapper reaches the real services module
# --------------------------------------------------------------------------------------


def _payload(result):
    assert result.is_error is False, result
    data = result.structured_content["result"]
    assert "error" not in data or "reason_codes" not in data, data
    return data


async def test_every_mcp_tool_reaches_real_services_in_fixture_mode(tmp_path):
    """Documented behaviour (passes): the twenty mcp_server tool wrappers call services.* with the shapes
    services exposes; one in-process client session drives the whole day-one flow in FIXTURE mode."""
    cfg = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'mcp.db'}",
        allow_fixture_ledger=True,
        data_mode="fixture",
        auth_mode="none",
    )
    database = open_database(cfg.effective_database_url, allow_fixture_ledger=True)
    clock = FixedClock(NOW - timedelta(hours=4))  # 11:00 ET on opening day
    server = build_server(cfg, database, clock)
    seen: set[str] = set()

    async with Client(server) as client:

        async def call(name: str, args: dict | None = None):
            seen.add(name)
            return _payload(await client.call_tool(name, args or {}))

        status = await call("get_system_status")
        assert status["data_modes_available"] == ["MANUAL_INPUT", "FIXTURE"]
        await call("set_user_settings", {"confirm_onboarding": True})
        coverage = await call("check_data_coverage", {"date_local": DAY, "probe_props": True})
        assert coverage["data_mode"] == "FIXTURE"
        slate = await call("get_nba_slate", {"date_local": DAY})
        assert len(slate["events"]) == 3
        await call("get_injury_context", {"event_id": "fixture:PHI@NYK"})
        build = await call("build_three_leg_parlays", {"date_local": DAY})
        primary = build["candidates"][0]
        cid = primary["candidate_id"]
        await call(
            "analyze_leg", {"selection_id": primary["ticket"]["legs"][0]["selection_id"], "date_local": DAY}
        )
        await call("check_parlay_correlation", {"candidate_id": cid})
        quoted = await call(
            "import_hardrock_quote",
            {"candidate_id": cid, "quote_fields": {"combined_decimal": "7.0", "user_confirmed": True}},
        )
        assert quoted["state"] == "READY_FOR_USER_REVIEW"
        await call("refresh_parlay", {"candidate_id": cid})
        selected = await call(
            "select_ticket", {"candidate_id": cid, "stake_usd": "4", "idempotency_key": "k1"}
        )
        await call("get_daily_budget", {"date_local": DAY, "proposed_stake_usd": "1"})
        await call(
            "release_reservation",
            {"reservation_id": selected["reservation"]["reservation_id"], "reason": "not placing"},
        )
        recorded = await call(
            "record_actual_bet",
            {
                "confirmed_ticket_fields": {
                    "candidate_id": cid,
                    "legs": [{"description": leg["description"]} for leg in primary["ticket"]["legs"]],
                    "stake_usd": "4",
                },
                "idempotency_key": "bet-k1",
            },
        )
        await call(
            "reconcile_settlement",
            {"bet_id": recorded["bet"]["bet_id"], "settlement_fields": {"status": "LOST"}},
        )
        await call("get_performance", {"start_date": DAY, "end_date": DAY})
        await call("generate_30_day_review")
        await call("add_cost", {"cost": {"date_local": DAY, "description": "odds api", "amount_usd": "1.00"}})
        await call("export_my_data")
        typed = await call("analyze_my_parlay", {"three_selections": TYPED_MULTI_GAME, "date_local": DAY})
        assert typed["parlay_type"] == "MULTI_GAME"
    assert seen == set(TOOL_NAMES)
    database.dispose()
