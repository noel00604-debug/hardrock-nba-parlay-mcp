"""Hosted app tests over httpx ASGITransport: OAuth discovery, DCR, PKCE login flow, bearer /mcp calls, account pages.

No network. The services namespace is a FIXTURE fake that records the user id it was called with.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.config import FixedClock, Settings
from hardrock_nba_parlay.db import open_database
from hardrock_nba_parlay.web import DELETE_CONFIRMATION, create_app, transport_security_for

# The SDK only allows http issuers on loopback hosts, so the hosted test server lives at http://localhost.
BASE = "http://localhost"
SECRET = "web-test-secret-key-not-for-production"
CLAUDE_CALLBACK = "https://claude.ai/api/mcp/auth_callback"
MCP_HEADERS = {"accept": "application/json, text/event-stream", "content-type": "application/json"}


@dataclass
class RequestContext:
    user_id: str
    clock: Any
    db: Any
    settings: Any
    providers: Any = None


def make_fake(seen: list[str]) -> SimpleNamespace:
    def get_system_status(ctx: Any) -> S.SystemStatus:
        seen.append(ctx.user_id)
        return S.SystemStatus(
            app_version="0.1.0",
            now_utc=ctx.clock.now_utc(),
            now_display="x",
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
        )

    def get_daily_budget(ctx: Any, date_local: str, proposed: Decimal | None) -> S.DailyBudget:
        seen.append(ctx.user_id)
        return S.DailyBudget(
            date_local=date_local,
            cap_usd=Decimal("10"),
            recorded_stake_usd=Decimal("0"),
            reserved_stake_usd=Decimal("0"),
            remaining_usd=Decimal("10"),
            raw_remaining_usd=Decimal("10"),
        )

    return SimpleNamespace(
        RequestContext=RequestContext, get_system_status=get_system_status, get_daily_budget=get_daily_budget
    )


@pytest.fixture
def hosted_settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'web.db'}",
        auth_mode="builtin_oauth",
        public_url=BASE,
        secret_key=SECRET,
        odds_api_key="ODDSKEY-SHOULD-NEVER-APPEAR-1234567890",
        allow_fixture_ledger=True,
    )


@pytest.fixture
def seen() -> list[str]:
    return []


@asynccontextmanager
async def running(hosted_settings: Settings, seen: list[str]):
    """The hosted app with its lifespan entered, reachable through an httpx client (one task: anyio task groups
    cannot be entered and exited in different tasks, which is what an async pytest fixture would do)."""
    database = open_database(hosted_settings.effective_database_url, allow_fixture_ledger=True)
    clock = FixedClock(datetime.now(UTC))  # the SDK compares token expiry with wall-clock time
    app = create_app(hosted_settings, database, clock, make_fake(seen), json_response=True)
    try:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url=BASE) as http:
                http.hrnba_app = app  # type: ignore[attr-defined]
                yield http
    finally:
        database.dispose()


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


async def signup(
    http: httpx.AsyncClient, email: str, password: str = "correct horse battery"
) -> httpx.Response:
    return await http.post(
        "/signup", data={"email": email, "password": password, "password2": password, "age_attest": "yes"}
    )


async def register(http: httpx.AsyncClient, redirect_uris: list[str] | None = None) -> str:
    response = await http.post(
        "/register",
        json={
            "redirect_uris": redirect_uris or [CLAUDE_CALLBACK, "http://localhost/callback"],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "client_name": "Claude (test)",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["client_id"]


async def oauth_login(
    http: httpx.AsyncClient, client_id: str, email: str, password: str, redirect_uri: str = CLAUDE_CALLBACK
) -> dict[str, Any]:
    """Run /authorize -> /login -> /token for an already signed-up user. Returns the token response JSON."""
    verifier, challenge = pkce()
    state = secrets.token_hex(8)
    browser = httpx.AsyncClient(
        transport=http._transport, base_url=BASE
    )  # a separate cookie jar, like a browser
    async with browser:
        authorize = await browser.get(
            "/authorize",
            params={
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": state,
                "scope": "parlay",
                "resource": f"{BASE}/mcp",
            },
        )
        assert authorize.status_code == 302, authorize.text
        login_url = httpx.URL(authorize.headers["location"])
        assert login_url.path == "/login"
        req = login_url.params["req"]
        page = await browser.get(str(login_url))
        assert page.status_code == 200 and f'name="req" value="{req}"' in page.text
        done = await browser.post("/login", data={"req": req, "email": email, "password": password})
        assert done.status_code == 302, done.text
        callback = httpx.URL(done.headers["location"])
        assert str(callback).startswith(redirect_uri)
        assert callback.params["state"] == state
        code = callback.params["code"]
    token = await http.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
            "resource": f"{BASE}/mcp",
        },
    )
    assert token.status_code == 200, token.text
    return token.json()


async def mcp_session(http: httpx.AsyncClient, access_token: str) -> dict[str, str]:
    headers = {**MCP_HEADERS, "authorization": f"Bearer {access_token}"}
    init = await http.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            },
        },
        headers=headers,
    )
    assert init.status_code == 200, init.text
    assert init.json()["result"]["serverInfo"]["name"] == "NBA Three-Leg Parlay Analyst"
    headers["mcp-session-id"] = init.headers["mcp-session-id"]
    ack = await http.post(
        "/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=headers
    )
    assert ack.status_code == 202
    return headers


async def call_tool(
    http: httpx.AsyncClient, headers: dict[str, str], name: str, arguments: dict[str, Any] | None = None
) -> dict[str, Any]:
    response = await http.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]


# ---- discovery and the unauthenticated 401 ----


async def test_unauthenticated_mcp_gets_401_with_resource_metadata(hosted_settings, seen):
    async with running(hosted_settings, seen) as client:
        response = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            headers=MCP_HEADERS,
        )
        assert response.status_code == 401
        www = response.headers["www-authenticate"]
        assert www.startswith("Bearer ")
        assert f'resource_metadata="{BASE}/.well-known/oauth-protected-resource/mcp"' in www
        garbage = await client.post(
            "/mcp", json={}, headers={**MCP_HEADERS, "authorization": "Bearer not-a-real-token"}
        )
        assert garbage.status_code == 401
        assert "resource_metadata" in garbage.headers["www-authenticate"]


async def test_discovery_metadata(hosted_settings, seen):
    async with running(hosted_settings, seen) as client:
        prm = await client.get("/.well-known/oauth-protected-resource/mcp")
        assert prm.status_code == 200
        assert prm.json()["resource"] == f"{BASE}/mcp"
        assert prm.json()["authorization_servers"][0] == BASE
        assert prm.json()["scopes_supported"] == ["parlay"]
        meta = await client.get("/.well-known/oauth-authorization-server")
        assert meta.status_code == 200
        body = meta.json()
        assert body["issuer"] == BASE
        assert body["registration_endpoint"] == f"{BASE}/register"
        assert body["token_endpoint"] == f"{BASE}/token"
        assert body["authorization_endpoint"] == f"{BASE}/authorize"
        assert body["revocation_endpoint"] == f"{BASE}/revoke"
        assert "S256" in body["code_challenge_methods_supported"]
        assert "refresh_token" in body["grant_types_supported"]


# ---- the full flow ----


async def test_full_oauth_flow_and_bearer_tool_call(seen, hosted_settings):
    async with running(hosted_settings, seen) as client:
        created = await signup(client, "Alice@Example.com")
        assert created.status_code == 303 and created.headers["location"] == "/account"
        account = await client.get("/account")
        assert account.status_code == 200 and "usr_" in account.text and "Download my data" in account.text

        client_id = await register(client)
        token = await oauth_login(client, client_id, "alice@example.com", "correct horse battery")
        assert token["token_type"] == "Bearer" and token["scope"] == "parlay" and token["expires_in"] == 3600
        assert token["refresh_token"]

        headers = await mcp_session(client, token["access_token"])
        result = await call_tool(client, headers, "get_system_status")
        status = result["structuredContent"]["result"]
        assert status["auth_mode"] == "builtin_oauth"
        assert len(seen) == 1 and seen[0].startswith("usr_")
        assert status["user_id_masked"] == seen[0][:4] + "***"
        # the authenticated subject is the signed-up user's id, never anything from arguments
        bundle = client.hrnba_app.state.oauth_provider.db.export_user(seen[0])
        assert bundle["user_settings"][0]["user_id"] == seen[0]
        text = json.dumps(result)
        for secret_text in (
            SECRET,
            "ODDSKEY-SHOULD-NEVER-APPEAR",
            token["access_token"],
            token["refresh_token"],
        ):
            assert secret_text not in text


async def test_loopback_redirect_with_port_like_claude_code(seen, hosted_settings):
    async with running(hosted_settings, seen) as client:
        await signup(client, "code@example.com")
        client_id = await register(client, ["http://localhost/callback", "http://127.0.0.1/callback"])
        token = await oauth_login(
            client,
            client_id,
            "code@example.com",
            "correct horse battery",
            redirect_uri="http://localhost:3118/callback",
        )
        headers = await mcp_session(client, token["access_token"])
        await call_tool(client, headers, "get_daily_budget", {})
        assert len(seen) == 1


async def test_two_users_are_isolated(seen, hosted_settings):
    async with running(hosted_settings, seen) as client:
        await signup(client, "one@example.com")
        await signup(client, "two@example.com")
        client_id = await register(client)
        tok1 = await oauth_login(client, client_id, "one@example.com", "correct horse battery")
        tok2 = await oauth_login(client, client_id, "two@example.com", "correct horse battery")
        h1 = await mcp_session(client, tok1["access_token"])
        h2 = await mcp_session(client, tok2["access_token"])
        await call_tool(client, h1, "get_system_status")
        await call_tool(client, h2, "get_system_status")
        await call_tool(client, h1, "get_system_status")
        assert len(seen) == 3 and seen[0] == seen[2] and seen[0] != seen[1]
        # a session bound to user one cannot be driven with user two's token
        mixed = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {"name": "get_system_status", "arguments": {}},
            },
            headers={**h1, "authorization": h2["authorization"]},
        )
        assert mixed.status_code in (401, 403, 404)
        assert len(seen) == 3


async def test_wrong_code_verifier_and_wrong_redirect_are_rejected(hosted_settings, seen):
    async with running(hosted_settings, seen) as client:
        await signup(client, "pkce@example.com")
        client_id = await register(client)
        verifier, challenge = pkce()
        authorize = await client.get(
            "/authorize",
            params={
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": CLAUDE_CALLBACK,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "s1",
                "scope": "parlay",
            },
        )
        req = httpx.URL(authorize.headers["location"]).params["req"]
        done = await client.post(
            "/login", data={"req": req, "email": "pkce@example.com", "password": "correct horse battery"}
        )
        code = httpx.URL(done.headers["location"]).params["code"]
        bad = await client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "redirect_uri": CLAUDE_CALLBACK,
                "code_verifier": "x" + verifier,
            },
        )
        assert bad.status_code == 400 and bad.json()["error"] == "invalid_grant"
        good = await client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "redirect_uri": CLAUDE_CALLBACK,
                "code_verifier": verifier,
            },
        )
        assert good.status_code == 200
        replay = await client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "redirect_uri": CLAUDE_CALLBACK,
                "code_verifier": verifier,
            },
        )
        assert replay.status_code == 400 and replay.json()["error"] == "invalid_grant"
        unregistered = await client.get(
            "/authorize",
            params={
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": "https://attacker.test/cb",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "s2",
            },
        )
        assert unregistered.status_code == 400
        assert "attacker.test" not in unregistered.headers.get("location", "")


async def test_refresh_rotates_and_revoke_returns_401(seen, hosted_settings):
    async with running(hosted_settings, seen) as client:
        await signup(client, "rot@example.com")
        client_id = await register(client)
        first = await oauth_login(client, client_id, "rot@example.com", "correct horse battery")
        refreshed = await client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": first["refresh_token"],
                "client_id": client_id,
            },
        )
        assert refreshed.status_code == 200
        second = refreshed.json()
        assert (
            second["access_token"] != first["access_token"]
            and second["refresh_token"] != first["refresh_token"]
        )
        dead = await client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": first["refresh_token"],
                "client_id": client_id,
            },
        )
        assert dead.status_code == 400 and dead.json()["error"] == "invalid_grant"

        headers = await mcp_session(client, second["access_token"])
        await call_tool(client, headers, "get_system_status")
        revoked = await client.post(
            "/revoke", data={"token": second["access_token"], "client_id": client_id, "client_secret": ""}
        )
        assert revoked.status_code == 200
        after = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "get_system_status", "arguments": {}},
            },
            headers=headers,
        )
        assert after.status_code == 401 and "resource_metadata" in after.headers["www-authenticate"]
        gone = await client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": second["refresh_token"],
                "client_id": client_id,
            },
        )
        assert gone.status_code == 400
        assert len(seen) == 1


async def test_login_rate_limit_after_ten_bad_attempts(hosted_settings, seen):
    async with running(hosted_settings, seen) as client:
        await signup(client, "limit@example.com")
        for _ in range(10):
            bad = await client.post(
                "/login", data={"email": "limit@example.com", "password": "nope-nope-nope"}
            )
            assert bad.status_code == 401
            assert "not recognized" in bad.text and "nope-nope" not in bad.text
        limited = await client.post(
            "/login", data={"email": "limit@example.com", "password": "correct horse battery"}
        )
        assert limited.status_code == 429


async def test_signup_validation(hosted_settings, seen):
    async with running(hosted_settings, seen) as client:
        mismatch = await client.post(
            "/signup",
            data={
                "email": "v@example.com",
                "password": "correct horse battery",
                "password2": "different",
                "age_attest": "yes",
            },
        )
        assert mismatch.status_code == 400 and "do not match" in mismatch.text
        no_attest = await client.post(
            "/signup",
            data={
                "email": "v@example.com",
                "password": "correct horse battery",
                "password2": "correct horse battery",
            },
        )
        assert no_attest.status_code == 400 and "wagering age" in no_attest.text
        ok = await signup(client, "v@example.com")
        assert ok.status_code == 303
        dup = await signup(client, "V@example.com")
        assert dup.status_code == 400 and "already registered" in dup.text
        page = await client.get("/signup")
        assert page.status_code == 200 and "legal" in page.text and "wagering age" in page.text
        escaped = await client.post(
            "/signup",
            data={
                "email": "<script>@x.com",
                "password": "correct horse battery",
                "password2": "nope",
                "age_attest": "yes",
            },
        )
        assert "<script>" not in escaped.text and "&lt;script&gt;" in escaped.text


async def test_account_export_and_delete(seen, hosted_settings):
    async with running(hosted_settings, seen) as client:
        await signup(client, "del@example.com")
        client_id = await register(client)
        token = await oauth_login(client, client_id, "del@example.com", "correct horse battery")
        headers = await mcp_session(client, token["access_token"])
        await call_tool(client, headers, "get_system_status")
        user_id = seen[0]

        export = await client.post("/account/export")
        assert export.status_code == 200 and export.headers["content-type"].startswith("application/json")
        assert "attachment" in export.headers["content-disposition"]
        bundle = export.json()
        assert (
            bundle["user_id_masked"] != user_id and bundle["tables"]["user_settings"][0]["user_id"] == user_id
        )
        assert "credentials" not in bundle["tables"] and "oauth_tokens" not in bundle["tables"]
        assert token["access_token"] not in export.text

        wrong = await client.post("/account/delete", data={"confirm": "delete my data"})
        assert wrong.status_code == 400
        deleted = await client.post("/account/delete", data={"confirm": DELETE_CONFIRMATION})
        assert deleted.status_code == 200 and "deleted" in deleted.text
        after = await client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "get_system_status", "arguments": {}},
            },
            headers=headers,
        )
        assert after.status_code == 401
        assert client.hrnba_app.state.oauth_provider.db.export_user(user_id)["user_settings"] == []
        assert (await client.get("/account")).status_code == 303


async def test_healthz_landing_privacy_terms(hosted_settings, seen):
    async with running(hosted_settings, seen) as client:
        health = await client.get("/healthz")
        assert health.status_code == 200 and health.json() == {
            "status": "ok",
            "version": hosted_settings.version,
        }
        assert "usr_" not in health.text and SECRET not in health.text
        landing = await client.get("/")
        assert (
            landing.status_code == 200 and "never places bets" in landing.text and "/privacy" in landing.text
        )
        for path in ("/privacy", "/terms"):
            doc = await client.get(path)
            assert doc.status_code == 200 and doc.headers["content-type"].startswith("text/plain")
            assert len(doc.text) > 20
        expired = await client.get("/login", params={"req": "not-a-real-token"})
        assert expired.status_code == 200  # the form renders; the bad token fails on POST
        bad_post = await client.post(
            "/login",
            data={"req": "not-a-real-token", "email": "x@example.com", "password": "correct horse battery"},
        )
        assert bad_post.status_code in (400, 401)


def test_transport_security_allows_public_host_and_loopback(hosted_settings):
    ts = transport_security_for(
        hosted_settings.model_copy(update={"public_url": "https://parlay.example.test"})
    )
    assert ts.enable_dns_rebinding_protection is True
    assert "parlay.example.test" in ts.allowed_hosts and "parlay.example.test:*" in ts.allowed_hosts
    assert "localhost" in ts.allowed_hosts and "127.0.0.1:*" in ts.allowed_hosts
    assert "https://parlay.example.test" in ts.allowed_origins


async def test_host_header_rebinding_is_rejected(hosted_settings, seen):
    async with running(hosted_settings, seen) as client:
        response = await client.get("/healthz", headers={"host": "evil.example"})
        assert response.status_code == 200  # non-MCP routes are plain pages
        mcp = await client.post(
            "/mcp", json={}, headers={**MCP_HEADERS, "host": "evil.example", "authorization": "Bearer nope"}
        )
        assert mcp.status_code in (401, 421)


# ---- open DCR: foreign redirect URIs are refused; the login page is a consent step ----


async def test_registration_refuses_redirect_uris_outside_claudes_set(hosted_settings, seen):
    async with running(hosted_settings, seen) as client:
        for uris in (
            ["https://attacker.test/cb"],
            [CLAUDE_CALLBACK, "https://attacker.test/cb"],
            ["https://localhost/callback"],
            ["http://localhost/callback?next=https://attacker.test"],
        ):
            response = await client.post(
                "/register",
                json={
                    "redirect_uris": uris,
                    "token_endpoint_auth_method": "none",
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                    "client_name": "Claude Parlay Helper (fake)",
                },
            )
            assert response.status_code == 400, (uris, response.text)
            assert response.json()["error"] == "invalid_redirect_uri"
        # Claude's documented set still registers
        assert await register(client, [CLAUDE_CALLBACK])
        assert await register(client, ["http://localhost/callback", "http://127.0.0.1/callback"])


async def test_login_and_signup_pages_name_the_client_and_destination(hosted_settings, seen):
    async with running(hosted_settings, seen) as client:
        await signup(client, "consent@example.com")
        client_id = await register(client, [CLAUDE_CALLBACK])
        _, challenge = pkce()
        authorize = await client.get(
            "/authorize",
            params={
                "client_id": client_id,
                "response_type": "code",
                "redirect_uri": CLAUDE_CALLBACK,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "s",
                "scope": "parlay",
            },
        )
        login_url = httpx.URL(authorize.headers["location"])
        req = login_url.params["req"]
        page = await client.get(str(login_url))
        assert page.status_code == 200
        assert "Claude (test)" in page.text and "https://claude.ai" in page.text
        assert "Sign in and connect" in page.text and "started this connection yourself" in page.text
        signup_page = await client.get("/signup", params={"req": req})
        assert "Claude (test)" in signup_page.text and "https://claude.ai" in signup_page.text
        assert "Create account and connect" in signup_page.text
        # a failed login re-renders the consent line with the error
        bad = await client.post(
            "/login", data={"req": req, "email": "consent@example.com", "password": "wrong-wrong"}
        )
        assert bad.status_code == 401 and "Claude (test)" in bad.text and "not recognized" in bad.text
        # without a request token the page is a plain sign-in form
        plain = await client.get("/login")
        assert "is asking to connect" not in plain.text and ">Sign in<" in plain.text
        # a forged/expired token says so instead of silently showing a bare form
        forged = await client.get("/login", params={"req": "not-a-real-token"})
        assert forged.status_code == 200 and "invalid or has expired" in forged.text


def test_err_text_is_redacted_and_capped():
    from hardrock_nba_parlay.errors import ServiceError
    from hardrock_nba_parlay.web import _err_text

    text = _err_text(
        ServiceError(
            "provider rejected", ["PROVIDER_AUTH_FAILED"], "GET https://x/?apiKey=SECRET123VALUE -> 401"
        )
    )
    assert "SECRET123VALUE" not in text and "[REDACTED]" in text and text.startswith("provider rejected")
    assert len(_err_text(ServiceError("x" * 1000))) <= 300


# ---- the HTTP transport never serves an authless /mcp beyond loopback ----


def test_loopback_host_detection():
    from hardrock_nba_parlay.web import is_loopback_host

    for host in ("127.0.0.1", "127.0.0.2", "localhost", "LOCALHOST", "::1", "[::1]"):
        assert is_loopback_host(host), host
    for host in (
        "0.0.0.0",
        "::",
        "",
        None,
        "10.0.0.5",
        "192.168.1.10",
        "fe80::1",
        "example.test",
        "localhost.attacker",
    ):
        assert not is_loopback_host(host), host


def test_run_http_refuses_non_loopback_without_oauth_and_allows_loopback(tmp_path, monkeypatch):
    import uvicorn

    from hardrock_nba_parlay.web import UnsafeBindError, ensure_safe_bind, run_http

    started: list[dict[str, Any]] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: started.append(kw))
    local = Settings(data_dir=tmp_path, database_url=f"sqlite:///{tmp_path / 'local.db'}", auth_mode="none")
    for host in ("0.0.0.0", "::", "10.0.0.5"):
        with pytest.raises(UnsafeBindError) as refused:
            run_http(local, host=host)
        assert refused.value.reason_codes == ["FORBIDDEN"] and host in (refused.value.detail or "")
        assert isinstance(refused.value, ValueError)
    with pytest.raises(UnsafeBindError):
        run_http(local.model_copy(update={"host": "0.0.0.0"}))
    assert started == []
    assert ensure_safe_bind(local, "localhost") == "localhost"
    run_http(local, host="127.0.0.1", port=8123)
    assert started[-1]["host"] == "127.0.0.1" and started[-1]["port"] == 8123
    hosted = Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'hosted.db'}",
        auth_mode="builtin_oauth",
        public_url="https://parlay.example.test",
        secret_key=SECRET,
        host="0.0.0.0",
    )
    run_http(hosted)
    assert started[-1]["host"] == "0.0.0.0"
