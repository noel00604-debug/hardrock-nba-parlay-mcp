# Support

Contact for product and security concerns: [OWNER TO FILL IN before submission: an email
address the owner reads, or the public GitHub Issues URL once the repository is public].
This contact is also the `supportUrl` stamped into the plugin manifest and the security
vulnerability reporting channel required by the Anthropic Software Directory Terms.

## How to report a problem

Include:

- which surface you used (claude.ai, Claude Desktop, Cowork, Claude Code) and, for Claude
  Code, the version from `claude --version`;
- the tool name and the reason codes in the response (for example `QUOTE_STALE`,
  `UNAUTHENTICATED`);
- the America/New_York date and approximate time;
- the candidate id or bet id, if any.

Do not include your password, your The Odds API key, or receipts showing sportsbook
account numbers. The server never needs them and the maintainer will not ask for them.

## What to expect

A single maintainer runs this project. There is no service-level agreement. Reports are
read and answered as time allows; security reports are prioritised. Fixes ship as new
plugin versions (raise of `version` in `plugin.json`) and server deployments.

## Known limitations (2026-10-19)

- No public endpoint or repository yet; see `docs/publication-readiness.md`.
- Same-game parlay joint probabilities are reported as unknown; there is no validated
  model.
- Player-prop settlement is user-reported from the Hard Rock app; automatic provisional
  settlement covers team legs only.
- Which player-prop markets `hardrockbet_fl` returns through The Odds API is unverified
  until a live probe runs with a real key.
