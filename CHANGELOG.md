# Changelog

Project-level changelog for hardrock-nba-parlay-mcp (server, CLI, docs, deployment). The
plugin bundle keeps its own `plugin/nba-three-leg-parlays/CHANGELOG.md`.

## 0.1.1 (2026-10-21)

- Self-hosted plugin: the bundle launches the server locally with uvx from the tagged GitHub release and asks installers for their own The Odds API key.
- The server creates a missing database folder on first start.
- Published to https://github.com/noel00604-debug/hardrock-nba-parlay-mcp (direct install route; not an Anthropic directory listing).

## 0.1.0 (unreleased, in build since 2026-10-19)

- Foundation: `schemas.py`, `config.py`, `db.py`, `errors.py`, `docs/ARCHITECTURE.md`.
- Research notes under `docs/research/` with source URLs and retrieval times.
- Release module: plugin bundle `plugin/nba-three-leg-parlays` (0.1.0 unreleased),
  marketplace manifest, `scripts/build_plugin_zip.py`, `scripts/stamp_release.py`,
  `deploy/` (Dockerfile, Railway, Fly, docker-compose, README), `docs/` publication and
  operations documents, `CLAUDE.md`, `.env.example`, this changelog.
- Not yet: deployment, directory submission, live-data verification, integrated tests
  (see `docs/launch-readiness.md`).
- Release review fixes, 2026-10-19 evening (`docs/integration-notes/review-release.md`
  D1 to D12): settlements only from what the user reports; official injury-report
  deadlines copied into the skill references; `stamp_release.py` refuses reserved
  top-level domains and placeholder GitHub names; documents updated for the real
  `hrnba` commands and `HRNBA_DATA_MODE`.
