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

The server runs on your own computer (Claude Code starts it for you). It calls The Odds
API with your own key (for Hard Rock Florida and reference prices and NBA scores) and reads
the official NBA injury report PDFs. Your records (candidates, reservations, bets,
settlements, costs) are stored in a local file under your home folder and never leave your
machine. Delete that file to delete everything. See the project's privacy policy document
for details.

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

- Your own Claude account on a paid plan with plugins enabled, and Claude Code on your
  computer. This is a self-hosted plugin: the server runs on your own machine, so it works
  in Claude Code (and in Cowork sessions that run locally). It does not work in claude.ai
  chat, Claude Desktop, or on a phone until a hosted server exists.
- The `uv` tool (https://docs.astral.sh/uv/), which downloads Python and the server on
  first use. Nothing else to install.
- Your own free The Odds API key from https://the-odds-api.com (the Starter plan, 500
  credits a month, is enough for a few games a day). Claude Code asks for it when the
  plugin is installed and passes it only to the local server. Without a key the tool
  still works in manual mode: you type the prices from the Hard Rock app.

Your records stay in a file on your computer (`~/.hardrock-nba-parlay/local.db`). Nothing
is sent to the plugin author.

## Install

### (a) Direct install from the GitHub marketplace (Claude Code)

```
claude plugin marketplace add noel00604-debug/hardrock-nba-parlay-mcp
claude plugin install nba-three-leg-parlays@hardrock-nba-parlay-marketplace
```

Claude Code prompts for your Odds API key (optional) and starts the local server for you.
This is a direct install; it is not an Anthropic-reviewed directory listing.

### (b) Run the server yourself

Clone `https://github.com/noel00604-debug/hardrock-nba-parlay-mcp`, then follow `docs/day-one-runbook.md` in the
repository. The server registers with `claude mcp add` and the skill loads from
`~/.claude/skills`.

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

Report problems on the project's issue tracker: https://github.com/noel00604-debug/hardrock-nba-parlay-mcp/issues. Security reports are
welcome there too: open an issue titled "Security" without the details and the maintainer
will reply with a private channel.
