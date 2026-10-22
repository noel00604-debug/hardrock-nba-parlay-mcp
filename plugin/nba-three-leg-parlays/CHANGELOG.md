# Changelog

All notable changes to the nba-three-leg-parlays plugin bundle are recorded here.

## 0.1.1 (2026-10-21)

- Self-hosted plugin: the bundle launches the server locally with uvx from the tagged GitHub release and asks installers for their own The Odds API key.
- The server creates a missing database folder on first start.
- Published to https://github.com/noel00604-debug/hardrock-nba-parlay-mcp (direct install route; not an Anthropic directory listing).

## 0.1.0 (unreleased)

Initial bundle. Not yet published to any marketplace or to the Anthropic directory.

- Plugin manifest at `.claude-plugin/plugin.json` (name `nba-three-leg-parlays`, display name "NBA Three-Leg Parlay Analyst").
- `.mcp.json` with one remote HTTP server entry, `nba-three-leg-parlays`. The `url` is empty until a stable HTTPS endpoint exists; `scripts/stamp_release.py` in the project repository fills it.
- Skill `skills/nba-three-leg-parlays/SKILL.md` covering the seven day-one prompts, the exact tool sequence, the three-leg output format, freshness rules, correlation limits, the daily budget rules, candidate states, screenshot handling, and language rules.
- References: `methodology.md`, `hard-rock-rules.md`, `workflows.md`, `settlement-and-review.md`.
- README with data-handling, AI-involvement, and responsible-gambling notes.
- MIT license.
