# Day one runbook (Tuesday 2026-10-20)

Earliest tip is 3:00 PM ET (Celtics at Pistons), then 7:00 PM (76ers at Knicks) and 9:30 PM (Thunder at
Spurs). Do the steps below in the morning. Every command is one line; nothing here places a bet.

## 1. Get a free The Odds API key (owner, in the browser)

Sign up at https://the-odds-api.com/ (Starter plan: free, 500 credits per month). Opening night costs
roughly 20 credits for odds, props and reference prices across the three games; a full month of daily use
does not fit the free plan (see docs/costs.md for the $30 per month 20K plan).

## 2. Store the key on this Mac (it is never typed into chat)

The command prompts for the key and stores it in the macOS keychain:

```bash
/opt/homebrew/bin/uv run --directory /Users/noelfernandez/hardrock-nba-parlay-mcp hrnba secret set ODDS_API_KEY
```

Confirm it resolves (prints only yes or no, never the value):

```bash
/opt/homebrew/bin/uv run --directory /Users/noelfernandez/hardrock-nba-parlay-mcp hrnba secret check ODDS_API_KEY
```

## 3. Check status and coverage (spends about 6 credits with the props probe)

```bash
/opt/homebrew/bin/uv run --directory /Users/noelfernandez/hardrock-nba-parlay-mcp hrnba status
```

```bash
/opt/homebrew/bin/uv run --directory /Users/noelfernandez/hardrock-nba-parlay-mcp hrnba coverage --date 2026-10-20 --probe-props
```

The coverage report says, per market, whether Hard Rock Florida prices came back, whether Pinnacle reference
prices paired with them within the 60-second skew rule, and whether the injury report was fetched.

## 3a. If the coverage report says Hard Rock Florida is BLOCKED

On the evening of 2026-10-19 the feed had no Hard Rock Florida NBA markets for opening night (it does carry
Hard Rock Florida for the NFL, so the key and plan are fine). If that is still true in the morning, use the
manual path: open the Hard Rock Bet app, read the exact prices of the legs you are considering, and give them
to Claude ("analyze my parlay: DET +3.5 at -110, PHI/NYK over 224.5 at -110, OKC ML at -150, from
Hard Rock Florida"). The tool then applies the live Pinnacle references, the official injury report, the
correlation checks and the budget rules to your typed legs. A bet-slip screenshot works the same way after you
confirm the fields Claude reads from it.

## 4. Build candidates (about 15 credits)

```bash
/opt/homebrew/bin/uv run --directory /Users/noelfernandez/hardrock-nba-parlay-mcp hrnba build --date 2026-10-20
```

## 5. Use it inside Claude Code

The MCP server `nba-three-leg-parlays` is already registered in your user config (stdio, local SQLite
ledger under ~/.hardrock-nba-parlay/local.db) and the skill is linked at ~/.claude/skills/nba-three-leg-parlays.
Open Claude Code and ask, for example:

- Review today's NBA slate for a three-leg Hard Rock Florida parlay within my $10 daily cap.
- Give me one primary candidate and explain the weakest leg.
- Here is my Hard Rock bet-slip screenshot. Verify the three selections and combined payout.
- Refresh this ticket using current injuries and prices before I decide.
- I placed this exact ticket for $10 at these accepted odds. Record it.
- Show my actual results, costs, and remaining daily budget.

Claude will ask you to confirm the combined quote shown on your slip, reserve the stake, and record the bet
only after you say you placed it.

## 6. After the games

Report the settlement as the Hard Rock app shows it (won, lost, void, cash out, with the cash returned), and
ask for performance. Provisional results never overwrite the app's confirmed settlement.

## Removing what was configured tonight

```bash
claude mcp remove nba-three-leg-parlays -s user
```

```bash
rm /Users/noelfernandez/.claude/skills/nba-three-leg-parlays
```
