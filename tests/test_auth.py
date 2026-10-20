"""auth.py unit tests: identity resolution, signup/login, rate limiting, and the DB-backed OAuth provider."""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import pytest
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken, AuthorizationParams, AuthorizeError, TokenError
from mcp.shared.auth import InvalidRedirectUriError, OAuthClientInformationFull
from pydantic import AnyUrl
from sqlalchemy import select

from hardrock_nba_parlay import auth
from hardrock_nba_parlay import db as dbm
from hardrock_nba_parlay.config import Settings
from hardrock_nba_parlay.errors import InvalidInput, Unauthenticated

NOW = datetime(2026, 10, 20, 19, 0, tzinfo=UTC)
CLAUDE_CALLBACK = "https://claude.ai/api/mcp/auth_callback"


@pytest.fixture
def hosted_settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'hosted.db'}",
        auth_mode="builtin_oauth",
        public_url="https://parlay.example.test/",
        secret_key="unit-test-secret-key-not-real",
        allow_fixture_ledger=True,
    )


@pytest.fixture
def provider(hosted_settings, db, clock) -> auth.DbOAuthProvider:
    return auth.DbOAuthProvider(db, hosted_settings, clock)


def _client(
    client_id: str = "client-1", redirect_uris: list[str] | None = None
) -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id=client_id,
        redirect_uris=[AnyUrl(u) for u in (redirect_uris or [CLAUDE_CALLBACK, "http://localhost/callback"])],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        scope="parlay",
        client_name="test",
    )


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


# ---- identity ----


def test_current_user_id_local_mode(settings):
    assert auth.current_user_id(settings) == settings.local_user_id == "local-owner"


def test_current_user_id_hosted_requires_token(hosted_settings):
    with pytest.raises(Unauthenticated) as exc:
        auth.current_user_id(hosted_settings)
    assert exc.value.reason_codes == ["UNAUTHENTICATED"]
    token = AccessToken(token="t", client_id="c", scopes=["parlay"], subject="usr_abc")
    reset = auth_context_var.set(AuthenticatedUser(token))
    try:
        assert auth.current_user_id(hosted_settings) == "usr_abc"
    finally:
        auth_context_var.reset(reset)


def test_ensure_user_creates_rows_once(db, settings):
    auth.ensure_user(db, "usr_new", NOW, settings)
    auth.ensure_user(db, "usr_new", NOW + timedelta(days=1), settings)
    with db.engine.connect() as conn:
        users = conn.execute(select(dbm.users).where(dbm.users.c.user_id == "usr_new")).mappings().all()
        us = (
            conn.execute(select(dbm.user_settings).where(dbm.user_settings.c.user_id == "usr_new"))
            .mappings()
            .all()
        )
    assert len(users) == 1 and len(us) == 1
    assert (
        us[0]["daily_cap_cents"] == 1000
        and us[0]["onboarding_complete"] == 0
        and us[0]["display_tz"] == "America/New_York"
    )
    assert users[0]["created_at"] == "2026-10-20T19:00:00.000Z"


# ---- users and passwords ----


def test_signup_normalizes_email_hashes_with_argon2id_and_is_unique(db, settings):
    user_id = auth.signup(db, "  Alice@Example.COM ", "correct horse battery", NOW, settings)
    assert user_id.startswith("usr_")
    with db.engine.connect() as conn:
        user = conn.execute(select(dbm.users).where(dbm.users.c.user_id == user_id)).mappings().first()
        cred = (
            conn.execute(select(dbm.credentials).where(dbm.credentials.c.user_id == user_id))
            .mappings()
            .first()
        )
    assert user["email"] == "alice@example.com"
    assert cred["password_hash"].startswith("$argon2id$")
    assert "correct horse" not in cred["password_hash"]
    with pytest.raises(InvalidInput):
        auth.signup(db, "alice@example.com", "another password", NOW, settings)
    with pytest.raises(InvalidInput):
        auth.signup(db, "not-an-email", "another password", NOW, settings)
    with pytest.raises(InvalidInput):
        auth.signup(db, "short@example.com", "short", NOW, settings)


def test_login_success_wrong_password_and_unknown_email(db, settings):
    user_id = auth.signup(db, "bob@example.com", "correct horse battery", NOW, settings)
    assert auth.login(db, "BOB@example.com", "correct horse battery", NOW, "10.0.0.1") == user_id
    with pytest.raises(auth.LoginFailed) as bad:
        auth.login(db, "bob@example.com", "wrong password", NOW, "10.0.0.1")
    with pytest.raises(auth.LoginFailed) as missing:
        auth.login(db, "nobody@example.com", "wrong password", NOW, "10.0.0.1")
    assert str(bad.value) == str(missing.value) == "login failed"


def test_login_rate_limit_per_email_and_per_client(db, settings):
    auth.signup(db, "carol@example.com", "correct horse battery", NOW, settings)
    for _ in range(auth.LOGIN_MAX_ATTEMPTS):
        with pytest.raises(auth.LoginFailed):
            auth.login(db, "carol@example.com", "wrong", NOW, "1.1.1.1")
    with pytest.raises(auth.LoginRateLimited):
        auth.login(db, "carol@example.com", "correct horse battery", NOW + timedelta(minutes=1), "2.2.2.2")
    with pytest.raises(auth.LoginRateLimited):
        auth.login(db, "someone-else@example.com", "whatever", NOW + timedelta(minutes=1), "1.1.1.1")
    # the window expires after 15 minutes
    assert auth.login(
        db, "carol@example.com", "correct horse battery", NOW + timedelta(minutes=16), "1.1.1.1"
    )


# ---- redirect URI matching ----


def test_loopback_redirect_matches_ignoring_port_only():
    assert auth.redirect_uris_match("http://localhost/callback", "http://localhost:3118/callback")
    assert auth.redirect_uris_match("http://127.0.0.1/callback", "http://127.0.0.1:51234/callback")
    assert auth.redirect_uris_match(CLAUDE_CALLBACK, CLAUDE_CALLBACK)
    assert not auth.redirect_uris_match("http://localhost/callback", "http://localhost:3118/other")
    assert not auth.redirect_uris_match(
        "https://claude.ai/api/mcp/auth_callback", "https://claude.ai:8443/api/mcp/auth_callback"
    )
    assert not auth.redirect_uris_match("https://evil.test/callback", "https://evil.test:1/callback")
    client = auth.RegisteredClient.model_validate(_client().model_dump(mode="json"))
    assert (
        str(client.validate_redirect_uri(AnyUrl("http://localhost:3118/callback")))
        == "http://localhost:3118/callback"
    )
    with pytest.raises(InvalidRedirectUriError):
        client.validate_redirect_uri(AnyUrl("https://attacker.test/callback"))


# ---- OAuth provider ----


async def test_register_and_get_client_persist_json(provider, db):
    await provider.register_client(_client("client-xyz"))
    loaded = await provider.get_client("client-xyz")
    assert isinstance(loaded, auth.RegisteredClient)
    assert [str(u) for u in loaded.redirect_uris] == [CLAUDE_CALLBACK, "http://localhost/callback"]
    assert await provider.get_client("missing") is None


async def test_authorize_returns_login_url_with_signed_request(provider, hosted_settings):
    client = _client()
    _, challenge = _pkce()
    params = AuthorizationParams(
        state="st4te",
        scopes=["parlay"],
        code_challenge=challenge,
        redirect_uri=AnyUrl(CLAUDE_CALLBACK),
        redirect_uri_provided_explicitly=True,
        resource="https://parlay.example.test/mcp",
    )
    url = await provider.authorize(client, params)
    assert url.startswith("https://parlay.example.test/login?req=")
    req = url.split("req=", 1)[1]
    data = provider.login_request_from_token(req)
    assert (
        data["client_id"] == "client-1" and data["state"] == "st4te" and data["code_challenge"] == challenge
    )
    assert data["redirect_uri"] == CLAUDE_CALLBACK and data["scopes"] == ["parlay"]
    with pytest.raises(InvalidInput):
        provider.login_request_from_token(req[:-3] + "xyz")
    with pytest.raises(AuthorizeError):
        await provider.authorize(client, params.model_copy(update={"resource": "https://other.example/mcp"}))


async def test_code_and_token_lifecycle_stores_only_hashes(provider, db, clock):
    client = _client()
    await provider.register_client(client)
    verifier, challenge = _pkce()
    req = {
        "client_id": client.client_id,
        "redirect_uri": CLAUDE_CALLBACK,
        "redirect_uri_provided_explicitly": True,
        "code_challenge": challenge,
        "state": "abc",
        "scopes": ["parlay"],
    }
    redirect = provider.complete_login(req, "usr_owner", clock.now_utc())
    assert redirect.startswith(CLAUDE_CALLBACK + "?")
    code = redirect.split("code=")[1].split("&")[0]
    with db.engine.connect() as conn:
        stored_codes = [r[0] for r in conn.execute(select(dbm.oauth_codes.c.code))]
    assert stored_codes == [auth.hash_token(code)]
    assert code not in stored_codes

    loaded = await provider.load_authorization_code(client, code)
    assert loaded is not None and loaded.subject == "usr_owner" and loaded.code_challenge == challenge
    assert await provider.load_authorization_code(_client("other-client"), code) is None

    token = await provider.exchange_authorization_code(client, loaded)
    assert token.token_type == "Bearer" and token.expires_in == 3600 and token.scope == "parlay"
    assert token.refresh_token
    with db.engine.connect() as conn:
        rows = conn.execute(select(dbm.oauth_tokens)).mappings().all()
    assert await provider.load_authorization_code(client, code) is None
    assert {r["kind"] for r in rows} == {"access", "refresh"}
    assert {r["token"] for r in rows} == {
        auth.hash_token(token.access_token),
        auth.hash_token(token.refresh_token),
    }
    for row in rows:
        assert token.access_token not in row["token"] and token.refresh_token not in row["token"]
        assert row["user_id"] == "usr_owner" and row["scopes"] == "parlay"

    with pytest.raises(TokenError):
        await provider.exchange_authorization_code(client, loaded)

    access = await provider.load_access_token(token.access_token)
    assert (
        access is not None
        and access.subject == "usr_owner"
        and access.resource == "https://parlay.example.test/mcp"
    )
    assert access.expires_at == int((clock.now_utc() + timedelta(hours=1)).timestamp())
    clock.advance(3601)
    assert await provider.load_access_token(token.access_token) is None


async def test_refresh_rotates_and_revocation_kills_siblings(provider, db, clock):
    client = _client()
    await provider.register_client(client)
    _, challenge = _pkce()
    req = {
        "client_id": client.client_id,
        "redirect_uri": CLAUDE_CALLBACK,
        "code_challenge": challenge,
        "state": None,
        "scopes": ["parlay"],
    }
    code = provider.complete_login(req, "usr_owner", clock.now_utc()).split("code=")[1]
    first = await provider.exchange_authorization_code(
        client, await provider.load_authorization_code(client, code)
    )

    refresh = await provider.load_refresh_token(client, first.refresh_token)
    assert refresh is not None and refresh.subject == "usr_owner"
    assert await provider.load_refresh_token(_client("other"), first.refresh_token) is None
    second = await provider.exchange_refresh_token(client, refresh, ["parlay"])
    assert second.access_token != first.access_token and second.refresh_token != first.refresh_token
    assert await provider.load_refresh_token(client, first.refresh_token) is None
    with pytest.raises(TokenError):
        await provider.exchange_refresh_token(client, refresh, ["parlay"])
    assert await provider.load_access_token(second.access_token) is not None

    await provider.revoke_token(await provider.load_access_token(second.access_token))
    assert await provider.load_access_token(second.access_token) is None
    assert await provider.load_refresh_token(client, second.refresh_token) is None
    await provider.revoke_token(AccessToken(token="unknown", client_id="c", scopes=[]))  # no error


async def test_revoke_user_tokens(provider, clock):
    client = _client()
    await provider.register_client(client)
    _, challenge = _pkce()
    req = {
        "client_id": client.client_id,
        "redirect_uri": CLAUDE_CALLBACK,
        "code_challenge": challenge,
        "scopes": ["parlay"],
    }
    code = provider.complete_login(req, "usr_gone", clock.now_utc()).split("code=")[1]
    tok = await provider.exchange_authorization_code(
        client, await provider.load_authorization_code(client, code)
    )
    assert provider.revoke_user_tokens("usr_gone") == 2
    assert await provider.load_access_token(tok.access_token) is None


def test_build_auth_settings(hosted_settings):
    s = auth.build_auth_settings(hosted_settings)
    assert str(s.issuer_url) == "https://parlay.example.test"
    assert str(s.resource_server_url) == "https://parlay.example.test/mcp"
    assert s.client_registration_options.enabled and s.client_registration_options.valid_scopes == ["parlay"]
    assert s.revocation_options.enabled and s.required_scopes == ["parlay"]
    assert s.validate_token_resource is True


def test_provider_requires_public_url_and_secret(tmp_path, db, clock):
    with pytest.raises(ValueError):
        auth.DbOAuthProvider(
            db, Settings(data_dir=tmp_path, auth_mode="builtin_oauth", secret_key="x"), clock
        )
    with pytest.raises(ValueError):
        auth.DbOAuthProvider(
            db, Settings(data_dir=tmp_path, auth_mode="builtin_oauth", public_url="https://a.test"), clock
        )


# ---- redirect URI allowlist (open DCR must not register a foreign callback) ----


def test_redirect_uri_allowlist_accepts_only_claude_callbacks():
    for ok in (
        CLAUDE_CALLBACK,
        "http://localhost/callback",
        "http://localhost:3118/callback",
        "http://127.0.0.1:51234/callback",
        "http://localhost",
        "http://localhost:8080/",
        "http://[::1]:9/callback",
    ):
        assert auth.redirect_uri_allowed(ok), ok
        assert auth.redirect_uri_allowed(AnyUrl(ok)), ok
    for bad in (
        "https://attacker.test/cb",
        "https://claude.ai/api/mcp/auth_callback?x=1",
        "https://claude.ai:8443/api/mcp/auth_callback",
        "https://claude.ai/api/mcp/auth_callback/",
        "http://localhost/other",
        "https://localhost/callback",
        "http://localhost/callback?next=https://attacker.test",
        "http://localhost/callback#frag",
        "http://user@localhost/callback",
        "http://localhost.attacker.test/callback",
        "http://127.0.0.1.attacker.test/callback",
        "",
    ):
        assert not auth.redirect_uri_allowed(bad), bad
    assert auth.redirect_host_label("http://localhost:3118/callback?code=x") == "http://localhost:3118"
    assert auth.redirect_host_label(CLAUDE_CALLBACK) == "https://claude.ai"


async def test_register_client_refuses_foreign_redirect_uris(provider):
    from mcp.server.auth.provider import RegistrationError

    with pytest.raises(RegistrationError) as refused:
        await provider.register_client(_client("evil-1", ["https://attacker.test/cb"]))
    assert refused.value.error == "invalid_redirect_uri"
    assert "attacker.test" in (refused.value.error_description or "")
    assert await provider.get_client("evil-1") is None
    # one bad URI among good ones is enough to refuse the whole registration
    with pytest.raises(RegistrationError):
        await provider.register_client(_client("evil-2", [CLAUDE_CALLBACK, "https://attacker.test/cb"]))
    assert await provider.get_client("evil-2") is None
    with pytest.raises(RegistrationError):
        auth.check_redirect_uris([])
    # Claude's documented set still registers
    await provider.register_client(_client("good", [CLAUDE_CALLBACK, "http://127.0.0.1/callback"]))
    assert await provider.get_client("good") is not None


async def test_authorize_and_complete_login_refuse_non_claude_redirects(provider, clock):
    _, challenge = _pkce()
    client = _client()
    params = AuthorizationParams(
        state="s",
        scopes=["parlay"],
        code_challenge=challenge,
        redirect_uri=AnyUrl("https://attacker.test/cb"),
        redirect_uri_provided_explicitly=True,
        resource=None,
    )
    with pytest.raises(AuthorizeError) as refused:
        await provider.authorize(client, params)
    assert refused.value.error == "invalid_request"
    req = {
        "client_id": client.client_id,
        "redirect_uri": "https://attacker.test/cb",
        "code_challenge": challenge,
        "scopes": ["parlay"],
    }
    with pytest.raises(InvalidInput):
        provider.complete_login(req, "usr_victim", clock.now_utc())
    assert _stored_codes(provider) == []  # a refused login mints no authorization code


def _stored_codes(provider: auth.DbOAuthProvider) -> list[str]:
    with provider.db.engine.connect() as conn:
        return [r[0] for r in conn.execute(select(dbm.oauth_codes.c.code))]


async def test_describe_login_request_names_client_and_redirect_host(provider):
    await provider.register_client(
        _client("named", [CLAUDE_CALLBACK]).model_copy(update={"client_name": "Claude (test)"})
    )
    info = await provider.describe_login_request({"client_id": "named", "redirect_uri": CLAUDE_CALLBACK})
    assert info == {"client_name": "Claude (test)", "redirect_host": "https://claude.ai"}
    unknown = await provider.describe_login_request(
        {"client_id": "missing", "redirect_uri": "http://localhost:3118/callback"}
    )
    assert unknown == {"client_name": "an MCP client", "redirect_host": "http://localhost:3118"}
