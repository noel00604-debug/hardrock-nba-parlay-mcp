"""MCP server tests: in-process client session against a FAKE services namespace (no network, no real services)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from mcp.client import Client
from sqlalchemy import select

from hardrock_nba_parlay import db as dbm
from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.errors import NotFound
from hardrock_nba_parlay.mcp_server import TOOL_NAMES, build_server, make_request_context

NOW = datetime(2026, 10, 20, 19, 0, tzinfo=UTC)


@dataclass
class RequestContext:
    user_id: str
    clock: Any
    db: Any
    settings: Any
    providers: Any = None


def system_status(ctx: Any) -> S.SystemStatus:
    now = ctx.clock.now_utc()
    return S.SystemStatus(
        app_version=ctx.settings.version,
        now_utc=now,
        now_display="2026-10-20T15:00:00-04:00",
        display_tz="America/New_York",
        auth_mode=ctx.settings.auth_mode,
        user_id_masked=ctx.user_id[:4] + "***",
        database_ok=True,
        database_kind="sqlite",
        provider_configured=False,
        data_modes_available=[S.DataMode.FIXTURE],
        target_book="hardrockbet_fl",
        jurisdiction="US-FL",
        daily_cap_usd=Decimal("10.00"),
        onboarding_complete=False,
        warnings=["FIXTURE data only"],
    )


def daily_budget(date_local: str, recorded: Decimal = Decimal("0")) -> S.DailyBudget:
    cap = Decimal("10.00")
    return S.DailyBudget(
        date_local=date_local,
        cap_usd=cap,
        recorded_stake_usd=recorded,
        reserved_stake_usd=Decimal("0"),
        remaining_usd=max(Decimal("0"), cap - recorded),
        raw_remaining_usd=cap - recorded,
    )


def accepted_legs() -> list[S.AcceptedLeg]:
    return [
        S.AcceptedLeg(
            description="DET +3.5",
            market_type=S.MarketType.SPREAD,
            side=S.Side.HOME,
            line=Decimal("3.5"),
            accepted_decimal=Decimal("1.91"),
        ),
        S.AcceptedLeg(
            description="PHI/NYK over 224.5",
            market_type=S.MarketType.TOTAL,
            side=S.Side.OVER,
            line=Decimal("224.5"),
            accepted_decimal=Decimal("1.91"),
        ),
        S.AcceptedLeg(
            description="OKC ML",
            market_type=S.MarketType.MONEYLINE,
            side=S.Side.AWAY,
            accepted_decimal=Decimal("1.67"),
        ),
    ]


def make_fake_services(calls: list[tuple[str, Any]]) -> SimpleNamespace:
    """A FIXTURE services namespace with the contract signatures; records (name, ctx/args) for assertions."""

    def get_system_status(ctx: Any) -> S.SystemStatus:
        calls.append(("get_system_status", ctx))
        return system_status(ctx)

    def get_nba_slate(ctx: Any, date_local: str) -> S.SlateResponse:
        calls.append(("get_nba_slate", date_local))
        return S.SlateResponse(
            date_local=date_local, events=[], data_mode=S.DataMode.FIXTURE, warnings=["FIXTURE slate"]
        )

    def get_daily_budget(ctx: Any, date_local: str, proposed_stake_usd: Decimal | None) -> S.DailyBudget:
        calls.append(("get_daily_budget", (date_local, proposed_stake_usd)))
        budget = daily_budget(date_local)
        budget.proposed_stake_usd = proposed_stake_usd
        return budget

    def record_actual_bet(ctx: Any, ticket: S.ConfirmedTicketInput, idempotency_key: str) -> S.RecordResponse:
        calls.append(("record_actual_bet", (ctx.user_id, ticket, idempotency_key)))
        now = ctx.clock.now_utc()
        bet = S.ActualBet(
            bet_id="bet_fixture1",
            user_id=ctx.user_id,
            date_local="2026-10-20",
            candidate_id=ticket.candidate_id,
            book=ticket.book,
            ticket_ref=ticket.ticket_ref,
            legs=ticket.legs,
            external=ticket.external,
            accepted_combined_decimal=ticket.accepted_combined_decimal,
            stake_usd=ticket.stake_usd,
            placed_at_utc=ticket.placed_at_utc or now,
            source=ticket.source,
            idempotency_key=idempotency_key,
            payload_hash="deadbeef",
            created_at_utc=now,
        )
        return S.RecordResponse(
            bet=bet, budget=daily_budget("2026-10-20", ticket.stake_usd), replay=False, breach_flags=[]
        )

    def check_parlay_correlation(ctx: Any, candidate_id: str) -> S.CorrelationReport:
        raise NotFound("candidate not found", detail=candidate_id)

    def select_ticket(
        ctx: Any, candidate_id: str, stake_usd: Decimal, idempotency_key: str | None
    ) -> S.SelectResponse:
        raise RuntimeError("provider exploded while calling https://x/?apiKey=SECRET123VALUE")

    def build_providers(ctx: Any) -> str:
        return "providers-sentinel"

    return SimpleNamespace(
        RequestContext=RequestContext,
        get_system_status=get_system_status,
        get_nba_slate=get_nba_slate,
        get_daily_budget=get_daily_budget,
        record_actual_bet=record_actual_bet,
        check_parlay_correlation=check_parlay_correlation,
        select_ticket=select_ticket,
        build_providers=build_providers,
    )


@pytest.fixture
def calls() -> list[tuple[str, Any]]:
    return []


@pytest.fixture
def server(settings, db, clock, calls):
    return build_server(settings, db, clock, make_fake_services(calls))


def _text(result: Any) -> str:
    return "\n".join(block.text for block in result.content if getattr(block, "type", "") == "text")


async def test_initialize_and_list_tools_have_titles_annotations_and_output_schema(server):
    async with Client(server) as client:
        assert client.server_info is not None and client.server_info.name == "NBA Three-Leg Parlay Analyst"
        assert "never places bets" in (client.instructions or "")
        listing = await client.list_tools()
    tools = {tool.name: tool for tool in listing.tools}
    assert set(tools) == set(TOOL_NAMES)
    assert len(TOOL_NAMES) == 20
    for name, tool in tools.items():
        assert len(name) <= 64
        assert tool.title, name
        assert tool.description, name
        assert tool.annotations is not None, name
        for hint in ("read_only_hint", "destructive_hint", "idempotent_hint", "open_world_hint"):
            assert getattr(tool.annotations, hint) is not None, (name, hint)
        assert tool.output_schema is not None, name
        assert tool.input_schema.get("type") == "object"
        for forbidden in ("place", "shell", "sql", "delete"):
            assert forbidden not in name
    assert tools["get_system_status"].annotations.read_only_hint is True
    assert tools["build_three_leg_parlays"].annotations.read_only_hint is False
    assert tools["build_three_leg_parlays"].annotations.idempotent_hint is False
    assert tools["build_three_leg_parlays"].annotations.open_world_hint is True
    assert tools["select_ticket"].annotations.destructive_hint is True
    for name in ("select_ticket", "record_actual_bet", "reconcile_settlement"):
        assert (tools[name].meta or {}).get("anthropic/requiresUserInteraction") is True, name
    props = tools["record_actual_bet"].input_schema["properties"]
    assert "confirmed_ticket_fields" in props and "idempotency_key" in props
    assert "user_id" not in props


async def test_get_system_status_round_trips_structured_content(server, settings, db, calls):
    async with Client(server) as client:
        result = await client.call_tool("get_system_status", {})
    assert result.is_error is False
    payload = result.structured_content["result"]
    assert payload["app_version"] == settings.version
    assert payload["auth_mode"] == "none"
    assert payload["daily_cap_usd"] == "10.00"
    assert "AI-assisted" in payload["ai_disclosure"]
    name, ctx = calls[0]
    assert name == "get_system_status"
    assert ctx.user_id == settings.local_user_id
    assert ctx.providers == "providers-sentinel"
    assert ctx.db is db
    with db.engine.connect() as conn:
        row = (
            conn.execute(
                select(dbm.user_settings).where(dbm.user_settings.c.user_id == settings.local_user_id)
            )
            .mappings()
            .first()
        )
    assert row is not None and row["daily_cap_cents"] == 1000 and row["onboarding_complete"] == 0


async def test_record_actual_bet_round_trips_structured_content(server, calls):
    ticket = {
        "candidate_id": "cand_fixture",
        "ticket_ref": "HR-123",
        "legs": [leg.model_dump(mode="json") for leg in accepted_legs()],
        "accepted_combined_decimal": "6.10",
        "stake_usd": "10",
        "placed_at_utc": "2026-10-20T18:30:00Z",
        "source": "USER_CONFIRMATION",
    }
    async with Client(server) as client:
        result = await client.call_tool(
            "record_actual_bet", {"confirmed_ticket_fields": ticket, "idempotency_key": "key-1"}
        )
    assert result.is_error is False
    payload = result.structured_content["result"]
    assert payload["bet"]["stake_usd"] == "10.00"
    assert payload["bet"]["idempotency_key"] == "key-1"
    assert payload["bet"]["legs"][0]["description"] == "DET +3.5"
    assert payload["budget"]["remaining_usd"] == "0.00"
    assert payload["replay"] is False
    name, (user_id, parsed, key) = calls[-1]
    assert name == "record_actual_bet" and key == "key-1"
    assert isinstance(parsed, S.ConfirmedTicketInput) and parsed.stake_usd == Decimal("10.00")
    assert parsed.placed_at_utc == datetime(2026, 10, 20, 18, 30, tzinfo=UTC)


async def test_service_error_becomes_tool_error_without_traceback(server):
    async with Client(server) as client:
        result = await client.call_tool("check_parlay_correlation", {"candidate_id": "cand_missing"})
    assert result.is_error is False
    payload = result.structured_content["result"]
    assert payload["error"] == "candidate not found"
    assert payload["reason_codes"] == ["NOT_FOUND"]
    assert payload["detail"] == "cand_missing"
    text = _text(result)
    assert "Traceback" not in text and 'File "' not in text


async def test_unexpected_exception_is_redacted_tool_error(server):
    async with Client(server) as client:
        result = await client.call_tool("select_ticket", {"candidate_id": "cand_x", "stake_usd": "10"})
    payload = result.structured_content["result"]
    assert payload["reason_codes"] == ["PROVIDER_ERROR"]
    assert payload["error"] == "internal error"
    assert "SECRET123VALUE" not in _text(result)
    assert "Traceback" not in _text(result)


async def test_date_local_defaults_to_today_in_eastern_time(server, calls, clock):
    # 2026-10-20 19:00Z is 15:00 ET on 2026-10-20; 03:30Z on 10-21 is still 23:30 ET on 10-20.
    async with Client(server) as client:
        await client.call_tool("get_nba_slate", {})
        clock.set(datetime(2026, 10, 21, 3, 30, tzinfo=UTC))
        await client.call_tool("get_nba_slate", {})
        await client.call_tool("get_nba_slate", {"date_local": "2026-10-25"})
        bad = await client.call_tool("get_nba_slate", {"date_local": "next tuesday"})
    dates = [args for name, args in calls if name == "get_nba_slate"]
    assert dates == ["2026-10-20", "2026-10-20", "2026-10-25"]
    assert bad.is_error is True
    assert "Traceback" not in _text(bad)


async def test_missing_required_argument_is_rejected_cleanly(server):
    async with Client(server) as client:
        result = await client.call_tool(
            "record_actual_bet", {"confirmed_ticket_fields": {"legs": [], "stake_usd": "1"}}
        )
    assert result.is_error is True
    assert "Traceback" not in _text(result)


async def test_budget_decimal_arguments_round_trip(server, calls):
    async with Client(server) as client:
        result = await client.call_tool("get_daily_budget", {"proposed_stake_usd": 7.5})
    payload = result.structured_content["result"]
    assert payload["proposed_stake_usd"] == "7.50"
    name, (date_local, proposed) = calls[-1]
    assert date_local == "2026-10-20" and proposed == Decimal("7.5")


def test_make_request_context_positional_fallback(settings, db, clock):
    class Positional:
        def __init__(self, user_id, clock, db, settings, providers):  # noqa: ANN001
            self.user_id, self.clock, self.db, self.settings, self.providers = (
                user_id,
                clock,
                db,
                settings,
                providers,
            )

    svc = SimpleNamespace(RequestContext=Positional)
    ctx = make_request_context(svc, user_id="u1", clock=clock, db=db, settings=settings)
    assert ctx.user_id == "u1" and ctx.providers is None and ctx.clock is clock


def test_hosted_server_carries_auth_settings(tmp_path, db, clock):
    from hardrock_nba_parlay.config import Settings

    hosted = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'h.db'}",
        auth_mode="builtin_oauth",
        public_url="https://parlay.example.test",
        secret_key="unit-test-secret-key",
    )
    server = build_server(hosted, db, clock, make_fake_services([]))
    assert server.settings.auth is not None
    assert str(server.settings.auth.resource_server_url) == "https://parlay.example.test/mcp"
    assert server.settings.auth.required_scopes == ["parlay"]
    assert server.settings.auth.client_registration_options.enabled is True


def test_token_expiry_math_does_not_depend_on_wall_clock():
    assert NOW + timedelta(hours=1) == datetime(2026, 10, 20, 20, 0, tzinfo=UTC)


# ---- error conversion: redaction, reason codes, arity, and internal errors ----


def _manual_leg(game: str, side: str = "HOME") -> dict[str, Any]:
    return {"game": game, "market": "MONEYLINE", "side": side, "odds_american": -110}


def _payload(result: Any) -> dict[str, Any]:
    return result.structured_content["result"]


async def test_service_error_message_and_detail_are_redacted(settings, db, clock):
    from hardrock_nba_parlay.errors import ProviderError

    def get_nba_slate(ctx: Any, date_local: str) -> S.SlateResponse:
        raise ProviderError(
            "provider rejected Bearer SECRET123VALUE",
            ["PROVIDER_AUTH_FAILED"],
            detail="GET https://api.the-odds-api.com/v4/sports?apiKey=SECRET123VALUE -> 401 " + "x" * 2000,
        )

    server = build_server(
        settings, db, clock, SimpleNamespace(RequestContext=RequestContext, get_nba_slate=get_nba_slate)
    )
    async with Client(server) as client:
        result = await client.call_tool("get_nba_slate", {})
    payload = _payload(result)
    assert payload["reason_codes"] == ["PROVIDER_AUTH_FAILED"]
    assert "SECRET123VALUE" not in _text(result)
    assert "[REDACTED]" in payload["error"] and "[REDACTED]" in payload["detail"]
    assert len(payload["detail"]) <= 1000 and payload["detail"].endswith("...")


async def test_analyze_my_parlay_schema_and_arity(settings, db, clock):
    received: list[int] = []

    def analyze_my_parlay(ctx: Any, selections: list[Any], combined: Any, date_local: str) -> S.Candidate:
        received.append(len(selections))
        raise NotFound("reached services", detail=date_local)

    server = build_server(
        settings,
        db,
        clock,
        SimpleNamespace(RequestContext=RequestContext, analyze_my_parlay=analyze_my_parlay),
    )
    async with Client(server) as client:
        listing = await client.list_tools()
        schema = {t.name: t for t in listing.tools}["analyze_my_parlay"].input_schema
        items = schema["properties"]["three_selections"]
        assert items["minItems"] == 3 and items["maxItems"] == 3
        for count in (0, 2, 4):
            legs = [_manual_leg(f"G{i} @ H{i}") for i in range(count)]
            result = await client.call_tool("analyze_my_parlay", {"three_selections": legs})
            assert result.is_error or "NOT_THREE_LEGS" in _payload(result)["reason_codes"], count
            assert "Traceback" not in _text(result)
        assert received == []
        three = await client.call_tool(
            "analyze_my_parlay",
            {
                "three_selections": [
                    _manual_leg("BOS @ DET"),
                    _manual_leg("PHI @ NYK"),
                    _manual_leg("OKC @ SAS"),
                ]
            },
        )
    assert received == [3]
    assert _payload(three)["error"] == "reached services" and _payload(three)["detail"] == "2026-10-20"


async def test_record_actual_bet_requires_three_legs_unless_external(settings, db, clock, calls):
    server = build_server(settings, db, clock, make_fake_services(calls))
    two = [leg.model_dump(mode="json") for leg in accepted_legs()[:2]]
    async with Client(server) as client:
        short = await client.call_tool(
            "record_actual_bet",
            {"confirmed_ticket_fields": {"legs": two, "stake_usd": "5"}, "idempotency_key": "k-short"},
        )
        assert _payload(short)["reason_codes"] == ["NOT_THREE_LEGS"]
        empty = await client.call_tool(
            "record_actual_bet",
            {"confirmed_ticket_fields": {"legs": [], "stake_usd": "5"}, "idempotency_key": "k-empty"},
        )
        assert _payload(empty)["reason_codes"] == ["INVALID_INPUT"]
        assert [name for name, _ in calls if name == "record_actual_bet"] == []
        external = await client.call_tool(
            "record_actual_bet",
            {
                "confirmed_ticket_fields": {"legs": two, "stake_usd": "5", "external": True},
                "idempotency_key": "k-ext",
            },
        )
    assert external.is_error is False and _payload(external)["bet"]["external"] is True
    assert [name for name, _ in calls if name == "record_actual_bet"] == ["record_actual_bet"]


async def test_schema_reason_codes_from_services_validation_errors(settings, db, clock):
    def check_parlay_correlation(ctx: Any, candidate_id: str) -> S.CorrelationReport:
        S.ManualSelectionInput(game=candidate_id, market="MONEYLINE", side="HOME")  # no odds at all
        raise AssertionError("unreachable")

    server = build_server(
        settings,
        db,
        clock,
        SimpleNamespace(RequestContext=RequestContext, check_parlay_correlation=check_parlay_correlation),
    )
    async with Client(server) as client:
        result = await client.call_tool("check_parlay_correlation", {"candidate_id": "apiKey=SECRET123VALUE"})
    payload = _payload(result)
    assert payload["reason_codes"] == ["QUOTE_FIELDS_MISSING", "INVALID_INPUT"]
    assert payload["error"] == "invalid input"
    assert "provide odds_american or odds_decimal" in payload["detail"]
    assert "SECRET123VALUE" not in _text(result)


def test_validation_helpers_keep_field_paths_and_fall_back_to_invalid_input():
    from pydantic import ValidationError

    from hardrock_nba_parlay.mcp_server import reason_codes_from_validation, tool_error_from_validation

    try:
        S.ConfirmedTicketInput.model_validate({"legs": [], "stake_usd": "x"})
    except ValidationError as exc:
        assert reason_codes_from_validation(exc) == ["INVALID_INPUT"]
        err = tool_error_from_validation(exc)
        assert err.reason_codes == ["INVALID_INPUT"] and err.detail is not None and "stake_usd" in err.detail
    try:
        S.ThreeLegTicket(legs=[])
    except ValidationError as exc:
        assert reason_codes_from_validation(exc) == ["NOT_THREE_LEGS", "INVALID_INPUT"]
        assert "NOT_THREE_LEGS" in (tool_error_from_validation(exc).detail or "")


async def test_services_type_error_is_an_internal_error_not_invalid_input(settings, db, clock):
    def get_injury_context(ctx: Any) -> S.InjuryResponse:  # drifted signature
        raise AssertionError("unreachable")

    def get_nba_slate(ctx: Any, date_local: str) -> S.SlateResponse:
        raise ValueError("date_local apiKey=SECRET123VALUE is not on the schedule")

    server = build_server(
        settings,
        db,
        clock,
        SimpleNamespace(
            RequestContext=RequestContext, get_injury_context=get_injury_context, get_nba_slate=get_nba_slate
        ),
    )
    async with Client(server) as client:
        drift = await client.call_tool("get_injury_context", {"event_id": "fixture:BOS@DET"})
        value = await client.call_tool("get_nba_slate", {})
    assert _payload(drift) == {
        "error": "internal error",
        "reason_codes": ["PROVIDER_ERROR"],
        "detail": "TypeError",
    }
    assert _payload(value)["reason_codes"] == ["INVALID_INPUT"]
    assert "SECRET123VALUE" not in _text(value) and "[REDACTED]" in _payload(value)["detail"]
