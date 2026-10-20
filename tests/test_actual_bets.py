"""Actual-bet ledger tests: recording, replay/conflict, breach flagging, ET day boundary incl. DST end,
fixture guard, tenant isolation and restart recovery. All data is FIXTURE-mode on a temp SQLite file."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from hardrock_nba_parlay import actual_bets, budget
from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.actual_bets import IdempotencyConflictError, LedgerError
from hardrock_nba_parlay.db import FixtureLedgerError, audit_log, bets, open_database

USER_A = "user-a"
USER_B = "user-b"
CAP = Decimal("10.00")
TZ = "America/New_York"
DATE = "2026-10-20"


def _legs(n: int = 3) -> list[S.AcceptedLeg]:
    markets = [S.MarketType.SPREAD, S.MarketType.TOTAL, S.MarketType.MONEYLINE]
    sides = [S.Side.HOME, S.Side.OVER, S.Side.AWAY]
    lines = [Decimal("3.5"), Decimal("224.5"), None]
    out = []
    for i in range(n):
        j = i % 3
        out.append(
            S.AcceptedLeg(
                description=f"leg {i}",
                event_id=f"fixture:E{i}",
                market_type=markets[j],
                period=S.Period.FULL_GAME,
                side=sides[j],
                line=lines[j],
                accepted_decimal=Decimal("1.9091"),
            )
        )
    return out


def _ticket(
    stake: str = "10.00",
    *,
    external: bool = False,
    candidate_id: str | None = None,
    legs: int = 3,
    placed_at: datetime | None = None,
    ticket_ref: str | None = "HR-123",
    accepted: str | None = "5.50",
    accepted_american: int | None = None,
) -> S.ConfirmedTicketInput:
    return S.ConfirmedTicketInput(
        candidate_id=candidate_id,
        ticket_ref=ticket_ref,
        legs=_legs(legs),
        accepted_combined_decimal=Decimal(accepted) if accepted else None,
        accepted_combined_american=accepted_american,
        stake_usd=Decimal(stake),
        placed_at_utc=placed_at,
        external=external,
        source=S.BetSource.EXTERNAL_REPORT if external else S.BetSource.USER_CONFIRMATION,
        notes="fixture ticket",
    )


SNAPSHOT = {
    "p_joint": Decimal("0.200000"),
    "model_state": "MARKET_BASELINE",
    "parlay_type": "MULTI_GAME",
    "market_composition": "MONEYLINE+SPREAD+TOTAL",
    "candidate_id": "cand-1",
}


def test_record_three_leg_bet(db, clock):
    now = clock.now_utc()
    bet, b, replay = actual_bets.record_bet(
        db,
        USER_A,
        _ticket(candidate_id="cand-1"),
        "idem-1",
        now,
        CAP,
        TZ,
        S.DataMode.FIXTURE,
        candidate_snapshot=SNAPSHOT,
        recommended_combined_decimal=Decimal("5.60"),
    )
    assert replay is False
    assert bet.bet_id.startswith("bet_")
    assert bet.user_id == USER_A
    assert bet.date_local == DATE
    assert bet.status == S.BetStatus.PENDING
    assert bet.stake_usd == Decimal("10.00")
    assert bet.accepted_combined_decimal == Decimal("5.5000")
    assert bet.recommended_combined_decimal == Decimal("5.6000")
    assert bet.placed_at_utc == now
    assert bet.breach_flags == []
    assert bet.external is False
    assert bet.ticket_ref == "HR-123"
    assert bet.notes == "fixture ticket"
    assert [leg.result for leg in bet.legs] == [S.LegResult.PENDING] * 3
    assert b.recorded_stake_usd == Decimal("10.00") and b.remaining_usd == Decimal("0.00")

    stored = actual_bets.get_stored_bet(db, USER_A, bet.bet_id)
    assert stored is not None
    assert stored.bet == bet
    assert stored.forecast == {
        "p_joint": "0.200000",
        "model_state": "MARKET_BASELINE",
        "parlay_type": "MULTI_GAME",
        "market_composition": "MONEYLINE+SPREAD+TOTAL",
        "candidate_id": "cand-1",
    }
    assert stored.data_mode == "FIXTURE"
    assert actual_bets.get_bet(db, USER_A, bet.bet_id) == bet
    assert actual_bets.current_settlement(db, USER_A, bet.bet_id) is None


def test_record_consumes_active_reservation(db, clock):
    now = clock.now_utc()
    res, _ = budget.reserve(
        db, USER_A, DATE, "cand-1", Decimal("10.00"), "rsv-1", now, CAP, now.replace(hour=23)
    )
    bet, b, _ = actual_bets.record_bet(
        db, USER_A, _ticket(candidate_id="cand-1"), "idem-1", now, CAP, TZ, S.DataMode.FIXTURE
    )
    assert bet.candidate_id == "cand-1"
    assert bet.reservation_id == res.reservation_id
    assert budget.get_reservation(db, USER_A, res.reservation_id).status == S.ReservationStatus.CONSUMED
    assert b.reserved_stake_usd == Decimal("0.00")
    assert b.recorded_stake_usd == Decimal("10.00")
    assert b.breaches == []


def test_record_without_reservation_still_records(db, clock):
    now = clock.now_utc()
    bet, b, _ = actual_bets.record_bet(
        db, USER_A, _ticket("4.00", candidate_id="cand-9"), "idem-1", now, CAP, TZ, S.DataMode.FIXTURE
    )
    assert bet.reservation_id is None
    assert b.remaining_usd == Decimal("6.00")


def test_replay_same_key_same_payload(db, clock):
    now = clock.now_utc()
    first, _, r1 = actual_bets.record_bet(db, USER_A, _ticket(), "idem-1", now, CAP, TZ, S.DataMode.FIXTURE)
    clock.advance(60)
    second, b, r2 = actual_bets.record_bet(
        db, USER_A, _ticket(), "idem-1", clock.now_utc(), CAP, TZ, S.DataMode.FIXTURE
    )
    assert (r1, r2) == (False, True)
    assert first.bet_id == second.bet_id
    assert first == second
    assert len(actual_bets.list_bets(db, USER_A, DATE, DATE)) == 1
    assert b.recorded_stake_usd == Decimal("10.00")


def test_conflict_same_key_different_payload(db, clock):
    now = clock.now_utc()
    actual_bets.record_bet(db, USER_A, _ticket("10.00"), "idem-1", now, CAP, TZ, S.DataMode.FIXTURE)
    with pytest.raises(IdempotencyConflictError) as exc:
        actual_bets.record_bet(db, USER_A, _ticket("9.00"), "idem-1", now, CAP, TZ, S.DataMode.FIXTURE)
    assert exc.value.reason_codes == ["IDEMPOTENCY_CONFLICT"]
    assert len(actual_bets.list_bets(db, USER_A, DATE, DATE)) == 1


def test_external_over_cap_is_recorded_and_flagged(db, clock):
    now = clock.now_utc()
    bet, b, _ = actual_bets.record_bet(
        db, USER_A, _ticket("15.00", external=True, legs=1), "ext-1", now, CAP, TZ, S.DataMode.MANUAL_INPUT
    )
    assert bet.external is True
    assert len(bet.legs) == 1
    assert bet.stake_usd == Decimal("15.00")
    assert bet.breach_flags == ["BUDGET_BREACH_RECORDED"]
    assert b.recorded_stake_usd == Decimal("15.00")
    assert b.raw_remaining_usd == Decimal("-5.00")
    assert b.remaining_usd == Decimal("0.00")
    assert b.breaches == ["BUDGET_BREACH_RECORDED"]
    with db.engine.connect() as conn:
        actions = [
            r.action
            for r in conn.execute(
                select(audit_log).where(audit_log.c.user_id == USER_A).order_by(audit_log.c.id)
            )
        ]
    assert actions == ["bet.record", "budget.breach_recorded"]
    # a later in-cap bet on the same day is also recorded and flagged, never refused
    bet2, b2, _ = actual_bets.record_bet(
        db, USER_A, _ticket("5.00"), "idem-2", now, CAP, TZ, S.DataMode.MANUAL_INPUT
    )
    assert bet2.breach_flags == ["BUDGET_BREACH_RECORDED"]
    assert b2.recorded_stake_usd == Decimal("20.00")


def test_two_bets_summing_over_cap_flag_only_the_second(db, clock):
    now = clock.now_utc()
    b1, _, _ = actual_bets.record_bet(db, USER_A, _ticket("6.00"), "i1", now, CAP, TZ, S.DataMode.FIXTURE)
    b2, budget_after, _ = actual_bets.record_bet(
        db, USER_A, _ticket("5.00"), "i2", now, CAP, TZ, S.DataMode.FIXTURE
    )
    assert b1.breach_flags == []
    assert b2.breach_flags == ["BUDGET_BREACH_RECORDED"]
    assert budget_after.recorded_stake_usd == Decimal("11.00")


def test_tool_prepared_bet_requires_three_legs(db, clock):
    now = clock.now_utc()
    with pytest.raises(LedgerError) as exc:
        actual_bets.record_bet(db, USER_A, _ticket(legs=2), "idem-1", now, CAP, TZ, S.DataMode.FIXTURE)
    assert exc.value.reason_codes == ["NOT_THREE_LEGS"]
    with pytest.raises(LedgerError):
        actual_bets.record_bet(db, USER_A, _ticket(legs=4), "idem-2", now, CAP, TZ, S.DataMode.FIXTURE)
    assert actual_bets.list_bets(db, USER_A, DATE, DATE) == []


@pytest.mark.parametrize(
    ("placed_at", "expected_date"),
    [
        (datetime(2026, 10, 21, 3, 59, tzinfo=UTC), "2026-10-20"),  # 23:59 EDT
        (datetime(2026, 10, 21, 4, 0, tzinfo=UTC), "2026-10-21"),  # 00:00 EDT
        (datetime(2026, 11, 2, 4, 30, tzinfo=UTC), "2026-11-01"),  # 23:30 EST after DST end
        (datetime(2026, 11, 2, 5, 30, tzinfo=UTC), "2026-11-02"),  # 00:30 EST
        (datetime(2026, 11, 1, 5, 30, tzinfo=UTC), "2026-11-01"),  # 01:30 EDT (first pass)
        (datetime(2026, 11, 1, 6, 30, tzinfo=UTC), "2026-11-01"),  # 01:30 EST (second pass)
    ],
)
def test_et_day_boundary_including_dst_end(db, clock, placed_at, expected_date):
    bet, b, _ = actual_bets.record_bet(
        db,
        USER_A,
        _ticket(placed_at=placed_at),
        f"idem-{placed_at.isoformat()}",
        clock.now_utc(),
        CAP,
        TZ,
        S.DataMode.FIXTURE,
    )
    assert bet.date_local == expected_date
    assert b.date_local == expected_date
    assert b.recorded_stake_usd == Decimal("10.00")
    assert [x.bet_id for x in actual_bets.list_bets(db, USER_A, expected_date, expected_date)] == [bet.bet_id]


def test_dst_end_day_budget_spans_both_sides_of_the_fall_back(db, clock):
    now = clock.now_utc()
    actual_bets.record_bet(
        db,
        USER_A,
        _ticket("4.00", placed_at=datetime(2026, 11, 1, 5, 30, tzinfo=UTC)),
        "a",
        now,
        CAP,
        TZ,
        S.DataMode.FIXTURE,
    )
    actual_bets.record_bet(
        db,
        USER_A,
        _ticket("4.00", placed_at=datetime(2026, 11, 2, 4, 30, tzinfo=UTC)),
        "b",
        now,
        CAP,
        TZ,
        S.DataMode.FIXTURE,
    )
    b = budget.get_daily_budget(db, USER_A, "2026-11-01", now, CAP)
    assert b.recorded_stake_usd == Decimal("8.00")
    assert b.remaining_usd == Decimal("2.00")
    assert budget.get_daily_budget(db, USER_A, "2026-11-02", now, CAP).recorded_stake_usd == Decimal("0.00")


def test_fixture_data_refused_on_strict_ledger(strict_db, clock):
    now = clock.now_utc()
    with pytest.raises(FixtureLedgerError):
        actual_bets.record_bet(strict_db, USER_A, _ticket(), "idem-1", now, CAP, TZ, S.DataMode.FIXTURE)
    assert actual_bets.list_bets(strict_db, USER_A, DATE, DATE) == []
    bet, _, _ = actual_bets.record_bet(
        strict_db, USER_A, _ticket(), "idem-2", now, CAP, TZ, S.DataMode.MANUAL_INPUT
    )
    assert bet.status == S.BetStatus.PENDING
    assert actual_bets.get_stored_bet(strict_db, USER_A, bet.bet_id).data_mode == "MANUAL_INPUT"


def test_tenant_isolation(db, clock):
    now = clock.now_utc()
    bet_a, _, _ = actual_bets.record_bet(
        db, USER_A, _ticket(), "shared-key", now, CAP, TZ, S.DataMode.FIXTURE
    )
    assert actual_bets.get_bet(db, USER_B, bet_a.bet_id) is None
    assert actual_bets.get_stored_bet(db, USER_B, bet_a.bet_id) is None
    assert actual_bets.list_bets(db, USER_B, "2026-01-01", "2026-12-31") == []
    assert actual_bets.current_settlement(db, USER_B, bet_a.bet_id) is None
    bet_b, b, replay = actual_bets.record_bet(
        db, USER_B, _ticket(), "shared-key", now, CAP, TZ, S.DataMode.FIXTURE
    )
    assert replay is False
    assert bet_b.bet_id != bet_a.bet_id
    assert b.recorded_stake_usd == Decimal("10.00")
    assert budget.get_daily_budget(db, USER_A, DATE, now, CAP).recorded_stake_usd == Decimal("10.00")
    assert [x.user_id for x in actual_bets.list_bets(db, USER_A, DATE, DATE)] == [USER_A]


def test_restart_recovery_reopens_same_file(settings, clock):
    now = clock.now_utc()
    url = settings.effective_database_url
    db1 = open_database(url, allow_fixture_ledger=True)
    try:
        bet, _, _ = actual_bets.record_bet(
            db1,
            USER_A,
            _ticket(candidate_id="cand-1"),
            "idem-1",
            now,
            CAP,
            TZ,
            S.DataMode.FIXTURE,
            candidate_snapshot=SNAPSHOT,
        )
    finally:
        db1.dispose()
    db2 = open_database(url, allow_fixture_ledger=True)
    try:
        again = actual_bets.get_stored_bet(db2, USER_A, bet.bet_id)
        assert again is not None
        assert again.bet == bet
        assert again.forecast["p_joint"] == "0.200000"
        assert budget.get_daily_budget(db2, USER_A, DATE, now, CAP).recorded_stake_usd == Decimal("10.00")
        _, _, replay = actual_bets.record_bet(
            db2, USER_A, _ticket(candidate_id="cand-1"), "idem-1", now, CAP, TZ, S.DataMode.FIXTURE
        )
        assert replay is True
    finally:
        db2.dispose()


def test_ticket_hash_is_canonical_over_stored_values(db, clock):
    now = clock.now_utc()
    base = _ticket(accepted="5.50")
    assert actual_bets.ticket_payload_hash(_ticket(accepted="5.5")) == actual_bets.ticket_payload_hash(base)
    assert actual_bets.ticket_payload_hash(_ticket(accepted=None, accepted_american=450)) == (
        actual_bets.ticket_payload_hash(base)
    )
    spelled = base.model_copy(deep=True)
    spelled.legs[0].line = Decimal("3.50")
    spelled.legs[0].accepted_decimal = Decimal("1.90910")
    assert actual_bets.ticket_payload_hash(spelled) == actual_bets.ticket_payload_hash(base)
    assert actual_bets.ticket_payload_hash(_ticket("10.0")) == actual_bets.ticket_payload_hash(base)
    assert actual_bets.ticket_payload_hash(_ticket("9.00")) != actual_bets.ticket_payload_hash(base)
    assert actual_bets.ticket_payload_hash(_ticket(accepted="5.51")) != actual_bets.ticket_payload_hash(base)
    offset = _ticket(placed_at=datetime(2026, 10, 20, 15, 0, tzinfo=timezone(timedelta(hours=-4))))
    utc = _ticket(placed_at=datetime(2026, 10, 20, 19, 0, tzinfo=UTC))
    assert actual_bets.ticket_payload_hash(offset) == actual_bets.ticket_payload_hash(utc)
    # and the ledger replays rather than conflicting on a respelled retry
    first, _, _ = actual_bets.record_bet(db, USER_A, base, "idem-1", now, CAP, TZ, S.DataMode.FIXTURE)
    again, _, replay = actual_bets.record_bet(
        db, USER_A, _ticket(accepted=None, accepted_american=450), "idem-1", now, CAP, TZ, S.DataMode.FIXTURE
    )
    assert replay is True and again.bet_id == first.bet_id
    assert len(actual_bets.list_bets(db, USER_A, DATE, DATE)) == 1


def test_accepted_american_converted_exactly(db, clock):
    now = clock.now_utc()
    bet, _, _ = actual_bets.record_bet(
        db, USER_A, _ticket(accepted=None, accepted_american=450), "i1", now, CAP, TZ, S.DataMode.FIXTURE
    )
    assert bet.accepted_combined_decimal == Decimal("5.5000")
    bet2, _, _ = actual_bets.record_bet(
        db,
        USER_A,
        _ticket("0.00", accepted=None, accepted_american=-150),
        "i2",
        now,
        CAP,
        TZ,
        S.DataMode.FIXTURE,
    )
    assert bet2.accepted_combined_decimal == Decimal("1.6667")
    assert actual_bets.american_to_decimal(-110) == Decimal("1.9091")
    with pytest.raises(LedgerError):
        actual_bets.american_to_decimal(50)


def test_list_bets_is_ordered_and_bounded(db, clock):
    now = clock.now_utc()
    later = datetime(2026, 10, 22, 1, 0, tzinfo=UTC)  # 21:00 ET on 10-21
    actual_bets.record_bet(
        db, USER_A, _ticket("2.00", placed_at=later), "i2", now, CAP, TZ, S.DataMode.FIXTURE
    )
    actual_bets.record_bet(db, USER_A, _ticket("3.00", placed_at=now), "i1", now, CAP, TZ, S.DataMode.FIXTURE)
    listed = actual_bets.list_bets(db, USER_A, "2026-10-20", "2026-10-21")
    assert [x.stake_usd for x in listed] == [Decimal("3.00"), Decimal("2.00")]
    assert actual_bets.list_bets(db, USER_A, "2026-10-21", "2026-10-21")[0].stake_usd == Decimal("2.00")
    assert actual_bets.list_bets(db, USER_A, "2026-10-22", "2026-10-30") == []
    with db.engine.connect() as conn:
        rows = conn.execute(select(bets.c.user_id, bets.c.data_mode, bets.c.external)).all()
    assert {(r.user_id, r.data_mode, r.external) for r in rows} == {(USER_A, "FIXTURE", 0)}
