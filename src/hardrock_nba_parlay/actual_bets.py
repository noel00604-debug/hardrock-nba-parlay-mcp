"""Actual-bet ledger: user-confirmed wagers, recorded truthfully, once, per user.

A bet is recorded only after the user's explicit placement confirmation or a reviewed receipt (the
caller enforces that; this module records what it is given). Records are append-only: nothing here
deletes or rewrites a stake. Over-cap wagers are recorded AND flagged (BUDGET_BREACH_RECORDED);
history is never refused.

Storage: ``bets.json`` holds ``{"bet": <ActualBet>, "forecast": <candidate snapshot or null>,
"data_mode": ...}``. The ``forecast`` block (p_joint, model_state, parlay_type, market composition)
is kept so that calibration can later be reported only where a numerical forecast existed before
placement.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, insert, select, update
from sqlalchemy.engine import Row

from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.budget import (
    IdempotencyConflictError,
    LedgerError,
    compute_budget,
    consume_reservations_for_candidate,
    expire_stale,
    q_money,
    q_odds,
    write_audit,
)
from hardrock_nba_parlay.config import local_date
from hardrock_nba_parlay.db import Database, bets, cents, dumps, iso, loads, new_id, settlements

FORECAST_KEY = "forecast"


@dataclass(frozen=True)
class StoredBet:
    """A bet together with the pre-placement forecast snapshot stored beside it."""

    bet: S.ActualBet
    forecast: dict[str, Any] | None
    data_mode: str


# --------------------------------------------------------------------------------------
# Hashing and conversions
# --------------------------------------------------------------------------------------


def american_to_decimal(american: int) -> Decimal:
    """Exact Decimal conversion of American odds (|a| >= 100), quantized to 4 dp."""
    if american == 0 or abs(american) < 100:
        raise LedgerError("INVALID_INPUT", "INVALID_INPUT: american odds must be <= -100 or >= +100")
    if american > 0:
        return q_odds(Decimal(1) + Decimal(american) / Decimal(100))
    return q_odds(Decimal(1) + Decimal(100) / Decimal(abs(american)))


def resolve_accepted_decimal(ticket: S.ConfirmedTicketInput) -> Decimal | None:
    """The accepted combined decimal odds the ledger stores: the decimal field (4 dp) or the American one converted."""
    if ticket.accepted_combined_decimal is not None:
        return q_odds(ticket.accepted_combined_decimal)
    if ticket.accepted_combined_american is not None:
        return american_to_decimal(ticket.accepted_combined_american)
    return None


def _canonical_line(value: Decimal | None) -> str | None:
    """A line without trailing zeros or exponent (``3.50`` -> ``3.5``, ``100.0`` -> ``100``)."""
    return None if value is None else format(value.normalize(), "f")


def canonical_ticket_json(ticket: S.ConfirmedTicketInput) -> str:
    """Canonical JSON of a confirmed ticket over the values the ledger stores.

    Odds are quantized to 4 dp, money to 2 dp, lines stripped of trailing zeros, datetimes rendered as
    ISO UTC, and the accepted odds resolved to one decimal figure, so the same ticket re-sent with a
    different Decimal spelling (``5.5`` vs ``5.50``) or with American instead of decimal odds hashes
    the same and replays instead of raising IDEMPOTENCY_CONFLICT.
    """
    accepted = resolve_accepted_decimal(ticket)
    payload: dict[str, Any] = {
        "candidate_id": ticket.candidate_id,
        "book": ticket.book,
        "ticket_ref": ticket.ticket_ref,
        "legs": [
            {
                "description": leg.description,
                "event_id": leg.event_id,
                "market_type": None if leg.market_type is None else leg.market_type.value,
                "period": None if leg.period is None else leg.period.value,
                "side": None if leg.side is None else leg.side.value,
                "line": _canonical_line(leg.line),
                "player_name": leg.player_name,
                "team_name": leg.team_name,
                "accepted_decimal": None
                if leg.accepted_decimal is None
                else str(q_odds(leg.accepted_decimal)),
                "result": leg.result.value,
            }
            for leg in ticket.legs
        ],
        "accepted_combined_decimal": None if accepted is None else str(accepted),
        "stake_usd": str(q_money(ticket.stake_usd)),
        "placed_at_utc": iso(ticket.placed_at_utc),
        "source": ticket.source.value,
        "external": ticket.external,
        "notes": ticket.notes,
    }
    return dumps(payload)


def ticket_payload_hash(ticket: S.ConfirmedTicketInput) -> str:
    """sha256 hex digest of the canonical ticket JSON; equal payloads replay, different ones conflict."""
    return hashlib.sha256(canonical_ticket_json(ticket).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------------------
# Row mapping
# --------------------------------------------------------------------------------------


def _payload(row: Row[Any]) -> dict[str, Any]:
    payload = loads(row.json)
    if not isinstance(payload, dict) or "bet" not in payload:
        raise LedgerError("INVALID_INPUT", "corrupt bet row")
    return payload


def bet_from_row(row: Row[Any]) -> S.ActualBet:
    """Build an ``ActualBet`` from a ``bets`` row (the ``status`` column is authoritative)."""
    data = dict(_payload(row)["bet"])
    data["status"] = row.status
    return S.ActualBet.model_validate(data)


def stored_bet_from_row(row: Row[Any]) -> StoredBet:
    """Build a ``StoredBet`` (bet + forecast snapshot) from a ``bets`` row."""
    payload = _payload(row)
    forecast = payload.get(FORECAST_KEY)
    return StoredBet(
        bet=bet_from_row(row),
        forecast=forecast if isinstance(forecast, dict) else None,
        data_mode=str(payload.get("data_mode") or row.data_mode),
    )


def settlement_from_row(row: Row[Any]) -> S.SettlementRecord:
    """Build a ``SettlementRecord`` from a ``settlements`` row."""
    return S.SettlementRecord.model_validate(loads(row.json))


def persist_bet(conn: Connection, bet: S.ActualBet) -> None:
    """Rewrite the stored ``ActualBet`` (status column + json) for ``bet.user_id``; keeps the forecast."""
    row = conn.execute(select(bets).where(bets.c.bet_id == bet.bet_id, bets.c.user_id == bet.user_id)).first()
    if row is None:
        raise LedgerError("NOT_FOUND", "NOT_FOUND: bet not found for this user")
    payload = _payload(row)
    payload["bet"] = bet.model_dump(mode="json")
    conn.execute(
        update(bets)
        .where(bets.c.bet_id == bet.bet_id, bets.c.user_id == bet.user_id)
        .values(status=bet.status.value, json=dumps(payload))
    )


# --------------------------------------------------------------------------------------
# Recording
# --------------------------------------------------------------------------------------


def record_bet(
    db: Database,
    user_id: str,
    ticket: S.ConfirmedTicketInput,
    idempotency_key: str,
    now: datetime,
    cap_usd: Decimal,
    tz_name: str,
    data_mode: S.DataMode | str,
    candidate_snapshot: dict[str, Any] | None = None,
    recommended_combined_decimal: Decimal | None = None,
) -> tuple[S.ActualBet, S.DailyBudget, bool]:
    """Record a user-confirmed wager. Returns ``(bet, budget_after, replay)``.

    ONE transaction with ``lock_user_day``:
    - ``date_local`` comes from ``ticket.placed_at_utc`` (or ``now``) in ``tz_name``;
    - ``db.guard_ledger_mode(data_mode)`` refuses FIXTURE data on a real ledger (``FixtureLedgerError``);
    - replay when ``(user_id, idempotency_key)`` exists with the same payload hash; a different payload
      raises ``IdempotencyConflictError`` (IDEMPOTENCY_CONFLICT);
    - every ACTIVE reservation of ``ticket.candidate_id`` for this user is CONSUMED and the oldest is
      linked as ``reservation_id``;
    - when recorded + stake > cap the bet is still recorded, with BUDGET_BREACH_RECORDED in
      ``breach_flags`` and an audit row. History is never refused.
    Tool-prepared bets must have exactly three legs; ``external=True`` bets may have any count.
    """
    mode = S.DataMode(data_mode)
    db.guard_ledger_mode(mode.value)
    if not idempotency_key:
        raise LedgerError("INVALID_INPUT", "INVALID_INPUT: idempotency_key is required")
    if not ticket.legs:
        raise LedgerError("INVALID_INPUT", "INVALID_INPUT: a bet needs at least one leg")
    if not ticket.external and len(ticket.legs) != 3:
        raise LedgerError(
            "NOT_THREE_LEGS", "NOT_THREE_LEGS: a tool-prepared bet must have exactly three legs"
        )

    placed_at = ticket.placed_at_utc or now
    date_local = local_date(placed_at, tz_name)
    stake = q_money(ticket.stake_usd)
    payload_hash = ticket_payload_hash(ticket)

    accepted = resolve_accepted_decimal(ticket)

    recommended = recommended_combined_decimal
    if recommended is None and candidate_snapshot and candidate_snapshot.get("recommended_combined_decimal"):
        recommended = Decimal(str(candidate_snapshot["recommended_combined_decimal"]))
    if recommended is not None:
        recommended = q_odds(recommended)

    forecast: dict[str, Any] | None = None
    if candidate_snapshot is not None:
        forecast = loads(dumps(candidate_snapshot))  # JSON-safe copy (Decimal/datetime become strings)

    with db.tx() as conn:
        db.lock_user_day(conn, user_id, date_local, now)
        expire_stale(conn, user_id, date_local, now)

        existing = conn.execute(
            select(bets).where(bets.c.user_id == user_id, bets.c.idempotency_key == idempotency_key)
        ).first()
        if existing is not None:
            if existing.payload_hash != payload_hash:
                raise IdempotencyConflictError(
                    message="IDEMPOTENCY_CONFLICT: idempotency_key already used for a different ticket"
                )
            bet = bet_from_row(existing)
            return bet, compute_budget(conn, user_id, bet.date_local, cap_usd), True

        reservation_id: str | None = None
        if ticket.candidate_id:
            consumed = consume_reservations_for_candidate(conn, user_id, ticket.candidate_id, now)
            if consumed:
                reservation_id = consumed[0].reservation_id

        recorded_before = compute_budget(conn, user_id, date_local, cap_usd).recorded_stake_usd
        breach_flags: list[str] = []
        if recorded_before + stake > q_money(cap_usd):
            breach_flags.append("BUDGET_BREACH_RECORDED")

        bet = S.ActualBet(
            bet_id=new_id("bet"),
            user_id=user_id,
            date_local=date_local,
            candidate_id=ticket.candidate_id,
            reservation_id=reservation_id,
            book=ticket.book,
            ticket_ref=ticket.ticket_ref,
            legs=[leg.model_copy(deep=True) for leg in ticket.legs],
            external=ticket.external,
            accepted_combined_decimal=accepted,
            recommended_combined_decimal=recommended,
            stake_usd=stake,
            placed_at_utc=placed_at,
            source=ticket.source,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            breach_flags=breach_flags,
            status=S.BetStatus.PENDING,
            created_at_utc=now,
            notes=ticket.notes,
        )
        conn.execute(
            insert(bets).values(
                bet_id=bet.bet_id,
                user_id=user_id,
                date_local=date_local,
                candidate_id=bet.candidate_id,
                reservation_id=reservation_id,
                stake_cents=cents(stake),
                status=bet.status.value,
                idempotency_key=idempotency_key,
                payload_hash=payload_hash,
                external=1 if bet.external else 0,
                data_mode=mode.value,
                json=dumps(
                    {"bet": bet.model_dump(mode="json"), FORECAST_KEY: forecast, "data_mode": mode.value}
                ),
                placed_at=iso(placed_at),
                created_at=iso(now),
            )
        )
        write_audit(
            conn,
            user_id,
            "bet.record",
            bet.bet_id,
            {
                "date_local": date_local,
                "stake_usd": str(stake),
                "external": bet.external,
                "candidate_id": bet.candidate_id,
                "reservation_id": reservation_id,
                "source": bet.source.value,
                "data_mode": mode.value,
                "recorded_before_usd": str(recorded_before),
            },
            now,
        )
        if breach_flags:
            write_audit(
                conn,
                user_id,
                "budget.breach_recorded",
                bet.bet_id,
                {
                    "reason": "BUDGET_BREACH_RECORDED",
                    "date_local": date_local,
                    "cap_usd": str(q_money(cap_usd)),
                    "recorded_after_usd": str(recorded_before + stake),
                },
                now,
            )
        budget = compute_budget(conn, user_id, date_local, cap_usd)
        return bet, budget, False


# --------------------------------------------------------------------------------------
# Reads (all scoped by user_id)
# --------------------------------------------------------------------------------------


def get_stored_bet(db: Database, user_id: str, bet_id: str) -> StoredBet | None:
    """Bet plus forecast snapshot; ``None`` when the id is not this user's."""
    with db.engine.connect() as conn:
        row = conn.execute(select(bets).where(bets.c.bet_id == bet_id, bets.c.user_id == user_id)).first()
    return None if row is None else stored_bet_from_row(row)


def get_bet(db: Database, user_id: str, bet_id: str) -> S.ActualBet | None:
    """Fetch one bet; ``None`` for another user's id or an unknown id."""
    stored = get_stored_bet(db, user_id, bet_id)
    return None if stored is None else stored.bet


def list_stored_bets(db: Database, user_id: str, start_date: str, end_date: str) -> list[StoredBet]:
    """Bets (with forecasts) placed on ``start_date..end_date`` inclusive (ET dates), placement order."""
    with db.engine.connect() as conn:
        rows = conn.execute(
            select(bets)
            .where(bets.c.user_id == user_id, bets.c.date_local >= start_date, bets.c.date_local <= end_date)
            .order_by(bets.c.placed_at, bets.c.created_at, bets.c.bet_id)
        ).all()
    return [stored_bet_from_row(r) for r in rows]


def list_bets(db: Database, user_id: str, start_date: str, end_date: str) -> list[S.ActualBet]:
    """Bets placed on ``start_date..end_date`` inclusive (ET dates), placement order."""
    return [s.bet for s in list_stored_bets(db, user_id, start_date, end_date)]


def current_settlement_in(conn: Connection, user_id: str, bet_id: str) -> S.SettlementRecord | None:
    """Highest-``seq`` settlement of the bet within an open connection; ``None`` when none exists."""
    row = conn.execute(
        select(settlements)
        .where(settlements.c.bet_id == bet_id, settlements.c.user_id == user_id)
        .order_by(settlements.c.seq.desc())
        .limit(1)
    ).first()
    return None if row is None else settlement_from_row(row)


def current_settlement(db: Database, user_id: str, bet_id: str) -> S.SettlementRecord | None:
    """The latest (highest ``seq``) settlement record of this user's bet, or ``None``."""
    with db.engine.connect() as conn:
        return current_settlement_in(conn, user_id, bet_id)
