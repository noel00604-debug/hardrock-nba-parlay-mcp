# NBA Three-Leg Parlay Analyst

A Claude plugin for researching exactly three-leg NBA parlays on Hard Rock Bet Florida.
It bundles one skill and one remote MCP connector (`nba-three-leg-parlays`). The
connector reads current Hard Rock Florida odds and official NBA injury reports, checks
the three legs for correlation and freshness, accepts the combined quote you read from
the Hard Rock app, keeps a daily budget ledger (default $10 per America/New_York day),
and tracks the wagers you confirm you placed so you can review results after 30 days.

Author: Noel Fernandez. License: MIT. Version 0.1.0 (unreleased).

## What it does

- Lists the day's NBA games with start times in Eastern Time and source timestamps.
- Reports which Hard Rock Florida markets are covered today and which are not.
- Builds up to three candidate three-leg tickets (one primary, two alternatives) or
  answers NO SUITABLE TICKET when prices, coverage, or injury information are inadequate.
- Flags correlated legs and never multiplies same-game probabilities together.
- Reviews a ticket you built yourself, including a bet-slip screenshot whose fields you
  confirm in chat.
- Refreshes a ticket right before you decide, and expires it when a game has started,
  a price went stale, or an injury designation changed.
- Reserves budget for the ticket you select, records the wager you confirm you placed,
  records the book's settlement, and reports stakes, returns, profit or loss, costs, and
  remaining daily budget.

## What it never does

- It never places a bet, cashes out, deposits, withdraws, or moves money of any kind.
- It never logs into Hard Rock Bet, never asks for your Hard Rock password, payment
  details, or location, and never automates a sportsbook session.
- It never calls a ticket a lock, guaranteed, risk-free, or safe, and never reports a
  win rate that was not computed from your own settled tickets.
- It never raises your daily cap on its own.

## What data it sends, and where

The skill runs inside Claude. When you use a tool, Claude sends only structured fields
to the connector's server: the date you asked about, the three selections and odds you
confirmed, a stake amount, a combined quote you confirmed, and settlement results you
report. Screenshots stay in the chat; Claude extracts the fields, you confirm them, and
only the confirmed fields are sent. No chat history, memories, or other attachments are
sent.

The server is hosted by the plugin author. It calls The Odds API (for Hard Rock Florida
and reference prices and NBA scores) and reads the official NBA injury report PDFs. Your
records (candidates, reservations, bets, settlements, costs) are stored under your own
server account and are not visible to other users. You can export or delete them from the
server's account page. See the project's privacy policy document for retention details.

## AI involvement

Every analysis is produced with AI assistance (Claude plus the connector). It is
research, not a prediction and not financial advice. You make every decision and place
every wager yourself. The analysis is not endorsed by the NBA, Hard Rock Bet, or
Anthropic.

## Responsible gambling

Sports betting in Florida is for people 21 and older who are physically in Florida. If
gambling is a problem for you or someone you know, call 1-833-PLAYWISE (the number
published on the Hard Rock Bet Florida page). Set a cap you can afford to lose; the
default is $10 per day and the tool never increases it for you.

## Requirements

- Your own Claude account on a paid plan (Pro, Max, Team, or Enterprise) with plugins
  enabled. Using this plugin does not give you access to the author's Claude account.
- Your own account on the connector's server, created on its sign-up page the first time
  you connect. Each account has its own budget, records, and (optionally) its own
  The Odds API key.
- Installing the plugin does not sign you in to anything. The connector must show
  Connected before prices, injuries, or your ledger are available.

## Install

Three routes exist. Only the first two can be used before the directory listing is
published.

### (a) Direct install from the GitHub marketplace (Claude Code)

Add the marketplace from the GitHub repository `OWNER/REPO`, then install the plugin:

```
claude plugin marketplace add OWNER/REPO
claude plugin install nba-three-leg-parlays@hardrock-nba-parlay-marketplace
```

Then open a session and run `/mcp`, choose `plugin:nba-three-leg-parlays:nba-three-leg-parlays`,
and sign in through the browser. This is a direct install; it is not an Anthropic-reviewed
directory listing.

### (b) Upload the ZIP to claude.ai

Build or download `nba-three-leg-parlays-<version>.zip`, then in claude.ai go to
Customize > Plugins > Add > Upload plugin and select the file. Open the plugin's
Connectors tab, add the `nba-three-leg-parlays` connector, and sign in. The uploaded
plugin lives on your own account and is not reviewed by Anthropic.

### (c) Anthropic directory

Status: not yet submitted. When a listing is published it will appear under Customize >
Plugins > Discover. Until then, this route does not exist.

## Using it

Ask Claude, for example:

- "Review today's NBA slate for a three-leg Hard Rock Florida parlay within my $10 daily cap."
- "Here is my Hard Rock bet-slip screenshot. Verify the three selections and combined payout."
- "I placed this exact ticket for $10 at these accepted odds. Record it."

The skill explains its output format, the freshness rules (odds older than 180 seconds
are stale), and the budget rules. Detailed methodology, Hard Rock Florida house rules,
workflow maps, and settlement notes are in `skills/nba-three-leg-parlays/references/`.

## Support

Report problems through the support channel listed in the project's `docs/support.md`
(the owner will fill in the contact before publication). Security reports are welcome
through the same channel.
