# Reviewer test account

The Anthropic Software Directory Policy (3.D) requires "a standard testing account with
sample data for Anthropic to verify full Software functionality." The connector
submission form asks for the credentials in its Test & launch step, where only reviewers
see them. The credentials are never written into this repository, the plugin bundle, or
any document.

## 1. Create the account (after the server is deployed)

1. Open `https://<host>/signup` in a private browser window.
2. Use an email address the owner controls and that is dedicated to this purpose (for
   example a plus-addressed alias of the owner's mailbox). Choose a strong password and
   store it in the owner's password manager.
3. Sign in once at `https://<host>/login` to confirm the account works, then complete
   onboarding through Claude by adding the connector in claude.ai with that account and
   calling `set_user_settings(confirm_onboarding=true)`. Keep the default $10 cap.

The owner's own account is a different user id; nothing below touches the owner's ledger
because every record is scoped to the signed-in account.

## 2. Load sample data without fixtures

The server refuses FIXTURE-mode records in any real ledger, so sample data is entered as
ordinary records on the test account, clearly labelled as samples in `notes`. Signed in
as the test account (through claude.ai, Claude Code, or MCP Inspector), run:

1. `get_system_status` and `check_data_coverage(<today>)`: no data needed.
2. `analyze_my_parlay` with three legs typed from the Hard Rock app for an upcoming slate
   (any three real markets with the odds as shown); this creates a candidate in
   `MANUAL_INPUT` mode.
3. `import_hardrock_quote` with the app's combined odds, `user_confirmed=true`.
4. `select_ticket(candidate_id, stake_usd="5.00")`.
5. `record_actual_bet` with `stake_usd="5.00"`, `source=USER_CONFIRMATION`,
   `notes="reviewer sample; not a real wager"` and idempotency key `sample-1`. Record a
   second external wager with `external=true`, `stake_usd="4.00"`, idempotency key
   `sample-2`, and a third one with `stake_usd="3.00"` and key `sample-3` so the reviewer
   sees `BUDGET_BREACH_RECORDED` on the ledger (5 + 4 + 3 = 12 > 10).
6. After the games finish, `reconcile_settlement` for each bet with `status` WON or LOST,
   `source=BOOK_CONFIRMED`, and the cash returned (for a sample, state the amounts the
   app would have shown and say so in `notes`).
7. `add_cost(date_local=<today>, description="sample data cost", amount_usd="1.00", category="DATA", idempotency_key="sample-cost-1")`.
8. `get_performance(<start>, <end>)` and `generate_30_day_review()` to confirm the sample
   ledger renders.

A server-side seeding command (`hrnba seed-test-account`) that performs steps 2 to 7
from a JSON file has been requested from the server module
(`docs/integration-notes/release.md`); until it exists, the manual procedure above is
the documented path.

## 3. Reviewer instructions to paste into the portal

Steps "detailed enough for a reviewer to connect to your server and run its tools":

1. In claude.ai, Customize > Connectors > Add custom connector, URL `https://<host>/mcp`,
   OAuth client "Use Claude's published identity", Sign in now. Enter the test-account
   credentials on the server's login page.
2. Ask: "Review today's NBA slate for a three-leg Hard Rock Florida parlay within my $10
   daily cap." Expect the slate, coverage, and either candidates or NO SUITABLE TICKET.
3. Ask: "Show my actual results, costs, and remaining daily budget." Expect the three
   sample tickets, the budget breach flag, the cost entry, and the remaining budget.
4. Ask: "Here is a ticket: [three legs with odds]. Verify the three selections and the
   combined payout of +650." Expect a candidate in the eight-block format with
   correlation flags and NEEDS BOOK QUOTE or the quote math.
5. Every tool can be invoked; none places a bet. `export_my_data` returns the sample
   records.

## 4. Hygiene

- Rotate the test-account password after review and when a reviewer's access period
  ends.
- The test account is not exempt from the credit guard; provider credits it consumes
  count against the server-wide key.
- Delete the sample records (account page > Delete account) if the account is retired.
