"""Report tests: performance arithmetic with stated denominators, 30-day review wording, cost
idempotency, dashboard HTML escaping, tenant isolation. All data is FIXTURE-mode."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from hardrock_nba_parlay import actual_bets, reports, settlement
from hardrock_nba_parlay import schemas as S
from hardrock_nba_parlay.budget import IdempotencyConflictError, LedgerError, get_daily_budget

USER_A = "user-a"
USER_B = "user-b"
CAP = Decimal("10.00")
TZ = "America/New_York"


def _at(day: int, hour: int = 22) -> datetime:
    return datetime(2026, 10, day, hour, 0, tzinfo=UTC)  # 18:00 ET on the same calendar day


def _legs(markets, events=(("fixture:E1"), ("fixture:E2"), ("fixture:E3"))) -> list[S.AcceptedLeg]:
    return [
        S.AcceptedLeg(
            description=f"leg {i}",
            event_id=ev,
            market_type=m,
            period=S.Period.FULL_GAME,
            side=S.Side.OVER if m in S.PLAYER_MARKETS or m == S.MarketType.TOTAL else S.Side.HOME,
            line=None if m == S.MarketType.MONEYLINE else Decimal("1.5"),
        )
        for i, (m, ev) in enumerate(zip(markets, events, strict=True))
    ]


MULTI = _legs([S.MarketType.SPREAD, S.MarketType.TOTAL, S.MarketType.MONEYLINE])
SAME = _legs(
    [S.MarketType.PLAYER_POINTS, S.MarketType.PLAYER_ASSISTS, S.MarketType.TOTAL], events=("fixture:E1",) * 3
)


def _record(
    db, user, key, stake, placed_at, legs, *, accepted="5.50", external=False, snapshot=None, recommended=None
):
    ticket = S.ConfirmedTicketInput(
        candidate_id=f"cand-{key}",
        legs=legs,
        accepted_combined_decimal=Decimal(accepted) if accepted else None,
        stake_usd=Decimal(stake),
        placed_at_utc=placed_at,
        external=external,
        source=S.BetSource.EXTERNAL_REPORT if external else S.BetSource.USER_CONFIRMATION,
    )
    bet, _, _ = actual_bets.record_bet(
        db,
        user,
        ticket,
        key,
        placed_at,
        CAP,
        TZ,
        S.DataMode.FIXTURE,
        candidate_snapshot=snapshot,
        recommended_combined_decimal=Decimal(recommended) if recommended else None,
    )
    return bet


@pytest.fixture
def ledger(db, clock):
    """Five bets over four ET days plus one data cost, for user A only."""
    now = clock.now_utc()
    b1 = _record(
        db,
        USER_A,
        "b1",
        "10.00",
        _at(20),
        MULTI,
        snapshot={"p_joint": "0.200000", "model_state": "MARKET_BASELINE", "parlay_type": "MULTI_GAME"},
        recommended="5.60",
    )
    settlement.reconcile(
        db,
        USER_A,
        b1.bet_id,
        S.SettlementInput(
            status=S.BetStatus.WON, cash_returned_usd=Decimal("55.00"), leg_results=[S.LegResult.WON] * 3
        ),
        now,
    )

    b2 = _record(
        db,
        USER_A,
        "b2",
        "10.00",
        _at(21),
        SAME,
        accepted="6.00",
        snapshot={"parlay_type": "SAME_GAME", "model_state": "INSUFFICIENT_EVIDENCE", "p_joint": None},
    )
    settlement.reconcile(
        db,
        USER_A,
        b2.bet_id,
        S.SettlementInput(
            status=S.BetStatus.LOST,
            cash_returned_usd=Decimal("0.00"),
            leg_results=[S.LegResult.WON, S.LegResult.LOST, S.LegResult.WON],
        ),
        now,
    )

    b3 = _record(db, USER_A, "b3", "5.00", _at(22), MULTI)  # pending

    b4 = _record(db, USER_A, "b4", "5.00", _at(22, 23), MULTI, accepted=None)
    settlement.reconcile(
        db,
        USER_A,
        b4.bet_id,
        S.SettlementInput(
            status=S.BetStatus.WON,
            source=S.SettlementSource.PROVISIONAL_NBA_RESULTS,
            leg_results=[S.LegResult.WON] * 3,
        ),
        now,
    )

    b5 = _record(
        db,
        USER_A,
        "b5",
        "15.00",
        _at(23),
        _legs([S.MarketType.MONEYLINE], events=("fixture:E9",)),
        external=True,
    )
    settlement.reconcile(db, USER_A, b5.bet_id, S.SettlementInput(status=S.BetStatus.VOID), now)

    reports.add_cost(
        db,
        USER_A,
        S.CostInput(
            date_local="2026-10-20",
            description="odds api",
            amount_usd=Decimal("12.50"),
            category="DATA",
            idempotency_key="cost-1",
        ),
        now,
    )
    return {"b1": b1, "b2": b2, "b3": b3, "b4": b4, "b5": b5}


def test_performance_numbers_with_stated_denominators(db, clock, ledger):
    rep = reports.performance(db, USER_A, "2026-10-20", "2026-10-23", clock.now_utc())
    assert rep.tickets_placed == 5
    assert rep.total_stake_usd == Decimal("45.00")
    assert rep.settled_tickets == 4  # b1 WON, b2 LOST, b4 provisional WON, b5 VOID
    assert rep.total_cash_returned_usd == Decimal(
        "70.00"
    )  # 55 + 0 + 15 (void refunds the $15 stake); b4 has no cash figure
    assert rep.net_profit_usd == Decimal("35.00")  # 45 - 10 + 0
    assert rep.pending_exposure_usd == Decimal("5.00")  # b3 only
    assert rep.voids == 1
    assert (rep.ticket_win_rate.numerator, rep.ticket_win_rate.denominator) == (2, 3)
    assert rep.ticket_win_rate.value == Decimal("0.666667")
    assert (rep.leg_hit_rate.numerator, rep.leg_hit_rate.denominator) == (8, 9)
    assert rep.leg_hit_rate.value == Decimal("0.888889")
    assert rep.data_costs_usd == Decimal("12.50")
    assert rep.after_cost_net_usd == Decimal("22.50")

    assert set(rep.by_parlay_type) == {"MULTI_GAME", "SAME_GAME", "UNKNOWN"}
    multi = rep.by_parlay_type["MULTI_GAME"]
    assert (multi.tickets, multi.won, multi.pending, multi.lost) == (3, 2, 1, 0)
    assert multi.stake_usd == Decimal("20.00") and multi.net_usd == Decimal("45.00")
    same = rep.by_parlay_type["SAME_GAME"]
    assert (same.tickets, same.lost, same.net_usd) == (1, 1, Decimal("-10.00"))
    unknown = rep.by_parlay_type["UNKNOWN"]
    assert (unknown.tickets, unknown.void_or_other, unknown.net_usd) == (1, 1, Decimal("0.00"))

    assert set(rep.by_market_composition) == {
        "MONEYLINE+SPREAD+TOTAL",
        "PLAYER_ASSISTS+PLAYER_POINTS+TOTAL",
        "MONEYLINE",
    }
    assert rep.by_market_composition["MONEYLINE+SPREAD+TOTAL"].tickets == 3

    deltas = {d.bet_id: d for d in rep.accepted_vs_recommended}
    assert deltas[ledger["b1"].bet_id].delta == Decimal("-0.1000")
    assert (
        deltas[ledger["b2"].bet_id].delta is None and deltas[ledger["b2"].bet_id].recommended_decimal is None
    )
    assert ledger["b4"].bet_id not in deltas

    assert [c.bet_id for c in rep.calibration] == [ledger["b1"].bet_id]
    assert rep.calibration[0].forecast_p_joint == Decimal("0.200000")
    assert rep.calibration[0].model_state == S.ModelState.MARKET_BASELINE
    assert rep.calibration[0].outcome == "WON"

    by_id = {b.bet_id: b for b in rep.bets}
    assert by_id[ledger["b4"].bet_id].provisional is True
    assert by_id[ledger["b4"].bet_id].net_usd is None
    assert by_id[ledger["b1"].bet_id].provisional is False
    assert by_id[ledger["b1"].bet_id].net_usd == Decimal("45.00")
    assert by_id[ledger["b3"].bet_id].status == S.BetStatus.PENDING
    assert by_id[ledger["b2"].bet_id].leg_results == [S.LegResult.WON, S.LegResult.LOST, S.LegResult.WON]
    assert [b.bet_id for b in rep.bets] == [ledger[k].bet_id for k in ("b1", "b2", "b3", "b4", "b5")]

    assert any(ledger["b4"].bet_id in n and "cash-returned" in n for n in rep.incomplete_data_notes)
    assert any("Small sample" in n for n in rep.notes)
    assert any("provisional" in n for n in rep.notes)
    assert any("pending exposure" in n for n in rep.notes)
    assert any("not a parlay win rate" in n for n in rep.notes)


def test_corrections_and_superseded_provisionals_in_performance(db, clock):
    """Upward correction counts as a win; a later superseded provisional never displaces book figures."""
    now = clock.now_utc()
    b1 = _record(
        db,
        USER_A,
        "c1",
        "10.00",
        _at(20),
        MULTI,
        snapshot={"p_joint": "0.2", "model_state": "MARKET_BASELINE"},
    )
    settlement.reconcile(
        db,
        USER_A,
        b1.bet_id,
        S.SettlementInput(
            status=S.BetStatus.WON, cash_returned_usd=Decimal("55.00"), leg_results=[S.LegResult.WON] * 3
        ),
        now,
    )
    settlement.reconcile(
        db,
        USER_A,
        b1.bet_id,
        S.SettlementInput(
            status=S.BetStatus.CORRECTED, cash_returned_usd=Decimal("60.00"), notes="payout fixed"
        ),
        now,
    )
    settlement.reconcile(
        db,
        USER_A,
        b1.bet_id,
        S.SettlementInput(
            status=S.BetStatus.LOST,
            source=S.SettlementSource.PROVISIONAL_NBA_RESULTS,
            leg_results=[S.LegResult.LOST] * 3,
            settled_at_utc=now,
        ),
        now,
    )
    rep = reports.performance(db, USER_A, "2026-10-20", "2026-10-20", now)
    assert rep.net_profit_usd == Decimal("50.00") and rep.total_cash_returned_usd == Decimal("60.00")
    assert (rep.ticket_win_rate.numerator, rep.ticket_win_rate.denominator) == (1, 1)
    assert (rep.leg_hit_rate.numerator, rep.leg_hit_rate.denominator) == (3, 3)
    assert [c.outcome for c in rep.calibration] == ["WON"]
    summary = rep.bets[0]
    assert summary.status == S.BetStatus.CORRECTED and summary.provisional is False
    assert summary.net_usd == Decimal("50.00") and summary.leg_results == [S.LegResult.WON] * 3
    bucket = rep.by_parlay_type["MULTI_GAME"]
    assert (bucket.won, bucket.lost, bucket.void_or_other, bucket.net_usd) == (1, 0, 0, Decimal("50.00"))
    assert not any("provisional" in n for n in rep.notes)
    assert rep.incomplete_data_notes == []


def test_performance_window_bounds_and_empty(db, clock, ledger):
    rep = reports.performance(db, USER_A, "2026-10-21", "2026-10-21", clock.now_utc())
    assert rep.tickets_placed == 1
    assert rep.net_profit_usd == Decimal("-10.00")
    assert rep.data_costs_usd == Decimal("0.00")
    assert rep.after_cost_net_usd == Decimal("-10.00")
    empty = reports.performance(db, USER_A, "2026-12-01", "2026-12-31", clock.now_utc())
    assert empty.tickets_placed == 0
    assert empty.ticket_win_rate.value is None and empty.ticket_win_rate.denominator == 0
    assert empty.leg_hit_rate.value is None
    assert empty.net_profit_usd == Decimal("0.00")
    assert empty.by_parlay_type == {} and empty.bets == []
    with pytest.raises(LedgerError):
        reports.performance(db, USER_A, "2026-10-23", "2026-10-20", clock.now_utc())


def test_reports_are_tenant_scoped(db, clock, ledger):
    rep = reports.performance(db, USER_B, "2026-10-01", "2026-12-31", clock.now_utc())
    assert rep.tickets_placed == 0
    assert rep.data_costs_usd == Decimal("0.00")
    assert reports.list_costs(db, USER_B) == []
    review = reports.thirty_day_review(db, USER_B, "2026-10-20", "2026-11-18", CAP, clock.now_utc())
    assert review.days_with_bets == 0
    assert review.performance.tickets_placed == 0


def test_thirty_day_review(db, clock, ledger):
    review = reports.thirty_day_review(db, USER_A, "2026-10-20", "2026-11-18", CAP, clock.now_utc())
    assert review.max_possible_gross_stake_usd == Decimal("300.00")
    assert review.days_with_bets == 4
    assert review.performance.tickets_placed == 5
    joined = " ".join(review.observed_results)
    assert "5 ticket(s) placed on 4 of 30 days" in joined
    assert "$45.00 of a maximum possible $300.00" in joined
    assert "net profit $35.00" in joined
    assert "2/3" in joined
    skill = " ".join(review.evidence_of_skill)
    assert "cannot establish predictive skill" in skill
    assert "makes no claim of skill" in skill
    assert "1 ticket(s) had a numerical pre-placement forecast" in skill
    assert not any(s.lower().startswith("evidence of skill") for s in review.evidence_of_skill)
    dep = " ".join(review.dependence_and_sample_notes)
    assert "1 ticket(s) were same-game or mixed" in dep
    assert "1 ticket(s) shared a game with another ticket placed the same day" in dep
    assert review.continue_operation_note == "Normal operation continues; daily cap unchanged at $10.00."


def test_add_cost_replay_conflict_and_listing(db, clock):
    now = clock.now_utc()
    cost = S.CostInput(
        date_local="2026-10-20",
        description="odds api",
        amount_usd=Decimal("12.50"),
        category="DATA",
        idempotency_key="c1",
    )
    first, r1 = reports.add_cost(db, USER_A, cost, now)
    second, r2 = reports.add_cost(db, USER_A, cost, now)
    assert (r1, r2) == (False, True)
    assert first == second
    assert first.amount_usd == Decimal("12.50") and first.category == "DATA" and first.user_id == USER_A
    with pytest.raises(IdempotencyConflictError):
        reports.add_cost(db, USER_A, cost.model_copy(update={"amount_usd": Decimal("13.00")}), now)
    assert len(reports.list_costs(db, USER_A)) == 1
    # no key: every call is a new entry
    reports.add_cost(
        db,
        USER_A,
        S.CostInput(
            date_local="2026-11-01", description="hosting", amount_usd=Decimal("5.00"), category="HOSTING"
        ),
        now,
    )
    reports.add_cost(
        db,
        USER_A,
        S.CostInput(
            date_local="2026-11-01", description="hosting", amount_usd=Decimal("5.00"), category="HOSTING"
        ),
        now,
    )
    assert len(reports.list_costs(db, USER_A)) == 3
    assert [c.amount_usd for c in reports.list_costs(db, USER_A, "2026-11-01", "2026-11-30")] == [
        Decimal("5.00"),
        Decimal("5.00"),
    ]
    # keys are per user
    other, replay = reports.add_cost(db, USER_B, cost, now)
    assert replay is False and other.cost_id != first.cost_id
    rep = reports.performance(db, USER_A, "2026-10-01", "2026-11-30", now)
    assert rep.data_costs_usd == Decimal("22.50")
    assert rep.after_cost_net_usd == Decimal("-22.50")


def test_dashboard_html_is_self_contained_and_escaped(db, clock, ledger):
    now = clock.now_utc()
    rep = reports.performance(db, USER_A, "2026-10-20", "2026-10-23", now)
    rep.notes.append("<script>alert('x')</script> & \"quotes\"")
    budget_today = get_daily_budget(db, USER_A, "2026-10-23", now, CAP)
    html_out = reports.dashboard_html(rep, budget_today, reports.list_costs(db, USER_A))
    assert html_out.startswith("<!DOCTYPE html>")
    assert "<script" not in html_out
    assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt; &amp; &quot;quotes&quot;" in html_out
    assert "http://" not in html_out and "https://" not in html_out
    assert "<style>" in html_out and "<link" not in html_out and "<img" not in html_out
    assert html_out.count("<table>") == 5
    assert ledger["b1"].bet_id in html_out
    assert "$45.00" in html_out and "$35.00" in html_out and "$22.50" in html_out and "$12.50" in html_out
    assert "BUDGET_BREACH_RECORDED" in html_out  # 10-23 carries the $15 external report
    assert "$15.00" in html_out
    assert "2/3 = 0.666667" in html_out
    assert "odds api" in html_out
    assert "Not a sportsbook account limit" in html_out


def test_dashboard_handles_empty_report(db, clock):
    now = clock.now_utc()
    rep = reports.performance(db, USER_A, "2026-10-20", "2026-10-23", now)
    html_out = reports.dashboard_html(rep, get_daily_budget(db, USER_A, "2026-10-20", now, CAP))
    assert "No bets recorded in this window" in html_out
    assert "(n/a)" in html_out
