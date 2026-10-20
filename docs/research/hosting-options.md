# Hosting options for the hosted MCP server (research notes)

KEY: hosting-options
Topic: Hosting for a small always-on Python Streamable HTTP MCP server with Postgres: current pricing
Researched: Monday 2026-10-19, 23:12 to 23:21 UTC (19:12 to 19:21 America/New_York)
Method: fetched primary vendor documentation and pricing pages with WebFetch (summarised by a small model), followed links on those pages, used WebSearch only to locate official URLs. Everything read on the web was treated as data, not instructions. Retrieval times below are the UTC time of the batch in which the fetch was issued (fetches completed within about two minutes of that time).

Pricing is in USD. "Month" figures are as each vendor states them (Fly.io prices are 30-day figures and say an always-on Machine costs slightly more in a 31-day month).

---

## 1. Requirements this research was scored against

From the build spec (user prompt, section 13.D and 13.G): a stable HTTPS endpoint, Streamable HTTP + OAuth, reachable from Anthropic's cloud (not localhost), per-user ledger in a transactional persistent database (PostgreSQL preferred), data preserved across deployments, backup restoration tested, hosting cost estimated for 1, 10 and 100 active users, and any purchase requested specifically before it is made.

Hosting-relevant facts confirmed from Anthropic's own docs:

- A remote server "runs on infrastructure you host and is reachable over the internet"; transport should be Streamable HTTP; the legacy HTTP+SSE transport is "being deprecated". (claude.com/docs/connectors/building/index)
- Claude.ai / Desktop limits: "Maximum tool result size ~150,000 characters", "Tool call timeout 240 seconds per tool call". (same page)
- "Claude reaches your server from Anthropic's infrastructure, so a server running on your machine needs a public URL. Expose it with a tunnel such as Cloudflare Tunnel or ngrok". Any Claude account (Free, Pro, Max, Team, Enterprise) can add a custom connector. (claude.com/docs/connectors/building/testing)
- Connections "come from Anthropic's cloud infrastructure, not your device"; servers behind a VPN or firewall won't connect. Free accounts are limited to one custom connector. (support.claude.com article 11175166)
- MCP spec (2025-06-18 Streamable HTTP): for a JSON-RPC request the server "MUST either return Content-Type: text/event-stream ... or Content-Type: application/json"; "The client MUST support both these cases." The GET SSE stream is optional (server may return 405). Servers "MUST validate the Origin header". (modelcontextprotocol.io spec)
- Python SDK v2 (py.sdk.modelcontextprotocol.io/run/): `mcp.run(transport="streamable-http", port=...)`; option `json_response=True` makes the server answer each POST with "a single JSON body instead of an SSE stream" (elicitation/sampling then raise NoBackChannelError; progress/log notifications are dropped). Default appears to be SSE streaming. Deploy page: without `transport_security=` the default DNS-rebinding protection, "Deployed behind a real hostname, that same default rejects every request until you say otherwise" -> allowlist the public hostname in `allowed_hosts`. Behind a TLS-terminating proxy run uvicorn with `--proxy-headers --forwarded-allow-ips=...`. The deploy page states the modern protocol revision it calls 2026-07-28 is sessionless ("Any worker serves any request"); legacy sessions need sticky routing or `stateless_http=True`.

Implication: the server must run always-on behind real TLS, with its public hostname allow-listed, and (if ever fronted by something that cannot stream SSE) with `json_response=True`.

---

## 2. Provider-by-provider answers (question 1)

### 2a. Fly.io (docs.fly.io; fly.io/docs/about/pricing now 301-redirects to docs.fly.io/about/pricing)

| Item | Finding | Source |
|---|---|---|
| Smallest always-on container | shared-cpu-1x: 256 MB "$2.19/month", 512 MB "$3.69/month", 1 GB "$6.70/month" (Ashburn iad / Secaucus ewr table; "Machine prices vary by region"); "Billed by the second while running"; "an always-on Machine costs slightly more in a 31-day month". Additional RAM "$6.00/GB/month". | docs.fly.io/about/pricing |
| Sleeping | No forced sleep, but `fly launch` writes `auto_stop_machines = "stop"`, `auto_start_machines = true`, `min_machines_running = 0`, so "Fly Proxy stops all of your app's Machines when there's no traffic". To stay always-on set `min_machines_running = 1` or `auto_stop_machines = "off"`. Stopped Machines are not billed for CPU/RAM but rootfs costs $0.15/GB/month. | docs.fly.io/launch/autostop-autostart |
| Free tier | "No. New organizations don't have a free tier or a monthly free usage allowance." Trial: "2 hours of machine runtime or 7 days of access, whichever comes first"; a payment method is needed to continue; apps stop when the trial ends. | docs.fly.io/about/pricing; docs.fly.io/about/free-trial |
| Managed Postgres (MPG) | Basic: Shared-2x CPU, 1 GB, "$38.00"/month; Starter 2 GB $72; storage "$0.28 per GB" per 30 days. "All plans include high availability, backups, and connection pooling", "Automatic backups and recovery" (retention not stated). MPG regions include iad, dfw, lax, ord, sjc (not ewr). | docs.fly.io/postgres; docs.fly.io/reference/regions |
| Unmanaged Postgres | Pricing page: single-node dev cluster "about $2/month" under "Unsupported Products". The what-you-should-know page carries an archive warning: "Fly Postgres (unmanaged) is no longer maintained, and Fly.io Support is not able to provide support or guidance for it"; it has "daily snapshots"; single node: "you will lose any data accumulated since the last snapshot" on failure. | docs.fly.io/about/pricing; docs.fly.io/postgres/getting-started/what-you-should-know |
| Volumes | $0.15/GB/month provisioned; snapshots $0.08/GB/month after first 10 GB free. "A volume exists on one server in a single region"; "Always provision at least two volumes per app"; daily snapshots kept 5 days by default (configurable 1 to 60). | docs.fly.io/about/pricing; docs.fly.io/volumes/overview |
| TLS / custom domain | Each app gets a fly.dev subdomain with HTTPS; `fly certs add example.com` and "Fly.io automatically validates your domain ownership and issues certificates" (Let's Encrypt). Managed certs: first 10 single-hostname certs free, then $0.10/month each. Shared IPv4 free; dedicated IPv4 $2/month. | docs.fly.io/networking/custom-domain; pricing page |
| Deploy | Dockerfile/`fly launch`/`fly deploy` (standard Fly workflow; not separately fetched - see unresolved) | - |
| Egress | North America "Outbound to the internet: $0.02/GB"; inbound free. | pricing page |
| Region near Florida | Miami (mia) and Atlanta (atl) do NOT appear in the current 17-region list. Closest US-East: iad Ashburn VA, ewr Secaucus NJ. | docs.fly.io/reference/regions |
| Support | Community free; Standard $29/month. | pricing page |

### 2b. Railway (railway.com/pricing; docs.railway.com)

| Item | Finding | Source |
|---|---|---|
| Plans | Free "$0/month, with $1/month in usage credits" (1 vCPU / 0.5 GB per service, 0 custom domains); Hobby "$5/month, with $5/month in usage credits" (2 custom domains, 5 GB max volume); Pro "$20/month per workspace" with $20 credit; Trial: "$5 one-time credit (30 days)". Included usage "is part of the subscription", does not roll over; above it "you will be charged the delta". | railway.com/pricing; docs.railway.com/reference/pricing/plans |
| Usage rates | Memory "$0.00000386 per GB/s" (= $10 per GB-month); CPU "$0.00000772 per vCPU/s" (= $20 per vCPU-month); Volumes "$0.00000006 per GB/s" (= $0.15 per GB-month); Egress "$0.05 per GB". "Billing is per second, so stopped services cost nothing." | railway.com/pricing |
| Sleeping | "Serverless" (formerly App-Sleeping) is a per-service toggle under Deploy > Serverless ("Enable Serverless"); when enabled the service sleeps after about 5 minutes without outbound traffic and the first request "may return a 502 Bad Gateway". Default state is not stated explicitly on the pages read; leave the toggle off. | docs.railway.com/reference/app-sleeping; docs.railway.com/pricing/cost-control |
| Postgres | Railway template "deploys a single node that Railway maintains", built on the official Postgres image, data on an attached Volume, private networking by default (`DATABASE_URL`), optional TCP proxy for public access (egress billed). HA with automatic failover is a separate conversion. Native Backups recommended; "point-in-time recovery also available". | docs.railway.com/databases/postgresql |
| Backups | Volume backups: Daily (kept 6 days), Weekly (27 days), Monthly (89 days), plus manual; billed incrementally at the volume rate; restore mounts a new volume and redeploys. Plan availability not stated. | docs.railway.com/reference/backups |
| TLS / domain | "Free SSL certificates automatically provisioned and renewed"; Railway-provided `.railway.app` domain via "Generate Domain"; custom domain needs the CNAME and TXT records Railway provides. | docs.railway.com/networking/public-networking |
| Deploy | "Railway will look for and use a `Dockerfile` at the root of the source directory"; override with `RAILWAY_DOCKERFILE_PATH`. GitHub-linked services "automatically deploy when new commits are pushed to the connected branch". | docs.railway.com/builds/dockerfiles; docs.railway.com/deployments/github-autodeploys |
| Region | "US East Metal (Virginia, USA): us-east4-eqdc4a" (also us-west2, europe-west4, asia-southeast1). | docs.railway.com/reference/regions |
| Card | "Railway requires the use of a post-paid card"; prepayment no longer offered. | docs.railway.com/reference/pricing/plans |
| Cost control | Hard usage limit (minimum $10) takes workloads offline when reached; soft limit emails. | docs.railway.com/pricing/cost-control |

### 2c. Render (render.com/pricing is JS-rendered; the markdown mirror render.com/pricing.md and docs were used)

| Item | Finding | Source |
|---|---|---|
| Workspace plans | Hobby "$0/month + compute", 5 GB bandwidth, 500 build minutes; Pro "$25/month + compute", 25 GB; Scale $499. Bandwidth overage "$0.15 per GB". | render.com/pricing.md |
| Smallest always-on web service | "0.5c-512mb": less than 1 CPU, 512 MB, "$7"/month. Next: 1c-2g $25. Free (512 MB, $0) spins down. | render.com/pricing.md |
| Free tier behaviour | Free web service spins down after "15 minutes without receiving any inbound traffic", restart takes about one minute; 750 free instance hours/workspace/month; docs: "Do not use them for production applications." Free Postgres "expire 30 days after creation", 1 GB, no backups. | render.com/docs/free |
| Postgres | "0.1c-256mb": 256 MB, 100 connections, "$6"/month, "1 GB SSD storage included", "Expandable storage ($0.30/GB)"; 0.5c-1g $19; 1c-2g $40. | render.com/pricing.md |
| Backups | Paid databases: continuous point-in-time recovery, window "Past 3 days" on Hobby workspace, "Past 7 days" on Pro; logical backups retained seven days; Free: no PITR, no Render-generated backups. Restore creates a new instance. | render.com/docs/postgresql-backups |
| TLS / domain | "Render automatically creates and renews TLS certificates for all custom domains, including wildcard domains"; HTTP redirected to HTTPS; included custom domains: 2 Hobby, 15 Pro; extra $0.25/month each. | render.com/docs/custom-domains |
| Deploy | Builds "based on the Dockerfile in your project repo" (Dockerfile Path setting); prebuilt registry images supported. | render.com/docs/docker |
| Persistent disk | "$0.25 per GB per month". | render.com/pricing.md |
| Region near Florida | Virginia, USA and Ohio, USA (plus Oregon, Frankfurt, Singapore); region cannot be changed after creation. | render.com/docs/regions |

### 2d. Neon (neon.com/pricing; docs)

| Item | Finding | Source |
|---|---|---|
| Free | "$0/month", "no credit card required"; 100 CU-hours per project per month; storage 1 GB per project (20 GB account total); "Scale-to-zero after 5 minutes" and it "cannot be turned off"; history window 6 hours; 5 GB egress/project. "Hitting compute-hour or egress limits suspends compute until the next billing period." | neon.com/pricing; neon.com/docs/introduction/plans |
| Launch | No base fee ("pay for what you use", "no minimum monthly fee"); compute "$0.106/CU-hour"; storage "$0.35/GB-month"; instant restore "$0.20/GB-month"; history window up to 7 days; scale-to-zero after 5 min "can be disabled"; 500 GB egress included. | same |
| Scale | $0.222/CU-hour; 30-day history window; scale-to-zero configurable "from 1 minute to always on"; uptime SLA. | same |
| CU | "approximately 4 GB of RAM" per CU; minimum compute 0.25 CU (1 GB RAM). | neon.com/docs/introduction/plans |
| Cold start | Suspended compute reactivates "within a few hundred milliseconds" on the next query. | neon.com/docs/introduction/scale-to-zero |
| Backups/restore | Branch history window (6 h Free / 7 d Launch / 30 d Scale); manual snapshots 1 (Free) or 100 (paid); scheduled snapshots $0.09/GB-month. | neon.com/pricing |
| Region | "US East (N. Virginia) aws-us-east-1", "US East (Ohio) aws-us-east-2"; Azure regions deprecated (no new projects). Region cannot be changed after project creation. | neon.com/docs/introduction/regions |

### 2e. Cloudflare Tunnel (question 3)

Quick Tunnels (TryCloudflare):

- "do not need a Cloudflare account or domain"; command `cloudflared tunnel --url http://localhost:8080`. (developers.cloudflare.com quick-tunnels page; canonical URL now developers.cloudflare.com/tunnel/get-started/quick-tunnels/)
- Limits quoted verbatim: "Each Quick Tunnel supports up to 200 in-flight requests. Additional requests return a 429 response." / "Quick Tunnels do not support Server-Sent Events (SSE)." / "Quick Tunnels have no uptime guarantee." / "The hostname changes each time you create a Quick Tunnel." No custom hostnames.
- HTTPS: try.cloudflare.com lists "Automatic HTTPS", example URL `https://quiet-marble-otter.trycloudflare.com`, "No account, DNS records, or open ports", "Ends with the process". The docs page itself does not state the URL scheme.
- Verdict for a claude.ai custom-connector smoke test: workable only with caveats. (1) Because SSE is unsupported, run the Python SDK with `json_response=True` (and do not rely on the GET notification stream). (2) The hostname changes on every run, so the OAuth issuer / protected-resource metadata and the allow-listed host change each time and the connector must be re-added in claude.ai each session. (3) No uptime guarantee and 200 in-flight cap; fine for a few minutes of tools/list and tool calls, not for multi-day testing or review by Anthropic.

Named tunnel (Cloudflare Tunnel):

- Prerequisites: "A Cloudflare account", "A domain on Cloudflare (required to publish applications)", a host running `cloudflared`; outbound port 7844 must be reachable. Public hostname routes map a hostname to e.g. `http://localhost:8000`; a proxied CNAME points at `<TUNNEL_ID>.cfargotunnel.com`; "Cloudflare automatically proxies traffic through its network, applying CDN caching, WAF, and DDoS protection." (developers.cloudflare.com/tunnel/get-started/)
- Plan: the Tunnel product page says "Available on all plans"; Cloudflare's Free website plan is $0 ("Sign Up Free"). Neither page states a tunnel-specific price; Cloudflare Registrar "does not mark up domain prices at all" but lists no per-TLD prices on the page read. So: free with a free Cloudflare account plus a domain you already own or buy (domain price not confirmed here).
- Suitability: stable HTTPS hostname, so OAuth metadata and connector config stay valid; still depends on the Mac being awake and online, so it is a dev/test path, not the production deployment.

ngrok (the other tunnel Anthropic's testing page names): Free plan "$0", "Up to 3 online endpoints", one assigned dev domain, "Up to 1GB data transfer", "Up to 20k HTTP/S requests" per month, and "Interstitial page on HTTP/S endpoints"; first paid plan Hobbyist $10/month. (ngrok.com/pricing) The interstitial behaviour for non-browser MCP clients was not verified.

---

## 3. Monthly estimates for 1, 10 and 100 active users (question 2)

Assumptions (stated so they can be changed):

- 30-day month; 20 MCP tool calls per active user per day -> 600 / 6,000 / 60,000 calls per month.
- About 2 KB in and 20 KB out per call -> egress about 0.012 / 0.12 / 1.2 GB per month.
- About 0.2 CPU-seconds per call -> 0.03 / 0.33 / 3.3 vCPU-hours per month (negligible everywhere).
- Python server (uvicorn + MCP SDK + httpx + asyncpg) around 200 MB resident; a self-hosted Postgres container around 150 MB.
- Database stays under 1 GB at all three tiers (ledger rows are tiny).
- No background workers; odds-provider fees are excluded (separate research key).
- Neon Free compute: usage clustered around the NBA evening slate; assume the database is awake about 1 h/day (1 user), 4 h/day (10), 16 h/day (100) at 0.25 CU -> 7.5 / 30 / 120 CU-hours per month. The 100-user case exceeds the Free plan's 100 CU-hours, so it is priced on Launch (120 x $0.106 = $12.72 + $0.35 storage).

| Option (region) | 1 user | 10 users | 100 users | Notes |
|---|---|---|---|---|
| A. Railway Hobby: app + Railway Postgres + daily backups (us-east4 Virginia) | ~$5.00 | ~$5.00 | ~$5 to $7 | Estimated usage: app RAM 0.2 GB x $10 = $2.00; Postgres RAM 0.15 GB x $10 = $1.50; CPU under $0.60; volume 1 GB x $0.15; backups a few cents; egress up to $0.06. Total about $4 to $4.5, inside the $5 included usage, so the bill is the $5 plan fee. If real RSS is 300 MB+ the bill rises by the delta (about $1 to $2). |
| B. Fly.io shared-cpu-1x 512 MB always-on (iad) + Neon Postgres (aws-us-east-1) | ~$3.70 | ~$3.70 | ~$3.75 (Neon Free) or ~$16.80 (Neon Launch) | $3.69 Machine (about $3.81 in a 31-day month) + egress $0.00 to $0.02 + Neon $0 (Free) or about $13 (Launch at 120 CU-h). Choose 1 GB Machine ($6.70) if memory is tight. Neon Free risk: compute suspended for the rest of the month if 100 CU-h are exceeded. |
| C. Fly.io 512 MB + Fly Managed Postgres Basic (iad) | ~$42 | ~$42 | ~$42 | $3.69 + $38.00 + storage $0.28/GB (about $0.28). HA and automatic backups included. |
| D. Render Hobby workspace: web 0.5c-512mb + Postgres 0.1c-256mb (Virginia or Ohio) | $13.00 | $13.00 | $13.00 | $7 + $6; 1 GB DB storage included; 1.2 GB egress is within the 5 GB included (overage would be $0.15/GB). PITR 3 days included. 1c-2g web service would make it $31. |
| E. Render web 0.5c-512mb + Neon Free/Launch | $7.00 | $7.00 | $7.00 to $20 | As D for the app, Neon as in B. |
| F. Fly.io 512 MB + unmanaged Fly Postgres single node (iad) | ~$5.85 | ~$5.85 | ~$5.90 | $3.69 + about $2 + 1 GB volume $0.15. Unsupported/archived product; single node loses data since the last daily snapshot on failure. Not recommended for the ledger. |

Reading: at this scale cost is dominated by the fixed always-on container plus the database floor; per-call CPU and egress are cents. Going from 1 to 100 users changes the bill by at most a few dollars on A/D and by the Neon plan step on B/E.

---

## 4. Recommendation (question 4)

Primary: Railway Hobby plan, one project in us-east4 (Virginia) containing the MCP server service (Dockerfile at repo root, GitHub auto-deploy) and the Railway Postgres service with Daily + Weekly volume backups enabled; Serverless toggle left OFF; use the generated `*.railway.app` HTTPS domain first, add a custom domain later if wanted (2 included). Expected bill about $5/month at 1 to 10 users, about $5 to $7 at 100. Reasons: one vendor and one bill; cheapest option that includes Postgres with a built-in scheduled backup and in-dashboard restore (so "test backup restoration" is a documented click path); automatic TLS; Virginia region; hard usage limit available to cap spend. Caveats: Railway Postgres is a single node on a volume (no automatic failover unless converted to HA); the exact split of the $5 credit depends on measured RAM; Railway bills via a post-paid card.

Fallback: Fly.io shared-cpu-1x 512 MB in iad with `min_machines_running = 1` (or `auto_stop_machines = "off"`), plus Neon Postgres in aws-us-east-1 (Free to start, Launch when CU-hours approach 100). About $3.70/month at 1 to 10 users, about $17 at 100 on Launch. Reasons: lowest fixed cost, Fly and Neon sit in the same AWS Northern Virginia metro, Neon branch history gives point-in-time restore without running Postgres yourself. Caveats: two accounts; Fly has no free tier and needs a card after a 2-hour/7-day trial; Neon Free scale-to-zero adds a few hundred ms to the first query after idle and a hard monthly CU-hour cap; `fly launch` defaults would stop the Machine unless the fly.toml is edited.

Render ($13/month) is the "fully managed with PITR, no tuning" alternative if the owner prefers simplicity over price; Fly Managed Postgres ($38/month) is more than the rest of the stack and is not justified for a tiny ledger.

Development/test path: run the server locally and expose it with a Cloudflare named tunnel (free account + a domain on Cloudflare) for a stable HTTPS hostname; use a Quick Tunnel only for a throwaway smoke test with `json_response=True`, knowing the hostname and OAuth metadata change each run.

What must be purchased or signed up, and by whom (the project owner, Noel, using his own card and accounts; nothing is bought by this build):

1. Railway account on Hobby ($5/month, post-paid card required). If the fallback is chosen instead: Fly.io account with payment method (pay-as-you-go, about $3.69/month) and a Neon account (Free, no card).
2. Optional: a custom domain (any registrar; Cloudflare Registrar sells at registry cost, price per TLD not confirmed here). Not required: both Railway (`*.railway.app`) and Fly (`*.fly.dev`) give HTTPS hostnames.
3. For local testing through a named Cloudflare Tunnel: a free Cloudflare account and a domain on Cloudflare. Quick Tunnels need nothing.
4. Claude side: any Claude account can add the custom connector (Free accounts: one connector).

---

## 5. Sources

| URL | retrieved_at_utc | What it established |
|---|---|---|
| https://fly.io/docs/about/pricing/ | 2026-10-19 23:12 | 301 redirect to https://docs.fly.io/about/pricing |
| https://docs.fly.io/about/pricing | 2026-10-19 23:13 and 23:15 | shared-cpu-1x 256MB $2.19, 512MB $3.69, 1GB $6.70 (iad); no free tier; trial 2 h / 7 days; MPG from $38; volumes $0.15/GB; egress $0.02/GB NA; certs first 10 free then $0.10; dedicated IPv4 $2; unmanaged PG about $2; support tiers |
| https://docs.fly.io/launch/autostop-autostart/ | 2026-10-19 23:15 | fly launch defaults auto_stop "stop", min_machines_running 0; how to keep always-on; stopped rootfs billing |
| https://docs.fly.io/about/free-trial | 2026-10-19 23:15 | trial contents; payment method needed to continue; apps stop at trial end |
| https://docs.fly.io/postgres | 2026-10-19 23:15 | MPG plans Basic $38 (1 GB) to Performance $1,922; storage $0.28/GB; HA, backups, pooling included |
| https://docs.fly.io/reference/regions | 2026-10-19 23:15 and 23:17 | 17 regions; US: iad, ewr, ord, dfw, lax, sjc; no mia/atl; MPG regions |
| https://docs.fly.io/networking/custom-domain/ | 2026-10-19 23:15 | fly certs add; automatic Let's Encrypt certs; fly.dev subdomain |
| https://docs.fly.io/postgres/getting-started/what-you-should-know/ | 2026-10-19 23:18 | unmanaged Fly Postgres archived/unsupported; daily snapshots; single-node data-loss warning |
| https://docs.fly.io/volumes/overview/ | 2026-10-19 23:18 | volume on one server; two volumes recommended; daily snapshots kept 5 days (1 to 60) |
| https://railway.com/pricing | 2026-10-19 23:12 | plans Free/Hobby/Pro and credits; per-second rates for memory, CPU, volumes; egress $0.05/GB; per-plan limits |
| https://docs.railway.com/reference/pricing/plans | 2026-10-19 23:13 | included usage semantics; overage billed as delta; post-paid card required; per-plan RAM/vCPU caps |
| https://docs.railway.com/reference/app-sleeping | 2026-10-19 23:13 | Serverless sleep after about 5 min inactivity; 502 on first wake |
| https://docs.railway.com/pricing/cost-control | 2026-10-19 23:15 | Serverless is a toggle under Deploy; hard/soft usage limits (hard min $10) |
| https://docs.railway.com/pricing/faqs | 2026-10-19 23:15 | usage billed in arrears; Hobby $5 includes $5 usage, excess charged |
| https://docs.railway.com/pricing/free-trial | 2026-10-19 23:17 | $5 one-time trial, then Free plan with $1/month; trial volumes deleted 30 days after credits expire |
| https://docs.railway.com/reference/regions | 2026-10-19 23:13 | us-east4-eqdc4a Virginia and other regions |
| https://docs.railway.com/reference/databases | 2026-10-19 23:13 | Postgres template; data persisted via attached Volume |
| https://docs.railway.com/databases/postgresql | 2026-10-19 23:15 | single node Railway maintains; private DATABASE_URL; HA optional; backups + PITR available |
| https://docs.railway.com/reference/backups | 2026-10-19 23:13 | daily/weekly/monthly schedules and retention; incremental billing at volume rate; restore steps |
| https://docs.railway.com/networking/public-networking | 2026-10-19 23:15 | free auto-renewed SSL; .railway.app domain; custom domain CNAME + TXT |
| https://docs.railway.com/builds/dockerfiles | 2026-10-19 23:15 | Dockerfile auto-detected at root; RAILWAY_DOCKERFILE_PATH |
| https://docs.railway.com/deployments/github-autodeploys | 2026-10-19 23:20 | auto-deploy on push to connected branch |
| https://docs.railway.com/networking/specs-limits | 2026-10-19 23:20 | 404 (request timeout limits not confirmed) |
| https://render.com/pricing | 2026-10-19 23:13 | page is JS-rendered; headings only |
| https://render.com/pricing.md | 2026-10-19 23:15 | workspace plans; 0.5c-512mb $7; Postgres 0.1c-256mb $6 with 1 GB included, $0.30/GB extra; disk $0.25/GB; bandwidth overage $0.15/GB |
| https://render.com/docs/free | 2026-10-19 23:13 | free web service spin-down after 15 min, about 1 min cold start; free Postgres expires after 30 days; not for production |
| https://render.com/docs/postgresql-backups | 2026-10-19 23:15 | PITR 3 days (Hobby) / 7 days (Pro) for paid DBs; logical backups 7 days; Free has none |
| https://render.com/docs/custom-domains | 2026-10-19 23:15 | automatic TLS incl. wildcard; 2 custom domains on Hobby; $0.25/month extra |
| https://render.com/docs/docker | 2026-10-19 23:15 | Dockerfile builds from repo; prebuilt images |
| https://render.com/docs/regions | 2026-10-19 23:13 | Oregon, Ohio, Virginia, Frankfurt, Singapore |
| https://neon.com/pricing | 2026-10-19 23:12 | Free/Launch/Scale details, rates, history windows, no card for Free, no minimum on paid |
| https://neon.com/docs/introduction/plans | 2026-10-19 23:13 | CU definition (~4 GB RAM), 0.25 CU minimum, scale-to-zero rules per plan |
| https://neon.com/docs/introduction/scale-to-zero | 2026-10-19 23:15 | 5-minute default; restart within a few hundred milliseconds; Free cannot disable |
| https://neon.com/docs/introduction/regions | 2026-10-19 23:13 | aws-us-east-1, aws-us-east-2 etc.; Azure deprecated; region fixed per project |
| https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/ | 2026-10-19 23:12 and 23:13 | quick tunnel: no account/domain; 200 in-flight; no SSE; no uptime guarantee; hostname changes; canonical URL now /tunnel/get-started/quick-tunnels/ |
| https://try.cloudflare.com/ | 2026-10-19 23:17 | "Automatic HTTPS"; example https://quiet-marble-otter.trycloudflare.com; "Ends with the process" |
| https://developers.cloudflare.com/tunnel/get-started/ | 2026-10-19 23:13 | named tunnel prerequisites: Cloudflare account, domain on Cloudflare; public hostname routing; port 7844 |
| https://developers.cloudflare.com/tunnel/ | 2026-10-19 23:15 | "Available on all plans" |
| https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/ | 2026-10-19 23:17 | Cloudflare One tunnel docs (private networking focus); no pricing statement |
| https://www.cloudflare.com/plans/free/ | 2026-10-19 23:15 | Free plan exists ("Sign Up Free"); no tunnel mention |
| https://www.cloudflare.com/plans/zero-trust-services/ | 2026-10-19 23:13 | page content not rendered; no numbers obtained |
| https://www.cloudflare.com/products/registrar/ | 2026-10-19 23:17 | "does not mark up domain prices at all"; no per-TLD prices listed |
| https://www.cloudflare.com/tld-policies/ | 2026-10-19 23:17 | registry operators only; no prices |
| https://blog.cloudflare.com/a-free-argo-tunnel-for-your-next-project/ | 2026-10-19 23:15 | 2019 post: free tunnels for testing/development, not production |
| https://raw.githubusercontent.com/cloudflare/cloudflared/master/README.md | 2026-10-19 23:17 | TryCloudflare mentioned; no example URL |
| https://ngrok.com/pricing | 2026-10-19 23:17 | Free: 3 endpoints, 1 dev domain, 1 GB, 20k requests, interstitial; Hobbyist $10/month |
| https://support.claude.com/en/articles/11175166-getting-started-with-custom-connectors-using-remote-mcp | 2026-10-19 23:13 | custom connectors on all plans (Free limited to one); connections come from Anthropic's cloud; must be publicly reachable |
| https://claude.com/docs/connectors/building/index | 2026-10-19 23:15 | remote server hosted by you; Streamable HTTP; 150k char result limit; 240 s tool timeout; redirect URI https://claude.ai/api/mcp/auth_callback |
| https://claude.com/docs/connectors/building/testing | 2026-10-19 23:17 | tunnel with Cloudflare Tunnel or ngrok; keep auth on; Inspector CLI; connection-failure causes |
| https://modelcontextprotocol.io/specification/2025-06-18/basic/transports | 2026-10-19 23:13 | server may answer POST with JSON or SSE; client must support both; GET stream optional; Origin validation |
| https://py.sdk.modelcontextprotocol.io/ and /llms.txt | 2026-10-19 23:17 | v2 is current stable line; docs index |
| https://py.sdk.modelcontextprotocol.io/run/ | 2026-10-19 23:17 | run(transport="streamable-http"), json_response=True (single JSON body instead of SSE), stateless_http, limits |
| https://py.sdk.modelcontextprotocol.io/run/deploy/ | 2026-10-19 23:18 | DNS-rebinding default rejects requests behind a real hostname; allowed_hosts; proxy headers; sessionless modern protocol (page labels it 2026-07-28) |
| https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/main/README.md | 2026-10-19 23:15 | README defers to py.sdk.modelcontextprotocol.io; `mcp run server.py --transport streamable-http` |
| WebSearch (render pricing; cloudflare free plan) | 2026-10-19 23:13 and 23:17 | located render.com/pricing.md; third-party claims about Zero Trust "50 users" not used as findings |

## 6. Unresolved

- Fly.io price for the exact machine in regions other than iad/ewr (the page says prices vary by region; mia is not offered at all).
- Whether Railway bills memory on measured usage versus a reserved amount, and the real RSS of the server, which decides whether usage stays inside the $5 Hobby credit.
- Railway Serverless default state (documented only as a toggle) and Railway request/idle timeout limits (specs page 404).
- Railway: whether volume backups / PITR need Hobby or Pro (plan availability not stated).
- Render: a third-party post claims a plan change on 1 August 2026 and a bandwidth cut; Render's own pricing.md (5 GB on Hobby) is what is recorded here; no Render changelog was fetched.
- Fly MPG backup retention window and GA status; Fly Dockerfile deploy page not fetched (standard workflow assumed).
- Cloudflare: Zero Trust plan page did not render; the "free up to 50 users" figure appears only in third-party sources and is not needed for a public-hostname tunnel. Domain prices not obtained.
- ngrok Free interstitial page: whether it interferes with Anthropic's non-browser MCP client was not tested.
- Whether claude.ai's MCP client works against a server that returns `json_response=True` (spec says clients MUST accept JSON; not verified against Claude).
- The Python SDK docs refer to a protocol revision "2026-07-28" as sessionless; this was not cross-checked against modelcontextprotocol.io.
- Idle/connection timeouts of each provider's edge proxy versus Claude's 240 s tool-call limit (not fetched; the planned tool calls should finish in seconds).
