"""Budget ledger tests: $10 cap, partial remaining, expiry, replay/conflict, concurrency, tenant scoping.

All data is FIXTURE-mode on a temporary SQLite file; nothing touches the network or a real ledger.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from hardrock_nba_parlay import actual_bets, budget, settlement
from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.budget import (
    BudgetExceeded,
    IdempotencyConflictError,
    LedgerError,
    NotFoundError,
    ReservationNotActiveError,
)
from hardrock_nba_parlay.db import audit_log

USER_A = "user-a"
USER_B = "user-b"
CAP = Decimal("10.00")
DATE = "2026-10-20"  # NOW (2026-10-20T19:00Z) is 15:00 ET on this day
TZ = "America/New_York"


def _reserve(
    db, clock, stake: str, key: str, *, user: str = USER_A, candidate: str = "cand-1", ttl_hours: int = 2
):
    now = clock.now_utc()
    return budget.reserve(
        db,
        user,
        DATE,
        candidate,
        Decimal(stake),
        key,
        now,
        CAP,
        now + timedelta(hours=ttl_hours),
    )


def _legs(n: int = 3) -> list[S.AcceptedLeg]:
    return [
        S.AcceptedLeg(
            description=f"leg {i}",
            event_id=f"fixture:E{i}",
            market_type=S.MarketType.MONEYLINE,
            period=S.Period.FULL_GAME,
            side=S.Side.HOME,
            accepted_decimal=Decimal("1.8000"),
        )
        for i in range(n)
    ]


def _ticket(stake: str, *, external: bool = False, candidate_id: str | None = None, legs: int = 3):
    return S.ConfirmedTicketInput(
        candidate_id=candidate_id,
        legs=_legs(legs),
        accepted_combined_decimal=Decimal("5.50"),
        stake_usd=Decimal(stake),
        external=external,
        source=S.BetSource.EXTERNAL_REPORT if external else S.BetSource.USER_CONFIRMATION,
    )


def test_fresh_day_has_full_cap(db, clock):
    b = budget.get_daily_budget(db, USER_A, DATE, clock.now_utc(), CAP)
    assert b.cap_usd == Decimal("10.00")
    assert b.recorded_stake_usd == Decimal("0.00")
    assert b.reserved_stake_usd == Decimal("0.00")
    assert b.remaining_usd == Decimal("10.00")
    assert b.raw_remaining_usd == Decimal("10.00")
    assert b.breaches == []
    assert "Not a sportsbook account limit" in b.note


def test_reserve_reduces_remaining_and_partial_budget(db, clock):
    res, replay = _reserve(db, clock, "4.00", "k1")
    assert replay is False
    assert res.status == S.ReservationStatus.ACTIVE
    assert res.stake_usd == Decimal("4.00")
    assert res.user_id == USER_A and res.date_local == DATE and res.candidate_id == "cand-1"

    b = budget.get_daily_budget(db, USER_A, DATE, clock.now_utc(), CAP, proposed_stake_usd=Decimal("7.00"))
    assert b.reserved_stake_usd == Decimal("4.00")
    assert b.remaining_usd == Decimal("6.00")
    assert b.proposed_stake_usd == Decimal("7.00")
    assert b.breaches == ["BUDGET_EXCEEDED"]

    ok = budget.get_daily_budget(db, USER_A, DATE, clock.now_utc(), CAP, proposed_stake_usd=Decimal("6.00"))
    assert ok.breaches == []

    _reserve(db, clock, "6.00", "k2", candidate="cand-2")
    b2 = budget.get_daily_budget(db, USER_A, DATE, clock.now_utc(), CAP)
    assert b2.remaining_usd == Decimal("0.00")
    with pytest.raises(BudgetExceeded) as exc:
        _reserve(db, clock, "0.01", "k3", candidate="cand-3")
    assert exc.value.remaining == Decimal("0.00")


def test_reserve_over_cap_raises_and_writes_nothing(db, clock):
    with pytest.raises(BudgetExceeded) as exc:
        _reserve(db, clock, "10.01", "k1")
    assert "BUDGET_EXCEEDED" in exc.value.reason_codes
    assert exc.value.remaining == Decimal("10.00")
    assert isinstance(exc.value, ValueError)
    assert budget.list_reservations(db, USER_A, DATE) == []
    assert budget.get_daily_budget(db, USER_A, DATE, clock.now_utc(), CAP).remaining_usd == Decimal("10.00")


def test_exact_cap_reservation_is_allowed(db, clock):
    res, _ = _reserve(db, clock, "10.00", "k1")
    assert res.stake_usd == Decimal("10.00")
    assert budget.get_daily_budget(db, USER_A, DATE, clock.now_utc(), CAP).remaining_usd == Decimal("0.00")


def test_duplicate_idempotency_key_replays(db, clock):
    first, replay1 = _reserve(db, clock, "5.00", "same-key")
    second, replay2 = _reserve(db, clock, "5.00", "same-key")
    assert replay1 is False and replay2 is True
    assert first.reservation_id == second.reservation_id
    b = budget.get_daily_budget(db, USER_A, DATE, clock.now_utc(), CAP)
    assert b.reserved_stake_usd == Decimal("5.00")
    assert len(budget.list_reservations(db, USER_A, DATE)) == 1


def test_same_key_different_payload_conflicts(db, clock):
    _reserve(db, clock, "5.00", "same-key")
    with pytest.raises(IdempotencyConflictError) as exc:
        _reserve(db, clock, "6.00", "same-key")
    assert exc.value.reason_codes == ["IDEMPOTENCY_CONFLICT"]
    assert isinstance(exc.value, ValueError)
    with pytest.raises(ValueError, match="IDEMPOTENCY_CONFLICT"):
        _reserve(db, clock, "5.00", "same-key", candidate="other-candidate")
    assert len(budget.list_reservations(db, USER_A, DATE)) == 1


def test_release_restores_remaining_and_is_not_repeatable(db, clock):
    res, _ = _reserve(db, clock, "7.00", "k1")
    assert budget.get_daily_budget(db, USER_A, DATE, clock.now_utc(), CAP).remaining_usd == Decimal("3.00")
    released = budget.release(db, USER_A, res.reservation_id, "user cancelled", clock.now_utc())
    assert released.status == S.ReservationStatus.RELEASED
    assert released.released_reason == "user cancelled"
    assert budget.get_daily_budget(db, USER_A, DATE, clock.now_utc(), CAP).remaining_usd == Decimal("10.00")
    with pytest.raises(ReservationNotActiveError) as exc:
        budget.release(db, USER_A, res.reservation_id, "again", clock.now_utc())
    assert exc.value.reason_codes == ["RESERVATION_NOT_ACTIVE"]
    fetched = budget.get_reservation(db, USER_A, res.reservation_id)
    assert fetched is not None and fetched.status == S.ReservationStatus.RELEASED


def test_release_by_other_user_is_not_found(db, clock):
    res, _ = _reserve(db, clock, "7.00", "k1")
    with pytest.raises(NotFoundError) as exc:
        budget.release(db, USER_B, res.reservation_id, "steal", clock.now_utc())
    assert exc.value.reason_codes == ["NOT_FOUND"]
    assert budget.get_reservation(db, USER_B, res.reservation_id) is None
    assert budget.get_reservation(db, USER_A, res.reservation_id) is not None
    assert budget.get_reservation(db, USER_A, res.reservation_id).status == S.ReservationStatus.ACTIVE


def test_stale_reservation_expires_and_frees_budget(db, clock):
    res, _ = _reserve(db, clock, "8.00", "k1", ttl_hours=1)
    assert budget.get_daily_budget(db, USER_A, DATE, clock.now_utc(), CAP).remaining_usd == Decimal("2.00")
    clock.advance(2 * 3600)
    b = budget.get_daily_budget(db, USER_A, DATE, clock.now_utc(), CAP)
    assert b.reserved_stake_usd == Decimal("0.00")
    assert b.remaining_usd == Decimal("10.00")
    expired = budget.get_reservation(db, USER_A, res.reservation_id)
    assert expired is not None
    assert expired.status == S.ReservationStatus.EXPIRED
    assert expired.released_reason == "RESERVATION_EXPIRED"
    with pytest.raises(ReservationNotActiveError):
        budget.release(db, USER_A, res.reservation_id, "late", clock.now_utc())


def test_list_reservations_expires_when_now_given(db, clock):
    _reserve(db, clock, "3.00", "k1", ttl_hours=1)
    clock.advance(2 * 3600)
    assert budget.list_reservations(db, USER_A, DATE)[0].status == S.ReservationStatus.ACTIVE
    listed = budget.list_reservations(db, USER_A, DATE, now=clock.now_utc())
    assert [r.status for r in listed] == [S.ReservationStatus.EXPIRED]


def test_concurrent_reservations_never_exceed_cap(db, clock):
    now = clock.now_utc()
    expires = now + timedelta(hours=1)

    def attempt(i: int):
        try:
            res, _ = budget.reserve(
                db, USER_A, DATE, f"cand-{i}", Decimal("3.00"), f"key-{i}", now, CAP, expires
            )
            return ("ok", res)
        except BudgetExceeded as exc:
            return ("exceeded", exc)

    with ThreadPoolExecutor(max_workers=10) as pool:
        outcomes = list(pool.map(attempt, range(10)))

    successes = [r for kind, r in outcomes if kind == "ok"]
    failures = [r for kind, r in outcomes if kind == "exceeded"]
    assert len(successes) + len(failures) == 10
    assert len(successes) <= 3
    assert len(successes) == 3  # 3 x $3 fits under $10; the fourth cannot
    assert all(isinstance(f, BudgetExceeded) for f in failures)
    b = budget.get_daily_budget(db, USER_A, DATE, now, CAP)
    assert b.reserved_stake_usd <= CAP
    assert b.reserved_stake_usd == Decimal("9.00")
    assert len(budget.list_reservations(db, USER_A, DATE)) == 3


def test_idempotency_keys_are_per_user(db, clock):
    a, _ = _reserve(db, clock, "5.00", "shared-key", user=USER_A)
    b, _ = _reserve(db, clock, "5.00", "shared-key", user=USER_B)
    assert a.reservation_id != b.reservation_id
    assert budget.get_daily_budget(db, USER_A, DATE, clock.now_utc(), CAP).reserved_stake_usd == Decimal(
        "5.00"
    )
    assert budget.get_daily_budget(db, USER_B, DATE, clock.now_utc(), CAP).reserved_stake_usd == Decimal(
        "5.00"
    )
    assert [r.user_id for r in budget.list_reservations(db, USER_A, DATE)] == [USER_A]
    assert [r.user_id for r in budget.list_reservations(db, USER_B, DATE)] == [USER_B]


def test_winnings_refunds_and_cash_outs_never_increase_remaining(db, clock):
    now = clock.now_utc()
    bet, b, _ = actual_bets.record_bet(
        db, USER_A, _ticket("10.00"), "bet-1", now, CAP, TZ, S.DataMode.FIXTURE
    )
    assert b.remaining_usd == Decimal("0.00")

    settlement.reconcile(
        db,
        USER_A,
        bet.bet_id,
        S.SettlementInput(status=S.BetStatus.WON, cash_returned_usd=Decimal("55.00")),
        now,
    )
    assert budget.get_daily_budget(db, USER_A, DATE, now, CAP).remaining_usd == Decimal("0.00")

    settlement.reconcile(db, USER_A, bet.bet_id, S.SettlementInput(status=S.BetStatus.VOID), now)
    assert budget.get_daily_budget(db, USER_A, DATE, now, CAP).remaining_usd == Decimal("0.00")

    settlement.reconcile(
        db,
        USER_A,
        bet.bet_id,
        S.SettlementInput(status=S.BetStatus.CASHED_OUT, cash_returned_usd=Decimal("12.00")),
        now,
    )
    after = budget.get_daily_budget(db, USER_A, DATE, now, CAP)
    assert after.recorded_stake_usd == Decimal("10.00")
    assert after.remaining_usd == Decimal("0.00")
    with pytest.raises(BudgetExceeded):
        _reserve(db, clock, "1.00", "k-after")


def test_breach_is_visible_in_budget(db, clock):
    now = clock.now_utc()
    actual_bets.record_bet(
        db, USER_A, _ticket("15.00", external=True, legs=1), "ext-1", now, CAP, TZ, S.DataMode.FIXTURE
    )
    b = budget.get_daily_budget(db, USER_A, DATE, now, CAP)
    assert b.recorded_stake_usd == Decimal("15.00")
    assert b.raw_remaining_usd == Decimal("-5.00")
    assert b.remaining_usd == Decimal("0.00")
    assert b.breaches == ["BUDGET_BREACH_RECORDED"]


def test_reservation_then_record_consumes_it(db, clock):
    now = clock.now_utc()
    res, _ = _reserve(db, clock, "10.00", "k1", candidate="cand-x")
    bet, b, _ = actual_bets.record_bet(
        db, USER_A, _ticket("10.00", candidate_id="cand-x"), "bet-1", now, CAP, TZ, S.DataMode.FIXTURE
    )
    assert bet.reservation_id == res.reservation_id
    assert budget.get_reservation(db, USER_A, res.reservation_id).status == S.ReservationStatus.CONSUMED
    assert b.recorded_stake_usd == Decimal("10.00")
    assert b.reserved_stake_usd == Decimal("0.00")
    assert b.remaining_usd == Decimal("0.00")
    assert b.breaches == []


def test_invalid_reserve_inputs(db, clock):
    now = clock.now_utc()
    with pytest.raises(LedgerError) as exc:
        budget.reserve(db, USER_A, DATE, "c", Decimal("0.00"), "k", now, CAP, now + timedelta(hours=1))
    assert exc.value.reason_codes == ["INVALID_INPUT"]
    with pytest.raises(LedgerError):
        budget.reserve(db, USER_A, DATE, "c", Decimal("1.00"), "k", now, CAP, now)
    with pytest.raises(LedgerError):
        budget.reserve(db, USER_A, DATE, "c", Decimal("1.00"), "", now, CAP, now + timedelta(hours=1))
    assert budget.list_reservations(db, USER_A, DATE) == []


def test_audit_rows_are_user_scoped(db, clock):
    _reserve(db, clock, "2.00", "k1", user=USER_A)
    _reserve(db, clock, "2.00", "k1", user=USER_B)
    with db.engine.connect() as conn:
        actions_a = [r.action for r in conn.execute(select(audit_log).where(audit_log.c.user_id == USER_A))]
        actions_b = [r.action for r in conn.execute(select(audit_log).where(audit_log.c.user_id == USER_B))]
    assert actions_a == ["reservation.create"]
    assert actions_b == ["reservation.create"]
