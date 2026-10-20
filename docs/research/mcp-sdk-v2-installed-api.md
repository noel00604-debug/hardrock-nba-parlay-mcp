# MCP Python SDK: installed API facts (direct inspection, mcp==2.3.0)

Inspected on 2026-10-19 (America/New_York evening) by importing the installed package in this
project's uv environment. These are facts about the code actually installed, not documentation claims.

- Installed: `mcp==2.3.0`; `mcp.types.LATEST_PROTOCOL_VERSION == "2026-07-28"`.
- `mcp.server.fastmcp` no longer exists. Import error text: "This is mcp 2.x, where FastMCP was renamed
  to MCPServer (from mcp.server.mcpserver import MCPServer)". Migration guide:
  https://py.sdk.modelcontextprotocol.io/v2/migration/#fastmcp-renamed-to-mcpserver
- `from mcp.server.mcpserver import MCPServer, Context`; `from mcp.server.mcpserver.exceptions import ToolError`.
- `MCPServer(name=None, title=None, description=None, instructions=None, website_url=None, icons=None,
  version='', auth_server_provider=None, token_verifier=None, *, tools=None, resources=None, extensions=None,
  debug=False, log_level='INFO', ..., lifespan=None, auth: AuthSettings | None = None, ..., middleware=None)`.
  Pass everything after `name` by keyword.
- `@server.tool(name=None, title=None, description=None, annotations: ToolAnnotations | None = None, icons=None,
  meta=None, structured_output: bool | None = None)`. Structured output auto-detected from the return annotation
  (pydantic models -> output_schema + structured_content). A tool may declare `ctx: Context`.
- `ToolAnnotations` fields: `title, read_only_hint, destructive_hint, idempotent_hint, open_world_hint`.
- Sync `def` tools run on a worker thread (fine for our sync SQLAlchemy services).
- `server.run(transport='stdio' | 'sse' | 'streamable-http', **kwargs)`;
  `server.streamable_http_app(*, streamable_http_path='/mcp', json_response=False, stateless_http=False,
  event_store=None, retry_interval=None, max_request_body_size=4194304, session_idle_timeout=1800,
  max_sessions=10000, transport_security: TransportSecuritySettings | None = None, host='127.0.0.1') -> Starlette`.
  The host app's lifespan must enter `server.session_manager.run()`. DNS-rebinding protection is on for
  localhost hosts; set `transport_security` (allowed hosts/origins) for a real hostname.
- `server.custom_route(...)` exists for extra Starlette routes (login pages, account page, healthz).
- Auth (server side), module `mcp.server.auth`:
  - `mcp.server.auth.provider.OAuthAuthorizationServerProvider` protocol methods:
    `get_client(client_id) -> OAuthClientInformationFull | None`, `register_client(client_info) -> None`,
    `authorize(client, params: AuthorizationParams) -> str` (returns the URL to redirect the user agent to),
    `load_authorization_code(client, code) -> AuthorizationCode | None`,
    `exchange_authorization_code(client, authorization_code) -> OAuthToken`,
    `load_refresh_token(client, refresh_token) -> RefreshToken | None`,
    `exchange_refresh_token(client, refresh_token, scopes) -> OAuthToken`,
    `load_access_token(token) -> AccessToken | None`, `revoke_token(token) -> None`,
    `exchange_identity_assertion(client, params) -> OAuthToken` (only when identity_assertion_enabled).
  - `AuthorizationParams` fields: `state, scopes, code_challenge, redirect_uri, redirect_uri_provided_explicitly, resource`.
  - `AuthorizationCode` fields: `code, scopes, expires_at, client_id, code_challenge, redirect_uri,
    redirect_uri_provided_explicitly, resource, subject`.
  - `AccessToken` fields: `token, client_id, scopes, expires_at, resource, subject, claims`.
    `RefreshToken` fields: `token, client_id, scopes, expires_at, resource, subject`.
  - `OAuthToken` fields: `access_token, token_type, expires_in, scope, refresh_token`.
  - `OAuthClientInformationFull` (from `mcp.shared.auth`) includes `client_id, client_secret, redirect_uris,
    grant_types, token_endpoint_auth_method, client_name, scope, ...`.
  - `mcp.server.auth.provider.construct_redirect_uri(redirect_uri_base, **params)` helper exists.
  - `mcp.server.auth.settings.AuthSettings(issuer_url: AnyHttpUrl, service_documentation_url=None,
    client_registration_options: ClientRegistrationOptions | None, revocation_options: RevocationOptions | None,
    required_scopes: list[str] | None, identity_assertion_enabled=False, resource_server_url: AnyHttpUrl | None,
    validate_token_resource: bool | None)`.
    `ClientRegistrationOptions(enabled=False, client_secret_expiry_seconds=None, valid_scopes=None, default_scopes=None)`;
    `RevocationOptions(enabled=False)`.
  - `mcp.server.auth.routes.create_auth_routes(provider, issuer_url, service_documentation_url, client_registration_options,
    revocation_options, identity_assertion_enabled)` and `create_protected_resource_routes(resource_url,
    authorization_servers, scopes_supported, resource_name, resource_documentation)`; constants AUTHORIZATION_PATH,
    TOKEN_PATH, REGISTRATION_PATH, REVOCATION_PATH. When `auth`+`auth_server_provider` are passed to MCPServer the
    streamable HTTP app wires these routes itself.
  - Identity inside a tool: `from mcp.server.auth.middleware.auth_context import get_access_token`;
    `get_access_token() -> AccessToken | None`; the user is `AccessToken.subject`.
    `mcp.server.mcpserver.authenticated_principal(ctx)` binds (client_id, issuer, subject).
- `Context` offers: `request_context, request_id, session, headers, protocol_version, info/debug/warning/error/log,
  report_progress, elicit, read_resource, mcp_server`.
- Removed in v2 (per migration guide): `get_context()`, `ctx.fastmcp` (now `ctx.mcp_server`), `ctx.client_id`,
  `mcp.shared.progress`, `McpError` (now `MCPError`), `streamablehttp_client` (now `streamable_http_client`),
  WebSocket transport; the SDK uses `httpx2` internally (our provider code uses `httpx` separately).
