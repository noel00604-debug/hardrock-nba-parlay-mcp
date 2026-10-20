"""Independent adversarial review of the ledger module (budget, actual_bets, settlement, reports).

Every test here reproduced a defect against the original ledger code; the module fixes keep them
passing, except the one marked "documents correct behaviour" (which always passed) and the Money
rounding test, which is a foundation defect in ``schemas._nonneg_money`` (ROUND_HALF_EVEN) that the
ledger cannot fix in its own files: it is marked ``xfail(strict=True)`` so it fails loudly, and the
marker must be removed, as soon as the integration lead applies the request in
``docs/integration-notes/ledger.md``. Expected values are computed by hand with Decimal, never with
the module's own helpers. All data is FIXTURE-mode on the temporary SQLite database from conftest.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from hardrock_nba_parlay import actual_bets, budget, reports, settlement
from hardrock_nba_parlay import schemas as S

USER_A = "user-a"
CAP = Decimal("10.00")
TZ = "America/New_York"
DATE = "2026-10-20"  # conftest NOW is 2026-10-20T19:00Z == 15:00 ET
CENT = Decimal("0.01")

W, L, V = S.LegResult.WON, S.LegResult.LOST, S.LegResult.VOID


def _legs() -> list[S.AcceptedLeg]:
    return [
        S.AcceptedLeg(
            description=f"leg {i}",
            event_id=f"fixture:E{i}",
            market_type=S.MarketType.MONEYLINE,
            period=S.Period.FULL_GAME,
            side=S.Side.HOME,
            accepted_decimal=Decimal("1.8000"),
        )
        for i in range(3)
    ]


def _ticket(stake: str = "10.00", accepted: str | None = "5.50") -> S.ConfirmedTicketInput:
    return S.ConfirmedTicketInput(
        candidate_id="cand-1",
        legs=_legs(),
        accepted_combined_decimal=Decimal(accepted) if accepted else None,
        stake_usd=Decimal(stake),
        source=S.BetSource.USER_CONFIRMATION,
    )


def _book(status: S.BetStatus, cash: str | None = None, **kw) -> S.SettlementInput:
    return S.SettlementInput(
        status=status,
        source=S.SettlementSource.BOOK_CONFIRMED,
        cash_returned_usd=Decimal(cash) if cash is not None else None,
        **kw,
    )


def _provisional(status: S.BetStatus, **kw) -> S.SettlementInput:
    return S.SettlementInput(status=status, source=S.SettlementSource.PROVISIONAL_NBA_RESULTS, **kw)


def _record(
    db, now, key: str = "k1", ticket: S.ConfirmedTicketInput | None = None, snapshot=None
) -> S.ActualBet:
    bet, _, _ = actual_bets.record_bet(
        db, USER_A, ticket or _ticket(), key, now, CAP, TZ, S.DataMode.FIXTURE, candidate_snapshot=snapshot
    )
    return bet


FORECAST = {"p_joint": "0.200000", "model_state": "MARKET_BASELINE", "parlay_type": "MULTI_GAME"}


# --------------------------------------------------------------------------------------
# 1. A superseded provisional record appended AFTER a book settlement corrupts the report.
#    reports._latest_settlements / settlement.effective_leg_results take the highest seq regardless of
#    source, so the book's confirmed cash figure is dropped, the ticket is labelled provisional and the
#    leg hit rate is computed from the provisional (wrong) legs. The nightly provisional job will do
#    exactly this whenever its settled_at/stamp changes (new payload hash -> new row, SUPERSEDED_BY_BOOK).
# --------------------------------------------------------------------------------------


def test_report_keeps_book_figures_when_a_superseded_provisional_is_appended_later(db, clock):
    now = clock.now_utc()
    bet = _record(db, now, snapshot=FORECAST)
    settlement.reconcile(db, USER_A, bet.bet_id, _book(S.BetStatus.LOST, "0.00", leg_results=[W, L, W]), now)
    # provisional grading arrives later with a different stamp: appended, SUPERSEDED_BY_BOOK
    _, _, replay, warnings = settlement.reconcile(
        db,
        USER_A,
        bet.bet_id,
        _provisional(S.BetStatus.WON, leg_results=[W, W, W], settled_at_utc=now + timedelta(hours=1)),
        now + timedelta(hours=1),
    )
    assert replay is False and warnings == ["SUPERSEDED_BY_BOOK"]
    assert actual_bets.get_bet(db, USER_A, bet.bet_id).status == S.BetStatus.LOST

    rep = reports.performance(db, USER_A, DATE, DATE, now + timedelta(hours=2))
    expected_net = (Decimal("0.00") - Decimal("10.00")).quantize(CENT, rounding=ROUND_HALF_UP)  # -10.00
    summary = rep.bets[0]
    assert rep.net_profit_usd == expected_net, "book-confirmed loss must stay in net profit"
    assert rep.total_cash_returned_usd == Decimal("0.00")
    assert summary.net_usd == expected_net
    assert summary.cash_returned_usd == Decimal("0.00")
    assert summary.provisional is False, "a book-settled ticket must not be labelled provisional"
    assert summary.leg_results == [W, L, W], (
        "leg results must come from the book record, not the superseded one"
    )
    assert (rep.leg_hit_rate.numerator, rep.leg_hit_rate.denominator) == (2, 3)
    assert not any("without a confirmed cash-returned figure" in n for n in rep.incomplete_data_notes)
    assert not any("provisional" in n for n in rep.notes)


# --------------------------------------------------------------------------------------
# 2. Provisional records are given invented cash figures (LOST -> 0.00, VOID -> stake) and a provisional
#    LOST flows into net_profit_usd as if confirmed, while a provisional WON carries no cash and is
#    excluded. The report's own note says net counts "confirmed cash-returned figure only", and the
#    module's provisional notes say "Cash figures await the book"; net profit is biased downward during
#    the provisional window.
# --------------------------------------------------------------------------------------


def test_provisional_records_never_carry_invented_cash_or_profit(db, clock):
    now = clock.now_utc()
    bet = _record(db, now)
    bet_after, rec, _, warnings = settlement.reconcile(
        db, USER_A, bet.bet_id, _provisional(S.BetStatus.LOST, leg_results=[W, L, W]), now
    )
    assert warnings == ["PROVISIONAL_RESULT"]
    assert rec.cash_returned_usd is None, "no cash figure exists until the book settles"
    assert settlement.cash_profit(bet_after, rec) is None

    rep = reports.performance(db, USER_A, DATE, DATE, now)
    assert rep.bets[0].provisional is True
    assert rep.bets[0].net_usd is None
    assert rep.net_profit_usd == Decimal("0.00"), "provisional results must not move net profit"
    assert rep.total_cash_returned_usd == Decimal("0.00")

    _, rec_void, _, _ = settlement.reconcile(
        db, USER_A, bet.bet_id, _provisional(S.BetStatus.VOID, leg_results=[V, V, V]), now
    )
    assert rec_void.cash_returned_usd is None, "a provisional VOID must not default cash to the stake"


# --------------------------------------------------------------------------------------
# 3. A CORRECTED ticket whose corrected leg results contain a LOST leg (cash 0.00) is dropped from the
#    ticket win rate (0/0) and from calibration, and the 30-day review reports it as "void or other".
#    Stat corrections usually go against the bettor, so the win rate is biased upward and the forecast
#    loses its (now known) outcome. The brief: ticket_win_rate = won / settled-with-result.
# --------------------------------------------------------------------------------------


def test_corrected_ticket_with_lost_leg_counts_as_a_loss(db, clock):
    now = clock.now_utc()
    bet = _record(db, now, snapshot=FORECAST)
    settlement.reconcile(db, USER_A, bet.bet_id, _book(S.BetStatus.WON, "55.00", leg_results=[W, W, W]), now)
    settlement.reconcile(
        db,
        USER_A,
        bet.bet_id,
        _book(S.BetStatus.CORRECTED, "0.00", leg_results=[W, W, L], notes="stat correction"),
        now + timedelta(hours=1),
    )
    rep = reports.performance(db, USER_A, DATE, DATE, now + timedelta(hours=2))
    assert rep.net_profit_usd == Decimal("-10.00")  # already right: 0.00 - 10.00
    assert (rep.ticket_win_rate.numerator, rep.ticket_win_rate.denominator) == (0, 1)
    assert [c.outcome for c in rep.calibration] == ["LOST"]
    bucket = rep.by_parlay_type["MULTI_GAME"]
    assert (bucket.won, bucket.lost, bucket.void_or_other) == (0, 1, 0)
    review = reports.thirty_day_review(db, USER_A, DATE, "2026-11-18", CAP, now + timedelta(hours=2))
    assert any("lost 1" in line for line in review.observed_results)


# --------------------------------------------------------------------------------------
# 4/5. Idempotency hashes are not canonical: the same ticket or settlement re-sent with a different
#      Decimal spelling (5.5 vs 5.50, 3.2 vs 3.20) hashes differently, so a retry raises
#      IDEMPOTENCY_CONFLICT (bet) or appends a new settlement row instead of replaying.
# --------------------------------------------------------------------------------------


def test_same_ticket_with_different_decimal_spelling_replays(db, clock):
    now = clock.now_utc()
    first = _record(db, now, "k1", _ticket(accepted="5.50"))
    second, _, replay = actual_bets.record_bet(
        db, USER_A, _ticket(accepted="5.5"), "k1", now, CAP, TZ, S.DataMode.FIXTURE
    )
    assert replay is True
    assert second.bet_id == first.bet_id
    assert len(actual_bets.list_bets(db, USER_A, DATE, DATE)) == 1


def test_same_settlement_with_different_decimal_spelling_replays(db, clock):
    now = clock.now_utc()
    bet = _record(db, now)
    _, first, _, _ = settlement.reconcile(
        db,
        USER_A,
        bet.bet_id,
        _book(S.BetStatus.REPRICED, "32.00", repriced_combined_decimal=Decimal("3.20")),
        now,
    )
    _, again, replay, warnings = settlement.reconcile(
        db,
        USER_A,
        bet.bet_id,
        _book(S.BetStatus.REPRICED, "32.00", repriced_combined_decimal=Decimal("3.2")),
        now,
    )
    assert replay is True and warnings == ["IDEMPOTENT_REPLAY"]
    assert again.settlement_id == first.settlement_id
    assert len(settlement.list_settlements(db, USER_A, bet.bet_id)) == 1


# --------------------------------------------------------------------------------------
# 6. Rounding: the ledger quantizes raw Decimal inputs ROUND_HALF_UP (reserve, cap) but every pydantic
#    Money field (stake_usd, cash_returned_usd, ...) is quantized by schemas._nonneg_money with the
#    default ROUND_HALF_EVEN before the ledger sees it. The same stake reserves as 2.35 and records as
#    2.34. Root cause is in schemas.py (foundation), observable only through the ledger API.
# --------------------------------------------------------------------------------------


def test_money_inputs_round_half_up_like_the_ledger(db, clock):
    now = clock.now_utc()
    raw = Decimal("2.345")
    expected = raw.quantize(CENT, rounding=ROUND_HALF_UP)  # 2.35
    reservation, _ = budget.reserve(db, USER_A, DATE, "cand-1", raw, "r1", now, CAP, now + timedelta(hours=1))
    assert reservation.stake_usd == expected
    bet = _record(db, now, "k1", _ticket(stake="2.345"))
    assert bet.stake_usd == expected, "stake must round the same way the reservation did"
    cash = S.SettlementInput(status=S.BetStatus.WON, cash_returned_usd=Decimal("55.005")).cash_returned_usd
    assert cash == Decimal("55.005").quantize(CENT, rounding=ROUND_HALF_UP)  # 55.01


# --------------------------------------------------------------------------------------
# 7. A book re-settlement whose payload equals an OLDER record (not the latest) is treated as a replay
#    of that older record, so the authoritative latest book figure is dropped and the bet keeps the
#    intervening status. WON -> CORRECTED -> WON again leaves the bet CORRECTED with a LOST leg.
#    Replay should mean "identical to the latest record"; a ledger-local fix is to key the stored hash
#    on the preceding seq (the db UNIQUE(bet_id, payload_hash) then no longer collides).
# --------------------------------------------------------------------------------------


def test_book_resettlement_identical_to_an_older_record_is_not_dropped(db, clock):
    now = clock.now_utc()
    bet = _record(db, now)
    won = _book(S.BetStatus.WON, "55.00", leg_results=[W, W, W])
    settlement.reconcile(db, USER_A, bet.bet_id, won, now)
    settlement.reconcile(
        db,
        USER_A,
        bet.bet_id,
        _book(S.BetStatus.CORRECTED, "0.00", leg_results=[W, W, L]),
        now + timedelta(hours=1),
    )
    bet_after, rec, replay, _ = settlement.reconcile(db, USER_A, bet.bet_id, won, now + timedelta(hours=2))
    assert replay is False, "the book reverting its correction is a new event, not a replay of seq 1"
    assert rec.seq == 3
    assert bet_after.status == S.BetStatus.WON
    assert [leg.result for leg in bet_after.legs] == [W, W, W]
    assert settlement.cash_profit(
        bet_after, actual_bets.current_settlement(db, USER_A, bet.bet_id)
    ) == Decimal("45.00")
    assert actual_bets.get_bet(db, USER_A, bet.bet_id).status == S.BetStatus.WON


# --------------------------------------------------------------------------------------
# Documents correct behaviour (passes): concurrent reconciles of one bet never collide on seq.
# Not covered by the module's own tests; relies on BEGIN IMMEDIATE serialising db.tx() on SQLite.
# --------------------------------------------------------------------------------------


def test_concurrent_reconciles_get_unique_sequence_numbers(db, clock):
    now = clock.now_utc()
    bet = _record(db, now)

    def attempt(i: int) -> int:
        _, rec, _, _ = settlement.reconcile(
            db, USER_A, bet.bet_id, _book(S.BetStatus.WON, "55.00", notes=f"attempt {i}"), now
        )
        return rec.seq

    with ThreadPoolExecutor(max_workers=10) as pool:
        seqs = sorted(pool.map(attempt, range(10)))
    assert seqs == list(range(1, 11))
    assert [r.seq for r in settlement.list_settlements(db, USER_A, bet.bet_id)] == list(range(1, 11))
