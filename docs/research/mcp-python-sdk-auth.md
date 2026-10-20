# Research notes: MCP Python SDK (version, Streamable HTTP, OAuth AS/RS, annotations, structured output)

KEY: `mcp-python-sdk-auth`
Research run: 2026-10-19, 23:03Z to 23:10Z (America/New_York evening). All times below are UTC from `date -u`; each fetch batch is anchored to the nearest `date -u` reading, so individual retrieval times are accurate to about one minute.

Everything quoted here was read from the web or from source files downloaded from GitHub. Page text was treated as data; nothing in it was followed as an instruction.

---

## 0. Headline conclusions for this build

1. **The official SDK is now the v2 line.** `mcp` 2.3.0 is the latest stable on PyPI (uploaded 2026-10-02T22:06:56Z). `pip install mcp` installs 2.x. v1.x (last: 1.30.0, 2026-09-07) is in maintenance mode.
2. **The API names assumed in the task brief are v1 names.** In v2, `FastMCP` is `MCPServer` (`from mcp.server import MCPServer`), `mcp.get_context()` is gone (declare `ctx: Context`), `Context.client_id` is gone (use `get_access_token()`), and all transport settings (`host`, `port`, `streamable_http_path`, `json_response`, `stateless_http`, ...) moved from the constructor to `run()` / `streamable_http_app()`. Importing `mcp.server.fastmcp` now raises a pointer to the migration guide.
3. **`fastmcp` on PyPI (jlowin) is a different, third-party project** (4.1.1, 2026-10-18). Do not use it; the brief requires the official SDK.
4. **The current MCP spec revision is 2026-07-28**, and the SDK 2.x implements it while serving 2025-era clients from the same app with no configuration. Anthropic's own docs say Claude's client follows the 2025-03-26 / 2025-06-18 / 2025-11-25 authorization specs and registers via Dynamic Client Registration by default, so in practice Claude will hit the SDK's legacy (session-based) path.
5. **Auth architecture to use: Resource Server mode** (`token_verifier=` + `AuthSettings(...)`). The SDK docs explicitly say the embedded authorization server (`auth_server_provider=`) "predates the AS/RS separation" and "new servers should not use it"; however the SDK still ships `create_auth_routes()` to host a separate AS, which is exactly what the `simple-auth` example does.
6. **Identity in a tool:** `from mcp.server.auth.middleware.auth_context import get_access_token` returns the verifier's `AccessToken` (`client_id`, `scopes`, `subject`, `expires_at`, `resource`, `claims`). Scope all ledger rows to `subject` (plus issuer from `claims["iss"]`), never to a model-supplied `user_id`.
7. **Deployment gotcha:** the SDK's DNS-rebinding protection auto-enables for localhost hosts and, behind a real hostname, returns `421` for every request until you pass `TransportSecuritySettings(allowed_hosts=[...], allowed_origins=[...])`.

---

## 1. Latest stable release (Question 1)

### 1.1 `mcp` on PyPI

From `https://pypi.org/pypi/mcp/json` (fetched 2026-10-19T23:05Z via curl):

- `version: 2.3.0`
- `requires_python: >=3.10`
- `summary: Model Context Protocol SDK`
- Upload time of 2.3.0: `2026-10-02T22:06:56`
- `requires_dist` (runtime): `anyio>=4.9` (`>=4.10` on 3.14), `httpx2>=2.10.0`, `jsonschema>=4.20.0`, `mcp-types==2.3.0`, `opentelemetry-api>=1.28.0`, `pydantic>=2.12.0`, `pyjwt[crypto]>=2.10.1`, `python-multipart>=0.0.9`, `pywin32>=311 (win32)`, `sse-starlette>=3.0.0`, `starlette>=0.27` (`>=0.48.0` on 3.14), `typing-extensions>=4.13.0`, `typing-inspection>=0.4.1`, `uvicorn>=0.31.1`.
- Extras: `cli` adds `python-dotenv>=1.0.0`, `typer>=0.16.0`; `rich` adds `rich>=13.9.4`.
- Note: the HTTP client dependency is **`httpx2`**, not `httpx`. The What's-new page: "`httpx` was replaced by `httpx2`, which verifies TLS through the OS trust store."

Recent release timeline (PyPI upload times, UTC):

| Version | Uploaded | Line |
|---|---|---|
| 1.27.0 | 2026-04-02 | v1 |
| 1.27.1 | 2026-05-08 | v1 |
| 1.27.2 | 2026-05-29 | v1 |
| 2.0.0a1 | 2026-06-11 | v2 pre |
| 1.28.0 | 2026-06-16 | v1 |
| 2.0.0b1 / b2 | 2026-06-30 / 2026-07-14 | v2 pre |
| 2.0.0rc1 | 2026-07-27 | v2 pre |
| 1.29.0 | 2026-07-28 | v1 |
| **2.0.0** | **2026-07-28** | v2 stable |
| 1.29.1 | 2026-08-24 | v1 |
| 2.1.0 | 2026-08-24 | v2 |
| 2.1.1 | 2026-08-25 | v2 |
| 2.0.1 | 2026-08-26 | v2 backport |
| 1.30.0 | 2026-09-07 | v1 (maintenance) |
| 2.2.0 | 2026-09-07 | v2 |
| **2.3.0** | **2026-10-02** | **v2 latest** |

GitHub Releases API (`published_at`) agrees: v2.3.0 2026-10-02T22:02:27Z; v2.2.0 2026-09-07T15:53:57Z; v2.0.0 2026-07-28T13:41:36Z.

### 1.2 Python requirement: a discrepancy to record

- PyPI metadata for 2.3.0 and the tagged `v2.3.0` `pyproject.toml` say `requires-python = ">=3.10"`.
- The docs home and installation page say "**Python 3.11+**".
- `pyproject.toml` on `main` already says `requires-python = ">=3.11"`, so the next release will drop 3.10.
- Decision: target Python 3.11 or newer (3.12 is a safe choice).

### 1.3 `mcp-types`

`https://pypi.org/pypi/mcp-types/json`: version 2.3.0, uploaded 2026-10-02T22:06:57, `requires_python >=3.10`, deps only `pydantic>=2.12.0`, `typing-extensions>=4.13.0`. `mcp` pins `mcp-types==2.3.0` exactly (lock-step); the PyPI page says "The `mcp` package re-exports these names, so existing `from mcp import Tool` imports keep working." Python attributes are snake_case (`input_schema`), JSON stays camelCase.

### 1.4 `fastmcp` (jlowin) is not the official SDK

`https://pypi.org/pypi/fastmcp/json`: version 4.1.1, uploaded 2026-10-18T02:14:16, author "Jeremiah Lowin, Nate Nowack", `requires_python >=3.10`, summary "The fast, Pythonic way to build MCP servers and clients." Its README states "FastMCP 1.0 was incorporated into the official MCP Python SDK in 2024." It lists no `mcp` dependency. It is a separate, actively developed third-party project with its own 2.x/3.x/4.x API and upgrade guides. **Not to be used for this build.**

---

## 2. Server API in v2 (Question 2)

### 2.1 Creating a server

Docs home quickstart (verbatim):

```python
from mcp.server import MCPServer

mcp = MCPServer("Demo")

@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b
```

Constructor (from `src/mcp/server/mcpserver/server.py` on `main`): positional order is `name, title, description, instructions, website_url, icons, version, auth_server_provider, token_verifier`, then keyword-only `tools, resources, extensions, debug, log_level, warn_on_duplicate_*, dependencies, lifespan, auth, resource_security, request_state_security, cache_hints, subscriptions, middleware`. Migration guide warning: "A v1 call that passed instructions positionally silently lands in `title`. Pass `instructions=` by keyword."

`mcp.settings` now holds only `debug`, `log_level`, `warn_on_duplicate_*`, `dependencies`, `lifespan`, `auth`. "`MCP_*` environment variables and `.env` files are no longer read."

### 2.2 `@mcp.tool()` and `ToolAnnotations`

Decorator signature (source, `main`):

```python
def tool(self, name=None, title=None, description=None,
         annotations: ToolAnnotations | None = None,
         icons: list[Icon] | None = None,
         meta: dict[str, Any] | None = None,
         structured_output: bool | None = None)
```

Docs example (Tools page, verbatim):

```python
from mcp.server import MCPServer
from mcp.types import ToolAnnotations

mcp = MCPServer("Bookshop")

@mcp.tool(
    title="Search the catalog",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
)
def search_books(query: str) -> str:
    """Search the catalog by title or author."""
    return f"Found 3 books matching {query!r}."
```

Python `ToolAnnotations` (from `src/mcp-types/mcp_types/_v2026_07_28/__init__.py`): fields `title: str | None = None`, `read_only_hint` (alias `readOnlyHint`), `destructive_hint` (alias `destructiveHint`), `idempotent_hint` (alias `idempotentHint`), `open_world_hint` (alias `openWorldHint`), all `bool | None = None`. Class docstring: "all properties in `ToolAnnotations` are **hints** ... Clients should never make tool use decisions based on `ToolAnnotations` received from untrusted servers."

Spec defaults (from `schema/2026-07-28/schema.ts`): `readOnlyHint` default **false**; `destructiveHint` default **true** ("meaningful only when `readOnlyHint == false`"); `idempotentHint` default **false**; `openWorldHint` default **true**. `Tool.annotations` docstring: "Display name precedence order is: `title`, `annotations.title`, then `name`."

Spec tools page: "clients **MUST** consider tool annotations to be untrusted unless they come from trusted servers." Tool names SHOULD be 1-128 chars from `[A-Za-z0-9_.-]`. `tools/list` "**MUST NOT** vary per-connection ... The set **MAY** vary by the authorization presented on the request". Servers SHOULD return tools in deterministic order.

### 2.3 Structured output (`outputSchema` / `structuredContent`)

Structured Output page: "the return type annotation is the output schema." Rules recorded:

- Pydantic `BaseModel` -> used directly, no wrapper; `Field(description=...)` appears in the schema. `TypedDict` and dataclasses also work.
- Scalars (`str`, `int`, `float`, `bool`, `bytes`, `None`) and lists/tuples/unions/`Optional` are wrapped as `{"result": ...}`.
- `dict[str, ...]` is not wrapped; `dict[int, ...]` falls back to the wrapper.
- Return values are validated against the schema before leaving the server; a mismatch yields `is_error=True` with "Error executing tool" and an ERROR log naming the field.
- `@mcp.tool(structured_output=False)` makes a tool text-only. `structured_output=True` makes a non-schema-capable return type raise at import time.
- Pitfall: a class whose body has no type annotations gets no schema and the model sees only its `repr`, "silently."
- v2.1.0 behaviour change: a tool annotated to return `TextContent`, `EmbeddedResource`, `Image`, `Audio` (or lists/unions) "no longer advertises `outputSchema` or returns `structuredContent`".

Spec: "For backwards compatibility, a tool that returns structured content SHOULD also return the serialized JSON in a TextContent block." `structuredContent` may be any JSON value; servers MUST conform to `outputSchema` if provided.

### 2.4 Context

Context page: annotate a parameter with `Context`; the SDK injects it and hides it from the input schema. Members: `ctx.request_id`, `ctx.session`, `ctx.headers` ("client-supplied ... never for identity"), `ctx.request_context` (its `lifespan_context` holds the lifespan object), `await ctx.read_resource(uri)`, `await ctx.report_progress(progress, total, message)`, `await ctx.elicit(...)`, `ctx.notify_tools_changed()` etc. for 2026-07-28 clients. `ctx.debug/info/warning/error(data=...)` exist but are deprecated under SEP-2577 ("Standard `import logging` to stderr" is the replacement). Source (`context.py`) confirms there is **no** `client_id` attribute. Migration guide: "`Context.client_id` was removed. Use the authenticated token instead" via `get_access_token()`.

### 2.5 Lifespan with typed context (DB handles)

Lifespan page example (condensed but structurally exact):

```python
@dataclass
class State:
    pool: Pool

@asynccontextmanager
async def lifespan(server: MCPServer) -> AsyncIterator[State]:
    pool = await Pool.open()
    try:
        yield State(pool=pool)
    finally:
        await pool.close()

app = MCPServer("Library", lifespan=lifespan)

@app.tool()
def count_items(topic: str, ctx: Context[State]) -> str:
    pool = ctx.request_context.lifespan_context.pool
```

"The lifespan runs once, so every request shares the same yielded object." Migration guide: for streamable HTTP "The lifespan is now entered once at manager startup and its state is shared across sessions and requests."

### 2.6 Running: `run()`, transports, settings

Run page and source:

- `mcp.run()` defaults to `stdio`. `mcp.run(transport="streamable-http", port=3001)` builds a Starlette app and serves it with uvicorn; default endpoint `http://127.0.0.1:8000/mcp`.
- `run()` streamable-http keyword options (source overload): `host` (default `127.0.0.1`), `port` (default 8000), `streamable_http_path` (default `/mcp`), `json_response` (default False), `stateless_http` (default False), `event_store`, `retry_interval`, `max_request_body_size` (default 4 MiB; larger -> HTTP 413), `session_idle_timeout` (default 1800 s), `max_sessions` (default 10,000), `transport_security`.
- "Transport options belong to `run()`, not the `MCPServer(...)` constructor. Passing `port=` to the constructor raises a `TypeError`."
- `json_response=True`: single JSON body per POST; mid-request `ctx.elicit()`/sampling raise `NoBackChannelError`; progress/log notifications dropped.
- `stateless_http=True`: new transport per request, no session tracking; affects only the legacy (pre-2026) path.
- `sse` transport still exists but "Don't use it for new work."
- CLI: `uv run mcp dev server.py` (Inspector), `uv run mcp run server.py --transport streamable-http`, `mcp install` (Claude Desktop), `mcp version`. `mcp run` only forwards `--transport`.
- Authorization page: "Authorization applies only to HTTP transports. `stdio` and the in-memory `Client(mcp)` skip it, so `token_verifier` is never consulted there."

### 2.7 `streamable_http_app()` and mounting into Starlette/uvicorn

Source signature: `streamable_http_app(*, streamable_http_path="/mcp", json_response=False, stateless_http=False, event_store=None, retry_interval=None, max_request_body_size=..., session_idle_timeout=1800, max_sessions=10000, transport_security=None, host="127.0.0.1") -> Starlette`.

ASGI page (verbatim example):

```python
mcp = MCPServer("Notes")

@asynccontextmanager
async def lifespan(app):
    async with mcp.session_manager.run():
        yield

app = Starlette(
    routes=[Mount("/", app=mcp.streamable_http_app())],
    lifespan=lifespan,
)
```

- "The host app must start the session manager in its own lifespan, using `mcp.session_manager.run()`" or the first request fails with "Task group is not initialized. Make sure to use run()."
- "`session_manager` exists only after `streamable_http_app()` is called".
- `mount_path` was removed; mount the app under a prefix instead. Default endpoint is prefix + `/mcp`.
- `@mcp.custom_route("/health", methods=["GET"])` adds plain routes; "These routes are never authenticated, so keep private data out of them."
- Scaling: `uvicorn server:app --workers 4`; "The SDK has no `workers=` option".

### 2.8 Transport security and proxies (deploy page)

- "Without `transport_security=`, the app accepts only localhost Host headers and returns `421` for any real hostname."
- Fix: `TransportSecuritySettings(allowed_hosts=["mcp.example.com", "mcp.example.com:*"], allowed_origins=["https://app.example.com"])` passed to `streamable_http_app()` / `run()`; behind a proxy that controls Host, `enable_dns_rebinding_protection=False` is an option.
- TLS-terminating proxy: run uvicorn with `--proxy-headers` and `--forwarded-allow-ips`.
- Spec (Streamable HTTP): servers MUST validate `Origin`; when local, SHOULD bind 127.0.0.1.

### 2.9 Stateless vs stateful, sessions, multi-worker

- 2026-07-28 requests are self-contained: no `Mcp-Session-Id`, no sticky routing.
- 2025-11-25 and earlier (the path Claude currently uses): session lives in one worker's memory; load balancer must use sticky sessions, or set `stateless_http=True` (loses server-to-client back-channel and resumability).
- Idle legacy sessions expire after 30 minutes (2.2.0); cap 10,000 sessions (503 beyond). Disable with `session_idle_timeout=None, max_sessions=None`.
- `RequestStateSecurity(keys=[...])` must be shared across workers for MRTR `requestState` (2026-07-28 only). `SubscriptionBus` for cross-replica change notifications; built-in bus is in-process only. No shipped `EventStore`.

### 2.10 Errors

Handling-errors page: raise `ToolError` (from `mcp.server.mcpserver.exceptions`) for model-fixable failures -> result `is_error=True` with your message; raise `MCPError` for protocol-level rejection (JSON-RPC error, model sees nothing); any other exception -> `is_error=True` with only "Error executing tool <name>" (2.1.0 behaviour), traceback logged at ERROR. Input-schema validation errors are returned to the model before the function runs.

---

## 3. Authorization in the SDK (Question 3)

### 3.1 `AuthSettings` (source: `src/mcp/server/auth/settings.py`, `main`)

```python
class ClientRegistrationOptions(BaseModel):
    enabled: bool = False
    client_secret_expiry_seconds: int | None = None
    valid_scopes: list[str] | None = None
    default_scopes: list[str] | None = None

class RevocationOptions(BaseModel):
    enabled: bool = False

class AuthSettings(BaseModel):
    model_config = ConfigDict(url_preserve_empty_path=True)
    issuer_url: AnyHttpUrl                              # required
    service_documentation_url: AnyHttpUrl | None = None
    client_registration_options: ClientRegistrationOptions | None = None
    revocation_options: RevocationOptions | None = None
    required_scopes: list[str] | None = None
    identity_assertion_enabled: bool = False            # SEP-990 ID-JAG at /token
    resource_server_url: AnyHttpUrl | None              # required field, may be None (AS-only mode)
    validate_token_resource: bool | None = None
```

Validator: `validate_token_resource=True` requires `resource_server_url`; leaving it `None` with `resource_server_url` set emits `MCPDeprecationWarning` ("it will default to True in 3.0"). Docs: "If your authorization server uses its own audience identifiers instead, leave this off and check `aud` in your verifier."

Constructor rules (source): `auth` and exactly one of `token_verifier` / `auth_server_provider` must be given together; otherwise `ValueError`. With `auth_server_provider` and no `token_verifier`, the SDK wraps the provider in `ProviderTokenVerifier`.

### 3.2 `TokenVerifier` protocol and `AccessToken` (source: `provider.py`)

```python
class AccessToken(BaseModel):
    token: str
    client_id: str
    scopes: list[str]
    expires_at: int | None = None
    resource: str | None = None     # RFC 8707 resource indicator
    subject: str | None = None      # RFC 7662/9068 `sub`; "unique only per issuer"
    claims: dict[str, Any] | None = None

class TokenVerifier(Protocol):
    async def verify_token(self, token: str) -> AccessToken | None: ...
```

Docstring: "Set `AccessToken.resource` to the resource the token was issued for ... With `AuthSettings.validate_token_resource` the bearer middleware then refuses any token whose resource is not `resource_server_url`; without it, confirming the token was issued for this server ... is up to the verifier."

`BearerAuthBackend.authenticate` (source `bearer_auth.py`): reads `Authorization: Bearer ...`, calls `verify_token`, rejects if `expires_at < now`, and (when `resource_server_url` is set via `validate_token_resource`) rejects if `AccessToken.resource` does not equal it (trailing slash ignored, compared as URLs).

### 3.3 How the HTTP app wires auth (source: `lowlevel/server.py::streamable_http_app`)

- Middleware: `AuthenticationMiddleware(backend=BearerAuthBackend(token_verifier, resource_server_url=auth.resource_server_url if auth.validate_token_resource else None))`, then `AuthContextMiddleware`.
- The `/mcp` route is wrapped in `RequireAuthMiddleware(app, required_scopes, resource_metadata_url)`.
- `RequireAuthMiddleware` returns **401** `{"error":"invalid_token","error_description":"Authentication required"}` with `WWW-Authenticate: Bearer error="invalid_token", error_description="Authentication required", resource_metadata="<url>"` when unauthenticated, and **403** `insufficient_scope` ("Required scope: X") when a required scope is missing. Note: the SDK does **not** emit a `scope=` parameter in `WWW-Authenticate`.
- If `auth.resource_server_url` is set, `create_protected_resource_routes(resource_url=..., authorization_servers=[auth.issuer_url], scopes_supported=auth.required_scopes)` adds the RFC 9728 document.
- If `auth_server_provider` is set, `create_auth_routes(...)` adds the AS endpoints to the same app.
- Default localhost DNS-rebinding settings are applied when `host` is `127.0.0.1`/`localhost`/`::1` and no `transport_security` is passed.

### 3.4 Discovery documents

`routes.py`:

- `build_resource_metadata_url("https://example.com/mcp")` -> `https://example.com/.well-known/oauth-protected-resource/mcp` (RFC 9728 §3.1 path insertion). The route is registered at that exact path only. Docs: "Over Streamable HTTP, the app serves `/mcp` and `/.well-known/oauth-protected-resource/mcp`."
- Protected resource metadata fields: `resource`, `authorization_servers`, `scopes_supported`, `resource_name`, `resource_documentation`, `bearer_methods_supported` (defaults to `["header"]`).
- `create_auth_routes(provider, issuer_url, service_documentation_url, client_registration_options, revocation_options, identity_assertion_enabled)` returns routes: `/.well-known/oauth-authorization-server` (GET), `/authorize` (GET/POST), `/token` (POST), `/register` (POST, only if `ClientRegistrationOptions.enabled`), `/revoke` (POST, only if `RevocationOptions.enabled`).
- `build_metadata` advertises: `response_types_supported=["code"]`, `grant_types_supported=["authorization_code","refresh_token"]` (+ jwt-bearer when identity assertion is on), `token_endpoint_auth_methods_supported=["client_secret_post","client_secret_basic"]`, `code_challenge_methods_supported=["S256"]`, `scopes_supported=client_registration_options.valid_scopes`, `registration_endpoint` if enabled, `revocation_endpoint` if enabled.
- `validate_issuer_url`: "Issuer URL must be HTTPS" except `localhost`/`127.0.0.1`/`[::1]`; no fragment or query.

### 3.5 Reading the authenticated identity in a tool

`src/mcp/server/auth/middleware/auth_context.py`:

```python
auth_context_var = contextvars.ContextVar[AuthenticatedUser | None]("auth_context", default=None)

def get_access_token() -> AccessToken | None:
    auth_user = auth_context_var.get()
    return auth_user.access_token if auth_user else None
```

Docs: it "returns the same `AccessToken` your verifier built, with `client_id`, `scopes`, `subject`, `expires_at`, and any `claims`. It works in tools, resources, and prompts. It returns `None` outside an authenticated HTTP request." Helper `principal_components(token) -> (client_id, issuer, subject)` where issuer comes from `claims["iss"]`.

### 3.6 `OAuthAuthorizationServerProvider` protocol (AS mode with DCR)

Generic over `AuthorizationCodeT, RefreshTokenT, AccessTokenT`. Methods (source):

- `get_client(client_id) -> OAuthClientInformationFull | None`
- `register_client(client_info) -> None` (raises `RegistrationError`)
- `authorize(client, params: AuthorizationParams) -> str` (redirect URL; `AuthorizationParams` has `state, scopes, code_challenge, redirect_uri, redirect_uri_provided_explicitly, resource`)
- `load_authorization_code(client, code) -> AuthorizationCodeT | None`
- `exchange_authorization_code(client, authorization_code) -> OAuthToken` (raises `TokenError`)
- `load_refresh_token(client, refresh_token) -> RefreshTokenT | None`
- `exchange_refresh_token(client, refresh_token, scopes) -> OAuthToken` ("Implementations SHOULD rotate both the access token and refresh token.")
- `load_access_token(token) -> AccessTokenT | None`
- `revoke_token(token: AccessTokenT | RefreshTokenT) -> None`
- `exchange_identity_assertion(client, params) -> OAuthToken` (SEP-990; default raises `unsupported_grant_type`)

Migration guide (v2 behaviour): `/token` client-auth failures now return 401 `invalid_client`; "Secret-based clients without a stored secret are rejected"; fix is "registering the client as public (`token_endpoint_auth_method="none"`) or by storing a secret."

Docs verdict on embedded AS: "the constructor argument `auth_server_provider=` embeds a full authorization server in your MCP server. The page says it predates the AS/RS separation in the MCP authorization spec and that new servers should not use it."

### 3.7 The `simple-auth` example architecture (source files downloaded from `main`)

Files: `README.md`, `pyproject.toml` (`requires-python >=3.11`), `mcp_simple_auth/{server.py, auth_server.py, token_verifier.py, simple_auth_provider.py, legacy_as_server.py}`. Entry points: `mcp-simple-auth-rs`, `mcp-simple-auth-as`, `mcp-simple-auth-legacy`.

- **Authorization Server** (`auth_server.py`, port 9000): a plain Starlette app built from `create_auth_routes(provider=SimpleOAuthProvider, issuer_url=..., client_registration_options=ClientRegistrationOptions(enabled=True, valid_scopes=["user"], default_scopes=["user"]), revocation_options=...)` plus `/login` (HTML form), `/login/callback` (POST) and an RFC 7662 `/introspect` endpoint returning `active, client_id, scope, exp, iat, token_type, aud, sub, iss`. Authentication is a hard-coded demo username/password (`demo_user`/`demo_password` via `MCP_` env settings). **It is no longer GitHub-backed** (the task brief's "GitHub-backed AS" is outdated). All state is in-memory dicts. README: "NOTE: this is a simplified example ... not a production-ready implementation."
- **Resource Server** (`server.py`, port 8001): `MCPServer(name=..., token_verifier=IntrospectionTokenVerifier(introspection_endpoint, server_url, validate_resource=oauth_strict), auth=AuthSettings(issuer_url=auth_server_url, required_scopes=["user"], resource_server_url="http://localhost:8001/mcp", validate_token_resource=True))`, then `mcp_server.run(transport="streamable-http", host="localhost", port=8001)`. `--oauth-strict` enables RFC 8707 checking of `aud`.
- **`IntrospectionTokenVerifier`**: POSTs `token=` to `/introspect` with `httpx2`, rejects non-`https`/non-localhost endpoints (SSRF guard), returns `AccessToken(token, client_id, scopes, expires_at=exp, resource=<aud entry matching this server>, subject=sub, claims=data)`.
- **Legacy combined server** (`legacy_as_server.py`, port 8000): `MCPServer(auth_server_provider=provider, auth=AuthSettings(..., resource_server_url=None))` with `@app.custom_route("/login")`; README says it provides no `/.well-known/oauth-protected-resource`.
- Discovery per README: RS `/.well-known/oauth-protected-resource` -> `{"resource": ..., "authorization_servers": [...]}`; AS `/.well-known/oauth-authorization-server` -> `{"issuer", "authorization_endpoint", "token_endpoint"}`.

---

## 4. Spec version and authorization requirements (Question 4)

### 4.1 Protocol version

- `https://modelcontextprotocol.io/specification/versioning`: "The **current** protocol version is **2026-07-28**." `.../specification/latest/...` pages render as 2026-07-28 (all internal links point to `/specification/2026-07-28/`). `schema.ts`: `LATEST_PROTOCOL_VERSION = "2026-07-28"`.
- SDK protocol-versions page: the pinnable set is "exactly `["2026-07-28"]`"; handshake-era versions ("up to `2025-11-25`") are served via automatic fallback and rejected if pinned. Release note v2.0.0: "It supports the 2026-07-28 revision ... and serves every earlier revision from the same server."
- Legacy-clients page: "the `streamable_http_app()` you already deploy serves both"; routing is by the `MCP-Protocol-Version` header; "there is no `legacy=` option and no way to disable either era."

### 4.2 2026-07-28 changelog items that matter here

- Protocol-level sessions and `Mcp-Session-Id` removed; no `initialize` handshake; every request carries version/capabilities in `_meta`; `server/discover` is mandatory.
- `subscriptions/listen` replaces the GET stream and `resources/subscribe`.
- MRTR (`resultType: "input_required"`) replaces server-initiated elicitation/sampling/roots; `resultType` is required on all results.
- Streamable HTTP POSTs MUST carry `MCP-Protocol-Version`, `Mcp-Method`, and (for `tools/call`, `resources/read`, `prompts/get`) `Mcp-Name`; `x-mcp-header` maps arguments to `Mcp-Param-*`.
- SSE resumability (`Last-Event-ID`) removed.
- Deprecated: Roots, Sampling, Logging (SEP-2577); HTTP+SSE transport; **Dynamic Client Registration "in favor of Client ID Metadata Documents"** (retained for backwards compatibility).
- New error codes `-32020` HeaderMismatch, `-32021` MissingRequiredClientCapability, `-32022` UnsupportedProtocolVersion.

### 4.3 Authorization spec (2026-07-28) normative points

- Based on "OAuth 2.1 IETF DRAFT (draft-ietf-oauth-v2-1-13)", RFC 6750, RFC 8414, RFC 7591, RFC 8707, RFC 9728, RFC 9207, CIMD draft, OIDC Discovery/Registration.
- Roles: "A protected *MCP server* acts as an OAuth 2.1 resource server".
- "Authorization servers **MUST** implement OAuth 2.1".
- "Authorization servers and MCP clients **SHOULD** support OAuth Client ID Metadata Documents"; "**MAY** support ... Dynamic Client Registration ... Dynamic Client Registration is deprecated".
- "MCP servers **MUST** implement OAuth 2.0 Protected Resource Metadata (RFC9728)"; the document "**MUST** include the `authorization_servers` field". Servers MUST use either the `WWW-Authenticate` `resource_metadata` pointer on 401 or the well-known URI (path-aware `/.well-known/oauth-protected-resource/<path>` or root).
- "MCP authorization servers **MUST** provide at least one of" RFC 8414 metadata or OIDC Discovery.
- PKCE: "MCP clients **MUST** implement PKCE ... **MUST** use the `S256` code challenge method"; "If `code_challenge_methods_supported` is absent, the authorization server does not support PKCE and MCP clients **MUST** refuse to proceed."
- Resource indicators: "MCP clients **MUST** implement Resource Indicators for OAuth 2.0 as defined in RFC 8707"; `resource` "**MUST** be included in both authorization requests and token requests" and use the canonical server URI (e.g. `https://mcp.example.com/mcp`).
- Token handling: Bearer header on every request; "Access tokens **MUST NOT** be included in the URI query string"; "MCP servers **MUST** validate that access tokens were issued specifically for them as the intended audience"; "MCP servers **MUST NOT** accept or transit any other tokens" (no token passthrough); invalid/expired -> 401; insufficient scope -> 403 with `error="insufficient_scope"`, `scope=...`.
- Servers SHOULD include `scope` in the 401 `WWW-Authenticate` challenge; clients otherwise use `scopes_supported` from PRM. Servers SHOULD NOT advertise `offline_access` in PRM.
- `iss` (RFC 9207): AS SHOULD include; clients MUST validate when present.
- Security: AS endpoints MUST be HTTPS; redirect URIs MUST be `localhost` or HTTPS; AS MUST rotate refresh tokens for public clients; AS MUST validate exact redirect URIs; AS displaying CIMD localhost redirects MUST show the hostname.
- Registration priority for clients: pre-registered -> CIMD (if `client_id_metadata_document_supported`) -> DCR (if `registration_endpoint`) -> prompt user. DCR clients MUST send `application_type`.

### 4.4 What Claude's client actually does (cross-check, Anthropic docs)

From `https://claude.com/docs/connectors/building/index` and `.../authentication` (2026-10-19T23:08Z-23:09Z):

- "Claude follows the 2025-03-26, 2025-06-18, and 2025-11-25 authorization specifications" (not yet 2026-07-28).
- Transport: "Use Streamable HTTP"; legacy HTTP+SSE also supported but deprecated.
- Registration: `oauth_dcr` "Supported by default"; `oauth_cimd` is selected "only when your authorization server metadata advertises both `"client_id_metadata_document_supported": true` and `"none"` in `token_endpoint_auth_methods_supported`"; otherwise "Claude falls back to DCR". "DCR causes Claude to register a new client on every fresh connection".
- Discovery: "A `401` is required to start sign-in, and Claude ignores a `WWW-Authenticate` header on a `200`"; "Claude uses only the first entry in your metadata's `authorization_servers` list"; `resource` in PRM "must equal the URL as the user enters it in Claude, including any path component"; fallback probing `/.well-known/oauth-protected-resource/<path>` then root.
- PKCE: "Claude includes a PKCE `code_challenge` with `code_challenge_method=S256` on every authorization request".
- Scopes: taken from `scope` in the 401 `WWW-Authenticate` if present, else PRM `scopes_supported`; appends `offline_access` when the AS lists it.
- Redirect URIs: `https://claude.ai/api/mcp/auth_callback` for hosted apps; Claude Code uses a loopback on an ephemeral port and declares `http://localhost/callback` and `http://127.0.0.1/callback` in its CIMD (`https://claude.ai/oauth/claude-code-client-metadata`), so the AS must match port-agnostically.
- Token endpoint: must accept `application/x-www-form-urlencoded`; return `invalid_grant` for dead refresh tokens; rotate refresh tokens for public clients; Claude refreshes on 401 and up to five minutes before expiry.
- Latency: discovery/registration/token endpoints get 10 s, refresh 30 s.
- Limits: tool result ~150,000 characters (claude.ai/Desktop), 240 s per tool call; Claude Code 25,000 tokens (`MAX_MCP_OUTPUT_TOKENS`).
- Unsupported by Claude: resource subscriptions, sampling, "Advanced or draft capabilities".
- Egress IP range for allowlists: `160.79.104.0/21`.

Implication: with the SDK's built-in AS, `token_endpoint_auth_methods_supported` is `["client_secret_post","client_secret_basic"]` (no `"none"`), so Claude will not choose CIMD and will use DCR via `/register`; `ClientRegistrationOptions(enabled=True)` is therefore mandatory if the SDK AS is used, and the registration handler must accept public clients (see unresolved items).

---

## 5. Breaking changes in the last ~6 months (Question 5)

Source: GitHub release bodies (API) and the What's-new/migration pages.

- **v2.0.0 (2026-07-28)**: `FastMCP` -> `MCPServer`; new `Client`; transport settings moved to `run()`; `mount_path` removed; `get_context()` removed; `Context.client_id` removed; `httpx` -> `httpx2`; WebSocket transport and `mcp[ws]` removed; experimental Tasks API removed; `MCP_*` env vars and pydantic-settings removed; `streamablehttp_client` removed (`streamable_http_client`, 2-tuple); low-level `Server` rebuilt (constructor `on_*` handlers, `(ctx, params)` signature, explicit result types); wire types moved to `mcp-types` with snake_case attributes; unexpected exceptions become sanitized errors; `McpError` -> `MCPError`; `RFC7523OAuthClientProvider`/`JWTParameters` removed; `callback_handler` returns `AuthorizationCodeResult` (RFC 9207 `iss`); Streamable HTTP bodies over 4 MiB -> 413; OpenTelemetry on by default; "v1.x is in maintenance mode and will only receive security fixes".
- **v2.1.0 (2026-08-24)**: handler exceptions reach the client only as "Error executing tool <name>" (use `ToolError`/`ResourceError`); content-block return annotations no longer advertise `outputSchema`; 4 MiB limit extended to SSE and OAuth endpoints.
- **v2.1.1 / v2.0.1 (2026-08-25/26)**: importing `mcp.server.fastmcp` points at the migration guide ("either pin `mcp<2` or upgrade to 2").
- **v2.2.0 (2026-09-07)**: HTTP redirects followed only within the endpoint's origin; idle legacy sessions expire after 30 minutes and are capped at 10,000; OAuth client validates AS `issuer` on the legacy path too; new `AuthSettings.validate_token_resource` plus `MCPDeprecationWarning` when it is unset with `resource_server_url`; `issuer=` deprecation on client-credentials providers. Known gaps: tasks extension (SEP-2663), DPoP (SEP-1932), `jwt-bearer` grant.
- **v2.3.0 (2026-10-02)**: `httpx2>=2.10.0` required; invalid `x-mcp-header` fails at tool registration (`InvalidSignature`); empty `_meta`/`params` no longer sent on legacy connections; `initialize` omits empty `experimental`; `Mcp-Param-*` validation looks tools up by name; interactive OAuth login no longer counts against request timeouts; new `max_sse_event_size`, `MCPServer(subscriptions=False)`, `get_tool_input_schema=`.
- **v1.x tail**: 1.29.0 (2026-07-28) body limits; 1.29.1 (2026-08-24); 1.30.0 (2026-09-07) backports redirect/session-expiry/issuer changes and adds `validate_token_resource`, `session_idle_timeout`, `max_sessions` to `FastMCP`. 1.x docs moved to `/v1/`.
- **Upcoming (3.0, no date)**: `validate_token_resource` defaults to `True` when `resource_server_url` is set; `issuer=` becomes required on client-credentials providers; deprecated helpers removed. All deprecations emit `MCPDeprecationWarning` (a `UserWarning` subclass); tests can set `"error::mcp.MCPDeprecationWarning"`.
- **Other v2 runtime notes**: DNS-rebinding protection auto-enables on localhost hosts (bare `Host` -> `421 Invalid Host header`); `def` (sync) tools now run on a worker thread; results are validated before send; `MCPServer("...")` with no name reports `mcp-server`.

---

## 6. Unresolved items

1. **Python floor**: PyPI says `>=3.10` for 2.3.0, docs and `main` say 3.11+. Not a blocker (use 3.11+), but the exact release that drops 3.10 is not published yet.
2. **DCR public-client registration in the SDK AS**: Claude registers as a public client. The migration guide says public clients (`token_endpoint_auth_method="none"`) are supported at `/token`, but the SDK's AS metadata advertises only `client_secret_post`/`client_secret_basic`, and the `/register` handler's acceptance of `token_endpoint_auth_method: "none"` was not exercised in this session. Needs a live test with Claude (custom connector) before relying on the SDK's built-in AS.
3. **CIMD with the SDK AS**: because the metadata omits `"none"` and `client_id_metadata_document_supported`, Claude will never select CIMD against the SDK's `create_auth_routes` AS. Whether the SDK AS supports CIMD at all was not confirmed.
4. **RFC 8707 `resource` from Claude**: Anthropic's authentication page does not say whether Claude sends the `resource` parameter. If it does not, an AS that only binds audience from `resource` would issue tokens without `resource`, and `validate_token_resource=True` would reject them. The AS must therefore bind audience by its own policy (single-audience AS) or the verifier must check `aud` itself.
5. **Loopback redirect matching**: Claude Code needs port-agnostic matching of `http://localhost/callback` and `http://127.0.0.1/callback`. Whether the SDK's `AuthorizationHandler` performs exact-match only was not verified; the spec and SDK docs both say exact redirect URI validation. Must be tested or handled in the provider.
6. **Migration guide OAuth section** was read through WebFetch summaries (quotes capped at ~125 chars); field-level facts were confirmed from source instead. The "revoke_token" signature in the example (`token: str, token_type_hint`) differs from the protocol (`token: AccessTokenT | RefreshTokenT`) and carries a `TODO` comment in the example itself.
7. **GitHub Releases HTML page** does not show years; dates were taken from the GitHub API and PyPI JSON instead.
8. **Live behaviour** of a 2.3.0 server against Claude's 2025-11-25 client (session negotiation, `MCP-Protocol-Version` fallback) was not tested here; the SDK docs say no configuration is needed.
9. **Whether Claude's hosted surfaces send `Origin`**: irrelevant for `allowed_hosts` but the `allowed_origins` list must not block Claude; the SDK checks `Origin` only when present. Not verified against live traffic.

---

## 7. Recommendations

1. Pin `mcp>=2.3.0,<3` and `mcp-types` will follow (exact pin by `mcp`). Do not add `fastmcp`. Use Python 3.11+ (3.12 recommended) with `uv`.
2. Write all server code against the v2 API: `from mcp.server import MCPServer`; `from mcp.server.mcpserver import Context`; `from mcp.server.mcpserver.exceptions import ToolError`; `from mcp.types import ToolAnnotations`; `from mcp.server.auth.settings import AuthSettings`; `from mcp.server.auth.provider import AccessToken, TokenVerifier`; `from mcp.server.auth.middleware.auth_context import get_access_token`.
3. Run as **Resource Server only**: `MCPServer(name, instructions=..., lifespan=..., token_verifier=<JWT or introspection verifier>, auth=AuthSettings(issuer_url=AS_ISSUER, resource_server_url=PUBLIC_MCP_URL, required_scopes=[...], validate_token_resource=True))`. Set `resource_server_url` to the exact URL users will paste into Claude (e.g. `https://<host>/mcp`), because Claude requires PRM `resource` to match it exactly.
4. Pick the AS deliberately. Options: (a) an external OAuth 2.1 AS that supports DCR, S256 PKCE, refresh-token rotation, `invalid_grant`, form-encoded `/token`, both Claude redirect URIs (port-agnostic loopback), and sub-10 s latency; or (b) the SDK's `create_auth_routes()` AS in a separate Starlette app backed by a persistent store (clients, codes, refresh/access tokens in Postgres, not in-memory), with `ClientRegistrationOptions(enabled=True, valid_scopes=..., default_scopes=...)` and `RevocationOptions(enabled=True)`. In either case verify items 2-5 of the unresolved list with a live custom-connector test.
5. Derive identity from `get_access_token()`; use `(claims["iss"], subject)` as the tenant key for every ledger, reservation, idempotency key and export. Reject calls where `get_access_token()` is `None` on HTTP. Never accept a `user_id` argument from the model.
6. Annotate tools: read-only research tools `ToolAnnotations(read_only_hint=True, open_world_hint=True)` (they fetch external odds/injury data); pure calculators `read_only_hint=True, open_world_hint=False`; `select_ticket`, `record_actual_bet`, `reconcile_settlement`, `import_hardrock_quote` -> `read_only_hint=False, destructive_hint=False, idempotent_hint=True` (append-only with idempotency keys), `open_world_hint=False`. Give each a `title`.
7. Return pydantic `BaseModel`s from tools so `outputSchema`/`structuredContent` are generated and validated; keep results well under Claude's ~150k-character limit; raise `ToolError` for model-actionable failures.
8. Deployment: mount via `streamable_http_app(transport_security=TransportSecuritySettings(allowed_hosts=["<host>", "<host>:*"], allowed_origins=["https://claude.ai", ...]))`, run uvicorn with `--proxy-headers --forwarded-allow-ips`, start single-process (or `stateless_http=True` for multiple workers since Claude does not use sampling/elicitation back-channel features), keep `/health` free of private data, and leave `session_idle_timeout`/`max_sessions` at defaults.
9. Tests: use the in-memory `Client(mcp)` for tool logic (auth is skipped there) and an HTTP-level test with a fake `TokenVerifier` for 401/403/`WWW-Authenticate`/PRM behaviour; set pytest `filterwarnings = error::mcp.MCPDeprecationWarning` so SDK deprecations surface early.

---

## Sources

| URL | retrieved_at_utc | what it established |
|---|---|---|
| https://py.sdk.modelcontextprotocol.io/ | 2026-10-19T23:04Z | v2 is the current stable line; `MCPServer` quickstart; Python 3.11+; doc section map |
| https://pypi.org/project/mcp/ | 2026-10-19T23:04Z | mcp 2.3.0 released Oct 2, 2026; `cli` extra; links |
| https://pypi.org/pypi/mcp/json (curl) | 2026-10-19T23:05Z | version 2.3.0, `requires_python >=3.10`, full `requires_dist`, upload timestamps for 1.23.2 through 2.3.0 |
| https://github.com/modelcontextprotocol/python-sdk | 2026-10-19T23:04Z | README uses `MCPServer`; MIT license; doc links |
| https://github.com/modelcontextprotocol/python-sdk/tree/main/examples/servers/simple-auth | 2026-10-19T23:04Z | AS/RS split example overview, ports, `--oauth-strict`, legacy mode |
| https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/main/examples/servers/simple-auth/{README.md,pyproject.toml,mcp_simple_auth/server.py,auth_server.py,token_verifier.py,simple_auth_provider.py,legacy_as_server.py} | 2026-10-19T23:05Z | Exact example code: credential-based AS (not GitHub), `/introspect`, `IntrospectionTokenVerifier`, RS `AuthSettings` usage, legacy combined server |
| https://modelcontextprotocol.io/specification/latest/basic/authorization | 2026-10-19T23:04Z | Resolves to 2026-07-28; OAuth 2.1 draft-13 basis; MUST/SHOULD list; RFC 8707 `resource`; token handling; 401/403/400; scope strategy |
| https://modelcontextprotocol.io/specification/latest/basic/authorization/authorization-server-discovery | 2026-10-19T23:05Z | PRM MUST; `WWW-Authenticate` or well-known paths; RFC 8414/OIDC discovery order; issuer validation |
| https://modelcontextprotocol.io/specification/latest/basic/authorization/client-registration | 2026-10-19T23:05Z | CIMD SHOULD; DCR deprecated/MAY; priority order; `application_type`; AS binding |
| https://modelcontextprotocol.io/specification/latest/basic/authorization/security-considerations | 2026-10-19T23:05Z | PKCE S256 MUST; `code_challenge_methods_supported` check; audience validation; no passthrough; HTTPS; redirect rules |
| https://modelcontextprotocol.io/specification/latest/server/tools | 2026-10-19T23:04Z | Tool fields, `outputSchema`, `structuredContent`, annotations untrusted, naming, errors, security MUSTs |
| https://modelcontextprotocol.io/specification/2026-07-28/changelog | 2026-10-19T23:05Z | Full list of 2026-07-28 major/minor changes and deprecations (incl. DCR deprecated) |
| https://modelcontextprotocol.io/specification/versioning | 2026-10-19T23:08Z | "The current protocol version is 2026-07-28"; per-request negotiation |
| https://modelcontextprotocol.io/specification/latest/basic/transports/streamable-http | 2026-10-19T23:08Z | Required headers, no sessions/GET, Origin validation, backward-compat rules |
| https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/main/schema/2026-07-28/schema.ts | 2026-10-19T23:08Z | `ToolAnnotations` defaults (false/true/false/true), `Tool`, `CallToolResult`, `LATEST_PROTOCOL_VERSION` |
| https://py.sdk.modelcontextprotocol.io/whats-new/ | 2026-10-19T23:05Z | Complete v2 change tour: renames, config to `run()`, removals, auth, protocol support |
| https://py.sdk.modelcontextprotocol.io/migration/ (offsets 0, 100000, 150000, 200000) | 2026-10-19T23:05Z to 23:08Z | Before/after code for renames, settings, `streamable_http_app`, lifespan, `Context.client_id`, auth carry-overs, `/token` `invalid_client`, public clients |
| https://py.sdk.modelcontextprotocol.io/run/authorization/ | 2026-10-19T23:05Z | RS setup, `TokenVerifier`, `AuthSettings` fields, discovery endpoint, 401 header, `get_access_token`, embedded AS discouraged, stdio skips auth |
| https://py.sdk.modelcontextprotocol.io/servers/tools/ | 2026-10-19T23:05Z | `@mcp.tool()` usage, `ToolAnnotations` snake_case example, validation errors |
| https://py.sdk.modelcontextprotocol.io/servers/structured-output/ | 2026-10-19T23:05Z | Return-type -> schema rules, wrapping, validation, opt-out |
| https://py.sdk.modelcontextprotocol.io/handlers/context/ | 2026-10-19T23:05Z | `Context` injection and members; headers not identity |
| https://py.sdk.modelcontextprotocol.io/handlers/lifespan/ | 2026-10-19T23:05Z | Typed lifespan example; `ctx.request_context.lifespan_context` |
| https://py.sdk.modelcontextprotocol.io/run/ | 2026-10-19T23:05Z | `run()` transports and options; CLI; `__main__` guard |
| https://py.sdk.modelcontextprotocol.io/run/asgi/ | 2026-10-19T23:05Z | Mounting, `session_manager.run()`, custom routes unauthenticated, CORS |
| https://py.sdk.modelcontextprotocol.io/run/deploy/ | 2026-10-19T23:05Z | 421 without `transport_security`; proxy headers; stateless vs stateful; workers; `RequestStateSecurity` |
| https://py.sdk.modelcontextprotocol.io/run/legacy-clients/ | 2026-10-19T23:05Z | One app serves both eras; session limits; `stateless_http` scope |
| https://py.sdk.modelcontextprotocol.io/protocol-versions/ | 2026-10-19T23:05Z | Pinnable set `["2026-07-28"]`; auto fallback |
| https://py.sdk.modelcontextprotocol.io/deprecated/ | 2026-10-19T23:05Z | SEP-2577 deprecations; `validate_token_resource` warning; 3.0 defaults; `MCPDeprecationWarning` |
| https://py.sdk.modelcontextprotocol.io/get-started/installation/ | 2026-10-19T23:05Z | Python 3.11+; extras; pin `mcp>=1.28,<2` if staying on v1 |
| https://py.sdk.modelcontextprotocol.io/get-started/real-host/ | 2026-10-19T23:06Z | Host registration commands; stdio for local hosts |
| https://py.sdk.modelcontextprotocol.io/servers/handling-errors/ | 2026-10-19T23:08Z | `ToolError` vs `MCPError` vs crash behaviour |
| https://github.com/modelcontextprotocol/python-sdk/releases | 2026-10-19T23:05Z | Release list and headline changes (no years shown) |
| https://api.github.com/repos/modelcontextprotocol/python-sdk/releases?per_page=12 | 2026-10-19T23:06Z / 23:08Z | `published_at` dates; full release bodies for v2.0.0, v2.0.1, v2.1.0, v2.2.0, v2.3.0 |
| https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/main/pyproject.toml and .../v2.3.0/pyproject.toml | 2026-10-19T23:06Z | `requires-python` `>=3.11` on main vs `>=3.10` at v2.3.0 |
| https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/main/src/mcp/server/auth/settings.py | 2026-10-19T23:06Z | Exact `AuthSettings`, `ClientRegistrationOptions`, `RevocationOptions` fields and validator |
| .../src/mcp/server/auth/provider.py | 2026-10-19T23:07Z | `TokenVerifier`, `AccessToken`, `OAuthAuthorizationServerProvider` methods, `ProviderTokenVerifier` |
| .../src/mcp/server/auth/middleware/auth_context.py | 2026-10-19T23:06Z | `get_access_token()` implementation via contextvar |
| .../src/mcp/server/auth/middleware/bearer_auth.py | 2026-10-19T23:07Z | `BearerAuthBackend` resource check; `RequireAuthMiddleware` 401/403 bodies and `WWW-Authenticate` format |
| .../src/mcp/server/auth/routes.py | 2026-10-19T23:07Z | `create_auth_routes`, `build_metadata`, `build_resource_metadata_url`, `create_protected_resource_routes`, issuer HTTPS rule |
| .../src/mcp/server/mcpserver/server.py | 2026-10-19T23:06Z | `MCPServer.__init__`, `run()` overloads, `streamable_http_app()`, `tool()` signature, auth constructor rules |
| .../src/mcp/server/lowlevel/server.py | 2026-10-19T23:08Z | HTTP app auth wiring: middleware stack, `RequireAuthMiddleware` on `/mcp`, PRM route, localhost DNS-rebinding defaults |
| .../src/mcp/server/mcpserver/{__init__.py,context.py} | 2026-10-19T23:09Z | Public exports; `Context` members; no `client_id` |
| .../src/mcp-types/mcp_types/_v2026_07_28/__init__.py | 2026-10-19T23:09Z | Python `ToolAnnotations` (snake_case, aliases, `None` defaults) and `Tool` fields |
| https://pypi.org/project/fastmcp/ and https://pypi.org/pypi/fastmcp/json | 2026-10-19T23:05Z / 23:06Z | fastmcp 4.1.1 (2026-10-18), jlowin project, separate from official SDK |
| https://pypi.org/project/mcp-types/ and https://pypi.org/pypi/mcp-types/json | 2026-10-19T23:06Z | mcp-types 2.3.0 wire-types package re-exported by `mcp` |
| https://claude.com/docs/connectors/building/index | 2026-10-19T23:08Z | Claude follows 2025-03-26/06-18/11-25 auth specs; DCR; callback URL; limits; unsupported features |
| https://claude.com/docs/connectors/building/authentication | 2026-10-19T23:09Z | Auth types table; DCR vs CIMD selection rule; 401 required; PKCE S256; redirect URIs; refresh rules; latency; egress range |
