"""Settlement tests: append-only records, replay, book authority over provisional results, every
status flow, cash profit arithmetic, provisional grading from NBA results, tenant isolation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from hardrock_nba_parlay import actual_bets, settlement
from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.budget import LedgerError, NotFoundError
from hardrock_nba_parlay.db import open_database

USER_A = "user-a"
USER_B = "user-b"
CAP = Decimal("10.00")
TZ = "America/New_York"
E1, E2, E3 = "fixture:BOS@DET", "fixture:PHI@NYK", "fixture:OKC@SAS"


def _stamp(at: datetime) -> S.SourceStamp:
    return S.SourceStamp(
        source="fixture:results", received_at_utc=at, source_timestamp_utc=at, data_mode=S.DataMode.FIXTURE
    )


def _legs() -> list[S.AcceptedLeg]:
    return [
        S.AcceptedLeg(
            description="DET -3.5",
            event_id=E1,
            market_type=S.MarketType.SPREAD,
            period=S.Period.FULL_GAME,
            side=S.Side.HOME,
            line=Decimal("-3.5"),
            team_name="Detroit Pistons",
            accepted_decimal=Decimal("1.9091"),
        ),
        S.AcceptedLeg(
            description="PHI/NYK over 224.5",
            event_id=E2,
            market_type=S.MarketType.TOTAL,
            period=S.Period.FULL_GAME,
            side=S.Side.OVER,
            line=Decimal("224.5"),
            accepted_decimal=Decimal("1.9091"),
        ),
        S.AcceptedLeg(
            description="Jalen Brunson over 25.5 pts",
            event_id=E3,
            market_type=S.MarketType.PLAYER_POINTS,
            period=S.Period.FULL_GAME,
            side=S.Side.OVER,
            line=Decimal("25.5"),
            player_name="Jalen Brunson",
            accepted_decimal=Decimal("1.8700"),
        ),
    ]


def _result(
    event_id: str,
    home: int | None,
    away: int | None,
    at: datetime,
    *,
    completed: bool = True,
    status: S.EventStatus = S.EventStatus.FINAL,
) -> S.GameResult:
    return S.GameResult(
        event_id=event_id,
        home_score=home,
        away_score=away,
        completed=completed,
        status=status,
        stamp=_stamp(at),
    )


def _stat(
    event_id: str,
    name: str,
    at: datetime,
    *,
    played: bool = True,
    points: int | None = None,
    rebounds: int | None = None,
    assists: int | None = None,
    threes: int | None = None,
) -> S.PlayerGameStat:
    return S.PlayerGameStat(
        event_id=event_id,
        player_name_raw=name,
        played=played,
        points=points,
        rebounds=rebounds,
        assists=assists,
        threes=threes,
        stamp=_stamp(at),
    )


@pytest.fixture
def placed_bet(db, clock) -> S.ActualBet:
    ticket = S.ConfirmedTicketInput(
        candidate_id="cand-1",
        ticket_ref="HR-1",
        legs=_legs(),
        accepted_combined_decimal=Decimal("5.50"),
        stake_usd=Decimal("10.00"),
        source=S.BetSource.USER_CONFIRMATION,
    )
    bet, _, _ = actual_bets.record_bet(
        db, USER_A, ticket, "idem-1", clock.now_utc(), CAP, TZ, S.DataMode.FIXTURE
    )
    return bet


def _book(status: S.BetStatus, cash: str | None = None, **kw) -> S.SettlementInput:
    return S.SettlementInput(
        status=status,
        source=S.SettlementSource.BOOK_CONFIRMED,
        cash_returned_usd=Decimal(cash) if cash is not None else None,
        **kw,
    )


def _provisional(status: S.BetStatus, **kw) -> S.SettlementInput:
    return S.SettlementInput(status=status, source=S.SettlementSource.PROVISIONAL_NBA_RESULTS, **kw)


def test_book_won_sets_status_legs_and_profit(db, clock, placed_bet):
    now = clock.now_utc()
    bet, rec, replay, warnings = settlement.reconcile(
        db, USER_A, placed_bet.bet_id, _book(S.BetStatus.WON, "55.00", leg_results=[S.LegResult.WON] * 3), now
    )
    assert replay is False and warnings == []
    assert rec.seq == 1 and rec.status == S.BetStatus.WON and rec.source == S.SettlementSource.BOOK_CONFIRMED
    assert rec.cash_returned_usd == Decimal("55.00")
    assert bet.status == S.BetStatus.WON
    assert [leg.result for leg in bet.legs] == [S.LegResult.WON] * 3
    assert settlement.cash_profit(bet, rec) == Decimal("45.00")  # returns include the $10 stake
    assert actual_bets.get_bet(db, USER_A, bet.bet_id).status == S.BetStatus.WON
    assert actual_bets.current_settlement(db, USER_A, bet.bet_id) == rec
    assert bet.stake_usd == Decimal("10.00")  # settlement never alters the stake


def test_replay_of_identical_payload_adds_no_row(db, clock, placed_bet):
    now = clock.now_utc()
    payload = _book(S.BetStatus.WON, "55.00", leg_results=[S.LegResult.WON] * 3)
    _, first, _, _ = settlement.reconcile(db, USER_A, placed_bet.bet_id, payload, now)
    clock.advance(3600)
    bet, again, replay, warnings = settlement.reconcile(
        db, USER_A, placed_bet.bet_id, payload, clock.now_utc()
    )
    assert replay is True
    assert again == first
    assert warnings == ["IDEMPOTENT_REPLAY"]
    assert len(settlement.list_settlements(db, USER_A, bet.bet_id)) == 1
    assert settlement.cash_profit(bet, again) == Decimal("45.00")


def test_lost_defaults_cash_to_zero(db, clock, placed_bet):
    bet, rec, _, warnings = settlement.reconcile(
        db,
        USER_A,
        placed_bet.bet_id,
        _book(S.BetStatus.LOST, leg_results=[S.LegResult.WON, S.LegResult.LOST, S.LegResult.WON]),
        clock.now_utc(),
    )
    assert warnings == []
    assert rec.cash_returned_usd == Decimal("0.00")
    assert settlement.cash_profit(bet, rec) == Decimal("-10.00")
    assert [leg.result for leg in bet.legs] == [S.LegResult.WON, S.LegResult.LOST, S.LegResult.WON]


def test_void_defaults_cash_to_stake(db, clock, placed_bet):
    bet, rec, _, warnings = settlement.reconcile(
        db, USER_A, placed_bet.bet_id, _book(S.BetStatus.VOID), clock.now_utc()
    )
    assert warnings == []
    assert bet.status == S.BetStatus.VOID
    assert rec.cash_returned_usd == Decimal("10.00")
    assert settlement.cash_profit(bet, rec) == Decimal("0.00")


def test_void_with_explicit_cash_keeps_it(db, clock, placed_bet):
    bet, rec, _, _ = settlement.reconcile(
        db, USER_A, placed_bet.bet_id, _book(S.BetStatus.VOID, "9.50"), clock.now_utc()
    )
    assert rec.cash_returned_usd == Decimal("9.50")
    assert settlement.cash_profit(bet, rec) == Decimal("-0.50")


def test_partially_void_without_figures_warns_but_is_stored(db, clock, placed_bet):
    bet, rec, _, warnings = settlement.reconcile(
        db,
        USER_A,
        placed_bet.bet_id,
        _book(S.BetStatus.PARTIALLY_VOID, leg_results=[S.LegResult.WON, S.LegResult.VOID, S.LegResult.WON]),
        clock.now_utc(),
    )
    assert warnings == ["SETTLEMENT_RULES_UNKNOWN"]
    assert bet.status == S.BetStatus.PARTIALLY_VOID
    assert rec.cash_returned_usd is None and rec.repriced_combined_decimal is None
    assert settlement.cash_profit(bet, rec) is None
    assert [leg.result for leg in bet.legs] == [S.LegResult.WON, S.LegResult.VOID, S.LegResult.WON]


def test_partially_void_with_cash_is_complete(db, clock, placed_bet):
    bet, rec, _, warnings = settlement.reconcile(
        db,
        USER_A,
        placed_bet.bet_id,
        _book(S.BetStatus.PARTIALLY_VOID, "28.80", repriced_combined_decimal=Decimal("2.88")),
        clock.now_utc(),
    )
    assert warnings == []
    assert rec.repriced_combined_decimal == Decimal("2.88")
    assert settlement.cash_profit(bet, rec) == Decimal("18.80")


def test_repriced_requires_figures(db, clock, placed_bet):
    _, _, _, w1 = settlement.reconcile(
        db, USER_A, placed_bet.bet_id, _book(S.BetStatus.REPRICED), clock.now_utc()
    )
    assert w1 == ["SETTLEMENT_RULES_UNKNOWN"]
    bet, rec, _, w2 = settlement.reconcile(
        db,
        USER_A,
        placed_bet.bet_id,
        _book(S.BetStatus.REPRICED, "32.00", repriced_combined_decimal=Decimal("3.20")),
        clock.now_utc(),
    )
    assert w2 == []
    assert rec.seq == 2
    assert settlement.cash_profit(bet, rec) == Decimal("22.00")


def test_cashed_out_requires_cash(db, clock, placed_bet):
    with pytest.raises(LedgerError) as exc:
        settlement.reconcile(db, USER_A, placed_bet.bet_id, _book(S.BetStatus.CASHED_OUT), clock.now_utc())
    assert exc.value.reason_codes == ["INVALID_INPUT"]
    assert settlement.list_settlements(db, USER_A, placed_bet.bet_id) == []
    bet, rec, _, warnings = settlement.reconcile(
        db, USER_A, placed_bet.bet_id, _book(S.BetStatus.CASHED_OUT, "7.50"), clock.now_utc()
    )
    assert warnings == []
    assert bet.status == S.BetStatus.CASHED_OUT
    assert settlement.cash_profit(bet, rec) == Decimal("-2.50")


def test_disputed_keeps_profit_unknown(db, clock, placed_bet):
    bet, rec, _, _ = settlement.reconcile(
        db,
        USER_A,
        placed_bet.bet_id,
        _book(S.BetStatus.DISPUTED, "55.00", notes="book shows pending review"),
        clock.now_utc(),
    )
    assert bet.status == S.BetStatus.DISPUTED
    assert rec.cash_returned_usd == Decimal("55.00")
    assert settlement.cash_profit(bet, rec) is None
    assert settlement.cash_profit(bet, None) is None


def test_pending_book_settlement_has_no_profit(db, clock, placed_bet):
    bet, rec, _, _ = settlement.reconcile(
        db, USER_A, placed_bet.bet_id, _book(S.BetStatus.PENDING), clock.now_utc()
    )
    assert bet.status == S.BetStatus.PENDING
    assert settlement.cash_profit(bet, rec) is None


def test_corrected_supersedes_prior_values_and_keeps_history(db, clock, placed_bet):
    now = clock.now_utc()
    settlement.reconcile(
        db, USER_A, placed_bet.bet_id, _book(S.BetStatus.WON, "55.00", leg_results=[S.LegResult.WON] * 3), now
    )
    bet, rec, _, warnings = settlement.reconcile(
        db,
        USER_A,
        placed_bet.bet_id,
        _book(
            S.BetStatus.CORRECTED,
            "0.00",
            leg_results=[S.LegResult.WON, S.LegResult.WON, S.LegResult.LOST],
            notes="stat correction: Brunson 25 pts",
        ),
        now + timedelta(hours=2),
    )
    assert warnings == []
    assert rec.seq == 2
    assert bet.status == S.BetStatus.CORRECTED
    assert [leg.result for leg in bet.legs] == [S.LegResult.WON, S.LegResult.WON, S.LegResult.LOST]
    assert settlement.cash_profit(bet, rec) == Decimal("-10.00")
    history = settlement.list_settlements(db, USER_A, bet.bet_id)
    assert [h.seq for h in history] == [1, 2]
    assert [h.status for h in history] == [S.BetStatus.WON, S.BetStatus.CORRECTED]
    assert actual_bets.current_settlement(db, USER_A, bet.bet_id).seq == 2


def test_bonus_is_kept_separate_from_cash(db, clock, placed_bet):
    bet, rec, _, _ = settlement.reconcile(
        db,
        USER_A,
        placed_bet.bet_id,
        _book(S.BetStatus.LOST, "0.00", bonus_returned_usd=Decimal("10.00")),
        clock.now_utc(),
    )
    assert rec.bonus_returned_usd == Decimal("10.00")
    assert settlement.cash_profit(bet, rec) == Decimal("-10.00")


def test_provisional_sets_status_when_no_book_settlement(db, clock, placed_bet):
    bet, rec, _, warnings = settlement.reconcile(
        db,
        USER_A,
        placed_bet.bet_id,
        _provisional(S.BetStatus.WON, leg_results=[S.LegResult.WON] * 3),
        clock.now_utc(),
    )
    assert warnings == ["PROVISIONAL_RESULT"]
    assert bet.status == S.BetStatus.WON
    assert rec.source == S.SettlementSource.PROVISIONAL_NBA_RESULTS
    assert [leg.result for leg in bet.legs] == [
        S.LegResult.PENDING
    ] * 3  # provisional legs stay on the record
    assert settlement.effective_leg_results(bet, rec) == [S.LegResult.WON] * 3
    assert settlement.cash_profit(bet, rec) is None  # no cash figure from NBA results
    assert actual_bets.get_bet(db, USER_A, bet.bet_id).status == S.BetStatus.WON


def test_provisional_never_overrides_book(db, clock, placed_bet):
    now = clock.now_utc()
    settlement.reconcile(
        db,
        USER_A,
        placed_bet.bet_id,
        _book(S.BetStatus.LOST, "0.00", leg_results=[S.LegResult.WON, S.LegResult.LOST, S.LegResult.WON]),
        now,
    )
    bet, rec, replay, warnings = settlement.reconcile(
        db,
        USER_A,
        placed_bet.bet_id,
        _provisional(S.BetStatus.WON, leg_results=[S.LegResult.WON] * 3),
        now + timedelta(minutes=5),
    )
    assert replay is False
    assert warnings == ["SUPERSEDED_BY_BOOK"]
    assert rec.seq == 2  # appended for the record
    assert bet.status == S.BetStatus.LOST
    assert [leg.result for leg in bet.legs] == [S.LegResult.WON, S.LegResult.LOST, S.LegResult.WON]
    assert actual_bets.get_bet(db, USER_A, bet.bet_id).status == S.BetStatus.LOST
    # repeated provisional checks do not pile up rows
    _, _, replay2, _ = settlement.reconcile(
        db,
        USER_A,
        placed_bet.bet_id,
        _provisional(S.BetStatus.WON, leg_results=[S.LegResult.WON] * 3),
        now + timedelta(minutes=10),
    )
    assert replay2 is True
    assert len(settlement.list_settlements(db, USER_A, bet.bet_id)) == 2


def test_book_after_provisional_takes_over(db, clock, placed_bet):
    now = clock.now_utc()
    settlement.reconcile(
        db, USER_A, placed_bet.bet_id, _provisional(S.BetStatus.WON, leg_results=[S.LegResult.WON] * 3), now
    )
    bet, rec, _, warnings = settlement.reconcile(
        db,
        USER_A,
        placed_bet.bet_id,
        _book(S.BetStatus.LOST, "0.00", leg_results=[S.LegResult.LOST, S.LegResult.WON, S.LegResult.WON]),
        now,
    )
    assert warnings == []
    assert bet.status == S.BetStatus.LOST
    assert settlement.cash_profit(bet, rec) == Decimal("-10.00")


def test_provisional_partially_void_does_not_change_status(db, clock, placed_bet):
    bet, rec, _, warnings = settlement.reconcile(
        db,
        USER_A,
        placed_bet.bet_id,
        _provisional(
            S.BetStatus.PARTIALLY_VOID, leg_results=[S.LegResult.WON, S.LegResult.VOID, S.LegResult.WON]
        ),
        clock.now_utc(),
    )
    assert set(warnings) == {"PROVISIONAL_RESULT", "SETTLEMENT_RULES_UNKNOWN"}
    assert bet.status == S.BetStatus.PENDING
    assert rec.status == S.BetStatus.PARTIALLY_VOID
    assert settlement.cash_profit(bet, rec) is None


def test_leg_results_length_must_match(db, clock, placed_bet):
    with pytest.raises(LedgerError) as exc:
        settlement.reconcile(
            db,
            USER_A,
            placed_bet.bet_id,
            _book(S.BetStatus.WON, "55.00", leg_results=[S.LegResult.WON]),
            clock.now_utc(),
        )
    assert exc.value.reason_codes == ["INVALID_INPUT"]
    assert settlement.list_settlements(db, USER_A, placed_bet.bet_id) == []


def test_other_user_cannot_settle_or_read(db, clock, placed_bet):
    with pytest.raises(NotFoundError) as exc:
        settlement.reconcile(db, USER_B, placed_bet.bet_id, _book(S.BetStatus.WON, "55.00"), clock.now_utc())
    assert exc.value.reason_codes == ["NOT_FOUND"]
    assert settlement.list_settlements(db, USER_B, placed_bet.bet_id) == []
    assert settlement.list_settlements(db, USER_A, placed_bet.bet_id) == []
    assert actual_bets.get_bet(db, USER_A, placed_bet.bet_id).status == S.BetStatus.PENDING


def test_unknown_bet_is_not_found(db, clock):
    with pytest.raises(NotFoundError):
        settlement.reconcile(
            db, USER_A, "bet_does_not_exist", _book(S.BetStatus.WON, "1.00"), clock.now_utc()
        )


def test_settlements_survive_restart(settings, clock):
    url = settings.effective_database_url
    db1 = open_database(url, allow_fixture_ledger=True)
    try:
        ticket = S.ConfirmedTicketInput(
            legs=_legs(), accepted_combined_decimal=Decimal("5.50"), stake_usd=Decimal("10.00")
        )
        bet, _, _ = actual_bets.record_bet(
            db1, USER_A, ticket, "idem-1", clock.now_utc(), CAP, TZ, S.DataMode.FIXTURE
        )
        settlement.reconcile(
            db1,
            USER_A,
            bet.bet_id,
            _book(S.BetStatus.WON, "55.00", leg_results=[S.LegResult.WON] * 3),
            clock.now_utc(),
        )
    finally:
        db1.dispose()
    db2 = open_database(url, allow_fixture_ledger=True)
    try:
        reloaded = actual_bets.get_bet(db2, USER_A, bet.bet_id)
        current = actual_bets.current_settlement(db2, USER_A, bet.bet_id)
        assert reloaded.status == S.BetStatus.WON
        assert settlement.cash_profit(reloaded, current) == Decimal("45.00")
        _, _, replay, _ = settlement.reconcile(
            db2,
            USER_A,
            bet.bet_id,
            _book(S.BetStatus.WON, "55.00", leg_results=[S.LegResult.WON] * 3),
            clock.now_utc(),
        )
        assert replay is True
    finally:
        db2.dispose()


# --------------------------------------------------------------------------------------
# Effective settlement, replay chaining, provisional cash, ticket outcome
# --------------------------------------------------------------------------------------


def test_effective_settlement_prefers_latest_book_record(db, clock, placed_bet):
    now = clock.now_utc()
    settlement.reconcile(
        db, USER_A, placed_bet.bet_id, _provisional(S.BetStatus.WON, leg_results=[S.LegResult.WON] * 3), now
    )
    _, book, _, _ = settlement.reconcile(
        db,
        USER_A,
        placed_bet.bet_id,
        _book(S.BetStatus.LOST, "0.00", leg_results=[S.LegResult.WON, S.LegResult.LOST, S.LegResult.WON]),
        now + timedelta(minutes=5),
    )
    bet, later, replay, warnings = settlement.reconcile(
        db,
        USER_A,
        placed_bet.bet_id,
        _provisional(
            S.BetStatus.WON, leg_results=[S.LegResult.WON] * 3, settled_at_utc=now + timedelta(hours=1)
        ),
        now + timedelta(hours=1),
    )
    assert replay is False and warnings == ["SUPERSEDED_BY_BOOK"] and later.seq == 3
    records = settlement.list_settlements(db, USER_A, bet.bet_id)
    assert settlement.effective_settlement(records) == book
    assert settlement.current_effective_settlement(db, USER_A, bet.bet_id) == book
    assert actual_bets.current_settlement(db, USER_A, bet.bet_id) == later  # highest seq, as documented
    # even when handed the superseded record, leg results come from the book-graded bet
    assert settlement.effective_leg_results(bet, later) == [
        S.LegResult.WON,
        S.LegResult.LOST,
        S.LegResult.WON,
    ]
    assert settlement.cash_profit(bet, later) is None
    assert settlement.cash_profit(bet, book) == Decimal("-10.00")
    assert settlement.effective_settlement([]) is None


def test_replay_means_identical_to_the_latest_record_only(db, clock, placed_bet):
    now = clock.now_utc()
    won = _book(S.BetStatus.WON, "55.00", leg_results=[S.LegResult.WON] * 3)
    corrected = _book(
        S.BetStatus.CORRECTED, "0.00", leg_results=[S.LegResult.WON, S.LegResult.WON, S.LegResult.LOST]
    )
    _, r1, _, _ = settlement.reconcile(db, USER_A, placed_bet.bet_id, won, now)
    _, r2, _, _ = settlement.reconcile(db, USER_A, placed_bet.bet_id, corrected, now + timedelta(hours=1))
    _, r2_again, replay, _ = settlement.reconcile(
        db, USER_A, placed_bet.bet_id, corrected, now + timedelta(hours=2)
    )
    assert replay is True and r2_again == r2
    bet, r3, replay3, warnings = settlement.reconcile(
        db, USER_A, placed_bet.bet_id, won, now + timedelta(hours=3)
    )
    assert replay3 is False and warnings == [] and r3.seq == 3
    assert bet.status == S.BetStatus.WON and [leg.result for leg in bet.legs] == [S.LegResult.WON] * 3
    assert len({r.payload_hash for r in (r1, r2, r3)}) == 3  # chained to the preceding seq
    assert settlement.settlement_payload_hash(won, 0) == r1.payload_hash
    assert settlement.settlement_payload_hash(won, 2) == r3.payload_hash


def test_settlement_hash_is_canonical_for_decimal_spelling_and_datetime_offset():
    a = _book(S.BetStatus.REPRICED, "32.00", repriced_combined_decimal=Decimal("3.20"), settled_at_utc=AT)
    b = _book(
        S.BetStatus.REPRICED,
        "32.0",
        repriced_combined_decimal=Decimal("3.2"),
        settled_at_utc=AT.astimezone(timezone(timedelta(hours=-4))),
    )
    assert settlement.canonical_settlement_json(a) == settlement.canonical_settlement_json(b)
    assert settlement.settlement_payload_hash(a, 0) == settlement.settlement_payload_hash(b, 0)
    assert settlement.settlement_payload_hash(a, 0) != settlement.settlement_payload_hash(a, 1)
    c = _book(S.BetStatus.REPRICED, "32.01", repriced_combined_decimal=Decimal("3.20"), settled_at_utc=AT)
    assert settlement.settlement_payload_hash(a, 0) != settlement.settlement_payload_hash(c, 0)


def test_provisional_records_get_no_cash_defaults(db, clock, placed_bet):
    now = clock.now_utc()
    bet, lost, _, warnings = settlement.reconcile(
        db,
        USER_A,
        placed_bet.bet_id,
        _provisional(S.BetStatus.LOST, leg_results=[S.LegResult.WON, S.LegResult.LOST, S.LegResult.WON]),
        now,
    )
    assert warnings == ["PROVISIONAL_RESULT"] and bet.status == S.BetStatus.LOST
    assert lost.cash_returned_usd is None and settlement.cash_profit(bet, lost) is None
    _, void, _, _ = settlement.reconcile(
        db, USER_A, placed_bet.bet_id, _provisional(S.BetStatus.VOID, leg_results=[S.LegResult.VOID] * 3), now
    )
    assert void.cash_returned_usd is None
    # a figure the caller supplies is stored as given but still yields no profit (it is not the book's)
    _, explicit, _, _ = settlement.reconcile(
        db, USER_A, placed_bet.bet_id, _provisional(S.BetStatus.LOST, cash_returned_usd=Decimal("0.00")), now
    )
    assert explicit.cash_returned_usd == Decimal("0.00")
    assert settlement.cash_profit(bet, explicit) is None


def test_ticket_outcome_resolves_corrections(db, clock, placed_bet):
    now = clock.now_utc()
    bet = placed_bet
    assert settlement.ticket_outcome(bet, None) is None  # PENDING
    bet, won, _, _ = settlement.reconcile(
        db, USER_A, bet.bet_id, _book(S.BetStatus.WON, "55.00", leg_results=[S.LegResult.WON] * 3), now
    )
    assert settlement.ticket_outcome(bet, won) == S.BetStatus.WON
    # correction without leg results but a 0.00 return: lost, whatever the stale legs say
    bet, zero, _, _ = settlement.reconcile(
        db, USER_A, bet.bet_id, _book(S.BetStatus.CORRECTED, "0.00"), now + timedelta(hours=1)
    )
    assert [leg.result for leg in bet.legs] == [S.LegResult.WON] * 3
    assert settlement.ticket_outcome(bet, zero) == S.BetStatus.LOST
    # correction with a lost leg
    bet, lost_leg, _, _ = settlement.reconcile(
        db,
        USER_A,
        bet.bet_id,
        _book(
            S.BetStatus.CORRECTED, "0.00", leg_results=[S.LegResult.WON, S.LegResult.WON, S.LegResult.LOST]
        ),
        now + timedelta(hours=2),
    )
    assert settlement.ticket_outcome(bet, lost_leg) == S.BetStatus.LOST
    # upward payout correction, legs all won: still a win
    bet, upward, _, _ = settlement.reconcile(
        db,
        USER_A,
        bet.bet_id,
        _book(S.BetStatus.CORRECTED, "60.00", leg_results=[S.LegResult.WON] * 3),
        now + timedelta(hours=3),
    )
    assert settlement.ticket_outcome(bet, upward) == S.BetStatus.WON
    # a corrected partial void has no binary result
    bet, partial, _, _ = settlement.reconcile(
        db,
        USER_A,
        bet.bet_id,
        _book(
            S.BetStatus.CORRECTED,
            "28.80",
            leg_results=[S.LegResult.WON, S.LegResult.VOID, S.LegResult.WON],
        ),
        now + timedelta(hours=4),
    )
    assert settlement.ticket_outcome(bet, partial) is None
    bet, void, _, _ = settlement.reconcile(
        db, USER_A, bet.bet_id, _book(S.BetStatus.VOID), now + timedelta(hours=5)
    )
    assert settlement.ticket_outcome(bet, void) is None


# --------------------------------------------------------------------------------------
# provisional_from_results
# --------------------------------------------------------------------------------------


AT = datetime(2026, 10, 21, 4, 0, tzinfo=UTC)


def test_provisional_from_results_all_won(placed_bet):
    results = [_result(E1, 110, 100, AT), _result(E2, 115, 112, AT), _result(E3, 100, 99, AT)]
    stats = [_stat(E3, "Jalen Brunson", AT, points=30)]
    s = settlement.provisional_from_results(placed_bet, results, stats)
    assert s is not None
    assert s.source == S.SettlementSource.PROVISIONAL_NBA_RESULTS
    assert s.status == S.BetStatus.WON
    assert s.leg_results == [S.LegResult.WON] * 3
    assert s.cash_returned_usd is None
    assert s.settled_at_utc == AT


def test_provisional_from_results_any_lost_is_lost(placed_bet):
    results = [_result(E1, 100, 110, AT), _result(E2, 115, 112, AT)]  # DET loses; E3 not in results yet
    s = settlement.provisional_from_results(placed_bet, results, [])
    assert s is not None
    assert s.status == S.BetStatus.LOST
    assert s.leg_results == [S.LegResult.LOST, S.LegResult.WON, S.LegResult.PENDING]


def test_provisional_from_results_pending_until_every_event_completes(placed_bet):
    results = [
        _result(E1, 110, 100, AT),
        _result(E2, 80, 70, AT, completed=False, status=S.EventStatus.LIVE),
        _result(E3, 100, 99, AT),
    ]
    stats = [_stat(E3, "jalen brunson", AT, points=26)]
    s = settlement.provisional_from_results(placed_bet, results, stats)
    assert s is not None
    assert s.status == S.BetStatus.PENDING
    assert s.leg_results == [S.LegResult.WON, S.LegResult.PENDING, S.LegResult.WON]


def test_provisional_from_results_push_is_void_and_partial(placed_bet):
    results = [
        _result(E1, 110, 100, AT),
        _result(E2, 112, 112, AT),
        _result(E3, 100, 99, AT),
    ]  # total 224 vs 224.5 -> under; use exact push on spread instead
    bet = placed_bet.model_copy(deep=True)
    bet.legs[0].line = Decimal("-10")  # DET -10 with a 10-point win -> push
    stats = [_stat(E3, "Jalen Brunson", AT, points=30)]
    s = settlement.provisional_from_results(bet, [results[0], _result(E2, 115, 112, AT), results[2]], stats)
    assert s is not None
    assert s.leg_results == [S.LegResult.VOID, S.LegResult.WON, S.LegResult.WON]
    assert s.status == S.BetStatus.PARTIALLY_VOID
    assert s.cash_returned_usd is None
    assert s.repriced_combined_decimal is None


def test_provisional_from_results_dnp_voids_prop(placed_bet):
    results = [_result(E1, 110, 100, AT), _result(E2, 115, 112, AT), _result(E3, 100, 99, AT)]
    stats = [_stat(E3, "Jalen Brunson", AT, played=False)]
    s = settlement.provisional_from_results(placed_bet, results, stats)
    assert s is not None
    assert s.leg_results == [S.LegResult.WON, S.LegResult.WON, S.LegResult.VOID]
    assert s.status == S.BetStatus.PARTIALLY_VOID


def test_provisional_from_results_missing_stat_is_pending(placed_bet):
    results = [_result(E1, 110, 100, AT), _result(E2, 115, 112, AT), _result(E3, 100, 99, AT)]
    s = settlement.provisional_from_results(placed_bet, results, [_stat(E3, "Josh Hart", AT, points=40)])
    assert s is not None
    assert s.leg_results == [S.LegResult.WON, S.LegResult.WON, S.LegResult.PENDING]
    assert s.status == S.BetStatus.PENDING


def test_provisional_from_results_none_when_nothing_gradable(placed_bet):
    assert settlement.provisional_from_results(placed_bet, [], []) is None
    not_final = [_result(E1, None, None, AT, completed=False, status=S.EventStatus.SCHEDULED)]
    assert settlement.provisional_from_results(placed_bet, not_final, []) is None
    postponed = [_result(E1, None, None, AT, completed=False, status=S.EventStatus.POSTPONED)]
    assert settlement.provisional_from_results(placed_bet, postponed, []) is None


def test_provisional_from_results_all_void(placed_bet):
    bet = placed_bet.model_copy(deep=True)
    bet.legs[0].line = Decimal("-10")
    bet.legs[1].line = Decimal("227")
    results = [_result(E1, 110, 100, AT), _result(E2, 115, 112, AT), _result(E3, 100, 99, AT)]
    s = settlement.provisional_from_results(bet, results, [_stat(E3, "Jalen Brunson", AT, played=False)])
    assert s is not None
    assert s.leg_results == [S.LegResult.VOID] * 3
    assert s.status == S.BetStatus.VOID


def test_provisional_grading_of_each_market(placed_bet):
    event = S.Event(
        event_id=E1,
        season_stage="REGULAR",
        home_team=S.Team(team_id="nba:DET", name="Detroit Pistons", abbreviation="DET"),
        away_team=S.Team(team_id="nba:BOS", name="Boston Celtics", abbreviation="BOS"),
        commence_time_utc=AT - timedelta(hours=3),
        status=S.EventStatus.FINAL,
        stamp=_stamp(AT),
    )
    bet = placed_bet.model_copy(deep=True)
    bet.legs = [
        S.AcceptedLeg(
            description="BOS ML", event_id=E1, market_type=S.MarketType.MONEYLINE, side=S.Side.AWAY
        ),
        S.AcceptedLeg(
            description="BOS +3.5",
            event_id=E1,
            market_type=S.MarketType.SPREAD,
            side=S.Side.AWAY,
            line=Decimal("3.5"),
        ),
        S.AcceptedLeg(
            description="DET team total under 105.5",
            event_id=E1,
            market_type=S.MarketType.TEAM_TOTAL,
            side=S.Side.UNDER,
            line=Decimal("105.5"),
            team_name="Pistons",
        ),
    ]
    results = [_result(E1, 104, 108, AT)]
    s = settlement.provisional_from_results(bet, results, [], events=[event])
    assert s is not None
    assert s.leg_results == [S.LegResult.WON, S.LegResult.WON, S.LegResult.WON]
    # without the event list the team total cannot be attributed to a team: it stays PENDING
    s2 = settlement.provisional_from_results(bet, results, [])
    assert s2 is not None and s2.leg_results[2] == S.LegResult.PENDING
    # unsupported period is never graded
    bet.legs[0].period = S.Period.FIRST_HALF
    s3 = settlement.provisional_from_results(bet, results, [], events=[event])
    assert s3 is not None and s3.leg_results[0] == S.LegResult.PENDING


def test_provisional_grading_other_player_markets(placed_bet):
    bet = placed_bet.model_copy(deep=True)
    bet.legs = [
        S.AcceptedLeg(
            description="reb under 9.5",
            event_id=E3,
            market_type=S.MarketType.PLAYER_REBOUNDS,
            side=S.Side.UNDER,
            line=Decimal("9.5"),
            player_name="Chet Holmgren",
        ),
        S.AcceptedLeg(
            description="ast over 6.5",
            event_id=E3,
            market_type=S.MarketType.PLAYER_ASSISTS,
            side=S.Side.OVER,
            line=Decimal("6.5"),
            player_name="Chet Holmgren",
        ),
        S.AcceptedLeg(
            description="3pm over 2.5",
            event_id=E3,
            market_type=S.MarketType.PLAYER_THREES,
            side=S.Side.OVER,
            line=Decimal("2.5"),
            player_name="Chet Holmgren",
        ),
    ]
    stats = [_stat(E3, "Chet Holmgren", AT, rebounds=8, assists=6, threes=None)]
    s = settlement.provisional_from_results(bet, [_result(E3, 100, 99, AT)], stats)
    assert s is not None
    assert s.leg_results == [S.LegResult.WON, S.LegResult.LOST, S.LegResult.PENDING]
    assert s.status == S.BetStatus.LOST
