# Costs: data providers, hosting, and a 30-day estimate

Prices are as printed on the vendor pages retrieved 2026-10-19 (see `docs/sources.md`).
Nothing has been purchased by this build. The owner buys with his own card after reading
this file. The $10 daily wagering limit is not permission for data charges.

## 1. The Odds API (odds, Hard Rock Florida key `hardrockbet_fl`, scores)

| Plan | Price | Credits per month | Bookmakers |
|---|---|---|---|
| Starter | free | 500 | "Most bookmakers" (the paid-only keys are listed; no Hard Rock key and not `pinnacle` are among them, so coverage on the free plan is inferred, not stated) |
| 20K | $30 per month | 20,000 | all |
| 100K | $59 per month | 100,000 | all |
| 5M | $119 per month | 5,000,000 | all |
| 15M | $249 per month | 15,000,000 | all |

Credits reset on the first of each month; paid plans bill immediately and are
non-refundable; no overage mechanism is documented (at the limit the API returns 401).
Terms allow use in user-facing apps including commercial ones as long as the data is
not resold as a raw feed; attribution appreciated but not required.

### Worked credit model (from `docs/research/the-odds-api.md` section 11)

Cost rules: `/odds` = markets x regions (10 bookmakers count as one region);
`/events` = 0; `/events/{id}/markets` = 1; `/events/{id}/odds` = unique markets returned
x regions; `/scores?daysFrom=1` = 2.

One research pass over a slate of N games, `bookmakers=hardrockbet_fl,pinnacle` (one
region-equivalent):

| Call | Credits |
|---|---|
| featured odds, `h2h,spreads,totals` | 3 |
| per game: market discovery | 1 x N |
| per game: props and alternates, up to 7 markets, charged only when returned | up to 7 x N |
| scores for settlement, `daysFrom=1` | 2 |

Opening night (N = 3): 3 + 3 + 21 + 2 = up to 29 credits. A typical 6-game night: about
41 credits. A pre-handoff refresh repeats the featured call (3) plus the prop markets of
the three chosen legs (about 3), so a day with one refresh is roughly 35 (3 games) to
50 (6 games) credits. Thirty days: about 1,000 to 1,500 credits for one user.

Conclusion: the free Starter plan (500 per month, about 16 per day) cannot sustain
daily prop coverage. It can sustain a restricted routine of one featured call plus props
on one or two chosen games (about 10 to 17 credits per day). The 20K plan ($30 per
month, about 650 per day) covers the full routine with room for refreshes.

### Multi-user credit use

Assumptions: the server caches each provider request for 60 seconds and shares cached
slate data across users; each user triggers one research pass and one refresh per day.
Two guards apply on the server-wide key: the app-wide daily credit guard
(`HRNBA_DAILY_PROVIDER_CREDIT_BUDGET`, default 25 per ET day, sized for the free tier)
and the per-user daily quota (`HRNBA_PER_USER_DAILY_CREDIT_QUOTA`, default 30). Once a
guard is reached the server serves cached or null data with the reason code
`PROVIDER_CREDIT_GUARD`. The table assumes the owner raises the app-wide guard to about
200 per day after subscribing to the 20K plan; at the default 25 the full routine stops
after the featured call and one or two games' props, which is the intended free-tier
behaviour.

| Active users | Credits per day (estimate) | Credits per month | Plan |
|---|---|---|---|
| 1 | 35 to 50 | 1,000 to 1,500 | 20K ($30) |
| 10 | 60 to 120 (slate fetch shared; refreshes per user) | 2,000 to 3,600 | 20K ($30) |
| 100 | capped at 200 by the app-wide guard (each user also capped at 30); without the caps about 400 to 700 | 6,000 (capped) or 12,000 to 21,000 | 20K with the guard, 100K ($59) without it |

Users may store their own key (`set_user_settings`), in which case their calls are
billed to their plan and the server key is not used for them. The Odds API terms require
the key holder to keep the key private; per-user keys are encrypted at rest and never
returned by any tool.

## 2. balldontlie (player stats for prop settlement, injuries)

| Tier | Price | Rate limit | Includes `/v1/stats` (player box scores) |
|---|---|---|---|
| Free | $0 | 5 requests per minute | no |
| All-Star | $9.99 per month per sport | 60 per minute | yes (plus player injuries) |
| GOAT | $39.99 per month per sport | 600 per minute | yes, plus box scores, season averages, odds, props |
| All-Access | $299.99 per month, all sports | 600 per minute | yes, plus webhooks |

Day-one position: not required. Hard Rock's own settlement (reported by the user from
the app) is authoritative for money; The Odds API `/scores` (1 to 2 credits) gives a
provisional result for team legs. Automatic provisional settlement of player props would
need All-Star ($9.99 per month) and is a later purchase, to be requested separately with
a demonstrated need. stats.nba.com is not used: the NBA Terms of Use forbid use of NBA
Statistics "in connection with any gambling activity".

## 3. Hosting (from `docs/research/hosting-options.md`)

Assumptions: 30-day month; 20 tool calls per active user per day; about 2 KB in and 20
KB out per call; about 0.2 CPU-seconds per call; server about 200 MB resident; Postgres
about 150 MB; database under 1 GB; no background workers.

| Option | 1 user | 10 users | 100 users |
|---|---|---|---|
| A. Railway Hobby: server + Railway Postgres + daily backups (us-east4), primary | about $5.00 | about $5.00 | about $5 to $7 |
| B. Fly.io shared-cpu-1x 512 MB (iad) + Neon Postgres (aws-us-east-1), fallback | about $3.70 | about $3.70 | about $3.75 (Neon Free) or about $16.80 (Neon Launch) |
| C. Fly.io + Fly Managed Postgres Basic | about $42 | about $42 | about $42 |
| D. Render Hobby: web 0.5c-512mb + Postgres 0.1c-256mb | $13 | $13 | $13 |

Cost is dominated by the always-on container and the database floor; per-call CPU and
egress are cents. Railway bills a post-paid card; Fly has no free tier; Neon Free needs
no card.

## 4. Thirty-day estimate for the owner (2026-10-20 to 2026-11-18)

| Item | Amount | Required |
|---|---|---|
| The Odds API 20K plan | $30 | yes, unless the routine is restricted to the free tier's roughly 16 credits per day |
| Railway Hobby (server + Postgres + backups) | $5 (one month; usage inside the included $5) | yes, for the hosted connector; not needed for local stdio use |
| balldontlie All-Star | $9.99 | no (optional later) |
| Custom domain | not required; `*.railway.app` or `*.fly.dev` carry HTTPS | no |
| Cloudflare named tunnel for local testing | $0 plus a domain | no |
| Claude plan | already held (Max) | yes, for submission and plugins |

Total required for the 30-day window: about $35 (about $5 if the free odds tier is
used with a restricted routine). For comparison, the maximum gross stake in the window
at the $10 cap is $300. The server records these costs through `add_cost` so the review
shows an after-cost result.

## 5. Who buys what

All purchases are made by the owner, Noel Fernandez, on his own accounts:

1. The Odds API subscription (key stored as `HRNBA_ODDS_API_KEY` on the server, never in
   the repository).
2. Railway Hobby (or Fly.io plus Neon) with the hard usage limit set.
3. Optional later: balldontlie All-Star, a domain.

Public users bring their own Claude account (paid plan for plugins) and create their own
server account. They receive no access to the owner's Claude subscription or to his
provider key beyond the server-wide key the owner chooses to share through the server,
subject to the app-wide credit guard and the per-user quota.
