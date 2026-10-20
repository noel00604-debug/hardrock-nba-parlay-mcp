# Research notes: stats/results sources for settlement, Pinnacle reference, parlay-quote availability

KEY: `stats-results-reference`
Researched: 2026-10-19, 23:12 to 23:19 UTC (Monday evening, America/New_York)
Build context: Python MCP server (Streamable HTTP + OAuth) plus Claude plugin bundle for researching exactly-three-leg NBA parlays on Hard Rock Bet Florida; $10/day user budget; user places wagers manually.

All web content below is quoted as data. Quotes are kept short (max ~20 words). Times are UTC. Where I could not confirm something, it is listed under "Unresolved".

---

## 1. Short answers to the five questions

### Q1. Official final box scores (player PTS/REB/AST/3PM, team scores)

| Source | What it gives | Player IDs | Cost | Terms problem for this build | Verdict |
|---|---|---|---|---|---|
| stats.nba.com via `nba_api` (unofficial MIT wrapper, v1.11.4, 2026-02-20) | Full official box score (`boxscoretraditionalv3`: `personId`, `points`, `reboundsTotal`, `assists`, `threePointersMade`) | Yes (`personId`, static `players.py`) | Free, no key | NBA Terms of Use: NBA Statistics "may not be used in connection with any gambling activity (including legal gambling activity)". Also: live probe from this Mac timed out (15 s curl, 20 s urllib) and cdn.nba.com returned 403; community reports cloud IPs are blackholed. | Do not depend on it in production. |
| balldontlie | `/v1/stats` game player stats with `pts`, `reb`, `ast`, `fg3m`, nested `player` and `game` (`status_state: "final"`); `/v1/player_injuries`; `/v1/box_scores` | Yes (`player.id`) | Free tier does NOT include `/v1/stats`; ALL-STAR $9.99/mo (60 req/min) includes `/v1/stats` + injuries; GOAT $39.99/mo adds box scores, season averages, odds, props | Terms allow personal or commercial use; keys must not be shared; no reselling raw data; "unlawful gambling" prohibited (legal use not prohibited) | Primary settlement source (ALL-STAR tier). |
| ESPN unofficial `site.api.espn.com` | `scoreboard?dates=YYYYMMDD` (team scores, `STATUS_FINAL`, `completed: true`); `summary?event=ID` returns `boxscore.players[].statistics[].athletes[]` with `athlete.id`, `points`, `rebounds`, `assists`, 3PT as a `"made-attempted"` string | Yes (`athlete.id`) | Free, no key, undocumented | Disney Terms of Use 2.B(x) prohibit automated access and 2.B(viii) prohibit commercial use; no stability guarantee | Dev-time cross-check only; not a production dependency. |
| The Odds API `/scores` | Team scores only (`completed`, `scores[]` of team name + score), `daysFrom` 1..3, "Live scores update approximately every 30 seconds." | n/a (teams) | 1 credit (2 with `daysFrom`) | T&C allow user-facing apps; no redistribution as standalone data product | Fine for team legs (ML/spread/total); cannot settle player props. |

### Q2. Player identity

- Stable IDs exist in balldontlie (`/v1/players` -> `id`, `first_name`, `last_name`, `position`, `jersey_number`, `team{...}`), in `nba_api` static data (`id`, `full_name`, `is_active`) and in ESPN (`athlete.id`).
- The Odds API props carry NO player ID: "Relevant markets will have a description field in their outcomes." The example value is a plain name string (`"description": "David Blough"`). The `/participants` endpoint "does not return players on a team" (NBA returns teams only).
- Proposed matching: see section 4.

### Q3. Any API with Hard Rock Bet combined parlay / SGP prices?

None found.
- The Odds API v4 docs: zero occurrences of "parlay", "sgp", "same game", "combined", "correlat" (grep of the full docs page, 66,402 chars of text). It does list `hardrockbet_fl` (Hard Rock Bet (FL), region `us2`) for individual markets.
- balldontlie `/v2/odds` and player props list 13 / 9 vendors; Hard Rock Bet is not among them, and no parlay product is documented.
- Hard Rock Bet has no public API per a third-party vendor page (SharpAPI): "There is no public Hard Rock Bet API for odds data." and "There is no developer portal, no API key system, and no API documentation." (vendor claim; medium confidence). Trade press (Legal Sports Report) reports Hard Rock Bet integrated Kambi's Odds Feed+ API, a B2B supplier feed, not a developer product.
- Pinnacle's public API is closed (see Q4), so no parlay pricing from there either.

Conclusion: the combined price must be entered by the user from the Hard Rock Bet app, or estimated from leg prices with an explicit "estimate" label.

### Q4. Pinnacle as a reference

- Via The Odds API: key `pinnacle`, region `eu`. Bookmaker-page note, verbatim: "Odds are from public website which may incur a delay". Pinnacle is not among the bookmakers flagged "Only available on paid subscriptions" (those are `williamhill_us`, `fanatics`, `courtside`, `rebet`, `bet365_au`, `dabble_au`, `bet99_ca_on`), so it should be included in the free Starter plan ("Most bookmakers"). That inclusion is inferred, not stated outright.
- Request shape: `bookmakers=pinnacle` (takes priority over `regions`; "Every group of 10 bookmakers is the equivalent of 1 region."), so a Pinnacle-only query costs the same as one region.
- Pinnacle's own API: "Access to Pinnacle API suite has been closed for the general public since July 23rd, 2025."; "We offer bespoke data services for select high value bettors & commercial partnerships." (contact api@pinnacle.com); "Please note that in order to access Pinnacle API, you must have a funded account." Pinnacle also states: "we do not accept bets from any gamers based in the USA, whether residents or visitors." So direct Pinnacle API access is not a realistic path for a US hobby tool.
- Alternatives in The Odds API: `betonlineag` (listed in both `us` and `eu`), `lowvig` (`us`). Circa / `circasports` is NOT listed anywhere on the bookmaker page (grep: 0 hits). Exchanges: `betfair_ex_eu`, `matchbook` (`eu`), `novig`, `prophetx`, `kalshi` (`us_ex`).
- Whether Pinnacle (or BetOnline/LowVig) exposes NBA player props through The Odds API was not verified; the docs say "Coverage of player props is mainly limited to US sports and US bookmakers at this time."

### Q5. NBA data licensing restrictions relevant to a public tool

- NBA Terms of Use (LAST UPDATED: July 13, 2026), section 9 "NBA Statistics", verbatim fragments:
  - "(i) any use, display, or publication of the NBA Statistics shall include a prominent attribution to NBA.com"
  - "(ii) the NBA Statistics may only be used, displayed, or published for legitimate news reporting or private, non-commercial purposes"
  - "(iv) the NBA Statistics may not be used in connection with any gambling activity (including legal gambling activity)"
  - "(v) the NBA Statistics may not be used in connection with any fantasy game or other commercial product or service"
  - "(vii) ... a database (in any medium or format) of comprehensive, regularly updated statistics ... without the Operator's express prior consent"
- Official betting data is licensed to operators through Sportradar and Genius Sports: "non-exclusive rights to distribute official NBA and WNBA betting data to licensed sports betting operators" (pr.nba.com, Oct 29, 2020). Not available to a hobby tool.
- Practical effect: a public parlay-research tool should not pull from stats.nba.com / cdn.nba.com. Use a licensed aggregator (balldontlie) whose terms permit the use.

---

## 2. Detailed findings with evidence

### 2.1 nba_api (unofficial wrapper for stats.nba.com)

- Repo: https://github.com/swar/nba_api (retrieved 23:12 UTC). "`nba_api` is an API Client for `www.nba.com`." MIT license. Hosted under an individual account; not affiliated with the NBA. "NBA.com does not provide information regarding new, changed, or removed endpoints." The README notes "NBA.com has a Terms of Use regarding the use of the NBA's digital platforms."
- PyPI: https://pypi.org/project/nba_api/ (23:14 UTC): latest "1.11.4", released "Feb 20, 2026", "Python >=3.10".
- Box score endpoint doc (23:15 UTC): `https://stats.nba.com/stats/boxscoretraditionalv3`; `GameID` must match `^\d{10}$` (example `0021700807`); `player_stats` columns include `personId`, `firstName`, `familyName`, `minutes`, `points`, `reboundsTotal`, `assists`, `threePointersMade`, `threePointersAttempted`, `plusMinusPoints`.
- Static players doc (23:15 UTC): `find_players_by_full_name(regex_pattern)`, `find_player_by_id`, `get_players()`, `get_active_players()`; dict fields `id`, `full_name`, `first_name`, `last_name`, `is_active`. The doc does not say how often the static list is refreshed.
- Live box score source (23:16 UTC): `endpoint_url = "boxscore/boxscore_{game_id}.json"` on the cdn.nba.com liveData base; `__init__(self, game_id, proxy=None, headers=None, timeout=30, get_request=True)`.
- stats HTTP layer (23:18 UTC): `base_url = "https://stats.nba.com/stats/{endpoint}"`; fallback `STATS_HEADERS` mimic a Chrome browser (Host, User-Agent, Accept, Accept-Language, Accept-Encoding, Connection, Referer, Pragma, Cache-Control, Sec-Ch-Ua, Sec-Ch-Ua-Mobile, Sec-Fetch-Dest).
- Reliability, community reports (23:16 UTC):
  - bttmly/nba README: "the NBA has blacklisted certain blocks of IP addresses, specifically those of cloud hosting providers including AWS." and "Annoyingly, requests from these IPs seem to just hang." Workaround: "There is a simple pass-through server in `scripts/proxy` that can be used to get around this restriction".
  - nba_api issues matching "timeout cloud": #176 (closed) "HTTPSConnectionPool(host='stats.nba.com', port=443): Read timed out. (read timeout=30)", #320 (open), #472 (closed), #505 (closed, GitHub Codespace).
- Live probe from this Mac (sandboxed shell), 23:16 to 23:17 UTC:
  - `curl` with browser headers to `boxscoretraditionalv3?GameID=0022500001...`: no response in 15 s (http=000).
  - Python `urllib` with nba_api-style Firefox headers, 20 s timeout: "The read operation timed out".
  - `https://cdn.nba.com/static/json/liveData/boxscore/boxscore_0022500001.json`: HTTP 403, body "Access Denied".
  - Caveat: the same shell reached ESPN, the-odds-api.com and GitHub fine, so the network works; the failure may still be specific to curl/urllib TLS fingerprints rather than the IP. Not tested with the `nba_api` package itself or from a cloud host.

### 2.2 balldontlie

- Pricing page https://www.balldontlie.io/ (23:12 UTC):

  | Tier | Price | Rate limit | Data access |
  |---|---|---|---|
  | Free | $0/mo per sport | 5 req/min | Basic |
  | All-Star | $9.99/mo per sport | 60 req/min | Extended |
  | GOAT | $39.99/mo per sport | 600 req/min | Full |
  | All-Access | $299.99/mo all sports | 600 req/min | Full + webhooks |

  Annual "Save 20%" option (annual prices not shown). "48h free trial available in your dashboard".
- NBA docs https://nba.balldontlie.io/ (23:13 and 23:15 UTC), endpoint tiers:

  | Endpoint | Free | ALL-STAR | GOAT |
  |---|---|---|---|
  | `/v1/teams`, `/v1/players`, `/v1/games` | Yes | Yes | Yes |
  | `/v1/stats` (Game Player Stats) | No | Yes | Yes |
  | `/v1/players/active` | No | Yes | Yes |
  | `/v1/player_injuries` | No | Yes | Yes |
  | `/v1/season_averages/{category}` | No | No | Yes |
  | `/v1/box_scores`, `/v1/box_scores/live` | No | No | Yes |
  | `/v1/standings`, `/v1/leaders`, `/v1/plays`, `/v1/lineups` | No | No | Yes |
  | `/v2/odds`, player props (`/v2/odds/player_props`) | No | No | Yes |

  - `/v1/stats` sample response includes `pts`, `reb`, `ast`, `fg3m`; each record nests `player` and `game` (`"status_state": "final"`).
  - `/v1/players` sample: `"id": 115, "first_name": "Stephen", "last_name": "Curry", "position": "G", "jersey_number": "30", "team": {...}`.
  - `/v1/player_injuries`: "This endpoint retrieves all player injuries." Fields: nested `player`, `return_date`, `description`, `status` (example `"Out"`).
  - Freshness: "Game data is realtime for in-progress games." and "Player stats are realtime for in-progress games." No statement about when a final box score is locked.
  - Auth: header `Authorization: YOUR_API_KEY`; 401 = "Unauthorized - You either need an API key or your account tier does not have access to the endpoint."; trial keys capped at 5 req/min.
  - Odds: `/v2/odds` vendors: ballybet, bet365, betmgm, betparx, betrivers, betway, caesars, draftkings, fanatics, fanduel, kalshi, polymarket, rebet. Player props vendors: ballybet, betparx, betrivers, betway, caesars, draftkings, fanatics, fanduel, rebet. No Hard Rock Bet, no Pinnacle. "Player prop data is LIVE and updated in real-time. We do not store historical data."
- Terms https://www.balldontlie.io/terms.html (Last Updated September 17, 2026; retrieved 23:15 UTC):
  - "you may use Data for lawful personal or commercial purposes"
  - "API keys and account credentials may not be shared, sold, transferred, or distributed to third parties"
  - "These restrictions apply only to access to the Services, not to your use or distribution of Data"
  - "You may not sell or resell Data in its original, unmodified form."
  - "You may not use the Services or Data for unlawful gambling activity"
  - "evade rate limits or subscription restrictions" is prohibited.
  - Reading for this build (my interpretation, not the terms' words): one server-side key serving many end users is not "sharing" the key as long as the key never leaves the server and the raw feed is not re-exposed.

### 2.3 The Odds API (v4)

- Docs https://the-odds-api.com/liveapi/guides/v4/index.html (23:12, 23:13, 23:14, 23:16 UTC):
  - `/scores`: "Returns a list of upcoming, live and recently completed games for a given sport. Live and recently completed games contain scores." "Games from up to 3 days ago can be returned using the daysFrom parameter." "Live scores update approximately every 30 seconds." Example shows `"completed": true` and a `scores` array; upcoming games show `"completed": false` and `"scores": null`. Cost 1 credit, 2 with `daysFrom`. No player stats.
  - `/participants`: "This endpoint does not return players on a team." (NBA returns teams.)
  - Event odds `/events/{eventId}/odds`: "Relevant markets will have a description field in their outcomes." (player name string). Cost: unique markets returned x regions.
  - `bookmakers` param: "If both bookmakers and regions are both specified, bookmakers takes priority." "Every group of 10 bookmakers is the equivalent of 1 region."
  - Rate limiting: "If you enounter the rate limit, the API will respond with a status code of 429".
  - Grep of full docs text: 0 hits for parlay / sgp / same game / combined / correlat.
- Sports coverage https://the-odds-api.com/sports-odds-data/sports-apis.html (23:17 UTC): `basketball_nba` has the "Scores & Results" checkmark.
- Markets https://the-odds-api.com/sports-odds-data/betting-markets.html (23:13 UTC): NBA keys `player_points`, `player_rebounds`, `player_assists`, `player_threes`, `player_blocks`, `player_steals`, `player_turnovers`, `player_points_rebounds_assists`, `player_points_rebounds`, `player_points_assists`, `player_rebounds_assists`, `player_double_double`, `player_triple_double`, `player_first_basket`, plus `_alternate` variants. "Player props can be accessed one event at a time using the /events/{eventId}/odds endpoint". "Coverage of player props is mainly limited to US sports and US bookmakers at this time."
- Bookmakers https://the-odds-api.com/sports-odds-data/bookmaker-apis.html (23:13 UTC, parsed text 23:14 UTC):
  - `eu pinnacle Pinnacle ... Odds are from public website which may incur a delay`
  - `us2 hardrockbet Hard Rock Bet ... Indiana sportsbook, currently same odds as several other states`; `us2 hardrockbet_az`; `us2 hardrockbet_fl Hard Rock Bet (FL)`; `us2 hardrockbet_oh`
  - `us betonlineag`, `eu betonlineag`; `us lowvig LowVig.ag`
  - Paid-only labels on: williamhill_us, fanatics, courtside, rebet, bet365_au, dabble_au, bet99_ca_on. Not on pinnacle.
  - "circa": 0 hits.
- Plans https://the-odds-api.com/ (23:13 and 23:17 UTC): "Starter FREE 500 credits per month All sports Most bookmakers All betting markets Historical Odds"; 20K $30/mo; 100K $59/mo; 5M $119/mo; 15M $249/mo (paid tiers say "All bookmakers").
- Terms https://the-odds-api.com/terms-and-conditions.html (Last updated: 31 August 2026; retrieved 23:18 UTC):
  - "It is your responsibility to keep your API key private."
  - Supported uses include "websites, mobile apps, dashboards, analytical tools, and other user-facing applications."
  - "Do not resell, repackage, or redistribute our data as a standalone data product."
  - Commercial use allowed "provided our data is not the primary product being sold or redistributed".
  - "It is your responsibility to independently verify the accuracy of the data"; the service "provides general information only and does not constitute financial or wagering advice."
  - "We reserve the right to terminate API access at any time without warning."

### 2.4 Pinnacle

- https://www.pinnacle.com/en/ (23:12 UTC): JS-rendered; fetched text contained only "Pinnacle". No API information visible.
- https://github.com/pinnacleapi/pinnacleapi-documentation (23:14 UTC): "Access to Pinnacle API suite has been closed for the general public since July 23rd, 2025." "We offer bespoke data services for select high value bettors & commercial partnerships." (api@pinnacle.com). "Please note that in order to access Pinnacle API, you must have a funded account."
- https://www.pinnacle.com/en/corporate/licenses (23:18 UTC): "Accordingly, we do not accept bets from any gamers based in the USA, whether residents or visitors." Licences: Ontario, Curaçao, Anjouan, Malta, Sweden.
- https://support.pinnacle.com/hc/en-us/articles/42376081435153-Am-I-allowed-to-sign-up-from-my-country returned HTTP 403 to the fetcher (not read).

### 2.5 ESPN (unofficial)

- Guide https://dev.to/zuplo/unlocking-espns-hidden-api-a-developers-guide-1pp7 (23:15 UTC): "While ESPN doesn't officially provide an API"; "Unfortunately, there is no official documentation for the hidden API."; "its unofficial status means there's no guarantee of long-term stability or support."
- Community gist https://gist.github.com/akeaswaran/b48b02f1c94f873c6655e7129910fc3b (23:16 UTC): NBA scoreboard `http://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard`; teams `.../basketball/nba/teams`; summary pattern shown for college football `summary?event=:gameId`.
- Direct probe (23:16 to 23:17 UTC), both HTTP 200:
  - `GET https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20260419`: 4 events; event `401869191` "Philadelphia 76ers at Boston Celtics", status `STATUS_FINAL`, `completed: True`, BOS 123, PHI 91.
  - `GET .../basketball/nba/summary?event=401869191` (409 KB): keys include `boxscore`, `injuries`, `odds`, `header`; `boxscore.players[team].statistics[0].keys` = `minutes, points, fieldGoalsMade-fieldGoalsAttempted, threePointFieldGoalsMade-threePointFieldGoalsAttempted, freeThrowsMade-freeThrowsAttempted, rebounds, assists, turnovers, steals, blocks, offensiveRebounds, defensiveRebounds, fouls, plusMinus`; sample athlete `id 4251` "Paul George" stats `['28','17','4-8','1-2','8-9','4','1',...]`. 3PM must be parsed from the `"1-2"` string.
- Terms https://disneytermsofuse.com/english/ (23:15 UTC): 2.B(x) "access, monitor, copy or extract the Disney Products using a robot, spider, script, or other automated means" and "data mining or web scraping"; 2.B(viii) "use the Disney Products for any commercial or business-related use or build a business utilizing the Disney Products"; 2.A "no right to reproduce, distribute, communicate to the public".

### 2.6 Hard Rock Bet parlay/SGP pricing

- WebSearch (23:14 UTC) found no official Hard Rock Bet developer API. Legal Sports Report: Hard Rock Bet integrated Kambi's Odds Feed+ API (B2B supplier). Covers.com / SBC Americas: "SGP Max" lets players combine up to 20 bets.
- https://sharpapi.io/sportsbooks/hardrock-odds-api (vendor page, 23:16 UTC): "There is no public Hard Rock Bet API for odds data." "There is no developer portal, no API key system, and no API documentation." Vendor sells individual market odds (moneylines, spreads, totals; "Player prop coverage is expanding"); no parlay/SGP product mentioned. Free tier "$0/month with 60-second delayed data"; Pro $229/mo.
- https://sportsgameodds.com/hard-rock-bet-odds-api/ returned 404.
- Hard Rock Bet's own terms of service were not fetched in this task.

### 2.7 NBA official data licensing

- https://www.nba.com/termsofuse (23:13 UTC, verified by text grep 23:14 UTC): see Q5 quotes above. LAST UPDATED: July 13, 2026. No explicit "scraping"/"robot" clause found by grep; the restrictions are use-based (gambling, commercial, database) rather than access-based.
- https://www.nba.com/stats (23:12 UTC): no terms, licensing or "powered by" text in the fetched page; footer has NBA Fan Code of Conduct and support links only.
- https://pr.nba.com/nba-sportradar-genius-sports-group-partnerships (Oct 29, 2020; retrieved 23:15 UTC): Sportradar and Genius Sports Group retain "non-exclusive rights to distribute official NBA and WNBA betting data to licensed sports betting operators". No 2024/2025 renewal press release was found in the search.

---

## 3. Settlement source decision matrix

| Leg type | Primary | Fallback | Notes |
|---|---|---|---|
| Player PTS / REB / AST / 3PM over/under | balldontlie `/v1/stats` (ALL-STAR) filtered by `player_ids[]` + `dates[]`/`game_ids[]`, require `game.status_state == "final"` | ESPN `summary?event=` (dev/manual check only) | Store `balldontlie player.id` on each leg at research time so settlement never needs a name match. |
| Team ML / spread / total | The Odds API `/scores?daysFrom=1` (`completed == true`) | balldontlie `/v1/games` (free tier: `home_team_score`, `visitor_team_score`, `status`) | 1 to 2 credits per day. |
| Injury status at research time | balldontlie `/v1/player_injuries` (ALL-STAR) | ESPN `summary.injuries` | Also show "verify in app" reminder. |

Stat corrections: the NBA occasionally revises box scores after the game. None of the sources document a "final/locked" flag beyond `status_state: "final"`. Settle no earlier than the next morning and allow a manual override.

---

## 4. Player identity matching proposal (Odds API names -> balldontlie IDs)

1. Nightly, pull balldontlie `/v1/players/active` (ALL-STAR) and cache `{id, first_name, last_name, team.abbreviation}`; keep a small alias file for known mismatches.
2. For each prop outcome, take `description` (name), the event's `home_team` / `away_team`, and the bookmaker key.
3. Normalize both sides: NFKD-strip diacritics, lowercase, drop punctuation and suffixes (Jr., Sr., II, III, IV), collapse whitespace; map common nicknames (e.g. "Cam" vs "Cameron") through the alias file.
4. Candidate set = active players whose team is one of the two event teams. Exact normalized full-name match on that set -> accept. If 0 matches, retry on all active players; if still 0 or if >1, mark `unmatched` and require user confirmation before the leg is eligible (never silently guess).
5. Persist the resolved `player_id` on the leg; settlement uses IDs only.

Risks: traded players (team filter stale for a day), two active players with the same normalized name, bookmaker name formats that differ from balldontlie (initials, hyphenated names), roster additions (two-way contracts) missing from `/players/active`, and The Odds API not returning props for a bookmaker that does list them in-app. Mitigation: alias file + user confirmation + logging every unmatched name.

---

## 5. Pinnacle / sharp-reference plan

- Use The Odds API with `bookmakers=pinnacle,betonlineag,lowvig,draftkings,fanduel` (<=10 bookmakers = 1 region cost). For props use `/events/{eventId}/odds` with the needed `player_*` markets; expect Pinnacle props coverage to be thin or absent (unverified).
- Display Pinnacle-derived numbers with the caveat "Odds are from public website which may incur a delay" and the `last_update` timestamp.
- Devig per market (two-way) and treat Pinnacle as the no-vig reference when present, otherwise median of betonlineag/lowvig/draftkings/fanduel.
- Circa is not available from The Odds API; no API source for Circa was identified.

---

## 6. Budget note (credits)

- Starter (free, 500 credits/mo): a daily routine of 1 `/scores` call (2 credits) + N event-odds calls (markets x 1 region each) burns roughly `2 + N * markets` credits/day. Four markets across 6 games/day = ~26 credits/day = ~780/mo, over the free quota. Plan on the 20K tier ($30/mo) if props are pulled for every game, or restrict to 2 to 3 games/day to stay free.
- balldontlie ALL-STAR ($9.99/mo per sport) is the minimum tier that returns player game stats and injuries.

---

## 7. Unresolved

1. Whether the stats.nba.com / cdn.nba.com failures seen from this Mac are TLS-fingerprint specific to curl/urllib or would also affect the `nba_api` package from a cloud host (not tested with the package, not tested from a cloud IP).
2. Pinnacle availability on The Odds API free Starter plan is inferred from the absence of a paid-only label; not stated explicitly.
3. Whether Pinnacle, BetOnline or LowVig actually return NBA `player_*` markets through The Odds API (not tested; requires an API key).
4. The magnitude of the Pinnacle "delay" is not quantified by The Odds API.
5. Circa: not listed by The Odds API; no API source found.
6. Hard Rock Bet's own terms of service regarding automated access were not fetched; the "no public API" statement comes from a vendor page.
7. balldontlie: no documented latency or lock time for final box scores; "per sport" pricing and annual prices not shown on the page.
8. balldontlie terms do not explicitly address one server-side key serving many end users; my reading (allowed if the key stays server-side) is an interpretation.
9. ESPN: no official NBA summary endpoint documentation; the endpoint worked in a probe today but may change without notice; the Disney terms prohibit automated and commercial use.
10. No 2024/2025 NBA data-rights renewal release was located; the 2020 release is the latest found.
11. Pinnacle restricted-territories T&C page and support article were not readable (403); the licenses page statement was used instead.
12. Whether Hard Rock Bet settles props from official NBA (Sportradar/Genius) data was not researched here.

---

## 8. Recommendations

1. Settlement: balldontlie ALL-STAR `/v1/stats` for player legs (IDs, `status_state: "final"`), The Odds API `/scores` for team legs. Keep ESPN as a developer-only cross-check. Do not ship a dependency on stats.nba.com / `nba_api` (gambling-use clause plus cloud blocking).
2. Store `balldontlie player.id` on every leg at research time using the matching procedure in section 4; block unmatched legs until the user confirms.
3. Parlay/SGP price: make the Hard Rock Bet combined price a required user input (copied from the app). Compute the naive independent product from `hardrockbet_fl` leg prices and show the difference, labelled as an estimate.
4. Pinnacle via The Odds API (`bookmakers=pinnacle`, region `eu`), with the delay caveat on screen; fall back to betonlineag/lowvig and a DK/FD consensus.
5. Keep all API keys server-side; never expose raw feeds; add the Odds API "independently verify the accuracy" disclaimer and a "verify with the bookmaker" prompt before any wager.
6. Budget for The Odds API 20K tier ($30/mo) plus balldontlie ALL-STAR ($9.99/mo) unless the daily game count is capped.
7. Implement 429 backoff, response caching, and a persisted settlement log with manual override.

---

## 9. Sources

| URL | retrieved_at_utc | what it established |
|---|---|---|
| https://github.com/swar/nba_api | 2026-10-19 23:12 | Unofficial MIT client; NBA.com ToU applies; no endpoint change notices |
| https://raw.githubusercontent.com/swar/nba_api/master/README.md | 2026-10-19 23:13 | Proxy/headers/timeout options; static data; license |
| https://pypi.org/project/nba_api/ | 2026-10-19 23:14 | v1.11.4, Feb 20 2026, Python >=3.10 |
| https://raw.githubusercontent.com/swar/nba_api/master/docs/nba_api/stats/endpoints/boxscoretraditionalv3.md | 2026-10-19 23:15 | Endpoint URL, GameID format, player_stats columns |
| https://raw.githubusercontent.com/swar/nba_api/master/docs/nba_api/stats/static/players.md | 2026-10-19 23:15 | Static player lookup functions and fields |
| https://raw.githubusercontent.com/swar/nba_api/master/docs/table_of_contents.md | 2026-10-19 23:15 | Doc layout; http.md files; no live boxscore doc |
| https://raw.githubusercontent.com/swar/nba_api/master/docs/nba_api/stats/library/http.md | 2026-10-19 23:16 | STATS_HEADERS described; no rate-limit guidance |
| https://raw.githubusercontent.com/swar/nba_api/master/src/nba_api/live/nba/endpoints/boxscore.py | 2026-10-19 23:16 | Live boxscore path template, timeout=30 default |
| https://raw.githubusercontent.com/swar/nba_api/master/src/nba_api/stats/library/http.py | 2026-10-19 23:18 | base_url stats.nba.com/stats/{endpoint}; browser-mimic headers |
| https://github.com/swar/nba_api/issues?q=is%3Aissue+timeout+cloud | 2026-10-19 23:16 | Issues #176, #320 (open), #472, #505 on timeouts |
| https://github.com/bttmly/nba | 2026-10-19 23:15 | Cloud IP blacklisting, hanging requests, proxy workaround |
| Direct probe: https://stats.nba.com/stats/boxscoretraditionalv3?GameID=0022500001... | 2026-10-19 23:16 to 23:17 | curl 15 s no response; urllib 20 s timeout |
| Direct probe: https://cdn.nba.com/static/json/liveData/boxscore/boxscore_0022500001.json | 2026-10-19 23:16 | HTTP 403 Access Denied |
| https://www.balldontlie.io/ | 2026-10-19 23:12 (text grep 23:14) | Tier prices and rate limits; 48h trial; terms link |
| https://nba.balldontlie.io/ | 2026-10-19 23:13, 23:14, 23:15 | Endpoint tier table; /stats fields; players, injuries, odds vendors; auth |
| https://www.balldontlie.io/terms.html | 2026-10-19 23:15 | Terms (Sep 17 2026): commercial use OK, no key sharing, no raw resale, unlawful gambling prohibited |
| https://www.nba.com/stats | 2026-10-19 23:12 | No terms/licensing text on the stats landing page |
| https://www.nba.com/termsofuse | 2026-10-19 23:13 (grep 23:14) | Section 9 NBA Statistics restrictions incl. gambling; last updated July 13 2026 |
| https://pr.nba.com/nba-sportradar-genius-sports-group-partnerships | 2026-10-19 23:15 | Official betting data distributed to licensed operators via Sportradar/Genius |
| https://the-odds-api.com/liveapi/guides/v4/index.html | 2026-10-19 23:12, 23:13, 23:14, 23:16 | /scores, /participants, description field, quota, bookmakers param, 429; no parlay text |
| https://the-odds-api.com/sports-odds-data/bookmaker-apis.html | 2026-10-19 23:13 (parsed 23:14) | pinnacle eu + delay note; hardrockbet_fl us2; betonlineag/lowvig; paid-only list; no circa |
| https://the-odds-api.com/sports-odds-data/betting-markets.html | 2026-10-19 23:13 | NBA player prop market keys; event-odds endpoint; US coverage note |
| https://the-odds-api.com/sports-odds-data/sports-apis.html | 2026-10-19 23:17 | basketball_nba has Scores & Results |
| https://the-odds-api.com/ | 2026-10-19 23:13 (grep 23:17) | Plans: Starter free 500 credits "Most bookmakers"; $30/$59/$119/$249 |
| https://the-odds-api.com/terms-and-conditions.html | 2026-10-19 23:18 | T&C (Aug 31 2026): user-facing apps OK, no standalone redistribution, verify accuracy, termination |
| https://www.pinnacle.com/en/ | 2026-10-19 23:12 | JS page; nothing extractable |
| https://github.com/pinnacleapi/pinnacleapi-documentation | 2026-10-19 23:14 | API closed to public since July 23 2025; funded account; api@pinnacle.com |
| https://www.pinnacle.com/en/corporate/licenses | 2026-10-19 23:18 | No bets from USA-based gamers; licences list |
| https://dev.to/zuplo/unlocking-espns-hidden-api-a-developers-guide-1pp7 | 2026-10-19 23:15 | ESPN API unofficial/undocumented, no stability guarantee |
| https://gist.github.com/akeaswaran/b48b02f1c94f873c6655e7129910fc3b | 2026-10-19 23:16 | Community list of ESPN NBA scoreboard/teams URLs |
| Direct probe: https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=20260419 | 2026-10-19 23:16 | Final events with team scores |
| Direct probe: https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=401869191 | 2026-10-19 23:17 | Per-player box score with athlete.id; 3PT as made-attempted string |
| https://disneytermsofuse.com/english/ | 2026-10-19 23:15 | 2.B(x) automated access prohibited; 2.B(viii) commercial use prohibited |
| https://sharpapi.io/sportsbooks/hardrock-odds-api | 2026-10-19 23:16 | Vendor: no public Hard Rock Bet API; no parlay product |
| https://sportsgameodds.com/hard-rock-bet-odds-api/ | 2026-10-19 23:15 | 404 |
| WebSearch "Hard Rock Bet same game parlay odds API feed developer" | 2026-10-19 23:14 | Kambi Odds Feed+ B2B integration (LSR); SGP Max press; no developer API |
| WebSearch "Pinnacle API access requirements" | 2026-10-19 23:13 | Pointed to pinnacleapi docs; npm note on US IPs (unverified) |
| WebSearch "ESPN hidden API ..." | 2026-10-19 23:13 | Community guides; unofficial status |
| WebSearch "nba_api stats.nba.com blocked cloud IP ..." | 2026-10-19 23:14 | bttmly/nba README; HN reports of datacenter IP drops (anecdotal) |
| WebSearch "NBA official data distributor Sportradar Genius ..." | 2026-10-19 23:14 | 2018 deals and 2020 renewal; no 2024/25 release found |
| WebSearch Pinnacle restricted territories (pinnacle.com) | 2026-10-19 23:17 | Licenses page and support article URLs |
