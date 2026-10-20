"""Identity resolution, user accounts, password login, and the built-in OAuth 2.1 authorization server.

This is the ONLY place a user identity is resolved (docs/ARCHITECTURE.md sections 0 and 9):

- ``auth_mode == "none"`` (stdio / CLI): the identity is ``settings.local_user_id``.
- ``auth_mode == "builtin_oauth"`` (hosted): the identity is the ``subject`` of the verified bearer token that the
  MCP SDK placed in the request context. A user id is never accepted from tool arguments.

The OAuth provider persists clients, codes, and tokens in the ``oauth_*`` tables. Only SHA-256 hashes of
authorization codes, access tokens, and refresh tokens are stored. Passwords are hashed with argon2id.

Dynamic client registration is open (Claude registers a new client per connection), so the redirect URIs a
client may register are limited to Claude's documented set (``ALLOWED_REDIRECT_URIS`` plus loopback
``http://localhost|127.0.0.1|[::1][:port][/callback]``, docs/research/claude-directory-connectors.md). Without
that limit anyone could register a client pointing at their own host and phish an authorization code through
our genuine ``/login`` page. The same check runs again at ``authorize`` and ``complete_login``.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from itsdangerous import BadSignature, URLSafeTimedSerializer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.shared.auth import InvalidRedirectUriError, OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl
from sqlalchemy import delete, insert, select, update

from . import db as dbm
from .config import Clock, Settings
from .db import Database, cents, dumps, iso, loads, new_id, parse_iso
from .errors import InvalidInput, Unauthenticated

logger = logging.getLogger(__name__)

SCOPE = "parlay"
ACCESS_TOKEN_TTL_SECONDS = 60 * 60
REFRESH_TOKEN_TTL_SECONDS = 30 * 24 * 60 * 60
AUTH_CODE_TTL_SECONDS = 5 * 60
LOGIN_REQUEST_TTL_SECONDS = 10 * 60
LOGIN_MAX_ATTEMPTS = 10
LOGIN_WINDOW_SECONDS = 15 * 60
MIN_PASSWORD_LENGTH = 8
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "[::1]", "::1"})
# Claude's documented redirect URIs (docs/research/claude-directory-connectors.md, "Redirect URIs (exact)"):
# hosted apps register exactly the claude.ai callback; Claude Code uses a loopback on any port.
ALLOWED_REDIRECT_URIS = frozenset({"https://claude.ai/api/mcp/auth_callback"})
LOOPBACK_REDIRECT_PATHS = frozenset({"", "/", "/callback"})

_hasher = PasswordHasher()
_dummy_hash: str | None = None


class LoginFailed(Unauthenticated):
    """Generic login failure (wrong email or password). Deliberately says nothing about which one."""

    def __init__(self) -> None:
        super().__init__("login failed", "email or password not recognized")


class LoginRateLimited(Unauthenticated):
    """Too many failed attempts for this email or client in the current window."""

    def __init__(self) -> None:
        super().__init__("too many login attempts", "try again in 15 minutes")


# --------------------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------------------


def current_user_id(settings: Settings) -> str:
    """Resolve the caller's user id. Local mode: ``settings.local_user_id``. Hosted: verified token subject."""
    if settings.auth_mode == "none":
        return settings.local_user_id
    token = get_access_token()
    if token is None or not token.subject:
        raise Unauthenticated("authentication required", "no verified bearer token in this request")
    return token.subject


def ensure_user(db: Database, user_id: str, now: datetime, settings: Settings) -> None:
    """Create the ``users`` and ``user_settings`` rows the first time a user id is seen."""
    with db.tx() as conn:
        exists = conn.execute(select(dbm.users.c.user_id).where(dbm.users.c.user_id == user_id)).first()
        if exists is None:
            conn.execute(
                insert(dbm.users).values(
                    user_id=user_id, email=None, display_name=None, disabled=0, created_at=iso(now)
                )
            )
        has_settings = conn.execute(
            select(dbm.user_settings.c.user_id).where(dbm.user_settings.c.user_id == user_id)
        ).first()
        if has_settings is None:
            conn.execute(
                insert(dbm.user_settings).values(
                    user_id=user_id,
                    daily_cap_cents=cents(settings.daily_cap_usd_default),
                    display_tz=settings.display_tz,
                    onboarding_complete=0,
                    odds_api_key_encrypted=None,
                    created_at=iso(now),
                    updated_at=iso(now),
                )
            )


# --------------------------------------------------------------------------------------
# Users and passwords
# --------------------------------------------------------------------------------------


def normalize_email(email: str) -> str:
    """Lower-case, trimmed email. Raises InvalidInput when it does not look like an address."""
    value = (email or "").strip().lower()
    if "@" not in value or value.startswith("@") or value.endswith("@") or len(value) > 254:
        raise InvalidInput("invalid email address")
    return value


def _dummy_password_hash() -> str:
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = _hasher.hash(secrets.token_urlsafe(24))
    return _dummy_hash


def signup(db: Database, email: str, password: str, now: datetime, settings: Settings | None = None) -> str:
    """Create a user with an argon2id password hash. Returns the new user id. Email must be unique."""
    value = normalize_email(email)
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise InvalidInput(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) > 1024:
        raise InvalidInput("password too long")
    password_hash = _hasher.hash(password)
    cap = settings.daily_cap_usd_default if settings is not None else Decimal("10.00")
    tz_name = settings.display_tz if settings is not None else "America/New_York"
    user_id = new_id("usr")
    with db.tx() as conn:
        taken = conn.execute(select(dbm.users.c.user_id).where(dbm.users.c.email == value)).first()
        if taken is not None:
            raise InvalidInput("email already registered")
        conn.execute(
            insert(dbm.users).values(
                user_id=user_id, email=value, display_name=None, disabled=0, created_at=iso(now)
            )
        )
        conn.execute(
            insert(dbm.user_settings).values(
                user_id=user_id,
                daily_cap_cents=cents(cap),
                display_tz=tz_name,
                onboarding_complete=0,
                odds_api_key_encrypted=None,
                created_at=iso(now),
                updated_at=iso(now),
            )
        )
        conn.execute(
            insert(dbm.credentials).values(user_id=user_id, password_hash=password_hash, updated_at=iso(now))
        )
    return user_id


def _attempt_keys(email: str, client_key: str) -> list[str]:
    return [f"email:{email}", f"client:{client_key or 'unknown'}"]


def _rate_limited(db: Database, keys: list[str], now: datetime) -> bool:
    with db.engine.connect() as conn:
        for key in keys:
            row = (
                conn.execute(select(dbm.login_attempts).where(dbm.login_attempts.c.key == key))
                .mappings()
                .first()
            )
            if row is None:
                continue
            started = parse_iso(row["window_start"])
            if started is None or now - started > timedelta(seconds=LOGIN_WINDOW_SECONDS):
                continue
            if int(row["count"]) >= LOGIN_MAX_ATTEMPTS:
                return True
    return False


def _record_failure(db: Database, keys: list[str], now: datetime) -> None:
    with db.tx() as conn:
        for key in keys:
            row = (
                conn.execute(select(dbm.login_attempts).where(dbm.login_attempts.c.key == key))
                .mappings()
                .first()
            )
            started = parse_iso(row["window_start"]) if row is not None else None
            if row is None:
                conn.execute(insert(dbm.login_attempts).values(key=key, window_start=iso(now), count=1))
            elif started is None or now - started > timedelta(seconds=LOGIN_WINDOW_SECONDS):
                conn.execute(
                    update(dbm.login_attempts)
                    .where(dbm.login_attempts.c.key == key)
                    .values(window_start=iso(now), count=1)
                )
            else:
                conn.execute(
                    update(dbm.login_attempts)
                    .where(dbm.login_attempts.c.key == key)
                    .values(count=int(row["count"]) + 1)
                )


def _clear_failures(db: Database, keys: list[str]) -> None:
    with db.tx() as conn:
        conn.execute(delete(dbm.login_attempts).where(dbm.login_attempts.c.key.in_(keys)))


def login(db: Database, email: str, password: str, now: datetime, client_key: str) -> str:
    """Verify email + password. Returns the user id.

    Rate limited to LOGIN_MAX_ATTEMPTS failures per LOGIN_WINDOW_SECONDS per email and per client key. The
    argon2 verifier always runs, even for unknown emails, so timing does not reveal whether an email exists.
    Raises LoginRateLimited or LoginFailed (both carry only generic messages).
    """
    try:
        value = normalize_email(email)
    except InvalidInput:
        value = (email or "").strip().lower()[:254] or "-"
    keys = _attempt_keys(value, client_key)
    if _rate_limited(db, keys, now):
        raise LoginRateLimited()
    with db.engine.connect() as conn:
        row = (
            conn.execute(
                select(dbm.users.c.user_id, dbm.users.c.disabled, dbm.credentials.c.password_hash)
                .select_from(
                    dbm.users.join(dbm.credentials, dbm.users.c.user_id == dbm.credentials.c.user_id)
                )
                .where(dbm.users.c.email == value)
            )
            .mappings()
            .first()
        )
    stored_hash = row["password_hash"] if row is not None else _dummy_password_hash()
    ok = False
    try:
        ok = _hasher.verify(stored_hash, password or "")
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        ok = False
    if row is None or not ok or int(row["disabled"] or 0):
        _record_failure(db, keys, now)
        raise LoginFailed()
    user_id = str(row["user_id"])
    _clear_failures(db, keys)
    if _hasher.check_needs_rehash(stored_hash):
        with db.tx() as conn:
            conn.execute(
                update(dbm.credentials)
                .where(dbm.credentials.c.user_id == user_id)
                .values(password_hash=_hasher.hash(password), updated_at=iso(now))
            )
    return user_id


# --------------------------------------------------------------------------------------
# OAuth 2.1 authorization server backed by the database
# --------------------------------------------------------------------------------------


def hash_token(token: str) -> str:
    """SHA-256 hex digest; the only form in which codes and tokens are stored."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _is_loopback(url: AnyUrl | str) -> bool:
    host = (urlsplit(str(url)).hostname or "").lower()
    return host in LOOPBACK_HOSTS


def redirect_uri_allowed(url: AnyUrl | str) -> bool:
    """True when a redirect URI is one Claude's clients are documented to use.

    Exactly ``https://claude.ai/api/mcp/auth_callback``, or plain-http loopback (``localhost``, ``127.0.0.1``,
    ``[::1]``) on any port with path ``/callback`` or ``/`` and no query, fragment, or userinfo (RFC 8252 7.3).
    """
    text = str(url).strip()
    if text in ALLOWED_REDIRECT_URIS:
        return True
    parts = urlsplit(text)
    if parts.scheme != "http" or not _is_loopback(text):
        return False
    if parts.query or parts.fragment or parts.username is not None or parts.password is not None:
        return False
    return (parts.path or "") in LOOPBACK_REDIRECT_PATHS


def check_redirect_uris(uris: list[AnyUrl] | list[str] | None) -> None:
    """Raise ``RegistrationError('invalid_redirect_uri')`` unless every URI passes ``redirect_uri_allowed``."""
    if not uris:
        raise RegistrationError("invalid_redirect_uri", "redirect_uris is required")
    for uri in uris:
        if not redirect_uri_allowed(uri):
            raise RegistrationError(
                "invalid_redirect_uri",
                "redirect URIs must be https://claude.ai/api/mcp/auth_callback or a loopback "
                "http://localhost[:port]/callback (Claude Code); got "
                f"{_redirect_host_label(uri)}",
            )


def _redirect_host_label(url: AnyUrl | str) -> str:
    """Scheme and host of a redirect URI for messages and the consent page (never the query string)."""
    parts = urlsplit(str(url))
    host = parts.netloc or "(no host)"
    return f"{parts.scheme}://{host}" if parts.scheme else host


def redirect_host_label(url: AnyUrl | str) -> str:
    """Public alias used by the login/consent page: ``https://claude.ai`` or ``http://localhost:3118``."""
    return _redirect_host_label(url)


def redirect_uris_match(registered: AnyUrl | str, requested: AnyUrl | str) -> bool:
    """Exact match, except that loopback redirect URIs (Claude Code) match with the port ignored (RFC 8252 7.3)."""
    a, b = str(registered), str(requested)
    if a == b:
        return True
    pa, pb = urlsplit(a), urlsplit(b)
    if not (_is_loopback(a) and _is_loopback(b)):
        return False
    return (
        pa.scheme == pb.scheme
        and (pa.hostname or "").lower() == (pb.hostname or "").lower()
        and (pa.path or "/") == (pb.path or "/")
        and pa.query == pb.query
    )


class RegisteredClient(OAuthClientInformationFull):
    """A stored client whose redirect-URI check tolerates loopback ports (the SDK's own check is exact)."""

    def validate_redirect_uri(self, redirect_uri: AnyUrl | None) -> AnyUrl:
        if redirect_uri is None:
            return super().validate_redirect_uri(None)
        for registered in self.redirect_uris or []:
            if redirect_uris_match(registered, redirect_uri):
                return redirect_uri
        raise InvalidRedirectUriError(f"Redirect URI '{redirect_uri}' not registered for client")


def _normalize_resource(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip().rstrip("/").lower()


class DbOAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    """OAuth authorization server for Claude's clients: DCR, PKCE S256, refresh rotation, revocation.

    ``authorize`` sends the user agent to our own ``/login`` page with a signed, short-lived request token;
    the web layer calls ``complete_login`` after a successful password login to mint the authorization code
    and build the redirect back to the client.
    """

    def __init__(self, db: Database, settings: Settings, clock: Clock) -> None:
        if settings.public_url is None:
            raise ValueError("public_url is required in hosted mode")
        if settings.secret_key is None or not settings.secret_key.get_secret_value():
            raise ValueError("secret_key is required in hosted mode")
        self.db = db
        self.settings = settings
        self.clock = clock
        self.base_url = settings.public_url.rstrip("/")
        self.resource_url = self.base_url + "/mcp"
        self._serializer = URLSafeTimedSerializer(
            settings.secret_key.get_secret_value(), salt="hrnba-oauth-login-request"
        )

    # ---- clients (RFC 7591 dynamic client registration) ----
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        with self.db.engine.connect() as conn:
            row = conn.execute(
                select(dbm.oauth_clients.c.client_json).where(dbm.oauth_clients.c.client_id == client_id)
            ).first()
        if row is None:
            return None
        return RegisteredClient.model_validate_json(row[0])

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        """Store a dynamically registered client. Refuses redirect URIs outside Claude's documented set."""
        if not client_info.client_id:
            raise ValueError("client_id required")
        check_redirect_uris(client_info.redirect_uris)
        payload = client_info.model_dump_json(exclude_none=True)
        now = self.clock.now_utc()
        with self.db.tx() as conn:
            existing = conn.execute(
                select(dbm.oauth_clients.c.client_id).where(
                    dbm.oauth_clients.c.client_id == client_info.client_id
                )
            ).first()
            if existing is None:
                conn.execute(
                    insert(dbm.oauth_clients).values(
                        client_id=client_info.client_id, client_json=payload, created_at=iso(now)
                    )
                )
            else:
                conn.execute(
                    update(dbm.oauth_clients)
                    .where(dbm.oauth_clients.c.client_id == client_info.client_id)
                    .values(client_json=payload)
                )
        logger.info(
            "registered oauth client %s (%s)", client_info.client_id, client_info.client_name or "unnamed"
        )

    # ---- authorization request -> our login page ----
    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        if params.resource is not None and _normalize_resource(params.resource) != _normalize_resource(
            self.resource_url
        ):
            raise AuthorizeError("invalid_target", f"resource must be {self.resource_url}")
        if not redirect_uri_allowed(params.redirect_uri):
            # A client stored before the registration check existed, or a hand-edited row: never send the
            # user agent toward a redirect URI that is not Claude's.
            raise AuthorizeError("invalid_request", "redirect_uri is not an allowed Claude callback")
        scopes = list(params.scopes) if params.scopes else [SCOPE]
        payload = {
            "client_id": client.client_id,
            "redirect_uri": str(params.redirect_uri),
            "redirect_uri_provided_explicitly": bool(params.redirect_uri_provided_explicitly),
            "code_challenge": params.code_challenge,
            "state": params.state,
            "scopes": scopes,
            "resource": self.resource_url,
        }
        req = self._serializer.dumps(payload)
        return f"{self.base_url}/login?req={req}"

    def login_request_from_token(self, req: str) -> dict[str, Any]:
        """Verify and decode the signed login-request token (10-minute lifetime)."""
        try:
            data = self._serializer.loads(req, max_age=LOGIN_REQUEST_TTL_SECONDS)
        except BadSignature as exc:  # SignatureExpired is a BadSignature subclass
            raise InvalidInput("login request is invalid or has expired; start the connection again") from exc
        if not isinstance(data, dict) or "client_id" not in data or "code_challenge" not in data:
            raise InvalidInput("login request is malformed")
        return data

    async def describe_login_request(self, req: dict[str, Any]) -> dict[str, str]:
        """What the consent line on the login page shows: the registered client's name and the redirect host."""
        client = await self.get_client(str(req.get("client_id", "")))
        name = (client.client_name if client is not None and client.client_name else "") or "an MCP client"
        return {
            "client_name": str(name)[:120],
            "redirect_host": _redirect_host_label(str(req.get("redirect_uri", ""))),
        }

    def complete_login(self, req: dict[str, Any], user_id: str, now: datetime) -> str:
        """After a successful login: mint the authorization code and return the client's redirect URL."""
        if not redirect_uri_allowed(str(req.get("redirect_uri", ""))):
            raise InvalidInput("login request targets a redirect URI that is not an allowed Claude callback")
        code = secrets.token_urlsafe(32)
        expires_at = now + timedelta(seconds=AUTH_CODE_TTL_SECONDS)
        record = {
            "scopes": list(req.get("scopes") or [SCOPE]),
            "expires_at": expires_at.timestamp(),
            "client_id": str(req["client_id"]),
            "code_challenge": str(req["code_challenge"]),
            "redirect_uri": str(req["redirect_uri"]),
            "redirect_uri_provided_explicitly": bool(req.get("redirect_uri_provided_explicitly", True)),
            "resource": self.resource_url,
            "subject": user_id,
        }
        with self.db.tx() as conn:
            conn.execute(delete(dbm.oauth_codes).where(dbm.oauth_codes.c.expires_at < iso(now)))
            conn.execute(
                insert(dbm.oauth_codes).values(
                    code=hash_token(code),
                    client_id=record["client_id"],
                    user_id=user_id,
                    json=dumps(record),
                    expires_at=iso(expires_at),
                )
            )
        return construct_redirect_uri(str(req["redirect_uri"]), code=code, state=req.get("state"))

    # ---- authorization codes ----
    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        with self.db.engine.connect() as conn:
            row = (
                conn.execute(
                    select(dbm.oauth_codes).where(dbm.oauth_codes.c.code == hash_token(authorization_code))
                )
                .mappings()
                .first()
            )
        if row is None or row["client_id"] != client.client_id:
            return None
        expires = parse_iso(row["expires_at"])
        if expires is None or expires < self.clock.now_utc():
            with self.db.tx() as conn:
                conn.execute(delete(dbm.oauth_codes).where(dbm.oauth_codes.c.code == row["code"]))
            return None
        data = loads(row["json"])
        data["redirect_uri"] = AnyUrl(data["redirect_uri"])
        return AuthorizationCode(code=authorization_code, **data)

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        # TokenError is a frozen dataclass; it must be raised outside the transaction context manager.
        now = self.clock.now_utc()
        subject = authorization_code.subject or ""
        if not subject:
            raise TokenError("invalid_grant", "authorization code has no subject")
        token: OAuthToken | None = None
        with self.db.tx() as conn:
            deleted = conn.execute(
                delete(dbm.oauth_codes).where(dbm.oauth_codes.c.code == hash_token(authorization_code.code))
            )
            if (deleted.rowcount or 0) > 0:
                token = self._issue_pair(
                    conn, client.client_id, subject, list(authorization_code.scopes), now
                )
        if token is None:
            raise TokenError("invalid_grant", "authorization code already used")
        return token

    # ---- tokens ----
    def _issue_pair(
        self, conn: Any, client_id: str, user_id: str, scopes: list[str], now: datetime
    ) -> OAuthToken:
        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(32)
        scope_text = " ".join(scopes)
        conn.execute(
            insert(dbm.oauth_tokens).values(
                token=hash_token(access),
                kind="access",
                client_id=client_id,
                user_id=user_id,
                scopes=scope_text,
                expires_at=iso(now + timedelta(seconds=ACCESS_TOKEN_TTL_SECONDS)),
                revoked=0,
                created_at=iso(now),
            )
        )
        conn.execute(
            insert(dbm.oauth_tokens).values(
                token=hash_token(refresh),
                kind="refresh",
                client_id=client_id,
                user_id=user_id,
                scopes=scope_text,
                expires_at=iso(now + timedelta(seconds=REFRESH_TOKEN_TTL_SECONDS)),
                revoked=0,
                created_at=iso(now),
            )
        )
        return OAuthToken(
            access_token=access,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            scope=scope_text,
            refresh_token=refresh,
        )

    def _load_token_row(self, token: str, kind: str) -> dict[str, Any] | None:
        with self.db.engine.connect() as conn:
            row = (
                conn.execute(
                    select(dbm.oauth_tokens).where(
                        dbm.oauth_tokens.c.token == hash_token(token),
                        dbm.oauth_tokens.c.kind == kind,
                        dbm.oauth_tokens.c.revoked == 0,
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        expires = parse_iso(row["expires_at"])
        if expires is not None and expires < self.clock.now_utc():
            return None
        return dict(row)

    async def load_access_token(self, token: str) -> AccessToken | None:
        row = self._load_token_row(token, "access")
        if row is None:
            return None
        expires = parse_iso(row["expires_at"])
        return AccessToken(
            token=token,
            client_id=row["client_id"],
            scopes=row["scopes"].split(),
            expires_at=int(expires.timestamp()) if expires else None,
            resource=self.resource_url,
            subject=row["user_id"],
            claims={"iss": self.base_url},
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        row = self._load_token_row(refresh_token, "refresh")
        if row is None or row["client_id"] != client.client_id:
            return None
        expires = parse_iso(row["expires_at"])
        return RefreshToken(
            token=refresh_token,
            client_id=row["client_id"],
            scopes=row["scopes"].split(),
            expires_at=int(expires.timestamp()) if expires else None,
            resource=self.resource_url,
            subject=row["user_id"],
        )

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        """Rotate: revoke the presented refresh token and issue a new access + refresh pair."""
        now = self.clock.now_utc()
        granted = [s for s in scopes if s in refresh_token.scopes] or list(refresh_token.scopes)
        subject = refresh_token.subject or ""
        if not subject:
            raise TokenError("invalid_grant", "refresh token has no subject")
        token: OAuthToken | None = None
        with self.db.tx() as conn:
            rotated = conn.execute(
                update(dbm.oauth_tokens)
                .where(
                    dbm.oauth_tokens.c.token == hash_token(refresh_token.token),
                    dbm.oauth_tokens.c.kind == "refresh",
                    dbm.oauth_tokens.c.revoked == 0,
                )
                .values(revoked=1)
            )
            if (rotated.rowcount or 0) > 0:
                token = self._issue_pair(conn, client.client_id, subject, granted, now)
        if token is None:
            raise TokenError("invalid_grant", "refresh token is no longer valid")
        return token

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        """Revoke the presented token and every sibling issued to the same client for the same user."""
        row = self._load_token_row(token.token, "access") or self._load_token_row(token.token, "refresh")
        if row is None:
            return
        with self.db.tx() as conn:
            conn.execute(
                update(dbm.oauth_tokens)
                .where(
                    dbm.oauth_tokens.c.client_id == row["client_id"],
                    dbm.oauth_tokens.c.user_id == row["user_id"],
                )
                .values(revoked=1)
            )

    def revoke_user_tokens(self, user_id: str) -> int:
        """Revoke every token and pending code for a user (account deletion, password reset)."""
        with self.db.tx() as conn:
            res = conn.execute(
                update(dbm.oauth_tokens)
                .where(dbm.oauth_tokens.c.user_id == user_id, dbm.oauth_tokens.c.revoked == 0)
                .values(revoked=1)
            )
            conn.execute(delete(dbm.oauth_codes).where(dbm.oauth_codes.c.user_id == user_id))
        return res.rowcount or 0


def build_auth_settings(settings: Settings) -> AuthSettings:
    """AuthSettings for the hosted server: issuer = public_url, resource = public_url + '/mcp', scope 'parlay'."""
    if not settings.public_url:
        raise ValueError("public_url is required in hosted mode")
    base = settings.public_url.rstrip("/")
    return AuthSettings(
        issuer_url=base,
        resource_server_url=base + "/mcp",
        client_registration_options=ClientRegistrationOptions(
            enabled=True, valid_scopes=[SCOPE], default_scopes=[SCOPE]
        ),
        revocation_options=RevocationOptions(enabled=True),
        required_scopes=[SCOPE],
        validate_token_resource=True,
    )
