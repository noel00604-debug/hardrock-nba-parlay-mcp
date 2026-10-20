"""Shared data contract for every module (docs/ARCHITECTURE.md section 3).

Frozen during the parallel build. Modules must not edit this file; they record requested changes in
docs/integration-notes/<module>.md.

Conventions
- Decimal for every odds, probability, and money value (USD).
- All datetimes are timezone-aware UTC (`UtcDatetime` rejects naive values and normalises to UTC).
- Every model forbids unknown fields so that tool inputs are validated strictly.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

# --------------------------------------------------------------------------------------
# Scalars
# --------------------------------------------------------------------------------------


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("datetime must be timezone-aware (UTC)")
    return value.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_ensure_utc)]


def _nonneg_money(value: Decimal) -> Decimal:
    if value < 0:
        raise ValueError("money must be >= 0")
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


Money = Annotated[Decimal, AfterValidator(_nonneg_money)]


def _probability(value: Decimal) -> Decimal:
    if not (Decimal(0) <= value <= Decimal(1)):
        raise ValueError("probability must be within [0, 1]")
    return value


Probability = Annotated[Decimal, AfterValidator(_probability)]


def _decimal_odds(value: Decimal) -> Decimal:
    if value <= 1:
        raise ValueError("decimal odds must be > 1")
    return value


DecimalOdds = Annotated[Decimal, AfterValidator(_decimal_odds)]


def _american_odds(value: int) -> int:
    if value == 0 or abs(value) < 100:
        raise ValueError("american odds must be <= -100 or >= +100")
    return value


AmericanOdds = Annotated[int, AfterValidator(_american_odds)]

LocalDate = Annotated[
    str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="YYYY-MM-DD in America/New_York")
]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_assignment=True)


# --------------------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------------------


class DataMode(StrEnum):
    LIVE_PROVIDER = "LIVE_PROVIDER"
    MANUAL_INPUT = "MANUAL_INPUT"
    FIXTURE = "FIXTURE"


class MarketType(StrEnum):
    MONEYLINE = "MONEYLINE"
    SPREAD = "SPREAD"
    TOTAL = "TOTAL"
    TEAM_TOTAL = "TEAM_TOTAL"
    PLAYER_POINTS = "PLAYER_POINTS"
    PLAYER_REBOUNDS = "PLAYER_REBOUNDS"
    PLAYER_ASSISTS = "PLAYER_ASSISTS"
    PLAYER_THREES = "PLAYER_THREES"


PLAYER_MARKETS: frozenset[MarketType] = frozenset(
    {
        MarketType.PLAYER_POINTS,
        MarketType.PLAYER_REBOUNDS,
        MarketType.PLAYER_ASSISTS,
        MarketType.PLAYER_THREES,
    }
)
TEAM_MARKETS: frozenset[MarketType] = frozenset(
    {MarketType.MONEYLINE, MarketType.SPREAD, MarketType.TOTAL, MarketType.TEAM_TOTAL}
)


class Period(StrEnum):
    FULL_GAME = "FULL_GAME"  # includes overtime per house rules
    FIRST_HALF = "FIRST_HALF"
    SECOND_HALF = "SECOND_HALF"
    FIRST_QUARTER = "FIRST_QUARTER"


SUPPORTED_PERIODS: frozenset[Period] = frozenset({Period.FULL_GAME})


class Side(StrEnum):
    HOME = "HOME"
    AWAY = "AWAY"
    OVER = "OVER"
    UNDER = "UNDER"


class ParlayType(StrEnum):
    MULTI_GAME = "MULTI_GAME"
    SAME_GAME = "SAME_GAME"
    MIXED = "MIXED"


class CandidateState(StrEnum):
    RESEARCH_CANDIDATE = "RESEARCH_CANDIDATE"
    NEEDS_BOOK_QUOTE = "NEEDS_BOOK_QUOTE"
    READY_FOR_USER_REVIEW = "READY_FOR_USER_REVIEW"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"
    USER_CONFIRMED_PLACED = "USER_CONFIRMED_PLACED"
    SETTLED = "SETTLED"


class ModelState(StrEnum):
    MARKET_BASELINE = "MARKET_BASELINE"
    UNVALIDATED_MODEL = "UNVALIDATED_MODEL"
    VALIDATED_MODEL = "VALIDATED_MODEL"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class InjuryDesignation(StrEnum):
    OUT = "OUT"
    DOUBTFUL = "DOUBTFUL"
    QUESTIONABLE = "QUESTIONABLE"
    PROBABLE = "PROBABLE"
    AVAILABLE = "AVAILABLE"
    NOT_LISTED = "NOT_LISTED"
    UNKNOWN = "UNKNOWN"


class LegDecision(StrEnum):
    USABLE = "USABLE"
    WAIT_FOR_UPDATE = "WAIT_FOR_UPDATE"
    UNUSABLE = "UNUSABLE"


class EventStatus(StrEnum):
    SCHEDULED = "SCHEDULED"
    LIVE = "LIVE"
    FINAL = "FINAL"
    POSTPONED = "POSTPONED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class CorrelationType(StrEnum):
    SAME_PLAYER_POINTS_THREES = "SAME_PLAYER_POINTS_THREES"
    ASSISTS_AND_TEAMMATE_POINTS = "ASSISTS_AND_TEAMMATE_POINTS"
    TEAM_WIN_AND_SPREAD = "TEAM_WIN_AND_SPREAD"
    PLAYER_SCORING_AND_GAME_TOTAL = "PLAYER_SCORING_AND_GAME_TOTAL"
    MULTIPLE_OVERS_SHARED_PACE = "MULTIPLE_OVERS_SHARED_PACE"
    SHARED_MINUTES_OR_INJURY = "SHARED_MINUTES_OR_INJURY"
    SHARED_BLOWOUT_SENSITIVITY = "SHARED_BLOWOUT_SENSITIVITY"
    DUPLICATE = "DUPLICATE"
    NESTED = "NESTED"
    CONTRADICTORY = "CONTRADICTORY"
    MUTUALLY_EXCLUSIVE = "MUTUALLY_EXCLUSIVE"
    SAME_GAME_UNQUANTIFIED = "SAME_GAME_UNQUANTIFIED"


class Severity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    BLOCKING = "BLOCKING"


class BetStatus(StrEnum):
    PENDING = "PENDING"
    WON = "WON"
    LOST = "LOST"
    VOID = "VOID"
    PARTIALLY_VOID = "PARTIALLY_VOID"
    REPRICED = "REPRICED"
    CASHED_OUT = "CASHED_OUT"
    DISPUTED = "DISPUTED"
    CORRECTED = "CORRECTED"


FINAL_BET_STATUSES: frozenset[BetStatus] = frozenset(
    {
        BetStatus.WON,
        BetStatus.LOST,
        BetStatus.VOID,
        BetStatus.PARTIALLY_VOID,
        BetStatus.REPRICED,
        BetStatus.CASHED_OUT,
        BetStatus.CORRECTED,
    }
)


class LegResult(StrEnum):
    PENDING = "PENDING"
    WON = "WON"
    LOST = "LOST"
    VOID = "VOID"


class SettlementSource(StrEnum):
    BOOK_CONFIRMED = "BOOK_CONFIRMED"
    PROVISIONAL_NBA_RESULTS = "PROVISIONAL_NBA_RESULTS"


class ReservationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class QuoteSource(StrEnum):
    USER_TYPED = "USER_TYPED"
    SCREENSHOT_EXTRACTED = "SCREENSHOT_EXTRACTED"
    RECEIPT = "RECEIPT"


class BetSource(StrEnum):
    USER_CONFIRMATION = "USER_CONFIRMATION"
    RECEIPT_REVIEW = "RECEIPT_REVIEW"
    EXTERNAL_REPORT = "EXTERNAL_REPORT"


class CoverageStatus(StrEnum):
    PASS = "PASS"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    UNKNOWN = "UNKNOWN"


# --------------------------------------------------------------------------------------
# Reason codes (section 7). Kept as plain strings so modules can extend their own lists.
# --------------------------------------------------------------------------------------

REASON_CODES: tuple[str, ...] = (
    "NO_PROVIDER_KEY",
    "PROVIDER_AUTH_FAILED",
    "PROVIDER_QUOTA_EXHAUSTED",
    "PROVIDER_RATE_LIMITED",
    "PROVIDER_ERROR",
    "PROVIDER_CREDIT_GUARD",
    "BOOK_NOT_AVAILABLE",
    "MARKET_NOT_OFFERED",
    "REFERENCE_MISSING",
    "REFERENCE_INCOMPLETE",
    "LINE_MISMATCH",
    "PERIOD_UNSUPPORTED",
    "PLAYER_UNMATCHED",
    "EVENT_UNMATCHED",
    "TEAM_UNMATCHED",
    "WRONG_BOOK",
    "WRONG_LEAGUE",
    "WRONG_JURISDICTION",
    "QUOTE_STALE",
    "TIMESTAMP_SKEW",
    "SOURCE_TIMESTAMP_UNKNOWN",
    "GAME_STARTED",
    "GAME_POSTPONED",
    "GAME_CANCELLED",
    "MARKET_SUSPENDED",
    "INJURY_OUT",
    "INJURY_DOUBTFUL",
    "INJURY_QUESTIONABLE_MATERIAL",
    "INJURY_QUESTIONABLE_IMMATERIAL",
    "INJURY_REPORT_STALE",
    "INJURY_REPORT_MISSING",
    "MINUTES_RESTRICTION",
    "NOT_THREE_LEGS",
    "DUPLICATE_SELECTION",
    "CONTRADICTORY_SELECTION",
    "NESTED_SELECTION",
    "MUTUALLY_EXCLUSIVE_SELECTION",
    "SAME_GAME_CORRELATION",
    "COMBINATION_UNVERIFIED",
    "BUDGET_EXCEEDED",
    "BUDGET_BREACH_RECORDED",
    "RESERVATION_EXPIRED",
    "RESERVATION_NOT_ACTIVE",
    "IDEMPOTENT_REPLAY",
    "IDEMPOTENCY_CONFLICT",
    "QUOTE_FIELDS_MISSING",
    "QUOTE_SIGN_AMBIGUOUS",
    "QUOTE_UNCONFIRMED",
    "QUOTE_CONFLICTS_WITH_LEGS",
    "QUOTE_REPLACES_INDICATIVE",
    "JOINT_PROBABILITY_UNAVAILABLE",
    "EV_UNAVAILABLE",
    "SETTLEMENT_RULES_UNKNOWN",
    "PROVISIONAL_RESULT",
    "SUPERSEDED_BY_BOOK",
    "NEEDS_ONBOARDING",
    "UNAUTHENTICATED",
    "FORBIDDEN",
    "NOT_FOUND",
    "INVALID_INPUT",
    "NO_SUITABLE_TICKET",
    "WAIT_FOR_UPDATE",
    "FIXTURE_DATA",
    "MANUAL_DATA",
)


AI_DISCLOSURE = (
    "AI-assisted analysis. This tool researches and prepares tickets; it never places wagers, moves money, or "
    "guarantees outcomes. You decide and place every wager yourself in the Hard Rock Bet app."
)


# --------------------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------------------


class SourceStamp(Model):
    source: str = Field(
        description='e.g. "the-odds-api", "nba-official-injury-report", "user", "fixture:<name>"'
    )
    source_url: str | None = None
    source_record_id: str | None = None
    source_timestamp_utc: UtcDatetime | None = Field(
        default=None, description="Publication/update time per the source; None when unknown"
    )
    received_at_utc: UtcDatetime = Field(description="When this process received the data")
    data_mode: DataMode


# --------------------------------------------------------------------------------------
# Domain
# --------------------------------------------------------------------------------------


class Team(Model):
    team_id: str = Field(description='canonical id, e.g. "nba:MIA"')
    name: str
    abbreviation: str | None = None


class Player(Model):
    player_id: str = Field(description='canonical id, e.g. "player:bam-adebayo" or "nba:1628389" when known')
    name: str
    team_id: str | None = None
    external_ids: dict[str, str] = Field(default_factory=dict)


class Event(Model):
    event_id: str = Field(description='"oddsapi:<id>" | "manual:<slug>" | "fixture:<id>"')
    league: Literal["NBA"] = "NBA"
    season_stage: Literal["REGULAR", "PRESEASON", "PLAYOFFS", "CUP", "UNKNOWN"] = "UNKNOWN"
    home_team: Team
    away_team: Team
    commence_time_utc: UtcDatetime
    status: EventStatus = EventStatus.SCHEDULED
    stamp: SourceStamp

    @property
    def short_name(self) -> str:
        return f"{self.away_team.abbreviation or self.away_team.name} @ {self.home_team.abbreviation or self.home_team.name}"


class MarketQuote(Model):
    """One priced side of one market at one book."""

    quote_id: str
    event_id: str
    book: str = Field(description='bookmaker key, "hardrockbet_fl" for the target')
    jurisdiction: str | None = Field(default=None, description='"US-FL" for the target book')
    market_type: MarketType
    period: Period = Period.FULL_GAME
    is_alternate: bool = False
    side: Side
    team_id: str | None = None
    player_id: str | None = None
    player_name_raw: str | None = None
    line: Decimal | None = Field(
        default=None,
        description="Signed handicap for SPREAD as offered for this side; threshold for totals/props",
    )
    odds_american: AmericanOdds | None = None
    odds_decimal: DecimalOdds
    stamp: SourceStamp

    @model_validator(mode="after")
    def _shape(self) -> MarketQuote:
        if self.market_type in PLAYER_MARKETS:
            if self.side not in (Side.OVER, Side.UNDER):
                raise ValueError("player markets use OVER/UNDER")
            if self.line is None:
                raise ValueError("player markets require a line")
            if not self.player_id and not self.player_name_raw:
                raise ValueError("player markets require a player")
        elif self.market_type in (MarketType.TOTAL, MarketType.TEAM_TOTAL):
            if self.side not in (Side.OVER, Side.UNDER):
                raise ValueError("totals use OVER/UNDER")
            if self.line is None:
                raise ValueError("totals require a line")
        elif self.market_type == MarketType.SPREAD:
            if self.side not in (Side.HOME, Side.AWAY):
                raise ValueError("spreads use HOME/AWAY")
            if self.line is None:
                raise ValueError("spreads require a signed handicap")
        elif self.market_type == MarketType.MONEYLINE:
            if self.side not in (Side.HOME, Side.AWAY):
                raise ValueError("moneylines use HOME/AWAY")
            if self.line is not None:
                raise ValueError("moneylines have no line")
        if self.odds_american is not None:
            implied = Decimal(1) + (
                Decimal(self.odds_american) / Decimal(100)
                if self.odds_american > 0
                else Decimal(100) / Decimal(abs(self.odds_american))
            )
            if abs(implied - self.odds_decimal) > Decimal("0.0105"):
                raise ValueError(
                    f"odds_american {self.odds_american} does not match odds_decimal {self.odds_decimal}"
                )
        return self

    def identity_tuple(self) -> tuple[str, str, str, bool, str, str | None, str]:
        """Key used for the deterministic selection id and for duplicate detection."""
        subject = self.player_id or self.player_name_raw or self.team_id or ""
        return (
            self.event_id,
            self.market_type.value,
            self.period.value,
            self.is_alternate,
            self.side.value,
            None if self.line is None else format(self.line.normalize(), "f"),
            subject,
        )


def compute_selection_id(quote: MarketQuote) -> str:
    """Deterministic id: same event/book/market/period/alt/side/line/subject -> same id across refreshes."""
    parts = (quote.book, *[str(p) for p in quote.identity_tuple()])
    return "sel_" + hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:20]


class ReferenceTwoWay(Model):
    """Both sides of one market from ONE book snapshot, same line and period.

    For SPREAD, `line` is the HOME handicap and the AWAY handicap is its negation (complementary).
    """

    book: str
    event_id: str
    market_type: MarketType
    period: Period = Period.FULL_GAME
    player_id: str | None = None
    team_id: str | None = Field(
        default=None, description="For TEAM_TOTAL references: the team the total belongs to"
    )
    line: Decimal | None = None
    side_a: Side
    odds_a: DecimalOdds
    side_b: Side
    odds_b: DecimalOdds
    stamp: SourceStamp

    @model_validator(mode="after")
    def _complementary(self) -> ReferenceTwoWay:
        pair = {self.side_a, self.side_b}
        if pair not in ({Side.HOME, Side.AWAY}, {Side.OVER, Side.UNDER}):
            raise ValueError("reference sides must be HOME/AWAY or OVER/UNDER")
        if self.market_type in (MarketType.MONEYLINE, MarketType.SPREAD) and pair != {Side.HOME, Side.AWAY}:
            raise ValueError("team win/spread references use HOME/AWAY")
        if self.market_type not in (MarketType.MONEYLINE, MarketType.SPREAD) and pair != {
            Side.OVER,
            Side.UNDER,
        }:
            raise ValueError("totals/props references use OVER/UNDER")
        if self.market_type != MarketType.MONEYLINE and self.line is None:
            raise ValueError("reference requires a line for this market")
        return self

    def odds_for(self, side: Side) -> Decimal:
        if side == self.side_a:
            return self.odds_a
        if side == self.side_b:
            return self.odds_b
        raise KeyError(side)

    def opposite(self, side: Side) -> Side:
        return self.side_b if side == self.side_a else self.side_a


class Selection(Model):
    selection_id: str
    quote: MarketQuote
    event: Event
    team: Team | None = None
    player: Player | None = None
    description: str

    @model_validator(mode="after")
    def _ids_match(self) -> Selection:
        if self.quote.event_id != self.event.event_id:
            raise ValueError("selection quote/event mismatch")
        expected = compute_selection_id(self.quote)
        if self.selection_id != expected:
            raise ValueError(f"selection_id must be deterministic ({expected})")
        return self


class ThreeLegTicket(Model):
    legs: list[Selection]
    parlay_type: ParlayType | None = Field(default=None, description="Derived from the legs when omitted")

    @model_validator(mode="after")
    def _exactly_three_distinct(self) -> ThreeLegTicket:
        if len(self.legs) != 3:
            raise ValueError("NOT_THREE_LEGS: a ticket must contain exactly three selections")
        ids = {leg.selection_id for leg in self.legs}
        if len(ids) != 3:
            raise ValueError("DUPLICATE_SELECTION: selections must be distinct")
        tuples = {leg.quote.identity_tuple() for leg in self.legs}
        if len(tuples) != 3:
            raise ValueError("DUPLICATE_SELECTION: selections must be distinct markets")
        events = {leg.event.event_id for leg in self.legs}
        derived = (
            ParlayType.MULTI_GAME
            if len(events) == 3
            else ParlayType.SAME_GAME
            if len(events) == 1
            else ParlayType.MIXED
        )
        if self.parlay_type is None:
            object.__setattr__(self, "parlay_type", derived)
        elif self.parlay_type != derived:
            raise ValueError(f"parlay_type {self.parlay_type} does not match legs ({derived})")
        return self

    @property
    def event_ids(self) -> list[str]:
        return [leg.event.event_id for leg in self.legs]


class InjuryContext(Model):
    event_id: str
    team_id: str | None = None
    player_id: str | None = None
    player_name_raw: str | None = None
    designation: InjuryDesignation
    reason: str | None = None
    report_timestamp_utc: UtcDatetime | None = None
    stamp: SourceStamp
    material_to_selection: bool | None = None
    note: str | None = None


class SourcedFact(Model):
    text: str
    stamp: SourceStamp


class DataQuality(Model):
    """Data-quality grade. This is NOT a win probability."""

    grade: Literal["A", "B", "C", "D"]
    checks: dict[str, bool]
    notes: list[str] = Field(default_factory=list)


class ProbabilityEstimate(Model):
    value: Probability | None = Field(default=None, description="None when INSUFFICIENT_EVIDENCE")
    state: ModelState
    method: str
    reference_book: str | None = None
    reference_stamp: SourceStamp | None = None
    assumptions: list[str] = Field(default_factory=list)


class PriceValue(Model):
    target_decimal: DecimalOdds
    fair_decimal: Decimal | None = Field(default=None, description="1 / reference probability")
    edge_per_dollar: Decimal | None = Field(
        default=None, description="p_reference * target_decimal - 1; None without a reference"
    )
    note: str


class LegAnalysis(Model):
    selection_id: str
    facts: list[SourcedFact] = Field(default_factory=list)
    interpretations: list[str] = Field(default_factory=list)
    strongest_reason_against: str
    injury: list[InjuryContext] = Field(default_factory=list)
    data_quality: DataQuality
    probability: ProbabilityEstimate
    price_value: PriceValue
    decision: LegDecision
    reason_codes: list[str] = Field(default_factory=list)
    analyzed_at_utc: UtcDatetime


class CorrelationFlag(Model):
    type: CorrelationType
    leg_indexes: list[int]
    severity: Severity
    explanation: str


class CorrelationReport(Model):
    flags: list[CorrelationFlag] = Field(default_factory=list)
    joint_numeric_allowed: bool = Field(
        description="False whenever legs share an event or a BLOCKING shared-assumption flag exists"
    )
    weakest_assumption: str
    explanation: str


class BookQuote(Model):
    """The sportsbook's combined quote for a ticket, supplied by the user (typed, screenshot, or receipt)."""

    book_quote_id: str
    candidate_id: str
    combined_decimal: DecimalOdds
    combined_american: AmericanOdds | None = None
    stake_shown_usd: Money | None = None
    payout_shown_usd: Money | None = None
    payout_includes_stake: bool | None = None
    legs_as_shown: list[str] = Field(default_factory=list)
    source: QuoteSource
    captured_at_utc: UtcDatetime
    confirmed_by_user: bool = False
    unresolved_fields: list[str] = Field(default_factory=list)


class PayoutMath(Model):
    combined_decimal: Decimal | None
    combined_source: Literal["BOOK_QUOTE", "INDICATIVE_MULTIPLIED", "NONE"]
    stake_usd: Money
    gross_return_usd: Decimal | None = None
    net_profit_usd: Decimal | None = None
    max_loss_usd: Money
    break_even_probability: Decimal | None = None
    assumptions: list[str] = Field(default_factory=list)


class Candidate(Model):
    candidate_id: str
    user_id: str
    created_at_utc: UtcDatetime
    updated_at_utc: UtcDatetime
    state: CandidateState
    parlay_type: ParlayType
    ticket: ThreeLegTicket
    leg_analyses: list[LegAnalysis]
    correlation: CorrelationReport
    indicative_multiplied_decimal: DecimalOdds
    book_quote: BookQuote | None = None
    model_state: ModelState
    p_joint: Probability | None = None
    p_joint_method: str
    ev_per_dollar: Decimal | None = None
    payout: PayoutMath
    rationale: str
    rechecks_required: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    ranking: dict[str, str] = Field(default_factory=dict)
    inputs_snapshot_utc: UtcDatetime
    expires_at_utc: UtcDatetime
    data_mode: DataMode
    ai_disclosure: str = AI_DISCLOSURE

    @model_validator(mode="after")
    def _consistent(self) -> Candidate:
        if len(self.leg_analyses) != 3:
            raise ValueError("a candidate needs exactly three leg analyses")
        if self.parlay_type != self.ticket.parlay_type:
            raise ValueError("candidate parlay_type must match the ticket")
        if self.ev_per_dollar is not None and self.p_joint is None:
            raise ValueError("ev_per_dollar requires p_joint")
        return self


class BudgetReservation(Model):
    reservation_id: str
    user_id: str
    date_local: LocalDate
    candidate_id: str
    stake_usd: Money
    status: ReservationStatus
    idempotency_key: str
    created_at_utc: UtcDatetime
    expires_at_utc: UtcDatetime
    released_reason: str | None = None


class DailyBudget(Model):
    date_local: LocalDate
    cap_usd: Money
    recorded_stake_usd: Money
    reserved_stake_usd: Money
    proposed_stake_usd: Money | None = None
    remaining_usd: Money = Field(
        description="max(0, cap - recorded - reserved); see breaches for negative raw values"
    )
    raw_remaining_usd: Decimal = Field(
        description="cap - recorded - reserved, may be negative after a breach"
    )
    breaches: list[str] = Field(default_factory=list)
    note: str = "Application budget ledger (America/New_York calendar day). Not a sportsbook account limit."


class AcceptedLeg(Model):
    description: str
    event_id: str | None = None
    market_type: MarketType | None = None
    period: Period | None = None
    side: Side | None = None
    line: Decimal | None = None
    player_name: str | None = None
    player_id: str | None = None
    team_name: str | None = None
    team_id: str | None = None
    accepted_decimal: DecimalOdds | None = None
    result: LegResult = LegResult.PENDING


class ActualBet(Model):
    bet_id: str
    user_id: str
    date_local: LocalDate
    candidate_id: str | None = None
    reservation_id: str | None = None
    book: str
    ticket_ref: str | None = None
    legs: list[AcceptedLeg]
    external: bool = Field(description="True for a wager the user reports that this tool did not prepare")
    accepted_combined_decimal: DecimalOdds | None = None
    recommended_combined_decimal: DecimalOdds | None = None
    stake_usd: Money
    placed_at_utc: UtcDatetime
    source: BetSource
    idempotency_key: str
    payload_hash: str
    breach_flags: list[str] = Field(default_factory=list)
    status: BetStatus = BetStatus.PENDING
    created_at_utc: UtcDatetime
    notes: str | None = None

    @model_validator(mode="after")
    def _legs(self) -> ActualBet:
        if not self.external and len(self.legs) != 3:
            raise ValueError("NOT_THREE_LEGS: a tool-prepared bet must have exactly three legs")
        if not self.legs:
            raise ValueError("a bet needs at least one leg")
        return self


class SettlementRecord(Model):
    settlement_id: str
    bet_id: str
    user_id: str
    seq: int
    status: BetStatus
    source: SettlementSource
    cash_returned_usd: Money | None = None
    bonus_returned_usd: Money | None = None
    repriced_combined_decimal: DecimalOdds | None = None
    leg_results: list[LegResult] = Field(default_factory=list)
    settled_at_utc: UtcDatetime | None = None
    notes: str | None = None
    payload_hash: str
    created_at_utc: UtcDatetime


class CostEntry(Model):
    cost_id: str
    user_id: str
    date_local: LocalDate
    description: str
    amount_usd: Money
    category: Literal["DATA", "SOFTWARE", "HOSTING", "OTHER"]
    created_at_utc: UtcDatetime


class UserSettings(Model):
    user_id: str
    daily_cap_usd: Money
    display_tz: str
    onboarding_complete: bool
    has_own_odds_api_key: bool
    created_at_utc: UtcDatetime
    updated_at_utc: UtcDatetime


class CoverageItem(Model):
    status: CoverageStatus
    detail: str
    reason_codes: list[str] = Field(default_factory=list)
    stamp: SourceStamp | None = None


class CoverageReport(Model):
    date_local: LocalDate
    generated_at_utc: UtcDatetime
    data_mode: DataMode
    hard_rock_single_leg: dict[str, CoverageItem] = Field(description="keyed by MarketType value")
    reference_markets: dict[str, CoverageItem]
    injury_information: CoverageItem
    three_leg_combinability: CoverageItem
    combined_payout_verification: CoverageItem
    stats_and_settlement_rules: CoverageItem
    provider_quota: dict[str, int | None] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class SystemStatus(Model):
    app_version: str
    now_utc: UtcDatetime
    now_display: str
    display_tz: str
    auth_mode: str
    user_id_masked: str
    database_ok: bool
    database_kind: str
    provider_configured: bool
    provider_last_ok_utc: UtcDatetime | None = None
    provider_quota: dict[str, int | None] = Field(default_factory=dict)
    data_modes_available: list[DataMode]
    target_book: str
    jurisdiction: str
    daily_cap_usd: Money
    onboarding_complete: bool
    warnings: list[str] = Field(default_factory=list)
    ai_disclosure: str = AI_DISCLOSURE


class ToolError(Model):
    error: str
    reason_codes: list[str] = Field(default_factory=list)
    detail: str | None = None


# --------------------------------------------------------------------------------------
# Results / stats (settlement providers)
# --------------------------------------------------------------------------------------


class GameResult(Model):
    event_id: str
    home_team_id: str | None = None
    away_team_id: str | None = None
    home_score: int | None = None
    away_score: int | None = None
    completed: bool
    status: EventStatus
    stamp: SourceStamp


class PlayerGameStat(Model):
    event_id: str
    player_id: str | None = None
    player_name_raw: str
    team_id: str | None = None
    played: bool
    minutes: Decimal | None = None
    points: int | None = None
    rebounds: int | None = None
    assists: int | None = None
    threes: int | None = None
    stamp: SourceStamp


class ProviderProbe(Model):
    provider: str
    auth_ok: bool | None
    nba_active: bool | None
    target_book_present: bool | None
    reference_books_present: dict[str, bool] = Field(default_factory=dict)
    quota: dict[str, int | None] = Field(default_factory=dict)
    checked_at_utc: UtcDatetime
    warnings: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------------------
# Manual-import inputs (tool arguments)
# --------------------------------------------------------------------------------------


class ManualSelectionInput(Model):
    """One pasted leg. Provide american or decimal odds (both are cross-checked when present)."""

    game: str = Field(description='e.g. "Heat @ Magic", "MIA@ORL", or an event_id from the slate')
    market: MarketType
    period: Period = Period.FULL_GAME
    is_alternate: bool = False
    side: Side
    line: Decimal | None = None
    player_name: str | None = None
    team: str | None = Field(
        default=None, description="Team name or abbreviation; required for TEAM_TOTAL legs"
    )
    odds_american: AmericanOdds | None = None
    odds_decimal: DecimalOdds | None = None
    book: str = "hardrockbet_fl"
    observed_at_utc: UtcDatetime | None = None

    @model_validator(mode="after")
    def _odds(self) -> ManualSelectionInput:
        if self.odds_american is None and self.odds_decimal is None:
            raise ValueError("QUOTE_FIELDS_MISSING: provide odds_american or odds_decimal")
        if self.odds_american is not None and self.odds_decimal is not None:
            a = self.odds_american
            implied = Decimal(1) + (Decimal(a) / Decimal(100) if a > 0 else Decimal(100) / Decimal(abs(a)))
            if abs(implied - self.odds_decimal) > Decimal("0.0105"):
                raise ValueError("QUOTE_SIGN_AMBIGUOUS: american and decimal odds disagree")
        return self


class ManualQuoteInput(Model):
    """The slip's combined quote as shown by the sportsbook."""

    combined_decimal: DecimalOdds | None = None
    combined_american: AmericanOdds | None = None
    stake_shown_usd: Money | None = None
    payout_shown_usd: Money | None = None
    payout_includes_stake: bool | None = None
    legs_as_shown: list[str] = Field(default_factory=list)
    source: QuoteSource = QuoteSource.USER_TYPED
    captured_at_utc: UtcDatetime | None = None
    user_confirmed: bool = False


class ConfirmedTicketInput(Model):
    candidate_id: str | None = None
    book: str = "hardrockbet_fl"
    ticket_ref: str | None = None
    legs: list[AcceptedLeg]
    accepted_combined_decimal: DecimalOdds | None = None
    accepted_combined_american: AmericanOdds | None = None
    stake_usd: Money
    placed_at_utc: UtcDatetime | None = None
    source: BetSource = BetSource.USER_CONFIRMATION
    external: bool = False
    notes: str | None = None


class SettlementInput(Model):
    status: BetStatus
    source: SettlementSource = SettlementSource.BOOK_CONFIRMED
    cash_returned_usd: Money | None = None
    bonus_returned_usd: Money | None = None
    repriced_combined_decimal: DecimalOdds | None = None
    leg_results: list[LegResult] | None = None
    settled_at_utc: UtcDatetime | None = None
    notes: str | None = None


class CostInput(Model):
    date_local: LocalDate
    description: str
    amount_usd: Money
    category: Literal["DATA", "SOFTWARE", "HOSTING", "OTHER"] = "DATA"
    idempotency_key: str | None = None


# --------------------------------------------------------------------------------------
# Service responses
# --------------------------------------------------------------------------------------


class EventSummary(Model):
    event_id: str
    away: str
    home: str
    commence_time_utc: UtcDatetime
    commence_time_display: str
    status: EventStatus
    season_stage: str


class SlateResponse(Model):
    date_local: LocalDate
    events: list[EventSummary]
    data_mode: DataMode
    stamps: list[SourceStamp] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


class InjuryResponse(Model):
    event_id: str
    entries: list[InjuryContext]
    report_timestamp_utc: UtcDatetime | None = None
    stamp: SourceStamp | None = None
    warnings: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)


class BuildResponse(Model):
    date_local: LocalDate
    candidates: list[Candidate]
    primary_candidate_id: str | None = None
    no_ticket_reason: str | None = Field(default=None, description="Set when NO SUITABLE TICKET")
    reason_codes: list[str] = Field(default_factory=list)
    coverage_summary: dict[str, str] = Field(default_factory=dict)
    data_mode: DataMode
    credits_used: int | None = None
    legs_considered: int = 0
    combinations_evaluated: int = 0
    warnings: list[str] = Field(default_factory=list)
    ai_disclosure: str = AI_DISCLOSURE


class SelectResponse(Model):
    candidate: Candidate
    reservation: BudgetReservation
    budget: DailyBudget
    replay: bool = False


class RecordResponse(Model):
    bet: ActualBet
    budget: DailyBudget
    replay: bool = False
    breach_flags: list[str] = Field(default_factory=list)


class SettlementResponse(Model):
    bet: ActualBet
    settlement: SettlementRecord
    replay: bool = False
    warnings: list[str] = Field(default_factory=list)


class Ratio(Model):
    numerator: int
    denominator: int
    value: Decimal | None = Field(default=None, description="None when denominator is 0")


class PerfBucket(Model):
    tickets: int
    stake_usd: Money
    cash_returned_usd: Money
    net_usd: Decimal
    won: int
    lost: int
    void_or_other: int
    pending: int


class OddsDelta(Model):
    bet_id: str
    recommended_decimal: Decimal | None
    accepted_decimal: Decimal | None
    delta: Decimal | None


class CalibrationPoint(Model):
    bet_id: str
    forecast_p_joint: Decimal
    model_state: ModelState
    outcome: Literal["WON", "LOST", "VOID", "PENDING"]


class BetSummary(Model):
    bet_id: str
    date_local: LocalDate
    parlay_type: str | None
    stake_usd: Money
    accepted_decimal: Decimal | None
    status: BetStatus
    cash_returned_usd: Decimal | None
    net_usd: Decimal | None
    provisional: bool
    leg_results: list[LegResult]


class PerformanceReport(Model):
    start_date: LocalDate
    end_date: LocalDate
    generated_at_utc: UtcDatetime
    tickets_placed: int
    total_stake_usd: Money
    settled_tickets: int
    total_cash_returned_usd: Money
    net_profit_usd: Decimal
    pending_exposure_usd: Money
    voids: int
    ticket_win_rate: Ratio
    leg_hit_rate: Ratio
    by_parlay_type: dict[str, PerfBucket] = Field(default_factory=dict)
    by_market_composition: dict[str, PerfBucket] = Field(default_factory=dict)
    accepted_vs_recommended: list[OddsDelta] = Field(default_factory=list)
    calibration: list[CalibrationPoint] = Field(default_factory=list)
    data_costs_usd: Money
    after_cost_net_usd: Decimal
    bets: list[BetSummary] = Field(default_factory=list)
    incomplete_data_notes: list[str] = Field(default_factory=list)
    late_injury_notes: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ReviewReport(Model):
    window_start: LocalDate
    window_end: LocalDate
    generated_at_utc: UtcDatetime
    performance: PerformanceReport
    max_possible_gross_stake_usd: Money
    days_with_bets: int
    observed_results: list[str]
    evidence_of_skill: list[str]
    dependence_and_sample_notes: list[str]
    continue_operation_note: str


class ExportBundle(Model):
    user_id_masked: str
    exported_at_utc: UtcDatetime
    tables: dict[str, list[dict[str, Any]]]


__all__ = [name for name in globals() if not name.startswith("_")]
