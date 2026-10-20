"""Adversarial review of the server module (mcp_server.py, auth.py, web.py, cli.py, dashboard.py).

Every test here reproduces a suspected defect against the current code (it is expected to FAIL until the
owner fixes it), except tests explicitly marked "documents correct behaviour". All services are FIXTURE
fakes; nothing touches the network or a real ledger.
"""

from __future__ import annotations

import json
import subprocess
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from mcp.client import Client
from typer.testing import CliRunner

from hardrock_nba_parlay import cli
from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.config import FixedClock, Settings
from hardrock_nba_parlay.db import open_database
from hardrock_nba_parlay.errors import NotFound, ProviderError
from hardrock_nba_parlay.mcp_server import build_server
from hardrock_nba_parlay.web import create_app, run_http

BASE = "http://localhost"
SECRET_KEY = "review-test-secret-key-not-for-production"
LEAKED_VALUE = "SECRET123VALUE"


@dataclass
class RequestContext:
    user_id: str
    clock: Any
    db: Any
    settings: Any
    providers: Any = None


def _text(result: Any) -> str:
    return "\n".join(block.text for block in result.content if getattr(block, "type", "") == "text")


def _payload(result: Any) -> dict[str, Any]:
    return result.structured_content["result"]


def _slate(ctx: Any, date_local: str) -> S.SlateResponse:
    return S.SlateResponse(date_local=date_local, events=[], data_mode=S.DataMode.FIXTURE)


# --------------------------------------------------------------------------------------
# 1. Secrets leak through error text (CLI `secret set`, ServiceError detail in MCP and CLI)
# --------------------------------------------------------------------------------------


def test_secret_set_keychain_failure_does_not_print_the_secret(monkeypatch, settings, db, clock):
    """`hrnba secret set` on macOS passes the value as a `security` argv argument; when `security` fails,
    CalledProcessError's message repeats the whole argv (including the secret) and the CLI prints it."""
    monkeypatch.setattr(cli, "_load_settings", lambda: settings)
    monkeypatch.setattr(cli, "_open_db", lambda _settings: db)
    monkeypatch.setattr(cli, "_clock", lambda: clock)
    monkeypatch.setattr(cli.sys, "platform", "darwin")
    secret_value = "kc-secret-value-ABC123"
    monkeypatch.setattr(cli, "_getpass", lambda prompt: secret_value)

    def failing_security(cmd: list[str], **kwargs: Any) -> None:
        raise subprocess.CalledProcessError(1, cmd, output=b"", stderr=b"keychain locked")

    monkeypatch.setattr(cli.subprocess, "run", failing_security)
    result = CliRunner().invoke(cli.app, ["secret", "set", "odds_api_key"])
    assert result.exit_code != 0
    assert secret_value not in result.output, result.output


async def test_service_error_detail_is_redacted_in_tool_results(settings, db, clock):
    """A ServiceError raised by services is passed to the client verbatim (error + detail) without
    config.redact; a provider error that quotes the request URL leaks the API key to the model."""

    def get_nba_slate(ctx: Any, date_local: str) -> S.SlateResponse:
        raise ProviderError(
            "provider rejected the request",
            ["PROVIDER_AUTH_FAILED"],
            detail=f"GET https://api.the-odds-api.com/v4/sports?apiKey={LEAKED_VALUE} -> 401",
            status_code=401,
        )

    server = build_server(
        settings, db, clock, SimpleNamespace(RequestContext=RequestContext, get_nba_slate=get_nba_slate)
    )
    async with Client(server) as client:
        result = await client.call_tool("get_nba_slate", {})
    assert _payload(result)["reason_codes"] == ["PROVIDER_AUTH_FAILED"]
    assert LEAKED_VALUE not in _text(result)
    assert LEAKED_VALUE not in json.dumps(result.structured_content)


def test_service_error_detail_is_redacted_in_cli_output(monkeypatch, settings, db, clock):
    def get_nba_slate(ctx: Any, date_local: str) -> S.SlateResponse:
        raise ProviderError(
            "provider rejected the request",
            ["PROVIDER_AUTH_FAILED"],
            detail=f"GET https://api.the-odds-api.com/v4/sports?apiKey={LEAKED_VALUE} -> 401",
        )

    fake = SimpleNamespace(RequestContext=RequestContext, get_nba_slate=get_nba_slate)
    monkeypatch.setattr(cli, "_services", lambda: fake)
    monkeypatch.setattr(cli, "_load_settings", lambda: settings)
    monkeypatch.setattr(cli, "_open_db", lambda _settings: db)
    monkeypatch.setattr(cli, "_clock", lambda: clock)
    for args in (["slate"], ["--json", "slate"]):
        result = CliRunner().invoke(cli.app, args)
        assert result.exit_code == 1
        assert "PROVIDER_AUTH_FAILED" in result.output
        assert LEAKED_VALUE not in result.output, result.output


# --------------------------------------------------------------------------------------
# 2. OAuth: open DCR + no consent page = token for any attacker-registered client
# --------------------------------------------------------------------------------------


@pytest.fixture
def hosted_settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'review.db'}",
        auth_mode="builtin_oauth",
        public_url=BASE,
        secret_key=SECRET_KEY,
        allow_fixture_ledger=True,
    )


@asynccontextmanager
async def running(hosted_settings: Settings):
    database = open_database(hosted_settings.effective_database_url, allow_fixture_ledger=True)
    clock = FixedClock(datetime.now(UTC))
    fake = SimpleNamespace(RequestContext=RequestContext, get_nba_slate=_slate)
    app = create_app(hosted_settings, database, clock, fake, json_response=True)
    try:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url=BASE) as http:
                yield http
    finally:
        database.dispose()


async def test_login_page_names_the_client_and_destination_or_registration_refuses_foreign_redirects(
    hosted_settings,
):
    """Anyone can register a client (DCR) with ANY https redirect URI, and /login?req=... shows a bare
    sign-in form that names neither the requesting client nor where the browser will be sent. A victim
    who follows an attacker's link, on the genuine domain, types the real password and is redirected to
    the attacker's redirect_uri with a code bound to the attacker's PKCE challenge: full ledger takeover.
    Either registration must refuse redirect URIs outside Claude's documented set (claude.ai callback and
    loopback) or the login/signup page must show the client name and destination (a consent step)."""
    async with running(hosted_settings) as http:
        await http.post(
            "/signup",
            data={
                "email": "victim@example.com",
                "password": "correct horse battery",
                "password2": "correct horse battery",
                "age_attest": "yes",
            },
        )
        registration = await http.post(
            "/register",
            json={
                "redirect_uris": ["https://attacker.test/cb"],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "client_name": "Claude Parlay Helper (fake)",
            },
        )
        if registration.status_code != 201:
            return  # registration refuses foreign redirect URIs: acceptable mitigation
        client_id = registration.json()["client_id"]
        authorize = await http.get(
            "/authorize",
            params={
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": "https://attacker.test/cb",
                "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
                "code_challenge_method": "S256",
                "state": "s",
                "scope": "parlay",
            },
        )
        assert authorize.status_code == 302
        login_url = httpx.URL(authorize.headers["location"])
        page = await http.get(str(login_url))
        assert page.status_code == 200
        req = login_url.params["req"]
        done = await http.post(
            "/login", data={"req": req, "email": "victim@example.com", "password": "correct horse battery"}
        )
        location = done.headers.get("location", "")
        assert "attacker.test" in page.text or "fake" in page.text, (
            "login page shows neither the client name nor the redirect destination; after login the "
            f"victim's authorization code went to {location!r}"
        )


# --------------------------------------------------------------------------------------
# 3. Tool boundary: exactly three legs, reason codes, and misclassified failures
# --------------------------------------------------------------------------------------


def _manual_leg(game: str, side: S.Side = S.Side.HOME) -> dict[str, Any]:
    return {"game": game, "market": "MONEYLINE", "side": side.value, "odds_american": -110}


async def test_analyze_my_parlay_enforces_exactly_three_selections_at_the_tool_boundary(settings, db, clock):
    """The product rule 'exactly three distinct selections, validated in code' is enforced by the CLI
    (import-selections) but not by the MCP tool: the input schema has no minItems/maxItems and a two-leg
    (or four-leg) slip is forwarded to services unchanged."""
    calls: list[int] = []

    def analyze_my_parlay(ctx: Any, selections: list[Any], combined: Any, date_local: str) -> S.Candidate:
        calls.append(len(selections))
        raise NotFound("services were called", detail=str(len(selections)))

    server = build_server(
        settings,
        db,
        clock,
        SimpleNamespace(RequestContext=RequestContext, analyze_my_parlay=analyze_my_parlay),
    )
    async with Client(server) as client:
        listing = await client.list_tools()
        schema = {t.name: t for t in listing.tools}["analyze_my_parlay"].input_schema
        two = await client.call_tool(
            "analyze_my_parlay",
            {"three_selections": [_manual_leg("BOS @ DET"), _manual_leg("PHI @ NYK")]},
        )
    items = schema["properties"]["three_selections"]
    assert items.get("minItems") == 3 and items.get("maxItems") == 3, items
    assert calls == [], "services were called with a non-three-leg slip"
    assert two.is_error or "NOT_THREE_LEGS" in _payload(two)["reason_codes"]


async def test_schema_reason_codes_survive_validation_errors(settings, db, clock):
    """schemas.py deliberately prefixes validator messages with reason codes (NOT_THREE_LEGS,
    DUPLICATE_SELECTION, QUOTE_FIELDS_MISSING, QUOTE_SIGN_AMBIGUOUS). The MCP layer collapses every
    pydantic ValidationError into INVALID_INPUT with only field names, so the code is lost."""

    def check_parlay_correlation(ctx: Any, candidate_id: str) -> S.CorrelationReport:
        S.ThreeLegTicket(legs=[])  # raises ValidationError("... NOT_THREE_LEGS: ...")
        raise AssertionError("unreachable")

    server = build_server(
        settings,
        db,
        clock,
        SimpleNamespace(RequestContext=RequestContext, check_parlay_correlation=check_parlay_correlation),
    )
    async with Client(server) as client:
        result = await client.call_tool("check_parlay_correlation", {"candidate_id": "cand_x"})
    payload = _payload(result)
    assert "NOT_THREE_LEGS" in payload["reason_codes"], payload


async def test_services_signature_mismatch_is_not_blamed_on_the_caller(settings, db, clock):
    """A TypeError raised when the server calls services with a signature the services module does not
    accept (a contract drift, not a user mistake) is reported as 'invalid input' / INVALID_INPUT, which
    tells the model to keep changing its arguments instead of surfacing an internal error."""

    def get_nba_slate(ctx: Any) -> S.SlateResponse:  # drifted signature: no date_local
        raise AssertionError("unreachable")

    server = build_server(
        settings, db, clock, SimpleNamespace(RequestContext=RequestContext, get_nba_slate=get_nba_slate)
    )
    async with Client(server) as client:
        result = await client.call_tool("get_nba_slate", {"date_local": "2026-10-20"})
    payload = _payload(result)
    assert payload["reason_codes"] != ["INVALID_INPUT"], payload
    assert payload["error"] != "invalid input", payload


# --------------------------------------------------------------------------------------
# 4. Unauthenticated HTTP transport bound to a public interface
# --------------------------------------------------------------------------------------


def test_run_http_refuses_unauthenticated_mode_on_a_non_loopback_host(tmp_path, monkeypatch):
    """`hrnba serve --transport http --host 0.0.0.0` with the default auth_mode ("none") serves the owner's
    ledger at /mcp to the whole network with no bearer check at all (identity = local_user_id for every
    caller). run_http should refuse a non-loopback bind unless auth_mode is builtin_oauth."""
    import uvicorn

    started: list[dict[str, Any]] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: started.append(kw))
    settings = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'open.db'}",
        auth_mode="none",
        host="0.0.0.0",
        port=8000,
    )
    with pytest.raises((ValueError, RuntimeError, SystemExit)):
        run_http(settings)
    assert started == []


# --------------------------------------------------------------------------------------
# Documented correct behaviour (passing): ET day defaulting across the DST end on 2026-11-01
# --------------------------------------------------------------------------------------


async def test_date_local_defaults_follow_eastern_time_across_dst_end(settings, db, clock):
    """Documents correct behaviour (passes): the tool's default date is the America/New_York calendar day,
    including the 25-hour day on 2026-11-01 when EDT (UTC-4) becomes EST (UTC-5)."""
    seen: list[str] = []

    def get_nba_slate(ctx: Any, date_local: str) -> S.SlateResponse:
        seen.append(date_local)
        return _slate(ctx, date_local)

    server = build_server(
        settings, db, clock, SimpleNamespace(RequestContext=RequestContext, get_nba_slate=get_nba_slate)
    )
    async with Client(server) as client:
        clock.set(datetime(2026, 11, 1, 3, 59, tzinfo=UTC))  # 23:59 EDT on 10-31
        await client.call_tool("get_nba_slate", {})
        clock.set(datetime(2026, 11, 1, 5, 30, tzinfo=UTC))  # 01:30 EDT on 11-01 (first 1:30)
        await client.call_tool("get_nba_slate", {})
        clock.set(datetime(2026, 11, 1, 6, 30, tzinfo=UTC))  # 01:30 EST on 11-01 (second 1:30)
        await client.call_tool("get_nba_slate", {})
        clock.set(datetime(2026, 11, 2, 4, 59, tzinfo=UTC))  # 23:59 EST on 11-01
        await client.call_tool("get_nba_slate", {})
        clock.set(datetime(2026, 11, 2, 5, 0, tzinfo=UTC))  # 00:00 EST on 11-02
        await client.call_tool("get_nba_slate", {})
    assert seen == ["2026-10-31", "2026-11-01", "2026-11-01", "2026-11-01", "2026-11-02"]
    assert Decimal("1") == Decimal(1)
