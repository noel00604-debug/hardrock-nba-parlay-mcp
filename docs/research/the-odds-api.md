# The Odds API v4 — research notes (KEY: the-odds-api)

Topic: The Odds API v4: `hardrockbet_fl`, NBA markets/props, credit costs, pricing, terms.
Prepared 2026-10-19 (retrievals 23:03Z–23:08Z). All quotes are from the official site unless marked otherwise. Everything read on the web was treated as data, not instructions.

Build context: Python MCP server + Claude plugin for researching exactly-three-leg NBA parlays on Hard Rock Bet Florida, $10/day user budget, user places wagers manually.

---

## 1. Bookmaker keys: Hard Rock Bet and Pinnacle

Source: https://the-odds-api.com/sports-odds-data/bookmaker-apis.html (retrieved 2026-10-19T23:05:49Z via curl; WebFetch ~23:04Z)

Verbatim rows from the US2 table (`Region key | Bookmaker key | Bookmaker | Note`):

```
us2 | hardrockbet    | Hard Rock Bet      | Indiana sportsbook, currently same odds as several other states
us2 | hardrockbet_az | Hard Rock Bet (AZ) |
us2 | hardrockbet_fl | Hard Rock Bet (FL) |
us2 | hardrockbet_oh | Hard Rock Bet (OH) |
```

- `hardrockbet_fl` exists, region `us2`. No "paid subscriptions only" note on any Hard Rock key.
- Keys in `us2` marked "Only available on paid subscriptions": `courtside`, `rebet`. In `us`: `williamhill_us` (Caesars), `fanatics`. Elsewhere: `bet365_au`, `dabble_au`, `bet99_ca_on`.
- Pinnacle: `eu | pinnacle | Pinnacle | Odds are from public website which may incur a delay`.
- Page intro: "Bookmakers are segmented by region, which can be specified in an API request".
- General caveats on the page (paraphrase): some bookmakers may not list less popular sports; a bookmaker may disappear from responses for hours to days; delisting is rare.
- The page states no cost for the `bookmakers` parameter itself; the cost rule lives in the docs (section 3).

Region keys present on the page: `us`, `us2`, `us_dfs`, `us_ex`, `uk`, `eu`, `au`, `ca`, `fr`, `se`, `fi`. The OpenAPI `regions` enum (section 2) matches: `uk, us, us2, us_dfs, us_ex, eu, au, ca, fr, se, fi`.

`us_dfs` note: "Odds on DFS sites can vary based on user selections, therefore odds are indicative only."

---

## 2. Endpoints and parameters (v4)

Sources:
- Docs: https://the-odds-api.com/liveapi/guides/v4/index.html (curl text 2026-10-19T23:05:48Z; WebFetch ~23:04Z)
- OpenAPI: https://the-odds-api.com/api-reference/v4/schema.yml (2026-10-19T23:07:52Z; file header comment `# 2025-11-05`, `openapi: 3.0.1`, `version: '4'`)
- Reference UI: https://the-odds-api.com/api-reference/v4/ (2026-10-19T23:07:35Z; Scalar, loads `schema.yml`)

Host: "All requests use the host https://api.the-odds-api.com" (IPv6: `https://ipv6-api.the-odds-api.com`). Key is passed as `apiKey` query param ("Access key (40 characters)").

OpenAPI paths (complete list, 11 paths):
```
/v4/sports
/v4/sports/{sport}/odds
/v4/sports/{sport}/scores
/v4/sports/{sport}/events
/v4/sports/{sport}/events/{eventId}/odds
/v4/sports/{sport}/events/{eventId}/markets
/v4/sports/{sport}/participants
/v4/historical/sports/{sport}/odds
/v4/historical/sports/{sport}/events
/v4/historical/sports/{sport}/events/{eventId}/odds
/v4/historical/sports/{sport}/events/{eventId}/markets
```

### GET /v4/sports
- Params: `apiKey`; `all` (optional, `all=true` returns in- and out-of-season).
- "This endpoint does not count against the usage quota."
- Fields: `key`, `group`, `title`, `description`, `active`, `has_outrights`.

### GET /v4/sports/{sport}/odds
Docs param text (verbatim or near-verbatim):
- `sport`: sport key; "`upcoming` is always valid, returning any live games as well as the next 8 upcoming games across all sports".
- `regions`: "Determines the bookmakers to be returned. For example, us, us2 (United States), uk (United Kingdom), au (Australia) and eu (Europe). Multiple regions can be specified if comma delimited." OpenAPI: `required: true`, enum `uk,us,us2,us_dfs,us_ex,eu,au,ca,fr,se,fi`; "Each region will count as 1 request against the usage quota for each market."
- `markets`: "Optional - ... Defaults to h2h ... Valid markets are h2h (moneyline), spreads (points handicaps), totals (over/under) and outrights (futures). Multiple markets can be specified if comma delimited. spreads and totals markets are mainly available for US sports and bookmakers at this time. Each specified market costs 1 against the usage quota, for each region." Exchanges add `h2h_lay` automatically. OpenAPI enum here: `h2h, spreads, totals, outrights`.
- `dateFormat`: `unix` or `iso` (ISO 8601), default `iso`.
- `oddsFormat`: `decimal` (default) or `american`; "When set to american, small discrepancies might exist for some bookmakers due to rounding errors."
- `eventIds`: "Comma-separated game ids. Filters the response to only return games with the specified ids."
- `bookmakers`: "Optional - Comma-separated list of bookmakers to be returned. If both bookmakers and regions are both specified, bookmakers takes priority. Bookmakers can be from any region. Every group of 10 bookmakers is the equivalent of 1 region. For example, specifying up to 10 bookmakers counts as 1 region. Specifying between 11 and 20 bookmakers counts as 2 regions."
- `commenceTimeFrom` / `commenceTimeTo`: ISO 8601, e.g. `2023-09-09T00:00:00Z`; "no effect if the sport is set to 'upcoming'".
- `includeLinks`: "if true, the response will include bookmaker links to events, markets, and betslips if available."
- `includeSids`: "source ids (bookmaker ids) for events, markets and outcomes if available ... useful to construct your own links to handle variations in state or mobile app links."
- `includeBetLimits`: "bet limit of each betting option, mainly available for betting exchanges."
- `includeRotationNumbers`: home/away rotation numbers if available.

### GET /v4/sports/{sport}/scores
- Params: `daysFrom` ("integers from 1 to 3. If this parameter is missing, only live and upcoming games are returned."), `dateFormat`, `eventIds`.
- "Live scores update approximately every 30 seconds." "Games from up to 3 days ago can be returned using the daysFrom parameter."
- "The scores endpoint applies to selected sports". Sports page marks NBA (`basketball_nba`) with Scores & Results ✔.

### GET /v4/sports/{sport}/events
- "Returns a list of in-play and pre-match events ... Odds are not included in the response. This endpoint does not count against the usage quota."
- Params: `dateFormat`, `eventIds`, `commenceTimeFrom`, `commenceTimeTo`, `includeRotationNumbers`.

### GET /v4/sports/{sport}/events/{eventId}/odds
- "Returns odds for a single event. Accepts any available betting markets using the markets parameter. Coverage of non-featured markets is currently limited to selected bookmakers and sports, and expanding over time."
- "Parameters are the same as for the /odds endpoint with exceptions listed below. All available market keys are accepted in the markets parameter."
- `eventId` (path): from the `id` field of `/events`. OpenAPI: "If the event has expired (not receiving updates due to completion or cancellation), a HTTP 404 status code will be returned."
- `includeMultipliers`: US DFS only, default false.
- Response differences: single game; "The last_update field is only available on the market level"; "Relevant markets will have a description field in their outcomes."

### GET /v4/sports/{sport}/events/{eventId}/markets
- "Returns available market keys for each bookmaker for a single event." "only returns recently seen market keys for each bookmaker - it is not a comprehensive list ... As an event's commence time approaches, this endpoint will return more market keys as bookmakers open more markets."
- Params: `regions`, `bookmakers` (same 10-per-region rule), `dateFormat`.
- Example response: per bookmaker, `markets: [{key, last_update}, ...]` (keys only, no outcomes).

### GET /v4/sports/{sport}/participants
- "For example for NBA, a list of teams is returned." "This endpoint does not return players on a team." "treated as a whitelist and may include participants that are not currently active."
- Response: `[{full_name, id}]` (ids like `par_01hq...`).

### Historical (all "only available on paid usage plans")
- `/v4/historical/sports/{sport}/odds` — `/odds` params + `date` (ISO8601); "closest snapshot equal to or earlier than the provided date". Data from 2020-06-06, 10-min snapshots; 5-min from Sept 2022. Response wrapped in `{timestamp, previous_timestamp, next_timestamp, data}`.
- `/v4/historical/sports/{sport}/events` — `date` + events params.
- `/v4/historical/sports/{sport}/events/{eventId}/odds` — any market key; "Historical data for additional markets (player props, alternate lines, period markets) are available after 2023-05-03T05:30:00Z."; 5-min snapshots; `includeMultipliers`.
- `/v4/historical/sports/{sport}/events/{eventId}/markets` — market keys at the snapshot.
- Historical-odds page (https://the-odds-api.com/historical-odds-data/, ~23:05Z): NBA featured history starts `2020-06-27T03:55:00Z`; "Historical data is only available on paid usage plans."

### Error codes (OpenAPI)
- `401`: "Unauthenticated or unauthorized. The API key might be missing or invalid (unauthenticated), or it might at its usage limit (unauthorized). The repsonse body will contain more info"
- `404` (event endpoints): "The event id is invalid or the event has expired"
- `422`: "One or more of the query params are invalid. The repsonse body will contain more info"
- `429`: "The request was throttled because requests are being sent too frequently"
- `500`: "Internal error"

---

## 3. Credit (usage quota) cost rules, exactly as documented

Source: docs page (section 2 URL), retrieved 2026-10-19T23:05:48Z.

| Endpoint | Cost rule (verbatim where quoted) |
|---|---|
| `/sports` | "This endpoint does not count against the usage quota." |
| `/sports/{sport}/odds` | "The usage quota cost is 1 per region per market. cost = [number of markets specified] x [number of regions specified]" Examples: 1×1=1; 3 markets×1 region=3; 1×3=3; `basketball_nba ... markets=h2h,spreads,totals&regions=us,uk,au` = 9. "If no events are returned, the request will not count against the usage quota" |
| `bookmakers` param (odds, event odds, event markets) | "Every group of 10 bookmakers is the equivalent of 1 region. For example, specifying up to 10 bookmakers counts as 1 region. Specifying between 11 and 20 bookmakers counts as 2 regions." OpenAPI: "Every group of 10 bookmakers counts as 1 request. For example for a single market, specifying up to 10 bookmakers is the equivalent of 1 region." If both given, "bookmakers takes priority". |
| `/sports/{sport}/scores` | "The usage quota cost is 2 if the daysFrom parameter is specified (returning completed events), otherwise the usage quota cost is 1." |
| `/sports/{sport}/events` | "This endpoint does not count against the usage quota." |
| `/sports/{sport}/events/{eventId}/odds` | "cost = [number of unique markets returned] x [number of regions specified]". "Responses with empty data do not count towards the usage quota." "if you specify 5 different markets and 1 region in the API call, and data is only available for 2 markets, the cost will be [2 markets] x [1 region] = 2" |
| `/sports/{sport}/events/{eventId}/markets` | "A call to this endpoint costs 1 usage credit." |
| `/sports/{sport}/participants` | "A call to this endpoint costs 1 usage credit." |
| `/historical/sports/{sport}/odds` | "cost = 10 x [number of markets specified] x [number of regions specified]"; empty responses free |
| `/historical/sports/{sport}/events` | "This endpoint costs 1 from usage quota. If no events are found, it will not cost." |
| `/historical/.../events/{eventId}/odds` | "cost = 10 x [number of unique markets returned] x [number of regions specified]"; empty free |
| `/historical/.../events/{eventId}/markets` | "A call to this endpoint costs 1 usage credit." |

Note on `bookmakers` and event odds: the event-odds section says "Parameters are the same as for the /odds endpoint", so the 10-bookmakers-per-region rule applies there too; the cost formula text itself only says "regions specified". Not restated explicitly for event odds (see unresolved).

Quota headers (on every call): `x-requests-remaining` "The usage credits remaining until the quota resets"; `x-requests-used` "The usage credits used since the last quota reset"; `x-requests-last` "The usage cost of the last API call". FAQ: "Usage credits are automatically reset on the first of every month."

FAQ "What is a request?" (https://the-odds-api.com/manage/faqs.html, 23:07:02Z): "if you request odds for basketball NBA, from US-region bookmakers, and moneyline betting markets ... This will count as 1 request from your plan's usage quota."

---

## 4. basketball_nba market keys

Sources: https://the-odds-api.com/sports-odds-data/betting-markets.html (curl 2026-10-19T23:05:49Z); https://the-odds-api.com/sports-odds-data/sports-apis.html (~23:05Z); https://the-odds-api.com/sports-odds-data/nba-odds.html (~23:06Z).

Sport keys (sports page): `basketball_nba` (NBA, Scores ✔), `basketball_nba_preseason`, `basketball_nba_all_stars`, `basketball_nba_summer_league`, `basketball_nba_championship_winner`, `basketball_wnba`, `basketball_ncaab`, `basketball_wncaab`, `basketball_ncaab_championship_winner`, `basketball_nbl`, `basketball_euroleague`. Covered "when in season".

Featured markets (available on `/odds`): `h2h`, `spreads`, `totals`, `outrights`, `h2h_lay`, `outrights_lay`. "spreads and totals markets are mainly available for US sports and bookmakers at this time."

Additional markets (event endpoint only): "Additional markets are currently limited to US sports and selected bookmakers, however coverage is expanding. Additional markets update at 1 minute intervals." "Due to the growing size of the API response, additional markets need to be accessed one event at a time using the new /events/{eventId}/odds endpoint."
- Game: `alternate_spreads`, `alternate_totals`, `team_totals`, `alternate_team_totals` (also `btts`, `draw_no_bet`, `h2h_3_way` for soccer-type sports).
- Period (quarters/halves): `h2h_q1..q4`, `h2h_h1`, `h2h_h2`, `spreads_q1..q4`, `spreads_h1/h2`, `totals_q1..q4`, `totals_h1/h2`, `alternate_spreads_q1..q4/h1/h2`, `alternate_totals_q1..q4/h1/h2`, `team_totals_q1..q4/h1/h2`, `alternate_team_totals_q1..q4/h1/h2`.

Player props: "Coverage of player props is mainly limited to US sports and US bookmakers at this time. Player props can be accessed one event at a time using the /events/{eventId}/odds endpoint."

"NBA, NCAAB, WNBA Player Props API" table (verbatim keys): `player_points`, `player_points_q1`, `player_rebounds`, `player_rebounds_q1`, `player_assists`, `player_assists_q1`, `player_threes`, `player_blocks`, `player_steals`, `player_blocks_steals`, `player_turnovers`, `player_points_rebounds_assists`, `player_points_rebounds`, `player_points_assists`, `player_rebounds_assists`, `player_field_goals`, `player_frees_made`, `player_frees_attempts`, `player_first_basket`, `player_first_team_basket`, `player_double_double`, `player_triple_double`, `player_method_of_first_basket`, `player_fantasy_points` (DFS only).

"Alternate NBA Player Props API": "Alternate player markets cover milestones (X+ lines), and markets that sportsbooks label as "alternate"." Keys: `player_points_alternate`, `player_rebounds_alternate`, `player_assists_alternate`, `player_blocks_alternate`, `player_steals_alternate`, `player_turnovers_alternate`, `player_threes_alternate`, `player_points_assists_alternate`, `player_points_rebounds_alternate`, `player_rebounds_assists_alternate`, `player_points_rebounds_assists_alternate`, `player_fantasy_points_alternate` (DFS only).

Discovery guidance on the markets page: "For the most up-to-date list of available markets by each bookmaker, query the markets endpoint."

NBA odds page: "NBA player props, limited to US and AU bookmakers"; US bookmaker examples named are "Draftkings, Fanduel, FoxBet, BetMGM, Caesars, Bovada, and more". Hard Rock Bet is not named on the NBA page, the markets page, the deep-links page or the bets-api page. **No official page states which prop markets `hardrockbet_fl` carries.** The documented way to find out is `/sports/basketball_nba/events/{eventId}/markets?bookmakers=hardrockbet_fl` (1 credit).

Parlay / SGP: no mention of "parlay", "same game" or "SGP" on the docs page, markets page, bookmakers page, or in the OpenAPI path list (grep of extracted text returned nothing). No combined-price endpoint exists.

---

## 5. Response shape

Sources: docs examples + OpenAPI components (section 2 URLs).

Event (odds endpoint):
```
id            "A unique 32 character identifier for the event." (MatchId)
sport_key     e.g. "basketball_nba"
sport_title   e.g. "NBA" ("Occassionally this value can change")
commence_time "The match start time (ISO 8601 formatted). This will be unix timestamp integer if ... dateFormat=unix."
home_team / away_team  nullable (null for outrights)
bookmakers[]  { key, title, last_update, markets[] }
markets[]     { key, last_update, outcomes[] }
outcomes[]    { name, price, point?, description?, link?, sid?, bet_limit?, multiplier? }
```
- Outcome.name: "For totals markets, this will be 'Over' or 'Under'. For team markets, it will be the name of the team or participant, or 'Draw'".
- Outcome.price: "The odds of the outcome. The format is determined by the oddsFormat query param."
- Outcome.point: "only applicable to spreads and totals markets (this property will be missing for h2h and outrights markets)".
- Outcome.description: "only relevant for certain markets ... for player prop markets, it includes the player's name". Docs example: `{"name": "Over", "description": "David Blough", "price": -205, "point": 0.5}`.
- Outcome.link: "If available, link to the bookmaker's website and populate the betslip" (includeLinks=true). Outcome.sid: bookmaker's id for the selection (includeSids=true). bet_limit (includeBetLimits=true). multiplier (DFS).
- Market-level `last_update` (OpenAPI): "To check recency of odds, we recommend using this field instead of the "last_update" field at the bookmaker level." Docs: "The bookmaker-level last_update field is deprecated." "When a market is suspended or closed, its last_update stops advancing, and the market is removed from the API response after about 15 minutes."
- In-play detection: "If commence_time is less than the current time, the event is in-play. The /odds endpoint does not return completed events".
- `/events` returns `{id, sport_key, sport_title, commence_time, home_team, away_team}`.

Scores response (docs example, NBA):
```
{ id, sport_key: "basketball_nba", sport_title: "NBA", commence_time, completed: true,
  home_team, away_team, scores: [{name: "Sacramento Kings", score: "113"}, ...], last_update }
```
OpenAPI: `completed` "true if the event has finished, otherwise false"; `scores` "A list of teams and their scores. List will be empty if event has not started."; `last_update` "ISO8601 datetime of when the scores were last updated. Will be null if event has not started". Scores are strings. "The game id field in the scores response matches the game id field in the odds response". No player box-score / player stats fields exist anywhere in the schema.

Update frequency (https://the-odds-api.com/sports-odds-data/update-intervals.html, ~23:05Z): "Odds update at intervals which depend on the market type and the proximity to an event's start time." Featured markets: 60 s pre-match, 40 s in-play. Additional markets (player props, alternates, period markets): 60 s pre-match, 60 s in-play. Outrights: 5 min / 60 s. Exchanges: 20 s / 10 s. "Six hours before an event's start time, the update interval begins decreasing from the pre-match interval."

---

## 6. Pricing, quotas, rate limits, plan restrictions

Source: https://the-odds-api.com/ (curl 2026-10-19T23:07:02Z; WebFetch ~23:04Z). Verbatim "Get Access" block:

| Plan | Price | Quota | Sports | Bookmakers | Markets | Historical |
|---|---|---|---|---|---|---|
| Starter | FREE | 500 credits per month | All sports | Most bookmakers | All betting markets | listed (historical endpoints are "only available on paid usage plans" per docs) |
| 20K | $30 per month, USD | 20,000 credits per month | All sports | All bookmakers | All betting markets | Historical Odds |
| 100K | $59 per month, USD | 100,000 credits per month | All sports | All bookmakers | All betting markets | Historical Odds |
| 5M | $119 per month, USD | 5M credits per month | All sports | All bookmakers | All betting markets | Historical Odds |
| 15M | $249 per month, USD | 15M credits per month | All sports | All bookmakers | All betting markets | Historical Odds |

"Create an account to discover higher usage plans". "For paid plans, billing happens straight away." Renews monthly on the same day. "Your subscription will automatically cancel before the next billing cycle." Terms: "Payments are non-refundable".

Overage: no overage purchase or pay-as-you-go is documented anywhere fetched (home, FAQ, docs, terms). The only documented behavior at the limit is the OpenAPI 401 text: "it might at its usage limit (unauthorized)".

Rate limit (https://the-odds-api.com/guide/rate-limit.html, curl 2026-10-19T23:07:53Z): "The current rate limit is 30 requests per second on paid usage plans." "When a request is rate limited, the API returns a 429 error code." "consider retrying the request after a couple of seconds." "It is highly recommended to combine multiple markets in the same request ... The same applies if you are querying multiple regions." "you might cache the /sports response for an hour, and the /events endpoint for 10 minutes." Free-plan rate limit: not stated.

Plan restrictions on bookmakers: the free tier says "Most bookmakers"; the bookmaker page marks exactly these as paid-only: `williamhill_us`, `fanatics`, `courtside`, `rebet`, `bet365_au`, `dabble_au`, `bet99_ca_on`. No Hard Rock key and not `pinnacle` are so marked.

---

## 7. Terms of use (verbatim lines)

Source: https://the-odds-api.com/terms-and-conditions.html (curl 2026-10-19T23:05:48Z). "Last updated: 31 August 2026". Provider: "The Odds API Pty Ltd, an Australian registered company, ACN: 627461947".

Restrictions section, verbatim:
- "Do not resell, repackage, or redistribute our data as a standalone data product. This includes, but is not limited to, offering our data through your own API, data feed, downloadable files, or any other format intended to serve as a source of raw data for others."
- "We support and encourage the use of our data in websites, mobile apps, dashboards, analytical tools, and other user-facing applications, including commercial use, provided our data is not the primary product being sold or redistributed."
- Permitted uses "include, but are not limited to: Storing our data and retaining it indefinitely; Displaying our data in a UI, website, or mobile app, including for commercial use; Using our data in research papers and analytical dashboards; Calculating and displaying values you derive from our data; Using our data to train statistical and machine learning models".
- "We mainly prohibit reselling the data as a raw data feed, i.e. a competing product. In other words, don't resell our data as your own API or data source."
- "Attribution to The Odds API is not required, but is always appreciated."
- "If we reasonably suspect a violation of these terms, including the resale or redistribution of our data as a data service, we reserve the right to revoke your API key and block future access."
- "If you are unsure whether your use case is permitted, please contact us."

Other relevant clauses:
- Personal vs commercial: no distinction drawn; commercial use is expressly allowed subject to the "not the primary product" condition.
- API key: "It is your responsibility to keep your API key private. Failure to do so will make it vulnerable to quota depletion by unauthorized users."
- Liability: "wagering markets are highly volatile; on occasion, errors or additional delays may be present." "It is your responsibility to independently verify the accuracy of the data with the respective wagering operator before acting on it." "we will not be held liable for losses resulting from actions made based on the data provided in our API". "We assume no responsibility for any products or applications created by users of the Service."
- Responsible gambling: "users are encouraged to display appropriate responsible gambling messaging (e.g., "Gamble Responsibly. 18+") on their customer-facing platforms. It is the user's sole responsibility to ensure that their use of the data complies with the specific responsible gambling regulations and advertising standards of their local jurisdiction."
- Data sourcing: "aggregated from publicly accessible sources ... the Service does not circumvent authentication controls". Not affiliated with any bookmaker.
- Termination: "we reserve the right to terminate API access at any time without warning" (abuse / legal order).
- Governing law: New South Wales, Australia.

---

## 8. Parlay / SGP combined-price endpoint

None. The OpenAPI path list (11 paths, section 2) contains only sports, odds, scores, events, event odds, event markets, participants and the four historical endpoints. The words "parlay", "same game" and "SGP" do not appear in the docs page, markets page or bookmakers page text (grep of extracted text, 2026-10-19T23:07:02Z). The "Bets API" page (https://the-odds-api.com/sports-odds-data/bets-api.html, ~23:07Z) is a marketing page: "The bets API offers odds for moneyline, points spreads and over/under (totals) markets" plus select futures; no parlay content.

---

## 9. Scores coverage

- `daysFrom` 1–3 (integers); without it "only live and upcoming games are returned".
- Fields: `completed` (bool), `scores` (array of `{name, score}` with score as string; "empty if event has not started"), `last_update` ("null if event has not started").
- "Live scores update approximately every 30 seconds."
- NBA is listed with Scores & Results ✔ on the sports page.
- Player stats: not offered. The scores schema only has team-level `scores`; `participants` "does not return players on a team"; no box-score endpoint in the OpenAPI paths.

---

## 10. Deep links (for sending the user to Hard Rock Bet)

Source: https://the-odds-api.com/releases/deep-links.html (~23:07Z). Release "2024-September-22". `includeLinks=true` adds `link` at bookmaker (event), market and outcome levels "if available"; `includeSids=true` adds `sid`. Fallback guidance: use shallower link, then your own bookmaker homepage. Which bookmakers support links is not listed; Hard Rock is not mentioned. Must be verified live for `hardrockbet_fl`.

---

## 11. Worked cost model for this build (derived, not from the vendor)

Assumptions: `bookmakers=hardrockbet_fl` (optionally `hardrockbet_fl,pinnacle`; both ≤10 bookmakers = 1 region-equivalent), one NBA slate per day.

- `/sports/basketball_nba/events` → 0 credits (cache ~10 min per vendor advice).
- `/sports/basketball_nba/odds?bookmakers=hardrockbet_fl&markets=h2h,spreads,totals` → 3 credits per call (markets specified × 1).
- `/sports/basketball_nba/events/{id}/markets?bookmakers=hardrockbet_fl` → 1 credit per event (discover which props Hard Rock FL actually lists).
- `/sports/basketball_nba/events/{id}/odds?bookmakers=hardrockbet_fl&markets=player_points,player_rebounds,player_assists,player_threes,alternate_spreads,alternate_totals,team_totals` → up to 7 credits per event, charged only for markets that return data.
- `/sports/basketball_nba/scores?daysFrom=1` → 2 credits.

Example day: 1 odds call (3) + 6 events × (1 markets + ~5 props returned) (36) + 1 scores (2) ≈ 41 credits. Free tier (500/month ≈ 16/day) cannot sustain that; the 20K plan ($30/mo ≈ 650/day) can. A free-tier design must limit to the featured-odds call plus props on 1–2 chosen events.

---

## Sources

| URL | retrieved_at_utc | what it established |
|---|---|---|
| https://the-odds-api.com/liveapi/guides/v4/index.html | 2026-10-19T23:04Z (WebFetch), 2026-10-19T23:05:48Z (curl text) | all endpoints, params, cost formulas, quota headers, response notes, 429 text |
| https://the-odds-api.com/api-reference/v4/ | 2026-10-19T23:07:35Z | Scalar reference UI; points to schema.yml |
| https://the-odds-api.com/api-reference/v4/schema.yml | 2026-10-19T23:07:52Z | OpenAPI 3.0.1 (dated 2025-11-05): regions enum, param descriptions, 401/404/422/429 texts, Outcome/Score schemas, 11 paths |
| https://the-odds-api.com/sports-odds-data/bookmaker-apis.html | 2026-10-19T23:04Z (WebFetch), 2026-10-19T23:05:49Z (curl) | hardrockbet, hardrockbet_az, hardrockbet_fl, hardrockbet_oh in us2; pinnacle in eu with delay note; paid-only keys |
| https://the-odds-api.com/sports-odds-data/betting-markets.html | 2026-10-19T23:04Z (WebFetch), 2026-10-19T23:05:49Z (curl) | featured vs additional markets; NBA prop and alternate keys; coverage caveats; no parlay |
| https://the-odds-api.com/ | 2026-10-19T23:04Z (WebFetch), 2026-10-19T23:07:02Z (curl) | pricing tiers, 500 free credits, "Most bookmakers" vs "All bookmakers", billing, link map |
| https://the-odds-api.com/liveapi/guides/v4/samples.html | 2026-10-19T23:04Z | code-sample landing page only; no response shapes |
| https://the-odds-api.com/terms-and-conditions.html | 2026-10-19T23:05Z (WebFetch), 2026-10-19T23:05:48Z (curl) | restrictions, permitted uses, attribution, liability, responsible gambling, governing law |
| https://the-odds-api.com/manage/faqs.html | 2026-10-19T23:05Z (WebFetch), 2026-10-19T23:07:02Z (curl) | credit definition, monthly reset on the 1st, billing/cancel; no overage or rate-limit text |
| https://the-odds-api.com/sports-odds-data/update-intervals.html | 2026-10-19T23:05Z | 60s/40s featured, 60s/60s additional, 6-hour ramp |
| https://the-odds-api.com/historical-odds-data/ | 2026-10-19T23:05Z | paid-only historical; 10x multipliers; NBA start 2020-06-27; props from 2023-05-03 |
| https://the-odds-api.com/sports-odds-data/sports-apis.html | 2026-10-19T23:05Z | basketball_nba and related keys; NBA scores covered |
| https://the-odds-api.com/sports-odds-data/nba-odds.html | 2026-10-19T23:06Z | NBA props "limited to US and AU bookmakers"; Hard Rock not named; example URL |
| https://the-odds-api.com/guide/rate-limit.html | 2026-10-19T23:07Z (WebFetch), 2026-10-19T23:07:53Z (curl) | 30 req/s on paid plans; 429 handling; caching advice |
| https://the-odds-api.com/sports-odds-data/bets-api.html | 2026-10-19T23:07Z | marketing page; featured markets only; no parlay/SGP |
| https://the-odds-api.com/releases/deep-links.html | 2026-10-19T23:07Z | includeLinks/includeSids semantics; link/sid fields; supported books not listed |
| https://the-odds-api.com/sports-odds-data/live-sports-odds.html | 2026-10-19T23:07Z | marketing page; in-play "approx. every 30 seconds"; no Hard Rock mention |
| https://github.com/the-odds-api/samples-python/blob/master/README.md | 2026-10-19T23:05Z | sample script description only |
| https://raw.githubusercontent.com/the-odds-api/samples-python/master/odds.py | 2026-10-19T23:06Z | reads headers x-requests-remaining / x-requests-used; params regions, markets, oddsFormat, dateFormat |

## Unresolved

1. Whether `hardrockbet_fl` returns NBA player props / alternate lines: not documented on any official page. Needs a live probe of `/events/{id}/markets?bookmakers=hardrockbet_fl` with a real key.
2. Whether `hardrockbet_fl` has `includeLinks` deep links to betslips: not documented.
3. Free-plan rate limit: not stated (only "30 requests per second on paid usage plans").
4. Overage / what the 401 body says at quota exhaustion: no overage mechanism documented; 401 body contents not documented.
5. Whether the free tier's "Most bookmakers" includes all Hard Rock keys: inferred yes from the paid-only markers, not stated outright.
6. Whether `bookmakers` is counted exactly like regions on the event-odds endpoint: implied by "Parameters are the same as for the /odds endpoint" but the event-odds cost formula only says "regions specified".
7. Whether `hardrockbet` (Indiana, "currently same odds as several other states") mirrors FL: not stated.
