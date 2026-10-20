"""Settlement: append-only reconciliation of a bet's outcome, and provisional grading from NBA results.

Authority
- ``BOOK_CONFIRMED`` (Hard Rock's own settlement, as reported by the user) is authoritative: it updates
  ``bets.status`` and the per-leg results inside the bet record.
- ``PROVISIONAL_NBA_RESULTS`` never supersedes a book settlement. When no book settlement exists it may
  move the bet between PENDING/WON/LOST (flagged PROVISIONAL_RESULT); it is always appended as its own
  record so repeated checks do not double-count anything. Once a book record exists it governs the bet
  whatever is appended later: ``effective_settlement`` returns the latest BOOK_CONFIRMED record when
  one exists, else the latest record.
- Every record carries a payload hash chained to the preceding ``seq``. A payload identical to the
  LATEST record is a replay and adds no row; a payload identical to an older record is a new event
  (the book reverting a correction, for instance) and is appended.

Money
- Cash profit of a settled ticket = confirmed cash returned - original cash stake. Returns include the
  original stake where applicable (a $10 ticket at 5.50 returns $55 and earns $45).
- Only BOOK_CONFIRMED records carry cash defaults (VOID -> stake, LOST -> 0.00) and only they yield a
  cash profit. A provisional record stores just what the caller supplied and never moves net profit:
  NBA results cannot state what the book pays.
- Bonus credits are stored separately (``bonus_returned_usd``) and never mixed into cash profit.

House-rule conventions used for provisional grading (docs/research/hard-rock-house-rules.md): full-game
markets include overtime; a push (spread/total/prop landing exactly on the line) voids the leg; a player
who does not see court time voids the prop; a parlay with a void leg stands on the remaining legs at a
recalculated payout that only the book can state, so a provisional partial void carries no cash figure.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from sqlalchemy import insert, select

from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.actual_bets import bet_from_row, persist_bet, settlement_from_row
from hardrock_nba_parlay.budget import LedgerError, NotFoundError, q_money, q_odds, write_audit
from hardrock_nba_parlay.db import Database, bets, cents, dumps, iso, new_id, settlements

_NON_BINARY_STATUSES: frozenset[S.BetStatus] = frozenset({S.BetStatus.PENDING, S.BetStatus.DISPUTED})
_PROVISIONAL_APPLIES: frozenset[S.BetStatus] = frozenset(
    {S.BetStatus.PENDING, S.BetStatus.WON, S.BetStatus.LOST}
)


def canonical_settlement_json(s: S.SettlementInput) -> str:
    """Canonical JSON of a settlement input: money 2 dp, odds 4 dp, datetimes ISO UTC, sorted keys.

    Two inputs that differ only in Decimal spelling (``3.2`` vs ``3.20``) or datetime offset spelling
    produce the same string, so they hash the same and replay.
    """
    payload = {
        "status": s.status.value,
        "source": s.source.value,
        "cash_returned_usd": None if s.cash_returned_usd is None else str(q_money(s.cash_returned_usd)),
        "bonus_returned_usd": None if s.bonus_returned_usd is None else str(q_money(s.bonus_returned_usd)),
        "repriced_combined_decimal": None
        if s.repriced_combined_decimal is None
        else str(q_odds(s.repriced_combined_decimal)),
        "leg_results": None if s.leg_results is None else [r.value for r in s.leg_results],
        "settled_at_utc": iso(s.settled_at_utc),
        "notes": s.notes,
    }
    return dumps(payload)


def settlement_payload_hash(s: S.SettlementInput, prev_seq: int = 0) -> str:
    """sha256 of ``prev_seq`` plus the canonical settlement JSON.

    The hash is chained to the ``seq`` of the record it follows, so the same payload appended at two
    different points in a bet's history yields two different hashes (the database enforces
    UNIQUE(bet_id, payload_hash)) while a resend of the latest record still matches it exactly.
    """
    material = f"{prev_seq}\n{canonical_settlement_json(s)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def list_settlements(db: Database, user_id: str, bet_id: str) -> list[S.SettlementRecord]:
    """All settlement records of this user's bet in ``seq`` order (empty for another user's bet)."""
    with db.engine.connect() as conn:
        rows = conn.execute(
            select(settlements)
            .where(settlements.c.bet_id == bet_id, settlements.c.user_id == user_id)
            .order_by(settlements.c.seq)
        ).all()
    return [settlement_from_row(r) for r in rows]


def reconcile(
    db: Database, user_id: str, bet_id: str, s: S.SettlementInput, now: datetime
) -> tuple[S.ActualBet, S.SettlementRecord, bool, list[str]]:
    """Append a settlement record for ``bet_id`` and apply it per the authority rules.

    Returns ``(bet_after, record, replay, warnings)``. Warnings use section-7 codes:
    IDEMPOTENT_REPLAY, SUPERSEDED_BY_BOOK, PROVISIONAL_RESULT, SETTLEMENT_RULES_UNKNOWN.

    Replay: a payload identical to the bet's LATEST settlement record returns that record with
    ``replay=True`` and no new row. A payload identical to an older record is a new event (seq last+1).

    Status rules (BOOK_CONFIRMED)
    - VOID: ``cash_returned_usd`` defaults to the stake. LOST: defaults to 0.00.
    - PARTIALLY_VOID / REPRICED: need ``repriced_combined_decimal`` or ``cash_returned_usd``; otherwise
      the status is stored anyway with warning SETTLEMENT_RULES_UNKNOWN (no cash figure is invented).
    - CASHED_OUT: ``cash_returned_usd`` is required (``LedgerError`` INVALID_INPUT otherwise).
    - DISPUTED: the bet status becomes DISPUTED; no profit is reported until resolved.
    - CORRECTED: supersedes prior values; the latest record carries the corrected figures.
    PROVISIONAL_NBA_RESULTS records get no cash defaults: they store only what the caller supplied
    (``provisional_from_results`` supplies none) and never yield a cash profit.
    Leg results, when given, must match the bet's leg count and are written into the bet only for
    BOOK_CONFIRMED records; provisional leg results stay on their settlement record.
    """
    if s.status == S.BetStatus.CASHED_OUT and s.cash_returned_usd is None:
        raise LedgerError("INVALID_INPUT", "INVALID_INPUT: CASHED_OUT requires cash_returned_usd")
    is_book = s.source == S.SettlementSource.BOOK_CONFIRMED

    with db.tx() as conn:
        row = conn.execute(select(bets).where(bets.c.bet_id == bet_id, bets.c.user_id == user_id)).first()
        if row is None:
            raise NotFoundError(message="NOT_FOUND: bet not found for this user")
        db.lock_user_day(conn, user_id, row.date_local, now)
        bet = bet_from_row(row)

        if s.leg_results is not None and len(s.leg_results) != len(bet.legs):
            raise LedgerError(
                "INVALID_INPUT",
                f"INVALID_INPUT: leg_results has {len(s.leg_results)} entries, bet has {len(bet.legs)} legs",
            )

        prior = conn.execute(
            select(settlements)
            .where(settlements.c.bet_id == bet_id, settlements.c.user_id == user_id)
            .order_by(settlements.c.seq)
        ).all()
        latest_row = prior[-1] if prior else None
        last_seq = latest_row.seq if latest_row is not None else 0
        if latest_row is not None and latest_row.payload_hash == settlement_payload_hash(s, last_seq - 1):
            return bet, settlement_from_row(latest_row), True, ["IDEMPOTENT_REPLAY"]
        payload_hash = settlement_payload_hash(s, last_seq)
        has_book = any(p.source == S.SettlementSource.BOOK_CONFIRMED.value for p in prior)

        warnings: list[str] = []
        status = s.status
        cash = q_money(s.cash_returned_usd) if s.cash_returned_usd is not None else None
        repriced = s.repriced_combined_decimal
        if is_book and status == S.BetStatus.VOID and cash is None:
            cash = bet.stake_usd
        elif is_book and status == S.BetStatus.LOST and cash is None:
            cash = Decimal("0.00")
        elif (
            status in (S.BetStatus.PARTIALLY_VOID, S.BetStatus.REPRICED) and cash is None and repriced is None
        ):
            warnings.append("SETTLEMENT_RULES_UNKNOWN")

        apply_status = False
        apply_legs = False
        if not is_book:
            if has_book:
                warnings.append("SUPERSEDED_BY_BOOK")
            else:
                warnings.append("PROVISIONAL_RESULT")
                apply_status = status in _PROVISIONAL_APPLIES
        else:
            apply_status = True
            apply_legs = s.leg_results is not None

        record = S.SettlementRecord(
            settlement_id=new_id("stl"),
            bet_id=bet_id,
            user_id=user_id,
            seq=last_seq + 1,
            status=status,
            source=s.source,
            cash_returned_usd=cash,
            bonus_returned_usd=s.bonus_returned_usd,
            repriced_combined_decimal=repriced,
            leg_results=list(s.leg_results) if s.leg_results is not None else [],
            settled_at_utc=s.settled_at_utc,
            notes=s.notes,
            payload_hash=payload_hash,
            created_at_utc=now,
        )
        conn.execute(
            insert(settlements).values(
                settlement_id=record.settlement_id,
                bet_id=bet_id,
                user_id=user_id,
                seq=record.seq,
                status=record.status.value,
                source=record.source.value,
                cash_returned_cents=cents(cash) if cash is not None else None,
                bonus_returned_cents=cents(s.bonus_returned_usd)
                if s.bonus_returned_usd is not None
                else None,
                payload_hash=payload_hash,
                json=dumps(record.model_dump(mode="json")),
                created_at=iso(now),
            )
        )

        if apply_status:
            bet.status = status
        if apply_legs and s.leg_results is not None:
            for leg, result in zip(bet.legs, s.leg_results, strict=True):
                leg.result = result
        if apply_status or apply_legs:
            persist_bet(conn, bet)

        write_audit(
            conn,
            user_id,
            "settlement.append",
            record.settlement_id,
            {
                "bet_id": bet_id,
                "seq": record.seq,
                "status": status.value,
                "source": s.source.value,
                "applied_to_bet": apply_status,
                "warnings": warnings,
            },
            now,
        )
        return bet, record, False, warnings


# --------------------------------------------------------------------------------------
# Profit and effective leg results
# --------------------------------------------------------------------------------------


def effective_settlement(records: Sequence[S.SettlementRecord]) -> S.SettlementRecord | None:
    """The record that governs a bet: the latest BOOK_CONFIRMED record when any exists, else the latest.

    A provisional record appended after a book settlement (the nightly job re-running with a new stamp)
    is SUPERSEDED_BY_BOOK and must not displace the book's figures in reports.
    """
    if not records:
        return None
    book = [r for r in records if r.source == S.SettlementSource.BOOK_CONFIRMED]
    pool = book or list(records)
    return max(pool, key=lambda r: r.seq)


def current_effective_settlement(db: Database, user_id: str, bet_id: str) -> S.SettlementRecord | None:
    """``effective_settlement`` over every record of this user's bet (``None`` when there is none)."""
    return effective_settlement(list_settlements(db, user_id, bet_id))


def cash_profit(bet: S.ActualBet, settlement: S.SettlementRecord | None) -> Decimal | None:
    """Confirmed cash returned minus the original cash stake (returns include the stake).

    ``None`` when there is no settlement, the record is not BOOK_CONFIRMED (no confirmed figure, no
    profit), there is no cash figure, or the settlement status is PENDING or DISPUTED. Bonus credits
    are not included.
    """
    if settlement is None or settlement.cash_returned_usd is None:
        return None
    if settlement.source != S.SettlementSource.BOOK_CONFIRMED:
        return None
    if settlement.status in _NON_BINARY_STATUSES:
        return None
    return q_money(settlement.cash_returned_usd - bet.stake_usd)


def _settlement_legs(bet: S.ActualBet, settlement: S.SettlementRecord | None) -> list[S.LegResult] | None:
    if settlement is not None and settlement.leg_results and len(settlement.leg_results) == len(bet.legs):
        return list(settlement.leg_results)
    return None


def effective_leg_results(bet: S.ActualBet, settlement: S.SettlementRecord | None) -> list[S.LegResult]:
    """Per-leg results to report.

    Book leg results are written into the bet record, so a bet with any graded leg is book-graded and
    those legs win over a provisional record. Otherwise the settlement's own list is used when it
    matches the leg count, else the bet's legs (all PENDING when nothing has graded them).
    """
    bet_legs = [leg.result for leg in bet.legs]
    if settlement is None:
        return bet_legs
    book_graded = any(r != S.LegResult.PENDING for r in bet_legs)
    if settlement.source != S.SettlementSource.BOOK_CONFIRMED and book_graded:
        return bet_legs
    return _settlement_legs(bet, settlement) or bet_legs


def ticket_outcome(bet: S.ActualBet, settlement: S.SettlementRecord | None) -> S.BetStatus | None:
    """WON or LOST when the ticket has a binary result, else ``None``.

    - WON / LOST: the status itself (a provisional status counts; reports label it provisional).
    - CORRECTED: a 0.00 cash return is LOST; otherwise the corrected leg results decide (the record's
      own list, else the legs the book last wrote into the bet): any LOST -> LOST, all WON -> WON.
    - Every other status (VOID, PARTIALLY_VOID, REPRICED, CASHED_OUT, PENDING, DISPUTED) has no binary
      result and belongs outside the ticket win rate.
    """
    if bet.status in (S.BetStatus.WON, S.BetStatus.LOST):
        return bet.status
    if bet.status != S.BetStatus.CORRECTED:
        return None
    if (
        settlement is not None
        and settlement.source == S.SettlementSource.BOOK_CONFIRMED
        and settlement.cash_returned_usd is not None
        and settlement.cash_returned_usd == Decimal("0.00")
    ):
        return S.BetStatus.LOST
    legs = effective_leg_results(bet, settlement)
    if any(r == S.LegResult.LOST for r in legs):
        return S.BetStatus.LOST
    if legs and all(r == S.LegResult.WON for r in legs):
        return S.BetStatus.WON
    return None


# --------------------------------------------------------------------------------------
# Provisional grading from independently sourced NBA results
# --------------------------------------------------------------------------------------

_NAME_STRIP = re.compile(r"[^a-z0-9 ]+")


def _norm_name(name: str | None) -> str:
    if not name:
        return ""
    return " ".join(_NAME_STRIP.sub(" ", name.lower()).split())


def _compare(actual: Decimal, line: Decimal, side: S.Side) -> S.LegResult:
    if actual == line:
        return S.LegResult.VOID  # push: the leg is voided and the parlay recalculated by the book
    if side == S.Side.OVER:
        return S.LegResult.WON if actual > line else S.LegResult.LOST
    if side == S.Side.UNDER:
        return S.LegResult.WON if actual < line else S.LegResult.LOST
    return S.LegResult.PENDING


def _team_side(leg: S.AcceptedLeg, events: dict[str, S.Event]) -> S.Side | None:
    """Resolve a TEAM_TOTAL leg's team to HOME/AWAY using the event's teams; ``None`` when unknown."""
    if leg.event_id is None or leg.event_id not in events:
        return None
    event = events[leg.event_id]
    wanted = _norm_name(leg.team_name)
    if not wanted:
        return None
    for side, team in ((S.Side.HOME, event.home_team), (S.Side.AWAY, event.away_team)):
        names = {
            _norm_name(team.name),
            _norm_name(team.abbreviation),
            _norm_name(team.team_id.split(":")[-1]),
        }
        if wanted in names or wanted == _norm_name(team.name.split()[-1]):
            return side
    return None


def _grade_team_leg(leg: S.AcceptedLeg, result: S.GameResult, events: dict[str, S.Event]) -> S.LegResult:
    if result.home_score is None or result.away_score is None or leg.side is None:
        return S.LegResult.PENDING
    home = Decimal(result.home_score)
    away = Decimal(result.away_score)
    market = leg.market_type
    if market == S.MarketType.MONEYLINE:
        if home == away:
            return S.LegResult.VOID
        home_won = home > away
        if leg.side == S.Side.HOME:
            return S.LegResult.WON if home_won else S.LegResult.LOST
        if leg.side == S.Side.AWAY:
            return S.LegResult.LOST if home_won else S.LegResult.WON
        return S.LegResult.PENDING
    if market == S.MarketType.SPREAD:
        if leg.line is None:
            return S.LegResult.PENDING
        if leg.side == S.Side.HOME:
            margin = home - away + leg.line
        elif leg.side == S.Side.AWAY:
            margin = away - home + leg.line
        else:
            return S.LegResult.PENDING
        if margin == 0:
            return S.LegResult.VOID
        return S.LegResult.WON if margin > 0 else S.LegResult.LOST
    if market == S.MarketType.TOTAL:
        if leg.line is None:
            return S.LegResult.PENDING
        return _compare(home + away, leg.line, leg.side)
    if market == S.MarketType.TEAM_TOTAL:
        if leg.line is None:
            return S.LegResult.PENDING
        team_side = _team_side(leg, events)
        if team_side is None:
            return S.LegResult.PENDING
        return _compare(home if team_side == S.Side.HOME else away, leg.line, leg.side)
    return S.LegResult.PENDING


def _stat_value(stat: S.PlayerGameStat, market: S.MarketType) -> int | None:
    return {
        S.MarketType.PLAYER_POINTS: stat.points,
        S.MarketType.PLAYER_REBOUNDS: stat.rebounds,
        S.MarketType.PLAYER_ASSISTS: stat.assists,
        S.MarketType.PLAYER_THREES: stat.threes,
    }.get(market)


def _grade_player_leg(leg: S.AcceptedLeg, stats: Sequence[S.PlayerGameStat]) -> S.LegResult:
    if leg.side is None or leg.line is None or leg.market_type is None:
        return S.LegResult.PENDING
    wanted = _norm_name(leg.player_name)
    if not wanted:
        return S.LegResult.PENDING
    stat = next(
        (st for st in stats if st.event_id == leg.event_id and _norm_name(st.player_name_raw) == wanted), None
    )
    if stat is None:
        return S.LegResult.PENDING
    if not stat.played:
        return S.LegResult.VOID  # no court time: the prop has no action
    value = _stat_value(stat, leg.market_type)
    if value is None:
        return S.LegResult.PENDING
    return _compare(Decimal(value), leg.line, leg.side)


def grade_leg(
    leg: S.AcceptedLeg,
    results: dict[str, S.GameResult],
    stats: Sequence[S.PlayerGameStat],
    events: dict[str, S.Event],
) -> S.LegResult:
    """Grade one leg from NBA results. PENDING whenever the event is not completed or data is missing.

    Only FULL_GAME (overtime included) is graded; other periods stay PENDING (PERIOD_UNSUPPORTED).
    """
    if leg.event_id is None or leg.market_type is None:
        return S.LegResult.PENDING
    if leg.period not in (None, S.Period.FULL_GAME):
        return S.LegResult.PENDING
    result = results.get(leg.event_id)
    if result is None or not result.completed or result.status != S.EventStatus.FINAL:
        return S.LegResult.PENDING
    if leg.market_type in S.TEAM_MARKETS:
        return _grade_team_leg(leg, result, events)
    if leg.market_type in S.PLAYER_MARKETS:
        return _grade_player_leg(leg, stats)
    return S.LegResult.PENDING


def provisional_from_results(
    bet: S.ActualBet,
    results: Sequence[S.GameResult],
    stats: Sequence[S.PlayerGameStat],
    events: Sequence[S.Event] | None = None,
) -> S.SettlementInput | None:
    """Build a PROVISIONAL_NBA_RESULTS settlement input from game results and player stats.

    Aggregation: any LOST leg -> LOST; any PENDING leg (and none lost) -> PENDING; all WON -> WON;
    all VOID -> VOID; some VOID with the rest WON -> PARTIALLY_VOID with ``cash_returned_usd=None``
    (the book recalculates the payout; the rules do not let us state it). Returns ``None`` when no leg
    could be graded. ``events`` is optional and only needed to resolve TEAM_TOTAL legs to a team.
    """
    results_by_event = {r.event_id: r for r in results}
    events_by_id = {e.event_id: e for e in (events or [])}
    leg_results = [grade_leg(leg, results_by_event, stats, events_by_id) for leg in bet.legs]
    if all(r == S.LegResult.PENDING for r in leg_results):
        return None

    if any(r == S.LegResult.LOST for r in leg_results):
        status = S.BetStatus.LOST
    elif any(r == S.LegResult.PENDING for r in leg_results):
        status = S.BetStatus.PENDING
    elif all(r == S.LegResult.WON for r in leg_results):
        status = S.BetStatus.WON
    elif all(r == S.LegResult.VOID for r in leg_results):
        status = S.BetStatus.VOID
    else:
        status = S.BetStatus.PARTIALLY_VOID

    used = [results_by_event[leg.event_id] for leg in bet.legs if leg.event_id in results_by_event]
    settled_at = max((r.stamp.source_timestamp_utc or r.stamp.received_at_utc for r in used), default=None)
    return S.SettlementInput(
        status=status,
        source=S.SettlementSource.PROVISIONAL_NBA_RESULTS,
        cash_returned_usd=None,
        bonus_returned_usd=None,
        repriced_combined_decimal=None,
        leg_results=leg_results,
        settled_at_utc=settled_at,
        notes="Provisional grading from NBA results; not a Hard Rock settlement. Cash figures await the book.",
    )
