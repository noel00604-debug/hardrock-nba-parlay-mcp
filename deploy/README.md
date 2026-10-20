# Deploying the hosted MCP server

This folder holds everything needed to run `hardrock-nba-parlay-mcp` as the remote MCP
connector that the plugin bundle points at. The server must be reachable over HTTPS from
Anthropic's cloud (connections do not come from the user's device), must speak Streamable
HTTP at `/mcp`, and must keep each user's ledger in a durable PostgreSQL database.

Hosting facts and prices below come from `docs/research/hosting-options.md` (vendor pages
retrieved 2026-10-19). Prices change; check the vendor page before paying.

Status on 2026-10-19: nothing here has been deployed. Docker is not installed on the
development Mac, so the Dockerfile has not been built locally either. The first deployment
is a manual step for the owner (Noel Fernandez) using his own accounts and card.

## 1. Files

| File | Purpose |
|---|---|
| `Dockerfile` | `python:3.12-slim`, uv 0.13.1, `uv sync --frozen --no-dev`, non-root user, `hrnba serve --transport http --host 0.0.0.0 --port 8080` |
| `railway.toml` | Railway build and health-check settings (primary option; key names not verified, see the file header) |
| `fly.toml` | Fly.io fallback: shared-cpu-1x 512 MB in `iad`, always on |
| `docker-compose.yml` | Local PostgreSQL plus the server for a laptop test; secrets come from the shell |
| this README | first deployment, variables, TLS, backups, restore test, tunnel smoke test |

## 2. Required environment variables

All settings use the `HRNBA_` prefix (full list with comments in `.env.example`).

| Variable | Hosted value | Notes |
|---|---|---|
| `HRNBA_AUTH_MODE` | `builtin_oauth` | enables the built-in OAuth authorization server, login and sign-up pages |
| `HRNBA_PUBLIC_URL` | `https://<your-host>` | the https origin; the issuer and protected-resource metadata are derived from it, and `/mcp` is appended for the resource |
| `HRNBA_SECRET_KEY` | 64 random hex characters | cookie signing and per-user key encryption; generate with `python3 -c "import secrets; print(secrets.token_hex(32))"`; losing it invalidates sessions and encrypted per-user provider keys |
| `HRNBA_DATABASE_URL` | `postgresql+psycopg://user:password@host:5432/dbname` | Railway injects `DATABASE_URL` (`postgresql://...`); set `HRNBA_DATABASE_URL` to the same value with the `postgresql+psycopg://` scheme so SQLAlchemy uses psycopg 3 |
| `HRNBA_ODDS_API_KEY` | your The Odds API key | server-wide key; users may store their own key through `set_user_settings`, which overrides it |
| `HRNBA_HOST` / `HRNBA_PORT` | `0.0.0.0` / `8080` | set in the Dockerfile; the CMD also passes them explicitly |
| `HRNBA_LOG_LEVEL` | `INFO` | logs are redacted of keys and bearer tokens |

Never put any of these in the repository, the plugin bundle, or a Dockerfile `ENV`.

## 3. First deployment on Railway (primary)

Expected bill: about $5/month on Hobby for 1 to 10 users (the $5 plan fee includes $5 of
usage; the app at about 200 MB RSS plus Postgres at about 150 MB fits inside it), about
$5 to $7 at 100 users. Railway requires a post-paid card.

1. Create a Railway account, choose the Hobby plan, add the card. Set a hard usage limit
   (minimum $10) under the workspace billing settings so a mistake cannot run up a bill.
2. New Project, region `us-east4` (Virginia).
3. Add the PostgreSQL template service. Railway creates a single-node Postgres on a volume
   and exposes `DATABASE_URL` on the private network.
4. Add a service from the GitHub repository (push the repository first). In the service
   Variables add `RAILWAY_DOCKERFILE_PATH=deploy/Dockerfile` so Railway uses this
   Dockerfile instead of looking at the repo root.
5. Add the variables from section 2. Use Railway's variable reference for the database:
   `HRNBA_DATABASE_URL=postgresql+psycopg://${{Postgres.PGUSER}}:${{Postgres.PGPASSWORD}}@${{Postgres.PGHOST}}:${{Postgres.PGPORT}}/${{Postgres.PGDATABASE}}`
   (the reference-variable syntax is Railway's; confirm the Postgres service's variable
   names in its Variables tab).
6. Settings > Networking > Generate Domain. Railway issues the `*.railway.app` hostname
   with an automatically provisioned and renewed TLS certificate. Set `HRNBA_PUBLIC_URL`
   to `https://<that hostname>` and redeploy.
7. Settings > Deploy: leave Serverless OFF (the server must stay awake; a sleeping
   service answers the first request with a 502).
8. Postgres service > Backups: enable Daily (kept 6 days) and Weekly (kept 27 days).
9. Verify: `curl -s https://<host>/healthz` returns the health JSON with no personal
   data; `curl -si https://<host>/mcp` returns `401` with a `WWW-Authenticate` header that
   carries `resource_metadata`; `curl -s https://<host>/.well-known/oauth-protected-resource/mcp`
   returns JSON whose `resource` equals `https://<host>/mcp`.
10. Create the owner account on `https://<host>/signup`, then add the server as a custom
    connector in claude.ai (Customize > Connectors > Add custom connector, URL
    `https://<host>/mcp`, OAuth client "Use Claude's published identity") and sign in.
11. Run `python3 scripts/stamp_release.py --server-url https://<host>/mcp --repo-url https://github.com/<owner>/<repo>`
    to write the URL into the plugin bundle, rebuild the ZIP, and reinstall the plugin.

Later deployments: push to the connected branch; Railway rebuilds and redeploys. The
database lives in the Postgres service, not in the server container, so records survive
redeploys. The SQLite fallback under `/data` inside the container does not survive a
redeploy; do not run hosted mode without `HRNBA_DATABASE_URL`.

## 4. TLS and allowed hosts

- Railway and Fly both terminate TLS at their edge with certificates from recognised
  authorities and forward plain HTTP to the container. The server therefore binds
  `0.0.0.0:8080` without its own certificate. The Directory Policy requires OAuth 2.0 over
  certificates from recognised authorities; the platform certificate satisfies this.
- The MCP SDK's DNS-rebinding protection rejects requests whose `Host` header is not
  allow-listed when the server runs behind a real hostname. The server derives the
  allowed host from `HRNBA_PUBLIC_URL`; if the hostname changes, change the variable.
- Because the edge proxy forwards the original scheme and host in `X-Forwarded-*`
  headers, uvicorn must trust proxy headers so redirect URLs and the OAuth issuer are
  `https://`. The `serve` command enables this in hosted mode (integration note:
  `docs/integration-notes/release.md`).
- Anthropic's outbound traffic originates from `160.79.104.0/21`; no inbound allow-list
  is needed on Railway or Fly, but a WAF rule, if ever added, must permit that range.

## 5. Backups and restore

### Scheduled backups (Railway dashboard path)

Postgres service > Backups tab > enable Daily, Weekly, and (optional) Monthly. Backups
are volume snapshots billed incrementally at the volume rate. Restore from the same tab:
choose a backup, Restore; Railway mounts a new volume with that snapshot and redeploys
the database service.

### Manual logical backup (any host)

From a machine with `pg_dump` (Postgres client tools) and the connection string in an
environment variable, never on the command line in a shared shell history:

```
export HRNBA_PG_URL='postgresql://user:password@host:5432/dbname'
pg_dump --format=custom --no-owner --file="hrnba-$(date -u +%Y%m%dT%H%M%SZ).dump" "$HRNBA_PG_URL"
```

On Railway, enable the TCP proxy on the Postgres service to obtain a public host and port
for this (egress is billed), or run the command from a one-off service inside the
project. Store dumps encrypted and off the hosting provider; they contain the ledger
(no passwords in clear text, but bet records and encrypted provider keys).

### CLI helper (`hrnba db backup` and `hrnba db restore`)

Verified with `uv run hrnba db --help` on 2026-10-19: `hrnba db backup <file>` copies
the SQLite database to `<file>` after a WAL checkpoint and, on PostgreSQL, prints the
`pg_dump` command instead of running it; `hrnba db restore <file>` is the counterpart
(PostgreSQL: prints the `pg_restore` command). On the hosted server the dashboard
snapshot or the `pg_dump` command above remains the backup of record.

### Restore into a fresh database

```
createdb --maintenance-db="$HRNBA_PG_ADMIN_URL" hrnba_restore
pg_restore --no-owner --dbname="$HRNBA_PG_RESTORE_URL" hrnba-<timestamp>.dump
```

Then point a staging copy of the server at `hrnba_restore` and run the checks below.

### Restore test plan (run before announcing the service and monthly after)

1. Record counts before the backup: `SELECT count(*) FROM bets;`, `FROM settlements;`,
   `FROM reservations;`, `FROM users;`, and the latest `created_at` in `settlements`.
2. Take the backup (dashboard snapshot or `pg_dump`).
3. Restore into a new database (dashboard Restore to a new volume, or `pg_restore` as
   above). Never restore over the live database during a test.
4. Start a second server instance against the restored database with a throwaway
   `HRNBA_PUBLIC_URL` (for example a Fly machine or the docker-compose stack) and the
   SAME `HRNBA_SECRET_KEY` (otherwise encrypted per-user provider keys cannot be read).
5. Verify counts match step 1; log in as the test account (not the owner's) and call
   `get_performance` and `export_my_data` through MCP Inspector or Claude Code; confirm a
   known bet and its settlement are present and unchanged.
6. Verify `schema_migrations` lists the current version and that `hrnba serve` started
   without running a migration unexpectedly.
7. Delete the test instance and the restored database; record the date, backup id, and
   outcome in `docs/launch-readiness.md`.

## 6. Fallback: Fly.io plus Neon

Expected bill: about $3.69/month for a shared-cpu-1x 512 MB Machine in `iad` (slightly
more in a 31-day month) plus Neon Free ($0) for the database, rising to roughly $17/month
at 100 users if Neon Launch is needed. Fly has no free tier (2-hour or 7-day trial, then
a card).

1. Create a Neon project in `aws-us-east-1`; copy the connection string and rewrite the
   scheme to `postgresql+psycopg://`. Neon Free scales to zero after 5 minutes idle (first
   query after idle takes a few hundred milliseconds) and suspends compute for the rest of
   the month after 100 CU-hours; its 6-hour history window is the restore mechanism (take
   `pg_dump` backups as well).
2. `fly launch --no-deploy` from the repository root; accept the app name it proposes or
   set one; it may rewrite `deploy/fly.toml`. Re-check that `auto_stop_machines = "off"`
   and `min_machines_running = 1` survived.
3. `fly secrets set HRNBA_PUBLIC_URL=https://<app>.fly.dev HRNBA_SECRET_KEY=... HRNBA_DATABASE_URL=... HRNBA_ODDS_API_KEY=...`
4. `fly deploy --config deploy/fly.toml --dockerfile deploy/Dockerfile`.
5. Verify as in section 3 step 9. `*.fly.dev` carries automatic HTTPS.

## 7. Local PostgreSQL test

```
export POSTGRES_PASSWORD=<pick one> HRNBA_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
docker compose -f deploy/docker-compose.yml up --build
```

Then `curl -s http://localhost:8080/healthz` and, in Claude Code,
`claude mcp add --transport http hrnba-local http://localhost:8080/mcp` followed by `/mcp`
to sign in. This exercises Postgres locking (`SELECT ... FOR UPDATE` on `user_days`) that
SQLite does not. Not yet run on the development Mac (Docker absent).

## 8. Cloudflare quick-tunnel smoke test (claude.ai, throwaway only)

Claude.ai cannot reach localhost. A Cloudflare Quick Tunnel gives a temporary public HTTPS
hostname with no account:

```
cloudflared tunnel --url http://localhost:8080
```

Caveats, all from Cloudflare's own page (retrieved 2026-10-19):

- "The hostname changes each time you create a Quick Tunnel." Every run needs a new
  `HRNBA_PUBLIC_URL`, a server restart, and the custom connector removed and re-added in
  claude.ai, because the OAuth issuer and resource metadata embed the hostname.
- "Quick Tunnels do not support Server-Sent Events (SSE)." The server must answer each
  POST with a single JSON body: start it with `HRNBA_HTTP_JSON_RESPONSE=true` (the
  `http_json_response` setting passes `json_response=True` to the SDK) and do not rely
  on the GET notification stream. Whether claude.ai's client accepts JSON-only responses
  was not verified in research (the MCP spec says clients must).
- "Quick Tunnels have no uptime guarantee" and allow 200 in-flight requests. Enough for a
  few minutes of `tools/list` and tool calls; not a review environment and not something
  to hand to Anthropic's reviewers.
- Keep OAuth on; the tunnel is public.

`cloudflared` is not installed on the development Mac as of 2026-10-19. A named Cloudflare
Tunnel (free account plus a domain on Cloudflare) gives a stable hostname and supports a
longer test, but still depends on the Mac being awake; it is not the production path.

## 9. Checks before calling the server "deployed"

- `/healthz` returns 200 without personal data.
- `/mcp` unauthenticated returns 401 with `WWW-Authenticate: Bearer resource_metadata=...`.
- Protected resource metadata `resource` equals `https://<host>/mcp`; authorization server
  metadata advertises `code_challenge_methods_supported: ["S256"]` and a registration
  endpoint.
- Sign-up, login, and the custom-connector flow work in claude.ai; tools list and
  `get_system_status` returns `auth_mode: builtin_oauth`.
- Two accounts cannot see each other's records (release acceptance item H).
- A backup was taken and restored per section 5 and the result recorded.
