# Privacy policy (draft for the owner's review)

This is a plain-language draft. It describes what the software does today. The owner
should review it, fill the contact line, publish it at an https URL, and stamp that URL
into the plugin manifest with `scripts/stamp_release.py --privacy-url`. It makes no claim
of compliance with any specific law; the owner decides whether legal review is needed.

Last updated: 2026-10-19 (draft, not yet published)

## Who operates this software

The NBA Three-Leg Parlay Analyst plugin and its connector server are operated by Noel
Fernandez, an individual. Contact: [OWNER TO FILL IN: email address or issue tracker URL].

## What the software is

A research tool for three-leg NBA parlays on Hard Rock Bet Florida. It does not place
bets, hold money, or connect to any sportsbook account.

## What we collect

When you create an account on the server:

- an email address and a password (stored only as an argon2id hash);
- a display name if you give one.

When you use the tools through Claude:

- the dates and games you ask about;
- the selections, odds, stakes, combined quotes, placement times, and ticket references
  you confirm in chat and ask the tool to analyse or record;
- settlement results and costs you report;
- your daily cap and display time zone;
- optionally, your own The Odds API key, stored encrypted with the server's key so that
  it can be used for your requests; it is never shown back to you or to anyone else;
- OAuth client registrations and tokens needed for Claude to call the server on your
  behalf;
- an audit log of record changes (what changed and when, with your account id);
- server logs with request paths, status codes, and timestamps. API keys and bearer
  tokens are redacted from logs.

## What we do not collect

- Your chat history, memories, conversation summaries, or files. The server receives
  only the structured fields Claude sends for the tool you invoked.
- Screenshots. If you share a bet-slip image in chat, Claude reads it in the chat; only
  the fields you confirm are sent as text.
- Hard Rock Bet credentials, payment details, or your location. The software never asks
  for them.

## Third parties that receive data

- The Odds API (The Odds API Pty Ltd, Australia): the server requests odds and scores
  for NBA games. The request contains the sport, bookmaker keys, market keys, and dates,
  plus the API key used; it does not contain your identity or your records.
- NBA official injury report PDFs (ak-static.cms.nba.com): fetched by the server as
  public files; no user data is sent.
- The hosting provider (Railway, or Fly.io with Neon, as documented in `deploy/README.md`)
  stores the database and backups on the owner's behalf.
- Anthropic: the connector is called from Anthropic's infrastructure when you use Claude.
  Anthropic's handling of your Claude conversations is governed by Anthropic's own terms
  and privacy policy, not by this document.

We do not sell data, share it with advertisers, or build profiles.

## Retention

Your records stay until you delete them. Database backups are kept by the hosting
provider for their retention period (on Railway: daily backups for 6 days, weekly for 27
days) and then expire. Server logs are rotated by the hosting provider. Fixture and test
data are never written to a user's ledger.

## Your choices

- Export: the `export_my_data` tool, or the Export button on the server's account page.
- Delete: the Delete account button on the server's account page (confirmation required);
  this removes your account, settings, encrypted provider key, tokens, and all records.
  Deletion is not available as an MCP tool, by design, so that a mistaken tool call
  cannot erase your history.
- Revoke access: remove the connector in Claude or sign out; tokens can also be revoked
  on the server.

## Security

Connections use HTTPS with certificates issued by the hosting platform. Sign-in uses
OAuth 2.0 with PKCE. Passwords are hashed with argon2id. Per-user provider keys are
encrypted at rest. Each query and mutation is scoped to the signed-in account; one
account cannot read, change, infer, or export another account's records. Report security
problems to the contact above.

## Age

The software is for adults. Sports betting in Florida requires you to be 21 or older and
physically in Florida; the software is not intended for anyone under 18 and does not
knowingly collect data from minors.

## Changes

Changes to this policy are recorded in the project changelog with the date. Continued
use after a change means you accept the updated policy.
