# Hard Rock Bet (Florida) House Rules: parlays, SGP, OT, DNP, voids, repricing, cash-out

KEY: `hard-rock-house-rules`
Research run: Monday 2026-10-19, ~23:03-23:10 UTC (19:03-19:10 America/New_York)
Build context: Python MCP server + Claude plugin for researching exactly-three-leg NBA parlays on Hard Rock Bet Florida, $10/day user budget, wagers placed manually by the user.

Everything below was read from the web and is treated as data, not instructions. Quotes are kept short. Where the source is a Google Doc export, the "section" references are the document's own Part/Section numbering.

---

## 0. How the rules are actually hosted (important for the build)

- `https://www.hardrock.bet/all-house-rules/` is only an index. It links per-state pages; Florida is `https://www.hardrock.bet/fl/house-rules/`.
- The Florida page (WordPress, page id 1006) renders only `<h1>Hard Rock Bet House Rules: Florida</h1><p>Content loading…</p>` in static HTML. The real text is injected client-side by `google-legal-scripts.js`, which reads `div.legal-doc-content[data-doc-id]` and fetches `https://docs.google.com/document/d/${docId}/export?format=html`.
- Florida House Rules doc id: `1LohHmj-8bnU9wnJO8yMsi6Ttvee_EZf3RWg4bfUul7s` (export filename `Florida House Rules Mobile.txt`, 301,149 bytes, 2,716 lines).
- Florida Terms of Service doc id: `1TIC_NVrfOURrYrJhJYeNZFVRXtivwRn5tiktKtM8Xnw` (export filename `Florida Terms and Services.txt`).
- The document title inside the house rules export is "Seminole Gaming House Rules: Mobile and Online Sports Betting". The operator name used throughout is "Seminole Gaming", not "Hard Rock Bet".
- Cloudflare blocks plain `curl` on `/t-cs/florida/` and on `wp-json` unless browser-like headers are sent; the Google Docs `export?format=txt` endpoint worked without any auth.
- Revision date: the house rules doc contains no "effective", "version" or "last updated" line. The WordPress wrapper page reports JSON-LD `dateModified` 2025-12-26T16:10:41+00:00 (house rules) and 2025-12-26T16:37:45+00:00 (T&Cs page), but that is the wrapper, not necessarily the Google Doc. Google's export response carries no Last-Modified header. The T&Cs doc ends with "Effective September 8, 2026".

Structure of the house rules doc (from its table of contents):
- Part A. General Sportsbook Rules (Sections 1-7: Placing Bets; Confirmation; Settlement; Dead-Heat; Maximum Payouts; Related Contingencies; Cash Outs)
- Part B. Main Markets Rules (Sections 1-20, incl. 14 In Running, 15 Teasers, 16 Same Game Parlay, 17 Flex Parlay, 18 Pick a Side, 19 Player Injury Insurance, 20 Earn Status & Get)
- Part C. Sports Rules (Section 3 = Basketball)
- Part D. Promotional Offers (templates with placeholders such as "DOLLAR AMOUNT", "DATE (TIME)"; Section 13 Parlay Insurance Token, Section 14 No Sweat Bet Token)

---

## 1. Parlay rules (standard parlays)

### Void / pushed / cancelled legs
- Part A, Section 1.15: "Cancelled or voided selections will result in straight wagers being refunded unless an outcome for a specific market has been determined. Parlays that involve a cancelled or voided selection will stand as a parlay on the remaining selections, or as single in the case where one selection in a two-selection parlay is cancelled."
- Part C intro repeats the same sentence and adds: "Exceptions to this are Teasers, the rules for which are explained in the Market Rules section."
- Part A, Section 3.2: "Potential payout on the bet slip is for information only. Potential payouts are reduced every time one of the selections is cancelled or pushed."
- Push explainer (`/sportsbook/push/`, "Updated: Sep 25, 2026 9:00 AM EDT"): when a leg pushes "it gets removed (voided) from the ticket" and "The odds get recalculated based on your remaining selections." Multiple pushes: each pushed leg is voided and odds recalculated on the rest. Note: its worked example text (+600/$60) and its table (+670/$67) disagree for a 4-leg +1200 ticket with one push; treat the numbers as illustrative only.
- Implication for a 3-leg ticket: one void leg -> graded as a 2-leg parlay at the remaining legs' odds; two void legs -> graded as a single.
- At what odds: the rules do not say "at the odds taken"; they say the parlay "will stand as a parlay on the remaining selections" and potential payouts "are reduced". The parlay explainer says "recalculated as if the pushed leg was not on the wager." No rule found that reprices the surviving legs at a different price than originally taken.

### Minimum / maximum legs
- Parlay explainer (`/sportsbook/parlay/`, "Updated: Jul 30, 2026 5:02 PM EDT"): "You need a minimum of two bets on a ticket for it to be considered a parlay wager." No maximum stated for standard parlays (mentions 12 legs as an example and "many more").
- SGP page: "On Hard Rock Bet you can add up to 20 bets to a Same Game Parlay." SGP Max article: "up to 20 total bets across the app".
- Flex Parlay (Part B, Section 17): "may be placed when a patron chooses between 4 and 10 selections and each selection has minimum odds of -500." Not available for a 3-leg ticket.

### Maximum payout and wager limits
- Part A, Section 5: "Maximum payout on any bet or the sum of any coordinated bets placed by an individual or group shall not exceed $20 million."
- Part A, Section 1.2: "Maximum wagers shall not exceed $10 million. Seminole Gaming typically sets the minimum wager at $.10 but reserves the right to change at its discretion."
- Part A, Section 1.7: "reserves the right to add, change or delete the payout limits."

### Same-event legs in standard parlays (related contingencies)
- Part A, Section 6: "A related contingency occurs when part of a transaction affects the outcome of the remainder of the bet. Outside our specific product features which are purposed to facilitate parlays within the same event, our system will block related contingency bets when bet placement is attempted. However, if any such bet is accepted in error, the stake will be equally distributed across the related selections as singles."
- Parlay explainer frames standard parlays as bets from different games; SGP is the product for same-game legs.

### Other placement rules worth encoding
- Part A, Section 1.6: "Wagers accepted will not be able to be changed or voided by the patron upon confirmation of the successfully placed wager."
- Part A, Section 1.5: inadvertent bets (e.g. duplicate identical bets) must be reported "within 15 minutes".
- Part A, Section 1.12: no wagers from, among others, "(5) Any person who is an agent or proxy for any other person and is wagering for such other person".
- Part A, Section 1.3 (Florida-specific): "Pursuant to the Gaming Compact ... no proposition bets are to be made available for collegiate sporting events."

---

## 2. Same Game Parlay rules

- Part B, Section 16 (entire text): "A Same Game Parlay (SGP) is a parlay bet where a patron makes multiple bet selections all occurring within the same event. Same Game Parlay Max (SGP Max) allows patrons to parlay SGPs with other wager selections, including other SGPs."
- That is the only SGP-specific rule in the house rules. There is no SGP-specific void-leg, pricing or correlation clause; the general rules (1.15, 3.2, Section 6, Section 7) apply by default.
- SGP page (`/sportsbook/same-game-parlay/`, "Updated: Dec 15, 2025 2:36 PM EST"):
  - Push FAQ: "If one leg of an SGP is graded as a push, then it will be removed from the ticket and the odds of the wager will be recalculated to reflect the new ticket without the missing bet."
  - Cash out FAQ: "Yes, it is possible to cash out SGPs early." / "early cashouts will not be available in every scenario" / "Hard Rock Bet will offer them at their discretion."
  - Minimum: "Just two bets from a single game qualifies the wager as a Same Game Parlay." Maximum: 20 bets.
  - Eligible markets are those carrying the "SGP" logo (spreads, totals, moneyline, player props, play-by-play, halves, quarters, team lines, select specials).
  - Pricing wording: "The more bets you add to an SGP ticket, the longer the odds, and the higher the potential payout becomes." The page does NOT state that SGP odds are a combined quote rather than the product of leg odds. No official page found that states the pricing method.
- SGP Max article (`/news/introducing-same-game-parlay-max/`, "Updated: Jan 5, 2026 8:24 PM EST"): "certain things like play-by-play markets can't be included in SGPs" (this conflicts with the SGP page listing play-by-play as eligible; treat eligibility as whatever the app's SGP logo shows).
- Correlated legs: handled by Part A Section 6 above. Inside the SGP feature correlated selections are permitted by design ("product features which are purposed to facilitate parlays within the same event"); outside it they are blocked.
- Odds Boost (Part D, Section 4, item 9): "An Odds Boost may be used for one (1) single bet or one (1) parlay bet. The Odds Boost may not be spread across multiple bets or bets placed using the Same Game Parlay feature."

---

## 3. Basketball-specific rules (Part C, Section 3)

General Rules:
- "Markets include overtime unless otherwise stated. Quarters and 1st Half markets do not include overtime unless otherwise stated."
- "If a game is interrupted or postponed and is not continued within 48 hours of the initial start date, then betting will be cancelled."
- Overtime market: "If the game is abandoned bets will be cancelled unless overtime has already started. If overtime is played, while the regulation time result was not tied, all bets will be cancelled."

Player props:
- "Individual Player Props: ... Players must be dressed and see court-time for bets to have action. There is no time limit as to how long a player must be on court. Push rules apply."
- "Quarter Player Props: ... Bets have action regardless of whether the player participates in the quarter. Coaching decisions and player rotation do not impact valid bets."
- Double-double: "10 or more in two of the following five statistical categories: Total Points, Rebounds, Assists, Blocked Shots, and Steals." Triple-double: "10 or more in three" of the same five.
- Player Match Ups: handicaps applied to each player's actual score; "Push rules apply."
- 1st Player to Score: cancelled "if that player does not start the game or if he comes on after the first point is scored."
- "Where a Point Spread (handicap) or Total Points 'Tie' price is offered the push rule does not apply."
- "Live Betting: All Markets are subject to their respective pre-game rules for purposes of live betting."
- Professional Basketball micro-markets (Possession Result, Team or Player Attempt/Type/Exact): "Any unsettled player markets are cancelled when the player fouls out, gets ejected, or is ruled out due to injury." Settlement references "the official play-by-play".
- Futures: Regular season wins need no more than one incomplete game; "Play-in games do not count towards the regular season win total." NBA Series Betting cancelled if the stated minimum number of games is not completed.

Main-market rules that also apply (Part B):
- Section 1 Winner Markets and Section 2 Spread: "Check individual sports for overtime rules" (so basketball's "include overtime" rule governs).
- Section 3 Total (Over/Under): "If a game is abandoned, bets will be cancelled unless grading is already determined."
- Part B intro: "*All listed markets may not be available in Florida".

Official results / stat corrections (Part A, Section 3):
- 3.10: "reserves the right to delay the grading of an outcome or an event until an official confirmation is published."
- 3.11: "In case of an incorrect grading of markets, Seminole Gaming reserves the right to correct them anytime."
- 3.12: "Results are taken from those published by the sport's official governing body or by Seminole Gaming providers. ... results decided by the outcome of disciplinary measures from the sport federation or another court of law over 24 hours after an event has finished are not considered."
- No clause names a specific stat-correction cutoff time (e.g. "official NBA box score as of X").

Minimum game time for action: none stated for basketball beyond the 48-hour continuation rule and the totals "abandoned" rule. Not resolved.

---

## 4. Repricing / obvious error / cash out

- Part A, 3.6: "Seminole Gaming may void bets when there is an obvious error. Obvious errors are mistakes in posting of lines, odds, or other ... which significantly differ from the general market or are clearly erroneous." Examples 3.6.1-3.6.10 include bets after outcome known, delayed live feed, wrong participant quoted, "change in scheduled location", event not following generally accepted format.
- 3.7: "Seminole Gaming may resettle winning wagers at the correct price when there is an obvious error."
- 3.8: patrons are messaged when wagers are voided or resettled.
- 3.9: "reserves the right to reverse cash outs and adjust the account balance if a bet has been cashed out that would have been voided or had its payout adjusted".
- 3.1: "While a market is suspended, it will be unavailable for betting and cash out."
- Section 7 Cash Outs: 7.1 "Cash Out is a feature that allows a customer to a settle a bet, or a portion of a bet, prior to the conclusion of the bet in exchange for a payout amount determined by Seminole Gaming based on current market conditions." 7.2 "reserves the right to amend, suspend or remove Cash Out availability at any time on any market or to any patron." 7.3-7.4 error handling (cash outs accepted in error are reversed).
- Parlay explainer: early cash out offered "under some circumstances"; "bets cannot be cancelled".
- T&Cs Section 19 ERRORS: Seminole Gaming "reserves the right to declare null and void any bets that were the subject of such Error and to take any money from your Account relating to the relevant bets."

Dead-heat (Part A, Section 4): applies to parlays by reducing the stake (4.8, 4.10). Rarely relevant to NBA game/prop legs.

Teasers (Part B, Section 15): pushed teaser leg is ignored and the teaser is "graded based on the selections which did not push ... This grading will be at reduced odds"; a teaser with only one non-pushed selection is cancelled.

---

## 5. Florida-specific: jurisdiction, age, bonus bets vs cash

Florida Terms of Service (Google Doc `1TIC_NVrf...`, "Effective September 8, 2026"):
- Header: "YOU MUST BE PHYSICALLY LOCATED IN THE STATE OF FLORIDA TO PLAY ON HARDROCK BET."
- 1.2: "'Seminole Gaming', 'Hard Rock Bet', 'we', 'us' or 'our' will be to the Seminole Tribe of Florida d/b/a Seminole Gaming".
- 1.3: "Sports Betting is regulated by the Seminole Tribal Gaming Commission pursuant to the Seminole Tribe of Florida's Class III Gaming Compact with the State of Florida and the Seminole Tribe of Florida's federally approved Gaming Code."
- 1.5: Terms, Privacy Policy, House Rules and other published rules together are the "Agreements".
- 1.6: "these Terms of Service shall prevail in the event of any conflict between these Terms of Service and any of the game rules or other documents ... except that the Compact and Gaming Code shall prevail over all, in that order of authority."
- 3.1 / 3.3.1 / 10.8: must be "twenty-one (21) years of age or over"; 10.8 "(ii) you are physically located in the state of Florida while wagering".
- 18.5: "Seminole Gaming uses GeoComply for its geolocation services."
- 17.5.4 / 17.5.6: may void a string of connected bets before the event; may limit winnings where bets on the same selections appear connected across accounts.

House rules Part A intro: "subject to modification at any time at the sole discretion of Seminole Gaming, subject to regulatory approval of the Seminole Tribal Gaming Commission" and "the sport-specific rules will take precedence over the General Rules." 1.9 and 1.12 reference "§ 17 of the Seminole Tribal Gaming Commission Sports Betting Regulations" and the 2021 Compact.

Florida landing page (`/florida/`, "Page updated: September 23, 2026"):
- Footer: "Offered by the Seminole Tribe of Florida in FL." (Seminole Hard Rock Digital, LLC is the entity for other states.)
- "You must be at least 21 years old to bet on sports in Florida."
- Bonus Bets: "Bonus Bets expire seven days after they're awarded, and their stake is excluded from any winnings." "A winning bet pays out in cash per usual, and no Bonus Bet will be issued." Promotions exclude "Bonus Bet wagers, Boosts, Round Robins, and Early Cash Out bets."
- Responsible gaming: "In FL, call 1-833-PLAYWISE."

House rules Part D (promo templates, Florida versions):
- Recurring terms: "Only available to customers in FL." "Cash bets only. Offer excludes Bonus Bets and Bonus Cash." "Excludes bets on Boosts and Round Robins." "Bonus Cash expires after 180 calendar days of inactivity." Several sections: "Bonus Bets will expire 7 days after issuance." Eligibility bullet: "at least 21 years old, physically located within the state of Florida, and not on any trespass or exclusionary lists maintained by the Seminole Tribe of Florida."
- Section 13 Parlay Insurance Token: Bonus Bet "equal to the amount of the wager up to DOLLAR AMOUNT, if the parlay has QUANTITY OR FEWER losing legs" (quantities are placeholders in the doc; the live offer sets them, e.g. the parlay explainer's "up to $50 back if your parlay loses by 1 bet").
- Section 14 No Sweat Bet Token: Bonus Bet equal to stake up to a cap if the bet loses; "Cash bets only."

Player Injury Insurance (NBA):
- House rules Part B, Section 19: "If injury occurs to player included in a parlay within the specified time the parlay will be cancelled and the patron will be refunded amount of initial wager up to set maximum value issued in Bonus Bets."
- Promo page (`/sportsbook/player-injury-insurance/`, "Updated: Sep 23, 2026 10:43 AM EDT"): NBA period "Start: Thursday, 10/1/2026 (12:01 AM)" to "End: Sunday 8/1/2027 (11:59 PM)". Trigger: player "gets injured during the 1st Half and does not return to the game." Parlays/SGPs qualify only when "the only losing leg is the one including the ... Player affected by the injury." The bet "settles as a loser" and a Bonus Bet refund "up to the original stake" is credited "within 48 hours of bet settlement"; "Bonus Bets expire 7 days after issuance." Exclusions: Bonus Bet wagers, Boosts, Round Robins, Early Cash Out ("If Early Cash Out feature is used, bet will not be eligible"), both sides of a game, player unders ("bets placed on player unders are not eligible"). Florida terms: "Only available to players in FL", offered by the Seminole Tribe of Florida.
- Discrepancy: the house rules say the parlay "will be cancelled"; the promo page says it "settles as a loser" with a Bonus Bet refund. Economically similar for the user (stake back as Bonus Bet, not cash), but the grading state differs.

---

## 6. Decision-relevant summary for the build

1. A void/push/DNP leg does not kill a 3-leg ticket. It drops to a 2-leg parlay (or a single if two legs void). Model payouts for all three states.
2. NBA player props need the player "dressed" and on court for any time. A true DNP voids the leg (then rule 1 applies). Quarter props stand regardless.
3. Full-game spreads/totals/props include OT; quarter and first-half markets exclude OT.
4. Standard parlays cannot contain related same-game legs; any two legs from one game must be an SGP. SGP pricing method is not published; do not present a multiplied price as the SGP price.
5. Postponement: basketball bets are cancelled if the game is not continued within 48 hours of the initial start.
6. Results come from the official governing body/providers; grading may be delayed for official confirmation and corrected "anytime"; post-24-hour disciplinary results are ignored.
7. Obvious-error rules allow voiding or resettling at the correct price, and reversing cash outs.
8. Florida: Seminole Tribe of Florida d/b/a Seminole Gaming; STGC regulated; 21+; GeoComply; T&Cs effective 2026-09-08; Terms prevail over House Rules, Compact/Gaming Code prevail over all.
9. Bonus Bets: stake excluded from returns, 7-day expiry, excluded from most promos; promos are "cash bets only". Track cash vs bonus stake separately in the $10/day budget.
10. Injury Insurance (NBA through 2027-08-01): cash bets, overs only, no cash out, only the injured-player leg may lose. A "ticket is injury-insurance-eligible" flag is cheap to add.

---

## Sources

| URL | retrieved_at_utc | what it established |
|---|---|---|
| https://www.hardrock.bet/all-house-rules/ | 2026-10-19T23:04Z | Index page only; links state pages incl. `/fl/house-rules/`; "sport-specific rules ... take precedence over the General Rules" |
| https://www.hardrock.bet/fl/house-rules/ | 2026-10-19T23:06Z | WordPress wrapper; static HTML shows "Content loading…"; `data-doc-id="1LohHmj-8bnU9wnJO8yMsi6Ttvee_EZf3RWg4bfUul7s"`; JSON-LD dateModified 2025-12-26 |
| https://www.hardrock.bet/wp-content/cache/min/1/wp-content/themes/salient-child/footer-scripts/google-legal-scripts.js | 2026-10-19T23:07Z | Loader fetches `https://docs.google.com/document/d/${docId}/export?format=html` into `.legal-doc-content` |
| https://docs.google.com/document/d/1LohHmj-8bnU9wnJO8yMsi6Ttvee_EZf3RWg4bfUul7s/export?format=txt | 2026-10-19T23:07:18Z | Full Florida house rules text ("Seminole Gaming House Rules: Mobile and Online Sports Betting"); Parts A-D; all rule quotes above; no version/effective date in doc; no Last-Modified header |
| https://www.hardrock.bet/t-cs/ | 2026-10-19T23:05Z | T&Cs landing; links `/t-cs/florida`; "operated and controlled by Hard Rock Digital" (generic text) |
| https://www.hardrock.bet/t-cs/florida/ | 2026-10-19T23:07Z | Wrapper page; `data-doc-id="1TIC_NVrfOURrYrJhJYeNZFVRXtivwRn5tiktKtM8Xnw"`; Cloudflare blocks bare curl |
| https://docs.google.com/document/d/1TIC_NVrfOURrYrJhJYeNZFVRXtivwRn5tiktKtM8Xnw/export?format=txt | 2026-10-19T23:07:49Z | Florida Terms of Service; Seminole Tribe of Florida d/b/a Seminole Gaming; STGC/Compact; 21+; physical presence; GeoComply; §1.6 precedence; §19 Errors; "Effective September 8, 2026" |
| https://www.hardrock.bet/sportsbook/same-game-parlay/ | 2026-10-19T23:04Z and 23:08Z | "Updated: Dec 15, 2025 2:36 PM EST"; min 2 / max 20 bets; push leg removed and odds recalculated; cash out at discretion; no pricing-method statement |
| https://www.hardrock.bet/sportsbook/parlay/ | 2026-10-19T23:05Z | "Updated: Jul 30, 2026 5:02 PM EDT"; minimum two bets; pushed leg removed, odds recalculated; no max/payout cap stated; bets cannot be cancelled; Parlay Insurance example |
| https://www.hardrock.bet/sportsbook/push/ | 2026-10-19T23:05Z | "Updated: Sep 25, 2026 9:00 AM EDT"; push = leg "removed (voided)", odds recalculated; multiple pushes same; NBA cannot tie; example text/table inconsistency |
| https://www.hardrock.bet/news/introducing-same-game-parlay-max/ | 2026-10-19T23:05Z | "Updated: Jan 5, 2026 8:24 PM EST"; SGP Max up to 20 bets across app; play-by-play markets "can't be included in SGPs"; 21+ |
| https://www.hardrock.bet/florida/ | 2026-10-19T23:04Z | "Page updated: September 23, 2026"; "Offered by the Seminole Tribe of Florida in FL"; 21+; GeoComply on desktop; Bonus Bets expire 7 days, stake excluded; promos exclude Bonus Bets/Boosts/Round Robins/Early Cash Out; 1-833-PLAYWISE |
| https://www.hardrock.bet/sportsbook/player-injury-insurance/ | 2026-10-19T23:06Z | "Updated: Sep 23, 2026 10:43 AM EDT"; NBA period 10/1/2026-8/1/2027; 1st-half injury, no return; only losing leg; settles as loser + Bonus Bet refund within 48h; excludes unders, cash out, boosts, round robins; FL by Seminole Tribe |
| https://www.hardrock.bet/sportsbook/prop-bet/ | 2026-10-19T23:06Z | "Updated: Sep 25, 2026 9:01 AM EDT"; explainer only; no DNP/OT/minutes rules |
| https://www.hardrock.bet/help-center/ | 2026-10-19T23:05Z | Navigation only; no cash-out, void, or settlement articles found |
| https://www.hardrock.bet/nj/house-rules/ | 2026-10-19T23:06Z | Same "Content loading…" pattern (not read further; out of scope) |

Secondary (not relied on for findings): WebSearch results from sports.techopedia.com and sailgp.com describing Hard Rock Bet injury insurance and cash out; superseded by the official pages above.
