# ARCHITECTURE.md: shared interface contract (v0.1)

This file is the contract that every module is coded against. `schemas.py`, `config.py`, and
`db.py` are the foundation and are frozen while modules are built in parallel. If a module needs a
change to the foundation, it must NOT edit those files; it writes the request to
`docs/integration-notes/<module>.md` and works around it locally. The integration lead applies
foundation changes.

## 0. Ground rules

- Python 3.12, `uv`-managed project, package `hardrock_nba_parlay` under `src/`. Tests with
  `pytest`. Lint with `ruff`. Type hints everywhere; `pydantic` v2 models in `schemas.py`.
- `Decimal` for every odds, probability, and money value. Never `float` for those. Money is USD.
  In the database: money is stored as integer cents (`*_cents` columns), odds and probabilities as
  decimal strings (TEXT). Conversions live in `db.py` helpers `cents(Decimal)`, `from_cents(int)`,
  `dec(str)`.
- Time: Python objects are tz-aware `datetime` in UTC. The ONLY clock is `config.Clock.now_utc()`
  (injectable in tests). Database stores ISO-8601 UTC strings ending in `Z`. Local dates are
  `YYYY-MM-DD` strings in `America/New_York` ("ET") computed with `config.local_date(dt_utc)`.
  Display helpers render ET with offset, e.g. `2026-10-20T19:30:00-04:00`.
- Secrets: never logged, never returned by tools, never in URLs that get logged. Use
  `config.redact(text)` on anything that may contain a key. HTTP client logs must strip `apiKey`.
- Data mode is always visible: every response that carries market data includes `data_mode`
  (`LIVE_PROVIDER`, `MANUAL_INPUT`, or `FIXTURE`) and source timestamps.
- Tests never hit the network. Offline fixtures live in `tests/fixtures/` and carry
  `"data_mode": "FIXTURE"`. Fixture records are never written to a real ledger: `db.Database`
  refuses to store a bet whose `data_mode == FIXTURE` unless the database itself was opened with
  `allow_fixture_ledger=True` (tests only).
- Tenant scoping: every ledger table has `user_id`. Every query and mutation filters by the
  `user_id` from `RequestContext`, which is derived from verified auth (hosted) or from
  `settings.local_user_id` (stdio/CLI). A `user_id` is NEVER accepted as a tool argument.
- No tool places bets, moves money, runs shell commands, or runs arbitrary SQL.
- Reason codes (section 7) are the vocabulary for every rejection, null, and warning.

## 1. Module ownership for the parallel build

| Owner | Files (exclusive) | Depends on |
|---|---|---|
| foundation (lead) | `schemas.py`, `config.py`, `db.py`, `pyproject.toml` | none |
| quant | `probabilities.py`, `correlation.py`, `tests/test_probabilities.py`, `tests/test_correlation.py` | foundation |
| data | `providers/base.py`, `providers/odds_api.py`, `providers/manual.py`, `providers/fixtures.py`, `providers/nba_injury_report.py`, `normalization.py`, `freshness.py`, `injury_context.py`, `tests/test_providers.py`, `tests/test_normalization.py`, `tests/test_freshness.py`, `tests/fixtures/*` | foundation |
| ledger | `budget.py`, `actual_bets.py`, `settlement.py`, `reports.py`, `tests/test_budget.py`, `tests/test_actual_bets.py`, `tests/test_settlement.py`, `tests/test_reports.py` | foundation |
| pipeline | `candidate_builder.py`, `quote_review.py`, `services.py`, `tests/test_candidate_builder.py`, `tests/test_quote_review.py`, `tests/test_services.py` | foundation + the signatures in this file for quant/data/ledger |
| server | `mcp_server.py`, `auth.py`, `web.py`, `cli.py`, `dashboard.py`, `tests/test_mcp_server.py`, `tests/test_auth.py`, `tests/test_cli.py` | foundation + `services.py` signatures |
| release | `plugin/**`, `deploy/**`, `README.md`, `LICENSE`, `CHANGELOG.md`, `CLAUDE.md`, `.env.example`, `docs/*.md` (except this file and research notes) | everything, by contract |

A module may import any other module's PUBLIC names listed in this contract. Until the other module
exists, tests for a module must not import it; use the schemas and fakes.

## 2. `config.py`

```python
class Settings(BaseSettings):            # env prefix HRNBA_, also reads ~/.hardrock-nba-parlay/.env (0600) and ./.env
    app_name: str = "hardrock-nba-parlay-mcp"
    version: str                          # read from package metadata
    database_url: str                     # default sqlite:////Users/<me>/.hardrock-nba-parlay/local.db
    data_dir: Path                        # default ~/.hardrock-nba-parlay
    display_tz: str = "America/New_York"
    local_user_id: str = "local-owner"    # used only when auth_mode == "none" (stdio / CLI)
    auth_mode: Literal["none", "builtin_oauth", "external_jwt"] = "none"
    public_url: str | None = None         # https base URL of the hosted server (issuer + resource)
    secret_key: SecretStr | None = None   # session/cookie signing + Fernet key derivation (hosted)
    odds_api_key: SecretStr | None = None # server-wide key; per-user keys override (hosted)
    odds_api_base_url: str = "https://api.the-odds-api.com/v4"
    target_book: str = "hardrockbet_fl"
    target_jurisdiction: str = "US-FL"
    reference_books: list[str] = ["pinnacle"]              # sharp benchmark for team markets
    prop_reference_books: list[str] = ["pinnacle", "draftkings", "fanduel"]  # documented fallback benchmark for props
    daily_cap_usd_default: Decimal = Decimal("10.00")
    max_odds_age_seconds: int = 180
    max_reference_skew_seconds: int = 60
    injury_report_max_age_seconds: int = 6 * 3600
    reservation_ttl_seconds: int = 2 * 3600
    http_timeout_seconds: float = 15.0
    http_max_retries: int = 3
    provider_cache_ttl_seconds: int = 60
    daily_provider_credit_budget: int = 200   # app-level guard against runaway credit use
    review_window_start: date = date(2026, 10, 20)
    review_window_end: date = date(2026, 11, 18)
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"

def get_settings() -> Settings
def local_date(dt_utc: datetime, tz: str = "America/New_York") -> str          # 'YYYY-MM-DD'
def local_day_bounds_utc(date_local: str, tz: str = ...) -> tuple[datetime, datetime]
def to_display(dt_utc: datetime, tz: str = ...) -> str                          # ISO with offset
def redact(text: str) -> str                                                    # masks apiKey=..., Bearer ..., known secrets
def get_secret(name: str) -> str | None   # env HRNBA_<NAME> -> dotenv -> macOS keychain (security find-generic-password -s hardrock-nba-parlay -a <NAME> -w)
class Clock(Protocol): def now_utc(self) -> datetime
class SystemClock(Clock)
class FixedClock(Clock)   # tests
```

## 3. `schemas.py` (frozen during parallel build)

Enums (all `str` enums):

- `DataMode`: LIVE_PROVIDER, MANUAL_INPUT, FIXTURE
- `MarketType`: MONEYLINE, SPREAD, TOTAL, TEAM_TOTAL, PLAYER_POINTS, PLAYER_REBOUNDS, PLAYER_ASSISTS, PLAYER_THREES
- `Period`: FULL_GAME (includes overtime per house rules), FIRST_HALF, SECOND_HALF, FIRST_QUARTER (only FULL_GAME is supported day one; others are rejected with PERIOD_UNSUPPORTED)
- `Side`: HOME, AWAY, OVER, UNDER
- `ParlayType`: MULTI_GAME, SAME_GAME, MIXED
- `CandidateState`: RESEARCH_CANDIDATE, NEEDS_BOOK_QUOTE, READY_FOR_USER_REVIEW, EXPIRED, REJECTED, USER_CONFIRMED_PLACED, SETTLED
- `ModelState`: MARKET_BASELINE, UNVALIDATED_MODEL, VALIDATED_MODEL, INSUFFICIENT_EVIDENCE
- `InjuryDesignation`: OUT, DOUBTFUL, QUESTIONABLE, PROBABLE, AVAILABLE, NOT_LISTED, UNKNOWN
- `LegDecision`: USABLE, WAIT_FOR_UPDATE, UNUSABLE
- `EventStatus`: SCHEDULED, LIVE, FINAL, POSTPONED, CANCELLED, UNKNOWN
- `CorrelationType`: SAME_PLAYER_POINTS_THREES, ASSISTS_AND_TEAMMATE_POINTS, TEAM_WIN_AND_SPREAD, PLAYER_SCORING_AND_GAME_TOTAL, MULTIPLE_OVERS_SHARED_PACE, SHARED_MINUTES_OR_INJURY, SHARED_BLOWOUT_SENSITIVITY, DUPLICATE, NESTED, CONTRADICTORY, MUTUALLY_EXCLUSIVE, SAME_GAME_UNQUANTIFIED
- `Severity`: INFO, WARNING, BLOCKING
- `BetStatus`: PENDING, WON, LOST, VOID, PARTIALLY_VOID, REPRICED, CASHED_OUT, DISPUTED, CORRECTED
- `LegResult`: PENDING, WON, LOST, VOID
- `SettlementSource`: BOOK_CONFIRMED, PROVISIONAL_NBA_RESULTS
- `ReservationStatus`: ACTIVE, CONSUMED, RELEASED, EXPIRED
- `QuoteSource`: USER_TYPED, SCREENSHOT_EXTRACTED, RECEIPT
- `BetSource`: USER_CONFIRMATION, RECEIPT_REVIEW, EXTERNAL_REPORT

Core models (pydantic `BaseModel`, `model_config = ConfigDict(frozen=False, extra="forbid")`):

```python
class SourceStamp(BaseModel):
    source: str                     # e.g. "the-odds-api", "nba-official-injury-report", "user", "fixture:<name>"
    source_url: str | None
    source_record_id: str | None
    source_timestamp_utc: datetime | None   # publication/update time per the source, None when unknown
    received_at_utc: datetime               # when this process received it
    data_mode: DataMode

class Team(BaseModel):  team_id: str; name: str; abbreviation: str | None
class Player(BaseModel): player_id: str; name: str; team_id: str | None; external_ids: dict[str, str] = {}

class Event(BaseModel):
    event_id: str                  # "oddsapi:<id>" | "manual:<slug>" | "fixture:<id>"
    league: Literal["NBA"] = "NBA"
    season_stage: Literal["REGULAR", "PRESEASON", "PLAYOFFS", "CUP", "UNKNOWN"]
    home_team: Team; away_team: Team
    commence_time_utc: datetime
    status: EventStatus
    stamp: SourceStamp

class MarketQuote(BaseModel):      # one priced side at one book
    quote_id: str
    event_id: str
    book: str                      # "hardrockbet_fl" for the target
    jurisdiction: str | None       # "US-FL" for the target
    market_type: MarketType
    period: Period
    is_alternate: bool
    side: Side
    team_id: str | None
    player_id: str | None
    player_name_raw: str | None
    line: Decimal | None           # signed handicap for SPREAD (as offered for that side), threshold for totals/props
    odds_american: int | None
    odds_decimal: Decimal          # > 1
    stamp: SourceStamp

class ReferenceTwoWay(BaseModel):  # both sides from ONE book snapshot, same line, same period
    book: str; event_id: str; market_type: MarketType; period: Period
    player_id: str | None; line: Decimal | None    # for SPREAD: the home handicap; away is its negation
    side_a: Side; odds_a: Decimal                  # HOME or OVER
    side_b: Side; odds_b: Decimal                  # AWAY or UNDER
    stamp: SourceStamp
    # validator: sides complementary; for SPREAD caller guarantees complementary handicaps

class Selection(BaseModel):
    selection_id: str              # deterministic: sha256 of (event_id, book, market_type, period, is_alternate, side, line, player_id or team_id)[:20]
    quote: MarketQuote
    event: Event
    team: Team | None
    player: Player | None
    description: str               # human text, e.g. "Heat -3.5 (full game)"

class ThreeLegTicket(BaseModel):   # validator: exactly 3, distinct selection_ids, distinct (event_id, market_type, period, player_id/team_id, side) tuples
    legs: list[Selection]
    parlay_type: ParlayType        # derived: 3 distinct events -> MULTI_GAME; 1 event -> SAME_GAME; else MIXED

class InjuryContext(BaseModel):
    event_id: str; team_id: str | None; player_id: str | None; player_name_raw: str | None
    designation: InjuryDesignation; reason: str | None
    report_timestamp_utc: datetime | None; stamp: SourceStamp
    material_to_selection: bool | None; note: str | None

class SourcedFact(BaseModel): text: str; stamp: SourceStamp
class DataQuality(BaseModel):      # NOT a win probability
    grade: Literal["A", "B", "C", "D"]; checks: dict[str, bool]; notes: list[str]

class ProbabilityEstimate(BaseModel):
    value: Decimal | None          # None when INSUFFICIENT_EVIDENCE
    state: ModelState
    method: str                    # e.g. "proportional_no_vig(pinnacle h2h)"
    reference_book: str | None; reference_stamp: SourceStamp | None
    assumptions: list[str]

class PriceValue(BaseModel):
    target_decimal: Decimal
    fair_decimal: Decimal | None   # 1/p_reference
    edge_per_dollar: Decimal | None  # p_reference * target_decimal - 1 (None when no reference)
    note: str

class LegAnalysis(BaseModel):
    selection_id: str
    facts: list[SourcedFact]; interpretations: list[str]
    strongest_reason_against: str
    injury: list[InjuryContext]
    data_quality: DataQuality
    probability: ProbabilityEstimate
    price_value: PriceValue
    decision: LegDecision; reason_codes: list[str]
    analyzed_at_utc: datetime

class CorrelationFlag(BaseModel): type: CorrelationType; leg_indexes: list[int]; severity: Severity; explanation: str
class CorrelationReport(BaseModel):
    flags: list[CorrelationFlag]
    joint_numeric_allowed: bool    # False whenever any two legs share an event or a shared-assumption flag is BLOCKING
    weakest_assumption: str
    explanation: str

class BookQuote(BaseModel):        # the sportsbook's combined quote, user-supplied
    book_quote_id: str; candidate_id: str
    combined_decimal: Decimal; combined_american: int | None
    stake_shown_usd: Decimal | None; payout_shown_usd: Decimal | None; payout_includes_stake: bool | None
    legs_as_shown: list[str]       # free text per leg as displayed by the book
    source: QuoteSource; captured_at_utc: datetime; confirmed_by_user: bool
    unresolved_fields: list[str]   # names of fields still ambiguous

class PayoutMath(BaseModel):
    combined_decimal: Decimal | None; combined_source: Literal["BOOK_QUOTE", "INDICATIVE_MULTIPLIED", "NONE"]
    stake_usd: Decimal; gross_return_usd: Decimal | None; net_profit_usd: Decimal | None
    max_loss_usd: Decimal; break_even_probability: Decimal | None
    assumptions: list[str]         # includes "all legs have action"

class Candidate(BaseModel):
    candidate_id: str; user_id: str; created_at_utc: datetime; updated_at_utc: datetime
    state: CandidateState; parlay_type: ParlayType
    ticket: ThreeLegTicket
    leg_analyses: list[LegAnalysis]
    correlation: CorrelationReport
    indicative_multiplied_decimal: Decimal
    book_quote: BookQuote | None
    model_state: ModelState
    p_joint: Decimal | None; p_joint_method: str
    ev_per_dollar: Decimal | None  # only when p_joint and a BOOK_QUOTE (or explicit indicative, labeled) exist
    payout: PayoutMath
    rationale: str; rechecks_required: list[str]; reason_codes: list[str]
    ranking: dict[str, str]        # transparent components, e.g. {"evidence_tier": "B", "sum_edge": "0.041", "note": "..."}
    inputs_snapshot_utc: datetime; expires_at_utc: datetime
    data_mode: DataMode

class BudgetReservation(BaseModel): reservation_id; user_id; date_local; candidate_id; stake_usd; status; idempotency_key; created_at_utc; expires_at_utc; released_reason: str | None
class DailyBudget(BaseModel):
    date_local: str; cap_usd: Decimal; recorded_stake_usd: Decimal; reserved_stake_usd: Decimal
    proposed_stake_usd: Decimal | None; remaining_usd: Decimal; breaches: list[str]; note: str   # note says this is the app ledger, not a book limit

class AcceptedLeg(BaseModel): description: str; event_id: str | None; market_type: MarketType | None; period: Period | None; side: Side | None; line: Decimal | None; player_name: str | None; team_name: str | None; accepted_decimal: Decimal | None; result: LegResult = PENDING
class ActualBet(BaseModel):
    bet_id: str; user_id: str; date_local: str
    candidate_id: str | None; reservation_id: str | None
    book: str; ticket_ref: str | None
    legs: list[AcceptedLeg]        # exactly 3 unless `external` (then any count, recorded truthfully)
    external: bool                 # user-reported wager not produced by this tool
    accepted_combined_decimal: Decimal | None
    recommended_combined_decimal: Decimal | None
    stake_usd: Decimal; placed_at_utc: datetime
    source: BetSource; idempotency_key: str; payload_hash: str
    breach_flags: list[str]        # e.g. BUDGET_BREACH_RECORDED
    status: BetStatus; created_at_utc: datetime

class SettlementRecord(BaseModel):   # append-only
    settlement_id: str; bet_id: str; user_id: str; seq: int
    status: BetStatus; source: SettlementSource
    cash_returned_usd: Decimal | None; bonus_returned_usd: Decimal | None
    repriced_combined_decimal: Decimal | None; leg_results: list[LegResult]
    settled_at_utc: datetime | None; notes: str | None; payload_hash: str; created_at_utc: datetime

class CostEntry(BaseModel): cost_id; user_id; date_local; description; amount_usd; category: Literal["DATA", "SOFTWARE", "HOSTING", "OTHER"]

class UserSettings(BaseModel):
    user_id: str; daily_cap_usd: Decimal; display_tz: str; onboarding_complete: bool
    has_own_odds_api_key: bool; created_at_utc: datetime; updated_at_utc: datetime

class CoverageItem(BaseModel): status: Literal["PASS", "PARTIAL", "BLOCKED", "NOT_IMPLEMENTED", "UNKNOWN"]; detail: str; reason_codes: list[str]; stamp: SourceStamp | None
class CoverageReport(BaseModel):
    date_local: str; generated_at_utc: datetime; data_mode: DataMode
    hard_rock_single_leg: dict[str, CoverageItem]      # keyed by MarketType value
    reference_markets: dict[str, CoverageItem]
    injury_information: CoverageItem
    three_leg_combinability: CoverageItem
    combined_payout_verification: CoverageItem
    stats_and_settlement_rules: CoverageItem
    provider_quota: dict[str, int | None]              # requests_remaining/used/last, None when unknown
    notes: list[str]

class SystemStatus(BaseModel):
    app_version: str; now_utc: datetime; now_display: str; display_tz: str
    auth_mode: str; user_id_masked: str
    database_ok: bool; database_kind: str
    provider_configured: bool; provider_last_ok_utc: datetime | None; provider_quota: dict[str, int | None]
    data_modes_available: list[DataMode]; target_book: str; jurisdiction: str
    daily_cap_usd: Decimal; onboarding_complete: bool; warnings: list[str]

class ToolError(BaseModel): error: str; reason_codes: list[str]; detail: str | None
```

Manual-import input models (used by `providers/manual.py`, `quote_review.py`, MCP tools):

```python
class ManualSelectionInput(BaseModel):   # one pasted leg
    game: str                     # "Heat @ Magic" or "MIA@ORL"; matched to the slate
    market: MarketType; period: Period = FULL_GAME; is_alternate: bool = False
    side: Side; line: Decimal | None; player_name: str | None
    odds_american: int | None; odds_decimal: Decimal | None   # at least one; validator cross-checks when both
    book: str = "hardrockbet_fl"; observed_at_utc: datetime | None
class ManualQuoteInput(BaseModel):       # the slip's combined quote
    combined_decimal: Decimal | None; combined_american: int | None
    stake_shown_usd: Decimal | None; payout_shown_usd: Decimal | None; payout_includes_stake: bool | None
    legs_as_shown: list[str]; source: QuoteSource; captured_at_utc: datetime | None
    user_confirmed: bool = False
class ConfirmedTicketInput(BaseModel):   # for record_actual_bet
    candidate_id: str | None; book: str = "hardrockbet_fl"; ticket_ref: str | None
    legs: list[AcceptedLeg]; accepted_combined_decimal: Decimal | None; accepted_combined_american: int | None
    stake_usd: Decimal; placed_at_utc: datetime | None; source: BetSource; external: bool = False; notes: str | None
class SettlementInput(BaseModel):
    status: BetStatus; source: SettlementSource = BOOK_CONFIRMED
    cash_returned_usd: Decimal | None; bonus_returned_usd: Decimal | None; repriced_combined_decimal: Decimal | None
    leg_results: list[LegResult] | None; settled_at_utc: datetime | None; notes: str | None
```

## 4. `db.py`

```python
class Database:
    def __init__(self, url: str, *, allow_fixture_ledger: bool = False)   # SQLAlchemy Core 2.x engine; sqlite -> WAL, busy_timeout 5000, foreign_keys ON; sqlite transactions begin with BEGIN IMMEDIATE
    def migrate(self) -> None                                              # idempotent, records schema_migrations
    @contextmanager def tx(self) -> Iterator[Connection]                   # short transaction; commit on exit, rollback on error
    def lock_user_day(self, conn, user_id, date_local, now) -> None             # Postgres: SELECT ... FOR UPDATE on user_days; SQLite: no-op (BEGIN IMMEDIATE already serializes writers)
    # helpers: cents(), from_cents(), dec(), iso(), parse_iso(), new_id(prefix)
```

Tables (all have `user_id TEXT NOT NULL` where noted; all timestamps TEXT ISO UTC):

- `schema_migrations(version INTEGER PK, applied_at)`
- `users(user_id PK, email, display_name, created_at, disabled INTEGER)` (hosted only; local mode has a single row inserted lazily)
- `user_settings(user_id PK FK, daily_cap_cents, display_tz, onboarding_complete, odds_api_key_encrypted, created_at, updated_at)`
- `user_days(user_id, date_local, created_at, PRIMARY KEY(user_id, date_local))` lock row
- `oauth_clients(client_id PK, client_json, created_at)`; `oauth_codes(code PK, client_id, user_id, json, expires_at)`; `oauth_tokens(token PK, kind, client_id, user_id, scopes, expires_at, revoked INTEGER)`; `credentials(user_id PK, password_hash, updated_at)`; `login_attempts(key, window_start, count)`
- `events_cache(event_id PK, json, received_at)`
- `odds_snapshots(snapshot_id PK, user_id NULL, event_id, book, market_type, period, is_alternate, side, line, player_id, odds_decimal, source_ts, received_at, data_mode, json)` index (event_id, book, received_at)
- `injury_snapshots(snapshot_id PK, report_ts, event_id, team_id, player_id, designation, json, received_at)`
- `candidates(candidate_id PK, user_id, date_local, state, parlay_type, json, created_at, updated_at, expires_at)` index (user_id, date_local)
- `candidate_history(id PK, candidate_id, user_id, from_state, to_state, reason, json, created_at)` append-only
- `book_quotes(book_quote_id PK, candidate_id, user_id, json, created_at)`
- `reservations(reservation_id PK, user_id, date_local, candidate_id, stake_cents, status, idempotency_key, created_at, expires_at, released_reason, UNIQUE(user_id, idempotency_key))`
- `bets(bet_id PK, user_id, date_local, candidate_id, reservation_id, stake_cents, status, idempotency_key, payload_hash, external, json, placed_at, created_at, UNIQUE(user_id, idempotency_key))` index (user_id, date_local)
- `settlements(settlement_id PK, bet_id, user_id, seq, status, source, cash_returned_cents, bonus_returned_cents, payload_hash, json, created_at, UNIQUE(bet_id, seq), UNIQUE(bet_id, payload_hash))`
- `costs(cost_id PK, user_id, date_local, category, amount_cents, description, created_at)`
- `provider_usage(id PK, user_id NULL, provider, endpoint, credits_cost, requests_remaining, requests_used, created_at)`
- `audit_log(id PK, user_id, action, ref_id, json, created_at)`

Deletion/export: `db.export_user(user_id) -> dict` and `db.delete_user(user_id) -> dict` (counts), used by CLI and the account web page, never by an MCP tool.

## 5. Public function signatures

### providers

```python
class OddsProvider(Protocol):
    name: str
    def list_events(self, date_local: str) -> ProviderResult[list[Event]]
    def fetch_featured_odds(self, date_local: str, books: list[str], markets: list[MarketType]) -> ProviderResult[list[MarketQuote]]
    def fetch_event_props(self, event_id: str, books: list[str], markets: list[MarketType], include_alternates: bool) -> ProviderResult[list[MarketQuote]]
    def fetch_scores(self, days_from: int) -> ProviderResult[list[GameResult]]
    def probe(self) -> ProviderProbe        # auth ok?, basketball_nba active?, quota headers, target book present?
class ProviderResult(Generic[T]): data: T; stamp: SourceStamp; credits_cost: int | None; quota: dict[str, int | None]; warnings: list[str]
class ProviderError(Exception): reason_code: str; retry_after: float | None
# providers/odds_api.py: OddsApiProvider(api_key, settings, clock, http=httpx.Client) -- bounded retries (429/5xx, exponential backoff, max 3), 60s in-process cache keyed by full request (minus key), credit accounting to provider_usage, app-level daily credit guard, redacted logging
# providers/manual.py: parse_pasted_selections(text) -> list[ManualSelectionInput]; load_csv(path|str) ; load_json(...); selections_from_inputs(inputs, slate: list[Event], clock) -> list[Selection]  (raises with EVENT_UNMATCHED / QUOTE_SIGN_AMBIGUOUS...)
# providers/fixtures.py: load_fixture_slate(name) -> (events, quotes, references, injuries) all stamped FIXTURE
# providers/nba_injury_report.py: fetch_injury_report(date_local, clock) -> ProviderResult[list[InjuryContext]]; parse_injury_report_pdf(bytes, report_ts) -> list[InjuryContext]; manual_injury_entries(...)
```

### normalization.py / freshness.py / injury_context.py

```python
def canonical_team(name: str) -> Team                      # NBA 30 teams, aliases; raises TEAM_UNMATCHED
def canonical_player(name: str, team_hint: Team | None) -> Player   # slug id "player:<normalized-name>" plus external ids when known
def match_event(game_text: str, slate: list[Event]) -> Event
def selection_id_for(quote: MarketQuote) -> str
def build_selections(quotes: list[MarketQuote], events: dict[str, Event]) -> list[Selection]
def pair_reference(selection: Selection, reference_quotes: list[MarketQuote]) -> ReferenceTwoWay | None   # exact line, period, complementary handicap; None with reason LINE_MISMATCH / REFERENCE_INCOMPLETE
def check_quote_age(quote: MarketQuote, now: datetime, max_age_s: int) -> list[str]            # reason codes
def check_reference_skew(target: MarketQuote, ref: ReferenceTwoWay, max_skew_s: int) -> list[str]
def check_event_not_started(event: Event, now: datetime) -> list[str]
def injury_for_selection(selection: Selection, report: list[InjuryContext], report_max_age_s: int, now) -> tuple[list[InjuryContext], LegDecision, list[str]]
```

### probabilities.py

```python
def american_to_decimal(a: int) -> Decimal                 # rejects 0 and -99..99 except 100/-100 edge per rules: |a| >= 100
def decimal_to_american(d: Decimal) -> int
def implied_probability(d: Decimal) -> Decimal             # 1/d
def no_vig_two_way(d1: Decimal, d2: Decimal) -> tuple[Decimal, Decimal]   # proportional
def independence_baseline(ps: list[Decimal]) -> Decimal    # product; caller must label the assumption
def indicative_multiplied_decimal(ds: list[Decimal]) -> Decimal
def payout_math(stake: Decimal, combined_decimal: Decimal | None, source: str) -> PayoutMath
def break_even_probability(d: Decimal) -> Decimal          # 1/d
def ev_per_dollar(p_joint: Decimal, d: Decimal) -> Decimal # p*d - 1
def estimate_leg_probability(selection: Selection, ref: ReferenceTwoWay | None) -> ProbabilityEstimate
def joint_probability(ticket: ThreeLegTicket, legs: list[ProbabilityEstimate], correlation: CorrelationReport) -> tuple[Decimal | None, ModelState, str]
Q = Decimal quantization helpers: q_odds (4 dp), q_prob (6 dp), q_money (2 dp, ROUND_HALF_UP)
```

### correlation.py

```python
def check_correlation(ticket: ThreeLegTicket) -> CorrelationReport
def hard_rejections(ticket: ThreeLegTicket) -> list[str]   # DUPLICATE_SELECTION, CONTRADICTORY_SELECTION, NESTED_SELECTION, NOT_THREE_LEGS
```

### candidate_builder.py / quote_review.py / services.py

```python
def analyze_leg(selection, references, injuries, now, settings) -> LegAnalysis
def build_candidates(selections, references, injuries, parlay_type: Literal["auto","multi_game","same_game","mixed"], max_candidates: int, now, settings, user_id) -> list[Candidate]   # bounded search: top 24 usable legs by edge then C(24,3)=2024 combos max
def review_book_quote(candidate: Candidate, quote: ManualQuoteInput, now) -> tuple[Candidate, list[str]]   # replaces indicative math; flags QUOTE_CONFLICTS_WITH_LEGS when legs_as_shown do not match
def revalidate(candidate: Candidate, fresh_selections, fresh_refs, fresh_injuries, now, settings) -> Candidate   # EXPIRED/REJECTED/READY_FOR_USER_REVIEW transitions with history
def analyze_user_ticket(inputs: list[ManualSelectionInput], combined: ManualQuoteInput | None, slate, refs, injuries, now, settings, user_id) -> Candidate

# services.py: every function takes ctx: RequestContext(user_id, clock, db, settings, providers)
get_system_status(ctx) -> SystemStatus
check_data_coverage(ctx, date_local, probe_props: bool = False) -> CoverageReport
get_nba_slate(ctx, date_local) -> SlateResponse(date_local, events, data_mode, warnings, stamps)
get_injury_context(ctx, event_id) -> InjuryResponse(event_id, entries, report_timestamp_utc, stamp, warnings)
analyze_leg(ctx, selection_id, date_local | None) -> LegAnalysis
build_three_leg_parlays(ctx, date_local, parlay_type="auto", max_candidates=3, include_props=True) -> BuildResponse(candidates, no_ticket_reason: str | None, coverage_summary, data_mode, credits_used)
analyze_my_parlay(ctx, selections: list[ManualSelectionInput], combined: ManualQuoteInput | None, date_local) -> Candidate
check_parlay_correlation(ctx, candidate_id) -> CorrelationReport
import_hardrock_quote(ctx, candidate_id, quote: ManualQuoteInput) -> Candidate
refresh_parlay(ctx, candidate_id) -> Candidate
select_ticket(ctx, candidate_id, stake_usd, idempotency_key: str | None) -> SelectResponse(candidate, reservation, budget: DailyBudget)
release_reservation(ctx, reservation_id, reason) -> BudgetReservation
get_daily_budget(ctx, date_local, proposed_stake_usd: Decimal | None) -> DailyBudget
record_actual_bet(ctx, ticket: ConfirmedTicketInput, idempotency_key) -> RecordResponse(bet, budget, replay: bool, breach_flags)
reconcile_settlement(ctx, bet_id, settlement: SettlementInput) -> SettlementResponse(bet, settlement, replay: bool)
get_performance(ctx, start_date, end_date) -> PerformanceReport
generate_30_day_review(ctx) -> ReviewReport
set_user_settings(ctx, daily_cap_usd | None, display_tz | None, odds_api_key | None, confirm_onboarding: bool) -> UserSettings
add_cost(ctx, CostEntry fields) -> CostEntry
export_my_data(ctx) -> dict
```

Budget algorithm (`budget.py`), inside ONE transaction with `lock_user_day`:
1. expire reservations past `expires_at` (status EXPIRED, reason RESERVATION_EXPIRED).
2. recorded = sum(stake of bets for user/date, all statuses, external included).
3. reserved = sum(stake of ACTIVE reservations for user/date, excluding the one being consumed).
4. remaining = cap - recorded - reserved (floor 0 for display; the raw value may be negative after a breach).
5. reserve(stake): if idempotency_key exists -> return existing (replay). If stake > remaining -> raise BUDGET_EXCEEDED (no reservation). Else insert ACTIVE with expires_at = min(now + ttl, earliest leg commence_time).
6. record(bet): consume linked reservation (CONSUMED). If recorded + stake > cap -> still record, add BUDGET_BREACH_RECORDED to breach_flags, audit_log. Never refuse to record history.
7. Winnings, refunds, cash-outs never increase `remaining`.

Settlement (`settlement.py`): append `SettlementRecord` with seq = last+1; identical payload_hash -> replay, no new row. `BOOK_CONFIRMED` is authoritative; `PROVISIONAL_NBA_RESULTS` never supersedes an existing BOOK_CONFIRMED record and is marked provisional in reports. Cash profit = cash_returned - stake (returns include stake). Bonus kept separate.

## 6. MCP tools (`mcp_server.py`)

Each tool: `title`, annotations, pydantic input validation, returns a typed model (structured output). Errors return `ToolError` (no stack traces). `user_id` always from auth.

| tool | annotations | mutates |
|---|---|---|
| get_system_status | readOnly | no |
| check_data_coverage(date_local, probe_props=false) | readOnly, openWorld | provider credits only |
| get_nba_slate(date_local) | readOnly, openWorld | no |
| get_injury_context(event_id) | readOnly, openWorld | no |
| analyze_leg(selection_id, date_local?) | readOnly, openWorld | no |
| build_three_leg_parlays(date_local, parlay_type="auto", max_candidates=3, include_props=true) | openWorld, idempotent=false | creates candidate records |
| analyze_my_parlay(three_selections, combined_odds?) | openWorld | creates one candidate record |
| check_parlay_correlation(candidate_id) | readOnly | no |
| import_hardrock_quote(candidate_id, quote_fields) | idempotent | updates candidate |
| refresh_parlay(candidate_id) | openWorld | updates candidate + history |
| select_ticket(candidate_id, stake_usd, idempotency_key?) | idempotent | budget reservation |
| release_reservation(reservation_id, reason) | idempotent | reservation |
| get_daily_budget(date_local?, proposed_stake_usd?) | readOnly | no |
| record_actual_bet(confirmed_ticket_fields, idempotency_key) | idempotent | ledger (append) |
| reconcile_settlement(bet_id, settlement_fields) | idempotent | ledger (append-only) |
| get_performance(start_date, end_date) | readOnly | no |
| generate_30_day_review() | readOnly | no |
| set_user_settings(...) | idempotent | user settings |
| add_cost(...) | idempotent (with key) | ledger |
| export_my_data() | readOnly | no |

Never exposed: place bet, shell, raw SQL, delete-all (deletion is CLI / account page with confirmation).

Transports: `stdio` (local, auth_mode none) and `streamable-http` at `/mcp` (hosted, auth_mode builtin_oauth). The hosted app is a Starlette app from `web.py` that mounts the MCP app plus `/login`, `/signup`, `/account`, `/healthz` (no personal data), `/.well-known/*` served by the SDK auth routes.

## 7. Reason codes

NO_PROVIDER_KEY, PROVIDER_AUTH_FAILED, PROVIDER_QUOTA_EXHAUSTED, PROVIDER_RATE_LIMITED, PROVIDER_ERROR, PROVIDER_CREDIT_GUARD,
BOOK_NOT_AVAILABLE, MARKET_NOT_OFFERED, REFERENCE_MISSING, REFERENCE_INCOMPLETE, LINE_MISMATCH, PERIOD_UNSUPPORTED, PLAYER_UNMATCHED, EVENT_UNMATCHED, TEAM_UNMATCHED, WRONG_BOOK, WRONG_LEAGUE, WRONG_JURISDICTION,
QUOTE_STALE, TIMESTAMP_SKEW, SOURCE_TIMESTAMP_UNKNOWN, GAME_STARTED, GAME_POSTPONED, GAME_CANCELLED, MARKET_SUSPENDED,
INJURY_OUT, INJURY_DOUBTFUL, INJURY_QUESTIONABLE_MATERIAL, INJURY_QUESTIONABLE_IMMATERIAL, INJURY_REPORT_STALE, INJURY_REPORT_MISSING, MINUTES_RESTRICTION,
NOT_THREE_LEGS, DUPLICATE_SELECTION, CONTRADICTORY_SELECTION, NESTED_SELECTION, MUTUALLY_EXCLUSIVE_SELECTION, SAME_GAME_CORRELATION, COMBINATION_UNVERIFIED,
BUDGET_EXCEEDED, BUDGET_BREACH_RECORDED, RESERVATION_EXPIRED, RESERVATION_NOT_ACTIVE, IDEMPOTENT_REPLAY, IDEMPOTENCY_CONFLICT,
QUOTE_FIELDS_MISSING, QUOTE_SIGN_AMBIGUOUS, QUOTE_UNCONFIRMED, QUOTE_CONFLICTS_WITH_LEGS, QUOTE_REPLACES_INDICATIVE,
JOINT_PROBABILITY_UNAVAILABLE, EV_UNAVAILABLE, SETTLEMENT_RULES_UNKNOWN, PROVISIONAL_RESULT, SUPERSEDED_BY_BOOK,
NEEDS_ONBOARDING, UNAUTHENTICATED, FORBIDDEN, NOT_FOUND, INVALID_INPUT, NO_SUITABLE_TICKET, WAIT_FOR_UPDATE

## 8. Test requirements by module (minimum)

- quant: 3 independent 70% legs -> 0.343; p 0.20 and D 5.50 -> EV 0.10; stake 10 at 5.50 -> gross 55, net 45; american conversions incl. rejection of 0 and |a|<100; no-vig sums to 1; book quote replaces multiplied; correlation flags for every type in section 3; nested/contradictory/duplicate rejections; exactly-three validator.
- data: fixture parsing; hardrockbet_fl filtering (never substitute hardrockbet); stale quote; skew; started game; player/event/line/period mismatch; OCR sign ambiguity; injury change; 401/429/5xx handling with backoff; quota headers; credit guard; redaction.
- ledger: $10 cap; partial remaining; ET day boundary incl. DST end 2026-11-01; concurrent reservations (threads) never exceed cap; duplicate idempotency keys; breach recorded and flagged; replays; void/repriced/cash-out/disputed/corrected; repeated reconcile no double count; provisional never overrides book; profit = cash returned - stake; restart recovery (reopen DB).
- pipeline: NO SUITABLE TICKET when inputs inadequate; WAIT_FOR_UPDATE on material questionable; multi-game default; same-game joint unknown; refresh expiry; quote conflicts.
- server: stdio init + list tools + call; HTTP init with auth; unauthenticated 401 with WWW-Authenticate resource metadata; two users isolated (guessed ids, idempotency collisions, caches); tool annotations present; structured output present.

## 9. MCP SDK 2.x facts that bind the server module (added after inspecting mcp==2.3.0)

See `docs/research/mcp-sdk-v2-installed-api.md`. In short:

- `from mcp.server.mcpserver import MCPServer, Context` (FastMCP no longer exists). Tool errors:
  `from mcp.server.mcpserver.exceptions import ToolError`.
- Tools are plain sync `def` functions returning pydantic models (structured output auto-detected); pass
  `annotations=ToolAnnotations(read_only_hint=..., destructive_hint=False, idempotent_hint=..., open_world_hint=...)`.
- Identity: `get_access_token().subject` (from `mcp.server.auth.middleware.auth_context`) is the `user_id` in
  hosted mode. In `auth_mode == "none"` (stdio/CLI) the identity is `settings.local_user_id`. Resolve this in ONE
  helper `auth.current_user_id()`; every tool calls it; never read a user id from arguments.
- Hosted app: `server.streamable_http_app(streamable_http_path="/mcp", transport_security=TransportSecuritySettings(...))`
  mounted in a Starlette app whose lifespan enters `server.session_manager.run()`. Extra routes (login, signup,
  account, healthz) via `server.custom_route(...)` or the outer Starlette app.
- Built-in OAuth AS: implement `OAuthAuthorizationServerProvider` in `auth.py` backed by the `oauth_*` and
  `credentials` tables (DCR enabled, PKCE S256 required, refresh tokens, revocation). `authorize()` returns the URL of
  our own `/login` page carrying an opaque signed request id; after password login the page redirects to the
  client's `redirect_uri` with `code` and `state`. Passwords hashed with argon2id; login rate-limited.

## 10. `errors.py` (foundation, added 2026-10-19 evening)

`ServiceError(message, reason_codes, detail)` with subclasses `NotFound`, `Forbidden`, `Unauthenticated`,
`InvalidInput`, `ProviderError(retry_after, status_code)`. Services raise these; the MCP layer converts
them to `ToolError` results (no stack traces); the CLI prints them. Ledger-specific `BudgetExceeded` may
subclass `ServiceError` with reason code `BUDGET_EXCEEDED`.

## 11. Decisions after the research critique (2026-10-19, ~19:45 ET)

- `pyproject.toml` pins `mcp>=2.3,<3`. Python 3.12.
- `Settings.daily_provider_credit_budget` default is 25 (The Odds API free tier is 500 credits/month); hosted mode
  also enforces `per_user_daily_credit_quota` (default 30) per user on the server-wide key; users may store their own
  key via `set_user_settings(odds_api_key=...)` (encrypted at rest with the server secret).
- `schemas.AI_DISCLOSURE` is attached to `SystemStatus`, `BuildResponse` and `Candidate` (field `ai_disclosure`);
  the MCP server `instructions` and the skill repeat it at session start.
- Reference skew: when a reference snapshot is older than `max_reference_skew_seconds` relative to the target quote,
  the leg's probability state is INSUFFICIENT_EVIDENCE with reason TIMESTAMP_SKEW (never silently loosened); the
  coverage report measures the observed skew so the user can decide to raise the threshold explicitly.
- Day one runs locally (stdio, user `local-owner`, SQLite). `db.import_user(user_id, bundle, now)` plus a CLI command
  move those records into the hosted database later without double counting (primary keys and idempotency keys kept).
- Injury PDFs are fetched automatically (`injury_auto_fetch`), with manual entry always available; the NBA Terms of
  Use question for a public listing is recorded in `docs/publication-readiness.md`, not resolved here.
- Plugin name `nba-three-leg-parlays`; `.mcp.json` server key `nba-three-leg-parlays`; marketplace name
  `hardrock-nba-parlay-marketplace`.
