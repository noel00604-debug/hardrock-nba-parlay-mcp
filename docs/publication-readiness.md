# Publication readiness: Anthropic directory and Usage Policy

Status on 2026-10-19 (evening ET): NOT SUBMITTED. Not yet READY TO SUBMIT. The package
validates locally, but the hosted server has no public URL, the repository is not on
GitHub, and the owner items in section 7 are open. Nothing in this file is Anthropic's
approval; a local validator pass is not directory approval, and "Approved" in the portal
is not "Published".

All policy text below is quoted from `docs/research/anthropic-policies.md` and
`docs/research/claude-directory-connectors.md` (pages retrieved 2026-10-19 between
23:03 and 23:07 UTC). Interpretations are marked as such.

## 1. Policies and their printed dates

| Document | URL | Date printed on the page | Applies |
|---|---|---|---|
| Anthropic Software Directory Policy | https://support.claude.com/en/articles/13145358-anthropic-software-directory-policy | April 15, 2026 | to both submissions (plugin bundle and MCP connector) |
| Anthropic Software Directory Terms | https://support.claude.com/en/articles/13145338-anthropic-software-directory-terms | March 16, 2026 | agreed to at submission |
| Usage Policy, previous version | https://www.anthropic.com/legal/archive/22742366-2ef0-4c7a-a833-6523f10d3944 | Effective September 15, 2025 | in force 2026-10-19 through 2026-11-11 |
| Usage Policy, canonical URL | https://www.anthropic.com/legal/aup | Effective November 12, 2026 | in force from 2026-11-12, inside the 30-day review window |
| 2026 Usage Policy update announcement | https://www.anthropic.com/news/2026-usage-policy-update | Oct 8, 2026 | "The updated policy takes effect on November 12." |

Action: re-read https://www.anthropic.com/legal/aup on or after 2026-11-12 and update
this file. Whether directory reviewers apply the November text before that date is
unknown (the new text already sits at the canonical URL).

## 2. Financial transactions: Directory Policy section 4.A

Verbatim: "Unless otherwise expressly permitted by us in writing, we do not allow
Software with certain capabilities into our Directories. We may revisit these
restrictions as our Directories and Anthropic Services evolve." and
"A. Software that transfers money, cryptocurrency, or other financial assets, or
executes financial transactions on behalf of users."

How the product relates (fact): no tool places a bet, cashes out, deposits, withdraws,
or transfers anything. The twenty tools in `docs/ARCHITECTURE.md` section 6 read data,
create research records, reserve an application-level budget figure, and append
user-reported wager and settlement records. The user places every wager in the Hard
Rock app. This is stated in the plugin description, README, and skill.

Interpretation: the manual-placement design keeps the product outside the wording of
4.A. No clause mentions research or recommendations about wagers. No document reviewed
mentions gambling, betting, wagering, sportsbooks, odds, or parlays at all; silence is
not approval.

## 3. High-risk Finance classification: UNRESOLVED

Both Usage Policy versions impose two requirements on High-risk use cases: review by a
qualified professional or person before delivery, and disclosure that AI was used.

Usage Policy effective September 15, 2025, Finance definition, verbatim:
"Finance: Use cases related to financial decisions, including investment advice, loan
approvals, and determining financial eligibility or creditworthiness"

Usage Policy effective November 12, 2026, Finance definition, verbatim:
"Finance: a personalized recommendation to buy, sell, hold, or allocate among specific
investment products, such as securities, funds, digital assets, or annuities; advising
an individual on their own taxes, such as what to report, deduct, or claim; or preparing
a tax return for them to sign or file."

(The policy text has a dash after "Finance"; it is rendered here as a colon because this repository's documents avoid dashes.)

November 12, 2026 Exclusions, verbatim in part: the requirements do not apply to
"General information or educational content ... without applying it to the individual's
circumstances", "Internal drafting, research, summarization, or analysis that is not the
ultimate High-risk AI Recommendation delivered", and "Carrying out a decision a person
has already made, or applying a fixed rule, formula, or algorithm where the model
exercises no judgment about the individual."

Facts: neither version says whether a sports wager is a "financial decision" or an
"investment product"; neither says whether the user receiving a recommendation about
their own money can be the qualified reviewer. Recorded as UNRESOLVED. Manual placement
and the $10 cap do not settle the classification and are not claimed to.

What the build does regardless (fact):

- AI-involvement disclosure at the start of every session and under every candidate
  (section 6 below).
- Sourced facts, fixed-formula calculations (odds conversion, no-vig, payout, budget
  ledger) and the user's explicit selection step are separated from any "selected
  ticket" step; the selection is a user action (`select_ticket`), not a tool decision.
- No "lock", "guaranteed", "risk-free", "safe", no invented win rates, no loss-recovery
  prompts, no automatic stake increases.
- Plan: ask the classification question in the directory submission notes and record
  Anthropic's answer here. Do not assert either answer in public materials.

## 4. Directory Policy section 3 (developer requirements) and section 5 (MCP servers)

Status legend: DONE (in this repository), TODO (owner) (needs an account, purchase,
URL, or person), PENDING INTEGRATION TEST (code exists or is being built by another
module; must be exercised against the live server before submission).

| Clause | Requirement (summary of verbatim text) | Status | Where |
|---|---|---|---|
| 3.A | privacy policy link covering collection, usage, retention when software collects data or connects to a remote service | DONE (draft) / TODO (owner): publish at an https URL and stamp `privacyPolicyUrl` | `docs/privacy-policy.md`; `scripts/stamp_release.py --privacy-url` |
| 3.B | verified contact information and support channels for product or security concerns | TODO (owner): choose the contact; fill `docs/support.md`; stamp `supportUrl` | `docs/support.md` |
| 3.C | documentation of how the software works, purpose, troubleshooting | DONE (draft) / TODO (owner): publish at an https URL (a public repo README qualifies as "a help-center article or blog post" level documentation only if public) | `README.md`, `plugin/.../README.md`, `docs/install.md`, skill references |
| 3.D | a standard testing account with sample data for Anthropic | TODO (owner) after deployment; procedure written | `docs/test-account.md` |
| 3.E | at least three working examples of prompts or use cases | DONE (written) / PENDING INTEGRATION TEST (must be run against the live server) | `docs/use-cases.md` |
| 3.F | verify ownership or control of every API endpoint, domain, UI, and external resource the software connects to; plugins may connect to any approved Connector | TODO (owner): the server domain is the owner's hosting hostname; The Odds API and the NBA injury PDFs are third-party data sources the server reads (declare in the connector Data handling step as proxied or third-party data) | this file; connector submission |
| 3.G | maintain the software and address issues within reasonable timeframes | TODO (owner): commitment; support channel | `docs/support.md` |
| 3.H | agree to the Directory Terms and follow published design guidelines | TODO (owner): agree at submission; the design guidelines referenced in 3.H were not located in research | portal |
| 5.A | graceful errors with helpful feedback | PENDING INTEGRATION TEST: `ToolError` with reason codes, no stack traces | `errors.py`, `mcp_server.py` (server module) |
| 5.B | token frugality; options to exclude unnecessary text | PENDING INTEGRATION TEST: bounded responses, `max_candidates`, `include_props` | server module |
| 5.C | tool names 64 characters or fewer | DONE: longest is `check_parlay_correlation` (24), then `build_three_leg_parlays` (23) and `generate_30_day_review` (22) | `ARCHITECTURE.md` section 6 |
| 5.D | OAuth 2.0 with certificates from recognised authorities for remote servers requiring auth | PENDING INTEGRATION TEST: built-in OAuth AS (DCR, PKCE S256); platform TLS | `auth.py`, `web.py`; `deploy/README.md` section 4 |
| 5.E | annotations: readOnlyHint, destructiveHint, title on every tool | PENDING INTEGRATION TEST: annotations table exists in the contract | `ARCHITECTURE.md` section 6 |
| 5.F | Streamable HTTP transport | PENDING INTEGRATION TEST: `/mcp` Streamable HTTP | server module |
| 5.G | local servers built with current dependencies | not applicable (remote server); dependencies pinned in `uv.lock` | `docs/sources.md` |

Other clauses:

| Clause | Requirement | Status |
|---|---|---|
| 1.A | comply with the Usage Policy, including High-Risk requirements | see section 3; UNRESOLVED classification |
| 1.C, 1.D | protect privacy; collect only data needed; no extraneous conversation data, even for logging | DONE by design: the server receives structured fields only; logs are redacted; no chat text is sent (skill section 10, README) |
| 1.F | must not query or extract data from Claude's memory, chat history, conversation summaries, or user-generated or uploaded files | DONE for the server (it never receives files). OPEN QUESTION: whether in-chat extraction from a user-supplied screenshot, confirmed by the user, falls under 1.F; the image never reaches the server. Ask during review. |
| 2.B | descriptions must precisely match functionality | DONE: plugin description, skill description, tool table match the contract; must be re-checked against the implemented tools before submission |
| 2.F, 2.G | no dynamic external behavioural instructions; no hidden or encoded instructions | DONE: the skill and references are plain Markdown; no fetched instructions |
| Terms | mechanism for receiving security vulnerability reports | TODO (owner): the support channel in `docs/support.md` doubles as the security contact |
| Terms | no statement suggesting partnership, sponsorship, or endorsement by Anthropic | DONE: README and skill state the opposite |
| Terms (iv) | provide and adhere to a privacy policy; provide third-party policies | TODO (owner): link The Odds API terms and the hosting provider's privacy policy from the published privacy policy |

## 5. Plugin-bundle checklist items (pre-submission checklist page)

| Item | Status |
|---|---|
| `.claude-plugin/plugin.json` present with name, description, author, version | DONE |
| README at least 40 words, code blocks excluded | DONE (see the word count in the release report) |
| LICENSE file or `license` field | DONE (both) |
| `.mcp.json` valid; remote server has `type: http` and an absolute `https://` URL, or `""` when no fixed endpoint | DONE with `""`; TODO (owner): stamp the real URL before submission |
| no secrets anywhere; no `.DS_Store`, `__MACOSX`; no `bin/`; no lockfile in the plugin folder; files under 256 KiB; fewer than 512 files | DONE; enforced by `scripts/build_plugin_zip.py` |
| name rules (lowercase, digits, hyphens, 64 chars, not reserved, not another org's) | DONE locally; collision check happens in the portal |
| `claude plugin validate` | run on Claude Code 2.1.123 (no `--strict`, no `.mcp.json` checks): it reports `root: Unrecognized key: "displayName"` and fails, because that build predates the `displayName` field documented in the current manifest reference and read by the directory; a copy without `displayName` passes on 2.1.123, and the same build loads the bundle (`claude --plugin-dir ... plugin list` shows `Status: loaded`). `displayName` is kept as the brief requires. Re-run on 2.1.281 or later before submitting, and run it again after `scripts/stamp_release.py` has written the real URL: from 2.1.281 the validator also checks `.mcp.json` and reports a remote `url` that is not a valid absolute URL, and whether it accepts the documented `""` placeholder was not tested; the marketplace manifest passes on 2.1.123 |
| public GitHub repository, GitHub account connected on claude.ai | TODO (owner) |
| Data handling answers (reads or stores personal data: yes; sends data to services other than declared connectors: the server calls The Odds API and nba.com; retention: until the user deletes; intended for under 18: no) | TODO (owner), drafted here |
| four plugin acknowledgements; contact email | TODO (owner) |

## 6. AI disclosure: where it is implemented

| Surface | Text location | Status |
|---|---|---|
| Session start | `plugin/nba-three-leg-parlays/skills/nba-three-leg-parlays/SKILL.md` section 1 and section 5 step 3 | DONE (skill instruction) |
| Every candidate | SKILL.md section 7 block 1 (header includes the disclosure line) | DONE (skill instruction) |
| Listing text | plugin README "AI involvement" section; project README | DONE |
| Tool responses | `schemas.AI_DISCLOSURE` attached as `ai_disclosure` on `SystemStatus`, `BuildResponse`, and `Candidate` (ARCHITECTURE section 11) | PENDING INTEGRATION TEST (foundation and server modules) |
| Server instructions | `MCPServer(instructions=...)` repeats the disclosure so clients without the skill see it (ARCHITECTURE section 11) | PENDING INTEGRATION TEST (server module) |

The disclosure names the tool, says the output is research and not a prediction or
financial advice, and says the user decides and places any wager. Neither policy
requires naming Anthropic, Claude, or the model.

## 6a. NBA Terms of Use and the injury report: UNRESOLVED

The server fetches the official NBA injury report PDFs (published by the league at
`ak-static.cms.nba.com/referee/injury/...`, linked from official.nba.com) automatically
(`injury_auto_fetch`, default on), with manual entry always available. The NBA Terms of
Use (nba.com/termsofuse, "LAST UPDATED: July 13, 2026", quoted in
`docs/research/stats-results-reference.md`) restrict "NBA Statistics": "(iv) the NBA
Statistics may not be used in connection with any gambling activity (including legal
gambling activity)" and "(v) ... any fantasy game or other commercial product or
service". Whether a participation-status report is "NBA Statistics" under that section,
and whether reading a public PDF for a research tool whose users wager is "use in
connection with gambling activity", was not researched and is not decided here. The
build does not use stats.nba.com or cdn.nba.com statistics at all. Recorded as an open
question for the public listing (Directory Terms warranty (ii): the software's ordinary
use must comply with applicable laws and third-party terms). Options if it must be
resolved against automatic fetching: default `HRNBA_INJURY_AUTO_FETCH=false` for the
public deployment and rely on manual injury entry, or obtain written permission.

## 7. What remains for the owner before READY TO SUBMIT

1. Public GitHub repository holding this project (the plugin folder at
   `plugin/nba-three-leg-parlays`, the marketplace manifest at the root); GitHub
   connected on claude.ai; secrets, receipts, and databases excluded (see `.gitignore`).
2. A stable HTTPS server URL (Railway primary; `deploy/README.md`), then
   `scripts/stamp_release.py` with `--server-url`, `--repo-url`, and the three listing
   URLs; commit; raise `version` for every later release.
3. Support contact (an email address or a public issue tracker) in `docs/support.md`
   and `supportUrl`. Not invented here; the owner chooses it.
4. Privacy policy and terms published at https URLs (drafts in `docs/privacy-policy.md`
   and `docs/terms.md`, reviewed by the owner).
5. A reviewer test account with sample data on the hosted server (`docs/test-account.md`),
   credentials entered only in the portal's Test & launch step.
6. Three working use cases verified against the live server (`docs/use-cases.md`).
7. Connector submission first (server URL; the portal syncs the tools and flags missing
   titles or annotations; seven acknowledgements), then the plugin bundle submission
   (repository; four acknowledgements), both from the same Max account, paired.
8. The High-risk Finance classification question raised in the submission notes.
9. Re-read the Usage Policy on 2026-11-12.
10. Decide the NBA Terms of Use question in section 6a (keep automatic injury fetching,
    switch the public deployment to manual entry, or seek permission).

## 8. Submission states (from the directory documentation)

Draft, Scanning, Needs changes, In review, Approved, Published, Not live yet, Delisted,
Withdrawn. "Approved doesn't mean people can install the plugin. A plugin is installable
only once its status is Published." Review time is not fixed. This project reports
PUBLISHED only after the public listing and an installation from it have been verified.
