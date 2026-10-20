"""Hosted Starlette app: the MCP streamable-HTTP endpoint plus the OAuth login/signup/account pages.

Routes served by the MCP SDK (mounted): ``/mcp``, ``/.well-known/oauth-authorization-server``,
``/.well-known/oauth-protected-resource/mcp``, ``/authorize``, ``/token``, ``/register``, ``/revoke``.
Routes served here: ``/``, ``/login``, ``/signup``, ``/account``, ``/account/export``, ``/account/delete``,
``/healthz``, ``/privacy``, ``/terms``.

Every /mcp request without a valid bearer token gets HTTP 401 with a ``WWW-Authenticate`` header whose
``resource_metadata`` points at the protected-resource metadata URL (SDK ``RequireAuthMiddleware``).

With ``auth_mode == "none"`` the HTTP transport has no bearer check at all (every caller is
``settings.local_user_id``), so ``run_http`` only binds it to a loopback interface; a non-loopback bind
requires ``auth_mode == "builtin_oauth"`` (``UnsafeBindError``, reason code ``FORBIDDEN``).
"""

from __future__ import annotations

import html
import ipaddress
import json
import logging
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import anyio
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Mount, Route

from . import auth, config
from . import schemas as S
from .config import Clock, Settings, SystemClock, mask_user_id
from .db import Database, open_database
from .errors import InvalidInput, ServiceError
from .mcp_server import build_server

logger = logging.getLogger(__name__)

DELETE_CONFIRMATION = "DELETE MY DATA"
_DOCS_DIR = Path(__file__).resolve().parents[2] / "docs"
ERROR_TEXT_MAX = 300

_CSS = (
    "body{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:560px;margin:40px auto;padding:0 16px;color:#1b1b1b}"
    "label{display:block;margin:12px 0 4px}input[type=text],input[type=email],input[type=password]{width:100%;padding:8px;box-sizing:border-box}"
    "button{margin-top:16px;padding:10px 16px;border:0;background:#1b4fd8;color:#fff;cursor:pointer}"
    ".err{color:#b00020}.muted{color:#666;font-size:0.9em}.danger{background:#b00020}"
    ".consent{border:1px solid #c9d4f5;background:#f3f6ff;padding:12px;border-radius:6px}"
)


class UnsafeBindError(ServiceError, ValueError):
    """Refusing to bind an unauthenticated (``auth_mode == "none"``) MCP endpoint to a non-loopback interface."""

    def __init__(self, host: str, auth_mode: str) -> None:
        super().__init__(
            "refusing to serve an unauthenticated MCP endpoint on a non-loopback host",
            ["FORBIDDEN"],
            f"host={host!r} auth_mode={auth_mode!r}: bind to 127.0.0.1 (or localhost) for local testing, or set "
            "HRNBA_AUTH_MODE=builtin_oauth with HRNBA_PUBLIC_URL and HRNBA_SECRET_KEY for a hosted deployment",
        )


def is_loopback_host(host: str | None) -> bool:
    """True for ``localhost`` and loopback IP literals (``127.0.0.0/8``, ``::1``), with or without brackets."""
    value = (host or "").strip().strip("[]").lower()
    if value == "localhost":
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def ensure_safe_bind(settings: Settings, host: str | None = None) -> str:
    """Return the host to bind, or raise ``UnsafeBindError`` when it is not loopback and auth is off."""
    bind = host or settings.host
    if settings.auth_mode != "builtin_oauth" and not is_loopback_host(bind):
        raise UnsafeBindError(bind, settings.auth_mode)
    return bind


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _page(title: str, body: str) -> HTMLResponse:
    doc = (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{_e(title)}</title><style>{_CSS}</style></head><body>"
        f"<h1>{_e(title)}</h1>{body}"
        f'<p class="muted">{_e(S.AI_DISCLOSURE)}</p>'
        '<p class="muted"><a href="/">Home</a> · <a href="/privacy">Privacy</a> · <a href="/terms">Terms</a></p>'
        "</body></html>"
    )
    return HTMLResponse(doc)


def _page_status(title: str, body: str, status_code: int) -> HTMLResponse:
    response = _page(title, body)
    response.status_code = status_code
    return response


def _err_text(exc: ServiceError) -> str:
    """User-facing text for a ServiceError: redacted (never a key or token) and capped in length."""
    text = config.redact(exc.message + (f": {exc.detail}" if exc.detail else ""))
    return text if len(text) <= ERROR_TEXT_MAX else text[: ERROR_TEXT_MAX - 3] + "..."


def _str_field(form: Any, name: str) -> str:
    value = form.get(name)
    return value if isinstance(value, str) else ""


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64] or "unknown"
    return (request.client.host if request.client else "") or "unknown"


def transport_security_for(settings: Settings) -> TransportSecuritySettings:
    """DNS-rebinding protection: allow the public hostname (with and without port) plus loopback variants."""
    hosts = {"localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*", "[::1]", "[::1]:*"}
    origins = {
        "http://localhost",
        "http://localhost:*",
        "http://127.0.0.1",
        "http://127.0.0.1:*",
        "http://[::1]",
        "http://[::1]:*",
        "https://localhost",
        "https://localhost:*",
    }
    if settings.public_url:
        parts = urlsplit(settings.public_url)
        if parts.hostname:
            hosts.update({parts.netloc, parts.hostname, f"{parts.hostname}:*"})
            origins.update(
                {
                    f"{parts.scheme}://{parts.netloc}",
                    f"{parts.scheme}://{parts.hostname}",
                    f"{parts.scheme}://{parts.hostname}:*",
                }
            )
    if settings.host and settings.host not in ("0.0.0.0", "::"):
        hosts.update({settings.host, f"{settings.host}:*"})
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=sorted(hosts),
        allowed_origins=sorted(origins),
    )


def _read_doc(name: str, placeholder: str) -> PlainTextResponse:
    for base in (_DOCS_DIR, Path.cwd() / "docs"):
        path = base / name
        try:
            if path.is_file():
                return PlainTextResponse(path.read_text(encoding="utf-8"))
        except OSError:
            continue
    return PlainTextResponse(placeholder)


def create_app(
    settings: Settings,
    db: Database,
    clock: Clock,
    services: Any | None = None,
    *,
    json_response: bool | None = None,
) -> Starlette:
    """Build the hosted Starlette app. ``json_response`` overrides ``settings.http_json_response``."""
    hosted = settings.auth_mode == "builtin_oauth"
    provider: auth.DbOAuthProvider | None = auth.DbOAuthProvider(db, settings, clock) if hosted else None
    server = build_server(settings, db, clock, services, auth_provider=provider)
    mcp_app = server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=settings.http_json_response if json_response is None else json_response,
        transport_security=transport_security_for(settings),
    )
    if settings.secret_key is not None and settings.secret_key.get_secret_value():
        session_secret = settings.secret_key.get_secret_value()
    elif hosted:
        raise ValueError("HRNBA_SECRET_KEY is required in hosted mode")
    else:
        session_secret = secrets.token_urlsafe(32)
    https_only = bool(settings.public_url and settings.public_url.startswith("https://"))

    # ---- pages ----

    async def landing(request: Request) -> Response:
        body = (
            "<p>Research assistant for exactly-three-leg NBA parlays on Hard Rock Bet (Florida), used through "
            "Claude as an MCP connector.</p>"
            "<p><strong>AI disclosure.</strong> Analysis is produced with AI assistance. You decide and place every "
            "wager yourself in the Hard Rock Bet app. This service never places bets, moves money, or guarantees "
            "outcomes. The default budget ledger is $10 per America/New_York day.</p>"
            '<p><a href="/signup">Create account</a> · <a href="/login">Sign in</a> · <a href="/account">My account</a></p>'
            f'<p class="muted">MCP endpoint: <code>{_e(settings.public_url or "")}/mcp</code></p>'
        )
        return _page("NBA Three-Leg Parlay Analyst", body)

    async def consent_banner(req: str) -> str:
        """The consent step for an OAuth login: who is asking and where the browser goes afterwards.

        Rendered above the login and signup forms whenever a signed request token is present, so a user who
        followed a link can see the client name and the redirect host before typing a password.
        """
        if not req or provider is None:
            return ""
        try:
            data = provider.login_request_from_token(req)
            info = await provider.describe_login_request(data)
        except ServiceError:
            return (
                '<p class="err">This connection link is invalid or has expired. Start the connection again '
                "from Claude.</p>"
            )
        return (
            f'<p class="consent"><strong>{_e(info["client_name"])}</strong> is asking to connect to your account. '
            f"After you sign in, your browser will be sent to <code>{_e(info['redirect_host'])}</code> with a "
            "one-time code that lets that client use the parlay tools as you. Continue only if you started this "
            "connection yourself in Claude.</p>"
        )

    def login_form(req: str, error: str | None = None, email: str = "", banner: str = "") -> str:
        err = f'<p class="err">{_e(error)}</p>' if error else ""
        return (
            f'{banner}{err}<form method="post" action="/login">'
            f'<input type="hidden" name="req" value="{_e(req)}">'
            f'<label for="email">Email</label><input id="email" type="email" name="email" value="{_e(email)}" autocomplete="username" required>'
            '<label for="password">Password</label><input id="password" type="password" name="password" autocomplete="current-password" required>'
            f'<button type="submit">{"Sign in and connect" if req else "Sign in"}</button></form>'
            f'<p class="muted">No account yet? <a href="/signup{"?req=" + _e(req) if req else ""}">Create one</a>.</p>'
        )

    async def finish_oauth_or_account(request: Request, req: str, user_id: str) -> Response:
        if req and provider is not None:
            try:
                data = provider.login_request_from_token(req)
                target = provider.complete_login(data, user_id, clock.now_utc())
            except InvalidInput as exc:
                return _page_status("Sign in", f'<p class="err">{_e(_err_text(exc))}</p>', 400)
            return RedirectResponse(target, status_code=302, headers={"Cache-Control": "no-store"})
        return RedirectResponse("/account", status_code=303)

    async def login(request: Request) -> Response:
        if request.method == "GET":
            req = request.query_params.get("req", "")
            return _page("Sign in", login_form(req, banner=await consent_banner(req)))
        form = await request.form()
        req = _str_field(form, "req")
        email = _str_field(form, "email")
        password = _str_field(form, "password")
        try:
            user_id = await anyio.to_thread.run_sync(
                auth.login, db, email, password, clock.now_utc(), _client_key(request)
            )
        except auth.LoginRateLimited as exc:
            banner = await consent_banner(req)
            return _page_status("Sign in", login_form(req, _err_text(exc), email, banner), 429)
        except ServiceError as exc:
            banner = await consent_banner(req)
            return _page_status("Sign in", login_form(req, _err_text(exc), email, banner), 401)
        request.session["user_id"] = user_id
        return await finish_oauth_or_account(request, req, user_id)

    def signup_form(req: str, error: str | None = None, email: str = "", banner: str = "") -> str:
        err = f'<p class="err">{_e(error)}</p>' if error else ""
        return (
            f'{banner}{err}<form method="post" action="/signup">'
            f'<input type="hidden" name="req" value="{_e(req)}">'
            f'<label for="email">Email</label><input id="email" type="email" name="email" value="{_e(email)}" autocomplete="username" required>'
            f'<label for="password">Password (at least {auth.MIN_PASSWORD_LENGTH} characters)</label>'
            '<input id="password" type="password" name="password" autocomplete="new-password" required>'
            '<label for="password2">Repeat password</label><input id="password2" type="password" name="password2" autocomplete="new-password" required>'
            '<label><input type="checkbox" name="age_attest" value="yes" required> I confirm that I am of legal '
            "wagering age in my jurisdiction and that I place every wager myself.</label>"
            f'<button type="submit">{"Create account and connect" if req else "Create account"}</button></form>'
        )

    async def signup(request: Request) -> Response:
        if request.method == "GET":
            req = request.query_params.get("req", "")
            return _page("Create account", signup_form(req, banner=await consent_banner(req)))
        form = await request.form()
        req = _str_field(form, "req")
        email = _str_field(form, "email")
        password = _str_field(form, "password")
        password2 = _str_field(form, "password2")
        attest = _str_field(form, "age_attest")
        if password != password2:
            banner = await consent_banner(req)
            return _page_status(
                "Create account", signup_form(req, "passwords do not match", email, banner), 400
            )
        if attest != "yes":
            banner = await consent_banner(req)
            return _page_status(
                "Create account",
                signup_form(req, "you must confirm your legal wagering age", email, banner),
                400,
            )
        try:
            user_id = await anyio.to_thread.run_sync(
                auth.signup, db, email, password, clock.now_utc(), settings
            )
        except ServiceError as exc:
            banner = await consent_banner(req)
            return _page_status("Create account", signup_form(req, _err_text(exc), email, banner), 400)
        request.session["user_id"] = user_id
        return await finish_oauth_or_account(request, req, user_id)

    async def account(request: Request) -> Response:
        user_id = request.session.get("user_id")
        if not isinstance(user_id, str) or not user_id:
            return RedirectResponse("/login", status_code=303)
        body = (
            f"<p>Signed in as <code>{_e(mask_user_id(user_id))}</code>.</p>"
            '<form method="post" action="/account/export"><button type="submit">Download my data (JSON)</button></form>'
            "<h2>Delete my account</h2>"
            f"<p>This removes every record stored for you and revokes every connection. Type <code>{_e(DELETE_CONFIRMATION)}</code> to confirm.</p>"
            '<form method="post" action="/account/delete">'
            '<label for="confirm">Confirmation</label><input id="confirm" type="text" name="confirm" autocomplete="off">'
            '<button type="submit" class="danger">Delete my data</button></form>'
            '<form method="post" action="/logout"><button type="submit">Sign out</button></form>'
        )
        return _page("My account", body)

    async def account_export(request: Request) -> Response:
        user_id = request.session.get("user_id")
        if not isinstance(user_id, str) or not user_id:
            return RedirectResponse("/login", status_code=303)
        from .services import scrub_export_bundle

        bundle = scrub_export_bundle(await anyio.to_thread.run_sync(db.export_user, user_id))
        payload = {
            "user_id_masked": mask_user_id(user_id),
            "exported_at_utc": clock.now_utc().isoformat(),
            "tables": bundle,
        }
        return Response(
            json.dumps(payload, default=str, indent=2),
            media_type="application/json",
            headers={
                "Content-Disposition": 'attachment; filename="hardrock-nba-parlay-export.json"',
                "Cache-Control": "no-store",
            },
        )

    async def account_delete(request: Request) -> Response:
        user_id = request.session.get("user_id")
        if not isinstance(user_id, str) or not user_id:
            return RedirectResponse("/login", status_code=303)
        form = await request.form()
        if _str_field(form, "confirm").strip() != DELETE_CONFIRMATION:
            return _page_status(
                "My account",
                f'<p class="err">Type {_e(DELETE_CONFIRMATION)} exactly to delete your data.</p>',
                400,
            )
        if provider is not None:
            await anyio.to_thread.run_sync(provider.revoke_user_tokens, user_id)
        counts = await anyio.to_thread.run_sync(db.delete_user, user_id)
        request.session.clear()
        logger.info("deleted user %s (%s rows)", mask_user_id(user_id), sum(counts.values()))
        return _page("Account deleted", "<p>Your data has been deleted and every connection revoked.</p>")

    async def logout(request: Request) -> Response:
        request.session.clear()
        return RedirectResponse("/", status_code=303)

    async def healthz(request: Request) -> Response:
        return JSONResponse({"status": "ok", "version": settings.version})

    async def privacy(request: Request) -> Response:
        return _read_doc(
            "privacy-policy.md",
            "Privacy policy: the operator of this server must publish docs/privacy-policy.md before use.",
        )

    async def terms(request: Request) -> Response:
        return _read_doc(
            "terms.md", "Terms of service: the operator of this server must publish docs/terms.md before use."
        )

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        async with server.session_manager.run():
            yield

    routes = [
        Route("/", landing, methods=["GET"]),
        Route("/login", login, methods=["GET", "POST"]),
        Route("/signup", signup, methods=["GET", "POST"]),
        Route("/account", account, methods=["GET"]),
        Route("/account/export", account_export, methods=["POST"]),
        Route("/account/delete", account_delete, methods=["POST"]),
        Route("/logout", logout, methods=["POST"]),
        Route("/healthz", healthz, methods=["GET"]),
        Route("/privacy", privacy, methods=["GET"]),
        Route("/terms", terms, methods=["GET"]),
        Mount("/", app=mcp_app),
    ]
    app = Starlette(
        routes=routes,
        middleware=[
            Middleware(
                SessionMiddleware,
                secret_key=session_secret,
                session_cookie="hrnba_session",
                max_age=12 * 3600,
                same_site="lax",
                https_only=https_only,
            )
        ],
        lifespan=lifespan,
    )
    app.state.mcp_server = server
    app.state.oauth_provider = provider
    return app


def run_http(settings: Settings, host: str | None = None, port: int | None = None) -> None:
    """Serve the hosted app with uvicorn (proxy headers trusted, for Fly/Railway/Cloudflare style fronting).

    Raises ``UnsafeBindError`` before anything is opened when ``auth_mode`` is not ``builtin_oauth`` and the
    bind host is not loopback: an authless ``/mcp`` must never be reachable from the network.
    """
    import uvicorn

    bind_host = ensure_safe_bind(settings, host)
    config.configure_logging(settings.log_level)
    db = open_database(settings.effective_database_url, allow_fixture_ledger=settings.allow_fixture_ledger)
    app = create_app(settings, db, SystemClock())
    uvicorn.run(
        app,
        host=bind_host,
        port=port or settings.port,
        proxy_headers=True,
        forwarded_allow_ips="*",
        log_level=settings.log_level.lower(),
    )
