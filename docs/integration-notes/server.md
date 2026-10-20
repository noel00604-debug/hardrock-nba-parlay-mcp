# Integration notes: server (mcp_server.py, auth.py, web.py, cli.py, dashboard.py)

Updated 2026-10-19 (evening) after the independent review (`tests/test_server_review.py`): DCR redirect-URI
allowlist + consent line, redaction of ServiceError text everywhere, keychain failures without the value, exact
three legs at the tool boundary, schema reason codes surfaced, TypeError as internal error, loopback-only
authless HTTP bind.

Requests for the integration lead, plus decisions other modules should know about. No foundation file was edited.

## Requests against the foundation / contract

1. `db.py`: the SQLite `begin` hook issues `BEGIN IMMEDIATE` for every transaction, including the autobegin that
   SQLAlchemy starts for a plain `SELECT` on `engine.connect()`. A read connection therefore holds the write lock
   until it is closed, and opening `db.tx()` while an `engine.connect()` block is still open deadlocks for
   `busy_timeout` (5 s) and then raises `database is locked`. The server module never nests them; other modules
   should not either (or the lead could gate the hook on `conn.get_execution_options()` / skip it for reads).
2. `ARCHITECTURE.md` section 9 / the brief name `http://testserver` as the hosted test URL. The installed SDK's
   `validate_issuer_url` only accepts plain `http` for `localhost`, `127.0.0.1`, `[::1]`; everything else must be
   `https`. The hosted tests therefore use `public_url = "http://localhost"` (same ASGI transport, no network).
3. `Settings.http_json_response` (added by the lead) is used as the streamable-HTTP `json_response` flag.
   `web.create_app(..., json_response=...)` overrides it (tests pass `True` so responses are plain JSON).
4. `auth_mode == "external_jwt"` is not implemented; `build_server` raises `NotImplementedError` for it.
5. `services.export_my_data` may return either `schemas.ExportBundle` or a plain dict; the MCP tool dumps either
   into `dict[str, Any]`. Every other tool is annotated with the exact `schemas` response model
   (`SlateResponse`, `BuildResponse`, `RecordResponse`, ...), so services must return those models.
6. `docs/privacy-policy.md` and `docs/terms.md` are served verbatim by `GET /privacy` and `GET /terms` (release
   owner). Until they exist a placeholder says the operator must publish them.

## How the server calls services (pipeline owner, please confirm)

- `mcp_server.make_request_context(svc, user_id=..., clock=..., db=..., settings=...)` calls
  `services.RequestContext(user_id=, clock=, db=, settings=, providers=None)` (keyword first, positional fallback).
  If `services.build_providers(ctx)` exists it is called once and its result is assigned to `ctx.providers`
  (attribute assignment, else the context is rebuilt with it). If it does not exist, `providers` stays `None`.
- Tool argument order follows ARCHITECTURE section 5 exactly, e.g. `check_data_coverage(ctx, date_local,
  probe_props=...)`, `select_ticket(ctx, candidate_id, stake_usd: Decimal, idempotency_key)`,
  `get_daily_budget(ctx, date_local, proposed_stake_usd)`, `record_actual_bet(ctx, ticket, idempotency_key)`,
  `set_user_settings(ctx, daily_cap_usd, display_tz, odds_api_key, confirm_onboarding)`, `add_cost(ctx, CostInput)`.
- `date_local` defaults to today in America/New_York (`config.local_date(clock.now_utc())`) when a tool caller omits it.
- Any `errors.ServiceError` becomes `schemas.ToolError(error=message, reason_codes, detail)` with `error` and
  `detail` passed through `config.redact` and capped (500 / 1000 chars): a `ProviderError` may quote the failing
  request URL, but `apiKey=...`, `Bearer ...`, and the configured secrets never reach the model, the CLI, or a web
  page. Pydantic validation errors become `INVALID_INPUT` and additionally carry every section-7 reason code that a
  `schemas.py` validator message starts with (`NOT_THREE_LEGS`, `DUPLICATE_SELECTION`, `QUOTE_FIELDS_MISSING`,
  `QUOTE_SIGN_AMBIGUOUS`, ...), e.g. `["QUOTE_FIELDS_MISSING", "INVALID_INPUT"]`, plus the field path and message in
  `detail`. A `ValueError` from services is `INVALID_INPUT`; a `TypeError` (signature drift) and every other
  exception is `PROVIDER_ERROR` / "internal error" with only the class name (message logged through
  `config.redact`). No traceback ever reaches the client. The same conversion is exported as
  `mcp_server.tool_error_from_validation` / `reason_codes_from_validation` and used by the CLI.
- `auth.ensure_user(db, user_id, now, settings)` runs before every service call, so `users` and `user_settings`
  rows always exist (cap = `settings.daily_cap_usd_default`, `onboarding_complete = 0`).

## MCP wire details (release / plugin owner)

- Server name `NBA Three-Leg Parlay Analyst`; 20 tools, names in `mcp_server.TOOL_NAMES`, all <= 64 chars, each
  with `title`, all four `ToolAnnotations` hints set explicitly, pydantic input models, and an output schema.
- Because each tool is annotated `Model | ToolError`, the SDK wraps structured output: `structuredContent` is
  `{"result": {...}}` and the text block is the JSON of the returned model. Clients reading structured output
  must take `result`.
- `select_ticket`, `record_actual_bet`, `reconcile_settlement` carry `_meta {"anthropic/requiresUserInteraction": true}`.
- Exactly three legs is enforced at the tool boundary, not only in services: `analyze_my_parlay.three_selections`
  is `minItems: 3, maxItems: 3` in the input schema (the SDK rejects other counts before the tool runs) and the tool
  returns `NOT_THREE_LEGS` itself as a second guard; `record_actual_bet` returns `NOT_THREE_LEGS` when
  `external` is false and `legs` is not exactly three (any count with `external: true`, recorded truthfully) and
  `INVALID_INPUT` for no legs. `hrnba record-bet` applies the same rule. Distinctness stays with
  `ThreeLegTicket` / `correlation.hard_rejections` (the pasted `game` text cannot be compared reliably).
- Hosted OAuth: issuer = `public_url`, resource = `public_url + "/mcp"`, single scope `parlay`, DCR enabled, PKCE
  S256 (enforced by the SDK token handler), refresh rotation, revocation. Unauthenticated `/mcp` gets 401 with
  `WWW-Authenticate: Bearer ... resource_metadata="<public_url>/.well-known/oauth-protected-resource/mcp"`.
- `AuthSettings.validate_token_resource=True`; every issued token is stamped with our resource URL, so the SDK's
  audience check always passes for our own tokens and the deprecation warning about the unset flag is avoided.
- Loopback redirect URIs (Claude Code, `http://localhost:<port>/callback`) match a registered
  `http://localhost/callback` with the port ignored (`auth.RegisteredClient.validate_redirect_uri`); every other
  redirect URI must match exactly (`https://claude.ai/api/mcp/auth_callback`).
- DCR is open (Claude registers a client per connection), so `POST /register` only accepts redirect URIs from
  Claude's documented set (docs/research/claude-directory-connectors.md): exactly
  `https://claude.ai/api/mcp/auth_callback`, or plain-http loopback (`localhost`, `127.0.0.1`, `[::1]`) on any port
  with path `/callback` or `/` and no query/fragment/userinfo. Anything else is `400 invalid_redirect_uri`
  (`auth.check_redirect_uris`, `auth.redirect_uri_allowed`). The same check runs in `authorize` (`invalid_request`)
  and `complete_login`, so a client row stored before this rule cannot be used either. Without it, anyone could
  register `https://attacker.test/cb` and phish an authorization code through our genuine `/login` page.
  The `claude.com` callback variant is not allowlisted: no official page documents it (research note, item 2); if
  Claude ever sends it, add it to `auth.ALLOWED_REDIRECT_URIS`.
- `/login?req=...` and `/signup?req=...` are a consent step: the page names the registered `client_name` and the
  redirect host (scheme + host only) before the password field, the button reads "Sign in and connect", and an
  invalid or expired `req` is said so on the page (the form still renders, HTTP 200).
- SDK quirk: `POST /revoke` requires a `client_secret` form field even for public clients (send it empty).
- Storage: only SHA-256 hashes of codes, access tokens, and refresh tokens are stored. Registered client JSON is
  stored as received; for a client that asked for `client_secret_post`/`client_secret_basic` that JSON includes
  the minted secret because the SDK's `ClientAuthenticator` compares it in plaintext. Claude's clients register
  with `token_endpoint_auth_method: "none"`, so no secret is minted for them.
- Revoking one token revokes every token issued to the same (client_id, user_id); DCR gives each Claude
  connection its own client_id, so this equals "disconnect this connection".
- Login: argon2id (`argon2-cffi` defaults), 10 failures per 15 minutes per email and per client key
  (`X-Forwarded-For` first hop, else the socket peer) -> HTTP 429; the hasher always runs even for unknown emails.
- Session cookie `hrnba_session` (Starlette `SessionMiddleware`, `settings.secret_key`, SameSite=Lax, Secure when
  `public_url` is https) is used only by `/account*`; `/mcp` never reads it.
- `web.transport_security_for(settings)` allows the `public_url` host (with and without port) plus loopback
  variants; behind Fly/Railway/Cloudflare the `Host` header must be the public hostname (uvicorn runs with
  `proxy_headers=True, forwarded_allow_ips="*"`).

## CLI

- `hrnba --json <command>`: the output flag is a global option and goes before the command name, because
  `import-quote`, `record-bet`, and `settle` use `--json FILE` for their input file.
- `hrnba serve --transport stdio` is the local MCP entry; `--transport http` runs uvicorn via `web.run_http`.
- `web.run_http` (and so `hrnba serve --transport http`) refuses to bind an unauthenticated endpoint beyond
  loopback: with `auth_mode == "none"` every `/mcp` caller is `local_user_id` with no bearer check, so the host must
  be `127.0.0.1`, `localhost`, or `::1` (`web.ensure_safe_bind`, `web.is_loopback_host`). `0.0.0.0`, `::`, or a LAN
  address raises `web.UnsafeBindError` (a `ServiceError` and `ValueError`, reason code `FORBIDDEN`) before the
  database is opened; the CLI prints it as a reason-coded error and exits 1. A non-loopback bind requires
  `HRNBA_AUTH_MODE=builtin_oauth` with `HRNBA_PUBLIC_URL` and `HRNBA_SECRET_KEY`. Release owner: README / install
  docs that mention `--host 0.0.0.0` should say this.
- `secret set NAME` stores in the macOS keychain (`security add-generic-password -U -s hardrock-nba-parlay -a NAME`)
  and in `data_dir/.env` (0600) elsewhere; `secret check NAME` prints only whether it resolves. When `security`
  fails or times out the CLI reports only the exit status and the scrubbed stderr (`cli._keychain_store`): the
  value is never echoed, because `subprocess` exception messages repeat the whole argv including `-w <value>`.
  The CLI catch-all likewise reports any `subprocess.SubprocessError` by class name only, and `cli._fail`
  redacts `error` / `detail` of every payload before printing. Residual exposure: the value is still an argv
  argument of `security` for the milliseconds it runs (visible to `ps` on the same Mac); `security` has no
  stdin option for `add-generic-password` short of its interactive `-i` mode, whose tokenizer is not safe for
  arbitrary values.
- `db backup FILE` / `db restore FILE` use the sqlite3 backup API after `PRAGMA wal_checkpoint(TRUNCATE)`; for
  PostgreSQL they print the `pg_dump` / `pg_restore` command with the password masked.
- `import-selections FILE` uses `providers.manual.load_csv/load_json` when present, else built-in CSV/JSON parsing
  into `ManualSelectionInput`, then `services.analyze_my_parlay`.
- `dashboard` uses `reports.dashboard_html(review.performance, budget_today)` when importable, else the generic
  escaped renderer in `dashboard.render_report_html`.
