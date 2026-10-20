"""Daily budget ledger: reservations and the cap-per-ET-day arithmetic.

Implements the "Budget algorithm" of docs/ARCHITECTURE.md section 5 on top of the ``reservations``,
``bets``, ``user_days`` and ``audit_log`` tables from ``db.py``.

Rules
- Every public function takes an explicit ``user_id`` and scopes every query by it. A caller derives
  the id from verified auth; it is never a tool argument.
- Money is ``Decimal`` quantized to 2 dp ROUND_HALF_UP; the database stores integer cents.
- ``now`` is always a parameter (tz-aware UTC). Nothing in this module reads the wall clock.
- ``recorded`` = every bet of the user-day regardless of status (external wagers included).
  ``reserved`` = ACTIVE reservations of the user-day. ``remaining`` = max(0, cap - recorded - reserved).
- Winnings, refunds, voids and cash-outs never increase ``remaining``: only gross stakes count, and a
  settlement never touches the ``bets.stake_cents`` column that the budget sums.
- Reservations are serialised per user-day with ``Database.lock_user_day`` inside ONE transaction
  (SQLite: BEGIN IMMEDIATE; PostgreSQL: SELECT ... FOR UPDATE), so concurrent callers cannot
  over-reserve.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import Connection, func, insert, select, update
from sqlalchemy.engine import Row

from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.db import (
    Database,
    audit_log,
    bets,
    cents,
    dumps,
    from_cents,
    iso,
    new_id,
    parse_iso,
    reservations,
)

MONEY_Q = Decimal("0.01")
ODDS_Q = Decimal("0.0001")
PROB_Q = Decimal("0.000001")
ZERO_MONEY = Decimal("0.00")


def q_money(value: Decimal | int | str) -> Decimal:
    """Quantize a money amount to 2 dp, ROUND_HALF_UP."""
    return Decimal(value).quantize(MONEY_Q, rounding=ROUND_HALF_UP)


def q_odds(value: Decimal | int | str) -> Decimal:
    """Quantize decimal odds to 4 dp, ROUND_HALF_UP."""
    return Decimal(value).quantize(ODDS_Q, rounding=ROUND_HALF_UP)


def q_prob(value: Decimal | int | str) -> Decimal:
    """Quantize a probability or rate to 6 dp, ROUND_HALF_UP."""
    return Decimal(value).quantize(PROB_Q, rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------------------
# Exceptions (reason codes from ARCHITECTURE.md section 7)
# --------------------------------------------------------------------------------------


class LedgerError(ValueError):
    """Base class for ledger rejections. ``reason_codes`` uses the section-7 vocabulary verbatim."""

    default_codes: tuple[str, ...] = ("INVALID_INPUT",)

    def __init__(self, reason_codes: list[str] | str | None = None, message: str | None = None) -> None:
        if reason_codes is None:
            codes = list(self.default_codes)
        elif isinstance(reason_codes, str):
            codes = [reason_codes]
        else:
            codes = list(reason_codes)
        self.reason_codes: list[str] = codes
        super().__init__(message or ", ".join(codes))


class NotFoundError(LedgerError):
    """The record does not exist for this user (another user's id is indistinguishable from a bad id)."""

    default_codes = ("NOT_FOUND",)


class IdempotencyConflictError(LedgerError):
    """The idempotency key was already used by this user with a different payload."""

    default_codes = ("IDEMPOTENCY_CONFLICT",)


class ReservationNotActiveError(LedgerError):
    """The reservation exists but is not ACTIVE (CONSUMED, RELEASED or EXPIRED)."""

    default_codes = ("RESERVATION_NOT_ACTIVE",)


class BudgetExceeded(LedgerError):
    """The proposed stake does not fit under the daily cap. ``remaining`` is what still fits."""

    default_codes = ("BUDGET_EXCEEDED",)

    def __init__(
        self, remaining: Decimal, reason_codes: list[str] | None = None, message: str | None = None
    ) -> None:
        self.remaining: Decimal = q_money(remaining)
        codes = list(reason_codes or [])
        if "BUDGET_EXCEEDED" not in codes:
            codes.insert(0, "BUDGET_EXCEEDED")
        super().__init__(
            codes, message or f"BUDGET_EXCEEDED: remaining {self.remaining} USD under the daily cap"
        )


# --------------------------------------------------------------------------------------
# Row mapping and audit
# --------------------------------------------------------------------------------------


def reservation_from_row(row: Row[Any]) -> S.BudgetReservation:
    """Build a ``BudgetReservation`` from a ``reservations`` row."""
    created = parse_iso(row.created_at)
    expires = parse_iso(row.expires_at)
    assert created is not None and expires is not None
    return S.BudgetReservation(
        reservation_id=row.reservation_id,
        user_id=row.user_id,
        date_local=row.date_local,
        candidate_id=row.candidate_id,
        stake_usd=from_cents(row.stake_cents),
        status=S.ReservationStatus(row.status),
        idempotency_key=row.idempotency_key,
        created_at_utc=created,
        expires_at_utc=expires,
        released_reason=row.released_reason,
    )


def write_audit(
    conn: Connection, user_id: str, action: str, ref_id: str | None, payload: dict[str, Any], now: datetime
) -> None:
    """Append one ``audit_log`` row for ``user_id`` (never contains secrets)."""
    conn.execute(
        insert(audit_log).values(
            user_id=user_id, action=action, ref_id=ref_id, json=dumps(payload), created_at=iso(now)
        )
    )


# --------------------------------------------------------------------------------------
# In-transaction primitives (callers hold ``db.tx()`` and ``lock_user_day``)
# --------------------------------------------------------------------------------------


def expire_stale(conn: Connection, user_id: str, date_local: str, now: datetime) -> list[str]:
    """Mark ACTIVE reservations of the user-day whose ``expires_at <= now`` as EXPIRED.

    Returns the ids expired. Reason stored: RESERVATION_EXPIRED.
    """
    rows = conn.execute(
        select(reservations).where(
            reservations.c.user_id == user_id,
            reservations.c.date_local == date_local,
            reservations.c.status == S.ReservationStatus.ACTIVE.value,
        )
    ).all()
    expired: list[str] = []
    for row in rows:
        expires = parse_iso(row.expires_at)
        if expires is not None and expires <= now:
            conn.execute(
                update(reservations)
                .where(reservations.c.reservation_id == row.reservation_id, reservations.c.user_id == user_id)
                .values(status=S.ReservationStatus.EXPIRED.value, released_reason="RESERVATION_EXPIRED")
            )
            write_audit(
                conn,
                user_id,
                "reservation.expire",
                row.reservation_id,
                {"reason": "RESERVATION_EXPIRED", "expires_at": row.expires_at, "now": iso(now)},
                now,
            )
            expired.append(row.reservation_id)
    return expired


def recorded_stake(conn: Connection, user_id: str, date_local: str) -> Decimal:
    """Sum of stakes of ALL bets for the user-day (every status, external included)."""
    total = conn.execute(
        select(func.coalesce(func.sum(bets.c.stake_cents), 0)).where(
            bets.c.user_id == user_id, bets.c.date_local == date_local
        )
    ).scalar_one()
    value = from_cents(int(total))
    assert value is not None
    return value


def reserved_stake(
    conn: Connection, user_id: str, date_local: str, exclude_reservation_id: str | None = None
) -> Decimal:
    """Sum of stakes of ACTIVE reservations for the user-day."""
    stmt = select(func.coalesce(func.sum(reservations.c.stake_cents), 0)).where(
        reservations.c.user_id == user_id,
        reservations.c.date_local == date_local,
        reservations.c.status == S.ReservationStatus.ACTIVE.value,
    )
    if exclude_reservation_id is not None:
        stmt = stmt.where(reservations.c.reservation_id != exclude_reservation_id)
    value = from_cents(int(conn.execute(stmt).scalar_one()))
    assert value is not None
    return value


def compute_budget(
    conn: Connection,
    user_id: str,
    date_local: str,
    cap_usd: Decimal,
    proposed_stake_usd: Decimal | None = None,
    exclude_reservation_id: str | None = None,
) -> S.DailyBudget:
    """Budget arithmetic for one user-day. Call after ``expire_stale`` inside the caller's transaction.

    ``remaining`` is floored at zero for display; ``raw_remaining_usd`` keeps the negative value after
    a recorded breach. ``breaches`` lists BUDGET_BREACH_RECORDED when recorded > cap and
    BUDGET_EXCEEDED when the proposed stake does not fit.
    """
    cap = q_money(cap_usd)
    recorded = recorded_stake(conn, user_id, date_local)
    reserved = reserved_stake(conn, user_id, date_local, exclude_reservation_id)
    raw = q_money(cap - recorded - reserved)
    remaining = raw if raw > 0 else ZERO_MONEY
    breaches: list[str] = []
    if recorded > cap:
        breaches.append("BUDGET_BREACH_RECORDED")
    proposed = q_money(proposed_stake_usd) if proposed_stake_usd is not None else None
    if proposed is not None and proposed > remaining:
        breaches.append("BUDGET_EXCEEDED")
    return S.DailyBudget(
        date_local=date_local,
        cap_usd=cap,
        recorded_stake_usd=recorded,
        reserved_stake_usd=reserved,
        proposed_stake_usd=proposed,
        remaining_usd=remaining,
        raw_remaining_usd=raw,
        breaches=breaches,
    )


def consume_reservations_for_candidate(
    conn: Connection, user_id: str, candidate_id: str, now: datetime
) -> list[S.BudgetReservation]:
    """Mark every ACTIVE reservation of ``candidate_id`` for this user as CONSUMED (oldest first).

    Used by ``actual_bets.record_bet`` inside its transaction. Returns the reservations consumed, in
    creation order, so the caller can link the first one to the bet.
    """
    rows = conn.execute(
        select(reservations)
        .where(
            reservations.c.user_id == user_id,
            reservations.c.candidate_id == candidate_id,
            reservations.c.status == S.ReservationStatus.ACTIVE.value,
        )
        .order_by(reservations.c.created_at, reservations.c.reservation_id)
    ).all()
    consumed: list[S.BudgetReservation] = []
    for row in rows:
        conn.execute(
            update(reservations)
            .where(reservations.c.reservation_id == row.reservation_id, reservations.c.user_id == user_id)
            .values(status=S.ReservationStatus.CONSUMED.value)
        )
        write_audit(
            conn, user_id, "reservation.consume", row.reservation_id, {"candidate_id": candidate_id}, now
        )
        refreshed = conn.execute(
            select(reservations).where(reservations.c.reservation_id == row.reservation_id)
        ).one()
        consumed.append(reservation_from_row(refreshed))
    return consumed


# --------------------------------------------------------------------------------------
# Public service functions
# --------------------------------------------------------------------------------------


def get_daily_budget(
    db: Database,
    user_id: str,
    date_local: str,
    now: datetime,
    cap_usd: Decimal,
    proposed_stake_usd: Decimal | None = None,
) -> S.DailyBudget:
    """Return the user's budget for ``date_local`` after expiring stale reservations.

    This is the application's ledger check, not a sportsbook account limit.
    """
    with db.tx() as conn:
        db.lock_user_day(conn, user_id, date_local, now)
        expire_stale(conn, user_id, date_local, now)
        return compute_budget(conn, user_id, date_local, cap_usd, proposed_stake_usd)


def reserve(
    db: Database,
    user_id: str,
    date_local: str,
    candidate_id: str,
    stake_usd: Decimal,
    idempotency_key: str,
    now: datetime,
    cap_usd: Decimal,
    expires_at: datetime,
) -> tuple[S.BudgetReservation, bool]:
    """Reserve ``stake_usd`` of the user's ``date_local`` budget for ``candidate_id``.

    ONE transaction: lock the user-day, expire stale reservations, compute remaining, then
    - replay: an existing reservation with the same ``(user_id, idempotency_key)`` is returned with
      ``replay=True`` (a different stake or candidate raises ``IdempotencyConflictError``, a ValueError);
    - ``BudgetExceeded`` when ``stake_usd > remaining`` (nothing is written);
    - otherwise insert an ACTIVE reservation expiring at ``expires_at`` and audit it.
    """
    stake = q_money(stake_usd)
    if stake <= 0:
        raise LedgerError("INVALID_INPUT", "INVALID_INPUT: stake must be positive")
    if not idempotency_key:
        raise LedgerError("INVALID_INPUT", "INVALID_INPUT: idempotency_key is required")
    if expires_at.tzinfo is None or now.tzinfo is None:
        raise LedgerError("INVALID_INPUT", "INVALID_INPUT: datetimes must be timezone-aware UTC")
    if expires_at <= now:
        raise LedgerError("INVALID_INPUT", "INVALID_INPUT: expires_at must be after now")

    with db.tx() as conn:
        db.lock_user_day(conn, user_id, date_local, now)
        expire_stale(conn, user_id, date_local, now)

        existing = conn.execute(
            select(reservations).where(
                reservations.c.user_id == user_id, reservations.c.idempotency_key == idempotency_key
            )
        ).first()
        if existing is not None:
            if existing.stake_cents != cents(stake) or existing.candidate_id != candidate_id:
                raise IdempotencyConflictError(
                    message=(
                        "IDEMPOTENCY_CONFLICT: idempotency_key already used for a different stake or candidate"
                    )
                )
            return reservation_from_row(existing), True

        budget = compute_budget(conn, user_id, date_local, cap_usd, proposed_stake_usd=stake)
        if stake > budget.remaining_usd:
            raise BudgetExceeded(budget.remaining_usd, budget.breaches)

        reservation_id = new_id("rsv")
        conn.execute(
            insert(reservations).values(
                reservation_id=reservation_id,
                user_id=user_id,
                date_local=date_local,
                candidate_id=candidate_id,
                stake_cents=cents(stake),
                status=S.ReservationStatus.ACTIVE.value,
                idempotency_key=idempotency_key,
                created_at=iso(now),
                expires_at=iso(expires_at),
                released_reason=None,
            )
        )
        write_audit(
            conn,
            user_id,
            "reservation.create",
            reservation_id,
            {
                "candidate_id": candidate_id,
                "date_local": date_local,
                "stake_usd": str(stake),
                "remaining_before_usd": str(budget.remaining_usd),
                "expires_at": iso(expires_at),
            },
            now,
        )
        row = conn.execute(select(reservations).where(reservations.c.reservation_id == reservation_id)).one()
        return reservation_from_row(row), False


def release(
    db: Database, user_id: str, reservation_id: str, reason: str, now: datetime
) -> S.BudgetReservation:
    """Release an ACTIVE reservation (status RELEASED, ``released_reason=reason``).

    Raises ``NotFoundError`` when the id does not belong to ``user_id`` and
    ``ReservationNotActiveError`` when it is not ACTIVE (stale ones are expired first).
    """
    with db.tx() as conn:
        row = conn.execute(
            select(reservations).where(
                reservations.c.reservation_id == reservation_id, reservations.c.user_id == user_id
            )
        ).first()
        if row is None:
            raise NotFoundError(message="NOT_FOUND: reservation not found for this user")
        db.lock_user_day(conn, user_id, row.date_local, now)
        expire_stale(conn, user_id, row.date_local, now)
        row = conn.execute(select(reservations).where(reservations.c.reservation_id == reservation_id)).one()
        if row.status != S.ReservationStatus.ACTIVE.value:
            raise ReservationNotActiveError(
                message=f"RESERVATION_NOT_ACTIVE: reservation is {row.status}, only ACTIVE reservations can be released"
            )
        conn.execute(
            update(reservations)
            .where(reservations.c.reservation_id == reservation_id, reservations.c.user_id == user_id)
            .values(status=S.ReservationStatus.RELEASED.value, released_reason=reason)
        )
        write_audit(conn, user_id, "reservation.release", reservation_id, {"reason": reason}, now)
        row = conn.execute(select(reservations).where(reservations.c.reservation_id == reservation_id)).one()
        return reservation_from_row(row)


def get_reservation(db: Database, user_id: str, reservation_id: str) -> S.BudgetReservation | None:
    """Fetch one reservation; ``None`` when it does not exist for this user."""
    with db.engine.connect() as conn:
        row = conn.execute(
            select(reservations).where(
                reservations.c.reservation_id == reservation_id, reservations.c.user_id == user_id
            )
        ).first()
    return None if row is None else reservation_from_row(row)


def list_reservations(
    db: Database, user_id: str, date_local: str, now: datetime | None = None
) -> list[S.BudgetReservation]:
    """List the user's reservations for ``date_local`` (creation order).

    When ``now`` is given, stale ACTIVE reservations are expired first so statuses are current.
    """
    if now is not None:
        with db.tx() as conn:
            db.lock_user_day(conn, user_id, date_local, now)
            expire_stale(conn, user_id, date_local, now)
    with db.engine.connect() as conn:
        rows = conn.execute(
            select(reservations)
            .where(reservations.c.user_id == user_id, reservations.c.date_local == date_local)
            .order_by(reservations.c.created_at, reservations.c.reservation_id)
        ).all()
    return [reservation_from_row(r) for r in rows]
