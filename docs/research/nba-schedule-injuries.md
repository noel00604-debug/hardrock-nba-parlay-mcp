# NBA games on 2026-10-20 and the official injury report process

Research key: `nba-schedule-injuries`
Prepared: 2026-10-19, between 23:03 and 23:11 UTC (19:03 to 19:11 America/New_York, EDT)
Scope: the Tuesday 2026-10-20 slate from official NBA sources, an ESPN cross-check, how the official NBA injury report is published, and schedule notes (NBA Cup, time zones, DST).

All web content below was read as data. Quotes are kept short. Retrieval times come from `date -u` calls made around each batch of requests; where a batch fell between two calls the bracket is shown.

---

## 1. Games on Tuesday 2026-10-20 (official sources)

### 1a. NBA Communications press release (primary)

Source: https://pr.nba.com/2026-27-nba-regular-season-schedule
Headline: "NBA announces schedule for 2026-27 regular season", dated August 13, 2026.
Retrieved: 2026-10-19 between 23:03:43 and 23:05:37 UTC (two fetches).

Key passage (verbatim fragments): "American Express NBA Tip-Off 2026 will begin on Tuesday, Oct. 20 with an NBC/Peacock tripleheader".

| # | Away | Home | Tip (ET) | Arena (per source) | National TV | Note in release |
|---|------|------|----------|--------------------|-------------|-----------------|
| 1 | Boston Celtics | Detroit Pistons | 3:00 PM | not named in the Oct. 20 paragraph | NBC/Peacock | "the Celtics visiting the Pistons" (East's two best 2025-26 records) |
| 2 | Philadelphia 76ers | New York Knicks | 7:00 PM | not named in the Oct. 20 paragraph | NBC/Peacock | Knicks "will raise their 2025-26 championship banner"; "Live coverage will begin with NBA Showtime at 6:30 p.m. ET" |
| 3 | Oklahoma City Thunder | San Antonio Spurs | 9:30 PM | Frost Bank Center | NBC/Peacock | "rematch of the 2026 Western Conference Finals" |

Other schedule facts from the same release:
- "ESPN/ESPN App will present doubleheaders on Wednesday, Oct. 21 and Thursday, Oct. 22" described as "the second and third days of the regular season".
- "defined dates and opponents for 80 of each team's 82 games" (the two unassigned games per team fall Dec. 4 to Dec. 10 and depend on NBA Cup Group Play results).
- "The NBA's 81st regular season will conclude on Sunday, April 11, 2027."
- "Coast 2 Coast Tuesday will return on Oct. 27" with "the Trail Blazers visiting the Lakers (8 p.m. PT)"; "an 8 p.m. PT game will be presented to NBC stations in the Mountain and Pacific time zones."
- The release does not state a preseason end date and does not contain a general time-zone note; all times are given in ET.

### 1b. nba.com key dates page (official)

Source: https://www.nba.com/news/key-dates
Heading: "Key dates for 2026-27 NBA season"; page shows "Updated on October 18, 2026 12:17 AM".
Retrieved: 2026-10-19 between 23:05:38 and 23:06:32 UTC.

- "Oct. 3: Preseason begins" (NBA Canada Games, Raptors vs. Heat, Quebec City).
- "Oct. 15-16: NBA ID Member Days (preseason action)".
- "Oct. 19: Rosters set for Opening Day (5 p.m. ET)".
- "Oct. 20: Regular season opens with three games, all on NBC/Peacock": Celtics vs. Pistons 3 p.m. ET; 76ers vs. Knicks 7 p.m. ET; Thunder vs. Spurs 9:30 p.m. ET.
- "Oct. 30: NBA Cup group play begins"; "Nov. 27: NBA Cup group play ends".
- Nov. 7: Mexico City Game, Nuggets vs. Pacers, Arena CDMX.
- Dec. 4-5 quarterfinals; Dec. 8 and/or 9 semifinals; Dec. 11 championship at Hinkle Fieldhouse, Indianapolis.
- Regular season ends April 11, 2027. All-Star 2027 Feb. 19-21 in Phoenix; All-Star break Feb. 19-24.

### 1c. nba.com/schedule (official, browser-rendered)

Source: https://www.nba.com/schedule
Retrieved: 2026-10-19 between 23:07:53 and 23:10:31 UTC, in the built-in browser pane (the raw HTML fetched by WebFetch at ~23:04 UTC contained filters only and no game rows; the schedule is JavaScript-rendered).

Rendered text (verbatim structure): "Week 1 (Oct 20 - Oct 25)" / "TUESDAY, OCTOBER 20" / "3 Games":
- "3:00 PM ET" Boston Celtics / Detroit Pistons (listed away then home)
- "7:00 PM ET" Philadelphia 76ers / New York Knicks
- "9:30 PM ET" Oklahoma City Thunder / San Antonio Spurs

National TV is shown as broadcaster logos, not text: the accessibility tree contains "NBC" and "Peacock" presentation nodes and peacocktv.app.link links next to the Week 1 games. Arenas are not shown in the list view. The page geolocated to South Florida (local TV "WPLG Local 10" and radio "WQAM" appear on Heat games), consistent with a Florida user.

"WEDNESDAY, OCTOBER 21 / 11 Games" and "THURSDAY, OCTOBER 22 / 2 Games" follow, matching the press release's "second and third days".

Preseason view (https://www.nba.com/schedule?pd=false&season=Preseason, same browser session): the last day heading found was "Friday, October 16 (Preseason)"; no headings for October 17, 18, or 19.

### 1d. Opening night and preseason status

- 2026-10-20 is opening night of the 2026-27 regular season. Two official statements: pr.nba.com "American Express NBA Tip-Off 2026 will begin on Tuesday, Oct. 20"; nba.com key dates "Oct. 20: Regular season opens with three games".
- Preseason is over. Official evidence: nba.com preseason schedule view ends at "Friday, October 16 (Preseason)"; key dates lists Oct. 15-16 as the last "preseason action" and Oct. 19 as the roster-set deadline (5 p.m. ET). ESPN (section 2) shows 12 preseason finals on Oct 16 and no NBA games Oct 17, 18, or 19.
- The 2025-26 champion is the New York Knicks (press release: "defending NBA champion New York Knicks").

---

## 2. ESPN cross-check (session ESPN tool)

Tool: `espn_scoreboard` (sport=basketball, league=nba, timezone=America/New_York). Date format YYYYMMDD worked on the first try.
Called: 2026-10-19 at about 23:05 UTC (20261020), 23:06 UTC (20261019, 20261021), 23:08 UTC (20261016/17/18 with seasonType=1).

Result for 20261020 (three games, all "Scheduled"):

| ESPN eventId | Matchup | ESPN time | ESPN venue | Agrees with NBA? |
|---|---|---|---|---|
| 401909088 | Boston Celtics at Detroit Pistons | 3:00 PM EDT | Little Caesars Arena | Yes (time, home/away). Arena not in NBA Oct. 20 text; ESPN supplies it |
| 401909089 | Philadelphia 76ers at New York Knicks | 7:00 PM EDT | Madison Square Garden | Yes. Arena not in NBA Oct. 20 text; ESPN supplies it |
| 401909090 | Oklahoma City Thunder at San Antonio Spurs | 9:30 PM EDT | Frost Bank Center | Yes, including arena |

Agreements: game count (3), matchups, home/away, tip times (ESPN labels them EDT, NBA labels them ET; identical instants). ESPN's 2026-10-21 slate (11 games) also matches nba.com/schedule's "11 Games" list game-for-game and time-for-time.
Disagreements: none found. Gaps: the ESPN scoreboard tool returned no broadcast/TV field, so national TV is sourced only from NBA.
Preseason boundary per ESPN: 20261016 returned 12 games, all "Final" (e.g., Miami at Orlando 115-136 at Kia Center; Denver at Lakers 121-106); 20261017, 20261018, 20261019 returned "No games found" with and without seasonType=1.

---

## 3. Official NBA injury report process

### 3a. Where the report lives, and the 2026-27 page question

- official.nba.com home (https://official.nba.com/, retrieved 2026-10-19 between 23:03:43 and 23:05:37 UTC) is dated October 19, 2026. Its header News menu item "Team Injury Reports" links to https://official.nba.com/nba-injury-report-2025-26-season/ . The footer's "Team Injury Reports" link points to the older https://official.nba.com/nba-injury-report-2022-23-season/ .
- https://official.nba.com/nba-injury-report-2026-27-season/ returned HTTP 404 Not Found (retrieved ~23:04 UTC). A web search for an official 2026-27 injury page found none.
- https://official.nba.com/nba-injury-report-2025-26-season/ (retrieved 23:05 and 23:06 UTC) has the title "NBA Injury Report: 2025-26 Season" but lists the current reports: a single date heading "October 19:" with links from "12:00 a.m ET report" through "7:00 p.m ET report", all dated 2026-10-19. The title is stale; the content is live.
- https://official.nba.com/nba-injury-report-2024-25-season/ (retrieved ~23:08 UTC) also resolved to the page titled "NBA Injury Report: 2025-26 Season" with the same October 19, 2026 links, which suggests older season URLs resolve to the current page (mechanism not confirmed; could be a redirect).

Implication for the build: do not hardcode a "2026-27" page URL and do not infer the season from the page title. Resolve the page from the official.nba.com navigation link labelled "Team Injury Reports", or go straight to the PDF URL pattern below.

### 3b. Reporting deadlines (verbatim from the official page)

From https://official.nba.com/nba-injury-report-2025-26-season/ (retrieved 2026-10-19 23:06 UTC):

1. "NBA teams must report information concerning player injuries, illnesses, other medical conditions, or rest for all NBA games."
2. "By 5 p.m. local time the day before a game (other than the second day of a back-to-back)," teams "must designate a participation status" and "identify a specific injury, illness, other medical condition, or other reason" for "any player whose participation in the game may be affected for any reason."
3. "For the second game of a back-to-back, teams must report the above information by 1 p.m. local time on the day of the game."
4. "teams are required to submit a game-day injury report between 11 a.m. and 1 p.m. local time" "(and between 8 and 10 a.m. for tip-offs 5 p.m. or earlier) on game days (besides the second game of a back-to-back)."
5. "Reports are updated on a continual basis throughout the day."

Not on the official page: any "1:30 PM ET" or "5:00 PM ET" publication time, any "30 minutes" or "60 minutes before tipoff" update rule, any definition of Out/Doubtful/Questionable/Probable/Available, and any sentence stating the PDF republication interval. Deadlines are stated in the team's local time, not ET.

For 2026-10-20 specifically: the day-before deadline was 5 p.m. local on Oct 19; the game-day report for Boston at Detroit (3:00 PM ET tip, so "5 p.m. or earlier") is due between 8 and 10 a.m. local (Detroit is ET); the 7:00 and 9:30 PM ET games get game-day reports between 11 a.m. and 1 p.m. local (New York: ET; San Antonio: CT, so 12 p.m. to 2 p.m. ET).

### 3c. PDF URL pattern and cadence

Host and pattern (from the page's links and direct checks):
`https://ak-static.cms.nba.com/referee/injury/Injury-Report_YYYY-MM-DD_HH_MMAM.pdf` and `..._HH_MMPM.pdf` (12-hour clock, zero-padded hour, e.g. `_12_00AM`, `_06_45PM`). The page labels these "12:00 a.m ET report", "12:15 a.m ET report", ... "7:00 p.m ET report": 15-minute slots. A 2019 result in search showed an older pattern without minutes (`Injury-Report_2019-10-25_05PM.pdf`), so the pattern has changed before.

HEAD checks run 2026-10-19 at 23:07:53 UTC (19:07 EDT):
- `Injury-Report_2026-10-19_12_00AM.pdf` -> HTTP 200
- `Injury-Report_2026-10-19_06_45PM.pdf` -> HTTP 200
- `Injury-Report_2026-10-19_07_15PM.pdf` -> HTTP 403 (slot not yet generated at 19:07 ET)
- `Injury-Report_2026-10-18_05_00PM.pdf` -> HTTP 403 and `Injury-Report_2026-10-18_12_00AM.pdf` -> HTTP 403 (Oct 18 had no next-day NBA games; unclear whether never generated or removed)
- `Injury-Report_2026-10-20_12_00AM.pdf` -> HTTP 403 (future)
Missing files return 403, not 404, on this host.

### 3d. Most recent report found, and its contents

URL: https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-10-19_07_00PM.pdf
Downloaded 2026-10-19 23:05:37 UTC: HTTP 200, 81,247 bytes, application/pdf, 2 pages.
PDF header: "Injury Report: 10/19/26 07:00 PM". Columns: "Game Date | Game Time | Matchup | Team | Player Name | Current Status | Reason". Game times are printed with "(ET)".

Rows as extracted by `pdftotext -layout` (team label prints only on a team's first row; long reasons wrap onto a second line; team attribution of some rows therefore needs confirmation against the PDF itself):

| Game Date | Game Time | Matchup | Team (as printed) | Player | Current Status | Reason |
|---|---|---|---|---|---|---|
| 10/20/2026 | 03:00 (ET) | BOS@DET | Boston Celtics | Carter, Devin | Out | Injury/Illness - Illness |
| | | | Detroit Pistons | Harkless, Elijah | Questionable | G League - Two-Way |
| | | | | Jones, Isaac | Out | G League - Two-Way |
| | | | | Onyenso, Ugonna | Out | G League - Two-Way |
| | | | | Prince, Taurean | Questionable | Personal Reasons |
| | 07:00 (ET) | PHI@NYK | Philadelphia 76ers | Barlow, Dominick | Out | Injury/Illness - Low Back Stress Reaction |
| | | | (no new team label printed) | Bona, Adem | Questionable | Injury/Illness - Left Foot Sprain |
| | | | | Fall, Tacko | Out | Injury/Illness - Left Quadriceps Strain |
| | | | | Hukporti, Ariel | Out | Injury/Illness - Right Achilles Tendon Rupture / Tear |
| | | | | Simons, Anfernee | Questionable | Injury/Illness - Left Hamstring Tightness / Soreness |
| | | | | Wade, Dean | Questionable | Injury/Illness - Left Ankle Sprain |
| | 09:30 (ET) | OKC@SAS | Oklahoma City Thunder | Oweh, Otega | Out | Injury/Illness - Right Achilles Tendon Repair / Surgery |
| | | | | Sorber, Thomas | Out | Injury/Illness - Right Knee Surgery |
| | | | | Topic, Nikola | Out | Injury/Illness - Low Back Surgery |
| | | | San Antonio Spurs | Harris, Tobias | Out | Injury/Illness - Left Calf Strain |
| | | | (page 2) | Quaintance, Jayden | Out | Injury/Illness - Right Knee Surgery |

Caution: in the text extraction, no "New York Knicks" label appeared in the PHI@NYK block; rows after "Barlow, Dominick" may belong to either team. Verify visually or with a column-aware parser before using team attribution.

### 3e. Designation vocabulary

Observed in official PDFs (primary evidence of the vocabulary in use):
- Oct 19, 2026 7:00 PM report: "Out", "Questionable".
- March 26, 2026 8:00 PM report (https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-03-26_08_00PM.pdf, downloaded 23:07:53 UTC, HTTP 200, 88,055 bytes): whole-word counts "Available" 14, "Probable" 5, "Questionable" 16, "Doubtful" 9, "Out" 101, "NOT YET SUBMITTED" 2.
So the live vocabulary is: Available, Probable, Questionable, Doubtful, Out, plus the placeholder "NOT YET SUBMITTED" for teams that have not filed.

Definitions: no league-level definitions page was found on official.nba.com, nba.com news, or pr.nba.com. The only nba.com-domain definition found is a Sacramento Kings team blog from January 5, 2017 (https://www.nba.com/kings/blog/injury-kings-clippers, read in the browser ~23:09 UTC), "Participation Status Key": "Probable – 75% chance that the player will play in the game", "Questionable – 50% chance", "Doubtful – 25% chance", "Out – Player will not play in the game". ESPN (2019, https://www.espn.com/nba/story/_/id/26784014/reliable-injury-info-hard-come-by, surfaced by search, not fetched) reports that rules require teams to announce whether a player is probable, questionable, doubtful or out by 5 p.m. the day before. Treat the percentages as a conventional key, not a current league definition.

---

## 4. Schedule-related notes

### 4a. Emirates NBA Cup 2026

Sources: pr.nba.com schedule release (above); https://www.nba.com/news/2026-nba-cup-group-play-schedule-announced ("Group Play schedule for Emirates NBA Cup 2026 revealed", August 12, 2026, retrieved ~23:06 UTC); https://www.nba.com/nba-cup/2026 (retrieved ~23:08 UTC); nba.com/schedule rendered view.
- Group Play: 60 games, "beginning on Oct. 30 and concluding on Nov. 27". Game dates: Fri Oct 30, Fri Nov 6, Fri Nov 13, Fri Nov 20, Tue Nov 24, Wed Nov 25, Fri Nov 27.
- Knockout: quarterfinals Fri Dec 4 and Sat Dec 5; semifinals Tue Dec 8 and/or Wed Dec 9; championship Fri Dec 11 at Hinkle Fieldhouse, Indianapolis.
- nba.com/schedule labels these games "EMIRATES NBA CUP" with a group tag (e.g., "EAST GROUP C" for Charlotte Hornets / Washington Wizards, Oct 30, 7:00 PM ET). The first Cup night falls inside the 30-day review window (Oct 20 to Nov 18).
- Groups (from search snippet of https://www.nba.com/news/emirates-nba-cup-2026-groups-announced, not fetched): East A Pistons, Raptors, Magic, Bucks, Nets; East B Knicks, Cavaliers, 76ers, Heat, Pacers; East C Celtics, Hawks, Hornets, Bulls, Wizards; West A Nuggets, Rockets, Suns, Mavericks, Jazz; West B Thunder, Timberwolves, Clippers, Pelicans, Grizzlies; West C Spurs, Lakers, Trail Blazers, Warriors, Kings.
- Whether Group Play games count in regular-season standings is not stated on the fetched pages; the press release's "80 of each team's 82 games" wording implies they do, but this is inference.

### 4b. Time zones

- NBA sources (pr.nba.com, nba.com key dates, nba.com/schedule, the injury PDF) print times as "ET" without distinguishing EDT/EST. ESPN prints "EDT" explicitly for Oct 20.
- Late West Coast games are listed in ET on nba.com (e.g., Oct 27 Portland Trail Blazers at Los Angeles Lakers "11:00 PM ET", which the press release calls "8 p.m. PT"); a late-night ET tip can finish after midnight ET, and 10:00/10:30 PM ET tips already start after 00:00 UTC the next day.
- Injury-report deadlines are in each team's local time (section 3b), so a Florida user must convert per home-team time zone.

### 4c. Daylight saving time

- NIST (https://www.nist.gov/pml/time-and-frequency-division/popular-links/daylight-saving-time-dst, retrieved 2026-10-19 23:10:31 UTC): DST "ends at 2:00 a.m. on the first Sunday of November"; for 2026 the page states DST runs "to November 1 at 2 a.m. (local time)"; it "begins at 2:00 a.m. on the second Sunday of March".
- Local verification with Python `zoneinfo` (America/New_York), run 23:06 UTC: 2026-10-20 15:00 = EDT (-04:00) = 19:00 UTC; 21:30 EDT = 01:30 UTC Oct 21; 2026-10-31 20:00 EDT = 00:00 UTC Nov 1; transition at 2026-11-01 02:00 EDT -> 01:00 EST; 2026-11-02 19:00 = EST (-05:00) = 00:00 UTC Nov 3.
- Consequence: from Nov 1 the same printed "7:00 PM ET" moves from 23:00 UTC to 00:00 UTC next day. Store UTC and compute the America/New_York calendar day for the $10 cap from UTC, never from a fixed offset.

### 4d. Machine-readable official schedule access (negative result)

- `https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json` returned HTTP 403 "Access Denied" (Akamai) from curl at 23:05:38 and again with browser-like headers at 23:06:32 UTC. `https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json` also 403 at 23:07:53 UTC. `https://stats.nba.com/stats/scheduleleaguev2?Season=2026-27&LeagueID=00` timed out after 30 s.
- The nba.com/schedule page only renders games through JavaScript. Automated official-schedule ingestion is therefore not verified from this machine; ESPN's scoreboard (via the session tool) and the odds provider's event list are the working machine-readable paths, with nba.com as the human cross-check.

### 4e. Other official.nba.com facts picked up

- Referee assignments page (https://official.nba.com/referee-assignments/, retrieved ~23:06 UTC): "Referee assignments are posted at approximately 9:00am ET each game day." On Oct 19, 2026 it listed no NBA game; the only entry was a WNBA assignment (Atlanta @ Golden State). The home page's "Today's Officials" block for Oct 19 was that WNBA game, not an NBA preseason game.
- 2026-27 Official NBA Playing Rules PDF: https://ak-static.cms.nba.com/wp-content/uploads/sites/4/2026/10/2026-27-Official-NBA-Playing-Rules.pdf (link seen on the home page; not downloaded).

---

## 5. Build implications (summary)

1. Opening night is 2026-10-20 with exactly three games; the earliest tip is 3:00 PM ET (19:00 UTC), so the day-one workflow must be usable in the morning, not the evening.
2. Day-before injury baseline for Oct 20 exists now: the 7:00 PM ET Oct 19 report. Game-day reports for the 3 PM game are due 8 to 10 a.m. Detroit time; for the 7 and 9:30 PM games, 11 a.m. to 1 p.m. local.
3. Injury report ingestion: resolve the page via the official.nba.com "Team Injury Reports" nav link or probe `Injury-Report_YYYY-MM-DD_HH_MM{AM,PM}.pdf` in 15-minute slots (latest first; missing = 403). Record the PDF header timestamp (ET) as the source publication time, separately from fetch time. Parse column-aware; handle wrapped reasons, team label only on first row, and "NOT YET SUBMITTED".
4. Treat Questionable/Doubtful as material unresolved status; the 75/50/25 key is conventional, not an official 2026-27 definition.
5. Store UTC, render America/New_York with offset; DST ends 2026-11-01 02:00 local inside the review window.
6. Tag Emirates NBA Cup games (from Oct 30) using nba.com's label; sportsbook rules for those games were not checked here.

---

## Sources

| URL | retrieved_at_utc (2026-10-19) | what it established |
|---|---|---|
| https://pr.nba.com/2026-27-nba-regular-season-schedule | 23:04 (between 23:03:43 and 23:05:37), re-fetched ~23:05:40 | Oct 20 tripleheader, times, NBC/Peacock, Frost Bank Center, Tip-Off wording, Oct 21-22 "second and third days", NBA Cup dates, season end Apr 11 2027, 8 p.m. PT note |
| https://www.nba.com/schedule (WebFetch raw HTML) | ~23:04 | Page is JS-rendered; no games in HTML |
| https://www.nba.com/schedule (built-in browser, rendered) | between 23:07:53 and 23:10:31 | "Week 1 (Oct 20 - Oct 25)", 3 games Oct 20 at 3:00/7:00/9:30 PM ET; 11 games Oct 21; Cup labels from Oct 30; NBC/Peacock nodes; Florida local broadcasters |
| https://www.nba.com/schedule?pd=false&season=Preseason (browser) | ~23:10 | Last preseason heading "Friday, October 16 (Preseason)"; none for Oct 17-19 |
| https://official.nba.com/ | ~23:04 | Dated Oct 19 2026; nav "Team Injury Reports" -> 2025-26 URL; footer -> 2022-23 URL; rulebook PDF URL; Today's Officials showed a WNBA game |
| https://official.nba.com/nba-injury-report-2026-27-season/ | ~23:04 | HTTP 404 |
| https://official.nba.com/nba-injury-report-2025-26-season/ | ~23:05 and ~23:06 | Verbatim reporting deadlines; "updated on a continual basis"; Oct 19 2026 PDF links 12:00 a.m. to 7:00 p.m. ET at 15-min labels; no designation definitions |
| https://official.nba.com/nba-injury-report-2024-25-season/ | ~23:08 | Resolves to the 2025-26-titled page with Oct 19 2026 links |
| https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-10-19_07_00PM.pdf | 23:05:37 | Most recent report; header "Injury Report: 10/19/26 07:00 PM"; Oct 20 rows; column layout |
| https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-10-19_12_00AM.pdf and _06_45PM.pdf | 23:07:53 (HEAD) | HTTP 200: slots exist |
| ..._2026-10-19_07_15PM.pdf, ..._2026-10-18_05_00PM.pdf, ..._2026-10-18_12_00AM.pdf, ..._2026-10-20_12_00AM.pdf | 23:07:53 (HEAD) | HTTP 403 for future/absent slots |
| https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-03-26_08_00PM.pdf | 23:07:53 | Vocabulary counts: Available, Probable, Questionable, Doubtful, Out, NOT YET SUBMITTED |
| https://official.nba.com/referee-assignments/ | ~23:06 | "posted at approximately 9:00am ET each game day"; Oct 19 WNBA-only listing |
| https://www.nba.com/news/key-dates | ~23:06 | Preseason Oct 3; Oct 15-16 preseason action; Oct 19 rosters set 5 p.m. ET; Oct 20 regular season opens; Cup Oct 30-Nov 27; Dec knockout dates; Apr 11 2027; All-Star Feb 19-21 |
| https://www.nba.com/news/2026-nba-cup-group-play-schedule-announced | ~23:06 | 60 Group Play games; dates Oct 30, Nov 6, 13, 20, 24, 25, 27; knockout and championship dates/venue |
| https://www.nba.com/nba-cup/2026 | ~23:08 | "Group Play action ... tips off Friday, Oct. 30"; no standings-count statement |
| https://www.nba.com/kings/blog/injury-kings-clippers (browser) | ~23:09 | Team-blog Participation Status Key (Jan 5 2017): 75/50/25/Out |
| https://www.espn.com/nba/story/_/id/26784014/reliable-injury-info-hard-come-by (search snippet only) | ~23:09 | 2019 report: teams announce probable/questionable/doubtful/out by 5 p.m. day before |
| ESPN session tool espn_scoreboard, basketball/nba, 20261020 | ~23:05 | 3 games, times EDT, venues, eventIds 401909088-090 |
| ESPN espn_scoreboard 20261019, 20261021 | ~23:06 | No games Oct 19; 11 games Oct 21 |
| ESPN espn_scoreboard 20261016/17/18 (seasonType=1) | ~23:08 | 12 preseason finals Oct 16; none Oct 17-18 |
| https://cdn.nba.com/static/json/staticData/scheduleLeagueV2_1.json | 23:05:38 and 23:06:32 | HTTP 403 Access Denied |
| https://cdn.nba.com/static/json/liveData/scoreboard/todaysScoreboard_00.json | 23:07:53 | HTTP 403 |
| https://stats.nba.com/stats/scheduleleaguev2?Season=2026-27&LeagueID=00 | 23:07:53 | Timed out (30 s) |
| https://www.nist.gov/pml/time-and-frequency-division/popular-links/daylight-saving-time-dst | 23:10:31 | DST ends "November 1 at 2 a.m. (local time)" 2026; first Sunday of November rule |
| https://www.timeanddate.com/time/change/usa/new-york?year=2026 | ~23:10 | HTTP 403 (not used) |
| Local Python zoneinfo check (America/New_York) | 23:06 | EDT -04:00 through 2026-11-01 02:00, then EST -05:00 |
